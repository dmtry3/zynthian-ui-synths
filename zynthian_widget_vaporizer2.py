#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Vaporizer2 Workstation Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces VAST Dynamics Vaporizer2's 755 raw LV2 parameters (~189 pages)
# with 6 dynamic workstation tabs mapped 1-to-1 to Zynthian's 4 physical
# encoders + one-tap ECO CPU tamer:
#   Macro | Osc | Filter | Env | LFO/Arp | FX   + ECO button
#
# Features:
# - Resilient controller resolver: matches Vaporizer2 LV2 zctrls by exact
#   symbol (e.g. m_fFilterCutoff_Filter1) and normalized name/label.
# - Preserves native LV2 physical ranges & scalePoints while adding smooth
#   logarithmic touch response for frequencies, envelope times, and rates.
# - Dynamic encoder binding: tapping any tab, sub-bank, oscillator, filter,
#   envelope, LFO/StepSeq/Arp, mod matrix slot, or FX bus/module immediately
#   rebinds Zynthian's 4 physical encoders.
# - Real-time interactive DSP visualizations:
#   * Macro: 4 vertical Custom Modulator faders + Master Vol/Glide + 16-slot
#     Modulation Matrix inspector with live transfer curve visualization.
#   * Osc: 4x 24-voice Wavetable banks (A-D) + Noise + Granular Sampler with
#     interactive 2D Wavetable/Morph/WTFX scope, Noise BPF pad & Grain pad.
#   * Filter: log-Hz 3-filter (F1/F2/F3) response graph across all 62 models
#     with family jump pills and 3 draggable 2D Cutoff/Resonance handles.
#   * Env: 5x MSEG interactive 2D ADSR graph with usage badges (VCA/VCF/LFO)
#     and automatic Tempo Sync step-mode switching.
#   * LFO/Arp: 5x LFO live waveform scope + 3x StepSeq + Arpeggiator pad.
#   * FX: 3 independent multiband FX busses (Mono Cut + Routing) x 13 modules
#     including interactive 8-band Graphic EQ and 2D Formant Vowel morph pad.
# - ECO toggle: caps Polyphony -> Poly4 and Unison -> 4 voices per osc bank
#   with one-tap restore of original preset settings for smooth Pi 5 playback.
# ******************************************************************************

import logging
import math
import re
import time
import tkinter

from zyngui import zynthian_gui_config
from zyngui import zynthian_widget_base

MULTI_INSTANCE = True
UPDATE_PERIOD = 0.06  # ~16 fps cap to keep CPU low on Pi 5
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

TABS = ["Macro", "Osc", "Filter", "Env", "LFO/Arp", "FX"]
TAB_ACCENTS = {
    "Macro":   "#4dabf7",  # blue
    "Osc":     "#cc5de8",  # violet
    "Filter":  "#ff922b",  # orange
    "Env":     "#51cf66",  # green
    "LFO/Arp": "#ffd43b",  # yellow
    "FX":      "#ff6b6b",  # coral
}
FILTER_COLS = ("#ff922b", "#38d9a9", "#4dabf7")

# ------------------------------------------------------------------------------
# Authentic Vaporizer2 Tables & Scales
# ------------------------------------------------------------------------------
OSC_SLOTS = [
    ("OscA",    "OSC A"),
    ("OscB",    "OSC B"),
    ("OscC",    "OSC C"),
    ("OscD",    "OSC D"),
    ("Noise",   "NOISE"),
    ("Sampler", "SMPLR"),
]

FILTER_FAMILIES = [
    ("DQF",    0,  9),
    ("DQF WS", 10, 16),
    ("Biquad", 17, 40),
    ("Ladder", 41, 48),
    ("SVF",    49, 57),
    ("Spec",   58, 61),
]

FILTER_TYPES = [
    "DQF LPF 12", "DQF LPF 24", "DQF BRF 12", "DQF BPF 12", "DQF HPF 12",
    "DQF LDF 6", "DQF LDF 12", "DQF LDF 18", "DQF LDF 24", "DQF COMB",
    "DQF LPF 12 WS", "DQF LPF 24 WS", "DQF BRF 12 WS", "DQF BPF 12 WS",
    "DQF HPF 12 WS", "DQF LDF 12 WS", "DQF COMB WS",
    "BQF LPF 6", "BQF HPF 6", "BQF BPF 6", "BQF AP 6", "BQF LS 6", "BQF HS 6", "BQF Notch 6", "BQF Peak 6",
    "BQF LPF 12", "BQF HPF 12", "BQF BPF 12", "BQF AP 12", "BQF LS 12", "BQF HS 12", "BQF Notch 12", "BQF Peak 12",
    "BQF LPF 18", "BQF HPF 18", "BQF BPF 18", "BQF AP 18", "BQF LS 18", "BQF HS 18", "BQF Notch 18", "BQF Peak 18",
    "LDF LPF 12", "LDF HPF 12", "LDF LPF 24", "LDF HPF 24", "LDF LPF 36", "LDF HPF 36", "LDF LPF 48", "LDF HPF 48",
    "SVF LPF 12", "SVF HPF 12", "SVF BPF 12", "SVF LPF 24", "SVF HPF 24", "SVF BPF 24", "SVF LPF 36", "SVF HPF 36", "SVF BPF 36",
    "COMB FILTER", "SCREAM", "KRG HPF 12", "KRG HPFSAT",
]

LFO_WAVES = ["Sine", "Saw", "Tri", "Pulse", "Noise", "SawSine", "S&H"]
POLARITY_NAMES = ["Unipolar", "Bipolar"]
SHAPER_TYPES = ["SoftClip", "HardClip", "Fold", "Sine"]
PREPOST_NAMES = ["Pre EQ", "Post EQ"]
VOWEL_NAMES = ["A", "E", "I", "O", "U"]

LFO_ARP_SLOTS = [
    ("lfo1", "LFO 1"),
    ("lfo2", "LFO 2"),
    ("lfo3", "LFO 3"),
    ("lfo4", "LFO 4"),
    ("lfo5", "LFO 5"),
    ("seq1", "SEQ 1"),
    ("seq2", "SEQ 2"),
    ("seq3", "SEQ 3"),
    ("arp",  "ARP"),
]

# 13 FX modules per FX Bus (Bus 1, Bus 2, Bus 3)
FX_MODULES = [
    ("eq",      "EQ",     "m_bEQOnOff"),
    ("dist",    "Dist",   "m_bDistortionOnOff"),
    ("shaper",  "Shape",  "m_bWaveshaperOnOff"),
    ("crush",   "Crush",  "m_bBitcrushOnOff"),
    ("comb",    "Comb",   "m_bCombOnOff"),
    ("formant", "Formt",  "m_bFormantOnOff"),
    ("dyn",     "Dyn",    "m_bLimiterOffOn"),
    ("chorus",  "Chorus", "m_bChorusOnOff"),
    ("phaser",  "Phaser", "m_bPhaserOnOff"),
    ("flanger", "Flang",  "m_bFlangerOnOff"),
    ("atom",    "Atom",   "m_bAtomizerOnOff"),
    ("delay",   "Delay",  "m_bDelayOnOff"),
    ("reverb",  "Reverb", "m_bReverbOnOff"),
]

EQ_BAND_LABELS = ["Low", "250", "500", "1k", "2k", "4k", "8k", "High"]

MOD_QUICK_SRCS = [
    ("LFO1",  9),
    ("LFO2",  10),
    ("MSEG1", 4),
    ("MSEG2", 5),
    ("Mac1",  17),
    ("ModW",  3),
    ("Vel",   1),
    ("KeyT",  21),
]
MOD_QUICK_DSTS = [
    ("F1 Cut", 86),
    ("F1 Res", 87),
    ("F2 Cut", 93),
    ("Pitch",  1),
    ("OA WT",  14),
    ("OA Mrp", 15),
    ("OA FX",  199),
    ("Gain",   2),
]

LOG_KEY_PATTERNS = (
    "cutoff", "lowcut", "highcut", "monofrequency", "lfofreq", "rate_hz",
    "minfrequency", "frequoffset", "fclow", "fchigh",
    "attacktime", "decaytime", "releasetime", "portamento",
    "delaytime", "predelay", "reverbfeedback", "stepseqspeed", "arpspeed",
)


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def _is_log_key(key):
    kl = str(key).lower()
    return any(p in kl for p in LOG_KEY_PATTERNS)


def _fx_key(base_sym, bus_idx):
    if bus_idx == 0:
        return base_sym
    return f"{base_sym}_bus{bus_idx + 1}"


def fmt_hz(hz):
    if hz >= 10000.0:
        return f"{hz / 1000.0:.1f}kHz"
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}kHz"
    if hz >= 100.0:
        return f"{hz:.0f}Hz"
    return f"{hz:.1f}Hz"


def fmt_lfo_hz(hz):
    if hz >= 100.0:
        return f"{hz:.0f}Hz"
    if hz >= 10.0:
        return f"{hz:.1f}Hz"
    return f"{hz:.2f}Hz"


def fmt_ms(ms):
    if ms < 0.5:
        return "0ms"
    if ms < 1000.0:
        return f"{ms:.0f}ms" if ms >= 10.0 else f"{ms:.1f}ms"
    s = ms / 1000.0
    return f"{s:.2f}s" if s < 10.0 else f"{s:.1f}s"


# ------------------------------------------------------------------------------
# Main Widget Class
# ------------------------------------------------------------------------------
class zynthian_widget_vaporizer2(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)

        self.next_update = 0.0
        self.active_tab = "Macro"

        # Per-tab sub-selection state (drives dynamic 4-encoder binding)
        self.macro_bank = 0      # 0: Macros 1-4, 1: Voicing, 2: Mod Matrix (Full Screen)
        self.mod_slot = 0        # 0..15 -> MOD 1..16
        self.mod_page = 0        # 0: Slots 1..8, 1: Slots 9..16
        self.osc_idx = 0         # 0..3: OscA..D, 4: Noise, 5: Sampler
        self.osc_bank = 0        # 0: WT/Morph, 1: Unison/Pitch, 2: Mix/Phase
        self.flt_idx = 0         # 0..2 -> Filter 1..3
        self.flt_bank = 0        # 0: Core, 1: Type & Env, 2: Gain & Route
        self.env_idx = 0         # 0..4 -> MSEG 1..5
        self.env_bank = 0        # 0: ADSR (ms), 1: Sync Steps
        self.lfo_slot = 0        # 0..8 -> LFO 1..5, SEQ 1..3, ARP
        self.fx_bus = 0          # 0..2 -> FX Bus 1..3
        self.fx_idx = 0          # 0..12 -> FX_MODULES
        self.eq_bank = 0         # 0: Bands 1,3,5,8, 1: Bands 2,4,6,7

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
    # Processor Setup, Resilient Lookup Index & Missing Enum Enhancement
    # --------------------------------------------------------------------------
    def set_processor(self, processor):
        super().set_processor(processor)
        if processor is None:
            return
        pid = id(processor)
        self._build_ctrl_index(processor)
        if pid not in self._enhanced_procs:
            self._enhanced_procs.add(pid)
            self._enhance_missing_enums()
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
                # Zynthian jalv prefixes lv2:Parameter URIs as "VASTvaporizer2_<param>"
                if k_sym.startswith("vastvaporizer2_"):
                    idx[k_sym[len("vastvaporizer2_"):]] = z
                elif "_m_" in k_sym:
                    idx[k_sym[k_sym.index("_m_") + 1:]] = z
            zname = getattr(z, "name", None)
            if zname:
                k_name = _norm_key(zname)
                if k_name and k_name not in idx:
                    idx[k_name] = z
        self._ctrl_index = idx

    def _get_zctrl(self, sym):
        if not self.processor or not sym:
            return None
        return self._ctrl_index.get(_norm_key(sym))

    @staticmethod
    def _apply_native_enum(z, labels):
        """Attach labels/ticks using native integer values (0..N-1) if missing."""
        if z is None or getattr(z, "labels", None):
            return
        try:
            cur_val = float(z.get_value())
        except Exception:
            cur_val = 0.0
        ticks = [float(i) for i in range(len(labels))]
        z.labels = list(labels)
        z.ticks = ticks
        z.is_toggle = (len(labels) == 2)
        z.is_integer = True
        z.value_min = 0.0
        z.value_max = float(len(labels) - 1)
        z.value_range = z.value_max
        z.value_mid = z.value_max * 0.5
        z.range_reversed = False
        z.label2value = {str(l): t for l, t in zip(labels, ticks)}
        z.value2label = {str(t): l for l, t in zip(labels, ticks)}
        z.value = max(0.0, min(z.value_max, round(cur_val)))

    def _enhance_missing_enums(self):
        for i in range(1, 6):
            self._apply_native_enum(self._get_zctrl(f"m_uLFOPolarity_LFO{i}"), POLARITY_NAMES)
            self._apply_native_enum(self._get_zctrl(f"m_uMSEGPolarity_MSEG{i}"), POLARITY_NAMES)
        for i in range(1, 17):
            self._apply_native_enum(self._get_zctrl(f"m_uModMatPolarity{i}"), POLARITY_NAMES)
        for b in range(3):
            self._apply_native_enum(self._get_zctrl(_fx_key("m_uPhaserLFOWave", b)), LFO_WAVES)
            self._apply_native_enum(self._get_zctrl(_fx_key("m_uFlangerLFOWave", b)), LFO_WAVES)
            self._apply_native_enum(self._get_zctrl(_fx_key("m_uAtomizerLFOWave", b)), LFO_WAVES)
            self._apply_native_enum(self._get_zctrl(_fx_key("m_uWaveshaperType", b)), SHAPER_TYPES)
            self._apply_native_enum(self._get_zctrl(_fx_key("m_uWaveshaperPrePostEq", b)), PREPOST_NAMES)
            self._apply_native_enum(self._get_zctrl(_fx_key("m_fFormantVowelOne", b)), VOWEL_NAMES)
            self._apply_native_enum(self._get_zctrl(_fx_key("m_fFormantVowelTwo", b)), VOWEL_NAMES)

    # --------------------------------------------------------------------------
    # Dynamic Page Definitions (1 Page per Tab -> 4 Physical Encoders)
    # --------------------------------------------------------------------------
    def _tab_items(self, tab_name):
        if tab_name == "Macro":
            if self.macro_bank == 0:
                return [
                    ("m_fCustomModulator1", "Macro 1"),
                    ("m_fCustomModulator2", "Macro 2"),
                    ("m_fCustomModulator3", "Macro 3"),
                    ("m_fCustomModulator4", "Macro 4"),
                ]
            if self.macro_bank == 1:
                return [
                    ("m_fMasterVolumedB", "Mstr Vol"),
                    ("m_fPortamento",     "Glide"),
                    ("m_fPitchMod",       "PitchMod"),
                    ("m_fVoiceGain",      "Vce Gain"),
                ]
            ms = self.mod_slot + 1
            return [
                (f"m_uModMatSrce{ms}",  f"M{ms} Src"),
                (f"m_uModMatDest{ms}",  f"M{ms} Dst"),
                (f"m_fModMatVal{ms}",   f"M{ms} Amt"),
                (f"m_fModMatCurve{ms}", f"M{ms} Crv"),
            ]

        if tab_name == "Osc":
            if self.osc_idx == 4:  # Noise
                if self.osc_bank == 0:
                    return [
                        ("m_fNoiseGain",      "Nse Gain"),
                        ("m_fNoiseLowCut",    "Nse LoC"),
                        ("m_fNoiseHighCut",   "Nse HiC"),
                        ("m_fNoiseResonance", "Nse Reso"),
                    ]
                return [
                    ("m_uNoiseType",     "Nse Type"),
                    ("m_fNoisePan",      "Nse Pan"),
                    ("m_uVCAEnv_Noise",  "Nse Env"),
                    ("m_uNoiseRouting1", "Nse Rte1"),
                ]
            if self.osc_idx == 5:  # Sampler
                if self.osc_bank == 0:
                    return [
                        ("m_fSamplerGain",            "Smp Gain"),
                        ("m_fSamplerCents",           "Smp Tune"),
                        ("m_fSamplerGrainInteronset", "Grn Time"),
                        ("m_fSamplerGrainShape",      "Grn Shp"),
                    ]
                return [
                    ("m_fSamplerGrainRandom", "Grn Rnd"),
                    ("m_fSamplerLoopRange",   "Loop Rng"),
                    ("m_uSamplerRootKey",     "Root Key"),
                    ("m_fSamplerPan",         "Smp Pan"),
                ]
            tag = OSC_SLOTS[self.osc_idx][0]  # OscA..OscD
            short = f"O{tag[-1]}"
            if self.osc_bank == 0:
                return [
                    (f"m_fOscWTPos_{tag}",  f"{short} WTPos"),
                    (f"m_fOscMorph_{tag}",  f"{short} Morph"),
                    (f"m_uWTFX_{tag}",      f"{short} WTFX"),
                    (f"m_fWTFXVal_{tag}",   f"{short} FXVal"),
                ]
            if self.osc_bank == 1:
                return [
                    (f"m_iNumOscs_{tag}",   f"{short} UniV"),
                    (f"m_fOscDetune_{tag}", f"{short} Detn"),
                    (f"m_fSpread_{tag}",    f"{short} Sprd"),
                    (f"m_fOscCents_{tag}",  f"{short} Tune"),
                ]
            return [
                (f"m_fOscGain_{tag}",  f"{short} Gain"),
                (f"m_fOscPan_{tag}",   f"{short} Pan"),
                (f"m_iOscOct_{tag}",   f"{short} Oct"),
                (f"m_fOscPhase_{tag}", f"{short} Phs"),
            ]

        if tab_name == "Filter":
            fi = self.flt_idx + 1
            if self.flt_bank == 0:
                return [
                    (f"m_fFilterCutoff_Filter{fi}", f"F{fi} Cut"),
                    (f"m_fFilterReso_Filter{fi}",   f"F{fi} Reso"),
                    (f"m_fFilterDrive_Filter{fi}",  f"F{fi} Drv"),
                    (f"m_fFilterDryWet_Filter{fi}", f"F{fi} Mix"),
                ]
            if self.flt_bank == 1:
                return [
                    (f"m_uFilterType_Filter{fi}",   f"F{fi} Type"),
                    (f"m_uVCFEnv_Filter{fi}",       f"F{fi} Env"),
                    (f"m_fVCFEnvMod_Filter{fi}",    f"F{fi} EMod"),
                    (f"m_fFilterScale_Filter{fi}",  f"F{fi} Scal"),
                ]
            return [
                (f"m_fFilterGain_Filter{fi}",     f"F{fi} Gain"),
                (f"m_uFilterRouting_Filter{fi}",  f"F{fi} Rte1"),
                (f"m_uFilterRouting2_Filter{fi}", f"F{fi} Rte2"),
                (f"m_bOnOff_Filter{fi}",          f"F{fi} On"),
            ]

        if tab_name == "Env":
            ei = self.env_idx + 1
            if self.env_bank == 0:
                return [
                    (f"m_fAttackTime_MSEG{ei}",   f"E{ei} Att"),
                    (f"m_fDecayTime_MSEG{ei}",    f"E{ei} Dec"),
                    (f"m_fSustainLevel_MSEG{ei}", f"E{ei} Sus"),
                    (f"m_fReleaseTime_MSEG{ei}",  f"E{ei} Rel"),
                ]
            return [
                (f"m_uMSEGTimeBeats_MSEG{ei}", f"E{ei} Beat"),
                (f"m_fAttackSteps_MSEG{ei}",   f"E{ei} AStep"),
                (f"m_fDecaySteps_MSEG{ei}",    f"E{ei} DStep"),
                (f"m_fReleaseSteps_MSEG{ei}",  f"E{ei} RStep"),
            ]

        if tab_name == "LFO/Arp":
            slot_id = LFO_ARP_SLOTS[self.lfo_slot][0]
            if slot_id.startswith("lfo"):
                li = int(slot_id[3:])
                sync_on = self._raw(self._get_zctrl(f"m_bLFOSynch_LFO{li}")) >= 0.5
                rate_k = f"m_uLFOTimeBeats_LFO{li}" if sync_on else f"m_fLFOFreq_LFO{li}"
                return [
                    (f"m_uLFOWave_LFO{li}",  f"L{li} Wave"),
                    (rate_k,                 f"L{li} Rate"),
                    (f"m_fLFORamp_LFO{li}",  f"L{li} Ramp"),
                    (f"m_fLFOPhase_LFO{li}", f"L{li} Phs"),
                ]
            if slot_id.startswith("seq"):
                si = int(slot_id[3:])
                sync_on = self._raw(self._get_zctrl(f"m_bStepSeqSynch_STEPSEQ{si}")) >= 0.5
                spd_k = f"m_uStepSeqTimeBeats_STEPSEQ{si}" if sync_on else f"m_fStepSeqSpeed_STEPSEQ{si}"
                return [
                    (spd_k,                       f"S{si} Spd"),
                    (f"m_fGlide_STEPSEQ{si}",     f"S{si} Glde"),
                    (f"m_fGate_STEPSEQ{si}",      f"S{si} Gate"),
                    (f"m_bStepSeqSynch_STEPSEQ{si}", f"S{si} Sync"),
                ]
            # ARP
            sync_on = self._raw(self._get_zctrl("m_bARPSynch")) >= 0.5
            spd_k = "m_uARPTimeBeats" if sync_on else "m_fARPSpeed"
            return [
                ("m_uARPMode",  "Arp Mode"),
                (spd_k,         "Arp Rate"),
                ("m_bARPSynch", "Arp Sync"),
                ("m_bARPOnOff", "Arp On"),
            ]

        # FX tab (Bus 1..3 x 13 modules)
        b = self.fx_bus
        fx_id = FX_MODULES[self.fx_idx][0]
        if fx_id == "eq":
            if self.eq_bank == 0:
                return [
                    (_fx_key("m_fEQ1", b), "EQ Low"),
                    (_fx_key("m_fEQ3", b), "EQ 500"),
                    (_fx_key("m_fEQ5", b), "EQ 2k"),
                    (_fx_key("m_fEQ8", b), "EQ High"),
                ]
            return [
                (_fx_key("m_fEQ2", b), "EQ 250"),
                (_fx_key("m_fEQ4", b), "EQ 1k"),
                (_fx_key("m_fEQ6", b), "EQ 4k"),
                (_fx_key("m_fEQ7", b), "EQ 8k"),
            ]
        if fx_id == "dist":
            return [
                (_fx_key("m_fDistDryWet", b), "Dst Mix"),
                (_fx_key("m_fDistDrive", b),  "Dst Drv"),
                (_fx_key("m_fDistFuzz", b),   "Dst Fuzz"),
                (_fx_key("m_fDistLowcut", b), "Dst LoC"),
            ]
        if fx_id == "shaper":
            return [
                (_fx_key("m_fWaveshaperDryWet", b), "Shp Mix"),
                (_fx_key("m_uWaveshaperType", b),   "Shp Type"),
                (_fx_key("m_fWaveshaperDrive", b),  "Shp Drv"),
                (_fx_key("m_fWaveshaperPreGain", b),"Shp Pre"),
            ]
        if fx_id == "crush":
            return [
                (_fx_key("m_fBitcrushDryWet", b),   "Crs Mix"),
                (_fx_key("m_fBitcrushBitdepth", b), "Crs Bits"),
                (_fx_key("m_fBitcrushBitrate", b),  "Crs Rate"),
                (_fx_key("m_fBitcrushJitter", b),   "Crs Jitt"),
            ]
        if fx_id == "comb":
            return [
                (_fx_key("m_fCombDryWet", b),      "Cmb Mix"),
                (_fx_key("m_fCombFrequOffset", b), "Cmb Freq"),
                (_fx_key("m_fCombDrive", b),       "Cmb Drv"),
                (_fx_key("m_fCombLevel", b),       "Cmb Lvl"),
            ]
        if fx_id == "formant":
            return [
                (_fx_key("m_fFormantDryWet", b),   "Frm Mix"),
                (_fx_key("m_fFormantVowelOne", b), "Vowel 1"),
                (_fx_key("m_fFormantVowelTwo", b), "Vowel 2"),
                (_fx_key("m_fFormantVowelMix", b), "Vwl Mix"),
            ]
        if fx_id == "dyn":
            return [
                (_fx_key("m_fLimiterThreshold", b),  "Lim Thr"),
                (_fx_key("m_fLimiterRatio", b),      "Lim Rat"),
                (_fx_key("m_fLimiterMakeupGain", b), "Lim Gain"),
                (_fx_key("m_fMBCompGainMB", b),      "Cmp Mid"),
            ]
        if fx_id == "chorus":
            sync = self._raw(self._get_zctrl(_fx_key("m_bChorusSynch", b))) >= 0.5
            rt = _fx_key("m_uChorusTimeBeats" if sync else "m_fChorusRate_hz", b)
            return [
                (_fx_key("m_fChorusDryWet", b), "Chr Mix"),
                (_fx_key("m_fChorusDepth", b),  "Chr Dpth"),
                (rt,                            "Chr Rate"),
                (_fx_key("m_fChorusGain", b),   "Chr Gain"),
            ]
        if fx_id == "phaser":
            sync = self._raw(self._get_zctrl(_fx_key("m_bPhaserSynch", b))) >= 0.5
            rt = _fx_key("m_uPhaserTimeBeats" if sync else "m_fPhaserLFOFreq", b)
            return [
                (_fx_key("m_fPhaserDryWet", b),   "Phs Mix"),
                (_fx_key("m_fPhaserWidth", b),    "Phs Wdth"),
                (_fx_key("m_fPhaserFeedback", b), "Phs FB"),
                (rt,                              "Phs Rate"),
            ]
        if fx_id == "flanger":
            sync = self._raw(self._get_zctrl(_fx_key("m_bFlangerSynch", b))) >= 0.5
            rt = _fx_key("m_uFlangerTimeBeats" if sync else "m_fFlangerLFOFreq", b)
            return [
                (_fx_key("m_fFlangerDryWet", b),   "Flg Mix"),
                (_fx_key("m_fFlangerDelay", b),    "Flg Dly"),
                (_fx_key("m_fFlangerFeedback", b), "Flg FB"),
                (rt,                               "Flg Rate"),
            ]
        if fx_id == "atom":
            sync = self._raw(self._get_zctrl(_fx_key("m_bAtomizerSynch", b))) >= 0.5
            rt = _fx_key("m_uAtomizerTimeBeats" if sync else "m_fAtomizerLFOFreq", b)
            return [
                (_fx_key("m_fAtomizerDryWet", b),    "Atm Mix"),
                (_fx_key("m_fAtomizerHarmonics", b), "Atm Harm"),
                (_fx_key("m_fAtomizerEmphasis", b),  "Atm Emph"),
                (rt,                                 "Atm Rate"),
            ]
        if fx_id == "delay":
            sync = self._raw(self._get_zctrl(_fx_key("m_bDelaySynch", b))) >= 0.5
            tm = _fx_key("m_uDelayTimeBeats" if sync else "m_fDelayTime", b)
            return [
                (_fx_key("m_fDelayWet", b),      "Dly Mix"),
                (tm,                             "Dly Time"),
                (_fx_key("m_fDelayFeedback", b), "Dly FB"),
                (_fx_key("m_fDelayLowcut", b),   "Dly LoC"),
            ]
        # reverb
        return [
            (_fx_key("m_fReverbDryWet", b),   "Vrb Mix"),
            (_fx_key("m_fReverbSize", b),     "Vrb Size"),
            (_fx_key("m_fReverbFeedback", b), "Vrb Dec"),
            (_fx_key("m_fReverbDamping", b),  "Vrb Damp"),
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
            logging.debug(f"Vaporizer2 widget: live swap error => {e}")

    def _sync_zyngui_list(self, target_tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page_by_title(target_tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Vaporizer2 widget: sync list error => {e}")

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
    # Native-Range & Logarithmic Value Helpers
    # --------------------------------------------------------------------------
    @staticmethod
    def _raw(zctrl, default=0.0):
        if zctrl is None:
            return default
        try:
            return float(zctrl.get_value())
        except Exception:
            return default

    @staticmethod
    def _norm(zctrl, default=0.0, log_scale=False):
        if zctrl is None:
            return default
        try:
            ticks = getattr(zctrl, "ticks", None)
            if ticks and len(ticks) > 1:
                idx = zctrl.get_value2index()
                if idx is not None:
                    return max(0.0, min(1.0, idx / float(len(ticks) - 1)))
            v = float(zctrl.get_value())
            vmin = float(zctrl.value_min)
            vmax = float(zctrl.value_max)
            if vmax <= vmin:
                return default
            v = max(vmin, min(vmax, v))
            if log_scale:
                if vmin > 0.0:
                    return max(0.0, min(1.0, math.log(v / vmin) / math.log(vmax / vmin)))
                return max(0.0, min(1.0, (v / vmax) ** (1.0 / 3.0)))
            return max(0.0, min(1.0, (v - vmin) / (vmax - vmin)))
        except Exception:
            return default

    @staticmethod
    def _set_norm(zctrl, norm_val, log_scale=False):
        if zctrl is None:
            return
        n = max(0.0, min(1.0, float(norm_val)))
        ticks = getattr(zctrl, "ticks", None)
        if ticks and len(ticks) > 1:
            idx = int(round(n * (len(ticks) - 1)))
            zctrl.set_value(ticks[idx], send=True)
            return
        vmin = float(zctrl.value_min)
        vmax = float(zctrl.value_max)
        if vmax <= vmin:
            return
        if log_scale:
            if vmin > 0.0:
                val = vmin * ((vmax / vmin) ** n)
            else:
                val = vmax * (n ** 3.0)
        else:
            val = vmin + n * (vmax - vmin)
        if getattr(zctrl, "is_integer", False):
            val = round(val)
        zctrl.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _cycle_enum(zctrl, step=1):
        if zctrl is None:
            return
        ticks = getattr(zctrl, "ticks", None)
        if ticks and len(ticks) > 0:
            idx = zctrl.get_value2index() or 0
            new_idx = (idx + step) % len(ticks)
            zctrl.set_value(ticks[new_idx], send=True)
            return
        vmin = float(zctrl.value_min)
        vmax = float(zctrl.value_max)
        if vmax - vmin <= 1.01:
            cur = float(zctrl.get_value())
            zctrl.set_value(vmin if cur >= (vmin + vmax) * 0.5 else vmax, send=True)

    @staticmethod
    def _enum_idx(zctrl, default=0):
        if zctrl is None:
            return default
        try:
            idx = zctrl.get_value2index()
            if idx is not None:
                return int(idx)
            return int(round(float(zctrl.get_value())))
        except Exception:
            return default

    @staticmethod
    def _fmt(zctrl, key=""):
        if zctrl is None:
            return "--"
        try:
            if getattr(zctrl, "labels", None):
                return str(zctrl.get_value2label())
        except Exception:
            pass
        v = zynthian_widget_vaporizer2._raw(zctrl)
        kl = str(key).lower()
        if any(p in kl for p in ("cutoff", "lowcut", "highcut", "monofrequency", "minfrequency", "frequoffset", "fclow", "fchigh", "mastertune")):
            return fmt_hz(v)
        if "lfofreq" in kl or "rate_hz" in kl:
            return fmt_lfo_hz(v)
        if any(p in kl for p in ("attacktime", "decaytime", "releasetime", "portamento", "delaytime", "predelay", "reverbfeedback", "stepseqspeed", "arpspeed", "flangerdelay", "limiterattack", "limiterrelease", "mbcompattack", "mbcomprelease", "graininteronset")):
            return fmt_ms(v)
        if any(p in kl for p in ("volumedb", "drive", "threshold", "makeupgain")) or re.search(r"eq[1-8]", kl) or "gainlb" in kl or "gainmb" in kl or "gainhb" in kl:
            return f"{v:+.1f}dB"
        if "cents" in kl:
            if abs(v) >= 100.0:
                return f"{v / 100.0:+.1f}st"
            return f"{v:+.0f}c"
        if "pan" in kl:
            if abs(v) < 1.0:
                return "Center"
            return f"{int(round(-v))}L" if v < 0 else f"{int(round(v))}R"
        if "bitdepth" in kl:
            return f"{v:.1f}b"
        if "ratio" in kl:
            return f"{v:.0f}:1"
        if "steps" in kl or "ramp" in kl:
            return f"{v:.1f}"
        if float(zctrl.value_min) < 0.0:
            return f"{int(round(v)):+d}%"
        return f"{int(round(v))}%"

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
            ms = self.mod_slot + 1
            keys = [
                "m_fCustomModulator1", "m_fCustomModulator2",
                "m_fCustomModulator3", "m_fCustomModulator4",
                "m_fMasterVolumedB", "m_fPortamento", "m_fMasterTune",
                "m_fPitchMod", "m_fVoiceGain", "m_uPolyMode", "m_bLegatoMode",
                f"m_uModMatSrce{ms}", f"m_uModMatDest{ms}",
                f"m_fModMatVal{ms}", f"m_fModMatCurve{ms}", f"m_uModMatPolarity{ms}",
            ]
            for i in range(1, 17):
                keys.append(f"m_uModMatSrce{i}")
            return keys
        if t == "Osc":
            keys = [
                "m_bOscOnOff_OscA", "m_bOscOnOff_OscB", "m_bOscOnOff_OscC",
                "m_bOscOnOff_OscD", "m_bNoiseOnOff", "m_bSamplerOnOff",
            ]
            if self.osc_idx == 4:
                keys.extend([
                    "m_uNoiseType", "m_fNoiseGain", "m_fNoisePan", "m_fNoiseResonance",
                    "m_fNoiseLowCut", "m_fNoiseHighCut", "m_uVCAEnv_Noise",
                    "m_uNoiseRouting1", "m_uNoiseRouting2",
                ])
            elif self.osc_idx == 5:
                keys.extend([
                    "m_fSamplerGain", "m_fSamplerCents", "m_fSamplerPan",
                    "m_bSamplerKeytrack", "m_uSamplerRootKey", "m_bSamplerLoop",
                    "m_bSamplerLoopOnly", "m_bSamplerLoopPingpong", "m_fSamplerLoopRange",
                    "m_bSamplerPoly", "m_uVCAEnv_Sampler", "m_uSamplerRouting1",
                    "m_fSamplerGrainInteronset", "m_fSamplerGrainRandom", "m_fSamplerGrainShape",
                ])
            else:
                tag = OSC_SLOTS[self.osc_idx][0]
                keys.extend([
                    f"m_fOscWTPos_{tag}", f"m_fOscMorph_{tag}", f"m_uWTFX_{tag}",
                    f"m_fWTFXVal_{tag}", f"m_iNumOscs_{tag}", f"m_fOscDetune_{tag}",
                    f"m_fSpread_{tag}", f"m_fOscCents_{tag}", f"m_fOscGain_{tag}",
                    f"m_fOscPan_{tag}", f"m_iOscOct_{tag}", f"m_fOscPhase_{tag}",
                    f"m_bExciterOnOff_{tag}", f"m_bOscInverterOnOff_{tag}",
                    f"m_bOscRetrigOnOff_{tag}", f"m_uVCAEnv_{tag}",
                    f"m_uOscRouting1_{tag}", f"m_uOscRouting2_{tag}",
                ])
            return keys
        if t == "Filter":
            keys = []
            for fi in (1, 2, 3):
                keys.extend([
                    f"m_bOnOff_Filter{fi}", f"m_uFilterType_Filter{fi}",
                    f"m_fFilterCutoff_Filter{fi}", f"m_fFilterReso_Filter{fi}",
                    f"m_fFilterDrive_Filter{fi}", f"m_fFilterDryWet_Filter{fi}",
                    f"m_uVCFEnv_Filter{fi}", f"m_fVCFEnvMod_Filter{fi}",
                    f"m_fFilterScale_Filter{fi}", f"m_fFilterGain_Filter{fi}",
                    f"m_uFilterRouting_Filter{fi}", f"m_uFilterRouting2_Filter{fi}",
                ])
            return keys
        if t == "Env":
            ei = self.env_idx + 1
            return [
                f"m_uMSEGPolarity_MSEG{ei}", f"m_fAttackTime_MSEG{ei}",
                f"m_fDecayTime_MSEG{ei}", f"m_fSustainLevel_MSEG{ei}",
                f"m_fReleaseTime_MSEG{ei}", f"m_bMSEGPerVoice_MSEG{ei}",
                f"m_bMSEGSynch_MSEG{ei}", f"m_uMSEGTimeBeats_MSEG{ei}",
                f"m_fAttackSteps_MSEG{ei}", f"m_fDecaySteps_MSEG{ei}",
                f"m_fReleaseSteps_MSEG{ei}",
                "m_uVCAEnv_OscA", "m_uVCAEnv_OscB", "m_uVCFEnv_Filter1", "m_uVCFEnv_Filter2",
            ]
        if t == "LFO/Arp":
            slot_id = LFO_ARP_SLOTS[self.lfo_slot][0]
            if slot_id.startswith("lfo"):
                li = int(slot_id[3:])
                return [
                    f"m_fLFOFreq_LFO{li}", f"m_uLFOWave_LFO{li}", f"m_uLFOPolarity_LFO{li}",
                    f"m_fLFORamp_LFO{li}", f"m_fLFOPhase_LFO{li}", f"m_bLFOPerVoice_LFO{li}",
                    f"m_bLFORetrigOnOff_LFO{li}", f"m_bLFOSynch_LFO{li}",
                    f"m_uLFOTimeBeats_LFO{li}", f"m_uLFOMSEG_LFO{li}",
                ]
            if slot_id.startswith("seq"):
                si = int(slot_id[3:])
                return [
                    f"m_fStepSeqSpeed_STEPSEQ{si}", f"m_fGlide_STEPSEQ{si}",
                    f"m_fGate_STEPSEQ{si}", f"m_bStepSeqSynch_STEPSEQ{si}",
                    f"m_uStepSeqTimeBeats_STEPSEQ{si}",
                ]
            return ["m_bARPOnOff", "m_uARPMode", "m_fARPSpeed", "m_bARPSynch", "m_uARPTimeBeats"]
        # FX
        b = self.fx_bus
        keys = [_fx_key(on_k, b) for _, _, on_k in FX_MODULES]
        keys.extend([
            _fx_key("m_fMBMonoFrequency", b), _fx_key("m_uFxBusRouting", b),
            _fx_key("m_bMBCompOffOn", b), _fx_key("m_uLimiterMode", b),
            _fx_key("m_uDelayMode", b), _fx_key("m_bDelaySynch", b),
            _fx_key("m_uReverbMode", b), _fx_key("m_bChorusSynch", b),
            _fx_key("m_bPhaserSynch", b), _fx_key("m_bFlangerSynch", b),
            _fx_key("m_bAtomizerSynch", b), _fx_key("m_uWaveshaperPrePostEq", b),
        ])
        for k, _ in self._tab_items("FX"):
            keys.append(k)
        if FX_MODULES[self.fx_idx][0] == "eq":
            for i in range(1, 9):
                keys.append(_fx_key(f"m_fEQ{i}", b))
        return keys

    def _state_snapshot(self):
        vals = tuple(round(self._raw(self._get_zctrl(k)), 3) for k in self._watched_keys())
        return (
            self.width, self.height, self.active_tab, self.eco_on,
            self.macro_bank, self.mod_slot, self.mod_page, self.osc_idx, self.osc_bank,
            self.flt_idx, self.flt_bank, self.env_idx, self.env_bank,
            self.lfo_slot, self.fx_bus, self.fx_idx, self.eq_bank,
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
    # Drawing Primitives (Unified UI Synths Style)
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
        if subtext is not None:
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.28, text=text,
                          fill=COL_DIM if not active else "#1a1c22", font=self._font(self._fs(0.76)))
            c.create_text((x0 + x1) / 2, y0 + (y1 - y0) * 0.72, text=subtext,
                          fill=accent if not active else "#000000", font=self._font(self._fs(0.90), bold=True))
        else:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                          fill=fg, font=self._font(self._fs(0.92), bold=True))
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
                font=self._font(self._fs(0.86), bold=act),
            )
            self.hitboxes.append((bx0, y0, bx1, y1, bank_kind, i))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent, bank_kind=None, bank_idx=None, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        is_log = _is_log_key(key)
        norm = self._norm(z, log_scale=is_log)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 6
        tx0, tx1 = x0 + pad, x1 - pad
        bar_h = max(7, min(11, int((y1 - y0) * 0.28)))
        by1 = y1 - 4
        by0 = by1 - bar_h
        lbl_y = y0 + (by0 - y0) / 2

        c.create_text(tx0, lbl_y, text=label, anchor="w", fill=COL_DIM, font=self._font(self._fs(0.82)))
        c.create_text(tx1, lbl_y, text=self._fmt(z, key)[:11], anchor="e", fill=COL_TEXT,
                      font=self._font(self._fs(0.88), bold=True))

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
            {"key": key, "tx0": tx0, "tx1": tx1, "log": is_log, "bank_kind": bank_kind, "bank_idx": bank_idx},
        ))

    def _draw_vfader(self, x0, y0, x1, y1, key, label, accent, bank_kind=None, bank_idx=None, bipolar=False):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        is_log = _is_log_key(key)
        norm = self._norm(z, log_scale=is_log)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 5
        lbl_h = 16
        val_h = 15
        tx0, tx1 = x0 + pad, x1 - pad
        ty0 = y0 + lbl_h + 2
        ty1 = y1 - val_h - 3

        c.create_text((x0 + x1) / 2, y0 + lbl_h / 2 + 1, text=label,
                      fill=COL_TEXT, font=self._font(self._fs(0.80), bold=True))
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

        c.create_text((x0 + x1) / 2, y1 - val_h / 2 - 1, text=self._fmt(z, key)[:8],
                      fill=COL_DIM, font=self._font(self._fs(0.74)))

        self.hitboxes.append((
            x0, y0, x1, y1, "vfader",
            {"key": key, "ty0": ty0, "ty1": ty1, "log": is_log, "bank_kind": bank_kind, "bank_idx": bank_idx},
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
        elif self.active_tab == "LFO/Arp":
            self._draw_tab_lfo_arp(bx0, by0, bx1, by1)
        elif self.active_tab == "FX":
            self._draw_tab_fx(bx0, by0, bx1, by1)

    def _draw_header(self, x0, y0, x1, y1):
        c = self.widget_canvas
        total_w = x1 - x0
        eco_w = max(58, int(total_w * 0.11))
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
                font=self._font(self._fs(0.94), bold=True),
            )
            self.hitboxes.append((cx, y0, cx + tw, y1, "tab", tname))
            cx += tw + gap

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
    # TAB 1: MACRO, VOICING & FULL-SCREEN 16-SLOT MOD MATRIX
    # --------------------------------------------------------------------------
    def _draw_tab_macro(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Macro"]
        gap = 6

        # Count active mod slots for header badge
        active_mods = sum(
            1 for i in range(1, 17)
            if self._enum_idx(self._get_zctrl(f"m_uModMatSrce{i}"), 0) > 0
        )
        mm_lbl = f"Mod Matrix ({active_mods})" if active_mods > 0 else "Mod Matrix"

        # Row 1: Encoder Bank Selector (left 58%) + Poly / Legato / Tune pills (right 42%)
        r1_h = 36
        left_w = int((x1 - x0) * 0.58)
        self._draw_bank_bar(
            x0, y0, x0 + left_w, y0 + r1_h,
            ["Macros 1-4", "Voicing", mm_lbl],
            self.macro_bank, accent, "macro_bank",
        )

        rx0 = x0 + left_w + gap
        pw = (x1 - rx0 - 2 * gap) / 3
        z_poly = self._get_zctrl("m_uPolyMode")
        z_leg = self._get_zctrl("m_bLegatoMode")
        z_tune = self._get_zctrl("m_fMasterTune")
        self._draw_pill(rx0, y0, rx0 + pw, y0 + r1_h, "Poly", False, accent,
                        "cycle", "m_uPolyMode", subtext=self._fmt(z_poly)[:7])
        leg_on = self._raw(z_leg) >= 0.5
        self._draw_pill(rx0 + pw + gap, y0, rx0 + 2 * pw + gap, y0 + r1_h, "Legato",
                        leg_on, "#51cf66", "cycle", "m_bLegatoMode", subtext="ON" if leg_on else "OFF")
        self._draw_pill(rx0 + 2 * (pw + gap), y0, x1, y0 + r1_h, "Tune", False, accent,
                        "macro_bank", 1, subtext=self._fmt(z_tune, "m_fMasterTune")[:7])

        my0 = y0 + r1_h + gap

        if self.macro_bank == 2:
            self._draw_mod_matrix_full(x0, my0, x1, y1, accent)
            return

        # Spacious Full-Width Macros 1-4 + Master Vol + Glide Faders
        perf_h = 46
        my1 = y1 - perf_h - gap
        act_m = (self.macro_bank == 0)
        c.create_rectangle(x0, my0, x1, my1, fill=COL_BG,
                           outline=accent if act_m else COL_BORDER, width=2 if act_m else 1)
        ipad = 5
        fw = (x1 - x0 - 2 * ipad - 5 * gap) / 6
        for i in range(4):
            fx0 = x0 + ipad + i * (fw + gap)
            self._draw_vfader(
                fx0, my0 + ipad, fx0 + fw, my1 - ipad,
                f"m_fCustomModulator{i + 1}", f"MACRO {i + 1}",
                accent if act_m else "#376996",
                bank_kind="macro_bank", bank_idx=0,
            )
        fx_gl = x0 + ipad + 4 * (fw + gap)
        self._draw_vfader(
            fx_gl, my0 + ipad, fx_gl + fw, my1 - ipad,
            "m_fPortamento", "GLIDE",
            "#ffd43b" if self.macro_bank == 1 else "#7a6a2a",
            bank_kind="macro_bank", bank_idx=1,
        )
        fx_vol = x0 + ipad + 5 * (fw + gap)
        self._draw_vfader(
            fx_vol, my0 + ipad, x1 - ipad, my1 - ipad,
            "m_fMasterVolumedB", "VOLUME",
            "#51cf66" if self.macro_bank == 1 else "#2e6b3a",
            bank_kind="macro_bank", bank_idx=1, bipolar=True,
        )

        # Bottom: Voicing Performance Strip
        py0 = my1 + gap
        act_v = (self.macro_bank == 1)
        c.create_rectangle(x0, py0, x1, y1, fill=COL_BG,
                           outline=accent if act_v else COL_BORDER, width=2 if act_v else 1)
        v_items = [
            ("m_fMasterVolumedB", "Master",   True),
            ("m_fPortamento",     "Glide",    False),
            ("m_fPitchMod",       "PitchMod", True),
            ("m_fVoiceGain",      "VceGain",  False),
        ]
        vw = (x1 - x0 - 3 * gap) / 4
        for i, (key, lbl, bip) in enumerate(v_items):
            px0 = x0 + i * (vw + gap)
            self._draw_param_box(px0, py0 + 2, px0 + vw, y1 - 2, key, lbl,
                                 accent if act_v else "#376996",
                                 bank_kind="macro_bank", bank_idx=1, bipolar=bip)

    def _draw_mod_matrix_full(self, x0, y0, x1, y1, accent):
        c = self.widget_canvas
        gap = 6
        ms = self.mod_slot + 1
        src_k = f"m_uModMatSrce{ms}"
        dst_k = f"m_uModMatDest{ms}"
        val_k = f"m_fModMatVal{ms}"
        crv_k = f"m_fModMatCurve{ms}"
        pol_k = f"m_uModMatPolarity{ms}"

        src_z = self._get_zctrl(src_k)
        dst_z = self._get_zctrl(dst_k)
        val_z = self._get_zctrl(val_k)
        crv_z = self._get_zctrl(crv_k)
        pol_z = self._get_zctrl(pol_k)

        # Row 2: Page toggle (1-8 / 9-16) + 8 Large Slot Buttons
        r2_h = 38
        pg_w = 68
        self._draw_pill(x0, y0, x0 + pg_w, y0 + r2_h,
                        "9–16" if self.mod_page else "1–8",
                        True, "#38d9a9", "mod_page", 1 - self.mod_page)

        sx_start = x0 + pg_w + gap
        sw = (x1 - sx_start - 7 * 4) / 8
        base_idx = self.mod_page * 8
        for col in range(8):
            idx = base_idx + col
            sx0 = sx_start + col * (sw + 4)
            is_sel = (idx == self.mod_slot)
            sz = self._get_zctrl(f"m_uModMatSrce{idx + 1}")
            s_idx = self._enum_idx(sz, 0)
            has_mod = (s_idx > 0)
            sub = self._fmt(sz)[:6] if has_mod else None
            self._draw_pill(sx0, y0, sx0 + sw, y0 + r2_h,
                            f"● M{idx + 1}" if has_mod else f"M{idx + 1}",
                            is_sel, accent, "mod_slot", idx, subtext=sub)

        # Row 3: Big Touch SOURCE (< | Name | >) + Uni/Bi + CLR + DEST (< | Name | >)
        r3_y0 = y0 + r2_h + gap
        r3_h = 44
        mid_w = 114
        side_w = (x1 - x0 - mid_w - 2 * gap) / 2
        arr_w = 36

        # SOURCE stepper
        self._draw_pill(x0, r3_y0, x0 + arr_w, r3_y0 + r3_h, "◀", False, accent, "mod_step", (src_k, -1))
        self._draw_pill(x0 + arr_w + 3, r3_y0, x0 + side_w - arr_w - 3, r3_y0 + r3_h,
                        f"SRC (M{ms})", False, accent, "mod_step", (src_k, 1),
                        subtext=self._fmt(src_z)[:14])
        self._draw_pill(x0 + side_w - arr_w, r3_y0, x0 + side_w, r3_y0 + r3_h, "▶", False, accent, "mod_step", (src_k, 1))

        # Center: Uni/Bi + CLR
        mx0 = x0 + side_w + gap
        half_m = (mid_w - 4) / 2
        pol_txt = "Bi ±" if self._enum_idx(pol_z, 1) == 1 else "Uni +"
        self._draw_pill(mx0, r3_y0, mx0 + half_m, r3_y0 + r3_h, pol_txt, False, "#ffd43b", "cycle", pol_k)
        self._draw_pill(mx0 + half_m + 4, r3_y0, mx0 + mid_w, r3_y0 + r3_h, "CLR", False, "#ff6b6b", "mod_clear", ms)

        # DEST stepper
        dx0 = mx0 + mid_w + gap
        self._draw_pill(dx0, r3_y0, dx0 + arr_w, r3_y0 + r3_h, "◀", False, "#cc5de8", "mod_step", (dst_k, -1))
        self._draw_pill(dx0 + arr_w + 3, r3_y0, x1 - arr_w - 3, r3_y0 + r3_h,
                        "DESTINATION", False, "#cc5de8", "mod_step", (dst_k, 1),
                        subtext=self._fmt(dst_z)[:15])
        self._draw_pill(x1 - arr_w, r3_y0, x1, r3_y0 + r3_h, "▶", False, "#cc5de8", "mod_step", (dst_k, 1))

        # Row 4a: Quick Sources (8 one-tap pills)
        q1_y0 = r3_y0 + r3_h + gap
        q_h = 34
        cur_src = self._enum_idx(src_z, 0)
        qw = (x1 - x0 - 7 * 4) / 8
        for i, (qlbl, qidx) in enumerate(MOD_QUICK_SRCS):
            qx0 = x0 + i * (qw + 4)
            self._draw_pill(qx0, q1_y0, qx0 + qw, q1_y0 + q_h, qlbl,
                            cur_src == qidx, accent, "mod_quick", (src_k, qidx, val_k))

        # Row 4b: Quick Destinations (8 one-tap pills)
        q2_y0 = q1_y0 + q_h + 4
        cur_dst = self._enum_idx(dst_z, 0)
        for i, (qlbl, qidx) in enumerate(MOD_QUICK_DSTS):
            qx0 = x0 + i * (qw + 4)
            self._draw_pill(qx0, q2_y0, qx0 + qw, q2_y0 + q_h, qlbl,
                            cur_dst == qidx, "#cc5de8", "mod_quick", (dst_k, qidx, val_k))

        # Row 5: Transfer Curve Graph (left 34%) + Large Depth & Curve Sliders (right 66%)
        cg_y0 = q2_y0 + q_h + gap
        cg_y1 = y1
        cg_w = max(90, int((x1 - x0) * 0.34))
        cg_x1 = x0 + cg_w
        c.create_rectangle(x0, cg_y0, cg_x1, cg_y1, fill=COL_PANEL, outline=accent, width=1)
        amt = (self._norm(val_z, 0.5) - 0.5) * 2.0
        crv = (self._norm(crv_z, 0.5) - 0.5) * 2.0
        mid_cy = (cg_y0 + cg_y1) / 2
        c.create_line(x0 + 6, mid_cy, cg_x1 - 6, mid_cy, fill=COL_GRID, dash=(2, 3))
        pts = []
        p_exp = 2.0 ** (crv * 2.2)
        for i in range(33):
            t = i / 32.0
            y_val = (t ** p_exp) * amt
            px = x0 + 8 + t * (cg_w - 16)
            py = mid_cy - y_val * ((cg_y1 - cg_y0) * 0.42)
            pts.extend([px, py])
        c.create_line(pts, fill=accent if abs(amt) > 0.01 else COL_DIM, width=2.6)

        sl_x0 = cg_x1 + gap
        sl_h = (cg_y1 - cg_y0 - 4) / 2
        self._draw_param_box(sl_x0, cg_y0, x1, cg_y0 + sl_h, val_k, f"M{ms} Depth", accent,
                             bank_kind="macro_bank", bank_idx=2, bipolar=True)
        self._draw_param_box(sl_x0, cg_y0 + sl_h + 4, x1, cg_y1, crv_k, f"M{ms} Curve", accent,
                             bank_kind="macro_bank", bank_idx=2, bipolar=True)

    # --------------------------------------------------------------------------
    # TAB 2: OSCILLATORS (OSC A..D + NOISE + GRANULAR SAMPLER)
    # --------------------------------------------------------------------------
    def _draw_tab_osc(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Osc"]
        gap = 6

        # Row 1: 6 Generator Selectors (OSC A..D, NOISE, SMPLR)
        r1_h = 36
        sw = (x1 - x0 - 5 * gap) / 6
        on_keys = [
            "m_bOscOnOff_OscA", "m_bOscOnOff_OscB", "m_bOscOnOff_OscC",
            "m_bOscOnOff_OscD", "m_bNoiseOnOff", "m_bSamplerOnOff",
        ]
        for i, (_, lbl) in enumerate(OSC_SLOTS):
            ox0 = x0 + i * (sw + gap)
            is_on = self._raw(self._get_zctrl(on_keys[i])) >= 0.5
            txt = f"● {lbl}" if is_on else lbl
            self._draw_pill(ox0, y0, ox0 + sw, y0 + r1_h, txt,
                            i == self.osc_idx, accent, "osc_idx", i)

        # Row 2: Encoder Bank Selector + Power Toggle
        r2_y0 = y0 + r1_h + gap
        r2_h = 34
        pwr_w = 96
        cur_on_k = on_keys[self.osc_idx]
        cur_on = self._raw(self._get_zctrl(cur_on_k)) >= 0.5
        self._draw_pill(x0, r2_y0, x0 + pwr_w, r2_y0 + r2_h,
                        "ACTIVE ●" if cur_on else "OFF",
                        cur_on, "#51cf66", "cycle", cur_on_k)

        if self.osc_idx == 4:
            banks = ["Noise Filter", "Noise Route"]
        elif self.osc_idx == 5:
            banks = ["Grain & Mix", "Loop & Key"]
        else:
            banks = ["WT & Morph", "Unison & Pitch", "Mix & Phase"]
        self._draw_bank_bar(
            x0 + pwr_w + gap, r2_y0, x1, r2_y0 + r2_h,
            banks, min(self.osc_bank, len(banks) - 1), accent, "osc_bank",
        )

        # Row 3: Interactive Scope/Pad (left 58%) + Quick Routing & Mode Pills (right 42%)
        mid_y0 = r2_y0 + r2_h + gap
        bot_h = 92
        mid_y1 = y1 - bot_h - gap
        mid_h = max(60, mid_y1 - mid_y0)

        scope_w = int((x1 - x0) * 0.58)
        sx1 = x0 + scope_w
        c.create_rectangle(x0, mid_y0, sx1, mid_y1, fill=COL_PANEL,
                           outline=accent if cur_on else COL_BORDER, width=1)

        if self.osc_idx < 4:
            self._draw_osc_wt_scope(x0, mid_y0, sx1, mid_y1, OSC_SLOTS[self.osc_idx][0], accent if cur_on else COL_DIM)
        elif self.osc_idx == 4:
            self._draw_noise_pad(x0, mid_y0, sx1, mid_y1, accent if cur_on else COL_DIM)
        else:
            self._draw_sampler_grain_pad(x0, mid_y0, sx1, mid_y1, accent if cur_on else COL_DIM)

        # Right Quick Controls
        rx0 = sx1 + gap
        if self.osc_idx < 4:
            tag = OSC_SLOTS[self.osc_idx][0]
            rh = (mid_h - 2 * 4) / 3
            hw = (x1 - rx0 - gap) / 2
            # Row 3a: Route 1 + Route 2
            self._draw_pill(rx0, mid_y0, rx0 + hw, mid_y0 + rh, "Route 1", False, accent,
                            "cycle", f"m_uOscRouting1_{tag}", subtext=self._fmt(self._get_zctrl(f"m_uOscRouting1_{tag}"))[:8])
            self._draw_pill(rx0 + hw + gap, mid_y0, x1, mid_y0 + rh, "Route 2", False, accent,
                            "cycle", f"m_uOscRouting2_{tag}", subtext=self._fmt(self._get_zctrl(f"m_uOscRouting2_{tag}"))[:8])
            # Row 3b: WT FX Type + VCA Env
            ry1 = mid_y0 + rh + 4
            self._draw_pill(rx0, ry1, rx0 + hw, ry1 + rh, "WT FX", False, accent,
                            "cycle", f"m_uWTFX_{tag}", subtext=self._fmt(self._get_zctrl(f"m_uWTFX_{tag}"))[:10])
            self._draw_pill(rx0 + hw + gap, ry1, x1, ry1 + rh, "VCA Env", False, "#51cf66",
                            "cycle", f"m_uVCAEnv_{tag}", subtext=self._fmt(self._get_zctrl(f"m_uVCAEnv_{tag}"))[:8])
            # Row 3c: Retrig + Exciter + Invert
            ry2 = ry1 + rh + 4
            tw3 = (x1 - rx0 - 2 * 4) / 3
            for j, (lbl, k) in enumerate((
                ("Retrig", f"m_bOscRetrigOnOff_{tag}"),
                ("Excit",  f"m_bExciterOnOff_{tag}"),
                ("Invrt",  f"m_bOscInverterOnOff_{tag}"),
            )):
                px = rx0 + j * (tw3 + 4)
                on = self._raw(self._get_zctrl(k)) >= 0.5
                self._draw_pill(px, ry2, px + tw3, mid_y1, lbl, on, accent, "cycle", k)
        elif self.osc_idx == 4:
            rh = (mid_h - 4) / 2
            hw = (x1 - rx0 - gap) / 2
            self._draw_pill(rx0, mid_y0, rx0 + hw, mid_y0 + rh, "Noise Type", False, accent,
                            "cycle", "m_uNoiseType", subtext=self._fmt(self._get_zctrl("m_uNoiseType")))
            self._draw_pill(rx0 + hw + gap, mid_y0, x1, mid_y0 + rh, "VCA Env", False, "#51cf66",
                            "cycle", "m_uVCAEnv_Noise", subtext=self._fmt(self._get_zctrl("m_uVCAEnv_Noise")))
            ry1 = mid_y0 + rh + 4
            self._draw_pill(rx0, ry1, rx0 + hw, mid_y1, "Route 1", False, accent,
                            "cycle", "m_uNoiseRouting1", subtext=self._fmt(self._get_zctrl("m_uNoiseRouting1"))[:8])
            self._draw_pill(rx0 + hw + gap, ry1, x1, mid_y1, "Route 2", False, accent,
                            "cycle", "m_uNoiseRouting2", subtext=self._fmt(self._get_zctrl("m_uNoiseRouting2"))[:8])
        else:
            rh = (mid_h - 2 * 4) / 3
            hw = (x1 - rx0 - gap) / 2
            self._draw_pill(rx0, mid_y0, rx0 + hw, mid_y0 + rh, "Route 1", False, accent,
                            "cycle", "m_uSamplerRouting1", subtext=self._fmt(self._get_zctrl("m_uSamplerRouting1"))[:8])
            self._draw_pill(rx0 + hw + gap, mid_y0, x1, mid_y0 + rh, "VCA Env", False, "#51cf66",
                            "cycle", "m_uVCAEnv_Sampler", subtext=self._fmt(self._get_zctrl("m_uVCAEnv_Sampler"))[:8])
            ry1 = mid_y0 + rh + 4
            for j, (lbl, k) in enumerate((("Loop", "m_bSamplerLoop"), ("PingPng", "m_bSamplerLoopPingpong"))):
                px = rx0 + j * (hw + gap)
                on = self._raw(self._get_zctrl(k)) >= 0.5
                self._draw_pill(px, ry1, px + hw, ry1 + rh, lbl, on, accent, "cycle", k)
            ry2 = ry1 + rh + 4
            for j, (lbl, k) in enumerate((("KeyTrk", "m_bSamplerKeytrack"), ("Poly", "m_bSamplerPoly"))):
                px = rx0 + j * (hw + gap)
                on = self._raw(self._get_zctrl(k)) >= 0.5
                self._draw_pill(px, ry2, px + hw, mid_y1, lbl, on, accent, "cycle", k)

        # Row 4: 2x2 Parameter Cards matching the 4 bound encoders
        py0 = mid_y1 + gap
        items = self._tab_items("Osc")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - 4) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + 4)
            bip = ("cents" in key.lower()) or ("pan" in key.lower()) or ("oct" in key.lower())
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent, bipolar=bip)

    def _draw_osc_wt_scope(self, x0, y0, x1, y1, tag, color):
        c = self.widget_canvas
        pad = 10
        gx0, gx1 = x0 + pad, x1 - pad
        gy0, gy1 = y0 + pad + 14, y1 - pad
        gw, gh = max(10, gx1 - gx0), max(10, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2

        wt_pos = self._norm(self._get_zctrl(f"m_fOscWTPos_{tag}"))
        morph = self._norm(self._get_zctrl(f"m_fOscMorph_{tag}"))
        wtfx_idx = self._enum_idx(self._get_zctrl(f"m_uWTFX_{tag}"), 0)
        wtfx_val = self._norm(self._get_zctrl(f"m_fWTFXVal_{tag}"))
        unison = max(1, int(round(self._raw(self._get_zctrl(f"m_iNumOscs_{tag}"), 1.0))))
        detune = self._norm(self._get_zctrl(f"m_fOscDetune_{tag}"))

        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))
        c.create_text(gx0, y0 + 9, text=f"{tag}  WT:{int(wt_pos*100)}%  Morph:{int(morph*100)}%  Uni:{unison}v",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.76), bold=True))

        # Draw unison ghost waves + primary wave
        layers = min(5, unison)
        for li in range(layers - 1, -1, -1):
            off = 0.0 if li == 0 else ((li % 2 * 2 - 1) * ((li + 1) // 2) * detune * 0.12)
            pts = []
            for i in range(65):
                t = i / 64.0
                ph = (t * 2.0 * math.pi) + off * 4.0
                # Blend harmonics based on wt_pos and morph
                w_base = math.sin(ph) * (1.0 - wt_pos * 0.5)
                w_harm = (
                    0.55 * math.sin(2.0 * ph + morph * math.pi) * wt_pos
                    + 0.30 * math.sin(3.0 * ph) * (wt_pos * 0.7 + morph * 0.3)
                    + 0.18 * math.sin(5.0 * ph + morph * 2.0) * morph
                )
                y = w_base + w_harm
                # Apply approximate WT FX visual distortion
                if wtfx_idx > 0 and wtfx_val > 0.02:
                    if wtfx_idx in (1, 2, 3):  # Bend
                        y = math.sin(ph + wtfx_val * 1.8 * math.sin(ph))
                    elif wtfx_idx in (7, 26):  # Dist / Crush
                        y = math.tanh(y * (1.0 + wtfx_val * 5.0))
                        if wtfx_idx == 26:
                            steps = max(2.0, 12.0 * (1.0 - wtfx_val * 0.85))
                            y = round(y * steps) / steps
                    elif wtfx_idx in (8, 9, 10, 12, 13, 14):  # Sync / FM
                        y = math.sin(ph * (1.0 + wtfx_val * 3.0) + wtfx_val * 2.0 * math.sin(2.0 * ph))
                    elif wtfx_idx == 11:  # PWM
                        y = 1.0 if ((t + wtfx_val * 0.45) % 1.0) < 0.5 else -1.0
                y = max(-1.0, min(1.0, y))
                pts.extend([gx0 + t * gw, mid_y - y * (gh * 0.44)])
            c.create_line(pts, fill=color if li == 0 else "#4a3358", width=2.4 if li == 0 else 1.1)

        # Draggable 2D handle: X = WT Pos, Y = Morph
        hx = gx0 + wt_pos * gw
        hy = gy1 - morph * gh
        c.create_oval(hx - 7, hy - 7, hx + 7, hy + 7, fill=color, outline="#ffffff", width=2)
        self.hitboxes.append((
            x0, y0, x1, y1, "xy_pad",
            {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
             "x_key": f"m_fOscWTPos_{tag}", "y_key": f"m_fOscMorph_{tag}",
             "bank_kind": "osc_bank", "bank_idx": 0},
        ))

    def _draw_noise_pad(self, x0, y0, x1, y1, color):
        c = self.widget_canvas
        pad = 12
        gx0, gx1 = x0 + pad, x1 - pad
        gy0, gy1 = y0 + pad + 14, y1 - pad
        gw, gh = max(10, gx1 - gx0), max(10, gy1 - gy0)
        lo = self._norm(self._get_zctrl("m_fNoiseLowCut"), log_scale=True)
        hi = self._norm(self._get_zctrl("m_fNoiseHighCut"), log_scale=True)
        reso = self._norm(self._get_zctrl("m_fNoiseResonance"))

        c.create_text(gx0, y0 + 9, text="Noise Bandpass  X: LowCut  Y: HighCut",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.76), bold=True))
        bx0 = gx0 + min(lo, hi) * gw
        bx1 = gx0 + max(lo, hi) * gw
        c.create_rectangle(bx0, gy0 + (1.0 - reso) * gh * 0.4, bx1, gy1,
                           fill="#342240", outline=color, width=2)
        hx = gx0 + lo * gw
        hy = gy1 - hi * gh
        c.create_oval(hx - 7, hy - 7, hx + 7, hy + 7, fill=color, outline="#ffffff", width=2)
        self.hitboxes.append((
            x0, y0, x1, y1, "xy_pad",
            {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
             "x_key": "m_fNoiseLowCut", "y_key": "m_fNoiseHighCut",
             "bank_kind": "osc_bank", "bank_idx": 0},
        ))

    def _draw_sampler_grain_pad(self, x0, y0, x1, y1, color):
        c = self.widget_canvas
        pad = 12
        gx0, gx1 = x0 + pad, x1 - pad
        gy0, gy1 = y0 + pad + 14, y1 - pad
        gw, gh = max(10, gx1 - gx0), max(10, gy1 - gy0)
        onset = self._norm(self._get_zctrl("m_fSamplerGrainInteronset"), log_scale=True)
        shape = self._norm(self._get_zctrl("m_fSamplerGrainShape"))
        rnd = self._norm(self._get_zctrl("m_fSamplerGrainRandom"))

        c.create_text(gx0, y0 + 9, text="Granular Cloud  X: Inter-Onset  Y: Shape",
                      anchor="w", fill=COL_DIM, font=self._font(self._fs(0.76), bold=True))
        hx = gx0 + onset * gw
        hy = gy1 - shape * gh
        rad = 10 + rnd * 28
        c.create_oval(hx - rad, hy - rad, hx + rad, hy + rad, outline=color, dash=(3, 3), width=1.5)
        c.create_oval(hx - 7, hy - 7, hx + 7, hy + 7, fill=color, outline="#ffffff", width=2)
        self.hitboxes.append((
            x0, y0, x1, y1, "xy_pad",
            {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
             "x_key": "m_fSamplerGrainInteronset", "y_key": "m_fSamplerGrainShape",
             "bank_kind": "osc_bank", "bank_idx": 0},
        ))

    # --------------------------------------------------------------------------
    # TAB 3: FILTER (TRIPLE FILTER RESPONSE GRAPH + 62 MODELS + 3x 2D HANDLES)
    # --------------------------------------------------------------------------
    def _draw_tab_filter(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Filter"]
        gap = 6

        # Row 1: Filter 1 / Filter 2 / Filter 3 + Encoder Bank Bar
        r1_h = 34
        left_w = int((x1 - x0) * 0.42)
        fw = (left_w - 2 * gap) / 3
        for i in range(3):
            fx0 = x0 + i * (fw + gap)
            is_on = self._raw(self._get_zctrl(f"m_bOnOff_Filter{i + 1}")) >= 0.5
            lbl = f"● F{i + 1}" if is_on else f"F{i + 1}"
            self._draw_pill(fx0, y0, fx0 + fw, y0 + r1_h, lbl,
                            i == self.flt_idx, FILTER_COLS[i], "flt_idx", i)

        self._draw_bank_bar(
            x0 + left_w + gap, y0, x1, y0 + r1_h,
            ["Core", "Type & Env", "Gain & Route"],
            self.flt_bank, FILTER_COLS[self.flt_idx], "flt_bank",
        )

        # Row 2: 6 Filter Family Jump Pills + Power Toggle
        r2_y0 = y0 + r1_h + gap
        r2_h = 34
        fi = self.flt_idx + 1
        f_on = self._raw(self._get_zctrl(f"m_bOnOff_Filter{fi}")) >= 0.5
        cur_type = self._enum_idx(self._get_zctrl(f"m_uFilterType_Filter{fi}"), 0)

        pwr_w = 78
        self._draw_pill(x0, r2_y0, x0 + pwr_w, r2_y0 + r2_h,
                        f"F{fi} ON" if f_on else f"F{fi} OFF",
                        f_on, "#51cf66", "cycle", f"m_bOnOff_Filter{fi}")

        fam_x0 = x0 + pwr_w + gap
        fam_w = (x1 - fam_x0 - (len(FILTER_FAMILIES) - 1) * 4) / len(FILTER_FAMILIES)
        for idx, (fname, lo_i, hi_i) in enumerate(FILTER_FAMILIES):
            bx0 = fam_x0 + idx * (fam_w + 4)
            act = (lo_i <= cur_type <= hi_i)
            self._draw_pill(bx0, r2_y0, bx0 + fam_w, r2_y0 + r2_h, fname,
                            act, FILTER_COLS[self.flt_idx], "flt_family", idx)

        # Row 3: Interactive Log-Hz Filter Response Graph (F1, F2, F3)
        gy0 = r2_y0 + r2_h + gap
        bot_h = 92
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=FILTER_COLS[self.flt_idx], width=1)
        self._draw_filter_graph(x0, gy0, x1, gy1)

        # Row 4: 2x2 Parameter Cards bound to 4 encoders
        py0 = gy1 + gap
        items = self._tab_items("Filter")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - 4) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + 4)
            bip = ("drive" in key.lower()) or ("envmod" in key.lower())
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl,
                                 FILTER_COLS[self.flt_idx], bipolar=bip)

    def _draw_filter_graph(self, x0, y0, x1, y1):
        c = self.widget_canvas
        pad_x, pad_t, pad_b = 12, 22, 16
        gx0, gx1 = x0 + pad_x, x1 - pad_x
        gy0, gy1 = y0 + pad_t, y1 - pad_b
        gw, gh = max(10, gx1 - gx0), max(10, gy1 - gy0)
        base_y = gy0 + gh * 0.56

        # Log frequency grid (50Hz, 200Hz, 1kHz, 5kHz, 20kHz)
        for hz, lbl in ((50, "50"), (200, "200"), (1000, "1k"), (5000, "5k"), (20000, "20k")):
            t = math.log(hz / 20.0) / math.log(28000.0 / 20.0)
            lx = gx0 + t * gw
            c.create_line(lx, gy0, lx, gy1, fill=COL_GRID, dash=(2, 4))
            c.create_text(lx, gy1 + 8, text=lbl, fill=COL_DIM, font=self._font(self._fs(0.70)))
        c.create_line(gx0, base_y, gx1, base_y, fill=COL_GRID)

        # Active filter model header
        fi = self.flt_idx + 1
        t_idx = self._enum_idx(self._get_zctrl(f"m_uFilterType_Filter{fi}"), 0)
        t_name = FILTER_TYPES[t_idx] if 0 <= t_idx < len(FILTER_TYPES) else f"Type {t_idx}"
        cut_str = self._fmt(self._get_zctrl(f"m_fFilterCutoff_Filter{fi}"), f"m_fFilterCutoff_Filter{fi}")
        res_str = self._fmt(self._get_zctrl(f"m_fFilterReso_Filter{fi}"), f"m_fFilterReso_Filter{fi}")
        c.create_text(gx0, y0 + 11, text=f"F{fi}: {t_name}  |  Cut: {cut_str}  Res: {res_str}",
                      anchor="w", fill=FILTER_COLS[self.flt_idx], font=self._font(self._fs(0.80), bold=True))

        states = []
        for idx in range(3):
            fn = idx + 1
            on = self._raw(self._get_zctrl(f"m_bOnOff_Filter{fn}")) >= 0.5
            cut_n = self._norm(self._get_zctrl(f"m_fFilterCutoff_Filter{fn}"), 0.8, log_scale=True)
            res_n = self._norm(self._get_zctrl(f"m_fFilterReso_Filter{fn}"), 0.0)
            ftype = self._enum_idx(self._get_zctrl(f"m_uFilterType_Filter{fn}"), 0)
            states.append((idx, cut_n, res_n, ftype, on))
            if not on and idx != self.flt_idx:
                continue

            fname = FILTER_TYPES[ftype] if 0 <= ftype < len(FILTER_TYPES) else "LPF"
            is_hpf = ("HPF" in fname)
            is_bpf = ("BPF" in fname)
            is_notch = ("BRF" in fname or "Notch" in fname)
            is_comb = ("COMB" in fname)
            slope = 3.5 if ("24" in fname or "36" in fname or "48" in fname or "LDF" in fname) else 2.2

            pts = []
            for i in range(65):
                t = i / 64.0
                d = (t - cut_n) * 10.0
                if is_comb:
                    resp = 0.25 * math.sin((t - cut_n) * 32.0) * (0.4 + res_n * 0.9)
                elif is_hpf:
                    resp = -max(0.0, -d) * slope * 0.14 + res_n * 0.45 * math.exp(-(d * 1.6) ** 2)
                elif is_bpf:
                    resp = -abs(d) * slope * 0.16 + res_n * 0.40 * math.exp(-(d * 1.8) ** 2)
                elif is_notch:
                    resp = -0.65 * math.exp(-(d * (1.2 + res_n * 2.5)) ** 2)
                else:  # LPF / Scream / Shelf
                    resp = -max(0.0, d) * slope * 0.14 + res_n * 0.48 * math.exp(-(d * 1.6) ** 2)
                py = max(gy0 + 2, min(gy1 - 2, base_y - resp * (gh * 0.72)))
                pts.extend([gx0 + t * gw, py])

            col = FILTER_COLS[idx] if on else COL_DIM
            c.create_line(pts, fill=col, width=2.6 if idx == self.flt_idx else 1.5)

            # 2D Handle
            hx = gx0 + cut_n * gw
            hy = gy1 - res_n * gh
            r = 8 if idx == self.flt_idx else 6
            c.create_oval(hx - r, hy - r, hx + r, hy + r,
                          fill=col, outline="#ffffff" if idx == self.flt_idx else COL_BG, width=2)
            c.create_text(hx, hy - r - 7, text=f"F{fn}", fill=col, font=self._font(self._fs(0.72), bold=True))

        self.hitboxes.append((
            x0, y0, x1, y1, "filter_xy",
            {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1, "states": states},
        ))

    # --------------------------------------------------------------------------
    # TAB 4: ENVELOPES (MSEG 1..5 + INTERACTIVE 2D ADSR + SYNC STEPS)
    # --------------------------------------------------------------------------
    def _draw_tab_env(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Env"]
        gap = 6

        # Detect which MSEGs are used as VCA/VCF
        usage = {i: [] for i in range(5)}
        for osc_tag in ("OscA", "OscB"):
            u = self._enum_idx(self._get_zctrl(f"m_uVCAEnv_{osc_tag}"), -1)
            if 0 <= u < 5 and "VCA" not in usage[u]:
                usage[u].append("VCA")
        for fn in (1, 2):
            u = self._enum_idx(self._get_zctrl(f"m_uVCFEnv_Filter{fn}"), -1)
            if 0 <= u < 5 and "VCF" not in usage[u]:
                usage[u].append("VCF")

        # Row 1: MSEG 1..5 Selector
        r1_h = 36
        ew = (x1 - x0 - 4 * gap) / 5
        for i in range(5):
            ex0 = x0 + i * (ew + gap)
            sub = "/".join(usage[i]) if usage[i] else None
            self._draw_pill(ex0, y0, ex0 + ew, y0 + r1_h, f"MSEG {i + 1}",
                            i == self.env_idx, accent, "env_idx", i, subtext=sub)

        # Row 2: Mode Pills (Per-Voice, Polarity, Sync) + Bank Selector
        r2_y0 = y0 + r1_h + gap
        r2_h = 34
        ei = self.env_idx + 1
        pv_on = self._raw(self._get_zctrl(f"m_bMSEGPerVoice_MSEG{ei}")) >= 0.5
        sync_on = self._raw(self._get_zctrl(f"m_bMSEGSynch_MSEG{ei}")) >= 0.5
        pol_txt = "Bi" if self._enum_idx(self._get_zctrl(f"m_uMSEGPolarity_MSEG{ei}"), 0) == 1 else "Uni"

        left_w = int((x1 - x0) * 0.52)
        pw = (left_w - 2 * gap) / 3
        self._draw_pill(x0, r2_y0, x0 + pw, r2_y0 + r2_h, "PerVoice", pv_on, accent,
                        "cycle", f"m_bMSEGPerVoice_MSEG{ei}")
        self._draw_pill(x0 + pw + gap, r2_y0, x0 + 2 * pw + gap, r2_y0 + r2_h, f"Pol: {pol_txt}", False, accent,
                        "cycle", f"m_uMSEGPolarity_MSEG{ei}")
        self._draw_pill(x0 + 2 * (pw + gap), r2_y0, x0 + left_w, r2_y0 + r2_h,
                        "Sync: ON" if sync_on else "Sync: OFF", sync_on, "#ffd43b",
                        "env_sync_toggle", f"m_bMSEGSynch_MSEG{ei}")

        self._draw_bank_bar(
            x0 + left_w + gap, r2_y0, x1, r2_y0 + r2_h,
            ["ADSR (ms)", "Sync Steps"], self.env_bank, accent, "env_bank",
        )

        # Row 3: Interactive 2D ADSR Envelope Graph
        gy0 = r2_y0 + r2_h + gap
        bot_h = 92
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad_x, pad_t, pad_b = 16, 20, 14
        gx0, gx1 = x0 + pad_x, x1 - pad_x
        g_top, g_bot = gy0 + pad_t, gy1 - pad_b
        gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)

        a_n = self._norm(self._get_zctrl(f"m_fAttackTime_MSEG{ei}"), log_scale=True)
        d_n = self._norm(self._get_zctrl(f"m_fDecayTime_MSEG{ei}"), log_scale=True)
        s_n = self._norm(self._get_zctrl(f"m_fSustainLevel_MSEG{ei}"))
        r_n = self._norm(self._get_zctrl(f"m_fReleaseTime_MSEG{ei}"), log_scale=True)

        seg_w = gw * 0.28
        xa = gx0 + max(4.0, a_n * seg_w)
        xd = xa + max(4.0, d_n * seg_w)
        xs = xd + gw * 0.16
        xr = min(gx1, xs + max(4.0, r_n * seg_w))
        ys = g_bot - s_n * gh

        c.create_line(gx0, g_bot, gx1, g_bot, fill=COL_GRID)
        c.create_line(gx0, g_top, gx1, g_top, fill=COL_GRID, dash=(2, 4))
        c.create_polygon(
            [gx0, g_bot, xa, g_top, xd, ys, xs, ys, xr, g_bot],
            fill="#1e3624", outline="",
        )
        c.create_line(
            [gx0, g_bot, xa, g_top, xd, ys, xs, ys, xr, g_bot],
            fill=accent, width=2.8,
        )

        # Draggable Nodes: A, D/S, R
        for nx, ny, lbl in ((xa, g_top, "A"), (xd, ys, "D/S"), (xr, g_bot, "R")):
            c.create_oval(nx - 8, ny - 8, nx + 8, ny + 8, fill=accent, outline="#ffffff", width=2)
            c.create_text(nx, ny - 14 if ny > g_top + 16 else ny + 15, text=lbl,
                          fill=COL_TEXT, font=self._font(self._fs(0.76), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "env_graph",
            {"ei": ei, "gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
             "xa": xa, "xd": xd, "xs": xs, "xr": xr, "ys": ys},
        ))

        # Row 4: 2x2 Parameter Cards bound to 4 encoders
        py0 = gy1 + gap
        items = self._tab_items("Env")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - 4) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + 4)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent)

    # --------------------------------------------------------------------------
    # TAB 5: LFO (1..5), STEP SEQUENCER (1..3) & ARPEGGIATOR
    # --------------------------------------------------------------------------
    def _draw_tab_lfo_arp(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["LFO/Arp"]
        gap = 4

        # Row 1: 9-Slot Selector (LFO 1..5, SEQ 1..3, ARP)
        r1_h = 34
        sw = (x1 - x0 - (len(LFO_ARP_SLOTS) - 1) * gap) / len(LFO_ARP_SLOTS)
        for i, (sid, lbl) in enumerate(LFO_ARP_SLOTS):
            sx0 = x0 + i * (sw + gap)
            act = (i == self.lfo_slot)
            if sid == "arp" and self._raw(self._get_zctrl("m_bARPOnOff")) >= 0.5:
                lbl = "● ARP"
            self._draw_pill(sx0, y0, sx0 + sw, y0 + r1_h, lbl, act, accent, "lfo_slot", i)

        slot_id = LFO_ARP_SLOTS[self.lfo_slot][0]
        r2_y0 = y0 + r1_h + 6
        r2_h = 34
        bot_h = 92
        gy0 = r2_y0 + r2_h + 6
        gy1 = y1 - bot_h - 6

        if slot_id.startswith("lfo"):
            li = int(slot_id[3:])
            sync_on = self._raw(self._get_zctrl(f"m_bLFOSynch_LFO{li}")) >= 0.5
            pv_on = self._raw(self._get_zctrl(f"m_bLFOPerVoice_LFO{li}")) >= 0.5
            rt_on = self._raw(self._get_zctrl(f"m_bLFORetrigOnOff_LFO{li}")) >= 0.5
            pol_txt = "Bi" if self._enum_idx(self._get_zctrl(f"m_uLFOPolarity_LFO{li}"), 1) == 1 else "Uni"
            mseg_txt = self._fmt(self._get_zctrl(f"m_uLFOMSEG_LFO{li}"))

            # Row 2: LFO Toggle Pills
            pw = (x1 - x0 - 4 * 6) / 5
            pills = [
                ("Sync: Beats" if sync_on else "Sync: Hz", sync_on, f"m_bLFOSynch_LFO{li}"),
                ("PerVoice", pv_on, f"m_bLFOPerVoice_LFO{li}"),
                ("Retrig", rt_on, f"m_bLFORetrigOnOff_LFO{li}"),
                (f"Pol: {pol_txt}", False, f"m_uLFOPolarity_LFO{li}"),
                (f"Env: {mseg_txt}", mseg_txt != "--", f"m_uLFOMSEG_LFO{li}"),
            ]
            for i, (txt, on, k) in enumerate(pills):
                px0 = x0 + i * (pw + 6)
                self._draw_pill(px0, r2_y0, px0 + pw, r2_y0 + r2_h, txt, on, accent, "cycle", k)

            # Row 3: Live LFO Waveform Scope + 7 Wave Selector Pills at bottom of scope
            wave_h = 32
            sc_y1 = gy1 - wave_h - 4
            c.create_rectangle(x0, gy0, x1, sc_y1, fill=COL_PANEL, outline=accent, width=1)
            self._draw_lfo_scope(x0, gy0, x1, sc_y1, li, accent)

            cur_w = self._enum_idx(self._get_zctrl(f"m_uLFOWave_LFO{li}"), 0)
            ww = (x1 - x0 - 6 * 4) / 7
            for i, wname in enumerate(LFO_WAVES):
                wx0 = x0 + i * (ww + 4)
                self._draw_pill(wx0, sc_y1 + 4, wx0 + ww, gy1, wname, i == cur_w, accent,
                                "set_enum", (f"m_uLFOWave_LFO{li}", i))

        elif slot_id.startswith("seq"):
            si = int(slot_id[3:])
            sync_on = self._raw(self._get_zctrl(f"m_bStepSeqSynch_STEPSEQ{si}")) >= 0.5
            self._draw_pill(x0, r2_y0, x0 + 180, r2_y0 + r2_h,
                            "Sync: Beats" if sync_on else "Sync: ms",
                            sync_on, accent, "cycle", f"m_bStepSeqSynch_STEPSEQ{si}")
            c.create_text(x0 + 196, r2_y0 + r2_h / 2, text=f"Step Sequencer {si}  (Drag Pad: X=Gate, Y=Glide)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.84)))

            c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)
            pad = 14
            gx0, gx1 = x0 + pad, x1 - pad
            g_top, g_bot = gy0 + pad, gy1 - pad
            gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)
            gate = self._norm(self._get_zctrl(f"m_fGate_STEPSEQ{si}"), 0.65)
            glide = self._norm(self._get_zctrl(f"m_fGlide_STEPSEQ{si}"), 0.25)

            # Visualize 8 rhythm pulses reflecting gate & glide
            step_w = gw / 8.0
            for st in range(8):
                sx0 = gx0 + st * step_w + 3
                pulse_w = max(4.0, (step_w - 6) * gate)
                h_fac = 0.4 + 0.55 * ((st * 3 + 2) % 5) / 4.0
                py_top = g_bot - h_fac * gh
                c.create_rectangle(sx0, py_top, sx0 + pulse_w, g_bot, fill="#3d3519", outline=accent, width=1.5)
            hx = gx0 + gate * gw
            hy = g_bot - glide * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((
                x0, gy0, x1, gy1, "xy_pad",
                {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot,
                 "x_key": f"m_fGate_STEPSEQ{si}", "y_key": f"m_fGlide_STEPSEQ{si}",
                 "bank_kind": None, "bank_idx": None},
            ))

        else:
            # ARP
            arp_on = self._raw(self._get_zctrl("m_bARPOnOff")) >= 0.5
            sync_on = self._raw(self._get_zctrl("m_bARPSynch")) >= 0.5
            hw = (x1 - x0 - 6) / 2
            self._draw_pill(x0, r2_y0, x0 + hw, r2_y0 + r2_h,
                            "ARPEGGIATOR: ON" if arp_on else "ARPEGGIATOR: OFF",
                            arp_on, "#51cf66", "cycle", "m_bARPOnOff")
            self._draw_pill(x0 + hw + 6, r2_y0, x1, r2_y0 + r2_h,
                            "Sync: Beats" if sync_on else "Sync: ms",
                            sync_on, accent, "cycle", "m_bARPSynch")

            c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent if arp_on else COL_BORDER, width=1)
            cur_m = self._enum_idx(self._get_zctrl("m_uARPMode"), 0)
            modes = ["Poly", "Up", "Down", "UpDown"]
            mw = (x1 - x0 - 20 - 3 * 8) / 4
            for i, mname in enumerate(modes):
                mx0 = x0 + 10 + i * (mw + 8)
                self._draw_pill(mx0, gy0 + 14, mx0 + mw, gy1 - 14, mname, i == cur_m, accent,
                                "set_enum", ("m_uARPMode", i))

        # Row 4: 2x2 Parameter Cards bound to 4 encoders
        py0 = gy1 + 6
        items = self._tab_items("LFO/Arp")
        cw = (x1 - x0 - 6) / 2
        ch = (y1 - py0 - 4) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + 6)
            py_i = py0 + row_i * (ch + 4)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent)

    def _draw_lfo_scope(self, x0, y0, x1, y1, li, color):
        c = self.widget_canvas
        pad = 10
        gx0, gx1 = x0 + pad, x1 - pad
        gy0, gy1 = y0 + pad, y1 - pad
        gw, gh = max(10, gx1 - gx0), max(10, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        wave = self._enum_idx(self._get_zctrl(f"m_uLFOWave_LFO{li}"), 0)
        phase = self._norm(self._get_zctrl(f"m_fLFOPhase_LFO{li}"))
        ramp = self._norm(self._get_zctrl(f"m_fLFORamp_LFO{li}"))

        pts = []
        for i in range(65):
            t = i / 64.0
            p = (t * 2.0 + phase) % 1.0
            if wave == 0:    # Sine
                y = math.sin(p * 2.0 * math.pi)
            elif wave == 1:  # Saw
                y = 1.0 - 2.0 * p
            elif wave == 2:  # Tri
                y = 4.0 * p - 1.0 if p < 0.5 else 3.0 - 4.0 * p
            elif wave == 3:  # Pulse
                y = 1.0 if p < 0.5 else -1.0
            elif wave == 4:  # Noise
                y = math.sin(i * 12.9898) * 0.85
            elif wave == 5:  # SawSine
                y = 0.5 * math.sin(p * 2.0 * math.pi) + 0.5 * (1.0 - 2.0 * p)
            else:            # S&H
                step = int(p * 4)
                y = [0.7, -0.4, 0.9, -0.8][step % 4]
            env = min(1.0, t / max(0.05, ramp * 0.7)) if ramp > 0.02 else 1.0
            pts.extend([gx0 + t * gw, mid_y - y * env * (gh * 0.44)])
        c.create_line(pts, fill=color, width=2.4)

    # --------------------------------------------------------------------------
    # TAB 6: FX (3x MULTIBAND FX BUSSES x 13 MODULES + GRAPHIC EQ + VOWEL PAD)
    # --------------------------------------------------------------------------
    def _draw_tab_fx(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["FX"]
        gap = 5
        b = self.fx_bus

        # Row 1: BUS 1/2/3 Selector + Bus Routing + Mono Cut + Active Module Power
        r1_h = 34
        bus_w = int((x1 - x0) * 0.36)
        bw = (bus_w - 2 * gap) / 3
        for i in range(3):
            bx0 = x0 + i * (bw + gap)
            self._draw_pill(bx0, y0, bx0 + bw, y0 + r1_h, f"BUS {i + 1}",
                            i == b, accent, "fx_bus", i)

        rx0 = x0 + bus_w + gap
        rem_w = x1 - rx0
        rw = (rem_w - 2 * gap) / 3
        rte_k = _fx_key("m_uFxBusRouting", b)
        mono_k = _fx_key("m_fMBMonoFrequency", b)
        fx_id, fx_lbl, on_base = FX_MODULES[self.fx_idx]
        on_k = _fx_key(on_base, b)
        fx_on = self._raw(self._get_zctrl(on_k)) >= 0.5

        self._draw_pill(rx0, y0, rx0 + rw, y0 + r1_h, "Bus Out", False, accent,
                        "cycle", rte_k, subtext=self._fmt(self._get_zctrl(rte_k))[:7])
        self._draw_param_box(rx0 + rw + gap, y0, rx0 + 2 * rw + gap, y0 + r1_h,
                             mono_k, "MonoCut", "#4dabf7")
        self._draw_pill(rx0 + 2 * (rw + gap), y0, x1, y0 + r1_h,
                        f"{fx_lbl}: ON" if fx_on else f"{fx_lbl}: OFF",
                        fx_on, "#51cf66", "cycle", on_k)

        # Row 2: 13 FX Module Buttons (Row 2a: 7 modules, Row 2b: 6 modules)
        r2_y0 = y0 + r1_h + gap
        btn_h = 30
        row_a = FX_MODULES[:7]
        row_b = FX_MODULES[7:]
        wa = (x1 - x0 - (len(row_a) - 1) * 4) / len(row_a)
        for i, (mid, mlbl, mon) in enumerate(row_a):
            mx0 = x0 + i * (wa + 4)
            is_on = self._raw(self._get_zctrl(_fx_key(mon, b))) >= 0.5
            self._draw_pill(mx0, r2_y0, mx0 + wa, r2_y0 + btn_h,
                            f"● {mlbl}" if is_on else mlbl,
                            i == self.fx_idx, accent, "fx_idx", i)
        r2b_y0 = r2_y0 + btn_h + 4
        wb = (x1 - x0 - (len(row_b) - 1) * 4) / len(row_b)
        for j, (mid, mlbl, mon) in enumerate(row_b):
            idx = j + 7
            mx0 = x0 + j * (wb + 4)
            is_on = self._raw(self._get_zctrl(_fx_key(mon, b))) >= 0.5
            self._draw_pill(mx0, r2b_y0, mx0 + wb, r2b_y0 + btn_h,
                            f"● {mlbl}" if is_on else mlbl,
                            idx == self.fx_idx, accent, "fx_idx", idx)

        # Row 3: Interactive Module Workspace (EQ 8-band, Formant Vowel Pad, or Mode/Visual)
        ws_y0 = r2b_y0 + btn_h + gap
        bot_h = 84
        ws_y1 = y1 - bot_h - gap

        if fx_id == "eq":
            c.create_rectangle(x0, ws_y0, x1, ws_y1, fill=COL_BG,
                               outline=accent if fx_on else COL_BORDER, width=1)
            ipad = 4
            fw = (x1 - x0 - 2 * ipad - 7 * 4) / 8
            for i in range(8):
                fx0 = x0 + ipad + i * (fw + 4)
                b_idx = 0 if i in (0, 2, 4, 7) else 1
                self._draw_vfader(
                    fx0, ws_y0 + ipad, fx0 + fw, ws_y1 - ipad,
                    _fx_key(f"m_fEQ{i + 1}", b), EQ_BAND_LABELS[i],
                    accent if fx_on else COL_DIM,
                    bank_kind="eq_bank", bank_idx=b_idx, bipolar=True,
                )
        elif fx_id == "formant":
            c.create_rectangle(x0, ws_y0, x1, ws_y1, fill=COL_PANEL,
                               outline=accent if fx_on else COL_BORDER, width=1)
            pad = 12
            gx0, gx1 = x0 + pad, x1 - pad
            gy0, gy1 = ws_y0 + pad + 12, ws_y1 - pad
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            v1 = self._norm(self._get_zctrl(_fx_key("m_fFormantVowelOne", b)))
            v2 = self._norm(self._get_zctrl(_fx_key("m_fFormantVowelTwo", b)))
            c.create_text(gx0, ws_y0 + 9, text="Formant 2D Vowel Pad  (X: Vowel 1 A-E-I-O-U, Y: Vowel 2)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.76), bold=True))
            for idx, vch in enumerate(VOWEL_NAMES):
                vx = gx0 + (idx / 4.0) * gw
                c.create_line(vx, gy0, vx, gy1, fill=COL_GRID, dash=(2, 3))
                c.create_text(vx, gy1 + 4, text=vch, fill=COL_DIM, font=self._font(self._fs(0.70)))
            hx = gx0 + v1 * gw
            hy = gy1 - v2 * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent if fx_on else COL_DIM,
                          outline="#ffffff", width=2)
            self.hitboxes.append((
                x0, ws_y0, x1, ws_y1, "xy_pad",
                {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                 "x_key": _fx_key("m_fFormantVowelOne", b), "y_key": _fx_key("m_fFormantVowelTwo", b),
                 "bank_kind": None, "bank_idx": None},
            ))
        else:
            # Module-specific quick mode pills + visual parameter bar readout
            c.create_rectangle(x0, ws_y0, x1, ws_y1, fill=COL_PANEL,
                               outline=accent if fx_on else COL_BORDER, width=1)
            self._draw_fx_module_panel(x0, ws_y0, x1, ws_y1, fx_id, b, accent if fx_on else COL_DIM)

        # Row 4: 2x2 Parameter Cards bound to 4 physical encoders
        py0 = ws_y1 + gap
        items = self._tab_items("FX")
        cw = (x1 - x0 - gap) / 2
        ch = (y1 - py0 - 4) / 2
        for i, (key, lbl) in enumerate(items):
            col_i = i % 2
            row_i = i // 2
            px0 = x0 + col_i * (cw + gap)
            py_i = py0 + row_i * (ch + 4)
            bip = ("eq" in key.lower() and not "onoff" in key.lower()) or ("threshold" in key.lower()) or ("makeup" in key.lower()) or ("combdrive" in key.lower())
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, key, lbl, accent, bipolar=bip)

    def _draw_fx_module_panel(self, x0, y0, x1, y1, fx_id, b, color):
        c = self.widget_canvas
        pad = 8
        pills = []
        if fx_id == "delay":
            pills = [
                ("Mode", _fx_key("m_uDelayMode", b)),
                ("Sync", _fx_key("m_bDelaySynch", b)),
            ]
        elif fx_id == "reverb":
            pills = [("Mode", _fx_key("m_uReverbMode", b))]
        elif fx_id == "chorus":
            pills = [("Sync", _fx_key("m_bChorusSynch", b))]
        elif fx_id == "phaser":
            pills = [("Sync", _fx_key("m_bPhaserSynch", b)), ("Wave", _fx_key("m_uPhaserLFOWave", b))]
        elif fx_id == "flanger":
            pills = [("Sync", _fx_key("m_bFlangerSynch", b)), ("Wave", _fx_key("m_uFlangerLFOWave", b))]
        elif fx_id == "atom":
            pills = [("Sync", _fx_key("m_bAtomizerSynch", b)), ("Wave", _fx_key("m_uAtomizerLFOWave", b))]
        elif fx_id == "shaper":
            pills = [("Type", _fx_key("m_uWaveshaperType", b)), ("EQ Pos", _fx_key("m_uWaveshaperPrePostEq", b))]
        elif fx_id == "dyn":
            pills = [
                ("MB Comp", _fx_key("m_bMBCompOffOn", b)),
                ("Lim Mode", _fx_key("m_uLimiterMode", b)),
            ]

        px_end = x0 + pad
        if pills:
            pw = min(130, int((x1 - x0) * 0.22))
            for i, (lbl, k) in enumerate(pills):
                px0 = x0 + pad + i * (pw + 6)
                self._draw_pill(px0, y0 + pad, px0 + pw, y1 - pad, lbl, False, color,
                                "fx_cycle", k, subtext=self._fmt(self._get_zctrl(k), k)[:9])
                px_end = px0 + pw + 8

        # Right side: bar readout of the 4 active FX params
        items = self._tab_items("FX")
        gx0, gx1 = px_end, x1 - pad
        gy0, gy1 = y0 + pad, y1 - pad
        if gx1 - gx0 > 80:
            bw = (gx1 - gx0 - 3 * 8) / 4
            gh = max(10, gy1 - gy0)
            for i, (key, lbl) in enumerate(items):
                bx0 = gx0 + i * (bw + 8)
                n = self._norm(self._get_zctrl(key), log_scale=_is_log_key(key))
                bh = n * gh
                c.create_rectangle(bx0, gy0, bx0 + bw, gy1, fill=COL_TRACK, outline="")
                if bh > 1:
                    c.create_rectangle(bx0, gy1 - bh, bx0 + bw, gy1, fill=color, outline="")
                c.create_text(bx0 + bw / 2, gy0 + 9, text=lbl, fill=COL_TEXT,
                              font=self._font(self._fs(0.74), bold=True))

    # --------------------------------------------------------------------------
    # ECO CPU-Tamer Mode (Polyphony <= Poly4, Unison <= 4 voices per osc bank)
    # --------------------------------------------------------------------------
    def _toggle_eco(self):
        if not self.processor:
            return
        if self.eco_on:
            for key, orig_raw in self._eco_backup.items():
                z = self._get_zctrl(key)
                if z is not None:
                    z.set_value(orig_raw, send=True)
            self._eco_backup.clear()
            self.eco_on = False
            return

        backup = {}

        # 1. Cap PolyMode: Poly16 (2) / Poly32 (3) -> Poly4 (1)
        z_poly = self._get_zctrl("m_uPolyMode")
        if z_poly is not None:
            cur_idx = self._enum_idx(z_poly, 0)
            if cur_idx > 1:
                backup["m_uPolyMode"] = self._raw(z_poly)
                ticks = getattr(z_poly, "ticks", None)
                z_poly.set_value(ticks[1] if ticks and len(ticks) > 1 else 1.0, send=True)

        # 2. Cap Unison voices per Osc Bank A..D to <= 4
        for tag in ("OscA", "OscB", "OscC", "OscD"):
            k = f"m_iNumOscs_{tag}"
            zu = self._get_zctrl(k)
            if zu is not None:
                cur_v = self._raw(zu, 1.0)
                if cur_v > 4.0:
                    backup[k] = cur_v
                    zu.set_value(4.0, send=True)

        self._eco_backup = backup
        self.eco_on = True

    # --------------------------------------------------------------------------
    # Touchscreen Interaction (Tap, Drag, Double-Tap Reset)
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

        if kind in ("macro_bank", "osc_bank", "flt_bank", "env_bank", "eq_bank"):
            self._switch_subbank(kind, payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mod_slot":
            self.mod_slot = payload
            self.macro_bank = 2
            self._live_swap_encoders("Macro")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mod_page":
            self.mod_page = payload
            self.mod_slot = payload * 8
            self._live_swap_encoders("Macro")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mod_step":
            k, step = payload
            self._cycle_enum(self._get_zctrl(k), step)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mod_quick":
            k, idx, val_k = payload
            z = self._get_zctrl(k)
            if z is not None:
                ticks = getattr(z, "ticks", None)
                z.set_value(ticks[idx] if ticks and 0 <= idx < len(ticks) else float(idx), send=True)
            zv = self._get_zctrl(val_k)
            if zv is not None and abs(self._raw(zv)) < 1.0:
                zv.set_value(50.0, send=True)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mod_clear":
            ms = payload
            for ck in (f"m_uModMatSrce{ms}", f"m_uModMatDest{ms}", f"m_fModMatVal{ms}", f"m_fModMatCurve{ms}"):
                z = self._get_zctrl(ck)
                if z is not None:
                    z.set_value(0.0, send=True)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "osc_idx":
            self.osc_idx = payload
            if payload in (4, 5) and self.osc_bank > 1:
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

        if kind == "flt_family":
            fi = self.flt_idx + 1
            z = self._get_zctrl(f"m_uFilterType_Filter{fi}")
            if z is not None:
                _, lo_i, hi_i = FILTER_FAMILIES[payload]
                cur = self._enum_idx(z, 0)
                nxt = (cur + 1) if (lo_i <= cur < hi_i) else lo_i
                ticks = getattr(z, "ticks", None)
                if ticks and nxt < len(ticks):
                    z.set_value(ticks[nxt], send=True)
                else:
                    z.set_value(float(nxt), send=True)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "env_idx":
            self.env_idx = payload
            self._live_swap_encoders("Env")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "env_sync_toggle":
            self._cycle_enum(self._get_zctrl(payload), 1)
            sync_on = self._raw(self._get_zctrl(payload)) >= 0.5
            self.env_bank = 1 if sync_on else 0
            self._live_swap_encoders("Env")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "lfo_slot":
            self.lfo_slot = payload
            self._live_swap_encoders("LFO/Arp")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "fx_bus":
            self.fx_bus = payload
            self._live_swap_encoders("FX")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "fx_idx":
            self.fx_idx = payload
            self._live_swap_encoders("FX")
            self.last_snapshot = None
            self._draw()
            return

        if kind == "set_enum":
            k, idx = payload
            z = self._get_zctrl(k)
            if z is not None:
                ticks = getattr(z, "ticks", None)
                if ticks and 0 <= idx < len(ticks):
                    z.set_value(ticks[idx], send=True)
                else:
                    z.set_value(float(idx), send=True)
            self.last_snapshot = None
            self._draw()
            return

        if kind in ("cycle", "fx_cycle"):
            self._cycle_enum(self._get_zctrl(payload), 1)
            if "synch" in str(payload).lower():
                self._live_swap_encoders(self.active_tab)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "filter_xy":
            gx0, gx1 = payload["gx0"], payload["gx1"]
            gy0, gy1 = payload["gy0"], payload["gy1"]
            gw, gh = max(1, gx1 - gx0), max(1, gy1 - gy0)
            best_idx = self.flt_idx
            best_d = 1e12
            for idx, cut_n, res_n, _, on in payload["states"]:
                if idx != self.flt_idx and not on:
                    continue
                hx = gx0 + cut_n * gw
                hy = gy1 - res_n * gh
                d = (event.x - hx) ** 2 + (event.y - hy) ** 2
                if d < best_d:
                    best_d = d
                    best_idx = idx
            if best_d < 900 and best_idx != self.flt_idx:
                self.flt_idx = best_idx
                self._live_swap_encoders("Filter")
            fi = self.flt_idx + 1
            self._switch_subbank("flt_bank", 0)
            now = time.monotonic()
            tap_id = ("filter_xy", fi)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for rk in (f"m_fFilterCutoff_Filter{fi}", f"m_fFilterReso_Filter{fi}"):
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("xy_pad", {
                "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                "x_key": f"m_fFilterCutoff_Filter{fi}",
                "y_key": f"m_fFilterReso_Filter{fi}",
            })
            self._apply_drag(event.x, event.y)
            return

        if kind == "xy_pad":
            self._switch_subbank(payload.get("bank_kind"), payload.get("bank_idx"))
            now = time.monotonic()
            tap_id = ("xy_pad", payload["x_key"], payload["y_key"])
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for rk in (payload["x_key"], payload["y_key"]):
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("xy_pad", payload)
            self._apply_drag(event.x, event.y)
            return

        if kind == "env_graph":
            self._switch_subbank("env_bank", 0)
            d_a = abs(event.x - payload["xa"])
            d_ds = math.hypot(event.x - payload["xd"], event.y - payload["ys"])
            d_r = abs(event.x - payload["xr"])
            node = "A" if (d_a <= d_ds and d_a <= d_r) else ("DS" if d_ds <= d_r else "R")
            now = time.monotonic()
            ei = payload["ei"]
            tap_id = ("env_node", ei, node)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                rkeys = (
                    [f"m_fAttackTime_MSEG{ei}"] if node == "A"
                    else ([f"m_fDecayTime_MSEG{ei}", f"m_fSustainLevel_MSEG{ei}"] if node == "DS"
                          else [f"m_fReleaseTime_MSEG{ei}"])
                )
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
                self._set_norm(self._get_zctrl(payload["key"]), (ty1 - y) / (ty1 - ty0), log_scale=payload.get("log", False))
        elif kind == "hfader":
            tx0, tx1 = payload["tx0"], payload["tx1"]
            if tx1 > tx0:
                self._set_norm(self._get_zctrl(payload["key"]), (x - tx0) / (tx1 - tx0), log_scale=payload.get("log", False))
        elif kind == "xy_pad":
            gx0, gx1 = payload["gx0"], payload["gx1"]
            gy0, gy1 = payload["gy0"], payload["gy1"]
            xk, yk = payload["x_key"], payload["y_key"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl(xk), (x - gx0) / (gx1 - gx0), log_scale=_is_log_key(xk))
            if gy1 > gy0:
                self._set_norm(self._get_zctrl(yk), (gy1 - y) / (gy1 - gy0), log_scale=_is_log_key(yk))
        elif kind == "env_node":
            ei = payload["ei"]
            gx0, gw = payload["gx0"], payload["gw"]
            g_top, g_bot = payload["g_top"], payload["g_bot"]
            seg_w = max(10.0, gw * 0.28)
            node = payload["node"]
            if node == "A":
                self._set_norm(self._get_zctrl(f"m_fAttackTime_MSEG{ei}"), (x - gx0) / seg_w, log_scale=True)
            elif node == "DS":
                self._set_norm(self._get_zctrl(f"m_fDecayTime_MSEG{ei}"), (x - payload["xa"]) / seg_w, log_scale=True)
                if g_bot > g_top:
                    self._set_norm(self._get_zctrl(f"m_fSustainLevel_MSEG{ei}"), (g_bot - y) / (g_bot - g_top))
            elif node == "R":
                self._set_norm(self._get_zctrl(f"m_fReleaseTime_MSEG{ei}"), (x - payload["xs"]) / seg_w, log_scale=True)

        self.last_snapshot = None
        self._draw()
