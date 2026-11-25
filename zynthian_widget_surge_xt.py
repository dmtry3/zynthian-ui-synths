#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Surge XT Workstation Widget for Zynthian (V5 800x480 & touchscreens)
#
# Replaces Surge XT's ~194 raw LV2 controller pages (775 parameters) with
# 6 dynamic controller pages mapped 1-to-1 to 6 interactive workstation tabs:
#   Macro | Osc | Filter | Env | LFO/Mod | Mix/FX   + Scene A/B toggle
#
# Features:
# - Complete Modulation Engine Support:
#   * All 12 LFOs (6 Voice LFOs 1..6 + 6 Scene LFOs 1..6) with instant touch
#     group/slot selection, 10 waveform algorithms, Phase, and full DAHDSR
#     envelope generators (Delay, Attack, Hold, Decay, Sustain, Release).
#   * Full Envelope Curvature & Mode Shaping: Attack Shape, Decay Shape,
#     Release Shape (-100% exp .. 0 linear .. +100% log) + Digital/Analog modes
#     for both Amp EG and Filter EG with real-time curved visual rendering.
#   * Dedicated Mod Routing Depths: Filter 1 & Filter 2 FEG Mod Amount,
#     Filter 1 & Filter 2 Keytrack, Pitch Bend Up/Down Ranges, Glide/Portamento,
#     VCA Velocity Sensitivity, VCA Gain, Analog Osc Drift, and Keytrack Root Note.
#   * 8 Universal Performance Macros (M1..M8) with live vertical faders.
# - Authentic DSP Scales & Units:
#   * Frequencies in Hz/kHz, times in ms/s, pitch in semitones, phase in degrees (0..360°),
#     bipolar modulation in ±%, note names (C-1..G9), and real filter/oscillator enum names.
# - Dynamic physical encoder binding:
#   * Tapping sub-banks immediately rebinds Zynthian's 4 physical encoders to
#     those exact 4 parameters with two-way synchronization.
# - High performance Touch-First UX:
#   * Buttons & pills >= 34-44px, dirty-checked 16 FPS redraw, CPU Tamer ECO mode,
#     drag gestures, and double-tap reset.
# ******************************************************************************

import logging
import math
import os
import re
import time
import tkinter
import tkinter.font
import xml.etree.ElementTree as ET

from zyngui import zynthian_gui_config
from zyngui import zynthian_widget_base

MULTI_INSTANCE = True
UPDATE_PERIOD = 0.06  # ~16 fps cap to keep CPU low on Pi 5
DOUBLE_TAP_S = 0.35

# ------------------------------------------------------------------------------
# Theme Palette (matches Zynthian dark UI & Eka suite)
# ------------------------------------------------------------------------------
COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

TABS = ["Macro", "Osc", "Filter", "Env", "LFO/Mod", "Mix/FX"]
TAB_ACCENTS = {
    "Macro":   "#4dabf7",  # blue
    "Osc":     "#cc5de8",  # violet
    "Filter":  "#ff922b",  # orange
    "Env":     "#51cf66",  # green
    "LFO/Mod": "#ffd43b",  # yellow
    "Mix/FX":  "#ff6b6b",  # coral
}
COL_SCENE_A = "#ff922b"
COL_SCENE_B = "#9775fa"
COL_F2 = "#38d9a9"

# ------------------------------------------------------------------------------
# Authentic Surge XT Enum Tables & Musical Scales
# ------------------------------------------------------------------------------
OSC_TYPES = [
    "Classic", "Modern", "Wavetable", "Window", "Sine", "FM2",
    "FM3", "String", "Twist", "Alias", "S&H Noise", "Audio In"
]

OSC_PARAM_NAMES = {
    0:  ["Shape", "Width 1", "Width 2", "Sub Mix", "Sync", "Detune", "Voices"],
    1:  ["Saw", "Pulse", "Tri/Sub", "Width", "Sync", "Detune", "Voices"],
    2:  ["Morph", "Skew V", "Saturate", "Formant", "Skew H", "Detune", "Voices"],
    3:  ["Morph", "Formant", "Window", "Low Cut", "High Cut", "Detune", "Voices"],
    4:  ["Shape", "Feedback", "FM Mode", "Low Cut", "High Cut", "Detune", "Voices"],
    5:  ["M1 Amt", "M1 Ratio", "M2 Amt", "M2 Ratio", "M12 Off", "Phase", "Feedback"],
    6:  ["M1 Amt", "M1 Ratio", "M2 Amt", "M2 Ratio", "M3 Amt", "M3 Ratio", "Feedbk"],
    7:  ["Exciter", "S1 Decay", "S2 Decay", "Detune", "Balance", "Stiff", "Tone"],
    8:  ["Engine", "Harmonic", "Timbre", "Morph", "Aux Mix", "LPG Rsp", "LPG Dec"],
    9:  ["Wave", "Wrap", "Mask", "Thresh", "Crush", "Detune", "Voices"],
    10: ["Correl", "Width", "Low Cut", "High Cut", "Sync", "Detune", "Voices"],
    11: ["Channel", "Gain", "Scn Mix", "Low Cut", "High Cut", "Param 6", "Param 7"],
}

FILTER_TYPES = [
    "Off", "LP 12dB", "LP 24dB", "LP Ladder", "HP 12dB", "HP 24dB",
    "BP 12dB", "Notch 12", "Comb +", "S&H", "Vintage", "OB-Xd 12",
    "OB-Xd 24", "K35 LP", "K35 HP", "Diode Lad", "CutWrp LP", "CutWrp HP",
    "CutWrp N", "CutWrp BP", "OB-Xd HP", "OB-Xd N", "OB-Xd BP", "BP 24dB",
    "Notch 24", "Comb -", "Allpass", "CutWrp AP", "ResWrp LP", "ResWrp HP",
    "ResWrp N", "ResWrp BP", "ResWrp AP", "Tri-Pole"
]

FB_CONFIGS = ["Serial 1", "Serial 2", "Serial 3", "Dual 1", "Dual 2", "Stereo", "Ring", "Wide"]

WS_TYPES = [
    "Off", "Soft", "Hard", "Asym", "Sine", "Digital",
    "Harm 2", "Harm 3", "Harm 4", "Harm 5",
    "FullRect", "Half +", "Half -", "SoftRect",
    "1-Fold", "2-Fold", "WC Fold",
    "Add 1+2", "Add 1+3", "Add 1+4", "Add 1+5", "Add 1-5", "Add Saw3", "Add Sq3",
    "Fuzz", "FuzzSoft", "FuzzHvy", "FuzzCtr", "FuzzEdge",
    "Sin+x", "Sin2x+x", "Sin3x+x", "Sin7x+x", "Sin10x+x",
    "2 Cycle", "7 Cycle", "10 Cycle", "2Cyc Bnd", "7Cyc Bnd", "10CycBnd",
    "Medium", "SoftFold", "HvyFold"
]

FM_ROUTINGS = ["Off", "2 > 1", "3 > 2 > 1", "2 & 3 > 1"]

LFO_SHAPES = [
    "Sine", "Triangle", "Square", "Sawtooth", "Noise",
    "S&H", "Envelope", "Step Seq", "MSEG", "Formula"
]
LFO_TRIGS = ["Freerun", "Keytrig", "Random"]

# 12 LFO slots: 6 Voice LFOs (Voice LFO 1..6) + 6 Scene LFOs (Scene LFO 1..6)
VOICE_LFO_SLOTS = [(f"lfo{i}", f"LFO {i+1}") for i in range(6)]
SCENE_LFO_SLOTS = [(f"lfo{i+6}", f"SLFO {i+1}") for i in range(6)]
ALL_LFO_SLOTS = VOICE_LFO_SLOTS + SCENE_LFO_SLOTS

PLAY_MODES = ["Poly", "Mono", "Mono ST", "Mono FP", "Mono ST+FP", "Latch"]
SCENE_MODES = ["Single", "Key Split", "Dual", "Ch Split"]
CHARACTERS = ["Warm", "Neutral", "Bright"]
OCTAVES = ["-3 oct", "-2 oct", "-1 oct", "0 oct", "+1 oct", "+2 oct", "+3 oct"]
ROUTES = ["F1", "Both", "F2"]
ENV_MODES = ["Digital", "Analog"]
ENV_SHAPES = ["Concave", "Linear", "Convex"]
TOGGLE_OFF_ON = ["Off", "On"]
BYPASS_LABELS = ["Active", "Bypass"]
VOICES_LABELS = [f"{v} v" for v in range(1, 17)]
POLYLIMIT_LABELS = tuple(f"{v}v" for v in range(2, 65))
POLY_PRESETS = (4, 6, 8, 12, 16, 24, 32, 64)
UNISON_OSC_TYPES = {0, 1, 2, 3, 4, 9, 10}

HEAVY_FILTER_MAP = {
    10: 2,  # Vintage Ladder -> LP 24dB
    13: 2,  # K35 LP -> LP 24dB
    14: 5,  # K35 HP -> HP 24dB
    15: 2,  # Diode Ladder -> LP 24dB
    16: 2,  # CutWarp LP -> LP 24dB
    17: 5,  # CutWarp HP -> HP 24dB
    18: 24, # CutWarp N -> Notch 24
    19: 23, # CutWarp BP -> BP 24dB
    28: 2,  # ResWarp LP -> LP 24dB
    29: 5,  # ResWarp HP -> HP 24dB
    30: 24, # ResWarp N -> Notch 24
    31: 23, # ResWarp BP -> BP 24dB
    33: 2,  # Tri-Pole -> LP 24dB
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def norm_to_hz(n):
    """Surge XT pitch-scaled cutoff (MIDI -60..+70 relative to A4=440Hz -> 13.75Hz..25kHz)."""
    n = max(0.0, min(1.0, float(n)))
    return 440.0 * (2.0 ** ((n * 130.0 - 60.0) / 12.0))


def fmt_hz(hz):
    if hz >= 10000.0:
        return f"{hz / 1000.0:.1f}kHz"
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}kHz"
    if hz >= 100.0:
        return f"{hz:.0f}Hz"
    return f"{hz:.1f}Hz"


def norm_to_env_s(n):
    """Surge XT envelope time: 2^(n*13 - 8) seconds (~3.9ms .. 32s, 0ms at min)."""
    n = max(0.0, min(1.0, float(n)))
    if n <= 0.001:
        return 0.0
    return 2.0 ** (n * 13.0 - 8.0)


def fmt_time_s(s):
    if s <= 0.0005:
        return "0ms"
    if s < 0.1:
        return f"{s * 1000.0:.1f}ms" if s < 0.01 else f"{s * 1000.0:.0f}ms"
    if s < 1.0:
        return f"{s * 1000.0:.0f}ms"
    return f"{s:.2f}s" if s < 10.0 else f"{s:.1f}s"


def norm_to_lfo_hz(n):
    """Surge XT LFO rate: 2^(n*16 - 7) Hz (~0.008 Hz .. 512 Hz)."""
    n = max(0.0, min(1.0, float(n)))
    return 2.0 ** (n * 16.0 - 7.0)


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


SCALE_PERCENT = _build_scale(101, lambda t: f"{int(round(t * 100))}%")
SCALE_BIPOLAR = _build_scale(101, lambda t: f"{int(round((t * 2 - 1) * 100)):+d}%")
SCALE_PAN = _build_scale(
    101,
    lambda t: "Center" if abs(t - 0.5) < 0.005 else (
        f"{int(round((0.5 - t) * 200))}L" if t < 0.5 else f"{int(round((t - 0.5) * 200))}R"
    ),
)
SCALE_FBAL = _build_scale(
    101,
    lambda t: "F1=F2" if abs(t - 0.5) < 0.005 else (
        f"F1 {int(round((0.5 - t) * 200))}%" if t < 0.5 else f"F2 {int(round((t - 0.5) * 200))}%"
    ),
)
SCALE_CUTOFF = _build_scale(127, lambda t: fmt_hz(norm_to_hz(t)))
SCALE_ENVTIME = _build_scale(101, lambda t: fmt_time_s(norm_to_env_s(t)))
SCALE_LFORATE = _build_scale(101, lambda t: fmt_lfo_hz(norm_to_lfo_hz(t)))
SCALE_PITCH = _build_scale(141, lambda t: f"{(t * 2 - 1) * 7.0:+.1f}st")
SCALE_PHASE = _build_scale(73, lambda t: f"{int(round(t * 360))}°")
SCALE_PBRANGE = _build_scale(25, lambda t: f"{int(round(t * 24))} st")
SCALE_NOTE = _build_scale(128, lambda t: f"{NOTE_NAMES[int(round(t * 127)) % 12]}{(int(round(t * 127)) // 12) - 1}")


def _enum_scale(names):
    n = len(names)
    if n <= 1:
        return list(names), [0.0]
    return list(names), [i / (n - 1) for i in range(n)]


# ------------------------------------------------------------------------------
# Surge XT .fxp Preset Sync (compensates for JUCE LV2 not reporting patch:Set)
# ------------------------------------------------------------------------------
SURGE_DATA_DIRS = (
    "/usr/local/share/surge-xt",
    "/usr/share/surge-xt",
    os.path.expanduser("~/.local/share/surge-xt"),
    "/root/.local/share/surge-xt",
)
_FXP_INDEX_CACHE = None


def _build_fxp_index():
    """Scan Surge XT factory/3rdparty .fxp directories once and build lookup maps."""
    global _FXP_INDEX_CACHE
    if _FXP_INDEX_CACHE is not None:
        return _FXP_INDEX_CACHE

    by_bank_label = {}
    by_label = {}
    by_name = {}
    init_path = None

    for base in SURGE_DATA_DIRS:
        if not os.path.isdir(base):
            continue
        for root_dir, _, files in os.walk(base):
            for fname in files:
                if not fname.lower().endswith(".fxp"):
                    continue
                full = os.path.join(root_dir, fname)
                stem = os.path.splitext(fname)[0].strip()
                stem_l = stem.lower()
                if stem_l == "init saw" and init_path is None:
                    init_path = full

                rel = os.path.relpath(full, base).replace("\\", "/")
                parts = rel.split("/")
                if not parts or not parts[0].startswith("patches_"):
                    continue
                sub = parts[1:]
                if not sub:
                    continue

                by_name.setdefault(stem_l, full)
                if len(sub) == 2:
                    bank_l = sub[0].strip().lower()
                    by_bank_label[(bank_l, stem_l)] = full
                    by_label.setdefault(stem_l, full)
                elif len(sub) == 3:
                    p0, p1 = sub[0].strip().lower(), sub[1].strip().lower()
                    lbl0 = f"{p0}/{stem_l}"
                    lbl1 = f"{p1}/{stem_l}"
                    by_bank_label[(p1, lbl0)] = full
                    by_bank_label[(p0, lbl1)] = full
                    by_bank_label[(f"{p0}/{p1}", stem_l)] = full
                    by_label.setdefault(lbl0, full)
                    by_label.setdefault(lbl1, full)
                elif len(sub) >= 4:
                    p0, p1 = sub[0].strip().lower(), sub[1].strip().lower()
                    mid = "/".join(x.strip().lower() for x in sub[2:-1])
                    lbl_a = f"{p0}/{mid}/{stem_l}"
                    lbl_b = f"{p1}/{mid}/{stem_l}"
                    by_bank_label[(p1, lbl_a)] = full
                    by_bank_label[(p0, lbl_b)] = full
                    by_bank_label[(sub[-2].strip().lower(), f"{'/'.join(x.strip().lower() for x in sub[:-2])}/{stem_l}")] = full
                    by_label.setdefault(lbl_a, full)
                    by_label.setdefault(lbl_b, full)

    _FXP_INDEX_CACHE = (by_bank_label, by_label, by_name, init_path)
    return _FXP_INDEX_CACHE


def _find_surge_fxp(bank_name, preset_name):
    """Resolve Zynthian (bank_name, preset_name) to the matching Surge XT .fxp file."""
    by_bank_label, by_label, by_name, init_path = _build_fxp_index()
    if not preset_name:
        return init_path
    p_clean = str(preset_name).strip().lower()
    if p_clean in ("default", "init", "init saw"):
        return init_path
    b_clean = str(bank_name or "").strip().lower()

    if b_clean:
        hit = by_bank_label.get((b_clean, p_clean))
        if hit:
            return hit
    hit = by_label.get(p_clean)
    if hit:
        return hit
    leaf = p_clean.split("/")[-1].strip()
    return by_name.get(leaf) or init_path


def _clamp01(v):
    return max(0.0, min(1.0, float(v)))


def _fxp_param_to_norm(tag, raw_val, raw_type, osc_types, f2_offset_flags):
    """Convert a Surge XT .fxp XML parameter value into LV2 normalized [0.0..1.0]."""
    try:
        v = float(raw_val)
    except Exception:
        return None
    # Guard against Surge XT raw int32 bitcast union fields in unused osc slots
    if abs(v) > 1e6:
        return None

    # Global parameters
    if tag == "volume":
        return _clamp01((v + 48.0) / 48.0)
    if tag.startswith("volume_FX"):
        return _clamp01(v)
    if tag == "character":
        return _clamp01(v / 2.0)
    if tag == "scenemode":
        return _clamp01(v / 3.0)
    if tag == "polylimit":
        return _clamp01((v - 2.0) / 62.0)
    if tag == "fx_bypass":
        return _clamp01(v / 3.0)
    if tag == "fx_disable":
        return 1.0 if int(v) != 0 else 0.0

    if len(tag) < 3 or tag[0] not in ("a", "b") or tag[1] != "_":
        return None
    sc = tag[0]
    rest = tag[2:]

    # Envelopes (Amp EG = env1, Filter EG = env2)
    if rest.startswith("env1_") or rest.startswith("env2_"):
        sub = rest[5:]
        if sub in ("attack", "decay", "release"):
            return _clamp01((v + 8.0) / 13.0)
        if sub == "sustain":
            return _clamp01(v)
        if sub in ("attack_shape", "decay_shape", "release_shape"):
            return _clamp01(v / 2.0)
        if sub == "mode":
            return _clamp01(v)
        return None

    # Filters 1 & 2
    if rest.startswith("filter1_") or rest.startswith("filter2_"):
        fi = rest[6]
        sub = rest[8:]
        if sub == "type":
            return _clamp01(v / 33.0)
        if sub == "cutoff":
            if fi == "2" and f2_offset_flags.get(sc, 0):
                return _clamp01((v + 60.0) / 120.0)
            return _clamp01((v + 60.0) / 130.0)
        if sub == "resonance":
            return _clamp01(v)
        if sub == "envmod":
            return _clamp01((v + 96.0) / 192.0)
        if sub == "keytrack":
            return _clamp01((v + 1.0) / 2.0)
        return None

    # LFOs 0..11
    if rest.startswith("lfo"):
        m = re.match(r"^lfo\d+_(.+)$", rest)
        if not m:
            return None
        sub = m.group(1)
        if sub == "shape":
            return _clamp01(v / 9.0)
        if sub == "rate":
            return _clamp01((v + 7.0) / 16.0)
        if sub in ("phase", "magnitude", "sustain"):
            return _clamp01(v)
        if sub == "deform":
            return _clamp01((v + 1.0) / 2.0)
        if sub == "trigmode":
            return _clamp01(v / 2.0)
        if sub == "unipolar":
            return _clamp01(v)
        if sub in ("delay", "attack", "hold", "decay", "release"):
            return _clamp01((v + 8.0) / 13.0)
        return None

    # Oscillators 1..3
    if rest.startswith("osc") and len(rest) > 5 and rest[3] in ("1", "2", "3") and rest[4] == "_":
        oi = int(rest[3])
        sub = rest[5:]
        if sub == "type":
            return _clamp01(v / 11.0)
        if sub == "octave":
            return _clamp01((v + 3.0) / 6.0)
        if sub == "pitch":
            return _clamp01((v + 7.0) / 14.0)
        if sub in ("keytrack", "retrigger"):
            return _clamp01(v)
        if sub == "param6":
            otype = osc_types.get((sc, oi), 0)
            if otype in UNISON_OSC_TYPES and raw_type == "0":
                return _clamp01((v - 1.0) / 15.0)
            if -1.0 <= v <= 1.0:
                return _clamp01((v + 1.0) / 2.0 if v < 0.0 else v)
            return None
        if sub.startswith("param"):
            if raw_type == "2":
                if -1.0 <= v <= 1.0:
                    return _clamp01((v + 1.0) / 2.0 if v < 0.0 else v)
                if -60.0 <= v <= 70.0:
                    return _clamp01((v + 60.0) / 130.0)
            return None

    # Scene-level parameters
    if rest == "octave":
        return _clamp01((v + 3.0) / 6.0)
    if rest == "pitch":
        return _clamp01((v + 7.0) / 14.0)
    if rest == "portamento":
        return _clamp01((v + 8.0) / 13.0)
    if rest in ("pbrange_up", "pbrange_dn"):
        return _clamp01(v / 24.0)
    if rest == "ktrkroot":
        return _clamp01(v / 127.0)
    if rest == "polymode":
        return _clamp01(v / 5.0)
    if rest == "fm_switch":
        return _clamp01(v / 3.0)
    if rest == "fm_depth":
        return _clamp01((v + 48.0) / 72.0)
    if rest == "drift":
        return _clamp01(v)
    if rest in ("noisecol", "pan", "pan2", "feedback", "f_balance"):
        return _clamp01((v + 1.0) / 2.0)
    if rest == "volume":
        return _clamp01(v)
    if rest == "vca_level":
        return _clamp01((v + 48.0) / 96.0)
    if rest == "vca_velsense":
        return _clamp01((v + 48.0) / 48.0)
    if rest == "fb_config":
        return _clamp01(v / 7.0)
    if rest == "lowcut":
        return _clamp01((v + 72.0) / 142.0)
    if rest == "ws_type":
        return _clamp01(v / 42.0)
    if rest == "ws_drive":
        return _clamp01((v + 24.0) / 48.0)
    if rest in ("f2_cf_is_offset", "f2_link_resonance"):
        return _clamp01(v)
    if rest == "level_pfg":
        return _clamp01((v + 48.0) / 96.0)
    if rest.startswith("send_fx_"):
        return _clamp01(v / 1.5874)
    if rest.startswith("level_"):
        return _clamp01(v)
    if rest.startswith("mute_") or rest.startswith("solo_"):
        return _clamp01(v)
    if rest.startswith("route_"):
        return _clamp01(v / 2.0)
    return None


def _parse_surge_fxp(fxp_path):
    """Parse a Surge XT .fxp file and return (norm_params_dict, macro_labels_list)."""
    norm_vals = {}
    macro_labels = [None] * 8
    try:
        with open(fxp_path, "rb") as fh:
            data = fh.read()
        i0 = data.find(b"<patch")
        i1 = data.find(b"</patch>")
        if i0 < 0 or i1 < 0:
            return norm_vals, macro_labels
        root = ET.fromstring(data[i0:i1 + 8].decode("utf-8", errors="replace"))
    except Exception as e:
        logging.debug(f"Surge XT widget: failed to parse fxp '{fxp_path}' => {e}")
        return norm_vals, macro_labels

    params_el = root.find("parameters")
    if params_el is not None:
        # First pass: collect osc types & f2 offset flags needed to scale dependent params
        osc_types = {}
        f2_offset_flags = {}
        for el in params_el:
            t = el.tag
            if len(t) == 11 and t[0] in ("a", "b") and t[1:5] == "_osc" and t[6:] == "_type":
                try:
                    osc_types[(t[0], int(t[5]))] = int(float(el.attrib.get("value", "0")))
                except Exception:
                    pass
            elif t in ("a_f2_cf_is_offset", "b_f2_cf_is_offset"):
                try:
                    f2_offset_flags[t[0]] = int(float(el.attrib.get("value", "0")))
                except Exception:
                    pass

        for el in params_el:
            val_s = el.attrib.get("value")
            if val_s is None:
                continue
            nv = _fxp_param_to_norm(el.tag, val_s, el.attrib.get("type", "2"), osc_types, f2_offset_flags)
            if nv is not None:
                norm_vals[el.tag] = nv

    cc_el = root.find("customcontroller")
    if cc_el is not None:
        for entry in cc_el:
            try:
                idx = int(entry.attrib.get("i", "-1"))
                if 0 <= idx < 8:
                    v = float(entry.attrib.get("v", "0"))
                    bip = entry.attrib.get("bipolar", "0") == "1"
                    norm_vals[f"macro_{idx}"] = _clamp01((v + 1.0) / 2.0 if bip else v)
                    lbl = (entry.attrib.get("label") or "").strip()
                    if lbl and lbl != "-":
                        macro_labels[idx] = lbl
            except Exception:
                pass

    return norm_vals, macro_labels


# ------------------------------------------------------------------------------
# Main Widget Class
# ------------------------------------------------------------------------------
class zynthian_widget_surge_xt(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)

        self.next_update = 0.0
        self.scene = 0               # 0 = Scene A, 1 = Scene B
        self.active_tab = "Macro"

        # Per-tab sub-selection state (controls which 4 parameters bind to physical encoders)
        self.macro_bank = 0          # 0: Macros 1-4, 1: Macros 5-8, 2: Pitch & Glide, 3: Voice & Mod
        self.osc_idx = 0             # 0: Osc 1, 1: Osc 2, 2: Osc 3
        self.osc_bank = 0            # 0: Shape, 1: Pitch & Unison, 2: Sub & Sync
        self.filter_bank = 0         # 0: Filter 1, 1: Filter 2, 2: Routing & Drive, 3: Offset & Link
        self.env_bank = 0            # 0: Amp EG ADSR, 1: Amp Curves, 2: Filter EG ADSR, 3: Filter Curves, 4: Env & Vel Mod
        self.lfo_group = 0           # 0: Voice LFO 1-6, 1: Scene LFO 1-6
        self.lfo_slot = 0            # 0..5 (into Voice or Scene group)
        self.lfo_idx = 0             # 0..11 into ALL_LFO_SLOTS (lfo_group * 6 + lfo_slot)
        self.lfo_bank = 0            # 0: Wave, 1: Trig & Phase, 2: EG Envelope, 3: Mod Depths
        self.mix_bank = 0            # 0: Osc Mix, 1: Ring & FM, 2: FX Sends, 3: Master & Return

        self.last_screen_title = None
        self.last_snapshot = None
        self._enhanced_procs = set()
        self._bound_proc_id = None
        self._synced_preset_sig = None
        self._macro_labels = [None] * 8
        self.eco_on = False
        self._eco_backup = {}

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
    # Processor Setup & zctrl Enhancement (real units & enum labels!)
    # --------------------------------------------------------------------------
    def set_processor(self, processor):
        super().set_processor(processor)
        if processor is None:
            return
        self._build_ctrl_index(processor)
        pid = id(processor)
        is_new_proc = pid not in self._enhanced_procs
        if is_new_proc:
            self._enhanced_procs.add(pid)
            self._enhance_all_zctrls(processor)
        self._maybe_sync_preset(only_zero=is_new_proc)
        if self._bound_proc_id != (pid, self.scene):
            self._bound_proc_id = (pid, self.scene)
            self._rebuild_all_pages(select_tab=self.active_tab, rebuild_list=True)

    def _preset_sig(self, processor):
        if not processor:
            return None
        pinfo = getattr(processor, "preset_info", None)
        uri = pinfo[0] if (isinstance(pinfo, (list, tuple)) and len(pinfo) > 0) else None
        return (
            id(processor),
            getattr(processor, "bank_name", None),
            getattr(processor, "preset_name", None),
            uri,
        )

    def _maybe_sync_preset(self, only_zero=False):
        """Sync Zynthian zctrl values (send=False) from the active Surge XT .fxp preset."""
        proc = self.processor
        if not proc:
            return
        sig = self._preset_sig(proc)
        if sig == self._synced_preset_sig:
            return
        prev_sig = self._synced_preset_sig
        self._synced_preset_sig = sig

        _, bank_name, preset_name, uri = sig
        # Don't clobber user-saved LV2 .ttl presets that aren't in factory .fxp banks
        if isinstance(uri, str) and uri.startswith("file://"):
            return

        fxp_path = _find_surge_fxp(bank_name, preset_name)
        if not fxp_path:
            return

        norm_vals, macro_labels = _parse_surge_fxp(fxp_path)
        if not norm_vals:
            return

        self._macro_labels = macro_labels
        cdict = proc.controllers_dict
        # On initial attach (prev_sig is None), preserve any non-zero user tweaks from snapshots
        preserve_nonzero = bool(only_zero and prev_sig is None)
        applied = 0
        for key, nv in norm_vals.items():
            z = cdict.get("surge_xt_" + key) or cdict.get(key)
            if z is None:
                continue
            try:
                cur = float(z.value)
            except Exception:
                cur = 0.0
            z.value_default = nv
            if preserve_nonzero and abs(cur) > 1e-6:
                continue
            try:
                z.set_value(nv, send=False)
                applied += 1
            except Exception:
                z.value = nv

        if applied > 0 and prev_sig is not None:
            # Refresh physical encoder widgets with newly synced preset values
            self._live_swap_encoders(self.active_tab)
        self.last_snapshot = None

    def _norm_key(self, s):
        return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")

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
            idx[self._norm_key(sym)] = z
            for attr in ("name", "short_name"):
                val = getattr(z, attr, None)
                if val:
                    nk = self._norm_key(val)
                    if nk not in idx:
                        idx[nk] = z
        self._ctrl_index = idx

    def _scene_prefix(self):
        return "a" if self.scene == 0 else "b"

    def _resolve_key(self, raw_key):
        return raw_key.replace("{s}", self._scene_prefix())

    def _get_zctrl(self, raw_key):
        if not self.processor:
            return None
        key = self._resolve_key(raw_key)
        cdict = self.processor.controllers_dict
        z = cdict.get("surge_xt_" + key)
        if z is not None:
            return z
        z = cdict.get(key)
        if z is not None:
            return z
        cidx = getattr(self, "_ctrl_index", None)
        if cidx:
            z = cidx.get(self._norm_key("surge_xt_" + key))
            if z is not None:
                return z
            return cidx.get(self._norm_key(key))
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

    def _enhance_all_zctrls(self, processor):
        cdict = processor.controllers_dict

        def enh(key_suffix, scale_pair):
            labels, ticks = scale_pair
            for prefix in ("surge_xt_", ""):
                z = cdict.get(prefix + key_suffix)
                if z is not None:
                    self._configure_zctrl_scale(z, labels, ticks)
                    break

        # Global & Macros
        for i in range(8):
            enh(f"macro_{i}", SCALE_PERCENT)
        enh("volume", SCALE_PERCENT)
        enh("character", _enum_scale(CHARACTERS))
        enh("scenemode", _enum_scale(SCENE_MODES))
        enh("polylimit", (POLYLIMIT_LABELS, [i / (len(POLYLIMIT_LABELS) - 1) for i in range(len(POLYLIMIT_LABELS))]))
        enh("fx_bypass", _enum_scale(BYPASS_LABELS))
        enh("fx_disable", _enum_scale(TOGGLE_OFF_ON))
        for fx_i in range(1, 5):
            enh(f"volume_FX{fx_i}", SCALE_PERCENT)

        # Scene A & B parameters
        for sc in ("a", "b"):
            enh(f"{sc}_octave", _enum_scale(OCTAVES))
            enh(f"{sc}_pitch", SCALE_PITCH)
            enh(f"{sc}_portamento", SCALE_ENVTIME)
            enh(f"{sc}_pbrange_up", SCALE_PBRANGE)
            enh(f"{sc}_pbrange_dn", SCALE_PBRANGE)
            enh(f"{sc}_ktrkroot", SCALE_NOTE)
            enh(f"{sc}_polymode", _enum_scale(PLAY_MODES))
            enh(f"{sc}_fm_switch", _enum_scale(FM_ROUTINGS))
            enh(f"{sc}_fm_depth", SCALE_PERCENT)
            enh(f"{sc}_drift", SCALE_PERCENT)
            enh(f"{sc}_noisecol", SCALE_BIPOLAR)
            enh(f"{sc}_volume", SCALE_PERCENT)
            enh(f"{sc}_pan", SCALE_PAN)
            enh(f"{sc}_pan2", SCALE_PERCENT)
            enh(f"{sc}_vca_level", SCALE_PERCENT)
            enh(f"{sc}_vca_velsense", SCALE_PERCENT)
            enh(f"{sc}_feedback", SCALE_BIPOLAR)
            enh(f"{sc}_fb_config", _enum_scale(FB_CONFIGS))
            enh(f"{sc}_f_balance", SCALE_FBAL)
            enh(f"{sc}_lowcut", SCALE_CUTOFF)
            enh(f"{sc}_ws_type", _enum_scale(WS_TYPES))
            enh(f"{sc}_ws_drive", SCALE_PERCENT)
            enh(f"{sc}_f2_cf_is_offset", _enum_scale(TOGGLE_OFF_ON))
            enh(f"{sc}_f2_link_resonance", _enum_scale(TOGGLE_OFF_ON))

            for fx_i in range(1, 5):
                enh(f"{sc}_send_fx_{fx_i}", SCALE_PERCENT)

            # Oscillators 1..3
            for oi in (1, 2, 3):
                enh(f"{sc}_osc{oi}_type", _enum_scale(OSC_TYPES))
                enh(f"{sc}_osc{oi}_octave", _enum_scale(OCTAVES))
                enh(f"{sc}_osc{oi}_pitch", SCALE_PITCH)
                for pi in range(6):
                    enh(f"{sc}_osc{oi}_param{pi}", SCALE_PERCENT)
                enh(f"{sc}_osc{oi}_param6", _enum_scale(VOICES_LABELS))
                enh(f"{sc}_osc{oi}_keytrack", _enum_scale(TOGGLE_OFF_ON))
                enh(f"{sc}_osc{oi}_retrigger", _enum_scale(TOGGLE_OFF_ON))

            # Mixer channels
            for ch in ("o1", "o2", "o3", "ring12", "ring23", "noise"):
                enh(f"{sc}_level_{ch}", SCALE_PERCENT)
                enh(f"{sc}_mute_{ch}", _enum_scale(TOGGLE_OFF_ON))
                enh(f"{sc}_solo_{ch}", _enum_scale(TOGGLE_OFF_ON))
                enh(f"{sc}_route_{ch}", _enum_scale(ROUTES))
            enh(f"{sc}_level_pfg", SCALE_PERCENT)

            # Filters 1 & 2
            for fi in (1, 2):
                enh(f"{sc}_filter{fi}_type", _enum_scale(FILTER_TYPES))
                enh(f"{sc}_filter{fi}_cutoff", SCALE_CUTOFF)
                enh(f"{sc}_filter{fi}_resonance", SCALE_PERCENT)
                enh(f"{sc}_filter{fi}_envmod", SCALE_BIPOLAR)
                enh(f"{sc}_filter{fi}_keytrack", SCALE_BIPOLAR)

            # Envelopes 1 (Amp) & 2 (Filter)
            for ei in (1, 2):
                enh(f"{sc}_env{ei}_attack", SCALE_ENVTIME)
                enh(f"{sc}_env{ei}_attack_shape", _enum_scale(ENV_SHAPES))
                enh(f"{sc}_env{ei}_decay", SCALE_ENVTIME)
                enh(f"{sc}_env{ei}_decay_shape", _enum_scale(ENV_SHAPES))
                enh(f"{sc}_env{ei}_sustain", SCALE_PERCENT)
                enh(f"{sc}_env{ei}_release", SCALE_ENVTIME)
                enh(f"{sc}_env{ei}_release_shape", _enum_scale(ENV_SHAPES))
                enh(f"{sc}_env{ei}_mode", _enum_scale(ENV_MODES))

            # All 12 LFOs
            for lfo_key, _ in ALL_LFO_SLOTS:
                enh(f"{sc}_{lfo_key}_shape", _enum_scale(LFO_SHAPES))
                enh(f"{sc}_{lfo_key}_rate", SCALE_LFORATE)
                enh(f"{sc}_{lfo_key}_phase", SCALE_PHASE)
                enh(f"{sc}_{lfo_key}_magnitude", SCALE_PERCENT)
                enh(f"{sc}_{lfo_key}_deform", SCALE_BIPOLAR)
                enh(f"{sc}_{lfo_key}_trigmode", _enum_scale(LFO_TRIGS))
                enh(f"{sc}_{lfo_key}_unipolar", _enum_scale(["Bipolar", "Unipolar"]))
                enh(f"{sc}_{lfo_key}_delay", SCALE_ENVTIME)
                enh(f"{sc}_{lfo_key}_attack", SCALE_ENVTIME)
                enh(f"{sc}_{lfo_key}_hold", SCALE_ENVTIME)
                enh(f"{sc}_{lfo_key}_decay", SCALE_ENVTIME)
                enh(f"{sc}_{lfo_key}_sustain", SCALE_PERCENT)
                enh(f"{sc}_{lfo_key}_release", SCALE_ENVTIME)

    # --------------------------------------------------------------------------
    # Dynamic Page Definitions (1 Page per Tab -> 4 Physical Encoders)
    # --------------------------------------------------------------------------
    def _osc_type_idx(self, osc_num=None):
        if osc_num is None:
            osc_num = self.osc_idx + 1
        z = self._get_zctrl(f"{{s}}_osc{osc_num}_type")
        n = self._norm(z)
        return max(0, min(len(OSC_TYPES) - 1, int(round(n * (len(OSC_TYPES) - 1)))))

    def _osc_param_names(self, osc_num=None):
        t_idx = self._osc_type_idx(osc_num)
        return OSC_PARAM_NAMES.get(t_idx, OSC_PARAM_NAMES[0])

    def _macro_name(self, idx, short=False):
        lbl = self._macro_labels[idx] if 0 <= idx < len(self._macro_labels) else None
        if lbl:
            return lbl[:7] if short else lbl[:12]
        return f"M{idx + 1}" if short else f"Macro {idx + 1}"

    def _tab_items(self, tab_name):
        if tab_name == "Macro":
            if self.macro_bank == 0:
                return [(f"macro_{i}", self._macro_name(i)) for i in range(4)]
            if self.macro_bank == 1:
                return [(f"macro_{i}", self._macro_name(i)) for i in range(4, 8)]
            if self.macro_bank == 2:
                return [("{s}_pitch", "Pitch"), ("{s}_portamento", "Glide"), ("{s}_pbrange_up", "PB Up"), ("{s}_pbrange_dn", "PB Down")]
            return [("{s}_drift", "Drift"), ("{s}_vca_level", "VCA Gain"), ("{s}_vca_velsense", "Vel > VCA"), ("{s}_ktrkroot", "Key Root")]

        if tab_name == "Osc":
            oi = self.osc_idx + 1
            pnames = self._osc_param_names(oi)
            if self.osc_bank == 0:
                return [
                    (f"{{s}}_osc{oi}_type",   f"O{oi} Type"),
                    (f"{{s}}_osc{oi}_param0", f"O{oi} {pnames[0]}"),
                    (f"{{s}}_osc{oi}_param1", f"O{oi} {pnames[1]}"),
                    (f"{{s}}_osc{oi}_param2", f"O{oi} {pnames[2]}"),
                ]
            if self.osc_bank == 1:
                return [
                    (f"{{s}}_osc{oi}_octave", f"O{oi} Oct"),
                    (f"{{s}}_osc{oi}_pitch",  f"O{oi} Pitch"),
                    (f"{{s}}_osc{oi}_param5", f"O{oi} {pnames[5]}"),
                    (f"{{s}}_osc{oi}_param6", f"O{oi} {pnames[6]}"),
                ]
            return [
                (f"{{s}}_osc{oi}_param3",    f"O{oi} {pnames[3]}"),
                (f"{{s}}_osc{oi}_param4",    f"O{oi} {pnames[4]}"),
                (f"{{s}}_osc{oi}_keytrack",  f"O{oi} KeyTrk"),
                (f"{{s}}_osc{oi}_retrigger", f"O{oi} Retrig"),
            ]

        if tab_name == "Filter":
            if self.filter_bank == 0:
                return [
                    ("{s}_filter1_cutoff",    "F1 Cutoff"),
                    ("{s}_filter1_resonance", "F1 Reso"),
                    ("{s}_filter1_envmod",    "F1 EnvMod"),
                    ("{s}_filter1_keytrack",  "F1 KeyTrk"),
                ]
            if self.filter_bank == 1:
                return [
                    ("{s}_filter2_cutoff",    "F2 Cutoff"),
                    ("{s}_filter2_resonance", "F2 Reso"),
                    ("{s}_filter2_envmod",    "F2 EnvMod"),
                    ("{s}_filter2_keytrack",  "F2 KeyTrk"),
                ]
            if self.filter_bank == 2:
                return [
                    ("{s}_fb_config", "F Config"),
                    ("{s}_f_balance", "F Balance"),
                    ("{s}_ws_drive",  "WS Drive"),
                    ("{s}_ws_type",   "WS Type"),
                ]
            return [
                ("{s}_f2_cf_is_offset",   "F2 Offset"),
                ("{s}_f2_link_resonance", "F2 Link"),
                ("{s}_feedback",          "Feedback"),
                ("{s}_lowcut",            "Highpass"),
            ]

        if tab_name == "Env":
            if self.env_bank == 0:
                return [
                    ("{s}_env1_attack",  "Amp Atk"),
                    ("{s}_env1_decay",   "Amp Dec"),
                    ("{s}_env1_sustain", "Amp Sus"),
                    ("{s}_env1_release", "Amp Rel"),
                ]
            if self.env_bank == 1:
                return [
                    ("{s}_env1_attack_shape",  "Atk Curv"),
                    ("{s}_env1_decay_shape",   "Dec Curv"),
                    ("{s}_env1_release_shape", "Rel Curv"),
                    ("{s}_env1_mode",          "Amp Mode"),
                ]
            if self.env_bank == 2:
                return [
                    ("{s}_env2_attack",  "Flt Atk"),
                    ("{s}_env2_decay",   "Flt Dec"),
                    ("{s}_env2_sustain", "Flt Sus"),
                    ("{s}_env2_release", "Flt Rel"),
                ]
            if self.env_bank == 3:
                return [
                    ("{s}_env2_attack_shape",  "Atk Curv"),
                    ("{s}_env2_decay_shape",   "Dec Curv"),
                    ("{s}_env2_release_shape", "Rel Curv"),
                    ("{s}_env2_mode",          "Flt Mode"),
                ]
            return [
                ("{s}_filter1_envmod", "F1 EnvMod"),
                ("{s}_filter2_envmod", "F2 EnvMod"),
                ("{s}_vca_velsense",   "Vel > VCA"),
                ("{s}_vca_level",      "VCA Gain"),
            ]

        if tab_name == "LFO/Mod":
            lkey, ltitle = ALL_LFO_SLOTS[self.lfo_idx]
            short = ltitle.replace("LFO ", "L").replace("SLFO ", "SL")
            if self.lfo_bank == 0:
                return [
                    (f"{{s}}_{lkey}_shape",     f"{short} Shape"),
                    (f"{{s}}_{lkey}_rate",      f"{short} Rate"),
                    (f"{{s}}_{lkey}_magnitude", f"{short} Depth"),
                    (f"{{s}}_{lkey}_deform",    f"{short} Deform"),
                ]
            if self.lfo_bank == 1:
                return [
                    (f"{{s}}_{lkey}_trigmode", f"{short} Trig"),
                    (f"{{s}}_{lkey}_phase",    f"{short} Phase"),
                    (f"{{s}}_{lkey}_unipolar", f"{short} Polar"),
                    (f"{{s}}_{lkey}_delay",    f"{short} Delay"),
                ]
            if self.lfo_bank == 2:
                return [
                    (f"{{s}}_{lkey}_attack",  f"{short} Atk"),
                    (f"{{s}}_{lkey}_hold",    f"{short} Hold"),
                    (f"{{s}}_{lkey}_decay",   f"{short} Dec"),
                    (f"{{s}}_{lkey}_release", f"{short} Rel"),
                ]
            return [
                ("{s}_filter1_envmod",   "F1 EnvMod"),
                ("{s}_filter2_envmod",   "F2 EnvMod"),
                ("{s}_filter1_keytrack", "F1 KeyTrk"),
                ("{s}_filter2_keytrack", "F2 KeyTrk"),
            ]

        # Mix/FX
        if self.mix_bank == 0:
            return [
                ("{s}_level_o1",    "Osc 1 Lvl"),
                ("{s}_level_o2",    "Osc 2 Lvl"),
                ("{s}_level_o3",    "Osc 3 Lvl"),
                ("{s}_level_noise", "Noise Lvl"),
            ]
        if self.mix_bank == 1:
            return [
                ("{s}_level_ring12", "Ring 1x2"),
                ("{s}_level_ring23", "Ring 2x3"),
                ("{s}_fm_depth",     "FM Depth"),
                ("{s}_level_pfg",    "PreFltGn"),
            ]
        if self.mix_bank == 2:
            return [
                ("{s}_send_fx_1", "FX 1 Send"),
                ("{s}_send_fx_2", "FX 2 Send"),
                ("{s}_send_fx_3", "FX 3 Send"),
                ("{s}_send_fx_4", "FX 4 Send"),
            ]
        return [
            ("volume_FX1", "FX 1 Ret"),
            ("volume_FX2", "FX 2 Ret"),
            ("{s}_volume", "Scene Vol"),
            ("volume",     "Master"),
        ]

    def _build_page_zctrls(self, tab_name):
        sc_tag = "A" if self.scene == 0 else "B"
        zctrls = []
        for raw_key, short_label in self._tab_items(tab_name):
            z = self._get_zctrl(raw_key)
            if z is not None:
                if "{s}" in raw_key:
                    z.short_name = f"{sc_tag}:{short_label}"
                else:
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
        """Instantly rebind Zynthian's 4 physical encoders to the current tab's active sub-bank."""
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
            logging.debug(f"Surge XT widget: live swap error => {e}")

    def _sync_zyngui_list(self, target_tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page_by_title(target_tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Surge XT widget: sync list error => {e}")

    def _select_page_by_title(self, title):
        try:
            list_data = getattr(self.zyngui_control, "list_data", None)
            if list_data:
                for i, row in enumerate(list_data):
                    if len(row) >= 5 and row[2] == title and row[3] is self.processor:
                        self.zyngui_control.select(i)
                        self.active_tab = title
                        self.last_screen_title = title
                        return True
            ctrls = getattr(self.zyngui_control, "ctrl_screens", [])
            for idx, c in enumerate(ctrls):
                if getattr(c, "title", None) == title:
                    self.zyngui_control.select_screen(idx)
                    self.last_screen_title = title
                    return True
            self.last_screen_title = title
        except Exception as e:
            logging.debug(f"Surge XT widget: select page error => {e}")
        return False

    def _follow_page(self):
        try:
            info = getattr(self.zyngui_control, "screen_info", None)
            title = None
            if info and len(info) >= 5 and info[3] is self.processor:
                title = info[2]
            elif hasattr(self.zyngui_control, "get_current_screen"):
                cur_scr = self.zyngui_control.get_current_screen()
                title = getattr(cur_scr, "title", None)
            if title and title != self.last_screen_title and title in TABS:
                self.last_screen_title = title
                if title != self.active_tab:
                    self.active_tab = title
                    self.last_snapshot = None
                    self._draw()
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # Zynthian Controller Helpers
    # --------------------------------------------------------------------------
    @staticmethod
    def _norm(zctrl, default=0.0):
        if zctrl is None:
            return default
        try:
            return max(0.0, min(1.0, float(zctrl.get_normalized_value())))
        except Exception:
            try:
                vmin = float(getattr(zctrl, "value_min", 0.0))
                vmax = float(getattr(zctrl, "value_max", 1.0))
                rng = vmax - vmin if vmax != vmin else 1.0
                return max(0.0, min(1.0, (float(zctrl.value) - vmin) / rng))
            except Exception:
                return default

    @staticmethod
    def _set_norm(zctrl, norm_val):
        if zctrl is None:
            return
        nv = max(0.0, min(1.0, float(norm_val)))
        try:
            zctrl.set_normalized_value(nv, send=True)
        except Exception:
            try:
                vmin = float(getattr(zctrl, "value_min", 0.0))
                vmax = float(getattr(zctrl, "value_max", 1.0))
                zctrl.set_value(vmin + nv * (vmax - vmin), send=True)
            except Exception:
                pass

    @staticmethod
    def _cycle_enum(zctrl, step=1):
        if zctrl is None:
            return
        try:
            ticks = getattr(zctrl, "ticks", None)
            labels = getattr(zctrl, "labels", None)
            if ticks and len(ticks) > 1:
                cur_idx = zctrl.get_value2index()
                if cur_idx is None:
                    cur_idx = 0
                nxt_idx = (cur_idx + step) % len(ticks)
                zctrl.set_value(ticks[nxt_idx], send=True)
                return
            if labels and len(labels) > 1:
                cur_idx = 0
                try:
                    cur_lbl = str(zctrl.get_value2label())
                    if cur_lbl in labels:
                        cur_idx = labels.index(cur_lbl)
                except Exception:
                    cur_idx = 0
                nxt_idx = (cur_idx + step) % len(labels)
                nv = nxt_idx / (len(labels) - 1)
                zynthian_widget_surge_xt._set_norm(zctrl, nv)
                return
            cur = zynthian_widget_surge_xt._norm(zctrl)
            zynthian_widget_surge_xt._set_norm(zctrl, 0.0 if cur >= 0.5 else 1.0)
        except Exception as e:
            logging.debug(f"Surge XT widget: cycle enum error => {e}")

    @staticmethod
    def _fmt(zctrl):
        if zctrl is None:
            return "--"
        try:
            lbl = zctrl.get_value2label()
            if lbl:
                return str(lbl).strip()
        except Exception:
            pass
        try:
            val = float(zctrl.value)
            return f"{val:.2f}"
        except Exception:
            return "--"

    # --------------------------------------------------------------------------
    # Lifecycle & Redraw Trigger
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
            return [f"macro_{i}" for i in range(8)] + [
                "scenemode", "{s}_polymode", "polylimit", "{s}_octave", "character", "fx_bypass",
                "{s}_pitch", "{s}_portamento", "{s}_pbrange_up", "{s}_pbrange_dn",
                "{s}_drift", "{s}_vca_level", "{s}_vca_velsense", "{s}_ktrkroot"
            ]
        if t == "Osc":
            oi = self.osc_idx + 1
            return [f"{{s}}_osc{oi}_type", f"{{s}}_osc{oi}_octave", f"{{s}}_osc{oi}_pitch",
                    f"{{s}}_osc{oi}_keytrack", f"{{s}}_osc{oi}_retrigger"] + [
                        f"{{s}}_osc{oi}_param{pi}" for pi in range(7)
                    ]
        if t == "Filter":
            return [
                "{s}_filter1_type", "{s}_filter1_cutoff", "{s}_filter1_resonance", "{s}_filter1_envmod", "{s}_filter1_keytrack",
                "{s}_filter2_type", "{s}_filter2_cutoff", "{s}_filter2_resonance", "{s}_filter2_envmod", "{s}_filter2_keytrack",
                "{s}_fb_config", "{s}_f_balance", "{s}_ws_type", "{s}_ws_drive",
                "{s}_f2_cf_is_offset", "{s}_f2_link_resonance", "{s}_feedback", "{s}_lowcut"
            ]
        if t == "Env":
            return [
                "{s}_env1_attack", "{s}_env1_attack_shape", "{s}_env1_decay", "{s}_env1_decay_shape",
                "{s}_env1_sustain", "{s}_env1_release", "{s}_env1_release_shape", "{s}_env1_mode",
                "{s}_env2_attack", "{s}_env2_attack_shape", "{s}_env2_decay", "{s}_env2_decay_shape",
                "{s}_env2_sustain", "{s}_env2_release", "{s}_env2_release_shape", "{s}_env2_mode",
                "{s}_filter1_envmod", "{s}_filter2_envmod", "{s}_vca_velsense", "{s}_vca_level"
            ]
        if t == "LFO/Mod":
            lkey, _ = ALL_LFO_SLOTS[self.lfo_idx]
            return [
                f"{{s}}_{lkey}_shape", f"{{s}}_{lkey}_rate", f"{{s}}_{lkey}_phase", f"{{s}}_{lkey}_magnitude",
                f"{{s}}_{lkey}_deform", f"{{s}}_{lkey}_trigmode", f"{{s}}_{lkey}_unipolar", f"{{s}}_{lkey}_delay",
                f"{{s}}_{lkey}_attack", f"{{s}}_{lkey}_hold", f"{{s}}_{lkey}_decay", f"{{s}}_{lkey}_sustain", f"{{s}}_{lkey}_release",
                "{s}_filter1_envmod", "{s}_filter2_envmod", "{s}_filter1_keytrack", "{s}_filter2_keytrack"
            ]
        # Mix/FX
        keys = ["{s}_fm_switch", "{s}_fm_depth", "{s}_level_pfg", "{s}_volume", "volume",
                "{s}_send_fx_1", "{s}_send_fx_2", "{s}_send_fx_3", "{s}_send_fx_4", "volume_FX1", "volume_FX2"]
        for ch in ("o1", "o2", "o3", "ring12", "ring23", "noise"):
            keys.extend([f"{{s}}_level_{ch}", f"{{s}}_mute_{ch}", f"{{s}}_solo_{ch}", f"{{s}}_route_{ch}"])
        return keys

    def _state_snapshot(self):
        vals = tuple(round(self._norm(self._get_zctrl(k)), 4) for k in self._watched_keys())
        return (
            self.width, self.height, self.scene, self.active_tab, self.eco_on,
            self.macro_bank, self.osc_idx, self.osc_bank,
            self.filter_bank, self.env_bank,
            self.lfo_group, self.lfo_slot, self.lfo_idx, self.lfo_bank, self.mix_bank,
            vals,
        )

    def refresh_gui(self):
        if not self.processor or self.width < 40 or self.height < 40:
            return
        self._maybe_sync_preset(only_zero=False)
        self._follow_page()
        if self.active_tab == "Osc":
            t_idx = self._osc_type_idx()
            if getattr(self, "_last_osc_type", None) != (self.osc_idx, t_idx):
                self._last_osc_type = (self.osc_idx, t_idx)
                self._live_swap_encoders("Osc")
        snap = self._state_snapshot()
        if snap != self.last_snapshot:
            self.last_snapshot = snap
            self._draw()

    # --------------------------------------------------------------------------
    # Drawing Primitives
    # --------------------------------------------------------------------------
    def _font(self, size, bold=False):
        k = (int(size), bool(bold))
        if k not in self._font_cache:
            family = zynthian_gui_config.font_family
            weight = "bold" if bold else "normal"
            self._font_cache[k] = tkinter.font.Font(family=family, size=max(6, int(size)), weight=weight)
        return self._font_cache[k]

    def _fs(self, scale=1.0):
        h = max(240, self.height)
        base = max(8, min(14, int(h * 0.024)))
        return max(7, int(base * scale))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, hit_kind, hit_payload, subtext=None):
        c = self.widget_canvas
        bg = accent if active else COL_PANEL
        fg = "#0d0e12" if active else COL_TEXT
        border = accent if active else COL_BORDER
        c.create_rectangle(x0, y0, x1, y1, fill=bg, outline=border, width=2 if active else 1)
        if subtext:
            ty = y0 + (y1 - y0) * 0.38
            c.create_text((x0 + x1) / 2, ty, text=text, fill=fg,
                          font=self._font(self._fs(0.88), bold=True))
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.72, text=subtext,
                          fill="#1b1c22" if active else accent,
                          font=self._font(self._fs(0.72), bold=False))
        else:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text, fill=fg,
                          font=self._font(self._fs(0.85), bold=True))
        if hit_kind is not None:
            self.hitboxes.append((x0, y0, x1, y1, hit_kind, hit_payload))

    def _draw_bank_bar(self, x0, y0, x1, y1, banks, active_idx, accent, bank_kind):
        gap = 6
        n = len(banks)
        bw = (x1 - x0 - gap * (n - 1)) / n
        for i, bname in enumerate(banks):
            bx0 = x0 + i * (bw + gap)
            self._draw_pill(bx0, y0, bx0 + bw, y1, bname, i == active_idx, accent,
                            bank_kind, i)

    def _draw_param_box(self, x0, y0, x1, y1, raw_key, label, accent, bank_kind=None, bank_idx=None, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(raw_key)
        val = self._norm(z)
        fmt = self._fmt(z)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        ty0 = y1 - 4
        ty1 = y1
        c.create_rectangle(x0, ty0, x1, ty1, fill=COL_TRACK, outline="")
        if bipolar:
            mid = (x0 + x1) / 2
            bx = mid + (val - 0.5) * (x1 - x0)
            c.create_rectangle(min(mid, bx), ty0, max(mid, bx), ty1, fill=accent, outline="")
        else:
            c.create_rectangle(x0, ty0, x0 + val * (x1 - x0), ty1, fill=accent, outline="")

        c.create_text(x0 + 6, y0 + (y1 - y0) * 0.38, text=label, anchor="w",
                      fill=COL_DIM, font=self._font(self._fs(0.75), bold=False))
        c.create_text(x1 - 6, y0 + (y1 - y0) * 0.38, text=fmt[:10], anchor="e",
                      fill=COL_TEXT, font=self._font(self._fs(0.82), bold=True))

        self.hitboxes.append((
            x0, y0, x1, y1, "hfader",
            {"key": raw_key, "tx0": x0, "tx1": x1, "bank_kind": bank_kind, "bank_idx": bank_idx},
        ))

    def _draw_vfader(self, x0, y0, x1, y1, raw_key, label, accent, bank_kind=None, bank_idx=None):
        c = self.widget_canvas
        z = self._get_zctrl(raw_key)
        val = self._norm(z)
        fmt = self._fmt(z)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        lbl_h = 16
        val_h = 16
        c.create_text((x0 + x1) / 2, y0 + lbl_h / 2 + 1, text=label, fill=COL_TEXT,
                      font=self._font(self._fs(0.78), bold=True))
        c.create_text((x0 + x1) / 2, y1 - val_h / 2 - 1, text=fmt[:7], fill=accent,
                      font=self._font(self._fs(0.72), bold=False))

        track_y0 = y0 + lbl_h + 3
        track_y1 = y1 - val_h - 3
        tw = 8
        tx0 = (x0 + x1) / 2 - tw / 2
        tx1 = tx0 + tw
        c.create_rectangle(tx0, track_y0, tx1, track_y1, fill=COL_TRACK, outline="")
        fill_y = track_y1 - val * (track_y1 - track_y0)
        c.create_rectangle(tx0, fill_y, tx1, track_y1, fill=accent, outline="")
        hw = 14
        hh = 6
        hx0 = (x0 + x1) / 2 - hw / 2
        hx1 = hx0 + hw
        c.create_rectangle(hx0, fill_y - hh / 2, hx1, fill_y + hh / 2,
                           fill="#ffffff", outline=accent, width=1)

        self.hitboxes.append((
            x0, y0, x1, y1, "vfader",
            {"key": raw_key, "ty0": track_y0, "ty1": track_y1, "bank_kind": bank_kind, "bank_idx": bank_idx},
        ))

    # --------------------------------------------------------------------------
    # Main Canvas Renderer
    # --------------------------------------------------------------------------
    def _draw(self):
        w, h = self.width, self.height
        if w < 40 or h < 40:
            return
        c = self.widget_canvas
        c.delete("all")
        self.hitboxes.clear()

        hdr_h = max(36, min(46, int(h * 0.11)))
        self._draw_header(6, 4, w - 6, hdr_h)

        body_y0 = hdr_h + 6
        body_y1 = h - 6
        bx0, bx1 = 6, w - 6

        if self.active_tab == "Macro":
            self._draw_tab_macro(bx0, body_y0, bx1, body_y1)
        elif self.active_tab == "Osc":
            self._draw_tab_osc(bx0, body_y0, bx1, body_y1)
        elif self.active_tab == "Filter":
            self._draw_tab_filter(bx0, body_y0, bx1, body_y1)
        elif self.active_tab == "Env":
            self._draw_tab_env(bx0, body_y0, bx1, body_y1)
        elif self.active_tab == "LFO/Mod":
            self._draw_tab_lfo(bx0, body_y0, bx1, body_y1)
        elif self.active_tab == "Mix/FX":
            self._draw_tab_mix(bx0, body_y0, bx1, body_y1)

    # --------------------------------------------------------------------------
    # Header: Scene A/B Toggle + 6 Workstation Tabs + ECO Button
    # --------------------------------------------------------------------------
    def _draw_header(self, x0, y0, x1, y1):
        gap = 6
        total_w = x1 - x0

        # Scene A/B toggle on far left
        sc_w = 48
        sc_col = COL_SCENE_A if self.scene == 0 else COL_SCENE_B
        sc_lbl = "SCN A" if self.scene == 0 else "SCN B"
        self._draw_pill(x0, y0, x0 + sc_w, y1, sc_lbl, True, sc_col, "scene", None)

        # ECO button on far right
        eco_w = 48
        eco_col = "#51cf66" if self.eco_on else "#495057"
        self._draw_pill(x1 - eco_w, y0, x1, y1, "ECO", self.eco_on, eco_col, "eco", None)

        # 6 Workstation Tabs
        tabs_w = total_w - sc_w - eco_w - gap * (len(TABS) + 1)
        tw = tabs_w / len(TABS)
        tx_start = x0 + sc_w + gap
        for i, tname in enumerate(TABS):
            tx0 = tx_start + i * (tw + gap)
            tx1 = tx0 + tw
            self._draw_pill(tx0, y0, tx1, y1, tname, tname == self.active_tab,
                            TAB_ACCENTS[tname], "tab", tname)

    # --------------------------------------------------------------------------
    # TAB 1: MACRO & PERFORMANCE (8 Universal Macros + Voice Mods)
    # --------------------------------------------------------------------------
    def _draw_tab_macro(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Macro"]

        # Row 1: Quick Performance Cycle Tiles
        tile_h = 38
        tiles = [
            ("Scene", "scenemode",    "cycle"),
            ("Play",  "{s}_polymode", "cycle"),
            ("Poly",  "polylimit",    "poly_cycle"),
            ("Oct",   "{s}_octave",   "cycle"),
            ("Char",  "character",    "cycle"),
            ("FX",    "fx_bypass",    "cycle"),
        ]
        gap = 6
        tw = (x1 - x0 - gap * (len(tiles) - 1)) / len(tiles)
        for i, (lbl, key, hit_kind) in enumerate(tiles):
            tx0 = x0 + i * (tw + gap)
            z = self._get_zctrl(key)
            self._draw_pill(tx0, y0, tx0 + tw, y0 + tile_h, lbl, False, accent,
                            hit_kind, key, subtext=self._fmt(z)[:8])

        # Row 2: Sub-bank selector for 4 physical encoders
        by0 = y0 + tile_h + 6
        bh = 34
        self._draw_bank_bar(
            x0, by0, x1, by0 + bh,
            ["Macros 1-4", "Macros 5-8", "Pitch & Glide", "Voice & Mod"],
            self.macro_bank, accent, "macro_bank",
        )

        # Row 3: 8 Macro vertical faders (2 banks of 4)
        my0 = by0 + bh + 6
        perf_h = 40
        my1 = y1 - perf_h - 6
        bank_gap = 8
        hw = (x1 - x0 - bank_gap) / 2

        for b_idx, (bx0, bx1, start_m) in enumerate([
            (x0, x0 + hw, 0),
            (x0 + hw + bank_gap, x1, 4),
        ]):
            act = (self.macro_bank == b_idx)
            c.create_rectangle(
                bx0, my0, bx1, my1,
                fill=COL_BG,
                outline=accent if act else COL_BORDER,
                width=2 if act else 1,
            )
            ipad = 4
            fw = (bx1 - bx0 - 2 * ipad - 3 * gap) / 4
            for i in range(4):
                m_idx = start_m + i
                fx0 = bx0 + ipad + i * (fw + gap)
                self._draw_vfader(
                    fx0, my0 + ipad, fx0 + fw, my1 - ipad,
                    f"macro_{m_idx}", self._macro_name(m_idx, short=True),
                    accent if act else "#376996",
                    bank_kind="macro_bank", bank_idx=b_idx,
                )

        # Row 4: Performance / Mod indicators strip
        py0 = my1 + 5
        act_p = (self.macro_bank in (2, 3))
        c.create_rectangle(
            x0, py0, x1, y1,
            fill=COL_BG,
            outline=accent if act_p else COL_BORDER,
            width=2 if act_p else 1,
        )
        if self.macro_bank == 3:
            p_items = [
                ("{s}_drift",        "Drift",    False),
                ("{s}_vca_level",    "VCA Gain", False),
                ("{s}_vca_velsense", "Vel>VCA",  False),
                ("{s}_ktrkroot",     "Key Root", False),
            ]
            bank_sel = 3
        else:
            p_items = [
                ("{s}_pitch",        "Pitch",   True),
                ("{s}_portamento",   "Glide",   False),
                ("{s}_pbrange_up",   "PB Up",   False),
                ("{s}_pbrange_dn",   "PB Down", False),
            ]
            bank_sel = 2

        pw = (x1 - x0 - 3 * gap) / 4
        for i, (key, lbl, bip) in enumerate(p_items):
            px0 = x0 + i * (pw + gap)
            self._draw_param_box(
                px0, py0 + 2, px0 + pw, y1 - 2,
                key, lbl, accent if act_p else "#376996",
                bank_kind="macro_bank", bank_idx=bank_sel, bipolar=bip,
            )

    # --------------------------------------------------------------------------
    # TAB 2: OSCILLATORS (Osc 1/2/3 + Type Grid + Live Waveform + Dynamic Params)
    # --------------------------------------------------------------------------
    def _draw_tab_osc(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Osc"]
        oi = self.osc_idx + 1
        t_idx = self._osc_type_idx(oi)
        pnames = self._osc_param_names(oi)

        # Row 1: Osc 1 / Osc 2 / Osc 3 selector + Encoder Bank selector
        r1_h = 34
        gap = 6
        left_w = (x1 - x0) * 0.36
        ow = (left_w - 2 * gap) / 3
        for i in range(3):
            ox0 = x0 + i * (ow + gap)
            self._draw_pill(ox0, y0, ox0 + ow, y0 + r1_h, f"OSC {i + 1}",
                            i == self.osc_idx, accent, "osc_idx", i)

        self._draw_bank_bar(
            x0 + left_w + 6, y0, x1, y0 + r1_h,
            ["Tone (1-3)", "Pitch & Uni", "Sub & Sync"],
            self.osc_bank, accent, "osc_bank",
        )

        # Row 2: 12 Oscillator Type tiles + Live Waveform Scope
        mid_y0 = y0 + r1_h + 6
        mid_h = int((y1 - mid_y0) * 0.48)
        mid_y1 = mid_y0 + mid_h

        grid_w = int((x1 - x0) * 0.54)
        gx1 = x0 + grid_w
        cols = 4
        rows = 3
        tw = (grid_w - (cols - 1) * 3) / cols
        th = (mid_h - (rows - 1) * 3) / rows
        short_types = ["Classic", "Modern", "Wavetbl", "Window", "Sine", "FM 2",
                       "FM 3", "String", "Twist", "Alias", "S&H", "AudioIn"]
        for idx, tlabel in enumerate(short_types):
            col = idx % cols
            row = idx // cols
            tx0 = x0 + col * (tw + 3)
            ty0 = mid_y0 + row * (th + 3)
            act = (idx == t_idx)
            c.create_rectangle(tx0, ty0, tx0 + tw, ty0 + th,
                               fill=accent if act else COL_PANEL,
                               outline=accent if act else COL_BORDER, width=2 if act else 1)
            c.create_text(tx0 + tw / 2, ty0 + th / 2, text=tlabel,
                          fill="#0d0e12" if act else COL_TEXT,
                          font=self._font(self._fs(0.72), bold=True))
            self.hitboxes.append((tx0, ty0, tx0 + tw, ty0 + th, "osc_type", idx))

        # Live Waveform Scope
        wx0 = gx1 + 6
        self._draw_osc_wave(wx0, mid_y0, x1, mid_y1, oi, t_idx, accent)

        # Row 3: Bottom 2x2 parameter grid for active Osc bank
        bot_y0 = mid_y1 + 6
        items = self._tab_items("Osc")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - bot_y0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col = i % 2
            row = i // 2
            px0 = x0 + col * (cw + gap)
            py_i = bot_y0 + row * (ch + gap)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent,
                                 bipolar=("pitch" in key))

    def _draw_osc_wave(self, x0, y0, x1, y1, oi, t_idx, accent):
        c = self.widget_canvas
        p0 = self._norm(self._get_zctrl(f"{{s}}_osc{oi}_param0"))
        p1 = self._norm(self._get_zctrl(f"{{s}}_osc{oi}_param1"), 0.5)
        p2 = self._norm(self._get_zctrl(f"{{s}}_osc{oi}_param2"), 0.5)
        p5 = self._norm(self._get_zctrl(f"{{s}}_osc{oi}_param5"), 0.0)
        zv = self._get_zctrl(f"{{s}}_osc{oi}_param6")
        voices = int(round(1 + self._norm(zv) * 15)) if (zv and t_idx in UNISON_OSC_TYPES) else 1

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=accent, width=1)
        pad = 8
        gx0, gx1 = x0 + pad, x1 - pad
        gy0, gy1 = y0 + pad, y1 - pad
        gw = max(10, gx1 - gx0)
        gh = max(10, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2
        amp = gh * 0.42

        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))
        n_pts = 64
        cycles = 2.0

        if voices > 1 and p5 > 0.02:
            sub_pts = []
            for i in range(n_pts + 1):
                t = i / n_pts
                ph = (t * cycles * 1.015 + 0.12) % 1.0
                y = math.sin(2 * math.pi * ph)
                sub_pts.extend([gx0 + t * gw, mid_y - y * amp * 0.75])
            c.create_line(sub_pts, fill="#5a3d70", width=1.2)

        pts = []
        for i in range(n_pts + 1):
            t = i / n_pts
            ph = (t * cycles) % 1.0
            if t_idx == 0:  # Classic: Pulse-Saw blend
                saw = 1.0 - 2.0 * ph
                pw = max(0.05, min(0.95, p1))
                sqr = 1.0 if ph < pw else -1.0
                y = saw * (1.0 - p0) + sqr * p0
            elif t_idx == 1:  # Modern: Saw/Pulse/Sub
                pw = max(0.05, min(0.95, p1))
                sqr = 1.0 if ph < pw else -1.0
                saw = 1.0 - 2.0 * ph
                tri = 1.0 - 4.0 * abs(ph - 0.5)
                y = (saw * p0 + sqr * (1.0 - p0)) * 0.7 + tri * p2 * 0.3
            elif t_idx == 4:  # Sine + Feedback
                fb = p1 * 0.7
                y = math.sin(2 * math.pi * ph + fb * math.sin(2 * math.pi * ph))
            elif t_idx in (5, 6):  # FM2 / FM3
                m1 = math.sin(2 * math.pi * ph * 2.0) * (p0 * 2.0)
                y = math.sin(2 * math.pi * ph + m1)
            elif t_idx == 8:  # Twist / Plaits macro
                harms = 1.0 + p1 * 3.0
                y = math.sin(2 * math.pi * ph) * (1.0 - p0) + math.sin(2 * math.pi * ph * harms) * p0
            elif t_idx == 10:  # S&H Noise
                step = int(t * cycles * 4)
                y = math.sin(step * 12.9898) * 0.8
            else:  # Wavetable / Window / General
                s1 = math.sin(2 * math.pi * ph)
                s2 = math.sin(4 * math.pi * ph) * p0
                s3 = math.sin(6 * math.pi * ph) * p1 * 0.5
                y = (s1 + s2 + s3) / max(1.0, 1.0 + p0 + p1 * 0.5)
            pts.extend([gx0 + t * gw, mid_y - y * amp])

        c.create_line(pts, fill=accent, width=2.0)
        uni_str = f"Uni: {voices}v ({int(p5*100)}%)" if voices > 1 else "1 Voice"
        c.create_text(x0 + 6, y0 + 6, text=f"{OSC_TYPES[t_idx]}  [{uni_str}]",
                      anchor="nw", fill=COL_TEXT, font=self._font(self._fs(0.72), bold=True))

    # --------------------------------------------------------------------------
    # TAB 3: FILTERS (Interactive 2D Dual Filter Curve + Keytrack & Drive)
    # --------------------------------------------------------------------------
    def _draw_tab_filter(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Filter"]

        # Row 1: Encoder Bank Selector
        bh = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + bh,
            ["Filter 1", "Filter 2", "Config & Drive", "Offset & Link"],
            self.filter_bank, accent, "filter_bank",
        )

        # Row 2: Quick Config / Waveshaper / HPF / Feedback pill strip
        ty0 = y0 + bh + 6
        th = 36
        quick = [
            ("Cfg",   "{s}_fb_config"),
            ("F1",    "{s}_filter1_type"),
            ("F2",    "{s}_filter2_type"),
            ("Shape", "{s}_ws_type"),
        ]
        gap = 6
        qw = (x1 - x0 - gap * (len(quick) - 1)) / len(quick)
        for i, (lbl, key) in enumerate(quick):
            qx0 = x0 + i * (qw + gap)
            z = self._get_zctrl(key)
            self._draw_pill(qx0, ty0, qx0 + qw, ty0 + th, lbl, False, accent,
                            "cycle", key, subtext=self._fmt(z)[:9])

        # Row 3: Dual Filter Log-Frequency Response Graph (20Hz .. 20kHz)
        gy0 = ty0 + th + 6
        bot_h = 84
        gy1 = y1 - bot_h - 6
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad_x, pad_y = 12, 10
        gx0, gx1 = x0 + pad_x, x1 - pad_x
        g_top, g_bot = gy0 + pad_y, gy1 - pad_y
        gw = max(10, gx1 - gx0)
        gh = max(10, g_bot - g_top)

        for hz, lbl in ((100.0, "100"), (1000.0, "1k"), (10000.0, "10k")):
            n_hz = (12.0 * math.log2(hz / 440.0) + 60.0) / 130.0
            lx = gx0 + max(0.0, min(1.0, n_hz)) * gw
            c.create_line(lx, gy0 + 2, lx, gy1 - 2, fill=COL_GRID, dash=(2, 4))
            c.create_text(lx + 3, gy1 - 8, text=lbl, anchor="sw", fill=COL_DIM, font=self._font(7))
        zero_y = g_top + gh * 0.45
        c.create_line(gx0, zero_y, gx1, zero_y, fill=COL_GRID, dash=(2, 4))

        f1_cut = self._norm(self._get_zctrl("{s}_filter1_cutoff"), 0.5)
        f1_res = self._norm(self._get_zctrl("{s}_filter1_resonance"), 0.0)
        f1_type_z = self._get_zctrl("{s}_filter1_type")
        f1_t = (f1_type_z.get_value2index() or 1) if f1_type_z else 1

        f2_cut = self._norm(self._get_zctrl("{s}_filter2_cutoff"), 0.5)
        f2_res = self._norm(self._get_zctrl("{s}_filter2_resonance"), 0.0)
        f2_type_z = self._get_zctrl("{s}_filter2_type")
        f2_t = (f2_type_z.get_value2index() or 0) if f2_type_z else 0

        hpf_cut = self._norm(self._get_zctrl("{s}_lowcut"), 0.0)

        def filter_curve(cut, res, ftype):
            pts = []
            n_pts = 56
            tname = FILTER_TYPES[min(ftype, len(FILTER_TYPES) - 1)]
            is_hp = tname.startswith("HP")
            is_bp = tname.startswith("BP") or "Comb" in tname
            is_notch = tname.startswith("Notch") or tname.startswith("N ")
            is_off = (ftype == 0)

            for i in range(n_pts + 1):
                t = i / n_pts
                if is_off:
                    db = 0.0
                else:
                    d = (t - cut) / 0.11
                    peak = (res * 16.0) * math.exp(-d * d * 2.2)
                    if is_hp:
                        roll = -24.0 * ((cut - t) / 0.16) ** 2 if t < cut else 0.0
                    elif is_bp:
                        roll = -18.0 * (abs(t - cut) / 0.16) ** 1.6
                    elif is_notch:
                        dip = -26.0 * math.exp(-d * d * 3.5)
                        roll = dip
                        peak = res * 6.0 * math.exp(-(abs(d) - 0.8) ** 2 * 3.0)
                    else:  # LP
                        roll = -24.0 * ((t - cut) / 0.16) ** 2 if t > cut else 0.0
                    if hpf_cut > 0.03 and t < hpf_cut:
                        roll -= 18.0 * ((hpf_cut - t) / 0.14) ** 2
                    db = max(-30.0, min(18.0, roll + peak))

                px = gx0 + t * gw
                py = zero_y - (db / 24.0) * (gh * 0.48)
                pts.extend([px, max(gy0 + 3, min(gy1 - 3, py))])
            return pts

        pts1 = filter_curve(f1_cut, f1_res, f1_t)
        pts2 = filter_curve(f2_cut, f2_res, f2_t)

        if self.filter_bank == 1:
            c.create_line(pts1, fill="#8a5522", width=1.5)
            c.create_polygon([gx0, gy1 - 2] + pts2 + [gx1, gy1 - 2], fill="#162b28", outline="")
            c.create_line(pts2, fill=COL_F2, width=2.5)
        else:
            if f2_t != 0:
                c.create_line(pts2, fill="#246b5a", width=1.5, dash=(3, 3))
            c.create_polygon([gx0, gy1 - 2] + pts1 + [gx1, gy1 - 2], fill="#2b1e14", outline="")
            c.create_line(pts1, fill=accent, width=2.5)

        for fi, cut, res, col, act in (
            (2, f2_cut, f2_res, COL_F2, self.filter_bank == 1),
            (1, f1_cut, f1_res, accent, self.filter_bank != 1),
        ):
            hx = gx0 + cut * gw
            hy = g_bot - res * gh
            r = 9 if act else 7
            c.create_oval(hx - r, hy - r, hx + r, hy + r,
                          fill=col if act else COL_PANEL_HI,
                          outline="#ffffff" if act else col, width=2 if act else 1)
            c.create_text(hx, hy, text=str(fi), fill="#000000" if act else col,
                          font=self._font(8, bold=True))

        f1_hz = fmt_hz(norm_to_hz(f1_cut))
        f2_hz = fmt_hz(norm_to_hz(f2_cut))
        f1_mod = self._fmt(self._get_zctrl("{s}_filter1_envmod"))
        hdr = f"F1: {FILTER_TYPES[min(f1_t, len(FILTER_TYPES)-1)]} {f1_hz} (EnvMod: {f1_mod}) | F2: {FILTER_TYPES[min(f2_t, len(FILTER_TYPES)-1)]} {f2_hz}"
        c.create_text(x0 + 8, gy0 + 10, text=hdr, anchor="w", fill=COL_TEXT,
                      font=self._font(self._fs(0.78), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "filter_xy",
            {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot,
             "f1_cut": f1_cut, "f1_res": f1_res, "f2_cut": f2_cut, "f2_res": f2_res},
        ))

        # Row 4: Bottom 2x2 parameter grid for active Filter bank
        py0 = gy1 + 5
        items = self._tab_items("Filter")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col = i % 2
            row = i // 2
            px0 = x0 + col * (cw + gap)
            py_i = py0 + row * (ch + gap)
            bip = any(k in key for k in ("envmod", "keytrack", "balance", "feedback"))
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl,
                                 COL_F2 if self.filter_bank == 1 else accent,
                                 bipolar=bip)

    # --------------------------------------------------------------------------
    # TAB 4: ENVELOPES (Interactive Dual ADSR + Real Curves + Digital/Analog Modes)
    # --------------------------------------------------------------------------
    def _draw_tab_env(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Env"]

        bh = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + bh,
            ["Amp ADSR", "Amp Curves", "Filter ADSR", "Filter Curves", "Env & Vel"],
            self.env_bank, accent, "env_bank",
        )

        is_feg = (self.env_bank in (2, 3))
        env_col = "#ff922b" if is_feg else accent
        prefix = "env2" if is_feg else "env1"

        gy0 = y0 + bh + 6
        bot_h = 84
        gy1 = y1 - bot_h - 6
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=env_col, width=1)

        pad = 12
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + pad + 14, gy1 - pad
        gw = max(20, gx1 - gx0)
        gh = max(20, g_bot - g_top)

        def get_adsr_nodes(pref):
            a = self._norm(self._get_zctrl(f"{{s}}_{pref}_attack"))
            d = self._norm(self._get_zctrl(f"{{s}}_{pref}_decay"))
            s = self._norm(self._get_zctrl(f"{{s}}_{pref}_sustain"))
            r = self._norm(self._get_zctrl(f"{{s}}_{pref}_release"))
            ash = self._norm(self._get_zctrl(f"{{s}}_{pref}_attack_shape"), 0.5) * 2.0 - 1.0
            dsh = self._norm(self._get_zctrl(f"{{s}}_{pref}_decay_shape"), 0.5) * 2.0 - 1.0
            rsh = self._norm(self._get_zctrl(f"{{s}}_{pref}_release_shape"), 0.5) * 2.0 - 1.0

            xa = gx0 + max(0.01, a) * (gw * 0.28)
            xd = xa + max(0.01, d) * (gw * 0.28)
            xs = xd + gw * 0.16
            xr = xs + max(0.01, r) * (gw * 0.28)
            ys = g_bot - s * gh

            # Build curved path reflecting Attack/Decay/Release shape
            n_sub = 14
            pts = []
            for k in range(n_sub + 1):
                u = k / n_sub
                v = (u ** (1.0 - ash * 1.6)) if ash < 0 else (1.0 - (1.0 - u) ** (1.0 + ash * 1.6))
                pts.extend([gx0 + u * (xa - gx0), g_bot - v * gh])
            for k in range(1, n_sub + 1):
                u = k / n_sub
                v = (u ** (1.0 - dsh * 1.6)) if dsh < 0 else (1.0 - (1.0 - u) ** (1.0 + dsh * 1.6))
                pts.extend([xa + u * (xd - xa), g_top + v * (ys - g_top)])
            pts.extend([xs, ys])
            for k in range(1, n_sub + 1):
                u = k / n_sub
                v = (u ** (1.0 - rsh * 1.6)) if rsh < 0 else (1.0 - (1.0 - u) ** (1.0 + rsh * 1.6))
                pts.extend([xs + u * (xr - xs), ys + v * (g_bot - ys)])

            return a, d, s, r, ash, dsh, rsh, xa, xd, xs, xr, ys, pts

        # Inactive envelope drawn dashed
        bg_pref = "env1" if is_feg else "env2"
        bg_col = "#2d5e38" if is_feg else "#784c22"
        _, _, _, _, _, _, _, _, _, _, _, _, bg_pts = get_adsr_nodes(bg_pref)
        c.create_line(bg_pts, fill=bg_col, width=1.5, dash=(3, 3))

        # Active envelope drawn solid with shaded area
        a, d, s, r, ash, dsh, rsh, xa, xd, xs, xr, ys, pts = get_adsr_nodes(prefix)
        c.create_polygon(pts + [gx0, g_bot], fill="#2b1f14" if is_feg else "#16291b", outline="")
        c.create_line(pts, fill=env_col, width=2.5)

        for tag, hx, hy in (("A", xa, g_top), ("D/S", xd, ys), ("R", xr, g_bot)):
            c.create_oval(hx - 7, hy - 7, hx + 7, hy + 7, fill=env_col, outline="#ffffff", width=2)

        a_txt = fmt_time_s(norm_to_env_s(a))
        d_txt = fmt_time_s(norm_to_env_s(d))
        s_txt = f"{int(round(s * 100))}%"
        r_txt = fmt_time_s(norm_to_env_s(r))
        mode_z = self._get_zctrl(f"{{s}}_{prefix}_mode")
        mode_txt = self._fmt(mode_z)
        ash_txt = self._fmt(self._get_zctrl(f"{{s}}_{prefix}_attack_shape"))
        hdr = f"{'FILTER EG' if is_feg else 'AMP EG'} [{mode_txt}]  A:{a_txt} ({ash_txt})  D:{d_txt}  S:{s_txt}  R:{r_txt}"
        c.create_text(x0 + 8, gy0 + 10, text=hdr, anchor="w", fill=env_col,
                      font=self._font(self._fs(0.80), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "env_graph",
            {"prefix": prefix, "gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
             "xa": xa, "xd": xd, "xs": xs, "xr": xr, "ys": ys},
        ))

        # Bottom 2x2 parameter cards for active Env bank
        py0 = gy1 + 5
        gap = 4
        items = self._tab_items("Env")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col = i % 2
            row = i // 2
            px0 = x0 + col * (cw + gap)
            py_i = py0 + row * (ch + gap)
            bip = ("envmod" in key)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, env_col,
                                 bipolar=bip)

    # --------------------------------------------------------------------------
    # TAB 5: LFO / MODULATION (12 LFOs + DAHDSR Envelopes + Phase & Mod Depths)
    # --------------------------------------------------------------------------
    def _draw_tab_lfo(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["LFO/Mod"]
        lkey, ltitle = ALL_LFO_SLOTS[self.lfo_idx]

        # Row 1: Group Selector (Voice LFO 1-6 vs Scene LFO 1-6) + 6 Slot Pills
        r1_h = 36
        gap = 6
        grp_w = int((x1 - x0) * 0.38)
        slot_w_total = (x1 - x0) - grp_w - gap

        # Voice vs Scene LFO group toggle pills
        gw = (grp_w - gap) / 2
        self._draw_pill(x0, y0, x0 + gw, y0 + r1_h, "Voice (1-6)",
                        self.lfo_group == 0, accent, "lfo_group", 0)
        self._draw_pill(x0 + gw + gap, y0, x0 + grp_w, y0 + r1_h, "Scene (1-6)",
                        self.lfo_group == 1, accent, "lfo_group", 1)

        # 6 Slot pills (L1..L6 or SL1..SL6)
        sw = (slot_w_total - gap * 5) / 6
        slot_x0 = x0 + grp_w + gap
        for i in range(6):
            sx = slot_x0 + i * (sw + gap)
            s_name = f"L{i+1}" if self.lfo_group == 0 else f"SL{i+1}"
            self._draw_pill(sx, y0, sx + sw, y0 + r1_h, s_name,
                            i == self.lfo_slot, accent, "lfo_slot", i)

        # Row 2: Encoder Bank Bar (Wave / Trig & Phase / EG Env / Mod Depths)
        r2_y = y0 + r1_h + 6
        r2_h = 34
        self._draw_bank_bar(
            x0, r2_y, x1, r2_y + r2_h,
            ["Wave & Rate", "Trig & Phase", "LFO Envelope", "Mod Depths"],
            self.lfo_bank, accent, "lfo_bank",
        )

        # Row 3: 10 Clickable LFO Shape Tiles
        r3_y = r2_y + r2_h + 6
        r3_h = 32
        sh_z = self._get_zctrl(f"{{s}}_{lkey}_shape")
        sh_idx = (sh_z.get_value2index() or 0) if sh_z else 0
        short_shapes = ["Sine", "Tri", "Sqr", "Saw", "Noise", "S&H", "Env", "Step", "MSEG", "Form"]
        sgap = 4
        sh_w = (x1 - x0 - sgap * (len(short_shapes) - 1)) / len(short_shapes)
        for i, slbl in enumerate(short_shapes):
            sx0 = x0 + i * (sh_w + sgap)
            act = (i == sh_idx)
            c.create_rectangle(sx0, r3_y, sx0 + sh_w, r3_y + r3_h,
                               fill=accent if act else COL_PANEL,
                               outline=accent if act else COL_BORDER, width=2 if act else 1)
            c.create_text(sx0 + sh_w / 2, r3_y + r3_h / 2, text=slbl,
                          fill="#0d0e12" if act else COL_TEXT,
                          font=self._font(self._fs(0.74), bold=True))
            self.hitboxes.append((sx0, r3_y, sx0 + sh_w, r3_y + r3_h, "lfo_shape", i))

        # Row 4: DAHDSR Envelope-wrapped LFO Waveform Graph
        gy0 = r3_y + r3_h + 6
        bot_h = 80
        gy1 = y1 - bot_h - 6
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        rate = self._norm(self._get_zctrl(f"{{s}}_{lkey}_rate"), 0.4)
        depth = self._norm(self._get_zctrl(f"{{s}}_{lkey}_magnitude"), 0.8)
        deform = self._norm(self._get_zctrl(f"{{s}}_{lkey}_deform"), 0.5)
        phase = self._norm(self._get_zctrl(f"{{s}}_{lkey}_phase"), 0.0)
        delay = self._norm(self._get_zctrl(f"{{s}}_{lkey}_delay"), 0.0)
        attack = self._norm(self._get_zctrl(f"{{s}}_{lkey}_attack"), 0.0)
        hold = self._norm(self._get_zctrl(f"{{s}}_{lkey}_hold"), 0.0)
        decay = self._norm(self._get_zctrl(f"{{s}}_{lkey}_decay"), 0.0)
        sustain = self._norm(self._get_zctrl(f"{{s}}_{lkey}_sustain"), 1.0)
        unip = self._norm(self._get_zctrl(f"{{s}}_{lkey}_unipolar"), 0.0) >= 0.5

        pad = 10
        gx0, gx1 = x0 + pad, x1 - pad
        gw = max(10, gx1 - gx0)
        mid_y = (gy0 + gy1) / 2 + 4
        amp = max(8, (gy1 - gy0) / 2 - 14)
        base_y = (gy1 - 8) if unip else mid_y
        c.create_line(gx0, base_y, gx1, base_y, fill=COL_GRID, dash=(2, 4))

        cycles = 1.5 + rate * 5.5
        d_frac = delay * 0.18
        a_frac = attack * 0.22
        h_frac = hold * 0.12
        dec_frac = decay * 0.22
        pts = []
        env_pts = []
        n_pts = 96

        for i in range(n_pts + 1):
            t = i / n_pts
            # DAHDSR envelope contour calculation
            if t < d_frac:
                env_g = 0.0
            elif a_frac > 0.01 and t < d_frac + a_frac:
                env_g = (t - d_frac) / a_frac
            elif t < d_frac + a_frac + h_frac:
                env_g = 1.0
            elif dec_frac > 0.01 and t < d_frac + a_frac + h_frac + dec_frac:
                dec_t = (t - (d_frac + a_frac + h_frac)) / dec_frac
                env_g = 1.0 - dec_t * (1.0 - sustain)
            else:
                env_g = sustain
            env_g *= depth

            ph = (t * cycles + phase) % 1.0
            if sh_idx == 0:
                y = math.sin(2 * math.pi * ph)
            elif sh_idx == 1:
                y = 1.0 - 4.0 * abs(ph - 0.5)
            elif sh_idx == 2:
                pw = 0.5 + (deform - 0.5) * 0.7
                y = 1.0 if ph < pw else -1.0
            elif sh_idx == 3:
                y = 1.0 - 2.0 * ph
            elif sh_idx in (4, 5):
                step = int(t * cycles * (2 if sh_idx == 5 else 6))
                y = math.sin(step * 12.9898) * 0.9
            elif sh_idx == 6:
                y = math.exp(-t * (2.5 - deform * 1.8)) * 2.0 - 1.0
            else:
                step = int(ph * 4)
                y = [0.8, -0.4, 0.4, -0.9][step % 4]

            bend = (deform - 0.5) * 1.4
            if abs(bend) > 0.05 and sh_idx in (0, 1, 3):
                y = (1.0 if y >= 0 else -1.0) * (abs(y) ** max(0.35, 1.0 - bend * 0.5))

            px = gx0 + t * gw
            if unip:
                val = 0.5 * (y + 1.0) * env_g
                py = base_y - val * (amp * 1.7)
                ey = base_y - env_g * (amp * 1.7)
            else:
                py = mid_y - y * env_g * amp
                ey = mid_y - env_g * amp
            pts.extend([px, py])
            env_pts.extend([px, ey])

        if any(v > 0.01 for v in (d_frac, a_frac, h_frac, dec_frac)) or sustain < 0.98:
            c.create_line(env_pts, fill="#38d9a9", width=1.2, dash=(3, 3))
        c.create_line(pts, fill=accent, width=2.2)

        rate_txt = fmt_lfo_hz(norm_to_lfo_hz(rate))
        trig_z = self._get_zctrl(f"{{s}}_{lkey}_trigmode")
        trig_txt = self._fmt(trig_z)
        hdr = f"{ltitle}: {LFO_SHAPES[sh_idx]}   Rate: {rate_txt}   Depth: {int(round(depth*100))}%   Phase: {int(round(phase*360))}°   Trig: {trig_txt}"
        c.create_text(x0 + 8, gy0 + 10, text=hdr, anchor="w", fill=accent,
                      font=self._font(self._fs(0.78), bold=True))

        # Row 5: Bottom 2x2 parameter cards for active LFO bank
        py0 = gy1 + 5
        items = self._tab_items("LFO/Mod")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - gap) / 2
        for i, (key, lbl) in enumerate(items):
            col = i % 2
            row = i // 2
            px0 = x0 + col * (cw + gap)
            py_i = py0 + row * (ch + gap)
            bip = any(k in key for k in ("deform", "envmod", "keytrack"))
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent,
                                 bipolar=bip)

    # --------------------------------------------------------------------------
    # TAB 6: MIXER & FX (6-Ch Mixer + FM Routing & Depth + FX Sends & Master)
    # --------------------------------------------------------------------------
    def _draw_tab_mix(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Mix/FX"]

        bh = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + bh,
            ["Osc Mix", "Ring & FM", "FX Sends", "Master & Ret"],
            self.mix_bank, accent, "mix_bank",
        )

        by0 = y0 + bh + 6
        left_w = int((x1 - x0) * 0.62)
        lx1 = x0 + left_w
        rx0 = lx1 + 6

        # Left Panel: 6 Channel Strips
        channels = [
            ("o1",     "O1",  0),
            ("o2",     "O2",  0),
            ("o3",     "O3",  0),
            ("ring12", "R12", 1),
            ("ring23", "R23", 1),
            ("noise",  "Ns",  0),
        ]
        gap = 6
        cw = (left_w - gap * 5) / 6
        btn_h = 34

        for i, (ch_key, lbl, b_idx) in enumerate(channels):
            cx0 = x0 + i * (cw + gap)
            cx1 = cx0 + cw

            rt_z = self._get_zctrl(f"{{s}}_route_{ch_key}")
            rt_idx = (rt_z.get_value2index() or 1) if rt_z else 1
            rt_txt = ROUTES[min(rt_idx, 2)]
            rt_col = "#ff922b" if rt_idx == 0 else (COL_F2 if rt_idx == 2 else "#4dabf7")
            c.create_rectangle(cx0, by0, cx1, by0 + btn_h, fill=COL_PANEL_HI, outline=rt_col, width=1)
            c.create_text((cx0 + cx1) / 2, by0 + btn_h / 2, text=rt_txt, fill=rt_col,
                          font=self._font(self._fs(0.72), bold=True))
            self.hitboxes.append((cx0, by0, cx1, by0 + btn_h, "cycle", f"{{s}}_route_{ch_key}"))

            my0 = by0 + btn_h + 4
            mz = self._get_zctrl(f"{{s}}_mute_{ch_key}")
            m_act = (self._norm(mz) >= 0.5)
            self._draw_pill(cx0, my0, cx1, my0 + btn_h, "M", m_act, "#ff6b6b",
                            "cycle", f"{{s}}_mute_{ch_key}")

            sy0 = my0 + btn_h + 4
            sz = self._get_zctrl(f"{{s}}_solo_{ch_key}")
            s_act = (self._norm(sz) >= 0.5)
            self._draw_pill(cx0, sy0, cx1, sy0 + btn_h, "S", s_act, "#ffd43b",
                            "cycle", f"{{s}}_solo_{ch_key}")

            fy0 = sy0 + btn_h + 4
            self._draw_vfader(cx0, fy0, cx1, y1, f"{{s}}_level_{ch_key}", lbl, accent,
                              bank_kind="mix_bank", bank_idx=b_idx)

        # Right Panel: FM, FX Sends & Master Output
        c.create_rectangle(rx0, by0, x1, y1, fill=COL_BG, outline=COL_BORDER, width=1)
        rpad = 6
        rw = (x1 - rx0 - 2 * rpad - 3 * gap) / 4

        if self.mix_bank == 1:
            right_faders = [
                ("{s}_fm_depth",  "FM Depth", accent, 1),
                ("{s}_level_pfg", "PreFltGn", accent, 1),
                ("{s}_volume",    "Scn Vol",  COL_TEXT, 3),
                ("volume",        "Master",   COL_TEXT, 3),
            ]
        elif self.mix_bank == 2:
            right_faders = [
                ("{s}_send_fx_1", "FX 1", "#4dabf7", 2),
                ("{s}_send_fx_2", "FX 2", "#4dabf7", 2),
                ("{s}_send_fx_3", "FX 3", "#4dabf7", 2),
                ("{s}_send_fx_4", "FX 4", "#4dabf7", 2),
            ]
        else:
            right_faders = [
                ("{s}_send_fx_1", "FX 1",    "#4dabf7", 2),
                ("{s}_send_fx_2", "FX 2",    "#4dabf7", 2),
                ("{s}_volume",    "Scn Vol", COL_TEXT,  3),
                ("volume",        "Master",  COL_TEXT,  3),
            ]

        for i, (f_key, f_lbl, f_col, f_bidx) in enumerate(right_faders):
            fx0 = rx0 + rpad + i * (rw + gap)
            self._draw_vfader(fx0, by0 + rpad, fx0 + rw, y1 - rpad, f_key, f_lbl, f_col,
                              bank_kind="mix_bank", bank_idx=f_bidx)

    # --------------------------------------------------------------------------
    # Touch & Drag Interaction
    # --------------------------------------------------------------------------
    def _find_hit(self, x, y):
        for item in reversed(self.hitboxes):
            x0, y0, x1, y1, kind, payload = item
            if x0 <= x <= x1 and y0 <= y <= y1:
                return kind, payload
        return None, None

    def _toggle_eco(self):
        def find_z(raw_key):
            return self._get_zctrl(raw_key)

        if self.eco_on:
            for key, orig_val in self._eco_backup.items():
                z = find_z(key)
                if z is not None:
                    z.set_value(orig_val, send=True)
            self._eco_backup.clear()
            self.eco_on = False
            return

        backup = {}

        def set_with_backup(key, new_val):
            z = find_z(key)
            if z is None:
                return
            cur = self._norm(z)
            if abs(cur - new_val) > 1e-4:
                backup[key] = cur
                z.set_value(new_val, send=True)

        z_poly = find_z("polylimit")
        if z_poly is not None:
            cur_v = int(round(2 + self._norm(z_poly) * 62))
            if cur_v > 8:
                set_with_backup("polylimit", (8 - 2) / 62.0)

        for sc in ("a", "b"):
            for oi in (1, 2, 3):
                zt = find_z(f"{sc}_osc{oi}_type")
                t_idx = (zt.get_value2index() or 0) if zt else 0
                if t_idx in UNISON_OSC_TYPES:
                    zv = find_z(f"{sc}_osc{oi}_param6")
                    if zv is not None:
                        voices = int(round(1 + self._norm(zv) * 15))
                        if voices > 4:
                            set_with_backup(f"{sc}_osc{oi}_param6", 2.0 / 15.0)

            for fi in (1, 2):
                zf = find_z(f"{sc}_filter{fi}_type")
                if zf is not None and getattr(zf, "ticks", None):
                    f_idx = zf.get_value2index() or 0
                    if f_idx in HEAVY_FILTER_MAP:
                        lite_idx = HEAVY_FILTER_MAP[f_idx]
                        set_with_backup(f"{sc}_filter{fi}_type", zf.ticks[lite_idx])

        # Also tame heavy global Send FX chains (All FX -> No Send FX) while keeping Scene FX
        z_fxb = find_z("fx_bypass")
        if z_fxb is not None:
            ticks = getattr(z_fxb, "ticks", None)
            if ticks and len(ticks) >= 2:
                fx_idx = z_fxb.get_value2index() or 0
                if fx_idx == 0:
                    set_with_backup("fx_bypass", ticks[1])
            elif self._norm(z_fxb) < 0.15:
                set_with_backup("fx_bypass", 1.0 / 3.0)

        self._eco_backup = backup
        self.eco_on = True

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

        if kind == "scene":
            self.scene = 1 - self.scene
            self._bound_proc_id = (id(self.processor), self.scene)
            self._rebuild_all_pages(select_tab=self.active_tab, rebuild_list=False)
            self._draw()
            return

        if kind == "eco":
            self._toggle_eco()
            self.last_snapshot = None
            self._draw()
            return

        if kind == "poly_cycle":
            z = self._get_zctrl("polylimit")
            if z is not None:
                cur_v = int(round(2 + self._norm(z) * 62))
                nxt = next((p for p in POLY_PRESETS if p > cur_v), POLY_PRESETS[0])
                self._set_norm(z, (nxt - 2) / 62.0)
            self.last_snapshot = None
            self._draw()
            return

        if kind in ("macro_bank", "osc_bank", "filter_bank", "env_bank", "lfo_bank", "mix_bank"):
            self._switch_subbank(kind, payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "osc_idx":
            self.osc_idx = payload
            self._live_swap_encoders("Osc")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "osc_type":
            oi = self.osc_idx + 1
            z = self._get_zctrl(f"{{s}}_osc{oi}_type")
            if z and getattr(z, "ticks", None) and 0 <= payload < len(z.ticks):
                z.set_value(z.ticks[payload], send=True)
            self._switch_subbank("osc_bank", 0)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "lfo_group":
            self.lfo_group = payload
            self.lfo_idx = self.lfo_group * 6 + self.lfo_slot
            self._live_swap_encoders("LFO/Mod")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "lfo_slot":
            self.lfo_slot = payload
            self.lfo_idx = self.lfo_group * 6 + self.lfo_slot
            self._live_swap_encoders("LFO/Mod")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "lfo_shape":
            lkey, _ = ALL_LFO_SLOTS[self.lfo_idx]
            z = self._get_zctrl(f"{{s}}_{lkey}_shape")
            if z and getattr(z, "ticks", None) and 0 <= payload < len(z.ticks):
                z.set_value(z.ticks[payload], send=True)
            self._switch_subbank("lfo_bank", 0)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "cycle":
            self._cycle_enum(self._get_zctrl(payload))
            self.last_snapshot = None
            self._draw()
            return

        if kind == "filter_xy":
            gx0, gx1 = payload["gx0"], payload["gx1"]
            gy0, gy1 = payload["gy0"], payload["gy1"]
            f1_dist = math.hypot(event.x - (gx0 + payload["f1_cut"] * (gx1 - gx0)),
                                 event.y - (gy1 - payload["f1_res"] * (gy1 - gy0)))
            f2_dist = math.hypot(event.x - (gx0 + payload["f2_cut"] * (gx1 - gx0)),
                                 event.y - (gy1 - payload["f2_res"] * (gy1 - gy0)))
            f_idx = 2 if f2_dist < f1_dist else 1
            self._switch_subbank("filter_bank", 1 if f_idx == 2 else 0)

            now = time.monotonic()
            tap_id = ("filter_handle", f_idx)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                z_cut = self._get_zctrl(f"{{s}}_filter{f_idx}_cutoff")
                z_res = self._get_zctrl(f"{{s}}_filter{f_idx}_resonance")
                if z_cut: z_cut.reset_value()
                if z_res: z_res.reset_value()
                self.last_snapshot = None
                self._draw()
                return

            self.last_tap = (tap_id, now)
            self.drag_target = ("filter_xy", {
                "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                "cut_key": f"{{s}}_filter{f_idx}_cutoff",
                "res_key": f"{{s}}_filter{f_idx}_resonance",
            })
            self._apply_drag(event.x, event.y)
            return

        if kind == "env_graph":
            if self.env_bank in (1, 3, 4):
                self._switch_subbank("env_bank", 2 if "env2" in payload["prefix"] else 0)
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
                rkeys = [f"{{s}}_{pref}_attack"] if node == "A" else ([f"{{s}}_{pref}_decay", f"{{s}}_{pref}_sustain"] if node == "DS" else [f"{{s}}_{pref}_release"])
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
            pref = payload["prefix"]
            gx0, gw = payload["gx0"], payload["gw"]
            g_top, g_bot = payload["g_top"], payload["g_bot"]
            seg_w = max(10.0, gw * 0.28)
            node = payload["node"]
            if node == "A":
                self._set_norm(self._get_zctrl(f"{{s}}_{pref}_attack"), (x - gx0) / seg_w)
            elif node == "DS":
                self._set_norm(self._get_zctrl(f"{{s}}_{pref}_decay"), (x - payload["xa"]) / seg_w)
                if g_bot > g_top:
                    self._set_norm(self._get_zctrl(f"{{s}}_{pref}_sustain"), (g_bot - y) / (g_bot - g_top))
            elif node == "R":
                self._set_norm(self._get_zctrl(f"{{s}}_{pref}_release"), (x - payload["xs"]) / seg_w)

        self.last_snapshot = None
        self._draw()
