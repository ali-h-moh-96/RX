# -*- coding: utf-8 -*-
"""Entry point: `python -m prescription_archive.main`"""

from .app import PrescriptionApp


def main():
    app = PrescriptionApp()
    app.mainloop()


if __name__ == "__main__":
    main()
