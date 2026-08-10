#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generic WMAA caller for HP OMEN WMI experiments (root only).

Usage:
    sudo python3 tools/wmi_call.py COMD CMDT [HEXPAYLOAD] [OUTSIZE]

Examples:
    sudo python3 tools/wmi_call.py 20008 10            # GM10: OMCC=1
    sudo python3 tools/wmi_call.py 20009 02            # read color table
    sudo python3 tools/wmi_call.py 20009 03 <128B hex> # write color table

Prints the raw response bytes as hex lines.
"""

from __future__ import annotations

import re
import sys

CALL_PATH = "/proc/acpi/call"
WMAA = r"\_SB.WMID.WMAA"


def mid_for_outsize(outsize: int) -> int:
    if outsize > 128:
        return 4
    if outsize > 4:
        return 3
    if outsize > 0:
        return 2
    return 1


def call_wmaa(command: int, cmdtype: int, payload: bytes, outsize: int) -> str:
    buf = bytearray(16 + len(payload))
    buf[0:4] = (0x55434553).to_bytes(4, "little")
    buf[4:8] = command.to_bytes(4, "little")
    buf[8:12] = cmdtype.to_bytes(4, "little")
    buf[12:16] = len(payload).to_bytes(4, "little")
    buf[16:] = payload
    line = "%s 0 %d b%s" % (WMAA, mid_for_outsize(outsize), buf.hex())
    with open(CALL_PATH, "w", encoding="ascii") as fh:
        fh.write(line + "\n")
    with open(CALL_PATH, "r", encoding="ascii", errors="replace") as fh:
        return fh.read().strip()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    command = int(sys.argv[1], 16)
    cmdtype = int(sys.argv[2], 16)
    payload = bytes.fromhex(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else b""
    outsize = int(sys.argv[4], 16) if len(sys.argv) > 4 else (128 if payload else 4)
    result = call_wmaa(command, cmdtype, payload, outsize)
    tokens = re.findall(r"0x([0-9A-Fa-f]{2})", result)
    raw = bytes(int(t, 16) for t in tokens)
    print("RAW: %s" % result)
    print("LEN: %d" % len(raw))
    for i in range(0, len(raw), 16):
        print("%04X: %s" % (i, " ".join("%02X" % b for b in raw[i:i + 16])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
