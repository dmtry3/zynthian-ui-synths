#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Calf Organ (Hammond Tonewheel & Additive Synthesizer) Widget for Zynthian V5
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces Calf Organ's 125 raw LV2 parameters (~32 pages) with 6 dynamic
# workstation tabs mapped 1-to-1 to Zynthian's 4 physical encoders + ECO:
#   Drawbars | Harmonic | Perc | Filter | Env | Vib/EQ   + ECO
#
# Features:
#   - Drawbars: 9 authentic color-coded Hammond B3 vertical drawbars (16'..1',
#     pull-down 0..8) + 4 one-tap classic registrations (Jazz, Full, Gospel,
#     Flute) + 3 encoder sub-banks (1-4 / 5-8 / 9+Vol).
#   - Harmonic: Per-drawbar selector (D1..D9), 36 waveforms with live additive
#     waveform preview, harmonic multiplier (1..32), detune, pan & routing.
#   - Perc: Dual Carrier + FM Percussion decay envelope visualizer (2D Decay x
#     Level / FM Decay x FM Depth), 4 trigger modes (First/Each/NoRetrig/Poly).
#   - Filter: Dual F1/F2 Bode response curve (20Hz..20kHz) with 2D Cutoff x
#     Reso pad, F1 LP/HP type & Filter Chain (Out / Flt 2) switches.
#   - Env: EG 1 / EG 2 / EG 3 selector, Quad Env & Amp Ctl pills, interactive
#     4-stage ADSR curve with draggable Attack / Decay-Sustain / Release nodes.
#   - Vib/EQ: Scanner Vibrato/Chorus (Allpass, V1/C1..Full) wave visualizer
#     (2D Rate x Chorus) + Bass/Treble shelf EQ curve (2D Bass x Treble).
#   - ECO button: caps Polyphony -> 8 voices for smooth Raspberry Pi performance
#     with one-tap restore.
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
# Unified UI Synths Palette
# ------------------------------------------------------------------------------
COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"
COL_ECO = "#40c057"

TABS = ["Drawbars", "Harmonic", "Perc", "Filter", "Env", "Vib/EQ"]
TAB_ACCENTS = {
    "Drawbars": "#ff922b",  # orange
    "Harmonic": "#cc5de8",  # violet
    "Perc":     "#ffd43b",  # yellow
    "Filter":   "#4dabf7",  # blue
    "Env":      "#51cf66",  # green
    "Vib/EQ":   "#ff6b6b",  # coral
}

# 9 Classic Hammond Drawbars: (footage, default_level, default_harm, color_role)
DRAWBARS = [
    ("16'",  8.0,  1, "brown"),
    ("5⅓'",  8.0,  3, "brown"),
    ("8'",   8.0,  2, "white"),
    ("4'",   0.0,  4, "white"),
    ("2⅔'",  0.0,  6, "black"),
    ("2'",   0.0,  8, "white"),
    ("1⅗'",  0.0, 10, "black"),
    ("1⅓'",  0.0, 12, "black"),
    ("1'",   8.0, 16, "white"),
]

DRAWBAR_COLORS = {
    "brown": ("#8d5524", "#c68642", "#ffffff"),
    "white": ("#dee2e6", "#ffffff", "#111217"),
    "black": ("#3a3e4d", "#5c6278", "#f1f3f5"),
}

# Classic one-tap Hammond B3 registrations
REGISTRATIONS = [
    ("Jazz",   [8, 8, 8, 0, 0, 0, 0, 0, 0]),
    ("Full",   [8, 8, 8, 8, 8, 8, 8, 8, 8]),
    ("Gospel", [8, 0, 0, 0, 0, 0, 0, 0, 8]),
    ("Flute",  [0, 0, 8, 8, 0, 0, 0, 0, 0]),
]

WAVEFORMS = [
    "Sin", "S0", "S00", "S000", "SSaw", "SSqr", "SPls",
    "Saw", "Sqr", "Pls", "S(", "Sq(", "S+", "Clvg",
    "Bell", "Bell2", "W1", "W2", "W3", "W4", "W5", "W6",
    "W7", "W8", "W9", "DSaw", "DSqr", "DPls",
    "P:SynS", "P:WideS", "P:Sine", "P:Bell", "P:Space", "P:Voice", "P:Hiss", "P:Chant",
]

ROUTINGS = ["Out", "Flt 1", "Flt 2"]
PERC_TRIGGERS = ["First", "Each", "NoRetr", "Poly"]
AMP_CTLS = ["None", "Direct", "Flt 1", "Flt 2", "All"]
VIB_MODES = ["None", "Direct", "Flt 1", "Flt 2", "Voice", "Global"]
VIB_TYPES = ["Allpass", "V1/C1", "V2/C2", "V3/C3", "Full"]

LOG_KEYS = {
    "perc_decay", "perc_fm_decay",
    "f1_cutoff", "f1_res", "f2_cutoff", "f2_res",
    "adsr_a", "adsr_d", "adsr_r",
    "adsr2_a", "adsr2_d", "adsr2_r",
    "adsr3_a", "adsr3_d", "adsr3_r",
    "vib_rate", "bass_freq", "bass_gain", "treble_freq", "treble_gain",
}

INT_KEYS = {
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9",
    "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8", "w9",
    "routing1", "routing2", "routing3", "routing4", "routing5",
    "routing6", "routing7", "routing8", "routing9",
    "perc_waveform", "perc_harmonic", "perc_fm_waveform", "perc_fm_harmonic",
    "perc_trigger", "filter_chain", "filter1_type",
    "eg1_amp_ctl", "eg2_amp_ctl", "eg3_amp_ctl", "quad_env",
    "vib_mode", "vib_type", "transpose", "polyphony", "foldnote",
}

BIPOLAR_KEYS = {
    "detune1", "detune2", "detune3", "detune4", "detune5",
    "detune6", "detune7", "detune8", "detune9",
    "pan1", "pan2", "pan3", "pan4", "pan5", "pan6", "pan7", "pan8", "pan9",
    "f1_env1", "f1_env2", "f1_env3", "f2_env1", "f2_env2", "f2_env3",
    "transpose", "detune",
}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    hz = float(hz)
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}k" if hz < 10000.0 else f"{hz / 1000.0:.1f}k"
    return f"{hz:.0f}Hz"


def fmt_ms(ms):
    ms = float(ms)
    if ms >= 1000.0:
        return f"{ms / 1000.0:.2f}s"
    if ms >= 10.0:
        return f"{ms:.0f}ms"
    return f"{ms:.1f}ms"


def fmt_gain_db(g):
    g = max(1e-4, float(g))
    return f"{20.0 * math.log10(g):+.1f}dB"


def synth_wave_sample(w_idx, phase):
    """Return illustrative waveform sample in [-1..1] for Calf Organ w1..w35."""
    p = phase % (2.0 * math.pi)
    t = p / (2.0 * math.pi)
    if w_idx == 0:  # Sin
        return math.sin(p)
    if w_idx in (1, 2, 3):  # S0, S00, S000 (harmonic rich sine)
        k = w_idx + 1
        return 0.72 * math.sin(p) + 0.28 * math.sin(k * p)
    if w_idx in (4, 7, 25):  # SSaw, Saw, DSaw
        raw = 1.0 - 2.0 * t
        return 0.65 * raw + 0.35 * math.sin(p) if w_idx == 4 else raw
    if w_idx in (5, 8, 26):  # SSqr, Sqr, DSqr
        raw = 1.0 if t < 0.5 else -1.0
        return 0.6 * raw + 0.4 * math.sin(p) if w_idx == 5 else raw
    if w_idx in (6, 9, 27):  # SPls, Pls, DPls
        return 1.0 if t < 0.22 else -0.45
    if w_idx in (10, 11, 12):  # S(, Sq(, S+
        return math.sin(p) + 0.45 * math.sin(2.0 * p) - 0.2 * math.cos(3.0 * p)
    if w_idx in (13, 14, 15):  # Clvg, Bell, Bell2
        return 0.55 * math.sin(p) + 0.35 * math.sin(3.0 * p) + 0.25 * math.sin(5.0 * p)
    if 16 <= w_idx <= 24:  # W1..W9 wavetables
        m = (w_idx - 15)
        return 0.55 * math.sin(p) + 0.3 * math.sin((m + 1) * p) + 0.15 * math.cos((2 * m + 1) * p)
    # Pad / Pipe / Choir (28..35)
    m = (w_idx - 27)
    return 0.5 * math.sin(p) + 0.28 * math.sin(2.0 * p + 0.4 * m) + 0.22 * math.sin(3.0 * p)


def eval_organ_filter_db(freq, cutoff, res, is_hp=False):
    """Evaluate 12 dB/oct resonant LP/HP magnitude response in dB."""
    fc = max(20.0, float(cutoff))
    q = max(0.7, float(res))
    r = max(1e-4, float(freq) / fc)
    if is_hp:
        r_inv = 1.0 / r
        denom = math.sqrt((1.0 - r_inv * r_inv) ** 2 + (r_inv / q) ** 2)
    else:
        denom = math.sqrt((1.0 - r * r) ** 2 + (r / q) ** 2)
    mag = 1.0 / max(1e-4, denom)
    return max(-30.0, min(24.0, 20.0 * math.log10(mag)))


def eval_tone_eq_db(freq, bass_f, bass_g, treb_f, treb_g):
    """Evaluate smooth low-shelf + high-shelf tone stack response in dB."""
    b_db = 20.0 * math.log10(max(0.05, float(bass_g)))
    t_db = 20.0 * math.log10(max(0.05, float(treb_g)))
    b_oct = math.log2(max(1e-4, float(freq) / max(20.0, float(bass_f))))
    t_oct = math.log2(max(1e-4, float(freq) / max(20.0, float(treb_f))))
    b_resp = b_db / (1.0 + math.exp(b_oct * 2.2))
    t_resp = t_db / (1.0 + math.exp(-t_oct * 2.2))
    return max(-24.0, min(24.0, b_resp + t_resp))


class zynthian_widget_calf_organ(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.active_tab = "Drawbars"
        self.db_bank = 0      # 0=1-4, 1=5-8, 2=9+Vol
        self.harm_idx = 0     # 0..8 (Drawbar 1..9)
        self.perc_bank = 0    # 0=Carrier, 1=FM Mod
        self.flt_idx = 0      # 0=F1, 1=F2
        self.flt_bank = 0     # 0=Main, 1=Env Mod
        self.env_idx = 0      # 0=EG1, 1=EG2, 2=EG3
        self.vib_bank = 0     # 0=Vibrato, 1=Tone EQ, 2=Master

        self.eco_on = False
        self._eco_backup_poly = None

        self.next_update = 0.0
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}
        self._tk_font_cache = {}
        self._vib_phase_anim = 0.0
        self._last_tick = time.monotonic()

        self.widget_canvas = tkinter.Canvas(self, highlightthickness=0, relief="flat", bg=COL_BG)
        self.widget_canvas.grid(sticky="news")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.widget_canvas.bind("<ButtonPress-1>", self._on_press)
        self.widget_canvas.bind("<B1-Motion>", self._on_drag)
        self.widget_canvas.bind("<ButtonRelease-1>", self._on_release)

    # --------------------------------------------------------------------------
    # Processor & Resilient Controller Resolver
    # --------------------------------------------------------------------------
    def set_processor(self, processor):
        super().set_processor(processor)
        if processor is None:
            return
        pid = id(processor)
        self._build_ctrl_index(processor)
        if self._bound_proc_id != pid:
            self._bound_proc_id = pid
            self._rebuild_all_pages(select_tab=self.active_tab, rebuild_list=True)

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
            ns = _norm_key(sym)
            if ns:
                idx[ns] = z
            for cand in (getattr(z, "symbol", ""), getattr(z, "name", "")):
                k = _norm_key(cand)
                if k and k not in idx:
                    idx[k] = z
        self._ctrl_index = idx

    def _get_zctrl(self, sym):
        if not self.processor:
            return None
        z = self.processor.controllers_dict.get(sym)
        if z is not None:
            return z
        return self._ctrl_index.get(_norm_key(sym))

    # --------------------------------------------------------------------------
    # Dynamic 4-Encoder Page Mapping (6 Tabs, 2-Level Sub-Banks)
    # --------------------------------------------------------------------------
    def _env_prefix(self):
        return ("adsr", "adsr2", "adsr3")[self.env_idx]

    def _tab_items(self, tab):
        if tab == "Drawbars":
            if self.db_bank == 0:
                return [("l1", "16'"), ("l2", "5⅓'"), ("l3", "8'"), ("l4", "4'")]
            if self.db_bank == 1:
                return [("l5", "2⅔'"), ("l6", "2'"), ("l7", "1⅗'"), ("l8", "1⅓'")]
            return [("l9", "1'"), ("perc_level", "Perc"), ("vib_wet", "Chorus"), ("master", "Master")]

        if tab == "Harmonic":
            n = self.harm_idx + 1
            return [
                (f"f{n}",      f"D{n} Harm"),
                (f"w{n}",      f"D{n} Wave"),
                (f"detune{n}", f"D{n} Det"),
                (f"pan{n}",    f"D{n} Pan"),
            ]

        if tab == "Perc":
            if self.perc_bank == 0:
                return [
                    ("perc_level",    "Level"),
                    ("perc_decay",    "Decay"),
                    ("perc_harmonic", "Harmonic"),
                    ("perc_waveform", "Waveform"),
                ]
            return [
                ("perc_fm_depth",    "FM Depth"),
                ("perc_fm_decay",    "FM Decay"),
                ("perc_fm_harmonic", "FM Harm"),
                ("perc_stereo",      "Stereo"),
            ]

        if tab == "Filter":
            fn = "f1" if self.flt_idx == 0 else "f2"
            fl = "F1" if self.flt_idx == 0 else "F2"
            if self.flt_bank == 0:
                return [
                    (f"{fn}_cutoff", f"{fl} Cut"),
                    (f"{fn}_res",    f"{fl} Reso"),
                    (f"{fn}_env1",   f"{fl} EG1"),
                    (f"{fn}_keyf",   f"{fl} Key"),
                ]
            return [
                (f"{fn}_env1", f"{fl} EG1"),
                (f"{fn}_env2", f"{fl} EG2"),
                (f"{fn}_env3", f"{fl} EG3"),
                (f"{fn}_keyf", f"{fl} Key"),
            ]

        if tab == "Env":
            p = self._env_prefix()
            el = f"EG{self.env_idx + 1}"
            return [
                (f"{p}_a", f"{el} Att"),
                (f"{p}_d", f"{el} Dec"),
                (f"{p}_s", f"{el} Sus"),
                (f"{p}_r", f"{el} Rel"),
            ]

        # Vib/EQ
        if self.vib_bank == 0:
            return [
                ("vib_rate",  "Vib Rate"),
                ("vib_amt",   "Vib Amt"),
                ("vib_wet",   "Chorus"),
                ("vib_phase", "Phase"),
            ]
        if self.vib_bank == 1:
            return [
                ("bass_freq",   "Bass Hz"),
                ("bass_gain",   "Bass dB"),
                ("treble_freq", "Treb Hz"),
                ("treble_gain", "Treb dB"),
            ]
        return [
            ("master",    "Master"),
            ("transpose", "Transp"),
            ("polyphony", "Poly"),
            ("foldnote",  "Foldover"),
        ]

    def _build_page_zctrls(self, tab):
        zl = []
        for k, lbl in self._tab_items(tab):
            z = self._get_zctrl(k)
            if z is not None:
                z.short_name = lbl
                zl.append(z)
        return zl

    def _rebuild_all_pages(self, select_tab=None, rebuild_list=False):
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
        target = select_tab if select_tab in screens else self.active_tab
        self.active_tab = target
        self.last_snapshot = None
        if rebuild_list:
            self.after(25, lambda t=target: self._sync_list(t))
        else:
            self._live_swap(target)

    def _live_swap(self, tab):
        if not self.processor:
            return
        zl = self._build_page_zctrls(tab)
        self.processor.ctrl_screens_dict[tab] = zl
        try:
            if self.zyngui_control.get_current_processor() is self.processor:
                # Keep list_data & screen_info in sync so select-encoder never restores stale bank
                ld = getattr(self.zyngui_control, "list_data", None)
                if ld:
                    for i, row in enumerate(ld):
                        if len(row) >= 5 and row[2] == tab and row[3] is self.processor:
                            new_row = (row[0], row[1], row[2], row[3], zl) + tuple(row[5:])
                            ld[i] = new_row
                            info = getattr(self.zyngui_control, "screen_info", None)
                            if info and len(info) >= 5 and info[2] == tab and info[3] is self.processor:
                                self.zyngui_control.screen_info = new_row
                            break
                if self.last_screen_title != tab:
                    self._select_page(tab)
                else:
                    self.zyngui_control.zcontrollers = zl
                    for i in range(4):
                        self.zyngui_control.set_zcontroller(i, zl[i] if i < len(zl) else None)
        except Exception as e:
            logging.debug(f"Calf Organ live swap error: {e}")

    def _sync_list(self, tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page(tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Calf Organ sync error: {e}")

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

    # --------------------------------------------------------------------------
    # ECO CPU Tamer (Caps Polyphony to 8v with one-tap restore)
    # --------------------------------------------------------------------------
    def _toggle_eco(self):
        zp = self._get_zctrl("polyphony")
        if not self.eco_on:
            self.eco_on = True
            if zp is not None:
                cur = self._raw(zp, 16.0)
                self._eco_backup_poly = cur
                if cur > 8.0:
                    zp.set_value(8.0, send=True)
        else:
            self.eco_on = False
            if zp is not None and self._eco_backup_poly is not None:
                zp.set_value(max(float(zp.value_min), min(float(zp.value_max), self._eco_backup_poly)), send=True)
            self._eco_backup_poly = None
        self.last_snapshot = None
        self._draw()

    # --------------------------------------------------------------------------
    # Value Helpers (Log & Int Aware)
    # --------------------------------------------------------------------------
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
            if _norm_key(key) in LOG_KEYS and vmin > 0.0:
                return max(0.0, min(1.0, math.log(max(vmin, v) / vmin) / math.log(vmax / vmin)))
            return max(0.0, min(1.0, (v - vmin) / (vmax - vmin)))
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
        nk = _norm_key(key)
        if nk in LOG_KEYS and vmin > 0.0:
            v = vmin * ((vmax / vmin) ** n)
        else:
            v = vmin + n * (vmax - vmin)
        if nk in INT_KEYS or getattr(z, "is_integer", False):
            v = round(v)
        z.set_value(max(vmin, min(vmax, v)), send=True)

    @staticmethod
    def _reset_zctrl(z, key=""):
        if z is None:
            return
        d = getattr(z, "value_default", None)
        if d is None:
            nk = _norm_key(key)
            if nk.startswith("l") and nk[1:].isdigit():
                idx = int(nk[1:]) - 1
                if 0 <= idx < len(DRAWBARS):
                    d = DRAWBARS[idx][1]
            elif nk in ("bass_gain", "treble_gain"):
                d = 1.0
            elif nk in BIPOLAR_KEYS:
                d = 0.0
            else:
                d = 0.5 * (float(z.value_min) + float(z.value_max))
        z.set_value(max(float(z.value_min), min(float(z.value_max), float(d))), send=True)

    def _fmt_param(self, key, z):
        nk = _norm_key(key)
        v = self._raw(z, 0.0)
        if nk.startswith("l") and nk[1:].isdigit():
            return f"{v:.1f}" if abs(v - round(v)) > 0.05 else f"{int(round(v))}"
        if nk.startswith("w") and nk[1:].isdigit():
            idx = max(0, min(len(WAVEFORMS) - 1, int(round(v))))
            return WAVEFORMS[idx]
        if nk in ("perc_waveform", "perc_fm_waveform"):
            idx = max(0, min(len(WAVEFORMS) - 1, int(round(v))))
            return WAVEFORMS[idx]
        if nk.startswith("f") and nk[1:].isdigit():
            return f"{int(round(v))}x"
        if nk in ("perc_harmonic", "perc_fm_harmonic"):
            return f"{int(round(v))}x"
        if nk.startswith("detune") or nk == "detune":
            return f"{v:+.0f}c"
        if nk.startswith("pan"):
            if abs(v) < 0.03:
                return "C"
            return f"R{int(round(v * 100))}" if v > 0 else f"L{int(round(-v * 100))}"
        if nk in ("perc_decay", "perc_fm_decay") or nk.endswith(("_a", "_d", "_r")):
            return fmt_ms(v)
        if nk.endswith("_cutoff") or nk in ("bass_freq", "treble_freq"):
            return fmt_hz(v)
        if nk.endswith("_res"):
            return f"Q {v:.2f}"
        if nk in ("bass_gain", "treble_gain"):
            return fmt_gain_db(v)
        if nk == "vib_rate":
            return f"{v:.1f}Hz" if v < 20.0 else f"{v:.0f}Hz"
        if nk in ("vib_phase", "perc_stereo"):
            return f"{int(round(v))}°"
        if nk in ("perc_level", "vib_amt", "vib_wet", "master") or nk.endswith("_s"):
            return f"{int(round(v * 100))}%"
        if nk == "perc_fm_depth":
            return f"{v:.2f}"
        if nk.endswith(("_env1", "_env2", "_env3")):
            return f"{v / 100.0:+.0f}st"
        if nk.endswith("_keyf"):
            return f"{int(round(v * 100))}%"
        if nk == "transpose":
            return f"{int(round(v)):+d}st"
        if nk == "polyphony":
            return f"{int(round(v))}v"
        if nk == "foldnote":
            notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            ni = max(0, min(127, int(round(v))))
            return f"{notes[ni % 12]}{(ni // 12) - 1}"
        return f"{v:.2f}"

    # --------------------------------------------------------------------------
    # Fonts & Drawing Primitives (Unified UI Synths Design System)
    # --------------------------------------------------------------------------
    def _font(self, size, bold=False):
        key = (max(8, int(size)), bool(bold))
        f = self._font_cache.get(key)
        if f is None:
            f = (zynthian_gui_config.font_family, key[0], "bold" if bold else "normal")
            self._font_cache[key] = f
        return f

    def _fit_font(self, text, max_w, max_sz, bold=False, min_sz=8):
        text = str(text)
        max_w = max(12, int(max_w))
        for sz in range(max(min_sz, int(max_sz)), min_sz - 1, -1):
            k = (sz, bool(bold))
            tf = self._tk_font_cache.get(k)
            if tf is None:
                try:
                    tf = tkinter.font.Font(
                        family=zynthian_gui_config.font_family,
                        size=sz,
                        weight="bold" if bold else "normal",
                    )
                except Exception:
                    return self._font(sz, bold)
                self._tk_font_cache[k] = tf
            if tf.measure(text) <= max_w:
                return self._font(sz, bold)
        return self._font(min_sz, bold)

    def _draw_pill(self, x1, y1, x2, y2, label, active, accent, tag, data=None, bold=True):
        c = self.widget_canvas
        fill = accent if active else COL_PANEL
        fg = "#111217" if active else COL_TEXT
        out = accent if active else COL_BORDER
        c.create_rectangle(x1, y1, x2, y2, fill=fill, outline=out, width=1)
        fnt = self._fit_font(label, (x2 - x1) - 8, max(9, min(13, int((y2 - y1) * 0.40))), bold=bold)
        c.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=label, fill=fg, font=fnt)
        self.hitboxes.append((x1, y1, x2, y2, tag, data))

    def _draw_param_box(self, x1, y1, x2, y2, key, label, accent):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z, key, 0.0)
        val_txt = self._fmt_param(key, z)
        nk = _norm_key(key)
        c.create_rectangle(x1, y1, x2, y2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 6
        bar_h = max(7, int((y2 - y1) * 0.22))
        by2 = y2 - pad
        by1 = by2 - bar_h
        bx1, bx2 = x1 + pad, x2 - pad
        c.create_rectangle(bx1, by1, bx2, by2, fill=COL_TRACK, outline="")
        if nk in BIPOLAR_KEYS or nk in ("bass_gain", "treble_gain"):
            mid = 0.5 * (bx1 + bx2)
            vx = bx1 + (bx2 - bx1) * n
            c.create_rectangle(min(mid, vx), by1, max(mid, vx), by2, fill=accent, outline="")
            c.create_line(mid, by1 - 2, mid, by2 + 2, fill=COL_DIM, width=1)
        elif n > 0.005:
            c.create_rectangle(bx1, by1, bx1 + (bx2 - bx1) * n, by2, fill=accent, outline="")
        top_y = y1 + (by1 - y1) * 0.48
        w_in = max(20, (x2 - x1) - 12)
        c.create_text(x1 + 6, top_y, text=label, anchor="w", fill=COL_DIM,
                      font=self._fit_font(label, w_in * 0.50, 11, bold=False))
        c.create_text(x2 - 6, top_y, text=val_txt, anchor="e", fill=COL_TEXT,
                      font=self._fit_font(val_txt, w_in * 0.54, 12, bold=True))
        self.hitboxes.append((x1, y1, x2, y2, "param", (key, x1 + pad, x2 - pad)))

    # --------------------------------------------------------------------------
    # Lifecycle & Throttled Update
    # --------------------------------------------------------------------------
    def on_size(self, event):
        if super().on_size(event):
            self.last_snapshot = None
            self._draw()

    def _snapshot(self):
        # Collect values relevant to active tab for dirty-checking
        keys = [k for k, _ in self._tab_items(self.active_tab)]
        if self.active_tab == "Drawbars":
            keys.extend([f"l{i}" for i in range(1, 10)])
        elif self.active_tab == "Harmonic":
            n = self.harm_idx + 1
            keys.extend([f"f{n}", f"w{n}", f"detune{n}", f"pan{n}", f"routing{n}"])
        elif self.active_tab == "Perc":
            keys.extend(["perc_level", "perc_decay", "perc_waveform", "perc_harmonic",
                         "perc_fm_depth", "perc_fm_decay", "perc_fm_harmonic", "perc_trigger", "perc_stereo"])
        elif self.active_tab == "Filter":
            keys.extend(["filter_chain", "filter1_type", "f1_cutoff", "f1_res", "f2_cutoff", "f2_res"])
        elif self.active_tab == "Env":
            p = self._env_prefix()
            keys.extend([f"{p}_a", f"{p}_d", f"{p}_s", f"{p}_r", f"{p}_v",
                         f"eg{self.env_idx + 1}_amp_ctl", "quad_env"])
        elif self.active_tab == "Vib/EQ":
            keys.extend(["vib_rate", "vib_amt", "vib_wet", "vib_phase", "vib_mode", "vib_type",
                         "bass_freq", "bass_gain", "treble_freq", "treble_gain", "master", "polyphony"])
        vals = tuple(round(self._raw(self._get_zctrl(k), 0.0), 4) for k in keys)
        state = (self.active_tab, self.db_bank, self.harm_idx, self.perc_bank,
                 self.flt_idx, self.flt_bank, self.env_idx, self.vib_bank,
                 self.eco_on, self.width, self.height)
        return (state, vals)

    def update(self):
        now = time.monotonic()
        if now < self.next_update:
            return
        self.next_update = now + UPDATE_PERIOD
        dt = max(0.001, min(0.25, now - self._last_tick))
        self._last_tick = now
        super().update()
        self._follow_page()

        # Subtle phase motion on Vib/EQ tab only when scanner vibrato is active
        vib_anim = False
        if self.active_tab == "Vib/EQ":
            vm = int(round(self._raw(self._get_zctrl("vib_mode"), 0.0)))
            if vm > 0:
                vr = max(0.2, min(14.0, self._raw(self._get_zctrl("vib_rate"), 6.6)))
                self._vib_phase_anim = (self._vib_phase_anim + dt * vr * 0.8) % (2.0 * math.pi)
                vib_anim = True

        snap = self._snapshot()
        if snap != self.last_snapshot or self.drag_target is not None or vib_anim:
            self.last_snapshot = snap
            self._draw()

    def refresh_gui(self):
        self.last_snapshot = None
        self._draw()

    # --------------------------------------------------------------------------
    # Main Render
    # --------------------------------------------------------------------------
    def _draw(self):
        c = self.widget_canvas
        w = max(240, int(self.width or c.winfo_width() or 640))
        h = max(200, int(self.height or c.winfo_height() or 440))

        c.delete("all")
        self.hitboxes = []

        pad = 6
        gap = 6
        hdr_h = max(36, min(46, int(h * 0.11)))
        sub_h = max(34, min(40, int(h * 0.09)))
        pbox_h = max(44, min(56, int(h * 0.135)))
        accent = TAB_ACCENTS.get(self.active_tab, "#ff922b")

        # --- Header: 6 Workstation Tabs + ECO ---
        eco_w = max(54, int(w * 0.095))
        tabs_w = w - 2 * pad - eco_w - gap
        tw = (tabs_w - gap * (len(TABS) - 1)) / len(TABS)
        for i, t in enumerate(TABS):
            tx1 = pad + i * (tw + gap)
            self._draw_pill(tx1, pad, tx1 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        self._draw_pill(w - pad - eco_w, pad, w - pad, pad + hdr_h,
                        "ECO" if not self.eco_on else "ECO 8v",
                        self.eco_on, COL_ECO, "eco", None)

        sub_y1 = pad + hdr_h + gap
        sub_y2 = sub_y1 + sub_h
        vis_y1 = sub_y2 + gap
        vis_y2 = h - pad - pbox_h - gap

        if self.active_tab == "Drawbars":
            self._draw_drawbars_tab(pad, sub_y1, sub_y2, vis_y1, vis_y2, w - pad, accent)
        elif self.active_tab == "Harmonic":
            self._draw_harmonic_tab(pad, sub_y1, sub_y2, vis_y1, vis_y2, w - pad, accent)
        elif self.active_tab == "Perc":
            self._draw_perc_tab(pad, sub_y1, sub_y2, vis_y1, vis_y2, w - pad, accent)
        elif self.active_tab == "Filter":
            self._draw_filter_tab(pad, sub_y1, sub_y2, vis_y1, vis_y2, w - pad, accent)
        elif self.active_tab == "Env":
            self._draw_env_tab(pad, sub_y1, sub_y2, vis_y1, vis_y2, w - pad, accent)
        else:
            self._draw_vib_eq_tab(pad, sub_y1, sub_y2, vis_y1, vis_y2, w - pad, accent)

        # --- Bottom 4 Encoder Parameter Boxes ---
        items = self._tab_items(self.active_tab)
        bw = (w - 2 * pad - 3 * gap) / 4.0
        by1 = h - pad - pbox_h
        by2 = h - pad
        for i, (k, lbl) in enumerate(items):
            px1 = pad + i * (bw + gap)
            self._draw_param_box(px1, by1, px1 + bw, by2, k, lbl, accent)

    # --------------------------------------------------------------------------
    # Tab 1: Drawbars — 9 Iconic Pull-Down Hammond B3 Drawbars
    # --------------------------------------------------------------------------
    def _draw_drawbars_tab(self, x1, sy1, sy2, vy1, vy2, x2, accent):
        c = self.widget_canvas
        gap = 6

        # Sub-bar: 3 Encoder Banks (left) + 4 Classic B3 Registrations (right)
        banks = [("1-4", 0), ("5-8", 1), ("9+Vol", 2)]
        total_w = x2 - x1
        n_pills = len(banks) + len(REGISTRATIONS)
        pw = (total_w - gap * (n_pills - 1)) / n_pills
        cx = x1
        for lbl, bidx in banks:
            self._draw_pill(cx, sy1, cx + pw, sy2, lbl, self.db_bank == bidx, accent, "db_bank", bidx)
            cx += pw + gap
        for rname, rvals in REGISTRATIONS:
            self._draw_pill(cx, sy1, cx + pw, sy2, rname, False, "#4dabf7", "reg_preset", rvals, bold=False)
            cx += pw + gap

        # 9 Drawbar Columns
        c.create_rectangle(x1, vy1, x2, vy2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        in_pad = 8
        col_gap = 6
        cw = (x2 - x1 - 2 * in_pad - 8 * col_gap) / 9.0
        track_top = vy1 + 24
        track_bot = vy2 - 22
        track_h = max(40, track_bot - track_top)

        # Which drawbar indices (0..8) are currently bound to encoders?
        bound_set = {0, 1, 2, 3} if self.db_bank == 0 else ({4, 5, 6, 7} if self.db_bank == 1 else {8})

        for i, (foot, _def_l, _def_f, role) in enumerate(DRAWBARS):
            bx1 = x1 + in_pad + i * (cw + col_gap)
            bx2 = bx1 + cw
            sym = f"l{i + 1}"
            val = max(0.0, min(8.0, self._raw(self._get_zctrl(sym), 0.0)))
            frac = val / 8.0

            # Top numeric readout (0..8)
            is_bound = i in bound_set
            c.create_text((bx1 + bx2) / 2, vy1 + 12, text=f"{val:.0f}",
                          fill=accent if is_bound else COL_TEXT,
                          font=self._font(11, bold=True))

            # Drawbar slot track
            slot_out = accent if is_bound else COL_BORDER
            c.create_rectangle(bx1, track_top, bx2, track_bot, fill="#121318", outline=slot_out, width=1.5 if is_bound else 1)

            # Subtle tick notches 1..7
            for t_i in range(1, 8):
                ty = track_top + (track_h * t_i / 8.0)
                c.create_line(bx1 + 3, ty, bx2 - 3, ty, fill=COL_GRID, width=1)

            # Pull-down drawbar shaft + cap handle (0 = top, 8 = fully pulled down)
            cap_h = max(18, min(26, int(track_h * 0.18)))
            pull_y = track_top + frac * (track_h - cap_h)
            shaft_col, cap_col, cap_fg = DRAWBAR_COLORS[role]
            if pull_y > track_top + 2:
                # Metallic shaft visible above cap
                sx1 = bx1 + max(4, cw * 0.16)
                sx2 = bx2 - max(4, cw * 0.16)
                c.create_rectangle(sx1, track_top + 1, sx2, pull_y, fill="#555a6e", outline="")
                # Numbered ruler markings on shaft
                steps_shown = int(round(val))
                for s_i in range(1, steps_shown + 1):
                    sy_m = track_top + (s_i / 8.0) * (track_h - cap_h) - 6
                    if sy_m > track_top + 5 and sy_m < pull_y - 4:
                        c.create_line(sx1 + 2, sy_m, sx2 - 2, sy_m, fill="#252730", width=1)

            # Colored Hammond drawbar handle tip
            c.create_rectangle(bx1 + 2, pull_y, bx2 - 2, pull_y + cap_h,
                               fill=shaft_col, outline=cap_col, width=1.5)
            c.create_text((bx1 + bx2) / 2, pull_y + cap_h * 0.5, text=foot,
                          fill=cap_fg, font=self._fit_font(foot, cw - 6, 10, bold=True))

            # Bottom footage label
            c.create_text((bx1 + bx2) / 2, vy2 - 11, text=foot,
                          fill=accent if is_bound else COL_DIM,
                          font=self._fit_font(foot, cw, 10, bold=is_bound))

            self.hitboxes.append((bx1 - 2, vy1, bx2 + 2, vy2, "drawbar", (sym, track_top + cap_h * 0.5, track_bot - cap_h * 0.5)))

    # --------------------------------------------------------------------------
    # Tab 2: Harmonic — Per-Drawbar Wave, Harmonic Multiplier, Routing & Preview
    # --------------------------------------------------------------------------
    def _draw_harmonic_tab(self, x1, sy1, sy2, vy1, vy2, x2, accent):
        c = self.widget_canvas
        gap = 6

        # Sub-bar: D1..D9 selector pills
        pw = (x2 - x1 - 8 * gap) / 9.0
        for i in range(9):
            px1 = x1 + i * (pw + gap)
            foot = DRAWBARS[i][0]
            self._draw_pill(px1, sy1, px1 + pw, sy2, f"{i + 1}:{foot}", self.harm_idx == i, accent, "harm_sel", i)

        n = self.harm_idx + 1
        w_val = int(round(self._raw(self._get_zctrl(f"w{n}"), 0.0)))
        w_idx = max(0, min(len(WAVEFORMS) - 1, w_val))
        h_mul = int(round(self._raw(self._get_zctrl(f"f{n}"), DRAWBARS[self.harm_idx][2])))
        det = self._raw(self._get_zctrl(f"detune{n}"), 0.0)
        pan = self._raw(self._get_zctrl(f"pan{n}"), 0.0)
        rt = int(round(self._raw(self._get_zctrl(f"routing{n}"), 0.0)))
        lvl = self._raw(self._get_zctrl(f"l{n}"), 0.0)

        # Left 62%: Live Waveform Scope + Stepper
        sw = int((x2 - x1 - gap) * 0.62)
        sx2 = x1 + sw
        c.create_rectangle(x1, vy1, sx2, vy2, fill=COL_PANEL, outline=COL_BORDER, width=1)

        title = f"Drawbar {n} ({DRAWBARS[self.harm_idx][0]}) · {WAVEFORMS[w_idx]} · {h_mul}x · Lvl {lvl:.0f}/8"
        c.create_text(x1 + 10, vy1 + 14, text=title, anchor="w", fill=COL_TEXT,
                      font=self._fit_font(title, sw - 20, 11, bold=True))

        # Waveform plot area
        wpx1, wpy1 = x1 + 12, vy1 + 28
        wpx2, wpy2 = sx2 - 12, vy2 - 46
        mid_y = 0.5 * (wpy1 + wpy2)
        amp_y = max(14.0, (wpy2 - wpy1) * 0.42)
        c.create_line(wpx1, mid_y, wpx2, mid_y, fill=COL_GRID, width=1)
        pts = []
        steps = 64
        cycles = max(1.0, min(4.0, 1.0 + math.log2(max(1, h_mul)) * 0.5))
        for i in range(steps + 1):
            frac = i / steps
            ph = frac * cycles * 2.0 * math.pi
            sv = synth_wave_sample(w_idx, ph)
            pts.extend([wpx1 + frac * (wpx2 - wpx1), mid_y - sv * amp_y])
        if len(pts) >= 4:
            c.create_line(*pts, fill=accent, width=2.5, smooth=True)

        # Waveform stepper pills (◀ Wave ▶) >= 34 px
        btn_y1 = vy2 - 40
        btn_y2 = vy2 - 6
        btn_w = max(56, int((sw - 24) * 0.24))
        self._draw_pill(x1 + 8, btn_y1, x1 + 8 + btn_w, btn_y2, "◀ Wave", False, accent, "wave_step", (f"w{n}", -1))
        self._draw_pill(sx2 - 8 - btn_w, btn_y1, sx2 - 8, btn_y2, "Wave ▶", False, accent, "wave_step", (f"w{n}", +1))
        c.create_text(0.5 * (x1 + sx2), 0.5 * (btn_y1 + btn_y2),
                      text=f"{w_idx + 1}/36: {WAVEFORMS[w_idx]}",
                      fill=accent, font=self._fit_font(f"{w_idx + 1}/36: {WAVEFORMS[w_idx]}", sw - 2 * btn_w - 24, 12, bold=True))

        # Right 38%: Routing Pills + 2D Detune x Pan Pad
        rx1 = sx2 + gap
        c.create_rectangle(rx1, vy1, x2, vy2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        c.create_text(rx1 + 10, vy1 + 14, text="Routing & Pan × Detune", anchor="w",
                      fill=COL_TEXT, font=self._fit_font("Routing & Pan × Detune", (x2 - rx1) - 20, 11, bold=True))

        # 3 Routing pills (Out / Flt 1 / Flt 2), >= 34px tall
        ry1 = vy1 + 26
        ry2 = ry1 + 34
        rw = (x2 - rx1 - 16 - 2 * gap) / 3.0
        for ri, rlbl in enumerate(ROUTINGS):
            rpx1 = rx1 + 8 + ri * (rw + gap)
            self._draw_pill(rpx1, ry1, rpx1 + rw, ry2, rlbl, rt == ri, accent, "set_int", (f"routing{n}", ri))

        # 2D Pan (X) x Detune (Y) Pad
        apx1, apy1 = rx1 + 10, ry2 + 8
        apx2, apy2 = x2 - 10, vy2 - 20
        c.create_rectangle(apx1, apy1, apx2, apy2, fill="#14151a", outline=COL_BORDER, width=1)
        c.create_line(0.5 * (apx1 + apx2), apy1, 0.5 * (apx1 + apx2), apy2, fill=COL_GRID)
        c.create_line(apx1, 0.5 * (apy1 + apy2), apx2, 0.5 * (apy1 + apy2), fill=COL_GRID)
        pn = self._norm(self._get_zctrl(f"pan{n}"), f"pan{n}", 0.5)
        dn = self._norm(self._get_zctrl(f"detune{n}"), f"detune{n}", 0.5)
        nx = apx1 + pn * (apx2 - apx1)
        ny = apy2 - dn * (apy2 - apy1)
        c.create_oval(nx - 9, ny - 9, nx + 9, ny + 9, fill=accent, outline="#ffffff", width=2)
        c.create_text(apx1, vy2 - 10, text=f"Pan {self._fmt_param(f'pan{n}', self._get_zctrl(f'pan{n}'))}",
                      anchor="w", fill=COL_DIM, font=self._font(9))
        c.create_text(apx2, vy2 - 10, text=f"Det {det:+.0f}c", anchor="e", fill=COL_DIM, font=self._font(9))
        self.hitboxes.append((apx1, apy1, apx2, apy2, "harm_2d", (n, apx1, apy1, apx2, apy2)))

    # --------------------------------------------------------------------------
    # Tab 3: Perc — Carrier & FM Percussion Envelope + Trigger Modes
    # --------------------------------------------------------------------------
    def _draw_perc_tab(self, x1, sy1, sy2, vy1, vy2, x2, accent):
        c = self.widget_canvas
        gap = 6

        # Sub-bar: Carrier / FM Mod + 4 Trigger Modes
        trg = int(round(self._raw(self._get_zctrl("perc_trigger"), 0.0)))
        n_pills = 6
        pw = (x2 - x1 - (n_pills - 1) * gap) / n_pills
        cx = x1
        for lbl, bidx in (("Carrier", 0), ("FM Mod", 1)):
            self._draw_pill(cx, sy1, cx + pw, sy2, lbl, self.perc_bank == bidx, accent, "perc_bank", bidx)
            cx += pw + gap
        for ti, tlbl in enumerate(PERC_TRIGGERS):
            self._draw_pill(cx, sy1, cx + pw, sy2, tlbl, trg == ti, "#4dabf7", "set_int", ("perc_trigger", ti))
            cx += pw + gap

        c.create_rectangle(x1, vy1, x2, vy2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        plvl = self._raw(self._get_zctrl("perc_level"), 0.25)
        pdec = self._raw(self._get_zctrl("perc_decay"), 200.0)
        pharm = int(round(self._raw(self._get_zctrl("perc_harmonic"), 3.0)))
        pwave = int(round(self._raw(self._get_zctrl("perc_waveform"), 0.0)))
        fm_dep = self._raw(self._get_zctrl("perc_fm_depth"), 0.0)
        fm_dec = self._raw(self._get_zctrl("perc_fm_decay"), 200.0)
        fm_h = int(round(self._raw(self._get_zctrl("perc_fm_harmonic"), 2.0)))

        wname = WAVEFORMS[max(0, min(len(WAVEFORMS) - 1, pwave))]
        hdr = f"Percussion · {wname} ({pharm}x) · Decay {fmt_ms(pdec)} · FM {fm_dep:.2f} ({fm_h}x)"
        c.create_text(x1 + 10, vy1 + 14, text=hdr, anchor="w", fill=COL_TEXT,
                      font=self._fit_font(hdr, (x2 - x1) - 20, 11, bold=True))

        px1, py1 = x1 + 16, vy1 + 28
        px2, py2 = x2 - 16, vy2 - 20
        pw_p = max(40, px2 - px1)
        ph_p = max(40, py2 - py1)

        for frac in (0.25, 0.5, 0.75):
            c.create_line(px1 + pw_p * frac, py1, px1 + pw_p * frac, py2, fill=COL_GRID)
            c.create_line(px1, py1 + ph_p * frac, px2, py1 + ph_p * frac, fill=COL_GRID)

        # Draw carrier exponential decay + FM decay overlay over 0..3.0s
        car_pts = []
        fm_pts = []
        steps = 64
        for i in range(steps + 1):
            frac = i / steps
            t_ms = frac * 3000.0
            ce = plvl * math.exp(-3.0 * t_ms / max(10.0, pdec))
            fe = min(1.0, (fm_dep / 4.0) * math.exp(-3.0 * t_ms / max(10.0, fm_dec)))
            sx = px1 + frac * pw_p
            car_pts.extend([sx, py2 - ce * ph_p])
            fm_pts.extend([sx, py2 - fe * ph_p])

        if len(fm_pts) >= 4 and fm_dep > 0.02:
            c.create_line(*fm_pts, fill="#cc5de8", dash=(4, 3), width=2, smooth=True)
        if len(car_pts) >= 4:
            c.create_line(*car_pts, fill=accent, width=2.5, smooth=True)

        # 2D Interactive Node (Carrier: Decay x Level | FM Mod: FM Decay x FM Depth)
        if self.perc_bank == 0:
            nx_n = self._norm(self._get_zctrl("perc_decay"), "perc_decay", 0.4)
            ny_n = self._norm(self._get_zctrl("perc_level"), "perc_level", 0.25)
            nlbl = "DECAY × LEVEL"
        else:
            nx_n = self._norm(self._get_zctrl("perc_fm_decay"), "perc_fm_decay", 0.4)
            ny_n = self._norm(self._get_zctrl("perc_fm_depth"), "perc_fm_depth", 0.0)
            nlbl = "FM DECAY × DEPTH"

        nx = px1 + nx_n * pw_p
        ny = py2 - ny_n * ph_p
        c.create_line(nx, py1, nx, py2, fill=accent, dash=(2, 3), width=1)
        c.create_line(px1, ny, px2, ny, fill=accent, dash=(2, 3), width=1)
        c.create_oval(nx - 10, ny - 10, nx + 10, ny + 10, fill=accent, outline="#ffffff", width=2)
        c.create_text(px1, vy2 - 10, text=f"Drag 2D: {nlbl} (Double-tap Reset)", anchor="w",
                      fill=COL_DIM, font=self._font(9))
        self.hitboxes.append((px1, py1, px2, py2, "perc_2d", (px1, py1, px2, py2)))

    # --------------------------------------------------------------------------
    # Tab 4: Filter — Dual F1/F2 Bode Response + 2D Cutoff x Resonance
    # --------------------------------------------------------------------------
    def _draw_filter_tab(self, x1, sy1, sy2, vy1, vy2, x2, accent):
        c = self.widget_canvas
        gap = 6

        f1_hp = self._raw(self._get_zctrl("filter1_type"), 0.0) >= 0.5
        chain = self._raw(self._get_zctrl("filter_chain"), 0.0) >= 0.5

        n_pills = 5
        pw = (x2 - x1 - (n_pills - 1) * gap) / n_pills
        cx = x1
        self._draw_pill(cx, sy1, cx + pw, sy2, "Filter 1", self.flt_idx == 0, accent, "flt_sel", 0)
        cx += pw + gap
        self._draw_pill(cx, sy1, cx + pw, sy2, "Filter 2", self.flt_idx == 1, accent, "flt_sel", 1)
        cx += pw + gap
        self._draw_pill(cx, sy1, cx + pw, sy2, "F1: 12dB HP" if f1_hp else "F1: 12dB LP",
                        f1_hp, "#ff922b", "toggle", "filter1_type")
        cx += pw + gap
        self._draw_pill(cx, sy1, cx + pw, sy2, "F1 → F2" if chain else "F1 → Out",
                        chain, "#cc5de8", "toggle", "filter_chain")
        cx += pw + gap
        self._draw_pill(cx, sy1, cx + pw, sy2, "Env Mod" if self.flt_bank == 1 else "Main",
                        self.flt_bank == 1, "#51cf66", "flt_bank", 1 - self.flt_bank)

        c.create_rectangle(x1, vy1, x2, vy2, fill=COL_PANEL, outline=COL_BORDER, width=1)

        f1_c = self._raw(self._get_zctrl("f1_cutoff"), 2000.0)
        f1_r = self._raw(self._get_zctrl("f1_res"), 2.0)
        f2_c = self._raw(self._get_zctrl("f2_cutoff"), 2000.0)
        f2_r = self._raw(self._get_zctrl("f2_res"), 2.0)

        px1, py1 = x1 + 32, vy1 + 26
        px2, py2 = x2 - 14, vy2 - 20
        pw_p = max(40, px2 - px1)
        ph_p = max(40, py2 - py1)

        def hz_to_x(hz):
            return px1 + (math.log(max(20.0, min(20000.0, hz)) / 20.0) / math.log(1000.0)) * pw_p

        def db_to_y(db):
            # -30..+24 dB
            return py2 - ((max(-30.0, min(24.0, db)) + 30.0) / 54.0) * ph_p

        # Frequency & dB grid
        for hz, lbl in ((50, "50"), (200, "200"), (1000, "1k"), (5000, "5k"), (15000, "15k")):
            gx = hz_to_x(hz)
            c.create_line(gx, py1, gx, py2, fill=COL_GRID)
            c.create_text(gx, py2 + 9, text=lbl, fill=COL_DIM, font=self._font(8))
        for db in (-24, -12, 0, 12):
            gy = db_to_y(db)
            c.create_line(px1, gy, px2, gy, fill="#383b4d" if db == 0 else COL_GRID)
            c.create_text(px1 - 4, gy, text=f"{db:+d}" if db > 0 else f"{db}", anchor="e", fill=COL_DIM, font=self._font(8))

        # Plot both F1 & F2 curves
        steps = 56
        pts1, pts2 = [], []
        for i in range(steps + 1):
            hz = 20.0 * (1000.0 ** (i / steps))
            d1 = eval_organ_filter_db(hz, f1_c, f1_r, is_hp=f1_hp)
            d2 = eval_organ_filter_db(hz, f2_c, f2_r, is_hp=False)
            pts1.extend([hz_to_x(hz), db_to_y(d1)])
            pts2.extend([hz_to_x(hz), db_to_y(d2)])

        if self.flt_idx == 0:
            c.create_line(*pts2, fill=COL_DIM, dash=(4, 3), width=1.5, smooth=True)
            c.create_line(*pts1, fill=accent, width=2.5, smooth=True)
            ac, ar, fn = f1_c, f1_r, "f1"
        else:
            c.create_line(*pts1, fill=COL_DIM, dash=(4, 3), width=1.5, smooth=True)
            c.create_line(*pts2, fill=accent, width=2.5, smooth=True)
            ac, ar, fn = f2_c, f2_r, "f2"

        # 2D Node for active filter
        nx = hz_to_x(ac)
        ny = py2 - self._norm(self._get_zctrl(f"{fn}_res"), f"{fn}_res", 0.3) * ph_p
        c.create_line(nx, py1, nx, py2, fill=accent, dash=(2, 3), width=1)
        c.create_oval(nx - 10, ny - 10, nx + 10, ny + 10, fill=accent, outline="#ffffff", width=2)
        c.create_text(x1 + 10, vy1 + 13,
                      text=f"Filter {self.flt_idx + 1} · Cutoff {fmt_hz(ac)} · Q {ar:.2f} · {'Series (F1→F2)' if chain else 'Parallel'}",
                      anchor="w", fill=COL_TEXT, font=self._font(11, bold=True))
        self.hitboxes.append((px1, py1, px2, py2, "flt_2d", (fn, px1, py1, px2, py2)))

    # --------------------------------------------------------------------------
    # Tab 5: Env — EG 1 / EG 2 / EG 3 Interactive 4-Stage ADSR
    # --------------------------------------------------------------------------
    def _draw_env_tab(self, x1, sy1, sy2, vy1, vy2, x2, accent):
        c = self.widget_canvas
        gap = 6

        p = self._env_prefix()
        quad = self._raw(self._get_zctrl("quad_env"), 0.0) >= 0.5
        amp_key = f"eg{self.env_idx + 1}_amp_ctl"
        amp_i = max(0, min(len(AMP_CTLS) - 1, int(round(self._raw(self._get_zctrl(amp_key), 0.0)))))

        n_pills = 5
        pw = (x2 - x1 - (n_pills - 1) * gap) / n_pills
        cx = x1
        for ei in range(3):
            self._draw_pill(cx, sy1, cx + pw, sy2, f"EG {ei + 1}", self.env_idx == ei, accent, "env_sel", ei)
            cx += pw + gap
        self._draw_pill(cx, sy1, cx + pw, sy2, "Quad Env", quad, "#ffd43b", "toggle", "quad_env")
        cx += pw + gap
        self._draw_pill(cx, sy1, cx + pw, sy2, f"Amp: {AMP_CTLS[amp_i]}", amp_i > 0, "#4dabf7",
                        "cycle_int", (amp_key, len(AMP_CTLS)))

        c.create_rectangle(x1, vy1, x2, vy2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        an = self._norm(self._get_zctrl(f"{p}_a"), f"{p}_a", 0.05)
        dn = self._norm(self._get_zctrl(f"{p}_d"), f"{p}_d", 0.35)
        sn = self._norm(self._get_zctrl(f"{p}_s"), f"{p}_s", 0.70)
        rn = self._norm(self._get_zctrl(f"{p}_r"), f"{p}_r", 0.25)

        a_ms = self._raw(self._get_zctrl(f"{p}_a"), 1.0)
        d_ms = self._raw(self._get_zctrl(f"{p}_d"), 350.0)
        r_ms = self._raw(self._get_zctrl(f"{p}_r"), 50.0)

        c.create_text(x1 + 10, vy1 + 14,
                      text=f"EG {self.env_idx + 1} · A {fmt_ms(a_ms)} · D {fmt_ms(d_ms)} · S {int(round(sn * 100))}% · R {fmt_ms(r_ms)}",
                      anchor="w", fill=COL_TEXT, font=self._font(11, bold=True))

        px1, py1 = x1 + 18, vy1 + 30
        px2, py2 = x2 - 18, vy2 - 18
        pw_p = max(60, px2 - px1)
        ph_p = max(40, py2 - py1)

        for frac in (0.25, 0.5, 0.75):
            c.create_line(px1, py1 + ph_p * frac, px2, py1 + ph_p * frac, fill=COL_GRID)

        # Geometry of A, D, S hold, R segments
        ax = px1 + (0.04 + 0.26 * an) * pw_p
        ay = py1 + 4
        dx = ax + (0.05 + 0.25 * dn) * pw_p
        sy = py2 - sn * (ph_p - 4)
        sx_end = dx + 0.16 * pw_p
        rx = min(px2, sx_end + (0.04 + 0.24 * rn) * pw_p)

        # Shaded envelope polygon
        c.create_polygon(px1, py2, ax, ay, dx, sy, sx_end, sy, rx, py2,
                         fill="#1f3226", outline="")
        c.create_line(px1, py2, ax, ay, dx, sy, sx_end, sy, rx, py2,
                      fill=accent, width=2.5)

        # 3 Large Touch Handles (A, D/S, R)
        for hx, hy, hlbl, htag in (
            (ax, ay, "A", "env_a"),
            (dx, sy, "D/S", "env_ds"),
            (rx, py2 - 10, "R", "env_r"),
        ):
            c.create_oval(hx - 10, hy - 10, hx + 10, hy + 10, fill=accent, outline="#ffffff", width=2)
            c.create_text(hx, hy - 16 if hy > py1 + 22 else hy + 17, text=hlbl,
                          fill=COL_TEXT, font=self._font(9, bold=True))
            self.hitboxes.append((hx - 26, hy - 26, hx + 26, hy + 26, htag, (p, px1, py1, px2, py2)))

    # --------------------------------------------------------------------------
    # Tab 6: Vib/EQ — Scanner Vibrato/Chorus + Tone Stack EQ
    # --------------------------------------------------------------------------
    def _draw_vib_eq_tab(self, x1, sy1, sy2, vy1, vy2, x2, accent):
        c = self.widget_canvas
        gap = 6

        vtype = max(0, min(len(VIB_TYPES) - 1, int(round(self._raw(self._get_zctrl("vib_type"), 1.0)))))
        vmode = max(0, min(len(VIB_MODES) - 1, int(round(self._raw(self._get_zctrl("vib_mode"), 5.0)))))

        n_pills = 5
        pw = (x2 - x1 - (n_pills - 1) * gap) / n_pills
        cx = x1
        for lbl, bidx in (("Vibrato", 0), ("Tone EQ", 1), ("Master", 2)):
            self._draw_pill(cx, sy1, cx + pw, sy2, lbl, self.vib_bank == bidx, accent, "vib_bank", bidx)
            cx += pw + gap
        self._draw_pill(cx, sy1, cx + pw, sy2, VIB_TYPES[vtype], vmode > 0, "#ffd43b",
                        "cycle_int", ("vib_type", len(VIB_TYPES)))
        cx += pw + gap
        self._draw_pill(cx, sy1, cx + pw, sy2, f"M: {VIB_MODES[vmode]}", vmode > 0, "#4dabf7",
                        "cycle_int", ("vib_mode", len(VIB_MODES)))

        # Split Left 52% Scanner Vibrato | Right 48% Tone Stack EQ
        mid_x = x1 + int((x2 - x1 - gap) * 0.52)

        # --- Left: Scanner Vibrato / Chorus Visualizer (2D: Rate x Chorus) ---
        c.create_rectangle(x1, vy1, mid_x, vy2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        vrate = self._raw(self._get_zctrl("vib_rate"), 6.6)
        vamt = self._raw(self._get_zctrl("vib_amt"), 0.5)
        vwet = self._raw(self._get_zctrl("vib_wet"), 0.5)
        vph = self._raw(self._get_zctrl("vib_phase"), 0.0)

        c.create_text(x1 + 10, vy1 + 13, text=f"Scanner {VIB_TYPES[vtype]} · {vrate:.1f}Hz",
                      anchor="w", fill=COL_TEXT, font=self._font(10, bold=True))

        vx1, vy_1 = x1 + 10, vy1 + 26
        vx2, vy_2 = mid_x - 10, vy2 - 18
        vw = max(40, vx2 - vx1)
        vh = max(30, vy_2 - vy_1)
        vmid = 0.5 * (vy_1 + vy_2)
        c.create_line(vx1, vmid, vx2, vmid, fill=COL_GRID)

        # Draw L & R phase-shifted scanner sine waves
        pts_l, pts_r = [], []
        ph_rad = math.radians(vph)
        cycles = max(1.0, min(6.0, 0.8 + math.log2(max(0.5, vrate)) * 0.7))
        amp = max(4.0, (vh * 0.40) * (0.25 + 0.75 * vamt))
        for i in range(49):
            f = i / 48.0
            ang = f * cycles * 2.0 * math.pi + self._vib_phase_anim
            sx = vx1 + f * vw
            pts_l.extend([sx, vmid - math.sin(ang) * amp])
            pts_r.extend([sx, vmid - math.sin(ang + ph_rad) * amp * (0.3 + 0.7 * vwet)])
        if vmode > 0:
            c.create_line(*pts_r, fill="#4dabf7", width=1.5, smooth=True)
            c.create_line(*pts_l, fill=accent, width=2.2, smooth=True)
        else:
            c.create_line(*pts_l, fill=COL_DIM, dash=(3, 3), width=1.5, smooth=True)

        # 2D Node: Rate (X) x Chorus Wet (Y)
        nx = vx1 + self._norm(self._get_zctrl("vib_rate"), "vib_rate", 0.5) * vw
        ny = vy_2 - self._norm(self._get_zctrl("vib_wet"), "vib_wet", 0.5) * vh
        c.create_oval(nx - 8, ny - 8, nx + 8, ny + 8, fill=accent, outline="#ffffff", width=2)
        c.create_text(vx1, vy2 - 9, text="2D: Rate × Chorus", anchor="w", fill=COL_DIM, font=self._font(8))
        self.hitboxes.append((vx1, vy_1, vx2, vy_2, "vib_2d", (vx1, vy_1, vx2, vy_2)))

        # --- Right: Bass & Treble Tone EQ Curve (2D: Bass Gain x Treble Gain) ---
        ex1 = mid_x + gap
        c.create_rectangle(ex1, vy1, x2, vy2, fill=COL_PANEL, outline=COL_BORDER, width=1)
        bf = self._raw(self._get_zctrl("bass_freq"), 120.0)
        bg = self._raw(self._get_zctrl("bass_gain"), 1.0)
        tf = self._raw(self._get_zctrl("treble_freq"), 4000.0)
        tg = self._raw(self._get_zctrl("treble_gain"), 1.0)

        c.create_text(ex1 + 10, vy1 + 13,
                      text=f"Tone EQ · B {fmt_gain_db(bg)} · T {fmt_gain_db(tg)}",
                      anchor="w", fill=COL_TEXT,
                      font=self._fit_font(f"Tone EQ · B {fmt_gain_db(bg)} · T {fmt_gain_db(tg)}", (x2 - ex1) - 18, 10, bold=True))

        epx1, epy1 = ex1 + 10, vy1 + 26
        epx2, epy2 = x2 - 10, vy2 - 18
        ew = max(40, epx2 - epx1)
        eh = max(30, epy2 - epy1)
        emid = 0.5 * (epy1 + epy2)
        c.create_line(epx1, emid, epx2, emid, fill="#383b4d")

        eq_pts = []
        for i in range(41):
            frac = i / 40.0
            hz = 20.0 * (1000.0 ** frac)
            db = eval_tone_eq_db(hz, bf, bg, tf, tg)
            ey = epy2 - ((db + 24.0) / 48.0) * eh
            eq_pts.extend([epx1 + frac * ew, ey])
        if len(eq_pts) >= 4:
            c.create_line(*eq_pts, fill="#ffd43b", width=2.2, smooth=True)

        # Dual Bass (left) & Treble (right) drag zones
        bx_n = epx1 + 0.25 * ew
        by_n = epy2 - self._norm(self._get_zctrl("bass_gain"), "bass_gain", 0.5) * eh
        tx_n = epx1 + 0.75 * ew
        ty_n = epy2 - self._norm(self._get_zctrl("treble_gain"), "treble_gain", 0.5) * eh
        c.create_oval(bx_n - 8, by_n - 8, bx_n + 8, by_n + 8, fill="#ff922b", outline="#ffffff", width=2)
        c.create_oval(tx_n - 8, ty_n - 8, tx_n + 8, ty_n + 8, fill="#4dabf7", outline="#ffffff", width=2)
        c.create_text(epx1, vy2 - 9, text="Bass", anchor="w", fill="#ff922b", font=self._font(8, bold=True))
        c.create_text(epx2, vy2 - 9, text="Treble", anchor="e", fill="#4dabf7", font=self._font(8, bold=True))
        self.hitboxes.append((epx1, epy1, epx2, epy2, "eq_2d", (epx1, epy1, epx2, epy2)))

    # --------------------------------------------------------------------------
    # Touch Interaction (Drag + Double-Tap Reset)
    # --------------------------------------------------------------------------
    def _hit(self, x, y):
        for x1, y1, x2, y2, tag, data in self.hitboxes:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return tag, data
        return None, None

    def _on_press(self, event):
        tag, data = self._hit(event.x, event.y)
        if tag is None:
            return
        now = time.monotonic()

        if tag == "tab":
            if data != self.active_tab:
                self.active_tab = data
                self._select_page(data)
                self.last_snapshot = None
                self._draw()
            return

        if tag == "eco":
            self._toggle_eco()
            return

        if tag == "db_bank":
            self.db_bank = int(data)
            self._live_swap("Drawbars")
            self.last_snapshot = None
            self._draw()
            return

        if tag == "reg_preset":
            for i, v in enumerate(data):
                z = self._get_zctrl(f"l{i + 1}")
                if z is not None:
                    z.set_value(float(v), send=True)
            self.last_snapshot = None
            self._draw()
            return

        if tag == "harm_sel":
            self.harm_idx = int(data)
            self._live_swap("Harmonic")
            self.last_snapshot = None
            self._draw()
            return

        if tag == "wave_step":
            sym, delta = data
            z = self._get_zctrl(sym)
            if z is not None:
                v = int(round(self._raw(z, 0.0)))
                nv = (v + delta) % len(WAVEFORMS)
                z.set_value(float(nv), send=True)
                self.last_snapshot = None
                self._draw()
            return

        if tag == "perc_bank":
            self.perc_bank = int(data)
            self._live_swap("Perc")
            self.last_snapshot = None
            self._draw()
            return

        if tag == "flt_sel":
            self.flt_idx = int(data)
            self._live_swap("Filter")
            self.last_snapshot = None
            self._draw()
            return

        if tag == "flt_bank":
            self.flt_bank = int(data)
            self._live_swap("Filter")
            self.last_snapshot = None
            self._draw()
            return

        if tag == "env_sel":
            self.env_idx = int(data)
            self._live_swap("Env")
            self.last_snapshot = None
            self._draw()
            return

        if tag == "vib_bank":
            self.vib_bank = int(data)
            self._live_swap("Vib/EQ")
            self.last_snapshot = None
            self._draw()
            return

        if tag == "toggle":
            z = self._get_zctrl(data)
            if z is not None:
                z.set_value(0.0 if self._raw(z, 0.0) >= 0.5 else 1.0, send=True)
                self.last_snapshot = None
                self._draw()
            return

        if tag == "set_int":
            sym, val = data
            z = self._get_zctrl(sym)
            if z is not None:
                z.set_value(float(val), send=True)
                self.last_snapshot = None
                self._draw()
            return

        if tag == "cycle_int":
            sym, count = data
            z = self._get_zctrl(sym)
            if z is not None:
                nv = (int(round(self._raw(z, 0.0))) + 1) % int(count)
                z.set_value(float(nv), send=True)
                self.last_snapshot = None
                self._draw()
            return

        # Double-tap reset check
        tap_id = (tag, data[0] if isinstance(data, tuple) else data)
        if self.last_tap[0] == tap_id and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
            self.last_tap = (None, 0.0)
            self.drag_target = None
            if tag in ("param", "drawbar"):
                self._reset_zctrl(self._get_zctrl(data[0]), data[0])
            elif tag == "harm_2d":
                n = data[0]
                self._reset_zctrl(self._get_zctrl(f"pan{n}"), f"pan{n}")
                self._reset_zctrl(self._get_zctrl(f"detune{n}"), f"detune{n}")
            elif tag == "perc_2d":
                if self.perc_bank == 0:
                    self._reset_zctrl(self._get_zctrl("perc_decay"), "perc_decay")
                    self._reset_zctrl(self._get_zctrl("perc_level"), "perc_level")
                else:
                    self._reset_zctrl(self._get_zctrl("perc_fm_decay"), "perc_fm_decay")
                    self._reset_zctrl(self._get_zctrl("perc_fm_depth"), "perc_fm_depth")
            elif tag == "flt_2d":
                fn = data[0]
                self._reset_zctrl(self._get_zctrl(f"{fn}_cutoff"), f"{fn}_cutoff")
                self._reset_zctrl(self._get_zctrl(f"{fn}_res"), f"{fn}_res")
            elif tag == "env_a":
                self._reset_zctrl(self._get_zctrl(f"{data[0]}_a"), f"{data[0]}_a")
            elif tag == "env_ds":
                self._reset_zctrl(self._get_zctrl(f"{data[0]}_d"), f"{data[0]}_d")
                self._reset_zctrl(self._get_zctrl(f"{data[0]}_s"), f"{data[0]}_s")
            elif tag == "env_r":
                self._reset_zctrl(self._get_zctrl(f"{data[0]}_r"), f"{data[0]}_r")
            elif tag == "vib_2d":
                self._reset_zctrl(self._get_zctrl("vib_rate"), "vib_rate")
                self._reset_zctrl(self._get_zctrl("vib_wet"), "vib_wet")
            elif tag == "eq_2d":
                self._reset_zctrl(self._get_zctrl("bass_gain"), "bass_gain")
                self._reset_zctrl(self._get_zctrl("treble_gain"), "treble_gain")
            self.last_snapshot = None
            self._draw()
            return

        self.last_tap = (tap_id, now)
        self.drag_target = (tag, data)
        self._apply_drag(event.x, event.y)

    def _on_drag(self, event):
        if self.drag_target is None:
            return
        self._apply_drag(event.x, event.y)

    def _on_release(self, _event):
        self.drag_target = None

    def _apply_drag(self, x, y):
        tag, data = self.drag_target
        if tag == "param":
            key, x1, x2 = data
            n = (x - x1) / max(1.0, float(x2 - x1))
            self._set_norm(self._get_zctrl(key), n, key)
        elif tag == "drawbar":
            sym, y_top, y_bot = data
            # Authentic pull-down Hammond drawbar: 0 at top, 8 at bottom
            n = max(0.0, min(1.0, (y - y_top) / max(1.0, float(y_bot - y_top))))
            z = self._get_zctrl(sym)
            if z is not None:
                # Quantize softly to 0.5 or smooth 0..8 (step 0.5 feels authentic & smooth)
                v = round(n * 16.0) / 2.0
                z.set_value(max(float(z.value_min), min(float(z.value_max), v)), send=True)
        elif tag == "harm_2d":
            n, x1, y1, x2, y2 = data
            nx = max(0.0, min(1.0, (x - x1) / max(1.0, float(x2 - x1))))
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            self._set_norm(self._get_zctrl(f"pan{n}"), nx, f"pan{n}")
            self._set_norm(self._get_zctrl(f"detune{n}"), ny, f"detune{n}")
        elif tag == "perc_2d":
            x1, y1, x2, y2 = data
            nx = max(0.0, min(1.0, (x - x1) / max(1.0, float(x2 - x1))))
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            if self.perc_bank == 0:
                self._set_norm(self._get_zctrl("perc_decay"), nx, "perc_decay")
                self._set_norm(self._get_zctrl("perc_level"), ny, "perc_level")
            else:
                self._set_norm(self._get_zctrl("perc_fm_decay"), nx, "perc_fm_decay")
                self._set_norm(self._get_zctrl("perc_fm_depth"), ny, "perc_fm_depth")
        elif tag == "flt_2d":
            fn, x1, y1, x2, y2 = data
            nx = max(0.0, min(1.0, (x - x1) / max(1.0, float(x2 - x1))))
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            self._set_norm(self._get_zctrl(f"{fn}_cutoff"), nx, f"{fn}_cutoff")
            self._set_norm(self._get_zctrl(f"{fn}_res"), ny, f"{fn}_res")
        elif tag == "env_a":
            p, x1, y1, x2, y2 = data
            na = max(0.0, min(1.0, ((x - x1) / max(1.0, float(x2 - x1)) - 0.04) / 0.26))
            self._set_norm(self._get_zctrl(f"{p}_a"), na, f"{p}_a")
        elif tag == "env_ds":
            p, x1, y1, x2, y2 = data
            an = self._norm(self._get_zctrl(f"{p}_a"), f"{p}_a", 0.05)
            ax = x1 + (0.04 + 0.26 * an) * (x2 - x1)
            nd = max(0.0, min(1.0, ((x - ax) / max(1.0, float(x2 - x1)) - 0.05) / 0.25))
            ns = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            self._set_norm(self._get_zctrl(f"{p}_d"), nd, f"{p}_d")
            self._set_norm(self._get_zctrl(f"{p}_s"), ns, f"{p}_s")
        elif tag == "env_r":
            p, x1, y1, x2, y2 = data
            an = self._norm(self._get_zctrl(f"{p}_a"), f"{p}_a", 0.05)
            dn = self._norm(self._get_zctrl(f"{p}_d"), f"{p}_d", 0.35)
            sx_end = x1 + (0.04 + 0.26 * an + 0.05 + 0.25 * dn + 0.16) * (x2 - x1)
            nr = max(0.0, min(1.0, ((x - sx_end) / max(1.0, float(x2 - x1)) - 0.04) / 0.24))
            self._set_norm(self._get_zctrl(f"{p}_r"), nr, f"{p}_r")
        elif tag == "vib_2d":
            x1, y1, x2, y2 = data
            nx = max(0.0, min(1.0, (x - x1) / max(1.0, float(x2 - x1))))
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            self._set_norm(self._get_zctrl("vib_rate"), nx, "vib_rate")
            self._set_norm(self._get_zctrl("vib_wet"), ny, "vib_wet")
        elif tag == "eq_2d":
            x1, y1, x2, y2 = data
            ny = max(0.0, min(1.0, (y2 - y) / max(1.0, float(y2 - y1))))
            if x < 0.5 * (x1 + x2):
                self._set_norm(self._get_zctrl("bass_gain"), ny, "bass_gain")
            else:
                self._set_norm(self._get_zctrl("treble_gain"), ny, "treble_gain")

        self.last_snapshot = None
        self._draw()
