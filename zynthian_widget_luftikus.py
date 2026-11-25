#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Luftikus (Maag EQ4 Mastering EQ) Widget for Zynthian (V5 800x480)
# Part of UI Synths (zynthian-ui-synths)
#
# 2 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   EQ Bands | Air & Master   + KEEP / ANALOG / MASTER switches
# Features:
#   - Live 6-band Maag EQ4 parallel frequency response curve (10Hz..40kHz)
#   - 6 independent touch-draggable EQ band nodes (10, 40, 160, 640, 2.5k, Air)
#     with double-tap zero/reset right on the curve
#   - Dedicated iconic 5-frequency Air Band selector (2.5 / 5 / 10 / 20 / 40 kHz)
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
COL_AIR = "#38d9a9"

TABS = ["EQ Bands", "Air & Master"]
TAB_ACCENTS = {
    "EQ Bands":     "#4dabf7",
    "Air & Master": "#ffd43b",
}

AIR_FREQS = [
    ("2.5k", 2500.0, 0.00),
    ("5k",   5000.0, 0.25),
    ("10k", 10000.0, 0.50),
    ("20k", 20000.0, 0.75),
    ("40k", 40000.0, 1.00),
]

BANDS = [
    ("gain_10_hz",   "10Hz",  10.0,  "#cc5de8"),
    ("gain_40_hz",   "40Hz",  40.0,  "#4dabf7"),
    ("gain_160_hz",  "160",  160.0,  "#51cf66"),
    ("gain_640_hz",  "640",  640.0,  "#ffd43b"),
    ("gain_2_5_khz", "2.5k", 2500.0, "#ff922b"),
]

BIPOLAR_KEYS = {"gain_10_hz", "gain_40_hz", "gain_160_hz", "gain_640_hz", "gain_2_5_khz", "mastervol"}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


class zynthian_widget_luftikus(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "EQ Bands"
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
        if tab == "EQ Bands":
            return [
                ("gain_10_hz",  "10Hz Sub"),
                ("gain_40_hz",  "40Hz Low"),
                ("gain_160_hz", "160Hz"),
                ("gain_640_hz", "640Hz"),
            ]
        return [
            ("gain_2_5_khz", "2.5kHz"),
            ("gain_high",    "Air Gain"),
            ("type_high",    "Air Freq"),
            ("mastervol",    "Master"),
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
            logging.debug(f"Luftikus sync error: {e}")

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
    def _air_idx(val):
        return max(0, min(4, int(round(max(0.0, min(1.0, float(val))) * 4.0))))

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        n = zynthian_widget_luftikus._norm(z)
        if key == "type_high":
            return AIR_FREQS[zynthian_widget_luftikus._air_idx(n)][0]
        if key == "gain_high":
            return f"+{n * 10.0:.1f}dB"
        if key == "mastervol":
            return f"{(n - 0.5) * 24.0:+.1f}dB"
        if key in BIPOLAR_KEYS:
            return f"{(n - 0.5) * 20.0:+.1f}dB"
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
        keys = ("gain_10_hz", "gain_40_hz", "gain_160_hz", "gain_640_hz", "gain_2_5_khz",
                "gain_high", "type_high", "keep_gain", "analog", "mastering", "mastervol")
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
        fnt = self._fit_font(text, max(16, (x1 - x0) - 6), self._fs(0.84), bold=True)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                      fill="#0d0e12" if active else COL_TEXT, font=fnt)
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z)
        bipolar = key in BIPOLAR_KEYS
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
        if bipolar:
            mx = (tx0 + tx1) / 2
            c.create_rectangle(min(mx, fx), by0, max(mx, fx), by1, fill=accent, outline="")
            c.create_line(mx, by0 - 1, mx, by1 + 1, fill=COL_TEXT, width=1)
        elif fx > tx0 + 1:
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

        keep_on = self._raw(self._get_zctrl("keep_gain")) >= 0.5
        ana_on = self._raw(self._get_zctrl("analog")) >= 0.5
        mst_on = self._raw(self._get_zctrl("mastering")) >= 0.5

        # Header: 2 Tabs (left 46%) + KEEP / ANALOG / MASTER pills (right 54%)
        left_w = int((w - 2 * pad) * 0.44)
        tw = (left_w - gap) / 2.0
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        rx0 = pad + left_w + gap
        sw = (w - pad - rx0 - 2 * gap) / 3.0
        self._draw_pill(rx0, pad, rx0 + sw, pad + hdr_h, "KEEP", keep_on, "#51cf66", "toggle", "keep_gain")
        self._draw_pill(rx0 + sw + gap, pad, rx0 + 2 * sw + gap, pad + hdr_h, "ANALOG", ana_on, "#ff922b", "toggle", "analog")
        self._draw_pill(rx0 + 2 * (sw + gap), pad, w - pad, pad + hdr_h, "MASTER", mst_on, "#cc5de8", "toggle", "mastering")

        # Row 2: Iconic 5-Frequency Air Band Selector (>=34px)
        r2_y0 = pad + hdr_h + gap
        r2_h = 34
        air_idx = self._air_idx(self._norm(self._get_zctrl("type_high"), 0.0))
        lbl_w = 52
        c.create_rectangle(pad, r2_y0, pad + lbl_w, r2_y0 + r2_h, fill=COL_PANEL, outline=COL_BORDER)
        c.create_text(pad + lbl_w / 2, r2_y0 + r2_h / 2, text="AIR", fill=COL_AIR,
                      font=self._font(self._fs(0.84), bold=True))
        ax0 = pad + lbl_w + gap
        aw = (w - pad - ax0 - 4 * gap) / 5.0
        for i, (albl, _, aval) in enumerate(AIR_FREQS):
            x0 = ax0 + i * (aw + gap)
            self._draw_pill(x0, r2_y0, x0 + aw, r2_y0 + r2_h, albl, i == air_idx, COL_AIR,
                            "set_norm", ("type_high", aval))

        # Main 6-Band Interactive Mastering EQ Curve
        bot_h = 94
        vy0 = r2_y0 + r2_h + gap
        vy1 = h - pad - bot_h - gap
        c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)
        gx0, gx1 = pad + 30, w - pad - 12
        gy0, gy1 = vy0 + 20, vy1 - 16
        gw, gh = max(24, gx1 - gx0), max(24, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2.0

        c.create_text(pad + 8, vy0 + 10, text="Luftikus 6-Band EQ  (Drag any band node up/down · Double-tap resets)",
                      anchor="w", fill=COL_DIM, font=self._fit_font(
                          "Luftikus 6-Band EQ  (Drag any band node up/down · Double-tap resets)",
                          w - 2 * pad - 16, self._fs(0.75), bold=True))

        f_min, f_max = 8.0, 45000.0
        log_span = math.log(f_max / f_min)

        def hz_to_x(hz):
            hz = max(f_min, min(f_max, hz))
            return gx0 + (math.log(hz / f_min) / log_span) * gw

        def db_to_y(db):
            db = max(-12.0, min(12.0, db))
            return mid_y - (db / 12.5) * (gh * 0.48)

        # dB grid (+10, +5, 0, -5, -10)
        for db in (10, 5, 0, -5, -10):
            y = db_to_y(db)
            c.create_line(gx0, y, gx1, y, fill="#3c4054" if db == 0 else COL_GRID, dash=(3, 4) if db == 0 else (2, 4))
            c.create_text(gx0 - 4, y, text=f"{db:+d}" if db != 0 else "0", anchor="e", fill=COL_DIM,
                          font=self._font(self._fs(0.66)))

        # Frequency grid
        for f_hz, flbl in ((10, "10"), (40, "40"), (160, "160"), (640, "640"), (2500, "2.5k"), (10000, "10k"), (40000, "40k")):
            fx = hz_to_x(f_hz)
            c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
            c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

        # Read all 6 band gains
        b_dbs = [(self._norm(self._get_zctrl(k), 0.5) - 0.5) * 20.0 for k, _, _, _ in BANDS]
        air_db = self._norm(self._get_zctrl("gain_high"), 0.0) * 10.0
        air_hz = AIR_FREQS[air_idx][1]

        # Compute combined EQ curve + Air Band contribution
        pts, pts_air = [], []
        poly = [gx0, mid_y]
        for i in range(81):
            t = i / 80.0
            f = f_min * ((f_max / f_min) ** t)
            db = 0.0
            for idx, (_, _, fc, _) in enumerate(BANDS):
                oct_d = math.log2(max(1e-4, f / fc))
                if idx == 0:  # 10 Hz sub shelf
                    db += b_dbs[idx] / (1.0 + math.exp(oct_d * 1.8))
                else:
                    db += b_dbs[idx] * math.exp(-(oct_d ** 2) / 1.45)
            # Air Band smooth high shelf
            oct_a = math.log2(max(1e-4, f / (air_hz * 0.55)))
            a_contrib = air_db / (1.0 + math.exp(-oct_a * 2.0))
            db_tot = max(-12.0, min(12.0, db + a_contrib))
            px = gx0 + t * gw
            py = db_to_y(db_tot)
            pts.extend([px, py])
            poly.extend([px, py])
            pts_air.extend([px, db_to_y(a_contrib)])
        poly.extend([gx1, mid_y])

        c.create_polygon(poly, fill="#192c3e", outline="")
        if air_db > 0.2:
            c.create_line(pts_air, fill=COL_AIR, width=1.6, dash=(3, 3))
        c.create_line(pts, fill="#74c0fc", width=2.8)

        # 6 draggable EQ nodes (5 bipolar bands + Air Band boost-only)
        node_list = []
        for idx, (k, lbl, fc, col) in enumerate(BANDS):
            nx = hz_to_x(fc)
            ny = db_to_y(b_dbs[idx])
            c.create_line(nx, mid_y, nx, ny, fill=col, width=1.8)
            c.create_oval(nx - 10, ny - 10, nx + 10, ny + 10, fill=col, outline="#ffffff", width=2)
            node_list.append({"key": k, "x": nx, "y": ny, "bipolar": True})

        ax = hz_to_x(air_hz)
        ay = db_to_y(air_db)
        c.create_line(ax, mid_y, ax, ay, fill=COL_AIR, width=2.0)
        c.create_oval(ax - 11, ay - 11, ax + 11, ay + 11, fill=COL_AIR, outline="#ffffff", width=2)
        c.create_text(ax, ay, text="A", fill="#0d0e12", font=self._font(self._fs(0.74), bold=True))
        node_list.append({"key": "gain_high", "x": ax, "y": ay, "bipolar": False})

        self.hitboxes.append((pad, vy0, w - pad, vy1, "eq_nodes", {
            "gy0": gy0, "gy1": gy1, "mid_y": mid_y, "gh": gh, "nodes": node_list,
        }))

        # Bottom 2x2 encoder-bound parameter boxes
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
                if kind == "toggle":
                    z = self._get_zctrl(payload)
                    if z is not None:
                        z.set_value(0.0 if self._raw(z) >= 0.5 else 1.0, send=True)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "set_norm":
                    k, nv = payload
                    self._set_norm(self._get_zctrl(k), nv)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "eq_nodes":
                    best = min(payload["nodes"], key=lambda nd: abs(event.x - nd["x"]) + 0.35 * abs(event.y - nd["y"]))
                    k = best["key"]
                    tid = ("eq_node", k)
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        z = self._get_zctrl(k)
                        if z is not None:
                            z.set_value(z.value_default, send=True)
                        self.last_snapshot = None
                        self._draw()
                        return
                    self.last_tap = (tid, now)
                    self.drag_target = ("eq_node", {
                        "key": k, "bipolar": best["bipolar"],
                        "mid_y": payload["mid_y"], "gh": payload["gh"],
                    })
                    self._apply_drag(event.x, event.y)
                    return
                if kind == "hfader":
                    tid = ("hfader", payload["key"])
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        z = self._get_zctrl(payload["key"])
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
        elif kind == "eq_node":
            db = ((p["mid_y"] - y) / max(1.0, p["gh"] * 0.48)) * 12.5
            if p["bipolar"]:
                n = max(0.0, min(1.0, 0.5 + db / 20.0))
            else:
                n = max(0.0, min(1.0, db / 10.0))
            self._set_norm(self._get_zctrl(p["key"]), n)
        self.last_snapshot = None
        self._draw()
