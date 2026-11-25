#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Monique Monosynth Workstation Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces Monique's ~300+ raw LV2 controller pages with 20 organized Zynthian
# encoder pages mapped 1-to-1 to 6 interactive touchscreen tabs:
#   Morph   -> Morph 1-4 | Morph MFO | Global
#   Osc/FM  -> OSC 1 | OSC 2 | OSC 3 | FM Engine
#   Filter  -> Filter Core | Filter Mod | Filter Mix | Filters 1-3
#   Env/LFO -> Amp ENV | Filter ENV | Filter LFO
#   Arp/Seq -> Arp Global | Arp Steps
#   EQ/FX   -> EQ & Dist | Chorus/Dly | Reverb | Loop/Mstr
#
# Features:
# - Two-way sync between Zynthian's encoder pages and the touchscreen UI:
#   scrolling pages with the Select encoder switches tabs/sub-banks on screen,
#   and tapping tabs/oscillators/filters/banks switches the active encoder page.
# - Large, finger-friendly touchscreen buttons (34-44px height) throughout.
# - Authentic Monique DSP scales & labels (35Hz-22kHz exp cutoff, 1ms-5s exp
#   envelope times, Sine->Saw->Square->Noise continuous wave morph, 16/1..1/64
#   LFO/MFO sync divisions, 7 Monique filter types, +-36st osc tuning).
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
UPDATE_PERIOD = 0.06  # ~16 fps cap to keep CPU low on Pi 5
DOUBLE_TAP_S = 0.35

# ------------------------------------------------------------------------------
# Theme Palette (matches Zynthian dark UI & UI Synths suite)
# ------------------------------------------------------------------------------
COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

TABS = ["Morph", "Osc/FM", "Filter", "Env/LFO", "Arp/Seq", "EQ/FX"]
TAB_ACCENTS = {
    "Morph":   "#4dabf7",  # blue
    "Osc/FM":  "#cc5de8",  # violet
    "Filter":  "#ff922b",  # orange
    "Env/LFO": "#51cf66",  # green
    "Arp/Seq": "#ffd43b",  # yellow
    "EQ/FX":   "#ff6b6b",  # coral
}
FILTER_COLS = ("#ff922b", "#38d9a9", "#4dabf7")

# Ordered list of all 20 Zynthian encoder pages & their owning widget tab
ENCODER_PAGES = [
    ("Morph 1-4",   "Morph"),
    ("Morph MFO",   "Morph"),
    ("Global",      "Morph"),
    ("OSC 1",       "Osc/FM"),
    ("OSC 2",       "Osc/FM"),
    ("OSC 3",       "Osc/FM"),
    ("FM Engine",   "Osc/FM"),
    ("Filter Core", "Filter"),
    ("Filter Mod",  "Filter"),
    ("Filter Mix",  "Filter"),
    ("Filters 1-3", "Filter"),
    ("Amp ENV",     "Env/LFO"),
    ("Filter ENV",  "Env/LFO"),
    ("Filter LFO",  "Env/LFO"),
    ("Arp Global",  "Arp/Seq"),
    ("Arp Steps",   "Arp/Seq"),
    ("EQ & Dist",   "EQ/FX"),
    ("Chorus/Dly",  "EQ/FX"),
    ("Reverb",      "EQ/FX"),
    ("Loop/Mstr",   "EQ/FX"),
]
PAGE_TO_TAB = dict(ENCODER_PAGES)

# ------------------------------------------------------------------------------
# Authentic Monique Enum Tables & Mathematical Scales
# ------------------------------------------------------------------------------
FILTER_TYPES = [
    "LP 24dB",   # 1: LPF_2_PASS
    "HP 12dB",   # 2: HPF
    "Bandpass",  # 3: BPF
    "HP 24dB",   # 4: HIGH_2_PASS
    "Bypass",    # 5: PASS
    "LP 12dB",   # 6: LPF
    "Moog LP",   # 7: MOOG_AND_LPF
]
FILTER_SHORT = ["LP24", "HP12", "BP", "HP24", "Pass", "LP12", "Moog"]

LFO_SPEEDS = [
    "16/1", "12/1", "8/1", "4/1", "3/1", "2/1", "1/1",
    "3/4", "1/2", "1/3", "1/4", "1/8", "1/12", "1/16", "1/24", "1/32", "1/64",
]

OCTAVES = ["-2 oct", "-1 oct", "0 oct", "+1 oct", "+2 oct"]
TOGGLE_OFF_ON = ["Off", "On"]
MORPH_GROUPS = [
    ("m_osc", "OSC", "M_OSC", "#cc5de8"),
    ("m_flt", "FLT", "M_FLT", "#ff922b"),
    ("m_arp", "ARP", "M_ARP", "#ffd43b"),
    ("m_fx",  "FX",  "M_FX",  "#ff6b6b"),
]
EQ_BAND_LABELS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7"]
LOOP_SIZES = ["1/2", "1/1", "2/1"]


def monique_cutoff_hz(n):
    """Monique authentic cutoff curve: ((exp(4n) - 1) / 53.5982) * 21965 + 35 Hz."""
    n = max(0.0, min(1.0, float(n)))
    return ((math.exp(n * 4.0) - 1.0) / 53.5982) * 21965.0 + 35.0


def hz_to_monique_norm(hz):
    hz = max(35.0, min(22000.0, float(hz)))
    r = (hz - 35.0) / 21965.0
    return max(0.0, min(1.0, math.log(r * 53.5982 + 1.0) / 4.0))


def fmt_hz(hz):
    if hz >= 10000.0:
        return f"{hz / 1000.0:.1f}kHz"
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}kHz"
    if hz >= 100.0:
        return f"{hz:.0f}Hz"
    return f"{hz:.1f}Hz"


def monique_env_ms(n):
    """Monique authentic envelope time curve: ((exp(4n) - 1) / 53.5982) * 4999 + 1 ms."""
    n = max(0.0, min(1.0, float(n)))
    return ((math.exp(n * 4.0) - 1.0) / 53.5982) * 4999.0 + 1.0


def fmt_ms(ms):
    if ms < 1000.0:
        return f"{ms:.0f}ms"
    return f"{ms / 1000.0:.2f}s"


def fmt_osc_wave(n):
    """Monique continuous wave morph: 0=Sine, 0.333=Saw, 0.667=Square, 1.0=Noise."""
    v = max(0.0, min(1.0, float(n))) * 3.0
    if v < 0.15:
        return "Sine"
    if v < 0.85:
        return f"Sin>{int(round(v * 100))}%"
    if v < 1.15:
        return "Saw"
    if v < 1.85:
        return f"Saw>{int(round((v - 1.0) * 100))}%"
    if v < 2.15:
        return "Square"
    if v < 2.85:
        return f"Sqr>{int(round((v - 2.0) * 100))}%"
    return "Noise"


def _build_scale(n_steps, fmt_fn):
    ticks = [i / (n_steps - 1) for i in range(n_steps)]
    labels = tuple(fmt_fn(t) for t in ticks)
    return labels, ticks


def _enum_scale(names):
    n = len(names)
    if n <= 1:
        return list(names), [0.0]
    return list(names), [i / (n - 1) for i in range(n)]


SCALE_PERCENT = _build_scale(101, lambda t: f"{int(round(t * 100))}%")
SCALE_BIPOLAR = _build_scale(101, lambda t: f"{int(round((t * 2.0 - 1.0) * 100)):+d}%")
SCALE_PAN = _build_scale(
    101,
    lambda t: "Center" if abs(t - 0.5) < 0.005 else (
        f"{int(round((0.5 - t) * 200))}L" if t < 0.5 else f"{int(round((t - 0.5) * 200))}R"
    ),
)
SCALE_MODMIX = _build_scale(
    101,
    lambda t: "50/50" if abs(t - 0.5) < 0.005 else (
        f"ENV {int(round((0.5 - t) * 200))}%" if t < 0.5 else f"LFO {int(round((t - 0.5) * 200))}%"
    ),
)
SCALE_CUTOFF = _build_scale(127, lambda t: fmt_hz(monique_cutoff_hz(t)))
SCALE_ENVTIME = _build_scale(101, lambda t: fmt_ms(monique_env_ms(t)))
SCALE_WAVE = _build_scale(101, fmt_osc_wave)
SCALE_PHASE = _build_scale(73, lambda t: f"{int(round(t * 360))}°")
SCALE_TUNE_36 = _build_scale(145, lambda t: f"{(t * 2.0 - 1.0) * 36.0:+.1f}st")
SCALE_ARP_TUNE = _build_scale(97, lambda t: f"{int(round((t * 2.0 - 1.0) * 48)):+d}st")
SCALE_BPM = _build_scale(121, lambda t: f"{int(round(20 + t * 980))}bpm")
SCALE_SHUFFLE = _build_scale(16, lambda t: f"{int(round(t * 15))}")
SCALE_STEPOFF = _build_scale(16, lambda t: f"Stp {int(round(t * 15)) + 1}")
SCALE_SPEEDMUL = _build_scale(31, lambda t: f"{int(round((t * 2.0 - 1.0) * 15)):+d}")
SCALE_FINEOFF = _build_scale(11, lambda t: f"{int(round((t * 2.0 - 1.0) * 5)):+d}")
SCALE_DELAY_REF = _build_scale(20, lambda t: f"{int(round(t * 19)) + 1}/16")


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


# Map logical widget keys -> exact Monique parameter short_name (from monique_core_Processor.cpp)
PARAM_NAMES = {
    # Oscillators & FM
    "osc1_keysync":   "OSC1 KeySync",
    "osc1_wave":      "OSC1 Wave",
    "osc1_fm_mass":   "OSC1 FM Mass",
    "osc1_phase":     "OSC1 Phase",
    "osc1_phase_mod": "OSC1 Phase_MOD",
    "osc1_lfo_mod":   "OSC1 PhaseMod",
    "osc2_sync":      "OSC2 Sync",
    "osc2_wave":      "OSC2 Wave",
    "osc2_fm_mass":   "OSC2 FM Mass",
    "osc2_tune":      "OSC2 Tune",
    "osc2_tune_mod":  "OSC2 Tune_MOD",
    "osc2_lfo_mod":   "OSC2 TuneMod",
    "osc3_sync":      "OSC3 Sync",
    "osc3_wave":      "OSC3 Wave",
    "osc3_fm_mass":   "OSC3 FM Mass",
    "osc3_tune":      "OSC3 Tune",
    "osc3_tune_mod":  "OSC3 Tune_MOD",
    "osc3_lfo_mod":   "OSC3 TuneMod",
    "fm_tune":        "FM Tune",
    "fm_sync":        "FM Sync",
    "fm_swing":       "FM Swing",
    "fm_shape":       "FM Shape",

    # Amp Envelope
    "amp_att":        "AMP_ENV Att",
    "amp_dec":        "AMP_ENV Dec",
    "amp_sus":        "AMP_ENV Sus",
    "amp_retrig":     "AMP_ENV Retrig",
    "amp_rel":        "AMP_ENV Rel",
    "amp_slope":      "AMP_ENV Slope",

    # Morph Groups (OSC, FLT, ARP, FX)
    "m_osc_state":    "M_OSC State *meta",
    "m_osc_toggle":   "M_OSC Toggle *meta",
    "m_osc_speed":    "M_OSC Speed",
    "m_osc_wave":     "M_OSC Wave",
    "m_osc_phase":    "M_OSC Phase",
    "m_osc_active":   "M_OSC Active *meta",

    "m_flt_state":    "M_FLT State *meta",
    "m_flt_toggle":   "M_FLT Toggle *meta",
    "m_flt_speed":    "M_FLT Speed",
    "m_flt_wave":     "M_FLT Wave",
    "m_flt_phase":    "M_FLT Phase",
    "m_flt_active":   "M_FLT Active *meta",

    "m_arp_state":    "M_ARP State *meta",
    "m_arp_toggle":   "M_ARP Toggle *meta",
    "m_arp_speed":    "M_ARP Speed",
    "m_arp_wave":     "M_ARP Wave",
    "m_arp_phase":    "M_ARP Phase",
    "m_arp_active":   "M_ARP Active *meta",

    "m_fx_state":     "M_FX State *meta",
    "m_fx_toggle":    "M_FX Toggle *meta",
    "m_fx_speed":     "M_FX Speed",
    "m_fx_wave":      "M_FX Wave",
    "m_fx_phase":     "M_FX Phase",
    "m_fx_active":    "M_FX Active *meta",

    # EQ & FX & Global
    "eq_mix":         "EQ All Mix",
    "eq_reso":        "EQ All Reso",
    "fx_dist":        "FX Dist",
    "fx_chorus":      "FX Chorus",
    "fx_chorus_pan":  "FX ChorusPan",
    "fx_delay_fb":    "FX DelayFBack",
    "fx_delay_ref":   "FX DelayReflex",
    "fx_delay_pan":   "FX DelayPan",
    "fx_loop_rec":    "FX LoopRecord",
    "fx_loop_rel":    "FX LoopRel",
    "fx_loop_size":   "FX LoopSize",
    "fx_verb_room":   "FX ReverbRoom",
    "fx_verb_width":  "FX ReverbWidth",
    "fx_verb_wet":    "FX ReverbWet",
    "fx_verb_pan":    "FX ReverbPan",
    "fx_mix":         "FX All Mix",
    "master_vol":     "MASTER Volume",

    # Arp & Global
    "arp_on":         "ARP Active",
    "arp_shuffle":    "ARP Shuffle",
    "arp_connect":    "ARP StepBind",
    "arp_step_off":   "ARP StepOffset",
    "arp_fine_off":   "ARP FineOffset",
    "arp_speed_mul":  "ARP SpeedMulti",
    "glob_glide":     "GLOB NoteGlide",
    "glob_vglide":    "GLOB VeloGlide",
    "glob_sync":      "GLOB SpeedSync",
    "glob_bpm":       "GLOB SpeedBPM",
    "glob_oct":       "GLOB OctaveOff",
    "glob_note":      "GLOB ProgNote",
}

for _fi in (1, 2, 3):
    PARAM_NAMES[f"f{_fi}_type"]       = f"F{_fi} FilterType"
    PARAM_NAMES[f"f{_fi}_cutoff"]     = f"F{_fi} Cutoff"
    PARAM_NAMES[f"f{_fi}_cutoff_mod"] = f"F{_fi} Cutoff_MOD"
    PARAM_NAMES[f"f{_fi}_cutoff_on"]  = f"F{_fi} CutoffMod"
    PARAM_NAMES[f"f{_fi}_reso"]       = f"F{_fi} Reso"
    PARAM_NAMES[f"f{_fi}_reso_mod"]   = f"F{_fi} Reso_MOD"
    PARAM_NAMES[f"f{_fi}_reso_on"]    = f"F{_fi} ResoMod"
    PARAM_NAMES[f"f{_fi}_dist"]       = f"F{_fi} Dist"
    PARAM_NAMES[f"f{_fi}_dist_mod"]   = f"F{_fi} Dist_MOD"
    PARAM_NAMES[f"f{_fi}_dist_on"]    = f"F{_fi} DistMod"
    PARAM_NAMES[f"f{_fi}_pan"]        = f"F{_fi} Pan"
    PARAM_NAMES[f"f{_fi}_pan_mod"]    = f"F{_fi} Pan_MOD"
    PARAM_NAMES[f"f{_fi}_pan_on"]     = f"F{_fi} PanMod"
    PARAM_NAMES[f"f{_fi}_vol"]        = f"F{_fi} Volume"
    PARAM_NAMES[f"f{_fi}_vol_mod"]    = f"F{_fi} Volume_MOD"
    PARAM_NAMES[f"f{_fi}_vol_on"]     = f"F{_fi} VolumeMod"
    PARAM_NAMES[f"f{_fi}_modmix"]     = f"F{_fi} ModMix"
    PARAM_NAMES[f"f{_fi}_env_att"]    = f"F{_fi} ENV Att"
    PARAM_NAMES[f"f{_fi}_env_dec"]    = f"F{_fi} ENV Dec"
    PARAM_NAMES[f"f{_fi}_env_sus"]    = f"F{_fi} ENV Sus"
    PARAM_NAMES[f"f{_fi}_env_retrig"] = f"F{_fi} ENV Retrig"
    PARAM_NAMES[f"f{_fi}_env_rel"]    = f"F{_fi} ENV Rel"
    PARAM_NAMES[f"f{_fi}_env_slope"]  = f"F{_fi} ENV Slope"
    PARAM_NAMES[f"lfo{_fi}_speed"]    = f"LFO{_fi} Speed"
    PARAM_NAMES[f"lfo{_fi}_wave"]     = f"LFO{_fi} Wave"
    PARAM_NAMES[f"lfo{_fi}_phase"]    = f"LFO{_fi} Phase"
    for _oi in (1, 2, 3):
        PARAM_NAMES[f"f{_fi}_osc{_oi}_in"] = f"F{_fi} OSC{_oi} Input"

for _bi in range(1, 8):
    PARAM_NAMES[f"eq{_bi}_gain"] = f"EQ{_bi} Gain"
    PARAM_NAMES[f"eq{_bi}_env_on"] = f"EQ{_bi} ENV Active"

_ARP_BAR_SUFFIX = {1: " B1", 5: " B2", 9: " B3", 13: " B4"}
for _si in range(1, 17):
    PARAM_NAMES[f"arp_step_{_si}"] = f"ARP Step{_si}{_ARP_BAR_SUFFIX.get(_si, '')}"
    PARAM_NAMES[f"arp_tune_{_si}"] = f"ARP Tune{_si}"
    PARAM_NAMES[f"arp_velo_{_si}"] = f"ARP Velo{_si}"


# ------------------------------------------------------------------------------
# Main Widget Class
# ------------------------------------------------------------------------------
class zynthian_widget_monique(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)

        self.next_update = 0.0
        self.active_tab = "Morph"

        # Per-tab sub-selection state (synced 2-way with Zynthian's 20 encoder pages)
        self.morph_idx = 0           # 0: OSC, 1: FLT, 2: ARP, 3: FX
        self.morph_bank = 0          # 0: Morph 1-4, 1: Morph MFO, 2: Global
        self.osc_idx = 0             # 0: OSC 1, 1: OSC 2, 2: OSC 3, 3: FM Engine
        self.flt_idx = 0             # 0: F1, 1: F2, 2: F3
        self.flt_bank = 0            # 0: Filter Core, 1: Filter Mod, 2: Filter Mix, 3: Filters 1-3
        self.env_idx = 0             # 0: Amp ENV, 1: F1 ENV, 2: F2 ENV, 3: F3 ENV
        self.env_bank = 0            # 0: Amp ENV / Filter ENV, 1: Filter LFO
        self.arp_bank = 0            # 0: Arp Global, 1: Step Tune (4), 2: Step Velo (4)
        self.arp_page = 0            # 0: 1-4, 1: 5-8, 2: 9-12, 3: 13-16
        self.fx_bank = 0             # 0: EQ & Dist, 1: Chorus/Dly, 2: Reverb, 3: Loop/Mstr

        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._enhanced_procs = set()
        self._bound_proc_id = None

        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}

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
    # Processor Setup, Resilient Lookup Index & zctrl Enhancement
    # --------------------------------------------------------------------------
    def set_processor(self, processor):
        super().set_processor(processor)
        if processor is None:
            return
        pid = id(processor)
        self._build_ctrl_index(processor)
        if pid not in self._enhanced_procs:
            self._enhanced_procs.add(pid)
            self._enhance_all_zctrls()
        if self._bound_proc_id != pid:
            self._bound_proc_id = pid
            self._rebuild_all_pages(select_page=self._active_page_title(), rebuild_list=True)

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
            k_sym = _norm_key(sym)
            if k_sym:
                idx[k_sym] = z
            zname = getattr(z, "name", None)
            if zname:
                k_name = _norm_key(zname)
                if k_name:
                    idx[k_name] = z
                    if k_name.endswith("_meta"):
                        idx[k_name[:-5]] = z
        self._ctrl_index = idx

    def _get_zctrl(self, logical_key):
        if not self.processor:
            return None
        target_name = PARAM_NAMES.get(logical_key, logical_key)
        k = _norm_key(target_name)
        z = self._ctrl_index.get(k)
        if z is not None:
            return z
        if k.endswith("_meta"):
            z = self._ctrl_index.get(k[:-5])
            if z is not None:
                return z
        return self._ctrl_index.get(_norm_key(logical_key))

    def _configure_zctrl_scale(self, z, labels, ticks):
        if z is None:
            return
        try:
            cur_val = float(z.value)
        except Exception:
            cur_val = 0.0
        z.labels = labels
        z.ticks = ticks
        z.is_toggle = (len(labels) == 2)
        z.is_integer = False
        z.value_min = 0.0
        z.value_max = 1.0
        z.value_range = 1.0
        z.value_mid = 0.5
        z.range_reversed = False
        z.label2value = {str(l): t for l, t in zip(labels, ticks)}
        z.value2label = {str(t): l for l, t in zip(labels, ticks)}
        z.value = max(0.0, min(1.0, cur_val))

    def _enhance_all_zctrls(self):
        def enh(key, scale_pair):
            z = self._get_zctrl(key)
            if z is not None:
                self._configure_zctrl_scale(z, scale_pair[0], scale_pair[1])

        enh("osc1_keysync", _enum_scale(TOGGLE_OFF_ON))
        enh("osc1_wave", SCALE_WAVE)
        enh("osc1_fm_mass", SCALE_PERCENT)
        enh("osc1_phase", SCALE_PHASE)
        enh("osc1_phase_mod", SCALE_BIPOLAR)
        enh("osc1_lfo_mod", _enum_scale(TOGGLE_OFF_ON))

        for oi in (2, 3):
            enh(f"osc{oi}_sync", _enum_scale(TOGGLE_OFF_ON))
            enh(f"osc{oi}_wave", SCALE_WAVE)
            enh(f"osc{oi}_fm_mass", SCALE_PERCENT)
            enh(f"osc{oi}_tune", SCALE_TUNE_36)
            enh(f"osc{oi}_tune_mod", SCALE_BIPOLAR)
            enh(f"osc{oi}_lfo_mod", _enum_scale(TOGGLE_OFF_ON))

        enh("fm_tune", SCALE_PERCENT)
        enh("fm_sync", _enum_scale(TOGGLE_OFF_ON))
        enh("fm_swing", SCALE_PERCENT)
        enh("fm_shape", SCALE_PERCENT)

        for fi in (1, 2, 3):
            enh(f"f{fi}_type", _enum_scale(FILTER_TYPES))
            enh(f"f{fi}_cutoff", SCALE_CUTOFF)
            enh(f"f{fi}_cutoff_mod", SCALE_BIPOLAR)
            enh(f"f{fi}_cutoff_on", _enum_scale(TOGGLE_OFF_ON))
            enh(f"f{fi}_reso", SCALE_PERCENT)
            enh(f"f{fi}_reso_mod", SCALE_BIPOLAR)
            enh(f"f{fi}_reso_on", _enum_scale(TOGGLE_OFF_ON))
            enh(f"f{fi}_dist", SCALE_PERCENT)
            enh(f"f{fi}_dist_mod", SCALE_BIPOLAR)
            enh(f"f{fi}_dist_on", _enum_scale(TOGGLE_OFF_ON))
            enh(f"f{fi}_pan", SCALE_PAN)
            enh(f"f{fi}_pan_mod", SCALE_BIPOLAR)
            enh(f"f{fi}_pan_on", _enum_scale(TOGGLE_OFF_ON))
            enh(f"f{fi}_vol", SCALE_PERCENT)
            enh(f"f{fi}_vol_mod", SCALE_BIPOLAR)
            enh(f"f{fi}_vol_on", _enum_scale(TOGGLE_OFF_ON))
            enh(f"f{fi}_modmix", SCALE_MODMIX)
            enh(f"f{fi}_env_att", SCALE_ENVTIME)
            enh(f"f{fi}_env_dec", SCALE_ENVTIME)
            enh(f"f{fi}_env_sus", SCALE_PERCENT)
            enh(f"f{fi}_env_retrig", SCALE_PERCENT)
            enh(f"f{fi}_env_rel", SCALE_ENVTIME)
            enh(f"f{fi}_env_slope", SCALE_BIPOLAR)
            enh(f"lfo{fi}_speed", _enum_scale(LFO_SPEEDS))
            enh(f"lfo{fi}_wave", SCALE_PERCENT)
            enh(f"lfo{fi}_phase", SCALE_PHASE)
            for oi in (1, 2, 3):
                enh(f"f{fi}_osc{oi}_in", SCALE_PERCENT if fi == 1 else SCALE_BIPOLAR)

        enh("amp_att", SCALE_ENVTIME)
        enh("amp_dec", SCALE_ENVTIME)
        enh("amp_sus", SCALE_PERCENT)
        enh("amp_retrig", SCALE_PERCENT)
        enh("amp_rel", SCALE_ENVTIME)
        enh("amp_slope", SCALE_BIPOLAR)

        for mk, _, _, _ in MORPH_GROUPS:
            enh(f"{mk}_state", SCALE_PERCENT)
            enh(f"{mk}_toggle", _enum_scale(["A", "B"]))
            enh(f"{mk}_speed", _enum_scale(LFO_SPEEDS))
            enh(f"{mk}_wave", SCALE_PERCENT)
            enh(f"{mk}_phase", SCALE_PHASE)
            enh(f"{mk}_active", _enum_scale(TOGGLE_OFF_ON))

        for bi in range(1, 8):
            enh(f"eq{bi}_gain", SCALE_PERCENT)
            enh(f"eq{bi}_env_on", _enum_scale(TOGGLE_OFF_ON))
        enh("eq_mix", SCALE_PERCENT)
        enh("eq_reso", SCALE_PERCENT)
        enh("fx_dist", SCALE_PERCENT)
        enh("fx_chorus", SCALE_PERCENT)
        enh("fx_chorus_pan", SCALE_PAN)
        enh("fx_delay_fb", SCALE_PERCENT)
        enh("fx_delay_ref", SCALE_DELAY_REF)
        enh("fx_delay_pan", SCALE_PAN)
        enh("fx_loop_rec", _enum_scale(TOGGLE_OFF_ON))
        enh("fx_loop_rel", SCALE_PERCENT)
        enh("fx_loop_size", _enum_scale(LOOP_SIZES))
        enh("fx_verb_room", SCALE_PERCENT)
        enh("fx_verb_width", SCALE_PERCENT)
        enh("fx_verb_wet", SCALE_PERCENT)
        enh("fx_verb_pan", SCALE_PAN)
        enh("fx_mix", SCALE_PERCENT)
        enh("master_vol", SCALE_PERCENT)

        enh("arp_on", _enum_scale(TOGGLE_OFF_ON))
        enh("arp_shuffle", SCALE_SHUFFLE)
        enh("arp_connect", _enum_scale(TOGGLE_OFF_ON))
        enh("arp_step_off", SCALE_STEPOFF)
        enh("arp_fine_off", SCALE_FINEOFF)
        enh("arp_speed_mul", SCALE_SPEEDMUL)
        enh("glob_glide", SCALE_PERCENT)
        enh("glob_vglide", SCALE_PERCENT)
        enh("glob_sync", _enum_scale(["Free", "Sync"]))
        enh("glob_bpm", SCALE_BPM)
        enh("glob_oct", _enum_scale(OCTAVES))
        for si in range(1, 17):
            enh(f"arp_step_{si}", _enum_scale(TOGGLE_OFF_ON))
            enh(f"arp_tune_{si}", SCALE_ARP_TUNE)
            enh(f"arp_velo_{si}", SCALE_PERCENT)

    # --------------------------------------------------------------------------
    # 20 Structured Zynthian Encoder Pages <-> Widget Tabs (2-Way Sync)
    # --------------------------------------------------------------------------
    def _page_items(self, page_title):
        """Return 4 (logical_key, short_label) pairs for any of the 20 encoder pages."""
        if page_title == "Morph 1-4":
            return [
                ("m_osc_state", "M:OSC"),
                ("m_flt_state", "M:FLT"),
                ("m_arp_state", "M:ARP"),
                ("m_fx_state",  "M:FX"),
            ]
        if page_title == "Morph MFO":
            mk, lbl, _, _ = MORPH_GROUPS[self.morph_idx]
            return [
                (f"{mk}_state",  f"{lbl} Mrph"),
                (f"{mk}_speed",  f"{lbl} Spd"),
                (f"{mk}_wave",   f"{lbl} Wave"),
                (f"{mk}_phase",  f"{lbl} Phs"),
            ]
        if page_title == "Global":
            return [
                ("master_vol", "Master"),
                ("glob_glide", "Glide"),
                ("glob_oct",   "Octave"),
                ("glob_bpm",   "BPM"),
            ]

        if page_title == "OSC 1":
            return [
                ("osc1_wave",    "O1 Wave"),
                ("osc1_phase",   "O1 Phase"),
                ("osc1_fm_mass", "O1 FM"),
                ("osc1_keysync", "O1 KSync"),
            ]
        if page_title == "OSC 2":
            return [
                ("osc2_wave",    "O2 Wave"),
                ("osc2_tune",    "O2 Tune"),
                ("osc2_fm_mass", "O2 FM"),
                ("osc2_sync",    "O2 Sync"),
            ]
        if page_title == "OSC 3":
            return [
                ("osc3_wave",    "O3 Wave"),
                ("osc3_tune",    "O3 Tune"),
                ("osc3_fm_mass", "O3 FM"),
                ("osc3_sync",    "O3 Sync"),
            ]
        if page_title == "FM Engine":
            return [
                ("fm_tune",  "FM Tune"),
                ("fm_swing", "FM Swing"),
                ("fm_shape", "FM Shape"),
                ("fm_sync",  "FM Sync"),
            ]

        fi = self.flt_idx + 1
        if page_title == "Filter Core":
            return [
                (f"f{fi}_cutoff", f"F{fi} Cut"),
                (f"f{fi}_reso",   f"F{fi} Reso"),
                (f"f{fi}_dist",   f"F{fi} Dist"),
                (f"f{fi}_vol",    f"F{fi} Vol"),
            ]
        if page_title == "Filter Mod":
            return [
                (f"f{fi}_cutoff_mod", f"F{fi} CutM"),
                (f"f{fi}_reso_mod",   f"F{fi} ResM"),
                (f"f{fi}_dist_mod",   f"F{fi} DstM"),
                (f"f{fi}_pan",        f"F{fi} Pan"),
            ]
        if page_title == "Filter Mix":
            return [
                (f"f{fi}_osc1_in", f"O1>F{fi}"),
                (f"f{fi}_osc2_in", f"O2>F{fi}"),
                (f"f{fi}_osc3_in", f"O3>F{fi}"),
                (f"f{fi}_type",    f"F{fi} Type"),
            ]
        if page_title == "Filters 1-3":
            return [
                ("f1_cutoff", "F1 Cut"),
                ("f2_cutoff", "F2 Cut"),
                ("f3_cutoff", "F3 Cut"),
                (f"f{fi}_reso", f"F{fi} Reso"),
            ]

        if page_title == "Amp ENV":
            return [
                ("amp_att", "Amp Att"),
                ("amp_dec", "Amp Dec"),
                ("amp_sus", "Amp Sus"),
                ("amp_rel", "Amp Rel"),
            ]
        if page_title == "Filter ENV":
            fe = max(1, self.env_idx)
            return [
                (f"f{fe}_env_att", f"F{fe} Att"),
                (f"f{fe}_env_dec", f"F{fe} Dec"),
                (f"f{fe}_env_sus", f"F{fe} Sus"),
                (f"f{fe}_env_rel", f"F{fe} Rel"),
            ]
        if page_title == "Filter LFO":
            li = max(1, self.env_idx)
            return [
                (f"lfo{li}_speed", f"LFO{li} Spd"),
                (f"lfo{li}_wave",  f"LFO{li} Wav"),
                (f"lfo{li}_phase", f"LFO{li} Phs"),
                (f"f{li}_modmix",  f"F{li} E/L"),
            ]

        if page_title == "Arp Global":
            return [
                ("arp_shuffle",   "Shuffle"),
                ("arp_step_off",  "Step Off"),
                ("arp_speed_mul", "Spd Mul"),
                ("arp_fine_off",  "Fine Off"),
            ]
        if page_title == "Arp Steps":
            base = self.arp_page * 4 + 1
            if self.arp_bank == 2:
                return [(f"arp_velo_{base + i}", f"S{base + i} Vel") for i in range(4)]
            return [(f"arp_tune_{base + i}", f"S{base + i} Tun") for i in range(4)]

        if page_title == "EQ & Dist":
            return [
                ("eq_mix",  "EQ Mix"),
                ("eq_reso", "EQ Reso"),
                ("fx_dist", "Distort"),
                ("fx_mix",  "FX Mix"),
            ]
        if page_title == "Chorus/Dly":
            return [
                ("fx_chorus",    "Chorus"),
                ("fx_delay_fb",  "Dly FB"),
                ("fx_delay_ref", "Dly Time"),
                ("fx_delay_pan", "Dly Pan"),
            ]
        if page_title == "Reverb":
            return [
                ("fx_verb_room",  "Verb Rm"),
                ("fx_verb_width", "Verb Wd"),
                ("fx_verb_wet",   "Verb Wet"),
                ("fx_verb_pan",   "Verb Pan"),
            ]
        # Loop/Mstr
        return [
            ("fx_loop_rec",  "Loop Rec"),
            ("fx_loop_size", "Loop Sz"),
            ("fx_loop_rel",  "Loop Rel"),
            ("master_vol",   "Master"),
        ]

    def _active_page_title(self):
        """Return the Zynthian encoder page title corresponding to current widget state."""
        t = self.active_tab
        if t == "Morph":
            return ("Morph 1-4", "Morph MFO", "Global")[self.morph_bank]
        if t == "Osc/FM":
            return ("OSC 1", "OSC 2", "OSC 3", "FM Engine")[self.osc_idx]
        if t == "Filter":
            return ("Filter Core", "Filter Mod", "Filter Mix", "Filters 1-3")[self.flt_bank]
        if t == "Env/LFO":
            if self.env_bank == 1:
                return "Filter LFO"
            return "Amp ENV" if self.env_idx == 0 else "Filter ENV"
        if t == "Arp/Seq":
            return "Arp Global" if self.arp_bank == 0 else "Arp Steps"
        return ("EQ & Dist", "Chorus/Dly", "Reverb", "Loop/Mstr")[self.fx_bank]

    def _apply_page_to_state(self, page_title):
        """Sync widget tab & sub-bank when user scrolls pages with Zynthian's Select encoder."""
        tab = PAGE_TO_TAB.get(page_title)
        if not tab:
            return
        self.active_tab = tab
        if page_title == "Morph 1-4":
            self.morph_bank = 0
        elif page_title == "Morph MFO":
            self.morph_bank = 1
        elif page_title == "Global":
            self.morph_bank = 2
        elif page_title == "OSC 1":
            self.osc_idx = 0
        elif page_title == "OSC 2":
            self.osc_idx = 1
        elif page_title == "OSC 3":
            self.osc_idx = 2
        elif page_title == "FM Engine":
            self.osc_idx = 3
        elif page_title == "Filter Core":
            self.flt_bank = 0
        elif page_title == "Filter Mod":
            self.flt_bank = 1
        elif page_title == "Filter Mix":
            self.flt_bank = 2
        elif page_title == "Filters 1-3":
            self.flt_bank = 3
        elif page_title == "Amp ENV":
            self.env_idx = 0
            self.env_bank = 0
        elif page_title == "Filter ENV":
            if self.env_idx == 0:
                self.env_idx = 1
            self.env_bank = 0
        elif page_title == "Filter LFO":
            if self.env_idx == 0:
                self.env_idx = 1
            self.env_bank = 1
        elif page_title == "Arp Global":
            self.arp_bank = 0
        elif page_title == "Arp Steps":
            if self.arp_bank == 0:
                self.arp_bank = 1
        elif page_title == "EQ & Dist":
            self.fx_bank = 0
        elif page_title == "Chorus/Dly":
            self.fx_bank = 1
        elif page_title == "Reverb":
            self.fx_bank = 2
        elif page_title == "Loop/Mstr":
            self.fx_bank = 3

    def _build_page_zctrls(self, page_title):
        zctrls = []
        for key, short_label in self._page_items(page_title):
            z = self._get_zctrl(key)
            if z is not None:
                z.short_name = short_label
                zctrls.append(z)
        return zctrls

    def _rebuild_all_pages(self, select_page=None, rebuild_list=False):
        if not self.processor:
            return
        new_screens = {}
        for ptitle, _ in ENCODER_PAGES:
            zlist = self._build_page_zctrls(ptitle)
            if zlist:
                new_screens[ptitle] = zlist
        if not new_screens:
            return
        self.processor.ctrl_screens_dict = new_screens
        target = select_page if select_page in new_screens else self._active_page_title()
        self.last_snapshot = None

        if rebuild_list:
            self.after(25, lambda p=target: self._sync_zyngui_list(p))
        else:
            self._live_swap_encoders(target)

    def _live_swap_encoders(self, page_title=None):
        if not self.processor:
            return
        if page_title is None:
            page_title = self._active_page_title()
        zlist = self._build_page_zctrls(page_title)
        self.processor.ctrl_screens_dict[page_title] = zlist
        try:
            if self.zyngui_control.get_current_processor() is self.processor:
                if self.last_screen_title != page_title:
                    self._select_page_by_title(page_title)
                else:
                    self.zyngui_control.zcontrollers = zlist
                    for i in range(4):
                        ctrl = zlist[i] if i < len(zlist) else None
                        self.zyngui_control.set_zcontroller(i, ctrl)
        except Exception as e:
            logging.debug(f"Monique widget: live swap error => {e}")

    def _sync_zyngui_list(self, target_page):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page_by_title(target_page)
            self._draw()
        except Exception as e:
            logging.debug(f"Monique widget: sync list error => {e}")

    def _select_page_by_title(self, title):
        try:
            for i, row in enumerate(self.zyngui_control.list_data):
                if len(row) >= 5 and row[2] == title and row[3] is self.processor:
                    self.zyngui_control.select(i)
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
                if title != self.last_screen_title and title in PAGE_TO_TAB:
                    self.last_screen_title = title
                    self._apply_page_to_state(title)
                    self.last_snapshot = None
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # Value Helpers
    # --------------------------------------------------------------------------
    @staticmethod
    def _norm(zctrl, default=0.0):
        if zctrl is None:
            return default
        try:
            v = float(zctrl.get_value())
            return max(0.0, min(1.0, v))
        except Exception:
            return default

    @staticmethod
    def _set_norm(zctrl, norm_val):
        if zctrl is None:
            return
        n = max(0.0, min(1.0, float(norm_val)))
        zctrl.set_value(n, send=True)

    @staticmethod
    def _cycle_enum(zctrl, step=1):
        if zctrl is None or not getattr(zctrl, "ticks", None):
            return
        idx = zctrl.get_value2index() or 0
        new_idx = (idx + step) % len(zctrl.ticks)
        zctrl.set_value(zctrl.ticks[new_idx], send=True)

    @staticmethod
    def _fmt(zctrl):
        if zctrl is None:
            return "--"
        try:
            if getattr(zctrl, "labels", None):
                return str(zctrl.get_value2label())
        except Exception:
            pass
        return f"{int(round(zynthian_widget_monique._norm(zctrl) * 100))}%"

    # --------------------------------------------------------------------------
    # Update Loop & Dirty Check
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
        t = self.active_tab
        if t == "Morph":
            keys = ["master_vol", "glob_glide", "glob_oct", "glob_bpm", "glob_sync", "fx_mix", "arp_on"]
            for mk, _, _, _ in MORPH_GROUPS:
                keys.extend([f"{mk}_state", f"{mk}_toggle", f"{mk}_speed", f"{mk}_wave", f"{mk}_phase", f"{mk}_active"])
            return keys
        if t == "Osc/FM":
            return [
                "osc1_keysync", "osc1_wave", "osc1_fm_mass", "osc1_phase", "osc1_lfo_mod",
                "osc2_sync", "osc2_wave", "osc2_fm_mass", "osc2_tune", "osc2_lfo_mod",
                "osc3_sync", "osc3_wave", "osc3_fm_mass", "osc3_tune", "osc3_lfo_mod",
                "fm_tune", "fm_sync", "fm_swing", "fm_shape",
            ]
        if t == "Filter":
            keys = []
            for fi in (1, 2, 3):
                keys.extend([
                    f"f{fi}_type", f"f{fi}_cutoff", f"f{fi}_cutoff_mod",
                    f"f{fi}_reso", f"f{fi}_reso_mod", f"f{fi}_dist", f"f{fi}_dist_mod",
                    f"f{fi}_pan", f"f{fi}_vol", f"f{fi}_osc1_in", f"f{fi}_osc2_in", f"f{fi}_osc3_in",
                ])
            return keys
        if t == "Env/LFO":
            keys = ["amp_att", "amp_dec", "amp_sus", "amp_rel", "amp_slope"]
            for fi in (1, 2, 3):
                keys.extend([
                    f"f{fi}_env_att", f"f{fi}_env_dec", f"f{fi}_env_sus", f"f{fi}_env_rel",
                    f"f{fi}_env_slope", f"f{fi}_modmix",
                    f"lfo{fi}_speed", f"lfo{fi}_wave", f"lfo{fi}_phase",
                ])
            return keys
        if t == "Arp/Seq":
            keys = ["arp_on", "arp_shuffle", "arp_connect", "arp_step_off", "arp_fine_off", "arp_speed_mul"]
            for si in range(1, 17):
                keys.extend([f"arp_step_{si}", f"arp_tune_{si}", f"arp_velo_{si}"])
            return keys
        # EQ/FX
        keys = [
            "eq_mix", "eq_reso", "fx_dist", "fx_chorus",
            "fx_delay_fb", "fx_delay_ref", "fx_delay_pan",
            "fx_loop_rec", "fx_loop_rel", "fx_loop_size",
            "fx_verb_room", "fx_verb_width", "fx_verb_wet", "fx_verb_pan",
            "fx_mix", "master_vol",
        ]
        for bi in range(1, 8):
            keys.append(f"eq{bi}_gain")
        return keys

    def _state_snapshot(self):
        vals = tuple(round(self._norm(self._get_zctrl(k)), 4) for k in self._watched_keys())
        return (
            self.width, self.height, self.active_tab,
            self.morph_idx, self.morph_bank, self.osc_idx,
            self.flt_idx, self.flt_bank, self.env_idx, self.env_bank,
            self.arp_bank, self.arp_page, self.fx_bank,
            vals,
        )

    def refresh_gui(self):
        if not self.processor or self.width < 40 or self.height < 40:
            return
        self._follow_page()
        snap = self._state_snapshot()
        if snap != self.last_snapshot:
            self.last_snapshot = snap
            self._draw()

    # --------------------------------------------------------------------------
    # Drawing Primitives (Large, Finger-Friendly Touch Controls)
    # --------------------------------------------------------------------------
    def _font(self, size, bold=False):
        key = (size, bold)
        if key not in self._font_cache:
            fam = zynthian_gui_config.font_family
            self._font_cache[key] = (fam, size, "bold") if bold else (fam, size)
        return self._font_cache[key]

    def _fs(self, scale=1.0):
        base = max(10, min(14, self.height // 30))
        return max(8, int(round(base * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, hit_kind, hit_payload, subtext=None):
        c = self.widget_canvas
        fill = accent if active else COL_PANEL
        fg = "#0d0e12" if active else COL_TEXT
        outline = accent if active else COL_BORDER
        c.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=2 if active else 1)
        if subtext:
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.28, text=text,
                          fill=COL_DIM if not active else "#1a1c22", font=self._font(self._fs(0.76)))
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.72, text=subtext,
                          fill=accent if not active else "#000000", font=self._font(self._fs(0.92), bold=True))
        else:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                          fill=fg, font=self._font(self._fs(0.94), bold=True))
        self.hitboxes.append((x0, y0, x1, y1, hit_kind, hit_payload))

    def _draw_bank_bar(self, x0, y0, x1, y1, banks, active_idx, accent, bank_kind):
        c = self.widget_canvas
        n = len(banks)
        gap = 6
        bw = (x1 - x0 - gap * (n - 1)) / n
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
                font=self._font(self._fs(0.88), bold=act),
            )
            self.hitboxes.append((bx0, y0, bx1, y1, bank_kind, i))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent, bank_kind=None, bank_idx=None, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        norm = self._norm(z)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 6
        tx0, tx1 = x0 + pad, x1 - pad
        bar_h = max(7, min(12, int((y1 - y0) * 0.30)))
        by1 = y1 - 4
        by0 = by1 - bar_h
        lbl_y = y0 + (by0 - y0) / 2

        c.create_text(tx0, lbl_y, text=label, anchor="w", fill=COL_DIM, font=self._font(self._fs(0.84)))
        c.create_text(tx1, lbl_y, text=self._fmt(z)[:10], anchor="e", fill=COL_TEXT,
                      font=self._font(self._fs(0.9), bold=True))

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
        norm = self._norm(z)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 5
        lbl_h = 18
        val_h = 16
        tx0, tx1 = x0 + pad, x1 - pad
        ty0 = y0 + lbl_h + 2
        ty1 = y1 - val_h - 3

        c.create_text((x0 + x1) / 2, y0 + lbl_h / 2 + 1, text=label,
                      fill=COL_TEXT, font=self._font(self._fs(0.86), bold=True))
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

        c.create_text((x0 + x1) / 2, y1 - val_h / 2 - 1, text=self._fmt(z)[:8],
                      fill=COL_DIM, font=self._font(self._fs(0.8)))

        self.hitboxes.append((
            x0, y0, x1, y1, "vfader",
            {"key": key, "ty0": ty0, "ty1": ty1, "bank_kind": bank_kind, "bank_idx": bank_idx},
        ))

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

        if self.active_tab == "Morph":
            self._draw_tab_morph(bx0, by0, bx1, by1)
        elif self.active_tab == "Osc/FM":
            self._draw_tab_osc(bx0, by0, bx1, by1)
        elif self.active_tab == "Filter":
            self._draw_tab_filter(bx0, by0, bx1, by1)
        elif self.active_tab == "Env/LFO":
            self._draw_tab_env_lfo(bx0, by0, bx1, by1)
        elif self.active_tab == "Arp/Seq":
            self._draw_tab_arp(bx0, by0, bx1, by1)
        elif self.active_tab == "EQ/FX":
            self._draw_tab_eq_fx(bx0, by0, bx1, by1)

    def _draw_header(self, x0, y0, x1, y1):
        c = self.widget_canvas
        total_w = x1 - x0
        arp_w = max(58, int(total_w * 0.11))
        gap = 6
        tabs_w = total_w - arp_w - gap * len(TABS)
        tw = tabs_w / len(TABS)

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
                font=self._font(self._fs(0.96), bold=True),
            )
            self.hitboxes.append((cx, y0, cx + tw, y1, "tab", tname))
            cx += tw + gap

        # Big ARP On/Off button in top-right corner
        ax0 = x1 - arp_w
        arp_on = self._norm(self._get_zctrl("arp_on")) >= 0.5
        arp_col = TAB_ACCENTS["Arp/Seq"]
        c.create_rectangle(
            ax0, y0, x1, y1,
            fill=arp_col if arp_on else COL_PANEL_HI,
            outline=arp_col if arp_on else COL_BORDER,
            width=2 if arp_on else 1,
        )
        c.create_text(
            (ax0 + x1) / 2, (y0 + y1) / 2,
            text="ARP ●" if arp_on else "ARP",
            fill="#0d0e12" if arp_on else COL_TEXT,
            font=self._font(self._fs(0.92), bold=True),
        )
        self.hitboxes.append((ax0, y0, x1, y1, "cycle", "arp_on"))

    # --------------------------------------------------------------------------
    # TAB 1: MORPH & GLOBAL (3 Encoder Pages: Morph 1-4 | Morph MFO | Global)
    # --------------------------------------------------------------------------
    def _draw_tab_morph(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Morph"]
        gap = 6

        # Row 1: Big Encoder Page Bar
        bh = 36
        mk_sel, lbl_sel, _, col_sel = MORPH_GROUPS[self.morph_idx]
        self._draw_bank_bar(
            x0, y0, x1, y0 + bh,
            ["Morph 1-4", f"MFO ({lbl_sel})", "Global"],
            self.morph_bank, accent, "morph_bank",
        )

        # Row 2: Big Quick Global Tiles (Octave, Sync, BPM, Master)
        ry2 = y0 + bh + 6
        tile_h = 38
        tiles = [
            ("Octave", "glob_oct",  "cycle"),
            ("Sync",   "glob_sync", "cycle"),
            ("BPM",    "glob_bpm",  "bank_glob"),
            ("Master", "master_vol","bank_glob"),
        ]
        tw = (x1 - x0 - gap * (len(tiles) - 1)) / len(tiles)
        for i, (lbl, key, hk) in enumerate(tiles):
            tx0 = x0 + i * (tw + gap)
            z = self._get_zctrl(key)
            self._draw_pill(tx0, ry2, tx0 + tw, ry2 + tile_h, lbl, False, accent,
                            hk, key, subtext=self._fmt(z)[:8])

        # Row 3: 4 Morph Columns (left 58%) + MFO/Global Controls (right 42%)
        my0 = ry2 + tile_h + 6
        left_w = int((x1 - x0) * 0.58)
        lx1 = x0 + left_w
        rx0 = lx1 + 6

        cw = (left_w - gap * 3) / 4
        btn_h = 34
        for i, (mk, lbl, _, col) in enumerate(MORPH_GROUPS):
            cx0 = x0 + i * (cw + gap)
            cx1 = cx0 + cw
            sel = (i == self.morph_idx)

            act_mfo = self._norm(self._get_zctrl(f"{mk}_active")) >= 0.5
            c.create_rectangle(cx0, my0, cx1, my0 + btn_h,
                               fill=col if sel else COL_PANEL_HI,
                               outline=col, width=2 if sel else 1)
            c.create_text((cx0 + cx1) / 2, my0 + btn_h / 2, text=lbl,
                          fill="#0d0e12" if sel else col,
                          font=self._font(self._fs(0.92), bold=True))
            self.hitboxes.append((cx0, my0, cx1, my0 + btn_h, "morph_idx", i))

            # Bottom MFO Auto + A/B Toggle buttons (big!)
            ab_y1 = y1
            ab_y0 = ab_y1 - btn_h
            mf_y1 = ab_y0 - 3
            mf_y0 = mf_y1 - btn_h

            c.create_rectangle(cx0, mf_y0, cx1, mf_y1,
                               fill=col if act_mfo else COL_PANEL,
                               outline=col if act_mfo else COL_BORDER, width=2 if act_mfo else 1)
            c.create_text((cx0 + cx1) / 2, (mf_y0 + mf_y1) / 2,
                          text="MFO ON" if act_mfo else "MFO",
                          fill="#0d0e12" if act_mfo else COL_TEXT,
                          font=self._font(self._fs(0.84), bold=True))
            self.hitboxes.append((cx0, mf_y0, cx1, mf_y1, "cycle", f"{mk}_active"))

            tog_b = self._norm(self._get_zctrl(f"{mk}_toggle")) >= 0.5
            c.create_rectangle(cx0, ab_y0, cx1, ab_y1,
                               fill=COL_PANEL_HI, outline=col if tog_b else COL_BORDER, width=1)
            c.create_text((cx0 + cx1) / 2, (ab_y0 + ab_y1) / 2,
                          text="SW: B" if tog_b else "SW: A",
                          fill=col if tog_b else COL_TEXT,
                          font=self._font(self._fs(0.84), bold=True))
            self.hitboxes.append((cx0, ab_y0, cx1, ab_y1, "cycle", f"{mk}_toggle"))

            self._draw_vfader(
                cx0, my0 + btn_h + 3, cx1, mf_y0 - 3,
                f"{mk}_state", f"M:{lbl}", col,
                bank_kind="morph_bank", bank_idx=0,
            )

        # Right Panel: Interactive 2D Quad Morph Pad (in Morph 1-4) OR MFO Scope (in MFO/Global)
        scope_h = int((y1 - my0) * 0.38)
        sy1 = my0 + scope_h
        if self.morph_bank == 0:
            c.create_rectangle(rx0, my0, x1, sy1, fill=COL_PANEL, outline=accent, width=1)
            px0, px1 = rx0 + 10, x1 - 10
            py_t, py_b = my0 + 18, sy1 - 10
            pw_q = max(16, px1 - px0)
            ph_q = max(16, py_b - py_t)
            c.create_text((rx0 + x1) / 2, my0 + 9, text="2D Quad Morph (OSC/FLT/ARP/FX)",
                          fill=accent, font=self._font(self._fs(0.76), bold=True))
            c.create_line(px0, (py_t + py_b) / 2, px1, (py_t + py_b) / 2, fill=COL_GRID, dash=(2, 3))
            c.create_line((px0 + px1) / 2, py_t, (px0 + px1) / 2, py_b, fill=COL_GRID, dash=(2, 3))

            # Corner labels: A=OSC (TL), B=FLT (TR), C=ARP (BL), D=FX (BR)
            m_vals = [self._norm(self._get_zctrl(f"{mk}_state"), 0.5) for mk, _, _, _ in MORPH_GROUPS]
            corners = [
                (px0 + 2, py_t + 6,  "w", "A:OSC", MORPH_GROUPS[0][3]),
                (px1 - 2, py_t + 6,  "e", "B:FLT", MORPH_GROUPS[1][3]),
                (px0 + 2, py_b - 6,  "w", "C:ARP", MORPH_GROUPS[2][3]),
                (px1 - 2, py_b - 6,  "e", "D:FX",  MORPH_GROUPS[3][3]),
            ]
            for cx_t, cy_t, anc, clbl, ccol in corners:
                c.create_text(cx_t, cy_t, text=clbl, anchor=anc, fill=ccol,
                              font=self._font(self._fs(0.68), bold=True))

            # Compute 2D puck centroid from 4 morph weights
            tot_m = max(1e-4, sum(m_vals))
            nx_p = max(0.0, min(1.0, (m_vals[1] + m_vals[3]) / tot_m))
            ny_p = max(0.0, min(1.0, (m_vals[0] + m_vals[1]) / tot_m))
            puck_x = px0 + nx_p * pw_q
            puck_y = py_b - ny_p * ph_q
            c.create_line(puck_x, py_t, puck_x, py_b, fill="#3b4259", dash=(2, 2))
            c.create_line(px0, puck_y, px1, puck_y, fill="#3b4259", dash=(2, 2))
            c.create_oval(puck_x - 9, puck_y - 9, puck_x + 9, puck_y + 9,
                          fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((rx0, my0, x1, sy1, "morph_quad",
                                  {"px0": px0, "px1": px1, "py0": py_t, "py1": py_b}))
        else:
            c.create_rectangle(rx0, my0, x1, sy1, fill=COL_PANEL, outline=col_sel, width=1)
            self._draw_lfo_scope(
                rx0, my0, x1, sy1,
                f"{mk_sel}_speed", f"{mk_sel}_wave", f"{mk_sel}_phase",
                f"MFO {lbl_sel}", col_sel,
            )

        py0 = sy1 + 5
        if self.morph_bank == 2:
            r_items = [
                ("master_vol", "Master Vol", False),
                ("glob_glide", "Note Glide", False),
                ("glob_oct",   "Octave Off", False),
                ("glob_bpm",   "Tempo BPM",  False),
            ]
            r_bidx = 2
            r_col = accent
        else:
            r_items = [
                (f"{mk_sel}_state", f"{lbl_sel} Morph", False),
                (f"{mk_sel}_speed", f"{lbl_sel} Speed", False),
                (f"{mk_sel}_wave",  f"{lbl_sel} Wave",  False),
                (f"{mk_sel}_phase", f"{lbl_sel} Phase", False),
            ]
            r_bidx = 1
            r_col = col_sel

        rh = (y1 - py0 - 3 * 4) / 4
        for i, (key, lbl, bip) in enumerate(r_items):
            ry0 = py0 + i * (rh + 4)
            self._draw_param_box(rx0, ry0, x1, ry0 + rh, key, lbl, r_col,
                                 bank_kind="morph_bank", bank_idx=r_bidx, bipolar=bip)

    # --------------------------------------------------------------------------
    # TAB 2: OSC / FM (4 Encoder Pages: OSC 1 | OSC 2 | OSC 3 | FM Engine)
    # --------------------------------------------------------------------------
    def _draw_tab_osc(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Osc/FM"]
        gap = 4

        # Row 1: Big 4-way selector = 4 Zynthian encoder pages!
        r1_h = 36
        ow = (x1 - x0 - 3 * gap) / 4
        for i, lbl in enumerate(("OSC 1", "OSC 2", "OSC 3", "FM ENGINE")):
            ox0 = x0 + i * (ow + gap)
            self._draw_pill(ox0, y0, ox0 + ow, y0 + r1_h, lbl,
                            i == self.osc_idx, accent, "osc_idx", i)

        # Row 2: Live Waveform Scope (left 56%) + Big 2x2 Wave Snap Buttons (right 44%)
        mid_y0 = y0 + r1_h + 5
        bot_h = 92
        mid_y1 = y1 - bot_h - 5

        scope_w = int((x1 - x0) * 0.56)
        sx1 = x0 + scope_w
        c.create_rectangle(x0, mid_y0, sx1, mid_y1, fill=COL_PANEL, outline=accent, width=1)
        self._draw_monique_osc_wave(x0, mid_y0, sx1, mid_y1, accent)

        rx0 = sx1 + 6
        if self.osc_idx < 3:
            oi = self.osc_idx + 1
            wave_val = self._norm(self._get_zctrl(f"osc{oi}_wave"))
            snaps = [("Sine", 0.0), ("Saw", 1.0 / 3.0), ("Square", 2.0 / 3.0), ("Noise", 1.0)]
            bw = (x1 - rx0 - gap) / 2
            bh = (mid_y1 - mid_y0 - gap) / 2
            for i, (slbl, sval) in enumerate(snaps):
                col_i = i % 2
                row_i = i // 2
                bx0 = rx0 + col_i * (bw + gap)
                by_i = mid_y0 + row_i * (bh + gap)
                act = abs(wave_val - sval) < 0.08
                self._draw_pill(bx0, by_i, bx0 + bw, by_i + bh, slbl, act, accent,
                                "wave_snap", (f"osc{oi}_wave", sval))
        else:
            fm_sync = self._norm(self._get_zctrl("fm_sync")) >= 0.5
            mid_h = mid_y1 - mid_y0
            self._draw_pill(rx0, mid_y0, x1, mid_y0 + mid_h * 0.55,
                            "FM SYNC: ON" if fm_sync else "FM SYNC: OFF",
                            fm_sync, accent, "cycle", "fm_sync")
            c.create_rectangle(rx0, mid_y0 + mid_h * 0.60, x1, mid_y1,
                               fill=COL_PANEL, outline=COL_BORDER, width=1)
            c.create_text((rx0 + x1) / 2, mid_y0 + mid_h * 0.80,
                          text="FM Osc modulates\nOSC 1-3 via FM Mass",
                          fill=COL_DIM, justify="center", font=self._font(self._fs(0.82)))

        # Row 3: Bottom 2x2 Big Parameter Cards for Active Osc / FM Page (bound to 4 encoders)
        py0 = mid_y1 + 5
        page_title = ("OSC 1", "OSC 2", "OSC 3", "FM Engine")[self.osc_idx]
        items = self._page_items(page_title)
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + gap)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent,
                                 bipolar=("tune" in key and key != "fm_tune"))

    def _draw_monique_osc_wave(self, x0, y0, x1, y1, accent):
        c = self.widget_canvas
        oi = min(3, self.osc_idx + 1)
        w_val = self._norm(self._get_zctrl(f"osc{oi}_wave")) * 3.0
        fm_mass = self._norm(self._get_zctrl(f"osc{oi}_fm_mass"))
        fm_tune = self._norm(self._get_zctrl("fm_tune"))
        fm_shape = self._norm(self._get_zctrl("fm_shape"))

        mid_y = (y0 + y1) / 2 + 8
        c.create_line(x0 + 8, mid_y, x1 - 8, mid_y, fill=COL_GRID, dash=(2, 4))

        pad = 10
        gw = max(10, (x1 - x0) - 2 * pad)
        amp = max(8, (y1 - y0) / 2 - 18)
        n_pts = 96

        def base_wave(ph, wv):
            s = math.sin(2.0 * math.pi * ph)
            saw = 2.0 * (ph % 1.0) - 1.0
            sqr = 1.0 if (ph % 1.0) < 0.5 else -1.0
            nse = math.sin(int(ph * 28.0) * 12.9898 + 4.1414) * 0.9
            if wv <= 1.0:
                return (1.0 - wv) * s + wv * saw
            if wv <= 2.0:
                t = wv - 1.0
                return (1.0 - t) * saw + t * sqr
            t = wv - 2.0
            return (1.0 - t) * sqr + t * nse

        pts = []
        fm_ratio = 1.0 + fm_tune * 6.0
        for i in range(n_pts + 1):
            t = i / n_pts
            ph = (t * 2.0) % 1.0
            if self.osc_idx == 3:
                y = math.sin(2.0 * math.pi * (t * (1.5 + fm_tune * 5.0)) + fm_shape * 2.0 * math.sin(4.0 * math.pi * t))
            else:
                mod = fm_mass * 0.45 * math.sin(2.0 * math.pi * t * 2.0 * fm_ratio + fm_shape * math.pi)
                y = base_wave((ph + mod) % 1.0, w_val)
            pts.extend([x0 + pad + t * gw, mid_y - max(-1.0, min(1.0, y)) * amp])

        c.create_line(pts, fill=accent, width=2.4)
        if self.osc_idx == 3:
            hdr = f"FM OSC   Tune:{int(round(fm_tune * 100))}%   Shape:{int(round(fm_shape * 100))}%"
        else:
            hdr = f"OSC {oi}: {fmt_osc_wave(w_val / 3.0)}   FM:{int(round(fm_mass * 100))}%"
        c.create_text(x0 + 8, y0 + 12, text=hdr, anchor="w", fill=accent,
                      font=self._font(self._fs(0.88), bold=True))

    # --------------------------------------------------------------------------
    # TAB 3: FILTER (4 Encoder Pages: Filter Core | Filter Mod | Filter Mix | Filters 1-3)
    # --------------------------------------------------------------------------
    def _draw_tab_filter(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = FILTER_COLS[self.flt_idx]
        fi = self.flt_idx + 1
        gap = 4

        # Row 1: Big F1 / F2 / F3 Selector (left 34%) + Big 4-Bank Encoder Page Bar (right 66%)
        r1_h = 34
        left_w = (x1 - x0) * 0.34
        fw = (left_w - 2 * gap) / 3
        for i in range(3):
            fx0 = x0 + i * (fw + gap)
            self._draw_pill(fx0, y0, fx0 + fw, y0 + r1_h, f"F{i + 1}",
                            i == self.flt_idx, FILTER_COLS[i], "flt_idx", i)

        self._draw_bank_bar(
            x0 + left_w + 6, y0, x1, y0 + r1_h,
            ["Core", "Mod", "Mix", "F1-3"],
            self.flt_bank, accent, "flt_bank",
        )

        # Row 2: Big 7 Filter Type Buttons
        r2_y = y0 + r1_h + 6
        r2_h = 34
        ft_z = self._get_zctrl(f"f{fi}_type")
        ft_idx = (ft_z.get_value2index() or 0) if ft_z else 0
        tw = (x1 - x0 - gap * (len(FILTER_SHORT) - 1)) / len(FILTER_SHORT)
        for i, slbl in enumerate(FILTER_SHORT):
            tx0 = x0 + i * (tw + gap)
            self._draw_pill(tx0, r2_y, tx0 + tw, r2_y + r2_h, slbl,
                            i == ft_idx, accent, "flt_type", i)

        # Row 3: 3-Filter Log-Hz Response Graph
        gy0 = r2_y + r2_h + 5
        bot_h = 88
        gy1 = y1 - bot_h - 5
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad_x, pad_y = 12, 10
        gx0, gx1 = x0 + pad_x, x1 - pad_x
        g_top, g_bot = gy0 + pad_y, gy1 - pad_y
        gw = max(10, gx1 - gx0)
        gh = max(10, g_bot - g_top)

        for hz, lbl in ((100.0, "100"), (1000.0, "1k"), (10000.0, "10k")):
            lx = gx0 + hz_to_monique_norm(hz) * gw
            c.create_line(lx, gy0 + 2, lx, gy1 - 2, fill=COL_GRID, dash=(2, 4))
            c.create_text(lx + 3, gy1 - 6, text=lbl, anchor="sw", fill=COL_DIM, font=self._font(8))
        zero_y = g_top + gh * 0.45
        c.create_line(gx0, zero_y, gx1, zero_y, fill=COL_GRID, dash=(2, 4))

        def build_curve(cut, res, ftype):
            pts = []
            n_pts = 56
            is_hp = ftype in (1, 3)
            is_bp = (ftype == 2)
            is_pass = (ftype == 4)
            slope = 24.0 if ftype in (0, 3, 6) else 14.0
            for i in range(n_pts + 1):
                t = i / n_pts
                if is_pass:
                    db = 0.0
                else:
                    d = (t - cut) / 0.11
                    peak = (res * 16.0) * math.exp(-d * d * 2.2)
                    if is_hp:
                        roll = -slope * ((cut - t) / 0.16) ** 2 if t < cut else 0.0
                    elif is_bp:
                        roll = -18.0 * (abs(t - cut) / 0.16) ** 1.6
                    else:
                        roll = -slope * ((t - cut) / 0.16) ** 2 if t > cut else 0.0
                    db = max(-30.0, min(18.0, roll + peak))
                px = gx0 + t * gw
                py = zero_y - (db / 24.0) * (gh * 0.48)
                pts.extend([px, max(gy0 + 3, min(gy1 - 3, py))])
            return pts

        f_states = []
        for idx in range(3):
            k = idx + 1
            cut = self._norm(self._get_zctrl(f"f{k}_cutoff"), 0.4)
            res = self._norm(self._get_zctrl(f"f{k}_reso"), 0.2)
            tz = self._get_zctrl(f"f{k}_type")
            ft = (tz.get_value2index() or 0) if tz else 0
            f_states.append((idx, cut, res, ft))

        for idx, cut, res, ft in f_states:
            if idx != self.flt_idx:
                c.create_line(build_curve(cut, res, ft), fill=FILTER_COLS[idx], width=1.4, dash=(3, 3))

        _, acut, ares, aft = f_states[self.flt_idx]
        apts = build_curve(acut, ares, aft)
        c.create_polygon([gx0, gy1 - 2] + apts + [gx1, gy1 - 2], fill="#241e18", outline="")
        c.create_line(apts, fill=accent, width=2.5)

        for idx, cut, res, _ in f_states:
            act = (idx == self.flt_idx)
            hx = gx0 + cut * gw
            hy = g_bot - res * gh
            r = 11 if act else 7
            col = FILTER_COLS[idx]
            c.create_oval(hx - r, hy - r, hx + r, hy + r,
                          fill=col if act else COL_PANEL_HI,
                          outline="#ffffff" if act else col, width=2 if act else 1)
            c.create_text(hx, hy, text=str(idx + 1), fill="#000000" if act else col,
                          font=self._font(9, bold=True))

        hdr = f"F{fi}: {FILTER_TYPES[min(aft, len(FILTER_TYPES) - 1)]}  {fmt_hz(monique_cutoff_hz(acut))}  Res:{int(round(ares * 100))}%"
        c.create_text(x0 + 8, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._font(self._fs(0.86), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "filter_xy",
            {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot, "states": f_states},
        ))

        # Row 4: Bottom 2x2 Big Parameter Cards
        py0 = gy1 + 5
        page_title = ("Filter Core", "Filter Mod", "Filter Mix", "Filters 1-3")[self.flt_bank]
        items = self._page_items(page_title)
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + gap)
            bip = ("_mod" in key or "_pan" in key or (fi > 1 and "_in" in key))
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent, bipolar=bip)

    # --------------------------------------------------------------------------
    # TAB 4: ENV / LFO (3 Encoder Pages: Amp ENV | Filter ENV | Filter LFO)
    # --------------------------------------------------------------------------
    def _draw_tab_env_lfo(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Env/LFO"]
        gap = 4

        # Row 1: Big Target Selector (AMP / F1 / F2 / F3) + ENV / LFO Page Toggle
        r1_h = 34
        left_w = (x1 - x0) * 0.56
        ew = (left_w - 3 * gap) / 4
        for i, lbl in enumerate(("AMP", "F1", "F2", "F3")):
            ex0 = x0 + i * (ew + gap)
            col = accent if i == 0 else FILTER_COLS[i - 1]
            self._draw_pill(ex0, y0, ex0 + ew, y0 + r1_h, lbl,
                            i == self.env_idx, col, "env_idx", i)

        self._draw_bank_bar(
            x0 + left_w + 6, y0, x1, y0 + r1_h,
            ["ENV", "LFO"],
            self.env_bank, accent, "env_bank",
        )

        # Row 2: Interactive 2D ADSR Graph (left 58%) + LFO Scope (right 42%)
        gy0 = y0 + r1_h + 5
        bot_h = 88
        gy1 = y1 - bot_h - 5

        env_col = accent if self.env_idx == 0 else FILTER_COLS[self.env_idx - 1]
        pref = "amp" if self.env_idx == 0 else f"f{self.env_idx}_env"
        env_title = "AMP ENV" if self.env_idx == 0 else f"F{self.env_idx} ENV"

        gw_tot = int((x1 - x0) * 0.58)
        ex1 = x0 + gw_tot
        c.create_rectangle(x0, gy0, ex1, gy1, fill=COL_PANEL, outline=env_col, width=1)

        pad = 12
        gx0, gx1 = x0 + pad, ex1 - pad
        g_top, g_bot = gy0 + pad + 16, gy1 - pad
        gw = max(20, gx1 - gx0)
        gh = max(20, g_bot - g_top)

        a = self._norm(self._get_zctrl(f"{pref}_att"))
        d = self._norm(self._get_zctrl(f"{pref}_dec"))
        s = self._norm(self._get_zctrl(f"{pref}_sus"))
        r = self._norm(self._get_zctrl(f"{pref}_rel"))
        slope = self._norm(self._get_zctrl(f"{pref}_slope"), 0.5)

        xa = gx0 + a * (gw * 0.28)
        xd = xa + max(0.02, d) * (gw * 0.28)
        xs = xd + gw * 0.16
        xr = xs + max(0.02, r) * (gw * 0.28)
        ys = g_bot - s * gh

        curve_pow = 2.0 ** ((0.5 - slope) * 2.2)
        pts = [gx0, g_bot]
        for seg_i in range(1, 13):
            t = seg_i / 12.0
            pts.extend([gx0 + (xa - gx0) * t, g_bot - (t ** curve_pow) * gh])
        for seg_i in range(1, 13):
            t = seg_i / 12.0
            pts.extend([xa + (xd - xa) * t, g_top + (1.0 - (1.0 - t) ** curve_pow) * (ys - g_top)])
        pts.extend([xs, ys])
        for seg_i in range(1, 13):
            t = seg_i / 12.0
            pts.extend([xs + (xr - xs) * t, ys + (1.0 - (1.0 - t) ** curve_pow) * (g_bot - ys)])

        c.create_polygon(pts + [gx0, g_bot], fill="#17241b", outline="")
        c.create_line(pts, fill=env_col, width=2.4)

        for hx, hy in ((xa, g_top), (xd, ys), (xr, g_bot)):
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=env_col, outline="#ffffff", width=2)

        hdr = f"{env_title}  A:{fmt_ms(monique_env_ms(a))} D:{fmt_ms(monique_env_ms(d))} S:{int(round(s * 100))}% R:{fmt_ms(monique_env_ms(r))}"
        c.create_text(x0 + 8, gy0 + 11, text=hdr, anchor="w", fill=env_col,
                      font=self._font(self._fs(0.8), bold=True))

        self.hitboxes.append((
            x0, gy0, ex1, gy1, "env_graph",
            {"prefix": pref, "gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
             "xa": xa, "xd": xd, "xs": xs, "xr": xr, "ys": ys},
        ))

        rx0 = ex1 + 6
        li = max(1, self.env_idx)
        lfo_col = FILTER_COLS[li - 1]
        c.create_rectangle(rx0, gy0, x1, gy1, fill=COL_PANEL, outline=lfo_col, width=1)
        self._draw_lfo_scope(
            rx0, gy0, x1, gy1,
            f"lfo{li}_speed", f"lfo{li}_wave", f"lfo{li}_phase",
            f"LFO {li}", lfo_col,
        )

        # Row 3: Bottom 2x2 Big Parameter Cards
        py0 = gy1 + 5
        items = self._page_items(self._active_page_title())
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + gap)
            bip = ("slope" in key or "modmix" in key)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl,
                                 lfo_col if self.env_bank == 1 else env_col, bipolar=bip)

    def _draw_lfo_scope(self, x0, y0, x1, y1, spd_key, wav_key, phs_key, title, color):
        c = self.widget_canvas
        spd_z = self._get_zctrl(spd_key)
        spd_n = self._norm(spd_z, 0.35)
        wav = self._norm(self._get_zctrl(wav_key), 0.0)
        phs = self._norm(self._get_zctrl(phs_key), 0.0)

        pad = 8
        gx0, gx1 = x0 + pad, x1 - pad
        gw = max(10, gx1 - gx0)
        mid_y = (y0 + y1) / 2 + 7
        amp = max(8, (y1 - y0) / 2 - 17)
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        cycles = 1.0 + spd_n * 4.5
        pts = []
        n_pts = 72
        for i in range(n_pts + 1):
            t = i / n_pts
            p = (t * cycles + phs) % 1.0
            s = math.sin(2.0 * math.pi * p)
            tri = 1.0 - 4.0 * abs(p - 0.5)
            sqr = 1.0 if p < 0.5 else -1.0
            if wav < 0.5:
                k = wav * 2.0
                y = (1.0 - k) * s + k * tri
            else:
                k = (wav - 0.5) * 2.0
                y = (1.0 - k) * tri + k * sqr
            pts.extend([gx0 + t * gw, mid_y - y * amp])

        c.create_line(pts, fill=color, width=2.2)
        hdr = f"{title}  {self._fmt(spd_z)}  {int(round(phs * 360))}°"
        c.create_text(x0 + 8, y0 + 11, text=hdr, anchor="w", fill=color,
                      font=self._font(self._fs(0.8), bold=True))

    # --------------------------------------------------------------------------
    # TAB 5: ARP / SEQ (2 Encoder Pages: Arp Global | Arp Steps)
    # --------------------------------------------------------------------------
    def _draw_tab_arp(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Arp/Seq"]
        gap = 4

        # Row 1: Big Toggles (ARP ON, BIND) + Big Encoder Bank Bar
        r1_h = 34
        arp_on = self._norm(self._get_zctrl("arp_on")) >= 0.5
        bind_on = self._norm(self._get_zctrl("arp_connect")) >= 0.5

        left_w = (x1 - x0) * 0.42
        bw = (left_w - gap) / 2
        self._draw_pill(x0, y0, x0 + bw, y0 + r1_h, "ARP ON" if arp_on else "ARP OFF",
                        arp_on, accent, "cycle", "arp_on")
        self._draw_pill(x0 + bw + gap, y0, x0 + left_w, y0 + r1_h,
                        "BIND ON" if bind_on else "BIND",
                        bind_on, accent, "cycle", "arp_connect")

        self._draw_bank_bar(
            x0 + left_w + 6, y0, x1, y0 + r1_h,
            ["Global", "Tune 4", "Velo 4"],
            self.arp_bank, accent, "arp_bank",
        )

        # Row 2: 16-Step Interactive Matrix with Big 32px Gate Buttons
        gy0 = y0 + r1_h + 5
        bot_h = 88
        gy1 = y1 - bot_h - 5

        sw = (x1 - x0 - 15 * 2) / 16
        led_h = 32
        tune_y0 = gy0 + led_h + 4
        tune_h = int((gy1 - tune_y0 - 4) * 0.54)
        tune_y1 = tune_y0 + tune_h
        vel_y0 = tune_y1 + 4
        vel_y1 = gy1

        for i in range(16):
            si = i + 1
            sx0 = x0 + i * (sw + 2)
            sx1 = sx0 + sw
            page_i = i // 4
            in_page = (page_i == self.arp_page and self.arp_bank in (1, 2))

            step_on = self._norm(self._get_zctrl(f"arp_step_{si}")) >= 0.5
            tune_n = self._norm(self._get_zctrl(f"arp_tune_{si}"), 0.5)
            velo_n = self._norm(self._get_zctrl(f"arp_velo_{si}"), 0.85)

            col_led = accent if step_on else COL_PANEL
            c.create_rectangle(sx0, gy0, sx1, gy0 + led_h,
                               fill=col_led,
                               outline="#ffffff" if in_page else (accent if i % 4 == 0 else COL_BORDER),
                               width=2 if in_page else 1)
            c.create_text((sx0 + sx1) / 2, gy0 + led_h / 2, text=str(si),
                          fill="#0d0e12" if step_on else COL_TEXT,
                          font=self._font(self._fs(0.84), bold=True))
            self.hitboxes.append((sx0, gy0, sx1, gy0 + led_h, "arp_step_toggle", (si, page_i)))

            c.create_rectangle(sx0, tune_y0, sx1, tune_y1, fill=COL_PANEL,
                               outline=accent if in_page else COL_BORDER, width=1)
            mid_y = (tune_y0 + tune_y1) / 2
            ty = tune_y1 - tune_n * (tune_y1 - tune_y0)
            tcol = accent if step_on else "#5c5328"
            c.create_rectangle(sx0 + 1, min(mid_y, ty), sx1 - 1, max(mid_y, ty), fill=tcol, outline="")
            c.create_line(sx0, mid_y, sx1, mid_y, fill=COL_DIM, width=1)
            self.hitboxes.append((
                sx0, tune_y0, sx1, tune_y1, "vfader",
                {"key": f"arp_tune_{si}", "ty0": tune_y0, "ty1": tune_y1,
                 "bank_kind": "arp_bank", "bank_idx": 1, "arp_page": page_i},
            ))

            c.create_rectangle(sx0, vel_y0, sx1, vel_y1, fill=COL_PANEL,
                               outline=accent if in_page else COL_BORDER, width=1)
            vy = vel_y1 - velo_n * (vel_y1 - vel_y0)
            vcol = "#51cf66" if step_on else "#2d4a33"
            if vel_y1 - vy > 1:
                c.create_rectangle(sx0 + 1, vy, sx1 - 1, vel_y1 - 1, fill=vcol, outline="")
            self.hitboxes.append((
                sx0, vel_y0, sx1, vel_y1, "vfader",
                {"key": f"arp_velo_{si}", "ty0": vel_y0, "ty1": vel_y1,
                 "bank_kind": "arp_bank", "bank_idx": 2, "arp_page": page_i},
            ))

        # Row 3: Bottom 2x2 Big Parameter Cards
        py0 = gy1 + 5
        items = self._page_items(self._active_page_title())
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + gap)
            bip = ("tune" in key or "mul" in key or "fine" in key)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent, bipolar=bip)

    # --------------------------------------------------------------------------
    # TAB 6: EQ / FX (4 Encoder Pages: EQ & Dist | Chorus/Dly | Reverb | Loop/Mstr)
    # --------------------------------------------------------------------------
    def _draw_tab_eq_fx(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["EQ/FX"]
        gap = 4

        # Row 1: Big 4-Page FX Selector Bar
        bh = 36
        self._draw_bank_bar(
            x0, y0, x1, y0 + bh,
            ["EQ & Dist", "Chorus/Dly", "Reverb", "Loop/Mstr"],
            self.fx_bank, accent, "fx_bank",
        )

        by0 = y0 + bh + 5
        left_w = int((x1 - x0) * 0.50)
        lx1 = x0 + left_w
        rx0 = lx1 + 6

        # Left Panel: 7-Band Graphic EQ vertical faders + Big EQ Mix / Reso strip
        eq_bot_h = 44
        eq_y1 = y1 - eq_bot_h - 4
        bw = (left_w - 6 * 3) / 7
        for i in range(7):
            bx0 = x0 + i * (bw + 3)
            self._draw_vfader(
                bx0, by0, bx0 + bw, eq_y1,
                f"eq{i + 1}_gain", EQ_BAND_LABELS[i],
                accent if self.fx_bank == 0 else "#964646",
                bank_kind="fx_bank", bank_idx=0,
            )

        ew2 = (left_w - gap) / 2
        self._draw_param_box(x0, eq_y1 + 4, x0 + ew2, y1, "eq_mix", "EQ Mix",
                             accent if self.fx_bank == 0 else "#964646",
                             bank_kind="fx_bank", bank_idx=0)
        self._draw_param_box(x0 + ew2 + gap, eq_y1 + 4, lx1, y1, "eq_reso", "EQ Reso",
                             accent if self.fx_bank == 0 else "#964646",
                             bank_kind="fx_bank", bank_idx=0)

        # Right Panel: 4 Big Parameter Cards for the Active FX Encoder Page + Master
        r_items = self._page_items(self._active_page_title())
        rh = (y1 - by0 - 3 * 5) / 4
        for i, (key, lbl) in enumerate(r_items):
            ry0 = by0 + i * (rh + 5)
            bip = ("pan" in key)
            self._draw_param_box(rx0, ry0, x1, ry0 + rh, key, lbl, accent, bipolar=bip)

    # --------------------------------------------------------------------------
    # Touchscreen Interaction
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
        cur = getattr(self, bank_kind, None)
        if cur != bank_idx:
            setattr(self, bank_kind, bank_idx)
            self._live_swap_encoders()

    def _on_press(self, event):
        kind, payload = self._find_hit(event.x, event.y)
        self.drag_target = None
        if kind is None:
            return

        if kind == "tab":
            if payload != self.active_tab:
                self.active_tab = payload
                self._live_swap_encoders()
                self.last_snapshot = None
                self._draw()
            return

        if kind in ("morph_bank", "flt_bank", "env_bank", "arp_bank", "fx_bank"):
            self._switch_subbank(kind, payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "bank_glob":
            self._switch_subbank("morph_bank", 2)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "morph_idx":
            self.morph_idx = payload
            self.morph_bank = 1
            self._live_swap_encoders("Morph MFO")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "morph_quad":
            now = time.monotonic()
            tap_id = ("morph_quad", "abcd")
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for mk, _, _, _ in MORPH_GROUPS:
                    self._set_norm(self._get_zctrl(f"{mk}_state"), 0.5)
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("morph_quad", payload)
            self._apply_drag(event.x, event.y)
            return

        if kind == "osc_idx":
            self.osc_idx = payload
            self._live_swap_encoders()
            self.last_snapshot = None
            self._draw()
            return

        if kind == "wave_snap":
            key, val = payload
            self._set_norm(self._get_zctrl(key), val)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "flt_idx":
            self.flt_idx = payload
            # Update all dynamic Filter pages so encoders immediately control the selected filter
            for p in ("Filter Core", "Filter Mod", "Filter Mix", "Filters 1-3"):
                self.processor.ctrl_screens_dict[p] = self._build_page_zctrls(p)
            self._live_swap_encoders()
            self.last_snapshot = None
            self._draw()
            return

        if kind == "flt_type":
            fi = self.flt_idx + 1
            z = self._get_zctrl(f"f{fi}_type")
            if z and getattr(z, "ticks", None) and 0 <= payload < len(z.ticks):
                z.set_value(z.ticks[payload], send=True)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "env_idx":
            self.env_idx = payload
            if payload == 0:
                self.env_bank = 0
            for p in ("Filter ENV", "Filter LFO"):
                self.processor.ctrl_screens_dict[p] = self._build_page_zctrls(p)
            self._live_swap_encoders()
            self.last_snapshot = None
            self._draw()
            return

        if kind == "arp_step_toggle":
            si, page_i = payload
            self._cycle_enum(self._get_zctrl(f"arp_step_{si}"), 1)
            if self.arp_page != page_i:
                self.arp_page = page_i
                self.processor.ctrl_screens_dict["Arp Steps"] = self._build_page_zctrls("Arp Steps")
                if self.arp_bank in (1, 2):
                    self._live_swap_encoders("Arp Steps")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "cycle":
            self._cycle_enum(self._get_zctrl(payload), 1)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "filter_xy":
            gx0, gx1 = payload["gx0"], payload["gx1"]
            gy0, gy1 = payload["gy0"], payload["gy1"]
            gw = max(1, gx1 - gx0)
            gh = max(1, gy1 - gy0)
            best_idx = self.flt_idx
            best_d = 1e12
            for idx, cut, res, _ in payload["states"]:
                hx = gx0 + cut * gw
                hy = gy1 - res * gh
                d = (event.x - hx) ** 2 + (event.y - hy) ** 2
                if d < best_d:
                    best_d = d
                    best_idx = idx
            if best_d < 1000 and best_idx != self.flt_idx:
                self.flt_idx = best_idx
                for p in ("Filter Core", "Filter Mod", "Filter Mix", "Filters 1-3"):
                    self.processor.ctrl_screens_dict[p] = self._build_page_zctrls(p)
            fi = self.flt_idx + 1
            self.flt_bank = 0
            self._live_swap_encoders("Filter Core")
            now = time.monotonic()
            tap_id = ("filter_xy", fi)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for rk in (f"f{fi}_cutoff", f"f{fi}_reso"):
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("filter_xy", {
                "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                "cut_key": f"f{fi}_cutoff", "res_key": f"f{fi}_reso",
            })
            self._apply_drag(event.x, event.y)
            return

        if kind == "env_graph":
            self.env_bank = 0
            self._live_swap_encoders()
            d_a = abs(event.x - payload["xa"])
            d_ds = math.hypot(event.x - payload["xd"], event.y - payload["ys"])
            d_r = abs(event.x - payload["xr"])
            if d_a <= d_ds and d_a <= d_r:
                node = "A"
            elif d_ds <= d_r:
                node = "DS"
            else:
                node = "R"
            now = time.monotonic()
            pref = payload["prefix"]
            tap_id = ("env_node", pref, node)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                rkeys = [f"{pref}_att"] if node == "A" else ([f"{pref}_dec", f"{pref}_sus"] if node == "DS" else [f"{pref}_rel"])
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

        if kind in ("vfader", "hfader"):
            if "arp_page" in payload and payload["arp_page"] != self.arp_page:
                self.arp_page = payload["arp_page"]
                self.processor.ctrl_screens_dict["Arp Steps"] = self._build_page_zctrls("Arp Steps")
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
            gx0, gx1 = payload["gx0"], payload["gx1"]
            gy0, gy1 = payload["gy0"], payload["gy1"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl(payload["cut_key"]), (x - gx0) / (gx1 - gx0))
            if gy1 > gy0:
                self._set_norm(self._get_zctrl(payload["res_key"]), (gy1 - y) / (gy1 - gy0))
        elif kind == "morph_quad":
            px0, px1 = payload["px0"], payload["px1"]
            py0, py1 = payload["py0"], payload["py1"]
            nx = max(0.0, min(1.0, (x - px0) / max(1.0, px1 - px0)))
            ny = max(0.0, min(1.0, (py1 - y) / max(1.0, py1 - py0)))
            # Bilinear A/B/C/D corner weights -> OSC (TL), FLT (TR), ARP (BL), FX (BR)
            weights = [
                (1.0 - nx) * ny,
                nx * ny,
                (1.0 - nx) * (1.0 - ny),
                nx * (1.0 - ny),
            ]
            # Normalize so peak corner hits 1.0 cleanly while center sits at 0.5
            peak = max(0.25, max(weights))
            for idx, (mk, _, _, _) in enumerate(MORPH_GROUPS):
                self._set_norm(self._get_zctrl(f"{mk}_state"), min(1.0, weights[idx] / peak * (0.5 + 0.5 * peak)))
        elif kind == "env_node":
            pref = payload["prefix"]
            gx0, gw = payload["gx0"], payload["gw"]
            g_top, g_bot = payload["g_top"], payload["g_bot"]
            seg_w = max(10.0, gw * 0.28)
            node = payload["node"]
            if node == "A":
                self._set_norm(self._get_zctrl(f"{pref}_att"), (x - gx0) / seg_w)
            elif node == "DS":
                self._set_norm(self._get_zctrl(f"{pref}_dec"), (x - payload["xa"]) / seg_w)
                if g_bot > g_top:
                    self._set_norm(self._get_zctrl(f"{pref}_sus"), (g_bot - y) / (g_bot - g_top))
            elif node == "R":
                self._set_norm(self._get_zctrl(f"{pref}_rel"), (x - payload["xs"]) / seg_w)

        self.last_snapshot = None
        self._draw()
