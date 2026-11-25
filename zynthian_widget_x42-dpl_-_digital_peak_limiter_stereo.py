#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# x42-dpl (Digital Peak Limiter Stereo) Widget for Zynthian (V5 800x480)
# Part of UI Synths (zynthian-ui-synths)
#
# 2 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Limiter | Scope   + 4x TRUE PEAK + ON/BYP
#
# Features:
#   - Live LV2 OutputPort telemetry (`level` -10..+20 dB relative to ceiling,
#     `latency` samples) with peak-hold & DSP transient preview while offline.
#   - Limiter tab: Brickwall transfer curve (-24..+12 dB) with shaded ceiling
#     clipping zone, draggable 2D Input Gain x Ceiling handle, and mastering
#     Peak / GR dual meter (0..-20 dB top-down GR + peak hold).
#   - Scope tab: Live 2.0s Peak & GR rolling oscilloscope + interactive 2D
#     Release (1ms..1.0s log) x Ceiling (-10..0 dB) pad.
#   - Unified Design System: >=34px touch targets, 6px gaps, double-tap reset.
# ******************************************************************************

from collections import deque
import logging
import math
import re
import time
import tkinter
import tkinter.font

from zyngui import zynthian_gui_config
from zyngui import zynthian_widget_base

MULTI_INSTANCE = True
UPDATE_PERIOD = 0.06  # ~16 fps cap
DOUBLE_TAP_S = 0.35

COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"
COL_LIVE = "#51cf66"
COL_SIM = "#ffd43b"
COL_TP = "#4dabf7"
COL_GR = "#ff922b"
COL_LIMIT = "#ff6b6b"
COL_CLIP = "#ff4d4f"

TABS = ["Limiter", "Scope"]
TAB_ACCENTS = {
    "Limiter": "#ff6b6b",
    "Scope":   "#ffd43b",
}

LOG_KEYS = {"release"}
DEFAULTS = {
    "enable": 1.0,
    "gain": 0.0,
    "threshold": -1.0,
    "release": 0.01,
    "truepeak": 0.0,
}

SCOPE_SAMPLES = 36
LIVE_HOLD_S = 2.0
DRAG_SIM_HOLD_S = 2.8
PEAK_HOLD_S = 1.15
PEAK_DECAY_DB_S = 16.0
CHANNEL_LABEL = "STEREO"


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_time_s(sec):
    ms = float(sec) * 1000.0
    if ms >= 1000.0:
        return f"{sec:.2f}s"
    if ms >= 10.0:
        return f"{ms:.0f}ms"
    return f"{ms:.1f}ms"


def dpl_transfer_db(in_db, gain_db, ceil_db):
    """Brickwall digital peak limiter transfer curve.

    Returns (out_db, gr_db) where gr_db <= 0.0.
    """
    driven = float(in_db) + float(gain_db)
    ceil_db = float(ceil_db)
    if driven > ceil_db:
        return ceil_db, ceil_db - driven
    return driven, 0.0


class zynthian_widget_x42_dpl_stereo(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Limiter"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}
        self._tk_font_cache = {}

        # Live telemetry state
        self._level_db = -10.0      # -10..+20 dB relative to ceiling
        self._level_peak_db = -10.0
        self._level_peak_ts = 0.0
        self._gr_db = 0.0           # <= 0.0 (0..-20 dB)
        self._gr_peak_db = 0.0      # <= 0.0
        self._gr_peak_ts = 0.0
        self._latency_smp = 0
        self._last_live_ts = 0.0
        self._last_interact_ts = 0.0
        self._last_tick = time.monotonic()
        self._history = deque([(-10.0, 0.0)] * SCOPE_SAMPLES, maxlen=SCOPE_SAMPLES)

        self.widget_canvas = tkinter.Canvas(self, highlightthickness=0, relief="flat", bg=COL_BG)
        self.widget_canvas.grid(sticky="news")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.widget_canvas.bind("<ButtonPress-1>", self._on_press)
        self.widget_canvas.bind("<B1-Motion>", self._on_drag)
        self.widget_canvas.bind("<ButtonRelease-1>", self._on_release)

    # --------------------------------------------------------------------------
    # Processor & Resilient Controller Resolver
    # --------------------------------------------------------------------------
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
        if not self.processor:
            return None
        z = self.processor.controllers_dict.get(sym)
        if z is not None:
            return z
        return self._ctrl_index.get(_norm_key(sym))

    # --------------------------------------------------------------------------
    # Live LV2 Monitor Polling
    # --------------------------------------------------------------------------
    def get_monitors(self):
        try:
            if self.processor and getattr(self.processor, "engine", None):
                fn = getattr(self.processor.engine, "get_monitors_dict", None)
                if callable(fn):
                    self.monitors = fn()
                    return
        except Exception:
            pass
        self.monitors = {}

    def _get_mon(self, key, default=None):
        mons = self.monitors
        if not isinstance(mons, dict) or not mons:
            return default
        if key in mons:
            try:
                return float(mons[key])
            except Exception:
                return default
        nk = _norm_key(key)
        for mk, mv in mons.items():
            nmk = _norm_key(mk)
            if nmk == nk or nmk.endswith("_" + nk):
                try:
                    return float(mv)
                except Exception:
                    return default
        return default

    def _update_telemetry(self, now):
        dt = max(0.001, min(0.25, now - self._last_tick))
        self._last_tick = now

        lvl = self._get_mon("level")
        lat = self._get_mon("latency")
        if lat is not None and lat >= 0.0:
            self._latency_smp = int(round(lat))

        if lvl is not None and lvl > -9.8:
            self._last_live_ts = now

        is_live = (now - self._last_live_ts) < LIVE_HOLD_S
        self._level_db = max(-10.0, min(20.0, lvl)) if lvl is not None else -10.0
        self._gr_db = -self._level_db if self._level_db > 0.0 else 0.0

        # Peak hold for signal level
        if self._level_db >= self._level_peak_db:
            self._level_peak_db = self._level_db
            self._level_peak_ts = now
        elif (now - self._level_peak_ts) > PEAK_HOLD_S:
            self._level_peak_db = max(self._level_db, self._level_peak_db - PEAK_DECAY_DB_S * dt)

        # Peak hold for GR (most negative)
        if self._gr_db <= self._gr_peak_db:
            self._gr_peak_db = self._gr_db
            self._gr_peak_ts = now
        elif (now - self._gr_peak_ts) > PEAK_HOLD_S:
            self._gr_peak_db = min(self._gr_db, self._gr_peak_db + PEAK_DECAY_DB_S * dt)

        self._history.append((self._level_db, self._gr_db))
        return is_live

    # --------------------------------------------------------------------------
    # Dynamic 4-Encoder Page Mapping
    # --------------------------------------------------------------------------
    def _tab_items(self, tab):
        if tab == "Limiter":
            return [
                ("gain",      "In Gain"),
                ("threshold", "Ceiling"),
                ("release",   "Release"),
                ("truepeak",  "TruePeak"),
            ]
        return [
            ("release",   "Release"),
            ("threshold", "Ceiling"),
            ("gain",      "In Gain"),
            ("truepeak",  "TruePeak"),
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
            logging.debug(f"x42-dpl sync error: {e}")

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

    # --------------------------------------------------------------------------
    # Value Helpers (Log-Aware)
    # --------------------------------------------------------------------------
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
            if _norm_key(key) in LOG_KEYS and vmin > 0.0:
                return max(0.0, min(1.0, math.log(max(vmin, v) / vmin) / math.log(vmax / vmin)))
            return max(0.0, min(1.0, (v - vmin) / (vmax - vmin)))
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
        if _norm_key(key) in LOG_KEYS and vmin > 0.0:
            v = vmin * ((vmax / vmin) ** n)
        else:
            v = vmin + n * (vmax - vmin)
        if _norm_key(key) in ("truepeak", "enable"):
            v = 1.0 if n >= 0.5 else 0.0
        z.set_value(max(vmin, min(vmax, v)), send=True)

    @staticmethod
    def _reset_zctrl(z, key=""):
        if z is None:
            return
        nk = _norm_key(key)
        d = getattr(z, "value_default", None)
        if d is None:
            d = DEFAULTS.get(nk)
        if d is None:
            d = 0.5 * (float(z.value_min) + float(z.value_max))
        z.set_value(max(float(z.value_min), min(float(z.value_max), float(d))), send=True)

    def _fmt_param(self, key, z):
        nk = _norm_key(key)
        v = self._raw(z, DEFAULTS.get(nk, 0.0))
        if nk == "gain":
            return f"{v:+.1f}dB"
        if nk == "threshold":
            return f"{v:.1f}dB"
        if nk == "release":
            return fmt_time_s(v)
        if nk == "truepeak":
            return "4x ON" if v >= 0.5 else "OFF"
        return f"{v:.2f}"

    # --------------------------------------------------------------------------
    # Fonts & Drawing Primitives
    # --------------------------------------------------------------------------
    def _font(self, size, bold=False):
        key = (max(8, int(size)), bool(bold))
        f = self._font_cache.get(key)
        if f is None:
            f = (zynthian_gui_config.font_family, key[0], "bold" if bold else "normal")
            self._font_cache[key] = f
        return f

    def _fit_font(self, text, max_w, max_sz, bold=False, min_sz=8):
        text = str(text)
        max_w = max(12, int(max_w))
        for sz in range(max(min_sz, int(max_sz)), min_sz - 1, -1):
            k = (sz, bool(bold))
            tf = self._tk_font_cache.get(k)
            if tf is None:
                try:
                    tf = tkinter.font.Font(
                        family=zynthian_gui_config.font_family,
                        size=sz,
                        weight="bold" if bold else "normal",
                    )
                except Exception:
                    return self._font(sz, bold)
                self._tk_font_cache[k] = tf
            if tf.measure(text) <= max_w:
                return self._font(sz, bold)
        return self._font(min_sz, bold)

    def _draw_pill(self, x1, y1, x2, y2, label, active, accent, tag, data=None, bold=True):
        c = self.widget_canvas
        fill = accent if active else COL_PANEL
        fg = "#111217" if active else COL_TEXT
        out = accent if active else COL_BORDER
        c.create_rectangle(x1, y1, x2, y2, fill=fill, outline=out, width=1)
        fnt = self._fit_font(label, (x2 - x1) - 8, max(9, min(13, int((y2 - y1) * 0.40))), bold=bold)
        c.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=label, fill=fg, font=fnt)
        self.hitboxes.append((x1, y1, x2, y2, tag, data))

    def _draw_param_box(self, x1, y1, x2, y2, key, label, accent):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z, key, 0.0)
        val_txt = self._fmt_param(key, z)
        nk = _norm_key(key)
        c.create_rectangle(x1, y1, x2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 6
        bar_h = max(7, int((y2 - y1) * 0.22))
        by2 = y2 - pad
        by1 = by2 - bar_h
        bx1, bx2 = x1 + pad, x2 - pad
        c.create_rectangle(bx1, by1, bx2, by2, fill=COL_TRACK, outline="")
        if nk == "gain" and z is not None:
            z0 = (0.0 - float(z.value_min)) / max(1e-6, float(z.value_max) - float(z.value_min))
            zx = bx1 + (bx2 - bx1) * max(0.0, min(1.0, z0))
            vx = bx1 + (bx2 - bx1) * n
            c.create_rectangle(min(zx, vx), by1, max(zx, vx), by2, fill=accent, outline="")
            c.create_line(zx, by1 - 2, zx, by2 + 2, fill=COL_DIM, width=1)
        elif nk == "truepeak":
            if n >= 0.5:
                c.create_rectangle(bx1, by1, bx2, by2, fill=COL_TP, outline="")
        elif n > 0.005:
            c.create_rectangle(bx1, by1, bx1 + (bx2 - bx1) * n, by2, fill=accent, outline="")
        top_y = y1 + (by1 - y1) * 0.48
        w_in = max(20, (x2 - x1) - 12)
        c.create_text(x1 + 6, top_y, text=label, anchor="w", fill=COL_DIM,
                      font=self._fit_font(label, w_in * 0.52, 11, bold=False))
        c.create_text(x2 - 6, top_y, text=val_txt, anchor="e",
                      fill=COL_TP if (nk == "truepeak" and n >= 0.5) else COL_TEXT,
                      font=self._fit_font(val_txt, w_in * 0.52, 12, bold=True))
        if nk == "truepeak":
            self.hitboxes.append((x1, y1, x2, y2, "toggle", "truepeak"))
        else:
            self.hitboxes.append((x1, y1, x2, y2, "param", (key, x1 + pad, x2 - pad)))

    # --------------------------------------------------------------------------
    # Lifecycle & Throttled Update
    # --------------------------------------------------------------------------
    def on_size(self, event):
        if super().on_size(event):
            self.last_snapshot = None
            self._draw()

    def _snapshot(self, is_live):
        vals = []
        for k in ("enable", "gain", "threshold", "release", "truepeak"):
            z = self._get_zctrl(k)
            vals.append(round(self._raw(z, 0.0), 4) if z else None)
        mon = (
            round(self._level_db, 1),
            round(self._level_peak_db, 1),
            round(self._gr_db, 1),
            round(self._gr_peak_db, 1),
            self._latency_smp,
            is_live,
        )
        return (self.active_tab, self.width, self.height, tuple(vals), mon)

    def update(self):
        now = time.monotonic()
        if now < self.next_update:
            return
        self.next_update = now + UPDATE_PERIOD
        super().update()
        self._follow_page()
        is_live = self._update_telemetry(now)
        snap = self._snapshot(is_live)
        if snap != self.last_snapshot or self.drag_target is not None:
            self.last_snapshot = snap
            self._draw(is_live=is_live)

    def refresh_gui(self):
        self.last_snapshot = None
        self._draw()

    # --------------------------------------------------------------------------
    # Main Render
    # --------------------------------------------------------------------------
    def _draw(self, is_live=None):
        c = self.widget_canvas
        w = max(240, int(self.width or c.winfo_width() or 640))
        h = max(200, int(self.height or c.winfo_height() or 440))
        now = time.monotonic()
        if is_live is None:
            is_live = (now - self._last_live_ts) < LIVE_HOLD_S

        c.delete("all")
        self.hitboxes = []

        pad = 6
        gap = 6
        hdr_h = max(36, min(46, int(h * 0.11)))
        accent = TAB_ACCENTS.get(self.active_tab, "#ff6b6b")

        en = self._raw(self._get_zctrl("enable"), 1.0) >= 0.5
        tp = self._raw(self._get_zctrl("truepeak"), 0.0) >= 0.5
        byp_w = max(68, int(w * 0.14))
        tp_w = max(84, int(w * 0.17))
        tabs_w = w - 2 * pad - byp_w - tp_w - 2 * gap
        tw = (tabs_w - gap) / len(TABS)
        for i, t in enumerate(TABS):
            tx1 = pad + i * (tw + gap)
            self._draw_pill(tx1, pad, tx1 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        tx1 = w - pad - byp_w - gap - tp_w
        self._draw_pill(tx1, pad, tx1 + tp_w, pad + hdr_h, "4x TP" if tp else "1x PEAK",
                        tp, COL_TP, "toggle", "truepeak")
        bx1 = w - pad - byp_w
        self._draw_pill(bx1, pad, w - pad, pad + hdr_h, "ON ●" if en else "BYP",
                        en, "#40c057" if en else "#ff6b6b", "toggle", "enable")

        top_y = pad + hdr_h + gap
        pbox_h = max(44, min(58, int(h * 0.14)))
        vis_y2 = h - pad - pbox_h - gap

        if self.active_tab == "Limiter":
            self._draw_limiter_view(pad, top_y, w - pad, vis_y2, accent, en, tp, is_live, now)
        else:
            self._draw_scope_view(pad, top_y, w - pad, vis_y2, accent, en, is_live, now)

        items = self._tab_items(self.active_tab)
        bw = (w - 2 * pad - 3 * gap) / 4.0
        by1 = h - pad - pbox_h
        by2 = h - pad
        for i, (k, lbl) in enumerate(items):
            px1 = pad + i * (bw + gap)
            self._draw_param_box(px1, by1, px1 + bw, by2, k, lbl, accent)

    # --------------------------------------------------------------------------
    # Tab 1: Limiter — Brickwall Transfer Curve + Mastering Peak/GR Meter
    # --------------------------------------------------------------------------
    def _draw_limiter_view(self, x1, y1, x2, y2, accent, en, tp, is_live, now):
        c = self.widget_canvas
        gap = 6
        meter_w = max(100, min(140, int((x2 - x1) * 0.24)))
        gx2 = x2 - meter_w - gap

        c.create_rectangle(x1, y1, gx2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        ig = self._raw(self._get_zctrl("gain"), 0.0)
        ceil_db = self._raw(self._get_zctrl("threshold"), -1.0)

        px1, py1 = x1 + 30, y1 + 26
        px2, py2 = gx2 - 12, y2 - 20
        pw = max(40, px2 - px1)
        ph = max(40, py2 - py1)

        # Input axis: -24..+12 dB (36 dB span); Output axis: -24..0 dB (24 dB span)
        def in_to_x(db):
            return px1 + ((max(-24.0, min(12.0, db)) + 24.0) / 36.0) * pw

        def out_to_y(db):
            return py2 - ((max(-24.0, min(0.0, db)) + 24.0) / 24.0) * ph

        # Shaded brickwall forbidden zone above ceiling
        cy = out_to_y(ceil_db)
        if cy > py1:
            c.create_rectangle(px1, py1, px2, cy, fill="#2c1d22", outline="")

        # Grid
        for db in (-18, -12, -6, 0, 6):
            gx = in_to_x(db)
            c.create_line(gx, py1, gx, py2, fill="#3c4054" if db == 0 else COL_GRID, width=1)
            c.create_text(gx, py2 + 9, text=f"{db:+d}" if db > 0 else f"{db}",
                          anchor="center", fill=COL_DIM, font=self._font(8))
        for db in (-18, -12, -6, 0):
            gy = out_to_y(db)
            c.create_line(px1, gy, px2, gy, fill=COL_GRID, width=1)
            c.create_text(px1 - 4, gy, text=f"{db}", anchor="e", fill=COL_DIM, font=self._font(8))

        # Unity 1:1 line (-24..0 dB)
        c.create_line(in_to_x(-24.0), out_to_y(-24.0), in_to_x(0.0), out_to_y(0.0),
                      fill="#383b4d", dash=(4, 4), width=1)

        # Brickwall ceiling horizontal line
        c.create_line(px1, cy, px2, cy, fill=COL_LIMIT, dash=(4, 3), width=1.5)
        c.create_text(px1 + 5, cy - 7, text=f"CEIL {ceil_db:.1f} dB{'TP' if tp else 'FS'}",
                      anchor="w", fill=COL_LIMIT, font=self._font(8, bold=True))

        # Brickwall transfer curve
        pts = []
        steps = 48
        for i in range(steps + 1):
            idb = -24.0 + (36.0 * i / steps)
            odb, _ = dpl_transfer_db(idb, ig, ceil_db)
            pts.extend([in_to_x(idb), out_to_y(odb)])
        if len(pts) >= 4:
            c.create_line(*pts, fill=accent if en else COL_DIM, width=2.5)

        # Live operating point (or simulated during drag)
        sim_active = (not is_live) and ((now - self._last_interact_ts) < DRAG_SIM_HOLD_S)
        if is_live and self._level_db > -9.9:
            # level_db = driven_peak - ceil_db => input = ceil_db + level_db - ig
            op_in = ceil_db + self._level_db - ig
            op_out = min(ceil_db, ceil_db + self._level_db)
            ox, oy = in_to_x(op_in), out_to_y(op_out)
            dot_col = COL_CLIP if self._level_db > 0.1 else COL_LIVE
            c.create_oval(ox - 5, oy - 5, ox + 5, oy + 5, fill=dot_col, outline="#ffffff", width=1.5)
        elif sim_active:
            sim_in = -6.0 + 7.5 * math.sin(now * 4.2)
            sim_out, _ = dpl_transfer_db(sim_in, ig, ceil_db)
            ox, oy = in_to_x(sim_in), out_to_y(sim_out)
            c.create_oval(ox - 4, oy - 4, ox + 4, oy + 4, fill=COL_SIM, outline="#111217", width=1)

        # Interactive 2D Knee Handle (where signal hits ceiling: in = ceil_db - ig)
        knee_in = max(-24.0, min(12.0, ceil_db - ig))
        kx = in_to_x(knee_in)
        ky = cy
        c.create_oval(kx - 10, ky - 10, kx + 10, ky + 10, fill=accent, outline="#ffffff", width=2)
        c.create_text(kx, ky + 16, text="DRIVE × CEIL", fill=COL_TEXT, font=self._font(8, bold=True))

        self.hitboxes.append((px1, py1, px2, py2, "dpl_2d", (px1, py1, px2, py2)))

        # Header overlay inside plot
        lat_txt = f" · {self._latency_smp}smp" if self._latency_smp > 0 else ""
        title = f"x42-DPL {CHANNEL_LABEL}{' · 4x TruePeak' if tp else ''}{lat_txt}"
        badge = "LIMIT" if (is_live and self._gr_db < -0.1) else ("LIVE" if is_live else ("SIM" if sim_active else "IDLE"))
        bcol = COL_CLIP if (is_live and self._gr_db < -0.1) else (COL_LIVE if is_live else (COL_SIM if sim_active else COL_DIM))
        c.create_text(x1 + 10, y1 + 13, text=title, anchor="w", fill=COL_TEXT,
                      font=self._fit_font(title, (gx2 - x1) - 65, 11, bold=True))
        c.create_text(gx2 - 10, y1 + 13, text=badge, anchor="e", fill=bcol, font=self._font(9, bold=True))

        # --- Right Panel: Dual Vertical Mastering Meter (PEAK & GR) ---
        mx1 = gx2 + gap
        c.create_rectangle(mx1, y1, x2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        c.create_text((mx1 + x2) / 2, y1 + 13, text="PEAK / GR", fill=COL_DIM, font=self._font(9, bold=True))

        mpad = 8
        my1 = y1 + 26
        my2 = y2 - 22
        mh = max(30, my2 - my1)
        mw_each = max(18, int((x2 - mx1 - 3 * mpad) / 2))

        # Bar 1: Signal Level relative to ceiling (-10..+20 dB; 0 dB at 1/3 height)
        p1 = mx1 + mpad
        p2 = p1 + mw_each
        c.create_rectangle(p1, my1, p2, my2, fill=COL_TRACK, outline=COL_BORDER, width=1)

        def lvl_to_y(ldb):
            return my2 - ((max(-10.0, min(20.0, ldb)) + 10.0) / 30.0) * mh

        y0 = lvl_to_y(0.0)
        c.create_line(p1, y0, p2, y0, fill=COL_LIMIT, width=1)

        disp_lvl = self._level_db
        disp_gr = self._gr_db
        if not is_live and sim_active:
            _, sgr = dpl_transfer_db(-6.0 + 7.5 * math.sin(now * 4.2), ig, ceil_db)
            disp_gr = max(-20.0, sgr)
            disp_lvl = -disp_gr if disp_gr < 0.0 else -3.0

        if disp_lvl > -9.9:
            ly = lvl_to_y(disp_lvl)
            lcol = COL_CLIP if disp_lvl > 0.05 else COL_LIVE
            c.create_rectangle(p1 + 1, ly, p2 - 1, my2 - 1, fill=lcol, outline="")
        if self._level_peak_db > -9.8:
            py_pk = lvl_to_y(self._level_peak_db)
            c.create_line(p1 + 1, py_pk, p2 - 1, py_pk, fill="#ffffff", width=2)
        c.create_text((p1 + p2) / 2, y2 - 11,
                      text=f"{disp_lvl:+.1f}" if disp_lvl > -9.8 else "-∞",
                      fill=COL_CLIP if disp_lvl > 0.1 else COL_TEXT,
                      font=self._font(9, bold=True))

        # Bar 2: Top-down Brickwall GR (0..-20 dB)
        g1 = p2 + mpad
        g2 = x2 - mpad
        c.create_rectangle(g1, my1, g2, my2, fill=COL_TRACK, outline=COL_BORDER, width=1)
        gr_n = max(0.0, min(1.0, -disp_gr / 20.0))
        if gr_n > 0.005:
            gy_bot = my1 + gr_n * mh
            gcol = COL_CLIP if disp_gr < -6.0 else COL_GR
            c.create_rectangle(g1 + 1, my1 + 1, g2 - 1, gy_bot, fill=gcol, outline="")
        gr_pk_n = max(0.0, min(1.0, -self._gr_peak_db / 20.0))
        if gr_pk_n > 0.01:
            gy_pk = my1 + gr_pk_n * mh
            c.create_line(g1 + 1, gy_pk, g2 - 1, gy_pk, fill="#ffffff", width=2)
        c.create_text((g1 + g2) / 2, y2 - 11,
                      text=f"{disp_gr:.1f}" if disp_gr < -0.05 else "0.0",
                      fill=COL_LIMIT if disp_gr < -0.1 else COL_TEXT,
                      font=self._font(9, bold=True))

    # --------------------------------------------------------------------------
    # Tab 2: Scope — Live 2.0s Peak/GR Oscilloscope + 2D Release x Ceiling Pad
    # --------------------------------------------------------------------------
    def _draw_scope_view(self, x1, y1, x2, y2, accent, en, is_live, now):
        c = self.widget_canvas
        gap = 6
        pad_w = max(145, int((x2 - x1) * 0.38))
        sx2 = x2 - pad_w - gap

        c.create_rectangle(x1, y1, sx2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        ceil_db = self._raw(self._get_zctrl("threshold"), -1.0)
        rel = self._raw(self._get_zctrl("release"), 0.01)
        ig = self._raw(self._get_zctrl("gain"), 0.0)

        px1, py1 = x1 + 10, y1 + 26
        px2, py2 = sx2 - 10, y2 - 10
        pw = max(40, px2 - px1)
        ph = max(40, py2 - py1)

        for frac in (0.25, 0.5, 0.75):
            gy = py1 + ph * frac
            c.create_line(px1, gy, px2, gy, fill=COL_GRID, width=1)

        # 0 dB Ceiling line
        y_ceil = py1 + ph * 0.35
        c.create_line(px1, y_ceil, px2, y_ceil, fill=COL_LIMIT, dash=(3, 3), width=1)
        c.create_text(px2 - 4, y_ceil - 7, text=f"CEIL {ceil_db:.1f}dB", anchor="e", fill=COL_LIMIT, font=self._font(8))

        if is_live:
            lvl_pts = []
            gr_pts = []
            hist = list(self._history)
            n_s = max(2, len(hist))
            for i, (ldb, gr_db) in enumerate(hist):
                sx = px1 + (pw * i / (n_s - 1))
                # Map -10..+20 dB
                ly = py2 - ((max(-10.0, min(20.0, ldb)) + 10.0) / 30.0) * ph
                # Map GR 0..-20 dB top-down from y_ceil
                gy = y_ceil + (min(20.0, -gr_db) / 20.0) * (py2 - y_ceil)
                lvl_pts.extend([sx, ly])
                gr_pts.extend([sx, gy])
            if len(lvl_pts) >= 4:
                c.create_line(*lvl_pts, fill=COL_TP, width=2, smooth=True)
            if len(gr_pts) >= 4:
                c.create_line(*gr_pts, fill=COL_LIMIT if en else COL_DIM, width=2.5, smooth=True)
            mode_lbl, mode_col = "LIVE 2.0s", COL_LIVE
        else:
            # Predictive brickwall transient-catch & release recovery curve
            steps = 56
            env_pts = []
            pk_pts = []
            t_win = 1.2
            dt = t_win / steps
            cur_gr = 0.0
            drive_depth = max(0.25, min(0.95, (ig - ceil_db + 6.0) / 28.0))
            for i in range(steps + 1):
                t = i * dt
                spike = 1.0 if (0.14 <= t <= 0.22 or 0.60 <= t <= 0.66) else 0.0
                if spike > 0.5:
                    cur_gr = drive_depth
                else:
                    tau = max(0.004, rel)
                    cur_gr *= math.exp(-dt / tau)
                sx = px1 + (pw * i / steps)
                pk_pts.extend([sx, py2 - (0.12 + 0.72 * spike) * ph])
                env_pts.extend([sx, y_ceil + cur_gr * (py2 - y_ceil - 4)])
            c.create_line(*pk_pts, fill="#383b4d", width=1.5)
            c.create_line(*env_pts, fill=accent if en else COL_DIM, width=2.5, smooth=True)
            mode_lbl, mode_col = "SIM ENV", COL_SIM

        c.create_text(x1 + 10, y1 + 13, text="Peak & GR Limiting Scope", anchor="w",
                      fill=COL_TEXT, font=self._fit_font("Peak & GR Limiting Scope", (sx2 - x1) - 80, 11, bold=True))
        c.create_text(sx2 - 10, y1 + 13, text=mode_lbl, anchor="e", fill=mode_col, font=self._font(9, bold=True))

        # --- Right: 2D Release x Ceiling Pad ---
        ax1 = sx2 + gap
        c.create_rectangle(ax1, y1, x2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        c.create_text(ax1 + 10, y1 + 13, text="Release × Ceiling (2D)", anchor="w",
                      fill=COL_TEXT, font=self._fit_font("Release × Ceiling (2D)", (x2 - ax1) - 20, 11, bold=True))

        apx1, apy1 = ax1 + 12, y1 + 28
        apx2, apy2 = x2 - 12, y2 - 20
        for frac in (0.25, 0.5, 0.75):
            c.create_line(apx1 + (apx2 - apx1) * frac, apy1, apx1 + (apx2 - apx1) * frac, apy2, fill=COL_GRID)
            c.create_line(apx1, apy1 + (apy2 - apy1) * frac, apx2, apy1 + (apy2 - apy1) * frac, fill=COL_GRID)

        rn = self._norm(self._get_zctrl("release"), "release", 0.3)
        cn = self._norm(self._get_zctrl("threshold"), "threshold", 0.9)
        nx = apx1 + rn * (apx2 - apx1)
        ny = apy2 - cn * (apy2 - apy1)

        c.create_line(nx, apy1, nx, apy2, fill=accent, dash=(2, 3), width=1)
        c.create_line(apx1, ny, apx2, ny, fill=accent, dash=(2, 3), width=1)
        c.create_oval(nx - 10, ny - 10, nx + 10, ny + 10, fill=accent, outline="#ffffff", width=2)
        c.create_text(apx1, y2 - 9, text=f"Rel {fmt_time_s(rel)}", anchor="w", fill=COL_DIM, font=self._font(9))
        c.create_text(apx2, y2 - 9, text=f"Ceil {ceil_db:.1f}dB", anchor="e", fill=COL_DIM, font=self._font(9))
        self.hitboxes.append((apx1, apy1, apx2, apy2, "scope_2d", (apx1, apy1, apx2, apy2)))

    # --------------------------------------------------------------------------
    # Touch Interaction (Drag + Double-Tap Reset)
    # --------------------------------------------------------------------------
    def _hit(self, x, y):
        for x1, y1, x2, y2, tag, data in self.hitboxes:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return tag, data
        return None, None

    def _on_press(self, event):
        tag, data = self._hit(event.x, event.y)
        if tag is None:
            return
        now = time.monotonic()
        self._last_interact_ts = now

        if tag == "tab":
            if data != self.active_tab:
                self.active_tab = data
                self._select_page(data)
                self.last_snapshot = None
                self._draw()
            return

        if tag == "toggle":
            z = self._get_zctrl(data)
            if z is not None:
                cur = self._raw(z, 0.0)
                z.set_value(0.0 if cur >= 0.5 else 1.0, send=True)
                self.last_snapshot = None
                self._draw()
            return

        tap_id = (tag, data[0] if isinstance(data, tuple) else data)
        if self.last_tap[0] == tap_id and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
            self.last_tap = (None, 0.0)
            self.drag_target = None
            if tag == "param":
                self._reset_zctrl(self._get_zctrl(data[0]), data[0])
            elif tag == "dpl_2d":
                self._reset_zctrl(self._get_zctrl("gain"), "gain")
                self._reset_zctrl(self._get_zctrl("threshold"), "threshold")
            elif tag == "scope_2d":
                self._reset_zctrl(self._get_zctrl("release"), "release")
                self._reset_zctrl(self._get_zctrl("threshold"), "threshold")
            self.last_snapshot = None
            self._draw()
            return

        self.last_tap = (tap_id, now)
        self.drag_target = (tag, data)
        self._apply_drag(event.x, event.y)

    def _on_drag(self, event):
        if self.drag_target is None:
            return
        self._last_interact_ts = time.monotonic()
        self._apply_drag(event.x, event.y)

    def _on_release(self, _event):
        self.drag_target = None

    def _apply_drag(self, x, y):
        tag, data = self.drag_target
        if tag == "param":
            key, x1, x2 = data
            n = (x - x1) / max(1.0, float(x2 - x1))
            self._set_norm(self._get_zctrl(key), n, key)
        elif tag == "dpl_2d":
            x1, y1, x2, y2 = data
            # Dragging X left/right adjusts Input Gain (-10..+30 dB); Y adjusts Ceiling (-10..0 dB)
            nx = max(0.0, min(1.0, (x - x1) / max(1.0, float(x2 - x1))))
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            self._set_norm(self._get_zctrl("gain"), nx, "gain")
            # Map upper half of transfer plot smoothly to -10..0 dB ceiling
            z_thr = self._get_zctrl("threshold")
            if z_thr is not None:
                # Map full Y cleanly to threshold -10..0 dB for maximum finger precision
                self._set_norm(z_thr, ny, "threshold")
        elif tag == "scope_2d":
            x1, y1, x2, y2 = data
            nx = max(0.0, min(1.0, (x - x1) / max(1.0, float(x2 - x1))))
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            self._set_norm(self._get_zctrl("release"), nx, "release")
            self._set_norm(self._get_zctrl("threshold"), ny, "threshold")
        self.last_snapshot = None
        self._draw()


# Zynthian loader alias for hyphenated plugin filename
globals()["zynthian_widget_x42-dpl_-_digital_peak_limiter_stereo"] = zynthian_widget_x42_dpl_stereo
