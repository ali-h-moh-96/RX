# -*- coding: utf-8 -*-
"""SQLite connection handling, schema creation/migration, and integrity checks."""

import os
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH, SCHEMA_VERSION, APP_VERSION, DEFAULT_CATEGORIES, LOGGER

@contextmanager
def connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def checkpoint_wal(db_path=DB_PATH):
    """Flush WAL contents into the main DB file so a plain file-copy is safe."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path, timeout=15)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.warning("wal_checkpoint failed: %s", exc)


def table_columns(conn, table_name):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def init_db():
    with connect() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS prescriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT, age TEXT, gender TEXT, doctor_name TEXT,
            date TEXT, category TEXT, notes TEXT, image_path TEXT,
            created_at TEXT, updated_at TEXT, deleted_at TEXT)""")
        # Case-insensitive uniqueness on medication name.
        c.execute("""CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE)""")
        c.execute("""CREATE TABLE IF NOT EXISTS prescription_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prescription_id INTEGER NOT NULL, medication_id INTEGER NOT NULL,
            strength TEXT, dose TEXT, frequency TEXT, duration TEXT,
            route TEXT, item_notes TEXT,
            FOREIGN KEY (prescription_id) REFERENCES prescriptions(id) ON DELETE CASCADE,
            FOREIGN KEY (medication_id) REFERENCES medications(id))""")
        c.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)")
        c.execute("CREATE TABLE IF NOT EXISTS search_history (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, searched_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, prescription_id INTEGER,
            action TEXT NOT NULL, details TEXT DEFAULT '', created_at TEXT NOT NULL,
            FOREIGN KEY (prescription_id) REFERENCES prescriptions(id) ON DELETE SET NULL)""")

        cols = table_columns(conn, "prescriptions")
        for col, decl in {"updated_at": "TEXT", "deleted_at": "TEXT", "notes": "TEXT"}.items():
            if col not in cols:
                c.execute(f"ALTER TABLE prescriptions ADD COLUMN {col} {decl}")

        if c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            c.executemany("INSERT OR IGNORE INTO categories(name) VALUES(?)",
                          [(x,) for x in DEFAULT_CATEGORIES])

        # Case-insensitive unique index for existing databases (safe if it fails).
        try:
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_medications_name_nocase "
                      "ON medications(name COLLATE NOCASE)")
        except sqlite3.IntegrityError:
            LOGGER.warning("Could not create NOCASE index (duplicates exist). "
                           "Cleaning duplicates…")
            c.execute("""DELETE FROM medications WHERE id NOT IN (
                            SELECT MIN(id) FROM medications GROUP BY LOWER(name))""")

        c.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('schema_version',?)",
                  (str(SCHEMA_VERSION),))
        c.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('app_version',?)",
                  (APP_VERSION,))

        for stmt in (
            "CREATE INDEX IF NOT EXISTS idx_prescriptions_date ON prescriptions(date)",
            "CREATE INDEX IF NOT EXISTS idx_prescriptions_deleted ON prescriptions(deleted_at)",
            "CREATE INDEX IF NOT EXISTS idx_prescriptions_category ON prescriptions(category)",
            "CREATE INDEX IF NOT EXISTS idx_items_prescription ON prescription_items(prescription_id)",
            "CREATE INDEX IF NOT EXISTS idx_items_medication ON prescription_items(medication_id)",
            "CREATE INDEX IF NOT EXISTS idx_search_history_query ON search_history(query)",
            "CREATE INDEX IF NOT EXISTS idx_audit_prescription ON audit_log(prescription_id)",
        ):
            c.execute(stmt)
    LOGGER.info("Database initialized at %s", DB_PATH)


def integrity_check(db_path=DB_PATH):
    try:
        with connect(db_path) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
            if result != "ok":
                return False, f"SQLite integrity_check: {result}"
            if fk:
                return False, f"Foreign-key errors: {len(fk)}"
            return True, "Database integrity is OK."
    except Exception as exc:
        return False, str(exc)
