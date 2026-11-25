#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# OB-Xf (Oberheim OB-X/OB-Xa Synthesizer) Workstation Widget for Zynthian (V5)
# Part of UI Synths (zynthian-ui-synths)
#
# Replaces OB-Xf's 102 raw LV2 parameters (~26 encoder pages) with 6 dynamic
# workstation tabs mapped 1-to-1 to Zynthian's 4 physical encoders + ECO:
#   Osc | Filter | Env | LFO | Voices | Perf   + ECO
#
# Features:
# - Resilient controller resolver: indexes full org_surge_synth_team_OB_Xf_*
#   symbols, unprefixed suffixes, and normalized display labels.
# - Authentic Oberheim OB-Xf visualizations & controls:
#   * Osc: Osc 1/2 Saw & Pulse toggles, Crossmod, Sync, PW, RingMod, Noise
#   * Filter: 2-Pole morphing (LP <-> Notch/BP <-> HP) + 4-Pole & 15 Xpander
#     modes + interactive 2D XY response graph (Cutoff -45..+75 x Resonance)
#   * Env: Dual interactive 2D ADSR (Amp + Filter with Attack Curve & Invert)
#   * LFO: Dual LFO 1 & LFO 2 continuous wave-morph scope + 6 routing toggles
#   * Voices: Iconic Oberheim 8-Voice Stereo Pan Spread faders + Unison/Slop
#   * Perf: Polyphony, Portamento, Velocity, Vibrato, Pitch Bend & Master Vol
# - ECO button: disables HQ Mode, caps Polyphony -> 8v & UnisonVoices -> 3v
#   with one-tap restore for smooth Pi 5 performance.
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

TABS = ["Osc", "Filter", "Env", "LFO", "Voices", "Perf"]
TAB_ACCENTS = {
    "Osc":    "#cc5de8",  # violet
    "Filter": "#ff922b",  # orange
    "Env":    "#51cf66",  # green
    "LFO":    "#ffd43b",  # yellow
    "Voices": "#4dabf7",  # blue
    "Perf":   "#ff6b6b",  # coral
}

# ------------------------------------------------------------------------------
# Authentic OB-Xf Enum Tables
# ------------------------------------------------------------------------------
NOISE_COLORS = ["White", "Pink", "Brown"]
NOTE_PRIORITIES = ["Last", "Low", "High"]
ENV_LEGATO = ["Both", "Filter", "Amp", "Retrig"]
LFO_DEST_MODES = ["Off", "Fwd", "Rev"]
VIB_WAVES = ["Sine", "Square"]
XPANDER_MODES = [
    "LP4", "LP3", "LP2", "LP1", "HP3", "HP2", "HP1", "BP4",
    "BP2", "N2", "PH3", "HP2+LP1", "HP3+LP1", "N2+LP1", "PH3+LP1",
]

PREFIX = "org_surge_synth_team_OB_Xf_"

BIPOLAR_KEYS = {
    "Osc1Pitch", "Osc2Pitch", "OscCrossmod", "Transpose", "Tune",
    "LFO1Wave1", "LFO1Wave2", "LFO1Wave3", "LFO2Wave1", "LFO2Wave2", "LFO2Wave3",
    "LFO2ModAmount2",
    "PanVoice1", "PanVoice2", "PanVoice3", "PanVoice4",
    "PanVoice5", "PanVoice6", "PanVoice7", "PanVoice8",
}


def _norm_key(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def obxf_cutoff_hz(val):
    """OB-Xf FilterCutoff is -45..+75 semitones around ~440Hz."""
    hz = 440.0 * (2.0 ** (float(val) / 12.0))
    return max(20.0, min(22000.0, hz))


def fmt_hz(hz):
    if hz >= 1000.0:
        return f"{hz / 1000.0:.2f}k" if hz < 10000.0 else f"{hz / 1000.0:.1f}k"
    return f"{int(round(hz))}Hz"


# ------------------------------------------------------------------------------
# OB-Xf Workstation Widget Class
# ------------------------------------------------------------------------------
class zynthian_widget_ob_xf(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)

        self.active_tab = "Osc"
        self.osc_bank = 0     # 0=Mixer/PW, 1=Pitch/Detune, 2=Crossmod/Noise
        self.flt_bank = 0     # 0=Cut/Res/Mode, 1=Env/Key/Slop
        self.env_idx = 0      # 0=Amp Env, 1=Filter Env
        self.env_bank = 0     # 0=ADSR, 1=Curve/Mod
        self.lfo_idx = 0      # 0=LFO 1, 1=LFO 2
        self.lfo_bank = 0     # 0=Rate/Amt, 1=Wave Morph
        self.voice_bank = 0   # 0=Pan 1-4, 1=Pan 5-8, 2=Unison & Slop
        self.perf_bank = 0    # 0=Master/Glide, 1=Vibrato/Bend, 2=Vel/Poly

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
    # Processor Setup & Resilient Controller Resolver
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
        pref_l = _norm_key(PREFIX) + "_"
        for sym, z in processor.controllers_dict.items():
            ns = _norm_key(sym)
            idx[ns] = z
            if sym.startswith(PREFIX):
                idx[_norm_key(sym[len(PREFIX):])] = z
            elif ns.startswith(pref_l):
                idx[ns[len(pref_l):]] = z
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
        z = cdict.get(PREFIX + key)
        if z is not None:
            return z
        z = cdict.get(key)
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
                    ("Osc1Mix",  "Osc1 Mix"),
                    ("Osc2Mix",  "Osc2 Mix"),
                    ("OscPW",    "Osc PW"),
                    ("NoiseMix", "Noise Mix"),
                ]
            if self.osc_bank == 1:
                return [
                    ("Osc1Pitch",    "Osc1 Ptch"),
                    ("Osc2Pitch",    "Osc2 Ptch"),
                    ("Osc2Detune",   "O2 Detune"),
                    ("Osc2PWOffset", "O2 PW Off"),
                ]
            return [
                ("OscCrossmod",   "Crossmod"),
                ("RingModMix",    "Ring Mod"),
                ("OscBrightness", "Osc Bright"),
                ("NoiseColor",    "Noise Clr"),
            ]

        if tab_name == "Filter":
            if self.flt_bank == 0:
                return [
                    ("FilterCutoff",    "Cutoff"),
                    ("FilterResonance", "Resonance"),
                    ("FilterMode",      "Flt Morph"),
                    ("FilterEnvAmount", "Flt EnvAmt"),
                ]
            return [
                ("FilterXpanderMode", "Xpander"),
                ("FilterKeyFollow",   "KeyFollow"),
                ("FilterSlop",        "Flt Slop"),
                ("VelToFilterEnv",    "Vel > Flt"),
            ]

        if tab_name == "Env":
            ep = "AmpEnv" if self.env_idx == 0 else "FilterEnv"
            el = "Amp" if self.env_idx == 0 else "Flt"
            if self.env_bank == 0:
                return [
                    (f"{ep}Attack",  f"{el} Att"),
                    (f"{ep}Decay",   f"{el} Dec"),
                    (f"{ep}Sustain", f"{el} Sus"),
                    (f"{ep}Release", f"{el} Rel"),
                ]
            return [
                (f"{ep}AttackCurve", f"{el} Curve"),
                ("EnvToPitchAmount", "Env>Pitch"),
                ("EnvToPWAmount",    "Env>PW"),
                ("EnvelopeSlop",     "Env Slop"),
            ]

        if tab_name == "LFO":
            li = self.lfo_idx + 1
            if self.lfo_bank == 0:
                return [
                    (f"LFO{li}Rate",       f"LFO{li} Rate"),
                    (f"LFO{li}ModAmount1", f"LFO{li} Amt1"),
                    (f"LFO{li}ModAmount2", f"LFO{li} Amt2"),
                    (f"LFO{li}PW",         f"LFO{li} PW"),
                ]
            return [
                (f"LFO{li}Wave1",     "Sin<>Tri"),
                (f"LFO{li}Wave2",     "Pls<>Saw"),
                (f"LFO{li}Wave3",     "S&H<>Gld"),
                (f"LFO{li}TempoSync", "Sync"),
            ]

        if tab_name == "Voices":
            if self.voice_bank == 0:
                return [
                    ("PanVoice1", "Pan V1"),
                    ("PanVoice2", "Pan V2"),
                    ("PanVoice3", "Pan V3"),
                    ("PanVoice4", "Pan V4"),
                ]
            if self.voice_bank == 1:
                return [
                    ("PanVoice5", "Pan V5"),
                    ("PanVoice6", "Pan V6"),
                    ("PanVoice7", "Pan V7"),
                    ("PanVoice8", "Pan V8"),
                ]
            return [
                ("UnisonVoices", "Uni Voice"),
                ("UnisonDetune", "Uni Det"),
                ("LevelSlop",    "Lvl Slop"),
                ("FilterSlop",   "Flt Slop"),
            ]

        # Perf
        if self.perf_bank == 0:
            return [
                ("Volume",     "Volume"),
                ("Portamento", "Glide"),
                ("Transpose",  "Transpose"),
                ("Tune",       "Fine Tune"),
            ]
        if self.perf_bank == 1:
            return [
                ("VibratoRate",   "Vib Rate"),
                ("PitchBendUp",   "PB Up"),
                ("PitchBendDown", "PB Down"),
                ("PortamentoSlop","GlideSlop"),
            ]
        return [
            ("Polyphony",      "Polyphony"),
            ("VelToAmpEnv",    "Vel>Amp"),
            ("VelToFilterEnv", "Vel>Flt"),
            ("EnvLegatoMode",  "Legato"),
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
            logging.debug(f"OB-Xf widget: live swap error => {e}")

    def _sync_zyngui_list(self, target_tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page_by_title(target_tab)
            self._draw()
        except Exception as e:
            logging.debug(f"OB-Xf widget: sync list error => {e}")

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
    # Native-Range Value Helpers
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
        if ticks and len(ticks) > 1:
            try:
                cur = float(zctrl.get_value())
                idx = min(range(len(ticks)), key=lambda i: abs(ticks[i] - cur))
            except Exception:
                idx = 0
            zctrl.set_value(ticks[(idx + step) % len(ticks)], send=True)
            return
        vmin = float(getattr(zctrl, "value_min", 0.0))
        vmax = float(getattr(zctrl, "value_max", 1.0))
        cur = zynthian_widget_ob_xf._val(zctrl, vmin)
        if vmax == 1.0 and vmin == 0.0:
            zctrl.set_value(0.0 if cur >= 0.5 else 1.0, send=True)
        else:
            iv = int(round(cur))
            nxt = int(vmin) + ((iv - int(vmin) + step) % (int(vmax) - int(vmin) + 1))
            zctrl.set_value(nxt, send=True)

    def _fmt(self, zctrl, key=None):
        if zctrl is None:
            return "--"
        v = self._val(zctrl, 0.0)
        if key == "FilterCutoff":
            return fmt_hz(obxf_cutoff_hz(v))
        if key == "FilterXpanderMode":
            return XPANDER_MODES[max(0, min(len(XPANDER_MODES) - 1, int(round(v))))]
        if key == "NoiseColor":
            idx = 0 if v < 0.25 else (1 if v < 0.75 else 2)
            return NOISE_COLORS[idx]
        if key == "NotePriority":
            return NOTE_PRIORITIES[max(0, min(2, int(round(v))))]
        if key == "EnvLegatoMode":
            return ENV_LEGATO[max(0, min(3, int(round(v))))]
        if key == "VibratoWave":
            return VIB_WAVES[1 if v >= 0.5 else 0]
        if key and "To" in key and key.startswith("LFO"):
            return LFO_DEST_MODES[0 if v < 0.25 else (1 if v < 0.75 else 2)]
        if key in ("Osc1Pitch", "Osc2Pitch", "Transpose", "EnvToPitchAmount", "PitchBendUp", "PitchBendDown"):
            return f"{v:+.0f}st" if key in ("Osc1Pitch", "Osc2Pitch", "Transpose") else f"{v:.0f}st"
        if key == "Tune":
            return f"{v:+.0f}ct"
        if key in ("Polyphony", "UnisonVoices"):
            return f"{int(round(v))}v"
        if key and key.startswith("PanVoice"):
            p = int(round(v * 100.0))
            return "C" if abs(p) < 3 else (f"L{-p}" if p < 0 else f"R{p}")
        if key in ("HQMode", "Unison", "OscSync", "Osc1SawWave", "Osc1PulseWave", "Osc2SawWave", "Osc2PulseWave",
                   "Filter2PoleBPBlend", "Filter2PolePush", "Filter4PoleMode", "Filter4PoleXpander",
                   "FilterEnvInvert", "LFO1TempoSync", "LFO2TempoSync"):
            return "ON" if v >= 0.5 else "OFF"
        if key in BIPOLAR_KEYS:
            return f"{int(round(v * 100.0)):+d}%"
        return f"{int(round(self._norm(zctrl, 0.0) * 100.0))}%"

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
            keys += ["Osc1SawWave", "Osc1PulseWave", "Osc2SawWave", "Osc2PulseWave",
                     "Osc1Mix", "Osc2Mix", "OscPW", "OscSync", "OscCrossmod", "NoiseMix", "RingModMix"]
        elif self.active_tab == "Filter":
            keys += ["FilterCutoff", "FilterResonance", "FilterMode", "FilterEnvAmount",
                     "Filter2PoleBPBlend", "Filter2PolePush", "Filter4PoleMode",
                     "Filter4PoleXpander", "FilterXpanderMode"]
        elif self.active_tab == "Env":
            keys += ["AmpEnvAttack", "AmpEnvDecay", "AmpEnvSustain", "AmpEnvRelease", "AmpEnvAttackCurve",
                     "FilterEnvAttack", "FilterEnvDecay", "FilterEnvSustain", "FilterEnvRelease",
                     "FilterEnvAttackCurve", "FilterEnvInvert"]
        elif self.active_tab == "LFO":
            li = self.lfo_idx + 1
            keys += [f"LFO{li}Rate", f"LFO{li}PW", f"LFO{li}Wave1", f"LFO{li}Wave2", f"LFO{li}Wave3",
                     f"LFO{li}TempoSync", f"LFO{li}ToFilterCutoff", f"LFO{li}ToOsc1Pitch",
                     f"LFO{li}ToOsc2Pitch", f"LFO{li}ToOsc1PW", f"LFO{li}ToOsc2PW", f"LFO{li}ToVolume"]
        elif self.active_tab == "Voices":
            keys += [f"PanVoice{i}" for i in range(1, 9)] + ["Unison", "UnisonVoices", "UnisonDetune", "Polyphony"]
        elif self.active_tab == "Perf":
            keys += ["Volume", "Portamento", "Polyphony", "HQMode", "NotePriority", "VibratoWave", "EnvLegatoMode"]
        return keys

    def _state_snapshot(self):
        vals = [
            self.active_tab, self.osc_bank, self.flt_bank, self.env_idx, self.env_bank,
            self.lfo_idx, self.lfo_bank, self.voice_bank, self.perf_bank, self.eco_on,
            self.width, self.height,
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
        elif self.active_tab == "Voices":
            self._draw_tab_voices(bx0, by0, bx1, by1)
        elif self.active_tab == "Perf":
            self._draw_tab_perf(bx0, by0, bx1, by1)

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
    # TAB 1: OSC (Oberheim Dual VCOs: Saw/Pulse, Sync, Crossmod, Ring, Noise)
    # --------------------------------------------------------------------------
    def _draw_tab_osc(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Osc"]
        gap = 6

        # Row 1: Encoder Sub-Bank Bar
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Mixer & PW", "Pitch & Detune", "X-Mod / Ring / Noise"],
            self.osc_bank, accent, "osc_bank",
        )

        # Row 2: Classic Oberheim Wave & Sync Switches
        r2_y = y0 + r1_h + gap
        r2_h = 34
        switches = [
            ("O1 SAW",  "Osc1SawWave",   accent),
            ("O1 PLS",  "Osc1PulseWave", accent),
            ("O2 SAW",  "Osc2SawWave",   "#4dabf7"),
            ("O2 PLS",  "Osc2PulseWave", "#4dabf7"),
            ("SYNC",    "OscSync",       "#51cf66"),
        ]
        sw = (x1 - x0 - gap * 4) / 5
        for i, (lbl, key, col) in enumerate(switches):
            sx0 = x0 + i * (sw + gap)
            on = self._val(self._get_zctrl(key), 0.0) >= 0.5
            self._draw_pill(sx0, r2_y, sx0 + sw, r2_y + r2_h,
                            f"●{lbl}" if on else lbl, on, col, "cycle", key)

        # Row 3: Live Oberheim Dual-VCO Scope (left 62%) + 3 Mix Faders (right 38%)
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        left_w = int((x1 - x0) * 0.62)
        lx1 = x0 + left_w
        rx0 = lx1 + gap

        c.create_rectangle(x0, gy0, lx1, gy1, fill=COL_PANEL, outline=accent, width=1)
        s1 = self._val(self._get_zctrl("Osc1SawWave"), 1.0) >= 0.5
        p1 = self._val(self._get_zctrl("Osc1PulseWave"), 0.0) >= 0.5
        s2 = self._val(self._get_zctrl("Osc2SawWave"), 1.0) >= 0.5
        p2 = self._val(self._get_zctrl("Osc2PulseWave"), 0.0) >= 0.5
        m1 = self._norm(self._get_zctrl("Osc1Mix"), 1.0)
        m2 = self._norm(self._get_zctrl("Osc2Mix"), 1.0)
        pw = self._val(self._get_zctrl("OscPW"), 0.5)
        xm = self._val(self._get_zctrl("OscCrossmod"), 0.0)

        pad = 10
        gx0, gx1 = x0 + pad, lx1 - pad
        mid_y = (gy0 + gy1) / 2 + 6
        gw = max(10, gx1 - gx0)
        amp = max(8, (gy1 - gy0) / 2 - 16)
        c.create_line(gx0, mid_y, gx1, mid_y, fill=COL_GRID, dash=(2, 4))

        pts = []
        for i in range(97):
            t = i / 96.0
            ph2 = (t * 2.02) % 1.0
            y2 = (0.5 * (2.0 * ph2 - 1.0) if s2 else 0.0) + (0.5 * (1.0 if ph2 < pw else -1.0) if p2 else 0.0)
            ph1 = (t * 2.0 + xm * 0.35 * y2) % 1.0
            y1v = (0.5 * (2.0 * ph1 - 1.0) if s1 else 0.0) + (0.5 * (1.0 if ph1 < pw else -1.0) if p1 else 0.0)
            ytot = (m1 * y1v + m2 * y2) / max(0.5, m1 + m2)
            pts.extend([gx0 + t * gw, mid_y - max(-1.0, min(1.0, ytot)) * amp])
        c.create_line(pts, fill=accent, width=2.4)
        hdr = f"OB-Xf VCO   PW:{int(round(pw*100))}%   XMOD:{int(round(xm*100)):+d}%"
        c.create_text(x0 + 8, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, left_w - 16, self._fs(0.84), bold=True))

        fw = (x1 - rx0 - gap * 2) / 3
        for i, (k, l) in enumerate((("Osc1Mix", "O1"), ("Osc2Mix", "O2"), ("NoiseMix", "NSE"))):
            fx0 = rx0 + i * (fw + gap)
            self._draw_vfader(fx0, gy0, fx0 + fw, gy1, k, l, accent, bank_kind="osc_bank", bank_idx=0)

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Osc", accent)

    # --------------------------------------------------------------------------
    # TAB 2: FILTER (Oberheim 2-Pole Morph + 4-Pole + 15 Xpander Modes + 2D XY)
    # --------------------------------------------------------------------------
    def _draw_tab_filter(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Filter"]
        gap = 6

        # Row 1: Sub-Bank Bar
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Cutoff / Res / Morph", "Xpander / Key / Slop"],
            self.flt_bank, accent, "flt_bank",
        )

        # Row 2: Oberheim Topology Switches (4-Pole, Xpander, BP Blend, 2P Push, Xpander Mode)
        r2_y = y0 + r1_h + gap
        r2_h = 34
        is_4p = self._val(self._get_zctrl("Filter4PoleMode"), 0.0) >= 0.5
        is_xp = self._val(self._get_zctrl("Filter4PoleXpander"), 0.0) >= 0.5
        is_bp = self._val(self._get_zctrl("Filter2PoleBPBlend"), 0.0) >= 0.5
        is_pu = self._val(self._get_zctrl("Filter2PolePush"), 0.0) >= 0.5
        xp_z = self._get_zctrl("FilterXpanderMode")
        pills = [
            ("4-POLE",  is_4p, "Filter4PoleMode"),
            ("XPANDR",  is_xp, "Filter4PoleXpander"),
            ("BP BLD",  is_bp, "Filter2PoleBPBlend"),
            ("2P PUSH", is_pu, "Filter2PolePush"),
            (self._fmt(xp_z, "FilterXpanderMode"), is_xp, "FilterXpanderMode"),
        ]
        pw = (x1 - x0 - gap * 4) / 5
        for i, (lbl, act, key) in enumerate(pills):
            px0 = x0 + i * (pw + gap)
            self._draw_pill(px0, r2_y, px0 + pw, r2_y + r2_h, lbl, act, accent, "cycle", key)

        # Row 3: Interactive 2D Filter Response Graph
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

        cut_n = self._norm(self._get_zctrl("FilterCutoff"), 0.8)
        res_n = self._norm(self._get_zctrl("FilterResonance"), 0.0)
        morph = self._norm(self._get_zctrl("FilterMode"), 0.0)
        xp_idx = max(0, min(len(XPANDER_MODES) - 1, int(round(self._norm(xp_z, 0.0) * (len(XPANDER_MODES) - 1))))) if is_xp else 0

        # Authentic smooth continuous analog SVF / 4-Pole / Xpander transfer function
        zeta = max(0.07, 1.0 - res_n * 0.92)
        pts = []
        for i in range(73):
            xn = i / 72.0
            u = 2.0 ** ((xn - cut_n) * 9.0)
            u2 = u * u
            denom = math.sqrt((1.0 - u2) ** 2 + (2.0 * zeta * u) ** 2)
            h_lp = 1.0 / denom
            h_hp = u2 / denom
            h_bp = (2.0 * max(0.18, zeta) * u) / denom
            h_nt = abs(1.0 - u2) / denom

            if is_xp:
                xname = XPANDER_MODES[xp_idx]
                if xname == "LP4":
                    mag = h_lp * h_lp
                elif xname == "LP3":
                    mag = h_lp * math.sqrt(h_lp)
                elif xname == "LP2":
                    mag = h_lp
                elif xname == "LP1":
                    mag = 1.0 / math.sqrt(1.0 + u2)
                elif xname == "HP3":
                    mag = h_hp * math.sqrt(h_hp)
                elif xname == "HP2":
                    mag = h_hp
                elif xname == "HP1":
                    mag = u / math.sqrt(1.0 + u2)
                elif xname == "BP4":
                    mag = h_bp * h_bp
                elif xname == "BP2":
                    mag = h_bp
                elif xname == "N2":
                    mag = h_nt
                elif xname == "PH3":
                    mag = max(0.15, abs(1.0 - 0.85 * u2) / denom)
                elif "HP" in xname and "LP" in xname:
                    mag = h_hp * (1.0 / math.sqrt(1.0 + u2))
                else:
                    mag = h_nt * (1.0 / math.sqrt(1.0 + u2))
            elif is_4p:
                mag = h_lp * h_lp
            else:
                # Continuous Oberheim SEM 2-Pole morph (no discrete jumps!):
                # BP Blend OFF: (1-m)*LP + m*HP -> exact analog Notch at m=0.5
                # BP Blend ON:  smooth LP -> BP -> HP crossfade
                if is_bp:
                    if morph <= 0.5:
                        k = morph * 2.0
                        mag = (1.0 - k) * h_lp + k * h_bp
                    else:
                        k = (morph - 0.5) * 2.0
                        mag = (1.0 - k) * h_bp + k * h_hp
                else:
                    # Complex sum of LP (1) and HP (-u^2) in SEM produces exact continuous notch!
                    mag = abs((1.0 - morph) - morph * u2) / denom

            db = 20.0 * math.log10(max(1e-4, mag))
            if is_pu and not is_4p and not is_xp:
                db += 3.0 * res_n * math.exp(-((xn - cut_n) / 0.08) ** 2)
            y = max(g_top, min(g_bot, zero_y - (db / 24.0) * (gh * 0.48)))
            pts.extend([gx0 + xn * gw, y])
        c.create_polygon([gx0, g_bot] + pts + [gx1, g_bot], fill="#2b1f14", outline="")
        c.create_line(pts, fill=accent, width=2.6)

        hx, hy = gx0 + cut_n * gw, g_bot - res_n * gh
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        if not is_4p and not is_xp:
            mid_tag = "BP" if is_bp else "NT"
            mode_lbl = f"2P LP↔{mid_tag}↔HP {int(round(morph*100))}%"
        else:
            mode_lbl = self._fmt(xp_z, "FilterXpanderMode") if is_xp else "4-POLE"
        hdr = f"{mode_lbl}   CUT:{self._fmt(self._get_zctrl('FilterCutoff'), 'FilterCutoff')}   RES:{int(round(res_n*100))}%"
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))

        self.hitboxes.append((x0, gy0, x1, gy1, "filter_xy", {"gx0": gx0, "gx1": gx1, "gy0": g_top, "gy1": g_bot}))
        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Filter", accent)

    # --------------------------------------------------------------------------
    # TAB 3: ENV (Interactive 2D Amp + Filter ADSR with Attack Curve & Invert)
    # --------------------------------------------------------------------------
    def _draw_tab_env(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Env"] if self.env_idx == 0 else "#ff922b"
        gap = 6

        # Row 1: Amp / Filter Env Selector + Sub-Bank Bar
        r1_h = 34
        left_w = (x1 - x0) * 0.44
        self._draw_bank_bar(x0, y0, x0 + left_w, y0 + r1_h, ["Amp EG", "Filter EG"], self.env_idx, accent, "env_idx")
        self._draw_bank_bar(x0 + left_w + gap, y0, x1, y0 + r1_h, ["ADSR", "Curve & Mod"], self.env_bank, accent, "env_bank")

        # Row 2: Interactive 2D ADSR Graph
        gy0 = y0 + r1_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        c.create_rectangle(x0, gy0, x1, gy1, fill=COL_PANEL, outline=accent, width=1)

        pad = 14
        gx0, gx1 = x0 + pad, x1 - pad
        g_top, g_bot = gy0 + 24, gy1 - pad
        gw, gh = max(20, gx1 - gx0), max(20, g_bot - g_top)

        ep = "AmpEnv" if self.env_idx == 0 else "FilterEnv"
        a = self._norm(self._get_zctrl(f"{ep}Attack"), 0.0)
        d = self._norm(self._get_zctrl(f"{ep}Decay"), 0.4)
        s = self._norm(self._get_zctrl(f"{ep}Sustain"), 0.7)
        r = self._norm(self._get_zctrl(f"{ep}Release"), 0.3)
        crv = self._norm(self._get_zctrl(f"{ep}AttackCurve"), 0.0)
        xa = gx0 + max(0.03, a) * (gw * 0.28)
        xd = xa + max(0.03, d) * (gw * 0.28)
        xs = xd + gw * 0.16
        xr = min(gx1, xs + max(0.03, r) * (gw * 0.28))
        ys = g_bot - s * gh

        # Curved attack segment
        att_pts = [gx0, g_bot]
        pw_c = 1.0 + crv * 2.5
        for k in range(1, 11):
            t = k / 10.0
            att_pts.extend([gx0 + (xa - gx0) * t, g_bot - (t ** pw_c) * gh])
        pts = att_pts + [xd, ys, xs, ys, xr, g_bot]
        c.create_polygon(pts + [gx0, g_bot], fill="#16291b" if self.env_idx == 0 else "#2b1f14", outline="")
        c.create_line(pts, fill=accent, width=2.6)
        for hx, hy in ((xa, g_top), (xd, ys), (xr, g_bot)):
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)

        hdr = f"{'AMP' if self.env_idx == 0 else 'FILTER'} EG   A:{int(round(a*100))}%  D:{int(round(d*100))}%  S:{int(round(s*100))}%  R:{int(round(r*100))}%"
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))

        self.hitboxes.append((
            x0, gy0, x1, gy1, "env_graph",
            {"ep": ep, "gx0": gx0, "gw": gw, "g_top": g_top, "g_bot": g_bot,
             "xa": xa, "xd": xd, "xs": xs, "xr": xr, "ys": ys},
        ))
        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Env", accent)

    # --------------------------------------------------------------------------
    # TAB 4: LFO (Dual LFO 1 & LFO 2 Wave Morph + 6 Target Routing Switches)
    # --------------------------------------------------------------------------
    def _draw_tab_lfo(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["LFO"]
        li = self.lfo_idx + 1
        gap = 6

        # Row 1: LFO 1 / LFO 2 + Sub-Bank Bar
        r1_h = 34
        left_w = (x1 - x0) * 0.40
        self._draw_bank_bar(x0, y0, x0 + left_w, y0 + r1_h, ["LFO 1", "LFO 2"], self.lfo_idx, accent, "lfo_idx")
        self._draw_bank_bar(x0 + left_w + gap, y0, x1, y0 + r1_h, ["Rate & Amt", "Wave Morph"], self.lfo_bank, accent, "lfo_bank")

        # Row 2: 6 Direct OB-Xf LFO Target Routing Switches (Off / Fwd / Rev)
        r2_y = y0 + r1_h + gap
        r2_h = 34
        dests = [
            ("Flt", f"LFO{li}ToFilterCutoff"),
            ("O1P", f"LFO{li}ToOsc1Pitch"),
            ("O2P", f"LFO{li}ToOsc2Pitch"),
            ("O1W", f"LFO{li}ToOsc1PW"),
            ("O2W", f"LFO{li}ToOsc2PW"),
            ("Vol", f"LFO{li}ToVolume"),
        ]
        sgap = 4
        dw = (x1 - x0 - sgap * 5) / 6
        for i, (lbl, key) in enumerate(dests):
            dx0 = x0 + i * (dw + sgap)
            v = self._val(self._get_zctrl(key), 0.0)
            st = self._fmt(self._get_zctrl(key), key)
            self._draw_pill(dx0, r2_y, dx0 + dw, r2_y + r2_h, lbl, v >= 0.25, accent,
                            "cycle", key, subtext=st)

        # Row 3: Live OB-Xf Multi-Wave Morphing LFO Scope
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

        rate = self._norm(self._get_zctrl(f"LFO{li}Rate"), 0.2)
        w1 = self._val(self._get_zctrl(f"LFO{li}Wave1"), 0.0)
        w2 = self._val(self._get_zctrl(f"LFO{li}Wave2"), 0.0)
        w3 = self._val(self._get_zctrl(f"LFO{li}Wave3"), 0.0)
        pw = self._val(self._get_zctrl(f"LFO{li}PW"), 0.5)
        cycles = 1.5 + rate * 5.0
        pts = []
        for i in range(97):
            t = i / 96.0
            p = (t * cycles) % 1.0
            sin_v = math.sin(2.0 * math.pi * p)
            tri_v = 1.0 - 4.0 * abs(p - 0.5)
            pls_v = 1.0 if p < pw else -1.0
            saw_v = 1.0 - 2.0 * p
            sh_v = math.sin(int(t * cycles * 2.0) * 12.9898 + 1.23) * 0.9
            # Blend according to OB-Xf's 3 bipolar wave knobs
            y = (sin_v if w1 < 0 else tri_v) * abs(w1) + (pls_v if w2 < 0 else saw_v) * abs(w2) + sh_v * abs(w3)
            norm_s = abs(w1) + abs(w2) + abs(w3)
            y = (y / norm_s) if norm_s > 0.05 else sin_v
            pts.extend([gx0 + t * gw, mid_y - max(-1.0, min(1.0, y)) * amp])
        c.create_line(pts, fill=accent, width=2.4)
        hdr = f"LFO {li}   RATE:{int(round(rate*100))}%   SYNC:{self._fmt(self._get_zctrl(f'LFO{li}TempoSync'), f'LFO{li}TempoSync')}"
        c.create_text(x0 + 10, gy0 + 11, text=hdr, anchor="w", fill=accent,
                      font=self._fit_font(hdr, (x1 - x0) - 20, self._fs(0.84), bold=True))

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "LFO", accent)

    # --------------------------------------------------------------------------
    # TAB 5: VOICES (Iconic Oberheim 8-Voice Stereo Pan Spread + Unison/Slop)
    # --------------------------------------------------------------------------
    def _draw_tab_voices(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Voices"]
        gap = 6

        # Row 1: Encoder Sub-Bank Bar + Unison Toggle
        r1_h = 34
        left_w = (x1 - x0) * 0.76
        self._draw_bank_bar(
            x0, y0, x0 + left_w, y0 + r1_h,
            ["Pan V1-4", "Pan V5-8", "Unison & Slop"],
            self.voice_bank, accent, "voice_bank",
        )
        uni_on = self._val(self._get_zctrl("Unison"), 0.0) >= 0.5
        self._draw_pill(x0 + left_w + gap, y0, x1, y0 + r1_h,
                        "●UNISON" if uni_on else "UNISON", uni_on, "#51cf66", "cycle", "Unison")

        # Row 2: 8 Bipolar Oberheim Voice Pan Vertical Faders (V1..V8)
        gy0 = y0 + r1_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        sgap = 4
        fw = (x1 - x0 - sgap * 7) / 8
        for i in range(8):
            fx0 = x0 + i * (fw + sgap)
            b_idx = 0 if i < 4 else 1
            col = "#4dabf7" if i < 4 else "#38d9a9"
            self._draw_vfader(fx0, gy0, fx0 + fw, gy1, f"PanVoice{i + 1}", f"V{i + 1}", col,
                              bank_kind="voice_bank", bank_idx=b_idx, bipolar=True)

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Voices", accent)

    # --------------------------------------------------------------------------
    # TAB 6: PERF (Polyphony, HQ Mode, Vibrato, Velocity, Pitch Bend, Master)
    # --------------------------------------------------------------------------
    def _draw_tab_perf(self, x0, y0, x1, y1):
        c = self.widget_canvas
        accent = TAB_ACCENTS["Perf"]
        gap = 6

        # Row 1: Encoder Sub-Bank Bar
        r1_h = 34
        self._draw_bank_bar(
            x0, y0, x1, y0 + r1_h,
            ["Master & Glide", "Vibrato & Bend", "Poly & Velocity"],
            self.perf_bank, accent, "perf_bank",
        )

        # Row 2: Quick Performance Tiles
        r2_y = y0 + r1_h + gap
        r2_h = 38
        quick = [
            ("HQ Mode", "HQMode"),
            ("Priority","NotePriority"),
            ("Legato",  "EnvLegatoMode"),
            ("VibWave", "VibratoWave"),
        ]
        qw = (x1 - x0 - gap * 3) / 4
        for i, (lbl, key) in enumerate(quick):
            qx0 = x0 + i * (qw + gap)
            z = self._get_zctrl(key)
            act = (key == "HQMode" and self._val(z, 0.0) >= 0.5)
            self._draw_pill(qx0, r2_y, qx0 + qw, r2_y + r2_h, lbl, act, accent,
                            "cycle", key, subtext=self._fmt(z, key))

        # Row 3: 5 Vertical Performance Faders
        gy0 = r2_y + r2_h + gap
        bot_h = 84
        gy1 = y1 - bot_h - gap
        faders = [
            ("Volume",         "VOL",   "#51cf66", 0),
            ("Portamento",     "GLIDE", "#4dabf7", 0),
            ("VibratoRate",    "VIB",   "#ffd43b", 1),
            ("VelToAmpEnv",    "V>AMP", "#cc5de8", 2),
            ("VelToFilterEnv", "V>FLT", "#ff922b", 2),
        ]
        fw = (x1 - x0 - gap * 4) / 5
        for i, (key, lbl, col, b_idx) in enumerate(faders):
            fx0 = x0 + i * (fw + gap)
            self._draw_vfader(fx0, gy0, fx0 + fw, gy1, key, lbl, col,
                              bank_kind="perf_bank", bank_idx=b_idx)

        self._draw_bottom_grid(x0, gy1 + gap, x1, y1, "Perf", accent)

    # --------------------------------------------------------------------------
    # ECO CPU Tamer (disables HQ Mode, caps Polyphony -> 8v, Unison -> 3v)
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
            z_hq = self._get_zctrl("HQMode")
            if z_hq is not None:
                self._eco_backup["HQMode"] = self._val(z_hq, 0.0)
                self._set_raw(z_hq, 0)
            z_p = self._get_zctrl("Polyphony")
            if z_p is not None:
                cur_p = int(round(self._val(z_p, 8)))
                self._eco_backup["Polyphony"] = cur_p
                if cur_p > 8:
                    self._set_raw(z_p, 8)
            z_u = self._get_zctrl("UnisonVoices")
            if z_u is not None:
                cur_u = int(round(self._val(z_u, 2)))
                self._eco_backup["UnisonVoices"] = cur_u
                if cur_u > 3:
                    self._set_raw(z_u, 3)
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

        if kind in ("osc_bank", "flt_bank", "env_idx", "env_bank", "lfo_idx", "lfo_bank", "voice_bank", "perf_bank"):
            self._switch_subbank(kind, payload)
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
            tap_id = ("filter_xy", "obxf")
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                for rk in ("FilterCutoff", "FilterResonance"):
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
            ep = payload["ep"]
            d_a = abs(event.x - payload["xa"])
            d_ds = math.hypot(event.x - payload["xd"], event.y - payload["ys"])
            d_r = abs(event.x - payload["xr"])
            node = "A" if (d_a <= d_ds and d_a <= d_r) else ("DS" if d_ds <= d_r else "R")
            now = time.monotonic()
            tap_id = ("env_graph", ep, node)
            if tap_id == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                self.last_tap = (None, 0.0)
                rkeys = [f"{ep}Attack"] if node == "A" else ([f"{ep}Decay", f"{ep}Sustain"] if node == "DS" else [f"{ep}Release"])
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
            gx0, gx1, gy0, gy1 = payload["gx0"], payload["gx1"], payload["gy0"], payload["gy1"]
            if gx1 > gx0:
                self._set_norm(self._get_zctrl("FilterCutoff"), (x - gx0) / (gx1 - gx0))
            if gy1 > gy0:
                self._set_norm(self._get_zctrl("FilterResonance"), (gy1 - y) / (gy1 - gy0))
        elif kind == "env_node":
            ep = payload["ep"]
            gx0, gw = payload["gx0"], payload["gw"]
            g_top, g_bot = payload["g_top"], payload["g_bot"]
            seg_w = max(10.0, gw * 0.28)
            node = payload["node"]
            if node == "A":
                self._set_norm(self._get_zctrl(f"{ep}Attack"), (x - gx0) / seg_w)
            elif node == "DS":
                self._set_norm(self._get_zctrl(f"{ep}Decay"), (x - payload["xa"]) / seg_w)
                if g_bot > g_top:
                    self._set_norm(self._get_zctrl(f"{ep}Sustain"), (g_bot - y) / (g_bot - g_top))
            elif node == "R":
                self._set_norm(self._get_zctrl(f"{ep}Release"), (x - payload["xs"]) / seg_w)

        self.last_snapshot = None
        self._draw()


# Register hyphenated class alias required by Zynthian's widget loader for "OB-Xf"
globals()["zynthian_widget_ob-xf"] = zynthian_widget_ob_xf
