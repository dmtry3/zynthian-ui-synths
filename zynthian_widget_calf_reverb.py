#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# Calf Reverb Widget for Zynthian (V5 800x480 & touchscreens)
# Part of UI Synths (zynthian-ui-synths)
#
# 3 dynamic tabs mapped 1-to-1 to Zynthian's 4 physical encoders:
#   Space | EQ & Damp | Mix & I/O   + ON/BYP
# Features live reverberation decay tail + room selector, interactive EQ & HF
# damping response curve, and 2D Wet/Dry balance pad.
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

COL_BG = zynthian_gui_config.color_bg
COL_PANEL = "#1b1c22"
COL_PANEL_HI = "#252730"
COL_BORDER = "#333644"
COL_GRID = "#262833"
COL_TRACK = "#282a36"
COL_TEXT = zynthian_gui_config.color_tx
COL_DIM = "#808496"

TABS = ["Space", "EQ & Damp", "Mix & I/O"]
TAB_ACCENTS = {
    "Space":     "#4dabf7",
    "EQ & Damp": "#ff922b",
    "Mix & I/O": "#51cf66",
}

ROOM_LABELS = ["Small", "Medium", "Large", "Tunnel", "Smooth", "Experim"]
LOG_KEYS = {"decay_time", "hf_damp", "bass_cut", "treble_cut", "level_in", "level_out"}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def fmt_hz(hz):
    return f"{hz / 1000.0:.2f}kHz" if hz >= 1000.0 else f"{hz:.0f}Hz"


def fmt_db(gain):
    if gain <= 1e-4:
        return "-inf"
    return f"{20.0 * math.log10(gain):+.1f}dB"


class zynthian_widget_calf_reverb(zynthian_widget_base.zynthian_widget_base):

    def __init__(self, parent):
        super().__init__(parent)
        self.next_update = 0.0
        self.active_tab = "Space"
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
        if tab == "Space":
            return [
                ("decay_time", "Decay"),
                ("room_size",  "Room"),
                ("diffusion",  "Diffusion"),
                ("predelay",   "PreDelay"),
            ]
        if tab == "EQ & Damp":
            return [
                ("bass_cut",   "Bass Cut"),
                ("treble_cut", "TrebleCut"),
                ("hf_damp",    "HF Damp"),
                ("decay_time", "Decay"),
            ]
        return [
            ("amount",    "Wet Amt"),
            ("dry",       "Dry Amt"),
            ("level_in",  "In Gain"),
            ("level_out", "Out Gain"),
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
            logging.debug(f"Calf Reverb sync error: {e}")

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
        if getattr(z, "is_integer", False) or key == "room_size":
            val = int(round(val))
        z.set_value(max(vmin, min(vmax, val)), send=True)

    @staticmethod
    def _fmt(z, key):
        if z is None:
            return "--"
        v = zynthian_widget_calf_reverb._raw(z)
        if key == "decay_time":
            return f"{v:.2f}s" if v < 10.0 else f"{v:.1f}s"
        if key == "predelay":
            return f"{v:.0f}ms"
        if key == "diffusion":
            return f"{int(round(v * 100))}%"
        if key == "room_size":
            idx = max(0, min(len(ROOM_LABELS) - 1, int(round(v))))
            return ROOM_LABELS[idx]
        if key in ("hf_damp", "bass_cut", "treble_cut"):
            return fmt_hz(v)
        if key in ("amount", "dry", "level_in", "level_out"):
            return fmt_db(v)
        return f"{v:.2f}"

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
        keys = ("on", "decay_time", "hf_damp", "room_size", "diffusion",
                "amount", "dry", "predelay", "bass_cut", "treble_cut", "level_in", "level_out")
        snap = (self.width, self.height, self.active_tab,
                tuple(round(self._raw(self._get_zctrl(k)), 3) for k in keys))
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
        fnt = self._fit_font(text, max(16, (x1 - x0) - 6), self._fs(0.88), bold=True)
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
        lbl_f = self._fit_font(label, avail * 0.52, self._fs(0.82), bold=False)
        val_f = self._fit_font(val_txt, avail * 0.48, self._fs(0.86), bold=True)
        c.create_text(tx0, y0 + (by0 - y0) / 2, text=label, anchor="w", fill=COL_DIM, font=lbl_f)
        c.create_text(tx1, y0 + (by0 - y0) / 2, text=val_txt, anchor="e", fill=COL_TEXT, font=val_f)
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

        pad = 6
        gap = 6
        accent = TAB_ACCENTS[self.active_tab]
        is_on = self._raw(self._get_zctrl("on"), 1.0) >= 0.5

        hdr_h = max(36, min(46, int(h * 0.11)))
        byp_w = 68
        tabs_w = w - 2 * pad - byp_w - gap
        tw = (tabs_w - 2 * gap) / 3
        for i, t in enumerate(TABS):
            tx0 = pad + i * (tw + gap)
            self._draw_pill(tx0, pad, tx0 + tw, pad + hdr_h, t, t == self.active_tab, TAB_ACCENTS[t], "tab", t)
        self._draw_pill(w - pad - byp_w, pad, w - pad, pad + hdr_h,
                        "ON ●" if is_on else "BYP", is_on, "#51cf66", "toggle", "on")

        bot_h = 96
        vy0 = pad + hdr_h + gap
        vy1 = h - pad - bot_h - gap

        if self.active_tab == "Space":
            # Room selector row (6 pills, >=34px) at top of main area
            row_h = 34
            ry0, ry1 = vy0, vy0 + row_h
            rw = (w - 2 * pad - 5 * gap) / 6
            room_idx = max(0, min(5, int(round(self._raw(self._get_zctrl("room_size"), 2.0)))))
            for i, rlbl in enumerate(ROOM_LABELS):
                rx0 = pad + i * (rw + gap)
                self._draw_pill(rx0, ry0, rx0 + rw, ry1, rlbl, i == room_idx, accent, "room", i)
            py0 = ry1 + gap
            c.create_rectangle(pad, py0, w - pad, vy1, fill=COL_PANEL,
                               outline=accent if is_on else COL_BORDER, width=1)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = py0 + 20, vy1 - 12
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            hdr_txt = "Decay Tail  (Drag 2D: X=Decay, Y=Diffusion)"
            c.create_text(gx0, py0 + 10, text=hdr_txt, anchor="w", fill=COL_DIM,
                          font=self._fit_font(hdr_txt, gw, self._fs(0.78), bold=True))

            dec_n = self._norm(self._get_zctrl("decay_time"), "decay_time")
            dif_n = self._norm(self._get_zctrl("diffusion"), "diffusion")
            pre_n = self._norm(self._get_zctrl("predelay"), "predelay")
            damp_n = self._norm(self._get_zctrl("hf_damp"), "hf_damp")

            # Grid lines
            for frac in (0.25, 0.5, 0.75):
                gy = gy0 + frac * gh
                c.create_line(gx0, gy, gx1, gy, fill=COL_GRID, dash=(2, 4))

            # Pre-delay offset + exponential reverb tail polygon
            px_start = gx0 + pre_n * gw * 0.28
            tail_w = max(12, (gx1 - px_start) * (0.22 + 0.78 * dec_n))
            # Pre-delay marker
            c.create_line(gx0, gy1, gx0, gy0 + 4, fill="#ffffff", width=2)
            if px_start > gx0 + 3:
                c.create_line(gx0, gy1 - 3, px_start, gy1 - 3, fill="#ffd43b", width=2)

            # Main decay envelope & HF-damped inner tail
            poly_lo = [px_start, gy1]
            poly_hi = [px_start, gy1]
            k_lo = 3.2 - 1.4 * dec_n
            k_hi = k_lo + (1.0 - damp_n) * 3.5
            for i in range(41):
                t = i / 40.0
                x = px_start + t * tail_w
                # Diffusion controls initial density/build-up smoothness
                buildup = 1.0 - math.exp(-t * (4.0 + 18.0 * (1.0 - dif_n)))
                amp_lo = buildup * math.exp(-k_lo * t)
                amp_hi = buildup * math.exp(-k_hi * t)
                poly_lo.extend([x, gy1 - amp_lo * (gh * 0.92)])
                poly_hi.extend([x, gy1 - amp_hi * (gh * 0.85)])
            poly_lo.extend([px_start + tail_w, gy1])
            poly_hi.extend([px_start + tail_w, gy1])
            c.create_polygon(poly_lo, fill="#1e3550" if is_on else "#22242c", outline="")
            c.create_polygon(poly_hi, fill="#294c73" if is_on else "#282a34", outline="")
            c.create_line(poly_lo[2:-2], fill=accent if is_on else COL_DIM, width=2.4)

            hx = gx0 + dec_n * gw
            hy = gy1 - dif_n * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, py0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "decay_time", "yk": "diffusion"}))

        elif self.active_tab == "EQ & Damp":
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL,
                               outline=accent if is_on else COL_BORDER, width=1)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 18
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            hdr_txt = "Reverb EQ & HF Damping  (Drag 2D: X=Bass Cut, Y=Treble Cut)"
            c.create_text(gx0, vy0 + 11, text=hdr_txt, anchor="w", fill=COL_DIM,
                          font=self._fit_font(hdr_txt, gw, self._fs(0.78), bold=True))

            bc = self._raw(self._get_zctrl("bass_cut"), 300.0)
            tc = self._raw(self._get_zctrl("treble_cut"), 5000.0)
            hd = self._raw(self._get_zctrl("hf_damp"), 5000.0)
            bc_n = self._norm(self._get_zctrl("bass_cut"), "bass_cut")
            tc_n = self._norm(self._get_zctrl("treble_cut"), "treble_cut")

            # Log frequency grid (20Hz..20kHz)
            for f_hz, flbl in ((100, "100"), (1000, "1k"), (5000, "5k"), (10000, "10k")):
                fx = gx0 + (math.log(f_hz / 20.0) / math.log(1000.0)) * gw
                c.create_line(fx, gy0, fx, gy1, fill=COL_GRID, dash=(2, 4))
                c.create_text(fx, gy1 + 9, text=flbl, fill=COL_DIM, font=self._font(self._fs(0.72)))

            # Compute bandpass + damping curve
            pts_eq = []
            pts_dmp = []
            for i in range(65):
                t = i / 64.0
                f = 20.0 * (1000.0 ** t)
                hp = 1.0 / math.sqrt(1.0 + (bc / max(1.0, f)) ** 4)
                lp = 1.0 / math.sqrt(1.0 + (f / max(1.0, tc)) ** 4)
                mag = hp * lp
                dmp = mag / math.sqrt(1.0 + (f / max(1.0, hd)) ** 2)
                x = gx0 + t * gw
                pts_eq.extend([x, gy1 - mag * gh * 0.90])
                pts_dmp.extend([x, gy1 - dmp * gh * 0.90])

            poly_eq = [gx0, gy1] + pts_eq + [gx1, gy1]
            c.create_polygon(poly_eq, fill="#382515" if is_on else "#22242c", outline="")
            c.create_line(pts_dmp, fill="#4dabf7", width=1.8, dash=(4, 3))
            c.create_line(pts_eq, fill=accent if is_on else COL_DIM, width=2.6)

            hx = gx0 + bc_n * gw
            hy = gy1 - tc_n * gh
            c.create_oval(hx - 8, hy - 8, hx + 8, hy + 8, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "bass_cut", "yk": "treble_cut"}))

        else:  # Mix & I/O
            c.create_rectangle(pad, vy0, w - pad, vy1, fill=COL_PANEL,
                               outline=accent if is_on else COL_BORDER, width=1)
            gx0, gx1 = pad + 14, w - pad - 14
            gy0, gy1 = vy0 + 22, vy1 - 14
            gw, gh = max(20, gx1 - gx0), max(20, gy1 - gy0)
            hdr_txt = "Wet × Dry Balance  (Drag 2D: X=Wet Amount, Y=Dry Amount)"
            c.create_text(gx0, vy0 + 11, text=hdr_txt, anchor="w", fill=COL_DIM,
                          font=self._fit_font(hdr_txt, gw, self._fs(0.78), bold=True))

            wet_n = self._norm(self._get_zctrl("amount"), "amount")
            dry_n = self._norm(self._get_zctrl("dry"), "dry")

            # Crosshair + unity (0dB = 0.5) guides
            mx, my = gx0 + gw * 0.5, gy0 + gh * 0.5
            c.create_line(mx, gy0, mx, gy1, fill=COL_GRID, dash=(3, 4))
            c.create_line(gx0, my, gx1, my, fill=COL_GRID, dash=(3, 4))
            c.create_text(gx1 - 2, my - 8, text="0dB", anchor="e", fill=COL_DIM, font=self._font(self._fs(0.72)))

            hx = gx0 + wet_n * gw
            hy = gy1 - dry_n * gh
            c.create_rectangle(gx0, hy, hx, gy1, fill="#193322" if is_on else "#22242c", outline="")
            c.create_line(hx, gy0, hx, gy1, fill="#334c3a", dash=(2, 3))
            c.create_line(gx0, hy, gx1, hy, fill="#334c3a", dash=(2, 3))
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=accent, outline="#ffffff", width=2)
            self.hitboxes.append((pad, vy0, w - pad, vy1, "xy_pad",
                                  {"gx0": gx0, "gx1": gx1, "gy0": gy0, "gy1": gy1,
                                   "xk": "amount", "yk": "dry"}))

        # 2x2 encoder-linked parameter boxes at bottom
        items = self._tab_items(self.active_tab)
        by0 = h - pad - bot_h
        cw = (w - 2 * pad - gap) / 2
        ch = (bot_h - gap) / 2
        for i, (k, lbl) in enumerate(items):
            rx0 = pad + (i % 2) * (cw + gap)
            ry0 = by0 + (i // 2) * (ch + gap)
            self._draw_param_box(rx0, ry0, rx0 + cw, ry0 + ch, k, lbl, accent)

    def _reset_default(self, key):
        z = self._get_zctrl(key)
        if z is not None:
            z.set_value(z.value_default, send=True)
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
                        self.last_snapshot = None
                        self._draw()
                    return
                if kind == "room":
                    z = self._get_zctrl("room_size")
                    if z is not None:
                        z.set_value(int(payload), send=True)
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

    def _on_drag(self, event):
        if self.drag_target:
            self._apply_drag(event.x, event.y)

    def _on_release(self, event):
        self.drag_target = None

    def _apply_drag(self, x, y):
        kind, p = self.drag_target
        if kind == "hfader":
            n = (x - p["tx0"]) / max(1.0, p["tx1"] - p["tx0"])
            self._set_norm(self._get_zctrl(p["key"]), n, p["key"])
        elif kind == "xy_pad":
            nx = (x - p["gx0"]) / max(1.0, p["gx1"] - p["gx0"])
            ny = 1.0 - (y - p["gy0"]) / max(1.0, p["gy1"] - p["gy0"])
            self._set_norm(self._get_zctrl(p["xk"]), nx, p["xk"])
            self._set_norm(self._get_zctrl(p["yk"]), ny, p["yk"])
        self.last_snapshot = None
        self._draw()
