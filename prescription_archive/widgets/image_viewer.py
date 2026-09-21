# -*- coding: utf-8 -*-
"""Zoomable / rotatable prescription image preview (tk.Canvas + PIL)."""

import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageOps, ImageTk

from ..utils import RESAMPLE_LANCZOS

class ImageViewer(ctk.CTkFrame):
    def __init__(self, parent, width=380, height=280):
        super().__init__(parent, fg_color="#111827", corner_radius=12,
                         width=width, height=height)
        self._init_width = width
        self._init_height = height
        self.grid_propagate(False)
        self.pack_propagate(False)

        self.canvas = tk.Canvas(self, bg="#111827", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)

        self.image = None
        self.tk_image = None
        self.zoom = 1.0
        self.fit_mode = True
        self.rotation = 0
        self._render_job = None

        self.canvas.bind("<Configure>", self._schedule_render)
        self.after(10, self._draw_placeholder)

    def _schedule_render(self, _event=None):
        if self._render_job:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
        self._render_job = self.after(50, self._render)

    def _draw_placeholder(self):
        self.canvas.delete("all")
        cw = self.canvas.winfo_width() or self._init_width
        ch = self.canvas.winfo_height() or self._init_height
        if cw <= 1: cw = self._init_width
        if ch <= 1: ch = self._init_height
        self.canvas.create_text(cw // 2, ch // 2, text="No image",
                                fill="#9CA3AF", font=("Segoe UI", 12),
                                anchor="center")

    def load(self, path):
        try:
            with Image.open(path) as im:
                self.image = ImageOps.exif_transpose(im).convert("RGB").copy()
        except Exception as exc:
            self.image = None
            self.tk_image = None
            self.canvas.delete("all")
            cw = self.canvas.winfo_width() or self._init_width
            ch = self.canvas.winfo_height() or self._init_height
            if cw <= 1: cw = self._init_width
            if ch <= 1: ch = self._init_height
            self.canvas.create_text(cw // 2, ch // 2,
                                    text=f"Could not load image\n{exc}",
                                    fill="#F87171", font=("Segoe UI", 10),
                                    anchor="center", justify="center")
            return
        self.zoom = 1.0
        self.fit_mode = True
        self.rotation = 0
        try:
            self.update_idletasks()
        except Exception:
            pass
        self._render()
        self.after(80, self._render)
        self.after(250, self._render)

    def clear(self):
        self.image = None
        self.tk_image = None
        self._draw_placeholder()

    def _render(self):
        self._render_job = None
        if self.image is None:
            return
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw = self._init_width
            ch = self._init_height
        img = self.image.rotate(-self.rotation, expand=True) if self.rotation else self.image
        ratio = min(cw / img.width, ch / img.height) if self.fit_mode else self.zoom
        new_w = max(1, int(img.width * ratio))
        new_h = max(1, int(img.height * ratio))
        resized = img.resize((new_w, new_h), RESAMPLE_LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        x = max((cw - new_w) // 2, 0)
        y = max((ch - new_h) // 2, 0)
        self.canvas.create_image(x, y, anchor="nw", image=self.tk_image)

    def zoom_in(self):
        self.fit_mode = False
        self.zoom = min(self.zoom * 1.2, 8)
        self._render()

    def zoom_out(self):
        self.fit_mode = False
        self.zoom = max(self.zoom / 1.2, 0.05)
        self._render()

    def fit(self):
        self.fit_mode = True
        self._render()

    def rotate(self):
        if self.image:
            self.rotation = (self.rotation + 90) % 360
            self._render()

