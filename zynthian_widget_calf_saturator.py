#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Calf Saturator Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 3 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Drive | Pre/Post | Tone & I/O   + PRE / POST / ON-BYP
# Features:
#   - Live LV2 metering (meter_inL/R, meter_outL/R, clip_inL/R, clip_outL/R)
#   - Drive: waveshaping transfer curve with animated saturation operating
#     point (real LV2 excitation + interactive preview) & vertical I/O meters
#   - Pre/Post: 4 independent touchable frequency handles (Pre HP/LP blue,
#     Post HP/LP orange) on log-frequency bandpass curves with double-tap reset
#   - Tone & I/O: harmonic tone bell on log-frequency grid + output L/R meters
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
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"
COL_PRE = "#4dabf7"
COL_POST = "#ff922b"
COL_CLIP = "#ff4d4f"
COL_LIVE = "#51cf66"

TABS = ["Drive", "Pre/Post", "Tone & I/O"]
TAB_ACCENTS = {
    "Drive":      "#ff922b",
    "Pre/Post":   "#4dabf7",
    "Tone & I/O": "#51cf66",
}
LOG_KEYS = {"lp_pre_freq", "hp_pre_freq", "lp_post_freq", "hp_post_freq", "p_freq", "p_q", "level_in", "level_out", "p_level"}

LIVE_HOLD_S = 2.0
PREVIEW_HOLD_S = 2.5


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.2f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


def _eval_sat(x_in, drv, asym, mix=1.0):
    wet = math.tanh((x_in + asym * (x_in ** 2)) * drv)
    return max(-1.0, min(1.0, (1.0 - mix) * x_in + mix * wet))


class zynthian_widget_calf_saturator(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Drive"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}

        # Live LV2 telemetry
        self._in_l = 0.0
        self._in_r = 0.0
        self._out_l = 0.0
        self._out_r = 0.0
        self._clip_in = False
        self._clip_out = False
        self._last_live_ts = 0.0
        self._last_interact_ts = 0.0

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
        in_l = self._get_mon("meter_inL")
        in_r = self._get_mon("meter_inR")
        out_l = self._get_mon("meter_outL")
        out_r = self._get_mon("meter_outR")
        c_in = (self._get_mon("clip_inL", 0.0) >= 0.5) or (self._get_mon("clip_inR", 0.0) >= 0.5)
        c_out = (self._get_mon("clip_outL", 0.0) >= 0.5) or (self._get_mon("clip_outR", 0.0) >= 0.5)

        has_signal = any(v is not None and v > 0.002 for v in (in_l, in_r, out_l, out_r))
        if has_signal:
            self._last_live_ts = now

        self._in_l = max(0.0, min(1.0, in_l if in_l is not None else 0.0))
        self._in_r = max(0.0, min(1.0, in_r if in_r is not None else self._in_l))
        self._out_l = max(0.0, min(1.0, out_l if out_l is not None else 0.0))
        self._out_r = max(0.0, min(1.0, out_r if out_r is not None else self._out_l))
        self._clip_in = c_in
        self._clip_out = c_out
        return (now - self._last_live_ts) < LIVE_HOLD_S

    def _tab_items(self, tab):
        if tab == "Drive":
            return [
                ("drive",    "Drive"),
                ("blend",    "Tape/Tube"),
                ("mix",      "Mix"),
                ("level_in", "In Gain"),
            ]
        if tab == "Pre/Post":
            return [
                ("hp_pre_freq",  "Pre HP"),
                ("lp_pre_freq",  "Pre LP"),
                ("hp_post_freq", "Post HP"),
                ("lp_post_freq", "Post LP"),
            ]
        return [
            ("p_freq",    "Tone Frq"),
            ("p_level",   "Tone Amt"),
            ("p_q",       "Gradient"),
            ("level_out", "Out Gain"),
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
            logging.debug(f"Calf Saturator sync error: {e}")

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
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_calf_saturator._raw(z)
        if "freq" in key:
            return fmt_hz(v)
        if key == "mix":
            return f"{int(round(v * 100))}%"
        if key == "blend":
            return f"Tube {v:+.1f}" if v >= 0 else f"Tape {v:+.1f}"
        if key in ("level_in", "level_out", "p_level"):
            return f"{20.0 * math.log10(max(1e-4, v)):+.1f}dB"
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
        now = time.monotonic()
        keys = ("bypass", "pre", "post", "drive", "blend", "mix", "level_in", "level_out",
                "lp_pre_freq", "hp_pre_freq", "lp_post_freq", "hp_post_freq", "p_freq", "p_level", "p_q")
        pvals = tuple(round(self._raw(self._get_zctrl(k)), 3) for k in keys)
        prev_p = self.last_snapshot[3] if (self.last_snapshot and len(self.last_snapshot) >= 4) else None
        if prev_p is not None and pvals != prev_p:
            self._last_interact_ts = now

        is_live = self._update_telemetry(now)
        previewing = (self.active_tab == "Drive") and (not is_live) and (
            self.drag_target is not None or (now - self._last_interact_ts) < PREVIEW_HOLD_S
        )
        if previewing:
            anim = int(now / UPDATE_PERIOD)
        elif is_live and self.active_tab in ("Drive", "Tone & I/O"):
            anim = (round(self._in_l, 2), round(self._in_r, 2), round(self._out_l, 2), round(self._out_r, 2),
                    self._clip_in, self._clip_out)
        else:
            anim = (is_live,)

        snap = (self.width, self.height, self.active_tab, pvals, anim)
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
                      fill="#0d0e12" if active else COL_TEXT, font=self._font(self._fs(0.90), bold=True))
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z, key)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        tx0, tx1 = x0 + 8, x1 - 8
        by1 = y1 - 6
        by0 = by1 - 11
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM, font=self._font(self._fs(0.84)))
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=self._fmt(z, key), anchor="e", fill=COL_TEXT,
                      font=self._font(self._fs(0.88), bold=True))
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

    def _draw_io_meters(self, c, mx0, my0, mx1, my1):
        c.create_rectangle(mx0, my0, mx1, my1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        mw = max(24, mx1 - mx0)
        top = my0 + 18
        bot = my1 - 20
        mh = max(20, bot - top)
        col_w = max(6, (mw - 18) / 4.0)
        bars = [
            (self._in_l, "#4dabf7"),
            (self._in_r, "#4dabf7"),
            (self._out_l, "#ff922b"),
            (self._out_r, "#ff922b"),
        ]
        c.create_text(mx0 + mw * 0.27, my0 + 9, text="IN", fill="#4dabf7", font=self._font(self._fs(0.68), bold=True))
        c.create_text(mx0 + mw * 0.73, my0 + 9, text="OUT", fill="#ff922b", font=self._font(self._fs(0.68), bold=True))
        for i, (lvl, col) in enumerate(bars):
            gap_x = 4 if i >= 2 else 0
            bx0 = mx0 + 5 + i * (col_w + 2) + gap_x
            c.create_rectangle(bx0, top, bx0 + col_w, bot, fill="#121318", outline="")
            if lvl > 0.01:
                bh = min(1.0, lvl) * mh
                c.create_rectangle(bx0, bot - bh, bx0 + col_w, bot, fill=col, outline="")
        # Clip LEDs
        led_y = my1 - 10
        c.create_oval(mx0 + mw * 0.27 - 4, led_y - 4, mx0 + mw * 0.27 + 4, led_y + 4,
                      fill=COL_CLIP if self._clip_in else "#2d303e", outline="")
        c.create_oval(mx0 + mw * 0.73 - 4, led_y - 4, mx0 + mw * 0.73 + 4, led_y + 4,
                      fill=COL_CLIP if self._clip_out else "#2d303e", outline="")

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
        byp = self._raw(self._get_zctrl("bypass")) >= 0.5
        pre_on = self._raw(self._get_zctrl("pre")) >= 0.5
        post_on = self._raw(self._get_zctrl("post")) >= 0.5

        hdr_h = max(36, min(46, int(h * 0.11)))
        tog_w = 72
        tabs_w = w - 2 * pad - 3 * (tog_w + gap)
        tw = (tabs_w - 2 * gap) / 3
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        rx = w - pad - 3 * tog_w - 2 * gap
        self._draw_pill(rx, pad, rx + tog_w, pad + hdr_h, "PRE", pre_on, COL_PRE, "toggle", "pre")
        self._draw_pill(rx + tog_w + gap, pad, rx + 2 * tog_w + gap, pad + hdr_h, "POST", post_on, COL_POST, "toggle", "post")
        self._draw_pill(w - pad - tog_w, pad, w - pad, pad + hdr_h, "BYP" if byp else "ON ●", not byp, "#51cf66", "toggle", "bypass")

        bot_h = 98
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap
        now = time.monotonic()
        is_live = (now - self._last_live_ts) < LIVE_HOLD_S

        if self.active_tab == "Drive":
            mtr_w = 62
            px1 = w - pad - mtr_w - gap
            c.create_rectangle(pad, vy0, px1, vy1, fill=COL_PANEL, outline=accent if not byp else COL_BORDER, width=1)
            self._draw_io_meters(c, px1 + gap, vy0, w - pad, vy1)

            gx0, gx1 = pad + 14, px1 - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            mid_x = (gx0 + gx1) / 2.0
            mid_y = (gy0 + gy1) / 2.0

            drv_n = self._norm(self._get_zctrl("drive"), "drive")
            bld_n = self._norm(self._get_zctrl("blend"), "blend")
            mix_n = self._norm(self._get_zctrl("mix"), "mix", 1.0)
            drv = 0.5 + drv_n * 8.0
            asym = (bld_n - 0.5) * 0.7

            c.create_text(gx0, vy0 + 11, text="Saturation Curve  (Drag 2D: X=Drive, Y=Tape ↔ Tube)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))
            st_txt, st_col = ("● LIVE", COL_LIVE) if is_live else ("◈ SAT", accent)
            c.create_text(px1 - 8, vy0 + 11, text=st_txt, anchor="e", fill=st_col,
                          font=self._font(self._fs(0.74), bold=True))

            # Axes + linear diagonal
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))
            c.create_line(mid_x, gy0, mid_x, gy1, fill=COL_GRID, dash=(2, 4))
            c.create_line(gx0, gy1, gx1, gy0, fill="#3b3f52", dash=(3, 4))

            pts = []
            for i in range(65):
                t = i / 64.0
                x_in = t * 2.0 - 1.0
                y_out = x_in if byp else _eval_sat(x_in, drv, asym, mix_n)
                pts.extend([gx0 + t * gw, mid_y - y_out * (gh * 0.46)])
            c.create_line(pts, fill=accent if not byp else COL_DIM, width=2.8)

            # Live / Animated saturation excitation dot along transfer curve
            if is_live:
                exc = max(self._in_l, self._in_r)
                sign = 1.0 if math.sin(now * 16.0) >= 0 else -1.0
                ex_in = max(-0.98, min(0.98, sign * exc))
            elif self.drag_target is not None or (now - self._last_interact_ts) < PREVIEW_HOLD_S:
                ex_in = 0.78 * math.sin(now * 5.2)
            else:
                ex_in = None

            if ex_in is not None:
                ex_out = ex_in if byp else _eval_sat(ex_in, drv, asym, mix_n)
                ex_px = gx0 + ((ex_in + 1.0) * 0.5) * gw
                ex_py = mid_y - ex_out * (gh * 0.46)
                c.create_line(ex_px, gy0, ex_px, gy1, fill="#4d3b2b", dash=(2, 3))
                c.create_line(gx0, ex_py, gx1, ex_py, fill="#4d3b2b", dash=(2, 3))
                dot_col = "#ff6b6b" if abs(ex_out) > 0.85 else "#ffd43b"
                c.create_oval(ex_px - 6, ex_py - 6, ex_px + 6, ex_py + 6, fill=dot_col, outline="#ffffff", width=1.6)

            hx = gx0 + drv_n * gw
            hy = gy1 - bld_n * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, px1, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "drive", "yk": "blend"}))

        elif self.active_tab == "Pre/Post":
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent if not byp else COL_BORDER, width=1)
            gx0, gx1 = pad + 16, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 18
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)

            hp1_hz = max(10.0, self._raw(self._get_zctrl("hp_pre_freq"), 10.0))
            lp1_hz = max(10.0, self._raw(self._get_zctrl("lp_pre_freq"), 20000.0))
            hp2_hz = max(10.0, self._raw(self._get_zctrl("hp_post_freq"), 10.0))
            lp2_hz = max(10.0, self._raw(self._get_zctrl("lp_post_freq"), 20000.0))

            c.create_text(gx0, vy0 + 11, text="Pre (Blue) & Post (Orange) Filters  (Drag any of 4 HP/LP nodes)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            f_min, f_max = 10.0, 20000.0
            log_span = math.log(f_max / f_min)

            def hz_to_x(hz):
                hz = max(f_min, min(f_max, hz))
                return gx0 + (math.log(hz / f_min) / log_span) * gw

            for f_hz, flbl in ((20, "20"), (50, "50"), (200, "200"), (1000, "1k"), (4000, "4k"), (12000, "12k")):
                fx = hz_to_x(f_hz)
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 9, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            # Smooth 12 dB/oct bandpass curves for Pre and Post
            pts_pre, pts_post = [], []
            poly_pre = [gx0, gy1]
            for i in range(73):
                t = i / 72.0
                f = f_min * ((f_max / f_min) ** t)
                g_pre = (1.0 / math.sqrt(1.0 + (hp1_hz / f) ** 4)) * (1.0 / math.sqrt(1.0 + (f / lp1_hz) ** 4))
                g_post = (1.0 / math.sqrt(1.0 + (hp2_hz / f) ** 4)) * (1.0 / math.sqrt(1.0 + (f / lp2_hz) ** 4))
                px = gx0 + t * gw
                y_pre = gy1 - g_pre * (gh * 0.88)
                y_post = gy1 - g_post * (gh * 0.72)
                pts_pre.extend([px, y_pre])
                poly_pre.extend([px, y_pre])
                pts_post.extend([px, y_post])
            poly_pre.extend([gx1, gy1])

            if pre_on:
                c.create_polygon(poly_pre, fill="#192a3d", outline="")
            c.create_line(pts_pre, fill=COL_PRE, width=2.5 if pre_on else 1.4, dash=() if pre_on else (3, 3))
            c.create_line(pts_post, fill=COL_POST, width=2.5 if post_on else 1.4, dash=() if post_on else (4, 3))

            # 4 independent interactive handles (Pre HP/LP upper band, Post HP/LP lower band)
            y_pre_n = gy0 + gh * 0.28
            y_post_n = gy0 + gh * 0.68
            nodes = [
                ("hp_pre_freq",  hz_to_x(hp1_hz), y_pre_n,  "HP", COL_PRE,  pre_on),
                ("lp_pre_freq",  hz_to_x(lp1_hz), y_pre_n,  "LP", COL_PRE,  pre_on),
                ("hp_post_freq", hz_to_x(hp2_hz), y_post_n, "HP", COL_POST, post_on),
                ("lp_post_freq", hz_to_x(lp2_hz), y_post_n, "LP", COL_POST, post_on),
            ]
            node_payload = []
            for k, nx, ny, lbl, col, active in nodes:
                c.create_line(nx, gy0, nx, gy1, fill="#283548" if col == COL_PRE else "#4a3320", dash=(2, 3))
                c.create_oval(nx - 10, ny - 10, nx + 10, ny + 10,
                              fill=col if active else COL_PANEL,
                              outline="#ffffff" if active else col, width=2)
                c.create_text(nx, ny, text=lbl, fill="#0d0e12" if active else col,
                              font=self._font(self._fs(0.66), bold=True))
                node_payload.append({"key": k, "x": nx, "y": ny})

            self.hitboxes.append((pad, vy0, w - pad, vy1, "prepost_nodes", {
                "gx0": gx0, "gx1": gx1, "nodes": node_payload,
            }))

        else:
            mtr_w = 62
            px1 = w - pad - mtr_w - gap
            c.create_rectangle(pad, vy0, px1, vy1, fill=COL_PANEL, outline=accent if not byp else COL_BORDER, width=1)
            self._draw_io_meters(c, px1 + gap, vy0, w - pad, vy1)

            gx0, gx1 = pad + 14, px1 - 14
            gy0, gy1 = vy0 + 22, vy1 - 16
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            mid_y = (gy0 + gy1) / 2.0
            c.create_line(gx0, mid_y, gx1, mid_y, fill="#3c4054", dash=(2, 4))

            pf = self._norm(self._get_zctrl("p_freq"), "p_freq")
            pl = self._norm(self._get_zctrl("p_level"), "p_level")
            pq = self._norm(self._get_zctrl("p_q"), "p_q")
            c.create_text(gx0, vy0 + 11, text="Harmonic Tone Bell  (Drag 2D: X=Tone Freq, Y=Tone Amount)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            for frac, flbl in ((0.12, "80"), (0.35, "300"), (0.58, "1.2k"), (0.82, "5k")):
                fx = gx0 + frac * gw
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            pts = []
            poly = [gx0, mid_y]
            gain = (pl - 0.5) * 2.0
            sig = max(0.05, 0.25 - pq * 0.18)
            for i in range(65):
                t = i / 64.0
                y = gain * math.exp(-((t - pf) / sig) ** 2)
                px = gx0 + t * gw
                py = mid_y - y * (gh * 0.45)
                pts.extend([px, py])
                poly.extend([px, py])
            poly.extend([gx1, mid_y])
            c.create_polygon(poly, fill="#193322", outline="")
            c.create_line(pts, fill=accent, width=2.6)
            hx = gx0 + pf * gw
            hy = gy1 - pl * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, px1, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "p_freq", "yk": "p_level"}))

        py0 = vy1 + gap
        items = self._tab_items(self.active_tab)
        cw = (w - 2 * pad - gap) / 2
        ch = (h - pad - py0 - 4) / 2
        for i, (k, lbl) in enumerate(items):
            px0 = pad + (i % 2) * (cw + gap)
            py_i = py0 + (i // 2) * (ch + 4)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, k, lbl, accent,
                                 bipolar=(k in ("blend", "p_level", "level_in", "level_out")))

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
                        cur = self._raw(z) >= 0.5
                        ticks = getattr(z, "ticks", None)
                        z.set_value((ticks[0] if cur else ticks[1]) if ticks and len(ticks) >= 2 else (0.0 if cur else 1.0), send=True)
                    self._last_interact_ts = now
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "prepost_nodes":
                    best = min(payload["nodes"], key=lambda nd: math.hypot(event.x - nd["x"], event.y - nd["y"]))
                    k = best["key"]
                    tid = ("prepost_node", k)
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        z = self._get_zctrl(k)
                        if z is not None:
                            z.reset_value()
                        self._last_interact_ts = now
                        self.last_snapshot = None
                        self._draw()
                        return
                    self.last_tap = (tid, now)
                    self.drag_target = ("prepost_node", {"key": k, "gx0": payload["gx0"], "gx1": payload["gx1"]})
                    self._apply_drag(event.x, event.y)
                    return
                if kind in ("hfader", "xy_pad"):
                    tid = (kind, payload.get("key") or payload.get("xk"))
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = [payload["key"]] if kind == "hfader" else [payload["xk"], payload["yk"]]
                        for rk in rks:
                            z = self._get_zctrl(rk)
                            if z is not None:
                                z.reset_value()
                        self._last_interact_ts = now
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
        self._last_interact_ts = time.monotonic()
        if kind == "hfader" and p["tx1"] > p["tx0"]:
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]), p["key"])
        elif kind == "prepost_node" and p["gx1"] > p["gx0"]:
            nx = max(0.0, min(1.0, (x - p["gx0"]) / (p["gx1"] - p["gx0"])))
            f_hz = 10.0 * ((20000.0 / 10.0) ** nx)
            z = self._get_zctrl(p["key"])
            if z is not None:
                z.set_value(max(float(z.value_min), min(float(z.value_max), f_hz)), send=True)
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]), p["xk"])
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]), p["yk"])
        self.last_snapshot = None
        self._draw()
