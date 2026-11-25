#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# YK Chorus Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# Roland Juno-60 style BBD Chorus UI with large tactile Mode buttons
# (OFF / I / II / I+II), live dual-LFO BBD modulation scope, and 2-way sync
# with Zynthian's 4 physical encoders.
# ******************************************************************************

import logging
import math
import re
import time
import tkinter

from zyngui import zynthian_gui_config
from zyngui import zynthian_widget_base

MULTI_INSTANCE = True
UPDATE_PERIOD = 0.06
DOUBLE_TAP_S = 0.35

COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"
ACCENT = "#4dabf7"
ACCENT_2 = "#ff922b"

PAGE_TITLE = "YK Chorus"


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


class zynthian_widget_yk_chorus(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}

        self.widget_canvas = tkinter.Canvas(
            self, highlightthickness=0, relief="flat", bg=COL_BG
        )
        self.widget_canvas.grid(sticky="news")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.widget_canvas.bind("<ButtonPress-1>", self._on_press)
        self.widget_canvas.bind("<B1-Motion>", self._on_drag)
        self.widget_canvas.bind("<ButtonRelease-1>", self._on_release)

    def set_processor(self, processor):
        super().set_processor(processor)
        if processor is None:
            return
        pid = id(processor)
        self._build_ctrl_index(processor)
        if self._bound_proc_id != pid:
            self._bound_proc_id = pid
            self._rebuild_pages()

    def _build_ctrl_index(self, processor):
        idx = {}
        for sym, z in processor.controllers_dict.items():
            if z is None:
                continue
            for attr in ("filter", "envelope"):
                if hasattr(z, attr):
                    try:
                        delattr(z, attr)
                    except Exception:
                        pass
            k = _norm_key(sym)
            if k:
                idx[k] = z
            zn = getattr(z, "name", None)
            if zn:
                kn = _norm_key(zn)
                if kn and kn not in idx:
                    idx[kn] = z
        self._ctrl_index = idx

    def _get_zctrl(self, sym):
        if not self.processor:
            return None
        return self._ctrl_index.get(_norm_key(sym))

    def _rebuild_pages(self):
        if not self.processor:
            return
        items = [
            ("chorus_1_enable",   "Mode I"),
            ("chorus_2_enable",   "Mode II"),
            ("chorus_1_lfo_rate", "Rate I"),
            ("chorus_2_lfo_rate", "Rate II"),
        ]
        zlist = []
        for k, lbl in items:
            z = self._get_zctrl(k)
            if z is not None:
                z.short_name = lbl
                zlist.append(z)
        if zlist:
            self.processor.ctrl_screens_dict = {PAGE_TITLE: zlist}
            self.after(25, self._sync_list)

    def _sync_list(self):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            for i, row in enumerate(self.zyngui_control.list_data):
                if len(row) >= 5 and row[2] == PAGE_TITLE and row[3] is self.processor:
                    self.zyngui_control.select(i)
                    break
            self._draw()
        except Exception as e:
            logging.debug(f"YK Chorus widget sync error: {e}")

    @staticmethod
    def _raw(z, default=0.0):
        if z is None:
            return default
        try:
            return float(z.get_value())
        except Exception:
            return default

    @staticmethod
    def _norm(z, default=0.0):
        if z is None:
            return default
        try:
            v = float(z.get_value())
            vmin, vmax = float(z.value_min), float(z.value_max)
            if vmax <= vmin:
                return default
            return max(0.0, min(1.0, (v - vmin) / (vmax - vmin)))
        except Exception:
            return default

    @staticmethod
    def _set_norm(z, n):
        if z is None:
            return
        n = max(0.0, min(1.0, float(n)))
        vmin, vmax = float(z.value_min), float(z.value_max)
        if vmax > vmin:
            z.set_value(vmin + n * (vmax - vmin), send=True)

    @staticmethod
    def _set_bool(z, state):
        if z is None:
            return
        ticks = getattr(z, "ticks", None)
        if ticks and len(ticks) >= 2:
            z.set_value(ticks[1] if state else ticks[0], send=True)
        else:
            z.set_value(1.0 if state else 0.0, send=True)

    def update(self):
        now = time.monotonic()
        if now < self.next_update:
            return
        self.next_update = now + UPDATE_PERIOD
        super().update()

    def on_size(self, event):
        if super().on_size(event):
            self.last_snapshot = None
            self._draw()
            return True
        return False

    def show(self):
        super().show()
        self.last_snapshot = None
        self._draw()

    def refresh_gui(self):
        if not self.processor or self.width < 40 or self.height < 40:
            return
        snap = (
            self.width, self.height,
            round(self._raw(self._get_zctrl("chorus_1_enable")), 2),
            round(self._raw(self._get_zctrl("chorus_2_enable")), 2),
            round(self._raw(self._get_zctrl("chorus_1_lfo_rate")), 3),
            round(self._raw(self._get_zctrl("chorus_2_lfo_rate")), 3),
        )
        if snap != self.last_snapshot:
            self.last_snapshot = snap
            self._draw()

    def _font(self, size, bold=False):
        key = (size, bold)
        if key not in self._font_cache:
            fam = zynthian_gui_config.font_family
            self._font_cache[key] = (fam, size, "bold") if bold else (fam, size)
        return self._font_cache[key]

    def _fs(self, scale=1.0):
        base = max(9, min(14, self.height // 32))
        return max(8, int(round(base * scale)))

    def _draw(self):
        c = self.widget_canvas
        w, h = self.width, self.height
        if w < 40 or h < 40:
            return
        c.delete("all")
        self.hitboxes = []

        pad = 6
        gap = 8
        c1_on = self._raw(self._get_zctrl("chorus_1_enable")) >= 0.5
        c2_on = self._raw(self._get_zctrl("chorus_2_enable")) >= 0.5
        r1 = self._raw(self._get_zctrl("chorus_1_lfo_rate"), 5.0)
        r2 = self._raw(self._get_zctrl("chorus_2_lfo_rate"), 8.3)

        # Header
        hdr_h = max(38, min(46, int(h * 0.11)))
        c.create_rectangle(pad, pad, w - pad, pad + hdr_h, fill=COL_PANEL, outline=ACCENT, width=1)
        c.create_text(pad + 12, pad + hdr_h / 2, text="YK CHORUS  —  JUNO-60 BBD ENSEMBLE",
                      anchor="w", fill=ACCENT, font=self._font(self._fs(1.0), bold=True))
        mode_lbl = "I + II" if (c1_on and c2_on) else ("MODE I" if c1_on else ("MODE II" if c2_on else "BYPASS"))
        c.create_text(w - pad - 12, pad + hdr_h / 2, text=mode_lbl,
                      anchor="e", fill="#51cf66" if (c1_on or c2_on) else COL_DIM,
                      font=self._font(self._fs(1.0), bold=True))

        # Big Retro Juno Mode Buttons
        btn_y0 = pad + hdr_h + gap
        btn_h = max(56, int(h * 0.19))
        btn_y1 = btn_y0 + btn_h
        modes = [
            ("OFF",     False, False, "#808496"),
            ("MODE I",  True,  False, ACCENT),
            ("MODE II", False, True,  ACCENT_2),
            ("I + II",  True,  True,  "#51cf66"),
        ]
        bw = (w - 2 * pad - 3 * gap) / 4
        for i, (lbl, m1, m2, col) in enumerate(modes):
            bx0 = pad + i * (bw + gap)
            act = (c1_on == m1 and c2_on == m2)
            c.create_rectangle(bx0, btn_y0, bx0 + bw, btn_y1,
                               fill=col if act else COL_PANEL,
                               outline=col if act else COL_BORDER, width=2 if act else 1)
            c.create_text(bx0 + bw / 2, (btn_y0 + btn_y1) / 2, text=lbl,
                          fill="#0d0e12" if act else COL_TEXT,
                          font=self._font(self._fs(1.15), bold=True))
            self.hitboxes.append((bx0, btn_y0, bx0 + bw, btn_y1, "mode", (m1, m2)))

        # Dual BBD LFO Scope
        sl_h = 62
        sc_y0 = btn_y1 + gap
        sc_y1 = h - pad - sl_h - gap
        c.create_rectangle(pad, sc_y0, w - pad, sc_y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        gx0, gx1 = pad + 14, w - pad - 14
        gy0, gy1 = sc_y0 + 14, sc_y1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(3, 4))

        for active, rate, col, ph in ((c1_on, r1, ACCENT, 0.0), (c2_on, r2, ACCENT_2, 1.4)):
            pts = []
            cycles = 1.0 + (rate / 10.0) * 6.0
            for i in range(97):
                t = i / 96.0
                y = math.sin(t * cycles * 2.0 * math.pi + ph)
                pts.extend([gx0 + t * gw, mid_y - y * (gh * 0.42)])
            c.create_line(pts, fill=col if active else COL_GRID, width=2.8 if active else 1.3)

        # Bottom 2 large horizontal rate faders
        fy0 = sc_y1 + gap
        fy1 = h - pad
        fw = (w - 2 * pad - gap) / 2
        self._draw_slider(pad, fy0, pad + fw, fy1, "chorus_1_lfo_rate", "Chorus I Rate", f"{r1:.2f} Hz", ACCENT if c1_on else COL_DIM)
        self._draw_slider(pad + fw + gap, fy0, w - pad, fy1, "chorus_2_lfo_rate", "Chorus II Rate", f"{r2:.2f} Hz", ACCENT_2 if c2_on else COL_DIM)

    def _draw_slider(self, x0, y0, x1, y1, key, lbl, val_str, col):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        tx0, tx1 = x0 + 10, x1 - 10
        by1 = y1 - 8
        by0 = by1 - 16
        c.create_text(tx0, y0 + 16, text=lbl, anchor="w", fill=COL_DIM, font=self._font(self._fs(0.9)))
        c.create_text(tx1, y0 + 16, text=val_str, anchor="e", fill=COL_TEXT, font=self._font(self._fs(0.95), bold=True))
        c.create_rectangle(tx0, by0, tx1, by1, fill=COL_TRACK, outline="")
        fx = tx0 + n * (tx1 - tx0)
        if fx > tx0 + 1:
            c.create_rectangle(tx0, by0, fx, by1, fill=col, outline="")
        c.create_line(fx, by0, fx, by1, fill="#ffffff", width=2)
        self.hitboxes.append((x0, y0, x1, y1, "hfader", {"key": key, "tx0": tx0, "tx1": tx1}))

    def _on_press(self, event):
        self.drag_target = None
        for x0, y0, x1, y1, kind, payload in reversed(self.hitboxes):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if kind == "mode":
                    m1, m2 = payload
                    self._set_bool(self._get_zctrl("chorus_1_enable"), m1)
                    self._set_bool(self._get_zctrl("chorus_2_enable"), m2)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "hfader":
                    now = time.monotonic()
                    if payload["key"] == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        z = self._get_zctrl(payload["key"])
                        if z is not None:
                            z.reset_value()
                        self.last_snapshot = None
                        self._draw()
                        return
                    self.last_tap = (payload["key"], now)
                    self.drag_target = payload
                    self._apply_drag(event.x)
                    return

    def _on_drag(self, event):
        if self.drag_target is not None:
            self._apply_drag(event.x)

    def _on_release(self, event):
        self.drag_target = None

    def _apply_drag(self, x):
        p = self.drag_target
        if p["tx1"] > p["tx0"]:
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]))
            self.last_snapshot = None
            self._draw()
