#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Calf Multi Chorus Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 3 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Chorus | Filter | I/O & Mix
# Features live 8-voice phase fan & dual bandpass scope with interactive 2D pads.
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

TABS = ["Chorus", "Filter", "I/O & Mix"]
TAB_ACCENTS = {
    "Chorus":    "#cc5de8",
    "Filter":    "#ff922b",
    "I/O & Mix": "#4dabf7",
}
LOG_KEYS = {"min_delay", "mod_depth", "mod_rate", "freq", "freq2", "q", "level_in", "level_out"}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}kHz"
    return f"{hz:.0f}Hz"


class zynthian_widget_calf_multi_chorus(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Chorus"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}

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
            k = _norm_key(sym)
            if k:
                idx[k] = z
        self._ctrl_index = idx

    def _get_zctrl(self, sym):
        return self._ctrl_index.get(_norm_key(sym)) if self.processor else None

    def _tab_items(self, tab):
        if tab == "Chorus":
            return [
                ("mod_rate",  "Rate"),
                ("mod_depth", "Depth"),
                ("voices",    "Voices"),
                ("min_delay", "Delay"),
            ]
        if tab == "Filter":
            return [
                ("freq",    "Freq 1"),
                ("freq2",   "Freq 2"),
                ("q",       "Q"),
                ("overlap", "Overlap"),
            ]
        return [
            ("amount", "Wet Amt"),
            ("dry",    "Dry Amt"),
            ("stereo", "StereoPh"),
            ("vphase", "VoicePh"),
        ]

    def _rebuild_pages(self):
        if not self.processor:
            return
        screens = {}
        for t in TABS:
            zlist = []
            for k, lbl in self._tab_items(t):
                z = self._get_zctrl(k)
                if z is not None:
                    z.short_name = lbl
                    zlist.append(z)
            if zlist:
                screens[t] = zlist
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
            logging.debug(f"Calf Multi Chorus sync error: {e}")

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
    def _norm(z, key="", default=0.0):
        if z is None:
            return default
        try:
            v = float(z.get_value())
            vmin, vmax = float(z.value_min), float(z.value_max)
            if vmax <= vmin:
                return default
            v = max(vmin, min(vmax, v))
            if key in LOG_KEYS and vmin > 0:
                return math.log(v / vmin) / math.log(vmax / vmin)
            return (v - vmin) / (vmax - vmin)
        except Exception:
            return default

    @staticmethod
    def _set_norm(z, n, key=""):
        if z is None:
            return
        n = max(0.0, min(1.0, float(n)))
        vmin, vmax = float(z.value_min), float(z.value_max)
        if vmax <= vmin:
            return
        val = vmin * ((vmax / vmin) ** n) if (key in LOG_KEYS and vmin > 0) else (vmin + n * (vmax - vmin))
        if getattr(z, "is_integer", False) or key == "voices":
            val = round(val)
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_calf_multi_chorus._raw(z)
        if key in ("freq", "freq2"):
            return fmt_hz(v)
        if key == "mod_rate":
            return f"{v:.2f}Hz"
        if key in ("min_delay", "mod_depth"):
            return f"{v:.1f}ms"
        if key == "voices":
            return f"{int(round(v))}v"
        if key in ("stereo", "vphase"):
            return f"{int(round(v))}°"
        if key in ("amount", "dry", "level_in", "level_out"):
            db = 20.0 * math.log10(max(1e-4, v))
            return f"{db:+.1f}dB" if v > 1e-3 else "-inf"
        if key == "overlap":
            return f"{int(round(v * 100))}%"
        return f"{v:.2f}"

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
        keys = ("on", "lfo", "mod_rate", "mod_depth", "voices", "min_delay",
                "freq", "freq2", "q", "overlap", "amount", "dry", "stereo", "vphase")
        snap = (self.width, self.height, self.active_tab, tuple(round(self._raw(self._get_zctrl(k)), 3) for k in keys))
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
        base = max(9, min(13, self.height // 34))
        return max(8, int(round(base * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                      fill="#0d0e12" if active else COL_TEXT, font=self._font(self._fs(0.92), bold=True))
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z, key)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        tx0, tx1 = x0 + 8, x1 - 8
        by1 = y1 - 6
        by0 = by1 - 11
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM, font=self._font(self._fs(0.84)))
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=self._fmt(z, key), anchor="e", fill=COL_TEXT,
                      font=self._font(self._fs(0.90), bold=True))
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

        pad = 6
        gap = 6
        accent = TAB_ACCENTS[self.active_tab]
        on_val = self._raw(self._get_zctrl("on"), 1.0) >= 0.5
        lfo_val = self._raw(self._get_zctrl("lfo"), 1.0) >= 0.5

        # Header: 3 Tabs + LFO + Active
        hdr_h = max(36, min(46, int(h * 0.11)))
        tog_w = 80
        tabs_w = w - 2 * pad - 2 * (tog_w + gap)
        tw = (tabs_w - 2 * gap) / 3
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        lx0 = w - pad - 2 * tog_w - gap
        self._draw_pill(lx0, pad, lx0 + tog_w, pad + hdr_h, "LFO ●" if lfo_val else "LFO", lfo_val, "#ffd43b", "toggle", "lfo")
        ax0 = w - pad - tog_w
        self._draw_pill(ax0, pad, w - pad, pad + hdr_h, "ON ●" if on_val else "BYP", on_val, "#51cf66", "toggle", "on")

        # Visual Canvas (Middle)
        bot_h = 98
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap
        c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent if on_val else COL_BORDER, width=1)
        gx0, gx1 = pad + 14, w - pad - 14
        gy0, gy1 = vy0 + 22, vy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        if self.active_tab == "Chorus":
            voices = max(1, min(8, int(round(self._raw(self._get_zctrl("voices"), 4.0)))))
            rate_n = self._norm(self._get_zctrl("mod_rate"), "mod_rate")
            depth_n = self._norm(self._get_zctrl("mod_depth"), "mod_depth")
            vph = self._raw(self._get_zctrl("vphase"), 64.0) * math.pi / 180.0
            c.create_text(gx0, vy0 + 11, text=f"Multi Chorus — {voices} Voices  (Drag 2D: X=Rate, Y=Depth)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
            cycles = 1.0 + rate_n * 5.0
            for vi in range(voices - 1, -1, -1):
                pts = []
                for i in range(65):
                    t = i / 64.0
                    y = math.sin(t * cycles * 2.0 * math.pi + vi * vph) * (0.2 + depth_n * 0.75)
                    pts.extend([gx0 + t * gw, mid_y - y * (gh * 0.46)])
                c.create_line(pts, fill=accent if vi == 0 else "#5a3269", width=2.4 if vi == 0 else 1.2)
            hx = gx0 + rate_n * gw
            hy = gy1 - depth_n * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "mod_rate", "yk": "mod_depth"}))
        elif self.active_tab == "Filter":
            f1_n = self._norm(self._get_zctrl("freq"), "freq")
            f2_n = self._norm(self._get_zctrl("freq2"), "freq2")
            q_n = self._norm(self._get_zctrl("q"), "q")
            c.create_text(gx0, vy0 + 11, text="Dual Bandpass Filter  (Drag 2D: X=Freq 1, Y=Freq 2)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
            pts = []
            sigma = max(0.04, 0.22 - q_n * 0.16)
            for i in range(65):
                t = i / 64.0
                r = math.exp(-((t - f1_n) / sigma) ** 2) + math.exp(-((t - f2_n) / sigma) ** 2)
                py = gy1 - min(1.0, r * 0.85) * gh
                pts.extend([gx0 + t * gw, py])
            c.create_line(pts, fill=accent, width=2.6)
            hx = gx0 + f1_n * gw
            hy = gy1 - f2_n * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "freq", "yk": "freq2"}))
        else:
            wet_n = self._norm(self._get_zctrl("amount"), "amount")
            dry_n = self._norm(self._get_zctrl("dry"), "dry")
            c.create_text(gx0, vy0 + 11, text="Stereo Mix  (Drag 2D: X=Dry, Y=Wet Amount)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
            hx = gx0 + dry_n * gw
            hy = gy1 - wet_n * gh
            c.create_rectangle(gx0, hy, hx, gy1, fill="#1c2c3d", outline=accent, width=1.5)
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "dry", "yk": "amount"}))

        # Bottom 2x2 parameter cards (bound to 4 encoders)
        py0 = vy1 + gap
        items = self._tab_items(self.active_tab)
        cw = (w - 2 * pad - gap) / 2
        ch = (h - pad - py0 - 4) / 2
        for i, (k, lbl) in enumerate(items):
            px0 = pad + (i % 2) * (cw + gap)
            py_i = py0 + (i // 2) * (ch + 4)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, k, lbl, accent)

    def _on_press(self, event):
        self.drag_target = None
        for x0, y0, x1, y1, kind, payload in reversed(self.hitboxes):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if kind == "tab":
                    if payload != self.active_tab:
                        self.active_tab = payload
                        self._select_page(payload)
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "toggle":
                    z = self._get_zctrl(payload)
                    if z is not None:
                        cur = self._raw(z) >= 0.5
                        ticks = getattr(z, "ticks", None)
                        z.set_value((ticks[0] if cur else ticks[1]) if ticks and len(ticks) >= 2 else (0.0 if cur else 1.0), send=True)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind in ("hfader", "xy_pad"):
                    now = time.monotonic()
                    tid = (kind, payload.get("key") or payload.get("xk"))
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = [payload["key"]] if kind == "hfader" else [payload["xk"], payload["yk"]]
                        for rk in rks:
                            z = self._get_zctrl(rk)
                            if z is not None:
                                z.reset_value()
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
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]), p["key"])
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]), p["xk"])
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]), p["yk"])
        self.last_snapshot = None
        self._draw()
