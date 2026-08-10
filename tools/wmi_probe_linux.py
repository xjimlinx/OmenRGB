#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Probe / drive the HP OMEN keyboard backlight through ACPI WMI + acpi_call.

This script talks to the firmware exactly like the in-kernel hp-wmi driver
does, but through the acpi_call module (/proc/acpi/call), so no kernel patch
or out-of-tree driver is required.

Usage (run as root):
    sudo python3 tools/wmi_probe_linux.py                  # read-only probe
    sudo python3 tools/wmi_probe_linux.py --set FF0000     # all 4 zones red
    sudo python3 tools/wmi_probe_linux.py --zone 0 00FF00  # zone 1 green
    sudo python3 tools/wmi_probe_linux.py --bright 75      # brightness 75

If the color read is truncated (acpi_call limits its text output to 256
bytes), the script prints instructions to enlarge BUFFER_SIZE and rebuild.
"""

from __future__ import annotations

import argparse
import os
import re
import sys


CALL_PATHS = ("/proc/acpi/call", "/sys/kernel/debug/acpi/call")
WMAA = r"\_SB.WMID.WMAA"

SIGNATURE = 0x55434553  # "SECU"
PASS_SIG = 0x53534150  # "PASS"

CMD_BACKLIGHT = 0x00020009
CMD_GAMING = 0x00020008

KEYBOARD_TYPES = {
    0: "无背光",
    1: "四分区 带数字键盘",
    2: "四分区 无数字键盘",
    3: "RGB 每键",
    4: "单分区 带数字键盘",
    5: "单分区 无数字键盘",
}


def find_call():
    for p in CALL_PATHS:
        if os.path.exists(p):
            return p
    return None


def mid_for_outsize(outsize):
    if outsize > 128:
        return 4
    if outsize > 4:
        return 3
    if outsize > 0:
        return 2
    return 1


def wmaa(cmdtype, payload=b"", outsize=128, command=CMD_BACKLIGHT, verbose=False):
    """Call \\_SB.WMID.WMAA and return (raw_response_bytes, truncated, text)."""
    path = find_call()
    if not path:
        sys.exit("错误: 未找到 acpi_call 接口。\n"
                 "  安装: sudo apt install acpi-call-dkms dkms   (Debian/Ubuntu)\n"
                 "        yay -S acpi_call-dkms                  (Arch)\n"
                 "  然后: sudo modprobe acpi_call")

    buf = bytearray(16 + len(payload))
    buf[0:4] = SIGNATURE.to_bytes(4, "little")
    buf[4:8] = command.to_bytes(4, "little")
    buf[8:12] = cmdtype.to_bytes(4, "little")
    buf[12:16] = len(payload).to_bytes(4, "little")
    buf[16:] = payload

    mid = mid_for_outsize(outsize)
    line = "%s 0 %d b%s" % (WMAA, mid, buf.hex())
    if verbose:
        print("  [call] %s" % line)

    try:
        with open(path, "w", encoding="ascii") as fh:
            fh.write(line + "\n")
        with open(path, "r", encoding="ascii", errors="replace") as fh:
            result = fh.read().strip()
    except PermissionError:
        sys.exit("错误: 没有权限读写 %s。\n  请用 sudo 运行本脚本（acpi_call 接口只有 root 可写）。" % path)
    except OSError as exc:
        sys.exit("错误: 访问 %s 失败: %s" % (path, exc))
    if verbose:
        print("  [raw ] %s" % result)

    tokens = re.findall(r"0x([0-9A-Fa-f]{2})", result)
    if not tokens:
        sys.exit("错误: WMAA 调用失败，返回: %r\n"
                 "  可能原因: acpi_call 模块未加载 / Secure Boot 拒绝未签名模块。\n"
                 "  检查: lsmod | grep acpi_call ; dmesg | grep -i acpi_call" % result)
    raw = bytes(int(t, 16) for t in tokens)
    truncated = not result.rstrip().endswith("}")
    return raw, truncated, result


def check_response(raw, text):
    if len(raw) < 8:
        sys.exit("错误: WMAA 返回过短: %s" % text)
    sig = int.from_bytes(raw[0:4], "little")
    retc = int.from_bytes(raw[4:8], "little")
    if sig != PASS_SIG:
        sys.exit("错误: 返回签名 0x%08X (应为 PASS), RETC=0x%X, 原文: %s"
                 % (sig, retc, text))
    if retc != 0:
        sys.exit("错误: WMAA 返回 RETC=0x%X (1=成功, 2=签名错误, 3=未知命令, "
                 "4=未知CMDT, 5=数据长度错误, 6=数据值错误)" % retc)
    return raw


def cmd_read(verbose):
    print("== 读取键盘类型 (0x20008 / 0x2B) ==")
    raw, trunc, text = wmaa(0x2B, outsize=4, command=CMD_GAMING, verbose=verbose)
    raw = check_response(raw, text)
    ktype = raw[8]
    print("  RE20=%d -> %s" % (ktype, KEYBOARD_TYPES.get(ktype, "未知")))

    print("\n== 读取背光能力 (0x20009 / 0x01) ==")
    raw, trunc, text = wmaa(0x01, outsize=4, verbose=verbose)
    raw = check_response(raw, text)
    print("  返回: %s" % " ".join("%02X" % b for b in raw[8:12]))

    print("\n== 读取亮度 (0x20009 / 0x04) ==")
    raw, trunc, text = wmaa(0x04, outsize=4, verbose=verbose)
    raw = check_response(raw, text)
    print("  LBRT=0x%02X (%d)" % (raw[8], raw[8]))

    print("\n== 读取颜色表 (0x20009 / 0x02) ==")
    raw, trunc, text = wmaa(0x02, outsize=128, verbose=verbose)
    raw = check_response(raw, text)
    print("  收到 %d 字节 %s" % (len(raw), "(被 acpi_call 截断!)" if trunc else ""))
    for i in range(0, len(raw), 16):
        print("    0x%02X: %s" % (i, " ".join("%02X" % b for b in raw[i:i + 16])))
    base = 8 + 0x19
    if len(raw) >= base + 12:
        print("  分区颜色 (表偏移 0x19):")
        for zone in range(4):
            off = base + zone * 3
            print("    分区 %d: #%02X%02X%02X" % (zone + 1, raw[off], raw[off + 1], raw[off + 2]))
    else:
        print("  颜色数据被截断，无法完整读取 4 个分区。")
        patch_hint()


def patch_hint():
    print("""
  ------------------------------------------------------------------
  acpi_call 把结果文本限制在 256 字节，136 字节的响应只显示前 42 字节。
  修复（改完重编译一次即可，之后所有读写都正常）：

    sudo sed -i 's/#define BUFFER_SIZE 256/#define BUFFER_SIZE 2048/' \\
        /usr/src/acpi_call-*/acpi_call.c
    sudo dkms reinstall acpi_call -k $(uname -r)

  (Arch: 编辑 /usr/src/acpi_call-*/acpi_call.c 后重新 makepkg 安装，
   或直接改源码后 sudo make -C /usr/src/acpi_call-* install)
  ------------------------------------------------------------------
""")


def cmd_set(rgb, verbose):
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", rgb or ""):
        sys.exit("颜色必须是 6 位十六进制 RRGGBB，如 FF0000")
    r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
    payload = bytearray(128)
    for zone in range(4):
        off = 0x19 + zone * 3
        payload[off] = r
        payload[off + 1] = g
        payload[off + 2] = b
    print("== 写入全部 4 个分区颜色 #%s (0x20009 / 0x03) ==" % rgb.upper())
    raw, trunc, text = wmaa(0x03, bytes(payload), outsize=128, verbose=verbose)
    check_response(raw, text)
    print("  写入成功 (RETC=0)。")


def cmd_zone(index, rgb, verbose):
    if not 0 <= index < 4:
        sys.exit("分区必须是 0-3")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", rgb or ""):
        sys.exit("颜色必须是 6 位十六进制 RRGGBB，如 FF0000")
    print("== 先读当前颜色表 ==")
    raw, trunc, text = wmaa(0x02, outsize=128, verbose=verbose)
    raw = check_response(raw, text)
    base = 8 + 0x19
    if len(raw) < base + 12:
        sys.exit("颜色表被截断，无法读改写单个分区。请先按提示扩大 acpi_call BUFFER_SIZE。")
    colors = [bytes(raw[base + z * 3: base + z * 3 + 3]) for z in range(4)]
    print("  当前: %s" % " ".join("#%s" % c.hex().upper() for c in colors))
    colors[index] = bytes((int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)))
    payload = bytearray(128)
    for zone, c in enumerate(colors):
        off = 0x19 + zone * 3
        payload[off:off + 3] = c
    print("== 写回分区 %d = #%s (0x20009 / 0x03) ==" % (index, rgb.upper()))
    raw, trunc, text = wmaa(0x03, bytes(payload), outsize=128, verbose=verbose)
    check_response(raw, text)
    print("  写入成功 (RETC=0)。")


def cmd_bright(level, verbose):
    if not 0 <= level <= 100:
        sys.exit("亮度必须是 0-100")
    value = 0xE4 if level > 0 else 0x64
    print("== 写亮度 (0x20009 / 0x05) LBRT=0x%02X (%d%%) ==" % (value, level))
    raw, trunc, text = wmaa(0x05, bytes([value]), outsize=1, verbose=verbose)
    check_response(raw, text)
    raw, trunc, text = wmaa(0x04, outsize=4, verbose=verbose)
    raw = check_response(raw, text)
    print("  读回 LBRT=0x%02X (%d)" % (raw[8], raw[8]))


def main():
    parser = argparse.ArgumentParser(description="HP OMEN 键盘背光 WMI 探测/控制")
    parser.add_argument("--set", metavar="RRGGBB", help="把 4 个分区都设为该颜色")
    parser.add_argument("--zone", nargs=2, metavar=("N", "RRGGBB"), help="设置单个分区颜色")
    parser.add_argument("--bright", type=int, metavar="0-100", help="设置亮度")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印原始调用与响应")
    args = parser.parse_args()

    if getattr(os, "geteuid", lambda: 1)() != 0:
        print("警告: 不是 root，acpi_call 读写通常需要 root。")

    if args.set:
        cmd_set(args.set, args.verbose)
    elif args.zone:
        cmd_zone(int(args.zone[0]), args.zone[1], args.verbose)
    elif args.bright is not None:
        cmd_bright(args.bright, args.verbose)
    else:
        cmd_read(args.verbose)


if __name__ == "__main__":
    main()
