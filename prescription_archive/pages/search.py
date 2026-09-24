# -*- coding: utf-8 -*-
"""
Production Search Archive page.

SearchMixin rewrite.

Design goals
------------
- Tkinter is NEVER touched directly from worker threads.
- Search workers communicate with Tk through a thread-safe Queue.
- Stale search results are discarded using generation tokens.
- Live search is debounced.
- Live search never creates messagebox dialogs.
- Manual searches validate dates and may display dialogs.
- Pagination uses an immutable filter snapshot.
- Ctrl+F is bound only once per application/window instance.
- LIKE wildcards are escaped so user input is literal.
- Prescription soft-delete is respected.
- Explicit SQL columns are used.
- Medicine lookup is batched per result page.
- Snapshot requests are generation protected.
- Search history is written only for manual searches.
- Old workers may finish, but their results are ignored safely.

Requirements from the surrounding application
---------------------------------------------
The host class is expected to provide:

    self._header(...)
    self._card(...)
    self._edit_from_id(...)
    self._trash_selected(...)
    self._open_fullscreen(...)
    self.after(...)
    self.bind(...)

The database layer must provide:

    connect()

The utilities module must provide:

    safe_path()
    valid_date()

The ImageViewer widget must provide:

    load(path)
    clear()
"""

from __future__ import annotations

import os
import queue
import threading
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..config import CARD, TEXT, MUTED, BORDER, DEFAULT_CATEGORIES
from ..db import connect
from ..utils import safe_path, valid_date
from ..widgets.image_viewer import ImageViewer


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PAGE_SIZE = 40

SEARCH_DEBOUNCE_MS = 350
MIN_LIVE_SEARCH_CHARS = 2

SELECTED_BORDER = "#2563EB"
DEFAULT_BORDER = BORDER


# Keys that cannot change the search text.
_IGNORED_KEYS = {
    "Return",
    "KP_Enter",
    "Tab",
    "Shift_L",
    "Shift_R",
    "Control_L",
    "Control_R",
    "Alt_L",
    "Alt_R",
    "Left",
    "Right",
    "Up",
    "Down",
    "Home",
    "End",
    "Escape",
}


# Tk modifier bits.
#
# Shift is deliberately excluded because Shift+A still changes text.
_MODIFIER_MASK = (
    0x4   # Control
    | 0x8     # Alt / Meta on some platforms
    | 0x10    # Mod2
    | 0x40    # Super / Windows
)


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_MED_SUBQUERY = """
    p.id IN (
        SELECT pi.prescription_id
        FROM prescription_items AS pi
        INNER JOIN medications AS m
            ON m.id = pi.medication_id
        WHERE {condition}
    )
"""


def _escape_like(value: str) -> str:
    """
    Escape SQLite LIKE wildcards.

    User input:
        %
        _
        \

    is treated literally.
    """
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _like(value: str) -> str:
    return f"%{_escape_like(value)}%"


# ---------------------------------------------------------------------------
# Search mixin
# ---------------------------------------------------------------------------

class SearchMixin:
    """
    Search Archive page implementation.
    """

    # =======================================================================
    # Page construction
    # =======================================================================

    def _page_search(self, parent):
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        self._header(
            parent,
            "Search Archive",
            "Find prescriptions by medicine, patient, doctor, category or date",
        )

        # ------------------------------------------------------------------
        # Search state
        # ------------------------------------------------------------------

        self._result_index = 0

        self._search_job = None
        self._search_generation = 0
        self._snapshot_generation = 0

        self._search_running = False
        self._search_worker_count = 0

        self._selected_card = None
        self.selected_search_id = None

        self._search_filters = None

        self._search_offset = 0
        self._search_has_more = False

        # Signature of the last successfully executed search.
        self._last_search_key = None

        # ------------------------------------------------------------------
        # Worker -> Tk communication
        #
        # IMPORTANT:
        # worker threads only put data into this queue.
        #
        # They NEVER call self.after(), self.configure(), widgets, etc.
        # ------------------------------------------------------------------

        if not hasattr(self, "_search_ui_queue"):
            self._search_ui_queue = queue.Queue()

        if not getattr(self, "_search_ui_pump_started", False):
            self._search_ui_pump_started = True
            self._start_search_ui_pump()

        # ------------------------------------------------------------------
        # Build UI
        # ------------------------------------------------------------------

        self._build_filters(parent)
        self._build_results_area(parent)

        # ------------------------------------------------------------------
        # Ctrl+F
        #
        # This is deliberately bound only once.
        # Rebuilding the Search page will NOT add another binding.
        # ------------------------------------------------------------------

        if not getattr(self, "_search_ctrl_f_bound", False):
            try:
                self.bind(
                    "<Control-f>",
                    self._focus_medicine,
                    add="+",
                )
                self._search_ctrl_f_bound = True
            except Exception:
                pass

    # =======================================================================
    # Thread-safe UI queue
    # =======================================================================

    def _start_search_ui_pump(self):
        """
        Start the main-thread queue processor.

        Only this function touches the UI after a worker finishes.
        """

        try:
            self.after(
                50,
                self._process_search_ui_queue,
            )
        except Exception:
            # Window may already be closing.
            self._search_ui_pump_started = False

    def _process_search_ui_queue(self):
        """
        Process worker messages on the Tk thread.
        """

        q = getattr(self, "_search_ui_queue", None)

        if q is None:
            self._search_ui_pump_started = False
            return

        try:
            while True:
                callback, args = q.get_nowait()

                try:
                    callback(*args)
                except Exception:
                    # Never allow one bad UI callback to kill the queue.
                    pass

        except queue.Empty:
            pass

        try:
            self.after(
                50,
                self._process_search_ui_queue,
            )
        except Exception:
            self._search_ui_pump_started = False

    def _post_to_ui(self, callback, *args):
        """
        Queue a callback for execution by Tk's main thread.

        This method is safe to call from worker threads.

        It does NOT call Tkinter itself.
        """

        q = getattr(self, "_search_ui_queue", None)

        if q is None:
            return

        try:
            q.put_nowait(
                (
                    callback,
                    args,
                )
            )
        except Exception:
            pass

    # =======================================================================
    # Ctrl+F
    # =======================================================================

    def _focus_medicine(self, _event=None):
        """
        Focus medicine search only when the Search page is visible.
        """

        try:
            if self.s_meds.winfo_ismapped():
                self.s_meds.focus_set()
                return "break"
        except Exception:
            pass

        return None

    # =======================================================================
    # Filters
    # =======================================================================

    def _build_filters(self, parent):
        filters = ctk.CTkFrame(
            parent,
            corner_radius=14,
            fg_color=CARD,
            border_width=1,
            border_color=BORDER,
        )

        filters.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=18,
            pady=6,
        )

        for column in range(4):
            filters.grid_columnconfigure(
                column,
                weight=1 if column else 2,
            )

        self.s_meds = self._filter_entry(
            filters,
            "Medicines (comma = ALL)",
            0,
            0,
        )

        self.s_people = self._filter_entry(
            filters,
            "Patient / Doctor",
            0,
            1,
        )

        self.s_category = self._filter_combo(
            filters,
            "Category",
            ["Any"] + list(DEFAULT_CATEGORIES),
            0,
            2,
        )

        self.s_date_from = self._filter_entry(
            filters,
            "From date",
            0,
            3,
        )

        self.s_date_to = self._filter_entry(
            filters,
            "To date",
            1,
            3,
        )

        self.s_or_mode = ctk.BooleanVar(
            value=False
        )

        ctk.CTkCheckBox(
            filters,
            text="Match ANY medicine (OR)",
            variable=self.s_or_mode,
            font=("Segoe UI", 10),
            checkbox_width=18,
            checkbox_height=18,
            command=self._schedule_search,
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=12,
            pady=(0, 8),
        )

        buttons = ctk.CTkFrame(
            filters,
            fg_color="transparent",
        )

        buttons.grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="w",
            padx=10,
            pady=8,
        )

        ctk.CTkButton(
            buttons,
            text="SEARCH",
            width=130,
            height=38,
            font=("Segoe UI", 11, "bold"),
            command=self._refresh_search,
        ).pack(
            side="left",
            padx=4,
        )

        ctk.CTkButton(
            buttons,
            text="Show All",
            width=110,
            height=38,
            fg_color="#E5E7EB",
            hover_color="#D1D5DB",
            text_color=TEXT,
            command=self._search_show_all,
        ).pack(
            side="left",
            padx=4,
        )

        # ------------------------------------------------------------------
        # Live search
        #
        # Dates deliberately do NOT trigger live search.
        # ------------------------------------------------------------------

        self.s_meds.bind(
            "<KeyRelease>",
            self._schedule_search,
        )

        self.s_people.bind(
            "<KeyRelease>",
            self._schedule_search,
        )

        # Enter performs an immediate manual search.
        for entry in (
            self.s_meds,
            self.s_people,
            self.s_date_from,
            self.s_date_to,
        ):
            entry.bind(
                "<Return>",
                self._refresh_search,
            )

        self.s_category.configure(
            command=self._schedule_search,
        )

    # =======================================================================
    # Results area
    # =======================================================================

    def _build_results_area(self, parent):
        results = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )

        results.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=18,
            pady=8,
        )

        results.grid_rowconfigure(
            0,
            weight=1,
        )

        results.grid_columnconfigure(
            0,
            weight=3,
        )

        results.grid_columnconfigure(
            1,
            weight=2,
            minsize=420,
        )

        # ------------------------------------------------------------------
        # Left side
        # ------------------------------------------------------------------

        left = self._card(
            results,
            0,
            0,
        )

        left.grid_rowconfigure(
            1,
            weight=1,
        )

        left.grid_columnconfigure(
            0,
            weight=1,
        )

        self.results_label = ctk.CTkLabel(
            left,
            text="Results",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT,
        )

        self.results_label.grid(
            row=0,
            column=0,
            sticky="w",
            padx=16,
            pady=(14, 8),
        )

        self.search_scroll = ctk.CTkScrollableFrame(
            left,
            fg_color="#F8FAFC",
        )

        self.search_scroll.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=10,
            pady=(0, 4),
        )

        self.search_scroll.grid_columnconfigure(
            0,
            weight=1,
        )

        self.load_more_btn = ctk.CTkButton(
            left,
            text="Load More",
            width=130,
            height=34,
            command=self._load_more,
        )

        self.load_more_btn.grid(
            row=2,
            column=0,
            pady=(4, 10),
        )

        self.load_more_btn.grid_remove()

        # ------------------------------------------------------------------
        # Right side
        # ------------------------------------------------------------------

        right = self._card(
            results,
            0,
            1,
        )

        right.grid_columnconfigure(
            0,
            weight=1,
        )

        right.grid_rowconfigure(
            1,
            weight=1,
            minsize=120,
        )

        right.grid_rowconfigure(
            2,
            weight=0,
            minsize=280,
        )

        ctk.CTkLabel(
            right,
            text="Prescription Snapshot",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=16,
            pady=(14, 8),
        )

        self.snapshot = ctk.CTkTextbox(
            right,
            height=140,
            corner_radius=10,
            fg_color="#F8FAFC",
            font=("Consolas", 10),
            wrap="word",
        )

        self.snapshot.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=12,
            pady=6,
        )

        self._style_snapshot_tags()

        self.snapshot.configure(
            state="disabled"
        )

        self.search_viewer = ImageViewer(
            right,
            width=380,
            height=280,
        )

        self.search_viewer.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=12,
            pady=6,
        )

        actions = ctk.CTkFrame(
            right,
            fg_color="transparent",
        )

        actions.grid(
            row=3,
            column=0,
            sticky="ew",
            padx=10,
            pady=8,
        )

        ctk.CTkButton(
            actions,
            text="Edit",
            height=36,
            command=self._edit_selected_search,
        ).pack(
            side="left",
            padx=3,
        )

        ctk.CTkButton(
            actions,
            text="Move to Trash",
            height=36,
            fg_color="#FEF3C7",
            hover_color="#FDE68A",
            text_color="#92400E",
            command=self._trash_selected,
        ).pack(
            side="left",
            padx=3,
        )

        ctk.CTkButton(
            actions,
            text="Fullscreen",
            height=36,
            command=self._open_search_fullscreen,
        ).pack(
            side="left",
            padx=3,
        )

    # =======================================================================
    # Snapshot styling
    # =======================================================================

    def _style_snapshot_tags(self):
        inner = getattr(
            self.snapshot,
            "_textbox",
            None,
        )

        if inner is not None:
            try:
                inner.tag_config(
                    "title",
                    font=("Consolas", 11, "bold"),
                )

                inner.tag_config(
                    "section",
                    font=("Consolas", 10, "bold"),
                )

                inner.tag_config(
                    "muted",
                    foreground=MUTED,
                )

                return

            except Exception:
                pass

        try:
            self.snapshot.tag_config(
                "title",
                foreground="#111827",
            )

            self.snapshot.tag_config(
                "section",
                foreground="#374151",
            )

            self.snapshot.tag_config(
                "muted",
                foreground=MUTED,
            )

        except Exception:
            pass

    # =======================================================================
    # Widget helpers
    # =======================================================================

    def _filter_entry(
        self,
        parent,
        label,
        row,
        col,
    ):
        box = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )

        box.grid(
            row=row,
            column=col,
            sticky="ew",
            padx=8,
            pady=6,
        )

        box.grid_columnconfigure(
            0,
            weight=1,
        )

        ctk.CTkLabel(
            box,
            text=label,
            font=("Segoe UI", 10, "bold"),
            text_color=MUTED,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=4,
            pady=(0, 3),
        )

        entry = ctk.CTkEntry(
            box,
            height=38,
            corner_radius=9,
            placeholder_text=label,
            font=("Segoe UI", 11),
        )

        entry.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=4,
        )

        return entry

    def _filter_combo(
        self,
        parent,
        label,
        values,
        row,
        col,
    ):
        box = ctk.CTkFrame(
            parent,
            fg_color="transparent",
        )

        box.grid(
            row=row,
            column=col,
            sticky="ew",
            padx=8,
            pady=6,
        )

        box.grid_columnconfigure(
            0,
            weight=1,
        )

        ctk.CTkLabel(
            box,
            text=label,
            font=("Segoe UI", 10, "bold"),
            text_color=MUTED,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=4,
            pady=(0, 3),
        )

        combo = ctk.CTkComboBox(
            box,
            values=values,
            height=38,
            corner_radius=9,
            font=("Segoe UI", 11),
            dropdown_font=("Segoe UI", 11),
            state="readonly",
        )

        combo.set("Any")

        combo.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=4,
        )

        return combo

    # =======================================================================
    # Live search
    # =======================================================================

    def _live_search_key(self):
        """
        Fields that participate in live search.

        Dates are intentionally excluded.
        """

        return (
            self.s_meds.get().strip(),
            self.s_people.get().strip(),
            self.s_category.get().strip(),
            bool(self.s_or_mode.get()),
        )

    def _schedule_search(
        self,
        event=None,
        *_args,
    ):
        """
        Debounce live search.

        Important:
        Enter, navigation keys and modifier combinations do not
        schedule another search.
        """

        keysym = getattr(
            event,
            "keysym",
            None,
        )

        if keysym in _IGNORED_KEYS:
            return

        state = getattr(
            event,
            "state",
            0,
        ) or 0

        if state & _MODIFIER_MASK:
            return

        current_key = self._live_search_key()

        if current_key == self._last_search_key:
            return

        if self._search_job is not None:
            try:
                self.after_cancel(
                    self._search_job
                )
            except Exception:
                pass

            self._search_job = None

        try:
            self._search_job = self.after(
                SEARCH_DEBOUNCE_MS,
                self._live_search,
            )
        except Exception:
            self._search_job = None

    def _live_search(self):
        self._search_job = None

        current_key = self._live_search_key()

        if current_key == self._last_search_key:
            return

        meds = self.s_meds.get().strip()
        people = self.s_people.get().strip()

        # Avoid hitting SQLite for one-character searches.
        if meds and len(meds) < MIN_LIVE_SEARCH_CHARS:
            return

        if people and len(people) < MIN_LIVE_SEARCH_CHARS:
            return

        self._refresh_search(
            live=True
        )

    # =======================================================================
    # Filter snapshot
    # =======================================================================

    def _current_filters(self):
        """
        Read all filter widgets.

        Must execute on Tk's thread.
        """

        return {
            "meds": self.s_meds.get().strip(),
            "people": self.s_people.get().strip(),
            "cat": self.s_category.get().strip(),
            "df": self.s_date_from.get().strip(),
            "dt": self.s_date_to.get().strip(),
            "or_mode": bool(
                self.s_or_mode.get()
            ),
        }

    # =======================================================================
    # Query builder
    # =======================================================================

    def _build_query(
        self,
        limit=PAGE_SIZE,
        offset=0,
        filters=None,
    ):
        """
        Build parameterized search SQL.

        Returns:
            (sql, params)

        Raises:
            ValueError for invalid date filters.
        """

        if filters is None:
            filters = self._current_filters()

        meds = filters["meds"]
        people = filters["people"]
        category = filters["cat"]
        date_from = filters["df"]
        date_to = filters["dt"]
        or_mode = filters["or_mode"]

        # ---------------------------------------------------------------
        # Date validation
        # ---------------------------------------------------------------

        if date_from and not valid_date(date_from):
            raise ValueError(
                f"From date '{date_from}' is not a valid date."
            )

        if date_to and not valid_date(date_to):
            raise ValueError(
                f"To date '{date_to}' is not a valid date."
            )

        if (
            date_from
            and date_to
            and date_from > date_to
        ):
            raise ValueError(
                "'From' date is after 'To' date."
            )

        # ---------------------------------------------------------------
        # Medicine terms
        # ---------------------------------------------------------------

        terms = [
            term.strip()
            for term in meds.replace(
                ";",
                ",",
            ).split(",")
            if term.strip()
        ]

        # Deduplicate while preserving user order.
        terms = list(
            dict.fromkeys(terms)
        )

        # ---------------------------------------------------------------
        # Base query
        # ---------------------------------------------------------------

        sql = [
            "SELECT",
            "p.id,",
            "p.patient_name,",
            "p.age,",
            "p.doctor_name,",
            "p.date,",
            "p.category",
            "FROM prescriptions AS p",
            "WHERE p.deleted_at IS NULL",
        ]

        params = []

        # ---------------------------------------------------------------
        # Medicine filter
        # ---------------------------------------------------------------

        if terms:

            if or_mode:
                conditions = [
                    (
                        "m.name LIKE ? "
                        "ESCAPE '\\' "
                        "COLLATE NOCASE"
                    )
                    for _ in terms
                ]

                sql.append(
                    "AND "
                    + _MED_SUBQUERY.format(
                        condition=" OR ".join(
                            conditions
                        )
                    )
                )

                params.extend(
                    _like(term)
                    for term in terms
                )

            else:
                # AND mode:
                # prescription must contain EVERY medicine term.
                for term in terms:

                    sql.append(
                        "AND "
                        + _MED_SUBQUERY.format(
                            condition=(
                                "m.name LIKE ? "
                                "ESCAPE '\\' "
                                "COLLATE NOCASE"
                            )
                        )
                    )

                    params.append(
                        _like(term)
                    )

        # ---------------------------------------------------------------
        # Patient / Doctor
        # ---------------------------------------------------------------

        if people:
            sql.append(
                "AND ("
                "p.patient_name LIKE ? "
                "ESCAPE '\\' "
                "COLLATE NOCASE "
                "OR "
                "p.doctor_name LIKE ? "
                "ESCAPE '\\' "
                "COLLATE NOCASE"
                ")"
            )

            params.extend(
                [
                    _like(people),
                    _like(people),
                ]
            )

        # ---------------------------------------------------------------
        # Category
        # ---------------------------------------------------------------

        if category and category != "Any":
            sql.append(
                "AND p.category = ?"
            )

            params.append(
                category
            )

        # ---------------------------------------------------------------
        # Date range
        # ---------------------------------------------------------------

        if date_from:
            sql.append(
                "AND p.date >= ?"
            )

            params.append(
                date_from
            )

        if date_to:
            sql.append(
                "AND p.date <= ?"
            )

            params.append(
                date_to
            )

        # ---------------------------------------------------------------
        # Stable ordering
        # ---------------------------------------------------------------

        sql.append(
            "ORDER BY p.date DESC, p.id DESC"
        )

        sql.append(
            "LIMIT ? OFFSET ?"
        )

        params.extend(
            [
                int(limit),
                int(offset),
            ]
        )

        return (
            " ".join(sql),
            params,
        )

    # =======================================================================
    # Main search
    # =======================================================================

    def _refresh_search(
        self,
        _event=None,
        live=False,
    ):
        """
        Start a new search.

        live=True:
            no popup dialogs
            no search history

        live=False:
            normal validation dialogs
            medicine query may be saved
        """

        if getattr(
            self,
            "search_scroll",
            None,
        ) is None:
            return

        self._cancel_pending_search()

        # Always clear stale state before validation.
        self._set_search_busy(False)

        filters = self._current_filters()

        try:
            sql, params = self._build_query(
                limit=PAGE_SIZE,
                offset=0,
                filters=filters,
            )

        except ValueError as exc:

            if live:
                self.results_label.configure(
                    text=f"Results — {exc}"
                )
            else:
                messagebox.showwarning(
                    "Invalid filter",
                    str(exc),
                )

            return

        # ---------------------------------------------------------------
        # Successful search
        # ---------------------------------------------------------------

        self._last_search_key = (
            self._live_search_key()
        )

        # New generation invalidates all previous workers.
        self._search_generation += 1

        generation = self._search_generation

        self._search_filters = filters

        self._search_offset = 0
        self._search_has_more = False

        self._clear_results()

        self._set_search_busy(True)

        self.results_label.configure(
            text="Results — searching…"
        )

        # Only manual medicine searches are stored.
        medicine_query = (
            None
            if live
            else filters["meds"]
        )

        self._run_search_worker(
            generation=generation,
            sql=sql,
            params=params,
            append=False,
            medicine_query=medicine_query,
            live=live,
        )

    # =======================================================================
    # Search worker
    # =======================================================================

    def _run_search_worker(
        self,
        generation,
        sql,
        params,
        append,
        medicine_query,
        live,
    ):
        """
        Run database search in background.

        No Tkinter access is permitted here.
        """

        self._search_worker_count += 1

        def worker():
            try:
                with connect() as conn:

                    # --------------------------------------------------
                    # Main prescription query
                    # --------------------------------------------------

                    rows = conn.execute(
                        sql,
                        params,
                    ).fetchall()

                    # --------------------------------------------------
                    # Batched medicine lookup
                    # --------------------------------------------------

                    meds_by_id = (
                        self._fetch_medicines(
                            conn,
                            rows,
                        )
                    )

                    # --------------------------------------------------
                    # Search history
                    #
                    # Only manual searches.
                    # Pagination never writes history.
                    # Live search never writes history.
                    # --------------------------------------------------

                    if (
                        not append
                        and not live
                        and medicine_query
                    ):
                        try:
                            conn.execute(
                                """
                                INSERT INTO search_history
                                    (
                                        query,
                                        searched_at
                                    )
                                VALUES (?, ?)
                                """,
                                (
                                    medicine_query,
                                    datetime.now().isoformat(),
                                ),
                            )

                            conn.commit()

                        except Exception:
                            # Search history is optional.
                            pass

                self._post_to_ui(
                    self._search_finished,
                    generation,
                    rows,
                    meds_by_id,
                    append,
                    None,
                    live,
                )

            except Exception as exc:

                self._post_to_ui(
                    self._search_finished,
                    generation,
                    [],
                    {},
                    append,
                    exc,
                    live,
                )

            finally:
                self._search_worker_count = max(
                    0,
                    self._search_worker_count - 1,
                )

        thread = threading.Thread(
            target=worker,
            name=f"prescription-search-{generation}",
            daemon=True,
        )

        thread.start()

    # =======================================================================
    # Search result callback
    # =======================================================================

    def _search_finished(
        self,
        generation,
        rows,
        meds_by_id,
        append,
        error,
        live,
    ):
        """
        Runs only on Tk's main thread.
        """

        # Ignore stale results.
        if generation != self._search_generation:
            return

        self._set_search_busy(False)

        if error is not None:

            self.results_label.configure(
                text="Results — error"
            )

            self._search_has_more = False

            try:
                self.load_more_btn.grid_remove()
            except Exception:
                pass

            # -----------------------------------------------------------
            # CRITICAL:
            #
            # Live search errors NEVER show a popup.
            # -----------------------------------------------------------

            if live:
                self.results_label.configure(
                    text=f"Results — {error}"
                )
                return

            messagebox.showerror(
                "Search error",
                str(error),
            )

            return

        # ---------------------------------------------------------------
        # Render results
        # ---------------------------------------------------------------

        for row in rows:

            self._result_card(
                row,
                meds_by_id.get(
                    row["id"],
                    [],
                ),
            )

        # ---------------------------------------------------------------
        # Pagination offset
        # ---------------------------------------------------------------

        if append:
            self._search_offset += len(
                rows
            )
        else:
            self._search_offset = len(
                rows
            )

        self._search_has_more = (
            len(rows) == PAGE_SIZE
        )

        total_loaded = (
            self._search_offset
        )

        if self._search_has_more:

            self.results_label.configure(
                text=(
                    f"Results "
                    f"({total_loaded} loaded)"
                )
            )

            self.load_more_btn.grid()

        else:

            self.results_label.configure(
                text=f"Results ({total_loaded})"
            )

            self.load_more_btn.grid_remove()

    # =======================================================================
    # Pagination
    # =======================================================================

    def _load_more(self):
        """
        Load the next page using the original filter snapshot.
        """

        if self._search_running:
            return

        if not self._search_has_more:
            return

        if self._search_filters is None:
            return

        generation = (
            self._search_generation
        )

        offset = (
            self._search_offset
        )

        try:
            sql, params = self._build_query(
                limit=PAGE_SIZE,
                offset=offset,
                filters=self._search_filters,
            )

        except ValueError:
            # Defensive fallback.
            self._search_has_more = False

            try:
                self.load_more_btn.grid_remove()
            except Exception:
                pass

            return

        self._set_search_busy(True)

        self._run_search_worker(
            generation=generation,
            sql=sql,
            params=params,
            append=True,
            medicine_query=None,
            live=False,
        )

    # =======================================================================
    # Busy state
    # =======================================================================

    def _set_search_busy(self, busy):
        self._search_running = bool(
            busy
        )

        try:
            if busy:
                self.load_more_btn.configure(
                    state="disabled",
                    text="Loading…",
                )
            else:
                self.load_more_btn.configure(
                    state="normal",
                    text="Load More",
                )
        except Exception:
            pass

    # =======================================================================
    # Debounce cancellation
    # =======================================================================

    def _cancel_pending_search(self):
        if self._search_job is None:
            return

        try:
            self.after_cancel(
                self._search_job
            )
        except Exception:
            pass

        self._search_job = None

    # =======================================================================
    # Medicine lookup
    # =======================================================================

    @staticmethod
    def _fetch_medicines(
        conn,
        rows,
    ):
        """
        Fetch medicines for the current page in one query.
        """

        if not rows:
            return {}

        ids = [
            row["id"]
            for row in rows
        ]

        placeholders = ",".join(
            "?"
            for _ in ids
        )

        med_rows = conn.execute(
            f"""
            SELECT
                pi.prescription_id,
                m.name
            FROM prescription_items AS pi
            INNER JOIN medications AS m
                ON m.id = pi.medication_id
            WHERE pi.prescription_id
                IN ({placeholders})
            ORDER BY
                pi.prescription_id,
                pi.id
            """,
            ids,
        ).fetchall()

        meds_by_id = {}

        for row in med_rows:

            prescription_id = (
                row["prescription_id"]
            )

            meds_by_id.setdefault(
                prescription_id,
                [],
            ).append(
                row["name"]
            )

        return meds_by_id

    # =======================================================================
    # Result cards
    # =======================================================================

    def _result_card(
        self,
        row,
        meds,
    ):
        card = ctk.CTkFrame(
            self.search_scroll,
            corner_radius=11,
            fg_color=CARD,
            border_width=1,
            border_color=DEFAULT_BORDER,
        )

        card.grid(
            row=self._result_index,
            column=0,
            sticky="ew",
            padx=4,
            pady=4,
        )

        card.grid_columnconfigure(
            0,
            weight=1,
        )

        self._result_index += 1

        patient_name = (
            row["patient_name"]
            or "Unnamed patient"
        )

        ctk.CTkLabel(
            card,
            text=(
                f"#{row['id']}  •  "
                f"{patient_name}"
            ),
            font=("Segoe UI", 12, "bold"),
            text_color=TEXT,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=12,
            pady=(10, 2),
        )

        medicine_text = ", ".join(
            medicine
            for medicine in meds
            if medicine
        ) or "No medicines"

        ctk.CTkLabel(
            card,
            text=(
                f"{row['date'] or '-'}  |  "
                f"{row['doctor_name'] or '-'}  |  "
                f"{row['category'] or '-'}\n"
                f"{medicine_text}"
            ),
            font=("Segoe UI", 10),
            text_color=MUTED,
            justify="left",
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=12,
            pady=(0, 10),
        )

        self._bind_card_click(
            card,
            row["id"],
        )

    def _bind_card_click(
        self,
        card,
        prescription_id,
    ):
        handler = (
            lambda _event,
            pid=prescription_id,
            selected_card=card:
            self._select_search(
                pid,
                selected_card,
            )
        )

        card.bind(
            "<Button-1>",
            handler,
        )

        for child in card.winfo_children():

            try:
                child.bind(
                    "<Button-1>",
                    handler,
                )
            except Exception:
                pass

    # =======================================================================
    # Selection
    # =======================================================================

    def _select_search(
        self,
        pid,
        card=None,
    ):
        # Remove previous visual selection.
        if self._selected_card is not None:

            try:
                self._selected_card.configure(
                    border_color=DEFAULT_BORDER
                )
            except Exception:
                pass

        self._selected_card = card

        if card is not None:

            try:
                card.configure(
                    border_color=SELECTED_BORDER
                )
            except Exception:
                pass

        self.selected_search_id = pid

        self._load_snapshot_async(
            pid
        )

    # =======================================================================
    # Clear results
    # =======================================================================

    def _clear_results(self):
        for widget in (
            self.search_scroll.winfo_children()
        ):
            try:
                widget.destroy()
            except Exception:
                pass

        self._result_index = 0

        self._selected_card = None
        self.selected_search_id = None

        self._search_has_more = False
        self._search_offset = 0

        try:
            self.load_more_btn.grid_remove()
        except Exception:
            pass

        self._clear_snapshot()

    # =======================================================================
    # Snapshot
    # =======================================================================

    def _clear_snapshot(self):
        # Invalidate any currently running snapshot worker.
        self._snapshot_generation += 1

        try:
            self.snapshot.configure(
                state="normal"
            )

            self.snapshot.delete(
                "1.0",
                "end",
            )

            self.snapshot.configure(
                state="disabled"
            )
        except Exception:
            pass

        try:
            self.search_viewer.clear()
        except Exception:
            pass

    def _load_snapshot_async(
        self,
        pid,
    ):
        self._snapshot_generation += 1

        generation = (
            self._snapshot_generation
        )

        def worker():

            try:
                with connect() as conn:

                    # --------------------------------------------------
                    # First verify prescription still exists.
                    # --------------------------------------------------

                    row = conn.execute(
                        """
                        SELECT
                            id,
                            patient_name,
                            age,
                            gender,
                            doctor_name,
                            date,
                            category,
                            notes,
                            image_path
                        FROM prescriptions
                        WHERE id = ?
                          AND deleted_at IS NULL
                        """,
                        (pid,),
                    ).fetchone()

                    # --------------------------------------------------
                    # If prescription disappeared, do not perform
                    # another unnecessary query.
                    # --------------------------------------------------

                    if not row:

                        self._post_to_ui(
                            self._snapshot_finished,
                            generation,
                            pid,
                            None,
                            [],
                            None,
                        )

                        return

                    # --------------------------------------------------
                    # Fetch medicine items.
                    # --------------------------------------------------

                    items = conn.execute(
                        """
                        SELECT
                            m.name,
                            pi.strength,
                            pi.dose,
                            pi.frequency,
                            pi.duration,
                            pi.route,
                            pi.item_notes
                        FROM prescription_items AS pi
                        INNER JOIN medications AS m
                            ON m.id = pi.medication_id
                        WHERE pi.prescription_id = ?
                        ORDER BY pi.id
                        """,
                        (pid,),
                    ).fetchall()

                self._post_to_ui(
                    self._snapshot_finished,
                    generation,
                    pid,
                    row,
                    items,
                    None,
                )

            except Exception as exc:

                self._post_to_ui(
                    self._snapshot_finished,
                    generation,
                    pid,
                    None,
                    [],
                    exc,
                )

        thread = threading.Thread(
            target=worker,
            name=f"prescription-snapshot-{pid}",
            daemon=True,
        )

        thread.start()

    def _snapshot_finished(
        self,
        generation,
        pid,
        row,
        items,
        error,
    ):
        """
        Runs only on Tk's main thread.
        """

        if generation != self._snapshot_generation:
            return

        if error is not None:

            messagebox.showerror(
                "Snapshot error",
                str(error),
            )

            self._clear_snapshot()

            return

        # ---------------------------------------------------------------
        # Prescription disappeared / was moved to trash.
        # ---------------------------------------------------------------

        if not row:

            if (
                self.selected_search_id
                == pid
            ):
                self.selected_search_id = None

                if self._selected_card is not None:
                    try:
                        self._selected_card.configure(
                            border_color=DEFAULT_BORDER
                        )
                    except Exception:
                        pass

                self._selected_card = None

            self._clear_snapshot()

            return

        # ---------------------------------------------------------------
        # Render snapshot
        # ---------------------------------------------------------------

        try:
            self.snapshot.configure(
                state="normal"
            )

            self.snapshot.delete(
                "1.0",
                "end",
            )

            self._write_snapshot(
                pid,
                row,
                items,
            )

            self.snapshot.configure(
                state="disabled"
            )

        except Exception:
            try:
                self.snapshot.configure(
                    state="disabled"
                )
            except Exception:
                pass

            return

        # ---------------------------------------------------------------
        # Image
        # ---------------------------------------------------------------

        path = safe_path(
            row["image_path"] or ""
        )

        if path and os.path.isfile(path):

            try:
                self.search_viewer.load(
                    path
                )
            except Exception:
                try:
                    self.search_viewer.clear()
                except Exception:
                    pass

        else:

            try:
                self.search_viewer.clear()
            except Exception:
                pass

    # =======================================================================
    # Snapshot rendering
    # =======================================================================

    def _write_snapshot(
        self,
        pid,
        row,
        items,
    ):
        box = self.snapshot

        box.insert(
            "end",
            f"Prescription #{pid}\n",
            "title",
        )

        box.insert(
            "end",
            "-" * 55 + "\n",
            "muted",
        )

        fields = (
            ("Patient", "patient_name"),
            ("Age", "age"),
            ("Gender", "gender"),
            ("Doctor", "doctor_name"),
            ("Date", "date"),
            ("Category", "category"),
            ("Notes", "notes"),
        )

        for label, key in fields:

            value = row[key]

            if value:
                box.insert(
                    "end",
                    f"{label}: {value}\n",
                )

        box.insert(
            "end",
            "\nMEDICINES\n",
            "section",
        )

        if not items:

            box.insert(
                "end",
                "  (none)\n",
                "muted",
            )

            return

        for index, item in enumerate(
            items,
            start=1,
        ):
            box.insert(
                "end",
                f"{index}. {item['name']}\n",
            )

            meta = [
                value
                for value in (
                    item["strength"],
                    item["dose"],
                    item["frequency"],
                    item["duration"],
                )
                if value
            ]

            if item["route"]:
                meta.append(
                    f"Route: {item['route']}"
                )

            if meta:
                box.insert(
                    "end",
                    "   "
                    + " | ".join(
                        str(value)
                        for value in meta
                    )
                    + "\n",
                    "muted",
                )

            if item["item_notes"]:

                box.insert(
                    "end",
                    "   Note: "
                    + str(
                        item["item_notes"]
                    )
                    + "\n",
                    "muted",
                )

    # =======================================================================
    # Actions
    # =======================================================================

    def _edit_selected_search(self):
        pid = self.selected_search_id

        if not pid:

            messagebox.showinfo(
                "Select",
                "Select a prescription first.",
            )

            return

        self._edit_from_id(
            pid
        )

    def _open_search_fullscreen(self):
        pid = self.selected_search_id

        if not pid:
            return

        try:

            with connect() as conn:

                row = conn.execute(
                    """
                    SELECT
                        image_path
                    FROM prescriptions
                    WHERE id = ?
                      AND deleted_at IS NULL
                    """,
                    (pid,),
                ).fetchone()

        except Exception as exc:

            messagebox.showerror(
                "Error",
                str(exc),
            )

            return

        path = safe_path(
            row["image_path"]
            if row
            else ""
        )

        if path and Path(path).is_file():

            try:
                self._open_fullscreen(
                    path
                )
            except Exception as exc:
                messagebox.showerror(
                    "Error",
                    str(exc),
                )

    # =======================================================================
    # Show all
    # =======================================================================

    def _search_show_all(self):
        self._cancel_pending_search()

        # ---------------------------------------------------------------
        # Clear filters
        # ---------------------------------------------------------------

        self.s_meds.delete(
            0,
            "end",
        )

        self.s_people.delete(
            0,
            "end",
        )

        self.s_category.set(
            "Any"
        )

        self.s_date_from.delete(
            0,
            "end",
        )

        self.s_date_to.delete(
            0,
            "end",
        )

        self.s_or_mode.set(
            False
        )

        # Reset the live-search signature so Show All always executes.
        self._last_search_key = None

        # Manual search, not live search.
        self._refresh_search(
            live=False
        )