#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Shiroverb Shimmer Reverb Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 2 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Shimmer | Space & Tone
# Features:
#   - 1-tap Shimmer Pitch Ratio pills (-1 Oct, Unison, +5th, +1 Oct)
#   - Harmonic shimmer cascade decay visualizer (2D: Decay x Shimmer)
#   - Spectral damping & room-size visualizer (2D: Room Size x Tone)
#   - Double-tap reset on all sliders & 2D pads + 2-way encoder sync
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
UPDATE_PERIOD = 0.06
DOUBLE_TAP_S = 0.35

COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

TABS = ["Shimmer", "Space & Tone"]
TAB_ACCENTS = {
    "Shimmer":      "#cc5de8",
    "Space & Tone": "#4dabf7",
}

RATIO_PRESETS = [
    ("-1 Oct", 0.5),
    ("Unison", 1.0),
    ("+5th",   1.5),
    ("+1 Oct", 2.0),
]
LOG_KEYS = {"tone"}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.2f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


class zynthian_widget_shiroverb(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Shimmer"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}
        self._tk_font_cache = {}

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

    def _tab_items(self, tab):
        if tab == "Shimmer":
            return [
                ("decay",   "Decay"),
                ("shimmer", "Shimmer"),
                ("ratio",   "Pitch"),
                ("mix",     "Mix"),
            ]
        return [
            ("roomsize",  "Room"),
            ("tone",      "Tone"),
            ("damping",   "Damp"),
            ("bandwidth", "Bandwdth"),
        ]

    def _rebuild_pages(self):
        if not self.processor:
            return
        screens = {}
        for t in TABS:
            zl = []
            for k, lbl in self._tab_items(t):
                z = self._get_zctrl(k)
                if z is not None:
                    z.short_name = lbl
                    zl.append(z)
            if zl:
                screens[t] = zl
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
            logging.debug(f"Shiroverb sync error: {e}")

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
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_shiroverb._raw(z)
        if key == "ratio":
            st = 12.0 * math.log2(max(0.25, v))
            return f"{v:.2f}x ({st:+.0f}st)"
        if key == "roomsize":
            return f"{v:.0f}m"
        if key == "tone":
            return fmt_hz(v)
        return f"{int(round(v))}%"

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
        keys = ("shimmer", "decay", "damping", "mix", "ratio", "roomsize", "bandwidth", "tone")
        snap = (self.width, self.height, self.active_tab,
                tuple(round(self._raw(self._get_zctrl(k)), 2) for k in keys))
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
            if tf is None or tf.measure(txt) <= max_w:
                break
            s -= 1
        return self._font(s, bold=bold)

    def _fs(self, scale=1.0):
        return max(8, int(round(max(9, min(13, self.height // 34)) * scale)))

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
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM,
                      font=self._fit_font(label, avail * 0.48, self._fs(0.82)))
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=val_txt, anchor="e", fill=COL_TEXT,
                      font=self._fit_font(val_txt, avail * 0.52, self._fs(0.86), bold=True))
        c.create_rectangle(tx0, by0, tx1, by1, fill=COL_TRACK, outline="")
        fx = tx0 + n * (tx1 - tx0)
        if fx > tx0 + 1:
            c.create_rectangle(tx0, by0, fx, by1, fill=accent, outline="")
        c.create_line(fx, by0, fx, by1, fill="#ffffff", width=2)
        self.hitboxes.append((x0, y0, x1, y1, "hfader", {"key": key, "tx0": tx0, "tx1": tx1}))

    def _draw(self):
        c = self.widget_canvas
        w, h = self.width, self.height
        if w < 40 or h < 40:
            return
        c.delete("all")
        self.hitboxes = []

        pad, gap = 6, 6
        accent = TAB_ACCENTS[self.active_tab]
        hdr_h = max(36, min(46, int(h * 0.11)))
        tw = (w - 2 * pad - gap) / 2.0
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        bot_h = 98
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap

        if self.active_tab == "Shimmer":
            # Pitch Ratio quick preset pills (>=34px)
            r2_h = 34
            rat = self._raw(self._get_zctrl("ratio"), 2.0)
            bw = (w - 2 * pad - 3 * gap) / 4.0
            for i, (rlbl, rval) in enumerate(RATIO_PRESETS):
                bx0 = pad + i * (bw + gap)
                self._draw_pill(bx0, vy0, bx0 + bw, vy0 + r2_h, rlbl, abs(rat - rval) < 0.08,
                                "#ffd43b", "set_raw", ("ratio", rval))

            py0 = vy0 + r2_h + gap
            c.create_rectangle(pad, py0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = py0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)

            dec_n = self._norm(self._get_zctrl("decay"), "decay", 0.5)
            shm_n = self._norm(self._get_zctrl("shimmer"), "shimmer", 0.5)
            mix_n = self._norm(self._get_zctrl("mix"), "mix", 0.5)
            c.create_text(gx0, py0 + 11, text="Shimmer Harmonic Cascade  (Drag 2D: X=Decay, Y=Shimmer)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            # Base reverb tail + 2 pitch-shifted shimmer harmonic bloom layers
            tau = 0.12 + dec_n * 0.85
            base_poly = [gx0, gy1]
            base_line = []
            shm1_line, shm2_line = [], []
            pitch_dir = 1.0 if rat >= 1.0 else -0.6
            for i in range(65):
                t = i / 64.0
                px = gx0 + t * gw
                amp_b = math.exp(-t / tau) * (0.25 + 0.65 * max(0.2, mix_n))
                # Shimmer swells smoothly after onset
                bloom = (1.0 - math.exp(-t * 5.5)) * math.exp(-t / (tau * 1.15)) * shm_n
                amp_s1 = max(0.0, min(0.96, amp_b * 0.55 + bloom * (0.58 + 0.18 * pitch_dir)))
                amp_s2 = max(0.0, min(0.96, bloom * (0.82 + 0.14 * pitch_dir) * (0.75 + 0.25 * math.sin(t * 16.0 * rat))))
                base_poly.extend([px, gy1 - amp_b * gh])
                base_line.extend([px, gy1 - amp_b * gh])
                shm1_line.extend([px, gy1 - amp_s1 * gh])
                shm2_line.extend([px, gy1 - amp_s2 * gh])
            base_poly.extend([gx1, gy1])

            c.create_polygon(base_poly, fill="#24192b", outline="")
            c.create_line(base_line, fill="#7950f2", width=2.0)
            if shm_n > 0.02:
                c.create_line(shm1_line, fill=accent, width=2.4)
                c.create_line(shm2_line, fill="#ffd43b", width=1.6, dash=(3, 3))

            hx, hy = gx0 + dec_n * gw, gy1 - shm_n * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, py0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "decay", "yk": "shimmer"}))
        else:
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)
            gx0, gx1 = pad + 18, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 16
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)

            rm_n = self._norm(self._get_zctrl("roomsize"), "roomsize", 0.5)
            tn_hz = max(500.0, self._raw(self._get_zctrl("tone"), 1500.0))
            tn_n = self._norm(self._get_zctrl("tone"), "tone", 0.45)
            dmp_n = self._norm(self._get_zctrl("damping"), "damping", 0.5)
            bw_n = self._norm(self._get_zctrl("bandwidth"), "bandwidth", 0.75)

            c.create_text(gx0, vy0 + 11, text="Room Space & Spectral Damping  (Drag 2D: X=Room Size, Y=Tone)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.78), bold=True))

            # Background translucent room wireframe scaling with roomsize
            rw = gw * (0.20 + rm_n * 0.72)
            rh = gh * (0.24 + rm_n * 0.68)
            rcx, rcy = (gx0 + gx1) / 2.0, (gy0 + gy1) / 2.0
            c.create_rectangle(rcx - rw / 2, rcy - rh / 2, rcx + rw / 2, rcy + rh / 2,
                               fill="#16212e", outline="#2a4563", width=1.6, dash=(4, 3))

            f_min, f_max = 100.0, 12000.0
            log_span = math.log(f_max / f_min)
            for f_hz, flbl in ((200, "200"), (500, "500"), (1500, "1.5k"), (4000, "4k"), (10000, "10k")):
                fx = gx0 + (math.log(f_hz / f_min) / log_span) * gw
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            # Spectral tone + damping + input bandwidth curve
            pts = []
            poly = [gx0, gy1]
            bw_cut = 400.0 + bw_n * 11000.0
            for i in range(65):
                t = i / 64.0
                f = f_min * ((f_max / f_min) ** t)
                lp_tn = 1.0 / math.sqrt(1.0 + (f / tn_hz) ** (2.0 + dmp_n * 2.5))
                lp_bw = 1.0 / math.sqrt(1.0 + (f / bw_cut) ** 2)
                lvl = max(0.03, min(0.95, 0.88 * lp_tn * lp_bw))
                px, py = gx0 + t * gw, gy1 - lvl * gh
                pts.extend([px, py])
                poly.extend([px, py])
            poly.extend([gx1, gy1])
            c.create_polygon(poly, fill="#1a2c3d", outline="")
            c.create_line(pts, fill=accent, width=2.8)

            hx, hy = gx0 + rm_n * gw, gy1 - tn_n * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "roomsize", "yk": "tone"}))

        py0 = vy1 + gap
        items = self._tab_items(self.active_tab)
        cw = (w - 2 * pad - gap) / 2.0
        ch = (h - pad - py0 - 4) / 2.0
        for i, (k, lbl) in enumerate(items):
            px0 = pad + (i % 2) * (cw + gap)
            py_i = py0 + (i // 2) * (ch + 4)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, k, lbl, accent)

    def _on_press(self, event):
        self.drag_target = None
        now = time.monotonic()
        for x0, y0, x1, y1, kind, payload in reversed(self.hitboxes):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if kind == "tab":
                    if payload != self.active_tab:
                        self.active_tab = payload
                        self._select_page(payload)
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "set_raw":
                    k, val = payload
                    z = self._get_zctrl(k)
                    if z is not None:
                        z.set_value(float(val), send=True)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind in ("hfader", "xy_pad"):
                    tid = (kind, payload.get("key") or payload.get("xk"))
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = [payload["key"]] if kind == "hfader" else [payload["xk"], payload["yk"]]
                        for rk in rks:
                            z = self._get_zctrl(rk)
                            if z is not None:
                                z.set_value(z.value_default, send=True)
                        self.last_snapshot = None
                        self._draw()
                        return
                    self.last_tap = (tid, now)
                    self.drag_target = (kind, payload)
                    self._apply_drag(event.x, event.y)
                    return

    def _on_drag(self, event):
        if self.drag_target is not None:
            self._apply_drag(event.x, event.y)

    def _on_release(self, event):
        self.drag_target = None

    def _apply_drag(self, x, y):
        kind, p = self.drag_target
        if kind == "hfader" and p["tx1"] > p["tx0"]:
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]), p["key"])
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]), p["xk"])
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]), p["yk"])
        self.last_snapshot = None
        self._draw()
