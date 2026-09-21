# -*- coding: utf-8 -*-
"""Dashboard page: summary stat cards + recent prescriptions list."""

from datetime import datetime
import customtkinter as ctk

from ..config import CARD, BORDER, MUTED, TEXT
from ..db import connect


class DashboardMixin:
    def _page_dashboard(self, p):
        p.grid_rowconfigure(2, weight=1)
        p.grid_columnconfigure(0, weight=1); p.grid_columnconfigure(1, weight=1)
        self._header(p, "Dashboard", "Overview of your local prescription archive")
        cards = ctk.CTkFrame(p, fg_color="transparent")
        cards.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=4)
        for i in range(4):
            cards.grid_columnconfigure(i, weight=1)
        self.stat_cards = {}
        for i, (key, label) in enumerate((("total", "Active Prescriptions"),
                                          ("meds", "Unique Medicines"),
                                          ("trash", "In Trash"),
                                          ("month", "This Month"))):
            card = ctk.CTkFrame(cards, corner_radius=14, fg_color=CARD,
                                border_width=1, border_color=BORDER)
            card.grid(row=0, column=i, sticky="ew", padx=7, pady=7)
            ctk.CTkLabel(card, text=label, font=("Segoe UI", 11),
                         text_color=MUTED).pack(anchor="w", padx=18, pady=(16, 3))
            val = ctk.CTkLabel(card, text="0", font=("Segoe UI", 25, "bold"),
                               text_color=TEXT)
            val.pack(anchor="w", padx=18, pady=(0, 16))
            self.stat_cards[key] = val

        recent = self._card(p, 2, 0, colspan=2)
        recent.grid_columnconfigure(0, weight=1); recent.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(recent, text="Recent Prescriptions", font=("Segoe UI", 16, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 10))
        self.dashboard_list = ctk.CTkTextbox(recent, height=330, corner_radius=10,
                                             fg_color="#F8FAFC", font=("Consolas", 11))
        self.dashboard_list.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))

    def _refresh_dashboard(self):
        with connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM prescriptions WHERE deleted_at IS NULL").fetchone()[0]
            meds = conn.execute("SELECT COUNT(*) FROM medications").fetchone()[0]
            trash = conn.execute("SELECT COUNT(*) FROM prescriptions WHERE deleted_at IS NOT NULL").fetchone()[0]
            month = datetime.now().replace(day=1).strftime("%Y-%m-%d")
            month_count = conn.execute("SELECT COUNT(*) FROM prescriptions WHERE deleted_at IS NULL AND date >= ?", (month,)).fetchone()[0]
            rows = conn.execute("""SELECT p.id,p.patient_name,p.doctor_name,p.date,p.category,
                GROUP_CONCAT(m.name, ', ') meds FROM prescriptions p
                LEFT JOIN prescription_items pi ON pi.prescription_id=p.id
                LEFT JOIN medications m ON m.id=pi.medication_id
                WHERE p.deleted_at IS NULL GROUP BY p.id ORDER BY p.id DESC LIMIT 15""").fetchall()
        for k, v in (("total", total), ("meds", meds), ("trash", trash), ("month", month_count)):
            self.stat_cards[k].configure(text=f"{v:,}")
        self.dashboard_list.configure(state="normal")
        self.dashboard_list.delete("1.0", "end")
        if not rows:
            self.dashboard_list.insert("end", "No prescriptions yet.\n")
        else:
            for r in rows:
                self.dashboard_list.insert("end",
                    f"#{r['id']:<5} {r['date'] or '-':<12} {r['patient_name'] or '-':<25} "
                    f"{r['category'] or '-':<15} {r['meds'] or '-'}\n")
        self.dashboard_list.configure(state="disabled")
