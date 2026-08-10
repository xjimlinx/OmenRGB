#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Transport matrix scan for the OMEN keyboard HID RGB interface.

Checks every vendor-ish interface with multiple report transports and init
sequences, reporting which combination gets any device response.

Run as root (needs /dev/bus/usb):
    sudo -n python3 tools/hid_matrix.py
"""

from __future__ import annotations

import ctypes
import fcntl
import glob
import os
import re
import sys
import time

USBDEVFS_CONTROL = 0xC0185500
USBDEVFS_CLAIMINTERFACE = 0x8004550F
USBDEVFS_RELEASEINTERFACE = 0x40045510
USBDEVFS_IOCTL = 0xC0105512
USBDEVFS_DISCONNECT = 0x00005516
USBDEVFS_CONNECT = 0x00005517
USBDEVFS_BULK = 0xC0185502
USBDEVFS_CLEAR_HALT = 0x80045515


def driver_ioctl(fd, ifno, code):
    pkt = ifno.to_bytes(4, "little", signed=True) + code.to_bytes(4, "little") + (0).to_bytes(8, "little")
    fcntl.ioctl(fd, USBDEVFS_IOCTL, pkt)


def ctrl(fd, req_type, request, wvalue, windex, length, data=None, timeout=2000):
    buf = ctypes.create_string_buffer(max(length, 1))
    if data is not None:
        buf.raw = bytes(data).ljust(length, b"\x00")
    pkt = (bytes([req_type, request])
           + wvalue.to_bytes(2, "little") + windex.to_bytes(2, "little")
           + length.to_bytes(2, "little") + timeout.to_bytes(4, "little")
           + b"\x00" * 4 + ctypes.addressof(buf).to_bytes(8, "little"))
    try:
        n = fcntl.ioctl(fd, USBDEVFS_CONTROL, pkt, True)
        if not isinstance(n, int):
            return None, "ioctl returned %r" % (n,)
        return n, buf.raw[:max(n, 0)]
    except OSError as exc:
        return None, str(exc)


def bulk(fd, ep, data, timeout=2000):
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    pkt = (ep.to_bytes(4, "little") + len(data).to_bytes(4, "little")
           + timeout.to_bytes(4, "little") + b"\x00" * 4
           + ctypes.addressof(buf).to_bytes(8, "little"))
    try:
        n = fcntl.ioctl(fd, USBDEVFS_BULK, pkt, True)
        return n, None
    except OSError as exc:
        return None, str(exc)


def clear_halt(fd, ep):
    try:
        fcntl.ioctl(fd, USBDEVFS_CLEAR_HALT, ep.to_bytes(4, "little"))
        return "ok"
    except OSError as exc:
        return str(exc)


INIT_SEQS = [
    ("none", b""),
    ("usermode-fcea", bytes([0x04, 0x00, 0x02, 0x00, 0xFC, 0xEA]) + b"\x00" * 58),
    ("hyperx-init", bytes([0x04, 0xF2, 0, 0, 0, 0, 0, 0, 0x09]) + b"\x00" * 55),
    ("lighting-on", bytes([0x09, 0x00, 0x01, 0x00, 0xFF]) + b"\x00" * 59),
]

GET_CMDS = [
    ("get-device-info", bytes([0x80, 0x01, 0x00, 0x00]) + b"\x00" * 60),
    ("get-effect", bytes([0x80, 0x01, 0x00, 0x00]) + b"\x00" * 60),
]


def find_interfaces():
    """Return {iface_num: (hidraw, usbfs, usage_page_hex)} for all 0C45:7D1C."""
    out = {}
    for rd in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/report_descriptor")):
        dev = os.path.realpath(os.path.join(os.path.dirname(rd), "..", ".."))
        try:
            idv = open(os.path.join(dev, "idVendor")).read().strip()
            idp = open(os.path.join(dev, "idProduct")).read().strip()
        except OSError:
            continue
        if idv.lower() != "0c45" or idp.lower() != "7d1c":
            continue
        hidraw = "/dev/" + rd.split("/")[4]
        bus = int(open(os.path.join(dev, "busnum")).read().strip())
        num = int(open(os.path.join(dev, "devnum")).read().strip())
        usbfs = "/dev/bus/usb/%03d/%03d" % (bus, num)
        iface = None
        for part in os.path.realpath(os.path.dirname(rd)).split("/"):
            m = re.search(r":(\d+)\.(\d+)", part)
            if m:
                iface = int(m.group(2))
        try:
            desc = open(rd, "rb").read()
        except OSError:
            desc = b""
        usage = desc[:3].hex()
        out.setdefault(iface, {"hidraw": hidraw, "usbfs": usbfs, "usage": usage, "hidraws": []})
        out[iface]["hidraws"].append(hidraw)
    return out


def try_interface(iface, info):
    print("\n==== interface %s  usage=%s hidraws=%s ====" % (iface, info["usage"], info["hidraws"]))
    fd = os.open(info["usbfs"], os.O_RDWR)
    if iface not in (2, 3):
        print("  skipping (testing interfaces 2 and 3)")
        os.close(fd)
        return
    try:
        driver_ioctl(fd, iface, USBDEVFS_DISCONNECT)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, iface.to_bytes(4, "little"))
    except OSError as exc:
        print("  claim failed: %s" % exc)
        os.close(fd)
        return

    for seq_name, init in INIT_SEQS:
        if init:
            n, r = ctrl(fd, 0x21, 0x09, (2 << 8) | 0, iface, 64, init)
            if n is not None:
                print("  [%s] init setreport64 -> n=%d %s" % (seq_name, n, r.hex(" ") if isinstance(r, bytes) else r))
            n, r = ctrl(fd, 0x21, 0x09, (2 << 8) | 0, iface, 65, b"\x00" + init)
            if n is not None:
                print("  [%s] init setreport65 -> n=%d" % (seq_name, n))
            n, r = bulk(fd, 0x05, init)
            print("  [%s] init bulk05 -> %r %s" % (seq_name, n, r or ""))
        for cmd_name, cmd in GET_CMDS:
            for label, payload, length, wv in (
                ("setreport64", cmd, 64, (2 << 8) | 0),
                ("setreport65", b"\x00" + cmd, 65, (2 << 8) | 0),
                ("setreport65-id05", b"\x05" + cmd, 65, (2 << 8) | 0),
                ("setreport-id05-no0", cmd, 64, (2 << 8) | 5),
                ("setfeature64", cmd, 64, (3 << 8) | 0),
            ):
                n, r = ctrl(fd, 0x21, 0x09, wv, iface, length, payload)
                if isinstance(r, bytes) and n and n > 0:
                    print("  [%s|%s] %s -> n=%d resp=%s" % (seq_name, cmd_name, label, n, r.hex(" ")))
                else:
                    print("  [%s|%s] %s -> %r %s" % (seq_name, cmd_name, label, n, r if isinstance(r, str) else ""))
            n, r = ctrl(fd, 0xA1, 0x01, (1 << 8) | 0, iface, 64)
            if isinstance(r, bytes) and n and n > 0:
                print("  [%s|%s] getreport-input -> n=%d resp=%s" % (seq_name, cmd_name, n, r.hex(" ")))
            n, r = ctrl(fd, 0xA1, 0x01, (1 << 8) | 5, iface, 65)
            if isinstance(r, bytes) and n and n > 0:
                print("  [%s|%s] getreport-input-id05 -> n=%d resp=%s" % (seq_name, cmd_name, n, r.hex(" ")))
            n, r = ctrl(fd, 0xA1, 0x01, (3 << 8) | 0, iface, 64)
            if isinstance(r, bytes) and n and n > 0:
                print("  [%s|%s] getreport-feature -> n=%d resp=%s" % (seq_name, cmd_name, n, r.hex(" ")))
            if iface == 3:
                n, r = bulk(fd, 0x05, cmd)
                print("  [%s|%s] bulk05 -> %r %s" % (seq_name, cmd_name, n, r or ""))
                n, r = bulk(fd, 0x84, cmd)
                if n:
                    print("  [%s|%s] bulk84-in -> n=%d %s" % (seq_name, cmd_name, n, r.hex(" ") if isinstance(r, bytes) else r))

    for attempt in range(3):
        try:
            fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, iface.to_bytes(4, "little"))
            break
        except OSError as exc:
            if attempt == 2:
                print("  release failed: %s" % exc)
            time.sleep(0.2)
    time.sleep(0.3)
    ok = False
    for attempt in range(5):
        try:
            driver_ioctl(fd, iface, USBDEVFS_CONNECT)
            ok = True
            break
        except OSError:
            time.sleep(0.3)
    print("  reconnected" if ok else "  reconnect FAILED")
    os.close(fd)


def main():
    ifs = find_interfaces()
    print("interfaces: %s" % ifs)
    for iface in sorted(ifs):
        try_interface(iface, ifs[iface])
    return 0


if __name__ == "__main__":
    sys.exit(main())
