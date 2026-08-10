#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""OMEN RGB 键盘控制器 — 深色游戏风 GUI（纯 tkinter，无额外依赖）。

硬件操作直接调用 WmiAcpiBackend；需要 root 的 WMAA 调用通过
仓库内两个固定脚本（tools/wmi_call.py、tools/hid_probe_linux.py）以
sudo -n 免密执行（需先运行 sudo ./install-sudo-rules.sh 安装一次规则），
因此普通用户即可改色，无需每次输密码。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
import tkinter.colorchooser as colorchooser
import tkinter.font as tkfont
import tkinter.messagebox as messagebox
from tkinter import ttk

from omenrgb import __version__
from omenrgb.core import OmenError, detect_backend, validate_rgb
from omenrgb.wmi_backend import ANIMATION_MODES, WmiAcpiBackend
from omenrgb import presets


# ---------------------------------------------------------------- palette
BG = "#0D1117"
PANEL = "#151B23"
PANEL2 = "#1B222C"
CARD = "#10151C"
BORDER = "#2A313C"
TEXT = "#E6EDF3"
MUTED = "#8B949E"
ACCENT = "#58A6FF"
ACCENT_DARK = "#1F6FEB"
OK = "#3FB950"
WARN = "#D29922"
ERR = "#F85149"
ZONE_GLOW = "#79C0FF"

ZONE_NAMES = ["QWER/ASDF", "左侧", "中间", "右侧"]

# 底部按钮按物理左→右排列：(分区索引, 显示名)
ZONE_BUTTONS = [(1, "左侧"), (0, "QWER/ASDF"), (2, "中间"), (3, "右侧")]

PRESET_HEX = [
    "FF3B30", "FF9500", "FFCC00", "34C759",
    "00C7BE", "007AFF", "5856D6", "AF52DE",
    "FF2D55", "FF6482", "FFD60A", "30D158",
    "64D2FF", "5E5CE6", "BF5AF2", "FFFFFF",
]

ANIMATION_CHOICES = ["静态"] + [name for name in sorted(ANIMATION_MODES)]


def round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    """Draw a rectangle on a tk.Canvas (simple, robust rendering)."""
    return canvas.create_rectangle(x1, y1, x2, y2, **kwargs)


class FlatButton(tk.Label):
    """A flat, hoverable button built on tk.Label for full styling control."""

    def __init__(self, master, text, command, *, bg=PANEL2, fg=TEXT,
                 hover=ACCENT_DARK, accent=False, padx=12, pady=6,
                 font=None, cursor="hand2"):
        self._bg = ACCENT if accent else bg
        self._fg = "#FFFFFF" if accent else fg
        self._hover = hover
        self._command = command
        self._disabled = False
        super().__init__(
            master, text=text, bg=self._bg, fg=self._fg, padx=padx, pady=pady,
            font=font or ("Sans", 10, "bold" if accent else "normal"),
            cursor=cursor, borderwidth=0,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, _e):
        if not self._disabled:
            self.configure(bg=self._hover)

    def _on_leave(self, _e):
        if not self._disabled:
            self.configure(bg=self._bg)

    def _on_click(self, _e):
        if not self._disabled:
            self._command()

    def set_disabled(self, flag):
        self._disabled = flag
        self.configure(bg="#21262D" if flag else self._bg, cursor="arrow" if flag else "hand2")


class Section(tk.Frame):
    """A titled dark card used for each control group."""

    def __init__(self, master, title, **kw):
        super().__init__(master, bg=PANEL, **kw)
        tk.Label(self, text=title, bg=PANEL, fg=MUTED,
                 font=("Sans", 9, "bold")).pack(anchor="w", padx=14, pady=(10, 4))
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=14, pady=(0, 12))


class OmenRGBApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OMEN RGB 键盘控制器")
        self.geometry("980x660")
        self.minsize(880, 600)
        self.configure(bg=BG)
        try:
            self.tk.call("tk", "scaling", 1.15)
        except tk.TclError:
            pass
        self._setup_ttk_style()

        self._selected = "all"          # "all" or 0..3
        self._zone_colors = ["FFFFFF"] * 4
        self._brightness = 100
        self._kbam = None
        self._kbam_label = None
        self._backend = None

        self._build()
        self.after(150, self._refresh)

    def _setup_ttk_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TScale", background=BG, troughcolor=PANEL2,
                        bordercolor=BORDER, lightcolor=PANEL2, darkcolor=PANEL2,
                        sliderlength=16)
        style.map("TScale", background=[("active", ACCENT)])
        style.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                        foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER,
                        lightcolor=PANEL2, darkcolor=PANEL2, padding=4)
        style.map("TCombobox",
                  fieldbackground=[("readonly", PANEL2)],
                  foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", PANEL2)],
                  selectforeground=[("readonly", TEXT)])

    # ------------------------------------------------------------- layout
    def _build(self):
        self._build_header()

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=18, pady=(4, 10))
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0)
        main.grid_rowconfigure(0, weight=1)

        self._build_keyboard_panel(main)
        self._build_side_panel(main)
        self._build_statusbar()

    def _build_header(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 2))
        left = tk.Frame(header, bg=BG)
        left.pack(side="left")
        tk.Label(left, text="OMEN RGB", bg=BG, fg=TEXT,
                 font=("Sans", 20, "bold")).pack(anchor="w")
        tk.Label(left, text="HP OMEN 16 · 四分区键盘灯控 · v%s" % __version__,
                 bg=BG, fg=MUTED, font=("Sans", 10)).pack(anchor="w", pady=(0, 2))

        right = tk.Frame(header, bg=BG)
        right.pack(side="right")
        self._backend_badge = tk.Label(right, text="后端: 检测中…", bg=PANEL2, fg=MUTED,
                                       padx=10, pady=5, font=("Sans", 9))
        self._backend_badge.pack(side="left", padx=(0, 8))
        self._kbam_badge = tk.Label(right, text="KBAM: --", bg=PANEL2, fg=MUTED,
                                    padx=10, pady=5, font=("Sans", 9))
        self._kbam_badge.pack(side="left", padx=(0, 8))
        FlatButton(right, "刷新", self._refresh, accent=True).pack(side="left")

    def _build_keyboard_panel(self, parent):
        panel = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        top = tk.Frame(panel, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(top, text="点击分区选择颜色", bg=PANEL, fg=MUTED,
                 font=("Sans", 9)).pack(side="left")
        self._sel_label = tk.Label(top, text="当前选择: 全部区域", bg=PANEL,
                                   fg=ACCENT, font=("Sans", 10, "bold"))
        self._sel_label.pack(side="right")

        self._canvas = tk.Canvas(panel, bg=CARD, highlightthickness=0, height=400)
        self._canvas.pack(fill="both", expand=True, padx=16, pady=8)
        self._canvas.bind("<Configure>", lambda e: self._redraw_keyboard())
        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._zone_items = {}

        bottom = tk.Frame(panel, bg=PANEL)
        bottom.pack(fill="x", padx=16, pady=(0, 14))
        FlatButton(bottom, "全部区域", lambda: self._select("all"), bg=PANEL2).pack(side="left")
        for idx, name in ZONE_BUTTONS:
            FlatButton(bottom, name, lambda i=idx: self._select(i), bg=PANEL2
                       ).pack(side="left", padx=(8, 0))

    def _build_side_panel(self, parent):
        panel = tk.Frame(parent, bg=BG)
        panel.grid(row=0, column=1, sticky="ns")

        # 颜色
        sec = Section(panel, "颜色")
        sec.pack(fill="x", pady=(0, 12))
        grid = tk.Frame(sec.body, bg=PANEL)
        grid.pack(fill="x")
        self._swatches = []
        for i, hexv in enumerate(PRESET_HEX):
            r, c = divmod(i, 4)
            sw = tk.Label(grid, bg="#%s" % hexv, width=3, height=1, cursor="hand2",
                          highlightthickness=1, highlightbackground=PANEL)
            sw.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
            sw.bind("<Button-1>", lambda _e, h=hexv: self._apply_hex(h))
            self._swatches.append(sw)
        for c in range(4):
            grid.grid_columnconfigure(c, weight=1)

        entry_row = tk.Frame(sec.body, bg=PANEL)
        entry_row.pack(fill="x", pady=(10, 0))
        self._hex_var = tk.StringVar(value="FF0000")
        self._hex_entry = tk.Entry(entry_row, textvariable=self._hex_var, bg=PANEL2,
                                   fg=TEXT, insertbackground=TEXT, relief="flat",
                                   font=("Sans Mono", 12, "bold"), justify="center")
        self._hex_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self._hex_entry.bind("<Return>", lambda e: self._apply_hex(self._hex_var.get()))
        FlatButton(entry_row, "取色器", self._pick_color, accent=True, padx=10
                   ).pack(side="left", padx=(8, 0))
        FlatButton(sec.body, "应用到所选分区", self._apply_current, bg=PANEL2
                   ).pack(fill="x", pady=(10, 0), ipady=4)

        # 亮度
        sec = Section(panel, "亮度")
        sec.pack(fill="x", pady=(0, 12))
        self._brightness_var = tk.IntVar(value=100)
        scale = ttk.Scale(sec.body, from_=0, to=100, variable=self._brightness_var,
                          command=self._on_brightness_drag)
        scale.pack(fill="x")
        row = tk.Frame(sec.body, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        self._brightness_label = tk.Label(row, text="100%", bg=PANEL, fg=TEXT,
                                          font=("Sans", 11, "bold"), width=5)
        self._brightness_label.pack(side="left")
        FlatButton(row, "应用亮度", self._apply_brightness, bg=PANEL2
                   ).pack(side="right")

        # 动画
        sec = Section(panel, "动画")
        sec.pack(fill="x", pady=(0, 12))
        self._anim_var = tk.StringVar(value="静态")
        self._anim_combo = ttk.Combobox(sec.body, textvariable=self._anim_var,
                                        values=ANIMATION_CHOICES, state="readonly")
        self._anim_combo.pack(fill="x")
        self._anim_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_animation())
        tk.Label(sec.body, text="选择后立即发送（实验性）", bg=PANEL, fg=MUTED,
                 font=("Sans", 8)).pack(anchor="w", pady=(4, 0))

        # 预设
        sec = Section(panel, "预设")
        sec.pack(fill="x")
        self._preset_var = tk.StringVar()
        self._preset_combo = ttk.Combobox(sec.body, textvariable=self._preset_var,
                                          state="readonly")
        self._preset_combo.pack(fill="x")
        row = tk.Frame(sec.body, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        FlatButton(row, "应用", self._apply_preset, bg=PANEL2).pack(side="left", expand=True, fill="x")
        FlatButton(row, "保存", self._save_preset, bg=PANEL2).pack(side="left", padx=(8, 0), expand=True, fill="x")
        FlatButton(row, "删除", self._delete_preset, bg=PANEL2).pack(side="left", padx=(8, 0), expand=True, fill="x")

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        bar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="就绪")
        self._status_label = tk.Label(bar, textvariable=self._status_var, bg=PANEL,
                                      fg=MUTED, font=("Sans", 9))
        self._status_label.pack(side="left", padx=16, pady=8)
        tk.Label(bar, text="写入立即生效", bg=PANEL, fg=OK,
                 font=("Sans", 9)).pack(side="right", padx=16)

    # ------------------------------------------------------- keyboard view
    def _redraw_keyboard(self):
        c = self._canvas
        c.delete("all")
        w = max(c.winfo_width(), 320)
        h = max(c.winfo_height(), 260)

        body = (30, 36, w - 30, h - 36)
        round_rect(c, *body, 16, fill=PANEL2, outline=BORDER, width=1)
        self._keyboard_rect = body

        # subtle key grid
        x1, y1, x2, y2 = body
        for gx in range(x1 + 28, x2 - 16, 34):
            c.create_line(gx, y1 + 26, gx, y2 - 18, fill="#232B36", width=1)
        for gy in range(y1 + 34, y2 - 12, 34):
            c.create_line(x1 + 22, gy, x2 - 10, gy, fill="#232B36", width=1)

        # zone geometry, indexed by WMI 分区号 (0..3)，按实测物理位置：
        # 0=QWER/ASDF 区、1=左侧、2=中间、3=右侧（含数字键盘）
        self._zone_geom = [
            (x1 + 190, y1 + 24, x1 + 330, y2 - 20),   # 0 QWER/ASDF
            (x1 + 18, y1 + 24, x1 + 178, y2 - 20),    # 1 左侧
            (x1 + 342, y1 + 24, x2 - 178, y2 - 20),   # 2 中间
            (x2 - 166, y1 + 24, x2 - 18, y2 - 20),    # 3 右侧
        ]
        for i, (zx1, zy1, zx2, zy2) in enumerate(self._zone_geom):
            fill = "#%s" % self._zone_colors[i]
            self._zone_items[i] = round_rect(
                c, zx1, zy1, zx2, zy2, 12,
                fill=fill, outline="#FFFFFF", width=0,
            )
            # name label
            c.create_text((zx1 + zx2) // 2, (zy1 + zy2) // 2,
                          text=ZONE_NAMES[i], fill="#FFFFFF",
                          font=("Sans", 9, "bold"))

        self._draw_selection()
        c.create_text(x2 - 20, y1 + 12, text="OMEN", fill=MUTED,
                      font=("Sans", 8, "bold"), anchor="e")

    def _draw_selection(self):
        c = self._canvas
        if self._selected == "all":
            round_rect(c, *self._keyboard_rect, 16, outline=ACCENT, width=3)
        else:
            zx1, zy1, zx2, zy2 = self._zone_geom[self._selected]
            round_rect(c, zx1 - 3, zy1 - 3, zx2 + 3, zy2 + 3, 14,
                       outline=ZONE_GLOW, width=3)

    def _on_canvas_click(self, event):
        for i in range(4):
            zx1, zy1, zx2, zy2 = self._zone_geom[i]
            if zx1 <= event.x <= zx2 and zy1 <= event.y <= zy2:
                self._select(i)
                return

    def _select(self, sel):
        self._selected = sel
        label = "全部区域" if sel == "all" else ZONE_NAMES[sel]
        self._sel_label.configure(text="当前选择: %s" % label)
        self._redraw_keyboard()

    # ----------------------------------------------------------- hardware
    def _backend_instance(self):
        if self._backend is None:
            if WmiAcpiBackend.driver_present():
                self._backend = WmiAcpiBackend(elevate=True)
            else:
                self._backend = detect_backend(elevate=True)
            if self._backend is None:
                raise OmenError(
                    "未检测到可用后端",
                    hint="请确认 acpi_call 模块已加载（sudo modprobe acpi_call），"
                         "或已安装 omen-rgb-keyboard 内核驱动。",
                )
        return self._backend

    def _refresh(self):
        self._set_status("读取状态…", muted=True)
        try:
            backend = self._backend_instance()
            state = backend.get_state()
            self._zone_colors = state["zones"]
            self._brightness = state["brightness"]
            self._brightness_var.set(self._brightness)
            self._brightness_label.configure(text="%d%%" % self._brightness)
            self._kbam = state.get("kbam")
            self._kbam_label = state.get("kbam_label")
            self._backend_name = state.get("backend")
            self._backend_badge.configure(
                text="后端: %s" % (self._backend_name or "?"),
                fg=OK if self._backend_name else ERR)
            if self._kbam is not None:
                self._kbam_badge.configure(
                    text="KBAM: %d (%s)" % (self._kbam, self._kbam_label or "?"),
                    fg=ACCENT)
            self._redraw_keyboard()
            self._load_presets()
            self._set_status("状态已刷新", ok=True)
        except Exception as exc:  # noqa: BLE001 - surface any parse error
            self._set_status("读取状态失败: %s" % exc, error=True)

    def _apply_hex(self, hexv):
        try:
            hexv = validate_rgb(hexv)
        except OmenError as exc:
            self._set_status(exc.message, error=True)
            return
        self._hex_var.set(hexv)
        try:
            backend = self._backend_instance()
            if self._selected == "all":
                backend.set_all(hexv)
                self._zone_colors = [hexv] * 4
                msg = "已应用 #%s 到全部区域" % hexv
            else:
                backend.set_zone(self._selected, hexv)
                self._zone_colors[self._selected] = hexv
                msg = "已应用 #%s 到%s" % (hexv, ZONE_NAMES[self._selected])
            self._redraw_keyboard()
            self._set_status(msg, ok=True)
        except OmenError as exc:
            self._set_status(exc.message, error=True, hint=exc.hint)

    def _apply_current(self):
        self._apply_hex(self._hex_var.get())

    def _pick_color(self):
        rgb, _ = colorchooser.askcolor(
            color="#%s" % self._hex_var.get(), title="选择颜色", parent=self)
        if rgb:
            self._apply_hex("%02X%02X%02X" % tuple(int(c) for c in rgb))

    def _on_brightness_drag(self, value):
        level = round(float(value))
        self._brightness_label.configure(text="%d%%" % level)

    def _apply_brightness(self):
        level = self._brightness_var.get()
        try:
            self._backend_instance().set_brightness(level)
            self._set_status("亮度已设为 %d%%" % level, ok=True)
        except OmenError as exc:
            self._set_status(exc.message, error=True, hint=exc.hint)

    def _apply_animation(self):
        choice = self._anim_var.get()
        try:
            if choice == "静态":
                self._apply_current()
            else:
                self._backend_instance().set_animation(choice)
                self._set_status("已发送动画: %s" % choice, ok=True)
        except OmenError as exc:
            self._set_status(exc.message, error=True, hint=exc.hint)

    # -------------------------------------------------------------- presets
    def _load_presets(self):
        try:
            names = list(presets.load().keys())
        except Exception:
            names = []
        self._preset_combo["values"] = names
        if names and not self._preset_var.get():
            self._preset_var.set(names[0])

    def _apply_preset(self):
        name = self._preset_var.get()
        if not name:
            return
        try:
            state = presets.get(name)
        except KeyError as exc:
            self._set_status("预设不存在: %s" % exc, error=True)
            return
        try:
            backend = self._backend_instance()
            zones = state.get("zones")
            if zones and len(zones) == 4:
                backend.set_all(validate_rgb(zones[0]))
                for i, c in enumerate(zones[1:], start=1):
                    if validate_rgb(c) != validate_rgb(zones[0]):
                        backend.set_zone(i, validate_rgb(c))
                self._zone_colors = [validate_rgb(c) for c in zones]
            b = state.get("brightness")
            if b is not None:
                backend.set_brightness(b)
                self._brightness_var.set(b)
            mode = state.get("mode")
            if mode and mode != "static" and mode in ANIMATION_MODES:
                backend.set_animation(mode)
            self._redraw_keyboard()
            self._set_status("已应用预设: %s" % name, ok=True)
        except OmenError as exc:
            self._set_status(exc.message, error=True, hint=exc.hint)

    def _save_preset(self):
        import tkinter.simpledialog as simpledialog
        name = simpledialog.askstring("保存预设", "预设名称:", parent=self)
        if not name:
            return
        state = {
            "mode": "static",
            "speed": 5,
            "brightness": self._brightness_var.get(),
            "zones": list(self._zone_colors),
            "gradient": "",
        }
        try:
            presets.save(name, state)
        except ValueError as exc:
            self._set_status("保存失败: %s" % exc, error=True)
            return
        self._load_presets()
        self._preset_var.set(name)
        self._set_status("已保存预设: %s" % name, ok=True)

    def _delete_preset(self):
        name = self._preset_var.get()
        if not name:
            return
        if not messagebox.askyesno("删除预设", "确定删除预设「%s」？" % name, parent=self):
            return
        presets.delete(name)
        self._load_presets()
        self._set_status("已删除预设: %s" % name)

    # ------------------------------------------------------------- status
    def _set_status(self, text, ok=False, error=False, muted=False, hint=None):
        color = MUTED if muted else ERR if error else OK if ok else TEXT
        self._status_var.set(text)
        self._status_label.configure(fg=color)
        if error and hint:
            messagebox.showerror("OMEN RGB", "%s\n\n提示: %s" % (text, hint), parent=self)


def main():
    app = OmenRGBApp()
    app.mainloop()


if __name__ == "__main__":
    main()
