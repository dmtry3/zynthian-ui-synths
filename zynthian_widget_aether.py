#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Aether Algorithmic Reverb Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces Aether's 47 raw LV2 ports with 4 dynamic workstation tabs mapped
# 1-to-1 to Zynthian's 4 physical encoders:
#   Mix & Space | Early | Late | EQ & Sat
# Features live Early-Tap + Late-Tail visualization, interactive EQ curve,
# and 2D touch pads with double-tap reset.
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

TABS = ["Mix & Space", "Early", "Late", "EQ & Sat"]
TAB_ACCENTS = {
    "Mix & Space": "#38d9a9",
    "Early":       "#4dabf7",
    "Late":        "#cc5de8",
    "EQ & Sat":    "#ff922b",
}
LOG_KEYS = {
    "early_low_cut_cutoff", "early_high_cut_cutoff",
    "late_low_shelf_cutoff", "late_high_shelf_cutoff", "late_high_cut_cutoff",
}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.2f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


class zynthian_widget_aether(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Mix & Space"
        self.sub_bank = 0
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
        if tab == "Mix & Space":
            if self.sub_bank == 1:
                return [
                    ("dry_level",      "Dry Lvl"),
                    ("predelay_level", "Pre Lvl"),
                    ("early_level",    "Early Lvl"),
                    ("late_level",     "Late Lvl"),
                ]
            return [
                ("mix",        "Mix"),
                ("predelay",   "Predelay"),
                ("width",      "Width"),
                ("late_level", "Late Lvl"),
            ]
        if tab == "Early":
            if self.sub_bank == 1:
                return [
                    ("early_diffusion_stages",   "Diff Stg"),
                    ("early_diffusion_delay",    "Diff Dly"),
                    ("early_diffusion_feedback", "Diff FB"),
                    ("early_diffusion_mod_depth","Diff Mod"),
                ]
            return [
                ("early_taps",       "Taps"),
                ("early_tap_length", "Tap Len"),
                ("early_tap_decay",  "Tap Dec"),
                ("early_tap_mix",    "Tap Mix"),
            ]
        if tab == "Late":
            if self.sub_bank == 1:
                return [
                    ("late_diffusion_stages",   "Diff Stg"),
                    ("late_diffusion_delay",    "Diff Dly"),
                    ("late_diffusion_feedback", "Diff FB"),
                    ("late_delay_mod_rate",     "Mod Rate"),
                ]
            return [
                ("late_Delay",               "Late Dly"),
                ("late_delay_line_feedback", "Late FB"),
                ("late_delay_lines",         "Lines"),
                ("late_delay_mod_depth",     "Mod Dpth"),
            ]
        # EQ & Sat
        if self.sub_bank == 1:
            return [
                ("early_low_cut_cutoff",  "Erly LoC"),
                ("early_high_cut_cutoff", "Erly HiC"),
                ("early_diffusion_drive", "Erly Drv"),
                ("late_diffusion_drive",  "Late Drv"),
            ]
        return [
            ("late_low_shelf_cutoff",  "Low Frq"),
            ("late_low_shelf_gain",    "Low Gain"),
            ("late_high_shelf_cutoff", "Hi Frq"),
            ("late_high_shelf_gain",   "Hi Gain"),
        ]

    def _build_page_zctrls(self, tab):
        zlist = []
        for k, lbl in self._tab_items(tab):
            z = self._get_zctrl(k)
            if z is not None:
                z.short_name = lbl
                zlist.append(z)
        return zlist

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
        zlist = self._build_page_zctrls(tab)
        self.processor.ctrl_screens_dict[tab] = zlist
        try:
            if self.zyngui_control.get_current_processor() is self.processor:
                if self.last_screen_title != tab:
                    self._select_page(tab)
                else:
                    self.zyngui_control.zcontrollers = zlist
                    for i in range(4):
                        self.zyngui_control.set_zcontroller(i, zlist[i] if i < len(zlist) else None)
        except Exception as e:
            logging.debug(f"Aether live swap error: {e}")

    def _sync_list(self, tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page(tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Aether sync error: {e}")

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
    def _norm(z, key="", default=0.0):
        if z is None:
            return default
        try:
            v = float(z.get_value())
            vmin, vmax = float(z.value_min), float(z.value_max)
            if vmax <= vmin:
                return default
            v = max(vmin, min(vmax, v))
            if _norm_key(key) in LOG_KEYS and vmin > 0:
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
        val = vmin * ((vmax / vmin) ** n) if (_norm_key(key) in LOG_KEYS and vmin > 0) else (vmin + n * (vmax - vmin))
        if getattr(z, "is_integer", False):
            val = round(val)
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_aether._raw(z)
        kl = _norm_key(key)
        if "cutoff" in kl:
            return fmt_hz(v)
        if "gain" in kl or "drive" in kl:
            return "Off" if ("drive" in kl and v <= -11.9) else f"{v:+.1f}dB"
        if "delay" in kl and "lines" not in kl and "level" not in kl and "feedback" not in kl and "mod" not in kl:
            return f"{v:.0f}ms"
        if "tap_length" in kl:
            return f"{v:.0f}ms"
        if "rate" in kl:
            return f"{v:.2f}Hz"
        if "feedback" in kl or "decay" in kl:
            return f"{int(round(v * 100))}%"
        if "stages" in kl or "taps" in kl or "lines" in kl:
            return f"{int(round(v))}"
        if "mix" in kl or "level" in kl or "width" in kl:
            return f"{int(round(v))}%"
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
        keys = [k for k, _ in self._tab_items(self.active_tab)] + [
            "mix", "predelay", "early_level", "late_level", "early_taps",
            "early_tap_decay", "late_Delay", "late_delay_line_feedback",
            "late_order", "interpolate", "late_low_shelf_enabled", "late_high_shelf_enabled",
            "late_high_cut_enabled", "late_high_cut_cutoff",
            "early_low_cut_enabled", "early_high_cut_enabled",
        ]
        snap = (self.width, self.height, self.active_tab, self.sub_bank,
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

    def _fs(self, scale=1.0):
        base = max(9, min(13, self.height // 34))
        return max(8, int(round(base * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                      fill="#0d0e12" if active else COL_TEXT, font=self._font(self._fs(0.88), bold=True))
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
                      font=self._font(self._fs(0.88), bold=True))
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

        # Header: 4 Tabs
        hdr_h = max(36, min(46, int(h * 0.11)))
        tw = (w - 2 * pad - 3 * gap) / 4
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        # Row 2: Sub-bank selector + Quick toggles
        r2_y0 = pad + hdr_h + gap
        r2_h = 34
        bank_names = {
            "Mix & Space": ("Core Mix", "Levels"),
            "Early":       ("Taps", "Diffusion"),
            "Late":        ("Delay & FB", "Diffusion"),
            "EQ & Sat":    ("Late EQ", "Early & Drive"),
        }[self.active_tab]
        bw = int((w - 2 * pad) * 0.44)
        bw2 = (bw - gap) / 2
        for bi, blbl in enumerate(bank_names):
            bx0 = pad + bi * (bw2 + gap)
            self._draw_pill(bx0, r2_y0, bx0 + bw2, r2_y0 + r2_h, f"● {blbl}" if bi == self.sub_bank else blbl,
                            bi == self.sub_bank, accent, "sub_bank", bi)

        # Right quick toggle pills
        qx0 = pad + bw + gap
        if self.active_tab == "EQ & Sat":
            togs = [
                ("LoShlf", "late_low_shelf_enabled"),
                ("HiShlf", "late_high_shelf_enabled"),
                ("HiCut",  "late_high_cut_enabled"),
            ]
        else:
            order_post = self._raw(self._get_zctrl("late_order")) >= 0.5
            togs = [
                ("Post" if order_post else "Pre", "late_order"),
                ("Interp", "interpolate"),
                ("HiCut", "late_high_cut_enabled"),
            ]
        qw = (w - pad - qx0 - (len(togs) - 1) * gap) / len(togs)
        for i, (lbl, k) in enumerate(togs):
            tx = qx0 + i * (qw + gap)
            on = self._raw(self._get_zctrl(k)) >= 0.5
            self._draw_pill(tx, r2_y0, tx + qw, r2_y0 + r2_h, lbl, on, accent, "toggle", k)

        # Row 3: Interactive Visualizer
        bot_h = 94
        vy0 = r2_y0 + r2_h + gap
        vy1 = h - pad - bot_h - gap
        c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)
        gx0, gx1 = pad + 14, w - pad - 14
        gy0, gy1 = vy0 + 22, vy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)

        if self.active_tab == "EQ & Sat":
            ls_on = self._raw(self._get_zctrl("late_low_shelf_enabled")) >= 0.5
            hs_on = self._raw(self._get_zctrl("late_high_shelf_enabled")) >= 0.5
            hc_on = self._raw(self._get_zctrl("late_high_cut_enabled")) >= 0.5
            ls_hz = max(15.0, min(22000.0, self._raw(self._get_zctrl("late_low_shelf_cutoff"), 100.0)))
            ls_db = max(-24.0, min(0.0, self._raw(self._get_zctrl("late_low_shelf_gain"), -2.0)))
            hs_hz = max(15.0, min(22000.0, self._raw(self._get_zctrl("late_high_shelf_cutoff"), 1500.0)))
            hs_db = max(-24.0, min(0.0, self._raw(self._get_zctrl("late_high_shelf_gain"), -3.0)))
            hc_hz = max(15.0, min(22000.0, self._raw(self._get_zctrl("late_high_cut_cutoff"), 20000.0)))

            hs_f = self._norm(self._get_zctrl("late_high_shelf_cutoff"), "late_high_shelf_cutoff")
            hs_g = self._norm(self._get_zctrl("late_high_shelf_gain"), "late_high_shelf_gain")

            eq_x0 = gx0 + 18
            eq_w = max(20, gx1 - eq_x0)
            eq_y0 = gy0 + 4
            eq_y1 = gy1 - 10
            eq_h = max(20, eq_y1 - eq_y0)

            active_tags = []
            if ls_on:
                active_tags.append("LoShlf")
            if hs_on:
                active_tags.append("HiShlf")
            if hc_on:
                active_tags.append("HiCut")
            st_txt = "+".join(active_tags) if active_tags else "EQ Bypassed"
            c.create_text(gx0, vy0 + 11, text=f"Aether Late EQ [{st_txt}]  (2D: HiShelf Frq×Gain)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            # dB grid (0 dB at top down to -24 dB at bottom)
            for db in (0, -6, -12, -18, -24):
                y = eq_y0 + (-db / 24.0) * eq_h
                c.create_line(eq_x0, y, gx1, y, fill="#383c4e" if db == 0 else COL_GRID, dash=(2, 4))
                c.create_text(eq_x0 - 3, y, text=f"{db}", anchor="e", fill=COL_DIM, font=self._font(self._fs(0.66)))

            # Log frequency grid (15 Hz .. 22 kHz)
            f_min, f_max = 15.0, 22000.0
            log_span = math.log(f_max / f_min)
            for f_hz, flbl in ((50, "50"), (200, "200"), (1000, "1k"), (4000, "4k"), (12000, "12k")):
                fx = eq_x0 + (math.log(f_hz / f_min) / log_span) * eq_w
                c.create_line(fx, eq_y0, fx, eq_y1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, eq_y1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            pts = []
            poly = [eq_x0, eq_y1]
            for i in range(65):
                t = i / 64.0
                f = f_min * ((f_max / f_min) ** t)
                db = 0.0
                if ls_on:
                    # Low shelf: attenuates below ls_hz (octaves < 0 -> weight -> 1)
                    oct_ls = math.log2(max(1e-4, f / ls_hz))
                    db += ls_db / (1.0 + math.exp(oct_ls * 2.4))
                if hs_on:
                    # High shelf: attenuates above hs_hz (octaves > 0 -> weight -> 1)
                    oct_hs = math.log2(max(1e-4, f / hs_hz))
                    db += hs_db / (1.0 + math.exp(-oct_hs * 2.4))
                if hc_on:
                    # 2nd-order low-pass high cut (-3 dB at hc_hz, 12 dB/oct)
                    r = f / hc_hz
                    db -= 10.0 * math.log10(1.0 + r ** 4)
                db = max(-24.0, min(0.0, db))
                px = eq_x0 + t * eq_w
                py = eq_y0 + (-db / 24.0) * eq_h
                pts.extend([px, py])
                poly.extend([px, py])
            poly.extend([gx1, eq_y1])

            c.create_polygon(poly, fill="#261e17" if active_tags else "#1d1f26", outline="")
            c.create_line(pts, fill=accent if active_tags else COL_DIM, width=2.6)

            hx = eq_x0 + hs_f * eq_w
            hy = eq_y1 - hs_g * eq_h
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8,
                          fill=accent if hs_on else COL_PANEL,
                          outline="#ffffff" if hs_on else COL_DIM, width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": eq_x0, "gx1": gx1, "gy0": eq_y0, "gy1": eq_y1,
                                   "xk": "late_high_shelf_cutoff", "yk": "late_high_shelf_gain"}))
        else:
            pre_n = self._norm(self._get_zctrl("predelay"), "predelay")
            taps = max(2, min(24, int(round(self._raw(self._get_zctrl("early_taps"), 12.0)))))
            t_dec = self._norm(self._get_zctrl("early_tap_decay"), "early_tap_decay")
            l_dly = self._norm(self._get_zctrl("late_Delay"), "late_Delay")
            l_fb = self._norm(self._get_zctrl("late_delay_line_feedback"), "late_delay_line_feedback")
            c.create_text(gx0, vy0 + 11, text="Aether Space: Early Taps + Late Decay Tail  (Drag 2D: X=Late Delay, Y=Feedback)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))
            pre_x = gx0 + pre_n * (gw * 0.25)
            # Early reflection vertical spikes
            for ti in range(taps):
                frac = ti / max(1, taps - 1)
                tx = pre_x + frac * (gw * 0.30)
                amp = (1.0 - frac * (0.3 + 0.65 * t_dec)) * 0.75
                c.create_line(tx, gy1, tx, gy1 - amp * gh, fill="#4dabf7", width=2)
            # Late exponential decay tail
            tail_x0 = pre_x + gw * 0.08
            tau = 0.08 + (l_fb ** 1.6) * 0.90 + l_dly * 0.25
            poly = [tail_x0, gy1]
            line = []
            for i in range(49):
                t = i / 48.0
                px = tail_x0 + t * (gx1 - tail_x0)
                amp = math.exp(-t / max(0.06, tau)) * (0.3 + 0.7 * l_fb)
                py = gy1 - amp * gh
                poly.extend([px, py])
                line.extend([px, py])
            poly.extend([gx1, gy1])
            c.create_polygon(poly, fill="#1f2d30", outline="")
            c.create_line(line, fill=accent, width=2.6)
            hx = gx0 + l_dly * gw
            hy = gy1 - l_fb * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "late_Delay", "yk": "late_delay_line_feedback"}))

        # Row 4: 2x2 Parameter Cards bound to 4 encoders
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
