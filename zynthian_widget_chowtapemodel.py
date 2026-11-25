#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# CHOWTapeModel Analog Tape Machine Widget for Zynthian (V5 800x480)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces CHOWTapeModel's 53 raw LV2 ports with 5 dynamic workstation tabs
# mapped 1-to-1 to Zynthian's 4 physical encoders + ECO CPU tamer:
#   Tape | Wow/Flt | Loss | Degrade | Tone/Comp   + ECO
# Features live B-H magnetic hysteresis loop, dual Wow+Flutter tape drift scope,
# Wallace head-loss frequency response, chew/degrade wear strip, tone/comp EQ,
# and full double-tap reset + 2-way encoder synchronization.
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
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

TABS = ["Tape", "Wow/Flt", "Loss", "Degrade", "Tone/Comp"]
TAB_ACCENTS = {
    "Tape":      "#ff922b",
    "Wow/Flt":   "#ffd43b",
    "Loss":      "#4dabf7",
    "Degrade":   "#cc5de8",
    "Tone/Comp": "#51cf66",
}

TAPE_MODES = ["RK2", "RK4", "NR4", "NR8", "STN", "V1"]
OS_FACTORS = ["1X", "2X", "4X", "8X", "16X"]
OS_MODES = ["Min Phs", "Lin Phs"]
BIPOLAR_KEYS = {"tone_bass", "tone_treble", "azimuth", "stereo_balance", "output_gain"}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.1f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


class zynthian_widget_chowtapemodel(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Tape"
        self.sub_bank = 0
        self.eco_on = False
        self._eco_saved = {}
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
            self._rebuild_pages(rebuild_list=True)

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
        if tab == "Tape":
            return [
                ("tape_drive",      "Drive"),
                ("tape_saturation", "Saturate"),
                ("tape_bias",       "Bias"),
                ("dry_wet",         "Dry/Wet"),
            ]
        if tab == "Wow/Flt":
            if self.sub_bank == 1:
                return [
                    ("wow_variance",  "Wow Var"),
                    ("wow_drift",     "Wow Drft"),
                    ("flutter_depth", "Flt Dpth"),
                    ("wow_depth",     "Wow Dpth"),
                ]
            return [
                ("wow_depth",     "Wow Dpth"),
                ("wow_rate",      "Wow Rate"),
                ("flutter_depth", "Flt Dpth"),
                ("flutter_rate",  "Flt Rate"),
            ]
        if tab == "Loss":
            if self.sub_bank == 1:
                return [
                    ("azimuth",             "Azimuth"),
                    ("oversampling_factor", "Oversamp"),
                    ("oversampling_mode",   "OS Mode"),
                    ("stereo_balance",      "Balance"),
                ]
            return [
                ("tape_speed",     "Speed"),
                ("tape_spacing",   "Spacing"),
                ("tape_thickness", "Thick"),
                ("playhead_gap",   "Head Gap"),
            ]
        if tab == "Degrade":
            if self.sub_bank == 1:
                return [
                    ("chew_depth",    "Chew Dpt"),
                    ("chew_freq",     "Chew Frq"),
                    ("chew_variance", "Chew Var"),
                    ("dry_wet",       "Dry/Wet"),
                ]
            return [
                ("degrade_depth",    "Deg Dpth"),
                ("degrade_amount",   "Deg Amt"),
                ("degrade_variance", "Deg Var"),
                ("degrade_envelope", "Deg Env"),
            ]
        # Tone/Comp
        if self.sub_bank == 1:
            return [
                ("compression_amount",  "Comp Amt"),
                ("compression_attack",  "Comp Atk"),
                ("compression_release", "Comp Rel"),
                ("input_low_cut",       "In LoCut"),
            ]
        return [
            ("input_gain",  "In Gain"),
            ("tone_bass",   "Bass"),
            ("tone_treble", "Treble"),
            ("output_gain", "Out Gain"),
        ]

    def _build_page_zctrls(self, tab):
        zl = []
        for k, lbl in self._tab_items(tab):
            z = self._get_zctrl(k)
            if z is not None:
                z.short_name = lbl
                zl.append(z)
        return zl

    def _rebuild_pages(self, rebuild_list=False):
        if not self.processor:
            return
        screens = {}
        for t in TABS:
            zl = self._build_page_zctrls(t)
            if zl:
                screens[t] = zl
        if not screens:
            return
        self.processor.ctrl_screens_dict = screens
        if rebuild_list:
            self.after(25, lambda: self._sync_list(self.active_tab))
        else:
            self._live_swap(self.active_tab)

    def _live_swap(self, tab):
        if not self.processor:
            return
        zl = self._build_page_zctrls(tab)
        self.processor.ctrl_screens_dict[tab] = zl
        try:
            if self.zyngui_control.get_current_processor() is self.processor:
                if self.last_screen_title != tab:
                    self._select_page(tab)
                else:
                    self.zyngui_control.zcontrollers = zl
                    for i in range(4):
                        self.zyngui_control.set_zcontroller(i, zl[i] if i < len(zl) else None)
        except Exception as e:
            logging.debug(f"CHOWTapeModel live swap error: {e}")

    def _sync_list(self, tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page(tab)
            self._draw()
        except Exception as e:
            logging.debug(f"CHOWTapeModel sync error: {e}")

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
                    self.sub_bank = 0
                    self._live_swap(t)
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
    def _fmt(z, key):
        if z is None:
            return "--"
        n = zynthian_widget_chowtapemodel._norm(z)
        if key == "tape_mode":
            return TAPE_MODES[min(len(TAPE_MODES) - 1, int(round(n * (len(TAPE_MODES) - 1))))]
        if key == "oversampling_factor":
            return OS_FACTORS[min(len(OS_FACTORS) - 1, int(round(n * (len(OS_FACTORS) - 1))))]
        if key == "oversampling_mode":
            return OS_MODES[1 if n >= 0.5 else 0]
        if key == "tape_speed":
            ips = 1.0 + n * 29.0
            return f"{ips:.1f}ips"
        if key in ("input_gain", "output_gain"):
            db = (n - 0.5) * 60.0 if key == "output_gain" else (n * 36.0 - 30.0)
            return f"{db:+.1f}dB"
        if key in ("tone_bass", "tone_treble"):
            return f"{(n - 0.5) * 200.0:+.0f}%"
        if key == "azimuth":
            return f"{(n - 0.5) * 150.0:+.0f}°"
        if key == "stereo_balance":
            return f"{(n - 0.5) * 200.0:+.0f}%"
        if key in ("input_low_cut", "input_high_cut"):
            hz = 20.0 * ((20000.0 / 20.0) ** n)
            return fmt_hz(hz)
        return f"{int(round(n * 100))}%"

    def _toggle_eco(self):
        os_z = self._get_zctrl("oversampling_factor")
        md_z = self._get_zctrl("tape_mode")
        if not self.eco_on:
            if os_z is not None:
                self._eco_saved["oversampling_factor"] = self._raw(os_z)
                os_z.set_value(0.0, send=True)  # 1X
            if md_z is not None:
                self._eco_saved["tape_mode"] = self._raw(md_z)
                md_z.set_value(0.0, send=True)  # RK2 (lowest CPU)
            self.eco_on = True
        else:
            for k, z in (("oversampling_factor", os_z), ("tape_mode", md_z)):
                if z is not None and k in self._eco_saved:
                    z.set_value(self._eco_saved[k], send=True)
            self.eco_on = False
        self.last_snapshot = None
        self._draw()

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
        keys = (
            "tape_on_off", "tape_drive", "tape_saturation", "tape_bias", "tape_mode", "dry_wet",
            "oversampling_factor", "oversampling_mode", "wow_flutter_on_off",
            "flutter_rate", "flutter_depth", "wow_rate", "wow_depth", "wow_variance", "wow_drift",
            "loss_on_off", "tape_speed", "tape_spacing", "tape_thickness", "playhead_gap", "azimuth",
            "degrade_on_off", "degrade_point1x", "degrade_depth", "degrade_amount", "degrade_variance", "degrade_envelope",
            "chew_on_off", "chew_depth", "chew_freq", "chew_variance",
            "input_filters_on_off", "input_low_cut", "input_high_cut", "tone_on_off", "tone_bass", "tone_treble",
            "compression_on_off", "compression_amount", "compression_attack", "compression_release",
            "input_gain", "output_gain", "mid_side_mode", "stereo_balance",
        )
        snap = (self.width, self.height, self.active_tab, self.sub_bank, self.eco_on,
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
        eco_w = 54
        tabs_w = w - 2 * pad - eco_w - gap
        tw = (tabs_w - (len(TABS) - 1) * gap) / len(TABS)
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        self._draw_pill(w - pad - eco_w, pad, w - pad, pad + hdr_h, "ECO", self.eco_on, "#40c057", "eco", None)

        r2_y0 = pad + hdr_h + gap
        r2_h = 34
        bot_h = 94
        vy0 = r2_y0 + r2_h + gap
        vy1 = h - pad - bot_h - gap

        if self.active_tab == "Tape":
            tape_on = self._raw(self._get_zctrl("tape_on_off"), 1.0) >= 0.5
            mode_n = self._norm(self._get_zctrl("tape_mode"), 0.4)
            mode_i = min(5, int(round(mode_n * 5.0)))
            on_w = 72
            self._draw_pill(pad, r2_y0, pad + on_w, r2_y0 + r2_h,
                            "TAPE ●" if tape_on else "TAPE", tape_on, accent, "toggle", "tape_on_off")
            mx0 = pad + on_w + gap
            mw = (w - pad - mx0 - 5 * gap) / 6.0
            for i, mlbl in enumerate(TAPE_MODES):
                x0 = mx0 + i * (mw + gap)
                self._draw_pill(x0, r2_y0, x0 + mw, r2_y0 + r2_h, mlbl, i == mode_i, accent,
                                "set_norm", ("tape_mode", i / 5.0))

            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent if tape_on else COL_BORDER)
            gx0, gx1 = pad + 16, w - pad - 16
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            mid_x, mid_y = (gx0 + gx1) / 2.0, (gy0 + gy1) / 2.0
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))
            c.create_line(mid_x, gy0, mid_x, gy1, fill=COL_GRID, dash=(2, 4))
            c.create_line(gx0, gy1, gx1, gy0, fill="#383c4e", dash=(3, 4))
            c.create_text(gx0, vy0 + 11, text=f"Magnetic Hysteresis Loop [{TAPE_MODES[mode_i]}]  (2D: Drive × Sat)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            drv = self._norm(self._get_zctrl("tape_drive"), 0.5)
            sat = self._norm(self._get_zctrl("tape_saturation"), 0.5)
            bias = self._norm(self._get_zctrl("tape_bias"), 0.5)
            gain = 0.8 + drv * 4.5 + sat * 2.5
            hyst_w = (0.04 + (1.0 - bias) * 0.28) * (0.4 + 0.6 * sat)
            asym = (0.5 - bias) * 0.22

            upper, lower = [], []
            for i in range(49):
                t = i / 48.0
                x = t * 2.0 - 1.0
                yu = math.tanh((x + hyst_w + asym * (x ** 2)) * gain)
                yl = math.tanh((x - hyst_w + asym * (x ** 2)) * gain)
                px = gx0 + t * gw
                upper.extend([px, mid_y - yu * (gh * 0.45)])
                lower.extend([px, mid_y - yl * (gh * 0.45)])
            # Build closed loop polygon from upper forward + lower reversed
            loop_poly = list(upper)
            for i in range(len(lower) - 2, -1, -2):
                loop_poly.extend([lower[i], lower[i + 1]])
            c.create_polygon(loop_poly, fill="#332318" if tape_on else "#20222b", outline="")
            c.create_line(upper, fill=accent if tape_on else COL_DIM, width=2.5)
            c.create_line(lower, fill="#ffa94d" if tape_on else COL_DIM, width=2.0)

            hx, hy = gx0 + drv * gw, gy1 - sat * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "tape_drive", "yk": "tape_saturation"}))

        elif self.active_tab == "Wow/Flt":
            wf_on = self._raw(self._get_zctrl("wow_flutter_on_off"), 1.0) >= 0.5
            bw = (w - 2 * pad - 2 * gap) / 3.0
            self._draw_pill(pad, r2_y0, pad + bw, r2_y0 + r2_h, "WF ON ●" if wf_on else "WF OFF",
                            wf_on, accent, "toggle", "wow_flutter_on_off")
            self._draw_pill(pad + bw + gap, r2_y0, pad + 2 * bw + gap, r2_y0 + r2_h,
                            "● Core" if self.sub_bank == 0 else "Core", self.sub_bank == 0, accent, "sub_bank", 0)
            self._draw_pill(pad + 2 * (bw + gap), r2_y0, w - pad, r2_y0 + r2_h,
                            "● Drift" if self.sub_bank == 1 else "Drift", self.sub_bank == 1, accent, "sub_bank", 1)

            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent if wf_on else COL_BORDER)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            mid_y = (gy0 + gy1) / 2.0
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))
            c.create_text(gx0, vy0 + 11, text="Wow (Slow) + Flutter (Fast) Pitch Drift  (2D: Flt × Wow Depth)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            wd = self._norm(self._get_zctrl("wow_depth"), 0.2)
            wr = self._norm(self._get_zctrl("wow_rate"), 0.25)
            fd = self._norm(self._get_zctrl("flutter_depth"), 0.2)
            fr = self._norm(self._get_zctrl("flutter_rate"), 0.3)
            pts_w, pts_tot = [], []
            for i in range(81):
                t = i / 80.0
                yw = wd * 0.34 * math.sin(t * math.pi * 2.0 * (0.8 + wr * 2.4))
                yf = fd * 0.24 * math.sin(t * math.pi * 2.0 * (5.0 + fr * 14.0))
                px = gx0 + t * gw
                pts_w.extend([px, mid_y - yw * gh])
                pts_tot.extend([px, mid_y - max(-0.46, min(0.46, yw + yf)) * gh])
            c.create_line(pts_w, fill="#6e5c1f", width=1.6, dash=(3, 3))
            c.create_line(pts_tot, fill=accent if wf_on else COL_DIM, width=2.6)

            hx, hy = gx0 + fd * gw, gy1 - wd * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "flutter_depth", "yk": "wow_depth"}))

        elif self.active_tab == "Loss":
            loss_on = self._raw(self._get_zctrl("loss_on_off"), 1.0) >= 0.5
            bw = (w - 2 * pad - 2 * gap) / 3.0
            self._draw_pill(pad, r2_y0, pad + bw, r2_y0 + r2_h, "LOSS ●" if loss_on else "LOSS OFF",
                            loss_on, accent, "toggle", "loss_on_off")
            self._draw_pill(pad + bw + gap, r2_y0, pad + 2 * bw + gap, r2_y0 + r2_h,
                            "● Head Loss" if self.sub_bank == 0 else "Head Loss", self.sub_bank == 0, accent, "sub_bank", 0)
            self._draw_pill(pad + 2 * (bw + gap), r2_y0, w - pad, r2_y0 + r2_h,
                            "● Azim / OS" if self.sub_bank == 1 else "Azim / OS", self.sub_bank == 1, accent, "sub_bank", 1)

            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent if loss_on else COL_BORDER)
            gx0, gx1 = pad + 20, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 16
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            c.create_text(gx0, vy0 + 11, text="Tape Head-Loss Spectrum  (Drag 2D: X=Speed, Y=Spacing)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            spd = self._norm(self._get_zctrl("tape_speed"), 0.5)
            spc = self._norm(self._get_zctrl("tape_spacing"), 0.0)
            thk = self._norm(self._get_zctrl("tape_thickness"), 0.0)
            gap_n = self._norm(self._get_zctrl("playhead_gap"), 0.0)
            f_min, f_max = 20.0, 20000.0
            log_span = math.log(f_max / f_min)
            for f_hz, flbl in ((50, "50"), (200, "200"), (1000, "1k"), (4000, "4k"), (12000, "12k")):
                fx = gx0 + (math.log(f_hz / f_min) / log_span) * gw
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            # Head-bump peak moves down with slower speed; HF rolloff increases with spacing/thickness/gap
            bump_hz = 40.0 + spd * 110.0
            hf_cut = max(800.0, (2500.0 + spd * 16500.0) / (1.0 + spc * 3.5 + thk * 1.8 + gap_n * 2.8))
            pts = []
            poly = [gx0, gy1]
            for i in range(65):
                t = i / 64.0
                f = f_min * ((f_max / f_min) ** t)
                if loss_on:
                    bump = 0.14 * math.exp(-((math.log2(f / bump_hz)) ** 2) / 0.45)
                    hf = 1.0 / math.sqrt(1.0 + (f / hf_cut) ** 3)
                    lvl = max(0.04, min(0.96, (0.72 + bump) * hf))
                else:
                    lvl = 0.72
                px, py = gx0 + t * gw, gy1 - lvl * gh
                pts.extend([px, py])
                poly.extend([px, py])
            poly.extend([gx1, gy1])
            c.create_polygon(poly, fill="#1a2c3d" if loss_on else "#1e2028", outline="")
            c.create_line(pts, fill=accent if loss_on else COL_DIM, width=2.8)

            hx, hy = gx0 + spd * gw, gy1 - spc * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "tape_speed", "yk": "tape_spacing"}))

        elif self.active_tab == "Degrade":
            deg_on = self._raw(self._get_zctrl("degrade_on_off"), 0.0) >= 0.5
            ch_on = self._raw(self._get_zctrl("chew_on_off"), 0.0) >= 0.5
            p1x = self._raw(self._get_zctrl("degrade_point1x"), 0.0) >= 0.5
            bw = (w - 2 * pad - 4 * gap) / 5.0
            self._draw_pill(pad, r2_y0, pad + bw, r2_y0 + r2_h, "DEG ●" if deg_on else "DEG", deg_on, accent, "toggle", "degrade_on_off")
            self._draw_pill(pad + bw + gap, r2_y0, pad + 2 * bw + gap, r2_y0 + r2_h, "0.1x", p1x, "#ffd43b", "toggle", "degrade_point1x")
            self._draw_pill(pad + 2 * (bw + gap), r2_y0, pad + 3 * bw + 2 * gap, r2_y0 + r2_h, "CHEW ●" if ch_on else "CHEW", ch_on, "#ff6b6b", "toggle", "chew_on_off")
            self._draw_pill(pad + 3 * (bw + gap), r2_y0, pad + 4 * bw + 3 * gap, r2_y0 + r2_h, "Degrade", self.sub_bank == 0, accent, "sub_bank", 0)
            self._draw_pill(pad + 4 * (bw + gap), r2_y0, w - pad, r2_y0 + r2_h, "Chew", self.sub_bank == 1, accent, "sub_bank", 1)

            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent if (deg_on or ch_on) else COL_BORDER)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            mid_y = (gy0 + gy1) / 2.0
            xk = "degrade_depth" if self.sub_bank == 0 else "chew_freq"
            yk = "degrade_amount" if self.sub_bank == 0 else "chew_depth"
            hdr_t = "Tape Wear & Dropouts  (2D: " + ("Deg Depth × Amt)" if self.sub_bank == 0 else "Chew Freq × Depth)")
            c.create_text(gx0, vy0 + 11, text=hdr_t, anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            dd = self._norm(self._get_zctrl("degrade_depth"), 0.0)
            da = self._norm(self._get_zctrl("degrade_amount"), 0.0)
            cd = self._norm(self._get_zctrl("chew_depth"), 0.0)
            cf = self._norm(self._get_zctrl("chew_freq"), 0.0)
            pts = []
            for i in range(81):
                t = i / 80.0
                base = math.sin(t * math.pi * 6.0) * 0.36
                if deg_on:
                    noise = math.sin(i * 19.7) * math.cos(i * 7.3) * (0.08 + 0.35 * dd * (0.3 + 0.7 * da))
                    base = base * (1.0 - 0.35 * dd) + noise
                if ch_on:
                    drop = 1.0 - cd * 0.85 * max(0.0, math.sin(t * math.pi * (3.0 + cf * 14.0))) ** 6
                    base *= drop
                pts.extend([gx0 + t * gw, mid_y - max(-0.46, min(0.46, base)) * gh])
            c.create_line(pts, fill=accent if (deg_on or ch_on) else COL_DIM, width=2.4)

            hx = gx0 + self._norm(self._get_zctrl(xk)) * gw
            hy = gy1 - self._norm(self._get_zctrl(yk)) * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": xk, "yk": yk}))

        else:  # Tone/Comp
            tn_on = self._raw(self._get_zctrl("tone_on_off"), 1.0) >= 0.5
            cp_on = self._raw(self._get_zctrl("compression_on_off"), 0.0) >= 0.5
            if_on = self._raw(self._get_zctrl("input_filters_on_off"), 0.0) >= 0.5
            ms_on = self._raw(self._get_zctrl("mid_side_mode"), 0.0) >= 0.5
            bw = (w - 2 * pad - 5 * gap) / 6.0
            self._draw_pill(pad, r2_y0, pad + bw, r2_y0 + r2_h, "TONE", tn_on, accent, "toggle", "tone_on_off")
            self._draw_pill(pad + bw + gap, r2_y0, pad + 2 * bw + gap, r2_y0 + r2_h, "COMP", cp_on, "#ff922b", "toggle", "compression_on_off")
            self._draw_pill(pad + 2 * (bw + gap), r2_y0, pad + 3 * bw + 2 * gap, r2_y0 + r2_h, "FLT", if_on, "#4dabf7", "toggle", "input_filters_on_off")
            self._draw_pill(pad + 3 * (bw + gap), r2_y0, pad + 4 * bw + 3 * gap, r2_y0 + r2_h, "M/S", ms_on, "#cc5de8", "toggle", "mid_side_mode")
            self._draw_pill(pad + 4 * (bw + gap), r2_y0, pad + 5 * bw + 4 * gap, r2_y0 + r2_h, "Tone", self.sub_bank == 0, accent, "sub_bank", 0)
            self._draw_pill(pad + 5 * (bw + gap), r2_y0, w - pad, r2_y0 + r2_h, "Comp", self.sub_bank == 1, accent, "sub_bank", 1)

            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent)
            gx0, gx1 = pad + 16, w - pad - 16
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            mid_y = (gy0 + gy1) / 2.0
            c.create_line(gx0, mid_y, gx1, mid_y, fill="#383c4e", dash=(3, 4))

            if self.sub_bank == 0:
                c.create_text(gx0, vy0 + 11, text="Pre-Emphasis Tone Tilt & Input Cuts  (2D: Bass × Treble)",
                              anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))
                bass = (self._norm(self._get_zctrl("tone_bass"), 0.5) - 0.5) * 2.0
                treb = (self._norm(self._get_zctrl("tone_treble"), 0.5) - 0.5) * 2.0
                lc = self._norm(self._get_zctrl("input_low_cut"), 0.0)
                hc = self._norm(self._get_zctrl("input_high_cut"), 1.0)
                pts = []
                for i in range(65):
                    t = i / 64.0
                    db = 0.0
                    if tn_on:
                        db += bass * (1.0 / (1.0 + math.exp((t - 0.35) * 8.0))) * 0.42
                        db += treb * (1.0 / (1.0 + math.exp((0.65 - t) * 8.0))) * 0.42
                    if if_on:
                        if t < lc:
                            db -= (lc - t) * 1.4
                        if t > hc:
                            db -= (t - hc) * 1.4
                    pts.extend([gx0 + t * gw, mid_y - max(-0.46, min(0.46, db)) * gh])
                c.create_line(pts, fill=accent if (tn_on or if_on) else COL_DIM, width=2.8)
                hx = gx0 + self._norm(self._get_zctrl("tone_bass"), 0.5) * gw
                hy = gy1 - self._norm(self._get_zctrl("tone_treble"), 0.5) * gh
                c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
                self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                      {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                       "xk": "tone_bass", "yk": "tone_treble"}))
            else:
                c.create_text(gx0, vy0 + 11, text="Tape Compression Curve  (2D: Comp Amount × Release)",
                              anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))
                amt = self._norm(self._get_zctrl("compression_amount"), 0.0)
                rel = self._norm(self._get_zctrl("compression_release"), 0.6)
                c.create_line(gx0, gy1, gx1, gy0, fill="#383c4e", dash=(3, 4))
                pts = []
                for i in range(57):
                    t = i / 56.0
                    y = t if not cp_on else (t / (1.0 + amt * 2.5 * max(0.0, t - 0.25)))
                    pts.extend([gx0 + t * gw, gy1 - max(0.0, min(1.0, y)) * gh])
                c.create_line(pts, fill="#ff922b" if cp_on else COL_DIM, width=2.8)
                hx, hy = gx0 + amt * gw, gy1 - rel * gh
                c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill="#ff922b", outline="#ffffff", width=2)
                self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                      {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                       "xk": "compression_amount", "yk": "compression_release"}))

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
                        self.sub_bank = 0
                        self._live_swap(payload)
                        self._select_page(payload)
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "sub_bank":
                    if payload != self.sub_bank:
                        self.sub_bank = payload
                        self._live_swap(self.active_tab)
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "eco":
                    self._toggle_eco()
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
