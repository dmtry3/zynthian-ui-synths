#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Temper Phase Distortion Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 2 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Distort | Filter & Out
# Features:
#   - Live phase-distortion + saturation transfer curve & harmonic output wave
#   - Interactive 2D pads (Drive x Curve, Cutoff x Resonance) + double-tap reset
#   - Resonant filter curve with authentic frequency scale (20Hz..20kHz)
# ******************************************************************************

import logging
import math
import re
import time
import tkinter
import tkinter.font

from zyngui import zynthian_gui_config
from zyngui import zynthian_widget_base

MULTI_INSTANCE = True
UPDATE_PERIOD = 0.06
DOUBLE_TAP_S = 0.35

COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

TABS = ["Distort", "Filter & Out"]
TAB_ACCENTS = {
    "Distort":      "#ff6b6b",
    "Filter & Out": "#ff922b",
}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.2f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


class zynthian_widget_temper(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Distort"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}
        self._tk_font_cache = {}

        self.widget_canvas = tkinter.Canvas(self, highlightthickness=0, relief="flat", bg=COL_BG)
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
            for cand in (sym, getattr(z, "symbol", ""), getattr(z, "name", "")):
                k = _norm_key(cand)
                if k and k not in idx:
                    idx[k] = z
        self._ctrl_index = idx

    def _get_zctrl(self, sym):
        return self._ctrl_index.get(_norm_key(sym)) if self.processor else None

    def _tab_items(self, tab):
        if tab == "Distort":
            return [
                ("drive",      "Drive"),
                ("saturation", "Saturate"),
                ("curve",      "Curve"),
                ("feedback",   "Feedback"),
            ]
        return [
            ("cutoff",    "Cutoff"),
            ("resonance", "Reso"),
            ("feedback",  "Feedback"),
            ("level",     "Level"),
        ]

    def _rebuild_pages(self):
        if not self.processor:
            return
        screens = {}
        for t in TABS:
            zl = []
            for k, lbl in self._tab_items(t):
                z = self._get_zctrl(k)
                if z is not None:
                    z.short_name = lbl
                    zl.append(z)
            if zl:
                screens[t] = zl
        if screens:
            self.processor.ctrl_screens_dict = screens
            self.after(25, lambda: self._sync_list(self.active_tab))

    def _sync_list(self, tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page(tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Temper sync error: {e}")

    def _select_page(self, title):
        try:
            for i, row in enumerate(self.zyngui_control.list_data):
                if len(row) >= 5 and row[2] == title and row[3] is self.processor:
                    self.zyngui_control.select(i)
                    self.active_tab = title
                    self.last_screen_title = title
                    return True
        except Exception:
            pass
        return False

    def _follow_page(self):
        try:
            info = self.zyngui_control.screen_info
            if info and len(info) >= 5 and info[3] is self.processor:
                t = info[2]
                if t != self.last_screen_title and t in TABS:
                    self.last_screen_title = t
                    self.active_tab = t
                    self.last_snapshot = None
        except Exception:
            pass

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
            return max(0.0, min(1.0, (v - vmin) / (vmax - vmin))) if vmax > vmin else default
        except Exception:
            return default

    @staticmethod
    def _set_norm(z, n):
        if z is None:
            return
        n = max(0.0, min(1.0, float(n)))
        vmin, vmax = float(z.value_min), float(z.value_max)
        if vmax > vmin:
            z.set_value(max(vmin, min(vmax, vmin + n * (vmax - vmin))), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        n = zynthian_widget_temper._norm(z)
        if key == "cutoff":
            return fmt_hz(20.0 * ((20000.0 / 20.0) ** n))
        if key == "level":
            db = n * 36.0 - 24.0
            return f"{db:+.1f}dB"
        if key == "curve":
            return f"{(n - 0.23) * 10.0:+.1f}"
        return f"{int(round(n * 100))}%"

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
        self._follow_page()
        keys = ("curve", "cutoff", "drive", "feedback", "level", "resonance", "saturation")
        snap = (self.width, self.height, self.active_tab,
                tuple(round(self._raw(self._get_zctrl(k)), 3) for k in keys))
        if snap != self.last_snapshot:
            self.last_snapshot = snap
            self._draw()

    def _font(self, size, bold=False):
        key = (size, bold)
        if key not in self._font_cache:
            fam = zynthian_gui_config.font_family
            self._font_cache[key] = (fam, size, "bold") if bold else (fam, size)
        return self._font_cache[key]

    def _fit_font(self, text, max_w, size, bold=False, min_size=7):
        fam = zynthian_gui_config.font_family
        s = int(size)
        txt = str(text)
        while s > min_size:
            k = (s, bold)
            tf = self._tk_font_cache.get(k)
            if tf is None:
                try:
                    tf = tkinter.font.Font(family=fam, size=s, weight="bold" if bold else "normal")
                except Exception:
                    tf = None
                self._tk_font_cache[k] = tf
            if tf is None or tf.measure(txt) <= max_w:
                break
            s -= 1
        return self._font(s, bold=bold)

    def _fs(self, scale=1.0):
        return max(8, int(round(max(9, min(13, self.height // 34)) * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        fnt = self._fit_font(text, max(16, (x1 - x0) - 6), self._fs(0.88), bold=True)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                      fill="#0d0e12" if active else COL_TEXT, font=fnt)
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        tx0, tx1 = x0 + 8, x1 - 8
        by1 = y1 - 6
        by0 = by1 - 11
        val_txt = self._fmt(z, key)
        avail = max(24, (tx1 - tx0) - 6)
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM,
                      font=self._fit_font(label, avail * 0.50, self._fs(0.82)))
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=val_txt, anchor="e", fill=COL_TEXT,
                      font=self._fit_font(val_txt, avail * 0.50, self._fs(0.86), bold=True))
        c.create_rectangle(tx0, by0, tx1, by1, fill=COL_TRACK, outline="")
        fx = tx0 + n * (tx1 - tx0)
        if fx > tx0 + 1:
            c.create_rectangle(tx0, by0, fx, by1, fill=accent, outline="")
        c.create_line(fx, by0, fx, by1, fill="#ffffff", width=2)
        self.hitboxes.append((x0, y0, x1, y1, "hfader", {"key": key, "tx0": tx0, "tx1": tx1}))

    def _draw(self):
        c = self.widget_canvas
        w, h = self.width, self.height
        if w < 40 or h < 40:
            return
        c.delete("all")
        self.hitboxes = []

        pad, gap = 6, 6
        accent = TAB_ACCENTS[self.active_tab]
        hdr_h = max(36, min(46, int(h * 0.11)))
        tw = (w - 2 * pad - gap) / 2.0
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        bot_h = 98
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap
        c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)
        gx0, gx1 = pad + 14, w - pad - 14
        gy0, gy1 = vy0 + 22, vy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2.0

        if self.active_tab == "Distort":
            drv = self._norm(self._get_zctrl("drive"), 0.7)
            sat = self._norm(self._get_zctrl("saturation"), 1.0)
            crv = self._norm(self._get_zctrl("curve"), 0.23)
            fbk = self._norm(self._get_zctrl("feedback"), 0.0)

            c.create_text(gx0, vy0 + 11, text="Temper Phase Distortion  (Drag 2D: X=Drive, Y=Curve)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            # Split panel: Left transfer curve (50%) | Right phase-distorted waveform (50%)
            split_x = gx0 + gw * 0.50
            c.create_line(split_x, gy0, split_x, gy1, fill=COL_GRID, dash=(3, 3))
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

            # Left: Transfer curve
            lx1 = split_x - 10
            lw = max(20, lx1 - gx0)
            c.create_line(gx0, gy1, lx1, gy0, fill="#383c4e", dash=(3, 4))
            t_pts = []
            gain = 1.0 + drv * 6.5
            k_crv = 1.0 + crv * 4.0
            for i in range(49):
                t = i / 48.0
                xin = t * 2.0 - 1.0
                shaped = math.tanh(xin * gain + (crv - 0.23) * 1.4 * (xin ** 2))
                yout = (1.0 - sat) * xin + sat * (math.tanh(shaped * k_crv) / math.tanh(k_crv))
                t_pts.extend([gx0 + t * lw, mid_y - max(-1.0, min(1.0, yout)) * (gh * 0.45)])
            c.create_line(t_pts, fill="#ff922b", width=2.4)

            # Right: Phase-distorted sine wave output
            rx0 = split_x + 10
            rw = max(20, gx1 - rx0)
            w_pts = []
            prev = 0.0
            for i in range(65):
                t = i / 64.0
                ph = t * math.pi * 4.0
                # Phase distortion bends phase using derivative + feedback
                pd = math.sin(ph + drv * 2.4 * math.cos(ph) + fbk * 1.9 * prev)
                y = (1.0 - sat) * pd + sat * math.tanh((pd + (crv - 0.23) * 0.8 * pd * pd) * (1.0 + drv * 3.5))
                prev = y
                w_pts.extend([rx0 + t * rw, mid_y - max(-1.0, min(1.0, y)) * (gh * 0.44)])
            c.create_line(w_pts, fill=accent, width=2.6)

            hx, hy = gx0 + drv * gw, gy1 - crv * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "drive", "yk": "curve"}))
        else:
            cut = self._norm(self._get_zctrl("cutoff"), 1.0)
            res = self._norm(self._get_zctrl("resonance"), 0.0)
            lvl = self._norm(self._get_zctrl("level"), 0.44)
            c.create_text(gx0, vy0 + 11, text="Temper Resonant Filter  (Drag 2D: X=Cutoff, Y=Resonance)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            gy1_f = gy1 - 10
            gh_f = max(20, gy1_f - gy0)
            zero_y = gy0 + gh_f * 0.44
            c.create_line(gx0, zero_y, gx1, zero_y, fill=COL_GRID, dash=(2, 4))
            for frac, flbl in ((0.12, "50"), (0.34, "250"), (0.56, "1k"), (0.78, "4k"), (0.94, "14k")):
                fx = gx0 + frac * gw
                c.create_line(fx, gy0, fx, gy1_f, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1_f + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            pts = []
            poly = [gx0, gy1_f]
            zeta = max(0.08, 1.0 - res * 0.90)
            for i in range(65):
                t = i / 64.0
                u = 2.0 ** ((t - cut) * 8.5)
                mag = 1.0 / math.sqrt((1.0 - u * u) ** 2 + (2.0 * zeta * u) ** 2)
                db = 20.0 * math.log10(max(1e-4, mag)) + (lvl - 0.44) * 14.0
                py = max(gy0, min(gy1_f, zero_y - (db / 24.0) * (gh_f * 0.48)))
                px = gx0 + t * gw
                pts.extend([px, py])
                poly.extend([px, py])
            poly.extend([gx1, gy1_f])
            c.create_polygon(poly, fill="#2b1f14", outline="")
            c.create_line(pts, fill=accent, width=2.8)

            hx, hy = gx0 + cut * gw, gy1_f - res * gh_f
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1_f,
                                   "xk": "cutoff", "yk": "resonance"}))

        py0 = vy1 + gap
        items = self._tab_items(self.active_tab)
        cw = (w - 2 * pad - gap) / 2.0
        ch = (h - pad - py0 - 4) / 2.0
        for i, (k, lbl) in enumerate(items):
            px0 = pad + (i % 2) * (cw + gap)
            py_i = py0 + (i // 2) * (ch + 4)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, k, lbl, accent)

    def _on_press(self, event):
        self.drag_target = None
        now = time.monotonic()
        for x0, y0, x1, y1, kind, payload in reversed(self.hitboxes):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if kind == "tab":
                    if payload != self.active_tab:
                        self.active_tab = payload
                        self._select_page(payload)
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind in ("hfader", "xy_pad"):
                    tid = (kind, payload.get("key") or payload.get("xk"))
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = [payload["key"]] if kind == "hfader" else [payload["xk"], payload["yk"]]
                        for rk in rks:
                            z = self._get_zctrl(rk)
                            if z is not None:
                                z.set_value(z.value_default, send=True)
                        self.last_snapshot = None
                        self._draw()
                        return
                    self.last_tap = (tid, now)
                    self.drag_target = (kind, payload)
                    self._apply_drag(event.x, event.y)
                    return

    def _on_drag(self, event):
        if self.drag_target is not None:
            self._apply_drag(event.x, event.y)

    def _on_release(self, event):
        self.drag_target = None

    def _apply_drag(self, x, y):
        kind, p = self.drag_target
        if kind == "hfader" and p["tx1"] > p["tx0"]:
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]))
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]))
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]))
        self.last_snapshot = None
        self._draw()
