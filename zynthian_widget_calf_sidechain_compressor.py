#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Calf Sidechain Compressor Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 4 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Comp | Time | S/C EQ | S/C Route   + SC Listen + ON/BYP
#
# Full live visualization:
#   - Two-tier monitoring engine: real LV2 OutputPorts (compression, meter_in,
#     meter_out, clip_in, clip_out, f1_active, f2_active) + DSP Predictive
#     Sidechain Simulation fallback when monitors are silent or unavailable.
#   - Comp tab: accurate transfer curve (Threshold x Ratio x Knee x Makeup x
#     Mix), vertical GR meter (0..-30 dB) with peak-hold & clip LEDs, live
#     operating point crosshair (In dB, Out dB), and dual interactive handles
#     (Knee node: Threshold x Makeup; Slope handle: Ratio).
#   - Time tab: live 2.0s Ducking Scope oscilloscope showing sidechain pulses
#     above threshold and anti-phase ducking envelope (Attack/Release), plus
#     RMS/Peak, Stereo Link Avg/Max, LIVE/SIM toggle, and 2D Attack x Release.
#   - S/C EQ tab: accurate 10-mode filter response with two independent
#     color-coded 2D touch nodes (F1 blue, F2 orange) controlling Freq x Gain
#     plus quick mode stepping.
#   - S/C Route tab: Internal/External routing, SC Listen, 2x5 mode selector.
# ******************************************************************************

from collections import deque
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

COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

COL_F1 = "#4dabf7"
COL_F2 = "#ff922b"
COL_GR_LOW = "#ffa94d"
COL_GR_MID = "#ff922b"
COL_GR_HIGH = "#ff6b6b"
COL_CLIP = "#ff4d4f"
COL_LIVE = "#51cf66"
COL_SIM = "#ffd43b"

TABS = ["Comp", "Time", "S/C EQ", "S/C Route"]
TAB_ACCENTS = {
    "Comp":      "#ff922b",
    "Time":      "#51cf66",
    "S/C EQ":    "#4dabf7",
    "S/C Route": "#cc5de8",
}

SC_MODES_SHORT = [
    "Wideband",
    "DeEss Wide",
    "DeEss Splt",
    "DeRmb Wide",
    "DeRmb Splt",
    "Weight #1",
    "Weight #2",
    "Weight #3",
    "Bandpass 1",
    "Bandpass 2",
]

SC_MODES_DESC = [
    "Wideband (F1:off / F2:off)",
    "Deesser wide (F1:Bell / F2:HP)",
    "Deesser split (F1:off / F2:HP)",
    "Derumbler wide (F1:LP / F2:Bell)",
    "Derumbler split (F1:LP / F2:off)",
    "Weighted #1 (F1:Shelf / F2:Shelf)",
    "Weighted #2 (F1:Shelf / F2:Bell)",
    "Weighted #3 (F1:Bell / F2:Shelf)",
    "Bandpass #1 (F1:BP / F2:off)",
    "Bandpass #2 (F1:HP / F2:LP)",
]

# Per-mode filter topology: (f1_type, f2_type)
# Types: "off", "bell", "hp", "lp", "lshelf", "hshelf", "bp"
SC_MODE_FILTERS = [
    ("off",    "off"),     # 0: Wideband
    ("bell",   "hp"),      # 1: Deesser wide
    ("off",    "hp"),      # 2: Deesser split
    ("lp",     "bell"),    # 3: Derumbler wide
    ("lp",     "off"),     # 4: Derumbler split
    ("lshelf", "hshelf"),  # 5: Weighted #1
    ("lshelf", "bell"),    # 6: Weighted #2
    ("bell",   "hshelf"),  # 7: Weighted #3
    ("bp",     "off"),     # 8: Bandpass #1
    ("hp",     "lp"),      # 9: Bandpass #2
]

GAIN_FILTER_TYPES = {"bell", "lshelf", "hshelf"}

LOG_KEYS = {
    "threshold", "ratio", "attack", "release", "makeup", "knee",
    "level_in", "f1_freq", "f2_freq", "f1_level", "f2_level", "sc_level",
}

SCOPE_WINDOW_S = 2.0
SCOPE_SAMPLES = 36
LIVE_ACTIVITY_HOLD_S = 2.2
DRAG_SIM_HOLD_S = 3.0
PEAK_HOLD_S = 1.15
PEAK_DECAY_DB_PER_S = 14.0


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.2f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


def fmt_ms(ms):
    if ms >= 1000.0:
        return f"{ms / 1000.0:.2f}s"
    if ms >= 10.0:
        return f"{ms:.0f}ms"
    return f"{ms:.2f}ms"


def fmt_db(gain):
    if gain <= 1e-5:
        return "-60dB"
    return f"{20.0 * math.log10(gain):+.1f}dB"


def lin_to_db(val, floor_db=-60.0):
    if val <= 1e-6:
        return floor_db
    return max(floor_db, 20.0 * math.log10(val))


def db_to_lin(db):
    return 10.0 ** (db / 20.0)


def compute_transfer_db(in_db, thr_db, ratio, knee_db, makeup_db, mix=1.0):
    """Return (out_db, gr_db) for static compressor transfer characteristic.

    gr_db is <= 0.0 (negative gain reduction in dB).
    Includes soft-knee quadratic transition, full makeup gain, and parallel mix.
    """
    ratio = max(1.0, float(ratio))
    knee_db = max(0.0, float(knee_db))
    diff = in_db - thr_db
    if knee_db > 0.15 and abs(diff) < knee_db:
        gr_db = ((1.0 / ratio) - 1.0) * ((diff + knee_db) ** 2) / (4.0 * knee_db)
    elif diff > 0.0:
        gr_db = diff * ((1.0 / ratio) - 1.0)
    else:
        gr_db = 0.0

    wet_db = in_db + gr_db + makeup_db
    if mix >= 0.999:
        out_db = wet_db
    elif mix <= 0.001:
        out_db = in_db
    else:
        dry_lin = db_to_lin(in_db)
        wet_lin = db_to_lin(wet_db)
        out_db = lin_to_db((1.0 - mix) * dry_lin + mix * wet_lin, floor_db=-72.0)
    return out_db, gr_db


def eval_filter_db(ftype, freq, fc, gain_db):
    """Evaluate smooth magnitude response (in dB) for a single S/C EQ band."""
    if ftype == "off":
        return 0.0
    fc = max(10.0, float(fc))
    r = max(1e-4, float(freq) / fc)
    octaves = math.log2(r)
    if ftype == "hp":
        # 2nd-order Butterworth high-pass (-3 dB at fc, 12 dB/oct rolloff)
        return -10.0 * math.log10(1.0 + (1.0 / r) ** 4)
    if ftype == "lp":
        # 2nd-order Butterworth low-pass (-3 dB at fc, 12 dB/oct rolloff)
        return -10.0 * math.log10(1.0 + r ** 4)
    if ftype == "bp":
        # 2nd-order bandpass (Q ~ 1.0)
        q = 1.0
        denom = 1.0 + (q * (r - 1.0 / r)) ** 2
        return -10.0 * math.log10(denom)
    if ftype == "bell":
        # Smooth bell peak centered at fc (bandwidth ~1.2 octaves)
        return gain_db * math.exp(-(octaves ** 2) / 0.55)
    if ftype == "lshelf":
        # Smooth low shelf transitioning around fc
        return gain_db / (1.0 + math.exp(octaves * 2.4))
    if ftype == "hshelf":
        # Smooth high shelf transitioning around fc
        return gain_db / (1.0 + math.exp(-octaves * 2.4))
    return 0.0


class zynthian_widget_calf_sidechain_compressor(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Comp"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}
        self._tk_font_cache = {}

        # Monitoring & simulation state
        self._has_lv2_monitors = False
        self._last_live_ts = 0.0
        self._last_interact_ts = 0.0
        self._force_sim = False
        self._active_sim_mode = False
        self._last_tick_ts = time.monotonic()

        # Live telemetry values
        self._in_db = -60.0
        self._out_db = -60.0
        self._gr_db = 0.0        # <= 0.0
        self._gr_peak_db = 0.0   # <= 0.0
        self._gr_peak_ts = 0.0
        self._clip_in = False
        self._clip_out = False
        self._f1_active_mon = None
        self._f2_active_mon = None

        # Rolling history for LIVE Ducking Scope: deque of (in_db, gr_db)
        self._live_history = deque([(-60.0, 0.0)] * SCOPE_SAMPLES, maxlen=SCOPE_SAMPLES)

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
        pid = id(processor)
        self._build_ctrl_index(processor)
        if self._bound_proc_id != pid:
            self._bound_proc_id = pid
            self._rebuild_pages()

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
            for cand in (sym, getattr(z, "symbol", ""), getattr(z, "name", "")):
                k = _norm_key(cand)
                if k and k not in idx:
                    idx[k] = z
        self._ctrl_index = idx

    def _get_zctrl(self, sym):
        return self._ctrl_index.get(_norm_key(sym)) if self.processor else None

    def get_monitors(self):
        try:
            if self.processor and getattr(self.processor, "engine", None):
                fn = getattr(self.processor.engine, "get_monitors_dict", None)
                if callable(fn):
                    self.monitors = fn()
                    return
        except Exception:
            pass
        self.monitors = {}

    def _get_mon(self, key):
        mons = self.monitors
        if not isinstance(mons, dict) or not mons:
            return None
        if key in mons:
            try:
                return float(mons[key])
            except Exception:
                return None
        nk = _norm_key(key)
        for mk, mv in mons.items():
            nmk = _norm_key(mk)
            if nmk == nk or nmk.endswith("_" + nk):
                try:
                    return float(mv)
                except Exception:
                    return None
        return None

    def _tab_items(self, tab):
        if tab == "Comp":
            return [
                ("threshold", "Threshold"),
                ("ratio",     "Ratio"),
                ("knee",      "Knee"),
                ("makeup",    "Makeup"),
            ]
        if tab == "Time":
            return [
                ("attack",   "Attack"),
                ("release",  "Release"),
                ("mix",      "Mix"),
                ("level_in", "In Gain"),
            ]
        if tab == "S/C EQ":
            return [
                ("f1_freq",  "F1 Freq"),
                ("f1_level", "F1 Gain"),
                ("f2_freq",  "F2 Freq"),
                ("f2_level", "F2 Gain"),
            ]
        return [
            ("sc_mode",  "S/C Mode"),
            ("sc_level", "S/C Gain"),
            ("mix",      "Mix"),
            ("makeup",   "Makeup"),
        ]

    def _rebuild_pages(self):
        if not self.processor:
            return
        screens = {}
        for t in TABS:
            zlist = []
            for k, lbl in self._tab_items(t):
                z = self._get_zctrl(k)
                if z is not None:
                    z.short_name = lbl
                    zlist.append(z)
            if zlist:
                screens[t] = zlist
        if screens:
            self.processor.ctrl_screens_dict = screens
            self.after(25, lambda: self._sync_list(self.active_tab))

    def _sync_list(self, tab):
        try:
            if not self.processor or self.zyngui_control.get_current_processor() is not self.processor:
                return
            self.zyngui_control.fill_list()
            self._select_page(tab)
            self._draw()
        except Exception as e:
            logging.debug(f"Calf SC Comp sync error: {e}")

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
            v = max(vmin, min(vmax, v))
            if key in LOG_KEYS and vmin > 0:
                return math.log(v / vmin) / math.log(vmax / vmin)
            return (v - vmin) / (vmax - vmin)
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
        val = vmin * ((vmax / vmin) ** n) if (key in LOG_KEYS and vmin > 0) else (vmin + n * (vmax - vmin))
        if getattr(z, "is_integer", False) or key in ("sc_mode", "detection", "stereo_link"):
            val = int(round(val))
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _set_raw_clamped(z, val):
        if z is None:
            return
        vmin, vmax = float(z.value_min), float(z.value_max)
        z.set_value(max(vmin, min(vmax, float(val))), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_calf_sidechain_compressor._raw(z)
        if key == "threshold":
            return fmt_db(v)
        if key == "ratio":
            return f"{v:.1f}:1"
        if key == "knee":
            return f"{20.0 * math.log10(max(1.0, v)):.1f}dB"
        if key in ("attack", "release"):
            return fmt_ms(v)
        if key == "mix":
            return f"{int(round(v * 100))}%"
        if key in ("f1_freq", "f2_freq"):
            return fmt_hz(v)
        if key in ("makeup", "level_in", "f1_level", "f2_level", "sc_level"):
            return fmt_db(v)
        if key == "sc_mode":
            idx = max(0, min(len(SC_MODES_SHORT) - 1, int(round(v))))
            return SC_MODES_SHORT[idx]
        return f"{v:.2f}"

    def _get_dsp_params(self):
        byp = self._raw(self._get_zctrl("bypass"), 0.0) >= 0.5
        thr_db = lin_to_db(self._raw(self._get_zctrl("threshold"), 0.125), floor_db=-60.0)
        ratio = max(1.0, self._raw(self._get_zctrl("ratio"), 2.0))
        knee_db = max(0.0, lin_to_db(max(1.0, self._raw(self._get_zctrl("knee"), 2.82843)), floor_db=0.0))
        makeup_db = max(0.0, lin_to_db(max(1.0, self._raw(self._get_zctrl("makeup"), 1.0)), floor_db=0.0))
        attack_ms = max(0.01, self._raw(self._get_zctrl("attack"), 20.0))
        release_ms = max(0.01, self._raw(self._get_zctrl("release"), 250.0))
        mix = max(0.0, min(1.0, self._raw(self._get_zctrl("mix"), 1.0)))
        in_gain_db = lin_to_db(self._raw(self._get_zctrl("level_in"), 1.0), floor_db=-36.0)
        sc_gain_db = lin_to_db(self._raw(self._get_zctrl("sc_level"), 1.0), floor_db=-36.0)
        return {
            "bypass": byp,
            "thr_db": thr_db,
            "ratio": ratio,
            "knee_db": knee_db,
            "makeup_db": makeup_db,
            "attack_ms": attack_ms,
            "release_ms": release_ms,
            "mix": mix,
            "in_gain_db": in_gain_db,
            "sc_gain_db": sc_gain_db,
        }

    def _simulate_scope(self, now, params, n_pts=72):
        """Run deterministic DSP sidechain compressor envelope follower over a
        scrolling 2.0s window (120 BPM four-on-the-floor kick pulse train).

        Returns list of (t_norm, sc_db, gr_db, eff_gr_db) from oldest (0.0) to
        newest (1.0). Because the entire window is evaluated for the current
        Attack/Release/Threshold/Ratio/Knee/Mix parameters, parameter tweaks
        deform all pulses on screen instantaneously.
        """
        beat_s = 0.50  # 120 BPM
        byp = params["bypass"]
        thr_db = params["thr_db"]
        ratio = params["ratio"]
        knee_db = params["knee_db"]
        mix = params["mix"]
        sc_boost = max(-24.0, min(18.0, params["sc_gain_db"] * 0.5))

        # Pre-roll 1.0s before the visible window so attack/release reaches steady state
        pre_s = 1.0
        total_s = SCOPE_WINDOW_S + pre_s
        dt = SCOPE_WINDOW_S / max(1, n_pts - 1)
        total_steps = int(round(total_s / dt)) + 1
        t_start = now - total_s

        att_s = max(0.002, params["attack_ms"] / 1000.0)
        rel_s = max(0.005, params["release_ms"] / 1000.0)
        c_att = 1.0 - math.exp(-dt / att_s)
        c_rel = 1.0 - math.exp(-dt / rel_s)

        env_gr_db = 0.0
        out = []
        vis_start_idx = total_steps - n_pts

        for i in range(total_steps):
            t = t_start + i * dt
            # Kick pulse phase within 0.5s beat
            bp = (t % beat_s) / beat_s  # 0..1
            if bp < 0.03:
                # Punchy transient rise
                env_lin = 0.08 + 0.84 * (bp / 0.03)
            elif bp < 0.22:
                # Kick body exponential decay
                env_lin = 0.08 + 0.84 * math.exp(-(bp - 0.03) * 12.0)
            else:
                # Subtle rhythmic tail / room floor
                env_lin = 0.075 + 0.015 * math.sin(bp * math.pi)
            sc_db = max(-60.0, min(0.0, lin_to_db(env_lin, floor_db=-60.0) + sc_boost))

            if byp:
                target_gr = 0.0
            else:
                _, target_gr = compute_transfer_db(sc_db, thr_db, ratio, knee_db, 0.0, mix=1.0)
                target_gr = max(-30.0, min(0.0, target_gr))

            # Attack when going deeper (more negative), release when recovering toward 0
            if target_gr < env_gr_db:
                env_gr_db += c_att * (target_gr - env_gr_db)
            else:
                env_gr_db += c_rel * (target_gr - env_gr_db)

            if i >= vis_start_idx:
                idx = i - vis_start_idx
                t_norm = idx / max(1, n_pts - 1)
                # Effective parallel-blended attenuation in dB
                if mix >= 0.999:
                    eff_gr = env_gr_db
                elif mix <= 0.001:
                    eff_gr = 0.0
                else:
                    eff_lin = (1.0 - mix) + mix * db_to_lin(env_gr_db)
                    eff_gr = lin_to_db(eff_lin, floor_db=-30.0)
                out.append((t_norm, sc_db, env_gr_db, eff_gr))
        return out

    def _update_telemetry(self, now):
        dt = max(0.001, min(0.5, now - self._last_tick_ts))
        self._last_tick_ts = now

        mon_comp = self._get_mon("compression")
        mon_in = self._get_mon("meter_in")
        mon_out = self._get_mon("meter_out")
        mon_clip_in = self._get_mon("clip_in")
        mon_clip_out = self._get_mon("clip_out")
        mon_f1_act = self._get_mon("f1_active")
        mon_f2_act = self._get_mon("f2_active")

        self._f1_active_mon = (mon_f1_act >= 0.5) if mon_f1_act is not None else None
        self._f2_active_mon = (mon_f2_act >= 0.5) if mon_f2_act is not None else None

        self._has_lv2_monitors = (mon_comp is not None) or (mon_in is not None) or (mon_out is not None)

        live_signal = False
        if self._has_lv2_monitors:
            if (mon_in is not None and mon_in > 0.0015) or (mon_out is not None and mon_out > 0.0015):
                live_signal = True
            if mon_comp is not None and mon_comp < 0.997:
                live_signal = True
            if live_signal:
                self._last_live_ts = now

        is_live = self._has_lv2_monitors and (now - self._last_live_ts) < LIVE_ACTIVITY_HOLD_S and not self._force_sim

        # Decide whether SIM predictive fallback is active
        use_sim = False
        if not is_live:
            if self._force_sim:
                use_sim = True
            elif not self._has_lv2_monitors:
                use_sim = True
            elif self.active_tab == "Time":
                # Ducking Scope stays alive with predictive envelope when no live audio
                use_sim = True
            elif self.active_tab == "Comp" and (self.drag_target is not None or (now - self._last_interact_ts) < DRAG_SIM_HOLD_S):
                # Responsive DSP preview during/just after tweaking Comp controls offline
                use_sim = True

        self._active_sim_mode = use_sim
        params = self._get_dsp_params()

        if is_live:
            in_db = lin_to_db(mon_in if mon_in is not None else 0.0, floor_db=-60.0)
            gr_db = 0.0 if params["bypass"] else max(-30.0, min(0.0, lin_to_db(max(0.03125, mon_comp if mon_comp is not None else 1.0), floor_db=-30.0)))
            if mon_out is not None:
                out_db = lin_to_db(mon_out, floor_db=-60.0)
            else:
                out_db, _ = compute_transfer_db(in_db, params["thr_db"], params["ratio"], params["knee_db"], params["makeup_db"], params["mix"])
            self._in_db = in_db
            self._gr_db = gr_db
            self._out_db = out_db
            self._clip_in = bool(mon_clip_in is not None and mon_clip_in >= 0.5)
            self._clip_out = bool(mon_clip_out is not None and mon_clip_out >= 0.5)
            self._live_history.append((in_db, gr_db))
        elif use_sim:
            # Evaluate single instantaneous sample from the predictive model
            sim = self._simulate_scope(now, params, n_pts=48)
            _, sc_db, gr_db, eff_gr = sim[-1]
            self._in_db = sc_db
            self._gr_db = gr_db
            if params["bypass"]:
                self._out_db = sc_db
            else:
                self._out_db = max(-60.0, min(18.0, sc_db + eff_gr + params["makeup_db"] * params["mix"]))
            self._clip_in = sc_db >= -0.3
            self._clip_out = self._out_db >= -0.3
        else:
            # Idle with LV2 monitors present (silent audio)
            self._in_db = -60.0
            self._gr_db = 0.0
            self._out_db = -60.0
            self._clip_in = False
            self._clip_out = False
            self._live_history.append((-60.0, 0.0))

        # Update GR peak hold (most negative dB)
        if self._gr_db <= self._gr_peak_db - 0.05:
            self._gr_peak_db = self._gr_db
            self._gr_peak_ts = now
        elif (now - self._gr_peak_ts) > PEAK_HOLD_S:
            self._gr_peak_db = min(0.0, self._gr_peak_db + PEAK_DECAY_DB_PER_S * dt)
            if self._gr_peak_db > self._gr_db:
                self._gr_peak_db = self._gr_db

        return is_live, use_sim

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
        now = time.monotonic()

        keys = ("bypass", "level_in", "threshold", "ratio", "attack", "release",
                "makeup", "knee", "detection", "stereo_link", "sc_mode",
                "f1_freq", "f2_freq", "f1_level", "f2_level",
                "sc_listen", "sc_route", "sc_level", "mix")
        param_vals = tuple(round(self._raw(self._get_zctrl(k)), 3) for k in keys)

        # Detect encoder/external parameter changes to trigger brief SIM preview on Comp when silent
        prev_params = self.last_snapshot[3] if (self.last_snapshot and len(self.last_snapshot) >= 4) else None
        if prev_params is not None and param_vals != prev_params:
            self._last_interact_ts = now

        is_live, use_sim = self._update_telemetry(now)

        # Animation tick only when actively animating on Comp or Time tabs (CPU friendly!)
        if self.active_tab == "Time" and (is_live or use_sim):
            anim_tok = int(now / UPDATE_PERIOD)
        elif self.active_tab == "Comp" and (is_live or use_sim or self._gr_peak_db < -0.1):
            anim_tok = (round(self._in_db, 1), round(self._gr_db, 1), round(self._gr_peak_db, 1),
                        round(self._out_db, 1), self._clip_in, self._clip_out, is_live, use_sim)
        else:
            anim_tok = (is_live, use_sim, self._f1_active_mon, self._f2_active_mon, round(self._gr_db, 1))

        snap = (self.width, self.height, self.active_tab, param_vals, self._force_sim, anim_tok)
        if snap != self.last_snapshot:
            self.last_snapshot = snap
            self._draw()

    def _font(self, size, bold=False):
        key = (size, bold)
        if key not in self._font_cache:
            fam = zynthian_gui_config.font_family
            self._font_cache[key] = (fam, size, "bold") if bold else (fam, size)
        return self._font_cache[key]

    def _fit_font(self, text, max_w, size, bold=False, min_size=7):
        fam = zynthian_gui_config.font_family
        s = int(size)
        txt = str(text)
        while s > min_size:
            k = (s, bold)
            tf = self._tk_font_cache.get(k)
            if tf is None:
                try:
                    tf = tkinter.font.Font(family=fam, size=s, weight="bold" if bold else "normal")
                except Exception:
                    tf = None
                self._tk_font_cache[k] = tf
            if tf is None:
                break
            if tf.measure(txt) <= max_w:
                break
            s -= 1
        return self._font(s, bold=bold)

    def _fs(self, scale=1.0):
        base = max(9, min(13, self.height // 34))
        return max(8, int(round(base * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        fnt = self._fit_font(text, max(16, (x1 - x0) - 6), self._fs(0.86), bold=True)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                      fill="#0d0e12" if active else COL_TEXT, font=fnt)
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z, key)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        tx0, tx1 = x0 + 8, x1 - 8
        by1 = y1 - 6
        by0 = by1 - 11
        val_txt = self._fmt(z, key)
        avail = max(24, (tx1 - tx0) - 6)
        lbl_f = self._fit_font(label, avail * 0.50, self._fs(0.82), bold=False)
        val_f = self._fit_font(val_txt, avail * 0.50, self._fs(0.86), bold=True)
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM, font=lbl_f)
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=val_txt, anchor="e", fill=COL_TEXT, font=val_f)
        c.create_rectangle(tx0, by0, tx1, by1, fill=COL_TRACK, outline="")
        fx = tx0 + n * (tx1 - tx0)
        if fx > tx0 + 1:
            c.create_rectangle(tx0, by0, fx, by1, fill=accent, outline="")
        c.create_line(fx, by0, fx, by1, fill="#ffffff", width=2)
        self.hitboxes.append((x0, y0, x1, y1, "hfader", {"key": key, "tx0": tx0, "tx1": tx1}))

    def _draw_status_badge(self, x1, y_mid, is_live, use_sim):
        c = self.widget_canvas
        if is_live:
            txt, col = "● LIVE", COL_LIVE
        elif use_sim:
            txt, col = "◈ SIM", COL_SIM
        else:
            txt, col = "○ IDLE", COL_DIM
        c.create_text(x1, y_mid, text=txt, anchor="e", fill=col,
                      font=self._font(self._fs(0.76), bold=True))

    # --------------------------------------------------------------------------
    # Tab 1: Comp (Transfer Curve + GR Meter + Crosshair + Knee & Ratio Nodes)
    # --------------------------------------------------------------------------
    def _draw_comp_tab(self, pad, gap, vy0, vy1, w, accent, byp):
        c = self.widget_canvas
        params = self._get_dsp_params()
        now = time.monotonic()
        is_live = self._has_lv2_monitors and (now - self._last_live_ts) < LIVE_ACTIVITY_HOLD_S and not self._force_sim
        use_sim = self._active_sim_mode

        gr_w = max(76, min(98, int(w * 0.145)))
        curve_x0 = pad
        curve_x1 = w - pad - gr_w - gap
        gr_x0 = curve_x1 + gap
        gr_x1 = w - pad

        # --- Left panel: Transfer Curve ---
        c.create_rectangle(curve_x0, vy0, curve_x1, vy1, fill=COL_PANEL,
                           outline=accent if not byp else COL_BORDER, width=1)
        gx0 = curve_x0 + 30
        gx1 = curve_x1 - 12
        gy0 = vy0 + 22
        gy1 = vy1 - 18
        gw = max(24, gx1 - gx0)
        gh = max(24, gy1 - gy0)

        hdr_txt = "Transfer  (Knee: Thr×Mkp  |  Edge: Ratio)"
        c.create_text(curve_x0 + 8, vy0 + 11, text=hdr_txt, anchor="w", fill=COL_DIM,
                      font=self._fit_font(hdr_txt, max(40, (curve_x1 - curve_x0) - 70), self._fs(0.76), bold=True))
        self._draw_status_badge(curve_x1 - 8, vy0 + 11, is_live, use_sim)

        # Axis coordinate mappers:
        # X: In dB [-60 .. 0]
        # Y: Out dB [-60 .. +12] so Makeup boosts visibly lift the transfer line above 0 dB
        x_min_db, x_max_db = -60.0, 0.0
        y_min_db, y_max_db = -60.0, 12.0

        def db_to_x(db):
            return gx0 + ((max(x_min_db, min(x_max_db, db)) - x_min_db) / (x_max_db - x_min_db)) * gw

        def db_to_y(db):
            return gy1 - ((max(y_min_db, min(y_max_db, db)) - y_min_db) / (y_max_db - y_min_db)) * gh

        # Grid lines & dB labels
        for db in (-48, -36, -24, -12, 0):
            x = db_to_x(db)
            c.create_line(x, gy0, x, gy1, fill=COL_GRID, dash=(2, 4))
            c.create_text(x, gy1 + 9, text=f"{db}", fill=COL_DIM, font=self._font(self._fs(0.68)))
        for db in (-48, -36, -24, -12, 0, 12):
            y = db_to_y(db)
            col_g = "#3c4054" if db == 0 else COL_GRID
            c.create_line(gx0, y, gx1, y, fill=col_g, dash=(4, 3) if db == 0 else (2, 4))
            lbl = "+12" if db > 0 else f"{db}"
            c.create_text(gx0 - 4, y, text=lbl, anchor="e", fill=COL_DIM, font=self._font(self._fs(0.66)))

        # Unity 1:1 diagonal (-60,-60) -> (0,0)
        c.create_line(db_to_x(-60.0), db_to_y(-60.0), db_to_x(0.0), db_to_y(0.0),
                      fill="#3b3f52", dash=(4, 4), width=1)

        thr_db = params["thr_db"]
        ratio = params["ratio"]
        knee_db = params["knee_db"]
        mk_db = params["makeup_db"]
        mix = params["mix"]

        # Subtle knee zone shading around threshold
        if knee_db > 0.4 and not byp:
            kx0 = db_to_x(max(x_min_db, thr_db - knee_db))
            kx1 = db_to_x(min(x_max_db, thr_db + knee_db))
            if kx1 > kx0 + 1:
                c.create_rectangle(kx0, gy0, kx1, gy1, fill="#221e1b", outline="")

        # Threshold vertical guide
        tx = db_to_x(thr_db)
        c.create_line(tx, gy0, tx, gy1, fill="#5a4328", dash=(3, 3))

        # Static transfer curve (exact Makeup + Soft Knee + Parallel Mix!)
        pts = []
        unity_pts = []
        for i in range(61):
            in_db = -60.0 + i
            out_db, _ = compute_transfer_db(in_db, thr_db, ratio, knee_db, mk_db, mix=mix)
            px = db_to_x(in_db)
            py = db_to_y(out_db)
            pts.extend([px, py])
            unity_pts.extend([px, db_to_y(in_db)])

        # Subtle fill between curve and bottom for depth
        fill_poly = [gx0, gy1] + pts + [gx1, gy1]
        c.create_polygon(fill_poly, fill="#241d18" if not byp else "#1e2028", outline="")
        # Re-draw unity dashed on top of fill for clarity
        c.create_line(db_to_x(-60.0), db_to_y(-60.0), db_to_x(0.0), db_to_y(0.0),
                      fill="#42475c", dash=(4, 4), width=1)
        c.create_line(pts, fill=accent if not byp else COL_DIM, width=2.8)

        # Live operating point crosshair (In dB, Out dB)
        if (is_live or use_sim) and self._in_db > -59.0:
            live_in = max(x_min_db, min(x_max_db, self._in_db))
            if is_live:
                # Dynamic position reflecting real GR + makeup
                if byp:
                    live_out = live_in
                else:
                    eff_out = live_in + self._gr_db + mk_db
                    if mix < 0.999:
                        eff_out = lin_to_db((1.0 - mix) * db_to_lin(live_in) + mix * db_to_lin(eff_out), floor_db=-60.0)
                    live_out = eff_out
            else:
                live_out = self._out_db
            cx = db_to_x(live_in)
            cy = db_to_y(live_out)
            active_comp = (self._gr_db < -0.4) and not byp
            dot_col = COL_GR_HIGH if active_comp else "#74c0fc"

            # Input/Output thin live axis activity bars
            c.create_line(gx0, gy1, cx, gy1, fill=dot_col, width=3)
            c.create_line(gx0, gy1, gx0, cy, fill=dot_col, width=3)
            # Crosshair guides
            c.create_line(cx, gy0, cx, gy1, fill="#495066", dash=(2, 3))
            c.create_line(gx0, cy, gx1, cy, fill="#495066", dash=(2, 3))
            # Glowing operating point
            c.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=dot_col, outline="#ffffff", width=1.5)

        # Node 1 (Primary Knee Node): sits at (thr_db, clamped(thr_db + mk_db))
        knee_y_db = max(y_min_db, min(y_max_db, thr_db + mk_db))
        kx = db_to_x(thr_db)
        ky = db_to_y(knee_y_db)
        c.create_oval(kx - 10, ky - 10, kx + 10, ky + 10, fill=accent, outline="#ffffff", width=2)
        c.create_text(kx, ky, text="T", fill="#0d0e12", font=self._font(self._fs(0.74), bold=True))

        # Node 2 (Ratio Slope Handle): sits at right edge in_db = 0 dB
        r_out_db, _ = compute_transfer_db(0.0, thr_db, ratio, knee_db, mk_db, mix=mix)
        rx = db_to_x(0.0) - 2
        ry = db_to_y(r_out_db)
        c.create_polygon(rx, ry - 9, rx + 9, ry, rx, ry + 9, rx - 9, ry,
                         fill="#ffd43b", outline="#ffffff", width=1.8)
        c.create_text(rx, ry, text="R", fill="#0d0e12", font=self._font(self._fs(0.68), bold=True))

        self.hitboxes.append((curve_x0, vy0, curve_x1, vy1, "comp_curve", {
            "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
            "x_min_db": x_min_db, "x_max_db": x_max_db,
            "y_min_db": y_min_db, "y_max_db": y_max_db,
            "kx": kx, "ky": ky, "rx": rx, "ry": ry,
        }))

        # --- Right panel: Vertical GR Meter (0 .. -30 dB) ---
        c.create_rectangle(gr_x0, vy0, gr_x1, vy1, fill=COL_PANEL,
                           outline=COL_GR_HIGH if (self._gr_db < -0.5 and not byp) else COL_BORDER, width=1)
        gr_cx = (gr_x0 + gr_x1) / 2.0
        c.create_text(gr_cx, vy0 + 10, text="GR", fill=COL_DIM, font=self._font(self._fs(0.74), bold=True))
        gr_val_txt = f"{self._gr_db:.1f}dB" if self._gr_db < -0.05 else "0.0dB"
        gr_txt_col = COL_GR_HIGH if self._gr_db <= -10.0 else (COL_GR_LOW if self._gr_db <= -0.5 else COL_DIM)
        c.create_text(gr_cx, vy0 + 25, text=gr_val_txt, fill=gr_txt_col,
                      font=self._fit_font(gr_val_txt, gr_w - 8, self._fs(0.84), bold=True))

        # Meter track geometry
        bar_y0 = vy0 + 37
        bar_y1 = vy1 - 24
        bar_h = max(24, bar_y1 - bar_y0)
        bar_x0 = gr_x0 + 26
        bar_x1 = gr_x1 - 8
        c.create_rectangle(bar_x0, bar_y0, bar_x1, bar_y1, fill="#121318", outline=COL_BORDER, width=1)

        max_gr_db = 30.0
        for tick_db in (0, 3, 6, 12, 18, 24, 30):
            ty = bar_y0 + (tick_db / max_gr_db) * bar_h
            c.create_line(bar_x0 - 3, ty, bar_x0, ty, fill=COL_DIM)
            c.create_line(bar_x0 + 1, ty, bar_x1 - 1, ty, fill=COL_GRID)
            lbl = "0" if tick_db == 0 else f"-{tick_db}"
            c.create_text(bar_x0 - 5, ty, text=lbl, anchor="e", fill=COL_DIM,
                          font=self._font(self._fs(0.64)))

        # Segmented gradient GR fill descending from 0 dB (top) downward
        gr_mag = min(max_gr_db, max(0.0, -self._gr_db))
        if gr_mag > 0.1 and not byp:
            # Draw in 3 colored vertical bands for smooth amber -> orange -> red gradient
            bands = [
                (0.0,  6.0,  COL_GR_LOW),
                (6.0,  15.0, COL_GR_MID),
                (15.0, 30.0, COL_GR_HIGH),
            ]
            for b0, b1, bcol in bands:
                if gr_mag <= b0:
                    break
                seg_top = bar_y0 + (b0 / max_gr_db) * bar_h
                seg_bot = bar_y0 + (min(gr_mag, b1) / max_gr_db) * bar_h
                if seg_bot > seg_top + 0.5:
                    c.create_rectangle(bar_x0 + 2, seg_top, bar_x1 - 2, seg_bot, fill=bcol, outline="")

        # Peak-hold bar
        pk_mag = min(max_gr_db, max(0.0, -self._gr_peak_db))
        if pk_mag > 0.25 and not byp:
            py = bar_y0 + (pk_mag / max_gr_db) * bar_h
            c.create_line(bar_x0 + 1, py, bar_x1 - 1, py, fill="#ffffff", width=2.2)

        # Bottom Clip / Sim indicator strip inside GR box
        led_y = vy1 - 11
        in_led_col = COL_CLIP if self._clip_in else "#2d303e"
        out_led_col = COL_CLIP if self._clip_out else "#2d303e"
        c.create_oval(gr_x0 + 8, led_y - 4, gr_x0 + 16, led_y + 4, fill=in_led_col, outline="")
        c.create_text(gr_x0 + 19, led_y, text="IN", anchor="w",
                      fill=COL_CLIP if self._clip_in else COL_DIM, font=self._font(self._fs(0.64), bold=True))
        c.create_oval(gr_cx + 2, led_y - 4, gr_cx + 10, led_y + 4, fill=out_led_col, outline="")
        c.create_text(gr_cx + 13, led_y, text="OUT", anchor="w",
                      fill=COL_CLIP if self._clip_out else COL_DIM, font=self._font(self._fs(0.64), bold=True))

        # Tap GR meter area to toggle SIM preview on/off when exploring offline
        self.hitboxes.append((gr_x0, vy0, gr_x1, vy1, "toggle_sim", None))

    # --------------------------------------------------------------------------
    # Tab 2: Time (Sidechain Activity & Ducking Scope Oscilloscope)
    # --------------------------------------------------------------------------
    def _draw_time_tab(self, pad, gap, vy0, vy1, w, accent, byp):
        c = self.widget_canvas
        params = self._get_dsp_params()
        now = time.monotonic()
        is_live = self._has_lv2_monitors and (now - self._last_live_ts) < LIVE_ACTIVITY_HOLD_S and not self._force_sim
        use_sim = self._active_sim_mode

        # Top row: Detection (RMS/Peak) + Stereo Link (Avg/Max) + SIM toggle (>=34px)
        row_h = 34
        ry0, ry1 = vy0, vy0 + row_h
        det = int(round(self._raw(self._get_zctrl("detection"), 0.0)))
        lnk = int(round(self._raw(self._get_zctrl("stereo_link"), 1.0)))
        sim_w = 68
        rem_w = w - 2 * pad - sim_w - 4 * gap
        bw = rem_w / 4.0
        self._draw_pill(pad, ry0, pad + bw, ry1, "RMS", det == 0, accent, "set_int", ("detection", 0))
        self._draw_pill(pad + bw + gap, ry0, pad + 2 * bw + gap, ry1, "Peak", det == 1, accent, "set_int", ("detection", 1))
        self._draw_pill(pad + 2 * (bw + gap), ry0, pad + 3 * bw + 2 * gap, ry1, "Link: Avg", lnk == 0, "#4dabf7", "set_int", ("stereo_link", 0))
        self._draw_pill(pad + 3 * (bw + gap), ry0, pad + 4 * bw + 3 * gap, ry1, "Link: Max", lnk == 1, "#4dabf7", "set_int", ("stereo_link", 1))
        sim_lbl = "LIVE" if is_live else "SIM"
        self._draw_pill(w - pad - sim_w, ry0, w - pad, ry1, sim_lbl, self._force_sim or is_live,
                        COL_LIVE if is_live else COL_SIM, "toggle_sim", None)

        # Main Ducking Scope panel
        py0 = ry1 + gap
        c.create_rectangle(pad, py0, w - pad, vy1, fill=COL_PANEL,
                           outline=accent if not byp else COL_BORDER, width=1)
        gx0 = pad + 32
        gx1 = w - pad - 12
        gy0 = py0 + 22
        gy1 = vy1 - 16
        gw = max(24, gx1 - gx0)
        gh = max(24, gy1 - gy0)

        hdr_txt = f"Ducking Scope  ·  ATK {fmt_ms(params['attack_ms'])}  REL {fmt_ms(params['release_ms'])}  (2D: Atk×Rel)"
        c.create_text(pad + 8, py0 + 11, text=hdr_txt, anchor="w", fill=COL_DIM,
                      font=self._fit_font(hdr_txt, max(40, (w - 2 * pad) - 76), self._fs(0.76), bold=True))
        self._draw_status_badge(w - pad - 8, py0 + 11, is_live, use_sim)

        # Vertical time grid (2.0 s window: -2.0s, -1.5s, -1.0s, -0.5s, Now)
        for idx, tlbl in enumerate(("-2.0s", "-1.5s", "-1.0s", "-0.5s", "Now")):
            tx = gx0 + (idx / 4.0) * gw
            c.create_line(tx, gy0, tx, gy1, fill=COL_GRID, dash=(2, 4))
            anc = "w" if idx == 0 else ("e" if idx == 4 else "center")
            c.create_text(tx, gy1 + 8, text=tlbl, anchor=anc, fill=COL_DIM, font=self._font(self._fs(0.66)))

        # Horizontal dB grid for Ducking Envelope (0 dB top -> -24 dB bottom)
        scope_max_gr = 24.0
        for db in (0, -6, -12, -18, -24):
            y = gy0 + (-db / scope_max_gr) * gh
            c.create_line(gx0, y, gx1, y, fill="#383c4e" if db == 0 else COL_GRID, dash=(2, 4) if db != 0 else ())
            c.create_text(gx0 - 4, y, text=f"{db}", anchor="e", fill=COL_DIM, font=self._font(self._fs(0.66)))

        # Collect waveform samples: (t_norm, sc_db, gr_db, eff_gr_db)
        if is_live:
            hist = list(self._live_history)
            n = len(hist)
            mix = params["mix"]
            samples = []
            for i, (in_db, gr_db) in enumerate(hist):
                tn = i / max(1, n - 1)
                if mix >= 0.999:
                    eff = gr_db
                elif mix <= 0.001:
                    eff = 0.0
                else:
                    eff = lin_to_db((1.0 - mix) + mix * db_to_lin(gr_db), floor_db=-30.0)
                samples.append((tn, in_db, gr_db, eff))
        else:
            samples = self._simulate_scope(now, params, n_pts=72)

        # 1) Background Sidechain / Trigger pulses (blue-cyan, rising from bottom)
        # Map sc_db [-60..0 dB] -> bottom (gy1) to top (gy0)
        sc_poly = [gx0, gy1]
        sc_line = []
        for tn, sc_db, _, _ in samples:
            px = gx0 + tn * gw
            h_frac = max(0.0, min(1.0, (sc_db + 60.0) / 60.0))
            py = gy1 - h_frac * (gh * 0.92)
            sc_poly.extend([px, py])
            sc_line.extend([px, py])
        sc_poly.extend([gx1, gy1])
        c.create_polygon(sc_poly, fill="#1a293a", outline="")
        c.create_line(sc_line, fill="#3b78b8", width=1.4)

        # Threshold horizontal reference line on the sidechain signal scale
        thr_frac = max(0.0, min(1.0, (params["thr_db"] + 60.0) / 60.0))
        thr_y = gy1 - thr_frac * (gh * 0.92)
        c.create_line(gx0, thr_y, gx1, thr_y, fill="#6e4d26", dash=(4, 3))
        c.create_text(gx1 - 3, max(gy0 + 8, thr_y - 7), text=f"Thr {params['thr_db']:.0f}dB",
                      anchor="e", fill="#c98744", font=self._font(self._fs(0.64)))

        # 2) Foreground Anti-Phase Ducking Curve (0 dB at top, dips downward by GR!)
        duck_poly = [gx0, gy0]
        duck_line = []
        eff_line = []
        for tn, _, gr_db, eff_gr in samples:
            px = gx0 + tn * gw
            g_y = gy0 + (min(scope_max_gr, max(0.0, -gr_db)) / scope_max_gr) * gh
            e_y = gy0 + (min(scope_max_gr, max(0.0, -eff_gr)) / scope_max_gr) * gh
            duck_poly.extend([px, g_y])
            duck_line.extend([px, g_y])
            eff_line.extend([px, e_y])
        duck_poly.extend([gx1, gy0])

        c.create_polygon(duck_poly, fill="#193b25" if not byp else "#23252e", outline="")
        if params["mix"] < 0.96 and not byp:
            c.create_line(eff_line, fill="#96f2d7", width=1.6, dash=(3, 3))
        c.create_line(duck_line, fill=accent if not byp else COL_DIM, width=2.6)

        # 3) Interactive Attack x Release 2D control handle
        att_n = self._norm(self._get_zctrl("attack"), "attack")
        rel_n = self._norm(self._get_zctrl("release"), "release")
        hx = gx0 + att_n * gw
        hy = gy1 - rel_n * gh
        c.create_line(hx, gy0, hx, gy1, fill="#2e4a37", dash=(2, 4))
        c.create_line(gx0, hy, gx1, hy, fill="#2e4a37", dash=(2, 4))
        c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
        c.create_text(hx, hy, text="AR", fill="#0d0e12", font=self._font(self._fs(0.64), bold=True))

        self.hitboxes.append((pad, py0, w - pad, vy1, "xy_pad", {
            "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
            "xk": "attack", "yk": "release",
        }))

    # --------------------------------------------------------------------------
    # Tab 3: S/C EQ (Dual Independent 2D Filter Nodes: F1 Blue & F2 Orange)
    # --------------------------------------------------------------------------
    def _draw_eq_tab(self, pad, gap, vy0, vy1, w, accent, byp):
        c = self.widget_canvas
        mode_idx = max(0, min(9, int(round(self._raw(self._get_zctrl("sc_mode"), 0.0)))))
        f1_type, f2_type = SC_MODE_FILTERS[mode_idx]
        f1_active = (f1_type != "off") if self._f1_active_mon is None else (self._f1_active_mon or f1_type != "off")
        f2_active = (f2_type != "off") if self._f2_active_mon is None else (self._f2_active_mon or f2_type != "off")

        # Top mode switcher bar (>=34px) so musician can switch filter topology right on S/C EQ
        row_h = 34
        ry0, ry1 = vy0, vy0 + row_h
        step_w = 46
        self._draw_pill(pad, ry0, pad + step_w, ry1, "◀", False, accent, "step_mode", -1)
        self._draw_pill(w - pad - step_w, ry0, w - pad, ry1, "▶", False, accent, "step_mode", +1)
        mid_x0 = pad + step_w + gap
        mid_x1 = w - pad - step_w - gap
        c.create_rectangle(mid_x0, ry0, mid_x1, ry1, fill=COL_PANEL_HI, outline=COL_BORDER, width=1)
        mode_lbl = SC_MODES_DESC[mode_idx]
        c.create_text((mid_x0 + mid_x1) / 2.0, (ry0 + ry1) / 2.0, text=mode_lbl, fill=COL_TEXT,
                      font=self._fit_font(mode_lbl, max(30, (mid_x1 - mid_x0) - 12), self._fs(0.84), bold=True))

        # Main EQ Graph Panel
        py0 = ry1 + gap
        c.create_rectangle(pad, py0, w - pad, vy1, fill=COL_PANEL,
                           outline=accent if not byp else COL_BORDER, width=1)
        gx0 = pad + 30
        gx1 = w - pad - 12
        gy0 = py0 + 22
        gy1 = vy1 - 18
        gw = max(24, gx1 - gx0)
        gh = max(24, gy1 - gy0)
        mid_y = (gy0 + gy1) / 2.0

        f1_hz = max(10.0, min(18000.0, self._raw(self._get_zctrl("f1_freq"), 250.0)))
        f2_hz = max(10.0, min(18000.0, self._raw(self._get_zctrl("f2_freq"), 4500.0)))
        g1_db = max(-24.0, min(24.0, lin_to_db(self._raw(self._get_zctrl("f1_level"), 1.0), floor_db=-24.0)))
        g2_db = max(-24.0, min(24.0, lin_to_db(self._raw(self._get_zctrl("f2_level"), 1.0), floor_db=-24.0)))

        # Header legend showing F1 & F2 exact live values
        f1_tag = f"F1({f1_type.upper()}): {fmt_hz(f1_hz)}" + (f" {g1_db:+.1f}dB" if f1_type in GAIN_FILTER_TYPES else "")
        f2_tag = f"F2({f2_type.upper()}): {fmt_hz(f2_hz)}" + (f" {g2_db:+.1f}dB" if f2_type in GAIN_FILTER_TYPES else "")
        c.create_text(pad + 8, py0 + 11, text=f1_tag, anchor="w",
                      fill=COL_F1 if f1_active else COL_DIM,
                      font=self._fit_font(f1_tag, gw * 0.48, self._fs(0.75), bold=True))
        c.create_text(w - pad - 8, py0 + 11, text=f2_tag, anchor="e",
                      fill=COL_F2 if f2_active else COL_DIM,
                      font=self._fit_font(f2_tag, gw * 0.48, self._fs(0.75), bold=True))

        f_min, f_max = 10.0, 18000.0
        log_span = math.log(f_max / f_min)

        def hz_to_x(hz):
            hz = max(f_min, min(f_max, hz))
            return gx0 + (math.log(hz / f_min) / log_span) * gw

        def db_to_y(db):
            db = max(-24.0, min(24.0, db))
            return mid_y - (db / 25.0) * (gh * 0.48)

        # Horizontal dB grid (+18, +12, 0, -12, -18)
        for db in (12, 0, -12):
            y = db_to_y(db)
            c.create_line(gx0, y, gx1, y, fill="#3c4054" if db == 0 else COL_GRID,
                          dash=(3, 4) if db == 0 else (2, 4))
            lbl = "+12" if db > 0 else f"{db}"
            c.create_text(gx0 - 4, y, text=lbl, anchor="e", fill=COL_DIM, font=self._font(self._fs(0.66)))

        # Vertical log-frequency grid
        for f_hz, flbl in ((20, "20"), (50, "50"), (120, "120"), (250, "250"),
                           (500, "500"), (1000, "1k"), (2500, "2.5k"), (5000, "5k"), (12000, "12k")):
            fx = hz_to_x(f_hz)
            c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
            c.create_text(fx, gy1 + 9, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

        # Evaluate F1, F2, and combined EQ response curves
        pts_sum = []
        pts_f1 = []
        pts_f2 = []
        poly_sum = [gx0, mid_y]
        n_steps = 80
        for i in range(n_steps + 1):
            t = i / float(n_steps)
            f = f_min * ((f_max / f_min) ** t)
            d1 = eval_filter_db(f1_type, f, f1_hz, g1_db) if f1_active else 0.0
            d2 = eval_filter_db(f2_type, f, f2_hz, g2_db) if f2_active else 0.0
            dsum = max(-24.0, min(24.0, d1 + d2))
            px = gx0 + t * gw
            py_sum = db_to_y(dsum)
            pts_sum.extend([px, py_sum])
            poly_sum.extend([px, py_sum])
            if f1_active:
                pts_f1.extend([px, db_to_y(max(-24.0, min(24.0, d1)))])
            if f2_active:
                pts_f2.extend([px, db_to_y(max(-24.0, min(24.0, d2)))])
        poly_sum.extend([gx1, mid_y])

        # Shaded combined response area
        c.create_polygon(poly_sum, fill="#1a2c3d" if not byp else "#20222b", outline="")

        # Individual band dashed curves when both bands are active
        if f1_active and f2_active:
            c.create_line(pts_f1, fill="#3472a8", width=1.4, dash=(3, 3))
            c.create_line(pts_f2, fill="#b06522", width=1.4, dash=(3, 3))

        # Bold combined EQ curve
        c.create_line(pts_sum, fill="#74c0fc" if not byp else COL_DIM, width=2.8)

        # Node F1 (Blue) & Node F2 (Orange) positions
        f1_x = hz_to_x(f1_hz)
        f1_y = db_to_y(g1_db if f1_type in GAIN_FILTER_TYPES else 0.0)
        f2_x = hz_to_x(f2_hz)
        f2_y = db_to_y(g2_db if f2_type in GAIN_FILTER_TYPES else 0.0)

        # Vertical frequency stalks to 0 dB line
        if f1_active:
            c.create_line(f1_x, gy0, f1_x, gy1, fill="#244361", dash=(2, 3))
        if f2_active:
            c.create_line(f2_x, gy0, f2_x, gy1, fill="#54381e", dash=(2, 3))

        # Draw Node 1 (Blue)
        if f1_active:
            c.create_oval(f1_x - 11, f1_y - 11, f1_x + 11, f1_y + 11, fill=COL_F1, outline="#ffffff", width=2)
            c.create_text(f1_x, f1_y, text="1", fill="#0d0e12", font=self._font(self._fs(0.78), bold=True))
        else:
            c.create_oval(f1_x - 9, f1_y - 9, f1_x + 9, f1_y + 9, fill=COL_PANEL, outline="#4a6580", width=1.8, dash=(2, 2))
            c.create_text(f1_x, f1_y, text="1", fill="#6b8aab", font=self._font(self._fs(0.72), bold=True))

        # Draw Node 2 (Orange)
        if f2_active:
            c.create_oval(f2_x - 11, f2_y - 11, f2_x + 11, f2_y + 11, fill=COL_F2, outline="#ffffff", width=2)
            c.create_text(f2_x, f2_y, text="2", fill="#0d0e12", font=self._font(self._fs(0.78), bold=True))
        else:
            c.create_oval(f2_x - 9, f2_y - 9, f2_x + 9, f2_y + 9, fill=COL_PANEL, outline="#7d5634", width=1.8, dash=(2, 2))
            c.create_text(f2_x, f2_y, text="2", fill="#a6774d", font=self._font(self._fs(0.72), bold=True))

        if not f1_active and not f2_active:
            hint = "Wideband (EQ bypassed) — tap ◀ / ▶ above to enable S/C filters"
            c.create_text((gx0 + gx1) / 2.0, gy0 + 18, text=hint, fill=COL_DIM,
                          font=self._fit_font(hint, gw - 16, self._fs(0.76), bold=False))

        self.hitboxes.append((pad, py0, w - pad, vy1, "eq_dual", {
            "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
            "f1_x": f1_x, "f1_y": f1_y, "f1_active": f1_active, "f1_has_gain": f1_type in GAIN_FILTER_TYPES,
            "f2_x": f2_x, "f2_y": f2_y, "f2_active": f2_active, "f2_has_gain": f2_type in GAIN_FILTER_TYPES,
        }))

    # --------------------------------------------------------------------------
    # Tab 4: S/C Route
    # --------------------------------------------------------------------------
    def _draw_route_tab(self, pad, gap, vy0, vy1, w, accent, sc_listen):
        c = self.widget_canvas
        row_h = 34
        ry0, ry1 = vy0, vy0 + row_h
        sc_rt = int(round(self._raw(self._get_zctrl("sc_route"), 0.0)))
        bw = (w - 2 * pad - 2 * gap) / 3.0
        self._draw_pill(pad, ry0, pad + bw, ry1, "Route: Internal", sc_rt == 0, accent, "set_int", ("sc_route", 0))
        self._draw_pill(pad + bw + gap, ry0, pad + 2 * bw + gap, ry1, "Route: External", sc_rt == 1, accent, "set_int", ("sc_route", 1))
        self._draw_pill(pad + 2 * (bw + gap), ry0, w - pad, ry1,
                        "SC Listen: ON" if sc_listen else "SC Listen: OFF", sc_listen, "#ffd43b", "toggle", "sc_listen")

        # Bottom compact topology/GR info strip
        info_h = 22
        info_y0 = vy1 - info_h
        gy0 = ry1 + gap
        gh = max(74, info_y0 - gap - gy0)
        cols, rows = 5, 2
        cw = (w - 2 * pad - (cols - 1) * gap) / cols
        ch = (gh - (rows - 1) * gap) / rows
        mode_idx = max(0, min(9, int(round(self._raw(self._get_zctrl("sc_mode"), 0.0)))))
        for idx, mlbl in enumerate(SC_MODES_SHORT):
            col = idx % cols
            row = idx // cols
            mx0 = pad + col * (cw + gap)
            my0 = gy0 + row * (ch + gap)
            self._draw_pill(mx0, my0, mx0 + cw, my0 + ch, mlbl, idx == mode_idx, accent, "set_int", ("sc_mode", idx))

        c.create_rectangle(pad, info_y0, w - pad, vy1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        desc = SC_MODES_DESC[mode_idx]
        c.create_text(pad + 8, info_y0 + info_h / 2.0, text=desc, anchor="w", fill=COL_TEXT,
                      font=self._fit_font(desc, max(40, (w - 2 * pad) - 90), self._fs(0.76), bold=False))
        gr_txt = f"GR {self._gr_db:.1f}dB" if self._gr_db < -0.05 else "GR 0.0dB"
        c.create_text(w - pad - 8, info_y0 + info_h / 2.0, text=gr_txt, anchor="e",
                      fill=COL_GR_HIGH if self._gr_db <= -6.0 else (COL_GR_LOW if self._gr_db < -0.5 else COL_DIM),
                      font=self._font(self._fs(0.76), bold=True))

    # --------------------------------------------------------------------------
    # Main Draw
    # --------------------------------------------------------------------------
    def _draw(self):
        c = self.widget_canvas
        w, h = self.width, self.height
        if w < 40 or h < 40:
            return
        c.delete("all")
        self.hitboxes = []

        pad = 6
        gap = 6
        accent = TAB_ACCENTS[self.active_tab]
        byp = self._raw(self._get_zctrl("bypass")) >= 0.5
        sc_listen = self._raw(self._get_zctrl("sc_listen")) >= 0.5

        hdr_h = max(36, min(46, int(h * 0.11)))
        sc_w = 50
        byp_w = 60
        tabs_w = w - 2 * pad - sc_w - byp_w - 2 * gap
        tw = (tabs_w - 3 * gap) / 4.0
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        sx0 = w - pad - byp_w - gap - sc_w
        self._draw_pill(sx0, pad, sx0 + sc_w, pad + hdr_h, "SC", sc_listen, "#ffd43b", "toggle", "sc_listen")
        self._draw_pill(w - pad - byp_w, pad, w - pad, pad + hdr_h,
                        "BYP" if byp else "ON ●", not byp, "#51cf66", "toggle", "bypass")

        bot_h = 96
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap

        if self.active_tab == "Comp":
            self._draw_comp_tab(pad, gap, vy0, vy1, w, accent, byp)
        elif self.active_tab == "Time":
            self._draw_time_tab(pad, gap, vy0, vy1, w, accent, byp)
        elif self.active_tab == "S/C EQ":
            self._draw_eq_tab(pad, gap, vy0, vy1, w, accent, byp)
        else:
            self._draw_route_tab(pad, gap, vy0, vy1, w, accent, sc_listen)

        # 2x2 encoder-linked parameter boxes at bottom
        items = self._tab_items(self.active_tab)
        by0 = h - pad - bot_h
        cw = (w - 2 * pad - gap) / 2.0
        ch = (bot_h - gap) / 2.0
        for i, (k, lbl) in enumerate(items):
            rx0 = pad + (i % 2) * (cw + gap)
            ry0 = by0 + (i // 2) * (ch + gap)
            self._draw_param_box(rx0, ry0, rx0 + cw, ry0 + ch, k, lbl, accent)

    # --------------------------------------------------------------------------
    # Touch & Gesture Handling (Drag + Double-Tap Reset)
    # --------------------------------------------------------------------------
    def _reset_default(self, key):
        z = self._get_zctrl(key)
        if z is not None:
            z.set_value(z.value_default, send=True)
            self._last_interact_ts = time.monotonic()
            self.last_snapshot = None
            self._draw()

    def _on_press(self, event):
        x, y = event.x, event.y
        now = time.monotonic()
        for x0, y0, x1, y1, kind, payload in reversed(self.hitboxes):
            if x0 <= x <= x1 and y0 <= y <= y1:
                if kind == "tab":
                    self.active_tab = payload
                    self._select_page(payload)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "toggle":
                    z = self._get_zctrl(payload)
                    if z is not None:
                        z.set_value(0.0 if self._raw(z) >= 0.5 else 1.0, send=True)
                        self._last_interact_ts = now
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "toggle_sim":
                    self._force_sim = not self._force_sim
                    self._last_interact_ts = now
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "step_mode":
                    z = self._get_zctrl("sc_mode")
                    if z is not None:
                        cur = int(round(self._raw(z, 0.0)))
                        nxt = (cur + int(payload)) % len(SC_MODES_SHORT)
                        z.set_value(nxt, send=True)
                        self._last_interact_ts = now
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "set_int":
                    k, val = payload
                    z = self._get_zctrl(k)
                    if z is not None:
                        z.set_value(int(val), send=True)
                        self._last_interact_ts = now
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "hfader":
                    tap_id = ("hfader", payload["key"])
                    if self.last_tap[0] == tap_id and (now - self.last_tap[1]) < DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        self._reset_default(payload["key"])
                        return
                    self.last_tap = (tap_id, now)
                    self.drag_target = (kind, payload)
                    self._apply_drag(x, y)
                    return
                if kind == "xy_pad":
                    tap_id = ("xy", payload["xk"], payload["yk"])
                    if self.last_tap[0] == tap_id and (now - self.last_tap[1]) < DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        self._reset_default(payload["xk"])
                        self._reset_default(payload["yk"])
                        return
                    self.last_tap = (tap_id, now)
                    self.drag_target = (kind, payload)
                    self._apply_drag(x, y)
                    return
                if kind == "comp_curve":
                    # Choose between Ratio slope handle (right edge) and Knee node (Threshold x Makeup)
                    d_r = math.hypot(x - payload["rx"], y - payload["ry"])
                    d_k = math.hypot(x - payload["kx"], y - payload["ky"])
                    node = "ratio" if (d_r <= 28.0 and d_r < d_k) else "knee"
                    tap_id = ("comp_curve", node)
                    if self.last_tap[0] == tap_id and (now - self.last_tap[1]) < DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        if node == "ratio":
                            self._reset_default("ratio")
                        else:
                            # Reset Threshold to -12 dB (0.251) and Makeup to 0 dB (1.0)
                            self._set_raw_clamped(self._get_zctrl("threshold"), db_to_lin(-12.0))
                            self._set_raw_clamped(self._get_zctrl("makeup"), 1.0)
                            self._last_interact_ts = now
                            self.last_snapshot = None
                            self._draw()
                        return
                    self.last_tap = (tap_id, now)
                    target = dict(payload)
                    target["node"] = node
                    self.drag_target = ("comp_curve", target)
                    self._apply_drag(x, y)
                    return
                if kind == "eq_dual":
                    # Pick nearest of F1 / F2 (with priority for active node when equidistant)
                    d1 = math.hypot(x - payload["f1_x"], y - payload["f1_y"])
                    d2 = math.hypot(x - payload["f2_x"], y - payload["f2_y"])
                    eff_d1 = d1 - (6.0 if payload["f1_active"] and not payload["f2_active"] else 0.0)
                    eff_d2 = d2 - (6.0 if payload["f2_active"] and not payload["f1_active"] else 0.0)
                    band = "f1" if eff_d1 <= eff_d2 else "f2"
                    tap_id = ("eq_dual", band)
                    if self.last_tap[0] == tap_id and (now - self.last_tap[1]) < DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        self._reset_default(f"{band}_freq")
                        self._reset_default(f"{band}_level")
                        return
                    self.last_tap = (tap_id, now)
                    target = dict(payload)
                    target["band"] = band
                    self.drag_target = ("eq_dual", target)
                    self._apply_drag(x, y)
                    return

    def _on_drag(self, event):
        if self.drag_target:
            self._apply_drag(event.x, event.y)

    def _on_release(self, event):
        self.drag_target = None

    def _apply_drag(self, x, y):
        kind, p = self.drag_target
        self._last_interact_ts = time.monotonic()

        if kind == "hfader":
            n = (x - p["tx0"]) / max(1.0, p["tx1"] - p["tx0"])
            self._set_norm(self._get_zctrl(p["key"]), n, p["key"])
        elif kind == "xy_pad":
            nx = (x - p["gx0"]) / max(1.0, p["gx1"] - p["gx0"])
            ny = 1.0 - (y - p["gy0"]) / max(1.0, p["gy1"] - p["gy0"])
            self._set_norm(self._get_zctrl(p["xk"]), nx, p["xk"])
            self._set_norm(self._get_zctrl(p["yk"]), ny, p["yk"])
        elif kind == "comp_curve":
            gx0, gx1 = p["gx0"], p["gx1"]
            gy0, gy1 = p["gy0"], p["gy1"]
            nx = max(0.0, min(1.0, (x - gx0) / max(1.0, gx1 - gx0)))
            ny = max(0.0, min(1.0, 1.0 - (y - gy0) / max(1.0, gy1 - gy0)))
            if p["node"] == "knee":
                # X -> Threshold (-60 .. 0 dB) directly on the curve
                thr_db = p["x_min_db"] + nx * (p["x_max_db"] - p["x_min_db"])
                self._set_raw_clamped(self._get_zctrl("threshold"), db_to_lin(thr_db))
                # Y -> Makeup Gain: lifting knee node vertically above diagonal boosts Makeup (0..+36 dB)
                y_db = p["y_min_db"] + ny * (p["y_max_db"] - p["y_min_db"])
                mk_db = max(0.0, min(36.0, y_db - thr_db))
                self._set_raw_clamped(self._get_zctrl("makeup"), db_to_lin(mk_db))
            else:
                # Dragging Ratio handle downward increases Ratio (flatter slope), upward reduces toward 1:1
                params = self._get_dsp_params()
                thr_db = params["thr_db"]
                mk_db = params["makeup_db"]
                y_db = p["y_min_db"] + ny * (p["y_max_db"] - p["y_min_db"])
                # Target output at 0 dB input (without makeup) = thr_db + (-thr_db)/ratio
                span = max(2.0, -thr_db)
                desired_above_thr = max(span / 20.0, min(span, (y_db - mk_db) - thr_db))
                ratio = max(1.0, min(20.0, span / desired_above_thr))
                self._set_raw_clamped(self._get_zctrl("ratio"), ratio)
        elif kind == "eq_dual":
            band = p["band"]
            nx = max(0.0, min(1.0, (x - p["gx0"]) / max(1.0, p["gx1"] - p["gx0"])))
            ny = max(0.0, min(1.0, 1.0 - (y - p["gy0"]) / max(1.0, p["gy1"] - p["gy0"])))
            self._set_norm(self._get_zctrl(f"{band}_freq"), nx, f"{band}_freq")
            if p.get(f"{band}_has_gain", True):
                self._set_norm(self._get_zctrl(f"{band}_level"), ny, f"{band}_level")

        self.last_snapshot = None
        self._draw()
