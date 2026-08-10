#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""omenrgbd — OMEN RGB 键盘灯效守护进程（以 root 运行）。

通过 Unix socket 向普通用户提供键盘灯效读写接口，避免每次操作都要
提权。由 install-systemd-service.sh 安装为 systemd 服务后自启动。

协议：换行分隔的 JSON。请求 {"cmd": "...", "args": [...]}，
响应 {"ok": true, "data": ...} 或 {"ok": false, "error": "..."}。

命令：
  ping                      -> {"pong": true}
  status                    -> 同 WmiAcpiBackend.get_state()
  set_all <RRGGBB>          -> 全部分区
  set_zone <0-3> <RRGGBB>   -> 单个分区
  brightness <0-100>
  animate <name>            -> Dojo 动画
  kbam                      -> 读模式寄存器
"""

from __future__ import annotations

import json
import os
import pwd
import grp
import signal
import socket
import sys
import threading

import os
import sys

# 作为脚本直接运行时，把仓库根目录加进导入路径（systemd ExecStart 直接跑本文件）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from omenrgb.core import OmenError, validate_rgb
from omenrgb.wmi_backend import WmiAcpiBackend, ANIMATION_MODES


SOCK_DIR = os.environ.get("OMENRGB_SOCK_DIR", "/run/omenrgb")
SOCK_PATH = os.environ.get("OMENRGB_SOCK_PATH", os.path.join(SOCK_DIR, "control.sock"))
SOCK_USER = os.environ.get("OMENRGB_SOCK_USER", "")
SOCK_GROUP = os.environ.get("OMENRGB_SOCK_GROUP", "")

_backend = None
_stop = threading.Event()


def backend():
    global _backend
    if _backend is None:
        _backend = WmiAcpiBackend(elevate=False)
    return _backend


def dispatch(cmd, args):
    b = backend()
    if cmd == "ping":
        return {"pong": True}
    if cmd == "status":
        return b.get_state()
    if cmd == "set_all":
        if not args:
            raise OmenError("缺少颜色参数")
        rgb = validate_rgb(args[0])
        b.set_all(rgb)
        return {"applied": rgb}
    if cmd == "set_zone":
        if len(args) < 2:
            raise OmenError("缺少分区/颜色参数")
        zone = int(args[0])
        rgb = validate_rgb(args[1])
        b.set_zone(zone, rgb)
        return {"applied": rgb}
    if cmd == "brightness":
        if not args:
            raise OmenError("缺少亮度参数")
        level = int(args[0])
        if not 0 <= level <= 100:
            raise OmenError("亮度必须是 0-100")
        b.set_brightness(level)
        return {"brightness": level}
    if cmd == "animate":
        if not args:
            raise OmenError("缺少动画名")
        name = args[0]
        if name not in ANIMATION_MODES:
            raise OmenError("未知动画: %s" % name)
        b.set_animation(name)
        return {"animation": name}
    if cmd == "kbam":
        value = b.read_kbam()
        return {"kbam": value, "label": b.kbam_label(value)}
    raise OmenError("未知命令: %s" % cmd)


def handle(conn):
    try:
        conn.settimeout(10)
        data = conn.recv(65536)
        if not data:
            return
        text = data.decode("utf-8", "replace").strip()
        try:
            req = json.loads(text)
            cmd = req.get("cmd", "")
            args = req.get("args") or []
        except (ValueError, AttributeError):
            raise OmenError("请求不是合法 JSON")
        try:
            result = dispatch(cmd, args)
            payload = (json.dumps({"ok": True, "data": result},
                                  ensure_ascii=False) + "\n").encode("utf-8")
            conn.sendall(payload)
        except OmenError as exc:
            payload = (json.dumps({"ok": False, "error": exc.message,
                                   "hint": exc.hint}, ensure_ascii=False) + "\n").encode("utf-8")
            conn.sendall(payload)
        except Exception as exc:  # noqa: BLE001
            payload = (json.dumps({"ok": False, "error": str(exc)},
                                  ensure_ascii=False) + "\n").encode("utf-8")
            conn.sendall(payload)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main() -> int:
    os.makedirs(SOCK_DIR, exist_ok=True)
    try:
        os.unlink(SOCK_PATH)
    except FileNotFoundError:
        pass

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o660)
    if SOCK_USER:
        try:
            uid = pwd.getpwnam(SOCK_USER).pw_uid
            gid = grp.getgrnam(SOCK_GROUP).gr_gid if SOCK_GROUP else pwd.getpwnam(SOCK_USER).pw_gid
            os.chown(SOCK_PATH, uid, gid)
        except KeyError as exc:
            print("警告: 无法解析用户/组 %s: %s" % (SOCK_USER, exc), file=sys.stderr)
    sock.listen(16)
    print("omenrgbd 监听 %s" % SOCK_PATH, flush=True)

    def _shutdown(_sig, _frm):
        _stop.set()
        try:
            sock.close()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while not _stop.is_set():
        try:
            conn, _ = sock.accept()
        except OSError:
            if _stop.is_set():
                break
            continue
        threading.Thread(target=handle, args=(conn,), daemon=True).start()

    try:
        os.unlink(SOCK_PATH)
    except FileNotFoundError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
