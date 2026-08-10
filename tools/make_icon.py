#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""生成 OMEN RGB 应用图标（参考 OGH/OMEN CC 图标重绘）。

风格：黑底圆角方块 + 红→橙渐变的对角环形 "O"（OMEN 标志的几何重绘）。

用法:
    python3 tools/make_icon.py [输出目录]
"""

from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter


# OGH 官方标志取色（从 Square44x44Logo 采样）
MAGENTA = (255, 44, 116)     # 顶部/左侧
RED = (255, 11, 29)          # 主体
ORANGE = (255, 95, 0)        # 右下
BG_TOP = (8, 8, 10)
BG_BOTTOM = (22, 22, 28)

SIZES = [512, 256, 128, 64, 48, 32]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ring_color(angle_deg):
    """渐变：225°(左上) 品红 → 315° 红 → 45°(右下) 橙。"""
    a = (angle_deg + 360) % 360
    if 225 <= a <= 315:
        return lerp(MAGENTA, RED, (a - 225) / 90.0)
    if a < 45:
        return lerp(RED, ORANGE, (a + 360 - 315) / 90.0)
    if a >= 315:
        return lerp(RED, ORANGE, (a - 315) / 90.0)
    return MAGENTA


def smoothstep(edge0, edge1, x):
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


def make_icon(size):
    """绘制一个 size x size 的图标（含 4x 超采样抗锯齿）。"""
    ss = 4
    S = size * ss

    # 背景：圆角方块 + 竖向微渐变
    bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    radius = int(S * 0.22)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=radius,
                        fill=(0, 0, 0, 0))
    grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gp = grad.load()
    for y in range(S):
        t = y / (S - 1)
        c = lerp(BG_TOP, BG_BOTTOM, t)
        for x in range(S):
            gp[x, y] = (c[0], c[1], c[2], 255)
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=255)
    bg = Image.composite(grad, bg, mask)

    # 环：菱形环（曼哈顿距离），即 OMEN 标志的几何形态
    cx = cy = S // 2
    r_out = S * 0.42
    r_in = S * 0.30
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rp = ring.load()
    span = int(S * 0.46)
    for y in range(cx - span, cx + span + 1):
        for x in range(cy - span, cy + span + 1):
            dist = abs(x - cx) + abs(y - cy)
            if dist > r_out + 2 or dist < r_in - 2:
                continue
            alpha = smoothstep(r_in - 2, r_in, dist) * (1 - smoothstep(r_out, r_out + 2, dist))
            if alpha <= 0:
                continue
            angle = math.degrees(math.atan2(y - cy, x - cx))
            c = ring_color(angle)
            rp[x, y] = (c[0], c[1], c[2], int(255 * alpha))

    # 合成：给环加一层柔和光晕
    glow = ring.filter(ImageFilter.GaussianBlur(S * 0.018))
    out = Image.alpha_composite(bg, glow)
    out = Image.alpha_composite(out, ring)

    return out.resize((size, size), Image.LANCZOS)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
    os.makedirs(outdir, exist_ok=True)
    for s in SIZES:
        path = os.path.join(outdir, "omenrgb-%d.png" % s)
        make_icon(s).save(path)
        print("生成 %s (%d×%d)" % (path, s, s))
    # 主图标（512）同时作为 omenrgb.png
    master = os.path.join(outdir, "omenrgb.png")
    make_icon(512).save(master)
    print("生成 %s" % master)
    return 0


if __name__ == "__main__":
    sys.exit(main())
