# -*- coding: utf-8 -*-
"""New/Edit Prescription page: form fields, medicine cards, image handling, save/edit logic."""

import os
import json
import uuid
import threading
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import datetime

from ..config import (BG, CARD, TEXT, MUTED, BORDER, ACCENT, GENDERS,
                       IMAGES_DIR, LOGGER, DATA_DIR, MAX_AGE)
from ..db import connect
from ..utils import safe_path, valid_date, valid_age, save_compressed_image, levenshtein
from ..widgets.autocomplete_entry import AutocompleteEntry
from ..widgets.medication_card import MedicationCard
from ..widgets.image_viewer import ImageViewer


class FormMixin:
    def _page_form(self, p):
        p.grid_rowconfigure(1, weight=1)
        p.grid_columnconfigure(0, weight=1)
        self._header(p, "New Prescription",
                     "Add medicines, attach the image, then fill patient details")

        # Scrollable content area (fixes layout on small screens).
        scroll = ctk.CTkScrollableFrame(p, fg_color=BG, corner_radius=0)
        scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        scroll.grid_columnconfigure(0, weight=1)

        body = ctk.CTkFrame(scroll, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=10, pady=(0, 6))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1, minsize=320)

        # -- medicines card --
        left = self._card(body, 0, 0)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text="Medicines", font=("Segoe UI", 16, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w",
                                            padx=18, pady=(16, 12))

        meds_section = ctk.CTkFrame(left, corner_radius=12, fg_color="#F8FAFC",
                                    border_width=1, border_color=BORDER)
        meds_section.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        meds_section.grid_rowconfigure(1, weight=1)
        meds_section.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(meds_section, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Medicine list", font=("Segoe UI", 12, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(head, text="+ Add Medicine", width=135, height=34,
                      command=self._add_medication_card).grid(row=0, column=1, sticky="e")

        self.med_scroll = ctk.CTkScrollableFrame(meds_section, fg_color="transparent",
                                                  height=380)
        self.med_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 10))
        self.med_scroll.grid_columnconfigure(0, weight=1)
        self.medication_cards = []

        # -- image card --
        right = self._card(body, 0, 1)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(right, text="Prescription Image", font=("Segoe UI", 16, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w",
                                            padx=16, pady=(16, 10))
        viewer_wrap = ctk.CTkFrame(right, fg_color="transparent")
        viewer_wrap.grid(row=1, column=0, sticky="nsew", padx=14, pady=4)
        viewer_wrap.grid_rowconfigure(0, weight=1)
        viewer_wrap.grid_columnconfigure(0, weight=1)
        self.form_viewer = ImageViewer(viewer_wrap, width=280, height=280)
        self.form_viewer.grid(row=0, column=0, sticky="nsew")

        toolbar = ctk.CTkFrame(right, fg_color="transparent")
        toolbar.grid(row=2, column=0, sticky="ew", padx=14, pady=(6, 14))
        toolbar.grid_columnconfigure(0, weight=1)
        toolbar.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(toolbar, text="Choose Image", height=38,
                      command=self._choose_image).grid(row=0, column=0, sticky="ew",
                                                        padx=(0, 5))
        ctk.CTkButton(toolbar, text="Remove Image", height=38,
                      fg_color="#FEE2E2", hover_color="#FECACA", text_color="#991B1B",
                      command=self._remove_image).grid(row=0, column=1, sticky="ew",
                                                        padx=(5, 0))

        # -- details card --
        details_card = ctk.CTkFrame(scroll, corner_radius=14, fg_color=CARD,
                                    border_width=1, border_color=BORDER)
        details_card.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 6))
        details_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(details_card, text="Patient & Prescription Details",
                     font=("Segoe UI", 13, "bold"), text_color=TEXT
                     ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 6))

        grid = ctk.CTkFrame(details_card, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 10))
        for c in (1, 3, 5, 7):
            grid.grid_columnconfigure(c, weight=1)

        def _lbl(parent, text, row, col):
            ctk.CTkLabel(parent, text=text, font=("Segoe UI", 9, "bold"),
                         text_color=MUTED).grid(row=row, column=col, sticky="e",
                                                 padx=(8, 4), pady=3)

        def _entry(parent, row, col, placeholder=""):
            e = ctk.CTkEntry(parent, height=30, corner_radius=7, fg_color="#F8FAFC",
                             placeholder_text=placeholder, font=("Segoe UI", 10))
            e.grid(row=row, column=col, sticky="ew", padx=(0, 8), pady=3)
            return e

        def _combo(parent, row, col, values):
            cb = ctk.CTkComboBox(parent, values=values, height=30, corner_radius=7,
                                 fg_color="#F8FAFC", font=("Segoe UI", 10),
                                 dropdown_font=("Segoe UI", 10))
            cb.grid(row=row, column=col, sticky="ew", padx=(0, 8), pady=3)
            return cb

        _lbl(grid, "Patient", 0, 0)
        self.p_patient = _entry(grid, 0, 1, placeholder="Full name")
        _lbl(grid, "Age", 0, 2)
        self.p_age = _entry(grid, 0, 3, placeholder="e.g. 34")
        _lbl(grid, "Gender", 0, 4)
        self.p_gender = _combo(grid, 0, 5, GENDERS)
        _lbl(grid, "Doctor", 0, 6)
        self.p_doctor = _entry(grid, 0, 7, placeholder="Dr. …")

        _lbl(grid, "Date", 1, 0)
        self.p_date = _entry(grid, 1, 1, placeholder="YYYY-MM-DD")
        self.p_date.insert(0, datetime.now().strftime("%Y-%m-%d"))
        _lbl(grid, "Category", 1, 2)
        self.p_category = _combo(grid, 1, 3, [])

        # Multi-line notes.
        _lbl(grid, "Notes", 2, 0)
        self.p_notes = ctk.CTkTextbox(grid, height=60, corner_radius=7,
                                      fg_color="#F8FAFC", font=("Segoe UI", 10),
                                      border_width=1, border_color=BORDER)
        self.p_notes.grid(row=2, column=1, columnspan=7, sticky="ew",
                          padx=(0, 8), pady=3)

        # -- status + bottom bar --
        self.form_status = ctk.CTkLabel(p, text="Ready for a new prescription",
                                        text_color=MUTED, anchor="w")
        self.form_status.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 4))

        self.bottom_bar = ctk.CTkFrame(p, fg_color=BG, corner_radius=0)
        self.bottom_bar.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.bottom_bar.grid_columnconfigure(0, weight=1)
        self.bottom_bar.grid_columnconfigure(1, weight=0)
        self.cancel_btn = ctk.CTkButton(self.bottom_bar, text="Cancel", width=110,
                                        height=44, state="disabled",
                                        command=self._cancel_edit)
        self.cancel_btn.grid(row=0, column=0, sticky="e", padx=(0, 8))
        self.save_btn = ctk.CTkButton(self.bottom_bar, text="SAVE PRESCRIPTION",
                                      width=210, height=46,
                                      font=("Segoe UI", 13, "bold"), command=self._save)
        self.save_btn.grid(row=0, column=1, sticky="e")

        self._add_medication_card()
        self._refresh_categories()

    def _add_medication_card(self, data=None):
        card = MedicationCard(self.med_scroll, self, data, self._remove_medication_card)
        card.grid(row=len(self.medication_cards), column=0, sticky="ew", padx=4, pady=5)
        self.medication_cards.append(card)

    def _remove_medication_card(self, card):
        if len(self.medication_cards) <= 1:
            card.set_data({}); return
        self.medication_cards.remove(card); card.destroy()
        for i, item in enumerate(self.medication_cards):
            item.grid_configure(row=i)

    def _med_suggestions(self, text):
        """Prefix-first, then contains fallback, case-insensitive."""
        with connect() as conn:
            rows = conn.execute(
                "SELECT name FROM medications WHERE name LIKE ? COLLATE NOCASE "
                "ORDER BY name LIMIT 20", (f"{text}%",)).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT name FROM medications WHERE name LIKE ? COLLATE NOCASE "
                    "ORDER BY name LIMIT 20", (f"%{text}%",)).fetchall()
        return [r[0] for r in rows]

    # ---------------- image ----------------
    def _choose_image(self):
        path = filedialog.askopenfilename(
            title="Choose prescription image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
                       ("All files", "*.*")])
        if path:
            self.current_image_path = path
            self.current_image_dirty = True
            self.form_viewer.load(path)
            self.form_status.configure(text=f"Image selected: {Path(path).name}")

    def _remove_image(self):
        self.current_image_path = None
        self.current_image_dirty = True
        self.form_viewer.clear()
        self.form_status.configure(text="Image removed")

    def _open_fullscreen(self, path=None):
        """Open fullscreen viewer. If path is None, use current form image.

        FIX: this never mutates the form's image path, even when called with an
        explicit path (from the search page).
        """
        target = path or self.current_image_path
        if not target or not os.path.exists(target):
            messagebox.showinfo("No image", "No image is available."); return
        win = ctk.CTkToplevel(self); win.title("Prescription Image")
        win.geometry("1000x750"); win.minsize(700, 500); win.transient(self)
        win.grid_rowconfigure(0, weight=1); win.grid_columnconfigure(0, weight=1)
        viewer = ImageViewer(win, width=900, height=650)
        viewer.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        viewer.load(target)
        bar = ctk.CTkFrame(win, corner_radius=12)
        bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        for txt, cmd in (("Zoom −", viewer.zoom_out), ("Fit", viewer.fit),
                         ("Zoom +", viewer.zoom_in), ("Rotate", viewer.rotate),
                         ("Close", win.destroy)):
            ctk.CTkButton(bar, text=txt, width=100, height=38,
                          command=cmd).pack(side="left", padx=5, pady=8)
        win.bind("<Escape>", lambda e: win.destroy())

    # ---------------- save / edit ----------------
    def _clear_form(self):
        if self._save_in_progress:
            return
        self.editing_id = None
        self.current_image_path = None
        self.current_image_dirty = False
        self.form_viewer.clear()
        for card in list(self.medication_cards):
            card.destroy()
        self.medication_cards.clear()
        self._add_medication_card()

        self.p_patient.delete(0, "end")
        self.p_age.delete(0, "end")
        self.p_gender.set("")
        self.p_doctor.delete(0, "end")
        self.p_date.delete(0, "end")
        self.p_date.insert(0, datetime.now().strftime("%Y-%m-%d"))
        with connect() as conn:
            row = conn.execute("SELECT name FROM categories ORDER BY name LIMIT 1").fetchone()
        self.p_category.set(row[0] if row else "General")
        self.p_notes.delete("1.0", "end")

        self.save_btn.configure(text="SAVE PRESCRIPTION", state="normal")
        self.cancel_btn.configure(state="disabled")
        self.form_status.configure(text="Ready for a new prescription")

    def _cancel_edit(self):
        self._clear_form()

    def _save(self):
        if self._save_in_progress:
            return

        rows = [r.get_data() for r in self.medication_cards if r.get_data()["name"]]
        if not rows:
            messagebox.showwarning("Missing Medicine",
                                    "Please enter at least one medicine name."); return
        if not self.editing_id and not self.current_image_path:
            messagebox.showwarning("Missing Image",
                                    "Please choose the prescription image."); return

        # ---- validate date & age ----
        date = self.p_date.get().strip() or datetime.now().strftime("%Y-%m-%d")
        if not valid_date(date):
            messagebox.showwarning("Invalid Date",
                                    "Date must be in YYYY-MM-DD format."); return
        age = self.p_age.get().strip()
        if not valid_age(age):
            messagebox.showwarning("Invalid Age",
                                    f"Age must be a whole number between 0 and {MAX_AGE}."); return

        # ---- similar names check ----
        names = [x["name"] for x in rows]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i].lower(), names[j].lower()
                if a != b and abs(len(a) - len(b)) <= 2 and levenshtein(a, b) <= 2:
                    if not messagebox.askyesno("Similar Medicine Names",
                        f"'{names[i]}' and '{names[j]}' look similar. Save anyway?"):
                        return

        # ---- capture state for the worker thread ----
        patient = self.p_patient.get().strip()
        gender = self.p_gender.get().strip()
        doctor = self.p_doctor.get().strip()
        category = self.p_category.get().strip() or "General"
        notes = self.p_notes.get("1.0", "end").strip()
        editing_id = self.editing_id
        image_source = self.current_image_path
        image_dirty = self.current_image_dirty

        # ---- lock UI ----
        self._save_in_progress = True
        self.save_btn.configure(state="disabled", text="SAVING…")
        self.cancel_btn.configure(state="disabled")
        self.form_status.configure(text="Saving, please wait…")

        threading.Thread(
            target=self._save_worker,
            args=(editing_id, image_source, image_dirty, rows,
                  patient, age, gender, doctor, date, category, notes),
            daemon=True,
        ).start()

    def _save_worker(self, editing_id, image_source, image_dirty, rows,
                     patient, age, gender, doctor, date, category, notes):
        new_image = None
        try:
            # 1) Handle image (slow part, hence the thread).
            image_rel = None
            if editing_id and not image_dirty:
                with connect() as conn:
                    r = conn.execute("SELECT image_path FROM prescriptions WHERE id=?",
                                     (editing_id,)).fetchone()
                    image_rel = r[0] if r else None
            elif image_source:
                new_name = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.jpg"
                new_image = os.path.join(IMAGES_DIR, new_name)
                save_compressed_image(image_source, new_image)
                image_rel = os.path.relpath(new_image, DATA_DIR)

            # 2) Database work (creates its own connection → thread-safe).
            now = datetime.now().isoformat()
            old_image = None
            with connect() as conn:
                c = conn.cursor()
                if editing_id:
                    pid = editing_id
                    old = c.execute("SELECT image_path FROM prescriptions WHERE id=?",
                                    (pid,)).fetchone()
                    old_image = old[0] if old else None
                    c.execute("""UPDATE prescriptions SET patient_name=?,age=?,gender=?,
                                 doctor_name=?,date=?,category=?,notes=?,image_path=?,
                                 updated_at=? WHERE id=?""",
                              (patient, age, gender, doctor, date, category,
                               notes, image_rel, now, pid))
                    c.execute("DELETE FROM prescription_items WHERE prescription_id=?", (pid,))
                    action = "UPDATE"
                else:
                    c.execute("""INSERT INTO prescriptions
                        (patient_name,age,gender,doctor_name,date,category,notes,
                         image_path,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                              (patient, age, gender, doctor, date, category,
                               notes, image_rel, now, now))
                    pid = c.lastrowid
                    action = "CREATE"

                for r in rows:
                    normalized = " ".join(r["name"].split())
                    # Case-insensitive lookup (fixes Panadol/panadol duplication).
                    existing = c.execute(
                        "SELECT id FROM medications WHERE name = ? COLLATE NOCASE",
                        (normalized,)).fetchone()
                    if existing:
                        mid = existing[0]
                    else:
                        c.execute("INSERT INTO medications(name) VALUES(?)", (normalized,))
                        mid = c.lastrowid
                    c.execute("""INSERT INTO prescription_items
                        (prescription_id,medication_id,strength,dose,frequency,
                         duration,route,item_notes) VALUES(?,?,?,?,?,?,?,?)""",
                              (pid, mid, r["strength"], r["dose"], r["frequency"],
                               r["duration"], r["route"], r["item_notes"]))
                c.execute("""INSERT INTO audit_log(prescription_id,action,details,
                             created_at) VALUES(?,?,?,?)""",
                          (pid, action, json.dumps({"medicine_count": len(rows)}), now))

            # 3) Delete the old image file (only after a successful save).
            if old_image and old_image != image_rel:
                old_full = safe_path(old_image)
                if old_full and os.path.exists(old_full):
                    try: os.remove(old_full)
                    except OSError: pass

            # 4) Notify the main thread.
            self.after(0, lambda: self._save_succeeded(pid))

        except Exception as exc:
            # Clean up any half-written new image file.
            if new_image and os.path.exists(new_image):
                try: os.remove(new_image)
                except OSError: pass
            LOGGER.exception("Save failed")
            self.after(0, lambda e=exc: self._save_failed(e))

    def _save_succeeded(self, pid):
        self._save_in_progress = False
        messagebox.showinfo("Saved", f"Prescription #{pid} saved successfully.")
        self._clear_form()
        self._refresh_all()
        self._show_page("dashboard")

    def _save_failed(self, exc):
        self._save_in_progress = False
        self.save_btn.configure(state="normal", text="SAVE PRESCRIPTION")
        self.cancel_btn.configure(state="normal" if self.editing_id else "disabled")
        self.form_status.configure(text="Save failed")
        messagebox.showerror("Save Error", str(exc))

    def _edit_from_id(self, pid):
        with connect() as conn:
            row = conn.execute("SELECT * FROM prescriptions WHERE id=?", (pid,)).fetchone()
            items = conn.execute("""SELECT m.name,pi.strength,pi.dose,pi.frequency,
                pi.duration,pi.route,pi.item_notes FROM prescription_items pi
                JOIN medications m ON m.id=pi.medication_id
                WHERE pi.prescription_id=? ORDER BY pi.id""", (pid,)).fetchall()
        if not row: return
        self._show_page("form")
        self._clear_form()
        self.editing_id = pid
        self.current_image_dirty = False

        self.p_patient.delete(0, "end"); self.p_patient.insert(0, row["patient_name"] or "")
        self.p_age.delete(0, "end");     self.p_age.insert(0, row["age"] or "")
        self.p_gender.set(row["gender"] or "")
        self.p_doctor.delete(0, "end");  self.p_doctor.insert(0, row["doctor_name"] or "")
        self.p_date.delete(0, "end")
        self.p_date.insert(0, row["date"] or datetime.now().strftime("%Y-%m-%d"))
        if row["category"]:
            self.p_category.set(row["category"])
        self.p_notes.delete("1.0", "end")
        if row["notes"]:
            self.p_notes.insert("1.0", row["notes"])

        for card in list(self.medication_cards): card.destroy()
        self.medication_cards.clear()
        for item in items:
            self._add_medication_card({
                "name": item[0], "strength": item[1] or "", "dose": item[2] or "",
                "frequency": item[3] or "", "duration": item[4] or "",
                "route": item[5] or "", "item_notes": item[6] or ""})
        if not items:
            self._add_medication_card()
        if row["image_path"]:
            path = safe_path(row["image_path"])
            if path and os.path.exists(path):
                self.current_image_path = path
                self.form_viewer.load(path)
        self.save_btn.configure(text="UPDATE PRESCRIPTION")
        self.cancel_btn.configure(state="normal")
        self.form_status.configure(text=f"Editing prescription #{pid}")

