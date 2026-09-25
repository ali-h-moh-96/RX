# -*- coding: utf-8 -*-
"""Tools page: categories management, DB health check, backup/restore (WAL-safe)."""

import os
import json
import shutil
import sqlite3
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime
import customtkinter as ctk
from tkinter import filedialog, messagebox, simpledialog

from ..config import (CARD, TEXT, MUTED, BORDER, BASE_DIR, DB_PATH,
                       BACKUPS_DIR, IMAGES_DIR, LOGS_DIR, AUTO_BACKUP_KEEP, LOGGER,
                       APP_VERSION, SCHEMA_VERSION, PROTECTED_CATEGORY)
from ..db import connect, integrity_check, checkpoint_wal, init_db
from ..utils import safe_path


class ToolsMixin:
    def _page_tools(self, p):
        p.grid_rowconfigure(1, weight=1); p.grid_columnconfigure(0, weight=1)
        self._header(p, "Tools & Settings",
                     "Backup, restore, categories and database health")
        body = ctk.CTkFrame(p, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=5)
        body.grid_columnconfigure(0, weight=1); body.grid_columnconfigure(1, weight=1)

        backup = self._card(body, 0, 0)
        ctk.CTkLabel(backup, text="Backup & Restore", font=("Segoe UI", 16, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=18, pady=(18, 6))
        ctk.CTkButton(backup, text="Create Backup", height=42,
                      command=self._backup).pack(fill="x", padx=18, pady=6)
        ctk.CTkButton(backup, text="Restore Backup", height=42,
                      command=self._restore).pack(fill="x", padx=18, pady=6)
        ctk.CTkLabel(backup, text=f"Automatic backups: {BACKUPS_DIR}",
                     font=("Segoe UI", 9), text_color=MUTED,
                     wraplength=480, justify="left").pack(anchor="w", padx=18, pady=10)

        cats = self._card(body, 0, 1)
        ctk.CTkLabel(cats, text="Categories", font=("Segoe UI", 16, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=18, pady=(18, 6))
        ctk.CTkButton(cats, text="Manage Categories", height=42,
                      command=self._manage_categories).pack(fill="x", padx=18, pady=6)
        ctk.CTkButton(cats, text="Database Health Check", height=42,
                      command=self._health_check).pack(fill="x", padx=18, pady=6)

        loc = self._card(body, 1, 0, colspan=2)
        ctk.CTkLabel(loc, text="Data Location", font=("Segoe UI", 16, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=18, pady=(18, 6))
        ctk.CTkLabel(loc,
            text=f"Database: {DB_PATH}\nImages:   {IMAGES_DIR}\n"
                 f"Backups:  {BACKUPS_DIR}\nLogs:     {LOGS_DIR}",
            font=("Consolas", 10), text_color=MUTED, justify="left"
            ).pack(anchor="w", padx=18, pady=(0, 18))

    def _manage_categories(self):
        win = ctk.CTkToplevel(self); win.title("Manage Categories")
        win.geometry("520x520"); win.minsize(420, 420)
        win.transient(self); win.grab_set()
        win.grid_rowconfigure(1, weight=1); win.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(win, text="Categories", font=("Segoe UI", 18, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=18)
        lb = ctk.CTkScrollableFrame(win)
        lb.grid(row=1, column=0, sticky="nsew", padx=18, pady=6)
        lb.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(win, height=40, placeholder_text="New category")
        entry.grid(row=2, column=0, sticky="ew", padx=18, pady=8)

        def reload():
            for w in lb.winfo_children(): w.destroy()
            with connect() as conn:
                cats = [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY name")]
            for i, name in enumerate(cats):
                row = ctk.CTkFrame(lb, corner_radius=9, fg_color="#F8FAFC")
                row.grid(row=i, column=0, sticky="ew", padx=4, pady=4)
                row.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(row, text=name, font=("Segoe UI", 11, "bold")
                             ).grid(row=0, column=0, sticky="w", padx=10, pady=8)
                ctk.CTkButton(row, text="Rename", width=80, height=30,
                              command=lambda n=name: rename(n)
                              ).grid(row=0, column=1, padx=4)
                ctk.CTkButton(row, text="Delete", width=70, height=30,
                              fg_color="#FEE2E2", hover_color="#FECACA",
                              text_color="#991B1B",
                              command=lambda n=name: delete(n)
                              ).grid(row=0, column=2, padx=8)

        def add():
            name = entry.get().strip()
            if not name: return
            with connect() as conn:
                conn.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
            entry.delete(0, "end"); reload(); self._refresh_categories()

        def rename(old):
            if old == PROTECTED_CATEGORY:
                messagebox.showinfo("Protected",
                    f"'{PROTECTED_CATEGORY}' is the fallback category and can't be renamed.",
                    parent=win)
                return
            new = simpledialog.askstring("Rename", f"Rename '{old}' to:", parent=win)
            if not new or not new.strip(): return
            with connect() as conn:
                conn.execute("UPDATE categories SET name=? WHERE name=?", (new.strip(), old))
                conn.execute("UPDATE prescriptions SET category=? WHERE category=?",
                             (new.strip(), old))
            reload(); self._refresh_categories()

        def delete(name):
            if name == PROTECTED_CATEGORY:
                messagebox.showinfo("Protected",
                    f"'{PROTECTED_CATEGORY}' is the fallback category used whenever a "
                    "prescription's category is deleted, so it can't be deleted itself.",
                    parent=win)
                return
            if not messagebox.askyesno("Confirm", f"Delete category '{name}'?", parent=win):
                return
            with connect() as conn:
                conn.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)",
                             (PROTECTED_CATEGORY,))
                conn.execute("DELETE FROM categories WHERE name=?", (name,))
                conn.execute("UPDATE prescriptions SET category=? WHERE category=?",
                             (PROTECTED_CATEGORY, name))
            reload(); self._refresh_categories()

        ctk.CTkButton(win, text="Add Category", height=40,
                      command=add).grid(row=3, column=0, sticky="ew", padx=18, pady=8)
        reload()

    def _health_check(self):
        ok, msg = integrity_check()
        with connect() as conn:
            orphan = conn.execute(
                "SELECT COUNT(*) FROM prescription_items pi "
                "LEFT JOIN prescriptions p ON p.id=pi.prescription_id "
                "WHERE p.id IS NULL").fetchone()[0]
            missing = 0
            for (path,) in conn.execute("SELECT image_path FROM prescriptions "
                                         "WHERE image_path IS NOT NULL"):
                if not safe_path(path) or not os.path.exists(safe_path(path)):
                    missing += 1
        messagebox.showinfo("Database Health",
            f"Integrity: {'OK' if ok else 'FAILED'}\n{msg}\n\n"
            f"Orphan items: {orphan}\nMissing images: {missing}")

    # ---------------- backup / restore (WAL-safe) ----------------
    def _backup(self, auto=False):
        if auto:
            target = os.path.join(BACKUPS_DIR,
                f"auto_backup_{datetime.now():%Y%m%d_%H%M%S}.zip")
        else:
            target = filedialog.asksaveasfilename(
                title="Save Backup As", defaultextension=".zip",
                initialfile=f"PrescriptionBackup_{datetime.now():%Y-%m-%d_%H%M%S}.zip",
                filetypes=[("ZIP archive", "*.zip")])
            if not target: return

        ok, msg = integrity_check()
        if not ok and not auto:
            messagebox.showerror("Backup",
                "Database integrity check failed:\n" + msg); return
        try:
            # FIX: flush WAL into the main file so a file-copy is complete.
            checkpoint_wal()

            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
                if os.path.exists(DB_PATH):
                    z.write(DB_PATH, "data/prescriptions.db")
                manifest = {"app_version": APP_VERSION, "schema_version": SCHEMA_VERSION,
                            "created_at": datetime.now().isoformat()}
                z.writestr("manifest.json", json.dumps(manifest, indent=2))
                for root, _, files in os.walk(IMAGES_DIR):
                    for f in files:
                        z.write(os.path.join(root, f),
                                os.path.relpath(os.path.join(root, f), BASE_DIR))
            if auto:
                self._prune_backups()
            else:
                messagebox.showinfo("Backup", f"Backup created successfully.\n\n{target}")
        except Exception as exc:
            messagebox.showerror("Backup Error", str(exc))
            LOGGER.exception("Backup failed")

    def _prune_backups(self):
        files = sorted(Path(BACKUPS_DIR).glob("auto_backup_*.zip"))
        while len(files) > AUTO_BACKUP_KEEP:
            try: files.pop(0).unlink()
            except OSError: pass

    def _remove_wal_side_files(self, db_path):
        """Remove -wal/-shm side files so a fresh DB can be installed cleanly."""
        for suffix in ("-wal", "-shm"):
            side = db_path + suffix
            if os.path.exists(side):
                try:
                    os.remove(side)
                except OSError:
                    pass

    def _restore(self):
        path = filedialog.askopenfilename(title="Choose backup",
                                          filetypes=[("ZIP archive", "*.zip")])
        if not path: return
        if not messagebox.askyesno("Confirm",
            "Restore will replace the current database and images. "
            "A safety backup will be created first. Continue?"): return
        self._backup(auto=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with zipfile.ZipFile(path, "r") as z:
                    for info in z.infolist():
                        dest = Path(tmp) / info.filename
                        if not str(dest.resolve()).startswith(str(Path(tmp).resolve())):
                            raise ValueError("Unsafe backup path")
                    z.extractall(tmp)
                db_src = Path(tmp) / "data" / "prescriptions.db"
                if not db_src.exists():
                    raise ValueError("Invalid backup: missing database")
                ok, msg = integrity_check(str(db_src))
                if not ok:
                    raise ValueError("Backup database failed integrity check: " + msg)

                # FIX: remove WAL/shm before swapping the DB.
                if os.path.exists(DB_PATH):
                    os.remove(DB_PATH)
                self._remove_wal_side_files(DB_PATH)
                shutil.copy2(db_src, DB_PATH)

                img_src = Path(tmp) / "data" / "images"
                if img_src.exists():
                    for f in Path(IMAGES_DIR).glob("*"):
                        if f.is_file():
                            try: f.unlink()
                            except OSError: pass
                    for f in img_src.iterdir():
                        if f.is_file():
                            shutil.copy2(f, Path(IMAGES_DIR) / f.name)

            init_db(); self._refresh_all(); self._clear_form()
            messagebox.showinfo("Restore", "Backup restored successfully.")
        except Exception as exc:
            messagebox.showerror("Restore Error", str(exc))
            LOGGER.exception("Restore failed")


    def _refresh_categories(self):
        with connect() as conn:
            cats = [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY name")]
        if hasattr(self, "p_category"):
            self.p_category.configure(values=cats)
            current = self.p_category.get()
            if current not in cats:
                self.p_category.set(cats[0] if cats else "General")
        if hasattr(self, "s_category"):
            self.s_category.configure(values=["Any"] + cats)

    def _refresh_all(self):
        self._refresh_categories(); self._refresh_dashboard()
        self._refresh_search(); self._refresh_trash(); self._refresh_stats()

    def _bind_shortcuts(self):
        self.bind("<Control-s>", lambda e: self._save())
        self.bind("<Control-n>", lambda e: self._clear_form())
        self.bind("<Control-f>", lambda e: self._show_page("search"))
        self.bind("<Escape>", lambda e: self._clear_form())

    def _on_close(self):
        # Avoid overlapping with an in-flight save.
        if self._save_in_progress:
            if not messagebox.askyesno("Save in progress",
                "A save is still running. Quit anyway?"):
                return
        try:
            self._backup(auto=True)
        except Exception:
            LOGGER.exception("Auto-backup on close failed")
        self.destroy()
