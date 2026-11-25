#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Calf Stereo Tools Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 4 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Stereo | M/S | Matrix | I/O   + ON/BYP
# Features:
#   - Real LV2 OutputPort telemetry (meter_inL/R, meter_outL/R, clip_inL/R,
#     clip_outL/R, meter_phase correlation)
#   - Interactive goniometer / stereo-field vectorscope with live L/R trace,
#     dedicated Phase Correlation Meter (-1..0..+1), and L/R output meters
#   - 2D Mid/Side stage pad, 7-mode stereo matrix + Mute/Phase/Softclip
#   - Live Input & Output L/R metering on I/O balance tab
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
COL_WARN = "#ffd43b"
COL_CLIP = "#ff4d4f"

TABS = ["Stereo", "M/S", "Matrix", "I/O"]
TAB_ACCENTS = {
    "Stereo": "#cc5de8",
    "M/S":    "#4dabf7",
    "Matrix": "#ffd43b",
    "I/O":    "#51cf66",
}

MATRIX_MODES = [
    "LR > LR",
    "LR > MS",
    "MS > LR",
    "LR > LL",
    "LR > RR",
    "LR > L+R",
    "LR > RL",
]

LOG_KEYS = {"level_in", "level_out", "mlev", "slev", "sc_level"}
BIPOLAR_KEYS = {"balance_in", "balance_out", "sbal", "mpan", "stereo_base", "delay"}
LIVE_HOLD_S = 2.0


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_db(gain):
    if gain <= 1e-5:
        return "-inf"
    return f"{20.0 * math.log10(gain):+.1f}dB"


def fmt_pan(v):
    if abs(v) < 0.02:
        return "Center"
    return f"L{int(round(-v * 100))}%" if v < 0 else f"R{int(round(v * 100))}%"


class zynthian_widget_calf_stereo_tools(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Stereo"
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
        self._clip_in_l = False
        self._clip_in_r = False
        self._clip_out_l = False
        self._clip_out_r = False
        self._phase_corr = 1.0  # -1.0 .. +1.0 (from meter_phase 0..1)
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
        m_ph = self._get_mon("meter_phase")

        has_signal = any(v is not None and v > 0.002 for v in (in_l, in_r, out_l, out_r))
        if has_signal:
            self._last_live_ts = now

        self._in_l = max(0.0, min(1.0, in_l if in_l is not None else 0.0))
        self._in_r = max(0.0, min(1.0, in_r if in_r is not None else self._in_l))
        self._out_l = max(0.0, min(1.0, out_l if out_l is not None else 0.0))
        self._out_r = max(0.0, min(1.0, out_r if out_r is not None else self._out_l))
        self._clip_in_l = self._get_mon("clip_inL", 0.0) >= 0.5
        self._clip_in_r = self._get_mon("clip_inR", 0.0) >= 0.5
        self._clip_out_l = self._get_mon("clip_outL", 0.0) >= 0.5
        self._clip_out_r = self._get_mon("clip_outR", 0.0) >= 0.5

        is_live = (now - self._last_live_ts) < LIVE_HOLD_S
        if is_live and m_ph is not None:
            # Calf meter_phase is 0..1 -> correlation -1..+1
            self._phase_corr = max(-1.0, min(1.0, 2.0 * m_ph - 1.0))
        else:
            # Predictive phase correlation from current Stereo Base, Phase, and Polarity switches
            ph_l = self._raw(self._get_zctrl("phasel")) >= 0.5
            ph_r = self._raw(self._get_zctrl("phaser")) >= 0.5
            pol = -1.0 if (ph_l != ph_r) else 1.0
            base = self._raw(self._get_zctrl("stereo_base"), 0.0)
            ph_rad = math.radians(self._raw(self._get_zctrl("stereo_phase"), 0.0))
            self._phase_corr = max(-1.0, min(1.0, pol * math.cos(ph_rad) * (1.0 - 0.55 * max(0.0, base))))
        return is_live

    def _tab_items(self, tab):
        if tab == "Stereo":
            return [
                ("stereo_base",  "Base"),
                ("stereo_phase", "Phase"),
                ("delay",        "L/R Delay"),
                ("sc_level",     "S/C Lvl"),
            ]
        if tab == "M/S":
            return [
                ("mlev", "Mid Gain"),
                ("mpan", "Mid Pan"),
                ("slev", "Side Gain"),
                ("sbal", "Side Bal"),
            ]
        if tab == "Matrix":
            return [
                ("mode",        "Mode"),
                ("stereo_base", "Base"),
                ("balance_in",  "In Bal"),
                ("balance_out", "Out Bal"),
            ]
        return [
            ("level_in",    "In Gain"),
            ("balance_in",  "In Bal"),
            ("level_out",   "Out Gain"),
            ("balance_out", "Out Bal"),
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
            logging.debug(f"Calf Stereo Tools sync error: {e}")

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
        if getattr(z, "is_integer", False) or key == "mode":
            val = int(round(val))
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_calf_stereo_tools._raw(z)
        if key in ("level_in", "level_out", "mlev", "slev"):
            return fmt_db(v)
        if key in ("balance_in", "balance_out", "mpan", "sbal"):
            return fmt_pan(v)
        if key == "stereo_base":
            return f"{v:+.2f}"
        if key == "stereo_phase":
            return f"{int(round(v))}°"
        if key == "delay":
            return f"{v:+.1f}ms"
        if key == "sc_level":
            return f"{v:.1f}x"
        if key == "mode":
            idx = max(0, min(len(MATRIX_MODES) - 1, int(round(v))))
            return MATRIX_MODES[idx]
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
        keys = ("bypass", "level_in", "level_out", "balance_in", "balance_out",
                "softclip", "mutel", "muter", "phasel", "phaser", "mode",
                "slev", "sbal", "mlev", "mpan", "stereo_base", "delay", "sc_level", "stereo_phase")
        mon_snap = (
            is_live, round(self._out_l, 2), round(self._out_r, 2),
            round(self._in_l, 2), round(self._in_r, 2),
            round(self._phase_corr, 2), self._clip_out_l, self._clip_out_r,
        ) if (is_live and self.active_tab in ("Stereo", "M/S", "I/O")) else (is_live, round(self._phase_corr, 2))
        snap = (self.width, self.height, self.active_tab,
                tuple(round(self._raw(self._get_zctrl(k)), 3) for k in keys), mon_snap)
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
            if tf is None:
                break
            if tf.measure(txt) <= max_w:
                break
            s -= 1
        return self._font(s, bold=bold)

    def _fs(self, scale=1.0):
        base = max(9, min(13, self.height // 34))
        return max(8, int(round(base * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        fnt = self._fit_font(text, max(16, (x1 - x0) - 6), self._fs(0.86), bold=True)
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
        lbl_f = self._fit_font(label, avail * 0.50, self._fs(0.82), bold=False)
        val_f = self._fit_font(val_txt, avail * 0.50, self._fs(0.86), bold=True)
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM, font=lbl_f)
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=val_txt, anchor="e", fill=COL_TEXT, font=val_f)
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

    def _draw_phase_bar(self, c, x0, y0, x1, y1, corr):
        c.create_rectangle(x0, y0, x1, y1, fill="#121318", outline=COL_BORDER, width=1)
        mx = (x0 + x1) / 2.0
        half_w = (x1 - x0) / 2.0
        px = mx + max(-1.0, min(1.0, corr)) * (half_w - 2)
        col = COL_LIVE if corr >= 0.2 else (COL_WARN if corr >= -0.2 else COL_CLIP)
        c.create_rectangle(min(mx, px), y0 + 2, max(mx, px), y1 - 2, fill=col, outline="")
        c.create_line(mx, y0, mx, y1, fill=COL_DIM, width=1)
        c.create_line(px, y0 + 1, px, y1 - 1, fill="#ffffff", width=2)
        c.create_text(x0 + 4, (y0 + y1) / 2, text="-1", anchor="w", fill=COL_CLIP, font=self._font(self._fs(0.66), bold=True))
        c.create_text(x1 - 4, (y0 + y1) / 2, text="+1", anchor="e", fill=COL_LIVE, font=self._font(self._fs(0.66), bold=True))
        c.create_text(mx, (y0 + y1) / 2, text=f"φ {corr:+.2f}", fill="#ffffff", font=self._font(self._fs(0.68), bold=True))

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
        mute_l = self._raw(self._get_zctrl("mutel")) >= 0.5
        mute_r = self._raw(self._get_zctrl("muter")) >= 0.5
        phase_l = self._raw(self._get_zctrl("phasel")) >= 0.5
        phase_r = self._raw(self._get_zctrl("phaser")) >= 0.5
        softclip = self._raw(self._get_zctrl("softclip")) >= 0.5
        now = time.monotonic()
        is_live = (now - self._last_live_ts) < LIVE_HOLD_S

        hdr_h = max(36, min(46, int(h * 0.11)))
        byp_w = 66
        tabs_w = w - 2 * pad - byp_w - gap
        tw = (tabs_w - 3 * gap) / 4
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        self._draw_pill(w - pad - byp_w, pad, w - pad, pad + hdr_h,
                        "BYP" if byp else "ON ●", not byp, "#51cf66", "toggle", "bypass")

        bot_h = 96
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap

        if self.active_tab == "Stereo":
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL,
                               outline=accent if not byp else COL_BORDER, width=1)
            gx0, gx1 = pad + 34, w - pad - 34
            gy0, gy1 = vy0 + 22, vy1 - 28
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            hdr_txt = "Stereo Goniometer & Phase  (Drag 2D: X=Base, Y=Phase)"
            c.create_text(pad + 10, vy0 + 11, text=hdr_txt, anchor="w", fill=COL_DIM,
                          font=self._fit_font(hdr_txt, max(40, (w - 2 * pad) - 70), self._fs(0.76), bold=True))
            c.create_text(w - pad - 10, vy0 + 11, text="● LIVE" if is_live else "○ PRED", anchor="e",
                          fill=COL_LIVE if is_live else COL_DIM, font=self._font(self._fs(0.74), bold=True))

            # Left & Right compact vertical output level bars flanking goniometer
            for side, bx0, lvl, clip in (
                ("L", pad + 8, self._out_l, self._clip_out_l),
                ("R", w - pad - 22, self._out_r, self._clip_out_r),
            ):
                bx1 = bx0 + 14
                c.create_rectangle(bx0, gy0, bx1, gy1, fill="#121318", outline=COL_BORDER)
                if lvl > 0.01:
                    bh = min(1.0, lvl) * gh
                    c.create_rectangle(bx0 + 1, gy1 - bh, bx1 - 1, gy1, fill=COL_CLIP if clip else accent, outline="")
                c.create_text((bx0 + bx1) / 2, gy1 + 8, text=side, fill=COL_CLIP if clip else COL_DIM,
                              font=self._font(self._fs(0.68), bold=True))

            cx, cy = (gx0 + gx1) / 2.0, gy1 - 4
            rad = min(gw * 0.46, gh * 0.92)
            c.create_arc(cx - rad, cy - rad, cx + rad, cy + rad, start=0, extent=180,
                         style="arc", outline=COL_GRID, width=1)
            c.create_arc(cx - rad * 0.6, cy - rad * 0.6, cx + rad * 0.6, cy + rad * 0.6,
                         start=0, extent=180, style="arc", outline=COL_GRID, width=1)
            c.create_line(cx - rad, cy, cx + rad, cy, fill=COL_GRID)
            c.create_line(cx, cy, cx, cy - rad, fill=COL_GRID, dash=(2, 4))
            d45 = rad * 0.7071
            c.create_line(cx, cy, cx - d45, cy - d45, fill="#333644")
            c.create_line(cx, cy, cx + d45, cy - d45, fill="#333644")
            c.create_text(cx - d45 - 8, cy - d45 - 4, text="L", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))
            c.create_text(cx + d45 + 8, cy - d45 - 4, text="R", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))
            c.create_text(cx, cy - rad + 8, text="M", fill=COL_DIM, font=self._font(self._fs(0.74)))

            base = self._raw(self._get_zctrl("stereo_base"), 0.0)
            ph_deg = self._raw(self._get_zctrl("stereo_phase"), 0.0)
            ph_rad = math.radians(ph_deg)
            delay_ms = self._raw(self._get_zctrl("delay"), 0.0)
            spread = max(0.04, (base + 1.0) * 0.5)

            # Interactive stereo field fan
            half_ang = math.radians(5.0 + spread * 78.0)
            tilt = (delay_ms / 20.0) * math.radians(18.0)
            fan = [cx, cy]
            for i in range(25):
                a = -half_ang + (2.0 * half_ang) * (i / 24.0) + tilt
                r_mod = rad * (0.78 + 0.14 * math.cos(a * 2.0 + ph_rad))
                fan.extend([cx + r_mod * math.sin(a), cy - r_mod * math.cos(a)])
            c.create_polygon(fan, fill="#331e3d" if not byp else "#22242c",
                             outline=accent if not byp else COL_DIM, width=2)

            # Live L/R Lissajous vectorscope trace driven by real meter_outL/R & meter_phase
            if is_live and max(self._out_l, self._out_r) > 0.01:
                corr = self._phase_corr
                l_amp = max(0.05, self._out_l)
                r_amp = max(0.05, self._out_r)
                # Phase angle between L and R channels derived from correlation
                delta = math.acos(max(-1.0, min(1.0, corr)))
                lissa = []
                for i in range(37):
                    th = (i / 36.0) * math.pi * 2.0
                    lv = l_amp * math.sin(th)
                    rv = r_amp * math.sin(th + delta)
                    # Rotate 45 deg into Mid (up) / Side (horizontal) coordinates
                    side_v = (rv - lv) * 0.7071
                    mid_v = abs(lv + rv) * 0.7071
                    lissa.extend([cx + side_v * rad * 0.92, cy - mid_v * rad * 0.92])
                tr_col = COL_LIVE if corr >= 0.2 else (COL_WARN if corr >= -0.2 else COL_CLIP)
                c.create_line(lissa, fill=tr_col, width=2.0)

            hx = gx0 + self._norm(self._get_zctrl("stereo_base"), "stereo_base") * gw
            hy = gy1 - self._norm(self._get_zctrl("stereo_phase"), "stereo_phase") * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)

            # Dedicated Phase Correlation Meter bar at bottom of goniometer panel
            self._draw_phase_bar(c, gx0, vy1 - 22, gx1, vy1 - 6, self._phase_corr)

            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "stereo_base", "yk": "stereo_phase"}))

        elif self.active_tab == "M/S":
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL,
                               outline=accent if not byp else COL_BORDER, width=1)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            hdr_txt = "Mid / Side Stage  (Drag 2D: X=Mid Pan, Y=Side Gain)"
            c.create_text(gx0, vy0 + 11, text=hdr_txt, anchor="w", fill=COL_DIM,
                          font=self._fit_font(hdr_txt, gw, self._fs(0.78), bold=True))

            mx, my = (gx0 + gx1) / 2, (gy0 + gy1) / 2
            c.create_line(mx, gy0, mx, gy1, fill=COL_GRID, dash=(3, 4))
            c.create_line(gx0, my, gx1, my, fill=COL_GRID, dash=(3, 4))

            m_n = self._norm(self._get_zctrl("mlev"), "mlev")
            s_n = self._norm(self._get_zctrl("slev"), "slev")
            mpan = self._raw(self._get_zctrl("mpan"), 0.0)
            sbal = self._raw(self._get_zctrl("sbal"), 0.0)

            sw = max(14, s_n * gw * 0.46)
            sh = max(12, m_n * gh * 0.44)
            sx = mx + sbal * (gw * 0.16)
            c.create_oval(sx - sw, my - sh, sx + sw, my + sh,
                          fill="#1a2f47" if not byp else "#22242c", outline=accent, width=2)
            mpx = mx + mpan * (gw * 0.44)
            c.create_line(mpx, gy1 - 4, mpx, gy1 - 4 - m_n * (gh * 0.88), fill="#ffd43b", width=3)

            hx = gx0 + self._norm(self._get_zctrl("mpan"), "mpan") * gw
            hy = gy1 - s_n * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "mpan", "yk": "slev"}))

        elif self.active_tab == "Matrix":
            gh = max(114, vy1 - vy0)
            rh = (gh - 2 * gap) / 3
            mode_idx = max(0, min(6, int(round(self._raw(self._get_zctrl("mode"), 0.0)))))

            cw4 = (w - 2 * pad - 3 * gap) / 4
            for i in range(4):
                x0 = pad + i * (cw4 + gap)
                self._draw_pill(x0, vy0, x0 + cw4, vy0 + rh, MATRIX_MODES[i],
                                i == mode_idx, accent, "set_int", ("mode", i))
            r2y = vy0 + rh + gap
            cw3 = (w - 2 * pad - 2 * gap) / 3
            for i in range(3):
                idx = 4 + i
                x0 = pad + i * (cw3 + gap)
                self._draw_pill(x0, r2y, x0 + cw3, r2y + rh, MATRIX_MODES[idx],
                                idx == mode_idx, accent, "set_int", ("mode", idx))
            r3y = vy0 + 2 * (rh + gap)
            cw5 = (w - 2 * pad - 4 * gap) / 5
            toggles = [
                ("Mute L",   mute_l,   "#ff6b6b", "mutel"),
                ("Mute R",   mute_r,   "#ff6b6b", "muter"),
                ("Phase L",  phase_l,  "#ff922b", "phasel"),
                ("Phase R",  phase_r,  "#ff922b", "phaser"),
                ("Softclip", softclip, "#51cf66", "softclip"),
            ]
            for i, (tlbl, act, col, tk) in enumerate(toggles):
                x0 = pad + i * (cw5 + gap)
                self._draw_pill(x0, r3y, x0 + cw5, vy1, tlbl, act, col, "toggle", tk)

        else:  # I/O
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL,
                               outline=accent if not byp else COL_BORDER, width=1)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            hdr_txt = "I/O Live Levels & Balance  (Drag 2D: X=Out Bal, Y=Out Gain)"
            c.create_text(gx0, vy0 + 11, text=hdr_txt, anchor="w", fill=COL_DIM,
                          font=self._fit_font(hdr_txt, gw - 60, self._fs(0.76), bold=True))
            c.create_text(gx1, vy0 + 11, text="● LIVE" if is_live else "○ GAIN", anchor="e",
                          fill=COL_LIVE if is_live else COL_DIM, font=self._font(self._fs(0.74), bold=True))

            mx, my = (gx0 + gx1) / 2, (gy0 + gy1) / 2
            c.create_line(mx, gy0, mx, gy1, fill=COL_GRID, dash=(3, 4))
            c.create_line(gx0, my, gx1, my, fill=COL_GRID, dash=(3, 4))

            out_n = self._norm(self._get_zctrl("level_out"), "level_out")
            bal_o = self._raw(self._get_zctrl("balance_out"), 0.0)
            if is_live:
                l_in, r_in = self._in_l, self._in_r
                l_out, r_out = self._out_l, self._out_r
            else:
                in_n = self._norm(self._get_zctrl("level_in"), "level_in")
                bal_i = self._raw(self._get_zctrl("balance_in"), 0.0)
                l_in = in_n * min(1.0, 1.0 - bal_i)
                r_in = in_n * min(1.0, 1.0 + bal_i)
                l_out = 0.0 if mute_l else out_n * min(1.0, 1.0 - bal_o)
                r_out = 0.0 if mute_r else out_n * min(1.0, 1.0 + bal_o)

            bar_w = max(20, gw * 0.11)
            bars = [
                (mx - 2 * bar_w - 22, l_in,  "#1b2d42", "#4dabf7", "In L",  self._clip_in_l),
                (mx - bar_w - 14,     r_in,  "#1b2d42", "#4dabf7", "In R",  self._clip_in_r),
                (mx + 14,             l_out, "#1f472d", accent,    "Out L" + (" Ø" if phase_l else ""), self._clip_out_l),
                (mx + bar_w + 22,     r_out, "#1f472d", accent,    "Out R" + (" Ø" if phase_r else ""), self._clip_out_r),
            ]
            for bx0, lvl, fill_c, out_c, lbl, clip in bars:
                c.create_rectangle(bx0, gy0, bx0 + bar_w, gy1, fill="#13151b", outline=COL_GRID)
                if lvl > 0.01:
                    c.create_rectangle(bx0, gy1 - min(1.0, lvl) * gh, bx0 + bar_w, gy1,
                                       fill=COL_CLIP if clip else (fill_c if not byp else "#262833"), outline=out_c)
                c.create_text(bx0 + bar_w / 2, gy1 - 10, text=lbl, fill=COL_TEXT,
                              font=self._font(self._fs(0.72), bold=True))

            hx = gx0 + self._norm(self._get_zctrl("balance_out"), "balance_out") * gw
            hy = gy1 - out_n * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "balance_out", "yk": "level_out"}))

        # 2x2 encoder-linked parameter boxes at bottom
        items = self._tab_items(self.active_tab)
        by0 = h - pad - bot_h
        cw = (w - 2 * pad - gap) / 2
        ch = (bot_h - gap) / 2
        for i, (k, lbl) in enumerate(items):
            rx0 = pad + (i % 2) * (cw + gap)
            ry0 = by0 + (i // 2) * (ch + gap)
            self._draw_param_box(rx0, ry0, rx0 + cw, ry0 + ch, k, lbl, accent)

    def _reset_default(self, key):
        z = self._get_zctrl(key)
        if z is not None:
            z.set_value(z.value_default, send=True)
            self.last_snapshot = None
            self._draw()

    def _on_press(self, event):
        x, y = event.x, event.y
        now = time.monotonic()
        for x0, y0, x1, y1, kind, payload in reversed(self.hitboxes):
            if x0 <= x <= x1 and y0 <= y <= y1:
                if kind == "tab":
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
                if kind == "hfader":
                    tap_id = ("hfader", payload["key"])
                    if self.last_tap[0] == tap_id and (now - self.last_tap[1]) < DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        self._reset_default(payload["key"])
                        return
                    self.last_tap = (tap_id, now)
                    self.drag_target = (kind, payload)
                    self._apply_drag(x, y)
                    return
                if kind == "xy_pad":
                    tap_id = ("xy", payload["xk"], payload["yk"])
                    if self.last_tap[0] == tap_id and (now - self.last_tap[1]) < DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        self._reset_default(payload["xk"])
                        self._reset_default(payload["yk"])
                        return
                    self.last_tap = (tap_id, now)
                    self.drag_target = (kind, payload)
                    self._apply_drag(x, y)
                    return

    def _on_drag(self, event):
        if self.drag_target:
            self._apply_drag(event.x, event.y)

    def _on_release(self, event):
        self.drag_target = None

    def _apply_drag(self, x, y):
        kind, p = self.drag_target
        if kind == "hfader":
            n = (x - p["tx0"]) / max(1.0, p["tx1"] - p["tx0"])
            self._set_norm(self._get_zctrl(p["key"]), n, p["key"])
        elif kind == "xy_pad":
            nx = (x - p["gx0"]) / max(1.0, p["gx1"] - p["gx0"])
            ny = 1.0 - (y - p["gy0"]) / max(1.0, p["gy1"] - p["gy0"])
            self._set_norm(self._get_zctrl(p["xk"]), nx, p["xk"])
            self._set_norm(self._get_zctrl(p["yk"]), ny, p["yk"])
        self.last_snapshot = None
        self._draw()
