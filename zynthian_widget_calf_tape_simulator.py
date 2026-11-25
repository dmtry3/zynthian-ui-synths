#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Calf Tape Simulator Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 3 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Tape | Filter | I/O   + ON/BYP
# Features:
#   - Live LV2 OutputPort metering (meter_inL/R, meter_outL/R, clip_inL/R, clip_outL/R)
#   - Tape: Animated twin Reel-to-Reel tape deck (Slow 7.5 ips / Fast 15 ips),
#     Magnetical & Post-Filter switches, Mechanical flutter + Tape Noise scope
#   - Filter: Magnetic head HF rolloff & speed head-bump curve (2D: Filter x Mix)
#   - I/O: Live IN/OUT stereo VU meters + Clip LEDs (2D: In Drive x Out Gain)
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
COL_CLIP = "#ff4d4f"
COL_LIVE = "#51cf66"

TABS = ["Tape", "Filter", "I/O"]
TAB_ACCENTS = {
    "Tape":   "#ff922b",
    "Filter": "#4dabf7",
    "I/O":    "#51cf66",
}

LOG_KEYS = {"level_in", "level_out", "lowpass"}
LIVE_HOLD_S = 2.0


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.2f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


def fmt_db(gain):
    if gain <= 1e-5:
        return "-36dB"
    return f"{20.0 * math.log10(gain):+.1f}dB"


class zynthian_widget_calf_tape_simulator(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Tape"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}
        self._tk_font_cache = {}

        # Live LV2 telemetry & reel angle
        self._in_l = 0.0
        self._in_r = 0.0
        self._out_l = 0.0
        self._out_r = 0.0
        self._clip_in = False
        self._clip_out = False
        self._last_live_ts = 0.0
        self._reel_angle = 0.0
        self._last_tick = time.monotonic()

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
        dt = max(0.001, min(0.25, now - self._last_tick))
        self._last_tick = now

        in_l = self._get_mon("meter_inL")
        in_r = self._get_mon("meter_inR")
        out_l = self._get_mon("meter_outL")
        out_r = self._get_mon("meter_outR")
        if any(v is not None and v > 0.002 for v in (in_l, in_r, out_l, out_r)):
            self._last_live_ts = now
        self._in_l = max(0.0, min(1.0, in_l if in_l is not None else 0.0))
        self._in_r = max(0.0, min(1.0, in_r if in_r is not None else self._in_l))
        self._out_l = max(0.0, min(1.0, out_l if out_l is not None else 0.0))
        self._out_r = max(0.0, min(1.0, out_r if out_r is not None else self._out_l))
        self._clip_in = (self._get_mon("clip_inL", 0.0) >= 0.5) or (self._get_mon("clip_inR", 0.0) >= 0.5)
        self._clip_out = (self._get_mon("clip_outL", 0.0) >= 0.5) or (self._get_mon("clip_outR", 0.0) >= 0.5)

        is_live = (now - self._last_live_ts) < LIVE_HOLD_S
        byp = self._raw(self._get_zctrl("bypass")) >= 0.5
        fast = self._raw(self._get_zctrl("speed"), 1.0) >= 0.5
        if is_live and not byp:
            self._reel_angle = (self._reel_angle + dt * (3.2 if fast else 1.6)) % (math.pi * 2.0)
        return is_live

    def _tab_items(self, tab):
        if tab == "Tape":
            return [
                ("level_in",   "In Drive"),
                ("lowpass",    "Filter"),
                ("mechanical", "Mechancl"),
                ("noise",      "Noise"),
            ]
        if tab == "Filter":
            return [
                ("lowpass",   "Filter"),
                ("mix",       "Mix"),
                ("level_in",  "In Drive"),
                ("level_out", "Out Gain"),
            ]
        return [
            ("level_in",  "In Gain"),
            ("level_out", "Out Gain"),
            ("mix",       "Mix"),
            ("noise",     "Noise"),
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
            logging.debug(f"Calf Tape Sim sync error: {e}")

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
        if getattr(z, "is_integer", False) or key == "speed":
            val = int(round(val))
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_calf_tape_simulator._raw(z)
        if key in ("level_in", "level_out"):
            return fmt_db(v)
        if key == "lowpass":
            return fmt_hz(v)
        return f"{int(round(v * 100))}%"

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
        is_live = self._update_telemetry(now)
        keys = ("bypass", "level_in", "level_out", "mix", "lowpass", "speed", "noise", "mechanical", "magnetical", "post")
        mon = (is_live, round(self._in_l, 2), round(self._out_l, 2), self._clip_in, self._clip_out,
               round(self._reel_angle, 1)) if is_live else (False,)
        snap = (self.width, self.height, self.active_tab,
                tuple(round(self._raw(self._get_zctrl(k)), 3) for k in keys), mon)
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
        n = self._norm(z, key)
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

    def _draw_reel(self, c, cx, cy, rad, angle, col):
        c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, fill="#161820", outline=col, width=2)
        c.create_oval(cx - rad * 0.72, cy - rad * 0.72, cx + rad * 0.72, cy + rad * 0.72,
                      fill="#231c17", outline="#4a382b", width=1)
        for k in range(3):
            a = angle + k * (2.0 * math.pi / 3.0)
            c.create_line(cx + rad * 0.22 * math.cos(a), cy + rad * 0.22 * math.sin(a),
                          cx + rad * 0.86 * math.cos(a), cy + rad * 0.86 * math.sin(a),
                          fill="#c9cdd8", width=2.4)
        c.create_oval(cx - rad * 0.22, cy - rad * 0.22, cx + rad * 0.22, cy + rad * 0.22,
                      fill="#383c4e", outline="#ffffff", width=1.4)

    def _draw_io_meters(self, c, mx0, my0, mx1, my1):
        c.create_rectangle(mx0, my0, mx1, my1, fill=COL_PANEL, outline=COL_BORDER)
        mw = max(24, mx1 - mx0)
        top, bot = my0 + 18, my1 - 20
        mh = max(20, bot - top)
        col_w = max(6, (mw - 18) / 4.0)
        c.create_text(mx0 + mw * 0.27, my0 + 9, text="IN", fill="#4dabf7", font=self._font(self._fs(0.68), bold=True))
        c.create_text(mx0 + mw * 0.73, my0 + 9, text="OUT", fill="#ff922b", font=self._font(self._fs(0.68), bold=True))
        for i, (lvl, col) in enumerate(((self._in_l, "#4dabf7"), (self._in_r, "#4dabf7"),
                                        (self._out_l, "#ff922b"), (self._out_r, "#ff922b"))):
            bx0 = mx0 + 5 + i * (col_w + 2) + (4 if i >= 2 else 0)
            c.create_rectangle(bx0, top, bx0 + col_w, bot, fill="#121318", outline="")
            if lvl > 0.01:
                bh = min(1.0, lvl) * mh
                c.create_rectangle(bx0, bot - bh, bx0 + col_w, bot, fill=col, outline="")
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

        pad, gap = 6, 6
        accent = TAB_ACCENTS[self.active_tab]
        byp = self._raw(self._get_zctrl("bypass")) >= 0.5
        fast = self._raw(self._get_zctrl("speed"), 1.0) >= 0.5
        mag = self._raw(self._get_zctrl("magnetical"), 1.0) >= 0.5
        post = self._raw(self._get_zctrl("post"), 0.0) >= 0.5

        hdr_h = max(36, min(46, int(h * 0.11)))
        byp_w = 66
        tabs_w = w - 2 * pad - byp_w - gap
        tw = (tabs_w - 2 * gap) / 3.0
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        self._draw_pill(w - pad - byp_w, pad, w - pad, pad + hdr_h,
                        "BYP" if byp else "ON ●", not byp, "#51cf66", "toggle", "bypass")

        bot_h = 96
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap

        if self.active_tab == "Tape":
            r2_h = 34
            bw = (w - 2 * pad - 3 * gap) / 4.0
            self._draw_pill(pad, vy0, pad + bw, vy0 + r2_h, "Slow 7.5ips", not fast, accent, "set_int", ("speed", 0))
            self._draw_pill(pad + bw + gap, vy0, pad + 2 * bw + gap, vy0 + r2_h, "Fast 15ips", fast, accent, "set_int", ("speed", 1))
            self._draw_pill(pad + 2 * (bw + gap), vy0, pad + 3 * bw + 2 * gap, vy0 + r2_h, "Magnetical", mag, "#ffd43b", "toggle", "magnetical")
            self._draw_pill(pad + 3 * (bw + gap), vy0, w - pad, vy0 + r2_h, "Post-Flt", post, "#4dabf7", "toggle", "post")

            py0 = vy0 + r2_h + gap
            mtr_w = 62
            px1 = w - pad - mtr_w - gap
            c.create_rectangle(pad, py0, px1, vy1, fill=COL_PANEL, outline=accent if not byp else COL_BORDER)
            self._draw_io_meters(c, px1 + gap, py0, w - pad, vy1)

            gx0, gx1 = pad + 14, px1 - 14
            gy0, gy1 = py0 + 22, vy1 - 12
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            c.create_text(gx0, py0 + 11, text="Reel-to-Reel Deck  (Drag 2D: X=Mechanical Flutter, Y=Tape Noise)",
                          anchor="w", fill=COL_DIM, font=self._fit_font(
                              "Reel-to-Reel Deck  (Drag 2D: X=Mechanical Flutter, Y=Tape Noise)",
                              gw, self._fs(0.75), bold=True))

            # Draw Twin Reels in upper 62% & Tape Strip Flutter/Noise wave in lower 38%
            reel_r = min(gw * 0.16, gh * 0.34)
            rcy = gy0 + reel_r + 4
            rlx = gx0 + gw * 0.28
            rrx = gx0 + gw * 0.72
            # Tape path between reels & magnetic head
            head_y = rcy + reel_r * 0.92
            c.create_line(rlx, rcy + reel_r, (rlx + rrx) / 2.0, head_y, rrx, rcy + reel_r,
                          fill="#8a5a36" if not byp else COL_DIM, width=2.4)
            c.create_rectangle((rlx + rrx) / 2.0 - 12, head_y - 5, (rlx + rrx) / 2.0 + 12, head_y + 5,
                               fill="#ffd43b" if mag else "#383c4e", outline=COL_BORDER)
            self._draw_reel(c, rlx, rcy, reel_r, self._reel_angle, accent if not byp else COL_DIM)
            self._draw_reel(c, rrx, rcy, reel_r, self._reel_angle * 1.08, accent if not byp else COL_DIM)

            # Mechanical flutter + Noise strip at bottom
            mech = self._norm(self._get_zctrl("mechanical"), "mechanical", 0.2)
            noi = self._norm(self._get_zctrl("noise"), "noise", 0.1)
            wave_y = gy1 - gh * 0.18
            pts = []
            for i in range(65):
                t = i / 64.0
                wobble = mech * 0.14 * gh * math.sin(t * math.pi * 6.0 + self._reel_angle)
                grain = noi * 0.10 * gh * math.sin(i * 17.3) * math.cos(i * 9.1)
                pts.extend([gx0 + t * gw, wave_y + wobble + grain])
            c.create_line(pts, fill="#ffa94d" if not byp else COL_DIM, width=2.0)

            hx, hy = gx0 + mech * gw, gy1 - noi * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, py0, px1, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "mechanical", "yk": "noise"}))

        elif self.active_tab == "Filter":
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent if not byp else COL_BORDER)
            gx0, gx1 = pad + 18, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 16
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            lp_hz = max(1000.0, self._raw(self._get_zctrl("lowpass"), 12500.0))
            mix = self._norm(self._get_zctrl("mix"), "mix", 1.0)
            c.create_text(gx0, vy0 + 11, text=f"Magnetic Head Filter [{'Post' if post else 'Pre'} · {'15ips' if fast else '7.5ips'}]  (2D: Filter × Mix)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.76), bold=True))

            f_min, f_max = 40.0, 22000.0
            log_span = math.log(f_max / f_min)
            for f_hz, flbl in ((80, "80"), (250, "250"), (1000, "1k"), (4000, "4k"), (12000, "12k")):
                fx = gx0 + (math.log(f_hz / f_min) / log_span) * gw
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            bump_hz = 110.0 if fast else 65.0
            pts = []
            poly = [gx0, gy1]
            for i in range(65):
                t = i / 64.0
                f = f_min * ((f_max / f_min) ** t)
                bump = (0.14 if mag else 0.04) * math.exp(-((math.log2(f / bump_hz)) ** 2) / 0.45)
                lp = 1.0 / math.sqrt(1.0 + (f / lp_hz) ** 4)
                lvl = (1.0 - mix) * 0.65 + mix * (0.65 + bump) * lp
                px, py = gx0 + t * gw, gy1 - max(0.03, min(0.95, lvl)) * gh
                pts.extend([px, py])
                poly.extend([px, py])
            poly.extend([gx1, gy1])
            c.create_polygon(poly, fill="#192c3e", outline="")
            c.create_line(pts, fill=accent if not byp else COL_DIM, width=2.8)

            hx = gx0 + self._norm(self._get_zctrl("lowpass"), "lowpass") * gw
            hy = gy1 - mix * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "lowpass", "yk": "mix"}))

        else:  # I/O
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent if not byp else COL_BORDER)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            c.create_text(gx0, vy0 + 11, text="Tape I/O Staging  (Drag 2D: X=In Drive, Y=Out Gain)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            mx = (gx0 + gx1) / 2.0
            bar_w = max(22, gw * 0.12)
            for bx0, lvl, col, lbl in (
                (mx - 2 * bar_w - 20, self._in_l,  "#4dabf7", "In L"),
                (mx - bar_w - 12,     self._in_r,  "#4dabf7", "In R"),
                (mx + 12,             self._out_l, accent,    "Out L"),
                (mx + bar_w + 20,     self._out_r, accent,    "Out R"),
            ):
                c.create_rectangle(bx0, gy0, bx0 + bar_w, gy1, fill="#13151b", outline=COL_GRID)
                if lvl > 0.01:
                    c.create_rectangle(bx0 + 1, gy1 - min(1.0, lvl) * gh, bx0 + bar_w - 1, gy1, fill=col, outline="")
                c.create_text(bx0 + bar_w / 2, gy1 - 10, text=lbl, fill=COL_TEXT, font=self._font(self._fs(0.72), bold=True))

            hx = gx0 + self._norm(self._get_zctrl("level_in"), "level_in") * gw
            hy = gy1 - self._norm(self._get_zctrl("level_out"), "level_out") * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "level_in", "yk": "level_out"}))

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
                if kind == "set_int":
                    k, val = payload
                    z = self._get_zctrl(k)
                    if z is not None:
                        z.set_value(int(val), send=True)
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
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]), p["key"])
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]), p["xk"])
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]), p["yk"])
        self.last_snapshot = None
        self._draw()
