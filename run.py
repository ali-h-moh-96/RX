# -*- coding: utf-8 -*-
"""Entry point for building a Windows .exe with PyInstaller.

Run the app normally during development with:
    python -m prescription_archive.main

Build the exe with (see README / chat instructions):
    pyinstaller --noconsole --onefile --collect-all customtkinter --icon=assets/prescription-archive.ico --name PrescriptionArchive run.py
"""

from prescription_archive.main import main

if __name__ == "__main__":
    main()
