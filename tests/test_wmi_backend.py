#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the acpi_call WMI backend (runs on any OS)."""

from __future__ import annotations

import builtins
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omenrgb import wmi_backend as wb
from omenrgb.core import OmenError


# ------------------------------------------------------------ fake firmware
def _handler(cmdtype, command, payload, mid):
    """Miniature DSDT simulator for the queries this backend uses."""
    local0 = {1: 0, 2: 4, 3: 0x80, 4: 0x400}.get(mid, 0)
    if not hasattr(wb, "_fake_color_table"):
        table = bytearray(0x80)
        # zone0 red, zone1 green, zone2 blue, zone3 white
        table[0x19:0x25] = bytes.fromhex("FF000000FF000000FFFFFFFFFF")
        wb._fake_color_table = bytes(table)
    if command == wb.CMD_GAMING and cmdtype == wb.CMDT_GET_KEYBOARD_TYPE:
        data = bytes([1, 0, 0, 0])  # 4-zone with numpad
    elif command == wb.CMD_BACKLIGHT and cmdtype == wb.CMDT_GET_CAPS:
        data = bytes([7, 0, 0, 0])
    elif command == wb.CMD_BACKLIGHT and cmdtype == wb.CMDT_GET_COLOR:
        data = bytearray(wb._fake_color_table)
        data[0] = 0x03
        data = bytes(data)
    elif command == wb.CMD_BACKLIGHT and cmdtype == wb.CMDT_SET_COLOR:
        wb._fake_color_table = payload
        data = b""
    elif command == wb.CMD_BACKLIGHT and cmdtype == wb.CMDT_GET_BRIGHTNESS:
        data = bytes([0xE4, 0, 0, 0])
    elif command == wb.CMD_BACKLIGHT and cmdtype == wb.CMDT_SET_BRIGHTNESS:
        wb._fake_stored_brightness = payload
        data = b""
    else:
        raise AssertionError("unexpected query: cmd=%X type=%X" % (command, cmdtype))

    resp = bytearray(8 + local0)
    resp[0:4] = wb.PASS_SIG.to_bytes(4, "little")
    resp[4:8] = (0).to_bytes(4, "little")
    resp[8:8 + len(data)] = data
    return bytes(resp)


def _acpi_text(response, limit):
    """Format a response the way the acpi_call module does (256-byte cap)."""
    out = ["{"]
    used = 1
    truncated = False
    for i, b in enumerate(response):
        piece = ("0x%02x" % b) if i == 0 else (", 0x%02x" % b)
        if used + len(piece) > limit:
            truncated = True
            break
        out.append(piece)
        used += len(piece)
    if truncated:
        out.append(",")
    else:
        out.append("}")
    return "".join(out)


class FakeAcpiCall:
    """Deterministic /proc/acpi/call stand-in via a patched builtins.open."""

    def __init__(self, limit=256):
        self.path = "/proc/acpi/call"
        self.result = "not called"
        self.calls = []
        self.limit = limit

    def install(self):
        self._orig_open = builtins.open
        self._orig_geteuid = getattr(os, "geteuid", None)
        self._orig_find_call_path = wb.find_call_path
        os.geteuid = lambda: 0
        builtins.open = self._fake_open
        wb.find_call_path = lambda: self.path

    def uninstall(self):
        builtins.open = self._orig_open
        wb.find_call_path = self._orig_find_call_path
        if self._orig_geteuid is None:
            del os.geteuid
        else:
            os.geteuid = self._orig_geteuid

    def _fake_open(self, file, mode="r", *args, **kwargs):
        if isinstance(file, str) and file == self.path:
            if "w" in mode or "+" in mode:
                return _FakeWriter(self)
            return io.StringIO(self.result)
        return self._orig_open(file, mode, *args, **kwargs)


class _FakeWriter:
    def __init__(self, fake):
        self.fake = fake

    def write(self, line):
        line = line.strip()
        self.fake.calls.append(line)
        parts = line.split()
        method = parts[0]
        assert method == r"\_SB.WMID.WMAA", method
        instance, mid = int(parts[1]), int(parts[2])
        assert instance == 0
        hexbuf = parts[3][1:]  # strip 'b'
        buf = bytes.fromhex(hexbuf)
        sig = int.from_bytes(buf[0:4], "little")
        command = int.from_bytes(buf[4:8], "little")
        cmdtype = int.from_bytes(buf[8:12], "little")
        payload = buf[16:16 + int.from_bytes(buf[12:16], "little")]
        response = _handler(cmdtype, command, payload, mid)
        self.fake.result = _acpi_text(response, self.fake.limit)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_build_wmaa_line():
    line = wb.build_wmaa_line(wb.CMDT_GET_COLOR, outsize=128)
    buf = bytes.fromhex(line.split()[3][1:])
    assert buf[0:4] == wb.SIGNATURE.to_bytes(4, "little")
    assert buf[4:8] == wb.CMD_BACKLIGHT.to_bytes(4, "little")
    assert buf[8:12] == wb.CMDT_GET_COLOR.to_bytes(4, "little")
    assert buf[12:16] == (0).to_bytes(4, "little")
    assert line.split()[2] == "3"  # mid for outsize=128
    assert wb.build_wmaa_line(wb.CMDT_GET_BRIGHTNESS, outsize=4).split()[2] == "2"
    assert wb.build_wmaa_line(wb.CMDT_SET_BRIGHTNESS, bytes([0xE4]), outsize=1).split()[2] == "2"


def test_parse_acpi_result_truncated():
    raw, truncated = wb.parse_acpi_result(
        "{0x50, 0x41, 0x53, 0x53, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00,"
    )
    assert truncated
    assert raw[0:4] == b"PASS"


def test_parse_acpi_result_error():
    try:
        wb.parse_acpi_result("Error: AE_NOT_FOUND")
        assert False, "should raise"
    except OmenError:
        pass


def test_full_backend_flow():
    fake = FakeAcpiCall(limit=2048)  # patched acpi_call (BUFFER_SIZE >= 2048)
    fake.install()
    try:
        backend = wb.WmiAcpiBackend()
        assert backend.keyboard_type() == 1
        assert backend.capabilities() == bytes([7, 0, 0, 0])
        assert backend.get_brightness() == 100  # 0xE4 -> 100
        colors = backend.get_all()
        assert colors == "FF0000,00FF00,0000FF,FFFFFF"
        zones = backend.read_color_table()
        assert zones == ["FF0000", "00FF00", "0000FF", "FFFFFF"]

        backend.set_zone(2, "123456")
        assert wb._fake_color_table[0x19:0x25] == bytes.fromhex("FF000000FF00123456FFFFFF")
        assert backend.get_state()["zones"] == ["FF0000", "00FF00", "123456", "FFFFFF"]

        backend.set_brightness(0)
        assert wb._fake_stored_brightness == bytes([0x64])
        backend.set_brightness(50)
        assert wb._fake_stored_brightness == bytes([0xE4])
    finally:
        fake.uninstall()


def test_acpi_truncation_warning_on_color_read():
    """Simulate the stock 256-byte acpi_call limit and check the backend
    raises a clear error for zone 3 instead of returning garbage."""
    fake = FakeAcpiCall()
    fake.install()
    try:
        backend = wb.WmiAcpiBackend()
        # The fake's text output for the 0x88-byte response truncates at 42
        # bytes; zone 3 needs byte 44, so the backend must complain.
        try:
            backend.read_color_table()
            assert False, "should raise on truncated color table"
        except OmenError as exc:
            assert "截断" in exc.message or "BUFFER_SIZE" in (exc.hint or "")
    finally:
        fake.uninstall()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok - %s" % name)
    print("all tests passed")
