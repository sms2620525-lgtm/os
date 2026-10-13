"""System data collection for Task Manager (psutil + /proc + systemd)."""

import configparser
import os
import platform
import pwd
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass
class ProcInfo:
    pid: int
    name: str
    exe: str
    user: str
    status: str
    cpu: float          # percent of total machine
    mem: int            # bytes (USS-ish: rss - shared)
    disk: float         # bytes/s
    net: float          # bytes/s (not available per process without root -> 0)
    threads: int
    ppid: int
    cmdline: str
    cpu_time: float
    create_time: float
    is_app: bool = False
    window_title: str = ""
    efficiency: bool = False


class Sampler:
    """Keeps psutil.Process objects alive so cpu_percent() deltas work."""

    def __init__(self):
        self.procs = {}
        self.io_prev = {}
        self.ncpu = psutil.cpu_count() or 1
        self.last = time.monotonic()
        psutil.cpu_percent(percpu=True)
        self.disk_prev = psutil.disk_io_counters(perdisk=True) or {}
        self.net_prev = psutil.net_io_counters(pernic=True) or {}
        self.net_time = time.monotonic()

    def processes(self, app_pids=None, titles=None) -> list:
        app_pids = app_pids or set()
        titles = titles or {}
        now = time.monotonic()
        dt = max(0.001, now - self.last)
        self.last = now
        result, alive = [], set()
        for proc in psutil.process_iter():
            pid = proc.pid
            alive.add(pid)
            p = self.procs.get(pid)
            if p is None:
                self.procs[pid] = p = proc
                try:
                    p.cpu_percent(None)
                except psutil.Error:
                    pass
            try:
                with p.oneshot():
                    name = p.name()
                    cpu = p.cpu_percent(None) / self.ncpu
                    mi = p.memory_info()
                    mem = max(0, mi.rss - getattr(mi, "shared", 0))
                    status = p.status()
                    try:
                        user = p.username()
                    except (KeyError, psutil.Error):
                        user = "?"
                    try:
                        io = p.io_counters()
                        total = io.read_bytes + io.write_bytes
                        prev = self.io_prev.get(pid, total)
                        self.io_prev[pid] = total
                        disk = max(0, total - prev) / dt
                    except (psutil.AccessDenied, AttributeError, psutil.Error):
                        disk = 0.0
                    try:
                        exe = p.exe()
                    except psutil.Error:
                        exe = ""
                    try:
                        cmd = " ".join(p.cmdline())
                    except psutil.Error:
                        cmd = ""
                    ct = p.cpu_times()
                    try:
                        nice = p.nice()
                    except psutil.Error:
                        nice = 0
                    result.append(ProcInfo(pid, name, exe, user, status, cpu, mem, disk, 0.0, p.num_threads(),
                                           p.ppid(), cmd, ct.user + ct.system, p.create_time(),
                                           pid in app_pids, titles.get(pid, ""), nice >= 19))
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except psutil.AccessDenied:
                continue
        for dead in set(self.procs) - alive:
            self.procs.pop(dead, None)
            self.io_prev.pop(dead, None)
        return result

    # --- performance -----------------------------------------------------
    def cpu(self):
        per = psutil.cpu_percent(percpu=True)
        freq = cpu_freq()
        return sum(per) / max(1, len(per)), per, freq.current if freq else 0.0

    def memory(self):
        return psutil.virtual_memory(), psutil.swap_memory()

    def disks(self):
        now = psutil.disk_io_counters(perdisk=True) or {}
        out = {}
        for name, c in now.items():
            if name.startswith(("loop", "ram", "zram", "dm-", "sr")):
                continue
            if re.match(r"^(sd|vd|hd|xvd)[a-z]+\d+$", name) or re.match(r"^(nvme\d+n\d+|mmcblk\d+)p\d+$", name):
                continue  # partition of a whole disk (sda1, nvme0n1p2)
            prev = self.disk_prev.get(name, c)
            busy = getattr(c, "busy_time", 0) - getattr(prev, "busy_time", 0)
            out[name] = {
                "read": c.read_bytes - prev.read_bytes,
                "write": c.write_bytes - prev.write_bytes,
                "active": min(100.0, busy / 10.0),  # busy ms per 1000ms -> %
            }
        self.disk_prev = now
        return out

    def network(self):
        now = psutil.net_io_counters(pernic=True) or {}
        t = time.monotonic()
        dt = max(0.001, t - self.net_time)
        self.net_time = t
        stats = psutil.net_if_stats()
        out = {}
        for nic, c in now.items():
            if nic == "lo" or nic.startswith(("veth", "docker", "br-", "virbr")):
                continue
            st = stats.get(nic)
            if st and not st.isup:
                continue
            prev = self.net_prev.get(nic, c)
            out[nic] = {"sent": (c.bytes_sent - prev.bytes_sent) / dt, "recv": (c.bytes_recv - prev.bytes_recv) / dt,
                        "speed": st.speed if st else 0}
        self.net_prev = now
        return out


def cpu_freq():
    """psutil.cpu_freq() can be missing or raise on Apple Silicon and some ARM boards."""
    try:
        return psutil.cpu_freq()
    except (OSError, NotImplementedError, AttributeError, RuntimeError):
        return None


def cpu_model() -> str:
    if sys.platform == "darwin":
        try:
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                  text=True, timeout=2).stdout.strip() or "Apple Silicon"
        except OSError:
            return "Apple Silicon"
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def gpu_info() -> list:
    """Return [(name, busy_percent or None)] for DRM GPUs."""
    gpus = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
        dev = card / "device"
        name = "GPU"
        try:
            vendor = (dev / "vendor").read_text().strip()
            name = {"0x8086": "Intel Graphics", "0x1002": "AMD Radeon", "0x10de": "NVIDIA GPU"}.get(vendor, "GPU")
        except OSError:
            pass
        busy = None
        try:
            busy = float((dev / "gpu_busy_percent").read_text())
        except (OSError, ValueError):
            pass
        gpus.append((f"{name} ({card.name})", busy))
    return gpus


def uptime() -> str:
    s = int(time.time() - psutil.boot_time())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}:{h:02d}:{m:02d}:{s:02d}"


def counts():
    n_proc, n_thr, n_fd = 0, 0, 0
    for p in psutil.process_iter(["num_threads", "num_fds"]):
        n_proc += 1
        n_thr += p.info.get("num_threads") or 0
        n_fd += p.info.get("num_fds") or 0
    return n_proc, n_thr, n_fd


# --- startup apps ---------------------------------------------------------

AUTOSTART_DIRS = [Path("/etc/xdg/autostart"), Path.home() / ".config/autostart"]


@dataclass
class StartupApp:
    file: str
    name: str
    publisher: str
    enabled: bool
    command: str


def startup_apps() -> list:
    entries = {}
    for d in AUTOSTART_DIRS:
        if not d.is_dir():
            continue
        for f in d.glob("*.desktop"):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            cp.optionxform = str
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            enabled = e.get("Hidden", "false") != "true" and e.get("X-GNOME-Autostart-enabled", "true") != "false"
            entries[f.name] = StartupApp(str(f), e.get("Name", f.stem), e.get("X-Publisher", e.get("Comment", "")),
                                         enabled, e.get("Exec", ""))
    return sorted(entries.values(), key=lambda a: a.name.lower())


def set_startup_enabled(app: StartupApp, enabled: bool) -> None:
    """Write a per-user override (like Windows' StartupApproved key)."""
    user_dir = Path.home() / ".config/autostart"
    user_dir.mkdir(parents=True, exist_ok=True)
    target = user_dir / Path(app.file).name
    if Path(app.file) != target:
        shutil.copy(app.file, target)
    lines = [l for l in target.read_text(encoding="utf-8").splitlines() if not l.startswith(("Hidden=", "X-GNOME-Autostart-enabled="))]
    out, inserted = [], False
    for l in lines:
        out.append(l)
        if l.strip() == "[Desktop Entry]" and not inserted:
            out.append(f"Hidden={'false' if enabled else 'true'}")
            out.append(f"X-GNOME-Autostart-enabled={'true' if enabled else 'false'}")
            inserted = True
    target.write_text("\n".join(out) + "\n", encoding="utf-8")


# --- services ---------------------------------------------------------------

@dataclass
class Service:
    name: str
    pid: str
    description: str
    status: str
    group: str = ""


def _launchd_services() -> list:
    """macOS: launchd jobs of the current user (launchctl list)."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    result = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3:
            pid, _status, label = parts
            result.append(Service(label, "" if pid == "-" else pid, label.split(".")[-1],
                                  "Running" if pid != "-" else "Stopped"))
    return result


def services() -> list:
    if sys.platform == "darwin":
        return _launchd_services()
    if not shutil.which("systemctl"):
        return []
    try:
        out = subprocess.run(["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain",
                              "--no-legend"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    result = []
    pids = {}
    try:
        show = subprocess.run(["systemctl", "show", "--type=service", "--property=Id,MainPID", "--all"],
                              capture_output=True, text=True, timeout=5).stdout
        cur = None
        for line in show.splitlines():
            if line.startswith("Id="):
                cur = line[3:]
            elif line.startswith("MainPID=") and cur:
                pids[cur] = line[8:]
    except (OSError, subprocess.TimeoutExpired):
        pass
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[:4]
        desc = parts[4] if len(parts) > 4 else ""
        status = "Running" if sub == "running" else ("Stopped" if active in ("inactive", "failed") else sub.capitalize())
        pid = pids.get(unit, "0")
        result.append(Service(unit.removesuffix(".service"), "" if pid == "0" else pid, desc, status))
    return result


def service_action(name: str, action: str) -> int:
    if sys.platform == "darwin":
        verb = {"start": "start", "stop": "stop", "restart": "kickstart"}[action]
        target = name if verb != "kickstart" else f"gui/{os.getuid()}/{name}"
        return subprocess.call(["launchctl", verb] + (["-k"] if verb == "kickstart" else []) + [target])
    cmd = ["systemctl", action, f"{name}.service"]
    if os.geteuid() != 0:
        cmd = (["pkexec"] if shutil.which("pkexec") else ["sudo", "-n"]) + cmd
    try:
        return subprocess.call(cmd)
    except OSError:
        return 1


def users_summary(procs) -> list:
    agg = {}
    for p in procs:
        a = agg.setdefault(p.user, {"cpu": 0.0, "mem": 0, "disk": 0.0, "n": 0})
        a["cpu"] += p.cpu
        a["mem"] += p.mem
        a["disk"] += p.disk
        a["n"] += 1
    sessions = {u.name: u for u in psutil.users()}
    out = []
    for name, a in agg.items():
        try:
            uid = pwd.getpwnam(name).pw_uid
        except KeyError:
            uid = -1
        if uid < 1000 and name not in sessions and name != os.environ.get("USER"):
            continue
        status = "Active" if name in sessions or name == os.environ.get("USER") else "Disconnected"
        out.append((name, status, a))
    return out
