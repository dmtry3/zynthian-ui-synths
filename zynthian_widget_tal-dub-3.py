#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Tal-Dub-3 Vintage Dub Delay Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 3 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Delay | Filter | Dub Mix   + x2 L / x2 R / LIVE switches
# Features:
#   - Stereo Dub Echo Tap Timeline with L/R x2 ping-pong offsets & feedback decay
#   - Quick tempo-sync bar (Free, 1/16, 1/8, 1/8., 1/4, 1/4., 1/8T, plus ◀/▶
#     through all 19 TAL-Dub-3 host sync divisions)
#   - Interactive feedback resonant bandpass filter with dual LC/HC+Reso nodes
#   - Input saturation & Dry/Wet dub stage visualizer + double-tap reset
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

TABS = ["Delay", "Filter", "Dub Mix"]
TAB_ACCENTS = {
    "Delay":   "#ffd43b",
    "Filter":  "#ff922b",
    "Dub Mix": "#51cf66",
}

SYNC_DIVS = [
    ("Free",  0.000000),
    ("1/16",  0.052631),
    ("1/8",   0.105263),
    ("1/4",   0.157895),
    ("1/2",   0.211053),
    ("1/1",   0.263158),
    ("2/1",   0.315789),
    ("1/16.", 0.368421),
    ("1/8.",  0.421052),
    ("1/4.",  0.473684),
    ("1/2.",  0.526316),
    ("1/1.",  0.578947),
    ("2/1.",  0.631579),
    ("1/16T", 0.684211),
    ("1/8T",  0.736842),
    ("1/4T",  0.789474),
    ("1/2T",  0.842105),
    ("1/1T",  0.894736),
    ("2/1T",  0.947368),
]

QUICK_SYNC_IDXS = [0, 1, 2, 8, 3, 9, 14]  # Free, 1/16, 1/8, 1/8., 1/4, 1/4., 1/8T


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.1f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


class zynthian_widget_tal_dub_3(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Delay"
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
        if tab == "Delay":
            return [
                ("delaytime",     "Time"),
                ("delaytimesync", "Sync"),
                ("feedback",      "Feedback"),
                ("inputdrive",    "In Drive"),
            ]
        if tab == "Filter":
            return [
                ("cutoff",    "Low Cut"),
                ("highcut",   "High Cut"),
                ("resonance", "Reso"),
                ("feedback",  "Feedback"),
            ]
        return [
            ("inputdrive", "In Drive"),
            ("dry",        "Dry"),
            ("wet",        "Wet"),
            ("feedback",   "Feedback"),
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
            logging.debug(f"Tal-Dub-3 sync error: {e}")

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
        ticks = getattr(z, "ticks", None)
        if ticks and len(ticks) > 1:
            z.set_value(ticks[int(round(n * (len(ticks) - 1)))], send=True)
            return
        vmin, vmax = float(z.value_min), float(z.value_max)
        if vmax > vmin:
            z.set_value(max(vmin, min(vmax, vmin + n * (vmax - vmin))), send=True)

    @staticmethod
    def _sync_idx(val):
        best_i = 0
        best_d = 99.0
        for i, (_, sv) in enumerate(SYNC_DIVS):
            d = abs(val - sv)
            if d < best_d:
                best_d = d
                best_i = i
        return best_i

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        n = zynthian_widget_tal_dub_3._norm(z)
        if key == "delaytimesync":
            return SYNC_DIVS[zynthian_widget_tal_dub_3._sync_idx(n)][0]
        if key == "delaytime":
            ms = 10.0 + (n ** 1.5) * 3990.0
            return f"{ms / 1000.0:.2f}s" if ms >= 1000.0 else f"{ms:.0f}ms"
        if key in ("cutoff", "highcut"):
            hz = 40.0 * ((18000.0 / 40.0) ** n)
            return fmt_hz(hz)
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
        keys = ("inputdrive", "delaytime", "delaytimesync", "delaytwice_l", "delaytwice_r",
                "feedback", "highcut", "cutoff", "resonance", "dry", "wet", "livemode")
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

        x2l = self._raw(self._get_zctrl("delaytwice_l")) >= 0.5
        x2r = self._raw(self._get_zctrl("delaytwice_r")) >= 0.5
        live_m = self._raw(self._get_zctrl("livemode")) >= 0.5

        tog_w = 56
        tabs_w = w - 2 * pad - 3 * (tog_w + gap)
        tw = (tabs_w - 2 * gap) / 3.0
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        rx = w - pad - 3 * tog_w - 2 * gap
        self._draw_pill(rx, pad, rx + tog_w, pad + hdr_h, "x2 L", x2l, "#ffd43b", "toggle", "delaytwice_l")
        self._draw_pill(rx + tog_w + gap, pad, rx + 2 * tog_w + gap, pad + hdr_h, "x2 R", x2r, "#4dabf7", "toggle", "delaytwice_r")
        self._draw_pill(w - pad - tog_w, pad, w - pad, pad + hdr_h, "LIVE", live_m, "#ff6b6b", "toggle", "livemode")

        bot_h = 96
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap

        if self.active_tab == "Delay":
            # Quick Tempo Sync Bar (>=34px)
            r2_h = 34
            sync_idx = self._sync_idx(self._norm(self._get_zctrl("delaytimesync"), 0.0))
            step_w = 34
            self._draw_pill(pad, vy0, pad + step_w, vy0 + r2_h, "◀", False, accent, "step_sync", -1)
            self._draw_pill(w - pad - step_w, vy0, w - pad, vy0 + r2_h, "▶", False, accent, "step_sync", +1)
            sx0 = pad + step_w + gap
            sw = (w - pad - step_w - gap - sx0 - (len(QUICK_SYNC_IDXS) - 1) * gap) / len(QUICK_SYNC_IDXS)
            for i, si in enumerate(QUICK_SYNC_IDXS):
                slbl, sval = SYNC_DIVS[si]
                bx0 = sx0 + i * (sw + gap)
                self._draw_pill(bx0, vy0, bx0 + sw, vy0 + r2_h, slbl, si == sync_idx, accent,
                                "set_val", ("delaytimesync", sval))

            py0 = vy0 + r2_h + gap
            c.create_rectangle(pad, py0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = py0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            mid_y = (gy0 + gy1) / 2.0

            d_t = self._norm(self._get_zctrl("delaytime"), 0.25)
            fb = self._norm(self._get_zctrl("feedback"), 0.3)
            drv = self._norm(self._get_zctrl("inputdrive"), 0.4)
            sync_lbl = SYNC_DIVS[sync_idx][0]
            c.create_text(gx0, py0 + 11, text=f"Dub Echo Timeline [{sync_lbl}]  (Drag 2D: X=Time, Y=Feedback)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))
            c.create_text(gx0 + 2, gy0 + 8, text="L", anchor="w", fill=accent, font=self._font(self._fs(0.72), bold=True))
            c.create_text(gx0 + 2, gy1 - 8, text="R", anchor="w", fill="#4dabf7", font=self._font(self._fs(0.72), bold=True))

            # Draw Stereo L (up) & R (down) decaying dub echo taps
            base_step = 0.045 + d_t * 0.16
            step_l = base_step * (2.0 if x2l else 1.0)
            step_r = base_step * (2.0 if x2r else 1.0)
            # Initial dry impulse at left
            c.create_line(gx0 + 12, mid_y - gh * 0.42, gx0 + 12, mid_y + gh * 0.42, fill="#ffffff", width=3)
            for ch_idx, (step, col, sign) in enumerate(((step_l, accent, -1), (step_r, "#4dabf7", +1))):
                amp = 0.40 + 0.08 * drv
                k = 1
                while True:
                    tx = gx0 + 12 + k * step * gw
                    if tx > gx1 or k > 18 or amp < 0.03:
                        break
                    c.create_line(tx, mid_y, tx, mid_y + sign * amp * gh, fill=col, width=2.6)
                    c.create_oval(tx - 3, mid_y + sign * amp * gh - 3, tx + 3, mid_y + sign * amp * gh + 3,
                                  fill="#ffffff", outline="")
                    amp *= (0.28 + fb * 0.68)
                    k += 1

            hx, hy = gx0 + d_t * gw, gy1 - fb * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, py0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "delaytime", "yk": "feedback"}))

        elif self.active_tab == "Filter":
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)
            gx0, gx1 = pad + 16, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 16
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)

            lc_n = self._norm(self._get_zctrl("cutoff"), 0.5)
            hc_n = self._norm(self._get_zctrl("highcut"), 0.3)
            res_n = self._norm(self._get_zctrl("resonance"), 0.4)
            c.create_text(gx0, vy0 + 11, text="Feedback Dub Filter  (Dual Nodes: L=LowCut, H=HighCut×Reso)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            for frac, flbl in ((0.10, "80"), (0.32, "300"), (0.55, "1.2k"), (0.78, "5k"), (0.94, "14k")):
                fx = gx0 + frac * gw
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            # Combine HP (cutoff) + LP (highcut) + resonance peak
            pts = []
            poly = [gx0, gy1]
            for i in range(65):
                t = i / 64.0
                hp = 1.0 / (1.0 + math.exp((lc_n - t) * 18.0))
                lp = 1.0 / (1.0 + math.exp((t - hc_n) * 18.0))
                peak = res_n * 0.45 * math.exp(-((t - hc_n) / 0.06) ** 2)
                lvl = max(0.03, min(0.96, 0.58 * hp * lp + peak * hp))
                px, py = gx0 + t * gw, gy1 - lvl * gh
                pts.extend([px, py])
                poly.extend([px, py])
            poly.extend([gx1, gy1])
            c.create_polygon(poly, fill="#2b2016", outline="")
            c.create_line(pts, fill=accent, width=2.8)

            lx, ly = gx0 + lc_n * gw, gy1 - 0.55 * gh
            hx, hy = gx0 + hc_n * gw, gy1 - res_n * gh
            c.create_oval(lx - 10, ly - 10, lx + 10, ly + 10, fill="#4dabf7", outline="#ffffff", width=2)
            c.create_text(lx, ly, text="L", fill="#0d0e12", font=self._font(self._fs(0.76), bold=True))
            c.create_oval(hx - 10, hy - 10, hx + 10, hy + 10, fill=accent, outline="#ffffff", width=2)
            c.create_text(hx, hy, text="H", fill="#0d0e12", font=self._font(self._fs(0.76), bold=True))
            self.hitboxes.append((pad, vy0, w - pad, vy1, "flt_dual", {
                "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                "lx": lx, "ly": ly, "hx": hx, "hy": hy,
            }))

        else:  # Dub Mix
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            mid_y = (gy0 + gy1) / 2.0

            dry_n = self._norm(self._get_zctrl("dry"), 0.5)
            wet_n = self._norm(self._get_zctrl("wet"), 0.45)
            drv_n = self._norm(self._get_zctrl("inputdrive"), 0.4)
            c.create_text(gx0, vy0 + 11, text="Dub Input Saturation & Dry/Wet Balance  (Drag 2D: X=Dry, Y=Wet)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            # Left: Input Saturation transfer curve
            split_x = gx0 + gw * 0.56
            c.create_line(split_x, gy0, split_x, gy1, fill=COL_GRID, dash=(3, 3))
            c.create_line(gx0, mid_y, split_x - 10, mid_y, fill=COL_GRID, dash=(2, 4))
            drv = 0.8 + drv_n * 6.5
            pts = []
            sw_c = max(20, split_x - 10 - gx0)
            for i in range(49):
                t = i / 48.0
                x_in = t * 2.0 - 1.0
                y_out = math.tanh(x_in * drv)
                pts.extend([gx0 + t * sw_c, mid_y - y_out * (gh * 0.44)])
            c.create_line(pts, fill="#ff922b", width=2.6)

            # Right: Dry & Wet level bars
            bar_w = max(22, (gx1 - split_x - 36) / 2.0)
            for idx, (blbl, bval, bcol) in enumerate((("DRY", dry_n, "#4dabf7"), ("WET", wet_n, accent))):
                bx0 = split_x + 14 + idx * (bar_w + 12)
                c.create_rectangle(bx0, gy0 + 4, bx0 + bar_w, gy1 - 14, fill="#13151b", outline=COL_BORDER)
                bh = bval * max(10, (gy1 - 14) - (gy0 + 4))
                c.create_rectangle(bx0 + 1, (gy1 - 14) - bh, bx0 + bar_w - 1, gy1 - 14, fill=bcol, outline="")
                c.create_text(bx0 + bar_w / 2, gy1 - 6, text=blbl, fill=COL_TEXT, font=self._font(self._fs(0.72), bold=True))

            hx, hy = gx0 + dry_n * gw, gy1 - wet_n * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "dry", "yk": "wet"}))

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
                if kind == "set_val":
                    k, val = payload
                    z = self._get_zctrl(k)
                    if z is not None:
                        z.set_value(val, send=True)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "step_sync":
                    z = self._get_zctrl("delaytimesync")
                    if z is not None:
                        cur = self._sync_idx(self._norm(z, 0.0))
                        nxt = (cur + int(payload)) % len(SYNC_DIVS)
                        z.set_value(SYNC_DIVS[nxt][1], send=True)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "flt_dual":
                    d_l = math.hypot(event.x - payload["lx"], event.y - payload["ly"])
                    d_h = math.hypot(event.x - payload["hx"], event.y - payload["hy"])
                    node = "low" if d_l <= d_h else "high"
                    tid = ("flt_dual", node)
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = ["cutoff"] if node == "low" else ["highcut", "resonance"]
                        for rk in rks:
                            z = self._get_zctrl(rk)
                            if z is not None:
                                z.set_value(z.value_default, send=True)
                        self.last_snapshot = None
                        self._draw()
                        return
                    self.last_tap = (tid, now)
                    target = dict(payload)
                    target["node"] = node
                    self.drag_target = ("flt_dual", target)
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
        elif kind == "flt_dual":
            nx = max(0.0, min(1.0, (x - p["gx0"]) / max(1.0, p["gx1"] - p["gx0"])))
            ny = max(0.0, min(1.0, (p["gy1"] - y) / max(1.0, p["gy1"] - p["gy0"])))
            if p["node"] == "low":
                self._set_norm(self._get_zctrl("cutoff"), nx)
            else:
                self._set_norm(self._get_zctrl("highcut"), nx)
                self._set_norm(self._get_zctrl("resonance"), ny)
        self.last_snapshot = None
        self._draw()


# Register hyphenated class alias required by Zynthian's widget loader for "Tal-Dub-3"
globals()["zynthian_widget_tal-dub-3"] = zynthian_widget_tal_dub_3
