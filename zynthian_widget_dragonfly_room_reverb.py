#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Dragonfly Room Reverb Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 4 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Space | Mix | Damp / EQ | Mod
# Dedicated per-tab interactive visualizations:
#   - Space: Room impulse response (Predelay + Early Taps + Diffuse Late Tail)
#   - Mix: Early reflections comb + Dry/Early/Late levels + Stereo Width arc
#   - Damp / EQ: Spectral damping profile (Low Boost + Early/Late Damp + High Cut)
#   - Mod: Room modulation LFO waves (Spin x Wander)
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

TABS = ["Space", "Mix", "Damp / EQ", "Mod"]
TAB_ACCENTS = {
    "Space":     "#51cf66",
    "Mix":       "#4dabf7",
    "Damp / EQ": "#ff922b",
    "Mod":       "#cc5de8",
}

LOG_KEYS = {"early_damp", "late_damp", "in_high_cut", "in_low_cut", "boost_freq"}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.1f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


class zynthian_widget_dragonfly_room_reverb(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Space"
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
        if tab == "Space":
            return [("decay", "Decay"), ("size", "Size"), ("predelay", "Predelay"), ("diffuse", "Diffuse")]
        if tab == "Mix":
            return [("dry_level", "Dry"), ("early_level", "Early"), ("late_level", "Late"), ("width", "Width")]
        if tab == "Damp / EQ":
            return [("early_damp", "Erly Dmp"), ("late_damp", "Late Dmp"), ("low_boost", "Low Bst"), ("in_high_cut", "High Cut")]
        return [("spin", "Spin"), ("wander", "Wander"), ("early_send", "Erly Snd"), ("in_low_cut", "Low Cut")]

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
            logging.debug(f"Dragonfly Room sync error: {e}")

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
    def _norm(z, default=0.0, key=""):
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
        v = zynthian_widget_dragonfly_room_reverb._raw(z)
        if key == "decay":
            return f"{v:.2f}s"
        if key == "size":
            return f"{v:.0f}m"
        if key == "predelay":
            return f"{v:.0f}ms"
        if key in ("early_damp", "late_damp", "in_high_cut", "in_low_cut", "boost_freq"):
            return fmt_hz(v)
        if key == "spin":
            return f"{v:.2f}Hz"
        return f"{int(round(v))}%"

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
        keys = ("decay", "size", "predelay", "diffuse", "dry_level", "early_level", "late_level",
                "width", "early_damp", "late_damp", "low_boost", "in_high_cut", "in_low_cut", "spin", "wander", "early_send")
        snap = (self.width, self.height, self.active_tab, tuple(round(self._raw(self._get_zctrl(k)), 2) for k in keys))
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
        return max(8, int(round(max(9, min(13, self.height // 34)) * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                      fill="#0d0e12" if active else COL_TEXT, font=self._font(self._fs(0.92), bold=True))
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z, key=key)
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

    def _draw_space_vis(self, c, pad, vy0, vy1, w, accent):
        gx0, gx1 = pad + 14, w - pad - 14
        gy0, gy1 = vy0 + 22, vy1 - 16
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)

        dec_n = self._norm(self._get_zctrl("decay"), 0.25)
        sz_n = self._norm(self._get_zctrl("size"), 0.35)
        pre_n = self._norm(self._get_zctrl("predelay"), 0.08)
        dif_n = self._norm(self._get_zctrl("diffuse"), 0.7)
        e_lvl = self._norm(self._get_zctrl("early_level"), 0.25)
        l_lvl = self._norm(self._get_zctrl("late_level"), 0.45)

        c.create_text(gx0, vy0 + 11, text="Room Impulse Response  (Drag 2D: X=Size, Y=Decay)",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))

        for frac, tlbl in ((0.0, "0s"), (0.25, "1s"), (0.5, "2s"), (0.75, "3s"), (1.0, "4s")):
            tx = gx0 + frac * gw
            c.create_line(tx, gy0, tx, gy1, fill=COL_GRID, dash=(2, 4))
            c.create_text(tx, gy1 + 8, text=tlbl, fill=COL_DIM, font=self._font(self._fs(0.68)))

        pre_x = gx0 + pre_n * (gw * 0.22)
        if pre_x > gx0 + 2:
            c.create_rectangle(gx0, gy0, pre_x, gy1, fill="#15191c", outline="")
            c.create_line(pre_x, gy0, pre_x, gy1, fill="#3b4c42", dash=(3, 3))

        n_taps = 7 + int(round(dif_n * 6))
        for i in range(n_taps):
            frac = i / max(1, n_taps - 1)
            ex = pre_x + frac * (gw * (0.16 + 0.16 * sz_n))
            amp = max(0.08, e_lvl) * (1.0 - frac * 0.60) * (0.72 + 0.28 * math.cos(i * 1.7))
            c.create_line(ex, gy1, ex, gy1 - amp * gh, fill="#4dabf7", width=2)

        poly = [pre_x, gy1]
        line = []
        tau = 0.08 + dec_n * 0.88
        attack_span = 0.03 + (1.0 - dif_n) * 0.08 + sz_n * 0.05
        for i in range(57):
            t = i / 56.0
            px = pre_x + t * (gx1 - pre_x)
            buildup = min(1.0, t / max(0.02, attack_span))
            amp = buildup * math.exp(-t / tau) * max(0.18, l_lvl)
            py = gy1 - amp * gh
            poly.extend([px, py])
            line.extend([px, py])
        poly.extend([gx1, gy1])
        c.create_polygon(poly, fill="#1c3022", outline="")
        c.create_line(line, fill=accent, width=2.6)

        hx = gx0 + sz_n * gw
        hy = gy1 - dec_n * gh
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                              {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "size", "yk": "decay"}))

    def _draw_mix_vis(self, c, pad, vy0, vy1, w, accent):
        gx0, gx1 = pad + 14, w - pad - 14
        gy0, gy1 = vy0 + 22, vy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)

        dry_n = self._norm(self._get_zctrl("dry_level"), 0.8)
        e_n = self._norm(self._get_zctrl("early_level"), 0.25)
        l_n = self._norm(self._get_zctrl("late_level"), 0.45)
        wid_n = self._norm(self._get_zctrl("width"), 0.65)
        pre_n = self._norm(self._get_zctrl("predelay"), 0.08)

        c.create_text(gx0, vy0 + 11, text="Room Early Reflections & Stereo Width  (Drag 2D: X=Early, Y=Late)",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))

        split_x = gx0 + gw * 0.58
        c.create_line(split_x, gy0, split_x, gy1, fill=COL_GRID, dash=(3, 3))

        bw = max(14, (split_x - gx0) * 0.11)
        bars = [("DRY", dry_n, "#868e96"), ("ERLY", e_n, accent), ("LATE", l_n, "#51cf66")]
        for i, (blbl, bval, bcol) in enumerate(bars):
            bx0 = gx0 + i * (bw + 6)
            c.create_rectangle(bx0, gy0 + 4, bx0 + bw, gy1 - 14, fill="#14161c", outline=COL_BORDER)
            bh = bval * max(10, (gy1 - 14) - (gy0 + 4))
            c.create_rectangle(bx0 + 1, (gy1 - 14) - bh, bx0 + bw - 1, gy1 - 14, fill=bcol, outline="")
            c.create_text(bx0 + bw / 2, gy1 - 6, text=blbl, fill=COL_DIM, font=self._font(self._fs(0.66), bold=True))

        comb_x0 = gx0 + 3 * (bw + 6) + 10
        comb_w = max(24, split_x - comb_x0 - 10)
        comb_y1 = gy1 - 14
        comb_h = max(20, comb_y1 - (gy0 + 4))
        c.create_line(comb_x0, comb_y1, comb_x0 + comb_w, comb_y1, fill=COL_BORDER)
        taps = [0.05, 0.12, 0.20, 0.28, 0.38, 0.49, 0.61, 0.74, 0.87, 0.96]
        for idx, tf in enumerate(taps):
            tx = comb_x0 + (pre_n * 0.14 + tf * 0.86) * comb_w
            amp = max(0.05, e_n) * (1.0 - idx * 0.07) * (0.76 + 0.24 * math.sin(idx * 2.2))
            c.create_line(tx, comb_y1, tx, comb_y1 - amp * comb_h, fill=accent, width=2.4)
            c.create_oval(tx - 2.5, comb_y1 - amp * comb_h - 2.5, tx + 2.5, comb_y1 - amp * comb_h + 2.5,
                          fill="#ffffff", outline="")
        c.create_text(comb_x0 + comb_w / 2, gy1 - 6, text="Room Early Taps", fill=COL_DIM,
                      font=self._font(self._fs(0.68)))

        scx = (split_x + gx1) / 2.0
        scy = gy1 - 14
        srad = min((gx1 - split_x) * 0.44, gh * 0.78)
        c.create_arc(scx - srad, scy - srad, scx + srad, scy + srad, start=0, extent=180,
                     style="arc", outline=COL_GRID, width=1)
        half_ang = math.radians(8.0 + wid_n * 76.0)
        fan = [scx, scy]
        for i in range(19):
            a = -half_ang + (2.0 * half_ang) * (i / 18.0)
            r = srad * (0.35 + 0.62 * max(e_n, l_n))
            fan.extend([scx + r * math.sin(a), scy - r * math.cos(a)])
        c.create_polygon(fan, fill="#1a2c3d", outline=accent, width=2)
        c.create_text(scx, gy1 - 6, text=f"Width {self._fmt(self._get_zctrl('width'), 'width')}",
                      fill=COL_DIM, font=self._font(self._fs(0.68), bold=True))

        hx = gx0 + e_n * gw
        hy = gy1 - l_n * gh
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                              {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                               "xk": "early_level", "yk": "late_level"}))

    def _draw_damp_vis(self, c, pad, vy0, vy1, w, accent):
        gx0, gx1 = pad + 26, w - pad - 12
        gy0, gy1 = vy0 + 22, vy1 - 16
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2.0

        ed_hz = max(200.0, self._raw(self._get_zctrl("early_damp"), 6000.0))
        ld_hz = max(200.0, self._raw(self._get_zctrl("late_damp"), 4000.0))
        lb_n = self._norm(self._get_zctrl("low_boost"), 0.2)
        hc_hz = max(200.0, self._raw(self._get_zctrl("in_high_cut"), 16000.0))
        lc_hz = max(20.0, self._raw(self._get_zctrl("in_low_cut"), 20.0))

        c.create_text(pad + 10, vy0 + 11, text="Spectral Damping (Blue=Early, Orange=Late)  (2D: LateDamp×LowBoost)",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.74), bold=True))

        f_min, f_max = 20.0, 20000.0
        log_span = math.log(f_max / f_min)

        def hz_to_x(hz):
            hz = max(f_min, min(f_max, hz))
            return gx0 + (math.log(hz / f_min) / log_span) * gw

        c.create_line(gx0, mid_y, gx1, mid_y, fill="#3c4054", dash=(3, 3))
        for f_hz, flbl in ((50, "50"), (200, "200"), (1000, "1k"), (4000, "4k"), (12000, "12k")):
            fx = hz_to_x(f_hz)
            c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
            c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

        pts_late, pts_early = [], []
        poly_late = [gx0, gy1]
        for i in range(65):
            t = i / 64.0
            f = f_min * ((f_max / f_min) ** t)
            hp_in = 1.0 / math.sqrt(1.0 + (lc_hz / f) ** 4)
            lp_in = 1.0 / math.sqrt(1.0 + (f / hc_hz) ** 4)
            boost = 1.0 + lb_n * 0.55 / (1.0 + (f / 260.0) ** 2)
            ed_att = 1.0 / math.sqrt(1.0 + (f / ed_hz) ** 2)
            ld_att = 1.0 / math.sqrt(1.0 + (f / ld_hz) ** 2)
            px = gx0 + t * gw
            ve = max(0.02, min(1.0, 0.62 * hp_in * lp_in * ed_att))
            vl = max(0.02, min(1.0, 0.62 * boost * hp_in * lp_in * ld_att))
            pts_early.extend([px, gy1 - ve * gh])
            pts_late.extend([px, gy1 - vl * gh])
            poly_late.extend([px, gy1 - vl * gh])
        poly_late.extend([gx1, gy1])

        c.create_polygon(poly_late, fill="#2b2016", outline="")
        c.create_line(pts_early, fill="#4dabf7", width=1.8, dash=(3, 3))
        c.create_line(pts_late, fill=accent, width=2.8)

        hx = hz_to_x(ld_hz)
        hy = gy1 - lb_n * gh
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                              {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                               "xk": "late_damp", "yk": "low_boost"}))

    def _draw_mod_vis(self, c, pad, vy0, vy1, w, accent):
        gx0, gx1 = pad + 14, w - pad - 14
        gy0, gy1 = vy0 + 22, vy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2.0

        spn_n = self._norm(self._get_zctrl("spin"), 0.3)
        wnd_n = self._norm(self._get_zctrl("wander"), 0.35)
        es_n = self._norm(self._get_zctrl("early_send"), 0.3)
        c.create_text(gx0, vy0 + 11, text="Room Tail Modulation  (Drag 2D: X=Spin Rate, Y=Wander Depth)",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(3, 4))

        cycles = 1.0 + spn_n * 5.0
        amp = (0.10 + wnd_n * 0.38) * gh
        pts_l, pts_r = [], []
        for i in range(73):
            t = i / 72.0
            drift = es_n * 0.7 * math.sin(t * math.pi * 2.0 * 0.6)
            yl = mid_y - math.sin(t * math.pi * 2.0 * cycles + drift) * amp
            yr = mid_y - math.sin(t * math.pi * 2.0 * cycles + 1.2 - drift) * amp * 0.82
            px = gx0 + t * gw
            pts_l.extend([px, yl])
            pts_r.extend([px, yr])
        c.create_line(pts_r, fill="#51cf66", width=1.8, dash=(3, 3))
        c.create_line(pts_l, fill=accent, width=2.8)

        hx = gx0 + spn_n * gw
        hy = gy1 - wnd_n * gh
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                              {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                               "xk": "spin", "yk": "wander"}))

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
        tw = (w - 2 * pad - 3 * gap) / 4
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        bot_h = 98
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap
        c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)

        if self.active_tab == "Space":
            self._draw_space_vis(c, pad, vy0, vy1, w, accent)
        elif self.active_tab == "Mix":
            self._draw_mix_vis(c, pad, vy0, vy1, w, accent)
        elif self.active_tab == "Damp / EQ":
            self._draw_damp_vis(c, pad, vy0, vy1, w, accent)
        else:
            self._draw_mod_vis(c, pad, vy0, vy1, w, accent)

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
                        self._select_page(payload)
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
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]), key=p["key"])
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]), key=p["xk"])
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]), key=p["yk"])
        self.last_snapshot = None
        self._draw()
