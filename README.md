# Medical Prescription Archive

A local, offline desktop app (CustomTkinter + SQLite) for archiving prescriptions:
patient details, medicines, and a scanned/photographed image, with search, trash,
statistics, and WAL-safe backup/restore.

## Project structure

```
prescription_archive/
├── main.py              # entry point
├── app.py               # main window: sidebar, page routing
├── config.py             # constants, colors, paths, logging setup
├── db.py                 # SQLite connection, schema, integrity check
├── utils.py               # image compression, fuzzy match, validators
├── widgets/
│   ├── autocomplete_entry.py
│   ├── medication_card.py
│   └── image_viewer.py
└── pages/                 # one file per app page (as a mixin)
    ├── dashboard.py
    ├── form.py
    ├── search.py
    ├── trash.py
    ├── stats.py
    └── tools.py            # backup/restore, categories, health check
```

Each page in `pages/` is a mixin class combined into `PrescriptionApp` in `app.py`,
so page logic can be edited independently while still sharing app state.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m prescription_archive.main
```

Local data (database, images, backups, logs) is created under `data/` next to the
app and is git-ignored — it never gets committed.
