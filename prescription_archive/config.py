# -*- coding: utf-8 -*-
"""Shared constants, paths, and logging setup."""

import os
import sys
import logging

APP_NAME = "Medical Prescription Archive"
APP_VERSION = "3.2.0"
SCHEMA_VERSION = 3
MAX_IMAGE_SIDE = 2400
JPEG_QUALITY = 88
AUTO_BACKUP_KEEP = 5
MAX_AGE = 150

DEFAULT_CATEGORIES = ["General", "Antibiotics", "Pediatrics", "Chronic", "Dermatology", "Emergency"]
ROUTES = ["", "Oral", "IV", "IM", "SC", "Topical", "Inhalation", "Rectal", "Ophthalmic", "Otic", "Nasal", "Other"]
GENDERS = ["", "Male", "Female", "Other"]

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
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
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
