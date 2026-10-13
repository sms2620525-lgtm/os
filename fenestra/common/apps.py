"""Application registry: built-in Fenestra apps plus XDG .desktop entries."""

import configparser
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class App:
    id: str
    name: str
    icon: str                 # Fenestra icon name or XDG icon name
    command: list = field(default_factory=list)
    builtin_icon: bool = True
    keywords: str = ""

    def launch(self, *args):
        cmd = list(self.command) + list(args)
        if not cmd:
            return None
        try:
            return subprocess.Popen(cmd, start_new_session=True,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return None


def _first(*candidates):
    """Return the first command (list) whose binary exists."""
    for cand in candidates:
        argv = shlex.split(cand)
        if shutil.which(argv[0]):
            return argv
    return shlex.split(candidates[-1])


def _py(module):
    return [sys.executable, "-m", module]


def builtin_apps() -> dict:
    apps = [
        App("explorer", "File Explorer", "explorer", _py("fenestra.explorer"), keywords="files folder 파일 탐색기"),
        App("settings", "Settings", "settings", _py("fenestra.settings"), keywords="control panel 설정"),
        App("taskmgr", "Task Manager", "taskmgr", _py("fenestra.taskmgr"), keywords="process cpu 작업 관리자"),
        App("compat", "Windows App Converter", "compat", _py("fenestra.compat"), keywords="exe wine msi 변환"),
        App("terminal", "Terminal", "terminal",
            _first("qterminal", "xfce4-terminal", "gnome-terminal", "konsole", "x-terminal-emulator", "xterm"),
            keywords="cmd powershell shell 터미널"),
        App("browser", "Browser", "browser",
            _first("firefox-esr", "firefox", "chromium", "google-chrome", "xdg-open https://"),
            keywords="web internet edge 브라우저"),
        App("store", "Store", "store", _first("gnome-software", "plasma-discover", "synaptic-pkexec", "gnome-software"),
            keywords="install apps 스토어"),
        App("text-editor", "Notepad", "text-editor", _first("mousepad", "gedit", "gnome-text-editor", "kate", "featherpad", "mousepad"),
            keywords="text 메모장"),
        App("calculator", "Calculator", "calculator", _first("gnome-calculator", "galculator", "kcalc", "qalculate-gtk", "gnome-calculator"),
            keywords="math 계산기"),
        App("photos", "Photos", "photos", _first("eog", "ristretto", "gwenview", "gthumb", "eog"), keywords="image 사진"),
        App("music", "Media Player", "music", _first("vlc", "celluloid", "totem", "parole", "vlc"), keywords="video audio 미디어"),
        App("control", "Control Panel", "control", _py("fenestra.settings") + ["--page", "system"], keywords="제어판"),
    ]
    if sys.platform == "darwin":
        mac = {"terminal": "Terminal", "browser": "Safari", "store": "App Store", "text-editor": "TextEdit",
               "calculator": "Calculator", "photos": "Photos", "music": "Music"}
        for a in apps:
            if a.id in mac:
                a.command = ["open", "-a", mac[a.id]]
    return {a.id: a for a in apps}


DESKTOP_DIRS = [
    Path.home() / ".local/share/applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
]


def _clean_exec(exec_line: str) -> list:
    try:
        argv = shlex.split(exec_line)
    except ValueError:
        return []
    return [a for a in argv if not (len(a) == 2 and a.startswith("%"))]


def desktop_apps() -> list:
    """Parse installed .desktop files (visible, application type)."""
    seen, result = set(), []
    lang = (os.environ.get("LANG") or "en").split(".")[0]
    for d in DESKTOP_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.desktop")):
            if f.name in seen:
                continue
            seen.add(f.name)
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            cp.optionxform = str
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("Type") != "Application" or e.get("NoDisplay") == "true" or e.get("Hidden") == "true":
                continue
            if "fenestra" in f.name:
                continue
            name = e.get(f"Name[{lang}]") or e.get(f"Name[{lang[:2]}]") or e.get("Name", f.stem)
            result.append(App(f.stem, name, e.get("Icon", "application-x-executable"),
                              _clean_exec(e.get("Exec", "")), builtin_icon=False,
                              keywords=e.get("Keywords", "") + " " + e.get("GenericName", "")))
    return sorted(result, key=lambda a: a.name.lower())


def all_apps() -> list:
    builtins = list(builtin_apps().values())
    return sorted(builtins + desktop_apps(), key=lambda a: a.name.lower())


def app_icon(app: App, color: str = "#1b1b1b"):
    from PyQt6.QtGui import QIcon
    from . import icons
    if app.builtin_icon:
        return icons.icon(app.icon, color)
    if os.path.isabs(app.icon) and os.path.exists(app.icon):
        return QIcon(app.icon)
    ic = QIcon.fromTheme(app.icon)
    return ic if not ic.isNull() else icons.icon("file-exe")
