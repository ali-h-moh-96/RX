# -*- coding: utf-8 -*-
"""Shared constants, paths, and logging setup."""

import os
import sys
import shutil
import logging

APP_NAME = "Medical Prescription Archive"
APP_VERSION = "3.3.0"
SCHEMA_VERSION = 3
MAX_IMAGE_SIDE = 2400
JPEG_QUALITY = 88
AUTO_BACKUP_KEEP = 5
MAX_AGE = 150

DEFAULT_CATEGORIES = ["General", "Antibiotics", "Pediatrics", "Chronic", "Dermatology", "Emergency"]
ROUTES = ["", "Oral", "IV", "IM", "SC", "Topical", "Inhalation", "Rectal", "Ophthalmic", "Otic", "Nasal", "Other"]
GENDERS = ["", "Male", "Female", "Other"]
PROTECTED_CATEGORY = "General"   # fallback category; cannot be deleted/renamed away

BG = "#F4F7FB"
CARD = "#FFFFFF"
TEXT = "#172033"
MUTED = "#64748B"
BORDER = "#D9E1EC"
ACCENT = "#2563EB"
SIDEBAR = "#0F172A"
SIDEBAR_ACTIVE = "#1E3A8A"


# ---------------------------------------------------------------------------
def get_base_dir():
    """Folder the running .exe (or the source package) lives in.

    Used only to locate the source tree in dev mode and, once, to find data
    left by older builds that stored everything next to the .exe (see
    get_data_dir below) — it is NOT where data is kept anymore.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir():
    """Where the database, images, backups and logs are stored.

    FIX (data loss on update): earlier builds stored data in a `data/`
    folder next to the .exe (BASE_DIR). That ties your prescriptions to
    wherever the .exe happens to sit — replacing the .exe with a new build,
    moving it, or installing to a new folder silently lost all data.

    Now, for a packaged .exe, data lives in a stable per-user app-data
    folder that has nothing to do with where the .exe file is:
      - Windows: %LOCALAPPDATA%\\PrescriptionArchive
      - macOS:   ~/Library/Application Support/PrescriptionArchive
      - Linux:   $XDG_DATA_HOME/PrescriptionArchive (or ~/.local/share/…)

    You can now update the app just by replacing PrescriptionArchive.exe
    with a new build (same name or not, same folder or not) and your data
    stays exactly where it is.

    Running from source (`python -m prescription_archive.main`) keeps the
    old dev-friendly `data/` folder next to the source tree, unchanged.

    One-time migration: if an old exe-adjacent `data/` folder is found and
    the new location doesn't exist yet, it's moved automatically so nobody
    loses existing prescriptions when upgrading to this version.
    """
    if not getattr(sys, "frozen", False):
        return os.path.join(get_base_dir(), "data")

    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        root = os.path.expanduser("~/Library/Application Support")
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    data_dir = os.path.join(root, "PrescriptionArchive")

    legacy_dir = os.path.join(get_base_dir(), "data")
    if os.path.isdir(legacy_dir) and not os.path.exists(data_dir):
        try:
            shutil.move(legacy_dir, data_dir)
        except Exception:
            pass  # best-effort; a fresh empty data_dir is created below

    return data_dir


BASE_DIR = get_base_dir()
DATA_DIR = get_data_dir()
IMAGES_DIR = os.path.join(DATA_DIR, "images")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "prescriptions.db")
LOG_PATH = os.path.join(LOGS_DIR, "app.log")

for directory in (DATA_DIR, IMAGES_DIR, BACKUPS_DIR, LOGS_DIR):
    os.makedirs(directory, exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
LOGGER = logging.getLogger("prescription_archive")
