#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line interface for the OMEN RGB keyboard tool."""

from __future__ import annotations

import argparse
import json
import sys

from omenrgb import __version__
from omenrgb.core import (
    ANIMATION_LABELS,
    ANIMATION_NAMES,
    OmenError,
    detect_backend,
    diagnose,
    format_diagnose,
    quick_help,
)
from omenrgb.wmi_backend import ANIMATION_MODES as WMI_ANIMATION_MODES
from omenrgb import presets


def _get_backend(args):
    backend = detect_backend(elevate=not args.no_elevate)
    if backend is None:
        print(
            "错误: 未检测到可用的 RGB 后端。\n"
            "  1) 先安装内核驱动:  sudo ./install-driver.sh\n"
            "  2) 或运行诊断查看原因:  omenrgb diagnose",
            file=sys.stderr,
        )
        sys.exit(1)
    return backend


def cmd_status(args):
    backend = _get_backend(args)
    state = backend.get_state()
    if getattr(args, "json", False):
        print(json.dumps(state, ensure_ascii=False))
        return 0
    print("后端: %s" % state["backend"])
    print("区域颜色: %s" % ", ".join(state["zones"]))
    print("亮度: %d%%" % state["brightness"])
    mode = state["mode"]
    print("动画模式: %s (%s)" % (mode, ANIMATION_LABELS.get(mode, mode)))
    print("动画速度: %d" % state["speed"])
    if state.get("gradient"):
        print("渐变配置: %s" % state["gradient"])
    kbam = state.get("kbam")
    if kbam is not None:
        label = state.get("kbam_label") or ("未知(0x%02X)" % kbam)
        print("键盘实际模式 (KBAM): %d (%s)" % (kbam, label))
        print()
        print("提示: 颜色通过 EC 邮箱（Dojo 协议）实时写入键盘，")
        print("      写入后立即生效；动画可用 'omenrgb animate <效果>' 发送。")
    return 0


def cmd_diagnose(args):
    print(format_diagnose(diagnose()))
    return 0


def cmd_get(args):
    backend = _get_backend(args)
    name = args.attr
    if name in ("zone", "zones"):
        print(", ".join(backend.get_zone(i) for i in range(4)))
    elif name == "all":
        print(backend.get_all())
    elif name == "brightness":
        print(backend.get_brightness())
    elif name == "mode":
        print(backend.get_mode())
    elif name == "speed":
        print(backend.get_speed())
    elif name == "gradient":
        print(backend.get_gradient() or "(空)")
    elif name == "kbam":
        value = backend.read_kbam()
        print("%d (%s)" % (value, backend.kbam_label(value)))
    else:
        print("未知属性: %s" % name, file=sys.stderr)
        return 1
    return 0


def cmd_set_zone(args):
    backend = _get_backend(args)
    backend.set_zone(args.index, args.rgb)
    return 0


def cmd_set_all(args):
    backend = _get_backend(args)
    backend.set_all(args.rgb)
    return 0


def cmd_brightness(args):
    backend = _get_backend(args)
    backend.set_brightness(args.level)
    return 0


def cmd_apply_ec(args):
    """Write colors + brightness straight to the EC MMIO window."""
    backend = _get_backend(args)
    if not hasattr(backend, "apply_ec"):
        print("错误: 当前后端不支持直接 EC 写入", file=sys.stderr)
        return 1
    colors = None
    if args.rgb:
        colors = [args.rgb] * 4
    brightness = args.level
    backend.apply_ec(colors=colors, brightness=brightness)
    print("已直接写入 EC（颜色=%s 亮度=%s）"
          % (colors or "不变", "不变" if brightness is None else brightness))
    return 0


def cmd_kbam(args):
    backend = _get_backend(args)
    if args.value is None:
        value = backend.read_kbam()
        print("KBAM = %d (%s)" % (value, backend.kbam_label(value)))
    else:
        backend.write_kbam(args.value)
        print("KBAM 已写为 %d，读回 %d" % (args.value, backend.read_kbam()))
    return 0


def cmd_animate(args):
    backend = _get_backend(args)
    if not hasattr(backend, "set_animation"):
        print("错误: 当前后端不支持动画", file=sys.stderr)
        return 1
    backend.set_animation(args.mode)
    print("已发送动画: %s" % args.mode)
    return 0


def cmd_mode(args):
    backend = _get_backend(args)
    backend.set_mode(args.mode)
    return 0


def cmd_speed(args):
    backend = _get_backend(args)
    backend.set_speed(args.speed)
    return 0


def cmd_gradient(args):
    backend = _get_backend(args)
    backend.set_gradient(args.config)
    return 0


def cmd_preset(args):
    backend = _get_backend(args)
    action = args.action
    if action == "list":
        for name in presets.load():
            print(name)
    elif action == "save":
        name = args.name
        state = backend.get_state()
        try:
            presets.save(name, state)
        except ValueError as exc:
            print("错误: %s" % exc, file=sys.stderr)
            return 1
        print("已保存预设: %s" % name)
    elif action == "delete":
        if presets.delete(args.name):
            print("已删除预设: %s" % args.name)
        else:
            print("预设不存在: %s" % args.name, file=sys.stderr)
            return 1
    elif action == "apply":
        try:
            state = presets.get(args.name)
        except KeyError as exc:
            print("错误: %s" % exc, file=sys.stderr)
            return 1
        backend.apply_state(state)
        print("已应用预设: %s" % args.name)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="omenrgb",
        description="HP OMEN 4-zone RGB 键盘控制工具 (v%s)" % __version__,
        epilog=quick_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--no-elevate",
        action="store_true",
        help="写入失败时不要自动尝试 pkexec/sudo 提权",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="显示驱动和当前灯光状态")
    p_status.add_argument("--json", action="store_true", help="以 JSON 输出")
    sub.add_parser("diagnose", help="生成详细诊断报告")

    p_get = sub.add_parser("get", help="读取某个属性")
    p_get.add_argument("attr", choices=["zone", "all", "brightness", "mode", "speed", "gradient", "kbam"])

    p_zone = sub.add_parser("set-zone", help="设置单个区域颜色")
    p_zone.add_argument("index", type=int, help="区域 0-3")
    p_zone.add_argument("rgb", help="RRGGBB 十六进制颜色，如 FF0000")

    p_all = sub.add_parser("set-all", help="设置全部区域为同一颜色")
    p_all.add_argument("rgb", help="RRGGBB 十六进制颜色，如 00FF00")

    p_br = sub.add_parser("brightness", help="设置亮度 0-100")
    p_br.add_argument("level", type=int)

    p_ec = sub.add_parser("apply-ec", help="直接写 EC 寄存器（绕过 WMI，强力写入）")
    p_ec.add_argument("--rgb", help="全部 4 个区域的颜色 RRGGBB")
    p_ec.add_argument("--level", type=int, help="亮度 0-100")

    p_kbam = sub.add_parser("kbam", help="读取/写入键盘模式寄存器 KBAM")
    p_kbam.add_argument("value", nargs="?", type=int, help="写入值 0-255（默认只读）")

    p_ani = sub.add_parser("animate", help="发送动画效果（EC 邮箱 Dojo 协议）")
    p_ani.add_argument("mode", help="效果名: %s" % ", ".join(sorted(WMI_ANIMATION_MODES)))

    p_mode = sub.add_parser("mode", help="设置动画模式")
    p_mode.add_argument("mode", choices=sorted(ANIMATION_NAMES))

    p_speed = sub.add_parser("speed", help="设置动画速度 1-10")
    p_speed.add_argument("speed", type=int)

    p_grad = sub.add_parser("gradient", help="设置渐变配置")
    p_grad.add_argument("config", help="例如 '0,1,2:FF0000,00FF00,0000FF;3:FF00FF,FFA500'")

    p_pre = sub.add_parser("preset", help="预设管理")
    pre_sub = p_pre.add_subparsers(dest="action", required=True)
    pre_sub.add_parser("list", help="列出所有预设")
    for action in ("save", "delete", "apply"):
        pp = pre_sub.add_parser(action, help="%s 预设" % action)
        pp.add_argument("name", help="预设名称")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        handlers = {
            "status": cmd_status,
            "diagnose": cmd_diagnose,
            "get": cmd_get,
            "set-zone": cmd_set_zone,
            "set-all": cmd_set_all,
            "brightness": cmd_brightness,
            "apply-ec": cmd_apply_ec,
            "kbam": cmd_kbam,
            "animate": cmd_animate,
            "mode": cmd_mode,
            "speed": cmd_speed,
            "gradient": cmd_gradient,
            "preset": cmd_preset,
        }
        return handlers[args.command](args)
    except OmenError as exc:
        print("错误: %s" % exc.message, file=sys.stderr)
        if exc.hint:
            print("提示: %s" % exc.hint, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
