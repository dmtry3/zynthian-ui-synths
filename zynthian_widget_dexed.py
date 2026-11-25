#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Dexed (DX7 FM Synth) Workstation Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces Dexed's ~155 raw LV2 parameters (~40 encoder pages) with 6 dynamic
# workstation tabs mapped 1-to-1 to Zynthian's 4 physical encoders + ECO toggle:
#   Algo | Osc/Tune | Op ENV | Scale | Pitch/LFO | Filter/Out   + ECO
#
# Features:
# - Live interactive diagram of all 32 authentic Yamaha DX7 algorithms (Carriers,
#   Modulators, modulation arrows, Feedback loop, tap to select, double-tap mute).
# - Real DX7 DSP scales & labels: Ratio (0.50x..31.00x * Fine) & Fixed Hz
#   (1Hz..9772Hz), Breakpoint MIDI notes (A-1..C8), -LIN/-EXP/+EXP/+LIN curves,
#   LFO waveforms (Tri/SawDn/SawUp/Sqr/Sin/S&H), Transpose (-24..+24st), Detune (-7..+7).
# - Interactive 2D visualizations:
#   * Algo: 32-algorithm routing diagram + 6-operator vertical level mixer
#   * Osc/Tune: live FM-modulated operator waveform scope + Ratio/Fixed readout
#   * Op ENV: 4-stage DX7 Rate/Level (R1-4 / L1-4) 2D draggable envelope graph
#   * Scale: Keyboard Level Scaling curve (A-1..C8) with draggable Breakpoint
#   * Pitch/LFO: live LFO wave with Delay/PMD/AMD + interactive 2D Pitch EG graph
#   * Filter/Out: interactive 2D SVF Filter XY pad (Cutoff/Resonance) + Master/Macros
# - Unified Design System (UI Synths): >=34px touch targets, 6px gaps, double-tap
#   reset on all sliders and 2D nodes, ~16 FPS dirty-checked Canvas rendering.
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

TABS = ["Algo", "Osc", "Env", "Scale", "LFO", "Filter"]
TAB_ACCENTS = {
    "Algo":   "#4dabf7",  # blue
    "Osc":    "#cc5de8",  # violet
    "Env":    "#51cf66",  # green
    "Scale":  "#ffd43b",  # yellow
    "LFO":    "#ff922b",  # orange
    "Filter": "#ff6b6b",  # coral
}
COL_CARRIER = "#4dabf7"
COL_MOD = "#cc5de8"

# ------------------------------------------------------------------------------
# Authentic Yamaha DX7 / Dexed Tables & Scales
# ------------------------------------------------------------------------------
ENGINE_NAMES = ["Modern", "Mark I", "OPL"]
POLY_MODES = ["Poly", "Mono"]
OSC_MODES = ["Ratio", "Fixed"]
LFO_WAVES = ["Tri", "SawD", "SawU", "Sqr", "Sin", "S&H"]
SCALE_CURVES = ["-LIN", "-EXP", "+EXP", "+LIN"]
TOGGLE_OFF_ON = ["Off", "On"]
VOICE_PRESETS = (4, 6, 8, 12, 16, 24, 32)
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# 32 Authentic Yamaha DX7 Algorithms:
# alg_num (1..32): (carriers_tuple, [(src, dst), ...], feedback_op)
DX7_ALGOS = {
    1:  ((1, 3),             [(6, 5), (5, 4), (4, 3), (2, 1)],                 6),
    2:  ((1, 3),             [(6, 5), (5, 4), (4, 3), (2, 1)],                 2),
    3:  ((1, 4),             [(6, 5), (5, 4), (3, 2), (2, 1)],                 6),
    4:  ((1, 4),             [(6, 5), (5, 4), (3, 2), (2, 1)],                 6),
    5:  ((1, 3, 5),          [(6, 5), (4, 3), (2, 1)],                         6),
    6:  ((1, 3, 5),          [(6, 5), (4, 3), (2, 1)],                         6),
    7:  ((1, 3),             [(6, 5), (5, 3), (4, 3), (2, 1)],                 6),
    8:  ((1, 3),             [(6, 5), (5, 3), (4, 3), (2, 1)],                 4),
    9:  ((1, 3),             [(6, 5), (5, 3), (4, 3), (2, 1)],                 2),
    10: ((1, 4),             [(6, 4), (5, 4), (3, 2), (2, 1)],                 3),
    11: ((1, 4),             [(6, 4), (5, 4), (3, 2), (2, 1)],                 6),
    12: ((1, 3),             [(6, 3), (5, 3), (4, 3), (2, 1)],                 2),
    13: ((1, 3),             [(6, 3), (5, 3), (4, 3), (2, 1)],                 6),
    14: ((1, 3),             [(6, 4), (5, 4), (4, 3), (2, 1)],                 6),
    15: ((1, 3),             [(6, 4), (5, 4), (4, 3), (2, 1)],                 2),
    16: ((1,),               [(6, 5), (5, 1), (4, 3), (3, 1), (2, 1)],         6),
    17: ((1,),               [(6, 5), (5, 1), (4, 3), (3, 1), (2, 1)],         2),
    18: ((1,),               [(6, 5), (5, 4), (4, 1), (3, 1), (2, 1)],         3),
    19: ((1, 4, 5),          [(6, 5), (6, 4), (3, 2), (2, 1)],                 6),
    20: ((1, 2, 4),          [(6, 4), (5, 4), (3, 2), (3, 1)],                 3),
    21: ((1, 2, 4, 5),       [(6, 5), (6, 4), (3, 2), (3, 1)],                 3),
    22: ((1, 3, 4, 5),       [(6, 5), (6, 4), (6, 3), (2, 1)],                 6),
    23: ((1, 2, 4, 5),       [(6, 5), (6, 4), (3, 2)],                         6),
    24: ((1, 2, 3, 4, 5),    [(6, 5), (6, 4), (6, 3)],                         6),
    25: ((1, 2, 3, 4, 5),    [(6, 5), (6, 4)],                                 6),
    26: ((1, 2, 4),          [(6, 4), (5, 4), (3, 2)],                         6),
    27: ((1, 2, 4),          [(6, 4), (5, 4), (3, 2)],                         3),
    28: ((1, 3, 6),          [(5, 4), (4, 3), (2, 1)],                         5),
    29: ((1, 2, 3, 5),       [(6, 5), (4, 3)],                                 6),
    30: ((1, 2, 3, 6),       [(5, 4), (4, 3)],                                 5),
    31: ((1, 2, 3, 4, 5),    [(6, 5)],                                         6),
    32: ((1, 2, 3, 4, 5, 6), [],                                               6),
}


def _norm_key(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def dx7_breakpoint_note(val):
    """DX7 Breakpoint 0..99 -> note name A-1..C8 (39 = C3)."""
    midi = 21 + max(0, min(99, int(round(val))))  # 21 = A0/A-1 in DX7 convention
    note = NOTE_NAMES[midi % 12]
    octv = (midi // 12) - 2  # DX7 displays C3 at val=39 (midi 60 -> 60//12 - 2 = 3)
    return f"{note}{octv}"


def dx7_op_freq_text(mode, coarse, fine):
    """Compute authentic Yamaha DX7 operator frequency string (Ratio or Fixed Hz)."""
    c = max(0, min(31, int(round(coarse))))
    f = max(0, min(99, int(round(fine))))
    if int(round(mode)) == 0:
        base = 0.5 if c == 0 else float(c)
        ratio = base * (1.0 + f / 100.0)
        return f"{ratio:.2f}x"
    exp = (c % 4) + (f / 100.0)
    hz = 10.0 ** exp
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}kHz"
    return f"{hz:.1f}Hz"


def dx7_svf_hz(norm):
    """Approximate Dexed SVF filter cutoff 0..1 -> 20Hz..20kHz log scale."""
    return 20.0 * (1000.0 ** max(0.0, min(1.0, float(norm))))


def fmt_hz(hz):
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}k" if hz < 10000.0 else f"{hz / 1000.0:.1f}k"
    return f"{int(round(hz))}Hz"


def _compute_algo_layout(alg_num):
    """Compute clean (col, row) positions for OP 1..6 in the given DX7 algorithm.
    Row 0 is bottom (Carriers); higher rows are Modulators stacked above their targets.
    """
    carriers, mods, _ = DX7_ALGOS.get(alg_num, DX7_ALGOS[1])
    # Compute depth (row) from carriers upward
    depth = {op: 0 for op in carriers}
    for _ in range(6):
        for src, dst in mods:
            if dst in depth:
                depth[src] = max(depth.get(src, 0), depth[dst] + 1)
    for op in range(1, 7):
        depth.setdefault(op, 0)

    # Group by row and assign horizontal slots cleanly
    rows = {}
    for op in range(1, 7):
        rows.setdefault(depth[op], []).append(op)
    max_row = max(rows.keys()) if rows else 0

    # Assign carrier columns left-to-right (OP1 on left -> OP6 on right)
    pos = {}
    c_sorted = sorted(carriers)
    n_c = max(1, len(c_sorted))
    for i, op in enumerate(c_sorted):
        pos[op] = ((i + 0.5) / n_c, 0)

    # Place modulators above their target(s)
    for r in range(1, max_row + 1):
        ops_r = sorted(rows.get(r, []))
        # Desired x is average of targets' x
        desired = []
        for op in ops_r:
            tgts = [dst for src, dst in mods if src == op and dst in pos]
            cx = sum(pos[t][0] for t in tgts) / len(tgts) if tgts else 0.5
            desired.append((cx, op))
        desired.sort()
        # Spread any overlapping nodes in the same row
        min_dx = 1.0 / max(len(ops_r) + 0.4, 3.2)
        xs = [d[0] for d in desired]
        for k in range(1, len(xs)):
            if xs[k] - xs[k - 1] < min_dx:
                xs[k] = xs[k - 1] + min_dx
        if xs:
            if xs[-1] > 0.90:
                shift = xs[-1] - 0.90
                xs = [max(0.10, x - shift) for x in xs]
            if xs[0] < 0.10:
                shift = 0.10 - xs[0]
                xs = [min(0.90, x + shift) for x in xs]
        for x_val, (_, op) in zip(xs, desired):
            pos[op] = (x_val, r)

    return pos, max_row


# ------------------------------------------------------------------------------
# Dexed Workstation Widget Class
# ------------------------------------------------------------------------------
class zynthian_widget_dexed(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)

        self.active_tab = "Algo"
        self.algo_bank = 0      # 0=Algo/Fbk, 1=OP 1-4 Lvl, 2=OP 5-6/Flt
        self.op_idx = 0         # 0..5 -> OP1..OP6
        self.osc_bank = 0       # 0=Freq/Lvl, 1=Mode/Sens
        self.env_bank = 0       # 0=Rates R1-4, 1=Levels L1-4, 2=Scale/Vel
        self.scale_bank = 0     # 0=Brk/Depths, 1=Curves/Sens
        self.lfo_bank = 0       # 0=LFO Core, 1=LFO Mod, 2=Pitch R1-4, 3=Pitch L1-4
        self.flt_bank = 0       # 0=Filter/Out, 1=Algo/Global

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

    def _configure_zctrl_enum(self, z, labels, ticks):
        """Attach readable enum labels while preserving Dexed's real native LV2 range."""
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
        z.value = max(z.value_min, min(z.value_max, int(round(cur_val)) if z.is_integer else cur_val))

    def _enhance_all_zctrls(self):
        # Prevent Zynthian's generic built-in filter/envelope widgets from hijacking
        # our custom Dexed workstation widget when switching to Filter or Env tabs!
        if self.processor:
            for z in self.processor.controllers_dict.values():
                for attr in ("filter", "envelope"):
                    if hasattr(z, attr):
                        try:
                            delattr(z, attr)
                        except Exception:
                            pass
        self._configure_zctrl_enum(self._get_zctrl("engine"), ENGINE_NAMES, [0, 1, 2])
        self._configure_zctrl_enum(self._get_zctrl("polymono"), POLY_MODES, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("oscillator_sync"), TOGGLE_OFF_ON, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("lfo_sync"), TOGGLE_OFF_ON, [0, 1])
        self._configure_zctrl_enum(self._get_zctrl("lfo_waveform"), LFO_WAVES, list(range(6)))
        self._configure_zctrl_enum(
            self._get_zctrl("algorithm_num"),
            [f"Alg {i}" for i in range(1, 33)],
            list(range(1, 33)),
        )
        self._configure_zctrl_enum(
            self._get_zctrl("transpose"),
            [f"{i - 24:+d}st" for i in range(49)],
            list(range(49)),
        )
        for oi in range(1, 7):
            self._configure_zctrl_enum(self._get_zctrl(f"op{oi}_enable"), TOGGLE_OFF_ON, [0, 1])
            self._configure_zctrl_enum(self._get_zctrl(f"op{oi}_osc_mode"), OSC_MODES, [0, 1])
            self._configure_zctrl_enum(self._get_zctrl(f"op{oi}_kbd_lev_scl_lft_curve"), SCALE_CURVES, [0, 1, 2, 3])
            self._configure_zctrl_enum(self._get_zctrl(f"op{oi}_kbd_lev_scl_rht_curve"), SCALE_CURVES, [0, 1, 2, 3])
            self._configure_zctrl_enum(
                self._get_zctrl(f"op{oi}_kbd_lev_scl_brk_pt"),
                [dx7_breakpoint_note(i) for i in range(100)],
                list(range(100)),
            )

    # --------------------------------------------------------------------------
    # Dynamic 4-Encoder Page Mapping (6 Tabs, 2-Level Sub-Banks)
    # --------------------------------------------------------------------------
    def _tab_items(self, tab_name):
        oi = self.op_idx + 1

        if tab_name == "Algo":
            if self.algo_bank == 0:
                return [
                    ("algorithm_num", "Algorithm"),
                    ("feedback",      "Feedback"),
                    ("transpose",     "Transpose"),
                    ("master_tune",   "MasterTune"),
                ]
            if self.algo_bank == 1:
                return [
                    ("op1_operator_output_level", "OP1 Level"),
                    ("op2_operator_output_level", "OP2 Level"),
                    ("op3_operator_output_level", "OP3 Level"),
                    ("op4_operator_output_level", "OP4 Level"),
                ]
            return [
                ("op5_operator_output_level", "OP5 Level"),
                ("op6_operator_output_level", "OP6 Level"),
                ("cutoff",                    "Cutoff"),
                ("resonance",                 "Resonance"),
            ]

        if tab_name == "Osc":
            if self.osc_bank == 0:
                return [
                    (f"op{oi}_operator_output_level", f"OP{oi} Level"),
                    (f"op{oi}_osc_freq_coarse",       f"OP{oi} Coarse"),
                    (f"op{oi}_osc_freq_fine",         f"OP{oi} Fine"),
                    (f"op{oi}_osc_detune",            f"OP{oi} Detune"),
                ]
            return [
                (f"op{oi}_osc_mode",            f"OP{oi} Mode"),
                (f"op{oi}_key_vel_sensitivity", f"OP{oi} VelSns"),
                (f"op{oi}_amp_mod_sensitivity", f"OP{oi} AmpMod"),
                ("oscillator_sync",             "Key Sync"),
            ]

        if tab_name == "Env":
            if self.env_bank == 0:
                return [
                    (f"op{oi}_eg_rate_1", f"OP{oi} Rate 1"),
                    (f"op{oi}_eg_rate_2", f"OP{oi} Rate 2"),
                    (f"op{oi}_eg_rate_3", f"OP{oi} Rate 3"),
                    (f"op{oi}_eg_rate_4", f"OP{oi} Rate 4"),
                ]
            if self.env_bank == 1:
                return [
                    (f"op{oi}_eg_level_1", f"OP{oi} Level 1"),
                    (f"op{oi}_eg_level_2", f"OP{oi} Level 2"),
                    (f"op{oi}_eg_level_3", f"OP{oi} Level 3"),
                    (f"op{oi}_eg_level_4", f"OP{oi} Level 4"),
                ]
            return [
                (f"op{oi}_kbd_rate_scaling",      f"OP{oi} RateScl"),
                (f"op{oi}_key_vel_sensitivity",   f"OP{oi} VelSns"),
                (f"op{oi}_amp_mod_sensitivity",   f"OP{oi} AmpMod"),
                (f"op{oi}_operator_output_level", f"OP{oi} Level"),
            ]

        if tab_name == "Scale":
            if self.scale_bank == 0:
                return [
                    (f"op{oi}_kbd_lev_scl_brk_pt",    f"OP{oi} BreakPt"),
                    (f"op{oi}_kbd_lev_scl_lft_depth", f"OP{oi} L Depth"),
                    (f"op{oi}_kbd_lev_scl_rht_depth", f"OP{oi} R Depth"),
                    (f"op{oi}_kbd_rate_scaling",      f"OP{oi} RateScl"),
                ]
            return [
                (f"op{oi}_kbd_lev_scl_lft_curve", f"OP{oi} L Curve"),
                (f"op{oi}_kbd_lev_scl_rht_curve", f"OP{oi} R Curve"),
                (f"op{oi}_key_vel_sensitivity",   f"OP{oi} VelSns"),
                (f"op{oi}_operator_output_level", f"OP{oi} Level"),
            ]

        if tab_name == "LFO":
            if self.lfo_bank == 0:
                return [
                    ("lfo_speed",           "LFO Speed"),
                    ("lfo_delay",           "LFO Delay"),
                    ("lfo_pitch_mod_depth", "Pitch Mod"),
                    ("lfo_amp_mod_depth",   "Amp Mod"),
                ]
            if self.lfo_bank == 1:
                return [
                    ("lfo_waveform",          "LFO Wave"),
                    ("lfo_sync",              "LFO Sync"),
                    ("pitch_mod_sensitivity", "Pitch Sens"),
                    ("transpose",             "Transpose"),
                ]
            if self.lfo_bank == 2:
                return [
                    ("pitch_eg_rate_1", "Pitch R1"),
                    ("pitch_eg_rate_2", "Pitch R2"),
                    ("pitch_eg_rate_3", "Pitch R3"),
                    ("pitch_eg_rate_4", "Pitch R4"),
                ]
            return [
                ("pitch_eg_level_1", "Pitch L1"),
                ("pitch_eg_level_2", "Pitch L2"),
                ("pitch_eg_level_3", "Pitch L3"),
                ("pitch_eg_level_4", "Pitch L4"),
            ]

        # Filter/Out
        if self.flt_bank == 0:
            return [
                ("cutoff",    "Cutoff"),
                ("resonance", "Resonance"),
                ("output",    "Master Out"),
                ("feedback",  "Feedback"),
            ]
        return [
            ("algorithm_num",    "Algorithm"),
            ("engine",           "Engine"),
            ("number_of_voices", "Voices"),
            ("pitch_bend_range", "PB Range"),
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
            logging.debug(f"Dexed widget: live swap error => {e}")

    def _sync_zyngui_list(self, target_tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page_by_title(target_tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Dexed widget: sync list error => {e}")

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
    # Native-Range Value Helpers (Dexed uses real DX7 integer & float port ranges)
    # --------------------------------------------------------------------------
    @staticmethod
    def _val(zctrl, default=0.0):
        if zctrl is None:
            return default
        try:
            return float(zctrl.get_value())
        except Exception:
            return default

    @staticmethod
    def _norm(zctrl, default=0.0):
        if zctrl is None:
            return default
        try:
            v = float(zctrl.get_value())
            vmin = float(getattr(zctrl, "value_min", 0.0))
            vmax = float(getattr(zctrl, "value_max", 1.0))
            span = vmax - vmin
            if span <= 0.0:
                return default
            return max(0.0, min(1.0, (v - vmin) / span))
        except Exception:
            return default

    @staticmethod
    def _set_norm(zctrl, norm_val):
        if zctrl is None:
            return
        n = max(0.0, min(1.0, float(norm_val)))
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
        vmin = getattr(zctrl, "value_min", 0)
        vmax = getattr(zctrl, "value_max", 1)
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
            idx = zctrl.get_value2index() or 0
            new_idx = (idx + step) % len(ticks)
            zctrl.set_value(ticks[new_idx], send=True)
            return
        vmin = int(round(getattr(zctrl, "value_min", 0)))
        vmax = int(round(getattr(zctrl, "value_max", 1)))
        if vmax > vmin:
            cur = int(round(zynthian_widget_dexed._val(zctrl, vmin)))
            nxt = vmin + ((cur - vmin + step) % (vmax - vmin + 1))
            zctrl.set_value(nxt, send=True)

    def _fmt(self, zctrl, key=None):
        if zctrl is None:
            return "--"
        if key == "cutoff":
            return fmt_hz(dx7_svf_hz(self._norm(zctrl, 1.0)))
        if key == "resonance":
            return f"{int(round(self._norm(zctrl, 0.0) * 100))}%"
        if key == "output":
            return f"{int(round(self._val(zctrl, 1.0) * 100))}%"
        if key == "master_tune":
            return f"{self._val(zctrl, 0.0) * 100.0:+.0f}ct"
        if key == "number_of_voices":
            return f"{int(round(self._val(zctrl, 16)))}v"
        if key and key.endswith("_osc_detune"):
            return f"{int(round(self._val(zctrl, 0))):+d}"
        try:
            if getattr(zctrl, "labels", None):
                return str(zctrl.get_value2label())
        except Exception:
            pass
        v = self._val(zctrl, 0.0)
        if getattr(zctrl, "is_integer", False):
            return str(int(round(v)))
        return f"{v:.2f}"

    def _alg_num(self):
        return max(1, min(32, int(round(self._val(self._get_zctrl("algorithm_num"), 1)))))

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
        oi = self.op_idx + 1
        if self.active_tab == "Algo":
            keys += [
                "algorithm_num", "feedback", "oscillator_sync", "transpose", "polymono", "engine",
                "number_of_voices",
            ] + [f"op{i}_operator_output_level" for i in range(1, 7)] + [f"op{i}_enable" for i in range(1, 7)]
        elif self.active_tab == "Osc":
            keys += [
                "algorithm_num", "feedback",
                f"op{oi}_enable", f"op{oi}_osc_mode", f"op{oi}_osc_freq_coarse",
                f"op{oi}_osc_freq_fine", f"op{oi}_osc_detune", f"op{oi}_operator_output_level",
            ] + [f"op{i}_enable" for i in range(1, 7)]
        elif self.active_tab == "Env":
            keys += [f"op{oi}_eg_rate_{k}" for k in range(1, 5)] + [f"op{oi}_eg_level_{k}" for k in range(1, 5)]
            keys += [f"op{i}_enable" for i in range(1, 7)]
        elif self.active_tab == "Scale":
            keys += [
                f"op{oi}_kbd_lev_scl_brk_pt", f"op{oi}_kbd_lev_scl_lft_depth",
                f"op{oi}_kbd_lev_scl_rht_depth", f"op{oi}_kbd_lev_scl_lft_curve",
                f"op{oi}_kbd_lev_scl_rht_curve", f"op{oi}_kbd_rate_scaling",
            ] + [f"op{i}_enable" for i in range(1, 7)]
        elif self.active_tab == "LFO":
            keys += [
                "lfo_speed", "lfo_delay", "lfo_pitch_mod_depth", "lfo_amp_mod_depth",
                "lfo_sync", "lfo_waveform", "pitch_mod_sensitivity",
            ] + [f"pitch_eg_rate_{k}" for k in range(1, 5)] + [f"pitch_eg_level_{k}" for k in range(1, 5)]
        elif self.active_tab == "Filter":
            keys += [
                "cutoff", "resonance", "output", "feedback", "algorithm_num",
                "engine", "number_of_voices", "polymono",
            ] + [f"op{i}_enable" for i in range(1, 7)]
        return keys

    def _state_snapshot(self):
        vals = [
            self.active_tab, self.algo_bank, self.op_idx, self.osc_bank,
            self.env_bank, self.scale_bank, self.lfo_bank, self.flt_bank,
            self.eco_on, self.width, self.height,
        ]
        for k in self._watched_keys():
            vals.append(round(self._val(self._get_zctrl(k), -999.0), 3))
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
    # Unified Drawing Primitives (UI Synths Design System)
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
        """Return a font that guarantees text fits inside max_w pixels."""
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
        norm = self._norm(z)

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
        norm = self._norm(z)

        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        pad = 4
        lbl_h = 18
        val_h = 16
        tx0, tx1 = x0 + pad, x1 - pad
        ty0 = y0 + lbl_h + 2
        ty1 = y1 - val_h - 3
        max_w = max(12, (x1 - x0) - 4)
        val_txt = self._fmt(z, key)[:6]

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

    def _draw_op_selector(self, x0, y0, x1, y1, accent):
        """Draw OP 1..6 selector row with Carrier/Modulator badge & enabled indicator."""
        carriers, _, _ = DX7_ALGOS.get(self._alg_num(), DX7_ALGOS[1])
        gap = 6
        ow = (x1 - x0 - gap * 5) / 6
        for i in range(6):
            op = i + 1
            ox0 = x0 + i * (ow + gap)
            is_on = self._val(self._get_zctrl(f"op{op}_enable"), 1) >= 0.5
            role = "C" if op in carriers else "M"
            txt = f"{'●' if is_on else ''}{op}{role}"
            col = COL_CARRIER if op in carriers else accent
            self._draw_pill(ox0, y0, ox0 + ow, y1, txt, i == self.op_idx, col, "op_idx", i)

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

        if self.active_tab == "Algo":
            self._draw_tab_algo(bx0, by0, bx1, by1)
        elif self.active_tab == "Osc":
            self._draw_tab_osc(bx0, by0, bx1, by1)
        elif self.active_tab == "Env":
            self._draw_tab_env(bx0, by0, bx1, by1)
        elif self.active_tab == "Scale":
            self._draw_tab_scale(bx0, by0, bx1, by1)
        elif self.active_tab == "LFO":
            self._draw_tab_lfo(bx0, by0, bx1, by1)
        elif self.active_tab == "Filter":
            self._draw_tab_filter(bx0, by0, bx1, by1)

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

        # ECO voice-cap button
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
    # TAB 1: ALGO (32-Algorithm Interactive Diagram + 6-Op Level Mixer)
    # --------------------------------------------------------------------------
    def _draw_tab_algo(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Algo"]
        gap = 6

        # Row 1: Quick DX7 Performance & Engine Tiles
        tile_h = 38
        tiles = [
            ("Engine",  "engine",           "cycle"),
            ("Voices",  "number_of_voices", "voice_cycle"),
            ("Mode",    "polymono",         "cycle"),
            ("KeySync", "oscillator_sync",  "cycle"),
            ("Transp",  "transpose",        "bank_algo"),
            ("Feedbk",  "feedback",         "cycle"),
        ]
        tw = (x1 - x0 - gap * (len(tiles) - 1)) / len(tiles)
        for i, (lbl, key, hk) in enumerate(tiles):
            tx0 = x0 + i * (tw + gap)
            z = self._get_zctrl(key)
            self._draw_pill(tx0, y0, tx0 + tw, y0 + tile_h, lbl, False, accent,
                            hk, key, subtext=self._fmt(z, key)[:8])

        # Row 2: Encoder Bank Bar
        by0 = y0 + tile_h + gap
        bh = 34
        self._draw_bank_bar(
            x0, by0, x1, by0 + bh,
            ["Algo / Fbk", "OP 1-4 Lvl", "OP 5-6 / Flt"],
            self.algo_bank, accent, "algo_bank",
        )

        # Row 3: Interactive Algorithm Diagram (left 54%) + 6-Op Level Mixer (right 46%)
        my0 = by0 + bh + gap
        left_w = int((x1 - x0) * 0.54)
        lx1 = x0 + left_w
        rx0 = lx1 + gap

        # Left: Algorithm Selector Strip (◀ ALG N/32 ▶) + Routing Canvas
        alg = self._alg_num()
        nav_h = 34
        btn_w = 44
        self._draw_pill(x0, my0, x0 + btn_w, my0 + nav_h, "◀", False, accent, "alg_step", -1)
        self._draw_pill(lx1 - btn_w, my0, lx1, my0 + nav_h, "▶", False, accent, "alg_step", 1)
        fb_val = int(round(self._val(self._get_zctrl("feedback"), 0)))
        alg_txt = f"ALG {alg:02d}/32  FB:{fb_val}"
        mid_w = max(20, (lx1 - btn_w - gap) - (x0 + btn_w + gap) - 8)
        c.create_rectangle(x0 + btn_w + gap, my0, lx1 - btn_w - gap, my0 + nav_h,
                           fill=COL_PANEL_HI, outline=accent, width=1)
        c.create_text((x0 + lx1) / 2, my0 + nav_h / 2,
                      text=alg_txt,
                      fill=accent, font=self._fit_font(alg_txt, mid_w, self._fs(0.9), bold=True))

        dg_y0 = my0 + nav_h + gap
        c.create_rectangle(x0, dg_y0, lx1, y1, fill=COL_PANEL, outline=accent, width=1)
        self._draw_algo_diagram(x0, dg_y0, lx1, y1, alg)

        # Right: 6 Vertical Operator Level Faders
        fw = (x1 - rx0 - gap * 5) / 6
        carriers, _, _ = DX7_ALGOS.get(alg, DX7_ALGOS[1])
        for i in range(6):
            op = i + 1
            fx0 = rx0 + i * (fw + gap)
            is_on = self._val(self._get_zctrl(f"op{op}_enable"), 1) >= 0.5
            col = "#555566" if not is_on else (COL_CARRIER if op in carriers else COL_MOD)
            b_idx = 1 if op <= 4 else 2
            self._draw_vfader(
                fx0, my0, fx0 + fw, y1,
                f"op{op}_operator_output_level", f"OP{op}",
                col, bank_kind="algo_bank", bank_idx=b_idx,
            )

    def _draw_algo_diagram(self, x0, y0, x1, y1, alg):
        c = self.widget_canvas
        carriers, mods, fb_op = DX7_ALGOS.get(alg, DX7_ALGOS[1])
        pos, max_row = _compute_algo_layout(alg)

        pad_x, pad_y = 14, 14
        gw = max(20, (x1 - x0) - 2 * pad_x)
        gh = max(20, (y1 - y0) - 2 * pad_y - 12)
        bw = min(44, max(30, gw / 6.2))
        bh = min(34, max(24, gh / max(max_row + 1.4, 2.5)))

        coords = {}
        for op, (nx, row) in pos.items():
            cx = x0 + pad_x + nx * gw
            if max_row == 0:
                cy = (y0 + y1) / 2
            else:
                cy = (y1 - pad_y - 10 - bh / 2) - (row / max_row) * max(10, gh - bh)
            coords[op] = (cx, cy)

        # Output bus line under carriers + C/M legend
        bus_y = y1 - 10
        c.create_line(x0 + 12, bus_y, x1 - 12, bus_y, fill=COL_CARRIER, width=2.4)
        c.create_text(x0 + 10, y0 + 8, text="● C=Carrier  ● M=Mod", anchor="w",
                      fill=COL_DIM, font=self._font(self._fs(0.70), bold=True))
        op_on = {op: (self._val(self._get_zctrl(f"op{op}_enable"), 1) >= 0.5) for op in range(1, 7)}
        op_lvl = {op: int(round(self._val(self._get_zctrl(f"op{op}_operator_output_level"), 99))) for op in range(1, 7)}

        for op in carriers:
            cx, cy = coords[op]
            active_c = op_on[op] and op_lvl[op] > 0
            c.create_line(cx, cy + bh / 2, cx, bus_y,
                          fill=COL_CARRIER if active_c else COL_BORDER,
                          width=3.0 if active_c else 1.4,
                          dash=() if active_c else (2, 3))

        # Modulation arrows (src -> dst): bright active flow vs muted dashed link
        for src, dst in mods:
            sx, sy = coords[src]
            dx, dy = coords[dst]
            active_m = op_on[src] and op_lvl[src] > 0 and op_on[dst]
            c.create_line(sx, sy + bh / 2, dx, dy - bh / 2,
                          fill="#74c0fc" if active_m else "#45495c",
                          width=2.6 if active_m else 1.3,
                          dash=() if active_m else (2, 3),
                          arrow=tkinter.LAST)

        # Feedback loop arc on fb_op
        if fb_op in coords:
            fx, fy = coords[fb_op]
            fb_val = int(round(self._val(self._get_zctrl("feedback"), 0)))
            fb_active = fb_val > 0 and op_on[fb_op] and op_lvl[fb_op] > 0
            fb_col = "#ff922b" if fb_active else COL_DIM
            c.create_line(
                fx + bw / 2, fy,
                fx + bw / 2 + 10, fy,
                fx + bw / 2 + 10, fy - bh / 2 - 7,
                fx, fy - bh / 2 - 7,
                fx, fy - bh / 2,
                fill=fb_col, width=2.4 if fb_active else 1, arrow=tkinter.LAST,
            )

        # Operator nodes (interactive hitboxes with Carrier/Modulator role badge!)
        for op in range(1, 7):
            cx, cy = coords[op]
            bx0, by0, bx1, by1 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
            is_c = op in carriers
            is_on = op_on[op]
            sel = (op - 1 == self.op_idx)
            lvl = op_lvl[op]
            base_col = COL_CARRIER if is_c else COL_MOD
            fill = base_col if sel else (("#183324" if is_c else "#192638") if (is_on and lvl > 0) else COL_BG)
            outline = "#ffffff" if sel else (base_col if is_on else COL_BORDER)
            c.create_rectangle(bx0, by0, bx1, by1, fill=fill, outline=outline, width=2.4 if (sel or (is_on and lvl > 0)) else 1)
            fg = "#0d0e12" if sel else (COL_TEXT if is_on else COL_DIM)
            role = "C" if is_c else "M"
            c.create_text(cx, cy - bh * 0.18, text=f"{op}{role}", fill=fg, font=self._font(self._fs(0.84), bold=True))
            c.create_text(cx, cy + bh * 0.24, text=f"{lvl}" if is_on else "OFF",
                          fill=fg if sel else (base_col if is_on else COL_DIM),
                          font=self._font(self._fs(0.70), bold=True))
            self.hitboxes.append((bx0, by0, bx1, by1, "algo_op", op - 1))

    # --------------------------------------------------------------------------
    # TAB 2: OSC / TUNE (OP 1..6 Frequency Ratio / Fixed Hz + Live FM Scope)
    # --------------------------------------------------------------------------
    def _draw_tab_osc(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Osc"]
        oi = self.op_idx + 1
        gap = 6

        # Row 1: OP 1..6 selector
        r1_h = 34
        self._draw_op_selector(x0, y0, x1, y0 + r1_h, accent)

        # Row 2: Power + Ratio/Fixed Mode + Encoder Bank Bar
        r2_y = y0 + r1_h + gap
        r2_h = 34
        is_on = self._val(self._get_zctrl(f"op{oi}_enable"), 1) >= 0.5
        mode = int(round(self._val(self._get_zctrl(f"op{oi}_osc_mode"), 0)))
        pw_w = 72
        md_w = 78
        self._draw_pill(x0, r2_y, x0 + pw_w, r2_y + r2_h,
                        f"OP{oi} ON" if is_on else f"OP{oi} OFF",
                        is_on, "#51cf66", "cycle", f"op{oi}_enable")
        self._draw_pill(x0 + pw_w + gap, r2_y, x0 + pw_w + gap + md_w, r2_y + r2_h,
                        "FIXED" if mode == 1 else "RATIO",
                        mode == 1, accent, "cycle", f"op{oi}_osc_mode")
        self._draw_bank_bar(
            x0 + pw_w + md_w + 2 * gap, r2_y, x1, r2_y + r2_h,
            ["Lvl & Tune", "Mode & Sens"],
            self.osc_bank, accent, "osc_bank",
        )

        # Row 3: Live FM Waveform Scope + DX7 Digital Readout
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent if is_on else COL_BORDER, width=1)

        coarse = self._val(self._get_zctrl(f"op{oi}_osc_freq_coarse"), 1)
        fine = self._val(self._get_zctrl(f"op{oi}_osc_freq_fine"), 0)
        det = int(round(self._val(self._get_zctrl(f"op{oi}_osc_detune"), 0)))
        lvl = self._norm(self._get_zctrl(f"op{oi}_operator_output_level"), 1.0)
        fb = self._norm(self._get_zctrl("feedback"), 0.0)
        _, mods, fb_op = DX7_ALGOS.get(self._alg_num(), DX7_ALGOS[1])
        # Sum modulation index from incoming active modulators
        mod_idx = 0.0
        mod_ratio = 2.0
        for src, dst in mods:
            if dst == oi and self._val(self._get_zctrl(f"op{src}_enable"), 1) >= 0.5:
                mod_idx += self._norm(self._get_zctrl(f"op{src}_operator_output_level"), 0.0) * 3.2
                sc = self._val(self._get_zctrl(f"op{src}_osc_freq_coarse"), 1)
                mod_ratio = 0.5 if sc == 0 else float(sc)

        pad = 12
        gx0, gx1 = x0 + pad, x1 - pad
        gw = max(10, gx1 - gx0)
        mid_y = (gy0 + gy1) / 2 + 8
        amp = max(8, (gy1 - gy0) / 2 - 20) * (0.15 + 0.85 * lvl)
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        base_c = 0.5 if int(round(coarse)) == 0 else float(int(round(coarse)))
        vis_cycles = max(1.0, min(6.0, base_c * (1.0 + fine / 100.0)))
        pts = []
        n_pts = 110
        prev_y = 0.0
        for i in range(n_pts + 1):
            t = i / n_pts
            ph = 2.0 * math.pi * vis_cycles * t
            fm_term = mod_idx * math.sin(2.0 * math.pi * min(8.0, mod_ratio) * t)
            fb_term = (fb * 2.4 * prev_y) if (oi == fb_op) else 0.0
            y = math.sin(ph + fm_term + fb_term)
            prev_y = y
            pts.extend([gx0 + t * gw, mid_y - y * amp])
        c.create_line(pts, fill=accent if is_on else COL_DIM, width=2.4)

        freq_txt = dx7_op_freq_text(mode, coarse, fine)
        hdr = f"OP{oi}  {OSC_MODES[mode].upper()}: {freq_txt}  DET:{det:+d}  LVL:{int(round(lvl * 99))}"
        c.create_text(x0 + 10, gy0 + 12, text=hdr, anchor="w", fill=accent if is_on else COL_DIM,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.88), bold=True))

        # Row 4: Bottom 2x2 Parameter Boxes
        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Osc", accent)

    # --------------------------------------------------------------------------
    # TAB 3: OP ENV (Interactive 4-Stage DX7 Rate/Level 2D Graph for OP 1..6)
    # --------------------------------------------------------------------------
    def _draw_tab_env(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Env"]
        oi = self.op_idx + 1
        gap = 6

        # Row 1: OP 1..6 selector
        r1_h = 34
        self._draw_op_selector(x0, y0, x1, y0 + r1_h, accent)

        # Row 2: Encoder Bank Bar
        r2_y = y0 + r1_h + gap
        r2_h = 34
        self._draw_bank_bar(
            x0, r2_y, x1, r2_y + r2_h,
            ["Rates R1-4", "Levels L1-4", "Scale & Vel"],
            self.env_bank, accent, "env_bank",
        )

        # Row 3: Interactive 4-Stage DX7 Envelope Graph
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 14
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + pad + 16, gy1 - pad
        gw = max(20, gx1 - gx0)
        gh = max(20, g_bot - g_top)

        def eval_dx7_env(op_n):
            # In DX7, Rate 99 = fastest (shortest segment), Rate 0 = slowest (longest segment)
            r1 = self._norm(self._get_zctrl(f"op{op_n}_eg_rate_1"), 0.9)
            r2 = self._norm(self._get_zctrl(f"op{op_n}_eg_rate_2"), 0.5)
            r3 = self._norm(self._get_zctrl(f"op{op_n}_eg_rate_3"), 0.5)
            r4 = self._norm(self._get_zctrl(f"op{op_n}_eg_rate_4"), 0.6)
            l1 = self._norm(self._get_zctrl(f"op{op_n}_eg_level_1"), 1.0)
            l2 = self._norm(self._get_zctrl(f"op{op_n}_eg_level_2"), 0.8)
            l3 = self._norm(self._get_zctrl(f"op{op_n}_eg_level_3"), 0.5)
            l4 = self._norm(self._get_zctrl(f"op{op_n}_eg_level_4"), 0.0)
            seg = gw * 0.22
            x1p = gx0 + max(0.05, 1.0 - r1) * seg
            x2p = x1p + max(0.05, 1.0 - r2) * seg
            x3p = x2p + max(0.05, 1.0 - r3) * seg
            xs  = x3p + gw * 0.12
            x4p = min(gx1, xs + max(0.05, 1.0 - r4) * seg)
            y0p = g_bot - l4 * gh
            y1p = g_bot - l1 * gh
            y2p = g_bot - l2 * gh
            y3p = g_bot - l3 * gh
            y4p = g_bot - l4 * gh
            return (r1, r2, r3, r4, l1, l2, l3, l4), (x1p, x2p, x3p, xs, x4p, y0p, y1p, y2p, y3p, y4p)

        # Ghost curve of OP1 behind OP2..6 for timing reference
        if oi != 1:
            _, (bx1, bx2, bx3, bxs, bx4, by0, by1, by2, by3, by4) = eval_dx7_env(1)
            c.create_line([gx0, by0, bx1, by1, bx2, by2, bx3, by3, bxs, by3, bx4, by4],
                          fill="#2d5e38", width=1.4, dash=(3, 3))

        (r1, r2, r3, r4, l1, l2, l3, l4), (x1p, x2p, x3p, xs, x4p, y0p, y1p, y2p, y3p, y4p) = eval_dx7_env(oi)
        pts = [gx0, y0p, x1p, y1p, x2p, y2p, x3p, y3p, xs, y3p, x4p, y4p]
        c.create_polygon(pts + [x4p, g_bot, gx0, g_bot], fill="#16291b", outline="")
        c.create_line(pts, fill=accent, width=2.6)

        nodes = [("1", x1p, y1p), ("2", x2p, y2p), ("3", x3p, y3p), ("4", x4p, y4p)]
        active_node = (self.drag_target[1].get("node")
                       if (self.drag_target and self.drag_target[0] == "op_env") else None)
        for tag, hx, hy in nodes:
            is_act = (active_node == int(tag))
            if is_act:
                c.create_oval(hx - 15, hy - 15, hx + 15, hy + 15, fill="", outline=accent, width=1.6, dash=(2, 2))
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            c.create_text(hx, hy, text=tag, fill="#0d0e12", font=self._font(8, bold=True))

        hdr = (f"OP{oi}  R:{int(round(r1*99))}/{int(round(r2*99))}/{int(round(r3*99))}/{int(round(r4*99))}"
               f"  L:{int(round(l1*99))}/{int(round(l2*99))}/{int(round(l3*99))}/{int(round(l4*99))}")
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "op_env",
            {
                "prefix": f"op{oi}_eg", "gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
                "nodes": [(1, x1p, y1p), (2, x2p, y2p), (3, x3p, y3p), (4, x4p, y4p)],
                "x1p": x1p, "x2p": x2p, "xs": xs,
            },
        ))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Env", accent)

    # --------------------------------------------------------------------------
    # TAB 4: SCALE (Keyboard Level Scaling Curve A-1..C8 + Breakpoint Drag)
    # --------------------------------------------------------------------------
    def _draw_tab_scale(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Scale"]
        oi = self.op_idx + 1
        gap = 6

        # Row 1: OP 1..6 selector
        r1_h = 34
        self._draw_op_selector(x0, y0, x1, y0 + r1_h, accent)

        # Row 2: Bank Bar + Quick L/R Curve Pills
        r2_y = y0 + r1_h + gap
        r2_h = 34
        left_w = (x1 - x0) * 0.52
        self._draw_bank_bar(
            x0, r2_y, x0 + left_w, r2_y + r2_h,
            ["Break & Depths", "Curves & Sens"],
            self.scale_bank, accent, "scale_bank",
        )
        rw = (x1 - (x0 + left_w + gap) - gap) / 2
        lc_z = self._get_zctrl(f"op{oi}_kbd_lev_scl_lft_curve")
        rc_z = self._get_zctrl(f"op{oi}_kbd_lev_scl_rht_curve")
        self._draw_pill(x0 + left_w + gap, r2_y, x0 + left_w + gap + rw, r2_y + r2_h,
                        f"L: {self._fmt(lc_z)}", False, accent, "cycle", f"op{oi}_kbd_lev_scl_lft_curve")
        self._draw_pill(x0 + left_w + 2 * gap + rw, r2_y, x1, r2_y + r2_h,
                        f"R: {self._fmt(rc_z)}", False, accent, "cycle", f"op{oi}_kbd_lev_scl_rht_curve")

        # Row 3: Interactive Keyboard Scaling Curve (A-1 .. C8)
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 14
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + pad + 14, gy1 - pad - 10
        gw = max(20, gx1 - gx0)
        gh = max(20, g_bot - g_top)
        mid_y = (g_top + g_bot) / 2

        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(3, 4))
        for note_v, nlbl in ((3, "C0"), (27, "C2"), (39, "C3"), (51, "C4"), (75, "C6")):
            nx = gx0 + (note_v / 99.0) * gw
            c.create_line(nx, g_top, nx, g_bot, fill=COL_GRID, dash=(2, 4))
            c.create_text(nx, gy1 - 5, text=nlbl, fill=COL_DIM, font=self._font(8))

        bp = self._norm(self._get_zctrl(f"op{oi}_kbd_lev_scl_brk_pt"), 0.39)
        ld = self._norm(self._get_zctrl(f"op{oi}_kbd_lev_scl_lft_depth"), 0.0)
        rd = self._norm(self._get_zctrl(f"op{oi}_kbd_lev_scl_rht_depth"), 0.0)
        lc = int(round(self._val(lc_z, 0)))  # 0=-LIN, 1=-EXP, 2=+EXP, 3=+LIN
        rc = int(round(self._val(rc_z, 0)))

        def curve_delta(t, depth, ctype):
            # t in 0..1 distance from breakpoint
            sign = -1.0 if ctype in (0, 1) else 1.0
            mag = (t ** 2.2) if ctype in (1, 2) else t
            return sign * depth * mag * (gh * 0.48)

        pts = []
        n_pts = 80
        for i in range(n_pts + 1):
            x_n = i / n_pts
            if x_n <= bp:
                t = (bp - x_n) / max(0.05, bp)
                dy = curve_delta(min(1.0, t), ld, lc)
            else:
                t = (x_n - bp) / max(0.05, 1.0 - bp)
                dy = curve_delta(min(1.0, t), rd, rc)
            pts.extend([gx0 + x_n * gw, max(g_top, min(g_bot, mid_y - dy))])

        c.create_line(pts, fill=accent, width=2.6)
        bpx = gx0 + bp * gw
        c.create_line(bpx, g_top, bpx, g_bot, fill=accent, dash=(2, 3), width=1.5)
        c.create_oval(bpx - 8, mid_y - 8, bpx + 8, mid_y + 8, fill=accent, outline="#ffffff", width=2)

        bp_lbl = dx7_breakpoint_note(bp * 99.0)
        hdr = f"OP{oi} BP:{bp_lbl}  L:{int(round(ld*99))}({SCALE_CURVES[lc%4]})  R:{int(round(rd*99))}({SCALE_CURVES[rc%4]})"
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "scale_graph",
            {"oi": oi, "gx0": gx0, "gx1": gx1, "g_top": g_top, "g_bot": g_bot, "bpx": bpx},
        ))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Scale", accent)

    # --------------------------------------------------------------------------
    # TAB 5: PITCH / LFO (Live LFO Scope + Interactive 2D Pitch EG Graph)
    # --------------------------------------------------------------------------
    def _draw_tab_lfo(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["LFO"]
        gap = 6

        # Row 1: 4 Encoder Banks (LFO Core | LFO Mod | Pitch R | Pitch L)
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["LFO Core", "LFO Mod", "Pitch R", "Pitch L"],
            self.lfo_bank, accent, "lfo_bank",
        )

        # Row 2: 6 LFO Waveforms + LFO Sync Toggle
        r2_y = y0 + r1_h + gap
        r2_h = 34
        wf_z = self._get_zctrl("lfo_waveform")
        wf_idx = int(round(self._val(wf_z, 0)))
        sync_on = self._val(self._get_zctrl("lfo_sync"), 0) >= 0.5
        sgap = 4
        sw = (x1 - x0 - sgap * len(LFO_WAVES)) / (len(LFO_WAVES) + 1)
        for i, wlbl in enumerate(LFO_WAVES):
            wx0 = x0 + i * (sw + sgap)
            self._draw_pill(wx0, r2_y, wx0 + sw, r2_y + r2_h, wlbl,
                            i == wf_idx, accent, "lfo_wave", i)
        self._draw_pill(x0 + len(LFO_WAVES) * (sw + sgap), r2_y, x1, r2_y + r2_h,
                        "SYNC" if not sync_on else "●SYNC", sync_on, "#51cf66", "cycle", "lfo_sync")

        # Row 3: Live LFO Scope (banks 0-1) OR Interactive 2D Pitch EG (banks 2-3)
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 14
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + pad + 14, gy1 - pad
        gw = max(20, gx1 - gx0)
        gh = max(20, g_bot - g_top)

        if self.lfo_bank < 2:
            mid_y = (g_top + g_bot) / 2
            amp = max(8, gh / 2 - 4)
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))
            spd = self._norm(self._get_zctrl("lfo_speed"), 0.35)
            dly = self._norm(self._get_zctrl("lfo_delay"), 0.0) * 0.35
            pmd = self._norm(self._get_zctrl("lfo_pitch_mod_depth"), 0.3)
            amd = self._norm(self._get_zctrl("lfo_amp_mod_depth"), 0.0)
            depth = max(0.25, max(pmd, amd))
            cycles = 1.5 + spd * 6.0
            pts = []
            n_pts = 100
            for i in range(n_pts + 1):
                t = i / n_pts
                env_g = 0.0 if t < dly else min(1.0, (t - dly) / 0.15)
                p = (t * cycles) % 1.0
                if wf_idx == 0:    # Tri
                    y = 1.0 - 4.0 * abs(p - 0.5)
                elif wf_idx == 1:  # SawDn
                    y = 1.0 - 2.0 * p
                elif wf_idx == 2:  # SawUp
                    y = 2.0 * p - 1.0
                elif wf_idx == 3:  # Sqr
                    y = 1.0 if p < 0.5 else -1.0
                elif wf_idx == 4:  # Sin
                    y = math.sin(2.0 * math.pi * p)
                else:              # S&H
                    y = math.sin(int(t * cycles * 2.0) * 12.9898 + 1.23) * 0.9
                pts.extend([gx0 + t * gw, mid_y - y * env_g * depth * amp])
            c.create_line(pts, fill=accent, width=2.4)
            hdr = f"LFO {LFO_WAVES[wf_idx % 6]}  SPD:{int(round(spd*99))}  DLY:{int(round(dly/0.35*99))}  PMD:{int(round(pmd*99))}  AMD:{int(round(amd*99))}"
            c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                          font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))
        else:
            # Interactive 2D Pitch EG Graph (center = 50 = 0 st)
            mid_y = (g_top + g_bot) / 2
            c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(3, 4))
            r1 = self._norm(self._get_zctrl("pitch_eg_rate_1"), 0.9)
            r2 = self._norm(self._get_zctrl("pitch_eg_rate_2"), 0.7)
            r3 = self._norm(self._get_zctrl("pitch_eg_rate_3"), 0.9)
            r4 = self._norm(self._get_zctrl("pitch_eg_rate_4"), 0.6)
            l1 = self._norm(self._get_zctrl("pitch_eg_level_1"), 0.5)
            l2 = self._norm(self._get_zctrl("pitch_eg_level_2"), 0.5)
            l3 = self._norm(self._get_zctrl("pitch_eg_level_3"), 0.5)
            l4 = self._norm(self._get_zctrl("pitch_eg_level_4"), 0.5)
            seg = gw * 0.22
            x1p = gx0 + max(0.05, 1.0 - r1) * seg
            x2p = x1p + max(0.05, 1.0 - r2) * seg
            x3p = x2p + max(0.05, 1.0 - r3) * seg
            xs  = x3p + gw * 0.12
            x4p = min(gx1, xs + max(0.05, 1.0 - r4) * seg)
            y0p, y1p, y2p, y3p, y4p = (g_bot - lv * gh for lv in (l4, l1, l2, l3, l4))
            pts = [gx0, y0p, x1p, y1p, x2p, y2p, x3p, y3p, xs, y3p, x4p, y4p]
            c.create_line(pts, fill=accent, width=2.6)
            for tag, hx, hy in (("1", x1p, y1p), ("2", x2p, y2p), ("3", x3p, y3p), ("4", x4p, y4p)):
                c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
                c.create_text(hx, hy - 13, text=tag, fill=COL_TEXT, font=self._font(8, bold=True))
            hdr = (f"PITCH EG  R:{int(round(r1*99))}/{int(round(r2*99))}/{int(round(r3*99))}/{int(round(r4*99))}"
                   f"  L:{int(round(l1*99))}/{int(round(l2*99))}/{int(round(l3*99))}/{int(round(l4*99))}")
            c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                          font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))
            self.hitboxes.append((
                x0, gy0, x1, gy1, "op_env",
                {
                    "prefix": "pitch_eg", "gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
                    "nodes": [(1, x1p, y1p), (2, x2p, y2p), (3, x3p, y3p), (4, x4p, y4p)],
                    "x1p": x1p, "x2p": x2p, "xs": xs,
                },
            ))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "LFO", accent)

    # --------------------------------------------------------------------------
    # TAB 6: FILTER / OUT (Interactive 2D SVF Filter XY Pad + OP Mute Matrix)
    # --------------------------------------------------------------------------
    def _draw_tab_filter(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Filter"]
        gap = 6

        # Row 1: Encoder Bank Bar
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Filter & Out", "Engine & Poly"],
            self.flt_bank, accent, "flt_bank",
        )

        # Row 2: 2D SVF Filter Response Pad (left 62%) + Quick OP 1..6 Mute Grid (right 38%)
        gy0 = y0 + r1_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        left_w = int((x1 - x0) * 0.62)
        lx1 = x0 + left_w
        rx0 = lx1 + gap

        # Left: 2D Filter XY Response Graph
        c.create_rectangle(x0, gy0, lx1, gy1, fill=COL_PANEL, outline=accent, width=1)
        pad = 12
        gx0, gx1 = x0 + pad, lx1 - pad
        g_top, g_bot = gy0 + pad + 14, gy1 - pad
        gw = max(10, gx1 - gx0)
        gh = max(10, g_bot - g_top)

        cut = self._norm(self._get_zctrl("cutoff"), 1.0)
        res = self._norm(self._get_zctrl("resonance"), 0.0)
        zero_y = g_top + gh * 0.45
        c.create_line(gx0, zero_y, gx1, zero_y, fill=COL_GRID, dash=(2, 4))

        pts = []
        n_pts = 56
        for i in range(n_pts + 1):
            xn = i / n_pts
            d = xn - cut
            db = 0.0 if d <= 0.0 else -36.0 * (d / 0.25)
            peak = res * 18.0 * math.exp(-((d / 0.055) ** 2))
            y = max(g_top, min(g_bot, zero_y - ((db + peak) / 24.0) * (gh * 0.48)))
            pts.extend([gx0 + xn * gw, y])
        c.create_polygon([gx0, g_bot] + pts + [gx1, g_bot], fill="#2e191b", outline="")
        c.create_line(pts, fill=accent, width=2.5)

        hx = gx0 + cut * gw
        hy = g_bot - res * gh
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        hdr = f"SVF  CUT:{fmt_hz(dx7_svf_hz(cut))}  RES:{int(round(res * 100))}%"
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (lx1 - x0) - 20, self._fs(0.84), bold=True))

        self.hitboxes.append((
            x0, gy0, lx1, gy1, "filter_xy",
            {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot},
        ))

        # Right: 2x3 Big OP 1..6 Mute/Enable Performance Pads
        carriers, _, _ = DX7_ALGOS.get(self._alg_num(), DX7_ALGOS[1])
        cw = (x1 - rx0 - gap) / 2
        ch = (gy1 - gy0 - 2 * gap) / 3
        for i in range(6):
            op = i + 1
            col_i = i % 2
            row_i = i // 2
            px0 = rx0 + col_i * (cw + gap)
            py0 = gy0 + row_i * (ch + gap)
            is_on = self._val(self._get_zctrl(f"op{op}_enable"), 1) >= 0.5
            role = "C" if op in carriers else "M"
            pcol = COL_CARRIER if op in carriers else COL_MOD
            self._draw_pill(px0, py0, px0 + cw, py0 + ch,
                            f"OP{op} {role}", is_on, pcol,
                            "cycle", f"op{op}_enable", subtext="ON" if is_on else "OFF")

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Filter", accent)

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
            bipolar = (key in ("master_tune", "transpose") or key.endswith("_osc_detune") or key.startswith("pitch_eg_level_"))
            self._draw_param_box(px0, py0, px0 + cw, py0 + ch, key, lbl, accent, bipolar=bipolar)

    # --------------------------------------------------------------------------
    # ECO CPU Tamer (caps polyphony to 8v with one-tap restore)
    # --------------------------------------------------------------------------
    def _toggle_eco(self):
        if not self.processor:
            return
        z_v = self._get_zctrl("number_of_voices")
        if self.eco_on:
            if z_v is not None and "number_of_voices" in self._eco_backup:
                self._set_raw(z_v, self._eco_backup["number_of_voices"])
            self._eco_backup.clear()
            self.eco_on = False
        else:
            self._eco_backup.clear()
            if z_v is not None:
                cur = int(round(self._val(z_v, 16)))
                self._eco_backup["number_of_voices"] = cur
                if cur > 8:
                    self._set_raw(z_v, 8)
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

        if kind == "voice_cycle":
            z = self._get_zctrl("number_of_voices")
            if z is not None:
                cur = int(round(self._val(z, 16)))
                nxt = next((v for v in VOICE_PRESETS if v > cur), VOICE_PRESETS[0])
                self._set_raw(z, nxt)
                self.last_snapshot = None
                self._draw()
            return

        if kind == "bank_algo":
            self._switch_subbank("algo_bank", 0)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "alg_step":
            z = self._get_zctrl("algorithm_num")
            if z is not None:
                cur = self._alg_num()
                nxt = ((cur - 1 + payload) % 32) + 1
                self._set_raw(z, nxt)
                self.last_snapshot = None
                self._draw()
            return

        if kind == "algo_op":
            now = time.monotonic()
            tap_id = ("algo_op", payload)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                self._cycle_enum(self._get_zctrl(f"op{payload + 1}_enable"), 1)
            else:
                self.last_tap = (tap_id, now)
                self.op_idx = payload
            self.last_snapshot = None
            self._draw()
            return

        if kind == "op_idx":
            if self.op_idx != payload:
                self.op_idx = payload
                self._live_swap_encoders(self.active_tab)
                self.last_snapshot = None
                self._draw()
            return

        if kind in ("algo_bank", "osc_bank", "env_bank", "scale_bank", "lfo_bank", "flt_bank"):
            self._switch_subbank(kind, payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "lfo_wave":
            self._set_raw(self._get_zctrl("lfo_waveform"), payload)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "cycle":
            self._cycle_enum(self._get_zctrl(payload), 1)
            self.last_snapshot = None
            self._draw()
            return

        if kind == "filter_xy":
            self._switch_subbank("flt_bank", 0)
            now = time.monotonic()
            tap_id = ("filter_xy", "svf")
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

        if kind == "scale_graph":
            self._switch_subbank("scale_bank", 0)
            oi = payload["oi"]
            now = time.monotonic()
            tap_id = ("scale_graph", oi)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for rk in (f"op{oi}_kbd_lev_scl_brk_pt", f"op{oi}_kbd_lev_scl_lft_depth", f"op{oi}_kbd_lev_scl_rht_depth"):
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("scale_graph", payload)
            self._apply_drag(event.x, event.y)
            return

        if kind == "op_env":
            # Generous 26 px priority touch capture radius around each (R_k, L_k) node
            hit_r2 = 26.0 ** 2
            best_n = 1
            best_d = 1e12
            in_radius_n = None
            in_radius_d = 1e12
            for n_idx, nx, ny in payload["nodes"]:
                d = (event.x - nx) ** 2 + (event.y - ny) ** 2
                if d <= hit_r2 and d < in_radius_d:
                    in_radius_d = d
                    in_radius_n = n_idx
                if d < best_d:
                    best_d = d
                    best_n = n_idx
            if in_radius_n is not None:
                best_n = in_radius_n
            now = time.monotonic()
            pref = payload["prefix"]
            tap_id = ("op_env", pref, best_n)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for rk in (f"{pref}_rate_{best_n}", f"{pref}_level_{best_n}"):
                    z = self._get_zctrl(rk)
                    if z is not None:
                        z.reset_value()
                self.last_snapshot = None
                self._draw()
                return
            self.last_tap = (tap_id, now)
            self.drag_target = ("op_env", dict(payload, node=best_n))
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
                self._set_norm(self._get_zctrl("cutoff"), (x - gx0) / (gx1 - gx0))
            if gy1 > gy0:
                self._set_norm(self._get_zctrl("resonance"), (gy1 - y) / (gy1 - gy0))
        elif kind == "scale_graph":
            oi = payload["oi"]
            gx0, gx1 = payload["gx0"], payload["gx1"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl(f"op{oi}_kbd_lev_scl_brk_pt"), (x - gx0) / (gx1 - gx0))
        elif kind == "op_env":
            pref = payload["prefix"]
            gx0, gw = payload["gx0"], payload["gw"]
            g_top, g_bot = payload["g_top"], payload["g_bot"]
            seg = max(10.0, gw * 0.22)
            n = payload["node"]
            anchor_x = gx0 if n == 1 else (payload["x1p"] if n == 2 else (payload["x2p"] if n == 3 else payload["xs"]))
            rate_n = 1.0 - max(0.0, min(1.0, (x - anchor_x) / seg))
            self._set_norm(self._get_zctrl(f"{pref}_rate_{n}"), rate_n)
            if g_bot > g_top:
                lvl_n = max(0.0, min(1.0, (g_bot - y) / (g_bot - g_top)))
                self._set_norm(self._get_zctrl(f"{pref}_level_{n}"), lvl_n)

        self.last_snapshot = None
        self._draw()
