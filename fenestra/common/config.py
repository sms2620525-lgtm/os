"""Persistent user configuration shared by every Fenestra component.

Stored as JSON in ``$XDG_CONFIG_HOME/fenestra/settings.json``.
"""

import json
import os
from pathlib import Path

DEFAULTS = {
    "theme": "light",            # "light" | "dark"
    "accent": "#0067c0",
    "taskbar_alignment": "center",  # "center" | "left"
    "transparency": True,
    "pinned_taskbar": ["explorer", "browser", "terminal", "settings", "store"],
    "pinned_start": [
        "explorer", "settings", "taskmgr", "terminal", "browser", "compat",
        "text-editor", "calculator", "store", "photos", "music", "control",
    ],
    "wallpaper": "",
    "show_seconds": False,
    "night_light": False,
    "volume": 60,
    "brightness": 80,
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    path = Path(base) / "fenestra"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path() -> Path:
    return config_dir() / "settings.json"


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(_path(), encoding="utf-8") as fh:
            data.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return data


def save(data: dict) -> None:
    tmp = _path().with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, _path())


def get(key):
    return load().get(key, DEFAULTS.get(key))


def set(key, value) -> None:  # noqa: A001 - mirrors dict API
    data = load()
    data[key] = value
    save(data)
