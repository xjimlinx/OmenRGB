#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Guided visual test for the OMEN keyboard RGB HID channel.

Confirmed transport: interface 2 (keyboard HID, "mi_02" on Windows),
control SET_REPORT(output), 64-byte reports, report ID 0.

Run as root and WATCH the keyboard. Each step pauses so you can check whether
the keyboard reacted (brightness/color/blink). Report back which step number
changed anything.

    sudo python3 tools/visual_test.py
"""

from __future__ import annotations

import ctypes
import fcntl
import glob
import os
import re
import subprocess
import sys
import time

USBDEVFS_CONTROL = 0xC0185500
USBDEVFS_CLAIMINTERFACE = 0x8004550F
USBDEVFS_RELEASEINTERFACE = 0x40045510
USBDEVFS_IOCTL = 0xC0105512
USBDEVFS_DISCONNECT = 0x00005516
USBDEVFS_CONNECT = 0x00005517

PAUSE = 3.0
IFACE = 2
USBFS = "/dev/bus/usb/005/005"
BIND = "/sys/bus/usb/drivers/usbhid/bind"


def note(msg):
    print("\n>>> %s" % msg)
    time.sleep(PAUSE)


def find_hidraw(iface):
    for rd in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/report_descriptor")):
        dev = os.path.realpath(os.path.join(os.path.dirname(rd), "..", ".."))
        try:
            idv = open(os.path.join(dev, "idVendor")).read().strip()
            idp = open(os.path.join(dev, "idProduct")).read().strip()
        except OSError:
            continue
        if idv.lower() != "0c45" or idp.lower() != "7d1c":
            continue
        for part in os.path.realpath(os.path.dirname(rd)).split("/"):
            m = re.search(r":(\d+)\.(\d+)", part)
            if m and int(m.group(2)) == iface:
                return "/dev/" + rd.split("/")[4]
    return None


def driver_ioctl(fd, ifno, code):
    pkt = ifno.to_bytes(4, "little", signed=True) + code.to_bytes(4, "little") + (0).to_bytes(8, "little")
    fcntl.ioctl(fd, USBDEVFS_IOCTL, pkt)


def ctrl(fd, req_type, request, wvalue, windex, length, data=None, timeout=2000):
    buf = ctypes.create_string_buffer(max(length, 1))
    if data is not None:
        buf.raw = bytes(data).ljust(length, b"\x00")
    pkt = (bytes([req_type, request]) + wvalue.to_bytes(2, "little") + windex.to_bytes(2, "little")
           + length.to_bytes(2, "little") + timeout.to_bytes(4, "little")
           + b"\x00" * 4 + ctypes.addressof(buf).to_bytes(8, "little"))
    try:
        fcntl.ioctl(fd, USBDEVFS_CONTROL, pkt, True)
        return 0, bytes(buf.raw)
    except OSError as exc:
        return None, str(exc)


def make(cmd, sub, length, payload=b""):
    buf = bytearray(64)
    buf[0] = cmd & 0xFF
    buf[1] = sub & 0xFF
    buf[2] = length & 0xFF
    buf[4:4 + len(payload)] = payload
    return bytes(buf)


def send(fd, label, pkt):
    n, r = ctrl(fd, 0x21, 0x09, (2 << 8) | 0, IFACE, 64, pkt)
    print("  [%s] %s" % (label, "OK" if n == 0 else r))
    return n == 0


def restore_iface():
    # rebind via sysfs (works even if the usbfs reconnect ioctl fails)
    try:
        subprocess.run(["bash", "-c", 'echo -n "5-1.3:1.%d" > %s' % (IFACE, BIND)],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    time.sleep(1)
    if find_hidraw(IFACE):
        print("  接口 %d 已恢复（hidraw=%s）" % (IFACE, find_hidraw(IFACE)))
    else:
        print("  接口 %d 恢复失败，请运行: echo -n '5-1.3:1.%d' | sudo tee %s"
              % (IFACE, IFACE, BIND))


def static_packets(rgb):
    r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
    data = bytes([r, g, b]) * 48  # 144 bytes
    return [
        ("3页(60+60+24)", [
            make(0x03, 0x00, 0x3C, data[:60]),
            make(0x03, 0x01, 0x3C, data[60:120]),
            make(0x03, 0x02, 0x18, data[120:144]),
        ]),
        ("单包144B", [make(0x03, 0x00, 0x90, data)]),
        ("0x81风格", [make(0x81, 0x00, 0x3C, (bytes([0x81, r, g, b]) * 15)[4:64])]),
    ]


def main() -> int:
    if os.geteuid() != 0:
        print("请用 sudo 运行")
        return 1
    hid = find_hidraw(IFACE)
    print("接口 %d hidraw=%s usbfs=%s" % (IFACE, hid, USBFS))

    note("步骤 0：记住键盘当前颜色（粉色）。每步停 3 秒观察变化。")

    fd = os.open(USBFS, os.O_RDWR)
    try:
        try:
            driver_ioctl(fd, IFACE, USBDEVFS_DISCONNECT)
        except OSError:
            pass
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, IFACE.to_bytes(4, "little"))
        print("已独占接口 %d" % IFACE)
    except OSError as exc:
        print("claim 失败: %s" % exc)
        os.close(fd)
        return 1

    try:
        send(fd, "启用软件控制", make(0x04, 0x00, 0x02, b"\xFC\xEA"))
        note("步骤 1.1：键盘有变化吗？（亮度/颜色）")

        send(fd, "开灯", make(0x09, 0x00, 0x01, b"\xFF"))
        note("步骤 1.2：键盘有变化吗？")

        send(fd, "查询设备", make(0x80, 0x01, 0x00))
        note("步骤 1.3：键盘有变化吗？")

        for vname, pkts in static_packets("FF0000"):
            for pkt in pkts:
                send(fd, vname, pkt)
            note("步骤 2.%s：键盘变红了吗？" % vname)

        for vname, pkts in static_packets("00FF00"):
            for pkt in pkts:
                send(fd, vname, pkt)
            note("步骤 3.%s：键盘变绿了吗？" % vname)
    finally:
        try:
            fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, IFACE.to_bytes(4, "little"))
        except OSError:
            pass
        time.sleep(0.3)
        try:
            driver_ioctl(fd, IFACE, USBDEVFS_CONNECT)
        except OSError:
            pass
        os.close(fd)
        restore_iface()

    print("\n完成。请告诉我哪一步有变化（尤其步骤 1.x 和 2.x）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
