# -*- coding: utf-8 -*-
"""Statistics page: usage counts, top medicines, category breakdown."""

import customtkinter as ctk
from datetime import datetime

from ..db import connect


class StatsMixin:
    def _page_stats(self, p):
        p.grid_rowconfigure(1, weight=1); p.grid_columnconfigure(0, weight=1)
        self._header(p, "Statistics",
                     "Usage, medicine frequency and category breakdown")
        card = self._card(p, 1, 0)
        card.grid_rowconfigure(0, weight=1); card.grid_columnconfigure(0, weight=1)
        self.stats_box = ctk.CTkTextbox(card, corner_radius=12,
                                        fg_color="#F8FAFC", font=("Consolas", 11))
        self.stats_box.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)

    def _refresh_stats(self):
        if not hasattr(self, "stats_box"): return
        with connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM prescriptions WHERE deleted_at IS NULL").fetchone()[0]
            meds = conn.execute("SELECT COUNT(*) FROM medications").fetchone()[0]
            trash = conn.execute("SELECT COUNT(*) FROM prescriptions WHERE deleted_at IS NOT NULL").fetchone()[0]
            month = conn.execute(
                "SELECT COUNT(*) FROM prescriptions WHERE deleted_at IS NULL AND date>=?",
                (datetime.now().replace(day=1).strftime("%Y-%m-%d"),)).fetchone()[0]
            top = conn.execute("""SELECT m.name,COUNT(pi.id) cnt FROM medications m
                JOIN prescription_items pi ON pi.medication_id=m.id
                JOIN prescriptions p ON p.id=pi.prescription_id
                WHERE p.deleted_at IS NULL
                GROUP BY m.id ORDER BY cnt DESC LIMIT 10""").fetchall()
            cats = conn.execute("""SELECT COALESCE(category,'(none)') cat,COUNT(*) cnt
                FROM prescriptions WHERE deleted_at IS NULL
                GROUP BY cat ORDER BY cnt DESC""").fetchall()
            searched = conn.execute("""SELECT query,COUNT(*) cnt FROM search_history
                GROUP BY query ORDER BY cnt DESC LIMIT 5""").fetchall()
        lines = ["MEDICAL PRESCRIPTION ARCHIVE", "=" * 62,
                 f"Active prescriptions : {total:,}",
                 f"Unique medicines     : {meds:,}",
                 f"In trash             : {trash:,}",
                 f"This month           : {month:,}", "", "TOP MEDICINES", "-" * 62]
        lines += [f"{r['name']:<40} {r['cnt']:>6}" for r in top] or ["(none)"]
        lines += ["", "BY CATEGORY", "-" * 62]
        lines += [f"{r['cat']:<40} {r['cnt']:>6}" for r in cats] or ["(none)"]
        lines += ["", "TOP SEARCHES", "-" * 62]
        lines += [f"{r['query']:<40} {r['cnt']:>6}" for r in searched] or ["(none)"]
        self.stats_box.configure(state="normal"); self.stats_box.delete("1.0", "end")
        self.stats_box.insert("1.0", "\n".join(lines))
        self.stats_box.configure(state="disabled")

