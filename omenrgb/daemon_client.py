#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""omenrgbd 的客户端：普通用户通过 Unix socket 读写键盘灯效。

DaemonBackend 实现了与 WmiAcpiBackend 相同的接口，detect_backend()
会优先使用它——守护进程运行后，CLI/GUI 无需任何提权即可工作。
"""

from __future__ import annotations

import json
import os
import socket

from omenrgb.core import OmenError, validate_rgb


DEFAULT_SOCK_PATH = "/run/omenrgb/control.sock"


class DaemonError(OmenError):
    pass


class DaemonClient:
    def __init__(self, path=DEFAULT_SOCK_PATH):
        self.path = path

    def _call(self, cmd, *args, timeout=15):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(self.path)
        except OSError as exc:
            raise DaemonError(
                "无法连接 omenrgb 守护进程: %s" % exc,
                hint="请先安装并启动服务：sudo ./install-systemd-service.sh",
            )
        try:
            req = json.dumps({"cmd": cmd, "args": list(args)}, ensure_ascii=False)
            sock.sendall((req + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
            resp = json.loads(buf.decode("utf-8", "replace").strip())
        except (OSError, ValueError) as exc:
            raise DaemonError("与守护进程通信失败: %s" % exc)
        finally:
            try:
                sock.close()
            except OSError:
                pass
        if not resp.get("ok"):
            raise DaemonError(resp.get("error", "未知错误"), hint=resp.get("hint"))
        return resp.get("data")

    def ping(self, timeout=2):
        try:
            return self._call("ping", timeout=timeout) == {"pong": True}
        except DaemonError:
            return False


class DaemonBackend:
    """Backend that talks to the root omenrgbd service over a unix socket."""

    backend_name = "omenrgb-daemon"

    def __init__(self, elevate=False, path=DEFAULT_SOCK_PATH):
        self.elevate = elevate
        self._client = DaemonClient(path)

    @classmethod
    def driver_present(cls, path=DEFAULT_SOCK_PATH):
        try:
            return DaemonClient(path).ping()
        except Exception:  # noqa: BLE001
            return False

    # ---------------------------------------------------------- hardware
    def get_state(self):
        return self._client._call("status")

    def set_zone(self, index, rgb, elevate=None):
        rgb = validate_rgb(rgb)
        if not 0 <= index < 4:
            raise OmenError("区域索引必须是 0-3")
        self._client._call("set_zone", str(index), rgb)

    def set_all(self, rgb, elevate=None):
        self._client._call("set_all", validate_rgb(rgb))

    def set_brightness(self, level, elevate=None):
        self._client._call("brightness", str(int(level)))

    def set_animation(self, mode, colors=None, brightness=None):
        self._client._call("animate", str(mode).strip().lower())

    def read_kbam(self):
        data = self._client._call("kbam")
        return data["kbam"]

    def kbam_label(self, value=None):
        data = self._client._call("kbam")
        return data["label"]

    # ---- not supported over the daemon (kept for interface compatibility)
    def get_zone(self, index):
        return self.get_state()["zones"][index]

    def get_all(self):
        zones = self.get_state()["zones"]
        return zones[0] if len(set(zones)) == 1 else ",".join(zones)

    def get_brightness(self):
        return self.get_state()["brightness"]

    def get_mode(self):
        return self.get_state()["mode"]

    def get_speed(self):
        return 1

    def get_gradient(self):
        return ""

    def set_mode(self, mode, elevate=None):
        mode = str(mode).strip().lower()
        if mode == "static":
            return
        self.set_animation(mode)

    def set_speed(self, speed, elevate=None):
        raise OmenError("守护进程后端不支持动画速度")

    def set_gradient(self, config, elevate=None):
        raise OmenError("守护进程后端不支持渐变动画")

    def apply_state(self, state, elevate=None):
        zones = state.get("zones")
        if zones and len(zones) == 4:
            base = validate_rgb(zones[0])
            self.set_all(base)
            for i, c in enumerate(zones[1:], start=1):
                cc = validate_rgb(c)
                if cc != base:
                    self.set_zone(i, cc)
        b = state.get("brightness")
        if b is not None:
            self.set_brightness(b)
        mode = state.get("mode")
        if mode and mode != "static":
            self.set_animation(mode)
