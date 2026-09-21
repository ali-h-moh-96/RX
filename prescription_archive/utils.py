# -*- coding: utf-8 -*-
"""Small pure-function helpers: image compression, fuzzy match, path safety, validators."""

from pathlib import Path
from datetime import datetime

from PIL import Image, ImageOps

from .config import BASE_DIR, MAX_IMAGE_SIDE, JPEG_QUALITY, MAX_AGE

try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:                       # Pillow < 9.1
    RESAMPLE_LANCZOS = Image.LANCZOS

def save_compressed_image(src_path, dst_path):
    with Image.open(src_path) as raw:
        img = ImageOps.exif_transpose(raw)
        if img.mode in ("RGBA", "LA", "P"):
            if img.mode == "P":
                img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, "white")
            if img.mode == "RGBA":
                bg.paste(img, mask=img.getchannel("A"))
            else:
                bg.paste(img)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_IMAGE_SIDE:
            ratio = MAX_IMAGE_SIDE / max(w, h)
            img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))),
                             RESAMPLE_LANCZOS)
        img.save(dst_path, "JPEG", quality=JPEG_QUALITY, optimize=True)


def levenshtein(a, b):
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def safe_path(relative):
    if not relative:
        return None
    base = Path(BASE_DIR).resolve()
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return str(target)


# --- Validators ------------------------------------------------------------
def valid_date(text):
    """Empty allowed; otherwise must be YYYY-MM-DD."""
    text = (text or "").strip()
    if not text:
        return True
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def valid_age(text):
    """Empty allowed; otherwise a non-negative integer ≤ MAX_AGE."""
    text = (text or "").strip()
    if not text:
        return True
    if not text.isdigit():
        return False
    return 0 <= int(text) <= MAX_AGE
