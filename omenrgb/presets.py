# SPDX-License-Identifier: GPL-3.0-or-later
"""Preset (profile) storage for the OMEN RGB tool.

User presets live in ~/.config/omenrgb/presets.json.
"""

from __future__ import annotations

import json
import os
import re


CONFIG_DIR = os.environ.get("OMENRGB_CONFIG_DIR") or os.path.join(
    os.path.expanduser("~"), ".config", "omenrgb"
)
PRESET_FILE = os.path.join(CONFIG_DIR, "presets.json")

NAME_RE = re.compile(r"^[\w\u4e00-\u9fff -]{1,40}$")


# Built-in presets (not written to disk, always available).
BUILTIN_PRESETS = {
    "默认白": {
        "mode": "static",
        "speed": 5,
        "brightness": 100,
        "zones": ["FFFFFF", "FFFFFF", "FFFFFF", "FFFFFF"],
        "gradient": "",
    },
    "关闭灯光": {
        "mode": "static",
        "speed": 5,
        "brightness": 0,
        "zones": ["000000", "000000", "000000", "000000"],
        "gradient": "",
    },
    "红色警戒": {
        "mode": "static",
        "speed": 5,
        "brightness": 90,
        "zones": ["FF0000", "FF0000", "FF0000", "FF0000"],
        "gradient": "",
    },
    "赛博青": {
        "mode": "static",
        "speed": 5,
        "brightness": 90,
        "zones": ["00FFFF", "FF00FF", "00FFFF", "FF00FF"],
        "gradient": "",
    },
    "彩虹循环": {
        "mode": "rainbow",
        "speed": 5,
        "brightness": 100,
        "zones": ["FF0000", "00FF00", "0000FF", "FFFFFF"],
        "gradient": "",
    },
    "呼吸红光": {
        "mode": "breathing",
        "speed": 4,
        "brightness": 100,
        "zones": ["FF0000", "FF0000", "FF0000", "FF0000"],
        "gradient": "",
    },
    "火焰渐变": {
        "mode": "gradient",
        "speed": 6,
        "brightness": 100,
        "zones": ["FF0000", "FF8000", "FFFF00", "FF4500"],
        "gradient": "0,1,2,3:FF0000,FF8000,FFFF00",
    },
    "极光": {
        "mode": "aurora",
        "speed": 3,
        "brightness": 90,
        "zones": ["00FFAA", "00AAFF", "00FFAA", "00AAFF"],
        "gradient": "",
    },
}


def _load_raw():
    try:
        with open(PRESET_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def load():
    """Return all presets: built-ins merged with user presets."""
    presets = dict(BUILTIN_PRESETS)
    presets.update(_load_raw())
    return presets


def _save_raw(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = PRESET_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, PRESET_FILE)


def save(name, state):
    name = str(name).strip()
    if not NAME_RE.match(name):
        raise ValueError("预设名只能包含字母、数字、中文、空格和 -，长度 1-40")
    data = _load_raw()
    data[name] = {
        "mode": str(state.get("mode", "static")),
        "speed": int(state.get("speed", 5)),
        "brightness": int(state.get("brightness", 100)),
        "zones": list(state.get("zones", ["FFFFFF"] * 4))[:4],
        "gradient": str(state.get("gradient", "")),
    }
    _save_raw(data)


def delete(name):
    name = str(name).strip()
    data = _load_raw()
    if name in data:
        del data[name]
        _save_raw(data)
        return True
    return False


def get(name):
    presets = load()
    if name not in presets:
        raise KeyError("未找到预设: %s" % name)
    return presets[name]
