#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# ZynAddSubFX Workstation Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces ZynAddSubFX's 11 raw controller pages with 6 dynamic workstation
# tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Main | Filter | Mod | Glide | Tone | Voice
#
# Features:
# - Live interactive Filter + Resonance 2D pad (Cutoff x Reso & Center x BW)
# - Live ModWheel Linear/Exp transfer curve + Pitch Bend Split visualizer
# - Live Portamento & Proportional Glide curve + quick toggle pills
# - Live Bandwidth detune-spread visualizer + Velocity Sens/Offset 2D curve
# - Full 2-way sync with Zynthian's 4 physical encoders & double-tap reset
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

TABS = ["Main", "Filter", "Mod", "Glide", "Tone", "Voice"]
TAB_ACCENTS = {
    "Main":   "#4dabf7",  # blue
    "Filter": "#ff922b",  # orange
    "Mod":    "#ffd43b",  # yellow
    "Glide":  "#51cf66",  # green
    "Tone":   "#cc5de8",  # violet
    "Voice":  "#ff6b6b",  # coral
}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


class zynthian_widget_zynaddsubfx(zynthian_widget_base.zynthian_widget_base):

    # ECO defaults: Voice Limit 8, no unison (not applicable), low quality
    ECO_PARAMS = {
        "voice limit": 8,
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Main"
        self.flt_bank = 0   # 0: Filter Core, 1: Resonance
        self.mod_bank = 0   # 0: ModWheel, 1: PitchWheel
        self.gld_bank = 0   # 0: Portamento, 1: Proportional
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
        # Ensure generic filter/envelope widgets do not hijack ZynAddSubFX tabs
        for z in processor.controllers_dict.values():
            if z is not None:
                if hasattr(z, "filter"):
                    try:
                        delattr(z, "filter")
                    except Exception:
                        pass
                if hasattr(z, "envelope"):
                    try:
                        delattr(z, "envelope")
                    except Exception:
                        pass
        try:
            if hasattr(self.zyngui_control, "screen_type"):
                self.zyngui_control.screen_type = None
        except Exception:
            pass

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
            k = _norm_key(sym)
            if k:
                idx[k] = z
            zn = getattr(z, "name", None)
            if zn:
                kn = _norm_key(zn)
                if kn and kn not in idx:
                    idx[kn] = z
        self._ctrl_index = idx

    def _get_zctrl(self, sym):
        return self._ctrl_index.get(_norm_key(sym)) if self.processor else None

    def _tab_items(self, tab):
        if tab == "Main":
            return [
                ("volume",           "Volume"),
                ("panning",          "Pan"),
                ("filter cutoff",    "Cutoff"),
                ("filter resonance", "Reso"),
            ]
        if tab == "Filter":
            if self.flt_bank == 1:
                return [
                    ("resonance center",    "Res Ctr"),
                    ("resonance bandwidth", "Res BW"),
                    ("rescenter depth",     "Ctr Dpth"),
                    ("resbw depth",         "BW Dpth"),
                ]
            return [
                ("filter cutoff",       "Cutoff"),
                ("filter resonance",    "Reso"),
                ("filter.cutoff depth", "Cut Dpth"),
                ("filter.Q depth",      "Q Dpth"),
            ]
        if tab == "Mod":
            if self.mod_bank == 1:
                return [
                    ("bendrange",       "Bend Up"),
                    ("bendrange down",  "Bend Dn"),
                    ("bendrange split", "Split"),
                    ("panning depth",   "Pan Dpth"),
                ]
            return [
                ("modulation",           "ModWhl"),
                ("modulation amplitude", "Mod Amp"),
                ("modwheel depth",       "MW Dpth"),
                ("modwheel exp",         "MW Exp"),
            ]
        if tab == "Glide":
            if self.gld_bank == 1:
                return [
                    ("portaprop on/off", "Prop On"),
                    ("portaprop rate",   "Prop Rt"),
                    ("portaprop depth",  "Prop Dp"),
                    ("portamento auto",  "Auto"),
                ]
            return [
                ("portamento time",    "Time"),
                ("portamento up/down", "Up/Down"),
                ("threshold",          "Thresh"),
                ("portamento enable",  "Enable"),
            ]
        if tab == "Tone":
            return [
                ("bandwidth",       "Bandwdth"),
                ("bandwidth depth", "BW Dpth"),
                ("bandwidth exp",   "BW Exp"),
                ("panning depth",   "Pan Dpth"),
            ]
        # Voice
        return [
            ("velocity sens.", "Vel Sens"),
            ("velocity offs.", "Vel Offs"),
            ("assign mode",    "Mode"),
            ("voice limit",    "Voices"),
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
        if hasattr(self.zyngui_control, "screen_type"):
            self.zyngui_control.screen_type = None
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
            logging.debug(f"ZynAddSubFX live swap error: {e}")

    def _sync_list(self, tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            if hasattr(self.zyngui_control, "screen_type"):
                self.zyngui_control.screen_type = None
            self.zyngui_control.fill_list()
            self._select_page(tab)
            self._draw()
        except Exception as e:
            logging.debug(f"ZynAddSubFX sync error: {e}")

    def _select_page(self, title):
        try:
            if hasattr(self.zyngui_control, "screen_type"):
                self.zyngui_control.screen_type = None
            for i, row in enumerate(self.zyngui_control.list_data):
                if len(row) >= 5 and row[2] == title and row[3] is self.processor:
                    self.zyngui_control.select(i)
                    if hasattr(self.zyngui_control, "screen_type"):
                        self.zyngui_control.screen_type = None
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
            ticks = getattr(z, "ticks", None)
            if ticks and len(ticks) > 1:
                idx = z.get_value2index()
                if idx is not None:
                    return max(0.0, min(1.0, idx / float(len(ticks) - 1)))
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
            val = vmin + n * (vmax - vmin)
            if getattr(z, "is_integer", False):
                val = round(val)
            z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _cycle_enum(z):
        if z is None:
            return
        ticks = getattr(z, "ticks", None)
        if ticks and len(ticks) > 0:
            idx = z.get_value2index() or 0
            z.set_value(ticks[(idx + 1) % len(ticks)], send=True)
        else:
            vmin, vmax = float(z.value_min), float(z.value_max)
            cur = float(z.get_value())
            z.set_value(vmin if cur >= (vmin + vmax) * 0.5 else vmax, send=True)

    @staticmethod
    def _is_on(z):
        if z is None:
            return False
        try:
            if getattr(z, "labels", None):
                lbl = str(z.get_value2label()).lower()
                return lbl in ("on", "1", "true", "yes")
            return float(z.get_value()) >= (float(z.value_min) + float(z.value_max)) * 0.5
        except Exception:
            return False

    @staticmethod
    def _fmt(z, key=""):
        if z is None:
            return "--"
        try:
            if getattr(z, "labels", None):
                lbl = str(z.get_value2label())
                if "bendrange" in key:
                    return f"{lbl}st"
                return lbl
        except Exception:
            pass
        v = zynthian_widget_zynaddsubfx._raw(z)
        if key == "panning":
            if abs(v - 64) < 1.5:
                return "Center"
            return f"{int(round(64 - v))}L" if v < 64 else f"{int(round(v - 64))}R"
        if key == "voice limit":
            return "Unlim" if int(round(v)) == 0 else f"{int(round(v))}v"
        return f"{int(round(v))}"

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
            "volume", "panning", "filter cutoff", "filter resonance", "modulation",
            "assign mode", "drum mode", "voice limit", "resonance center", "resonance bandwidth",
            "portamento enable", "portamento auto", "portamento receive", "portaprop on/off",
            "threshold type", "modwheel exp", "bendrange split", "bandwidth exp",
        ]
        snap = (self.width, self.height, self.active_tab, self.flt_bank, self.mod_bank, self.gld_bank,
                self.eco_on,
                tuple(round(self._norm(self._get_zctrl(k)), 3) for k in keys))
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

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload, subtext=None):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        if subtext is not None:
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.28, text=text,
                          fill=COL_DIM if not active else "#1a1c22", font=self._font(self._fs(0.76)))
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.72, text=subtext,
                          fill=accent if not active else "#000000", font=self._font(self._fs(0.90), bold=True))
        else:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                          fill="#0d0e12" if active else COL_TEXT, font=self._font(self._fs(0.90), bold=True))
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_bank_bar(self, x0, y0, x1, y1, banks, active_idx, accent, bank_kind):
        c = self.widget_canvas
        gap = 6
        bw = (x1 - x0 - gap * (len(banks) - 1)) / len(banks)
        for i, lbl in enumerate(banks):
            bx0 = x0 + i * (bw + gap)
            act = (i == active_idx)
            c.create_rectangle(bx0, y0, bx0 + bw, y1,
                               fill=COL_PANEL_HI if act else COL_PANEL,
                               outline=accent if act else COL_BORDER, width=2 if act else 1)
            c.create_text(bx0 + bw / 2, (y0 + y1) / 2, text=f"● {lbl}" if act else lbl,
                          fill=accent if act else COL_TEXT, font=self._font(self._fs(0.86), bold=act))
            self.hitboxes.append((bx0, y0, bx0 + bw, y1, bank_kind, i))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z)
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

    def _draw_vfader(self, x0, y0, x1, y1, key, label, accent, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        tx0, tx1 = x0 + 6, x1 - 6
        ty0, ty1 = y0 + 20, y1 - 20
        c.create_text((x0 + x1) / 2, y0 + 10, text=label, fill=COL_TEXT, font=self._font(self._fs(0.82), bold=True))
        c.create_rectangle(tx0, ty0, tx1, ty1, fill=COL_TRACK, outline="")
        fy = ty1 - n * (ty1 - ty0)
        if bipolar:
            my = (ty0 + ty1) / 2
            c.create_rectangle(tx0, min(my, fy), tx1, max(my, fy), fill=accent, outline="")
            c.create_line(tx0 - 1, my, tx1 + 1, my, fill=COL_TEXT, width=1)
        elif ty1 - fy > 1:
            c.create_rectangle(tx0, fy, tx1, ty1, fill=accent, outline="")
        c.create_line(tx0, fy, tx1, fy, fill="#ffffff", width=2)
        c.create_text((x0 + x1) / 2, y1 - 10, text=self._fmt(z, key), fill=COL_DIM, font=self._font(self._fs(0.76)))
        self.hitboxes.append((x0, y0, x1, y1, "vfader", {"key": key, "ty0": ty0, "ty1": ty1}))

    def _toggle_eco(self):
        """ECO: ограничивает Voice Limit до 8 (корректно сохраняя и восстанавливая 0=Unlimited)."""
        vl_z = self._get_zctrl("voice limit")
        if not self.eco_on:
            if vl_z is not None:
                cur_val = vl_z.get_value()
                self._eco_saved["voice limit"] = cur_val
                ticks = getattr(vl_z, "ticks", None)
                if ticks:
                    # Выбираем тик, ближайший к 8 голосам (исключая 0=Unlimited)
                    numeric_ticks = [t for t in ticks if isinstance(t, (int, float)) and t > 0]
                    target = min(numeric_ticks, key=lambda t: abs(t - 8)) if numeric_ticks else ticks[min(len(ticks) - 1, 1)]
                    vl_z.set_value(target, send=True)
                else:
                    vmin = float(getattr(vl_z, "value_min", 0))
                    vmax = float(getattr(vl_z, "value_max", 60))
                    target = max(vmin, min(vmax, 8))
                    vl_z.set_value(int(round(target)) if getattr(vl_z, "is_integer", False) else target, send=True)
            self.eco_on = True
        else:
            if vl_z is not None and "voice limit" in self._eco_saved:
                saved = self._eco_saved["voice limit"]
                limit = saved if saved is not None else 0
                vl_z.set_value(limit, send=True)
            self.eco_on = False
        self.last_snapshot = None
        self._draw()

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

        # ECO кнопка — справа, фиксированная ширина (зелёный акцент по стандарту GEMINI.md)
        eco_w = max(44, int(w * 0.072))
        eco_col = "#40c057" if self.eco_on else COL_PANEL
        eco_brd = "#51cf66" if self.eco_on else COL_BORDER
        eco_txt = "#0d0e12" if self.eco_on else COL_DIM
        c.create_rectangle(w - pad - eco_w, pad, w - pad, pad + hdr_h,
                           fill=eco_col, outline=eco_brd, width=2 if self.eco_on else 1)
        c.create_text(w - pad - eco_w / 2, pad + hdr_h / 2, text="ECO",
                      fill=eco_txt, font=self._font(self._fs(0.82), bold=True))
        self.hitboxes.append((w - pad - eco_w, pad, w - pad, pad + hdr_h, "eco", None))

        # Tabs — с учётом ECO кнопки справа
        tabs_x1 = w - pad - eco_w - gap
        tw = (tabs_x1 - pad - (len(TABS) - 1) * gap) / len(TABS)
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        by0 = pad + hdr_h + gap
        by1 = h - pad
        bx0, bx1 = pad, w - pad

        if self.active_tab == "Main":
            self._draw_tab_main(bx0, by0, bx1, by1, accent)
        elif self.active_tab == "Filter":
            self._draw_tab_filter(bx0, by0, bx1, by1, accent)
        elif self.active_tab == "Mod":
            self._draw_tab_mod(bx0, by0, bx1, by1, accent)
        elif self.active_tab == "Glide":
            self._draw_tab_glide(bx0, by0, bx1, by1, accent)
        elif self.active_tab == "Tone":
            self._draw_tab_tone(bx0, by0, bx1, by1, accent)
        else:
            self._draw_tab_voice(bx0, by0, bx1, by1, accent)

    def _draw_bottom_grid(self, x0, y0, x1, y1, tab, accent):
        items = self._tab_items(tab)
        cw = (x1 - x0 - 6) / 2
        ch = (y1 - y0 - 4) / 2
        for i, (k, lbl) in enumerate(items):
            px0 = x0 + (i % 2) * (cw + 6)
            py0 = y0 + (i // 2) * (ch + 4)
            bip = k in ("panning", "portamento up/down", "bendrange", "bendrange down")
            self._draw_param_box(px0, py0, px0 + cw, py0 + ch, k, lbl, accent, bipolar=bip)

    def _draw_tab_main(self, x0, y0, x1, y1, accent):
        gap = 6
        r1_h = 38
        pw = (x1 - x0 - 2 * gap) / 3
        self._draw_pill(x0, y0, x0 + pw, y0 + r1_h, "Assign Mode", False, accent,
                        "cycle", "assign mode", subtext=self._fmt(self._get_zctrl("assign mode")))
        dm_on = self._is_on(self._get_zctrl("drum mode"))
        self._draw_pill(x0 + pw + gap, y0, x0 + 2 * pw + gap, y0 + r1_h, "Drum Mode",
                        dm_on, "#ff922b", "cycle", "drum mode", subtext="ON" if dm_on else "OFF")
        self._draw_pill(x0 + 2 * (pw + gap), y0, x1, y0 + r1_h, "Voice Limit", False, "#51cf66",
                        "tab", "Voice", subtext=self._fmt(self._get_zctrl("voice limit"), "voice limit"))

        fy0 = y0 + r1_h + gap
        faders = [
            ("volume",           "VOLUME", "#51cf66", False),
            ("panning",          "PAN",    "#4dabf7", True),
            ("filter cutoff",    "CUTOFF", "#ff922b", False),
            ("filter resonance", "RESO",   "#ff922b", False),
            ("modulation",       "MOD",    "#ffd43b", False),
        ]
        fw = (x1 - x0 - (len(faders) - 1) * gap) / len(faders)
        for i, (k, lbl, col, bip) in enumerate(faders):
            fx0 = x0 + i * (fw + gap)
            self._draw_vfader(fx0, fy0, fx0 + fw, y1, k, lbl, col, bipolar=bip)

    def _draw_tab_filter(self, x0, y0, x1, y1, accent):
        c = self.widget_canvas
        gap = 6
        r1_h = 34
        self._draw_bank_bar(x0, y0, x1, y0 + r1_h, ["Filter Core", "Resonance Formant"], self.flt_bank, accent, "flt_bank")

        bot_h = 92
        gy0 = y0 + r1_h + gap
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)
        gx0, gx1 = x0 + 14, x1 - 14
        g_top, g_bot = gy0 + 22, gy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)
        base_y = g_top + gh * 0.56
        c.create_line(gx0, base_y, gx1, base_y, fill=COL_GRID, dash=(2, 4))

        cut = self._norm(self._get_zctrl("filter cutoff"), 0.5)
        res = self._norm(self._get_zctrl("filter resonance"), 0.5)
        rc = self._norm(self._get_zctrl("resonance center"), 0.5)
        rbw = self._norm(self._get_zctrl("resonance bandwidth"), 0.5)

        if self.flt_bank == 0:
            c.create_text(gx0, gy0 + 11, text="ZynAddSubFX Filter  (Drag 2D: X=Cutoff, Y=Resonance)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
            xk, yk, hx, hy = "filter cutoff", "filter resonance", gx0 + cut * gw, g_bot - res * gh
        else:
            c.create_text(gx0, gy0 + 11, text="Formant Resonance  (Drag 2D: X=Res Center, Y=Res Bandwidth)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
            xk, yk, hx, hy = "resonance center", "resonance bandwidth", gx0 + rc * gw, g_bot - rbw * gh

        pts = []
        for i in range(65):
            t = i / 64.0
            d = (t - cut) * 10.0
            resp = -max(0.0, d) * 0.32 + res * 0.48 * math.exp(-(d * 1.5) ** 2)
            resp += 0.22 * math.exp(-((t - rc) / max(0.05, 0.25 - rbw * 0.18)) ** 2)
            py = max(g_top + 2, min(g_bot - 2, base_y - resp * (gh * 0.72)))
            pts.extend([gx0 + t * gw, py])
        c.create_line(pts, fill=accent, width=2.6)
        c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
        self.hitboxes.append((x0, gy0, x1, gy1, "xy_pad", {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot, "xk": xk, "yk": yk}))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Filter", accent)

    def _draw_tab_mod(self, x0, y0, x1, y1, accent):
        c = self.widget_canvas
        gap = 6
        r1_h = 34
        self._draw_bank_bar(x0, y0, x1, y0 + r1_h, ["ModWheel", "PitchWheel"], self.mod_bank, accent, "mod_bank")

        bot_h = 92
        gy0 = y0 + r1_h + gap
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)
        gx0, gx1 = x0 + 14, x1 - 14
        g_top, g_bot = gy0 + 22, gy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)

        if self.mod_bank == 0:
            # ModWheel: кривая отклика (Linear / Exponential) + 2D-пэд Mod × Depth
            mw = self._norm(self._get_zctrl("modulation"), 0.0)
            mwd = self._norm(self._get_zctrl("modwheel depth"), 0.6)
            exp_on = self._is_on(self._get_zctrl("modwheel exp"))
            c.create_text(gx0, gy0 + 11,
                          text=f"ModWheel Response ({'Exponential' if exp_on else 'Linear'})  (Drag 2D: X=Mod, Y=Depth)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
            # кривая отклика MW
            pts = []
            for i in range(49):
                t = i / 48.0
                yv = (t ** 2.4 if exp_on else t) * mwd
                pts.extend([gx0 + t * gw, g_bot - yv * gh])
            c.create_line(pts, fill=accent, width=2.6)
            # текущая позиция: X = MW position, Y = depth
            hx, hy = gx0 + mw * gw, g_bot - mwd * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((x0, gy0, x1, gy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot,
                                   "xk": "modulation", "yk": "modwheel depth"}))
        else:
            # PitchWheel: диаграмма Bend Up / Bend Down + Split-точка
            br_z = self._get_zctrl("bendrange")
            brd_z = self._get_zctrl("bendrange down")
            spl_z = self._get_zctrl("bendrange split")
            pan_z = self._get_zctrl("panning depth")
            br = self._norm(br_z, 0.5)
            brd = self._norm(brd_z, 0.5)
            spl = self._norm(spl_z, 0.5)
            split_on = self._is_on(spl_z)

            c.create_text(gx0, gy0 + 11,
                          text="Pitch Bend Range  (Drag: X=Bend Up, Y=Bend Down)  Split shown as line",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))

            # Нулевая ось (нет бенда)
            mid_y = (g_top + g_bot) / 2
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

            # Верхний диапазон бенда (Bend Up) — треугольник вверх
            up_tip = g_top + (1.0 - br) * (mid_y - g_top) + 2
            pts_up = [gx0, mid_y, gx1, mid_y, gx1, up_tip, gx0, up_tip]
            c.create_polygon(pts_up, fill=accent + "44", outline="")
            c.create_line(gx0, up_tip, gx1, up_tip, fill=accent, width=2)
            br_val = self._fmt(br_z, "bendrange")
            c.create_text(gx1 - 6, up_tip + 10, text=f"+{br_val}", anchor="e",
                          fill=accent, font=self._font(self._fs(0.86), bold=True))

            # Нижний диапазон бенда (Bend Down) — треугольник вниз
            dn_tip = mid_y + (1.0 - brd) * (g_bot - mid_y) - 2
            pts_dn = [gx0, mid_y, gx1, mid_y, gx1, dn_tip, gx0, dn_tip]
            c.create_polygon(pts_dn, fill="#ff6b6b44", outline="")
            c.create_line(gx0, dn_tip, gx1, dn_tip, fill="#ff6b6b", width=2)
            brd_val = self._fmt(brd_z, "bendrange down")
            c.create_text(gx1 - 6, dn_tip - 10, text=f"-{brd_val}", anchor="e",
                          fill="#ff6b6b", font=self._font(self._fs(0.86), bold=True))

            # Split линия (делит клавиатуру по MIDI-ноте)
            if split_on:
                spl_x = gx0 + spl * gw
                c.create_line(spl_x, g_top, spl_x, g_bot, fill="#ffd43b", width=2, dash=(4, 3))
                c.create_text(spl_x + 4, g_top + 8, text="Split", anchor="w",
                              fill="#ffd43b", font=self._font(self._fs(0.78)))

            # Маркеры-ручки для Bend Up (gx1) и Bend Down
            c.create_oval(gx1 - 10, up_tip - 8, gx1 + 2, up_tip + 8,
                          fill=accent, outline="#ffffff", width=2)
            c.create_oval(gx1 - 10, dn_tip - 8, gx1 + 2, dn_tip + 8,
                          fill="#ff6b6b", outline="#ffffff", width=2)

            # 2D-пэд: X = Bend Up, Y = Bend Down
            self.hitboxes.append((x0, gy0, x1, gy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot,
                                   "xk": "bendrange", "yk": "bendrange down"}))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Mod", accent)

    def _draw_tab_glide(self, x0, y0, x1, y1, accent):
        c = self.widget_canvas
        gap = 6
        r1_h = 34
        self._draw_bank_bar(x0, y0, x1, y0 + r1_h, ["Portamento", "Proportional"], self.gld_bank, accent, "gld_bank")

        r2_y0 = y0 + r1_h + gap
        r2_h = 34
        togs = [
            ("Enable", "portamento enable"),
            ("Auto",   "portamento auto"),
            ("Recv",   "portamento receive"),
            ("Prop",   "portaprop on/off"),
            (f"Thr {self._fmt(self._get_zctrl('threshold type'))}", "threshold type"),
        ]
        tw = (x1 - x0 - 4 * 4) / 5
        for i, (lbl, k) in enumerate(togs):
            tx = x0 + i * (tw + 4)
            self._draw_pill(tx, r2_y0, tx + tw, r2_y0 + r2_h, lbl, self._is_on(self._get_zctrl(k)), accent, "cycle", k)

        bot_h = 92
        gy0 = r2_y0 + r2_h + gap
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)
        gx0, gx1 = x0 + 14, x1 - 14
        g_top, g_bot = gy0 + 22, gy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)

        pt = self._norm(self._get_zctrl("portamento time"), 0.5)
        pud = self._norm(self._get_zctrl("portamento up/down"), 0.5)
        c.create_text(gx0, gy0 + 11, text="Portamento Glide Curve  (Drag 2D: X=Time, Y=Up/Down Stretch)",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
        pts = []
        k_exp = 0.5 + pt * 4.0
        for i in range(49):
            t = i / 48.0
            y = 1.0 - math.exp(-t * (5.0 / max(0.4, k_exp)))
            pts.extend([gx0 + t * gw, g_bot - y * gh])
        c.create_line(pts, fill=accent, width=2.6)
        hx, hy = gx0 + pt * gw, g_bot - pud * gh
        c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
        self.hitboxes.append((x0, gy0, x1, gy1, "xy_pad", {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot, "xk": "portamento time", "yk": "portamento up/down"}))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Glide", accent)

    def _draw_tab_tone(self, x0, y0, x1, y1, accent):
        c = self.widget_canvas
        gap = 6
        bot_h = 96
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, y0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)
        gx0, gx1 = x0 + 14, x1 - 14
        g_top, g_bot = y0 + 22, gy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)

        bw = self._norm(self._get_zctrl("bandwidth"), 0.5)
        bwd = self._norm(self._get_zctrl("bandwidth depth"), 0.5)
        c.create_text(gx0, y0 + 11, text="Harmonic Detune Bandwidth  (Drag 2D: X=Bandwidth, Y=Depth)",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
        mid_x = (gx0 + gx1) / 2
        spread = (0.04 + bw * 0.42) * gw
        for k in range(-4, 5):
            lx = mid_x + (k / 4.0) * spread
            amp = (1.0 - abs(k) * 0.16) * (0.3 + 0.7 * bwd)
            c.create_line(lx, g_bot, lx, g_bot - amp * gh, fill=accent if k == 0 else "#7a3b91", width=3 if k == 0 else 2)
        hx, hy = gx0 + bw * gw, g_bot - bwd * gh
        c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
        self.hitboxes.append((x0, y0, x1, gy1, "xy_pad", {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot, "xk": "bandwidth", "yk": "bandwidth depth"}))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Tone", accent)

    def _draw_tab_voice(self, x0, y0, x1, y1, accent):
        c = self.widget_canvas
        gap = 6
        bot_h = 96
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, y0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)
        gx0, gx1 = x0 + 14, x1 - 14
        g_top, g_bot = y0 + 22, gy1 - 14
        gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)

        vs = self._norm(self._get_zctrl("velocity sens."), 0.5)
        vo = self._norm(self._get_zctrl("velocity offs."), 0.5)
        c.create_text(gx0, y0 + 11, text="Velocity Response Curve  (Drag 2D: X=Sensitivity, Y=Offset)",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))
        pts = []
        for i in range(49):
            t = i / 48.0
            y = max(0.0, min(1.0, (1.0 - vs) + vs * t + (vo - 0.5) * 0.6))
            pts.extend([gx0 + t * gw, g_bot - y * gh])
        c.create_line(pts, fill=accent, width=2.6)
        hx, hy = gx0 + vs * gw, g_bot - vo * gh
        c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
        self.hitboxes.append((x0, y0, x1, gy1, "xy_pad", {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot, "xk": "velocity sens.", "yk": "velocity offs."}))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Voice", accent)

    def _on_press(self, event):
        self.drag_target = None
        for x0, y0, x1, y1, kind, payload in reversed(self.hitboxes):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if kind == "eco":
                    self._toggle_eco()
                    return
                if kind == "tab":
                    if payload != self.active_tab:
                        self.active_tab = payload
                        self._live_swap(payload)
                        self._select_page(payload)
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind in ("flt_bank", "mod_bank", "gld_bank"):
                    if getattr(self, kind) != payload:
                        setattr(self, kind, payload)
                        self._live_swap(self.active_tab)
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "cycle":
                    self._cycle_enum(self._get_zctrl(payload))
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind in ("vfader", "hfader", "xy_pad"):
                    now = time.monotonic()
                    tid = (kind, payload.get("key") or payload.get("xk"))
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = [payload["key"]] if kind != "xy_pad" else [payload["xk"], payload["yk"]]
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
        if kind == "vfader" and p["ty1"] > p["ty0"]:
            self._set_norm(self._get_zctrl(p["key"]), (p["ty1"] - y) / (p["ty1"] - p["ty0"]))
        elif kind == "hfader" and p["tx1"] > p["tx0"]:
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]))
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]))
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]))
        self.last_snapshot = None
        self._draw()
