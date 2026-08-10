# SPDX-License-Identifier: GPL-3.0-or-later
"""Backend for controlling HP OMEN 4-zone RGB keyboards on Linux.

Primary backend: the out-of-tree "omen-rgb-keyboard" DKMS driver.
  sysfs root: /sys/devices/platform/omen-rgb-keyboard/rgb_zones/
  Attributes: zone00..zone03, all, brightness, animation_mode,
              animation_speed, gradient_config, mute_led, mute_state

Fallback backend: mainline hp-wmi multicolor LED class devices
  (static colors only, no animations).
  LEDs: /sys/class/leds/hp::kbd_zoned_backlight-{right,center,left,wasd}
        or /sys/class/leds/hp::kbd_backlight (single zone)

The sysfs base path can be overridden with the environment variable
OMENRGB_SYSFS_BASE (used for testing).
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys


SYSFS_BASE = os.environ.get(
    "OMENRGB_SYSFS_BASE",
    "/sys/devices/platform/omen-rgb-keyboard/rgb_zones",
)

DRIVER_NAME = "omen_rgb_keyboard"
WMI_BIOS_GUID = "5FB7F034-2C63-45E9-BE91-3D44E2C707E4"
WMI_EVENT_GUID = "95F24279-4D7B-4334-9387-ACCDC67EF61C"

ZONE_ATTRS = ["zone00", "zone01", "zone02", "zone03"]

# (internal name, display name in Chinese)
ANIMATION_MODES = [
    ("static", "静态 (纯色)"),
    ("breathing", "呼吸"),
    ("rainbow", "彩虹"),
    ("wave", "波浪"),
    ("pulse", "脉冲"),
    ("chase", "追逐"),
    ("sparkle", "闪烁星光"),
    ("candle", "烛光"),
    ("aurora", "极光"),
    ("disco", "迪斯科"),
    ("gradient", "渐变"),
]
ANIMATION_NAMES = {name for name, _ in ANIMATION_MODES}
ANIMATION_LABELS = dict(ANIMATION_MODES)

MAINLINE_LED_GLOBS = (
    "/sys/class/leds/hp::kbd_zoned_backlight-*",
    "/sys/class/leds/hp::kbd_zoned_backlight-?",
    "/sys/class/leds/hp::kbd_backlight",
)


class OmenError(Exception):
    """Raised when a hardware/back-end operation fails."""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.message = message
        self.hint = hint


def _is_linux():
    # Explicit OMENRGB_SYSFS_BASE override also enables testing on non-Linux
    # hosts (e.g. running the CLI against a fake sysfs tree).
    if os.environ.get("OMENRGB_SYSFS_BASE"):
        return True
    return sys.platform.startswith("linux")


def validate_rgb(value):
    """Return a normalized uppercase RRGGBB hex string or raise OmenError."""
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("#"):
            value = value[1:]
        if len(value) != 6:
            raise OmenError("颜色格式必须是 6 位十六进制 (RRGGBB)，例如 FF0000")
        try:
            int(value, 16)
        except ValueError:
            raise OmenError("颜色不是合法的十六进制值: %s" % value)
        return value.upper()
    raise OmenError("颜色值必须是字符串，例如 'FF0000'")


class OmenRGB:
    """Control the omen-rgb-keyboard driver through sysfs."""

    def __init__(self, elevate=False):
        self.elevate = elevate
        self.sysfs_base = SYSFS_BASE

    # ------------------------------------------------------------- presence
    @classmethod
    def driver_present(cls):
        if not _is_linux():
            return False
        return os.path.isdir(SYSFS_BASE)

    def _path(self, attr):
        return os.path.join(self.sysfs_base, attr)

    # ------------------------------------------------------------ low level
    def _read(self, attr):
        path = self._path(attr)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read().strip()
        except FileNotFoundError:
            raise OmenError(
                "sysfs 属性不存在: %s" % path,
                hint="驱动可能未正确加载，请运行 'omenrgb diagnose' 查看原因。",
            )
        except PermissionError:
            raise OmenError(
                "没有权限读取 %s" % path,
                hint="请运行 'sudo udevadm trigger' 或安装 udev 规则后重新登录。",
            )
        except OSError as exc:
            raise OmenError("读取 %s 失败: %s" % (path, exc))

    def _write(self, attr, value, elevate=None):
        path = self._path(attr)
        value = str(value)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(value)
            return
        except PermissionError:
            pass
        except FileNotFoundError:
            raise OmenError(
                "sysfs 属性不存在: %s" % path,
                hint="驱动可能未正确加载，请运行 'omenrgb diagnose' 查看原因。",
            )
        except OSError as exc:
            raise OmenError("写入 %s 失败: %s" % (path, exc))

        # Writing directly failed (permissions). Try an elevated helper when
        # allowed: pkexec for graphical auth, then sudo -n (non-interactive).
        if elevate is None:
            elevate = self.elevate
        if not elevate:
            raise OmenError(
                "没有权限写入 %s (需要 root 或 input 组成员)" % path,
                hint="a) 安装 udev 规则并加入 input 组后重新登录；"
                     "b) 或让本工具通过 pkexec 提权（安装 polkit）。",
            )
        self._elevated_write(path, value)

    @staticmethod
    def _elevated_write(path, value):
        shell = (
            "printf '%s' \"$1\" > \"$2\"",
            "omenrgb-helper",  # $0 for sh -c
            value,
            path,
        )
        attempts = []
        if shutil.which("pkexec"):
            attempts.append(["pkexec", "sh", "-c"] + list(shell))
        if shutil.which("sudo"):
            attempts.append(["sudo", "-n", "sh", "-c"] + list(shell))
        if not attempts:
            raise OmenError(
                "需要 root 权限但找不到 pkexec/sudo",
                hint="安装 polkit (pkexec) 或在终端中使用 sudo 运行本工具。",
            )
        last_error = None
        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode == 0:
                    return
                last_error = proc.stderr.strip() or "exit=%d" % proc.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
        raise OmenError("提权写入失败: %s" % last_error)

    # ------------------------------------------------------------ zone get
    def get_zone(self, index):
        if not 0 <= index < 4:
            raise OmenError("区域索引必须是 0-3")
        return self._read(ZONE_ATTRS[index]).lstrip("#").upper()

    def get_all(self):
        return self._read("all").lstrip("#").upper()

    def get_brightness(self):
        try:
            return int(self._read("brightness"))
        except ValueError:
            raise OmenError("无法解析亮度值")

    def get_mode(self):
        return self._read("animation_mode")

    def get_speed(self):
        try:
            return int(self._read("animation_speed"))
        except ValueError:
            raise OmenError("无法解析动画速度")

    def get_gradient(self):
        return self._read("gradient_config")

    # ------------------------------------------------------------ zone set
    def set_zone(self, index, rgb, elevate=None):
        if not 0 <= index < 4:
            raise OmenError("区域索引必须是 0-3")
        rgb = validate_rgb(rgb)
        self._write(ZONE_ATTRS[index], rgb, elevate=elevate)

    def set_all(self, rgb, elevate=None):
        rgb = validate_rgb(rgb)
        self._write("all", rgb, elevate=elevate)

    def set_brightness(self, level, elevate=None):
        try:
            level = int(level)
        except (TypeError, ValueError):
            raise OmenError("亮度必须是 0-100 的整数")
        if not 0 <= level <= 100:
            raise OmenError("亮度必须是 0-100 的整数")
        self._write("brightness", level, elevate=elevate)

    def set_mode(self, mode, elevate=None):
        mode = str(mode).strip().lower()
        if mode not in ANIMATION_NAMES:
            raise OmenError(
                "未知动画模式: %s (可选: %s)"
                % (mode, ", ".join(sorted(ANIMATION_NAMES)))
            )
        self._write("animation_mode", mode, elevate=elevate)

    def set_speed(self, speed, elevate=None):
        try:
            speed = int(speed)
        except (TypeError, ValueError):
            raise OmenError("速度必须是 1-10 的整数")
        if not 1 <= speed <= 10:
            raise OmenError("速度必须是 1-10 的整数")
        self._write("animation_speed", speed, elevate=elevate)

    def set_gradient(self, config, elevate=None):
        config = str(config).strip()
        if not config:
            raise OmenError("渐变配置不能为空")
        # Basic validation: "zone[,zone]:COLOR[,COLOR][;...]"
        for group in config.split(";"):
            if ":" not in group:
                raise OmenError("渐变格式错误: %r (应为 区域:颜色,颜色)" % group)
            zones_str, colors_str = group.split(":", 1)
            for z in zones_str.split(","):
                if z.strip() not in ("0", "1", "2", "3"):
                    raise OmenError("渐变区域只能是 0-3: %r" % z)
            for color in colors_str.split(","):
                validate_rgb(color)
        self._write("gradient_config", config, elevate=elevate)

    # ------------------------------------------------------------- presets
    def get_state(self):
        return {
            "backend": "omen-rgb-keyboard",
            "zones": [self.get_zone(i) for i in range(4)],
            "brightness": self.get_brightness(),
            "mode": self.get_mode(),
            "speed": self.get_speed(),
            "gradient": self.get_gradient(),
        }

    def apply_state(self, state, elevate=None):
        """Apply a preset/state dict in the correct order."""
        zones = state.get("zones")
        if zones:
            for i, color in enumerate(zones[:4]):
                if color:
                    self.set_zone(i, color, elevate=elevate)
        brightness = state.get("brightness")
        if brightness is not None:
            self.set_brightness(brightness, elevate=elevate)
        gradient = state.get("gradient")
        if gradient:
            self.set_gradient(gradient, elevate=elevate)
        mode = state.get("mode", "static")
        if mode:
            self.set_mode(mode, elevate=elevate)
        speed = state.get("speed")
        if speed:
            self.set_speed(speed, elevate=elevate)


class MainlineBackend:
    """Static-color control through mainline hp-wmi multicolor LEDs.

    Names in the kernel patch (v10) for a 4-zone keyboard:
      zone 0 = hp::kbd_zoned_backlight-right
      zone 1 = hp::kbd_zoned_backlight-center
      zone 2 = hp::kbd_zoned_backlight-left
      zone 3 = hp::kbd_zoned_backlight-wasd
    Single-zone keyboards expose hp::kbd_backlight.
    """

    def __init__(self, elevate=False):
        self.elevate = elevate

    @staticmethod
    def _find_leds():
        found = []
        for pattern in MAINLINE_LED_GLOBS:
            found.extend(glob.glob(pattern))
        found = set(found)
        # The kernel patch registers zones in this order:
        # right=0, center=1, left=2, wasd=3.
        zone_order = ["right", "center", "left", "wasd"]
        ordered = []
        for name in zone_order:
            for path in sorted(found):
                if path.endswith("-" + name):
                    ordered.append(path)
                    found.discard(path)
        ordered.extend(sorted(found))
        return ordered

    @classmethod
    def driver_present(cls):
        if not _is_linux():
            return False
        return bool(cls._find_leds())

    @property
    def _zones(self):
        leds = self._find_leds()
        if not leds:
            raise OmenError(
                "未检测到 hp-wmi 键盘 LED 设备",
                hint="你的内核可能还没有合并 hp-wmi RGB 补丁，"
                     "请改用 omen-rgb-keyboard 内核驱动。",
            )
        return leds

    @staticmethod
    def _read(path):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()

    @staticmethod
    def _write(path, value):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(value)

    def get_zone(self, index):
        leds = self._zones
        if index >= len(leds):
            raise OmenError("当前后端只有 %d 个区域" % len(leds))
        parts = self._read(os.path.join(leds[index], "multi_intensity")).split()
        if len(parts) != 3:
            raise OmenError("无法解析 multi_intensity: %r" % parts)
        return "".join("%02X" % int(p) for p in parts)

    def set_zone(self, index, rgb, elevate=None):
        leds = self._zones
        if index >= len(leds):
            raise OmenError("当前后端只有 %d 个区域" % len(leds))
        rgb = validate_rgb(rgb)
        r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
        self._write(os.path.join(leds[index], "multi_intensity"), "%d %d %d" % (r, g, b))

    def get_all(self):
        return self.get_zone(0)

    def set_all(self, rgb, elevate=None):
        for i in range(len(self._zones)):
            self.set_zone(i, rgb)

    def get_brightness(self):
        leds = self._zones
        try:
            val = int(self._read(os.path.join(leds[0], "brightness")))
        except (OSError, ValueError):
            raise OmenError("无法读取亮度")
        return round(val * 100 / 255)

    def set_brightness(self, level, elevate=None):
        level = int(level)
        if not 0 <= level <= 100:
            raise OmenError("亮度必须是 0-100 的整数")
        for led in self._zones:
            self._write(os.path.join(led, "brightness"), str(round(level * 255 / 100)))

    def get_mode(self):
        return "static"

    def get_speed(self):
        return 1

    def get_gradient(self):
        return ""

    def set_mode(self, mode, elevate=None):
        if str(mode).strip().lower() not in ("static",):
            raise OmenError(
                "主线内核 LED 后端只支持静态颜色，不支持动画",
                hint="动画需要安装 omen-rgb-keyboard 内核驱动。",
            )

    def set_speed(self, speed, elevate=None):
        raise OmenError("主线内核 LED 后端不支持动画速度")

    def set_gradient(self, config, elevate=None):
        raise OmenError("主线内核 LED 后端不支持渐变动画")

    def get_state(self):
        return {
            "backend": "hp-wmi-leds",
            "zones": [self.get_zone(i) for i in range(len(self._zones))],
            "brightness": self.get_brightness(),
            "mode": "static",
            "speed": 1,
            "gradient": "",
        }

    def apply_state(self, state, elevate=None):
        zones = state.get("zones")
        if zones:
            for i, color in enumerate(zones[: len(self._zones)]):
                if color:
                    self.set_zone(i, color)
        brightness = state.get("brightness")
        if brightness is not None:
            self.set_brightness(brightness)
        mode = state.get("mode", "static")
        if mode:
            self.set_mode(mode)


def detect_backend(elevate=False):
    """Return the best available backend object, or None."""
    try:
        from omenrgb.daemon_client import DaemonBackend

        if DaemonBackend.driver_present():
            return DaemonBackend(elevate=elevate)
    except Exception:
        pass
    if OmenRGB.driver_present():
        return OmenRGB(elevate=elevate)
    if MainlineBackend.driver_present():
        return MainlineBackend(elevate=elevate)
    try:
        from omenrgb.wmi_backend import WmiAcpiBackend

        if WmiAcpiBackend.driver_present():
            return WmiAcpiBackend(elevate=elevate)
    except Exception:
        pass
    return None


# ------------------------------------------------------------- diagnostics


def _proc_modules():
    if not os.path.exists("/proc/modules"):
        return ""
    try:
        with open("/proc/modules", "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _module_loaded(name):
    for line in _proc_modules().splitlines():
        if line.split()[0] == name:
            return True
    return False


def _os_release():
    info = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    info[k] = v.strip('"')
    except OSError:
        pass
    return info


def _secure_boot_state():
    """Return 'enabled', 'disabled', or None if unknown."""
    mokutil = shutil.which("mokutil")
    if mokutil:
        try:
            out = subprocess.run(
                [mokutil, "--sb-state"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "enabled" in out.stdout.lower():
                return "enabled"
            if "disabled" in out.stdout.lower():
                return "disabled"
        except (OSError, subprocess.TimeoutExpired):
            pass
    for path in glob.glob("/sys/firmware/efi/efivars/SecureBoot-*"):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            if data and data[-1] == 1:
                return "enabled"
            if data and data[-1] == 0:
                return "disabled"
        except OSError:
            pass
    return None


def _group_memberships():
    """Return set of group names the current user belongs to."""
    groups = set()
    try:
        import grp

        for gid in os.getgroups():
            try:
                groups.add(grp.getgrgid(gid).gr_name)
            except KeyError:
                pass
    except ImportError:
        pass
    return groups


def _dmesg_omen():
    try:
        proc = subprocess.run(
            ["dmesg"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return None
        lines = [ln for ln in proc.stdout.splitlines() if "omen" in ln.lower()]
        return "\n".join(lines[-20:]) or "(dmesg 中没有 omen 相关日志)"
    except (OSError, subprocess.TimeoutExpired):
        return None


def diagnose():
    """Collect a structured diagnostic report."""
    report = []

    def add(status, title, detail=""):
        report.append({"status": status, "title": title, "detail": detail})

    osr = _os_release()
    distro = " ".join(
        x for x in (osr.get("NAME"), osr.get("VERSION_ID")) if x
    ) or "未知发行版"
    try:
        kernel = os.uname().release
    except AttributeError:
        kernel = "未知"
    add("info", "系统", "%s / 内核 %s / Python %s" % (distro, kernel, sys.version.split()[0]))

    wmi_devices = []
    for path in glob.glob("/sys/bus/wmi/devices/*"):
        wmi_devices.append(os.path.basename(path))
    bios_guid_found = any(WMI_BIOS_GUID.upper() in d.upper() for d in wmi_devices)
    if bios_guid_found:
        add("ok", "HP WMI BIOS GUID", "已找到 %s" % WMI_BIOS_GUID)
    else:
        add(
            "err",
            "HP WMI BIOS GUID",
            "未在 /sys/bus/wmi/devices 中找到 %s (可能不是 OMEN/被 ACPI 屏蔽)" % WMI_BIOS_GUID,
        )

    if _module_loaded("hp_wmi"):
        add(
            "warn",
            "hp_wmi 模块",
            "hp_wmi 已加载，可能与 omen-rgb-keyboard 冲突，建议 blacklist 后重启",
        )
    else:
        add("ok", "hp_wmi 模块", "未加载（良好）")

    if _module_loaded(DRIVER_NAME):
        add("ok", DRIVER_NAME + " 模块", "已加载")
    else:
        add(
            "err",
            DRIVER_NAME + " 模块",
            "未加载。请先安装驱动: sudo ./install-driver.sh",
        )

    if os.path.isdir(SYSFS_BASE):
        try:
            files = sorted(os.listdir(SYSFS_BASE))
        except OSError as exc:
            files = []
            add("err", "sysfs 读取", str(exc))
        add("ok", "sysfs 接口", SYSFS_BASE + "\n  " + ", ".join(files))
        zone_path = os.path.join(SYSFS_BASE, "zone00")
        if os.access(zone_path, os.W_OK):
            add("ok", "写入权限", "当前用户可以直接写 sysfs")
        else:
            groups = _group_memberships()
            geteuid = getattr(os, "geteuid", lambda: -1)
            if "input" in groups or geteuid() == 0:
                add("warn", "写入权限", "os.access 报告不可写（可能因 sysfs 权限模型），可尝试实际操作")
            else:
                add(
                    "err",
                    "写入权限",
                    "当前用户不在 input 组且不是 root，无法写 sysfs。"
                    "运行 sudo ./install-udev-rules.sh 后重新登录。",
                )
    else:
        add(
            "err",
            "sysfs 接口",
            "%s 不存在" % SYSFS_BASE,
        )

    mainline = MainlineBackend._find_leds()
    if mainline:
        add("info", "主线 hp-wmi LED", "检测到 %d 个多色 LED 设备" % len(mainline))
    else:
        add("info", "主线 hp-wmi LED", "未检测到（正常，使用 omen-rgb-keyboard 驱动即可）")

    try:
        from omenrgb.wmi_backend import WmiAcpiBackend, acpi_call_installed

        if acpi_call_installed():
            add("ok", "acpi_call", "已找到 /proc/acpi/call，可绕过驱动直接调用 WMI")
            if getattr(os, "geteuid", lambda: 1)() != 0:
                add(
                    "info",
                    "WMI 深度探测",
                    "当前非 root，跳过。用 sudo omenrgb diagnose 可读取键盘类型/颜色/亮度。",
                )
            else:
                backend = WmiAcpiBackend()
                try:
                    ktype = backend.keyboard_type()
                    add(
                        "ok",
                        "键盘类型 (WMI 0x20008/0x2B)",
                        "RE20=%s -> %s"
                        % (
                            ktype,
                            {
                                0: "无背光",
                                1: "四分区带数字键盘",
                                2: "四分区无数字键盘",
                                3: "RGB 每键",
                                4: "单分区带数字键盘",
                                5: "单分区无数字键盘",
                            }.get(ktype, "未知"),
                        ),
                    )
                    caps = backend.capabilities()
                    add("ok", "背光能力 (WMI 0x20009/0x01)", "返回 %s" % caps.hex(" "))
                    try:
                        colors = backend.read_color_table()
                        add("ok", "当前颜色 (WMI 0x20009/0x02)", ", ".join("#" + c for c in colors))
                    except OmenError as exc:
                        add("err", "当前颜色", exc.message + "；" + (exc.hint or ""))
                    try:
                        add("ok", "亮度 (WMI 0x20009/0x04)", "%d" % backend.read_brightness())
                    except OmenError as exc:
                        add("warn", "亮度", exc.message)
                except OmenError as exc:
                    add("err", "WMI 探测", exc.message + "；" + (exc.hint or ""))
        else:
            add(
                "info",
                "acpi_call",
                "未找到 /proc/acpi/call。Debian/Ubuntu: sudo apt install acpi-call-dkms",
            )
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
        add("warn", "WMI 后端", "导入或探测失败: %s" % exc)

    sb = _secure_boot_state()
    if sb == "enabled":
        add(
            "warn",
            "Secure Boot",
            "已启用。未签名的 DKMS 模块可能被拒绝加载（Key was rejected by service），"
            "需要 MOK 签名或关闭 Secure Boot。",
        )
    elif sb == "disabled":
        add("ok", "Secure Boot", "已关闭")
    else:
        add("info", "Secure Boot", "无法确定（需要 mokutil）")

    dmesg = _dmesg_omen()
    if dmesg is None:
        add("info", "dmesg", "无法读取（dmesg 可能被内核限制，试试 sudo dmesg | grep -i omen）")
    else:
        add("info", "dmesg (omen)", dmesg)

    state_path = "/var/lib/omen-rgb-keyboard/state"
    if os.path.exists(state_path):
        add("ok", "状态文件", state_path + " 存在（驱动会持久化配置）")
    else:
        add("info", "状态文件", state_path + " 不存在（首次使用属正常）")

    return report


def format_diagnose(report=None):
    if report is None:
        report = diagnose()
    status_icon = {"ok": "[OK]  ", "warn": "[!]   ", "err": "[ERR] ", "info": "[--]  "}
    lines = []
    for item in report:
        lines.append("%s %s" % (status_icon[item["status"]], item["title"]))
        if item["detail"]:
            for sub in item["detail"].splitlines():
                lines.append("        " + sub)
    return "\n".join(lines)


def quick_help():
    return (
        "常用命令：\n"
        "  omenrgb status                查看当前状态\n"
        "  omenrgb diagnose              生成诊断报告\n"
        "  omenrgb set-all FF0000        全部区域设为红色\n"
        "  omenrgb set-zone 0 00FF00     区域 0 设为绿色\n"
        "  omenrgb brightness 75         亮度 75%\n"
        "  omenrgb mode rainbow          彩虹动画\n"
        "  omenrgb speed 5               动画速度 5\n"
        "  omenrgb preset apply 彩虹     应用预设\n"
    )
