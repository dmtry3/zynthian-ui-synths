#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Calf Transient Designer Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 3 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Shape | Filter | I/O & Adv   + LISTEN + ON/BYP
# Features:
#   - Live LV2 OutputPort metering (meter_inL/R, meter_outL/R, clip_inL/R, clip_outL/R)
#   - Shape: Transient shaper envelope comparing dry percussion pulse vs shaped
#     output with dual interactive 2D nodes: A (Atk Time x Boost) & R (Rel Time x Boost)
#   - Filter: 12/24/36 dB/oct detector HP/LP bandpass EQ with dual draggable nodes
#   - I/O & Adv: View mode selector, Lookahead, Sustain Threshold & live I/O bars
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
COL_ATK = "#ff922b"
COL_REL = "#51cf66"
COL_HP = "#4dabf7"
COL_LP = "#ff922b"
COL_CLIP = "#ff4d4f"
COL_LIVE = "#51cf66"

TABS = ["Shape", "Filter", "I/O & Adv"]
TAB_ACCENTS = {
    "Shape":     "#ff922b",
    "Filter":    "#4dabf7",
    "I/O & Adv": "#51cf66",
}

SLOPE_LABELS = ["Off", "12dB", "24dB", "36dB"]
VIEW_LABELS = ["Output", "Envelope", "Attack", "Release"]
LOG_KEYS = {"attack_time", "release_time", "hipass", "lopass", "level_in", "level_out", "sustain_threshold", "display"}
BIPOLAR_KEYS = {"attack_boost", "release_boost"}
LIVE_HOLD_S = 2.0


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.2f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


def fmt_ms(ms):
    return f"{ms / 1000.0:.2f}s" if ms >= 1000.0 else f"{ms:.0f}ms"


def fmt_db(gain):
    if gain <= 1e-5:
        return "-60dB"
    return f"{20.0 * math.log10(gain):+.1f}dB"


class zynthian_widget_calf_transient_designer(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Shape"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}
        self._tk_font_cache = {}

        # Live LV2 telemetry
        self._in_l = 0.0
        self._in_r = 0.0
        self._out_l = 0.0
        self._out_r = 0.0
        self._clip_in = False
        self._clip_out = False
        self._last_live_ts = 0.0

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
        if any(v is not None and v > 0.002 for v in (in_l, in_r, out_l, out_r)):
            self._last_live_ts = now
        self._in_l = max(0.0, min(1.0, in_l if in_l is not None else 0.0))
        self._in_r = max(0.0, min(1.0, in_r if in_r is not None else self._in_l))
        self._out_l = max(0.0, min(1.0, out_l if out_l is not None else 0.0))
        self._out_r = max(0.0, min(1.0, out_r if out_r is not None else self._out_l))
        self._clip_in = (self._get_mon("clip_inL", 0.0) >= 0.5) or (self._get_mon("clip_inR", 0.0) >= 0.5)
        self._clip_out = (self._get_mon("clip_outL", 0.0) >= 0.5) or (self._get_mon("clip_outR", 0.0) >= 0.5)
        return (now - self._last_live_ts) < LIVE_HOLD_S

    def _tab_items(self, tab):
        if tab == "Shape":
            return [
                ("attack_boost",  "Atk Boost"),
                ("attack_time",   "Atk Time"),
                ("release_boost", "Rel Boost"),
                ("release_time",  "Rel Time"),
            ]
        if tab == "Filter":
            return [
                ("hipass",  "Highpass"),
                ("hp_mode", "HP Slope"),
                ("lopass",  "Lowpass"),
                ("lp_mode", "LP Slope"),
            ]
        return [
            ("mix",               "Mix"),
            ("lookahead",         "Lookahead"),
            ("sustain_threshold", "Sust Thr"),
            ("level_out",         "Out Gain"),
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
            logging.debug(f"Calf Transient sync error: {e}")

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
        if getattr(z, "is_integer", False) or key in ("hp_mode", "lp_mode", "lookahead", "view"):
            val = int(round(val))
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_calf_transient_designer._raw(z)
        if key in ("attack_boost", "release_boost"):
            return f"{int(round(v * 100)):+d}%"
        if key in ("attack_time", "release_time", "display"):
            return fmt_ms(v)
        if key in ("hipass", "lopass"):
            return fmt_hz(v)
        if key in ("hp_mode", "lp_mode"):
            return SLOPE_LABELS[max(0, min(3, int(round(v))))]
        if key == "lookahead":
            return f"{int(round(v))}smp"
        if key == "mix":
            return f"{int(round(v * 100))}%"
        if key in ("level_in", "level_out", "sustain_threshold"):
            return fmt_db(v)
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
        is_live = self._update_telemetry(now)
        keys = ("bypass", "listen", "level_in", "level_out", "mix", "attack_time", "attack_boost",
                "sustain_threshold", "release_time", "release_boost", "lookahead", "view",
                "hipass", "lopass", "hp_mode", "lp_mode")
        mon = (is_live, round(self._in_l, 2), round(self._out_l, 2), self._clip_in, self._clip_out) if is_live else (False,)
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

    def _draw_io_meters(self, c, mx0, my0, mx1, my1):
        c.create_rectangle(mx0, my0, mx1, my1, fill=COL_PANEL, outline=COL_BORDER)
        mw = max(24, mx1 - mx0)
        top, bot = my0 + 18, my1 - 20
        mh = max(20, bot - top)
        col_w = max(6, (mw - 18) / 4.0)
        c.create_text(mx0 + mw * 0.27, my0 + 9, text="IN", fill="#4dabf7", font=self._font(self._fs(0.68), bold=True))
        c.create_text(mx0 + mw * 0.73, my0 + 9, text="OUT", fill="#51cf66", font=self._font(self._fs(0.68), bold=True))
        for i, (lvl, col) in enumerate(((self._in_l, "#4dabf7"), (self._in_r, "#4dabf7"),
                                        (self._out_l, "#51cf66"), (self._out_r, "#51cf66"))):
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
        lstn = self._raw(self._get_zctrl("listen")) >= 0.5

        hdr_h = max(36, min(46, int(h * 0.11)))
        lst_w = 56
        byp_w = 62
        tabs_w = w - 2 * pad - lst_w - byp_w - 2 * gap
        tw = (tabs_w - 2 * gap) / 3.0
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        lx0 = w - pad - byp_w - gap - lst_w
        self._draw_pill(lx0, pad, lx0 + lst_w, pad + hdr_h, "SC", lstn, "#ffd43b", "toggle", "listen")
        self._draw_pill(w - pad - byp_w, pad, w - pad, pad + hdr_h,
                        "BYP" if byp else "ON ●", not byp, "#51cf66", "toggle", "bypass")

        bot_h = 96
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap

        if self.active_tab == "Shape":
            mtr_w = 62
            px1 = w - pad - mtr_w - gap
            c.create_rectangle(pad, vy0, px1, vy1, fill=COL_PANEL, outline=accent if not byp else COL_BORDER)
            self._draw_io_meters(c, px1 + gap, vy0, w - pad, vy1)

            gx0, gx1 = pad + 14, px1 - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            c.create_text(gx0, vy0 + 11, text="Transient Shaper  (Dual Nodes: A=Attack, R=Release · 2xTap=0%)",
                          anchor="w", fill=COL_DIM, font=self._fit_font(
                              "Transient Shaper  (Dual Nodes: A=Attack, R=Release · 2xTap=0%)",
                              gw, self._fs(0.75), bold=True))

            atk_b = self._raw(self._get_zctrl("attack_boost"), 0.0)   # -1..1
            rel_b = self._raw(self._get_zctrl("release_boost"), 0.0)  # -1..1
            atk_n = self._norm(self._get_zctrl("attack_time"), "attack_time", 0.5)
            rel_n = self._norm(self._get_zctrl("release_time"), "release_time", 0.5)
            mix = self._raw(self._get_zctrl("mix"), 1.0)

            # Dry reference drum hit vs shaped transient envelope
            atk_span = 0.06 + atk_n * 0.24
            rel_tau = 0.10 + rel_n * 0.42
            dry_pts, wet_pts = [], []
            wet_poly = [gx0, gy1]
            for i in range(81):
                t = i / 80.0
                if t < 0.04:
                    dry = (t / 0.04) * 0.62
                else:
                    dt = t - 0.04
                    dry = 0.62 * math.exp(-dt / 0.22)
                if byp:
                    shaped = dry
                else:
                    # Attack window affects initial hit, release affects sustain tail
                    w_atk = math.exp(-((max(0.0, t - 0.04)) / max(0.03, atk_span)) ** 1.6)
                    w_rel = 1.0 - w_atk
                    gain_atk = 1.0 + atk_b * 0.72 * w_atk
                    gain_rel = max(0.05, 1.0 + rel_b * 0.85 * w_rel * math.exp(-max(0.0, t - 0.04 - atk_span) / max(0.08, rel_tau)))
                    wet = dry * max(0.05, gain_atk) * gain_rel
                    if rel_b > 0.0 and t > 0.04:
                        # Positive sustain lifts tail smoothly
                        wet = max(wet, dry * (1.0 + rel_b * 1.15 * w_rel) * math.exp(-max(0.0, t - 0.04) / (0.22 + rel_b * 0.35 * rel_n)))
                    shaped = (1.0 - mix) * dry + mix * wet
                px = gx0 + t * gw
                py_d = gy1 - max(0.0, min(0.96, dry)) * gh
                py_w = gy1 - max(0.0, min(0.96, shaped)) * gh
                dry_pts.extend([px, py_d])
                wet_pts.extend([px, py_w])
                wet_poly.extend([px, py_w])
            wet_poly.extend([gx1, gy1])

            c.create_polygon(wet_poly, fill="#261e16" if not byp else "#1e2028", outline="")
            c.create_line(dry_pts, fill="#555a70", width=1.6, dash=(3, 3))
            c.create_line(wet_pts, fill=accent if not byp else COL_DIM, width=2.8)

            # Dual interactive nodes: A (Attack Time x Boost) & R (Release Time x Boost)
            ax = gx0 + (0.08 + atk_n * 0.34) * gw
            ay = gy1 - ((atk_b + 1.0) * 0.5) * gh
            rx = gx0 + (0.48 + rel_n * 0.44) * gw
            ry = gy1 - ((rel_b + 1.0) * 0.5) * gh
            c.create_line(ax, gy0, ax, gy1, fill="#4d321c", dash=(2, 3))
            c.create_line(rx, gy0, rx, gy1, fill="#1f422a", dash=(2, 3))
            c.create_oval(ax - 11, ay - 11, ax + 11, ay + 11, fill=COL_ATK, outline="#ffffff", width=2)
            c.create_text(ax, ay, text="A", fill="#0d0e12", font=self._font(self._fs(0.76), bold=True))
            c.create_oval(rx - 11, ry - 11, rx + 11, ry + 11, fill=COL_REL, outline="#ffffff", width=2)
            c.create_text(rx, ry, text="R", fill="#0d0e12", font=self._font(self._fs(0.76), bold=True))

            self.hitboxes.append((pad, vy0, px1, vy1, "shape_dual", {
                "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "gw": gw,
                "ax": ax, "ay": ay, "rx": rx, "ry": ry,
            }))

        elif self.active_tab == "Filter":
            r2_h = 34
            hp_m = max(0, min(3, int(round(self._raw(self._get_zctrl("hp_mode"), 0.0)))))
            lp_m = max(0, min(3, int(round(self._raw(self._get_zctrl("lp_mode"), 0.0)))))
            bw = (w - 2 * pad - 2 * gap) / 3.0
            self._draw_pill(pad, vy0, pad + bw, vy0 + r2_h, f"HP: {SLOPE_LABELS[hp_m]}", hp_m > 0, COL_HP, "cycle_slope", "hp_mode")
            self._draw_pill(pad + bw + gap, vy0, pad + 2 * bw + gap, vy0 + r2_h, f"LP: {SLOPE_LABELS[lp_m]}", lp_m > 0, COL_LP, "cycle_slope", "lp_mode")
            self._draw_pill(pad + 2 * (bw + gap), vy0, w - pad, vy0 + r2_h,
                            "SC Listen: ON" if lstn else "SC Listen: OFF", lstn, "#ffd43b", "toggle", "listen")

            py0 = vy0 + r2_h + gap
            c.create_rectangle(pad, py0, w - pad, vy1, fill=COL_PANEL, outline=accent)
            gx0, gx1 = pad + 18, w - pad - 14
            gy0, gy1 = py0 + 22, vy1 - 16
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            c.create_text(gx0, py0 + 11, text="Detector Sidechain Filter  (Drag HP Blue / LP Orange nodes)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.76), bold=True))

            hp_hz = max(20.0, self._raw(self._get_zctrl("hipass"), 100.0))
            lp_hz = max(20.0, self._raw(self._get_zctrl("lopass"), 5000.0))
            f_min, f_max = 20.0, 20000.0
            log_span = math.log(f_max / f_min)

            def hz_to_x(hz):
                hz = max(f_min, min(f_max, hz))
                return gx0 + (math.log(hz / f_min) / log_span) * gw

            for f_hz, flbl in ((50, "50"), (200, "200"), (1000, "1k"), (4000, "4k"), (12000, "12k")):
                fx = hz_to_x(f_hz)
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            pts = []
            poly = [gx0, gy1]
            for i in range(73):
                t = i / 72.0
                f = f_min * ((f_max / f_min) ** t)
                g = 1.0
                if hp_m > 0:
                    g *= 1.0 / math.sqrt(1.0 + (hp_hz / f) ** (2 * hp_m * 2))
                if lp_m > 0:
                    g *= 1.0 / math.sqrt(1.0 + (f / lp_hz) ** (2 * lp_m * 2))
                px, py = gx0 + t * gw, gy1 - max(0.02, g * 0.88) * gh
                pts.extend([px, py])
                poly.extend([px, py])
            poly.extend([gx1, gy1])
            c.create_polygon(poly, fill="#192c3e" if (hp_m or lp_m) else "#1e2028", outline="")
            c.create_line(pts, fill=accent if (hp_m or lp_m) else COL_DIM, width=2.8)

            hpx, hpy = hz_to_x(hp_hz), gy0 + gh * 0.42
            lpx, lpy = hz_to_x(lp_hz), gy0 + gh * 0.42
            c.create_oval(hpx - 10, hpy - 10, hpx + 10, hpy + 10, fill=COL_HP if hp_m else COL_PANEL,
                          outline="#ffffff" if hp_m else COL_HP, width=2)
            c.create_text(hpx, hpy, text="HP", fill="#0d0e12" if hp_m else COL_HP, font=self._font(self._fs(0.68), bold=True))
            c.create_oval(lpx - 10, lpy - 10, lpx + 10, lpy + 10, fill=COL_LP if lp_m else COL_PANEL,
                          outline="#ffffff" if lp_m else COL_LP, width=2)
            c.create_text(lpx, lpy, text="LP", fill="#0d0e12" if lp_m else COL_LP, font=self._font(self._fs(0.68), bold=True))
            self.hitboxes.append((pad, py0, w - pad, vy1, "flt_dual", {
                "gx0": gx0, "gx1": gx1, "hpx": hpx, "hpy": hpy, "lpx": lpx, "lpy": lpy,
            }))

        else:  # I/O & Adv
            r2_h = 34
            vw = max(0, min(3, int(round(self._raw(self._get_zctrl("view"), 0.0)))))
            bw = (w - 2 * pad - 3 * gap) / 4.0
            for i, vlbl in enumerate(VIEW_LABELS):
                x0 = pad + i * (bw + gap)
                self._draw_pill(x0, vy0, x0 + bw, vy0 + r2_h, vlbl, i == vw, accent, "set_int", ("view", i))

            py0 = vy0 + r2_h + gap
            c.create_rectangle(pad, py0, w - pad, vy1, fill=COL_PANEL, outline=accent)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = py0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            c.create_text(gx0, py0 + 11, text="Live I/O Levels & Parallel Mix  (Drag 2D: X=Mix, Y=Out Gain)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.76), bold=True))

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

            hx = gx0 + self._norm(self._get_zctrl("mix"), "mix") * gw
            hy = gy1 - self._norm(self._get_zctrl("level_out"), "level_out") * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, py0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "mix", "yk": "level_out"}))

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
                if kind == "cycle_slope":
                    z = self._get_zctrl(payload)
                    if z is not None:
                        cur = int(round(self._raw(z, 0.0)))
                        z.set_value((cur + 1) % 4, send=True)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "shape_dual":
                    d_a = math.hypot(event.x - payload["ax"], event.y - payload["ay"])
                    d_r = math.hypot(event.x - payload["rx"], event.y - payload["ry"])
                    node = "atk" if d_a <= d_r else "rel"
                    tid = ("shape_dual", node)
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = ["attack_time", "attack_boost"] if node == "atk" else ["release_time", "release_boost"]
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
                    self.drag_target = ("shape_dual", target)
                    self._apply_drag(event.x, event.y)
                    return
                if kind == "flt_dual":
                    d_hp = abs(event.x - payload["hpx"])
                    d_lp = abs(event.x - payload["lpx"])
                    k = "hipass" if d_hp <= d_lp else "lopass"
                    tid = ("flt_dual", k)
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        z = self._get_zctrl(k)
                        if z is not None:
                            z.set_value(z.value_default, send=True)
                        self.last_snapshot = None
                        self._draw()
                        return
                    self.last_tap = (tid, now)
                    self.drag_target = ("flt_dual", {"key": k, "gx0": payload["gx0"], "gx1": payload["gx1"]})
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
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]), p["key"])
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]), p["xk"])
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]), p["yk"])
        elif kind == "shape_dual":
            ny = max(0.0, min(1.0, (p["gy1"] - y) / max(1.0, p["gy1"] - p["gy0"])))
            if p["node"] == "atk":
                nx = max(0.0, min(1.0, ((x - p["gx0"]) / max(1.0, p["gw"]) - 0.08) / 0.34))
                self._set_norm(self._get_zctrl("attack_time"), nx, "attack_time")
                self._set_norm(self._get_zctrl("attack_boost"), ny, "attack_boost")
            else:
                nx = max(0.0, min(1.0, ((x - p["gx0"]) / max(1.0, p["gw"]) - 0.48) / 0.44))
                self._set_norm(self._get_zctrl("release_time"), nx, "release_time")
                self._set_norm(self._get_zctrl("release_boost"), ny, "release_boost")
        elif kind == "flt_dual" and p["gx1"] > p["gx0"]:
            nx = max(0.0, min(1.0, (x - p["gx0"]) / (p["gx1"] - p["gx0"])))
            self._set_norm(self._get_zctrl(p["key"]), nx, p["key"])
        self.last_snapshot = None
        self._draw()
