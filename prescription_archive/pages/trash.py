# -*- coding: utf-8 -*-
"""Trash page: restore or permanently delete soft-deleted prescriptions."""

import os
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime

from ..config import CARD, TEXT, MUTED, BORDER, IMAGES_DIR
from ..db import connect
from ..utils import safe_path


class TrashMixin:
    def _page_trash(self, p):
        p.grid_rowconfigure(1, weight=1); p.grid_columnconfigure(0, weight=1)
        self._header(p, "Trash",
                     "Restore deleted prescriptions or permanently remove them")
        card = self._card(p, 1, 0)
        card.grid_rowconfigure(1, weight=1); card.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        ctk.CTkButton(bar, text="Refresh", width=100, height=36,
                      command=self._refresh_trash).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Restore Selected", width=145, height=36,
                      command=self._restore_selected).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Delete Permanently", width=160, height=36,
                      fg_color="#FEE2E2", hover_color="#FECACA", text_color="#991B1B",
                      command=self._permanent_delete_selected).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Empty Trash", width=120, height=36,
                      fg_color="#FEE2E2", hover_color="#FECACA", text_color="#991B1B",
                      command=self._empty_trash).pack(side="right", padx=4)
        self.trash_scroll = ctk.CTkScrollableFrame(card, fg_color="#F8FAFC")
        self.trash_scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.trash_scroll.grid_columnconfigure(0, weight=1)

    def _refresh_trash(self):
        if not hasattr(self, "trash_scroll"): return
        for w in self.trash_scroll.winfo_children(): w.destroy()
        with connect() as conn:
            rows = conn.execute("SELECT * FROM prescriptions WHERE deleted_at IS NOT NULL "
                                "ORDER BY deleted_at DESC").fetchall()
            for r in rows:
                meds = [x[0] for x in conn.execute(
                    "SELECT m.name FROM prescription_items pi "
                    "JOIN medications m ON m.id=pi.medication_id "
                    "WHERE pi.prescription_id=?", (r['id'],)).fetchall()]
                card = ctk.CTkFrame(self.trash_scroll, corner_radius=11, fg_color=CARD,
                                    border_width=1, border_color=BORDER)
                card.grid(row=len(self.trash_scroll.winfo_children()), column=0,
                          sticky="ew", padx=4, pady=4)
                card.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(card, text=f"#{r['id']}  {r['patient_name'] or 'Unnamed'}",
                             font=("Segoe UI", 12, "bold"), text_color=TEXT
                             ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))
                ctk.CTkLabel(card,
                    text=f"Deleted: {(r['deleted_at'] or '')[:19].replace('T', ' ')}  |  "
                         f"{r['date'] or '-'}  |  {r['category'] or '-'}\n"
                         f"{', '.join(meds) or '-'}",
                    font=("Segoe UI", 10), text_color=MUTED, justify="left"
                    ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 10))
                ctk.CTkButton(card, text="Select", width=80, height=30,
                              command=lambda pid=r['id']: self._select_trash(pid)
                              ).grid(row=0, column=1, rowspan=2, padx=12)

    def _select_trash(self, pid): self.selected_trash_id = pid

    def _restore_selected(self):
        if not self.selected_trash_id:
            messagebox.showinfo("Select", "Select an item first."); return
        pid = self.selected_trash_id
        with connect() as conn:
            conn.execute("UPDATE prescriptions SET deleted_at=NULL,updated_at=? WHERE id=?",
                         (datetime.now().isoformat(), pid))
            conn.execute("INSERT INTO audit_log(prescription_id,action,details,created_at) "
                         "VALUES(?,?,?,?)", (pid, "RESTORE", "", datetime.now().isoformat()))
        self.selected_trash_id = None; self._refresh_all()

    def _permanent_delete_selected(self):
        if not self.selected_trash_id:
            messagebox.showinfo("Select", "Select an item first."); return
        if messagebox.askyesno("Confirm",
            "Permanently delete this prescription? This cannot be undone."):
            self._permanent_delete(self.selected_trash_id)
            self.selected_trash_id = None
            self._refresh_all()

    def _permanent_delete(self, pid):
        with connect() as conn:
            row = conn.execute("SELECT image_path FROM prescriptions WHERE id=?",
                               (pid,)).fetchone()
            img = safe_path(row[0] if row else "")
            conn.execute("DELETE FROM prescription_items WHERE prescription_id=?", (pid,))
            conn.execute("DELETE FROM prescriptions WHERE id=?", (pid,))
        if img and os.path.exists(img):
            try: os.remove(img)
            except OSError: pass

    def _empty_trash(self):
        with connect() as conn:
            rows = conn.execute("SELECT id FROM prescriptions WHERE deleted_at IS NOT NULL").fetchall()
        if not rows:
            messagebox.showinfo("Trash", "Trash is already empty."); return
        if not messagebox.askyesno("Confirm", f"Permanently delete {len(rows)} item(s)?"):
            return
        for r in rows: self._permanent_delete(r[0])
        self._refresh_all()

    def _trash_selected(self):
        if not self.selected_search_id:
            messagebox.showinfo("Select", "Select a prescription first."); return
        if not messagebox.askyesno("Confirm", "Move this prescription to Trash?"):
            return
        pid = self.selected_search_id
        with connect() as conn:
            conn.execute("UPDATE prescriptions SET deleted_at=?,updated_at=? WHERE id=?",
                         (datetime.now().isoformat(), datetime.now().isoformat(), pid))
            conn.execute("INSERT INTO audit_log(prescription_id,action,details,created_at) "
                         "VALUES(?,?,?,?)", (pid, "TRASH", "", datetime.now().isoformat()))
        self.selected_search_id = None; self._refresh_all()

