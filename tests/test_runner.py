import io
import os
import shutil
import subprocess
import tarfile

import pytest

from fenestra.compat import runner
from pebuilder import build_pe


def _ar_members(data):
    assert data[:8] == b"!<arch>\n"
    off, out = 8, {}
    while off < len(data):
        hdr = data[off:off + 60]
        name = hdr[:16].decode().strip()
        size = int(hdr[48:58].decode())
        out[name] = data[off + 60:off + 60 + size]
        off += 60 + size + (size % 2)
    return out


def test_package_deb(tmp_path):
    appdir = tmp_path / "MyApp"
    appdir.mkdir()
    exe = build_pe(appdir / "myapp.exe", dlls=["kernel32.dll", "msvcp140.dll"],
                   version={"ProductName": "My App", "CompanyName": "Acme", "ProductVersion": "3.1.4"})
    (appdir / "helper.dll").write_bytes(b"MZ")
    deb = runner.package_deb(str(exe), str(tmp_path), log=lambda *_: None)
    assert deb.endswith("my-app_3.1.4_all.deb")
    members = _ar_members(open(deb, "rb").read())
    assert list(members) == ["debian-binary", "control.tar.gz", "data.tar.gz"]
    control = tarfile.open(fileobj=io.BytesIO(members["control.tar.gz"])).extractfile("./control").read().decode()
    assert "Package: my-app" in control and "Depends: wine64" in control
    names = tarfile.open(fileobj=io.BytesIO(members["data.tar.gz"])).getnames()
    assert "./opt/fenestra-apps/my-app/myapp.exe" in names
    assert "./opt/fenestra-apps/my-app/helper.dll" in names
    assert "./usr/bin/my-app" in names
    assert "./usr/share/applications/my-app.desktop" in names
    if subprocess.run(["which", "dpkg-deb"], capture_output=True).returncode == 0:
        r = subprocess.run(["dpkg-deb", "-I", deb], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_extract_icon(tmp_path, qapp):
    exe = build_pe(tmp_path / "x.exe")
    out = tmp_path / "icon.png"
    assert runner.extract_icon(str(exe), out)
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_write_launcher(tmp_path, qapp, monkeypatch):
    from fenestra.common import platform as hostos
    from fenestra.compat import analyzer
    monkeypatch.setattr(hostos, "IS_MAC", False)   # Linux launcher + .desktop entry, on any host
    monkeypatch.setattr(runner, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(runner, "APPS_DIR", tmp_path / "apps")
    monkeypatch.setattr(runner, "ICONS_DIR", tmp_path / "icons")
    exe = build_pe(tmp_path / "tool.exe", version={"ProductName": "Tool"})
    plan = analyzer.analyze(str(exe))
    launcher, desktop = runner.write_launcher("Tool", exe, tmp_path / "prefix", plan)
    text = launcher.read_text()
    assert "WINEPREFIX=" in text and "tool.exe" in text
    assert "Exec=" in desktop.read_text()
    assert (tmp_path / "icons" / "fenestra-tool.png").exists()


def test_slug():
    assert runner.slug("My Cool App 2.0!") == "my-cool-app-2-0"
    assert runner.slug("***") == "app"


@pytest.mark.skipif(not shutil.which("wine") or not os.environ.get("DISPLAY"),
                    reason="needs Wine and an X display (run under xvfb-run)")
def test_real_wine_end_to_end(tmp_path):
    """Run and convert a real Windows executable (Wine's own hostname.exe)."""
    import glob
    exes = glob.glob("/usr/lib/*/wine/x86_64-windows/hostname.exe") + glob.glob("/usr/lib/wine/x86_64-windows/hostname.exe")
    if not exes:
        pytest.skip("hostname.exe not found")
    exe = tmp_path / "hostname.exe"
    shutil.copy(exes[0], exe)
    res = runner.convert(str(exe), "Hostname Tool", log=lambda *_: None)
    out = subprocess.run([res["launcher"]], capture_output=True, text=True, timeout=120).stdout.strip()
    import socket
    assert out.lower() == socket.gethostname().lower()


def test_write_launcher_macos_app_bundle(tmp_path, qapp, monkeypatch):
    """On macOS the converted program becomes an .app bundle in ~/Applications."""
    from fenestra.common import platform as hostos
    from fenestra.compat import analyzer
    monkeypatch.setattr(hostos, "IS_MAC", True)
    monkeypatch.setattr(runner, "MAC_APPS_DIR", tmp_path / "Applications")
    exe = build_pe(tmp_path / "tool.exe", version={"ProductName": "Tool"})
    plan = analyzer.analyze(str(exe))
    launcher, app = runner.write_launcher("Tool", exe, tmp_path / "prefix", plan)
    assert app == tmp_path / "Applications" / "Tool.app" and app.is_dir()
    assert launcher.read_text().startswith("#!/bin/sh") and "tool.exe" in launcher.read_text()
    assert (app / "Contents" / "Info.plist").exists()
