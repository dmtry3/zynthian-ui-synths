#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# x42-comp (DARC Dynamic Compressor Mono) Widget for Zynthian (V5 800x480)
# Part of UI Synths (zynthian-ui-synths)
#
# 2 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Comp | Time   + HOLD + ON/BYP
#
# Features:
#   - Live LV2 OutputPort telemetry (rms, gain_min, gain_max) with peak-hold
#     and automatic DSP predictive preview while dragging offline.
#   - Authentic DARC auto-makeup transfer curve anchored at -10 dBFS/RMS
#     unity pivot, with dual 2D touch handles (Threshold x InGain & Ratio).
#   - Bipolar Gain Meter (-20..+40 dB) showing both auto-makeup boost and
#     dynamic gain reduction alongside RMS Input Meter (-60..0 dB).
#   - Time tab: live 2.0s RMS & Gain Envelope scope + interactive 2D
#     Attack (1..100ms log) x Release (30ms..3.0s log) pad.
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
COL_BOOST = "#4dabf7"
COL_GR = "#ff922b"
COL_GR_HI = "#ff6b6b"

TABS = ["Comp", "Time"]
TAB_ACCENTS = {
    "Comp": "#ff922b",
    "Time": "#51cf66",
}

LOG_KEYS = {"attack", "release"}
DEFAULTS = {
    "enable": 1.0,
    "hold": 0.0,
    "inputgain": 0.0,
    "threshold": -30.0,
    "ratio": 0.0,
    "attack": 0.01,
    "release": 0.30,
}

SCOPE_SAMPLES = 36
LIVE_HOLD_S = 2.0
DRAG_SIM_HOLD_S = 2.8
PEAK_HOLD_S = 1.15
PEAK_DECAY_DB_S = 16.0
CHANNEL_LABEL = "MONO"


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_time_s(sec):
    ms = float(sec) * 1000.0
    if ms >= 1000.0:
        return f"{sec:.2f}s"
    if ms >= 10.0:
        return f"{ms:.0f}ms"
    return f"{ms:.1f}ms"


def fmt_ratio(r_norm):
    r = max(0.0, min(1.0, float(r_norm)))
    if r >= 0.985:
        return "Lim"
    if r <= 0.005:
        return "1.0:1"
    eff = 1.0 / max(0.01, 1.0 - r)
    if eff >= 20.0:
        return f"{eff:.0f}:1"
    return f"{eff:.1f}:1"


def darc_transfer_db(in_db, thr_db, ratio_norm, in_gain_db=0.0):
    """Compute authentic x42-comp (DARC) static transfer curve.

    Input gain is applied before level detection. Above threshold, the slope is
    (1 - ratio_norm). Auto-makeup retains unity at -10 dBFS/RMS.
    Returns (out_db, net_gain_db).
    """
    r = max(0.0, min(1.0, float(ratio_norm)))
    x = float(in_db) + float(in_gain_db)
    makeup = r * max(0.0, -10.0 - float(thr_db))
    knee = 3.0
    diff = x - float(thr_db)
    if abs(diff) < knee:
        gr = -r * ((diff + knee) ** 2) / (4.0 * knee)
    elif diff > 0.0:
        gr = -r * diff
    else:
        gr = 0.0
    net_gain = max(-20.0, min(40.0, makeup + gr))
    return x + net_gain, net_gain


class zynthian_widget_x42_comp_mono(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Comp"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}
        self._tk_font_cache = {}

        # Telemetry & scope state
        self._rms_db = -80.0
        self._rms_peak_db = -80.0
        self._rms_peak_ts = 0.0
        self._gain_min_db = 0.0
        self._gain_max_db = 0.0
        self._gain_peak_db = 0.0
        self._gain_peak_ts = 0.0
        self._last_live_ts = 0.0
        self._last_interact_ts = 0.0
        self._last_tick = time.monotonic()
        self._history = deque([(-80.0, 0.0, 0.0)] * SCOPE_SAMPLES, maxlen=SCOPE_SAMPLES)

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
        if not self.processor:
            return None
        z = self.processor.controllers_dict.get(sym)
        if z is not None:
            return z
        return self._ctrl_index.get(_norm_key(sym))

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

        rms = self._get_mon("rms")
        gmin = self._get_mon("gain_min")
        gmax = self._get_mon("gain_max")

        if rms is not None and rms > -74.0:
            self._last_live_ts = now
        elif gmin is not None and abs(gmin) > 0.15:
            self._last_live_ts = now

        is_live = (now - self._last_live_ts) < LIVE_HOLD_S
        self._rms_db = max(-80.0, min(10.0, rms)) if rms is not None else -80.0
        self._gain_min_db = max(-20.0, min(40.0, gmin)) if gmin is not None else 0.0
        self._gain_max_db = max(-20.0, min(40.0, gmax)) if gmax is not None else self._gain_min_db

        if self._rms_db >= self._rms_peak_db:
            self._rms_peak_db = self._rms_db
            self._rms_peak_ts = now
        elif (now - self._rms_peak_ts) > PEAK_HOLD_S:
            self._rms_peak_db = max(self._rms_db, self._rms_peak_db - PEAK_DECAY_DB_S * dt)

        cur_g = self._gain_min_db if abs(self._gain_min_db) >= abs(self._gain_max_db) else self._gain_max_db
        if abs(cur_g) >= abs(self._gain_peak_db):
            self._gain_peak_db = cur_g
            self._gain_peak_ts = now
        elif (now - self._gain_peak_ts) > PEAK_HOLD_S:
            if self._gain_peak_db > 0.0:
                self._gain_peak_db = max(cur_g, self._gain_peak_db - PEAK_DECAY_DB_S * dt)
            else:
                self._gain_peak_db = min(cur_g, self._gain_peak_db + PEAK_DECAY_DB_S * dt)

        self._history.append((self._rms_db, self._gain_min_db, self._gain_max_db))
        return is_live

    def _tab_items(self, tab):
        if tab == "Comp":
            return [
                ("inputgain", "In Gain"),
                ("threshold", "Thresh"),
                ("Ratio",     "Ratio"),
                ("attack",    "Attack"),
            ]
        return [
            ("attack",    "Attack"),
            ("release",   "Release"),
            ("threshold", "Thresh"),
            ("Ratio",     "Ratio"),
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
            logging.debug(f"x42-comp mono sync error: {e}")

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
        if nk == "inputgain":
            return f"{v:+.1f}dB"
        if nk == "threshold":
            return f"{v:.1f}dB"
        if nk == "ratio":
            return fmt_ratio(v)
        if nk in ("attack", "release"):
            return fmt_time_s(v)
        return f"{v:.2f}"

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
        c.create_rectangle(x1, y1, x2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 6
        bar_h = max(7, int((y2 - y1) * 0.22))
        by2 = y2 - pad
        by1 = by2 - bar_h
        bx1, bx2 = x1 + pad, x2 - pad
        c.create_rectangle(bx1, by1, bx2, by2, fill=COL_TRACK, outline="")
        nk = _norm_key(key)
        if nk == "inputgain" and z is not None:
            z0 = (0.0 - float(z.value_min)) / max(1e-6, float(z.value_max) - float(z.value_min))
            zx = bx1 + (bx2 - bx1) * max(0.0, min(1.0, z0))
            vx = bx1 + (bx2 - bx1) * n
            c.create_rectangle(min(zx, vx), by1, max(zx, vx), by2, fill=accent, outline="")
            c.create_line(zx, by1 - 2, zx, by2 + 2, fill=COL_DIM, width=1)
        elif n > 0.005:
            c.create_rectangle(bx1, by1, bx1 + (bx2 - bx1) * n, by2, fill=accent, outline="")
        top_y = y1 + (by1 - y1) * 0.48
        w_in = max(20, (x2 - x1) - 12)
        c.create_text(x1 + 6, top_y, text=label, anchor="w", fill=COL_DIM,
                      font=self._fit_font(label, w_in * 0.52, 11, bold=False))
        c.create_text(x2 - 6, top_y, text=val_txt, anchor="e", fill=COL_TEXT,
                      font=self._fit_font(val_txt, w_in * 0.52, 12, bold=True))
        self.hitboxes.append((x1, y1, x2, y2, "param", (key, x1 + pad, x2 - pad)))

    def on_size(self, event):
        if super().on_size(event):
            self.last_snapshot = None
            self._draw()

    def _snapshot(self, is_live):
        vals = []
        for k in ("enable", "hold", "inputgain", "threshold", "Ratio", "attack", "release"):
            z = self._get_zctrl(k)
            vals.append(round(self._raw(z, 0.0), 4) if z else None)
        mon = (
            round(self._rms_db, 1),
            round(self._rms_peak_db, 1),
            round(self._gain_min_db, 1),
            round(self._gain_max_db, 1),
            round(self._gain_peak_db, 1),
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
        accent = TAB_ACCENTS.get(self.active_tab, "#ff922b")

        en = self._raw(self._get_zctrl("enable"), 1.0) >= 0.5
        hold = self._raw(self._get_zctrl("hold"), 0.0) >= 0.5
        byp_w = max(68, int(w * 0.14))
        hold_w = max(64, int(w * 0.13))
        tabs_w = w - 2 * pad - byp_w - hold_w - 2 * gap
        tw = (tabs_w - gap) / len(TABS)
        for i, t in enumerate(TABS):
            tx1 = pad + i * (tw + gap)
            self._draw_pill(tx1, pad, tx1 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        hx1 = w - pad - byp_w - gap - hold_w
        self._draw_pill(hx1, pad, hx1 + hold_w, pad + hdr_h, "HOLD", hold, COL_SIM, "toggle", "hold")
        bx1 = w - pad - byp_w
        self._draw_pill(bx1, pad, w - pad, pad + hdr_h, "ON ●" if en else "BYP",
                        en, "#40c057" if en else "#ff6b6b", "toggle", "enable")

        top_y = pad + hdr_h + gap
        pbox_h = max(44, min(58, int(h * 0.14)))
        vis_y2 = h - pad - pbox_h - gap

        if self.active_tab == "Comp":
            self._draw_comp_view(pad, top_y, w - pad, vis_y2, accent, en, is_live, now)
        else:
            self._draw_time_view(pad, top_y, w - pad, vis_y2, accent, en, is_live, now)

        items = self._tab_items(self.active_tab)
        bw = (w - 2 * pad - 3 * gap) / 4.0
        by1 = h - pad - pbox_h
        by2 = h - pad
        for i, (k, lbl) in enumerate(items):
            px1 = pad + i * (bw + gap)
            self._draw_param_box(px1, by1, px1 + bw, by2, k, lbl, accent)

    def _draw_comp_view(self, x1, y1, x2, y2, accent, en, is_live, now):
        c = self.widget_canvas
        gap = 6
        meter_w = max(92, min(130, int((x2 - x1) * 0.22)))
        gx2 = x2 - meter_w - gap

        c.create_rectangle(x1, y1, gx2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        ig = self._raw(self._get_zctrl("inputgain"), 0.0)
        thr = self._raw(self._get_zctrl("threshold"), -30.0)
        rat = self._raw(self._get_zctrl("Ratio"), 0.0)

        px1, py1 = x1 + 30, y1 + 26
        px2, py2 = gx2 - 12, y2 - 20
        pw = max(40, px2 - px1)
        ph = max(40, py2 - py1)

        def db_to_x(db):
            return px1 + ((max(-60.0, min(0.0, db)) + 60.0) / 60.0) * pw

        def db_to_y(db):
            return py2 - ((max(-60.0, min(0.0, db)) + 60.0) / 60.0) * ph

        for db in (-50, -40, -30, -20, -10):
            gx = db_to_x(db)
            gy = db_to_y(db)
            col = "#3c4054" if db == -10 else COL_GRID
            c.create_line(gx, py1, gx, py2, fill=col, width=1)
            c.create_line(px1, gy, px2, gy, fill=col, width=1)
            c.create_text(px1 - 4, gy, text=f"{db}", anchor="e", fill=COL_DIM, font=self._font(8))
            c.create_text(gx, py2 + 9, text=f"{db}", anchor="center", fill=COL_DIM, font=self._font(8))

        c.create_line(px1, py2, px2, py1, fill="#383b4d", dash=(4, 4), width=1)

        ux, uy = db_to_x(-10.0), db_to_y(-10.0)
        c.create_oval(ux - 4, uy - 4, ux + 4, uy + 4, outline=COL_DIM, width=1)
        c.create_text(ux - 6, uy - 9, text="-10dB Unity", anchor="e", fill=COL_DIM, font=self._font(8))

        eff_thr_in = max(-60.0, min(0.0, thr - ig))
        tx = db_to_x(eff_thr_in)
        c.create_line(tx, py1, tx, py2, fill="#ff922b", dash=(3, 3), width=1)

        pts = []
        steps = 44
        for i in range(steps + 1):
            in_db = -60.0 + (60.0 * i / steps)
            out_db, _ = darc_transfer_db(in_db, thr, rat, ig)
            pts.extend([db_to_x(in_db), db_to_y(out_db)])

        curve_col = accent if en else COL_DIM
        if len(pts) >= 4:
            c.create_line(*pts, fill=curve_col, width=2.5, smooth=True)

        sim_active = (not is_live) and ((now - self._last_interact_ts) < DRAG_SIM_HOLD_S)
        if is_live and self._rms_db > -60.0:
            op_in = max(-60.0, min(0.0, self._rms_db - ig))
            op_out = max(-60.0, min(0.0, self._rms_db + self._gain_min_db))
            ox, oy = db_to_x(op_in), db_to_y(op_out)
            c.create_line(ox, py2, ox, oy, fill=COL_LIVE, dash=(2, 2), width=1)
            c.create_line(px1, oy, ox, oy, fill=COL_LIVE, dash=(2, 2), width=1)
            c.create_oval(ox - 5, oy - 5, ox + 5, oy + 5, fill=COL_LIVE, outline="#ffffff", width=1.5)
        elif sim_active:
            sim_in = -24.0 + 12.0 * math.sin(now * 3.8)
            sim_out, _ = darc_transfer_db(sim_in, thr, rat, ig)
            ox, oy = db_to_x(sim_in), db_to_y(sim_out)
            c.create_oval(ox - 4, oy - 4, ox + 4, oy + 4, fill=COL_SIM, outline="#111217", width=1)

        kx = db_to_x(thr)
        k_out, _ = darc_transfer_db(thr - ig, thr, rat, ig)
        ky = db_to_y(k_out)
        c.create_oval(kx - 9, ky - 9, kx + 9, ky + 9, fill=accent, outline="#ffffff", width=2)
        c.create_text(kx, ky - 14, text="THR", fill=accent, font=self._font(8, bold=True))

        rx = db_to_x(-5.0)
        r_out, _ = darc_transfer_db(-5.0, thr, rat, ig)
        ry = db_to_y(r_out)
        c.create_polygon(rx, ry - 9, rx + 9, ry, rx, ry + 9, rx - 9, ry,
                         fill=COL_SIM, outline="#111217", width=1.5)
        c.create_text(rx - 10, ry, text=fmt_ratio(rat), anchor="e", fill=COL_SIM, font=self._font(8, bold=True))

        self.hitboxes.append((rx - 22, ry - 22, rx + 22, ry + 22, "ratio_drag", (py1, py2)))
        self.hitboxes.append((px1, py1, px2, py2, "comp_2d", (px1, py1, px2, py2)))

        badge = "LIVE" if is_live else ("SIM" if sim_active else CHANNEL_LABEL)
        bcol = COL_LIVE if is_live else (COL_SIM if sim_active else COL_DIM)
        c.create_text(x1 + 10, y1 + 13, text=f"x42-COMP {CHANNEL_LABEL} · Auto-Makeup (-10dB)",
                      anchor="w", fill=COL_TEXT,
                      font=self._fit_font(f"x42-COMP {CHANNEL_LABEL} · Auto-Makeup (-10dB)", (gx2 - x1) - 70, 11, bold=True))
        c.create_text(gx2 - 10, y1 + 13, text=badge, anchor="e", fill=bcol, font=self._font(9, bold=True))

        mx1 = gx2 + gap
        c.create_rectangle(mx1, y1, x2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        c.create_text((mx1 + x2) / 2, y1 + 13, text="RMS / GAIN", fill=COL_DIM, font=self._font(9, bold=True))

        mpad = 8
        my1 = y1 + 26
        my2 = y2 - 22
        mh = max(30, my2 - my1)
        mw_each = max(16, int((x2 - mx1 - 3 * mpad) / 2))

        r1 = mx1 + mpad
        r2 = r1 + mw_each
        c.create_rectangle(r1, my1, r2, my2, fill=COL_TRACK, outline=COL_BORDER, width=1)
        rms_n = max(0.0, min(1.0, (self._rms_db + 60.0) / 60.0))
        if rms_n > 0.01:
            ry_top = my2 - rms_n * mh
            rcol = COL_GR_HI if self._rms_db > -3.0 else (COL_SIM if self._rms_db > -12.0 else COL_LIVE)
            c.create_rectangle(r1 + 1, ry_top, r2 - 1, my2 - 1, fill=rcol, outline="")
        pk_n = max(0.0, min(1.0, (self._rms_peak_db + 60.0) / 60.0))
        if pk_n > 0.02:
            py_pk = my2 - pk_n * mh
            c.create_line(r1 + 1, py_pk, r2 - 1, py_pk, fill="#ffffff", width=2)
        rms_lbl = f"{self._rms_db:.0f}" if self._rms_db > -75.0 else "-∞"
        c.create_text((r1 + r2) / 2, y2 - 11, text=rms_lbl, fill=COL_TEXT, font=self._font(9, bold=True))

        g1 = r2 + mpad
        g2 = x2 - mpad
        c.create_rectangle(g1, my1, g2, my2, fill=COL_TRACK, outline=COL_BORDER, width=1)

        def gain_to_y(gdb):
            n = (max(-20.0, min(40.0, gdb)) + 20.0) / 60.0
            return my2 - n * mh

        y0 = gain_to_y(0.0)
        c.create_line(g1, y0, g2, y0, fill=COL_DIM, width=1)

        disp_g = self._gain_min_db
        if not is_live and sim_active:
            _, disp_g = darc_transfer_db(-24.0 + 12.0 * math.sin(now * 3.8), thr, rat, ig)
        gy_val = gain_to_y(disp_g)
        if abs(disp_g) > 0.1:
            gcol = COL_BOOST if disp_g > 0.0 else (COL_GR_HI if disp_g < -10.0 else COL_GR)
            c.create_rectangle(g1 + 1, min(y0, gy_val), g2 - 1, max(y0, gy_val), fill=gcol, outline="")
        if abs(self._gain_peak_db) > 0.2:
            gy_pk = gain_to_y(self._gain_peak_db)
            c.create_line(g1 + 1, gy_pk, g2 - 1, gy_pk, fill="#ffffff", width=2)
        glbl = f"{disp_g:+.1f}" if abs(disp_g) >= 0.05 else "0.0"
        c.create_text((g1 + g2) / 2, y2 - 11, text=glbl,
                      fill=COL_BOOST if disp_g > 0.2 else (COL_GR if disp_g < -0.2 else COL_TEXT),
                      font=self._font(9, bold=True))

    def _draw_time_view(self, x1, y1, x2, y2, accent, en, is_live, now):
        c = self.widget_canvas
        gap = 6
        pad_w = max(140, int((x2 - x1) * 0.40))
        sx2 = x2 - pad_w - gap

        c.create_rectangle(x1, y1, sx2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        thr = self._raw(self._get_zctrl("threshold"), -30.0)
        rat = self._raw(self._get_zctrl("Ratio"), 0.0)
        att = self._raw(self._get_zctrl("attack"), 0.01)
        rel = self._raw(self._get_zctrl("release"), 0.30)

        px1, py1 = x1 + 10, y1 + 26
        px2, py2 = sx2 - 10, y2 - 10
        pw = max(40, px2 - px1)
        ph = max(40, py2 - py1)

        for frac in (0.25, 0.5, 0.75):
            gy = py1 + ph * frac
            c.create_line(px1, gy, px2, gy, fill=COL_GRID, width=1)

        thr_y = py2 - ((max(-60.0, min(0.0, thr)) + 60.0) / 60.0) * ph
        c.create_line(px1, thr_y, px2, thr_y, fill="#ff922b", dash=(3, 3), width=1)
        c.create_text(px2 - 4, thr_y - 7, text=f"THR {thr:.0f}dB", anchor="e", fill="#ff922b", font=self._font(8))

        if is_live:
            rms_pts = []
            gr_pts = []
            hist = list(self._history)
            n_s = max(2, len(hist))
            for i, (r_db, g_min, _g_max) in enumerate(hist):
                sx = px1 + (pw * i / (n_s - 1))
                ry = py2 - ((max(-60.0, min(0.0, r_db)) + 60.0) / 60.0) * ph
                gn = max(0.0, min(1.0, (g_min + 20.0) / 60.0))
                gy = py2 - gn * ph
                rms_pts.extend([sx, ry])
                gr_pts.extend([sx, gy])
            if len(rms_pts) >= 4:
                c.create_line(*rms_pts, fill="#4dabf7", width=2, smooth=True)
            if len(gr_pts) >= 4:
                c.create_line(*gr_pts, fill=accent if en else COL_DIM, width=2.5, smooth=True)
            mode_lbl, mode_col = "LIVE 2.0s", COL_LIVE
        else:
            steps = 56
            env_pts = []
            in_pts = []
            t_win = 2.0
            t_on, t_off = 0.25, 0.90
            depth = max(0.15, rat * 0.85)
            cur = 0.0
            dt = t_win / steps
            for i in range(steps + 1):
                t = i * dt
                burst = 1.0 if (t_on <= t <= t_off) else 0.0
                target = depth * burst
                tau = max(0.002, att if target > cur else rel)
                alpha = 1.0 - math.exp(-dt / tau)
                cur += (target - cur) * alpha
                sx = px1 + (pw * i / steps)
                in_pts.extend([sx, py2 - (0.18 + 0.65 * burst) * ph])
                env_pts.extend([sx, py1 + 6 + cur * (ph - 16)])
            c.create_line(*in_pts, fill="#383b4d", width=1.5)
            c.create_line(*env_pts, fill=accent if en else COL_DIM, width=2.5, smooth=True)
            mode_lbl, mode_col = "SIM ENV", COL_SIM

        c.create_text(x1 + 10, y1 + 13, text="RMS & Gain Envelope Scope", anchor="w",
                      fill=COL_TEXT, font=self._fit_font("RMS & Gain Envelope Scope", (sx2 - x1) - 85, 11, bold=True))
        c.create_text(sx2 - 10, y1 + 13, text=mode_lbl, anchor="e", fill=mode_col, font=self._font(9, bold=True))

        ax1 = sx2 + gap
        c.create_rectangle(ax1, y1, x2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        c.create_text(ax1 + 10, y1 + 13, text="Attack × Release (2D)", anchor="w",
                      fill=COL_TEXT, font=self._fit_font("Attack × Release (2D)", (x2 - ax1) - 20, 11, bold=True))

        apx1, apy1 = ax1 + 12, y1 + 28
        apx2, apy2 = x2 - 12, y2 - 20
        for frac in (0.25, 0.5, 0.75):
            c.create_line(apx1 + (apx2 - apx1) * frac, apy1, apx1 + (apx2 - apx1) * frac, apy2, fill=COL_GRID)
            c.create_line(apx1, apy1 + (apy2 - apy1) * frac, apx2, apy1 + (apy2 - apy1) * frac, fill=COL_GRID)

        an = self._norm(self._get_zctrl("attack"), "attack", 0.5)
        rn = self._norm(self._get_zctrl("release"), "release", 0.5)
        nx = apx1 + an * (apx2 - apx1)
        ny = apy2 - rn * (apy2 - apy1)

        c.create_line(nx, apy1, nx, apy2, fill=accent, dash=(2, 3), width=1)
        c.create_line(apx1, ny, apx2, ny, fill=accent, dash=(2, 3), width=1)
        c.create_oval(nx - 10, ny - 10, nx + 10, ny + 10, fill=accent, outline="#ffffff", width=2)
        c.create_text(apx1, y2 - 9, text=f"Att {fmt_time_s(att)}", anchor="w", fill=COL_DIM, font=self._font(9))
        c.create_text(apx2, y2 - 9, text=f"Rel {fmt_time_s(rel)}", anchor="e", fill=COL_DIM, font=self._font(9))
        self.hitboxes.append((apx1, apy1, apx2, apy2, "time_2d", (apx1, apy1, apx2, apy2)))

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
            elif tag == "comp_2d":
                self._reset_zctrl(self._get_zctrl("threshold"), "threshold")
                self._reset_zctrl(self._get_zctrl("inputgain"), "inputgain")
            elif tag == "ratio_drag":
                self._reset_zctrl(self._get_zctrl("Ratio"), "Ratio")
            elif tag == "time_2d":
                self._reset_zctrl(self._get_zctrl("attack"), "attack")
                self._reset_zctrl(self._get_zctrl("release"), "release")
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
        elif tag == "comp_2d":
            x1, y1, x2, y2 = data
            nx = max(0.0, min(1.0, (x - x1) / max(1.0, float(x2 - x1))))
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            z_thr = self._get_zctrl("threshold")
            if z_thr is not None:
                thr_db = -60.0 + nx * 60.0
                z_thr.set_value(max(float(z_thr.value_min), min(float(z_thr.value_max), thr_db)), send=True)
            self._set_norm(self._get_zctrl("inputgain"), ny, "inputgain")
        elif tag == "ratio_drag":
            y1, y2 = data
            ny = max(0.0, min(1.0, (y - y1) / max(1.0, float(y2 - y1))))
            self._set_norm(self._get_zctrl("Ratio"), ny, "Ratio")
        elif tag == "time_2d":
            x1, y1, x2, y2 = data
            nx = max(0.0, min(1.0, (x - x1) / max(1.0, float(x2 - x1))))
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            self._set_norm(self._get_zctrl("attack"), nx, "attack")
            self._set_norm(self._get_zctrl("release"), ny, "release")
        self.last_snapshot = None
        self._draw()


# Zynthian loader alias for hyphenated plugin filename
globals()["zynthian_widget_x42-comp_-_dynamic_compressor_mono"] = zynthian_widget_x42_comp_mono
