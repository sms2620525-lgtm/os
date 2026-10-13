"""Minimal EWMH helpers (window list, activation, minimise, close).

Uses python-xlib when available and degrades gracefully to ``wmctrl`` or to
no-ops (e.g. on Wayland or in tests) so callers never crash.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass

try:
    from Xlib import X, Xatom, display, protocol  # type: ignore
except Exception:  # noqa: BLE001 - optional dependency
    display = None


@dataclass
class Window:
    wid: int
    title: str
    wm_class: str
    pid: int
    desktop: int = 0
    minimized: bool = False
    active: bool = False


class WindowManager:
    def __init__(self):
        self.d = None
        if display is not None and os.environ.get("DISPLAY"):
            try:
                self.d = display.Display()
                self.root = self.d.screen().root
                self._atoms = {}
            except Exception:  # noqa: BLE001
                self.d = None

    @property
    def available(self) -> bool:
        return self.d is not None or bool(shutil.which("wmctrl"))

    def atom(self, name):
        if name not in self._atoms:
            self._atoms[name] = self.d.intern_atom(name)
        return self._atoms[name]

    def _prop(self, win, name, kind=None):
        try:
            p = win.get_full_property(self.atom(name), kind if kind is not None else X.AnyPropertyType)
            return p.value if p else None
        except Exception:  # noqa: BLE001
            return None

    def windows(self) -> list:
        if self.d is None:
            return self._wmctrl_windows()
        ids = self._prop(self.root, "_NET_CLIENT_LIST") or []
        active = self._prop(self.root, "_NET_ACTIVE_WINDOW")
        active = active[0] if active is not None and len(active) else 0
        skip = {self.atom("_NET_WM_WINDOW_TYPE_DOCK"), self.atom("_NET_WM_WINDOW_TYPE_DESKTOP"),
                self.atom("_NET_WM_WINDOW_TYPE_SPLASH"), self.atom("_NET_WM_WINDOW_TYPE_TOOLBAR"),
                self.atom("_NET_WM_WINDOW_TYPE_MENU")}
        result = []
        for wid in ids:
            try:
                w = self.d.create_resource_object("window", wid)
                types = set(self._prop(w, "_NET_WM_WINDOW_TYPE") or [])
                state = set(self._prop(w, "_NET_WM_STATE") or [])
                if types & skip or self.atom("_NET_WM_STATE_SKIP_TASKBAR") in state:
                    continue
                title = self._prop(w, "_NET_WM_NAME")
                title = title.decode("utf-8", "replace") if isinstance(title, bytes) else (w.get_wm_name() or "")
                cls = w.get_wm_class() or ("", "")
                pid = self._prop(w, "_NET_WM_PID")
                result.append(Window(wid, str(title), cls[-1] if cls else "", int(pid[0]) if pid is not None and len(pid) else 0,
                                     minimized=self.atom("_NET_WM_STATE_HIDDEN") in state, active=(wid == active)))
            except Exception:  # noqa: BLE001 - window may vanish mid-query
                continue
        return result

    def _wmctrl_windows(self):
        if not shutil.which("wmctrl"):
            return []
        try:
            out = subprocess.run(["wmctrl", "-lpx"], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        res = []
        for line in out.splitlines():
            parts = line.split(None, 5)
            if len(parts) >= 5 and parts[1] != "-1":
                res.append(Window(int(parts[0], 16), parts[5] if len(parts) > 5 else "", parts[3].split(".")[-1], int(parts[2])))
        return res

    def _send(self, wid, name, data):
        w = self.d.create_resource_object("window", wid)
        ev = protocol.event.ClientMessage(window=w, client_type=self.atom(name), data=(32, (data + [0] * 5)[:5]))
        self.root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        self.d.flush()

    def activate(self, wid):
        if self.d is None:
            shutil.which("wmctrl") and subprocess.call(["wmctrl", "-ia", hex(wid)])
            return
        self._send(wid, "_NET_ACTIVE_WINDOW", [2, X.CurrentTime, 0])

    def minimize(self, wid):
        if self.d is None:
            return
        w = self.d.create_resource_object("window", wid)
        ev = protocol.event.ClientMessage(window=w, client_type=self.atom("WM_CHANGE_STATE"), data=(32, [3, 0, 0, 0, 0]))
        self.root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        self.d.flush()

    def close(self, wid):
        if self.d is None:
            shutil.which("wmctrl") and subprocess.call(["wmctrl", "-ic", hex(wid)])
            return
        self._send(wid, "_NET_CLOSE_WINDOW", [X.CurrentTime, 2])

    def toggle_maximize(self, wid):
        if self.d is None:
            return
        self._send(wid, "_NET_WM_STATE", [2, self.atom("_NET_WM_STATE_MAXIMIZED_VERT"),
                                          self.atom("_NET_WM_STATE_MAXIMIZED_HORZ"), 1])

    def show_desktop(self, on=True):
        if self.d is None:
            shutil.which("wmctrl") and subprocess.call(["wmctrl", "-k", "on" if on else "off"])
            return
        self._send(self.root.id, "_NET_SHOWING_DESKTOP", [1 if on else 0])

    def set_type(self, wid, kind="DOCK", states=()):
        """Set _NET_WM_WINDOW_TYPE (DOCK, DESKTOP, NOTIFICATION...) and states."""
        if self.d is None:
            return
        w = self.d.create_resource_object("window", wid)
        w.change_property(self.atom("_NET_WM_WINDOW_TYPE"), Xatom.ATOM, 32, [self.atom(f"_NET_WM_WINDOW_TYPE_{kind}")])
        if states:
            w.change_property(self.atom("_NET_WM_STATE"), Xatom.ATOM, 32,
                              [self.atom(f"_NET_WM_STATE_{s}") for s in states])
        self.d.flush()

    def icon(self, wid, want=32):
        """Return the window's _NET_WM_ICON as a QImage (or None)."""
        if self.d is None:
            return None
        try:
            w = self.d.create_resource_object("window", wid)
            data = self._prop(w, "_NET_WM_ICON")
        except Exception:  # noqa: BLE001
            return None
        if data is None or len(data) < 3:
            return None
        best, i = None, 0
        data = list(data)
        while i + 2 < len(data):
            iw, ih = data[i], data[i + 1]
            if iw <= 0 or ih <= 0 or i + 2 + iw * ih > len(data):
                break
            if best is None or abs(iw - want) < abs(best[0] - want) or (best[0] < want <= iw):
                best = (iw, ih, i + 2)
            i += 2 + iw * ih
        if best is None:
            return None
        import struct
        from PyQt6.QtGui import QImage
        iw, ih, off = best
        raw = struct.pack(f"<{iw * ih}I", *[v & 0xFFFFFFFF for v in data[off:off + iw * ih]])
        return QImage(raw, iw, ih, QImage.Format.Format_ARGB32).copy()

    def active_window(self) -> int:
        if self.d is None:
            return 0
        v = self._prop(self.root, "_NET_ACTIVE_WINDOW")
        return int(v[0]) if v is not None and len(v) else 0

    def set_strut(self, wid, bottom, width, height):
        """Reserve space at the bottom of the screen for the taskbar."""
        if self.d is None:
            return
        w = self.d.create_resource_object("window", wid)
        w.change_property(self.atom("_NET_WM_STRUT"), Xatom.CARDINAL, 32, [0, 0, 0, bottom])
        w.change_property(self.atom("_NET_WM_STRUT_PARTIAL"), Xatom.CARDINAL, 32,
                          [0, 0, 0, bottom, 0, 0, 0, 0, 0, 0, 0, width])
        self.d.flush()


_wm = None


def wm() -> WindowManager:
    global _wm
    if _wm is None:
        _wm = WindowManager()
    return _wm
