#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Vitalium Workstation Widget for Zynthian (V5 800x480 & touchscreens)
#
# Replaces Vitalium's ~780+ raw LV2 parameters with 6 dynamic workstation tabs
# mapped 1-to-1 to Zynthian's 4 physical encoders + one-tap ECO CPU tamer:
#   Macro | Osc | Filter | Env | LFO | FX   + ECO button
#
# Features:
# - Resilient controller resolver: matches Vitalium LV2 zctrls by normalized
#   display_name (rdfs:label) AND internal Vital parameter ID (symbol).
# - Authentic Vitalium DSP scales & enum labels (MIDI 8..136 cutoff -> Hz,
#   quartic envelope times 0..32s, 8 filter models, 12 spectral morphs, 13
#   phase distortions, 13 synced tempo divisions, 6 distortion types, etc.).
# - Dynamic encoder binding: tapping sub-banks, oscillators, filters, envelopes,
#   LFOs, or FX modules immediately rebinds Zynthian's 4 physical encoders.
# - Real-time interactive DSP visualizations:
#   * Macro: 4 vertical Macro faders + Mod Wheel + Volume + Performance strip
#   * Osc: live wavetable/morph/distortion + unison preview & routing pills
#   * Filter: log-Hz 3-filter (F1/F2/FX) response graph + draggable 2D handles
#   * Env: interactive 2D ADSR graph with Vital power curves (ENV 1..6)
#   * LFO: live LFO 1..6 & Random LFO 1..2 waveform scope + sync/trigger pills
#   * FX: 8-module FX rack (Dist, Chorus, Delay, Reverb, Comp, EQ, Flang, Phase)
# - ECO toggle: caps Oversampling -> 1x, Polyphony -> 8v, Unison -> 3v with
#   one-tap restore of original preset settings for smooth Pi 5 playback.
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
# Theme Palette (matches Zynthian dark UI, Surge XT & Monique widgets)
# ------------------------------------------------------------------------------
COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

TABS = ["Macro", "Osc", "Filter", "Env", "LFO", "FX"]
TAB_ACCENTS = {
    "Macro":  "#4dabf7",  # blue
    "Osc":    "#cc5de8",  # violet
    "Filter": "#ff922b",  # orange
    "Env":    "#51cf66",  # green
    "LFO":    "#ffd43b",  # yellow
    "FX":     "#ff6b6b",  # coral
}
FILTER_COLS = ("#ff922b", "#38d9a9", "#4dabf7")

# ------------------------------------------------------------------------------
# Authentic Vitalium Enum Tables & Mathematical Scales
# ------------------------------------------------------------------------------
TOGGLE_OFF_ON = ["Off", "On"]
OVERSAMPLING_NAMES = ["1x", "2x", "4x", "8x"]
STEREO_MODES = ["Spread", "Rotate"]
VOICE_PRIORITIES = ["Newest", "Oldest", "Highest", "Lowest", "RndRbn"]
POLY_PRESETS = (4, 6, 8, 12, 16, 24, 32)
POLY_LABELS = tuple(f"{v}v" for v in range(1, 33))
UNISON_VOICES_LABELS = tuple(f"{v}v" for v in range(1, 17))

FILTER_MODELS = ["Analog", "Dirty", "Ladder", "Digital", "Diode", "Formant", "Comb", "Phaser"]
FILTER_STYLES = ["12dB", "24dB", "Notch", "Spread", "B/P/N"]

SPECTRAL_MORPHS = [
    "None", "Vocode", "Formant", "HarmStr", "Inharm", "Smear",
    "RndAmp", "LowPass", "HighPass", "PhsDisp", "Shepard", "TimeSkw",
]
PHASE_DISTS = [
    "None", "Sync", "Formant", "Quantize", "Bend", "Squeeze", "Pulse",
    "FM O1", "FM O2", "FM Smp", "RM O1", "RM O2", "RM Smp",
]
DESTINATIONS = [
    "Filter 1", "Filter 2", "Flt 1+2", "Effects", "Direct",
    "Chorus", "Comp", "Delay", "Distort", "EQ", "FX Flt", "Flanger", "Phaser", "Reverb",
]
DEST_SHORT = ["F1", "F2", "F1+2", "FX", "Dir"]

FREQ_SYNC_NAMES = ["Secs", "Tempo", "Dotted", "Triplet", "KeyTrk"]
LFO_TRIG_NAMES = ["Trigger", "Sync", "Env", "Sus Env", "Loop", "LoopHld"]
SYNCED_TEMPOS = [
    "Freeze", "32/1", "16/1", "8/1", "4/1", "2/1", "1/1",
    "1/2", "1/4", "1/8", "1/16", "1/32", "1/64",
]
DELAY_TEMPOS = ["4/1", "2/1", "1/1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64"]
MOD_TEMPOS = ["Freeze", "32/1", "16/1", "8/1", "4/1", "2/1", "1/1", "1/2", "1/4", "1/8", "1/16"]
RANDOM_STYLES = ["Perlin", "S & H", "Sine", "Lorenz"]

DIST_TYPES = ["SoftClip", "HardClip", "LinFold", "SinFold", "BitCrush", "DownSmp"]
DELAY_STYLES = ["Mono", "Stereo", "PingPong", "MidPing"]
COMP_BANDS = ["Multi", "Low", "High", "Single"]
EQ_LOW_MODES = ["Shelf", "HPF"]
EQ_HIGH_MODES = ["Shelf", "LPF"]

FX_MODULES = [
    ("dist",   "Dist",   "distortion_on"),
    ("chorus", "Chorus", "chorus_on"),
    ("delay",  "Delay",  "delay_on"),
    ("reverb", "Reverb", "reverb_on"),
    ("comp",   "Comp",   "compressor_on"),
    ("eq",     "EQ",     "eq_on"),
    ("flang",  "Flang",  "flanger_on"),
    ("phase",  "Phase",  "phaser_on"),
]

LFO_SLOTS = [
    ("lfo_1", "LFO 1", False),
    ("lfo_2", "LFO 2", False),
    ("lfo_3", "LFO 3", False),
    ("lfo_4", "LFO 4", False),
    ("lfo_5", "LFO 5", False),
    ("lfo_6", "LFO 6", False),
    ("random_1", "RND 1", True),
    ("random_2", "RND 2", True),
]


def vital_cutoff_hz(n):
    """Vital cutoff is MIDI note 8..136 -> Hz = 440 * 2^((midi - 69) / 12)."""
    n = max(0.0, min(1.0, float(n)))
    midi = 8.0 + n * 128.0
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def hz_to_vital_norm(hz):
    hz = max(13.0, min(22000.0, float(hz)))
    midi = 69.0 + 12.0 * math.log2(hz / 440.0)
    return max(0.0, min(1.0, (midi - 8.0) / 128.0))


def fmt_hz(hz):
    if hz >= 10000.0:
        return f"{hz / 1000.0:.1f}kHz"
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}kHz"
    if hz >= 100.0:
        return f"{hz:.0f}Hz"
    return f"{hz:.1f}Hz"


def vital_env_s(n, max_raw=2.37842):
    """Vital quartic envelope time: (n * max_raw)^4 seconds (~0..32s)."""
    n = max(0.0, min(1.0, float(n)))
    return (n * max_raw) ** 4.0


def fmt_time_s(s):
    if s <= 0.0005:
        return "0ms"
    if s < 1.0:
        return f"{s * 1000.0:.0f}ms"
    return f"{s:.2f}s" if s < 10.0 else f"{s:.1f}s"


def vital_exp_hz(n, lo=-7.0, hi=9.0):
    """Vital exponential frequency: 2^(lo + n*(hi-lo)) Hz."""
    n = max(0.0, min(1.0, float(n)))
    return 2.0 ** (lo + n * (hi - lo))


def fmt_lfo_hz(hz):
    if hz >= 100.0:
        return f"{hz:.0f}Hz"
    if hz >= 10.0:
        return f"{hz:.1f}Hz"
    return f"{hz:.2f}Hz"


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
SCALE_CUTOFF = _build_scale(129, lambda t: fmt_hz(vital_cutoff_hz(t)))
SCALE_ENVTIME = _build_scale(101, lambda t: fmt_time_s(vital_env_s(t, 2.37842)))
SCALE_ENVSHORT = _build_scale(101, lambda t: fmt_time_s(vital_env_s(t, 1.41421)))
SCALE_TRANSPOSE = _build_scale(97, lambda t: f"{int(round((t * 2.0 - 1.0) * 48)):+d}st")
SCALE_TUNE_CENTS = _build_scale(101, lambda t: f"{int(round((t * 2.0 - 1.0) * 100)):+d}c")
SCALE_DRIVE_20 = _build_scale(81, lambda t: f"{t * 20.0:.1f}dB")
SCALE_DIST_DRIVE = _build_scale(91, lambda t: f"{-30.0 + t * 60.0:+.0f}dB")
SCALE_EQ_GAIN = _build_scale(61, lambda t: f"{-15.0 + t * 30.0:+.1f}dB")
SCALE_COMP_GAIN = _build_scale(61, lambda t: f"{-30.0 + t * 60.0:+.0f}dB")
SCALE_BLEND = _build_scale(
    101,
    lambda t: "LP" if t < 0.05 else ("BP" if abs(t - 0.5) < 0.05 else ("HP" if t > 0.95 else f"{int(round(t * 100))}%")),
)
SCALE_FRAME = _build_scale(129, lambda t: f"#{int(round(t * 256))}")
SCALE_PHASE = _build_scale(73, lambda t: f"{int(round(t * 360))}°")
SCALE_GLIDE = _build_scale(101, lambda t: "0ms" if t <= 0.01 else fmt_time_s(2.0 ** (-10.0 + t * 14.0)))
SCALE_LFO_FREQ = _build_scale(101, lambda t: fmt_lfo_hz(vital_exp_hz(t, -7.0, 9.0)))
SCALE_VERB_DECAY = _build_scale(101, lambda t: fmt_time_s(2.0 ** (-6.0 + t * 12.0)))
SCALE_POWER = _build_scale(81, lambda t: f"{(t * 2.0 - 1.0) * 20.0:+.1f}")


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


# Map internal Vital parameter ID -> exact Vital display_name (rdfs:label)
PARAM_DISPLAY = {
    "volume": "Volume",
    "polyphony": "Polyphony",
    "oversampling": "Oversampling",
    "legato": "Legato",
    "voice_transpose": "Voice Transpose",
    "voice_tune": "Voice Tune",
    "voice_priority": "Voice Priority",
    "stereo_mode": "Stereo Mode",
    "stereo_routing": "Stereo Routing",
    "portamento_time": "Portamento Time",
    "portamento_slope": "Portamento Slope",
    "portamento_force": "Portamento Force",
    "velocity_track": "Velocity Track",
    "mod_wheel": "Mod Wheel",
    "pitch_bend_range": "Pitch Bend Range",
    "macro_control_1": "Macro 1",
    "macro_control_2": "Macro 2",
    "macro_control_3": "Macro 3",
    "macro_control_4": "Macro 4",

    # Sample Osc
    "sample_on": "Sample Switch",
    "sample_level": "Sample Level",
    "sample_transpose": "Sample Transpose",
    "sample_tune": "Sample Tune",
    "sample_pan": "Sample Pan",
    "sample_loop": "Sample Loop",
    "sample_keytrack": "Sample Keytrack",
    "sample_random_phase": "Sample Random Phase",
    "sample_destination": "Sample Destination",

    # Distortion
    "distortion_on": "Distortion Switch",
    "distortion_type": "Distortion Type",
    "distortion_drive": "Distortion Drive",
    "distortion_mix": "Distortion Mix",
    "distortion_filter_cutoff": "Distortion Filter Cutoff",
    "distortion_filter_resonance": "Distortion Filter Resonance",

    # Chorus
    "chorus_on": "Chorus Switch",
    "chorus_dry_wet": "Chorus Mix",
    "chorus_feedback": "Chorus Feedback",
    "chorus_mod_depth": "Chorus Mod Depth",
    "chorus_tempo": "Chorus Tempo",
    "chorus_cutoff": "Chorus Filter Cutoff",
    "chorus_voices": "Chorus Voices",

    # Delay
    "delay_on": "Delay Switch",
    "delay_dry_wet": "Delay Mix",
    "delay_feedback": "Delay Feedback",
    "delay_style": "Delay Style",
    "delay_tempo": "Delay Tempo",
    "delay_filter_cutoff": "Delay Filter Cutoff",
    "delay_filter_spread": "Delay Filter Spread",

    # Reverb
    "reverb_on": "Reverb Switch",
    "reverb_dry_wet": "Reverb Mix",
    "reverb_decay_time": "Reverb Decay Time",
    "reverb_size": "Reverb Size",
    "reverb_pre_low_cutoff": "Reverb Pre Low Cutoff",
    "reverb_pre_high_cutoff": "Reverb Pre High Cutoff",
    "reverb_chorus_amount": "Reverb Chorus Amount",

    # Compressor
    "compressor_on": "Compressor Switch",
    "compressor_mix": "Compressor Mix",
    "compressor_attack": "Compressor Attack",
    "compressor_release": "Compressor Release",
    "compressor_enabled_bands": "Compressor Enabled Bands",
    "compressor_low_gain": "Compressor Low Gain",
    "compressor_band_gain": "Compressor Band Gain",
    "compressor_high_gain": "Compressor High Gain",

    # EQ
    "eq_on": "EQ Switch",
    "eq_low_mode": "EQ Low Mode",
    "eq_low_cutoff": "EQ Low Cutoff",
    "eq_low_gain": "EQ Low Gain",
    "eq_band_cutoff": "EQ Band Cutoff",
    "eq_band_gain": "EQ Band Gain",
    "eq_high_mode": "EQ High Mode",
    "eq_high_cutoff": "EQ High Cutoff",
    "eq_high_gain": "EQ High Gain",

    # Flanger
    "flanger_on": "Flanger Switch",
    "flanger_dry_wet": "Flanger Mix",
    "flanger_feedback": "Flanger Feedback",
    "flanger_mod_depth": "Flanger Mod Depth",
    "flanger_center": "Flanger Center",
    "flanger_tempo": "Flanger Tempo",

    # Phaser
    "phaser_on": "Phaser Switch",
    "phaser_dry_wet": "Phaser Mix",
    "phaser_feedback": "Phaser Feedback",
    "phaser_mod_depth": "Phaser Mod Depth",
    "phaser_center": "Phaser Center",
    "phaser_tempo": "Phaser Tempo",
}

for _oi in (1, 2, 3):
    PARAM_DISPLAY[f"osc_{_oi}_on"] = f"Oscillator {_oi} Switch"
    PARAM_DISPLAY[f"osc_{_oi}_level"] = f"Oscillator {_oi} Level"
    PARAM_DISPLAY[f"osc_{_oi}_pan"] = f"Oscillator {_oi} Pan"
    PARAM_DISPLAY[f"osc_{_oi}_transpose"] = f"Oscillator {_oi} Transpose"
    PARAM_DISPLAY[f"osc_{_oi}_tune"] = f"Oscillator {_oi} Tune"
    PARAM_DISPLAY[f"osc_{_oi}_wave_frame"] = f"Oscillator {_oi} Wave Frame"
    PARAM_DISPLAY[f"osc_{_oi}_unison_voices"] = f"Oscillator {_oi} Unison Voices"
    PARAM_DISPLAY[f"osc_{_oi}_unison_detune"] = f"Oscillator {_oi} Unison Detune"
    PARAM_DISPLAY[f"osc_{_oi}_unison_blend"] = f"Oscillator {_oi} Blend"
    PARAM_DISPLAY[f"osc_{_oi}_phase"] = f"Oscillator {_oi} Phase"
    PARAM_DISPLAY[f"osc_{_oi}_random_phase"] = f"Oscillator {_oi} Phase Randomization"
    PARAM_DISPLAY[f"osc_{_oi}_spectral_morph_type"] = f"Oscillator {_oi} Frequency Morph Type"
    PARAM_DISPLAY[f"osc_{_oi}_spectral_morph_amount"] = f"Oscillator {_oi} Frequency Morph Amount"
    PARAM_DISPLAY[f"osc_{_oi}_distortion_type"] = f"Oscillator {_oi} Distortion Type"
    PARAM_DISPLAY[f"osc_{_oi}_distortion_amount"] = f"Oscillator {_oi} Distortion Amount"
    PARAM_DISPLAY[f"osc_{_oi}_destination"] = f"Oscillator {_oi} Destination"

for _fid in ("1", "2", "fx"):
    PARAM_DISPLAY[f"filter_{_fid}_on"] = f"Filter {_fid} Switch"
    PARAM_DISPLAY[f"filter_{_fid}_model"] = f"Filter {_fid} Model"
    PARAM_DISPLAY[f"filter_{_fid}_style"] = f"Filter {_fid} Style"
    PARAM_DISPLAY[f"filter_{_fid}_cutoff"] = f"Filter {_fid} Cutoff"
    PARAM_DISPLAY[f"filter_{_fid}_resonance"] = f"Filter {_fid} Resonance"
    PARAM_DISPLAY[f"filter_{_fid}_drive"] = f"Filter {_fid} Drive"
    PARAM_DISPLAY[f"filter_{_fid}_mix"] = f"Filter {_fid} Mix"
    PARAM_DISPLAY[f"filter_{_fid}_blend"] = f"Filter {_fid} Blend"
    PARAM_DISPLAY[f"filter_{_fid}_keytrack"] = f"Filter {_fid} Key Track"
    PARAM_DISPLAY[f"filter_{_fid}_formant_x"] = f"Filter {_fid} Formant X"
    PARAM_DISPLAY[f"filter_{_fid}_formant_y"] = f"Filter {_fid} Formant Y"
    PARAM_DISPLAY[f"filter_{_fid}_osc1_input"] = f"Filter {_fid} OSC 1 Input"
    PARAM_DISPLAY[f"filter_{_fid}_osc2_input"] = f"Filter {_fid} OSC 2 Input"
    PARAM_DISPLAY[f"filter_{_fid}_osc3_input"] = f"Filter {_fid} OSC 3 Input"
    PARAM_DISPLAY[f"filter_{_fid}_sample_input"] = f"Filter {_fid} SAMPLE Input"
    PARAM_DISPLAY[f"filter_{_fid}_filter_input"] = f"Filter {_fid} FILTER Input"

for _ei in range(1, 7):
    PARAM_DISPLAY[f"env_{_ei}_delay"] = f"Envelope {_ei} Delay"
    PARAM_DISPLAY[f"env_{_ei}_attack"] = f"Envelope {_ei} Attack"
    PARAM_DISPLAY[f"env_{_ei}_hold"] = f"Envelope {_ei} Hold"
    PARAM_DISPLAY[f"env_{_ei}_decay"] = f"Envelope {_ei} Decay"
    PARAM_DISPLAY[f"env_{_ei}_sustain"] = f"Envelope {_ei} Sustain"
    PARAM_DISPLAY[f"env_{_ei}_release"] = f"Envelope {_ei} Release"
    PARAM_DISPLAY[f"env_{_ei}_attack_power"] = f"Envelope {_ei} Attack Power"
    PARAM_DISPLAY[f"env_{_ei}_decay_power"] = f"Envelope {_ei} Decay Power"
    PARAM_DISPLAY[f"env_{_ei}_release_power"] = f"Envelope {_ei} Release Power"

for _li in range(1, 7):
    PARAM_DISPLAY[f"lfo_{_li}_frequency"] = f"LFO {_li} Frequency"
    PARAM_DISPLAY[f"lfo_{_li}_tempo"] = f"LFO {_li} Tempo"
    PARAM_DISPLAY[f"lfo_{_li}_sync"] = f"LFO {_li} Sync"
    PARAM_DISPLAY[f"lfo_{_li}_sync_type"] = f"LFO {_li} Sync Type"
    PARAM_DISPLAY[f"lfo_{_li}_phase"] = f"LFO {_li} Phase"
    PARAM_DISPLAY[f"lfo_{_li}_delay_time"] = f"LFO {_li} Delay"
    PARAM_DISPLAY[f"lfo_{_li}_fade_time"] = f"LFO {_li} Fade In"
    PARAM_DISPLAY[f"lfo_{_li}_smooth_time"] = f"LFO {_li} Smooth Time"
    PARAM_DISPLAY[f"lfo_{_li}_stereo"] = f"LFO {_li} Stereo"

for _ri in (1, 2):
    PARAM_DISPLAY[f"random_{_ri}_style"] = f"Random LFO {_ri} Style"
    PARAM_DISPLAY[f"random_{_ri}_frequency"] = f"Random LFO {_ri} Frequency"
    PARAM_DISPLAY[f"random_{_ri}_tempo"] = f"Random LFO {_ri} Tempo"
    PARAM_DISPLAY[f"random_{_ri}_sync"] = f"Random LFO {_ri} Sync"
    PARAM_DISPLAY[f"random_{_ri}_stereo"] = f"Random LFO {_ri} Stereo"

for _mi in range(1, 65):
    PARAM_DISPLAY[f"modulation_{_mi}_amount"] = f"Modulation {_mi} Amount"
    PARAM_DISPLAY[f"modulation_{_mi}_power"] = f"Modulation {_mi} Power"
    PARAM_DISPLAY[f"modulation_{_mi}_bipolar"] = f"Modulation {_mi} Bipolar"
    PARAM_DISPLAY[f"modulation_{_mi}_stereo"] = f"Modulation {_mi} Stereo"
    PARAM_DISPLAY[f"modulation_{_mi}_bypass"] = f"Modulation {_mi} Bypass"


# ------------------------------------------------------------------------------
# Main Widget Class
# ------------------------------------------------------------------------------
class zynthian_widget_vitalium(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)

        self.next_update = 0.0
        self.active_tab = "Macro"

        # Per-tab sub-selection state (drives dynamic 4-encoder binding)
        self.macro_bank = 0          # 0: Macros 1-4, 1: Glide & Pitch, 2: Output & Mod, 3: Mod Slots 1..64
        self.mod_slot = 1            # 1..64
        self.mod_view = 0            # 0: Active slots, 1: 1-16, 2: 17-32, 3: 33-48, 4: 49-64
        self.osc_idx = 0             # 0: OSC 1, 1: OSC 2, 2: OSC 3, 3: Sample
        self.osc_bank = 0            # 0: Tone & Frame, 1: Unison & Pitch, 2: Morph & Phase
        self.flt_idx = 0             # 0: Filter 1, 1: Filter 2, 2: FX Filter
        self.flt_bank = 0            # 0: Core (Cut/Res/Drv/Mix), 1: Blend & KeyTrk, 2: Model & Style
        self.env_idx = 0             # 0..5 -> ENV 1..6
        self.env_bank = 0            # 0: ADSR, 1: Delay/Hold/Curves
        self.lfo_idx = 0             # 0..7 -> LFO_SLOTS
        self.lfo_bank = 0            # 0: Rate & Phase, 1: Timing & Stereo
        self.fx_idx = 0              # 0..7 -> FX_MODULES

        self.eco_on = False
        self._eco_backup = {}

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
            k_sym = _norm_key(sym)
            if k_sym:
                idx[k_sym] = z
            zname = getattr(z, "name", None)
            if zname:
                k_name = _norm_key(zname)
                if k_name:
                    idx[k_name] = z
        self._ctrl_index = idx

    def _get_zctrl(self, vital_id):
        if not self.processor:
            return None
        z = self._ctrl_index.get(_norm_key(vital_id))
        if z is not None:
            return z
        disp = PARAM_DISPLAY.get(vital_id)
        if disp:
            return self._ctrl_index.get(_norm_key(disp))
        return None

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

        # Global & Macros
        for i in range(1, 5):
            enh(f"macro_control_{i}", SCALE_PERCENT)
        enh("volume", SCALE_PERCENT)
        enh("mod_wheel", SCALE_PERCENT)
        enh("polyphony", (POLY_LABELS, [i / (len(POLY_LABELS) - 1) for i in range(len(POLY_LABELS))]))
        enh("oversampling", _enum_scale(OVERSAMPLING_NAMES))
        enh("legato", _enum_scale(TOGGLE_OFF_ON))
        enh("voice_transpose", SCALE_TRANSPOSE)
        enh("voice_tune", SCALE_TUNE_CENTS)
        enh("voice_priority", _enum_scale(VOICE_PRIORITIES))
        enh("stereo_mode", _enum_scale(STEREO_MODES))
        enh("stereo_routing", SCALE_PERCENT)
        enh("portamento_time", SCALE_GLIDE)
        enh("portamento_slope", SCALE_BIPOLAR)
        enh("portamento_force", _enum_scale(TOGGLE_OFF_ON))
        enh("velocity_track", SCALE_BIPOLAR)

        # Oscillators 1..3 & Sample
        for oi in (1, 2, 3):
            enh(f"osc_{oi}_on", _enum_scale(TOGGLE_OFF_ON))
            enh(f"osc_{oi}_level", SCALE_PERCENT)
            enh(f"osc_{oi}_pan", SCALE_PAN)
            enh(f"osc_{oi}_transpose", SCALE_TRANSPOSE)
            enh(f"osc_{oi}_tune", SCALE_TUNE_CENTS)
            enh(f"osc_{oi}_wave_frame", SCALE_FRAME)
            enh(f"osc_{oi}_unison_voices", (UNISON_VOICES_LABELS, [i / 15.0 for i in range(16)]))
            enh(f"osc_{oi}_unison_detune", SCALE_PERCENT)
            enh(f"osc_{oi}_unison_blend", SCALE_PERCENT)
            enh(f"osc_{oi}_phase", SCALE_PHASE)
            enh(f"osc_{oi}_random_phase", SCALE_PERCENT)
            enh(f"osc_{oi}_spectral_morph_type", _enum_scale(SPECTRAL_MORPHS))
            enh(f"osc_{oi}_spectral_morph_amount", SCALE_PERCENT)
            enh(f"osc_{oi}_distortion_type", _enum_scale(PHASE_DISTS))
            enh(f"osc_{oi}_distortion_amount", SCALE_PERCENT)
            enh(f"osc_{oi}_destination", _enum_scale(DESTINATIONS))

        enh("sample_on", _enum_scale(TOGGLE_OFF_ON))
        enh("sample_level", SCALE_PERCENT)
        enh("sample_transpose", SCALE_TRANSPOSE)
        enh("sample_tune", SCALE_TUNE_CENTS)
        enh("sample_pan", SCALE_PAN)
        enh("sample_loop", _enum_scale(TOGGLE_OFF_ON))
        enh("sample_keytrack", _enum_scale(TOGGLE_OFF_ON))
        enh("sample_random_phase", _enum_scale(TOGGLE_OFF_ON))
        enh("sample_destination", _enum_scale(DESTINATIONS))

        # Filters 1, 2, FX
        for fid in ("1", "2", "fx"):
            enh(f"filter_{fid}_on", _enum_scale(TOGGLE_OFF_ON))
            enh(f"filter_{fid}_model", _enum_scale(FILTER_MODELS))
            enh(f"filter_{fid}_style", _enum_scale(FILTER_STYLES))
            enh(f"filter_{fid}_cutoff", SCALE_CUTOFF)
            enh(f"filter_{fid}_resonance", SCALE_PERCENT)
            enh(f"filter_{fid}_drive", SCALE_DRIVE_20)
            enh(f"filter_{fid}_mix", SCALE_PERCENT)
            enh(f"filter_{fid}_blend", SCALE_BLEND)
            enh(f"filter_{fid}_keytrack", SCALE_BIPOLAR)
            enh(f"filter_{fid}_formant_x", SCALE_PERCENT)
            enh(f"filter_{fid}_formant_y", SCALE_PERCENT)
            for inp in ("osc1", "osc2", "osc3", "sample", "filter"):
                enh(f"filter_{fid}_{inp}_input", _enum_scale(TOGGLE_OFF_ON))

        # Envelopes 1..6
        for ei in range(1, 7):
            enh(f"env_{ei}_delay", SCALE_ENVSHORT)
            enh(f"env_{ei}_attack", SCALE_ENVTIME)
            enh(f"env_{ei}_hold", SCALE_ENVSHORT)
            enh(f"env_{ei}_decay", SCALE_ENVTIME)
            enh(f"env_{ei}_sustain", SCALE_PERCENT)
            enh(f"env_{ei}_release", SCALE_ENVTIME)
            enh(f"env_{ei}_attack_power", SCALE_POWER)
            enh(f"env_{ei}_decay_power", SCALE_POWER)
            enh(f"env_{ei}_release_power", SCALE_POWER)

        # LFOs 1..6 & Random 1..2
        for li in range(1, 7):
            enh(f"lfo_{li}_frequency", SCALE_LFO_FREQ)
            enh(f"lfo_{li}_tempo", _enum_scale(SYNCED_TEMPOS))
            enh(f"lfo_{li}_sync", _enum_scale(FREQ_SYNC_NAMES))
            enh(f"lfo_{li}_sync_type", _enum_scale(LFO_TRIG_NAMES))
            enh(f"lfo_{li}_phase", SCALE_PHASE)
            enh(f"lfo_{li}_delay_time", SCALE_PERCENT)
            enh(f"lfo_{li}_fade_time", SCALE_PERCENT)
            enh(f"lfo_{li}_smooth_time", SCALE_GLIDE)
            enh(f"lfo_{li}_stereo", SCALE_BIPOLAR)
        for ri in (1, 2):
            enh(f"random_{ri}_style", _enum_scale(RANDOM_STYLES))
            enh(f"random_{ri}_frequency", SCALE_LFO_FREQ)
            enh(f"random_{ri}_tempo", _enum_scale(SYNCED_TEMPOS))
            enh(f"random_{ri}_sync", _enum_scale(FREQ_SYNC_NAMES))
            enh(f"random_{ri}_stereo", _enum_scale(TOGGLE_OFF_ON))

        # FX Suite
        for _, _, on_key in FX_MODULES:
            enh(on_key, _enum_scale(TOGGLE_OFF_ON))
        enh("distortion_type", _enum_scale(DIST_TYPES))
        enh("distortion_drive", SCALE_DIST_DRIVE)
        enh("distortion_mix", SCALE_PERCENT)
        enh("distortion_filter_cutoff", SCALE_CUTOFF)
        enh("chorus_dry_wet", SCALE_PERCENT)
        enh("chorus_feedback", SCALE_BIPOLAR)
        enh("chorus_mod_depth", SCALE_PERCENT)
        enh("chorus_tempo", _enum_scale(MOD_TEMPOS))
        enh("chorus_cutoff", SCALE_CUTOFF)
        enh("delay_dry_wet", SCALE_PERCENT)
        enh("delay_feedback", SCALE_BIPOLAR)
        enh("delay_style", _enum_scale(DELAY_STYLES))
        enh("delay_tempo", _enum_scale(DELAY_TEMPOS))
        enh("delay_filter_cutoff", SCALE_CUTOFF)
        enh("reverb_dry_wet", SCALE_PERCENT)
        enh("reverb_decay_time", SCALE_VERB_DECAY)
        enh("reverb_size", SCALE_PERCENT)
        enh("reverb_pre_high_cutoff", SCALE_CUTOFF)
        enh("reverb_chorus_amount", SCALE_PERCENT)
        enh("compressor_mix", SCALE_PERCENT)
        enh("compressor_attack", SCALE_PERCENT)
        enh("compressor_release", SCALE_PERCENT)
        enh("compressor_enabled_bands", _enum_scale(COMP_BANDS))
        enh("compressor_low_gain", SCALE_COMP_GAIN)
        enh("compressor_band_gain", SCALE_COMP_GAIN)
        enh("compressor_high_gain", SCALE_COMP_GAIN)
        enh("eq_low_mode", _enum_scale(EQ_LOW_MODES))
        enh("eq_high_mode", _enum_scale(EQ_HIGH_MODES))
        for band in ("low", "band", "high"):
            enh(f"eq_{band}_cutoff", SCALE_CUTOFF)
            enh(f"eq_{band}_gain", SCALE_EQ_GAIN)
        enh("flanger_dry_wet", SCALE_PERCENT)
        enh("flanger_feedback", SCALE_BIPOLAR)
        enh("flanger_mod_depth", SCALE_PERCENT)
        enh("flanger_center", SCALE_CUTOFF)
        enh("flanger_tempo", _enum_scale(MOD_TEMPOS))
        enh("phaser_dry_wet", SCALE_PERCENT)
        enh("phaser_feedback", SCALE_PERCENT)
        enh("phaser_mod_depth", SCALE_PERCENT)
        enh("phaser_center", SCALE_CUTOFF)
        enh("phaser_tempo", _enum_scale(MOD_TEMPOS))

        # Modulation Matrix Slots 1..64
        for mi in range(1, 65):
            enh(f"modulation_{mi}_amount", SCALE_BIPOLAR)
            enh(f"modulation_{mi}_power", SCALE_POWER)
            enh(f"modulation_{mi}_bipolar", _enum_scale(TOGGLE_OFF_ON))
            enh(f"modulation_{mi}_stereo", _enum_scale(TOGGLE_OFF_ON))
            enh(f"modulation_{mi}_bypass", _enum_scale(TOGGLE_OFF_ON))

    # --------------------------------------------------------------------------
    # Dynamic Page Definitions (1 Page per Tab -> 4 Physical Encoders)
    # --------------------------------------------------------------------------
    def _flt_id(self):
        return ("1", "2", "fx")[self.flt_idx]

    def _tab_items(self, tab_name):
        if tab_name == "Macro":
            if self.macro_bank == 0:
                return [
                    ("macro_control_1", "Macro 1"),
                    ("macro_control_2", "Macro 2"),
                    ("macro_control_3", "Macro 3"),
                    ("macro_control_4", "Macro 4"),
                ]
            if self.macro_bank == 1:
                return [
                    ("portamento_time", "Glide"),
                    ("voice_transpose", "Transp"),
                    ("voice_tune",      "Tune"),
                    ("velocity_track",  "VelTrk"),
                ]
            if self.macro_bank == 2:
                return [
                    ("mod_wheel",      "ModWhl"),
                    ("stereo_routing", "Stereo"),
                    ("polyphony",      "Poly"),
                    ("volume",         "Volume"),
                ]
            ms = self.mod_slot
            return [
                (f"modulation_{ms}_amount",  f"M{ms} Amt"),
                (f"modulation_{ms}_power",   f"M{ms} Crv"),
                (f"modulation_{ms}_bipolar", f"M{ms} Bi"),
                (f"modulation_{ms}_bypass",  f"M{ms} Byp"),
            ]

        if tab_name == "Osc":
            if self.osc_idx == 3:
                if self.osc_bank == 0:
                    return [
                        ("sample_level",     "Smp Lvl"),
                        ("sample_transpose", "Smp Trns"),
                        ("sample_tune",      "Smp Tune"),
                        ("sample_pan",       "Smp Pan"),
                    ]
                return [
                    ("sample_loop",         "Smp Loop"),
                    ("sample_keytrack",     "Smp KeyT"),
                    ("sample_random_phase", "Smp RndP"),
                    ("sample_destination",  "Smp Dest"),
                ]
            oi = self.osc_idx + 1
            if self.osc_bank == 0:
                return [
                    (f"osc_{oi}_level",                  f"O{oi} Level"),
                    (f"osc_{oi}_wave_frame",             f"O{oi} Frame"),
                    (f"osc_{oi}_spectral_morph_amount",  f"O{oi} Morph"),
                    (f"osc_{oi}_distortion_amount",      f"O{oi} Dist"),
                ]
            if self.osc_bank == 1:
                return [
                    (f"osc_{oi}_transpose",     f"O{oi} Trns"),
                    (f"osc_{oi}_tune",          f"O{oi} Tune"),
                    (f"osc_{oi}_unison_voices", f"O{oi} UniV"),
                    (f"osc_{oi}_unison_detune", f"O{oi} Detn"),
                ]
            return [
                (f"osc_{oi}_spectral_morph_type", f"O{oi} MrphT"),
                (f"osc_{oi}_distortion_type",     f"O{oi} DstT"),
                (f"osc_{oi}_phase",               f"O{oi} Phase"),
                (f"osc_{oi}_pan",                 f"O{oi} Pan"),
            ]

        if tab_name == "Filter":
            fid = self._flt_id()
            tag = "FXF" if fid == "fx" else f"F{fid}"
            if self.flt_bank == 0:
                return [
                    (f"filter_{fid}_cutoff",    f"{tag} Cut"),
                    (f"filter_{fid}_resonance", f"{tag} Reso"),
                    (f"filter_{fid}_drive",     f"{tag} Drv"),
                    (f"filter_{fid}_mix",       f"{tag} Mix"),
                ]
            if self.flt_bank == 1:
                return [
                    (f"filter_{fid}_blend",     f"{tag} Blnd"),
                    (f"filter_{fid}_keytrack",  f"{tag} KeyT"),
                    (f"filter_{fid}_formant_x", f"{tag} FrmX"),
                    (f"filter_{fid}_formant_y", f"{tag} FrmY"),
                ]
            return [
                (f"filter_{fid}_model",  f"{tag} Mdl"),
                (f"filter_{fid}_style",  f"{tag} Styl"),
                (f"filter_{fid}_on",     f"{tag} On"),
                (f"filter_{fid}_cutoff", f"{tag} Cut"),
            ]

        if tab_name == "Env":
            ei = self.env_idx + 1
            if self.env_bank == 0:
                return [
                    (f"env_{ei}_attack",  f"E{ei} Att"),
                    (f"env_{ei}_decay",   f"E{ei} Dec"),
                    (f"env_{ei}_sustain", f"E{ei} Sus"),
                    (f"env_{ei}_release", f"E{ei} Rel"),
                ]
            return [
                (f"env_{ei}_delay",         f"E{ei} Dly"),
                (f"env_{ei}_hold",          f"E{ei} Hld"),
                (f"env_{ei}_decay_power",   f"E{ei} DecC"),
                (f"env_{ei}_release_power", f"E{ei} RelC"),
            ]

        if tab_name == "LFO":
            lkey, ltitle, is_rnd = LFO_SLOTS[self.lfo_idx]
            short = ltitle.replace("LFO ", "L").replace("RND ", "R")
            if is_rnd:
                return [
                    (f"{lkey}_style",     f"{short} Styl"),
                    (f"{lkey}_tempo",     f"{short} Rate"),
                    (f"{lkey}_sync",      f"{short} Sync"),
                    (f"{lkey}_stereo",    f"{short} Ster"),
                ]
            sync_z = self._get_zctrl(f"{lkey}_sync")
            is_secs = ((sync_z.get_value2index() or 0) == 0) if sync_z else False
            rate_k = f"{lkey}_frequency" if is_secs else f"{lkey}_tempo"
            if self.lfo_bank == 0:
                return [
                    (rate_k,              f"{short} Rate"),
                    (f"{lkey}_sync",      f"{short} Sync"),
                    (f"{lkey}_phase",     f"{short} Phs"),
                    (f"{lkey}_smooth_time", f"{short} Smth"),
                ]
            return [
                (f"{lkey}_sync_type",  f"{short} Mode"),
                (f"{lkey}_delay_time", f"{short} Dly"),
                (f"{lkey}_fade_time",  f"{short} Fade"),
                (f"{lkey}_stereo",     f"{short} Ster"),
            ]

        # FX tab (8 modules)
        fx_id = FX_MODULES[self.fx_idx][0]
        if fx_id == "dist":
            return [
                ("distortion_type",          "Dst Type"),
                ("distortion_drive",         "Dst Drv"),
                ("distortion_mix",           "Dst Mix"),
                ("distortion_filter_cutoff", "Dst Cut"),
            ]
        if fx_id == "chorus":
            return [
                ("chorus_dry_wet",   "Chr Mix"),
                ("chorus_feedback",  "Chr FB"),
                ("chorus_mod_depth", "Chr Dpth"),
                ("chorus_tempo",     "Chr Rate"),
            ]
        if fx_id == "delay":
            return [
                ("delay_dry_wet",       "Dly Mix"),
                ("delay_feedback",      "Dly FB"),
                ("delay_tempo",         "Dly Time"),
                ("delay_filter_cutoff", "Dly Cut"),
            ]
        if fx_id == "reverb":
            return [
                ("reverb_dry_wet",         "Vrb Mix"),
                ("reverb_decay_time",      "Vrb Dec"),
                ("reverb_size",            "Vrb Size"),
                ("reverb_pre_high_cutoff", "Vrb Damp"),
            ]
        if fx_id == "comp":
            return [
                ("compressor_mix",       "Cmp Mix"),
                ("compressor_low_gain",  "Cmp Low"),
                ("compressor_band_gain", "Cmp Mid"),
                ("compressor_high_gain", "Cmp High"),
            ]
        if fx_id == "eq":
            return [
                ("eq_low_gain",    "EQ Low"),
                ("eq_band_gain",   "EQ Mid"),
                ("eq_high_gain",   "EQ High"),
                ("eq_band_cutoff", "EQ MidF"),
            ]
        if fx_id == "flang":
            return [
                ("flanger_dry_wet",   "Flg Mix"),
                ("flanger_feedback",  "Flg FB"),
                ("flanger_mod_depth", "Flg Dpth"),
                ("flanger_center",    "Flg Cntr"),
            ]
        return [
            ("phaser_dry_wet",   "Phs Mix"),
            ("phaser_feedback",  "Phs FB"),
            ("phaser_mod_depth", "Phs Dpth"),
            ("phaser_center",    "Phs Cntr"),
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
            logging.debug(f"Vitalium widget: live swap error => {e}")

    def _sync_zyngui_list(self, target_tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page_by_title(target_tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Vitalium widget: sync list error => {e}")

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
        return f"{int(round(zynthian_widget_vitalium._norm(zctrl) * 100))}%"

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
        if t == "Macro":
            keys = [
                "macro_control_1", "macro_control_2", "macro_control_3", "macro_control_4",
                "polyphony", "oversampling", "legato", "voice_transpose", "voice_tune",
                "voice_priority", "stereo_mode", "stereo_routing", "portamento_time",
                "velocity_track", "mod_wheel", "volume",
            ]
            if self.macro_bank == 3:
                ms = self.mod_slot
                keys.extend([
                    f"modulation_{ms}_amount", f"modulation_{ms}_power",
                    f"modulation_{ms}_bipolar", f"modulation_{ms}_stereo",
                    f"modulation_{ms}_bypass",
                ])
                for mi in range(1, 65):
                    keys.append(f"modulation_{mi}_amount")
            return keys
        if t == "Osc":
            if self.osc_idx == 3:
                return [
                    "sample_on", "sample_level", "sample_transpose", "sample_tune",
                    "sample_pan", "sample_loop", "sample_keytrack", "sample_random_phase",
                    "sample_destination",
                ]
            oi = self.osc_idx + 1
            return [
                f"osc_{oi}_on", f"osc_{oi}_level", f"osc_{oi}_pan",
                f"osc_{oi}_transpose", f"osc_{oi}_tune", f"osc_{oi}_wave_frame",
                f"osc_{oi}_unison_voices", f"osc_{oi}_unison_detune", f"osc_{oi}_phase",
                f"osc_{oi}_spectral_morph_type", f"osc_{oi}_spectral_morph_amount",
                f"osc_{oi}_distortion_type", f"osc_{oi}_distortion_amount", f"osc_{oi}_destination",
            ]
        if t == "Filter":
            keys = []
            for fid in ("1", "2", "fx"):
                keys.extend([
                    f"filter_{fid}_on", f"filter_{fid}_model", f"filter_{fid}_style",
                    f"filter_{fid}_cutoff", f"filter_{fid}_resonance", f"filter_{fid}_drive",
                    f"filter_{fid}_mix", f"filter_{fid}_blend", f"filter_{fid}_keytrack",
                    f"filter_{fid}_formant_x", f"filter_{fid}_formant_y",
                ])
            return keys
        if t == "Env":
            ei = self.env_idx + 1
            keys = ["env_1_attack", "env_1_decay", "env_1_sustain", "env_1_release"]
            keys.extend([
                f"env_{ei}_delay", f"env_{ei}_attack", f"env_{ei}_hold",
                f"env_{ei}_decay", f"env_{ei}_sustain", f"env_{ei}_release",
                f"env_{ei}_attack_power", f"env_{ei}_decay_power", f"env_{ei}_release_power",
            ])
            return keys
        if t == "LFO":
            lkey, _, is_rnd = LFO_SLOTS[self.lfo_idx]
            if is_rnd:
                return [f"{lkey}_style", f"{lkey}_frequency", f"{lkey}_tempo", f"{lkey}_sync", f"{lkey}_stereo"]
            return [
                f"{lkey}_frequency", f"{lkey}_tempo", f"{lkey}_sync", f"{lkey}_sync_type",
                f"{lkey}_phase", f"{lkey}_delay_time", f"{lkey}_fade_time",
                f"{lkey}_smooth_time", f"{lkey}_stereo",
            ]
        # FX
        keys = [on_k for _, _, on_k in FX_MODULES] + [k for k, _ in self._tab_items("FX")]
        keys.extend(["delay_style", "compressor_enabled_bands", "eq_low_cutoff", "eq_high_cutoff", "volume"])
        return keys

    def _state_snapshot(self):
        vals = tuple(round(self._norm(self._get_zctrl(k)), 4) for k in self._watched_keys())
        return (
            self.width, self.height, self.active_tab, self.eco_on,
            self.macro_bank, self.mod_slot, self.mod_view, self.osc_idx, self.osc_bank,
            self.flt_idx, self.flt_bank, self.env_idx, self.env_bank,
            self.lfo_idx, self.lfo_bank, self.fx_idx,
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
    # Drawing Primitives
    # --------------------------------------------------------------------------
    def _font(self, size, bold=False):
        key = (size, bold)
        if key not in self._font_cache:
            fam = zynthian_gui_config.font_family
            self._font_cache[key] = (fam, size, "bold") if bold else (fam, size)
        return self._font_cache[key]

    def _fs(self, scale=1.0):
        base = max(9, min(13, self.height // 34))
        return max(7, int(round(base * scale)))

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
        lbl_h = 16
        val_h = 15
        tx0, tx1 = x0 + pad, x1 - pad
        ty0 = y0 + lbl_h + 2
        ty1 = y1 - val_h - 3

        c.create_text((x0 + x1) / 2, y0 + lbl_h / 2 + 1, text=label,
                      fill=COL_TEXT, font=self._font(self._fs(0.82), bold=True))
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
                      fill=COL_DIM, font=self._font(self._fs(0.76)))

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

        if self.active_tab == "Macro":
            self._draw_tab_macro(bx0, by0, bx1, by1)
        elif self.active_tab == "Osc":
            self._draw_tab_osc(bx0, by0, bx1, by1)
        elif self.active_tab == "Filter":
            self._draw_tab_filter(bx0, by0, bx1, by1)
        elif self.active_tab == "Env":
            self._draw_tab_env(bx0, by0, bx1, by1)
        elif self.active_tab == "LFO":
            self._draw_tab_lfo(bx0, by0, bx1, by1)
        elif self.active_tab == "FX":
            self._draw_tab_fx(bx0, by0, bx1, by1)

    def _draw_header(self, x0, y0, x1, y1):
        c = self.widget_canvas
        total_w = x1 - x0
        eco_w = max(56, int(total_w * 0.11))
        gap = 6
        tabs_w = total_w - eco_w - gap * len(TABS)
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

        # ECO CPU-tamer toggle button
        ex0 = x1 - eco_w
        eco_col = "#51cf66"
        c.create_rectangle(
            ex0, y0, x1, y1,
            fill=eco_col if self.eco_on else COL_PANEL_HI,
            outline=eco_col if self.eco_on else COL_BORDER,
            width=2 if self.eco_on else 1,
        )
        c.create_text(
            (ex0 + x1) / 2, (y0 + y1) / 2,
            text="ECO ●" if self.eco_on else "ECO",
            fill="#0d0e12" if self.eco_on else COL_TEXT,
            font=self._font(self._fs(0.92), bold=True),
        )
        self.hitboxes.append((ex0, y0, x1, y1, "eco", None))

    # --------------------------------------------------------------------------
    # TAB 1: MACRO & PERFORMANCE
    # --------------------------------------------------------------------------
    def _draw_tab_macro(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Macro"]
        gap = 6

        # Row 1: Quick Voice / CPU / Play Tiles
        tile_h = 38
        tiles = [
            ("Poly",    "polyphony",      "poly_cycle"),
            ("OverSmp", "oversampling",   "cycle"),
            ("Legato",  "legato",         "cycle"),
            ("Transp",  "voice_transpose","bank_pitch"),
            ("Voice",   "voice_priority", "cycle"),
            ("Stereo",  "stereo_mode",    "cycle"),
        ]
        tw = (x1 - x0 - gap * (len(tiles) - 1)) / len(tiles)
        for i, (lbl, key, hk) in enumerate(tiles):
            tx0 = x0 + i * (tw + gap)
            z = self._get_zctrl(key)
            self._draw_pill(tx0, y0, tx0 + tw, y0 + tile_h, lbl, False, accent,
                            hk, key, subtext=self._fmt(z)[:8])

        # Row 2: Encoder Bank Selector
        by0 = y0 + tile_h + 6
        bh = 34
        active_mods = [
            mi for mi in range(1, 65)
            if abs(self._norm(self._get_zctrl(f"modulation_{mi}_amount"), 0.5) - 0.5) > 0.005
        ]
        mm_lbl = f"Mod ({len(active_mods)})" if active_mods else "Mod Slots"
        self._draw_bank_bar(
            x0, by0, x1, by0 + bh,
            ["Macros 1-4", "Glide & Pitch", "Out & ModW", mm_lbl],
            self.macro_bank, accent, "macro_bank",
        )

        # Row 3: Full-screen Mod Slots view when bank == 3
        my0 = by0 + bh + 6
        if self.macro_bank == 3:
            self._draw_vital_mod_slots(x0, my0, x1, y1, accent, active_mods)
            return

        # Row 3: 4 Macro Faders (left 66%) + Mod Wheel & Volume (right 34%)
        perf_h = 40
        my1 = y1 - perf_h - 6

        left_w = int((x1 - x0) * 0.66)
        lx1 = x0 + left_w
        rx0 = lx1 + 6

        act_m = (self.macro_bank == 0)
        c.create_rectangle(x0, my0, lx1, my1, fill=COL_BG,
                           outline=accent if act_m else COL_BORDER, width=2 if act_m else 1)
        ipad = 4
        fw = (left_w - 2 * ipad - 3 * gap) / 4
        for i in range(4):
            fx0 = x0 + ipad + i * (fw + gap)
            self._draw_vfader(
                fx0, my0 + ipad, fx0 + fw, my1 - ipad,
                f"macro_control_{i + 1}", f"MACRO {i + 1}",
                accent if act_m else "#376996",
                bank_kind="macro_bank", bank_idx=0,
            )

        act_o = (self.macro_bank == 2)
        c.create_rectangle(rx0, my0, x1, my1, fill=COL_BG,
                           outline=accent if act_o else COL_BORDER, width=2 if act_o else 1)
        rw = (x1 - rx0 - 2 * ipad - gap) / 2
        self._draw_vfader(rx0 + ipad, my0 + ipad, rx0 + ipad + rw, my1 - ipad,
                          "mod_wheel", "MOD", "#ffd43b" if act_o else "#7a6a2a",
                          bank_kind="macro_bank", bank_idx=2)
        self._draw_vfader(rx0 + ipad + rw + gap, my0 + ipad, x1 - ipad, my1 - ipad,
                          "volume", "VOL", "#51cf66" if act_o else "#2e6b3a",
                          bank_kind="macro_bank", bank_idx=2)

        # Row 4: Performance strip (Glide, Transpose, Tune, VelTrack)
        py0 = my1 + 5
        act_p = (self.macro_bank == 1)
        c.create_rectangle(x0, py0, x1, y1, fill=COL_BG,
                           outline=accent if act_p else COL_BORDER, width=2 if act_p else 1)
        p_items = [
            ("portamento_time", "Glide",  False),
            ("voice_transpose", "Transp", True),
            ("voice_tune",      "Tune",   True),
            ("velocity_track",  "VelTrk", True),
        ]
        pw = (x1 - x0 - 3 * gap) / 4
        for i, (key, lbl, bip) in enumerate(p_items):
            px0 = x0 + i * (pw + gap)
            self._draw_param_box(px0, py0 + 2, px0 + pw, y1 - 2, key, lbl,
                                 accent if act_p else "#376996",
                                 bank_kind="macro_bank", bank_idx=1, bipolar=bip)

    def _draw_vital_mod_slots(self, x0, y0, x1, y1, accent, active_mods):
        c = self.widget_canvas
        gap = 6

        # Row A: Filter / Page Selector (Active | 1-16 | 17-32 | 33-48 | 49-64)
        vh = 32
        views = [
            f"Active ({len(active_mods)})",
            "1–16", "17–32", "33–48", "49–64",
        ]
        vw = (x1 - x0 - 4 * 4) / 5
        for i, vlbl in enumerate(views):
            vx0 = x0 + i * (vw + 4)
            self._draw_pill(vx0, y0, vx0 + vw, y0 + vh, vlbl,
                            i == self.mod_view, "#38d9a9", "mod_view", i)

        # Determine which 16 slots to display
        if self.mod_view == 0 and active_mods:
            slots = active_mods[:16]
            if self.mod_slot not in slots:
                self.mod_slot = slots[0]
        else:
            start = 1 if self.mod_view == 0 else ((self.mod_view - 1) * 16 + 1)
            slots = list(range(start, start + 16))

        # Row B: 2x8 Large Slot Buttons
        gy0 = y0 + vh + gap
        row_h = 36
        sw = (x1 - x0 - 7 * 4) / 8
        for idx, slot_num in enumerate(slots):
            r = idx // 8
            col = idx % 8
            sx0 = x0 + col * (sw + 4)
            sy0 = gy0 + r * (row_h + 4)
            amt_n = self._norm(self._get_zctrl(f"modulation_{slot_num}_amount"), 0.5)
            byp = self._norm(self._get_zctrl(f"modulation_{slot_num}_bypass"), 0.0) >= 0.5
            pct = int(round((amt_n * 2.0 - 1.0) * 100))
            is_act = abs(pct) > 0
            sub = "BYP" if byp else (f"{pct:+d}%" if is_act else "0%")
            self._draw_pill(sx0, sy0, sx0 + sw, sy0 + row_h, f"M{slot_num}",
                            slot_num == self.mod_slot,
                            COL_DIM if byp else (accent if is_act else "#376996"),
                            "mod_slot", slot_num, subtext=sub)

        # Row C: Bottom Inspector (Left: Curve Graph | Right: Toggles + Amount & Power Sliders)
        ms = self.mod_slot
        amt_k = f"modulation_{ms}_amount"
        pwr_k = f"modulation_{ms}_power"
        bip_k = f"modulation_{ms}_bipolar"
        ste_k = f"modulation_{ms}_stereo"
        byp_k = f"modulation_{ms}_bypass"

        iy0 = gy0 + 2 * (row_h + 4) + gap - 2
        cg_w = max(90, int((x1 - x0) * 0.34))
        cg_x1 = x0 + cg_w
        byp_on = self._norm(self._get_zctrl(byp_k), 0.0) >= 0.5
        bip_on = self._norm(self._get_zctrl(bip_k), 0.0) >= 0.5
        ste_on = self._norm(self._get_zctrl(ste_k), 0.0) >= 0.5

        c.create_rectangle(x0, iy0, cg_x1, y1, fill=COL_PANEL,
                           outline=COL_DIM if byp_on else accent, width=1)
        amt = (self._norm(self._get_zctrl(amt_k), 0.5) - 0.5) * 2.0
        pwr = (self._norm(self._get_zctrl(pwr_k), 0.5) - 0.5) * 2.0
        mid_cy = (iy0 + y1) / 2
        c.create_line(x0 + 6, mid_cy, cg_x1 - 6, mid_cy, fill=COL_GRID, dash=(2, 3))
        c.create_text(x0 + 8, iy0 + 11, text=f"MOD SLOT #{ms}", anchor="w",
                      fill=COL_DIM if byp_on else accent, font=self._font(self._fs(0.78), bold=True))
        pts = []
        p_exp = 2.0 ** (pwr * 2.4)
        for i in range(33):
            t = i / 32.0
            y_val = (t ** p_exp) * amt
            px = x0 + 8 + t * (cg_w - 16)
            py = mid_cy - y_val * ((y1 - iy0) * 0.38)
            pts.extend([px, py])
        c.create_line(pts, fill=COL_DIM if byp_on else (accent if abs(amt) > 0.01 else COL_DIM), width=2.6)

        rx0 = cg_x1 + gap
        tog_h = 34
        tw4 = (x1 - rx0 - 3 * 4) / 4
        self._draw_pill(rx0, iy0, rx0 + tw4, iy0 + tog_h,
                        "BYPASS" if byp_on else "ACTIVE ●", not byp_on, "#51cf66", "cycle", byp_k)
        self._draw_pill(rx0 + tw4 + 4, iy0, rx0 + 2 * tw4 + 4, iy0 + tog_h,
                        "Bi ±" if bip_on else "Uni +", bip_on, "#ffd43b", "cycle", bip_k)
        self._draw_pill(rx0 + 2 * (tw4 + 4), iy0, rx0 + 3 * tw4 + 8, iy0 + tog_h,
                        "Stereo", ste_on, "#cc5de8", "cycle", ste_k)
        self._draw_pill(rx0 + 3 * (tw4 + 4), iy0, x1, iy0 + tog_h,
                        "ZERO", False, "#ff6b6b", "mod_zero", ms)

        sl_y0 = iy0 + tog_h + 4
        sl_h = (y1 - sl_y0 - 4) / 2
        self._draw_param_box(rx0, sl_y0, x1, sl_y0 + sl_h, amt_k, f"M{ms} Amount", accent,
                             bank_kind="macro_bank", bank_idx=3, bipolar=True)
        self._draw_param_box(rx0, sl_y0 + sl_h + 4, x1, y1, pwr_k, f"M{ms} Power", accent,
                             bank_kind="macro_bank", bank_idx=3, bipolar=True)

    # --------------------------------------------------------------------------
    # TAB 2: OSCILLATORS (OSC 1-3 + Sample + Live Wavetable/Morph Scope)
    # --------------------------------------------------------------------------
    def _draw_tab_osc(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Osc"]
        gap = 6

        # Row 1: OSC 1 / OSC 2 / OSC 3 / SMP selector + Power pill + Bank bar
        r1_h = 34
        left_w = (x1 - x0) * 0.44
        ow = (left_w - 3 * gap) / 4
        for i, (lbl, on_k) in enumerate((("OSC 1", "osc_1_on"), ("OSC 2", "osc_2_on"),
                                         ("OSC 3", "osc_3_on"), ("SMP", "sample_on"))):
            ox0 = x0 + i * (ow + gap)
            is_on = self._norm(self._get_zctrl(on_k)) >= 0.5
            txt = f"● {lbl}" if is_on else lbl
            self._draw_pill(ox0, y0, ox0 + ow, y0 + r1_h, txt,
                            i == self.osc_idx, accent, "osc_idx", i)

        bank_labels = ["Sample Mix", "Sample Opts"] if self.osc_idx == 3 else ["Tone & Frame", "Unison & Pitch", "Morph & Phase"]
        self._draw_bank_bar(
            x0 + left_w + 6, y0, x1, y0 + r1_h,
            bank_labels, min(self.osc_bank, len(bank_labels) - 1), accent, "osc_bank",
        )

        # Row 2: Live Waveform Scope (left 58%) + Power & Quick Routing/Morph pills (right 42%)
        mid_y0 = y0 + r1_h + 6
        mid_h = int((y1 - mid_y0) * 0.44)
        mid_y1 = mid_y0 + mid_h

        scope_w = int((x1 - x0) * 0.58)
        sx1 = x0 + scope_w
        c.create_rectangle(x0, mid_y0, sx1, mid_y1, fill=COL_PANEL, outline=accent, width=1)
        self._draw_vital_osc_wave(x0, mid_y0, sx1, mid_y1, accent)

        rx0 = sx1 + 6
        if self.osc_idx < 3:
            oi = self.osc_idx + 1
            on_k = f"osc_{oi}_on"
            is_on = self._norm(self._get_zctrl(on_k)) >= 0.5
            r_h = (mid_h - 2 * 3) / 3
            # Row 2a: Power + Destination
            hw = (x1 - rx0 - gap) / 2
            self._draw_pill(rx0, mid_y0, rx0 + hw, mid_y0 + r_h,
                            f"OSC {oi}: ON" if is_on else f"OSC {oi}: OFF",
                            is_on, "#51cf66", "cycle", on_k)
            dest_z = self._get_zctrl(f"osc_{oi}_destination")
            self._draw_pill(rx0 + hw + gap, mid_y0, x1, mid_y0 + r_h,
                            "Dest", False, accent, "cycle", f"osc_{oi}_destination",
                            subtext=self._fmt(dest_z)[:8])
            # Row 2b: Spectral Morph Type
            mt_z = self._get_zctrl(f"osc_{oi}_spectral_morph_type")
            self._draw_pill(rx0, mid_y0 + r_h + 3, x1, mid_y0 + 2 * r_h + 3,
                            f"Morph: {self._fmt(mt_z)}", False, accent, "cycle",
                            f"osc_{oi}_spectral_morph_type")
            # Row 2c: Phase Distortion Type
            dt_z = self._get_zctrl(f"osc_{oi}_distortion_type")
            self._draw_pill(rx0, mid_y0 + 2 * (r_h + 3), x1, mid_y1,
                            f"Dist: {self._fmt(dt_z)}", False, accent, "cycle",
                            f"osc_{oi}_distortion_type")
        else:
            on_k = "sample_on"
            is_on = self._norm(self._get_zctrl(on_k)) >= 0.5
            r_h = (mid_h - 3) / 2
            self._draw_pill(rx0, mid_y0, x1, mid_y0 + r_h,
                            "SAMPLE: ON" if is_on else "SAMPLE: OFF",
                            is_on, "#51cf66", "cycle", on_k)
            dest_z = self._get_zctrl("sample_destination")
            self._draw_pill(rx0, mid_y0 + r_h + 3, x1, mid_y1,
                            "Destination", False, accent, "cycle", "sample_destination",
                            subtext=self._fmt(dest_z)[:10])

        # Row 3: Parameter Columns matching the active Osc banks
        py0 = mid_y1 + 5
        if self.osc_idx == 3:
            cw = (x1 - x0 - 6) / 2
            cols = [
                (0, [
                    ("sample_level", "Level", False),
                    ("sample_transpose", "Transpose", True),
                    ("sample_tune", "Tune", True),
                    ("sample_pan", "Pan", True),
                ]),
                (1, [
                    ("sample_loop", "Loop", False),
                    ("sample_keytrack", "Keytrack", False),
                    ("sample_random_phase", "Rnd Phase", False),
                    ("sample_destination", "Dest", False),
                ]),
            ]
        else:
            oi = self.osc_idx + 1
            cw = (x1 - x0 - 12) / 3
            cols = [
                (0, [
                    (f"osc_{oi}_level", "Level", False),
                    (f"osc_{oi}_wave_frame", "Wave Frame", False),
                    (f"osc_{oi}_spectral_morph_amount", "Morph Amt", False),
                    (f"osc_{oi}_distortion_amount", "Dist Amt", False),
                ]),
                (1, [
                    (f"osc_{oi}_transpose", "Transpose", True),
                    (f"osc_{oi}_tune", "Tune", True),
                    (f"osc_{oi}_unison_voices", "Unison V", False),
                    (f"osc_{oi}_unison_detune", "Detune", False),
                ]),
                (2, [
                    (f"osc_{oi}_spectral_morph_type", "Morph Typ", False),
                    (f"osc_{oi}_distortion_type", "Dist Typ", False),
                    (f"osc_{oi}_phase", "Phase", False),
                    (f"osc_{oi}_pan", "Pan", True),
                ]),
            ]

        for b_idx, items in cols:
            cx0 = x0 + b_idx * (cw + 6)
            cx1 = cx0 + cw
            act = (self.osc_bank == b_idx)
            c.create_rectangle(cx0, py0, cx1, y1, fill=COL_BG,
                               outline=accent if act else COL_BORDER, width=2 if act else 1)
            ipad = 3
            rh = (y1 - py0 - 2 * ipad - 3 * 3) / 4
            for i, (key, lbl, bip) in enumerate(items):
                ry0 = py0 + ipad + i * (rh + 3)
                self._draw_param_box(cx0 + ipad, ry0, cx1 - ipad, ry0 + rh,
                                     key, lbl, accent if act else "#6d3b7d",
                                     bank_kind="osc_bank", bank_idx=b_idx, bipolar=bip)

    def _draw_vital_osc_wave(self, x0, y0, x1, y1, accent):
        c = self.widget_canvas
        mid_y = (y0 + y1) / 2 + 5
        c.create_line(x0 + 8, mid_y, x1 - 8, mid_y, fill=COL_GRID, dash=(2, 4))
        pad = 10
        gw = max(10, (x1 - x0) - 2 * pad)
        amp = max(8, (y1 - y0) / 2 - 15)
        n_pts = 88

        if self.osc_idx == 3:
            lvl = self._norm(self._get_zctrl("sample_level"), 0.7)
            pts = []
            for i in range(n_pts + 1):
                t = i / n_pts
                y = math.sin(i * 12.9898) * math.sin(math.pi * t) * lvl
                pts.extend([x0 + pad + t * gw, mid_y - y * amp])
            c.create_line(pts, fill=accent, width=1.8)
            c.create_text(x0 + 8, y0 + 10, text=f"SAMPLE   Lvl: {int(round(lvl * 100))}%",
                          anchor="w", fill=accent, font=self._font(self._fs(0.8), bold=True))
            return

        oi = self.osc_idx + 1
        frame = self._norm(self._get_zctrl(f"osc_{oi}_wave_frame"))
        morph = self._norm(self._get_zctrl(f"osc_{oi}_spectral_morph_amount"), 0.5)
        dist = self._norm(self._get_zctrl(f"osc_{oi}_distortion_amount"), 0.5)
        det = self._norm(self._get_zctrl(f"osc_{oi}_unison_detune"), 0.2)
        v_norm = self._norm(self._get_zctrl(f"osc_{oi}_unison_voices"))
        voices = max(1, int(round(1 + v_norm * 15)))

        def eval_wt(ph):
            # Continuous wavetable morph preview + phase distortion bend
            bend = (dist - 0.5) * 1.4
            p = ph ** max(0.3, 1.0 - bend * 0.55)
            h1 = math.sin(2.0 * math.pi * p)
            h2 = math.sin(2.0 * math.pi * p * (2.0 + int(frame * 6.0)))
            h3 = math.cos(2.0 * math.pi * p * (1.0 + morph * 5.0))
            return (1.0 - frame * 0.55) * h1 + frame * 0.45 * h2 + (morph - 0.5) * 0.45 * h3

        if voices > 1 and det > 0.02:
            g_pts = []
            po = 0.05 + det * 0.20
            for i in range(n_pts + 1):
                t = i / n_pts
                y = 0.5 * (eval_wt((t * 2.0 + po) % 1.0) + eval_wt((t * 2.0 - po) % 1.0))
                g_pts.extend([x0 + pad + t * gw, mid_y - max(-1.0, min(1.0, y)) * amp])
            c.create_line(g_pts, fill="#583066", width=1.4)

        pts = []
        for i in range(n_pts + 1):
            t = i / n_pts
            y = eval_wt((t * 2.0) % 1.0)
            pts.extend([x0 + pad + t * gw, mid_y - max(-1.0, min(1.0, y)) * amp])

        c.create_line(pts, fill=accent, width=2.2)
        c.create_text(x0 + 8, y0 + 10,
                      text=f"OSC {oi}   Frame #{int(round(frame * 256))}   ({voices}v)",
                      anchor="w", fill=accent, font=self._font(self._fs(0.8), bold=True))

    # --------------------------------------------------------------------------
    # TAB 3: FILTER (Filter 1 / Filter 2 / FX Filter + Log-Hz Plot + 2D Handles)
    # --------------------------------------------------------------------------
    def _draw_tab_filter(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = FILTER_COLS[self.flt_idx]
        fid = self._flt_id()
        gap = 6

        # Row 1: F1 / F2 / FX Filter selector + Power toggle + Encoder Bank bar
        r1_h = 34
        left_w = (x1 - x0) * 0.44
        fw = (left_w - 3 * gap) / 4
        for i, (lbl, k) in enumerate((("FLT 1", "1"), ("FLT 2", "2"), ("FX FLT", "fx"))):
            fx0 = x0 + i * (fw + gap)
            is_on = self._norm(self._get_zctrl(f"filter_{k}_on")) >= 0.5
            self._draw_pill(fx0, y0, fx0 + fw, y0 + r1_h, f"● {lbl}" if is_on else lbl,
                            i == self.flt_idx, FILTER_COLS[i], "flt_idx", i)
        # Power toggle for active filter
        cur_on = self._norm(self._get_zctrl(f"filter_{fid}_on")) >= 0.5
        px_on = x0 + 3 * (fw + gap)
        self._draw_pill(px_on, y0, x0 + left_w, y0 + r1_h, "ON" if cur_on else "OFF",
                        cur_on, "#51cf66", "cycle", f"filter_{fid}_on")

        self._draw_bank_bar(
            x0 + left_w + 6, y0, x1, y0 + r1_h,
            ["Core (Cut/Res/Drv)", "Blend & Formant", "Model & Style"],
            self.flt_bank, accent, "flt_bank",
        )

        # Row 2: 8 Clickable Filter Model Pills
        r2_y = y0 + r1_h + 6
        r2_h = 34
        fm_z = self._get_zctrl(f"filter_{fid}_model")
        fm_idx = (fm_z.get_value2index() or 0) if fm_z else 0
        mgap = 4
        mw = (x1 - x0 - mgap * (len(FILTER_MODELS) - 1)) / len(FILTER_MODELS)
        for i, mlbl in enumerate(FILTER_MODELS):
            mx0 = x0 + i * (mw + mgap)
            self._draw_pill(mx0, r2_y, mx0 + mw, r2_y + r2_h, mlbl[:7],
                            i == fm_idx, accent, "flt_model", i)

        # Row 3: 3-Filter Log-Hz Response Graph
        gy0 = r2_y + r2_h + 6
        bot_h = 84
        gy1 = y1 - bot_h - 6
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad_x, pad_y = 12, 10
        gx0, gx1 = x0 + pad_x, x1 - pad_x
        g_top, g_bot = gy0 + pad_y, gy1 - pad_y
        gw = max(10, gx1 - gx0)
        gh = max(10, g_bot - g_top)

        for hz, lbl in ((100.0, "100"), (1000.0, "1k"), (10000.0, "10k")):
            lx = gx0 + hz_to_vital_norm(hz) * gw
            c.create_line(lx, gy0 + 2, lx, gy1 - 2, fill=COL_GRID, dash=(2, 4))
            c.create_text(lx + 3, gy1 - 6, text=lbl, anchor="sw", fill=COL_DIM, font=self._font(7))
        zero_y = g_top + gh * 0.45
        c.create_line(gx0, zero_y, gx1, zero_y, fill=COL_GRID, dash=(2, 4))

        def vital_filter_curve(cut, res, blend, model_idx):
            pts = []
            n_pts = 56
            for i in range(n_pts + 1):
                t = i / n_pts
                d = (t - cut) / 0.11
                peak = (res * 16.0) * math.exp(-d * d * 2.2)
                if model_idx == 6:  # Comb
                    roll = 6.0 * math.cos((t - cut) * 28.0) - 6.0
                elif model_idx == 5:  # Formant
                    roll = 8.0 * math.exp(-((t - cut) / 0.08) ** 2) + 6.0 * math.exp(-((t - min(0.95, cut + 0.2)) / 0.09) ** 2) - 8.0
                else:
                    # Continuous LP (blend=0) <-> BP (blend=0.5) <-> HP (blend=1)
                    lp = -24.0 * ((t - cut) / 0.16) ** 2 if t > cut else 0.0
                    bp = -18.0 * (abs(t - cut) / 0.16) ** 1.6
                    hp = -24.0 * ((cut - t) / 0.16) ** 2 if t < cut else 0.0
                    if blend <= 0.5:
                        k = blend * 2.0
                        roll = (1.0 - k) * lp + k * bp
                    else:
                        k = (blend - 0.5) * 2.0
                        roll = (1.0 - k) * bp + k * hp
                db = max(-30.0, min(18.0, roll + peak))
                px = gx0 + t * gw
                py = zero_y - (db / 24.0) * (gh * 0.48)
                pts.extend([px, max(gy0 + 3, min(gy1 - 3, py))])
            return pts

        f_states = []
        for idx, k in enumerate(("1", "2", "fx")):
            cut = self._norm(self._get_zctrl(f"filter_{k}_cutoff"), 0.45)
            res = self._norm(self._get_zctrl(f"filter_{k}_resonance"), 0.5)
            bln = self._norm(self._get_zctrl(f"filter_{k}_blend"), 0.0)
            mz = self._get_zctrl(f"filter_{k}_model")
            md = (mz.get_value2index() or 0) if mz else 0
            on = self._norm(self._get_zctrl(f"filter_{k}_on")) >= 0.5
            f_states.append((idx, cut, res, bln, md, on))

        for idx, cut, res, bln, md, on in f_states:
            if idx != self.flt_idx and on:
                c.create_line(vital_filter_curve(cut, res, bln, md),
                              fill=FILTER_COLS[idx], width=1.2, dash=(3, 3))

        _, acut, ares, abln, amd, aon = f_states[self.flt_idx]
        apts = vital_filter_curve(acut, ares, abln, amd)
        c.create_polygon([gx0, gy1 - 2] + apts + [gx1, gy1 - 2], fill="#241e18", outline="")
        c.create_line(apts, fill=accent if aon else COL_DIM, width=2.5)

        for idx, cut, res, _, _, on in f_states:
            act = (idx == self.flt_idx)
            if not act and not on:
                continue
            hx = gx0 + cut * gw
            hy = g_bot - res * gh
            r = 9 if act else 6
            col = FILTER_COLS[idx]
            c.create_oval(hx - r, hy - r, hx + r, hy + r,
                          fill=col if act else COL_PANEL_HI,
                          outline="#ffffff" if act else col, width=2 if act else 1)
            c.create_text(hx, hy, text="X" if idx == 2 else str(idx + 1),
                          fill="#000000" if act else col, font=self._font(8, bold=True))

        tag = "FX FLT" if fid == "fx" else f"FLT {fid}"
        hdr = f"{tag}: {FILTER_MODELS[min(amd, len(FILTER_MODELS)-1)]}   {fmt_hz(vital_cutoff_hz(acut))}   Res: {int(round(ares * 100))}%"
        c.create_text(x0 + 8, gy0 + 10, text=hdr, anchor="w", fill=accent,
                      font=self._font(self._fs(0.82), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "filter_xy",
            {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot, "states": f_states},
        ))

        # Row 4: Bottom 2x2 parameter cards
        py0 = gy1 + 5
        items = self._tab_items("Filter")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + gap)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent,
                                 bipolar=("keytrack" in key))

    # --------------------------------------------------------------------------
    # TAB 4: ENVELOPES (ENV 1..6 + Interactive 2D ADSR with Power Curves)
    # --------------------------------------------------------------------------
    def _draw_tab_env(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Env"]
        ei = self.env_idx + 1
        gap = 6

        # Row 1: ENV 1..6 selector + Bank bar
        r1_h = 34
        left_w = (x1 - x0) * 0.62
        egap = 4
        ew = (left_w - 5 * egap) / 6
        for i in range(6):
            ex0 = x0 + i * (ew + egap)
            lbl = "E1(Amp)" if i == 0 else f"ENV {i + 1}"
            self._draw_pill(ex0, y0, ex0 + ew, y0 + r1_h, lbl,
                            i == self.env_idx, accent, "env_idx", i)

        self._draw_bank_bar(
            x0 + left_w + 6, y0, x1, y0 + r1_h,
            ["ADSR", "Dly/Hld/Crv"],
            self.env_bank, accent, "env_bank",
        )

        # Row 2: Interactive 2D ADSR Graph
        gy0 = y0 + r1_h + 6
        bot_h = 84
        gy1 = y1 - bot_h - 6
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 12
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + pad + 14, gy1 - pad
        gw = max(20, gx1 - gx0)
        gh = max(20, g_bot - g_top)

        def eval_env_nodes(idx):
            a = self._norm(self._get_zctrl(f"env_{idx}_attack"))
            d = self._norm(self._get_zctrl(f"env_{idx}_decay"))
            s = self._norm(self._get_zctrl(f"env_{idx}_sustain"), 1.0)
            r = self._norm(self._get_zctrl(f"env_{idx}_release"))
            xa = gx0 + a * (gw * 0.28)
            xd = xa + max(0.02, d) * (gw * 0.28)
            xs = xd + gw * 0.16
            xr = xs + max(0.02, r) * (gw * 0.28)
            ys = g_bot - s * gh
            return a, d, s, r, xa, xd, xs, xr, ys

        # Ghost Amp ENV (ENV 1) behind ENV 2..6
        if ei != 1:
            _, _, _, _, bxa, bxd, bxs, bxr, bys = eval_env_nodes(1)
            c.create_line([gx0, g_bot, bxa, g_top, bxd, bys, bxs, bys, bxr, g_bot],
                          fill="#2d5e38", width=1.4, dash=(3, 3))

        a, d, s, r, xa, xd, xs, xr, ys = eval_env_nodes(ei)
        dpow = self._norm(self._get_zctrl(f"env_{ei}_decay_power"), 0.45)
        rpow = self._norm(self._get_zctrl(f"env_{ei}_release_power"), 0.45)
        d_exp = 2.0 ** ((0.5 - dpow) * 2.5)
        r_exp = 2.0 ** ((0.5 - rpow) * 2.5)

        pts = [gx0, g_bot, xa, g_top]
        for k in range(1, 13):
            t = k / 12.0
            pts.extend([xa + (xd - xa) * t, g_top + (1.0 - (1.0 - t) ** d_exp) * (ys - g_top)])
        pts.extend([xs, ys])
        for k in range(1, 13):
            t = k / 12.0
            pts.extend([xs + (xr - xs) * t, ys + (1.0 - (1.0 - t) ** r_exp) * (g_bot - ys)])

        c.create_polygon(pts + [gx0, g_bot], fill="#16291b", outline="")
        c.create_line(pts, fill=accent, width=2.5)

        for hx, hy in ((xa, g_top), (xd, ys), (xr, g_bot)):
            c.create_oval(hx - 7, hy - 7, hx + 7, hy + 7, fill=accent, outline="#ffffff", width=2)

        hdr = f"ENV {ei}   A:{fmt_time_s(vital_env_s(a))}   D:{fmt_time_s(vital_env_s(d))}   S:{int(round(s * 100))}%   R:{fmt_time_s(vital_env_s(r))}"
        c.create_text(x0 + 8, gy0 + 10, text=hdr, anchor="w", fill=accent,
                      font=self._font(self._fs(0.82), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "env_graph",
            {"ei": ei, "gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
             "xa": xa, "xd": xd, "xs": xs, "xr": xr, "ys": ys},
        ))

        # Row 3: Bottom 2x2 parameter cards
        py0 = gy1 + 5
        items = self._tab_items("Env")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + gap)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent,
                                 bipolar=("power" in key))

    # --------------------------------------------------------------------------
    # TAB 5: LFO (LFO 1..6 + Random LFO 1..2 + Live Waveform Scope)
    # --------------------------------------------------------------------------
    def _draw_tab_lfo(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["LFO"]
        lkey, ltitle, is_rnd = LFO_SLOTS[self.lfo_idx]
        gap = 6

        # Row 1: 8 LFO / Random LFO Slot Pills
        r1_h = 34
        sgap = 4
        lw = (x1 - x0 - sgap * (len(LFO_SLOTS) - 1)) / len(LFO_SLOTS)
        for i, (_, name, _) in enumerate(LFO_SLOTS):
            lx0 = x0 + i * (lw + sgap)
            self._draw_pill(lx0, y0, lx0 + lw, y0 + r1_h, name,
                            i == self.lfo_idx, accent, "lfo_idx", i)

        # Row 2: Encoder Bank bar + Quick Sync/Mode pills
        r2_y = y0 + r1_h + 6
        r2_h = 34
        if is_rnd:
            tw = (x1 - x0 - gap * 2) / 3
            st_z = self._get_zctrl(f"{lkey}_style")
            sy_z = self._get_zctrl(f"{lkey}_sync")
            sr_z = self._get_zctrl(f"{lkey}_stereo")
            self._draw_pill(x0, r2_y, x0 + tw, r2_y + r2_h, f"Style: {self._fmt(st_z)}",
                            False, accent, "cycle", f"{lkey}_style")
            self._draw_pill(x0 + tw + gap, r2_y, x0 + 2 * tw + gap, r2_y + r2_h, f"Sync: {self._fmt(sy_z)}",
                            False, accent, "cycle", f"{lkey}_sync")
            self._draw_pill(x0 + 2 * (tw + gap), r2_y, x1, r2_y + r2_h, f"Stereo: {self._fmt(sr_z)}",
                            False, accent, "cycle", f"{lkey}_stereo")
        else:
            left_w = (x1 - x0) * 0.50
            self._draw_bank_bar(x0, r2_y, x0 + left_w, r2_y + r2_h,
                                ["Rate & Phase", "Delay & Stereo"],
                                self.lfo_bank, accent, "lfo_bank")
            rw = (x1 - (x0 + left_w + 6) - gap) / 2
            sy_z = self._get_zctrl(f"{lkey}_sync")
            md_z = self._get_zctrl(f"{lkey}_sync_type")
            self._draw_pill(x0 + left_w + 6, r2_y, x0 + left_w + 6 + rw, r2_y + r2_h,
                            f"Sync: {self._fmt(sy_z)}", False, accent, "cycle", f"{lkey}_sync")
            self._draw_pill(x0 + left_w + 6 + rw + gap, r2_y, x1, r2_y + r2_h,
                            f"Mode: {self._fmt(md_z)[:7]}", False, accent, "cycle", f"{lkey}_sync_type")

        # Row 3: Live LFO / Random LFO Scope
        gy0 = r2_y + r2_h + 6
        bot_h = 84
        gy1 = y1 - bot_h - 6
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 10
        gx0, gx1 = x0 + pad, x1 - pad
        gw = max(10, gx1 - gx0)
        mid_y = (gy0 + gy1) / 2 + 5
        amp = max(8, (gy1 - gy0) / 2 - 15)
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        rate_n = self._norm(self._get_zctrl(f"{lkey}_tempo"), 0.5)
        cycles = 1.5 + rate_n * 5.0
        pts = []
        n_pts = 96
        if is_rnd:
            st_z = self._get_zctrl(f"{lkey}_style")
            st_idx = (st_z.get_value2index() or 0) if st_z else 0
            for i in range(n_pts + 1):
                t = i / n_pts
                x_c = t * cycles * 3.0
                if st_idx == 1:  # S&H
                    y = math.sin(int(x_c) * 12.9898 + 1.23) * 0.85
                elif st_idx == 2:  # Sine interp
                    y = math.sin(x_c * 2.1) * 0.6 + math.cos(x_c * 3.7) * 0.35
                else:  # Perlin / Lorenz
                    y = math.sin(x_c * 1.7) * 0.5 + math.sin(x_c * 4.3 + 1.1) * 0.35 + math.cos(x_c * 7.1) * 0.15
                pts.extend([gx0 + t * gw, mid_y - y * amp])
            hdr = f"{ltitle}: {RANDOM_STYLES[min(st_idx, 3)]}   Rate: {self._fmt(self._get_zctrl(f'{lkey}_tempo'))}"
        else:
            phs = self._norm(self._get_zctrl(f"{lkey}_phase"), 0.0)
            dly = self._norm(self._get_zctrl(f"{lkey}_delay_time"), 0.0) * 0.25
            fade = self._norm(self._get_zctrl(f"{lkey}_fade_time"), 0.0) * 0.35
            for i in range(n_pts + 1):
                t = i / n_pts
                env_g = 0.0 if t < dly else ((t - dly) / fade if (fade > 0.01 and t < dly + fade) else 1.0)
                p = (t * cycles + phs) % 1.0
                y = 1.0 - 4.0 * abs(p - 0.5)  # default Vital triangle shape
                pts.extend([gx0 + t * gw, mid_y - y * env_g * amp])
            hdr = f"{ltitle}   Rate: {self._fmt(self._get_zctrl(f'{lkey}_tempo'))}   Phs: {int(round(phs * 360))}°"

        c.create_line(pts, fill=accent, width=2.2)
        c.create_text(x0 + 8, gy0 + 10, text=hdr, anchor="w", fill=accent,
                      font=self._font(self._fs(0.82), bold=True))

        # Row 4: Bottom 2x2 parameter cards
        py0 = gy1 + 5
        items = self._tab_items("LFO")
        cw = (x1 - x0 - 4) / 2
        ch = (y1 - py0 - 4) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + 4)
            py_i = py0 + row_i * (ch + 4)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent,
                                 bipolar=("stereo" in key))

    # --------------------------------------------------------------------------
    # TAB 6: FX RACK (8 Effects: Dist, Chorus, Delay, Reverb, Comp, EQ, Flang, Phase)
    # --------------------------------------------------------------------------
    def _draw_tab_fx(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["FX"]
        gap = 6

        # Row 1: 8 FX Module Selector Pills (with active dot if FX is ON)
        r1_h = 34
        sgap = 4
        fw = (x1 - x0 - sgap * (len(FX_MODULES) - 1)) / len(FX_MODULES)
        for i, (_, lbl, on_k) in enumerate(FX_MODULES):
            fx0 = x0 + i * (fw + sgap)
            is_on = self._norm(self._get_zctrl(on_k)) >= 0.5
            act = (i == self.fx_idx)
            txt = f"● {lbl}" if is_on else lbl
            self._draw_pill(fx0, y0, fx0 + fw, y0 + r1_h, txt, act, accent, "fx_idx", i)

        fx_id, fx_lbl, on_k = FX_MODULES[self.fx_idx]
        fx_on = self._norm(self._get_zctrl(on_k)) >= 0.5

        # Row 2: Active FX Header & Power/Mode Strip
        r2_y = y0 + r1_h + 6
        r2_h = 34
        pw_w = 104
        self._draw_pill(x0, r2_y, x0 + pw_w, r2_y + r2_h,
                        f"{fx_lbl.upper()}: ON" if fx_on else f"{fx_lbl.upper()}: OFF",
                        fx_on, "#51cf66", "cycle", on_k)

        # Extra mode pill depending on FX
        extra_x = x0 + pw_w + 6
        if fx_id == "dist":
            z = self._get_zctrl("distortion_type")
            self._draw_pill(extra_x, r2_y, x1, r2_y + r2_h, f"Type: {self._fmt(z)}",
                            False, accent, "cycle", "distortion_type")
        elif fx_id == "delay":
            z = self._get_zctrl("delay_style")
            self._draw_pill(extra_x, r2_y, x1, r2_y + r2_h, f"Style: {self._fmt(z)}",
                            False, accent, "cycle", "delay_style")
        elif fx_id == "comp":
            z = self._get_zctrl("compressor_enabled_bands")
            self._draw_pill(extra_x, r2_y, x1, r2_y + r2_h, f"Bands: {self._fmt(z)}",
                            False, accent, "cycle", "compressor_enabled_bands")
        elif fx_id == "eq":
            hw = (x1 - extra_x - gap) / 2
            self._draw_pill(extra_x, r2_y, extra_x + hw, r2_y + r2_h,
                            f"Low: {self._fmt(self._get_zctrl('eq_low_mode'))}",
                            False, accent, "cycle", "eq_low_mode")
            self._draw_pill(extra_x + hw + gap, r2_y, x1, r2_y + r2_h,
                            f"High: {self._fmt(self._get_zctrl('eq_high_mode'))}",
                            False, accent, "cycle", "eq_high_mode")
        else:
            c.create_rectangle(extra_x, r2_y, x1, r2_y + r2_h, fill=COL_PANEL, outline=COL_BORDER, width=1)
            c.create_text((extra_x + x1) / 2, r2_y + r2_h / 2,
                          text=f"{fx_lbl} Processor — 4 Encoders Bound",
                          fill=COL_DIM, font=self._font(self._fs(0.84)))

        # Row 3: FX Visual Preview Panel (EQ Curve / Distortion Transfer / Generic Bar Graph)
        gy0 = r2_y + r2_h + 6
        bot_h = 84
        gy1 = y1 - bot_h - 6
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent if fx_on else COL_BORDER, width=1)
        self._draw_fx_visual(x0, gy0, x1, gy1, fx_id, accent if fx_on else COL_DIM)

        # Row 4: Bottom 2x2 parameter cards (bound to 4 physical encoders)
        py0 = gy1 + 5
        items = self._tab_items("FX")
        cw = (x1 - x0 - 4) / 2
        ch = (y1 - py0 - 4) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + 4)
            py_i = py0 + row_i * (ch + 4)
            bip = ("feedback" in key and fx_id != "phaser") or ("gain" in key) or ("drive" in key)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent, bipolar=bip)

    def _draw_fx_visual(self, x0, y0, x1, y1, fx_id, color):
        c = self.widget_canvas
        pad = 12
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = y0 + pad, y1 - pad
        gw = max(10, gx1 - gx0)
        gh = max(10, g_bot - g_top)
        mid_y = (g_top + g_bot) / 2
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        if fx_id == "eq":
            lg = (self._norm(self._get_zctrl("eq_low_gain"), 0.5) - 0.5) * 2.0
            mg = (self._norm(self._get_zctrl("eq_band_gain"), 0.5) - 0.5) * 2.0
            hg = (self._norm(self._get_zctrl("eq_high_gain"), 0.5) - 0.5) * 2.0
            lc = self._norm(self._get_zctrl("eq_low_cutoff"), 0.25)
            mc = self._norm(self._get_zctrl("eq_band_cutoff"), 0.55)
            hc = self._norm(self._get_zctrl("eq_high_cutoff"), 0.78)
            pts = []
            for i in range(61):
                t = i / 60.0
                y = (
                    lg * (1.0 / (1.0 + math.exp((t - lc) * 14.0)))
                    + mg * math.exp(-((t - mc) / 0.14) ** 2)
                    + hg * (1.0 / (1.0 + math.exp((hc - t) * 14.0)))
                )
                pts.extend([gx0 + t * gw, mid_y - max(-1.0, min(1.0, y)) * (gh * 0.45)])
            c.create_line(pts, fill=color, width=2.4)
        elif fx_id == "dist":
            drv = self._norm(self._get_zctrl("distortion_drive"), 0.5)
            gain = 1.0 + drv * 7.0
            pts = []
            for i in range(61):
                t = i / 60.0
                x = t * 2.0 - 1.0
                y = math.tanh(x * gain)
                pts.extend([gx0 + t * gw, mid_y - y * (gh * 0.45)])
            c.create_line(pts, fill=color, width=2.4)
        else:
            # Visual bar readout of the 4 active FX parameters
            items = self._tab_items("FX")
            bw = (gw - 3 * 12) / 4
            for i, (key, lbl) in enumerate(items):
                bx0 = gx0 + i * (bw + 12)
                n = self._norm(self._get_zctrl(key))
                bh = n * gh
                c.create_rectangle(bx0, g_top, bx0 + bw, g_bot, fill=COL_TRACK, outline="")
                if bh > 1:
                    c.create_rectangle(bx0, g_bot - bh, bx0 + bw, g_bot, fill=color, outline="")
                c.create_text(bx0 + bw / 2, g_top + 8, text=lbl, fill=COL_TEXT,
                              font=self._font(self._fs(0.76), bold=True))

    # --------------------------------------------------------------------------
    # ECO CPU-Tamer Mode (Oversampling 1x, Polyphony <= 8v, Unison <= 3v)
    # --------------------------------------------------------------------------
    def _toggle_eco(self):
        if not self.processor:
            return
        if self.eco_on:
            for key, orig_val in self._eco_backup.items():
                z = self._get_zctrl(key)
                if z is not None:
                    z.set_value(orig_val, send=True)
            self._eco_backup.clear()
            self.eco_on = False
            return

        backup = {}

        def set_with_backup(key, new_val):
            z = self._get_zctrl(key)
            if z is None:
                return
            cur = self._norm(z)
            if abs(cur - new_val) > 1e-4:
                backup[key] = cur
                z.set_value(new_val, send=True)

        # 1. Oversampling -> 1x (0.0)
        set_with_backup("oversampling", 0.0)

        # 2. Polyphony <= 8 voices (1..32 -> (8-1)/31)
        z_poly = self._get_zctrl("polyphony")
        if z_poly is not None:
            cur_v = int(round(1 + self._norm(z_poly) * 31))
            if cur_v > 8:
                set_with_backup("polyphony", (8 - 1) / 31.0)

        # 3. Unison voices > 4 -> 3 voices (1..16 -> 2/15)
        for oi in (1, 2, 3):
            zu = self._get_zctrl(f"osc_{oi}_unison_voices")
            if zu is not None:
                v = int(round(1 + self._norm(zu) * 15))
                if v > 4:
                    set_with_backup(f"osc_{oi}_unison_voices", 2.0 / 15.0)

        self._eco_backup = backup
        self.eco_on = True

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
            self._live_swap_encoders(self.active_tab)

    def _on_press(self, event):
        kind, payload = self._find_hit(event.x, event.y)
        self.drag_target = None
        if kind is None:
            return

        if kind == "tab":
            if payload != self.active_tab:
                self.active_tab = payload
                self._live_swap_encoders(payload)
                self._select_page_by_title(payload)
                self.last_snapshot = None
                self._draw()
            return

        if kind == "eco":
            self._toggle_eco()
            self.last_snapshot = None
            self._draw()
            return

        if kind == "poly_cycle":
            z = self._get_zctrl("polyphony")
            if z is not None:
                cur_v = int(round(1 + self._norm(z) * 31))
                nxt = next((p for p in POLY_PRESETS if p > cur_v), POLY_PRESETS[0])
                self._set_norm(z, (nxt - 1) / 31.0)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "bank_pitch":
            self._switch_subbank("macro_bank", 1)
            self.last_snapshot = None
            self._draw()
            return

        if kind in ("macro_bank", "osc_bank", "flt_bank", "env_bank", "lfo_bank"):
            self._switch_subbank(kind, payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mod_view":
            self.mod_view = payload
            if payload > 0:
                self.mod_slot = (payload - 1) * 16 + 1
            self._live_swap_encoders("Macro")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mod_slot":
            self.mod_slot = payload
            self.macro_bank = 3
            self._live_swap_encoders("Macro")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mod_zero":
            z = self._get_zctrl(f"modulation_{payload}_amount")
            if z is not None:
                self._set_norm(z, 0.5)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "osc_idx":
            self.osc_idx = payload
            if payload == 3 and self.osc_bank > 1:
                self.osc_bank = 0
            self._live_swap_encoders("Osc")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "flt_idx":
            self.flt_idx = payload
            self._live_swap_encoders("Filter")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "flt_model":
            fid = self._flt_id()
            z = self._get_zctrl(f"filter_{fid}_model")
            if z and getattr(z, "ticks", None) and 0 <= payload < len(z.ticks):
                z.set_value(z.ticks[payload], send=True)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "env_idx":
            self.env_idx = payload
            self._live_swap_encoders("Env")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "lfo_idx":
            self.lfo_idx = payload
            self._live_swap_encoders("LFO")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "fx_idx":
            self.fx_idx = payload
            self._live_swap_encoders("FX")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "cycle":
            self._cycle_enum(self._get_zctrl(payload), 1)
            if self.active_tab == "LFO" and payload.endswith("_sync"):
                self._live_swap_encoders("LFO")
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
            for idx, cut, res, _, _, on in payload["states"]:
                if idx != self.flt_idx and not on:
                    continue
                hx = gx0 + cut * gw
                hy = gy1 - res * gh
                d = (event.x - hx) ** 2 + (event.y - hy) ** 2
                if d < best_d:
                    best_d = d
                    best_idx = idx
            if best_d < 900 and best_idx != self.flt_idx:
                self.flt_idx = best_idx
                self._live_swap_encoders("Filter")
            fid = self._flt_id()
            self._switch_subbank("flt_bank", 0)
            now = time.monotonic()
            tap_id = ("filter_xy", fid)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for rk in (f"filter_{fid}_cutoff", f"filter_{fid}_resonance"):
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("filter_xy", {
                "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                "cut_key": f"filter_{fid}_cutoff", "res_key": f"filter_{fid}_resonance",
            })
            self._apply_drag(event.x, event.y)
            return

        if kind == "env_graph":
            self._switch_subbank("env_bank", 0)
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
            ei = payload["ei"]
            tap_id = ("env_node", ei, node)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                rkeys = [f"env_{ei}_attack"] if node == "A" else ([f"env_{ei}_decay", f"env_{ei}_sustain"] if node == "DS" else [f"env_{ei}_release"])
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
        elif kind == "env_node":
            ei = payload["ei"]
            gx0, gw = payload["gx0"], payload["gw"]
            g_top, g_bot = payload["g_top"], payload["g_bot"]
            seg_w = max(10.0, gw * 0.28)
            node = payload["node"]
            if node == "A":
                self._set_norm(self._get_zctrl(f"env_{ei}_attack"), (x - gx0) / seg_w)
            elif node == "DS":
                self._set_norm(self._get_zctrl(f"env_{ei}_decay"), (x - payload["xa"]) / seg_w)
                if g_bot > g_top:
                    self._set_norm(self._get_zctrl(f"env_{ei}_sustain"), (g_bot - y) / (g_bot - g_top))
            elif node == "R":
                self._set_norm(self._get_zctrl(f"env_{ei}_release"), (x - payload["xs"]) / seg_w)

        self.last_snapshot = None
        self._draw()
