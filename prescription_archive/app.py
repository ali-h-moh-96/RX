# -*- coding: utf-8 -*-
"""Main application window: sidebar, page routing, and shared page helpers.

The six pages (dashboard/form/search/trash/stats/tools) are implemented as
mixins in pages/, kept here as a single class via multiple inheritance so
each page's code can live in its own file while still sharing `self`.
"""

import customtkinter as ctk

from .config import APP_NAME, APP_VERSION, BG, SIDEBAR, SIDEBAR_ACTIVE, CARD, BORDER, TEXT, MUTED
from .db import init_db
from .pages.dashboard import DashboardMixin
from .pages.form import FormMixin
from .pages.search import SearchMixin
from .pages.trash import TrashMixin
from .pages.stats import StatsMixin
from .pages.tools import ToolsMixin


class PrescriptionApp(ctk.CTk, DashboardMixin, FormMixin, SearchMixin,
                       TrashMixin, StatsMixin, ToolsMixin):
    def __init__(self):
        super().__init__()
        init_db()
        self.title(f"{APP_NAME}  •  v{APP_VERSION}")
        self.geometry("1420x900")
        self.minsize(1100, 720)
        self.configure(fg_color=BG)
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.editing_id = None
        self.current_image_path = None
        self.current_image_dirty = False
        self.medication_cards = []
        self.selected_search_id = None
        self.selected_trash_id = None
        self._save_in_progress = False

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=225)
        self.grid_columnconfigure(1, weight=1)

        self._build_sidebar()
        self._build_pages()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._show_page("dashboard")
        self._refresh_categories()
        self._clear_form()
        self._refresh_all()

    # ---------------- sidebar / pages ----------------
    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=225, corner_radius=0, fg_color=SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(8, weight=1)

        ctk.CTkLabel(self.sidebar, text="PRESCRIPTION", font=("Segoe UI", 19, "bold"),
                     text_color="white").grid(row=0, column=0, sticky="w", padx=22, pady=(28, 0))
        ctk.CTkLabel(self.sidebar, text="ARCHIVE", font=("Segoe UI", 11, "bold"),
                     text_color="#93C5FD").grid(row=1, column=0, sticky="w",
                                                 padx=22, pady=(0, 25))

        items = [
            ("dashboard", "⌂", "Dashboard"), ("form", "+", "New Prescription"),
            ("search", "⌕", "Search Archive"), ("trash", "♲", "Trash"),
            ("stats", "▥", "Statistics"), ("tools", "⚙", "Tools"),
        ]
        self.nav_buttons = {}
        for i, (key, icon, text) in enumerate(items, 2):
            btn = ctk.CTkButton(self.sidebar, text=f"  {icon}   {text}", anchor="w",
                                height=45, corner_radius=10, fg_color="transparent",
                                hover_color="#1E293B", text_color="#CBD5E1",
                                font=("Segoe UI", 12, "bold"),
                                command=lambda k=key: self._show_page(k))
            btn.grid(row=i, column=0, sticky="ew", padx=12, pady=5)
            self.nav_buttons[key] = btn

        ctk.CTkLabel(self.sidebar, text=f"v{APP_VERSION}\nLocal / Offline",
                     justify="left", font=("Segoe UI", 10), text_color="#64748B"
                     ).grid(row=9, column=0, sticky="sw", padx=22, pady=22)

    def _build_pages(self):
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        builders = (
            ("dashboard", self._page_dashboard),
            ("form",      self._page_form),
            ("search",    self._page_search),
            ("trash",     self._page_trash),
            ("stats",     self._page_stats),
            ("tools",     self._page_tools),
        )
        self.pages = {}
        for key, builder in builders:
            if key == "search":
                scroller = ctk.CTkScrollableFrame(self.content, fg_color=BG)
                scroller.grid(row=0, column=0, sticky="nsew")
                scroller.grid_remove()
                frame = ctk.CTkFrame(scroller, fg_color=BG)
                frame.pack(fill="both", expand=True)
                frame.grid_rowconfigure(2, weight=1)
                frame.grid_columnconfigure(0, weight=1)
                self.pages[key] = scroller
                builder(frame)
            else:
                frame = ctk.CTkFrame(self.content, fg_color=BG)
                frame.grid(row=0, column=0, sticky="nsew")
                frame.grid_remove()
                self.pages[key] = frame
                builder(frame)

    def _show_page(self, key):
        for page in self.pages.values():
            page.grid_remove()
        self.pages[key].grid()
        for name, btn in self.nav_buttons.items():
            btn.configure(fg_color=SIDEBAR_ACTIVE if name == key else "transparent")
        if key == "dashboard": self._refresh_dashboard()
        elif key == "search": self._refresh_search()
        elif key == "trash": self._refresh_trash()
        elif key == "stats": self._refresh_stats()

    def _header(self, parent, title, subtitle):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="ew", padx=26, pady=(24, 12))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=title, font=("Segoe UI", 27, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(frame, text=subtitle, font=("Segoe UI", 11),
                     text_color=MUTED).grid(row=1, column=0, sticky="w", pady=(3, 0))
        return frame

    def _card(self, parent, row, col, rowspan=1, colspan=1, **kwargs):
        card = ctk.CTkFrame(parent, corner_radius=16, fg_color=CARD,
                            border_width=1, border_color=BORDER, **kwargs)
        card.grid(row=row, column=col, rowspan=rowspan, columnspan=colspan,
                  sticky="nsew", padx=8, pady=8)
        return card

