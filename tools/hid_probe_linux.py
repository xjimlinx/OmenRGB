#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Probe the Primax/HyperX OMEN laptop keyboard over its 0xFF90 HID interface.

Reverse-engineered from HP.Omen.AccessoryKeyboardLightingModule +
McuKeyboardLightingSDK (Windows OMEN Command Center):

  64-byte command report:
    [0] command type   (0x03 effect/static, 0x04 led on-off, 0x09 kbd on-off,
                        0x80 get device info)
    [1] sub-command / page / effect id
    [2] data length (payload bytes after the 4-byte header)
    [3] reserved (0)
    [4..] payload

  Response: 64-byte input report; bytes [4..5] == 0xEC 0xAC on success.

Usage:
    python3 tools/hid_probe_linux.py info          # GET_DEVICE_INFO
    python3 tools/hid_probe_linux.py effect        # get current effect
    python3 tools/hid_probe_linux.py on            # keyboard lighting on
    python3 tools/hid_probe_linux.py usermode      # enable SW set/get
    python3 tools/hid_probe_linux.py raw <hex>     # send raw 64-byte report
    python3 tools/hid_probe_linux.py scan-cmds     # try cmd 0x00..0xFF, report ACKs
    sudo python3 tools/hid_probe_linux.py static <RRGGBB>   # full static-color
                                        # sequence via interface 2 with
                                        # desktop notifications at each step
    sudo python3 tools/hid_probe_linux.py kbam [VALUE]  # read / write the EC
                                        # keyboard-mode register (0xFE700364)
"""

from __future__ import annotations

import ctypes
import fcntl
import glob
import os
import re
import struct
import subprocess
import sys
import time

USBDEVFS_CONTROL = 0xC0185500
USBDEVFS_CLAIMINTERFACE = 0x8004550F
USBDEVFS_RELEASEINTERFACE = 0x40045510
USBDEVFS_IOCTL = 0xC0105512
USBDEVFS_DISCONNECT = 0x00005516
USBDEVFS_CONNECT = 0x00005517
USBDEVFS_BULK = 0xC0185502


def find_vendor_interface():
    """Return (hidraw_path, usbfs_path, iface_number) for the 0xFF90 interface."""
    hidraw = None
    usbfs = None
    iface = None
    for rd in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/report_descriptor")):
        try:
            with open(rd, "rb") as fh:
                if fh.read(3) != bytes([0x06, 0x90, 0xFF]):
                    continue
        except OSError:
            continue
        hidraw = "/dev/" + rd.split("/")[4]
        dev = os.path.realpath(os.path.join(os.path.dirname(rd), "..", ".."))
        bus = int(open(os.path.join(dev, "busnum")).read().strip())
        num = int(open(os.path.join(dev, "devnum")).read().strip())
        usbfs = "/dev/bus/usb/%03d/%03d" % (bus, num)
        for part in os.path.realpath(os.path.dirname(rd)).split("/"):
            m = re.search(r":(\d+)\.(\d+)", part)
            if m:
                iface = int(m.group(2))
        break
    return hidraw, usbfs, iface


def hidraw_write_read(hidraw, report: bytes, timeout=0.3):
    """Try hidraw (interrupt) write + read."""
    try:
        fd = os.open(hidraw, os.O_RDWR)
    except OSError as exc:
        return None, "open: %s" % exc
    try:
        os.write(fd, report)
        time.sleep(timeout)
        # non-blocking read
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        try:
            data = os.read(fd, 64)
            return data, None
        except BlockingIOError:
            return b"", "no input report"
        except OSError as exc:
            return b"", "read: %s" % exc
    except OSError as exc:
        return None, "write: %s" % exc
    finally:
        os.close(fd)


def ctrl(fd, req_type, request, wvalue, windex, length, data=None, timeout=2000):
    buf = ctypes.create_string_buffer(max(length, 1))
    if data is not None:
        buf.raw = bytes(data).ljust(length, b"\x00")
    pkt = bytearray(bytes([req_type, request])
                    + wvalue.to_bytes(2, "little") + windex.to_bytes(2, "little")
                    + length.to_bytes(2, "little") + timeout.to_bytes(4, "little")
                    + b"\x00" * 4 + ctypes.addressof(buf).to_bytes(8, "little"))
    try:
        n = fcntl.ioctl(fd, USBDEVFS_CONTROL, pkt, True)
        return n, buf.raw[:max(n, 0)]
    except OSError as exc:
        return None, str(exc)


def usbfs_control_transport(usbfs, iface, report: bytes):
    """SET_REPORT output over EP0; try 64B and 65B (with ID 0) variants."""
    results = []
    try:
        fd = os.open(usbfs, os.O_RDWR)
    except OSError as exc:
        return results
    try:
        for label, payload, length in (
            ("setreport64", report, len(report)),
            ("setreport65", b"\x00" + report, len(report) + 1),
        ):
            n, r = ctrl(fd, 0x21, 0x09, (2 << 8) | 0, iface, length, payload)
            results.append((label, n, r))
        # try GET_REPORT input to read response
        n, r = ctrl(fd, 0xA1, 0x01, (1 << 8) | 0, iface, 64)
        results.append(("getreport", n, r))
    finally:
        os.close(fd)
    return results


def driver_ioctl(fd, ifno, code):
    pkt = ifno.to_bytes(4, "little", signed=True) + code.to_bytes(4, "little") + (0).to_bytes(8, "little")
    fcntl.ioctl(fd, USBDEVFS_IOCTL, pkt)


def bulk_out(fd, ep, data, timeout=2000):
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    pkt = (ep.to_bytes(4, "little") + len(data).to_bytes(4, "little")
           + timeout.to_bytes(4, "little") + b"\x00" * 4
           + ctypes.addressof(buf).to_bytes(8, "little"))
    try:
        n = fcntl.ioctl(fd, USBDEVFS_BULK, pkt)
        return n, None
    except OSError as exc:
        return None, str(exc)


def bulk_in(fd, ep, length=64, timeout=3000):
    buf = ctypes.create_string_buffer(length)
    pkt = (ep.to_bytes(4, "little") + length.to_bytes(4, "little")
           + timeout.to_bytes(4, "little") + b"\x00" * 4
           + ctypes.addressof(buf).to_bytes(8, "little"))
    try:
        n = fcntl.ioctl(fd, USBDEVFS_BULK, pkt)
        return n, buf.raw[:max(n, 0)]
    except OSError as exc:
        return None, str(exc)


def usbfs_claimed_transport(usbfs, iface, report: bytes, claim: bool):
    """Disconnect usbhid, claim the interface, try control + bulk, restore."""
    out = []
    fd = os.open(usbfs, os.O_RDWR)
    try:
        if claim:
            try:
                driver_ioctl(fd, iface, USBDEVFS_DISCONNECT)
                out.append(("disconnect", "ok", None))
            except OSError as exc:
                out.append(("disconnect", "err", str(exc)))
            try:
                fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, iface.to_bytes(4, "little"))
                out.append(("claim", "ok", None))
            except OSError as exc:
                out.append(("claim", "err", str(exc)))

        for label, payload, length in (
            ("setreport64", report, 64),
            ("setreport65", b"\x00" + report, 65),
            ("setreport-feature", report, 64),
        ):
            wvalue = ((3 if label == "setreport-feature" else 2) << 8) | 0
            n, r = ctrl(fd, 0x21, 0x09, wvalue, iface, length, payload)
            out.append((label, n, r))

        n, r = ctrl(fd, 0xA1, 0x01, (1 << 8) | 0, iface, 64)
        out.append(("getreport-input", n, r))
        n, r = ctrl(fd, 0xA1, 0x01, (3 << 8) | 0, iface, 64)
        out.append(("getreport-feature", n, r))

        n, err = bulk_out(fd, 0x05, report)
        out.append(("bulk-ep05", n, err))
        n, r = ctrl(fd, 0xA1, 0x01, (1 << 8) | 0, iface, 64)
        out.append(("getreport-after-bulk", n, r))
    finally:
        if claim:
            try:
                fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, iface.to_bytes(4, "little"))
            except OSError:
                pass
            try:
                driver_ioctl(fd, iface, USBDEVFS_CONNECT)
                out.append(("reconnect", "ok", None))
            except OSError as exc:
                out.append(("reconnect", "err", str(exc)))
        os.close(fd)
    return out


def make_report(cmd: int, sub: int, length: int, payload: bytes = b"") -> bytes:
    buf = bytearray(64)
    buf[0] = cmd & 0xFF
    buf[1] = sub & 0xFF
    buf[2] = length & 0xFF
    buf[3] = 0
    buf[4:4 + len(payload)] = payload
    return bytes(buf)


def show(resp):
    if resp is None:
        print("  (write failed)")
        return
    if isinstance(resp, str):
        print("  %s" % resp)
        return
    if isinstance(resp, tuple):
        label, n, r = resp
        print("  %s: n=%r data=%s" % (label, n, r.hex() if isinstance(r, bytes) else r))
        return
    if not resp:
        print("  (no response)")
        return
    ok = len(resp) > 5 and resp[4] == 0xEC and resp[5] == 0xAC
    print("  resp: %s  %s" % (resp.hex(" "), "ACK=OK" if ok else "ACK=no"))


def notify(title, body, timeout_ms=10000):
    """Show a desktop notification as the logged-in user (we run as root)."""
    cmd = [
        "sudo", "-u", "xein", "env", "DISPLAY=:0",
        "notify-send", "-u", "critical", "-t", str(timeout_ms), title, body,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        pass


def static_sequence(usbfs, iface, rgb):
    """Send the Windows OMEN CC static-color sequence over interface 2.

    Packet format (McuKeyboardLightingSDK / DragonKBMcu):
      [cmd, index, len_lo, len_hi, payload...]
    Commands: 0x04 LED on/off + FC EA = software control,
              0x09 lighting on, 0x05/0x06/0x07 = R/G/B key pages,
              0x04 idx 1 len 18 = per-key write enable mask.
    """
    r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
    channel = {
        0x05: bytes([r]) * 144,
        0x06: bytes([g]) * 144,
        0x07: bytes([b]) * 144,
    }

    steps = []

    def add(label, cmd, index, length, payload=b""):
        steps.append((label, make_report(cmd, index, length, payload)))

    add("1. 启用软件控制", 0x04, 0x00, 0x02, b"\xFC\xEA")
    add("2. 开灯", 0x09, 0x00, 0x01, b"\xFF")
    add("3. 键位可写关闭", 0x04, 0x01, 0x12, b"\x00" * 18)
    for cmd in (0x05, 0x06, 0x07):
        data = channel[cmd]
        add("R页0" if cmd == 0x05 else "G页0" if cmd == 0x06 else "B页0",
            cmd, 0x00, 0x3C, data[0:60])
        add("R页1" if cmd == 0x05 else "G页1" if cmd == 0x06 else "B页1",
            cmd, 0x01, 0x3C, data[60:120])
        add("R页2" if cmd == 0x05 else "G页2" if cmd == 0x06 else "B页2",
            cmd, 0x02, 0x18, data[120:144])
    add("4. 键位可写开启", 0x04, 0x01, 0x12, b"\xFF" * 18)

    fd = os.open(usbfs, os.O_RDWR)
    try:
        try:
            driver_ioctl(fd, iface, USBDEVFS_DISCONNECT)
        except OSError:
            pass
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, iface.to_bytes(4, "little"))
        print("已独占接口 %d，开始发送 %d 条命令…" % (iface, len(steps)))
        notify("OMEN RGB 测试开始",
               "马上发送完整静态色序列，请盯住键盘，颜色应该变 #%s" % rgb)
        time.sleep(2)
        for label, report in steps:
            n, r = ctrl(fd, 0x21, 0x09, (2 << 8) | 0, iface, 64, report)
            ok = "OK" if n is not None and n >= 0 else "ERR(%s)" % r
            print("  [%s] %s" % (label, ok), flush=True)
            time.sleep(0.15)
        time.sleep(1)
        notify("序列发送完毕", "键盘应该已经变成 #%s。变了吗？" % rgb)
    finally:
        try:
            fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, iface.to_bytes(4, "little"))
        except OSError:
            pass
        time.sleep(0.3)
        try:
            driver_ioctl(fd, iface, USBDEVFS_CONNECT)
        except OSError:
            pass
        os.close(fd)
        subprocess.run(
            ["bash", "-c", 'echo -n "5-1.3:1.%d" > /sys/bus/usb/drivers/usbhid/bind' % iface],
            capture_output=True, timeout=5)


def monitor_interface(usbfs, iface, ep, duration=90):
    """Claim an interface and print every interrupt IN report received.

    While this runs, press the lighting shortcut (Fn+Space) a few times;
    the keyboard's mode-change report will be captured here.
    """
    fd = os.open(usbfs, os.O_RDWR)
    try:
        try:
            driver_ioctl(fd, iface, USBDEVFS_DISCONNECT)
        except OSError:
            pass
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, iface.to_bytes(4, "little"))
        print("监听接口 %d EP%02X %d 秒…请现在按几次 Fn+Space" % (iface, ep, duration), flush=True)
        notify("OMEN RGB 抓包", "现在开始监听键盘报告，请连按 5 次 Fn+Space（灯光键）", 12000)
        deadline = time.time() + duration
        while time.time() < deadline:
            n, data = bulk_in(fd, ep, 64, 3000)
            if n and n > 0:
                print("[%s] EP%02X %dB: %s" % (
                    time.strftime("%H:%M:%S"), ep, n,
                    data.hex(" ")), flush=True)
            elif isinstance(data, str) and "timeout" not in data:
                print("[%s] EP%02X read: %s" % (time.strftime("%H:%M:%S"), ep, data), flush=True)
    finally:
        try:
            fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, iface.to_bytes(4, "little"))
        except OSError:
            pass
        time.sleep(0.3)
        try:
            driver_ioctl(fd, iface, USBDEVFS_CONNECT)
        except OSError:
            pass
        os.close(fd)
        subprocess.run(
            ["bash", "-c", 'echo -n "5-1.3:1.%d" > /sys/bus/usb/drivers/usbhid/bind' % iface],
            capture_output=True, timeout=5)
        print("监听结束", flush=True)


def main() -> int:
    hidraw, usbfs, iface = find_vendor_interface()
    print("hidraw=%s usbfs=%s iface=%s" % (hidraw, usbfs, iface))
    if not hidraw:
        print("找不到 0xFF90 接口")
        return 1

    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"

    if cmd == "info":
        report = make_report(0x80, 0x01, 0)
    elif cmd == "effect":
        report = make_report(0x80, 0x01, 0)  # same GET header per SDK
    elif cmd == "on":
        report = make_report(0x09, 0x00, 0x01, b"\xFF")
    elif cmd == "off":
        report = make_report(0x03, 0x01, 0x16, b"\x00" * 22)
    elif cmd == "usermode":
        report = make_report(0x04, 0x00, 0x02, b"\xFC\xEA")
    elif cmd == "raw":
        report = bytes.fromhex(sys.argv[2])
        report = report.ljust(64, b"\x00")[:64]
    elif cmd == "scan-cmds":
        for c in range(0x00, 0x40):
            rep = make_report(c, 0x00, 0)
            data, err = hidraw_write_read(hidraw, rep)
            if data and len(data) > 5 and data[4] == 0xEC:
                print("cmd 0x%02X -> ACK %s" % (c, data.hex(" ")))
        return 0
    elif cmd == "claim":
        report = make_report(0x80, 0x01, 0)
    elif cmd == "static":
        rgb = (sys.argv[2] if len(sys.argv) > 2 else "00FF00").upper()
        if not re.fullmatch(r"[0-9A-F]{6}", rgb):
            print("颜色必须是 6 位十六进制 RRGGBB")
            return 2
        if not usbfs:
            print("找不到 USB 设备路径")
            return 1
        static_sequence(usbfs, 2, rgb)
        return 0
    elif cmd == "monitor":
        iface = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        ep = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x82
        duration = int(sys.argv[4]) if len(sys.argv) > 4 else 90
        if not usbfs:
            print("找不到 USB 设备路径")
            return 1
        monitor_interface(usbfs, iface, ep, duration)
        return 0
    elif cmd == "kbam":
        offset = 0x364
        base = 0xFE700000
        if len(sys.argv) > 2:
            value = int(sys.argv[2], 0)
            with open("/dev/mem", "r+b") as fh:
                fh.seek(base + offset)
                fh.write(bytes([value & 0xFF]))
        with open("/dev/mem", "rb") as fh:
            fh.seek(base + offset)
            val = fh.read(1)[0]
        print("KBAM = %d (0x%02X)" % (val, val))
        return 0
    else:
        print(__doc__)
        return 2

    print("report: %s" % report.hex(" "))

    print("[hidraw]")
    data, err = hidraw_write_read(hidraw, report)
    show(data if data is not None else err)

    if usbfs and iface is not None:
        print("[usbfs]")
        if cmd == "claim":
            for label, n, r in usbfs_claimed_transport(usbfs, iface, report, claim=True):
                if isinstance(r, bytes):
                    print("  %s: n=%r data=%s" % (label, n, r.hex(" ")))
                else:
                    print("  %s: n=%r %s" % (label, n, r if r else ""))
            return 0
        for label, n, r in usbfs_control_transport(usbfs, iface, report):
            print("  %s: n=%r data=%s" % (label, n, r.hex() if isinstance(r, bytes) else r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
