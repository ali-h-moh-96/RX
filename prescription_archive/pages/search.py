# -*- coding: utf-8 -*-
"""Search Archive page: filters, results list, snapshot preview."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..config import CARD, TEXT, MUTED, BORDER, DEFAULT_CATEGORIES
from ..db import connect
from ..utils import safe_path, valid_date
from ..widgets.image_viewer import ImageViewer


# --------------------------------------------------------------------------- #
#  Constants
# --------------------------------------------------------------------------- #
MAX_RESULTS = 200
SEARCH_DEBOUNCE_MS = 300
SELECTED_BORDER = "#2563EB"   # blue
DEFAULT_BORDER = BORDER

# Subquery that filters prescriptions by medicine name. Kept in one place
# so the AND/OR branches cannot drift apart.
_MED_SUBQUERY = (
    "p.id IN (SELECT pi.prescription_id "
    "         FROM prescription_items pi "
    "         JOIN medications m ON m.id = pi.medication_id "
    "         WHERE {cond})"
)


class SearchMixin:
    # ------------------------------------------------------------------ #
    #  Page construction
    # ------------------------------------------------------------------ #
    def _page_search(self, p):
        p.grid_rowconfigure(2, weight=1)
        p.grid_columnconfigure(0, weight=1)

        self._header(
            p, "Search Archive",
            "Find prescriptions by medicine, patient, doctor, category or date",
        )

        # Per-instance state
        self._result_index = 0
        self._search_job = None
        self._selected_card = None
        self.selected_search_id = None

        self._build_filters(p)
        self._build_results_area(p)

        # Optional: focus search field with Ctrl+F
        self.bind_all("<Control-f>", lambda _e: self.s_meds.focus_set())

    # ------------------------------------------------------------------ #
    #  Filters
    # ------------------------------------------------------------------ #
    def _build_filters(self, parent):
        filters = ctk.CTkFrame(
            parent, corner_radius=14, fg_color=CARD,
            border_width=1, border_color=BORDER,
        )
        filters.grid(row=1, column=0, sticky="ew", padx=18, pady=6)
        for i in range(4):
            filters.grid_columnconfigure(i, weight=1 if i else 2)

        self.s_meds     = self._filter_entry(filters, "Medicines (comma = ALL)", 0, 0)
        self.s_people   = self._filter_entry(filters, "Patient / Doctor",        0, 1)
        self.s_category = self._filter_combo(filters, "Category",
                                             ["Any"] + list(DEFAULT_CATEGORIES), 0, 2)
        self.s_date_from = self._filter_entry(filters, "From date", 0, 3)
        self.s_date_to   = self._filter_entry(filters, "To date",   1, 3)

        # AND/OR toggle
        self.s_or_mode = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            filters, text="Match ANY medicine (OR)",
            variable=self.s_or_mode, font=("Segoe UI", 10),
            checkbox_width=18, checkbox_height=18,
            command=self._schedule_search,
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        btns = ctk.CTkFrame(filters, fg_color="transparent")
        btns.grid(row=1, column=1, columnspan=2, sticky="w", padx=10, pady=8)
        ctk.CTkButton(
            btns, text="SEARCH", width=130, height=38,
            font=("Segoe UI", 11, "bold"),
            command=self._refresh_search,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Show All", width=110, height=38,
            fg_color="#E5E7EB", hover_color="#D1D5DB", text_color=TEXT,
            command=self._search_show_all,
        ).pack(side="left", padx=4)

        # Live (debounced) search while typing
        for entry in (self.s_meds, self.s_people,
                      self.s_date_from, self.s_date_to):
            entry.bind("<KeyRelease>", self._schedule_search)
            entry.bind("<Return>",     self._refresh_search)
        self.s_category.configure(command=self._schedule_search)

    # ------------------------------------------------------------------ #
    #  Results area
    # ------------------------------------------------------------------ #
    def _build_results_area(self, parent):
        results = ctk.CTkFrame(parent, fg_color="transparent")
        results.grid(row=2, column=0, sticky="nsew", padx=18, pady=8)
        results.grid_rowconfigure(0, weight=1)
        results.grid_columnconfigure(0, weight=3)
        results.grid_columnconfigure(1, weight=2, minsize=420)

        # ---------------- Left: results list ---------------- #
        left = self._card(results, 0, 0)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self.results_label = ctk.CTkLabel(
            left, text="Results", font=("Segoe UI", 15, "bold"), text_color=TEXT,
        )
        self.results_label.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))

        self.search_scroll = ctk.CTkScrollableFrame(left, fg_color="#F8FAFC")
        self.search_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.search_scroll.grid_columnconfigure(0, weight=1)

        # ---------------- Right: snapshot ---------------- #
        right = self._card(results, 0, 1)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1, minsize=120)
        right.grid_rowconfigure(2, weight=0, minsize=280)

        ctk.CTkLabel(
            right, text="Prescription Snapshot",
            font=("Segoe UI", 15, "bold"), text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))

        self.snapshot = ctk.CTkTextbox(
            right, height=140, corner_radius=10,
            fg_color="#F8FAFC", font=("Consolas", 10), wrap="word",
        )
        self.snapshot.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        self.snapshot.tag_config("title",   font=("Consolas", 11, "bold"))
        self.snapshot.tag_config("section", font=("Consolas", 10, "bold"))
        self.snapshot.tag_config("muted",   foreground=MUTED)
        self.snapshot.configure(state="disabled")

        self.search_viewer = ImageViewer(right, width=380, height=280)
        self.search_viewer.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=10, pady=8)
        ctk.CTkButton(actions, text="Edit", height=36,
                      command=self._edit_selected_search).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="Move to Trash", height=36,
                      fg_color="#FEF3C7", hover_color="#FDE68A",
                      text_color="#92400E",
                      command=self._trash_selected).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="Fullscreen", height=36,
                      command=self._open_search_fullscreen).pack(side="left", padx=3)

    # ------------------------------------------------------------------ #
    #  Small widget helpers
    # ------------------------------------------------------------------ #
    def _filter_entry(self, parent, label, row, col):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=8, pady=6)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=label, font=("Segoe UI", 10, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                            padx=4, pady=(0, 3))
        entry = ctk.CTkEntry(box, height=38, corner_radius=9,
                             placeholder_text=label, font=("Segoe UI", 11))
        entry.grid(row=1, column=0, sticky="ew", padx=4)
        return entry

    def _filter_combo(self, parent, label, values, row, col):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=8, pady=6)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=label, font=("Segoe UI", 10, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                            padx=4, pady=(0, 3))
        combo = ctk.CTkComboBox(box, values=values, height=38, corner_radius=9,
                                font=("Segoe UI", 11),
                                dropdown_font=("Segoe UI", 11),
                                state="readonly")
        combo.set("Any")
        combo.grid(row=1, column=0, sticky="ew", padx=4)
        return combo

    # ------------------------------------------------------------------ #
    #  Debounced search
    # ------------------------------------------------------------------ #
    def _schedule_search(self, *_):
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except Exception:
                pass
        self._search_job = self.after(SEARCH_DEBOUNCE_MS, self._refresh_search)

    # ------------------------------------------------------------------ #
    #  Build the SQL query from filter values
    # ------------------------------------------------------------------ #
    def _build_query(self):
        """Return (sql, params) or raise ValueError on bad user input."""
        meds   = self.s_meds.get().strip()
        people = self.s_people.get().strip()
        cat    = self.s_category.get().strip()
        df     = self.s_date_from.get().strip()
        dt     = self.s_date_to.get().strip()

        if df and not valid_date(df):
            raise ValueError(f"From date '{df}' is not a valid date.")
        if dt and not valid_date(dt):
            raise ValueError(f"To date '{dt}' is not a valid date.")
        if df and dt and df > dt:
            raise ValueError("'From' date is after 'To' date.")

        terms    = [t.strip() for t in meds.replace(";", ",").split(",") if t.strip()]
        or_mode  = bool(self.s_or_mode.get())

        sql = [
            "SELECT DISTINCT p.id, p.patient_name, p.age, p.doctor_name,",
            "       p.date, p.category",
            "FROM prescriptions p",
            "WHERE p.deleted_at IS NULL",
        ]
        params: list = []

        # Medicine filter
        if terms:
            if or_mode:
                cond = " OR ".join("m.name LIKE ? COLLATE NOCASE" for _ in terms)
                sql.append("AND " + _MED_SUBQUERY.format(cond=cond))
                params.extend(f"%{t}%" for t in terms)
            else:
                for t in terms:
                    sql.append("AND " + _MED_SUBQUERY.format(
                        cond="m.name LIKE ? COLLATE NOCASE"))
                    params.append(f"%{t}%")

        # People filter
        if people:
            sql.append("AND (p.patient_name LIKE ? OR p.doctor_name LIKE ?)")
            params.extend([f"%{people}%", f"%{people}%"])

        # Category filter
        if cat and cat != "Any":
            sql.append("AND p.category = ?")
            params.append(cat)

        # Date range
        if df:
            sql.append("AND p.date >= ?")
            params.append(df)
        if dt:
            sql.append("AND p.date <= ?")
            params.append(dt)

        sql.append("ORDER BY p.date DESC, p.id DESC")
        sql.append("LIMIT ?")
        params.append(MAX_RESULTS)

        return " ".join(sql), params

    # ------------------------------------------------------------------ #
    #  Main refresh
    # ------------------------------------------------------------------ #
    def _refresh_search(self):
        if getattr(self, "search_scroll", None) is None:
            return

        # Cancel any pending debounce
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except Exception:
                pass
            self._search_job = None

        try:
            sql, params = self._build_query()
        except ValueError as exc:
            messagebox.showwarning("Invalid filter", str(exc))
            return

        # Reset UI state before touching the DB so an exception leaves
        # us in a consistent (empty) state.
        self._clear_results()
        self.results_label.configure(text="Results — searching…")
        self.update_idletasks()

        try:
            with connect() as conn:
                rows = conn.execute(sql, params).fetchall()
                meds_by_id = self._fetch_medicines(conn, rows)
                if self.s_meds.get().strip():
                    conn.execute(
                        "INSERT INTO search_history(query, searched_at) VALUES (?, ?)",
                        (self.s_meds.get().strip(), datetime.now().isoformat()),
                    )
        except Exception as exc:
            self.results_label.configure(text="Results")
            messagebox.showerror("Search error", str(exc))
            return

        for r in rows:
            self._result_card(r, meds_by_id.get(r["id"], []))

        count = len(rows)
        suffix = " (showing first {})".format(MAX_RESULTS) if count == MAX_RESULTS else ""
        self.results_label.configure(text=f"Results ({count}){suffix}")

    # ------------------------------------------------------------------ #
    #  Fetch all medicines for the current page of results in one query
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fetch_medicines(conn, rows):
        if not rows:
            return {}

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        med_rows = conn.execute(
            f"""SELECT pi.prescription_id, m.name
                FROM prescription_items pi
                JOIN medications m ON m.id = pi.medication_id
                WHERE pi.prescription_id IN ({placeholders})
                ORDER BY pi.prescription_id, pi.id""",
            ids,
        ).fetchall()

        meds_by_id: dict = {}
        for pr_id, name in med_rows:
            meds_by_id.setdefault(pr_id, []).append(name)
        return meds_by_id

    # ------------------------------------------------------------------ #
    #  Result card
    # ------------------------------------------------------------------ #
    def _result_card(self, row, meds):
        card = ctk.CTkFrame(
            self.search_scroll, corner_radius=11, fg_color=CARD,
            border_width=1, border_color=DEFAULT_BORDER,
        )
        card.grid(row=self._result_index, column=0, sticky="ew", padx=4, pady=4)
        card.grid_columnconfigure(0, weight=1)
        self._result_index += 1

        ctk.CTkLabel(
            card,
            text=f"#{row['id']}  •  {row['patient_name'] or 'Unnamed patient'}",
            font=("Segoe UI", 12, "bold"), text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(
            card,
            text=(f"{row['date'] or '-'}  |  {row['doctor_name'] or '-'}  |  "
                  f"{row['category'] or '-'}\n"
                  f"{', '.join(meds) or 'No medicines'}"),
            font=("Segoe UI", 10), text_color=MUTED, justify="left",
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 10))

        self._bind_card_click(card, row["id"])

    def _bind_card_click(self, card, pid):
        handler = lambda _e, p=pid, c=card: self._select_search(p, c)
        card.bind("<Button-1>", handler)
        for child in card.winfo_children():
            child.bind("<Button-1>", handler)

    # ------------------------------------------------------------------ #
    #  Selection / snapshot
    # ------------------------------------------------------------------ #
    def _select_search(self, pid, card=None):
        # Restore old card border
        if self._selected_card is not None:
            try:
                self._selected_card.configure(border_color=DEFAULT_BORDER)
            except Exception:
                pass

        self._selected_card = card
        if card is not None:
            try:
                card.configure(border_color=SELECTED_BORDER)
            except Exception:
                pass

        self.selected_search_id = pid
        self._load_snapshot(pid)

    def _clear_results(self):
        for w in self.search_scroll.winfo_children():
            w.destroy()
        self._result_index = 0
        self._selected_card = None
        self.selected_search_id = None
        self._clear_snapshot()

    def _clear_snapshot(self):
        self.snapshot.configure(state="normal")
        self.snapshot.delete("1.0", "end")
        self.snapshot.configure(state="disabled")
        self.search_viewer.clear()

    def _load_snapshot(self, pid):
        try:
            with connect() as conn:
                row = conn.execute(
                    "SELECT * FROM prescriptions WHERE id = ?", (pid,)
                ).fetchone()
                items = conn.execute(
                    """SELECT m.name, pi.strength, pi.dose, pi.frequency,
                              pi.duration, pi.route, pi.item_notes
                       FROM prescription_items pi
                       JOIN medications m ON m.id = pi.medication_id
                       WHERE pi.prescription_id = ?
                       ORDER BY pi.id""",
                    (pid,),
                ).fetchall()
        except Exception as exc:
            messagebox.showerror("Snapshot error", str(exc))
            self._clear_snapshot()
            return

        if not row:
            self._clear_snapshot()
            return

        self.snapshot.configure(state="normal")
        self.snapshot.delete("1.0", "end")
        self._write_snapshot(pid, row, items)
        self.snapshot.configure(state="disabled")

        path = safe_path(row["image_path"] or "")
        if path and os.path.exists(path):
            self.search_viewer.load(path)
        else:
            self.search_viewer.clear()

    def _write_snapshot(self, pid, row, items):
        box = self.snapshot

        box.insert("end", f"Prescription #{pid}\n", "title")
        box.insert("end", "-" * 55 + "\n", "muted")

        for label, key in (("Patient", "patient_name"), ("Age", "age"),
                           ("Gender", "gender"), ("Doctor", "doctor_name"),
                           ("Date", "date"), ("Category", "category"),
                           ("Notes", "notes")):
            value = row[key]
            if value:
                box.insert("end", f"{label}: ")
                box.insert("end", f"{value}\n")

        box.insert("end", "\nMEDICINES\n", "section")

        if not items:
            box.insert("end", "  (none)\n", "muted")
            return

        for i, x in enumerate(items, 1):
            box.insert("end", f"{i}. {x['name']}\n")
            meta = [v for v in (x["strength"], x["dose"],
                                x["frequency"], x["duration"]) if v]
            if x["route"]:
                meta.append(f"Route: {x['route']}")
            if meta:
                box.insert("end", "   " + " | ".join(meta) + "\n", "muted")
            if x["item_notes"]:
                box.insert("end", f"   Note: {x['item_notes']}\n", "muted")

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _edit_selected_search(self):
        if not self.selected_search_id:
            messagebox.showinfo("Select", "Select a prescription first.")
            return
        self._edit_from_id(self.selected_search_id)

    def _open_search_fullscreen(self):
        """Pass the path directly; do not touch self.current_image_path."""
        if not self.selected_search_id:
            return
        try:
            with connect() as conn:
                r = conn.execute(
                    "SELECT image_path FROM prescriptions WHERE id = ?",
                    (self.selected_search_id,),
                ).fetchone()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return

        path = safe_path(r["image_path"] if r else "")
        if path and Path(path).is_file():
            self._open_fullscreen(path)

    # ------------------------------------------------------------------ #
    #  Show all / clear filters
    # ------------------------------------------------------------------ #
    def _search_show_all(self):
        self.s_meds.delete(0, "end")
        self.s_people.delete(0, "end")
        self.s_category.set("Any")
        self.s_date_from.delete(0, "end")
        self.s_date_to.delete(0, "end")
        self._refresh_search()