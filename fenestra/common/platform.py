"""Host platform abstraction (Linux x86-64, Linux ARM64 / Apple Silicon, macOS).

Everything that differs between hosts goes through here: opening files and
URLs, the terminal, CPU architecture and where per-user data lives.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
MACHINE = platform.machine().lower()
IS_ARM64 = MACHINE in ("arm64", "aarch64")
IS_X86_64 = MACHINE in ("x86_64", "amd64")


def is_apple_silicon() -> bool:
    """True on M1/M2/M3 Macs, and on Linux running on Apple Silicon (Asahi or a VM)."""
    if IS_MAC:
        return IS_ARM64
    if not IS_ARM64:
        return False
    for f in ("/proc/device-tree/compatible", "/sys/firmware/devicetree/base/compatible"):
        try:
            if b"apple," in Path(f).read_bytes():
                return True
        except OSError:
            pass
    try:
        # UTM / Apple Virtualization.framework guests
        vendor = Path("/sys/class/dmi/id/sys_vendor").read_text().strip().lower()
        return "apple" in vendor or "utm" in vendor
    except OSError:
        return False


def is_asahi() -> bool:
    try:
        return "asahi" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def page_size() -> int:
    try:
        return os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return 4096


def host_description() -> str:
    if IS_MAC:
        chip = _sysctl("machdep.cpu.brand_string") or ("Apple Silicon" if IS_ARM64 else "Intel")
        return f"macOS {platform.mac_ver()[0]} on {chip}"
    desc = f"Linux {platform.release()} on {MACHINE}"
    if is_asahi():
        desc += " (Asahi Linux, Apple Silicon)"
    elif is_apple_silicon():
        desc += " (Apple Silicon VM)"
    return desc


def _sysctl(name: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def data_home() -> Path:
    if IS_MAC and not os.environ.get("XDG_DATA_HOME"):
        return Path.home() / "Library" / "Application Support" / "Fenestra"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def _popen(argv, cwd=None):
    try:
        return subprocess.Popen(argv, cwd=cwd, start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def open_path(target: str):
    """Open a file, folder or URL with the default application."""
    return _popen(["open" if IS_MAC else "xdg-open", str(target)])


def terminal_command(cwd: str | None = None, command: str | None = None) -> list:
    if IS_MAC:
        if command:
            script = f'tell application "Terminal" to do script "{command}"'
        else:
            script = f'tell application "Terminal" to do script "cd {cwd or Path.home()}"'
        return ["osascript", "-e", script, "-e", 'tell application "Terminal" to activate']
    for t in ("x-terminal-emulator", "qterminal", "xfce4-terminal", "gnome-terminal", "konsole", "xterm"):
        if shutil.which(t):
            return [t, "-e", command] if command else [t]
    return ["xterm"] + (["-e", command] if command else [])


def open_terminal(cwd: str | None = None, command: str | None = None):
    return _popen(terminal_command(cwd, command), cwd=cwd if cwd and os.path.isdir(cwd) else None)
