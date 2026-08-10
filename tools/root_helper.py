#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured root helper: one sudoers entry for all privileged ops we need.

Run via:  sudo -n python3 /Code/Misc/Omen-RGB/tools/root_helper.py <cmd> [args]

Subcommands:
  read <path> [--hex]          print a file (--hex for binary)
  list <dir>                   list directory
  write <path> <base64>        atomically write a file (root)
  dmesg [--tail N]             kernel ring buffer
  journalctl [--since ...]     system journal
  lsblk                        block devices / partitions
  mount_ro <dev> <dir>         read-only mount (ntfs/ext4 autodetect)
  umount <dir>                 unmount
  modprobe <mod> | rmmod <mod> kernel module ops
  lsusb                        usb topology
  strings <path>               printable strings of a file
  sh <args...>                 run arbitrary command as root (escape hatch)
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys


def out(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def cmd_read(args: list[str]) -> int:
    if not args:
        out("usage: read <path> [--hex]")
        return 2
    path = args[0]
    hexmode = "--hex" in args[1:]
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        out("ERROR: %s" % exc)
        return 1
    if hexmode:
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            out("%08x: %s" % (i, " ".join("%02X" % b for b in chunk)))
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    return 0


def cmd_list(args: list[str]) -> int:
    path = args[0] if args else "."
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            try:
                st = os.lstat(full)
                out("%s\t%d\t%s" % ("d" if os.path.isdir(full) else "-", st.st_size, name))
            except OSError:
                out("-\t-\t%s" % name)
        return 0
    except OSError as exc:
        out("ERROR: %s" % exc)
        return 1


def cmd_write(args: list[str]) -> int:
    if len(args) != 2:
        out("usage: write <path> <base64>")
        return 2
    path, b64 = args
    try:
        data = base64.b64decode(b64)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        out("OK: wrote %d bytes to %s" % (len(data), path))
        return 0
    except (OSError, ValueError) as exc:
        out("ERROR: %s" % exc)
        return 1


def run(argv: list[str]) -> int:
    try:
        proc = subprocess.run(argv, capture_output=True)
    except OSError as exc:
        out("ERROR: %s" % exc)
        return 1
    sys.stdout.buffer.write(proc.stdout)
    sys.stderr.buffer.write(proc.stderr)
    sys.stdout.buffer.flush()
    return proc.returncode


def main() -> int:
    if len(sys.argv) < 2:
        out(__doc__)
        return 2
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "read":
        return cmd_read(args)
    if cmd == "list":
        return cmd_list(args)
    if cmd == "write":
        return cmd_write(args)
    if cmd == "dmesg":
        tail = None
        if args and args[0].startswith("--tail="):
            tail = int(args.pop(0).split("=", 1)[1])
        argv = ["dmesg", "-T"]
        if tail:
            argv += ["|", "tail", "-n", str(tail)]
        if tail:
            proc = subprocess.run(["dmesg", "-T"], capture_output=True)
            lines = proc.stdout.decode("utf-8", "replace").splitlines()
            sys.stdout.write("\n".join(lines[-tail:]) + "\n")
            return proc.returncode
        return run(argv)
    if cmd == "journalctl":
        return run(["journalctl"] + args)
    if cmd == "lsblk":
        return run(["lsblk", "-o", "NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS,MODEL"])
    if cmd == "mount_ro":
        if len(args) != 2:
            out("usage: mount_ro <dev> <dir>")
            return 2
        dev, mnt = args
        os.makedirs(mnt, exist_ok=True)
        return run(["mount", "-o", "ro", dev, mnt])
    if cmd == "umount":
        return run(["umount"] + args)
    if cmd == "modprobe":
        return run(["modprobe"] + args)
    if cmd == "rmmod":
        return run(["rmmod"] + args)
    if cmd == "lsusb":
        return run(["lsusb", "-t"])
    if cmd == "strings":
        if not args:
            out("usage: strings <path>")
            return 2
        return run(["strings", "-a", args[0]])
    if cmd == "sh":
        return run(args)
    out("unknown subcommand: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
