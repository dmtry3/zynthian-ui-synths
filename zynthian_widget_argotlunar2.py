#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Argotlunar2 Real-Time Granular Delay Widget for Zynthian (V5 800x480)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces Argotlunar2's 39 raw LV2 ports with 5 dynamic workstation tabs
# mapped 1-to-1 to Zynthian's 4 physical encoders + one-tap FREEZE button:
#   Grains | Pitch | Filter | Env | Mix/Mod   + FREEZE
#
# Features live Granular Cloud visualizer, Filter curve, Grain Envelope shape,
# interactive 2D touch pads (IOT x Duration, Pitch x Gliss, Freq x Q, Sustain x Skew),
# and double-tap reset.
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

TABS = ["Grains", "Pitch", "Filter", "Env", "Mix/Mod"]
TAB_ACCENTS = {
    "Grains":  "#ffd43b",
    "Pitch":   "#cc5de8",
    "Filter":  "#ff922b",
    "Env":     "#51cf66",
    "Mix/Mod": "#4dabf7",
}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


class zynthian_widget_argotlunar2(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Grains"
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
        if tab == "Grains":
            if self.sub_bank == 1:
                return [("iotv", "IOT Var"), ("durv", "Dur Var"), ("delayv", "Dly Var"), ("panv", "Pan Var")]
            return [("grains", "Grains"), ("iot", "IOT"), ("dur", "Duration"), ("delay", "Delay")]
        if tab == "Pitch":
            if self.sub_bank == 1:
                return [("scale", "Scale"), ("scale_key", "Key"), ("gliss", "Gliss"), ("glissv", "GlissVar")]
            return [("transpose", "Pitch"), ("transv", "PitchVar"), ("gliss", "Gliss"), ("scale", "Scale")]
        if tab == "Filter":
            return [("ffreq", "Freq"), ("fq", "Res Q"), ("ffreqv", "FreqVar"), ("filter_type", "Type")]
        if tab == "Env":
            return [("env_type", "Env Type"), ("env_sustain", "Sustain"), ("env_skew", "Skew"), ("ampv", "Amp Var")]
        # Mix/Mod
        if self.sub_bank == 1:
            return [("matrix_mod_1", "Mod 1"), ("matrix_mod_2", "Mod 2"), ("matrix_mod_3", "Mod 3"), ("pan", "Pan")]
        return [("mix", "Mix"), ("feedback", "Feedback"), ("input_gain", "In Gain"), ("amp", "Grn Amp")]

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
            logging.debug(f"Argotlunar2 live swap error: {e}")

    def _sync_list(self, tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page(tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Argotlunar2 sync error: {e}")

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
            return max(0.0, min(1.0, v))
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
        z.set_value(n, send=True)

    @staticmethod
    def _cycle_enum(z):
        if z is None:
            return
        ticks = getattr(z, "ticks", None)
        if ticks and len(ticks) > 0:
            idx = z.get_value2index() or 0
            z.set_value(ticks[(idx + 1) % len(ticks)], send=True)
        else:
            cur = float(z.get_value())
            z.set_value(0.0 if cur >= 0.5 else 1.0, send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        if getattr(z, "labels", None):
            try:
                return str(z.get_value2label())
            except Exception:
                pass
        v = zynthian_widget_argotlunar2._norm(z)
        if key in ("transpose", "gliss", "pan", "env_skew", "matrix_mod_1", "matrix_mod_2", "matrix_mod_3"):
            return f"{int(round((v - 0.5) * 200)):+d}%"
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
        keys = [k for k, _ in self._tab_items(self.active_tab)] + [
            "freeze_toggle", "trans_toggle", "gliss_toggle", "grains", "iot", "dur", "delay",
            "iotv", "durv", "delayv", "panv", "ffreq", "fq", "filter_type",
            "env_type", "env_sustain", "env_skew", "iot_quantize", "dur_quantize", "delay_quantize",
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
        return max(8, int(round(max(9, min(13, self.height // 34)) * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                      fill="#0d0e12" if active else COL_TEXT, font=self._font(self._fs(0.88), bold=True))
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        tx0, tx1 = x0 + 8, x1 - 8
        by1 = y1 - 6
        by0 = by1 - 11
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM, font=self._font(self._fs(0.84)))
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=self._fmt(z, key)[:11], anchor="e", fill=COL_TEXT,
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

    def _draw(self):
        c = self.widget_canvas
        w, h = self.width, self.height
        if w < 40 or h < 40:
            return
        c.delete("all")
        self.hitboxes = []

        pad, gap = 6, 6
        accent = TAB_ACCENTS[self.active_tab]
        freeze_on = self._raw(self._get_zctrl("freeze_toggle")) >= 0.5

        # Header: 5 Tabs + FREEZE Button
        hdr_h = max(36, min(46, int(h * 0.11)))
        frz_w = max(84, int((w - 2 * pad) * 0.14))
        tabs_w = w - 2 * pad - frz_w - gap
        tw = (tabs_w - (len(TABS) - 1) * gap) / len(TABS)
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        self._draw_pill(w - pad - frz_w, pad, w - pad, pad + hdr_h,
                        "FREEZE ●" if freeze_on else "FREEZE", freeze_on, "#38d9a9", "cycle", "freeze_toggle")

        # Row 2: Context Sub-banks & Quick Toggles
        r2_y0 = pad + hdr_h + gap
        r2_h = 34
        if self.active_tab in ("Grains", "Pitch", "Mix/Mod"):
            bnames = {
                "Grains":  ("Core Grains", "Variance"),
                "Pitch":   ("Pitch & Gliss", "Scale & Key"),
                "Mix/Mod": ("Mix & FB", "Mod Matrix"),
            }[self.active_tab]
            bw = int((w - 2 * pad) * 0.44)
            bw2 = (bw - gap) / 2
            for bi, blbl in enumerate(bnames):
                bx0 = pad + bi * (bw2 + gap)
                self._draw_pill(bx0, r2_y0, bx0 + bw2, r2_y0 + r2_h,
                                f"● {blbl}" if bi == self.sub_bank else blbl,
                                bi == self.sub_bank, accent, "sub_bank", bi)
            qx0 = pad + bw + gap
            if self.active_tab == "Grains":
                pills = [
                    (f"IOT: {self._fmt(self._get_zctrl('iot_quantize'), 'iot_quantize')}", False, "iot_quantize"),
                    (f"Dur: {self._fmt(self._get_zctrl('dur_quantize'), 'dur_quantize')}", False, "dur_quantize"),
                    (f"Dly: {self._fmt(self._get_zctrl('delay_quantize'), 'delay_quantize')}", False, "delay_quantize"),
                ]
            elif self.active_tab == "Pitch":
                p_on = self._raw(self._get_zctrl("trans_toggle")) >= 0.5
                g_on = self._raw(self._get_zctrl("gliss_toggle")) >= 0.5
                pills = [
                    ("Pitch: ON" if p_on else "Pitch: OFF", p_on, "trans_toggle"),
                    ("Gliss: ON" if g_on else "Gliss: OFF", g_on, "gliss_toggle"),
                    (f"Key: {self._fmt(self._get_zctrl('scale_key'), 'scale_key')}", False, "scale_key"),
                ]
            else:
                pills = [
                    (f"Grains: {self._fmt(self._get_zctrl('grains'), 'grains')}", False, "grains"),
                    (f"Env: {self._fmt(self._get_zctrl('env_type'), 'env_type')}", False, "env_type"),
                ]
            qw = (w - pad - qx0 - (len(pills) - 1) * gap) / len(pills)
            for i, (txt, on, k) in enumerate(pills):
                px = qx0 + i * (qw + gap)
                self._draw_pill(px, r2_y0, px + qw, r2_y0 + r2_h, txt, on, accent, "cycle", k)
        elif self.active_tab == "Filter":
            ft_z = self._get_zctrl("filter_type")
            ft_lbl = self._fmt(ft_z, "filter_type")
            self._draw_pill(pad, r2_y0, w - pad, r2_y0 + r2_h, f"Filter Type: {ft_lbl}  (Tap to cycle)",
                            ft_lbl.lower() != "off", accent, "cycle", "filter_type")
        else:
            et_lbl = self._fmt(self._get_zctrl("env_type"), "env_type")
            self._draw_pill(pad, r2_y0, w - pad, r2_y0 + r2_h, f"Grain Envelope: {et_lbl}  (Tap to cycle)",
                            False, accent, "cycle", "env_type")

        # Row 3: Interactive DSP Visualizer
        bot_h = 94
        vy0 = r2_y0 + r2_h + gap
        vy1 = h - pad - bot_h - gap
        c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL,
                           outline="#38d9a9" if freeze_on else accent, width=2 if freeze_on else 1)
        gx0, gx1 = pad + 14, w - pad - 14
        gy0, gy1 = vy0 + 22, vy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)

        if self.active_tab == "Filter":
            ff = self._norm(self._get_zctrl("ffreq"), 0.3)
            fq = self._norm(self._get_zctrl("fq"), 0.0)
            c.create_text(gx0, vy0 + 11, text="Grain Filter  (Drag 2D: X=Freq, Y=Q Resonance)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
            pts = []
            sig = max(0.04, 0.24 - fq * 0.18)
            for i in range(65):
                t = i / 64.0
                r = math.exp(-((t - ff) / sig) ** 2)
                pts.extend([gx0 + t * gw, gy1 - r * gh * 0.88])
            c.create_line(pts, fill=accent, width=2.6)
            hx, hy = gx0 + ff * gw, gy1 - fq * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "ffreq", "yk": "fq"}))
        elif self.active_tab == "Env":
            sus = self._norm(self._get_zctrl("env_sustain"), 0.0)
            skw = self._norm(self._get_zctrl("env_skew"), 0.5)
            c.create_text(gx0, vy0 + 11, text="Grain Window Envelope  (Drag 2D: X=Skew, Y=Sustain)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
            peak_x = gx0 + (0.1 + skw * 0.8) * gw
            flat_half = sus * gw * 0.35
            x_l = max(gx0 + 4, peak_x - flat_half)
            x_r = min(gx1 - 4, peak_x + flat_half)
            pts = [gx0, gy1, x_l, gy0 + 4, x_r, gy0 + 4, gx1, gy1]
            c.create_polygon(pts, fill="#1e3624", outline="")
            c.create_line(pts, fill=accent, width=2.8)
            hx, hy = gx0 + skw * gw, gy1 - sus * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "env_skew", "yk": "env_sustain"}))
        else:
            # Granular Cloud Visualizer
            gr_n = self._norm(self._get_zctrl("grains"), 0.5)
            iot_n = self._norm(self._get_zctrl("iot"), 0.25)
            dur_n = self._norm(self._get_zctrl("dur"), 0.3)
            panv = self._norm(self._get_zctrl("panv"), 0.5)
            n_grains = max(2, min(28, int(round(2 + gr_n * 24))))
            c.create_text(gx0, vy0 + 11, text="Granular Cloud  (Drag 2D: X=IOT Spacing, Y=Grain Duration)",
                          anchor="w", fill="#38d9a9" if freeze_on else COL_DIM, font=self._font(self._fs(0.80), bold=True))
            mid_y = (gy0 + gy1) / 2
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))
            for gi in range(n_grains):
                frac = gi / max(1, n_grains - 1)
                gx = gx0 + (0.05 + frac * 0.90) * gw
                gy = mid_y + math.sin(gi * 2.39996) * (gh * 0.40 * max(0.15, panv))
                rad_x = max(5.0, (0.04 + dur_n * 0.14) * gw * 0.5)
                rad_y = max(4.0, (0.10 + (1.0 - iot_n) * 0.18) * gh * 0.5)
                c.create_oval(gx - rad_x, gy - rad_y, gx + rad_x, gy + rad_y,
                              fill="#2f2a18" if not freeze_on else "#193330",
                              outline="#38d9a9" if freeze_on else accent, width=1.4)
            hx, hy = gx0 + iot_n * gw, gy1 - dur_n * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "xk": "iot", "yk": "dur"}))

        # Row 4: 2x2 Parameter Cards bound to 4 physical encoders
        py0 = vy1 + gap
        items = self._tab_items(self.active_tab)
        cw = (w - 2 * pad - gap) / 2
        ch = (h - pad - py0 - 4) / 2
        for i, (k, lbl) in enumerate(items):
            px0 = pad + (i % 2) * (cw + gap)
            py_i = py0 + (i // 2) * (ch + 4)
            bip = k in ("transpose", "gliss", "pan", "env_skew", "matrix_mod_1", "matrix_mod_2", "matrix_mod_3")
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, k, lbl, accent, bipolar=bip)

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
                if kind == "cycle":
                    self._cycle_enum(self._get_zctrl(payload))
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
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]))
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]))
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]))
        self.last_snapshot = None
        self._draw()
