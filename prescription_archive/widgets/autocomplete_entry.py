# -*- coding: utf-8 -*-
"""Entry widget with autocomplete popup (keyboard nav + prefix search)."""

import tkinter as tk
import customtkinter as ctk

from ..config import BORDER

class AutocompleteEntry(ctk.CTkEntry):
    def __init__(self, master, suggestions_callback, **kwargs):
        super().__init__(master, **kwargs)
        self._suggest = suggestions_callback
        self._popup = None
        self._listbox = None
        self._hide_job = None
        self.bind("<KeyRelease>", self._on_key)
        self.bind("<Down>", self._on_down_from_entry)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Escape>", lambda e: self._hide(return_focus=True))
        self.bind("<Return>", self._on_return_from_entry)

    # -- events ------------------------------------------------------------
    def _on_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab",
                            "Left", "Right", "Home", "End", "Prior", "Next"):
            return
        text = self.get().strip()
        if len(text) < 2:
            self._hide()
            return
        try:
            items = self._suggest(text)[:8]
        except Exception:
            items = []
        if items:
            self._show(items)
        else:
            self._hide()

    def _on_down_from_entry(self, event=None):
        if self._listbox and self._listbox.size() > 0:
            self._listbox.focus_set()
            self._listbox.selection_clear(0, "end")
            self._listbox.selection_set(0)
            self._listbox.activate(0)
            return "break"

    def _on_return_from_entry(self, event=None):
        # If popup visible, pick the first suggestion; otherwise let Return bubble.
        if self._listbox and self._listbox.size() > 0:
            self.delete(0, "end")
            self.insert(0, self._listbox.get(0))
            self._hide()
            return "break"

    def _on_focus_out(self, event=None):
        # Defer so a click on the listbox can register first.
        if self._hide_job:
            try:
                self.after_cancel(self._hide_job)
            except Exception:
                pass
        self._hide_job = self.after(180, self._check_hide)

    def _check_hide(self):
        self._hide_job = None
        try:
            focused = self.focus_get()
        except Exception:
            focused = None
        if focused is self._listbox:
            return
        self._hide()

    # -- popup -------------------------------------------------------------
    def _show(self, items):
        # Update in place if possible (avoids flicker).
        if self._listbox is None:
            self._popup = tk.Toplevel(self)
            self._popup.wm_overrideredirect(True)
            self._popup.attributes("-topmost", True)
            self._listbox = tk.Listbox(self._popup, activestyle="none",
                                       font=("Segoe UI", 10), borderwidth=0,
                                       exportselection=False,
                                       highlightthickness=1,
                                       highlightbackground=BORDER)
            self._listbox.pack(fill="both", expand=True)
            self._listbox.bind("<<ListboxSelect>>", self._pick)
            self._listbox.bind("<Return>", self._pick)
            self._listbox.bind("<Escape>", lambda e: self._hide(return_focus=True))
            self._listbox.bind("<Up>", self._on_up_in_listbox)
            self._listbox.bind("<FocusOut>", self._on_focus_out)
        else:
            self._listbox.delete(0, "end")

        for it in items:
            self._listbox.insert("end", it)

        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        w = max(self.winfo_width(), 220)
        h = min(len(items), 8) * 24
        self._popup.geometry(f"{w}x{h}+{x}+{y}")
        self._popup.deiconify()

    def _on_up_in_listbox(self, event=None):
        if self._listbox and self._listbox.curselection():
            if self._listbox.curselection()[0] == 0:
                self.focus_set()
                return "break"

    def _pick(self, event=None):
        if self._listbox:
            sel = self._listbox.curselection()
            if sel:
                self.delete(0, "end")
                self.insert(0, self._listbox.get(sel[0]))
        self._hide(return_focus=True)

    def _hide(self, return_focus=False):
        if self._hide_job:
            try:
                self.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None
        if self._popup:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None
            self._listbox = None
        if return_focus:
            try:
                self.focus_set()
            except Exception:
                pass

