#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Noize Mak3r (TAL-NoiseMaker) Workstation Widget for Zynthian (V5 800x480)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces TAL-NoiseMaker's 93 raw LV2 parameters (~24 encoder pages) with 6
# dynamic workstation tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Osc | Filter | Env | LFO | FX | Perf
#
# Features:
# - Authentic TAL-NoiseMaker DSP scales & exact scalePoint values (11 filter
#   types incl. Moog 24dB & SV 24dB, Osc 1/2 waveforms, LFO 1/2 shapes & dests,
#   Free AD & Envelope Editor routing, Juno-style Chorus I/II, Reverb & Delay).
# - Real-time interactive visualizations:
#   * Osc: Osc 1 + Osc 2 + Sub live synthesized waveform scope & mixer bars
#   * Filter: 11-model filter selector + log-Hz 2D XY pad (Cutoff x Resonance)
#   * Env: interactive 2D dual ADSR (Amp + Filter) + Free AD envelope graph
#   * LFO: live LFO 1 & LFO 2 waveform scope + Sync/KeyTrig/Dest selectors
#   * FX: big Juno-style Chorus I / II buttons + Reverb / Delay / Bitcrusher
#   * Perf: Voices, Portamento, Velocity matrix, Slop, Vintage Noise & Master
# - Unified Design System (UI Synths): >=34px touch targets, 6px gaps, _fit_font
#   zero-overflow labels, double-tap reset on all sliders & 2D nodes, ~16 FPS.
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

# ------------------------------------------------------------------------------
# Theme Palette (Unified UI Synths Design System)
# ------------------------------------------------------------------------------
COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

TABS = ["Osc", "Filter", "Env", "LFO", "FX", "Perf"]
TAB_ACCENTS = {
    "Osc":    "#cc5de8",  # violet
    "Filter": "#ff922b",  # orange
    "Env":    "#51cf66",  # green
    "LFO":    "#ffd43b",  # yellow
    "FX":     "#ff6b6b",  # coral
    "Perf":   "#4dabf7",  # blue
}

# ------------------------------------------------------------------------------
# Authentic TAL-NoiseMaker ScalePoints (from LV2 TTL)
# ------------------------------------------------------------------------------
OSC1_WAVES = [(0.0, "Saw"), (0.25, "Pulse"), (0.75, "Noise")]
OSC2_WAVES = [(0.0, "Saw"), (0.125, "Pulse"), (0.375, "Tri"), (0.625, "Sine"), (0.875, "Noise")]

FILTER_TYPES = [
    (0.000, "LP 24"), (0.050, "LP 18"), (0.140, "LP 12"), (0.230, "LP 6"),
    (0.320, "HP 12"), (0.410, "BP 12"), (0.500, "Notch"), (0.595, "SV LP"),
    (0.685, "SV HP"), (0.775, "SV BP"), (0.865, "Moog24"),
]

LFO_WAVES = [
    (0.0, "Sine"), (0.2, "Tri"), (0.4, "Saw"), (0.6, "Sqr"), (0.8, "S&H"), (1.0, "Noise"),
]

LFO1_DESTS = [
    (0.000, "Off"), (0.075, "Filter"), (0.215, "Osc1"), (0.360, "Osc2"),
    (0.500, "PW"), (0.645, "FM"), (0.790, "LFO2 R"), (0.930, "Osc1+2"),
]
LFO2_DESTS = [
    (0.000, "Off"), (0.075, "Filter"), (0.215, "Osc1"), (0.360, "Osc2"),
    (0.500, "Pan"), (0.645, "Volume"), (0.790, "LFO1 R"), (0.930, "Osc1+2"),
]
FREE_DESTS = [
    (0.0, "Off"), (0.1, "Filter"), (0.3, "Osc1"), (0.5, "Osc2"), (0.7, "PW"), (0.9, "FM"),
]
VOICE_MODES = [(0.0, "Mono"), (0.1, "2v"), (0.3, "3v"), (0.5, "4v"), (0.7, "5v"), (0.9, "6v")]
PORTA_MODES = [(0.0, "Off"), (0.25, "Auto"), (0.75, "On")]
TRANSPOSE_VALS = [(0.0, "-1 Oct"), (0.335, "0 Oct"), (0.67, "+1 Oct"), (1.0, "+2 Oct")]

ENUM_TABLES = {
    "osc1waveform":      OSC1_WAVES,
    "osc2waveform":      OSC2_WAVES,
    "filtertype":        FILTER_TYPES,
    "lfo1waveform":      LFO_WAVES,
    "lfo2waveform":      LFO_WAVES,
    "lfo1destination":   LFO1_DESTS,
    "lfo2destination":   LFO2_DESTS,
    "freeaddestination": FREE_DESTS,
    "voices":            VOICE_MODES,
    "portamentomode":    PORTA_MODES,
    "transpose":         TRANSPOSE_VALS,
}

TOGGLE_KEYS = {
    "oscsync", "lfo1sync", "lfo1keytrigger", "lfo2sync", "lfo2keytrigger",
    "chorus1enable", "chorus2enable", "delaysync", "delayfactorl", "delayfactorr",
    "envelopeoneshot", "envelopefixtempo",
}

BIPOLAR_KEYS = {
    "filtercontour", "osc1tune", "osc2tune", "osc1finetune", "osc2finetune",
    "oscmastertune", "lfo1amount", "lfo2amount", "freeadamount", "envelopeeditoramount",
}


def _norm_key(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def nm_cutoff_hz(norm):
    return 20.0 * (1000.0 ** max(0.0, min(1.0, float(norm))))


def fmt_hz(hz):
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}k" if hz < 10000.0 else f"{hz / 1000.0:.1f}k"
    return f"{int(round(hz))}Hz"


# ------------------------------------------------------------------------------
# Noize Mak3r Workstation Widget Class
# ------------------------------------------------------------------------------
class zynthian_widget_noize_mak3r(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)

        self.active_tab = "Osc"
        self.osc_bank = 0    # 0=Levels/PW, 1=Tuning, 2=FM/Ring/Crush
        self.flt_bank = 0    # 0=Cut/Res/Drv, 1=Contour/Key/HP
        self.env_idx = 0     # 0=Amp ADSR, 1=Filter ADSR, 2=Free AD
        self.lfo_idx = 0     # 0=LFO 1, 1=LFO 2
        self.fx_bank = 0     # 0=Reverb, 1=Delay, 2=Delay Cut/Crush
        self.perf_bank = 0   # 0=Voice/Vol, 1=Velocity, 2=Bend/Analog

        self._ctrl_index = {}
        self._enhanced_procs = set()
        self._bound_proc_id = None
        self.last_screen_title = None
        self.last_snapshot = None
        self.next_update = 0.0
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._fonts = {}

        self.widget_canvas = tkinter.Canvas(
            self,
            highlightthickness=0,
            relief="flat",
            bg=COL_BG,
        )
        self.widget_canvas.grid(sticky="news")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.widget_canvas.bind("<ButtonPress-1>", self._on_press)
        self.widget_canvas.bind("<B1-Motion>", self._on_drag)
        self.widget_canvas.bind("<ButtonRelease-1>", self._on_release)

    # --------------------------------------------------------------------------
    # Processor Setup & Controller Resolver
    # --------------------------------------------------------------------------
    def set_processor(self, processor):
        super().set_processor(processor)
        if processor is None:
            return
        self._build_ctrl_index(processor)
        pid = id(processor)
        if pid not in self._enhanced_procs:
            self._enhanced_procs.add(pid)
            self._enhance_all_zctrls()
        if self._bound_proc_id != pid:
            self._bound_proc_id = pid
            self._rebuild_all_pages(select_tab=self.active_tab, rebuild_list=True)

    def _build_ctrl_index(self, processor):
        idx = {}
        for sym, z in processor.controllers_dict.items():
            idx[_norm_key(sym)] = z
            for attr in ("name", "short_name"):
                val = getattr(z, attr, None)
                if val:
                    nk = _norm_key(val)
                    if nk not in idx:
                        idx[nk] = z
        self._ctrl_index = idx

    def _get_zctrl(self, key):
        if not self.processor:
            return None
        z = self.processor.controllers_dict.get(key)
        if z is not None:
            return z
        return self._ctrl_index.get(_norm_key(key))

    def _enhance_all_zctrls(self):
        if self.processor:
            for z in self.processor.controllers_dict.values():
                for attr in ("filter", "envelope"):
                    if hasattr(z, attr):
                        try:
                            delattr(z, attr)
                        except Exception:
                            pass

    # --------------------------------------------------------------------------
    # Dynamic 4-Encoder Page Mapping (6 Tabs, 2-Level Sub-Banks)
    # --------------------------------------------------------------------------
    def _tab_items(self, tab_name):
        if tab_name == "Osc":
            if self.osc_bank == 0:
                return [
                    ("osc1volume", "Osc1 Lvl"),
                    ("osc2volume", "Osc2 Lvl"),
                    ("osc3volume", "Sub Lvl"),
                    ("osc1pw",     "Osc1 PW"),
                ]
            if self.osc_bank == 1:
                return [
                    ("osc1tune",     "Osc1 Tune"),
                    ("osc2tune",     "Osc2 Tune"),
                    ("osc1finetune", "Osc1 Fine"),
                    ("osc2finetune", "Osc2 Fine"),
                ]
            return [
                ("osc2fm",         "Osc2 FM"),
                ("ringmodulation", "Ring Mod"),
                ("detune",         "Osc Slop"),
                ("oscbitcrusher",  "BitCrush"),
            ]

        if tab_name == "Filter":
            if self.flt_bank == 0:
                return [
                    ("cutoff",        "Cutoff"),
                    ("resonance",     "Resonance"),
                    ("filterdrive",   "Flt Drive"),
                    ("filtercontour", "Contour"),
                ]
            return [
                ("filtertype", "Flt Type"),
                ("keyfollow",  "KeyFollow"),
                ("highpass",   "HighPass"),
                ("volume",     "Master Vol"),
            ]

        if tab_name == "Env":
            if self.env_idx == 0:
                return [
                    ("ampattack",  "Amp Att"),
                    ("ampdecay",   "Amp Dec"),
                    ("ampsustain", "Amp Sus"),
                    ("amprelease", "Amp Rel"),
                ]
            if self.env_idx == 1:
                return [
                    ("filterattack",  "Flt Att"),
                    ("filterdecay",   "Flt Dec"),
                    ("filtersustain", "Flt Sus"),
                    ("filterrelease", "Flt Rel"),
                ]
            return [
                ("freeadattack",      "Free Att"),
                ("freeaddecay",       "Free Dec"),
                ("freeadamount",      "Free Amt"),
                ("freeaddestination", "Free Dest"),
            ]

        if tab_name == "LFO":
            li = self.lfo_idx + 1
            return [
                (f"lfo{li}rate",        f"LFO{li} Rate"),
                (f"lfo{li}amount",      f"LFO{li} Amt"),
                (f"lfo{li}phase",       f"LFO{li} Phs"),
                (f"lfo{li}destination", f"LFO{li} Dest"),
            ]

        if tab_name == "FX":
            if self.fx_bank == 0:
                return [
                    ("reverbwet",      "Rev Wet"),
                    ("reverbdecay",    "Rev Decay"),
                    ("reverbpredelay", "PreDelay"),
                    ("reverbhighcut",  "Rev HiCut"),
                ]
            if self.fx_bank == 1:
                return [
                    ("delaywet",      "Dly Wet"),
                    ("delaytime",     "Dly Time"),
                    ("delayfeedback", "Dly Fdbk"),
                    ("delayhighshelf","Dly HiCut"),
                ]
            return [
                ("delaylowshelf", "Dly LoCut"),
                ("reverblowcut",  "Rev LoCut"),
                ("oscbitcrusher", "BitCrush"),
                ("highpass",      "HighPass"),
            ]

        # Perf
        if self.perf_bank == 0:
            return [
                ("volume",        "Volume"),
                ("portamento",    "Glide"),
                ("oscmastertune", "MasterTune"),
                ("vintagenoise",  "VintNoise"),
            ]
        if self.perf_bank == 1:
            return [
                ("velocityvolume",  "Vel Vol"),
                ("velocitycontour", "Vel Cntr"),
                ("velocitycutoff",  "Vel Cut"),
                ("detune",          "Osc Slop"),
            ]
        return [
            ("pitchwheelpitch",  "Bend Ptch"),
            ("pitchwheelcutoff", "Bend Cut"),
            ("voices",           "Voices"),
            ("transpose",        "Transpose"),
        ]

    def _build_page_zctrls(self, tab_name):
        zctrls = []
        for key, short_label in self._tab_items(tab_name):
            z = self._get_zctrl(key)
            if z is not None:
                z.short_name = short_label
                zctrls.append(z)
        return zctrls

    def _rebuild_all_pages(self, select_tab=None, rebuild_list=False):
        if not self.processor:
            return
        new_screens = {}
        for tname in TABS:
            zlist = self._build_page_zctrls(tname)
            if zlist:
                new_screens[tname] = zlist
        if not new_screens:
            return
        self.processor.ctrl_screens_dict = new_screens
        target = select_tab if select_tab in new_screens else self.active_tab
        self.active_tab = target
        self.last_snapshot = None

        if rebuild_list:
            self.after(25, lambda t=target: self._sync_zyngui_list(t))
        else:
            self._live_swap_encoders(target)

    def _live_swap_encoders(self, tab_name):
        if not self.processor:
            return
        zlist = self._build_page_zctrls(tab_name)
        self.processor.ctrl_screens_dict[tab_name] = zlist
        try:
            if self.zyngui_control.get_current_processor() is self.processor:
                if self.last_screen_title != tab_name:
                    self._select_page_by_title(tab_name)
                else:
                    self.zyngui_control.zcontrollers = zlist
                    for i in range(4):
                        ctrl = zlist[i] if i < len(zlist) else None
                        self.zyngui_control.set_zcontroller(i, ctrl)
        except Exception as e:
            logging.debug(f"Noize Mak3r widget: live swap error => {e}")

    def _sync_zyngui_list(self, target_tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page_by_title(target_tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Noize Mak3r widget: sync list error => {e}")

    def _select_page_by_title(self, title):
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
                title = info[2]
                if title != self.last_screen_title and title in TABS:
                    self.last_screen_title = title
                    self.active_tab = title
                    self.last_snapshot = None
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # Value Helpers (TAL-NoiseMaker uses 0.0..1.0 floats with scalePoint stops)
    # --------------------------------------------------------------------------
    @staticmethod
    def _norm(zctrl, default=0.0):
        if zctrl is None:
            return default
        try:
            return max(0.0, min(1.0, float(zctrl.get_value())))
        except Exception:
            return default

    @staticmethod
    def _set_norm(zctrl, norm_val):
        if zctrl is None:
            return
        zctrl.set_value(max(0.0, min(1.0, float(norm_val))), send=True)

    def _enum_idx(self, key):
        tbl = ENUM_TABLES.get(key)
        if not tbl:
            return 0
        v = self._norm(self._get_zctrl(key), 0.0)
        return min(range(len(tbl)), key=lambda i: abs(tbl[i][0] - v))

    def _cycle_key(self, key, step=1):
        z = self._get_zctrl(key)
        if z is None:
            return
        if key in TOGGLE_KEYS:
            cur_on = self._norm(z, 0.0) >= 0.0025
            z.set_value(0.0 if cur_on else 1.0, send=True)
            return
        tbl = ENUM_TABLES.get(key)
        if tbl:
            nxt = (self._enum_idx(key) + step) % len(tbl)
            z.set_value(tbl[nxt][0], send=True)
            return
        ticks = getattr(z, "ticks", None)
        if ticks and len(ticks) > 1:
            idx = z.get_value2index() or 0
            z.set_value(ticks[(idx + step) % len(ticks)], send=True)

    def _fmt(self, zctrl, key=None):
        if zctrl is None:
            return "--"
        v = self._norm(zctrl, 0.0)
        if key in TOGGLE_KEYS:
            return "ON" if v >= 0.0025 else "OFF"
        if key in ENUM_TABLES:
            return ENUM_TABLES[key][self._enum_idx(key)][1]
        if key == "cutoff":
            return fmt_hz(nm_cutoff_hz(v))
        if key in ("osc1tune", "osc2tune"):
            return f"{int(round((v - 0.5) * 48.0)):+d}st"
        if key in ("osc1finetune", "osc2finetune", "oscmastertune"):
            return f"{int(round((v - 0.5) * 200.0)):+d}ct"
        if key in BIPOLAR_KEYS:
            return f"{int(round((v - 0.5) * 200.0)):+d}%"
        return f"{int(round(v * 100.0))}%"

    # --------------------------------------------------------------------------
    # Update Loop & Dirty Checking
    # --------------------------------------------------------------------------
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

    def _watched_keys(self):
        keys = [k for k, _ in self._tab_items(self.active_tab)]
        if self.active_tab == "Osc":
            keys += ["osc1waveform", "osc2waveform", "osc1volume", "osc2volume", "osc3volume",
                     "osc1pw", "osc2fm", "oscsync", "ringmodulation", "detune"]
        elif self.active_tab == "Filter":
            keys += ["filtertype", "cutoff", "resonance", "filterdrive", "filtercontour", "keyfollow", "highpass"]
        elif self.active_tab == "Env":
            keys += ["ampattack", "ampdecay", "ampsustain", "amprelease",
                     "filterattack", "filterdecay", "filtersustain", "filterrelease",
                     "freeadattack", "freeaddecay", "freeadamount", "freeaddestination"]
        elif self.active_tab == "LFO":
            li = self.lfo_idx + 1
            keys += [f"lfo{li}waveform", f"lfo{li}rate", f"lfo{li}amount", f"lfo{li}phase",
                     f"lfo{li}destination", f"lfo{li}sync", f"lfo{li}keytrigger"]
        elif self.active_tab == "FX":
            keys += ["chorus1enable", "chorus2enable", "reverbwet", "reverbdecay", "reverbpredelay",
                     "delaywet", "delaytime", "delayfeedback", "delaysync", "delayfactorl", "delayfactorr"]
        elif self.active_tab == "Perf":
            keys += ["voices", "portamento", "portamentomode", "transpose", "volume",
                     "velocityvolume", "velocitycontour", "velocitycutoff", "vintagenoise"]
        return keys

    def _state_snapshot(self):
        vals = [
            self.active_tab, self.osc_bank, self.flt_bank, self.env_idx,
            self.lfo_idx, self.fx_bank, self.perf_bank, self.width, self.height,
        ]
        for k in self._watched_keys():
            vals.append(round(self._norm(self._get_zctrl(k), -1.0), 3))
        return tuple(vals)

    def refresh_gui(self):
        if not self.processor:
            return
        self._follow_page()
        snap = self._state_snapshot()
        if snap != self.last_snapshot:
            self.last_snapshot = snap
            self._draw()

    # --------------------------------------------------------------------------
    # Unified Drawing Primitives (UI Synths Design System + _fit_font)
    # --------------------------------------------------------------------------
    def _font(self, size, bold=False):
        key = (size, bold)
        f = self._fonts.get(key)
        if f is None:
            f = tkinter.font.Font(
                family=zynthian_gui_config.font_family,
                size=max(7, int(size)),
                weight="bold" if bold else "normal",
            )
            self._fonts[key] = f
        return f

    def _fs(self, scale=1.0):
        base = max(9, min(14, int(self.width / 46)))
        return max(8, int(base * scale))

    def _fit_font(self, text, max_w, size, bold=False, min_size=7):
        s = max(min_size, int(size))
        avail = max(12, int(max_w))
        while s > min_size:
            f = self._font(s, bold=bold)
            try:
                if f.measure(str(text)) <= avail:
                    return f
            except Exception:
                return f
            s -= 1
        return self._font(min_size, bold=bold)

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, hit_kind, hit_payload, subtext=None):
        c = self.widget_canvas
        fill = accent if active else COL_PANEL
        fg = "#0d0e12" if active else COL_TEXT
        outline = accent if active else COL_BORDER
        max_w = max(12, (x1 - x0) - 6)
        c.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=2 if active else 1)
        if subtext:
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.28, text=text,
                          fill=COL_DIM if not active else "#1a1c22",
                          font=self._fit_font(text, max_w, self._fs(0.76)))
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.72, text=subtext,
                          fill=accent if not active else "#000000",
                          font=self._fit_font(subtext, max_w, self._fs(0.9), bold=True))
        else:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                          fill=fg, font=self._fit_font(text, max_w, self._fs(0.9), bold=True))
        self.hitboxes.append((x0, y0, x1, y1, hit_kind, hit_payload))

    def _draw_bank_bar(self, x0, y0, x1, y1, banks, active_idx, accent, bank_kind):
        c = self.widget_canvas
        n = len(banks)
        gap = 6
        bw = (x1 - x0 - gap * (n - 1)) / n
        max_w = max(12, bw - 8)
        for i, label in enumerate(banks):
            bx0 = x0 + i * (bw + gap)
            bx1 = bx0 + bw
            act = (i == active_idx)
            c.create_rectangle(
                bx0, y0, bx1, y1,
                fill=COL_PANEL_HI if act else COL_PANEL,
                outline=accent if act else COL_BORDER,
                width=2 if act else 1,
            )
            txt = f"● {label}" if act else label
            c.create_text(
                (bx0 + bx1) / 2, (y0 + y1) / 2,
                text=txt,
                fill=accent if act else COL_TEXT,
                font=self._fit_font(txt, max_w, self._fs(0.86), bold=act),
            )
            self.hitboxes.append((bx0, y0, bx1, y1, bank_kind, i))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent, bank_kind=None, bank_idx=None, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        norm = self._norm(z, 0.5 if bipolar else 0.0)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 6
        tx0, tx1 = x0 + pad, x1 - pad
        bar_h = max(7, min(12, int((y1 - y0) * 0.30)))
        by1 = y1 - 4
        by0 = by1 - bar_h
        lbl_y = y0 + (by0 - y0) / 2
        val_txt = self._fmt(z, key)[:10]
        half_w = max(20, (tx1 - tx0) * 0.52)

        c.create_text(tx0, lbl_y, text=label, anchor="w", fill=COL_DIM,
                      font=self._fit_font(label, half_w, self._fs(0.84)))
        c.create_text(tx1, lbl_y, text=val_txt, anchor="e", fill=COL_TEXT,
                      font=self._fit_font(val_txt, half_w, self._fs(0.88), bold=True))

        c.create_rectangle(tx0, by0, tx1, by1, fill=COL_TRACK, outline="")
        if bipolar:
            mid_x = (tx0 + tx1) / 2
            fx = tx0 + norm * (tx1 - tx0)
            c.create_rectangle(min(mid_x, fx), by0, max(mid_x, fx), by1, fill=accent, outline="")
            c.create_line(mid_x, by0 - 1, mid_x, by1 + 1, fill=COL_TEXT, width=1)
        else:
            fx = tx0 + norm * (tx1 - tx0)
            if fx - tx0 > 1:
                c.create_rectangle(tx0, by0, fx, by1, fill=accent, outline="")
            c.create_line(fx, by0, fx, by1, fill="#ffffff", width=2)

        self.hitboxes.append((
            x0, y0, x1, y1, "hfader",
            {"key": key, "tx0": tx0, "tx1": tx1, "bank_kind": bank_kind, "bank_idx": bank_idx},
        ))

    def _draw_vfader(self, x0, y0, x1, y1, key, label, accent, bank_kind=None, bank_idx=None, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        norm = self._norm(z, 0.5 if bipolar else 0.0)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 4
        lbl_h = 18
        val_h = 16
        tx0, tx1 = x0 + pad, x1 - pad
        ty0 = y0 + lbl_h + 2
        ty1 = y1 - val_h - 3
        max_w = max(12, (x1 - x0) - 4)
        val_txt = self._fmt(z, key)[:7]

        c.create_text((x0 + x1) / 2, y0 + lbl_h / 2 + 1, text=label,
                      fill=COL_TEXT, font=self._fit_font(label, max_w, self._fs(0.84), bold=True))
        c.create_rectangle(tx0, ty0, tx1, ty1, fill=COL_TRACK, outline="")

        fy = ty1 - norm * (ty1 - ty0)
        if bipolar:
            mid_y = (ty0 + ty1) / 2
            c.create_rectangle(tx0, min(mid_y, fy), tx1, max(mid_y, fy), fill=accent, outline="")
            c.create_line(tx0 - 1, mid_y, tx1 + 1, mid_y, fill=COL_TEXT, width=1)
        else:
            if ty1 - fy > 1:
                c.create_rectangle(tx0, fy, tx1, ty1, fill=accent, outline="")
        c.create_line(tx0, fy, tx1, fy, fill="#ffffff", width=2)

        c.create_text((x0 + x1) / 2, y1 - val_h / 2 - 1, text=val_txt,
                      fill=COL_DIM, font=self._fit_font(val_txt, max_w, self._fs(0.78)))

        self.hitboxes.append((
            x0, y0, x1, y1, "vfader",
            {"key": key, "ty0": ty0, "ty1": ty1, "bank_kind": bank_kind, "bank_idx": bank_idx},
        ))

    def _draw_bottom_grid(self, x0, y0, x1, y1, tab_name, accent):
        gap = 6
        items = self._tab_items(tab_name)
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - y0 - gap) / 2
        for i, (key, lbl) in enumerate(items[:4]):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py0 = y0 + row_i * (ch + gap)
            self._draw_param_box(px0, py0, px0 + cw, py0 + ch, key, lbl, accent,
                                 bipolar=(key in BIPOLAR_KEYS))

    # --------------------------------------------------------------------------
    # Master Canvas Layout
    # --------------------------------------------------------------------------
    def _draw(self):
        c = self.widget_canvas
        w, h = self.width, self.height
        if w < 40 or h < 40:
            return

        c.delete("all")
        self.hitboxes = []

        pad = 4
        hdr_h = max(36, min(46, int(h * 0.11)))
        self._draw_header(pad, pad, w - pad, pad + hdr_h)

        by0 = pad + hdr_h + 6
        by1 = h - pad
        bx0, bx1 = pad, w - pad

        if self.active_tab == "Osc":
            self._draw_tab_osc(bx0, by0, bx1, by1)
        elif self.active_tab == "Filter":
            self._draw_tab_filter(bx0, by0, bx1, by1)
        elif self.active_tab == "Env":
            self._draw_tab_env(bx0, by0, bx1, by1)
        elif self.active_tab == "LFO":
            self._draw_tab_lfo(bx0, by0, bx1, by1)
        elif self.active_tab == "FX":
            self._draw_tab_fx(bx0, by0, bx1, by1)
        elif self.active_tab == "Perf":
            self._draw_tab_perf(bx0, by0, bx1, by1)

    def _draw_header(self, x0, y0, x1, y1):
        c = self.widget_canvas
        total_w = x1 - x0
        gap = 6
        tw = (total_w - gap * (len(TABS) - 1)) / len(TABS)

        cx = x0
        for tname in TABS:
            act = (tname == self.active_tab)
            acc = TAB_ACCENTS[tname]
            c.create_rectangle(
                cx, y0, cx + tw, y1,
                fill=acc if act else COL_PANEL,
                outline=acc if act else COL_BORDER,
                width=2 if act else 1,
            )
            c.create_text(
                cx + tw / 2, (y0 + y1) / 2,
                text=tname,
                fill="#0d0e12" if act else COL_TEXT,
                font=self._fit_font(tname, tw - 6, self._fs(0.94), bold=True),
            )
            self.hitboxes.append((cx, y0, cx + tw, y1, "tab", tname))
            cx += tw + gap

    # --------------------------------------------------------------------------
    # TAB 1: OSC (Osc 1 + Osc 2 + Sub Live Scope & Quick Waveforms)
    # --------------------------------------------------------------------------
    def _draw_tab_osc(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Osc"]
        gap = 6

        # Row 1: Encoder Sub-Bank Bar
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Levels & PW", "Tuning", "FM / Ring / Slop"],
            self.osc_bank, accent, "osc_bank",
        )

        # Row 2: Osc 1 Wave + Osc 2 Wave + Sync + Voices
        r2_y = y0 + r1_h + gap
        r2_h = 34
        quick = [
            ("Osc1 Wave", "osc1waveform"),
            ("Osc2 Wave", "osc2waveform"),
            ("Osc Sync",  "oscsync"),
            ("Voices",    "voices"),
        ]
        qw = (x1 - x0 - gap * 3) / 4
        for i, (lbl, key) in enumerate(quick):
            qx0 = x0 + i * (qw + gap)
            z = self._get_zctrl(key)
            act = (key == "oscsync" and self._norm(z, 0.0) >= 0.0025)
            self._draw_pill(qx0, r2_y, qx0 + qw, r2_y + r2_h, lbl, act, accent,
                            "cycle", key, subtext=self._fmt(z, key))

        # Row 3: Live Combined Osc 1 + Osc 2 + Sub Waveform Scope (left 62%) + 3 Level Faders (right 38%)
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        left_w = int((x1 - x0) * 0.62)
        lx1 = x0 + left_w
        rx0 = lx1 + gap

        c.create_rectangle(x0, gy0, lx1, gy1, fill=COL_PANEL, outline=accent, width=1)
        w1 = self._enum_idx("osc1waveform")
        w2 = self._enum_idx("osc2waveform")
        v1 = self._norm(self._get_zctrl("osc1volume"), 0.8)
        v2 = self._norm(self._get_zctrl("osc2volume"), 0.0)
        v3 = self._norm(self._get_zctrl("osc3volume"), 0.5)
        pw = max(0.08, min(0.92, self._norm(self._get_zctrl("osc1pw"), 0.5)))
        fm = self._norm(self._get_zctrl("osc2fm"), 0.0)

        pad = 10
        gx0, gx1 = x0 + pad, lx1 - pad
        mid_y = (gy0 + gy1) / 2 + 6
        gw = max(10, gx1 - gx0)
        amp = max(8, (gy1 - gy0) / 2 - 16)
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        pts = []
        n_pts = 96
        for i in range(n_pts + 1):
            t = i / n_pts
            p2 = (t * 2.0) % 1.0
            if w2 == 0: y2 = 2.0 * p2 - 1.0
            elif w2 == 1: y2 = 1.0 if p2 < 0.5 else -1.0
            elif w2 == 2: y2 = 1.0 - 4.0 * abs(p2 - 0.5)
            elif w2 == 3: y2 = math.sin(2.0 * math.pi * p2)
            else: y2 = math.sin(i * 19.13) * 0.8
            p1 = (t * 2.0 + fm * 0.25 * y2) % 1.0
            if w1 == 0: y1v = 2.0 * p1 - 1.0
            elif w1 == 1: y1v = 1.0 if p1 < pw else -1.0
            else: y1v = math.sin(i * 12.9898) * 0.8
            y3 = 1.0 if (t % 1.0) < 0.5 else -1.0
            ytot = (v1 * y1v + v2 * y2 + 0.6 * v3 * y3) / max(0.5, v1 + v2 + 0.6 * v3)
            pts.extend([gx0 + t * gw, mid_y - max(-1.0, min(1.0, ytot)) * amp])
        c.create_line(pts, fill=accent, width=2.4)
        hdr = f"O1:{OSC1_WAVES[w1][1]}  O2:{OSC2_WAVES[w2][1]}  FM:{int(round(fm*100))}%"
        c.create_text(x0 + 8, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, left_w - 16, self._fs(0.84), bold=True))

        # Right: 3 Vertical Mixer Faders (Osc1, Osc2, Sub)
        fw = (x1 - rx0 - gap * 2) / 3
        for i, (k, l) in enumerate((("osc1volume", "O1"), ("osc2volume", "O2"), ("osc3volume", "SUB"))):
            fx0 = rx0 + i * (fw + gap)
            self._draw_vfader(fx0, gy0, fx0 + fw, gy1, k, l, accent, bank_kind="osc_bank", bank_idx=0)

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Osc", accent)

    # --------------------------------------------------------------------------
    # TAB 2: FILTER (11 TAL Filter Models + Interactive 2D XY Response Pad)
    # --------------------------------------------------------------------------
    def _draw_tab_filter(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Filter"]
        gap = 6

        # Row 1: Encoder Sub-Bank Bar
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Cutoff / Res / Drive", "Type / Key / HighPass"],
            self.flt_bank, accent, "flt_bank",
        )

        # Row 2: 8 Popular TAL Filter Models (incl. Moog 24dB & SV 24dB)
        r2_y = y0 + r1_h + gap
        r2_h = 34
        ft_idx = self._enum_idx("filtertype")
        quick_f = [0, 2, 4, 5, 6, 7, 8, 10]  # LP24, LP12, HP12, BP12, Notch, SV LP, SV HP, Moog24
        sgap = 4
        fw = (x1 - x0 - sgap * 7) / 8
        for i, f_i in enumerate(quick_f):
            fx0 = x0 + i * (fw + sgap)
            self._draw_pill(fx0, r2_y, fx0 + fw, r2_y + r2_h, FILTER_TYPES[f_i][1],
                            ft_idx == f_i, accent, "flt_type", FILTER_TYPES[f_i][0])

        # Row 3: Interactive 2D Log-Hz Filter Response Pad
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 14
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + 22, gy1 - pad
        gw, gh = max(10, gx1 - gx0), max(10, g_bot - g_top)
        zero_y = g_top + gh * 0.45
        c.create_line(gx0, zero_y, gx1, zero_y, fill=COL_GRID, dash=(2, 4))

        cut = self._norm(self._get_zctrl("cutoff"), 0.8)
        res = self._norm(self._get_zctrl("resonance"), 0.0)
        drv = self._norm(self._get_zctrl("filterdrive"), 0.0)
        pts = []
        for i in range(61):
            xn = i / 60.0
            d = xn - cut
            if ft_idx in (4, 8):      # HP
                db = 0.0 if d >= 0 else -36.0 * (-d / 0.24)
            elif ft_idx in (5, 9):    # BP
                db = -30.0 * (abs(d) / 0.18)
            elif ft_idx == 6:         # Notch
                db = -26.0 * math.exp(-((d / 0.05) ** 2))
            else:                     # LP / Moog24 / SV LP
                slope = 42.0 if ft_idx in (0, 7, 10) else 28.0
                db = 0.0 if d <= 0 else -slope * (d / 0.24)
            peak = res * 18.0 * math.exp(-((d / 0.05) ** 2)) if ft_idx != 6 else 0.0
            y = max(g_top, min(g_bot, zero_y - ((db + peak) / 24.0) * (gh * 0.48)))
            pts.extend([gx0 + xn * gw, y])
        c.create_polygon([gx0, g_bot] + pts + [gx1, g_bot], fill="#2b1f14", outline="")
        c.create_line(pts, fill=accent, width=2.6)

        hx, hy = gx0 + cut * gw, g_bot - res * gh
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        hdr = f"{FILTER_TYPES[ft_idx][1].upper()}   CUT:{fmt_hz(nm_cutoff_hz(cut))}   RES:{int(round(res*100))}%   DRV:{int(round(drv*100))}%"
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))

        self.hitboxes.append((x0, gy0, x1, gy1, "filter_xy", {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot}))
        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Filter", accent)

    # --------------------------------------------------------------------------
    # TAB 3: ENV (Interactive 2D Amp ADSR, Filter ADSR & Free AD)
    # --------------------------------------------------------------------------
    def _draw_tab_env(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Env"] if self.env_idx == 0 else ("#ff922b" if self.env_idx == 1 else "#4dabf7")
        gap = 6

        # Row 1: 3 Envelope Selectors
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Amp ADSR", "Filter ADSR", "Free AD"],
            self.env_idx, accent, "env_idx",
        )

        # Row 2: Interactive 2D Envelope Graph
        gy0 = y0 + r1_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 14
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + 24, gy1 - pad
        gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)

        if self.env_idx in (0, 1):
            pref = "amp" if self.env_idx == 0 else "filter"
            a = self._norm(self._get_zctrl(f"{pref}attack"), 0.0)
            d = self._norm(self._get_zctrl(f"{pref}decay"), 0.3)
            s = self._norm(self._get_zctrl(f"{pref}sustain"), 0.8)
            r = self._norm(self._get_zctrl(f"{pref}release"), 0.2)
            xa = gx0 + max(0.02, a) * (gw * 0.28)
            xd = xa + max(0.03, d) * (gw * 0.28)
            xs = xd + gw * 0.16
            xr = min(gx1, xs + max(0.03, r) * (gw * 0.28))
            ys = g_bot - s * gh
            pts = [gx0, g_bot, xa, g_top, xd, ys, xs, ys, xr, g_bot]
            c.create_polygon(pts + [gx0, g_bot], fill="#16291b" if self.env_idx == 0 else "#2b1f14", outline="")
            c.create_line(pts, fill=accent, width=2.6)
            for hx, hy in ((xa, g_top), (xd, ys), (xr, g_bot)):
                c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            hdr = f"{pref.upper()} EG   A:{int(round(a*100))}%  D:{int(round(d*100))}%  S:{int(round(s*100))}%  R:{int(round(r*100))}%"
            c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                          font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))
            self.hitboxes.append((
                x0, gy0, x1, gy1, "env_graph",
                {"pref": pref, "gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
                 "xa": xa, "xd": xd, "xs": xs, "xr": xr, "ys": ys},
            ))
        else:
            a = self._norm(self._get_zctrl("freeadattack"), 0.0)
            d = self._norm(self._get_zctrl("freeaddecay"), 0.4)
            xa = gx0 + max(0.03, a) * (gw * 0.45)
            xd = min(gx1, xa + max(0.05, d) * (gw * 0.50))
            pts = [gx0, g_bot, xa, g_top, xd, g_bot]
            c.create_polygon(pts + [gx0, g_bot], fill="#152333", outline="")
            c.create_line(pts, fill=accent, width=2.6)
            for hx, hy in ((xa, g_top), (xd, g_bot)):
                c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            dest = self._fmt(self._get_zctrl("freeaddestination"), "freeaddestination")
            hdr = f"FREE AD -> {dest}   A:{int(round(a*100))}%   D:{int(round(d*100))}%"
            c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                          font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))
            self.hitboxes.append((
                x0, gy0, x1, gy1, "free_env",
                {"gx0": gx0, "gw": gw, "xa": xa, "xd": xd},
            ))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Env", accent)

    # --------------------------------------------------------------------------
    # TAB 4: LFO (Dual LFO 1 & LFO 2 + Sync/KeyTrig/Destination)
    # --------------------------------------------------------------------------
    def _draw_tab_lfo(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["LFO"]
        li = self.lfo_idx + 1
        gap = 6

        # Row 1: LFO 1 / LFO 2 + Sync + KeyTrig + Dest
        r1_h = 34
        left_w = (x1 - x0) * 0.36
        self._draw_bank_bar(x0, y0, x0 + left_w, y0 + r1_h, ["LFO 1", "LFO 2"], self.lfo_idx, accent, "lfo_idx")
        rx0 = x0 + left_w + gap
        w3 = (x1 - rx0 - 2 * gap) / 3
        sy_on = self._norm(self._get_zctrl(f"lfo{li}sync"), 0.0) >= 0.0025
        kt_on = self._norm(self._get_zctrl(f"lfo{li}keytrigger"), 0.0) >= 0.0025
        self._draw_pill(rx0, y0, rx0 + w3, y0 + r1_h, "●SYNC" if sy_on else "SYNC",
                        sy_on, "#51cf66", "cycle", f"lfo{li}sync")
        self._draw_pill(rx0 + w3 + gap, y0, rx0 + 2 * w3 + gap, y0 + r1_h, "●TRIG" if kt_on else "TRIG",
                        kt_on, "#4dabf7", "cycle", f"lfo{li}keytrigger")
        dest_z = self._get_zctrl(f"lfo{li}destination")
        self._draw_pill(rx0 + 2 * (w3 + gap), y0, x1, y0 + r1_h,
                        self._fmt(dest_z, f"lfo{li}destination"), False, accent, "cycle", f"lfo{li}destination")

        # Row 2: 6 LFO Shape Pills
        r2_y = y0 + r1_h + gap
        r2_h = 34
        w_idx = self._enum_idx(f"lfo{li}waveform")
        sgap = 4
        sw = (x1 - x0 - sgap * 5) / 6
        for i, (wval, wlbl) in enumerate(LFO_WAVES):
            sx0 = x0 + i * (sw + sgap)
            self._draw_pill(sx0, r2_y, sx0 + sw, r2_y + r2_h, wlbl,
                            i == w_idx, accent, "lfo_wave", wval)

        # Row 3: Live LFO Scope
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 12
        gx0, gx1 = x0 + pad, x1 - pad
        mid_y = (gy0 + gy1) / 2 + 6
        gw = max(10, gx1 - gx0)
        amp = max(8, (gy1 - gy0) / 2 - 16)
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        rate = self._norm(self._get_zctrl(f"lfo{li}rate"), 0.3)
        amt = (self._norm(self._get_zctrl(f"lfo{li}amount"), 0.5) - 0.5) * 2.0
        phs = self._norm(self._get_zctrl(f"lfo{li}phase"), 0.0)
        cycles = 1.5 + rate * 5.0
        gain = max(0.25, abs(amt)) * (-1.0 if amt < 0 else 1.0)
        pts = []
        for i in range(97):
            t = i / 96.0
            p = (t * cycles + phs) % 1.0
            if w_idx == 0: y = math.sin(2.0 * math.pi * p)
            elif w_idx == 1: y = 1.0 - 4.0 * abs(p - 0.5)
            elif w_idx == 2: y = 1.0 - 2.0 * p
            elif w_idx == 3: y = 1.0 if p < 0.5 else -1.0
            else: y = math.sin(int(t * cycles * 2.0) * 12.9898 + 1.23) * 0.9
            pts.extend([gx0 + t * gw, mid_y - y * gain * amp])
        c.create_line(pts, fill=accent, width=2.4)
        hdr = f"LFO {li} ({LFO_WAVES[w_idx][1]}) -> {self._fmt(dest_z, f'lfo{li}destination')}   AMT:{int(round(amt*100)):+d}%"
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "LFO", accent)

    # --------------------------------------------------------------------------
    # TAB 5: FX (Juno Chorus I / II + Reverb + Delay + Bitcrusher)
    # --------------------------------------------------------------------------
    def _draw_tab_fx(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["FX"]
        gap = 6

        # Row 1: Encoder Sub-Bank Bar
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Reverb", "Delay", "Crush & Cuts"],
            self.fx_bank, accent, "fx_bank",
        )

        # Row 2: Big Juno-Style Chorus I / II + Delay Sync / x2 L / x2 R Toggles
        r2_y = y0 + r1_h + gap
        r2_h = 38
        toggles = [
            ("CHORUS I",  "chorus1enable", "#4dabf7"),
            ("CHORUS II", "chorus2enable", "#cc5de8"),
            ("DLY SYNC",  "delaysync",     "#51cf66"),
            ("x2 L",      "delayfactorl",  accent),
            ("x2 R",      "delayfactorr",  accent),
        ]
        tw = (x1 - x0 - gap * 4) / 5
        for i, (lbl, key, col) in enumerate(toggles):
            tx0 = x0 + i * (tw + gap)
            on = self._norm(self._get_zctrl(key), 0.0) >= 0.0025
            self._draw_pill(tx0, r2_y, tx0 + tw, r2_y + r2_h,
                            f"●{lbl}" if on else lbl, on, col, "cycle", key)

        # Row 3: 4 Vertical Faders for Active FX Bank
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        items = self._tab_items("FX")
        fw = (x1 - x0 - gap * 3) / 4
        for i, (key, lbl) in enumerate(items[:4]):
            fx0 = x0 + i * (fw + gap)
            self._draw_vfader(fx0, gy0, fx0 + fw, gy1, key, lbl, accent)

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "FX", accent)

    # --------------------------------------------------------------------------
    # TAB 6: PERF (Voices, Portamento, Velocity Matrix, Analog Slop & Master)
    # --------------------------------------------------------------------------
    def _draw_tab_perf(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Perf"]
        gap = 6

        # Row 1: Encoder Sub-Bank Bar
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Master & Glide", "Velocity", "Bend & Voices"],
            self.perf_bank, accent, "perf_bank",
        )

        # Row 2: Quick Performance Tiles
        r2_y = y0 + r1_h + gap
        r2_h = 38
        quick = [
            ("Voices", "voices"),
            ("Porta",  "portamentomode"),
            ("Transp", "transpose"),
            ("Sync",   "oscsync"),
        ]
        qw = (x1 - x0 - gap * 3) / 4
        for i, (lbl, key) in enumerate(quick):
            qx0 = x0 + i * (qw + gap)
            z = self._get_zctrl(key)
            self._draw_pill(qx0, r2_y, qx0 + qw, r2_y + r2_h, lbl, False, accent,
                            "cycle", key, subtext=self._fmt(z, key))

        # Row 3: 5 Vertical Performance Faders
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        faders = [
            ("volume",          "VOL",   "#51cf66", 0),
            ("portamento",      "GLIDE", "#4dabf7", 0),
            ("detune",          "SLOP",  "#ff922b", 1),
            ("vintagenoise",    "NOISE", "#ffd43b", 0),
            ("velocitycutoff",  "V>CUT", "#cc5de8", 1),
        ]
        fw = (x1 - x0 - gap * 4) / 5
        for i, (key, lbl, col, b_idx) in enumerate(faders):
            fx0 = x0 + i * (fw + gap)
            self._draw_vfader(fx0, gy0, fx0 + fw, gy1, key, lbl, col,
                              bank_kind="perf_bank", bank_idx=b_idx)

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Perf", accent)

    # --------------------------------------------------------------------------
    # Touchscreen Interaction (Drag + Double-Tap Reset on Sliders & 2D Nodes)
    # --------------------------------------------------------------------------
    def _find_hit(self, x, y):
        for hb in reversed(self.hitboxes):
            x0, y0, x1, y1, kind, payload = hb
            if x0 <= x <= x1 and y0 <= y <= y1:
                return kind, payload
        return None, None

    def _switch_subbank(self, bank_kind, bank_idx):
        if bank_kind is None or bank_idx is None:
            return
        if getattr(self, bank_kind, None) != bank_idx:
            setattr(self, bank_kind, bank_idx)
            self._live_swap_encoders(self.active_tab)

    def _on_press(self, event):
        kind, payload = self._find_hit(event.x, event.y)
        self.drag_target = None
        if kind is None:
            return

        if kind == "tab":
            if payload != self.active_tab:
                self.active_tab = payload
                if not self._select_page_by_title(payload):
                    self._live_swap_encoders(payload)
                self.last_snapshot = None
                self._draw()
            return

        if kind in ("osc_bank", "flt_bank", "env_idx", "lfo_idx", "fx_bank", "perf_bank"):
            self._switch_subbank(kind, payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "flt_type":
            self._set_norm(self._get_zctrl("filtertype"), payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "lfo_wave":
            li = self.lfo_idx + 1
            self._set_norm(self._get_zctrl(f"lfo{li}waveform"), payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "cycle":
            self._cycle_key(payload, 1)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "filter_xy":
            self._switch_subbank("flt_bank", 0)
            now = time.monotonic()
            tap_id = ("filter_xy", "main")
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for rk in ("cutoff", "resonance"):
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("filter_xy", payload)
            self._apply_drag(event.x, event.y)
            return

        if kind == "env_graph":
            pref = payload["pref"]
            d_a = abs(event.x - payload["xa"])
            d_ds = math.hypot(event.x - payload["xd"], event.y - payload["ys"])
            d_r = abs(event.x - payload["xr"])
            node = "A" if (d_a <= d_ds and d_a <= d_r) else ("DS" if d_ds <= d_r else "R")
            now = time.monotonic()
            tap_id = ("env_graph", pref, node)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                rkeys = [f"{pref}attack"] if node == "A" else ([f"{pref}decay", f"{pref}sustain"] if node == "DS" else [f"{pref}release"])
                for rk in rkeys:
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("env_node", dict(payload, node=node))
            self._apply_drag(event.x, event.y)
            return

        if kind == "free_env":
            d_a = abs(event.x - payload["xa"])
            d_d = abs(event.x - payload["xd"])
            node = "A" if d_a <= d_d else "D"
            now = time.monotonic()
            tap_id = ("free_env", node)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                z = self._get_zctrl("freeadattack" if node == "A" else "freeaddecay")
                if z is not None:
                    z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("free_env", dict(payload, node=node))
            self._apply_drag(event.x, event.y)
            return

        if kind in ("vfader", "hfader"):
            self._switch_subbank(payload.get("bank_kind"), payload.get("bank_idx"))
            now = time.monotonic()
            tap_id = (kind, payload["key"])
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                z = self._get_zctrl(payload["key"])
                if z is not None:
                    z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = (kind, payload)
            self._apply_drag(event.x, event.y)

    def _on_drag(self, event):
        if self.drag_target is not None:
            self._apply_drag(event.x, event.y)

    def _on_release(self, event):
        self.drag_target = None

    def _apply_drag(self, x, y):
        kind, payload = self.drag_target
        if kind == "vfader":
            ty0, ty1 = payload["ty0"], payload["ty1"]
            if ty1 > ty0:
                self._set_norm(self._get_zctrl(payload["key"]), (ty1 - y) / (ty1 - ty0))
        elif kind == "hfader":
            tx0, tx1 = payload["tx0"], payload["tx1"]
            if tx1 > tx0:
                self._set_norm(self._get_zctrl(payload["key"]), (x - tx0) / (tx1 - tx0))
        elif kind == "filter_xy":
            gx0, gx1, gy0, gy1 = payload["gx0"], payload["gx1"], payload["gy0"], payload["gy1"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl("cutoff"), (x - gx0) / (gx1 - gx0))
            if gy1 > gy0:
                self._set_norm(self._get_zctrl("resonance"), (gy1 - y) / (gy1 - gy0))
        elif kind == "env_node":
            pref = payload["pref"]
            gx0, gw = payload["gx0"], payload["gw"]
            g_top, g_bot = payload["g_top"], payload["g_bot"]
            seg_w = max(10.0, gw * 0.28)
            node = payload["node"]
            if node == "A":
                self._set_norm(self._get_zctrl(f"{pref}attack"), (x - gx0) / seg_w)
            elif node == "DS":
                self._set_norm(self._get_zctrl(f"{pref}decay"), (x - payload["xa"]) / seg_w)
                if g_bot > g_top:
                    self._set_norm(self._get_zctrl(f"{pref}sustain"), (g_bot - y) / (g_bot - g_top))
            elif node == "R":
                self._set_norm(self._get_zctrl(f"{pref}release"), (x - payload["xs"]) / seg_w)
        elif kind == "free_env":
            gx0, gw = payload["gx0"], payload["gw"]
            if payload["node"] == "A":
                self._set_norm(self._get_zctrl("freeadattack"), (x - gx0) / max(10.0, gw * 0.45))
            else:
                self._set_norm(self._get_zctrl("freeaddecay"), (x - payload["xa"]) / max(10.0, gw * 0.50))

        self.last_snapshot = None
        self._draw()
