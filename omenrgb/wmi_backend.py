# SPDX-License-Identifier: GPL-3.0-or-later
"""HP OMEN 4-zone RGB keyboard control through ACPI WMI (acpi_call).

The firmware exposes the classic HP WMI data block
(GUID 5FB7F034-2C63-45E9-BE91-3D44E2C707E4, control method \\_SB.WMID.WMAA).
This backend evaluates that method directly through the acpi_call module
(/proc/acpi/call), so it needs neither a kernel patch nor an out-of-tree
driver, only the acpi_call module (Debian/Ubuntu: acpi-call-dkms).

Firmware ABI (verified against the DSDT of the OMEN 16-ap1xxx):

    WMAA(instance=0, mid, input_buffer)

    input_buffer:
      [0x00] u32 signature = 0x55434553 ("SECU")
      [0x04] u32 command   = 0x20008 (Gaming) / 0x20009 (Backlight)
      [0x08] u32 cmdtype   = query type
      [0x0C] u32 datasize  = payload size in bytes
      [0x10] payload ...

    Backlight (0x20009) cmdtypes:
      0x01  capabilities (keyboard kind / backlight state)
      0x02  read 128-byte color table (RGB of 4 zones at payload[0x19..0x24])
      0x03  write color table (only those 12 bytes are consumed)
      0x04  read brightness (EC LBRT)
      0x05  write brightness (EC LBRT)

    Gaming (0x20008) cmdtypes:
      0x2B  read keyboard type (EC RE20): 0=none, 1=4-zone+numpad,
            2=4-zone, 3=per-key, 4/5=single zone

    mid = outsize encoding: 0 -> 1, 1-4 -> 2, 5-128 -> 3, 129-1024 -> 4

    Response buffer:
      [0x00] u32 signature = 0x53534150 ("PASS") on success
      [0x04] u32 return_code (0 = success)
      [0x08] data ...

acpi_call note: the module formats the response into a fixed 256-byte text
buffer, so a 136-byte response is truncated after 42 bytes.  The zone RGB
bytes live at response[0x21..0x2C] (bytes 33..44), so zone 3 is cut off
unless BUFFER_SIZE is raised.  See README: patch acpi_call's
"#define BUFFER_SIZE 256" to 2048 and rebuild.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from omenrgb.core import OmenError, validate_rgb


CALL_PATHS = (
    "/proc/acpi/call",
    "/sys/kernel/debug/acpi/call",
)

WMAA_METHOD = r"\_SB.WMID.WMAA"

# NOPASSWD sudoers allows this repo helper to run as root without a password,
# so a normal (non-root) user can still drive the firmware.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WMI_CALL_SCRIPT = os.path.join(REPO_ROOT, "tools", "wmi_call.py")
HID_PROBE_SCRIPT = os.path.join(REPO_ROOT, "tools", "hid_probe_linux.py")

CMD_BACKLIGHT = 0x00020009
CMD_GAMING = 0x00020008

CMDT_GET_CAPS = 0x01
CMDT_GET_COLOR = 0x02
CMDT_SET_COLOR = 0x03
CMDT_GET_BRIGHTNESS = 0x04
CMDT_SET_BRIGHTNESS = 0x05
CMDT_LIGHTBAR_MAILBOX = 0x0B  # EC mailbox: real lighting command (Dojo path)
CMDT_GET_KEYBOARD_TYPE = 0x2B

SIGNATURE = 0x55434553  # "SECU"
PASS_SIG = 0x53534150  # "PASS"

KEYBOARD_TYPES = {
    0: "无背光",
    1: "四分区带数字键盘",
    2: "四分区无数字键盘",
    3: "RGB 每键",
    4: "单分区带数字键盘",
    5: "单分区无数字键盘",
}

COLOR_TABLE_OFFSET = 0x19  # RGB data starts here (25) in the 128-byte table

# LightBarCmdByte layout (HP.Omen.Background.DojoLightingBg, reversed):
# the keyboard/lightbar lighting command payload for CMDT 0x0B.
LBB_DEVICE = 0
LBB_MODE = 1
LBB_CONFIG = 2
LBB_BRIGHTNESS = 3
LBB_TRIBE = 4
LBB_BASS = 5
LBB_COLOR_COUNT = 6
LBB_ZONE_RGB = 7        # 4 zones × (R,G,B) = 12 bytes

# TargetDevice: 0 = LightBar, 1 = FourZoneAni (keyboard)
DEVICE_KEYBOARD = 1

# MODE values (0 = static; animations from SetAnimationMode)
MODE_STATIC = 0

# _effectMapping from DojoLightingBg (effect id -> payload mode byte).
# Verified enum names follow the OMEN KbLightingEffect family where possible;
# ids 10-12 are newer effects and their display names are best-effort.
ANIMATION_MODES = {
    "ghosting": 4,
    "ripple": 5,
    "wave": 6,
    "xshape": 7,
    "raindrop": 8,
    "hpanimation": 9,
    "starlight": 10,
    "galaxy": 11,
    "linestreak": 12,
}
ANIMATION_MODE_BYTE = {4: 2, 5: 3, 6: 4, 7: 6, 8: 7, 9: 8, 10: 9, 11: 10, 12: 11}

# Direct EC/MMIO registers (DSDT: OperationRegion H2RA = SystemMemory 0xFE700000)
EC_MMIO_BASE = 0xFE700000
EC_MMIO_SIZE = 0x1000
REG_KBAM = 0x364          # keyboard animation mode (8 bit, status mirror)
REG_LCMC = 0xEE0          # lighting commit flag (bit 5)
REG_LRGB = 0xEE3          # 96-bit primary color table (12 bytes)
REG_BRGB = 0xEF0          # 96-bit secondary color table (12 bytes)
REG_LBRT = 0xEFC          # brightness: 0xE4 on, 0x64 off

# KBAM values observed on this machine (16-ap1xxx).  The firmware only exposes
# KBAM as a status mirror (updated when the Fn lighting shortcut is pressed);
# the mapping below is empirical: 4 == the "交替呼吸/颜色交替" mode the user
# activated with the shortcut.  Other values are reported raw.
KBAM_LABELS = {
    0: "未知(0)",
    1: "未知(1)",
    2: "未知(2)",
    3: "未知(3)",
    4: "动画(呼吸/颜色交替, 由快捷键触发)",
    5: "未知(5)",
    6: "未知(6)",
    7: "未知(7)",
    8: "未知(8)",
    9: "未知(9)",
}


def _mid_for_outsize(outsize):
    if outsize > 128:
        return 4
    if outsize > 4:
        return 3
    if outsize > 0:
        return 2
    return 1


def find_call_path():
    for path in CALL_PATHS:
        if os.path.exists(path):
            return path
    return None


def run_privileged(argv, timeout=40, manual=None):
    """Run argv as root with graceful fallbacks.

    1) sudo -n   — works when the repo NOPASSWD rules are installed (silent)
    2) pkexec    — graphical password dialog (KDE/GNOME polkit agent)
    3) otherwise — raise OmenError with the exact manual command.
    """
    errors = []
    attempts = []
    if shutil.which("sudo"):
        attempts.append(("sudo -n", ["sudo", "-n"] + argv))
    if shutil.which("pkexec"):
        attempts.append(("pkexec", ["pkexec"] + argv))
    for label, cmd in attempts:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append("%s: %s" % (label, exc))
            continue
        if proc.returncode == 0:
            return proc
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        errors.append("%s: rc=%d %s" % (label, proc.returncode,
                                        (tail[-1] if tail else "")[:120]))
        if label == "pkexec":
            break  # the user was prompted and declined; stop here
    if not errors:
        errors.append("没有可用的提权方式 (sudo/pkexec)")
    raise OmenError(
        "提权失败: %s" % "; ".join(errors),
        hint=manual or ("请在终端手动运行: sudo %s" % " ".join(argv)),
    )


def acpi_call_installed():
    return find_call_path() is not None


def build_wmaa_line(cmdtype, payload=b"", outsize=128, command=CMD_BACKLIGHT):
    """Build the acpi_call input line for \\_SB.WMID.WMAA."""
    buf = bytearray(16 + len(payload))
    buf[0:4] = SIGNATURE.to_bytes(4, "little")
    buf[4:8] = command.to_bytes(4, "little")
    buf[8:12] = cmdtype.to_bytes(4, "little")
    buf[12:16] = len(payload).to_bytes(4, "little")
    buf[16:] = payload
    return "%s 0 %d b%s" % (WMAA_METHOD, _mid_for_outsize(outsize), buf.hex())


def parse_acpi_result(result):
    """Parse the acpi_call text output into (raw_response_bytes, truncated)."""
    tokens = re.findall(r"0x([0-9A-Fa-f]{2})", result)
    if not tokens:
        raise OmenError(
            "WMAA 调用失败，返回: %r" % result,
            hint="确认 acpi_call 模块已加载 (lsmod | grep acpi_call)；"
                 "内核 Secure Boot 可能阻止了未签名模块。",
        )
    raw = bytes(int(t, 16) for t in tokens)
    if len(raw) < 8:
        raise OmenError("WMAA 返回过短: %s" % result)

    signature = int.from_bytes(raw[0:4], "little")
    retc = int.from_bytes(raw[4:8], "little")
    if signature != PASS_SIG:
        raise OmenError(
            "WMAA 返回签名异常 (0x%08X, RETC=0x%X): %s"
            % (signature, retc, result),
            hint="返回签名应是 'PASS'；若为 'FAIL' 请把上面的输出发给助手。",
        )
    if retc != 0:
        raise OmenError("WMAA 返回错误码 0x%X" % retc)

    truncated = not result.rstrip().endswith("}")
    return raw, truncated


class WmiAcpiBackend:
    """Control the keyboard backlight through \\_SB.WMID.WMAA via acpi_call."""

    backend_name = "hp-wmi-acpi"

    def __init__(self, elevate=False):
        self.elevate = elevate
        self._type = None
        self._caps = None
        self._colors = None
        self._brightness = None

    # ------------------------------------------------------------ presence
    @classmethod
    def driver_present(cls):
        if not sys.platform.startswith("linux"):
            return False
        return acpi_call_installed()

    # ---------------------------------------------------------- low level
    def _ensure_root(self):
        if getattr(os, "geteuid", lambda: 1)() == 0:
            return None
        if self.elevate and (shutil.which("pkexec") or shutil.which("sudo")):
            return None  # let the subprocess elevate
        raise OmenError(
            "acpi_call (/proc/acpi/call) 需要 root 权限",
            hint="请用 sudo 运行本工具，或安装 polkit (pkexec) 后重试。",
        )

    def _call(self, cmdtype, payload=b"", outsize=128, command=CMD_BACKLIGHT):
        """Evaluate WMAA and return the response bytes."""
        if getattr(os, "geteuid", lambda: 1)() != 0:
            return self._call_elevated(cmdtype, payload, outsize, command)
        self._ensure_root()
        path = find_call_path()
        if not path:
            raise OmenError(
                "未找到 acpi_call 接口 (/proc/acpi/call)",
                hint="Debian/Ubuntu: sudo apt install acpi-call-dkms dkms; "
                     "Arch: yay -S acpi_call-dkms。装完重启或 modprobe acpi_call。",
            )

        line = build_wmaa_line(cmdtype, payload, outsize, command)
        if len(line) >= 512:
            raise OmenError("acpi_call 输入超长 (%d 字符)" % len(line))

        try:
            if getattr(os, "geteuid", lambda: 1)() == 0:
                with open(path, "w", encoding="ascii") as fh:
                    fh.write(line + "\n")
                with open(path, "r", encoding="ascii", errors="replace") as fh:
                    result = fh.read().strip()
            else:
                result = self._elevated_call(path, line)
        except PermissionError:
            raise OmenError(
                "没有权限写 %s" % path,
                hint="请用 sudo 运行，或安装 polkit 后让本工具自动提权。",
            )
        except OSError as exc:
            raise OmenError("acpi_call 调用失败: %s" % exc)

        return parse_acpi_result(result)

    def _call_elevated(self, cmdtype, payload, outsize, command):
        """Run the WMAA call through tools/wmi_call.py as root."""
        if not os.path.exists(WMI_CALL_SCRIPT):
            raise OmenError(
                "找不到助手脚本 %s" % WMI_CALL_SCRIPT,
                hint="请保持仓库结构完整（tools/wmi_call.py 存在）。",
            )
        argv = [
            "/usr/bin/python3", WMI_CALL_SCRIPT,
            format(command, "x"), format(cmdtype, "x"),
            payload.hex(), format(outsize, "x"),
        ]
        proc = run_privileged(argv, manual="sudo /usr/bin/python3 %s" % WMI_CALL_SCRIPT)
        raw_line = next((ln for ln in proc.stdout.splitlines()
                         if ln.startswith("RAW:")), None)
        if raw_line is None:
            raise OmenError("wmi_call 输出异常: %s" % proc.stdout.strip())
        return parse_acpi_result(raw_line)

    @staticmethod
    def _elevated_call(path, line):
        shell = (
            'printf "%s\\n" "$1" > "$2" && cat "$2"',
            "wmi-helper",
            line,
            path,
        )
        attempts = []
        if shutil.which("pkexec"):
            attempts.append(["pkexec", "sh", "-c"] + list(shell))
        if shutil.which("sudo"):
            attempts.append(["sudo", "-n", "sh", "-c"] + list(shell))
        last_error = "没有可用的提权方式"
        for cmd in attempts:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if proc.returncode == 0:
                    return proc.stdout.strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
        raise OmenError("提权调用 acpi_call 失败: %s" % last_error)

    # ---------------------------------------------------------- raw queries
    def keyboard_type(self):
        raw, _ = self._call(CMDT_GET_KEYBOARD_TYPE, outsize=4, command=CMD_GAMING)
        self._type = raw[8] if len(raw) > 8 else None
        return self._type

    def capabilities(self):
        raw, _ = self._call(CMDT_GET_CAPS, outsize=4)
        self._caps = raw[8:] if len(raw) >= 10 else b""
        return self._caps

    def read_color_table(self):
        raw, truncated = self._call(CMDT_GET_COLOR, outsize=128)
        base = 8 + COLOR_TABLE_OFFSET
        if len(raw) < base + 12:
            raise OmenError(
                "读回的颜色表被 acpi_call 截断 (只返回 %d 字节)"
                % len(raw),
                hint="把 acpi_call 的 BUFFER_SIZE 从 256 改成 2048 后重新编译安装，"
                     "或先运行 tools/wmi_probe_linux.py 查看截断详情。",
            )
        colors = []
        for zone in range(4):
            off = base + zone * 3
            colors.append("%02X%02X%02X" % (raw[off], raw[off + 1], raw[off + 2]))
        self._colors = colors
        return colors

    def write_color_table(self, colors):
        """Write static colors through the real lighting path (EC mailbox).

        The legacy 128-byte color table (CMDT 0x03) only stores the BIOS/boot
        colors; the live keyboard is driven by CMDT 0x0B with the
        LightBarCmdByte payload (verified visually on 16-ap1xxx).
        """
        if len(colors) != 4:
            raise OmenError("颜色表必须包含 4 个区域")
        colors = [validate_rgb(c) for c in colors]
        payload = self.build_lightbar_payload(colors)
        self._call(CMDT_LIGHTBAR_MAILBOX, payload, outsize=8)
        # Also keep the legacy BIOS/boot color table in sync.
        legacy = bytearray(128)
        for zone, rgb in enumerate(colors):
            off = COLOR_TABLE_OFFSET + zone * 3
            legacy[off] = int(rgb[0:2], 16)
            legacy[off + 1] = int(rgb[2:4], 16)
            legacy[off + 2] = int(rgb[4:6], 16)
        try:
            self._call(CMDT_SET_COLOR, bytes(legacy), outsize=128)
        except OmenError:
            pass  # legacy table is best-effort
        self._colors = [c.upper() for c in colors]

    def build_lightbar_payload(self, colors, mode=MODE_STATIC, brightness=100,
                               device=DEVICE_KEYBOARD):
        """Build the 128-byte LightBarCmdByte command for the keyboard."""
        payload = bytearray(128)
        payload[LBB_DEVICE] = device
        payload[LBB_MODE] = mode
        payload[LBB_CONFIG] = 0
        payload[LBB_BRIGHTNESS] = brightness
        payload[LBB_COLOR_COUNT] = 4
        for zone, rgb in enumerate(colors[:4]):
            rgb = validate_rgb(rgb)
            off = LBB_ZONE_RGB + zone * 3
            payload[off] = int(rgb[0:2], 16)
            payload[off + 1] = int(rgb[2:4], 16)
            payload[off + 2] = int(rgb[4:6], 16)
        return bytes(payload)

    def read_brightness(self):
        raw, _ = self._call(CMDT_GET_BRIGHTNESS, outsize=4)
        if len(raw) < 9:
            raise OmenError("亮度读取返回过短")
        value = raw[8]
        if value == 0xE4:
            value = 100
        elif value == 0x64:
            value = 0
        self._brightness = value
        return value

    def write_brightness(self, level):
        level = int(level)
        if not 0 <= level <= 100:
            raise OmenError("亮度必须是 0-100 的整数")
        # Brightness lives in the LightBarCmdByte payload (byte 3); re-apply
        # the last-known colors with the new brightness through the mailbox.
        colors = self._colors or self.read_color_table()
        payload = self.build_lightbar_payload(colors, brightness=level)
        self._call(CMDT_LIGHTBAR_MAILBOX, payload, outsize=8)
        self._brightness = level

    # ---------------------------------------------- EC MMIO (mode & commit)
    @staticmethod
    def _mmio_read(offset, length=1):
        """Read bytes from the EC MMIO window (DSDT H2RA at 0xFE700000)."""
        try:
            with open("/dev/mem", "rb") as fh:
                fh.seek(EC_MMIO_BASE + offset)
                data = fh.read(length)
            if len(data) != length:
                raise OSError("short read")
            return data
        except (OSError, PermissionError, ValueError) as exc:
            raise OmenError(
                "无法读取 EC 寄存器 (0x%X)" % (EC_MMIO_BASE + offset),
                hint="需要 root 权限；若仍失败请确认内核未开启 "
                     "CONFIG_STRICT_DEVMEM 对此区域的限制。",
            ) from exc

    @staticmethod
    def _mmio_write(offset, data):
        try:
            with open("/dev/mem", "r+b") as fh:
                fh.seek(EC_MMIO_BASE + offset)
                fh.write(bytes(data))
        except (OSError, PermissionError, ValueError) as exc:
            raise OmenError(
                "无法写入 EC 寄存器 (0x%X)" % (EC_MMIO_BASE + offset),
                hint="需要 root 权限。",
            ) from exc

    def read_kbam(self):
        """Return the keyboard animation-mode register value (0-255)."""
        if getattr(os, "geteuid", lambda: 1)() != 0:
            proc = run_privileged(
                ["/usr/bin/python3", HID_PROBE_SCRIPT, "kbam"],
                manual="sudo /usr/bin/python3 %s kbam" % HID_PROBE_SCRIPT)
            match = re.search(r"KBAM = (\d+)", proc.stdout)
            if match:
                return int(match.group(1))
            raise OmenError("读取 KBAM 失败: %s" % (proc.stderr.strip() or proc.stdout.strip()))
        return self._mmio_read(REG_KBAM)[0]

    def kbam_label(self, value=None):
        if value is None:
            value = self.read_kbam()
        return KBAM_LABELS.get(value, "未知(0x%02X)" % value)

    def write_kbam(self, value):
        """Write the KBAM register directly (advanced, mostly a status mirror)."""
        value = int(value)
        if not 0 <= value <= 255:
            raise OmenError("KBAM 值必须是 0-255")
        if getattr(os, "geteuid", lambda: 1)() != 0:
            run_privileged(
                ["/usr/bin/python3", HID_PROBE_SCRIPT, "kbam", str(value)],
                manual="sudo /usr/bin/python3 %s kbam %d" % (HID_PROBE_SCRIPT, value))
            return
        self._mmio_write(REG_KBAM, bytes([value]))

    def ec_commit_colors(self, colors):
        """Write colors straight to EC LRGB/BRGB and re-assert LCMC.

        Equivalent to the WMI color-table write, but through the EC MMIO
        window directly.  Useful as a fallback when the WMI write alone does
        not visibly update the keyboard.
        """
        if len(colors) != 4:
            raise OmenError("颜色表必须包含 4 个区域")
        rgb = bytearray()
        for color in colors:
            color = validate_rgb(color)
            rgb += bytes((int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)))
        self._mmio_write(REG_LRGB, rgb)
        self._mmio_write(REG_BRGB, rgb)
        lcmc = self._mmio_read(REG_LCMC)[0]
        self._mmio_write(REG_LCMC, bytes([lcmc & ~0x20]))
        self._mmio_write(REG_LCMC, bytes([lcmc | 0x20]))
        self._colors = [c.upper() for c in colors]

    def ec_commit_brightness(self, level):
        level = int(level)
        value = 0xE4 if level > 0 else 0x64
        self._mmio_write(REG_LBRT, bytes([value]))
        self._brightness = level

    # ------------------------------------------------------- public API
    def _zones(self):
        return self.read_color_table()

    def get_zone(self, index):
        if not 0 <= index < 4:
            raise OmenError("区域索引必须是 0-3")
        return self.read_color_table()[index]

    def get_all(self):
        colors = self.read_color_table()
        return colors[0] if len(set(colors)) == 1 else ",".join(colors)

    def set_zone(self, index, rgb, elevate=None):
        if not 0 <= index < 4:
            raise OmenError("区域索引必须是 0-3")
        colors = self.read_color_table()
        colors[index] = validate_rgb(rgb)
        self.write_color_table(colors)

    def set_all(self, rgb, elevate=None):
        rgb = validate_rgb(rgb)
        self.write_color_table([rgb] * 4)

    def get_brightness(self):
        return self.read_brightness()

    def set_brightness(self, level, elevate=None):
        self.write_brightness(level)

    def get_mode(self):
        return "static"

    def get_speed(self):
        return 1

    def get_gradient(self):
        return ""

    def set_mode(self, mode, elevate=None):
        mode = str(mode).strip().lower()
        if mode == "static":
            return
        if mode not in ANIMATION_MODES:
            raise OmenError(
                "未知动画: %s (可选: %s)" % (mode, ", ".join(sorted(ANIMATION_MODES))),
                hint="这些动画通过 EC 邮箱直接驱动键盘 MCU（Dojo 协议）。",
            )
        self.set_animation(mode)

    def set_animation(self, mode, colors=None, brightness=None):
        """Send an animation effect through the EC mailbox (Dojo protocol)."""
        mode = str(mode).strip().lower()
        if mode not in ANIMATION_MODES:
            raise OmenError("未知动画: %s" % mode)
        colors = colors or self._colors or self.read_color_table()
        mode_byte = ANIMATION_MODE_BYTE[ANIMATION_MODES[mode]]
        payload = self.build_lightbar_payload(
            colors, mode=mode_byte,
            brightness=self._brightness if brightness is None else brightness,
        )
        self._call(CMDT_LIGHTBAR_MAILBOX, payload, outsize=8)

    def set_speed(self, speed, elevate=None):
        raise OmenError("WMI 后端不支持动画速度")

    def set_gradient(self, config, elevate=None):
        raise OmenError("WMI 后端不支持渐变动画")

    def get_state(self):
        state = {
            "backend": self.backend_name,
            "zones": self.read_color_table(),
            "brightness": self.read_brightness(),
            "mode": "static",
            "speed": 1,
            "gradient": "",
        }
        try:
            state["kbam"] = self.read_kbam()
            state["kbam_label"] = self.kbam_label()
        except OmenError:
            state["kbam"] = None
            state["kbam_label"] = None
        return state

    def apply_ec(self, colors=None, brightness=None):
        """Apply colors/brightness through the direct EC MMIO window."""
        if colors is not None:
            self.ec_commit_colors(colors)
        if brightness is not None:
            self.ec_commit_brightness(brightness)

    def apply_state(self, state, elevate=None):
        zones = state.get("zones")
        if zones:
            colors = [validate_rgb(c) for c in zones[:4] if c]
            if colors:
                if len(colors) == 4:
                    self.write_color_table(colors)
                else:
                    current = self.read_color_table()
                    for i, c in enumerate(colors):
                        current[i] = c
                    self.write_color_table(current)
        brightness = state.get("brightness")
        if brightness is not None:
            self.set_brightness(brightness)
        mode = state.get("mode", "static")
        if mode:
            self.set_mode(mode)
