"""Run and "convert" Windows programs.

Conversion turns a Windows program into a first-class Linux application:

* a dedicated Wine prefix (bottle) per application, with the Windows
  components the analyser recommended installed through winetricks;
* the installer (NSIS/Inno/MSI...) executed inside that prefix;
* a launcher script in ``~/.local/bin`` and a ``.desktop`` entry with the
  icon extracted from the ``.exe`` so it appears in the Start menu;
* optionally a standalone ``.deb`` package (built in pure Python) that bundles
  the program and depends on Wine, so it can be installed on any Debian/Ubuntu
  based system.
"""

import io
import os
import re
import shlex
import shutil
import stat
import struct
import subprocess
import tarfile
import time
from pathlib import Path

from ..common import platform as hostos
from . import analyzer, batch, hosts, pe

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
FEN_HOME = hostos.data_home() if hostos.IS_MAC else DATA_HOME / "fenestra"
PREFIXES = FEN_HOME / "prefixes"
MAC_APPS_DIR = Path.home() / "Applications"
BIN_DIR = Path.home() / ".local" / "bin"
APPS_DIR = DATA_HOME / "applications"
ICONS_DIR = DATA_HOME / "icons" / "hicolor" / "256x256" / "apps"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "app"


def runtime_for(plan) -> "hosts.Runtime":
    """The way this host executes the plan's binary (Wine, Hangover, FEX, box64, Rosetta 2)."""
    if plan.pe:
        return hosts.find_runtime(plan.pe.machine, plan.pe.bits)
    return hosts.find_runtime("x64", 64)


def env_for(prefix: Path, rt=None, arch64: bool = True) -> dict:
    env = dict(os.environ)
    env["WINEPREFIX"] = str(prefix)
    env.setdefault("WINEARCH", "win64" if arch64 else "win32")
    env.setdefault("WINEDEBUG", "-all")
    env.setdefault("DXVK_LOG_LEVEL", "none")
    if rt is not None:
        env.update(rt.env)
        env["WINE"] = rt.wine          # used by winetricks
    return env


class Log:
    """Collects progress lines; GUI can pass a callback."""

    def __init__(self, cb=None):
        self.cb = cb or (lambda line: print(line, flush=True))

    def __call__(self, msg: str):
        self.cb(msg)


def _run(cmd, env=None, log=None, cwd=None, check=False) -> int:
    log = log or Log()
    log("$ " + " ".join(shlex.quote(str(c)) for c in cmd))
    try:
        proc = subprocess.Popen([str(c) for c in cmd], env=env, cwd=cwd,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as exc:
        log(f"error: {exc}")
        if check:
            raise
        return 127
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
    rc = proc.wait()
    if check and rc:
        raise subprocess.CalledProcessError(rc, cmd)
    return rc


# --- prefixes ---------------------------------------------------------------

def ensure_prefix(name: str, plan: analyzer.Plan, log=None, rt=None) -> Path:
    log = log or Log()
    rt = rt or runtime_for(plan)
    prefix = PREFIXES / slug(name)
    # Modern Wine (WoW64) runs 32-bit programs in a 64-bit prefix; only very old
    # VB6 runtimes still need a pure 32-bit prefix.
    arch64 = "vb6run" not in plan.verbs
    if not (prefix / "system.reg").exists():
        prefix.mkdir(parents=True, exist_ok=True)
        if rt.ok:
            log(f"Creating Wine prefix {prefix} ({rt.name})")
            _run([*rt.argv, "wineboot", "--init"], env=env_for(prefix, rt, arch64), log=log)
        else:
            for n in rt.notes:
                log(n)
    verbs = [v for v in plan.verbs if v not in _installed_verbs(prefix)]
    if verbs and rt.ok and rt.name != "muvm-fex":
        if shutil.which("winetricks"):
            log("Installing Windows components: " + ", ".join(verbs))
            rc = _run(["winetricks", "-q", "--unattended", *verbs], env=env_for(prefix, rt, arch64), log=log)
            if rc == 0:
                with open(prefix / ".fenestra-verbs", "a") as fh:
                    fh.write("\n".join(verbs) + "\n")
        else:
            log("winetricks not found; skipping components " + ", ".join(verbs))
    return prefix


def _installed_verbs(prefix: Path) -> set:
    try:
        return set((prefix / ".fenestra-verbs").read_text().split())
    except OSError:
        return set()


def list_prefixes() -> list:
    if not PREFIXES.is_dir():
        return []
    return sorted(p for p in PREFIXES.iterdir() if p.is_dir())


# --- running ---------------------------------------------------------------

def run(path: str, args=(), log=None, wait=False) -> int:
    """Run any supported Windows file directly."""
    log = log or Log()
    plan = analyzer.analyze(path)
    if plan.runtime == "none":
        for n in plan.notes:
            log(n)
        return 1
    if plan.kind == "batch":
        script = batch.translate(Path(path).read_text(errors="replace"), os.path.basename(path))
        cache = DATA_HOME / "fenestra" / "bat2sh"
        cache.mkdir(parents=True, exist_ok=True)
        sh = cache / (slug(Path(path).stem) + ".sh")
        sh.write_text(script)
        sh.chmod(0o755)
        return _launch(["bash", str(sh), *args], cwd=os.path.dirname(os.path.abspath(path)), wait=wait)
    if plan.kind == "powershell":
        pwsh = shutil.which("pwsh") or "pwsh"
        return _launch([pwsh, "-File", path, *args], wait=wait)
    if plan.kind == "dos":
        return _launch(["dosbox", path], wait=wait)

    rt = runtime_for(plan)
    if not rt.ok:
        for n in rt.notes:
            log(n)
        if rt.install_hint:
            log(f"To fix: {rt.install_hint}")
        return 2
    name = plan.name
    prefix = ensure_prefix(name, plan, log, rt)
    env = env_for(prefix, rt)
    if plan.kind == "registry":
        return _run([*rt.argv, "regedit", path], env=env, log=log)
    if plan.kind == "msi":
        return _run([*rt.argv, "msiexec", "/i", path], env=env, log=log)
    if plan.kind == "shortcut":
        return _launch([*rt.argv, "start", "/unix", path, *args], env=env, wait=wait)
    cmd = [*rt.argv, path, *args]
    # Console programs started from the GUI get a terminal window; with --wait (shell, binfmt)
    # they keep using the caller's stdin/stdout.
    if (plan.pe and plan.pe.subsystem == "console" and not wait and not os.isatty(0) and not hostos.IS_MAC
            and shutil.which(hostos.terminal_command()[0])):
        cmd = hostos.terminal_command(command=" ".join(shlex.quote(c) for c in cmd))
    return _launch(cmd, env=env, cwd=os.path.dirname(os.path.abspath(path)), wait=wait)


def _launch(cmd, env=None, cwd=None, wait=False) -> int:
    try:
        p = subprocess.Popen(cmd, env=env, cwd=cwd, start_new_session=not wait)
    except OSError as exc:
        print(f"fenestra-compat: cannot start {cmd[0]}: {exc}")
        return 127
    return p.wait() if wait else 0


# --- icon extraction ---------------------------------------------------------

def extract_icon(exe: str, dest_png: Path) -> bool:
    try:
        ico = pe.PEFile(exe).icon_ico()
    except (pe.PEError, OSError):
        return False
    if not ico:
        return False
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PyQt6.QtGui import QImage
        img = QImage()
        if img.loadFromData(ico, "ICO") and not img.isNull():
            return img.save(str(dest_png), "PNG")
    except ImportError:
        pass
    # Fallback: keep the .ico (most icon themes / launchers accept it).
    dest_png.with_suffix(".ico").write_bytes(ico)
    return False


# --- launcher / desktop entry -----------------------------------------------

def find_installed_exe(prefix: Path, hint: str = "") -> Path | None:
    """After running an installer, guess the main program it installed."""
    roots = [prefix / "drive_c" / "Program Files", prefix / "drive_c" / "Program Files (x86)",
             prefix / "drive_c" / "users"]
    ignore = re.compile(r"unins|uninstall|setup|update|crash|helper|redist|vcredist|dxsetup|install", re.I)
    candidates = []
    for root in roots:
        if not root.is_dir():
            continue
        for exe in root.rglob("*.exe"):
            if ignore.search(exe.name) or "Common Files" in exe.parts or "Windows" in exe.parts:
                continue
            score = exe.stat().st_size
            if hint and slug(hint).split("-")[0] in slug(exe.stem):
                score *= 10
            if exe.stat().st_mtime > time.time() - 3600:
                score *= 2
            candidates.append((score, exe))
    return max(candidates)[1] if candidates else None


def _launcher_script(name: str, exe: Path, prefix: Path, rt) -> str:
    exports = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in rt.env.items())
    argv = " ".join(shlex.quote(a) for a in rt.argv) or "wine"
    return ("#!/bin/sh\n"
            f"# Fenestra launcher for {name} (runtime: {rt.name})\n"
            f"export WINEPREFIX={shlex.quote(str(prefix))}\n"
            "export WINEDEBUG=-all\n" + exports +
            f"cd {shlex.quote(str(exe.parent))} || exit 1\n"
            f"exec {argv} {shlex.quote(str(exe))} \"$@\"\n")


def write_launcher(name: str, exe: Path, prefix: Path, plan: analyzer.Plan, rt=None) -> tuple:
    rt = rt or runtime_for(plan)
    if rt.argv == []:
        rt = hosts.Runtime("wine", ["wine"])
    if hostos.IS_MAC:
        app = build_app_bundle(name, MAC_APPS_DIR, _launcher_script(name, exe, prefix, rt), exe)
        return app / "Contents" / "MacOS" / "launcher", app
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    s = slug(name)
    launcher = BIN_DIR / f"{s}"
    launcher.write_text(_launcher_script(name, exe, prefix, rt))
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    icon_path = ICONS_DIR / f"fenestra-{s}.png"
    icon = str(icon_path) if extract_icon(str(exe), icon_path) else "wine"
    desktop = APPS_DIR / f"fenestra-app-{s}.desktop"
    terminal = "true" if plan.pe and plan.pe.subsystem == "console" else "false"
    desktop.write_text(
        "[Desktop Entry]\nType=Application\n"
        f"Name={name}\nComment=Windows application (converted by Fenestra)\n"
        f"Exec={launcher} %F\nIcon={icon}\nTerminal={terminal}\n"
        "Categories=Wine;X-Fenestra-Converted;\n"
        f"StartupWMClass={exe.name.lower()}\n")
    return launcher, desktop


def convert(path: str, name: str | None = None, log=None) -> dict:
    """Convert a Windows program/installer into an installed Linux app."""
    log = log or Log()
    plan = analyzer.analyze(path)
    log(plan.summary())
    if plan.kind == "batch":
        out = Path(path).with_suffix(".sh")
        out.write_text(batch.translate(Path(path).read_text(errors="replace"), os.path.basename(path)))
        out.chmod(0o755)
        log(f"Batch file translated to {out}")
        return {"script": str(out)}
    if plan.runtime == "none" or plan.rating == "borked":
        raise RuntimeError("This file cannot be converted: " + "; ".join(plan.notes))
    rt = runtime_for(plan)
    if not rt.ok:
        raise RuntimeError(" ".join(rt.notes) + (f"  Fix: {rt.install_hint}" if rt.install_hint else ""))
    name = name or plan.name
    prefix = ensure_prefix(name, plan, log, rt)
    env = env_for(prefix, rt)
    exe = Path(path).resolve()
    if plan.is_installer:
        log(f"Running installer for {name} ...")
        if plan.kind == "msi":
            _run([*rt.argv, "msiexec", "/i", str(exe)], env=env, log=log)
        else:
            _run([*rt.argv, str(exe)], env=env, log=log, cwd=str(exe.parent))
        installed = find_installed_exe(prefix, name)
        if installed is None:
            raise RuntimeError("Installer finished but no program was found in the prefix.")
        log(f"Detected installed program: {installed}")
        exe = installed
    else:
        # Portable program: copy it into the prefix so the launcher keeps working
        target_dir = prefix / "drive_c" / "Program Files" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        if exe.parent != target_dir:
            for f in exe.parent.iterdir():
                if f.is_file() and (f == exe or f.suffix.lower() in (".dll", ".dat", ".ini", ".pak", ".cfg", ".json")):
                    shutil.copy2(f, target_dir / f.name)
                elif f.is_dir() and len(list(exe.parent.iterdir())) < 200:
                    shutil.copytree(f, target_dir / f.name, dirs_exist_ok=True)
            exe = target_dir / exe.name
    launcher, desktop = write_launcher(name, exe, prefix, plan, rt)
    log(f"Launcher:      {launcher}")
    log(f"Start menu:    {desktop}")
    return {"launcher": str(launcher), "desktop": str(desktop), "prefix": str(prefix), "exe": str(exe)}


# --- .deb packaging (pure Python, no dpkg-deb required) ---------------------

def _ar(members) -> bytes:
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in members:
        hdr = f"{name:<16}{int(time.time()):<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n"
        out.write(hdr.encode())
        out.write(data)
        if len(data) % 2:
            out.write(b"\n")
    return out.getvalue()


def _tar_gz(files) -> bytes:
    """files: list of (arcname, bytes|None for dir, mode)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tf:
        dirs = set()
        for arc, _, _ in files:
            parts = arc.strip("./").split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("./" + "/".join(parts[:i]))
        for d in sorted(dirs):
            ti = tarfile.TarInfo(d)
            ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
            tf.addfile(ti)
        for arc, data, mode in files:
            ti = tarfile.TarInfo(arc)
            ti.size, ti.mode, ti.mtime = len(data), mode, int(time.time())
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def package_deb(path: str, out_dir: str = ".", name: str | None = None, version: str | None = None,
                log=None) -> str:
    """Wrap a portable Windows program into a .deb that depends on Wine.

    The package installs the program under /opt/fenestra-apps/<slug>, a
    launcher in /usr/bin and a desktop entry; on first launch each user gets a
    private Wine prefix in ~/.local/share/fenestra/prefixes/<slug>.
    """
    log = log or Log()
    plan = analyzer.analyze(path)
    if plan.kind not in ("exe", "dotnet"):
        raise RuntimeError(f"Only portable .exe programs can be packaged (got {plan.kind}).")
    name = name or plan.name
    s = slug(name)
    version = version or (plan.pe.version.get("ProductVersion") or plan.pe.version.get("FileVersion") or "1.0")
    version = re.sub(r"[^0-9A-Za-z.+~-]", ".", version.split()[0]).strip(".") or "1.0"
    if not version[0].isdigit():
        version = "0." + version
    exe = Path(path).resolve()
    root = f"./opt/fenestra-apps/{s}"
    files = []
    src_dir = exe.parent
    siblings = [f for f in src_dir.iterdir()] if len(list(src_dir.iterdir())) < 500 else [exe]
    for f in siblings:
        if f.is_file() and (f == exe or f.suffix.lower() in (".dll", ".dat", ".ini", ".pak", ".cfg", ".json", ".xml")):
            files.append((f"{root}/{f.name}", f.read_bytes(), 0o644))
        elif f.is_dir() and f != exe.parent:
            for sub in f.rglob("*"):
                if sub.is_file():
                    files.append((f"{root}/{sub.relative_to(src_dir).as_posix()}", sub.read_bytes(), 0o644))
    wine = "wine64" if plan.pe.bits == 64 else "wine"
    launcher = (
        "#!/bin/sh\n"
        f"export WINEPREFIX=\"${{XDG_DATA_HOME:-$HOME/.local/share}}/fenestra/prefixes/{s}\"\n"
        "export WINEDEBUG=-all\n"
        "if [ ! -f \"$WINEPREFIX/system.reg\" ]; then\n"
        "  mkdir -p \"$WINEPREFIX\" && wineboot --init >/dev/null 2>&1\n"
        + (f"  command -v winetricks >/dev/null && winetricks -q {' '.join(plan.verbs)} >/dev/null 2>&1\n" if plan.verbs else "")
        + "fi\n"
        f"cd /opt/fenestra-apps/{s} || exit 1\n"
        "# ARM64 hosts (Apple Silicon, Raspberry Pi): let Fenestra pick Hangover/FEX/box64\n"
        "if [ \"$(uname -m)\" = aarch64 ] && command -v fenestra-compat >/dev/null; then\n"
        f"  exec fenestra-compat run --wait {shlex.quote(exe.name)} \"$@\"\nfi\n"
        f"if command -v {wine} >/dev/null; then exec {wine} {shlex.quote(exe.name)} \"$@\"; "
        f"else exec wine {shlex.quote(exe.name)} \"$@\"; fi\n")
    files.append((f"./usr/bin/{s}", launcher.encode(), 0o755))
    icon_png = Path(os.environ.get("TMPDIR", "/tmp")) / f"fenestra-{s}-{os.getpid()}.png"
    icon_name = "wine"
    if extract_icon(str(exe), icon_png) and icon_png.exists():
        files.append((f"./usr/share/icons/hicolor/256x256/apps/{s}.png", icon_png.read_bytes(), 0o644))
        icon_name = s
        icon_png.unlink()
    terminal = "true" if plan.pe.subsystem == "console" else "false"
    files.append((f"./usr/share/applications/{s}.desktop", (
        "[Desktop Entry]\nType=Application\n"
        f"Name={name}\nExec=/usr/bin/{s} %F\nIcon={icon_name}\nTerminal={terminal}\n"
        "Categories=Wine;X-Fenestra-Converted;\n").encode(), 0o644))
    installed_kb = sum(len(d) for _, d, _ in files) // 1024 + 1
    company = plan.pe.version.get("CompanyName", "Unknown").replace("\n", " ")
    arch_dep = "wine64 | wine (>= 6.0)" if plan.pe.bits == 64 else "wine (>= 6.0)"
    recommends = "winetricks"
    control = (
        f"Package: {s}\nVersion: {version}\nSection: otherosfs\nPriority: optional\n"
        f"Architecture: all\nDepends: {arch_dep}\nRecommends: {recommends}\n"
        f"Installed-Size: {installed_kb}\nMaintainer: Fenestra Converter <noreply@fenestra.local>\n"
        f"Description: {name} (Windows application)\n"
        f" Windows program by {company}, packaged for Linux by the Fenestra\n"
        f" Windows App Converter. It runs through the Wine compatibility layer.\n")
    control_tar = _tar_gz([("./control", control.encode(), 0o644)])
    data_tar = _tar_gz(files)
    deb = _ar([("debian-binary", b"2.0\n"), ("control.tar.gz", control_tar), ("data.tar.gz", data_tar)])
    out = Path(out_dir) / f"{s}_{version}_all.deb"
    out.write_bytes(deb)
    log(f"Built {out} ({len(deb) // 1024} KiB)")
    return str(out)


# --- binfmt / MIME integration ---------------------------------------------

def register_desktop_integration(log=None) -> None:
    """Make .exe/.msi/.bat files open with fenestra-compat (per user)."""
    log = log or Log()
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    entry = APPS_DIR / "fenestra-compat-run.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Run Windows program\n"
        "Exec=fenestra-compat run %f\nIcon=wine\nNoDisplay=true\n"
        "MimeType=application/x-ms-dos-executable;application/x-msdownload;application/x-msi;"
        "application/x-ms-shortcut;application/x-bat;text/x-ms-regedit;application/x-wine-extension-msp;\n")
    if shutil.which("xdg-mime"):
        for mt in ("application/x-ms-dos-executable", "application/x-msdownload", "application/x-msi",
                   "application/x-bat"):
            _run(["xdg-mime", "default", entry.name, mt], log=log)
    log(f"Registered {entry}")


# --- macOS .app bundles -------------------------------------------------------

def _png_bytes(img, size) -> bytes:
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    scaled = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    scaled.save(buf, "PNG")
    return bytes(ba)


def make_icns(png_by_size: dict) -> bytes:
    """Build an Apple .icns file from PNG data ({128: b'..', 256: .., 512: .., 1024: ..})."""
    types = {16: b"icp4", 32: b"icp5", 64: b"icp6", 128: b"ic07", 256: b"ic08", 512: b"ic09", 1024: b"ic10"}
    body = b""
    for size, data in sorted(png_by_size.items()):
        if size in types:
            body += types[size] + struct.pack(">I", len(data) + 8) + data
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def exe_icns(exe) -> bytes | None:
    try:
        ico = pe.PEFile(str(exe)).icon_ico()
        from PyQt6.QtGui import QImage
    except (pe.PEError, OSError, ImportError):
        return None
    if not ico:
        return None
    img = QImage()
    if not img.loadFromData(ico, "ICO") or img.isNull():
        return None
    return make_icns({s: _png_bytes(img, s) for s in (32, 128, 256, 512)})


def build_app_bundle(name: str, dest_dir, launcher_script: str, exe=None, resources=None) -> Path:
    """Create <dest_dir>/<name>.app whose executable is ``launcher_script``.

    resources: optional {relative_path: source Path} copied into Contents/Resources/app.
    """
    app = Path(dest_dir) / f"{name}.app"
    macos = app / "Contents" / "MacOS"
    res = app / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    for rel, src in (resources or {}).items():
        target = res / "app" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    launcher = macos / "launcher"
    launcher.write_text(launcher_script)
    launcher.chmod(0o755)
    icon_line = ""
    icns = exe_icns(exe) if exe else None
    if icns:
        (res / "AppIcon.icns").write_bytes(icns)
        icon_line = "  <key>CFBundleIconFile</key><string>AppIcon</string>\n"
    ident = "org.fenestra.converted." + slug(name)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"  <key>CFBundleName</key><string>{_xml(name)}</string>\n"
        f"  <key>CFBundleDisplayName</key><string>{_xml(name)}</string>\n"
        f"  <key>CFBundleIdentifier</key><string>{ident}</string>\n"
        "  <key>CFBundleExecutable</key><string>launcher</string>\n"
        "  <key>CFBundlePackageType</key><string>APPL</string>\n"
        "  <key>CFBundleVersion</key><string>1.0</string>\n"
        "  <key>LSMinimumSystemVersion</key><string>11.0</string>\n"
        "  <key>NSHighResolutionCapable</key><true/>\n"
        + icon_line +
        "</dict>\n</plist>\n")
    return app


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


MAC_LAUNCHER = r'''#!/bin/sh
# Windows program packaged as a macOS app by Fenestra.
HERE="$(cd "$(dirname "$0")/../Resources/app" && pwd)"
export WINEPREFIX="$HOME/Library/Application Support/Fenestra/prefixes/{slug}"
export WINEDEBUG=-all
WINE=""
for w in /opt/homebrew/bin/wine64 /opt/homebrew/bin/wine /usr/local/bin/wine64 /usr/local/bin/wine \
         "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine64" \
         "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine" \
         "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine"; do
    [ -x "$w" ] && WINE="$w" && break
done
if [ -z "$WINE" ]; then
    osascript -e 'display dialog "{name} needs Wine to run.\n\nInstall it with Homebrew:\nbrew install --cask --no-quarantine wine-stable" buttons {{"OK"}} with icon caution'
    exit 1
fi
if [ "$(uname -m)" = arm64 ] && ! arch -x86_64 /usr/bin/true 2>/dev/null; then
    osascript -e 'display dialog "Rosetta 2 is required. Run in Terminal:\nsoftwareupdate --install-rosetta --agree-to-license" buttons {{"OK"}} with icon caution'
    exit 1
fi
if [ ! -f "$WINEPREFIX/system.reg" ]; then
    mkdir -p "$WINEPREFIX" && "$WINE" wineboot --init >/dev/null 2>&1
{verbs}fi
cd "$HERE" || exit 1
exec "$WINE" {exe} "$@"
'''


def package_app(path: str, out_dir: str = ".", name: str | None = None, log=None) -> str:
    """Wrap a portable Windows program into a double-clickable macOS .app bundle."""
    log = log or Log()
    plan = analyzer.analyze(path)
    if plan.kind not in ("exe", "dotnet"):
        raise RuntimeError(f"Only portable .exe programs can be packaged (got {plan.kind}).")
    name = name or plan.name
    exe = Path(path).resolve()
    resources = {exe.name: exe}
    for f in exe.parent.iterdir():
        if f.is_file() and f.suffix.lower() in (".dll", ".dat", ".ini", ".pak", ".cfg", ".json", ".xml"):
            resources[f.name] = f
    verbs = (f"    command -v winetricks >/dev/null && WINE=\"$WINE\" winetricks -q {' '.join(plan.verbs)} >/dev/null 2>&1\n"
             if plan.verbs else "")
    script = MAC_LAUNCHER.format(slug=slug(name), name=_xml(name).replace("'", ""), verbs=verbs, exe=shlex.quote(exe.name))
    app = build_app_bundle(name, out_dir, script, exe, resources)
    log(f"Built {app}")
    return str(app)
