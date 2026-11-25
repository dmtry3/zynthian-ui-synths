#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Dragonfly Plate Reverb Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 2 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Plate | Tone
# Features Simple/Nested/Tank algorithm pills + dedicated per-tab visualizers:
#   - Plate: Algorithm-aware metallic plate decay envelope + Predelay & Width
#   - Tone: Spectral bandpass & damping EQ with dual interactive nodes (LC & HC)
# ******************************************************************************

import logging
import math
import re
import time
import tkinter

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

TABS = ["Plate", "Tone"]
TAB_ACCENTS = {"Plate": "#ff922b", "Tone": "#4dabf7"}
ALGORITHMS = ["Simple", "Nested", "Tank"]
LOG_KEYS = {"low_cut", "high_cut", "early_damp"}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.1f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


class zynthian_widget_dragonfly_plate_reverb(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Plate"
        self.last_screen_title = None
        self.last_snapshot = None
        self._ctrl_index = {}
        self._bound_proc_id = None
        self.hitboxes = []
        self.drag_target = None
        self.last_tap = (None, 0.0)
        self._font_cache = {}

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
        if tab == "Plate":
            return [("early_level", "Wet"), ("decay", "Decay"), ("predelay", "Predelay"), ("width", "Width")]
        return [("low_cut", "Low Cut"), ("high_cut", "High Cut"), ("early_damp", "Dampen"), ("dry_level", "Dry")]

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
            logging.debug(f"Dragonfly Plate sync error: {e}")

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
    def _norm(z, default=0.0, key=""):
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
        v = zynthian_widget_dragonfly_plate_reverb._raw(z)
        if key == "decay":
            return f"{v:.2f}s"
        if key == "predelay":
            return f"{v:.0f}ms"
        if key in ("low_cut", "high_cut", "early_damp"):
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
        keys = ("dry_level", "early_level", "algorithm", "width", "predelay", "decay", "low_cut", "high_cut", "early_damp")
        snap = (self.width, self.height, self.active_tab, tuple(round(self._raw(self._get_zctrl(k)), 2) for k in keys))
        if snap != self.last_snapshot:
            self.last_snapshot = snap
            self._draw()

    def _font(self, size, bold=False):
        key = (size, bold)
        if key not in self._font_cache:
            fam = zynthian_gui_config.font_family
            self._font_cache[key] = (fam, size, "bold") if bold else (fam, size)
        return self._font_cache[key]

    def _fs(self, scale=1.0):
        return max(8, int(round(max(9, min(13, self.height // 34)) * scale)))

    def _draw_pill(self, x0, y0, x1, y1, text, active, accent, kind, payload):
        c = self.widget_canvas
        c.create_rectangle(x0, y0, x1, y1, fill=accent if active else COL_PANEL,
                           outline=accent if active else COL_BORDER, width=2 if active else 1)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                      fill="#0d0e12" if active else COL_TEXT, font=self._font(self._fs(0.92), bold=True))
        self.hitboxes.append((x0, y0, x1, y1, kind, payload))

    def _draw_param_box(self, x0, y0, x1, y1, key, label, accent):
        c = self.widget_canvas
        z = self._get_zctrl(key)
        n = self._norm(z, key=key)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_PANEL, outline=COL_BORDER, width=1)
        tx0, tx1 = x0 + 8, x1 - 8
        by1 = y1 - 6
        by0 = by1 - 11
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM, font=self._font(self._fs(0.84)))
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=self._fmt(z, key), anchor="e", fill=COL_TEXT,
                      font=self._font(self._fs(0.88), bold=True))
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

        # Header: 2 Tabs (left 44%) + 3 Algorithm pills (right 56%)
        left_w = int((w - 2 * pad) * 0.44)
        tw = (left_w - gap) / 2
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)

        alg_idx = max(0, min(2, int(round(self._raw(self._get_zctrl("algorithm"), 1.0)))))
        ax0 = pad + left_w + gap
        aw = (w - pad - ax0 - 2 * gap) / 3
        for i, aname in enumerate(ALGORITHMS):
            bx0 = ax0 + i * (aw + gap)
            self._draw_pill(bx0, pad, bx0 + aw, pad + hdr_h, aname, i == alg_idx, "#ffd43b", "algo", i)

        bot_h = 98
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap
        c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL, outline=accent, width=1)

        if self.active_tab == "Plate":
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 16
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            dec_n = self._norm(self._get_zctrl("decay"), 0.25)
            wet_n = self._norm(self._get_zctrl("early_level"), 0.35)
            pre_n = self._norm(self._get_zctrl("predelay"), 0.05)
            dmp_n = self._norm(self._get_zctrl("early_damp"), 0.65, key="early_damp")
            c.create_text(gx0, vy0 + 11, text=f"Plate [{ALGORITHMS[alg_idx]}] Decay Tail  (Drag 2D: X=Decay, Y=Wet)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.80), bold=True))

            pre_x = gx0 + pre_n * (gw * 0.22)
            if pre_x > gx0 + 2:
                c.create_rectangle(gx0, gy0, pre_x, gy1, fill="#1b1815", outline="")
                c.create_line(pre_x, gy0, pre_x, gy1, fill="#54412e", dash=(3, 3))

            poly = [pre_x, gy1]
            line = []
            tau = 0.08 + dec_n * 0.88
            ripple_amp = (0.04, 0.09, 0.02)[alg_idx]
            ripple_f = (14.0, 26.0, 8.0)[alg_idx]
            for i in range(65):
                t = i / 64.0
                px = pre_x + t * (gx1 - pre_x)
                base_amp = math.exp(-t / tau) * (0.20 + 0.78 * wet_n)
                shimmer = 1.0 + ripple_amp * math.sin(t * ripple_f) * (0.4 + 0.6 * dmp_n)
                py = gy1 - max(0.0, min(1.0, base_amp * shimmer)) * gh
                poly.extend([px, py])
                line.extend([px, py])
            poly.extend([gx1, gy1])
            c.create_polygon(poly, fill="#332619", outline="")
            c.create_line(line, fill=accent, width=2.8)

            hx = gx0 + dec_n * gw
            hy = gy1 - wet_n * gh
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "decay", "yk": "early_level"}))
        else:
            # Tone tab: Spectral Bandpass & Damping EQ with Dual Nodes (LC blue, HC orange)
            gx0, gx1 = pad + 20, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 16
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            lc_hz = max(20.0, self._raw(self._get_zctrl("low_cut"), 80.0))
            hc_hz = max(200.0, self._raw(self._get_zctrl("high_cut"), 14000.0))
            dmp_hz = max(200.0, self._raw(self._get_zctrl("early_damp"), 6000.0))
            dmp_n = self._norm(self._get_zctrl("early_damp"), 0.6, key="early_damp")
            dry_n = self._norm(self._get_zctrl("dry_level"), 0.8)

            c.create_text(pad + 10, vy0 + 11, text="Plate Tone & Damping Spectrum  (Dual Nodes: L=LowCut, H=HiCut×Damp)",
                          anchor="w", fill=COL_DIM, font=self._font(self._fs(0.76), bold=True))

            f_min, f_max = 20.0, 20000.0
            log_span = math.log(f_max / f_min)

            def hz_to_x(hz):
                hz = max(f_min, min(f_max, hz))
                return gx0 + (math.log(hz / f_min) / log_span) * gw

            for f_hz, flbl in ((50, "50"), (200, "200"), (1000, "1k"), (4000, "4k"), (12000, "12k")):
                fx = hz_to_x(f_hz)
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 8, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.66)))

            pts, pts_dmp = [], []
            poly = [gx0, gy1]
            for i in range(65):
                t = i / 64.0
                f = f_min * ((f_max / f_min) ** t)
                hp = 1.0 / math.sqrt(1.0 + (lc_hz / f) ** 4)
                lp = 1.0 / math.sqrt(1.0 + (f / hc_hz) ** 4)
                dmp = 1.0 / math.sqrt(1.0 + (f / dmp_hz) ** 2)
                px = gx0 + t * gw
                v_band = 0.88 * hp * lp
                v_tail = v_band * dmp
                pts.extend([px, gy1 - v_band * gh])
                pts_dmp.extend([px, gy1 - v_tail * gh])
                poly.extend([px, gy1 - v_tail * gh])
            poly.extend([gx1, gy1])

            c.create_polygon(poly, fill="#1a2c3d", outline="")
            c.create_line(pts, fill="#80a8d6", width=1.8, dash=(3, 3))
            c.create_line(pts_dmp, fill=accent, width=2.8)

            lx, ly = hz_to_x(lc_hz), gy1 - dry_n * gh
            hx, hy = hz_to_x(hc_hz), gy1 - dmp_n * gh
            c.create_oval(lx - 10, ly - 10, lx + 10, ly + 10, fill=accent, outline="#ffffff", width=2)
            c.create_text(lx, ly, text="L", fill="#0d0e12", font=self._font(self._fs(0.76), bold=True))
            c.create_oval(hx - 10, hy - 10, hx + 10, hy + 10, fill="#ff922b", outline="#ffffff", width=2)
            c.create_text(hx, hy, text="H", fill="#0d0e12", font=self._font(self._fs(0.76), bold=True))

            self.hitboxes.append((pad, vy0, w - pad, vy1, "tone_dual", {
                "gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                "lx": lx, "ly": ly, "hx": hx, "hy": hy,
            }))

        py0 = vy1 + gap
        items = self._tab_items(self.active_tab)
        cw = (w - 2 * pad - gap) / 2
        ch = (h - pad - py0 - 4) / 2
        for i, (k, lbl) in enumerate(items):
            px0 = pad + (i % 2) * (cw + gap)
            py_i = py0 + (i // 2) * (ch + 4)
            self._draw_param_box(px0, py_i, px0 + cw, py_i + ch, k, lbl, accent)

    def _on_press(self, event):
        self.drag_target = None
        for x0, y0, x1, y1, kind, payload in reversed(self.hitboxes):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if kind == "tab":
                    if payload != self.active_tab:
                        self.active_tab = payload
                        self._select_page(payload)
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "algo":
                    z = self._get_zctrl("algorithm")
                    if z is not None:
                        ticks = getattr(z, "ticks", None)
                        z.set_value(ticks[payload] if ticks and payload < len(ticks) else float(payload), send=True)
                    self.last_snapshot = None
                    self._draw()
                    return
                if kind == "tone_dual":
                    now = time.monotonic()
                    d_l = math.hypot(event.x - payload["lx"], event.y - payload["ly"])
                    d_h = math.hypot(event.x - payload["hx"], event.y - payload["hy"])
                    node = "low" if d_l <= d_h else "high"
                    tid = ("tone_dual", node)
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = ["low_cut", "dry_level"] if node == "low" else ["high_cut", "early_damp"]
                        for rk in rks:
                            z = self._get_zctrl(rk)
                            if z is not None:
                                z.reset_value()
                        self.last_snapshot = None
                        self._draw()
                        return
                    self.last_tap = (tid, now)
                    target = dict(payload)
                    target["node"] = node
                    self.drag_target = ("tone_dual", target)
                    self._apply_drag(event.x, event.y)
                    return
                if kind in ("hfader", "xy_pad"):
                    now = time.monotonic()
                    tid = (kind, payload.get("key") or payload.get("xk"))
                    if tid == self.last_tap[0] and (now - self.last_tap[1]) <= DOUBLE_TAP_S:
                        self.last_tap = (None, 0.0)
                        rks = [payload["key"]] if kind == "hfader" else [payload["xk"], payload["yk"]]
                        for rk in rks:
                            z = self._get_zctrl(rk)
                            if z is not None:
                                z.reset_value()
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
            self._set_norm(self._get_zctrl(p["key"]), (x - p["tx0"]) / (p["tx1"] - p["tx0"]), key=p["key"])
        elif kind == "xy_pad":
            if p["gx1"] > p["gx0"]:
                self._set_norm(self._get_zctrl(p["xk"]), (x - p["gx0"]) / (p["gx1"] - p["gx0"]), key=p["xk"])
            if p["gy1"] > p["gy0"]:
                self._set_norm(self._get_zctrl(p["yk"]), (p["gy1"] - y) / (p["gy1"] - p["gy0"]), key=p["yk"])
        elif kind == "tone_dual":
            nx = max(0.0, min(1.0, (x - p["gx0"]) / max(1.0, p["gx1"] - p["gx0"])))
            ny = max(0.0, min(1.0, (p["gy1"] - y) / max(1.0, p["gy1"] - p["gy0"])))
            f_hz = 20.0 * ((20000.0 / 20.0) ** nx)
            if p["node"] == "low":
                z = self._get_zctrl("low_cut")
                if z is not None:
                    z.set_value(max(float(z.value_min), min(float(z.value_max), f_hz)), send=True)
                self._set_norm(self._get_zctrl("dry_level"), ny, key="dry_level")
            else:
                z = self._get_zctrl("high_cut")
                if z is not None:
                    z.set_value(max(float(z.value_min), min(float(z.value_max), f_hz)), send=True)
                self._set_norm(self._get_zctrl("early_damp"), ny, key="early_damp")
        self.last_snapshot = None
        self._draw()
