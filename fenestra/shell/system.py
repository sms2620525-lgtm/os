"""Thin wrappers around Linux system services used by the shell.

Every function fails soft: when a tool is missing the shell keeps working.
"""

import os
import re
import shutil
import subprocess
import sys

IS_MAC = sys.platform == "darwin"


def _out(cmd, timeout=2) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _bg(cmd):
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


# --- audio ---------------------------------------------------------------
def get_volume() -> tuple:
    """Return (percent, muted)."""
    if IS_MAC:
        out = _out(["osascript", "-e", "get volume settings"])
        m = re.search(r"output volume:(\d+).*output muted:(true|false)", out)
        if m:
            return int(m.group(1)), m.group(2) == "true"
    if shutil.which("pactl"):
        out = _out(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        m = re.search(r"(\d+)%", out)
        mute = "yes" in _out(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        if m:
            return int(m.group(1)), mute
    if shutil.which("amixer"):
        out = _out(["amixer", "get", "Master"])
        m = re.search(r"\[(\d+)%\].*\[(on|off)\]", out)
        if m:
            return int(m.group(1)), m.group(2) == "off"
    return 50, False


def set_volume(pct: int):
    pct = max(0, min(100, int(pct)))
    if IS_MAC:
        _bg(["osascript", "-e", f"set volume output volume {pct}"])
    elif shutil.which("pactl"):
        _bg(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"])
    elif shutil.which("amixer"):
        _bg(["amixer", "-q", "set", "Master", f"{pct}%"])


def toggle_mute():
    if shutil.which("pactl"):
        _bg(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
    elif shutil.which("amixer"):
        _bg(["amixer", "-q", "set", "Master", "toggle"])


# --- display brightness / night light -------------------------------------
def get_brightness() -> int | None:
    if shutil.which("brightnessctl"):
        cur, mx = _out(["brightnessctl", "g"]).strip(), _out(["brightnessctl", "m"]).strip()
        if cur.isdigit() and mx.isdigit() and int(mx):
            return round(int(cur) * 100 / int(mx))
    return None


def set_brightness(pct: int):
    if shutil.which("brightnessctl"):
        _bg(["brightnessctl", "-q", "s", f"{max(1, int(pct))}%"])
    elif shutil.which("xrandr"):
        out = _out(["xrandr", "--query"])
        m = re.search(r"^(\S+) connected", out, re.M)
        if m:
            _bg(["xrandr", "--output", m.group(1), "--brightness", f"{max(0.1, pct / 100):.2f}"])


def set_night_light(on: bool):
    if shutil.which("redshift"):
        _bg(["redshift", "-P", "-O", "4000"] if on else ["redshift", "-x"])
    elif shutil.which("xsct"):
        _bg(["xsct", "4000"] if on else ["xsct"])


# --- network / bluetooth ----------------------------------------------------
def wifi_state() -> tuple:
    """(enabled, connected_ssid or '')"""
    if not shutil.which("nmcli"):
        return False, ""
    enabled = "enabled" in _out(["nmcli", "radio", "wifi"])
    ssid = ""
    for line in _out(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"]).splitlines():
        if line.startswith("yes:"):
            ssid = line[4:]
    if not ssid:
        for line in _out(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "dev"]).splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "connected" and parts[0] in ("ethernet", "wifi"):
                ssid = parts[2]
    return enabled, ssid


def set_wifi(on: bool):
    _bg(["nmcli", "radio", "wifi", "on" if on else "off"])


def wifi_networks() -> list:
    out = _out(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"], timeout=6)
    nets = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[1]:
            nets.append({"active": parts[0] == "*", "ssid": parts[1], "signal": int(parts[2] or 0), "secure": bool(parts[3])})
    return nets


def connect_wifi(ssid: str, password: str | None = None):
    cmd = ["nmcli", "dev", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    _bg(cmd)


def bluetooth_state() -> bool:
    if not shutil.which("bluetoothctl"):
        return False
    return "Powered: yes" in _out(["bluetoothctl", "show"])


def set_bluetooth(on: bool):
    _bg(["bluetoothctl", "power", "on" if on else "off"])


def airplane(on: bool):
    if shutil.which("rfkill"):
        _bg(["rfkill", "block" if on else "unblock", "all"])


# --- power ---------------------------------------------------------------
def battery() -> tuple | None:
    try:
        import psutil
        b = psutil.sensors_battery()
    except Exception:  # noqa: BLE001
        b = None
    if b is None:
        return None
    return int(b.percent), bool(b.power_plugged)


def power(action: str):
    if IS_MAC:
        scripts = {"lock": 'tell application "System Events" to keystroke "q" using {control down, command down}',
                   "sleep": 'tell application "System Events" to sleep',
                   "restart": 'tell application "System Events" to restart',
                   "shutdown": 'tell application "System Events" to shut down',
                   "signout": 'tell application "System Events" to log out'}
        if action in scripts:
            _bg(["osascript", "-e", scripts[action]])
        return
    cmds = {
        "lock": [["loginctl", "lock-session"], ["light-locker-command", "-l"], ["xdg-screensaver", "lock"]],
        "sleep": [["systemctl", "suspend"]],
        "hibernate": [["systemctl", "hibernate"]],
        "restart": [["systemctl", "reboot"]],
        "shutdown": [["systemctl", "poweroff"]],
        "signout": [["openbox", "--exit"], ["loginctl", "terminate-session", os.environ.get("XDG_SESSION_ID", "")]],
    }
    for cmd in cmds.get(action, []):
        if shutil.which(cmd[0]):
            _bg(cmd)
            return


def open_settings(page: str = ""):
    import sys
    _bg([sys.executable, "-m", "fenestra.settings"] + (["--page", page] if page else []))


def screenshot():
    for cmd in (["flameshot", "gui"], ["xfce4-screenshooter", "-r"], ["gnome-screenshot", "-a"], ["scrot", "-s"]):
        if shutil.which(cmd[0]):
            _bg(cmd)
            return
