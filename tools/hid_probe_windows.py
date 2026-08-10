#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Probe HID interfaces of the OMEN keyboard on Windows (read-only).

Enumerates HID device interfaces, filters for VID 0C45 / PID 7D1C (the
"HP Gaming Keyboard" on HyperX OMEN 16-ap1xxx) and prints, for every
interface:
  - the device path (maps to the Linux hidraw node),
  - usage page / usage (identifies vendor RGB interfaces),
  - input/output/feature report lengths,
  - current feature report contents (read-only GET_FEATURE).

Run with any Python 3 (no dependencies):
    python tools/hid_probe_windows.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
from ctypes import POINTER, Structure, byref, c_ubyte, c_ulong, c_ushort, c_void_p, c_wchar_p, create_string_buffer, sizeof


class HIDD_ATTRIBUTES(Structure):
    _fields_ = [
        ("cbSize", c_ulong),
        ("VendorID", c_ushort),
        ("ProductID", c_ushort),
        ("VersionNumber", c_ushort),
    ]


class HIDP_CAPS(Structure):
    _fields_ = [
        ("Usage", c_ushort),
        ("UsagePage", c_ushort),
        ("InputReportByteLength", c_ushort),
        ("OutputReportByteLength", c_ushort),
        ("FeatureReportByteLength", c_ushort),
        ("Reserved", c_ushort * 17),
        ("NumberLinkCollectionNodes", c_ushort),
        ("NumberInputButtonCaps", c_ushort),
        ("NumberInputValueCaps", c_ushort),
        ("NumberInputDataIndices", c_ushort),
        ("NumberOutputButtonCaps", c_ushort),
        ("NumberOutputValueCaps", c_ushort),
        ("NumberOutputDataIndices", c_ushort),
        ("NumberFeatureButtonCaps", c_ushort),
        ("NumberFeatureValueCaps", c_ushort),
        ("NumberFeatureDataIndices", c_ushort),
    ]


class SP_DEVICE_INTERFACE_DATA(Structure):
    _fields_ = [
        ("cbSize", c_ulong),
        ("InterfaceClassGuid", c_ubyte * 16),
        ("Flags", c_ulong),
        ("Reserved", c_void_p),
    ]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(Structure):
    _fields_ = [("cbSize", c_ulong), ("DevicePath", c_wchar_p)]


DIGCF_PRESENT = 0x2
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ_WRITE = 3
OPEN_EXISTING = 3


def main():
    if not sys.platform.startswith("win"):
        print("此脚本只用于 Windows。")
        return 1

    hid = ctypes.WinDLL("hid.dll")
    setupapi = ctypes.WinDLL("setupapi.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")

    hid.HidD_GetHidGuid.argtypes = [POINTER(c_ubyte * 16)]
    hid.HidD_GetAttributes.argtypes = [c_void_p, POINTER(HIDD_ATTRIBUTES)]
    hid.HidD_GetAttributes.restype = ctypes.c_int
    hid.HidD_GetPreparsedData.argtypes = [c_void_p, POINTER(c_void_p)]
    hid.HidD_GetPreparsedData.restype = ctypes.c_int
    hid.HidP_GetCaps.argtypes = [c_void_p, POINTER(HIDP_CAPS)]
    hid.HidP_GetCaps.restype = ctypes.c_int
    hid.HidD_FreePreparsedData.argtypes = [c_void_p]
    hid.HidD_GetFeature.argtypes = [c_void_p, c_void_p, c_ulong]
    hid.HidD_GetFeature.restype = ctypes.c_int

    setupapi.SetupDiGetClassDevsW.argtypes = [POINTER(c_ubyte * 16), c_wchar_p, wt.HWND, c_ulong]
    setupapi.SetupDiGetClassDevsW.restype = c_void_p
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        c_void_p, c_void_p, POINTER(c_ubyte * 16), c_ulong, POINTER(SP_DEVICE_INTERFACE_DATA)
    ]
    setupapi.SetupDiEnumDeviceInterfaces.restype = ctypes.c_int
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        c_void_p, POINTER(SP_DEVICE_INTERFACE_DATA), c_void_p, c_ulong, POINTER(c_ulong), c_void_p
    ]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = ctypes.c_int
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [c_void_p]
    setupapi.SetupDiDestroyDeviceInfoList.restype = ctypes.c_int

    kernel32.CreateFileW.restype = c_void_p
    kernel32.CloseHandle.argtypes = [c_void_p]

    guid = (c_ubyte * 16)()
    hid.HidD_GetHidGuid(byref(guid))
    devs = setupapi.SetupDiGetClassDevsW(byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not devs or devs == c_void_p(-1).value:
        print("SetupDiGetClassDevsW 失败: %s" % ctypes.WinError(ctypes.get_last_error()))
        return 1

    def open_dev(path):
        h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None)
        return h if h not in (0, c_void_p(-1).value) else None

    found = []
    idx = 0
    while True:
        iface = SP_DEVICE_INTERFACE_DATA()
        iface.cbSize = sizeof(SP_DEVICE_INTERFACE_DATA)
        if not setupapi.SetupDiEnumDeviceInterfaces(devs, None, byref(guid), idx, byref(iface)):
            break
        idx += 1
        need = c_ulong(0)
        setupapi.SetupDiGetDeviceInterfaceDetailW(devs, byref(iface), None, 0, byref(need), None)
        if not need.value:
            continue
        buf = create_string_buffer(need.value + 4)
        ctypes.memmove(buf, byref(c_ulong(sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W))), 4)
        if not setupapi.SetupDiGetDeviceInterfaceDetailW(devs, byref(iface), buf, need.value, byref(need), None):
            continue
        path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
        if "0c45" not in path.lower():
            continue
        found.append(path)

    setupapi.SetupDiDestroyDeviceInfoList(devs)

    if not found:
        print("未找到 VID 0C45 的 HID 接口（键盘可能未枚举为 USB HID，或路径不匹配）。")
        return 1

    for path in found:
        print("=" * 96)
        print("PATH:", path)
        h = open_dev(path)
        if not h:
            print("  (无法打开，可能被其他进程独占)")
            continue
        attrs = HIDD_ATTRIBUTES()
        attrs.cbSize = sizeof(HIDD_ATTRIBUTES)
        hid.HidD_GetAttributes(h, byref(attrs))
        pre = c_void_p()
        caps = HIDP_CAPS()
        if not hid.HidD_GetPreparsedData(h, byref(pre)):
            print("  (HidD_GetPreparsedData 失败)")
            kernel32.CloseHandle(h)
            continue
        if not hid.HidP_GetCaps(pre, byref(caps)):
            print("  (HidP_GetCaps 失败)")
            hid.HidD_FreePreparsedData(pre)
            kernel32.CloseHandle(h)
            continue
        print("  VID=%04X PID=%04X REV=%04X" % (attrs.VendorID, attrs.ProductID, attrs.VersionNumber))
        print(
            "  UsagePage=%04X Usage=%04X | Input=%dB Output=%dB Feature=%dB"
            % (
                caps.UsagePage,
                caps.Usage,
                caps.InputReportByteLength,
                caps.OutputReportByteLength,
                caps.FeatureReportByteLength,
            )
        )
        print(
            "  value caps: in=%d out=%d feat=%d"
            % (caps.NumberInputValueCaps, caps.NumberOutputValueCaps, caps.NumberFeatureValueCaps)
        )
        if caps.FeatureReportByteLength > 0:
            seen = set()
            for rid in range(0, 256):
                fbuf = create_string_buffer(caps.FeatureReportByteLength + 1)
                ctypes.memset(fbuf, 0, caps.FeatureReportByteLength + 1)
                fbuf[0] = rid
                if hid.HidD_GetFeature(h, fbuf, caps.FeatureReportByteLength + 1):
                    data = bytes(fbuf.raw[: caps.FeatureReportByteLength + 1])
                    key = data[:8]
                    if key not in seen:
                        seen.add(key)
                        print(
                            "  FEATURE report id=%02X len=%d: %s"
                            % (rid, caps.FeatureReportByteLength + 1, data.hex(" "))
                        )
        hid.HidD_FreePreparsedData(pre)
        kernel32.CloseHandle(h)

    print()
    print("提示: 同一接口在 Linux 下对应一个 /dev/hidrawN 节点，")
    print("用 vendor 定义接口 (UsagePage FF00-FFFF) 的节点做 RGB 控制。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
