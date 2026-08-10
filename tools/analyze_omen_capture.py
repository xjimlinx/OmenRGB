#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract OMEN keyboard RGB reports from a USBPcap capture.

Usage:
    python3 tools/analyze_omen_capture.py <capture.pcap|pcapng|folder>

Uses tshark (Wireshark) to read the capture, filters for USB traffic of
VID 0x0C45 / PID 0x7D1C and prints:
  - every USB URB for the keyboard (time, endpoint, direction, length),
  - the payload of interrupt OUT transfers and SET_REPORT control transfers
    (these carry the RGB configuration),
  - the unique payloads and how often each appears (helps spot the
    red/green/blue/breathing packets).
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys


TSHARK_CANDIDATES = [
    r"D:\Wireshark\tshark.exe",
    r"C:\Program Files\Wireshark\tshark.exe",
    "/usr/bin/tshark",
    "/usr/local/bin/tshark",
]


def find_tshark():
    for cand in TSHARK_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    cand = shutil.which("tshark")
    if cand:
        return cand
    print("未找到 tshark，请安装 Wireshark 或指定路径。")
    sys.exit(1)


def capture_files(path):
    if os.path.isdir(path):
        return sorted(
            f
            for pat in ("*.pcap", "*.pcapng", "*.cap")
            for f in glob.glob(os.path.join(path, pat))
        )
    return [path]


FIELDS = [
    "frame.number",
    "frame.time_relative",
    "usb.bus_id",
    "usb.device_address",
    "usb.urb_type",
    "usb.endpoint_address",
    "usb.transfer_type",
    "usb.data_len",
    "usb.capdata",
    "usb.setup.bmRequestType",
    "usb.setup.bRequest",
    "usb.setup.wValue",
    "usb.setup.wIndex",
]


def tshark_fields(tshark, cap, extra_filter=""):
    base = "usb.idVendor == 0x0c45 && usb.idProduct == 0x7d1c"
    display = "%s%s" % (base, (" && " + extra_filter) if extra_filter else "")
    cmd = [
        tshark,
        "-r", cap,
        "-Y", display,
        "-T", "fields",
        "-E", "separator=|",
        "-E", "occurrence=f",
    ]
    for f in FIELDS:
        cmd += ["-e", f]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        return None, proc.stderr.strip()
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.split("|")
        rows.append(dict(zip(FIELDS, parts)))
    return rows, None


URB_NAMES = {
    "0x00000001": "SUBMIT",
    "0x00000002": "COMPLETE",
    "0x00000004": "ERROR",
}
TRANSFER_NAMES = {"0": "control", "1": "isoc", "2": "bulk", "3": "interrupt"}


def describe(row):
    ep = row.get("usb.endpoint_address", "")
    transfer = TRANSFER_NAMES.get(row.get("usb.transfer_type", ""), row.get("usb.transfer_type", ""))
    return "%s ep=%s %s len=%s" % (transfer, ep or "?", URB_NAMES.get(row.get("usb.urb_type", ""), row.get("usb.urb_type", "")), row.get("usb.data_len", "?"))


def analyze_file(tshark, cap):
    print("#" * 100)
    print("文件: %s" % cap)
    rows, err = tshark_fields(tshark, cap)
    if err:
        print("  tshark 失败: %s" % err)
        print("  提示: 如果过滤器没有匹配，试试用 Wireshark 打开并输入 usb.idVendor == 0x0c45")
        return
    if not rows:
        print("  (该文件没有 0C45:7D1C 的 USB 流量)")
        return

    print("  共 %d 条键盘 USB 记录:" % len(rows))
    payloads = {}
    for row in rows:
        data = row.get("usb.capdata", "")
        req = row.get("usb.setup.bRequest", "")
        tag = []
        if req:  # control transfer
            tag.append("SETUP bRequest=%s wValue=%s wIndex=%s" % (req, row.get("usb.setup.wValue", ""), row.get("usb.setup.wIndex", "")))
        tag.append(describe(row))
        print("  #%-6s t=%-8s %s" % (row.get("frame.number", ""), row.get("frame.time_relative", ""), " ".join(tag)))
        if data:
            print("      data: %s" % data)
            payloads.setdefault(data, 0)
            payloads[data] += 1

    if payloads:
        print()
        print("  不重复的 payload（出现次数）:")
        for data, count in sorted(payloads.items(), key=lambda kv: -kv[1]):
            print("    [%3d] %s" % (count, data))


def main():
    parser = argparse.ArgumentParser(description="从 USBPcap 抓包里提取 OMEN 键盘 RGB 报告")
    parser.add_argument("capture", help="pcap/pcapng 文件或包含抓包的文件夹")
    args = parser.parse_args()

    tshark = find_tshark()
    files = capture_files(args.capture)
    if not files:
        print("没有找到抓包文件。")
        return 1
    for cap in files:
        analyze_file(tshark, cap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
