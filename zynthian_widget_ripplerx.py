#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# RipplerX Physical Modeling Workstation Widget for Zynthian (V5 800x480)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces RipplerX's 77 raw LV2 parameters (~20 encoder pages) with 6 dynamic
# workstation tabs mapped 1-to-1 to Zynthian's 4 physical encoders + ECO toggle:
#   Couple | Model | Body | Mallet | Noise | VelMod   + ECO
#
# Features:
# - Resilient controller resolver: indexes full LV2 symbol (ripplerx_*), suffix
#   without prefix, and normalized rdfs:label / short_name.
# - Authentic RipplerX DSP scales & logarithmic mappings:
#   * 12 acoustic resonator models (String, Beam, Squared, Membrane, Plate,
#     Drumhead, Marimba, Open/Closed Tube, Marimba2, Bell, Djembe)
#   * 16 mallet exciters (non-contiguous scalePoints 0, 11..25)
#   * Partials enum (1, 2, 4, 8, 16, 32, 64), log Decay (0.01..100s), log Noise
#     Filter (20Hz..20kHz), log Stiffness (100..5000Hz), log ADSR (1ms..20s)
# - Real-time interactive DSP visualizations:
#   * Couple: interactive acoustic signal flow (Mallet+Noise -> A/B) + 4 faders
#   * Model: 3x4 physical body model grid + live modal partial spectrum graph
#   * Body: dual 2D physics pads (HitPos x Inharmonic + Decay x Material)
#   * Mallet: 16-type selector + interactive 2D Stiffness x Resonance pad
#   * Noise: 2D SVF Filter XY pad (LP/BP/HP) + interactive 2D ADSR+Tension graph
#   * VelMod: bipolar (-100%..+100%) interactive velocity modulation bar graph
# - Unified Design System (UI Synths): >=34px touch targets, 6px gaps, _fit_font
#   zero-overflow text, double-tap reset on all sliders/2D nodes, ECO partial cap.
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

TABS = ["Couple", "Model", "Body", "Mallet", "Noise", "VelMod"]
TAB_ACCENTS = {
    "Couple": "#4dabf7",  # blue
    "Model":  "#cc5de8",  # violet
    "Body":   "#ff922b",  # orange
    "Mallet": "#ffd43b",  # yellow
    "Noise":  "#51cf66",  # green
    "VelMod": "#ff6b6b",  # coral
}
COL_RES_A = "#4dabf7"
COL_RES_B = "#38d9a9"

# ------------------------------------------------------------------------------
# Authentic RipplerX Enum Tables, Modal Ratios & Logarithmic Scales
# ------------------------------------------------------------------------------
TOGGLE_OFF_ON = ["Off", "On"]
COUPLE_MODES = ["A+B", "A>B"]
NOISE_FLT_MODES = ["LP", "BP", "HP"]

RES_MODELS = [
    "String", "Beam", "Squared", "Membrane", "Plate", "Drumhead",
    "Marimba", "OpenTube", "ClosTube", "Marimba2", "Bell", "Djembe",
]

# Authentic RipplerX scalePoint order for a_partials / b_partials (values 0..6)
PARTIAL_LABELS = ["4", "8", "16", "32", "64", "1", "2"]
PARTIAL_COUNTS = [4, 8, 16, 32, 64, 1, 2]

# Authentic RipplerX scalePoints for mallet_type (note non-contiguous values 0, 11..25!)
MALLET_TYPES = [
    (0,  "Impulse"),
    (11, "User"),
    (12, "Click 1"),
    (13, "Click 2"),
    (14, "Click 3"),
    (15, "Click 4"),
    (16, "Click 5"),
    (17, "Click 6"),
    (18, "Blip"),
    (19, "Blop"),
    (20, "Metal 1"),
    (21, "Metal 2"),
    (22, "Wood"),
    (23, "Strike"),
    (24, "Perc 1"),
    (25, "Perc 2"),
]

# Characteristic modal overtone ratios for each physical model (for spectrum preview)
MODEL_MODES = {
    0:  [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0],         # String
    1:  [1.0, 2.76, 5.40, 8.93, 13.34, 18.64, 24.81, 31.87],                      # Beam
    2:  [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],                                 # Squared
    3:  [1.0, 1.59, 2.14, 2.30, 2.65, 2.92, 3.16, 3.50, 3.60, 4.06],              # Membrane
    4:  [1.0, 1.73, 2.35, 3.16, 3.61, 4.24, 5.10, 5.83, 6.48],                    # Plate
    5:  [1.0, 1.59, 2.14, 2.30, 2.65, 2.92, 3.16, 3.60],                          # Drumhead
    6:  [1.0, 3.93, 9.54, 16.5, 24.0, 32.0],                                      # Marimba
    7:  [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],                      # Open Tube
    8:  [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0],                              # Closed Tube
    9:  [1.0, 4.0, 9.2, 15.8, 23.4, 31.0],                                        # Marimba2
    10: [1.0, 2.0, 2.4, 3.0, 4.0, 4.2, 5.4, 6.8, 8.1],                            # Bell
    11: [1.0, 1.62, 2.24, 2.52, 2.98, 3.41, 3.85, 4.30],                          # Djembe
}

# Parameters that feel much better with logarithmic touch drag
LOG_PARAMS = {
    "a_decay":           (0.01, 100.0),
    "b_decay":           (0.01, 100.0),
    "a_ratio":           (0.1, 10.0),
    "b_ratio":           (0.1, 10.0),
    "a_rel":             (0.001, 1.0),
    "b_rel":             (0.001, 1.0),
    "mallet_stiff":      (100.0, 5000.0),
    "noise_filter_freq": (20.0, 20000.0),
    "noise_att":         (1.0, 20000.0),
    "noise_dec":         (1.0, 20000.0),
    "noise_rel":         (1.0, 20000.0),
}


def _norm_key(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def fmt_hz(hz):
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}k" if hz < 10000.0 else f"{hz / 1000.0:.1f}k"
    return f"{int(round(hz))}Hz"


def fmt_ms(ms):
    if ms >= 1000.0:
        return f"{ms / 1000.0:.2f}s" if ms < 10000.0 else f"{ms / 1000.0:.1f}s"
    return f"{int(round(ms))}ms"


def fmt_sec(sec):
    if sec < 1.0:
        return f"{int(round(sec * 1000.0))}ms"
    if sec < 10.0:
        return f"{sec:.2f}s"
    return f"{sec:.1f}s"


# ------------------------------------------------------------------------------
# RipplerX Workstation Widget Class
# ------------------------------------------------------------------------------
class zynthian_widget_ripplerx(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)

        self.active_tab = "Couple"
        self.res_idx = 0       # 0=A, 1=B
        self.couple_bank = 0   # 0=Couple/Mix, 1=Pitch A/B, 2=Exciters/Key
        self.model_bank = 0    # 0=Model/Partials, 1=Pitch/Cut
        self.body_bank = 0     # 0=Decay/Mat, 1=Hit/Inharm, 2=Pitch/Tube
        self.mallet_bank = 0   # 0=Core, 1=Tone/Vel
        self.noise_bank = 0    # 0=Filter/Mix, 1=ADSR, 2=Tension/DC
        self.vel_bank = 0      # 0=Res A, 1=Res B, 2=Mallet, 3=Noise Flt, 4=Noise Env

        self.eco_on = False
        self._eco_backup = {}

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
    # Processor Setup, Resilient Controller Resolver & Scale Enhancement
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
        """Index both full symbol (ripplerx_*) and unprefixed suffix + normalized labels."""
        idx = {}
        for sym, z in processor.controllers_dict.items():
            ns = _norm_key(sym)
            idx[ns] = z
            if ns.startswith("ripplerx_"):
                idx[ns[len("ripplerx_"):]] = z
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
        cdict = self.processor.controllers_dict
        z = cdict.get("ripplerx_" + key)
        if z is not None:
            return z
        z = cdict.get(key)
        if z is not None:
            return z
        return self._ctrl_index.get(_norm_key(key))

    def _configure_zctrl_enum(self, z, labels, ticks):
        if z is None or not labels or not ticks:
            return
        try:
            cur_val = float(z.get_value())
        except Exception:
            cur_val = float(ticks[0])
        z.labels = list(labels)
        z.ticks = list(ticks)
        z.is_toggle = (len(labels) == 2)
        z.is_integer = all(isinstance(t, int) for t in ticks)
        z.value_min = ticks[0]
        z.value_max = ticks[-1]
        z.value_range = z.value_max - z.value_min
        z.value_mid = z.value_min + z.value_range / 2.0
        z.range_reversed = False
        z.label2value = {str(l): t for l, t in zip(labels, ticks)}
        z.value2label = {str(t): l for l, t in zip(labels, ticks)}
        # Snap to nearest valid tick if non-contiguous (e.g. mallet_type 0, 11..25)
        nearest = min(ticks, key=lambda t: abs(t - cur_val))
        z.value = nearest

    def _enhance_all_zctrls(self):
        # Strip auto-widget hijack attributes (RipplerX Noise ADSR has param:attack..release)
        if self.processor:
            for z in self.processor.controllers_dict.values():
                for attr in ("filter", "envelope"):
                    if hasattr(z, attr):
                        try:
                            delattr(z, attr)
                        except Exception:
                            pass

        self._configure_zctrl_enum(self._get_zctrl("a_on"), TOGGLE_OFF_ON, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("b_on"), TOGGLE_OFF_ON, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("couple"), COUPLE_MODES, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("stereoizer"), TOGGLE_OFF_ON, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("reuse_voices"), TOGGLE_OFF_ON, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("fadeout_repeats"), TOGGLE_OFF_ON, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("noise_filter_mode"), NOISE_FLT_MODES, [0, 1, 2])
        self._configure_zctrl_enum(
            self._get_zctrl("mallet_type"),
            [lbl for _, lbl in MALLET_TYPES],
            [val for val, _ in MALLET_TYPES],
        )
        for p in ("a", "b"):
            self._configure_zctrl_enum(self._get_zctrl(f"{p}_model"), RES_MODELS, list(range(len(RES_MODELS))))
            self._configure_zctrl_enum(self._get_zctrl(f"{p}_partials"), PARTIAL_LABELS, list(range(len(PARTIAL_LABELS))))

    # --------------------------------------------------------------------------
    # Dynamic 4-Encoder Page Mapping (6 Tabs, 2-Level Sub-Banks)
    # --------------------------------------------------------------------------
    def _rp(self):
        return "a" if self.res_idx == 0 else "b"

    def _tab_items(self, tab_name):
        p = self._rp()
        P = p.upper()

        if tab_name == "Couple":
            if self.couple_bank == 0:
                return [
                    ("couple",   "Coupling"),
                    ("ab_mix",   "A+B Mix"),
                    ("ab_split", "A>B Split"),
                    ("gain",     "Res Gain"),
                ]
            if self.couple_bank == 1:
                return [
                    ("a_coarse", "A Coarse"),
                    ("a_fine",   "A Fine"),
                    ("b_coarse", "B Coarse"),
                    ("b_fine",   "B Fine"),
                ]
            return [
                ("mallet_mix", "Mallet Mix"),
                ("noise_mix",  "Noise Mix"),
                ("stereoizer", "Stereo"),
                ("bend_range", "PB Range"),
            ]

        if tab_name == "Model":
            if self.model_bank == 0:
                return [
                    (f"{p}_model",    f"{P} Model"),
                    (f"{p}_partials", f"{P} Partials"),
                    (f"{p}_ratio",    f"{P} Ratio"),
                    (f"{p}_radius",   f"{P} Radius"),
                ]
            return [
                (f"{p}_coarse", f"{P} Coarse"),
                (f"{p}_fine",   f"{P} Fine"),
                (f"{p}_cut",    f"{P} LowCut"),
                (f"{p}_rel",    f"{P} Release"),
            ]

        if tab_name == "Body":
            if self.body_bank == 0:
                return [
                    (f"{p}_decay", f"{P} Decay"),
                    (f"{p}_damp",  f"{P} Material"),
                    (f"{p}_tone",  f"{P} Tone"),
                    (f"{p}_rel",   f"{P} Release"),
                ]
            if self.body_bank == 1:
                return [
                    (f"{p}_hit",    f"{P} HitPos"),
                    (f"{p}_inharm", f"{P} Inharm"),
                    (f"{p}_ratio",  f"{P} Ratio"),
                    (f"{p}_cut",    f"{P} LowCut"),
                ]
            return [
                (f"{p}_coarse",   f"{P} Coarse"),
                (f"{p}_fine",     f"{P} Fine"),
                (f"{p}_partials", f"{P} Partials"),
                (f"{p}_radius",   f"{P} Radius"),
            ]

        if tab_name == "Mallet":
            if self.mallet_bank == 0:
                return [
                    ("mallet_type",  "Mallet"),
                    ("mallet_mix",   "Mix"),
                    ("mallet_stiff", "Stiff"),
                    ("mallet_pitch", "Pitch"),
                ]
            return [
                ("mallet_filter",    "Filter"),
                ("mallet_res",       "Resonance"),
                ("mallet_ktrack",    "KeyTrack"),
                ("vel_mallet_stiff", "Vel Stiff"),
            ]

        if tab_name == "Noise":
            if self.noise_bank == 0:
                return [
                    ("noise_mix",         "Noise Mix"),
                    ("noise_filter_freq", "Flt Freq"),
                    ("noise_filter_q",    "Flt Q"),
                    ("noise_res",         "Res Send"),
                ]
            if self.noise_bank == 1:
                return [
                    ("noise_att", "Attack"),
                    ("noise_dec", "Decay"),
                    ("noise_sus", "Sustain"),
                    ("noise_rel", "Release"),
                ]
            return [
                ("noise_att_ten", "Att Tens"),
                ("noise_dec_ten", "Dec Tens"),
                ("noise_rel_ten", "Rel Tens"),
                ("noise_osc",     "Noise DC"),
            ]

        # VelMod
        if self.vel_bank == 0:
            return [
                ("vel_a_decay", "Vel A Dec"),
                ("vel_a_hit",   "Vel A Hit"),
                ("vel_a_damp",  "Vel A Mat"),
                ("vel_a_tone",  "Vel A Tone"),
            ]
        if self.vel_bank == 1:
            return [
                ("vel_b_decay", "Vel B Dec"),
                ("vel_b_hit",   "Vel B Hit"),
                ("vel_b_damp",  "Vel B Mat"),
                ("vel_b_tone",  "Vel B Tone"),
            ]
        if self.vel_bank == 2:
            return [
                ("vel_mallet_mix",   "Vel MltMix"),
                ("vel_mallet_stiff", "Vel Stiff"),
                ("vel_mallet_res",   "Vel MltRes"),
                ("vel_noise_mix",    "Vel NseMix"),
            ]
        if self.vel_bank == 3:
            return [
                ("vel_noise_res",  "Vel NseRes"),
                ("vel_noise_freq", "Vel FltFrq"),
                ("vel_noise_q",    "Vel FltQ"),
                ("vel_a_inharm",   "Vel A Inh"),
            ]
        return [
            ("vel_noise_att", "Vel NseAtt"),
            ("vel_noise_dec", "Vel NseDec"),
            ("vel_noise_sus", "Vel NseSus"),
            ("vel_noise_rel", "Vel NseRel"),
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
            logging.debug(f"RipplerX widget: live swap error => {e}")

    def _sync_zyngui_list(self, target_tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page_by_title(target_tab)
            self._draw()
        except Exception as e:
            logging.debug(f"RipplerX widget: sync list error => {e}")

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
    def _val(zctrl, default=0.0):
        if zctrl is None:
            return default
        try:
            return float(zctrl.get_value())
        except Exception:
            return default

    def _norm(self, zctrl, key=None, default=0.0):
        if zctrl is None:
            return default
        try:
            v = float(zctrl.get_value())
            if key in LOG_PARAMS:
                lo, hi = LOG_PARAMS[key]
                v_clamped = max(lo, min(hi, v))
                return max(0.0, min(1.0, math.log(v_clamped / lo) / math.log(hi / lo)))
            vmin = float(getattr(zctrl, "value_min", 0.0))
            vmax = float(getattr(zctrl, "value_max", 1.0))
            span = vmax - vmin
            if span <= 0.0:
                return default
            return max(0.0, min(1.0, (v - vmin) / span))
        except Exception:
            return default

    def _set_norm(self, zctrl, norm_val, key=None):
        if zctrl is None:
            return
        n = max(0.0, min(1.0, float(norm_val)))
        if key in LOG_PARAMS:
            lo, hi = LOG_PARAMS[key]
            val = lo * ((hi / lo) ** n)
            zctrl.set_value(val, send=True)
            return
        ticks = getattr(zctrl, "ticks", None)
        if ticks and len(ticks) > 1 and getattr(zctrl, "is_integer", False):
            idx = int(round(n * (len(ticks) - 1)))
            zctrl.set_value(ticks[max(0, min(len(ticks) - 1, idx))], send=True)
            return
        vmin = float(getattr(zctrl, "value_min", 0.0))
        vmax = float(getattr(zctrl, "value_max", 1.0))
        val = vmin + n * (vmax - vmin)
        if getattr(zctrl, "is_integer", False) or getattr(zctrl, "is_toggle", False):
            val = int(round(val))
        zctrl.set_value(val, send=True)

    @staticmethod
    def _set_raw(zctrl, val):
        if zctrl is None:
            return
        vmin = getattr(zctrl, "value_min", 0.0)
        vmax = getattr(zctrl, "value_max", 1.0)
        v = max(vmin, min(vmax, val))
        if getattr(zctrl, "is_integer", False) or getattr(zctrl, "is_toggle", False):
            v = int(round(v))
        zctrl.set_value(v, send=True)

    @staticmethod
    def _cycle_enum(zctrl, step=1):
        if zctrl is None:
            return
        ticks = getattr(zctrl, "ticks", None)
        if ticks:
            try:
                cur = float(zctrl.get_value())
                idx = min(range(len(ticks)), key=lambda i: abs(ticks[i] - cur))
            except Exception:
                idx = 0
            new_idx = (idx + step) % len(ticks)
            zctrl.set_value(ticks[new_idx], send=True)
            return
        vmin = int(round(getattr(zctrl, "value_min", 0)))
        vmax = int(round(getattr(zctrl, "value_max", 1)))
        if vmax > vmin:
            cur = int(round(zynthian_widget_ripplerx._val(zctrl, vmin)))
            nxt = vmin + ((cur - vmin + step) % (vmax - vmin + 1))
            zctrl.set_value(nxt, send=True)

    def _mallet_idx(self):
        v = self._val(self._get_zctrl("mallet_type"), 0.0)
        return min(range(len(MALLET_TYPES)), key=lambda i: abs(MALLET_TYPES[i][0] - v))

    def _fmt(self, zctrl, key=None):
        if zctrl is None:
            return "--"
        if key == "mallet_type":
            return MALLET_TYPES[self._mallet_idx()][1]
        if key in ("a_model", "b_model"):
            idx = max(0, min(len(RES_MODELS) - 1, int(round(self._val(zctrl, 0)))))
            return RES_MODELS[idx]
        if key in ("a_partials", "b_partials"):
            idx = max(0, min(len(PARTIAL_LABELS) - 1, int(round(self._val(zctrl, 3)))))
            return PARTIAL_LABELS[idx]
        if key == "couple":
            return COUPLE_MODES[1 if self._val(zctrl, 0) >= 0.5 else 0]
        if key == "noise_filter_mode":
            idx = max(0, min(2, int(round(self._val(zctrl, 2)))))
            return NOISE_FLT_MODES[idx]
        if key in ("a_on", "b_on", "stereoizer", "reuse_voices", "fadeout_repeats"):
            return "On" if self._val(zctrl, 0) >= 0.5 else "Off"
        v = self._val(zctrl, 0.0)
        if key in ("a_decay", "b_decay"):
            return fmt_sec(v)
        if key in ("noise_att", "noise_dec", "noise_rel"):
            return fmt_ms(v)
        if key in ("mallet_stiff", "noise_filter_freq"):
            return fmt_hz(v)
        if key == "noise_filter_q":
            return f"Q {v:.2f}"
        if key in ("a_coarse", "b_coarse", "mallet_pitch"):
            return f"{int(round(v)):+d}st"
        if key in ("a_fine", "b_fine"):
            return f"{int(round(v)):+d}ct"
        if key == "gain":
            return f"{v:+.1f}dB"
        if key == "bend_range":
            return f"{int(round(v))}st"
        if key in ("a_ratio", "b_ratio"):
            return f"{v:.2f}x"
        if key in ("a_hit", "b_hit"):
            return f"{int(round(v * 100))}%"
        if key and (key.startswith("vel_") or key.endswith(("_damp", "_tone", "_cut", "_ten")) or key == "mallet_filter"):
            return f"{int(round(v * 100)):+d}%"
        if key in ("ab_mix", "ab_split", "mallet_mix", "mallet_res", "mallet_ktrack",
                   "noise_mix", "noise_osc", "noise_res", "noise_sus",
                   "a_rel", "b_rel", "a_inharm", "b_inharm", "a_radius", "b_radius"):
            return f"{int(round(v * 100))}%"
        try:
            if getattr(zctrl, "labels", None):
                return str(zctrl.get_value2label())
        except Exception:
            pass
        return f"{v:.2f}"

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
        p = self._rp()
        if self.active_tab == "Couple":
            keys += [
                "a_on", "b_on", "couple", "ab_mix", "ab_split", "gain",
                "mallet_mix", "noise_mix", "stereoizer", "reuse_voices",
                "fadeout_repeats", "a_model", "b_model",
            ]
        elif self.active_tab == "Model":
            keys += [
                "a_on", "b_on", f"{p}_model", f"{p}_partials",
                f"{p}_inharm", f"{p}_ratio", f"{p}_damp", f"{p}_radius",
            ]
        elif self.active_tab == "Body":
            keys += [
                "a_on", "b_on",
                "a_hit", "a_inharm", "a_decay", "a_damp", "a_tone", "a_rel",
                "b_hit", "b_inharm", "b_decay", "b_damp", "b_tone", "b_rel",
            ]
        elif self.active_tab == "Mallet":
            keys += [
                "mallet_type", "mallet_mix", "mallet_stiff", "mallet_pitch",
                "mallet_filter", "mallet_res", "mallet_ktrack",
            ]
        elif self.active_tab == "Noise":
            keys += [
                "noise_mix", "noise_osc", "noise_res", "noise_filter_mode",
                "noise_filter_freq", "noise_filter_q", "noise_att", "noise_dec",
                "noise_sus", "noise_rel", "noise_att_ten", "noise_dec_ten", "noise_rel_ten",
            ]
        elif self.active_tab == "VelMod":
            keys += [
                "vel_a_decay", "vel_a_hit", "vel_a_damp", "vel_a_tone", "vel_a_inharm",
                "vel_b_decay", "vel_b_hit", "vel_b_damp", "vel_b_tone", "vel_b_inharm",
                "vel_mallet_mix", "vel_mallet_stiff", "vel_mallet_res",
                "vel_noise_mix", "vel_noise_res", "vel_noise_freq", "vel_noise_q",
                "vel_noise_att", "vel_noise_dec", "vel_noise_sus", "vel_noise_rel",
            ]
        return keys

    def _state_snapshot(self):
        vals = [
            self.active_tab, self.res_idx, self.couple_bank, self.model_bank,
            self.body_bank, self.mallet_bank, self.noise_bank, self.vel_bank,
            self.eco_on, self.width, self.height,
        ]
        for k in self._watched_keys():
            vals.append(round(self._val(self._get_zctrl(k), -999.0), 4))
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
        norm = self._norm(z, key)

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
        norm = self._norm(z, key)

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

    def _draw_res_selector(self, x0, y0, x1, y1):
        """Draw RES A / RES B + ON/OFF selector strip (left half of row 1)."""
        gap = 6
        a_on = self._val(self._get_zctrl("a_on"), 1) >= 0.5
        b_on = self._val(self._get_zctrl("b_on"), 0) >= 0.5
        p = self._rp()
        cur_on = a_on if p == "a" else b_on
        w3 = (x1 - x0 - 2 * gap) / 3
        self._draw_pill(x0, y0, x0 + w3, y1, "●A" if a_on else "A",
                        self.res_idx == 0, COL_RES_A, "res_idx", 0)
        self._draw_pill(x0 + w3 + gap, y0, x0 + 2 * w3 + gap, y1, "●B" if b_on else "B",
                        self.res_idx == 1, COL_RES_B, "res_idx", 1)
        self._draw_pill(x0 + 2 * (w3 + gap), y0, x1, y1, "ON" if cur_on else "OFF",
                        cur_on, "#51cf66", "cycle", f"{p}_on")

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
            bipolar = (
                key.startswith("vel_")
                or key.endswith(("_damp", "_tone", "_cut", "_coarse", "_fine", "_ten"))
                or key in ("gain", "mallet_pitch", "mallet_filter")
            )
            self._draw_param_box(px0, py0, px0 + cw, py0 + ch, key, lbl, accent, bipolar=bipolar)

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

        if self.active_tab == "Couple":
            self._draw_tab_couple(bx0, by0, bx1, by1)
        elif self.active_tab == "Model":
            self._draw_tab_model(bx0, by0, bx1, by1)
        elif self.active_tab == "Body":
            self._draw_tab_body(bx0, by0, bx1, by1)
        elif self.active_tab == "Mallet":
            self._draw_tab_mallet(bx0, by0, bx1, by1)
        elif self.active_tab == "Noise":
            self._draw_tab_noise(bx0, by0, bx1, by1)
        elif self.active_tab == "VelMod":
            self._draw_tab_vel(bx0, by0, bx1, by1)

    def _draw_header(self, x0, y0, x1, y1):
        c = self.widget_canvas
        total_w = x1 - x0
        eco_w = max(52, int(total_w * 0.11))
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
                font=self._fit_font(tname, tw - 6, self._fs(0.94), bold=True),
            )
            self.hitboxes.append((cx, y0, cx + tw, y1, "tab", tname))
            cx += tw + gap

        ex0 = x1 - eco_w
        eco_col = "#51cf66"
        eco_txt = "ECO ●" if self.eco_on else "ECO"
        c.create_rectangle(
            ex0, y0, x1, y1,
            fill=eco_col if self.eco_on else COL_PANEL_HI,
            outline=eco_col if self.eco_on else COL_BORDER,
            width=2 if self.eco_on else 1,
        )
        c.create_text(
            (ex0 + x1) / 2, (y0 + y1) / 2,
            text=eco_txt,
            fill="#0d0e12" if self.eco_on else COL_TEXT,
            font=self._fit_font(eco_txt, eco_w - 6, self._fs(0.9), bold=True),
        )
        self.hitboxes.append((ex0, y0, x1, y1, "eco", None))

    # --------------------------------------------------------------------------
    # TAB 1: COUPLE (Interactive Acoustic Signal Flow + 4 Master Faders)
    # --------------------------------------------------------------------------
    def _draw_tab_couple(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Couple"]
        gap = 6

        # Row 1: Quick Global & Coupling Tiles
        tile_h = 38
        tiles = [
            ("Res A",   "a_on",            "cycle"),
            ("Res B",   "b_on",            "cycle"),
            ("Couple",  "couple",          "cycle"),
            ("Stereo",  "stereoizer",      "cycle"),
            ("Reuse",   "reuse_voices",    "cycle"),
            ("FadeRpt", "fadeout_repeats", "cycle"),
        ]
        tw = (x1 - x0 - gap * (len(tiles) - 1)) / len(tiles)
        for i, (lbl, key, hk) in enumerate(tiles):
            tx0 = x0 + i * (tw + gap)
            z = self._get_zctrl(key)
            act = (key in ("a_on", "b_on", "stereoizer", "reuse_voices", "fadeout_repeats") and self._val(z, 0) >= 0.5)
            self._draw_pill(tx0, y0, tx0 + tw, y0 + tile_h, lbl, act, accent,
                            hk, key, subtext=self._fmt(z, key)[:8])

        # Row 2: Encoder Bank Bar
        by0 = y0 + tile_h + gap
        bh = 34
        self._draw_bank_bar(
            x0, by0, x1, by0 + bh,
            ["Couple & Gain", "Pitch A / B", "Exciters & Key"],
            self.couple_bank, accent, "couple_bank",
        )

        # Row 3: Interactive Acoustic Routing Diagram (left 54%) + 4 Vertical Faders (right 46%)
        my0 = by0 + bh + gap
        left_w = int((x1 - x0) * 0.54)
        lx1 = x0 + left_w
        rx0 = lx1 + gap

        c.create_rectangle(x0, my0, lx1, y1, fill=COL_PANEL, outline=accent, width=1)
        self._draw_signal_flow(x0, my0, lx1, y1)

        # Right: 4 Vertical Master Faders
        is_serial = self._val(self._get_zctrl("couple"), 0) >= 0.5
        faders = [
            ("mallet_mix", "MLT",   TAB_ACCENTS["Mallet"], 2, False),
            ("noise_mix",  "NSE",   TAB_ACCENTS["Noise"],  2, False),
            ("ab_split" if is_serial else "ab_mix", "SPLIT" if is_serial else "A/B", accent, 0, False),
            ("gain",       "GAIN",  "#ff6b6b",             0, True),
        ]
        fw = (x1 - rx0 - gap * 3) / 4
        for i, (key, lbl, fcol, b_idx, bip) in enumerate(faders):
            fx0 = rx0 + i * (fw + gap)
            self._draw_vfader(fx0, my0, fx0 + fw, y1, key, lbl, fcol,
                              bank_kind="couple_bank", bank_idx=b_idx, bipolar=bip)

    def _draw_signal_flow(self, x0, y0, x1, y1):
        c = self.widget_canvas
        a_on = self._val(self._get_zctrl("a_on"), 1) >= 0.5
        b_on = self._val(self._get_zctrl("b_on"), 0) >= 0.5
        serial = self._val(self._get_zctrl("couple"), 0) >= 0.5
        a_mod = self._fmt(self._get_zctrl("a_model"), "a_model")
        b_mod = self._fmt(self._get_zctrl("b_model"), "b_model")
        m_lvl = int(round(self._val(self._get_zctrl("mallet_mix"), 0.5) * 100))
        n_lvl = int(round(self._val(self._get_zctrl("noise_mix"), 0.0) * 100))

        pad = 12
        w = (x1 - x0) - 2 * pad
        h = (y1 - y0) - 2 * pad
        bw = max(56, w * 0.36)
        bh = max(44, min(62, h * 0.34))

        # Left column: Mallet (top) & Noise (bottom)
        ex_x0 = x0 + pad
        ex_x1 = ex_x0 + bw
        m_y0 = y0 + pad + 12
        m_y1 = m_y0 + bh
        n_y1 = y1 - pad
        n_y0 = n_y1 - bh

        # Right column: Res A (top) & Res B (bottom)
        rs_x1 = x1 - pad
        rs_x0 = rs_x1 - bw
        a_y0, a_y1 = m_y0, m_y1
        b_y0, b_y1 = n_y0, n_y1

        # Routing arrows
        mid_x = (ex_x1 + rs_x0) / 2
        m_cy, n_cy = (m_y0 + m_y1) / 2, (n_y0 + n_y1) / 2
        a_cy, b_cy = (a_y0 + a_y1) / 2, (b_y0 + b_y1) / 2
        c.create_line(ex_x1, m_cy, mid_x, m_cy, mid_x, a_cy, rs_x0, a_cy,
                      fill=TAB_ACCENTS["Mallet"] if a_on else COL_DIM, width=2, arrow=tkinter.LAST)
        c.create_line(ex_x1, n_cy, mid_x, n_cy, mid_x, a_cy, rs_x0, a_cy,
                      fill=TAB_ACCENTS["Noise"] if a_on else COL_DIM, width=2)
        if serial:
            # A > B serial coupling arrow
            ax_mid = (rs_x0 + rs_x1) / 2
            c.create_line(ax_mid, a_y1, ax_mid, b_y0,
                          fill=COL_RES_B if (a_on and b_on) else COL_DIM, width=2.5, arrow=tkinter.LAST)
            mode_txt = "A > B  SERIAL COUPLED"
        else:
            # A + B parallel
            c.create_line(mid_x, m_cy, mid_x, b_cy, rs_x0, b_cy,
                          fill=COL_RES_B if b_on else COL_DIM, width=2, arrow=tkinter.LAST)
            mode_txt = "A + B  PARALLEL"

        c.create_text((x0 + x1) / 2, y0 + 11, text=mode_txt, fill=TAB_ACCENTS["Couple"],
                      font=self._fit_font(mode_txt, w, self._fs(0.84), bold=True))

        # Interactive blocks (tap to jump to tab or toggle A/B)
        self._draw_pill(ex_x0, m_y0, ex_x1, m_y1, "MALLET", m_lvl > 0, TAB_ACCENTS["Mallet"],
                        "tab", "Mallet", subtext=f"{m_lvl}%")
        self._draw_pill(ex_x0, n_y0, ex_x1, n_y1, "NOISE", n_lvl > 0, TAB_ACCENTS["Noise"],
                        "tab", "Noise", subtext=f"{n_lvl}%")
        self._draw_pill(rs_x0, a_y0, rs_x1, a_y1, "RES A", a_on, COL_RES_A,
                        "cycle", "a_on", subtext=a_mod if a_on else "OFF")
        self._draw_pill(rs_x0, b_y0, rs_x1, b_y1, "RES B", b_on, COL_RES_B,
                        "cycle", "b_on", subtext=b_mod if b_on else "OFF")

    # --------------------------------------------------------------------------
    # TAB 2: MODEL (12 Physical Body Models + Live Modal Partial Spectrum)
    # --------------------------------------------------------------------------
    def _draw_tab_model(self, x0, y0, x1, y1):
        c = self.widget_canvas
        p = self._rp()
        accent = COL_RES_A if p == "a" else COL_RES_B
        gap = 6

        # Row 1: RES A / B + ON/OFF (left 40%) + Bank Bar (right 60%)
        r1_h = 34
        left_w = (x1 - x0) * 0.40
        self._draw_res_selector(x0, y0, x0 + left_w, y0 + r1_h)
        self._draw_bank_bar(
            x0 + left_w + gap, y0, x1, y0 + r1_h,
            ["Model & Partials", "Pitch & Cut"],
            self.model_bank, accent, "model_bank",
        )

        # Row 2: 3x4 Physical Model Grid (left 56%) + Modal Overtone Spectrum (right 44%)
        mid_y0 = y0 + r1_h + gap
        bot_h = 84
        mid_y1 = y1 - bot_h - gap
        grid_w = int((x1 - x0) * 0.56)
        gx1 = x0 + grid_w

        m_idx = max(0, min(len(RES_MODELS) - 1, int(round(self._val(self._get_zctrl(f"{p}_model"), 0)))))
        cols, rows = 3, 4
        ggap = 4
        mw = (grid_w - (cols - 1) * ggap) / cols
        mh = (mid_y1 - mid_y0 - (rows - 1) * ggap) / rows
        for idx, mlbl in enumerate(RES_MODELS):
            col_i = idx % cols
            row_i = idx // cols
            tx0 = x0 + col_i * (mw + ggap)
            ty0 = mid_y0 + row_i * (mh + ggap)
            self._draw_pill(tx0, ty0, tx0 + mw, ty0 + mh, mlbl,
                            idx == m_idx, accent, "res_model", idx)

        # Right: Live Modal Partial Spectrum Visualizer
        sx0 = gx1 + gap
        c.create_rectangle(sx0, mid_y0, x1, mid_y1, fill=COL_PANEL, outline=accent, width=1)
        p_idx = max(0, min(len(PARTIAL_COUNTS) - 1, int(round(self._val(self._get_zctrl(f"{p}_partials"), 3)))))
        n_parts = PARTIAL_COUNTS[p_idx]
        inharm = self._val(self._get_zctrl(f"{p}_inharm"), 0.0)
        damp = self._val(self._get_zctrl(f"{p}_damp"), 0.0)
        modes = MODEL_MODES.get(m_idx, MODEL_MODES[0])

        sp_x0, sp_x1 = sx0 + 10, x1 - 10
        sp_top, sp_bot = mid_y0 + 24, mid_y1 - 10
        sp_w = max(10, sp_x1 - sp_x0)
        sp_h = max(10, sp_bot - sp_top)
        c.create_line(sp_x0, sp_bot, sp_x1, sp_bot, fill=COL_GRID, width=1)

        vis_n = min(len(modes), max(1, min(12, n_parts)))
        max_f = max(modes[vis_n - 1], 4.0) * (1.0 + inharm * 0.5)
        for k in range(vis_n):
            f_ratio = modes[k] * (1.0 + inharm * (k * 0.12))
            xn = math.log(max(1.0, f_ratio)) / math.log(max(2.0, max_f + 1.0))
            bx = sp_x0 + max(0.0, min(1.0, xn)) * sp_w
            # Material damp tilts higher partials up (metal) or down (wood)
            slope = max(0.25, 1.0 - (k / max(1, vis_n)) * (0.65 - damp * 0.45))
            bh_k = max(4.0, sp_h * slope)
            c.create_line(bx, sp_bot, bx, sp_bot - bh_k, fill=accent, width=3)
            c.create_oval(bx - 2.5, sp_bot - bh_k - 2.5, bx + 2.5, sp_bot - bh_k + 2.5, fill="#ffffff", outline="")

        hdr = f"{RES_MODELS[m_idx].upper()}  {n_parts}P"
        c.create_text(sx0 + 8, mid_y0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - sx0) - 16, self._fs(0.84), bold=True))

        self._draw_bottom_grid(x0, mid_y1 + gap, x1, y1, "Model", accent)

    # --------------------------------------------------------------------------
    # TAB 3: BODY (Dual 2D Physics Pads: HitPos x Inharm & Decay x Material)
    # --------------------------------------------------------------------------
    def _draw_tab_body(self, x0, y0, x1, y1):
        c = self.widget_canvas
        p = self._rp()
        other = "b" if p == "a" else "a"
        accent = COL_RES_A if p == "a" else COL_RES_B
        other_col = COL_RES_B if p == "a" else COL_RES_A
        gap = 6

        # Row 1: RES A / B + ON/OFF + Bank Bar
        r1_h = 34
        left_w = (x1 - x0) * 0.36
        self._draw_res_selector(x0, y0, x0 + left_w, y0 + r1_h)
        self._draw_bank_bar(
            x0 + left_w + gap, y0, x1, y0 + r1_h,
            ["Decay/Mat", "Hit/Inh", "Pitch"],
            self.body_bank, accent, "body_bank",
        )

        # Row 2: Dual 2D Physics Pads
        gy0 = y0 + r1_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        hw = (x1 - x0 - gap) / 2
        lx1 = x0 + hw
        rx0 = lx1 + gap

        # Left Pad: HitPos (X) x Inharmonicity (Y) with vibrating string preview
        c.create_rectangle(x0, gy0, lx1, gy1, fill=COL_PANEL, outline=accent, width=1)
        pad = 12
        ax0, ax1 = x0 + pad, lx1 - pad
        ay0, ay1 = gy0 + 22, gy1 - pad
        aw, ah = max(10, ax1 - ax0), max(10, ay1 - ay0)
        mid_y = (ay0 + ay1) / 2
        c.create_line(ax0, mid_y, ax1, mid_y, fill=COL_GRID, dash=(2, 4))

        hit_n = self._norm(self._get_zctrl(f"{p}_hit"), f"{p}_hit", 0.5)
        inh_n = self._norm(self._get_zctrl(f"{p}_inharm"), f"{p}_inharm", 0.0)
        # Draw standing wave plucked at hit_n
        pts = []
        for i in range(49):
            t = i / 48.0
            env = math.sin(math.pi * t)
            y = env * (0.65 * math.sin(math.pi * t) + 0.35 * math.sin(2 * math.pi * t * (1.0 + inh_n * 2.0)))
            pts.extend([ax0 + t * aw, mid_y - y * (ah * 0.42)])
        c.create_line(pts, fill=accent, width=2.2)

        hx = ax0 + hit_n * aw
        hy = ay1 - inh_n * ah
        c.create_line(hx, ay0, hx, ay1, fill=accent, dash=(2, 3))
        c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
        h_txt = f"HIT:{self._fmt(self._get_zctrl(f'{p}_hit'), f'{p}_hit')}  INH:{self._fmt(self._get_zctrl(f'{p}_inharm'), f'{p}_inharm')}"
        c.create_text(x0 + 8, gy0 + 11, text=h_txt, anchor="w", fill=accent,
                      font=self._fit_font(h_txt, hw - 16, self._fs(0.82), bold=True))
        self.hitboxes.append((x0, gy0, lx1, gy1, "body_hit", {"p": p, "gx0": ax0, "gx1": ax1, "gy0": ay0, "gy1": ay1}))

        # Right Pad: Decay (X, log) x Material/Damp (Y, wood->metal)
        c.create_rectangle(rx0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)
        bx0, bx1 = rx0 + pad, x1 - pad
        by0, by1 = gy0 + 22, gy1 - pad
        bw, bh = max(10, bx1 - bx0), max(10, by1 - by0)
        c.create_line(bx0, (by0 + by1) / 2, bx1, (by0 + by1) / 2, fill=COL_GRID, dash=(2, 4))

        # Ghost other resonator handle
        od_n = self._norm(self._get_zctrl(f"{other}_decay"), f"{other}_decay", 0.5)
        om_n = self._norm(self._get_zctrl(f"{other}_damp"), f"{other}_damp", 0.5)
        ox, oy = bx0 + od_n * bw, by1 - om_n * bh
        c.create_oval(ox - 5, oy - 5, ox + 5, oy + 5, fill=COL_PANEL_HI, outline=other_col, width=1.5)

        dec_n = self._norm(self._get_zctrl(f"{p}_decay"), f"{p}_decay", 0.5)
        mat_n = self._norm(self._get_zctrl(f"{p}_damp"), f"{p}_damp", 0.5)
        # Draw exponential decay envelope curve
        dpts = []
        for i in range(41):
            t = i / 40.0
            tau = 0.12 + dec_n * 1.4
            amp = math.exp(-t / tau)
            dpts.extend([bx0 + t * bw, by1 - amp * bh * (0.35 + 0.65 * mat_n)])
        c.create_line(dpts, fill=accent, width=2.2)

        dx, dy = bx0 + dec_n * bw, by1 - mat_n * bh
        c.create_oval(dx - 8, dy - 8, dx + 8, dy + 8, fill=accent, outline="#ffffff", width=2)
        d_txt = f"DEC:{self._fmt(self._get_zctrl(f'{p}_decay'), f'{p}_decay')}  MAT:{self._fmt(self._get_zctrl(f'{p}_damp'), f'{p}_damp')}"
        c.create_text(rx0 + 8, gy0 + 11, text=d_txt, anchor="w", fill=accent,
                      font=self._fit_font(d_txt, hw - 16, self._fs(0.82), bold=True))
        self.hitboxes.append((rx0, gy0, x1, gy1, "body_decay", {"p": p, "gx0": bx0, "gx1": bx1, "gy0": by0, "gy1": by1}))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Body", accent)

    # --------------------------------------------------------------------------
    # TAB 4: MALLET (16 Mallet Types + 2D Stiffness x Resonance Pad)
    # --------------------------------------------------------------------------
    def _draw_tab_mallet(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Mallet"]
        gap = 6

        # Row 1: Encoder Bank Bar + Mallet Step Selector (◀ TYPE ▶)
        r1_h = 34
        left_w = (x1 - x0) * 0.48
        self._draw_bank_bar(
            x0, y0, x0 + left_w, y0 + r1_h,
            ["Mallet Core", "Tone & Vel"],
            self.mallet_bank, accent, "mallet_bank",
        )
        rx0 = x0 + left_w + gap
        bw = 42
        self._draw_pill(rx0, y0, rx0 + bw, y0 + r1_h, "◀", False, accent, "mallet_step", -1)
        self._draw_pill(x1 - bw, y0, x1, y0 + r1_h, "▶", False, accent, "mallet_step", 1)
        m_lbl = MALLET_TYPES[self._mallet_idx()][1]
        c.create_rectangle(rx0 + bw + gap, y0, x1 - bw - gap, y0 + r1_h,
                           fill=COL_PANEL_HI, outline=accent, width=1)
        c.create_text((rx0 + x1) / 2, y0 + r1_h / 2, text=m_lbl, fill=accent,
                      font=self._fit_font(m_lbl, max(20, (x1 - rx0) - 2 * bw - 2 * gap - 6), self._fs(0.9), bold=True))

        # Row 2: Quick 8 Popular Mallet Family Pills
        r2_y = y0 + r1_h + gap
        r2_h = 34
        quick_m = [(0, "Imp"), (12, "Clk1"), (15, "Clk4"), (18, "Blip"), (20, "Mtl1"), (22, "Wood"), (23, "Strk"), (24, "Prc1")]
        cur_m_val = MALLET_TYPES[self._mallet_idx()][0]
        sgap = 4
        qw = (x1 - x0 - sgap * (len(quick_m) - 1)) / len(quick_m)
        for i, (mval, lbl) in enumerate(quick_m):
            qx0 = x0 + i * (qw + sgap)
            self._draw_pill(qx0, r2_y, qx0 + qw, r2_y + r2_h, lbl,
                            cur_m_val == mval, accent, "mallet_val", mval)

        # Row 3: Interactive 2D Pad (Stiffness Hz x Resonance) with Impulse Transient Wave
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 14
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + 22, gy1 - pad
        gw, gh = max(10, gx1 - gx0), max(10, g_bot - g_top)
        mid_y = (g_top + g_bot) / 2
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        stiff_n = self._norm(self._get_zctrl("mallet_stiff"), "mallet_stiff", 0.45)
        res_n = self._norm(self._get_zctrl("mallet_res"), "mallet_res", 0.8)
        # Render damped transient impulse whose width & ring respond to Stiffness & Resonance
        pts = []
        n_pts = 96
        freq = 2.0 + stiff_n * 14.0
        decay = 3.0 + (1.0 - res_n) * 9.0
        for i in range(n_pts + 1):
            t = i / n_pts
            y = math.exp(-t * decay) * math.sin(2.0 * math.pi * freq * t)
            pts.extend([gx0 + t * gw, mid_y - y * (gh * 0.46)])
        c.create_line(pts, fill=accent, width=2.4)

        hx = gx0 + stiff_n * gw
        hy = g_bot - res_n * gh
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        hdr = f"MALLET {m_lbl.upper()}   STIFF:{self._fmt(self._get_zctrl('mallet_stiff'), 'mallet_stiff')}   RES:{self._fmt(self._get_zctrl('mallet_res'), 'mallet_res')}"
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))

        self.hitboxes.append((x0, gy0, x1, gy1, "mallet_xy", {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot}))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Mallet", accent)

    # --------------------------------------------------------------------------
    # TAB 5: NOISE (2D SVF Filter XY Pad + Interactive 2D ADSR with Tension)
    # --------------------------------------------------------------------------
    def _draw_tab_noise(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Noise"]
        gap = 6

        # Row 1: Encoder Bank Bar (left 62%) + LP/BP/HP Filter Mode Pills (right 38%)
        r1_h = 34
        left_w = (x1 - x0) * 0.62
        self._draw_bank_bar(
            x0, y0, x0 + left_w, y0 + r1_h,
            ["Filter", "ADSR", "Tension"],
            self.noise_bank, accent, "noise_bank",
        )
        rx0 = x0 + left_w + gap
        fmode = max(0, min(2, int(round(self._val(self._get_zctrl("noise_filter_mode"), 2)))))
        mw = (x1 - rx0 - 2 * 4) / 3
        for i, mlbl in enumerate(NOISE_FLT_MODES):
            mx0 = rx0 + i * (mw + 4)
            self._draw_pill(mx0, y0, mx0 + mw, y0 + r1_h, mlbl,
                            i == fmode, accent, "noise_fmode", i)

        # Row 2: Interactive 2D Graph (Filter XY in bank 0, ADSR+Tension in banks 1-2)
        gy0 = y0 + r1_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 14
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + 22, gy1 - pad
        gw, gh = max(10, gx1 - gx0), max(10, g_bot - g_top)

        if self.noise_bank == 0:
            fn = self._norm(self._get_zctrl("noise_filter_freq"), "noise_filter_freq", 0.5)
            qn = self._norm(self._get_zctrl("noise_filter_q"), "noise_filter_q", 0.0)
            zero_y = g_top + gh * 0.48
            c.create_line(gx0, zero_y, gx1, zero_y, fill=COL_GRID, dash=(2, 4))

            pts = []
            for i in range(61):
                xn = i / 60.0
                d = xn - fn
                if fmode == 0:    # LP
                    db = 0.0 if d <= 0 else -36.0 * (d / 0.25)
                elif fmode == 2:  # HP
                    db = 0.0 if d >= 0 else -36.0 * (-d / 0.25)
                else:             # BP
                    db = -30.0 * (abs(d) / 0.18)
                peak = qn * 16.0 * math.exp(-((d / 0.055) ** 2))
                y = max(g_top, min(g_bot, zero_y - ((db + peak) / 24.0) * (gh * 0.48)))
                pts.extend([gx0 + xn * gw, y])
            c.create_polygon([gx0, g_bot] + pts + [gx1, g_bot], fill="#16291b", outline="")
            c.create_line(pts, fill=accent, width=2.5)

            hx, hy = gx0 + fn * gw, g_bot - qn * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            hdr = f"NOISE {NOISE_FLT_MODES[fmode]}   FREQ:{self._fmt(self._get_zctrl('noise_filter_freq'), 'noise_filter_freq')}   {self._fmt(self._get_zctrl('noise_filter_q'), 'noise_filter_q')}"
            c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                          font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))
            self.hitboxes.append((x0, gy0, x1, gy1, "noise_flt_xy", {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot}))
        else:
            a = self._norm(self._get_zctrl("noise_att"), "noise_att", 0.0)
            d = self._norm(self._get_zctrl("noise_dec"), "noise_dec", 0.5)
            s = self._norm(self._get_zctrl("noise_sus"), "noise_sus", 0.0)
            r = self._norm(self._get_zctrl("noise_rel"), "noise_rel", 0.5)
            at = self._val(self._get_zctrl("noise_att_ten"), 0.4)
            dt = self._val(self._get_zctrl("noise_dec_ten"), 0.4)
            rt = self._val(self._get_zctrl("noise_rel_ten"), 0.4)

            xa = gx0 + max(0.03, a) * (gw * 0.28)
            xd = xa + max(0.03, d) * (gw * 0.28)
            xs = xd + gw * 0.16
            xr = min(gx1, xs + max(0.03, r) * (gw * 0.28))
            ys = g_bot - s * gh

            def exp_seg(x_s, y_s, x_e, y_e, tens):
                pw = 2.0 ** (tens * 1.8)
                out = []
                for k in range(1, 11):
                    t = k / 10.0
                    out.extend([x_s + (x_e - x_s) * t, y_s + (y_e - y_s) * (t ** pw)])
                return out

            pts = [gx0, g_bot] + exp_seg(gx0, g_bot, xa, g_top, -at) + exp_seg(xa, g_top, xd, ys, dt) + [xs, ys] + exp_seg(xs, ys, xr, g_bot, rt)
            c.create_polygon(pts + [gx0, g_bot], fill="#16291b", outline="")
            c.create_line(pts, fill=accent, width=2.5)
            for hx, hy in ((xa, g_top), (xd, ys), (xr, g_bot)):
                c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)

            hdr = (f"NOISE ENV  A:{self._fmt(self._get_zctrl('noise_att'), 'noise_att')}"
                   f"  D:{self._fmt(self._get_zctrl('noise_dec'), 'noise_dec')}"
                   f"  S:{int(round(s*100))}%  R:{self._fmt(self._get_zctrl('noise_rel'), 'noise_rel')}")
            c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                          font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))
            self.hitboxes.append((
                x0, gy0, x1, gy1, "noise_env",
                {"gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
                 "xa": xa, "xd": xd, "xs": xs, "xr": xr, "ys": ys},
            ))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Noise", accent)

    # --------------------------------------------------------------------------
    # TAB 6: VELMOD (Bipolar Interactive Velocity Modulation Bars)
    # --------------------------------------------------------------------------
    def _draw_tab_vel(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["VelMod"]
        gap = 6

        # Row 1: 5 Velocity Mod Banks
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Res A", "Res B", "Mallet", "Nse Flt", "Nse Env"],
            self.vel_bank, accent, "vel_bank",
        )

        # Row 2: Interactive Bipolar Vertical Faders for Active Velocity Bank
        gy0 = y0 + r1_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        vel_sets = [
            [("vel_a_decay", "Decay"), ("vel_a_hit", "Hit"), ("vel_a_damp", "Mat"), ("vel_a_tone", "Tone"), ("vel_a_inharm", "Inh")],
            [("vel_b_decay", "Decay"), ("vel_b_hit", "Hit"), ("vel_b_damp", "Mat"), ("vel_b_tone", "Tone"), ("vel_b_inharm", "Inh")],
            [("vel_mallet_mix", "MltMix"), ("vel_mallet_stiff", "Stiff"), ("vel_mallet_res", "MltRes"), ("vel_noise_mix", "NseMix")],
            [("vel_noise_res", "NseRes"), ("vel_noise_freq", "FltFrq"), ("vel_noise_q", "FltQ"), ("vel_a_inharm", "A Inh")],
            [("vel_noise_att", "Att"), ("vel_noise_dec", "Dec"), ("vel_noise_sus", "Sus"), ("vel_noise_rel", "Rel")],
        ]
        bars = vel_sets[self.vel_bank]
        bw = (x1 - x0 - gap * (len(bars) - 1)) / len(bars)
        for i, (key, lbl) in enumerate(bars):
            bx0 = x0 + i * (bw + gap)
            self._draw_vfader(bx0, gy0, bx0 + bw, gy1, key, lbl, accent, bipolar=True)

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "VelMod", accent)

    # --------------------------------------------------------------------------
    # ECO CPU Tamer (caps modal partials to 16 & enables voice reuse)
    # --------------------------------------------------------------------------
    def _toggle_eco(self):
        if not self.processor:
            return
        if self.eco_on:
            for key, orig_val in self._eco_backup.items():
                z = self._get_zctrl(key)
                if z is not None:
                    self._set_raw(z, orig_val)
            self._eco_backup.clear()
            self.eco_on = False
        else:
            self._eco_backup.clear()
            for pk in ("a_partials", "b_partials"):
                z = self._get_zctrl(pk)
                if z is not None:
                    cur = int(round(self._val(z, 3)))
                    self._eco_backup[pk] = cur
                    # Indices 3 (32) and 4 (64) are heavy -> cap to 2 (16 partials)
                    if cur in (3, 4):
                        self._set_raw(z, 2)
            z_rv = self._get_zctrl("reuse_voices")
            if z_rv is not None:
                self._eco_backup["reuse_voices"] = int(round(self._val(z_rv, 0)))
                self._set_raw(z_rv, 1)
            self.eco_on = True

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

        if kind == "eco":
            self._toggle_eco()
            self.last_snapshot = None
            self._draw()
            return

        if kind == "res_idx":
            if self.res_idx != payload:
                self.res_idx = payload
                self._live_swap_encoders(self.active_tab)
                self.last_snapshot = None
                self._draw()
            return

        if kind in ("couple_bank", "model_bank", "body_bank", "mallet_bank", "noise_bank", "vel_bank"):
            self._switch_subbank(kind, payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "res_model":
            self._set_raw(self._get_zctrl(f"{self._rp()}_model"), payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mallet_step":
            nxt = (self._mallet_idx() + payload) % len(MALLET_TYPES)
            self._set_raw(self._get_zctrl("mallet_type"), MALLET_TYPES[nxt][0])
            self.last_snapshot = None
            self._draw()
            return

        if kind == "mallet_val":
            self._set_raw(self._get_zctrl("mallet_type"), payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "noise_fmode":
            self._set_raw(self._get_zctrl("noise_filter_mode"), payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "cycle":
            self._cycle_enum(self._get_zctrl(payload), 1)
            self.last_snapshot = None
            self._draw()
            return

        if kind in ("body_hit", "body_decay", "mallet_xy", "noise_flt_xy"):
            now = time.monotonic()
            tap_id = (kind, payload.get("p"))
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                if kind == "body_hit":
                    p = payload["p"]
                    rkeys = (f"{p}_hit", f"{p}_inharm")
                elif kind == "body_decay":
                    p = payload["p"]
                    rkeys = (f"{p}_decay", f"{p}_damp")
                elif kind == "mallet_xy":
                    rkeys = ("mallet_stiff", "mallet_res")
                else:
                    rkeys = ("noise_filter_freq", "noise_filter_q")
                for rk in rkeys:
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            if kind == "body_hit":
                self._switch_subbank("body_bank", 1)
            elif kind == "body_decay":
                self._switch_subbank("body_bank", 0)
            self.drag_target = (kind, payload)
            self._apply_drag(event.x, event.y)
            return

        if kind == "noise_env":
            d_a = abs(event.x - payload["xa"])
            d_ds = math.hypot(event.x - payload["xd"], event.y - payload["ys"])
            d_r = abs(event.x - payload["xr"])
            node = "A" if (d_a <= d_ds and d_a <= d_r) else ("DS" if d_ds <= d_r else "R")
            now = time.monotonic()
            tap_id = ("noise_env", node)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                rkeys = ["noise_att"] if node == "A" else (["noise_dec", "noise_sus"] if node == "DS" else ["noise_rel"])
                for rk in rkeys:
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("noise_env", dict(payload, node=node))
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
                k = payload["key"]
                self._set_norm(self._get_zctrl(k), (ty1 - y) / (ty1 - ty0), k)
        elif kind == "hfader":
            tx0, tx1 = payload["tx0"], payload["tx1"]
            if tx1 > tx0:
                k = payload["key"]
                self._set_norm(self._get_zctrl(k), (x - tx0) / (tx1 - tx0), k)
        elif kind == "body_hit":
            p = payload["p"]
            gx0, gx1, gy0, gy1 = payload["gx0"], payload["gx1"], payload["gy0"], payload["gy1"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl(f"{p}_hit"), (x - gx0) / (gx1 - gx0), f"{p}_hit")
            if gy1 > gy0:
                self._set_norm(self._get_zctrl(f"{p}_inharm"), (gy1 - y) / (gy1 - gy0), f"{p}_inharm")
        elif kind == "body_decay":
            p = payload["p"]
            gx0, gx1, gy0, gy1 = payload["gx0"], payload["gx1"], payload["gy0"], payload["gy1"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl(f"{p}_decay"), (x - gx0) / (gx1 - gx0), f"{p}_decay")
            if gy1 > gy0:
                self._set_norm(self._get_zctrl(f"{p}_damp"), (gy1 - y) / (gy1 - gy0), f"{p}_damp")
        elif kind == "mallet_xy":
            gx0, gx1, gy0, gy1 = payload["gx0"], payload["gx1"], payload["gy0"], payload["gy1"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl("mallet_stiff"), (x - gx0) / (gx1 - gx0), "mallet_stiff")
            if gy1 > gy0:
                self._set_norm(self._get_zctrl("mallet_res"), (gy1 - y) / (gy1 - gy0), "mallet_res")
        elif kind == "noise_flt_xy":
            gx0, gx1, gy0, gy1 = payload["gx0"], payload["gx1"], payload["gy0"], payload["gy1"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl("noise_filter_freq"), (x - gx0) / (gx1 - gx0), "noise_filter_freq")
            if gy1 > gy0:
                self._set_norm(self._get_zctrl("noise_filter_q"), (gy1 - y) / (gy1 - gy0), "noise_filter_q")
        elif kind == "noise_env":
            gx0, gw = payload["gx0"], payload["gw"]
            g_top, g_bot = payload["g_top"], payload["g_bot"]
            seg_w = max(10.0, gw * 0.28)
            node = payload["node"]
            if node == "A":
                self._set_norm(self._get_zctrl("noise_att"), (x - gx0) / seg_w, "noise_att")
            elif node == "DS":
                self._set_norm(self._get_zctrl("noise_dec"), (x - payload["xa"]) / seg_w, "noise_dec")
                if g_bot > g_top:
                    self._set_norm(self._get_zctrl("noise_sus"), (g_bot - y) / (g_bot - g_top), "noise_sus")
            elif node == "R":
                self._set_norm(self._get_zctrl("noise_rel"), (x - payload["xs"]) / seg_w, "noise_rel")

        self.last_snapshot = None
        self._draw()
