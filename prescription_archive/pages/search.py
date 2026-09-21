# -*- coding: utf-8 -*-
"""Search Archive page: filters, results list, snapshot preview."""

import os
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime

from ..config import CARD, TEXT, MUTED, BORDER, DEFAULT_CATEGORIES
from ..db import connect
from ..utils import safe_path, valid_date
from ..widgets.image_viewer import ImageViewer


class SearchMixin:
    def _page_search(self, p):
        p.grid_rowconfigure(2, weight=1)
        p.grid_columnconfigure(0, weight=1)
        self._header(p, "Search Archive",
                     "Find prescriptions by medicine, patient, doctor, category or date")

        filters = ctk.CTkFrame(p, corner_radius=14, fg_color=CARD,
                               border_width=1, border_color=BORDER)
        filters.grid(row=1, column=0, sticky="ew", padx=18, pady=6)
        for i in range(4):
            filters.grid_columnconfigure(i, weight=1 if i else 2)

        self.s_meds = self._filter_entry(filters, "Medicines (comma = ALL)", 0, 0)
        self.s_people = self._filter_entry(filters, "Patient / Doctor", 0, 1)
        self.s_category = self._filter_combo(filters, "Category",
                                              ["Any"] + DEFAULT_CATEGORIES, 0, 2)
        self.s_date_from = self._filter_entry(filters, "From date", 0, 3)
        self.s_date_to = self._filter_entry(filters, "To date", 1, 3)

        self.s_meds.bind("<Return>", lambda e: self._refresh_search())
        self.s_people.bind("<Return>", lambda e: self._refresh_search())

        # AND/OR toggle for multi-medicine search.
        self.s_or_mode = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(filters, text="Match ANY medicine (OR)",
                        variable=self.s_or_mode, font=("Segoe UI", 10),
                        checkbox_width=18, checkbox_height=18
                        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        btns = ctk.CTkFrame(filters, fg_color="transparent")
        btns.grid(row=1, column=1, columnspan=2, sticky="w", padx=10, pady=8)
        ctk.CTkButton(btns, text="SEARCH", width=130, height=38,
                      font=("Segoe UI", 11, "bold"),
                      command=self._refresh_search).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Show All", width=110, height=38,
                      fg_color="#E5E7EB", hover_color="#D1D5DB", text_color=TEXT,
                      command=self._search_show_all).pack(side="left", padx=4)

        results = ctk.CTkFrame(p, fg_color="transparent")
        results.grid(row=2, column=0, sticky="nsew", padx=18, pady=8)
        results.grid_rowconfigure(0, weight=1)
        results.grid_columnconfigure(0, weight=3)
        results.grid_columnconfigure(1, weight=2, minsize=420)

        left = self._card(results, 0, 0)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text="Results", font=("Segoe UI", 15, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w",
                                            padx=16, pady=(14, 8))
        self.search_scroll = ctk.CTkScrollableFrame(left, fg_color="#F8FAFC")
        self.search_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.search_scroll.grid_columnconfigure(0, weight=1)

        right = self._card(results, 0, 1)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1, minsize=120)
        right.grid_rowconfigure(2, weight=0, minsize=280)

        ctk.CTkLabel(right, text="Prescription Snapshot",
                     font=("Segoe UI", 15, "bold"), text_color=TEXT
                     ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))

        self.snapshot = ctk.CTkTextbox(right, height=140, corner_radius=10,
                                       fg_color="#F8FAFC", font=("Consolas", 10),
                                       wrap="word")
        self.snapshot.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)

        self.search_viewer = ImageViewer(right, width=380, height=280)
        self.search_viewer.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=10, pady=8)
        ctk.CTkButton(actions, text="Edit", height=36,
                      command=self._edit_selected_search).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="Move to Trash", height=36, fg_color="#FEF3C7",
                      hover_color="#FDE68A", text_color="#92400E",
                      command=self._trash_selected).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="Fullscreen", height=36,
                      command=self._open_search_fullscreen).pack(side="left", padx=3)

    def _filter_entry(self, parent, label, row, col):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=8, pady=6)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=label, font=("Segoe UI", 10, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                             padx=4, pady=(0, 3))
        e = ctk.CTkEntry(box, height=38, corner_radius=9,
                         placeholder_text=label, font=("Segoe UI", 11))
        e.grid(row=1, column=0, sticky="ew", padx=4)
        return e

    def _filter_combo(self, parent, label, values, row, col):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=8, pady=6)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=label, font=("Segoe UI", 10, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                             padx=4, pady=(0, 3))
        cb = ctk.CTkComboBox(box, values=values, height=38, corner_radius=9,
                             font=("Segoe UI", 11), dropdown_font=("Segoe UI", 11))
        cb.set("Any"); cb.grid(row=1, column=0, sticky="ew", padx=4)
        return cb

    def _refresh_search(self):
        if not hasattr(self, "search_scroll"): return
        for w in self.search_scroll.winfo_children(): w.destroy()
        meds = self.s_meds.get().strip(); people = self.s_people.get().strip()
        cat = self.s_category.get().strip(); df = self.s_date_from.get().strip()
        dt = self.s_date_to.get().strip()
        terms = [x.strip() for x in meds.replace(";", ",").split(",") if x.strip()]
        or_mode = bool(self.s_or_mode.get())

        sql = ("SELECT DISTINCT p.id,p.patient_name,p.age,p.doctor_name,p.date,p.category "
               "FROM prescriptions p WHERE p.deleted_at IS NULL")
        params = []
        if terms:
            if or_mode:
                sub = " OR ".join("m.name LIKE ? COLLATE NOCASE" for _ in terms)
                sql += (" AND p.id IN (SELECT pi.prescription_id FROM prescription_items pi "
                        "JOIN medications m ON m.id=pi.medication_id WHERE " + sub + ")")
                for t in terms:
                    params.append(f"%{t}%")
            else:
                for t in terms:
                    sql += (" AND p.id IN (SELECT pi.prescription_id FROM prescription_items pi "
                            "JOIN medications m ON m.id=pi.medication_id "
                            "WHERE m.name LIKE ? COLLATE NOCASE)")
                    params.append(f"%{t}%")
        if people:
            sql += " AND (p.patient_name LIKE ? OR p.doctor_name LIKE ?)"
            params += [f"%{people}%", f"%{people}%"]
        if cat and cat != "Any":
            sql += " AND p.category=?"; params.append(cat)
        if df and valid_date(df):
            sql += " AND p.date>=?"; params.append(df)
        if dt and valid_date(dt):
            sql += " AND p.date<=?"; params.append(dt)
        sql += " ORDER BY p.date DESC,p.id DESC"

        with connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            for r in rows:
                meds2 = [x[0] for x in conn.execute(
                    "SELECT m.name FROM prescription_items pi "
                    "JOIN medications m ON m.id=pi.medication_id "
                    "WHERE pi.prescription_id=? ORDER BY pi.id", (r["id"],)).fetchall()]
                self._result_card(r, meds2)
            if meds:
                conn.execute("INSERT INTO search_history(query,searched_at) VALUES(?,?)",
                             (meds, datetime.now().isoformat()))
        self.selected_search_id = None
        self._clear_snapshot()

    def _result_card(self, row, meds):
        card = ctk.CTkFrame(self.search_scroll, corner_radius=11, fg_color=CARD,
                            border_width=1, border_color=BORDER)
        card.grid(row=len(self.search_scroll.winfo_children()), column=0,
                  sticky="ew", padx=4, pady=4)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=f"#{row['id']}  •  {row['patient_name'] or 'Unnamed patient'}",
                     font=("Segoe UI", 12, "bold"), text_color=TEXT
                     ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(card,
            text=f"{row['date'] or '-'}  |  {row['doctor_name'] or '-'}  |  "
                 f"{row['category'] or '-'}\n{', '.join(meds) or 'No medicines'}",
            font=("Segoe UI", 10), text_color=MUTED, justify="left"
            ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 10))
        card.bind("<Button-1>", lambda e, pid=row['id']: self._select_search(pid))
        for child in card.winfo_children():
            child.bind("<Button-1>", lambda e, pid=row['id']: self._select_search(pid))

    def _select_search(self, pid):
        self.selected_search_id = pid
        self._load_snapshot(pid)

    def _clear_snapshot(self):
        self.snapshot.configure(state="normal"); self.snapshot.delete("1.0", "end")
        self.snapshot.configure(state="disabled")
        self.search_viewer.clear()

    def _load_snapshot(self, pid):
        with connect() as conn:
            row = conn.execute("SELECT * FROM prescriptions WHERE id=?", (pid,)).fetchone()
            items = conn.execute("""SELECT m.name,pi.strength,pi.dose,pi.frequency,
                pi.duration,pi.route,pi.item_notes FROM prescription_items pi
                JOIN medications m ON m.id=pi.medication_id
                WHERE pi.prescription_id=? ORDER BY pi.id""", (pid,)).fetchall()
        if not row: return
        lines = [f"Prescription #{pid}", "-" * 55]
        for label, key in (("Patient", "patient_name"), ("Age", "age"),
                            ("Gender", "gender"), ("Doctor", "doctor_name"),
                            ("Date", "date"), ("Category", "category"),
                            ("Notes", "notes")):
            if row[key]: lines.append(f"{label}: {row[key]}")
        lines.append(""); lines.append("MEDICINES")
        for i, x in enumerate(items, 1):
            lines.append(f"{i}. {x[0]}")
            meta = [v for v in x[1:5] if v]
            if x[5]: meta.append("Route: " + x[5])
            if meta: lines.append("   " + " | ".join(meta))
            if x[6]: lines.append("   Note: " + x[6])
        self.snapshot.configure(state="normal"); self.snapshot.delete("1.0", "end")
        self.snapshot.insert("1.0", "\n".join(lines))
        self.snapshot.configure(state="disabled")

        path = safe_path(row["image_path"] or "")
        if path and os.path.exists(path):
            self.search_viewer.load(path)
        else:
            self.search_viewer.clear()

    def _edit_selected_search(self):
        if self.selected_search_id: self._edit_from_id(self.selected_search_id)
        else: messagebox.showinfo("Select", "Select a prescription first.")

    def _open_search_fullscreen(self):
        """FIX: pass the path directly; do not touch self.current_image_path."""
        if not self.selected_search_id:
            return
        with connect() as conn:
            r = conn.execute("SELECT image_path FROM prescriptions WHERE id=?",
                             (self.selected_search_id,)).fetchone()
        path = safe_path(r[0] if r else "")
        if path and os.path.exists(path):
            self._open_fullscreen(path)          # <-- path passed explicitly

    def _search_show_all(self):
        self.s_meds.delete(0, "end"); self.s_people.delete(0, "end")
        self.s_category.set("Any"); self.s_date_from.delete(0, "end")
        self.s_date_to.delete(0, "end"); self._refresh_search()

