# -*- coding: utf-8 -*-
"""One medicine entry (name + strength/dose/frequency/duration/route/note)."""

import customtkinter as ctk

from ..config import TEXT, MUTED, BORDER, ROUTES
from .autocomplete_entry import AutocompleteEntry

class MedicationCard(ctk.CTkFrame):
    def __init__(self, parent, app, data=None, remove_callback=None):
        super().__init__(parent, corner_radius=14, fg_color="#F8FAFC",
                         border_width=1, border_color=BORDER)
        self.app = app
        self.remove_callback = remove_callback
        for i in range(4):
            self.grid_columnconfigure(i, weight=1)

        ctk.CTkLabel(self, text="Medicine", font=("Segoe UI", 11, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w",
                                            padx=12, pady=(10, 3))
        ctk.CTkButton(self, text="✕", width=34, height=30, corner_radius=9,
                      fg_color="#FEE2E2", hover_color="#FECACA", text_color="#991B1B",
                      command=self._remove).grid(row=0, column=3, sticky="e",
                                                  padx=10, pady=7)

        self.name = AutocompleteEntry(self, suggestions_callback=app._med_suggestions,
                                      height=38, corner_radius=9,
                                      placeholder_text="Medicine name",
                                      font=("Segoe UI", 12))
        self.name.grid(row=1, column=0, columnspan=4, sticky="ew",
                       padx=10, pady=(0, 9))

        self.strength = self._field("Strength", 2, 0, "e.g. 500 mg")
        self.dose = self._field("Dose", 2, 1, "e.g. 1 tablet")
        self.frequency = self._field("Frequency", 2, 2, "e.g. twice daily")
        self.duration = self._field("Duration", 2, 3, "e.g. 7 days")
        self.route = self._combo("Route", 3, 0, ROUTES)
        self.note = self._field("Item note", 3, 1, "Optional note", span=3)

        if data:
            self.set_data(data)

    def _field(self, label, row, col, placeholder, span=1):
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=row, column=col, columnspan=span, sticky="ew", padx=6, pady=5)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=label, font=("Segoe UI", 10, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                             padx=4, pady=(0, 3))
        entry = ctk.CTkEntry(box, height=36, corner_radius=8,
                             placeholder_text=placeholder, font=("Segoe UI", 11))
        entry.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 3))
        return entry

    def _combo(self, label, row, col, values):
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=6, pady=5)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=label, font=("Segoe UI", 10, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                             padx=4, pady=(0, 3))
        combo = ctk.CTkComboBox(box, values=values, height=36, corner_radius=8,
                                font=("Segoe UI", 11), dropdown_font=("Segoe UI", 11))
        combo.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 3))
        return combo

    def _remove(self):
        if self.remove_callback:
            self.remove_callback(self)

    def get_data(self):
        return {
            "name": self.name.get().strip(),
            "strength": self.strength.get().strip(),
            "dose": self.dose.get().strip(),
            "frequency": self.frequency.get().strip(),
            "duration": self.duration.get().strip(),
            "route": self.route.get().strip(),
            "item_notes": self.note.get().strip(),
        }

    def set_data(self, data):
        self.name.delete(0, "end"); self.name.insert(0, data.get("name", ""))
        for widget, key in ((self.strength, "strength"), (self.dose, "dose"),
                            (self.frequency, "frequency"), (self.duration, "duration"),
                            (self.note, "item_notes")):
            widget.delete(0, "end"); widget.insert(0, data.get(key, ""))
        self.route.set(data.get("route", ""))
