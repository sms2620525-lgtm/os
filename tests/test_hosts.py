"""Runtime selection for every host the project supports (simulated)."""

import plistlib
import struct

import pytest

from fenestra.common import platform as hostos
from fenestra.compat import hosts, runner
from pebuilder import build_pe


@pytest.fixture
def host(monkeypatch):
    def set_host(mac=False, arm=False, have=(), page=4096, hangover=False, rosetta=True):
        monkeypatch.setattr(hostos, "IS_MAC", mac)
        monkeypatch.setattr(hostos, "IS_ARM64", arm)
        monkeypatch.setattr(hostos, "page_size", lambda: page)
        monkeypatch.setattr(hosts, "hangover_installed", lambda: hangover)
        monkeypatch.setattr(hosts, "rosetta_installed", lambda: rosetta)
        monkeypatch.setattr(hosts.shutil, "which", lambda n: f"/usr/bin/{n}" if n in have else None)
        monkeypatch.setattr(hosts, "_which", lambda *names: next(
            (n if n.startswith("/") else f"/usr/bin/{n}" for n in names if n and (n in have or n.split("/")[-1] in have and n.startswith("/opt/homebrew"))), None))
    return set_host


def test_linux_x86(host):
    host(have=("wine64", "wine"))
    rt = hosts.find_runtime("x64", 64)
    assert rt.ok and rt.name == "wine" and rt.argv == ["/usr/bin/wine64"]
    assert not hosts.find_runtime("arm64", 64).ok


def test_linux_x86_without_wine(host):
    host()
    rt = hosts.find_runtime("x86", 32)
    assert not rt.ok and "apt install wine" in rt.install_hint


def test_arm64_hangover(host):
    host(arm=True, have=("wine",), hangover=True)
    rt = hosts.find_runtime("x86", 32)
    assert rt.name == "hangover" and rt.ok and rt.speed == "emulated"
    assert "HODLL" in rt.env
    assert hosts.find_runtime("x64", 64).env.get("HODLL64") == "libarm64ecfex.dll"


def test_arm64_native_arm_exe(host):
    host(arm=True, have=("wine",))
    rt = hosts.find_runtime("arm64", 64)
    assert rt.ok and rt.speed == "native"


def test_asahi_muvm_fex(host):
    host(arm=True, have=("wine", "muvm", "FEXBash"), page=16384)
    rt = hosts.find_runtime("x64", 64)
    assert rt.name == "muvm-fex" and rt.argv[:2] == ["muvm", "--"]


def test_arm64_box64(host, monkeypatch):
    host(arm=True, have=("box64", "/opt/wine-x86_64/bin/wine64"))
    rt = hosts.find_runtime("x64", 64)
    assert rt.name == "box64" and rt.argv == ["/usr/bin/box64", "/opt/wine-x86_64/bin/wine64"]


def test_arm64_nothing_installed(host):
    host(arm=True)
    rt = hosts.find_runtime("x64", 64)
    assert not rt.ok and "setup-arm" in rt.install_hint


def test_mac_apple_silicon_rosetta(host):
    host(mac=True, arm=True, have=("/opt/homebrew/bin/wine64",))
    rt = hosts.find_runtime("x64", 64)
    assert rt.name == "rosetta" and rt.ok and rt.speed == "translated"
    host(mac=True, arm=True, have=("/opt/homebrew/bin/wine64",), rosetta=False)
    rt = hosts.find_runtime("x64", 64)
    assert not rt.ok and "install-rosetta" in rt.install_hint


def test_mac_without_wine(host):
    host(mac=True, arm=True)
    rt = hosts.find_runtime("x64", 64)
    assert not rt.ok and "brew install" in rt.install_hint


def test_analyzer_reports_host(host, tmp_path):
    host(arm=True, have=("wine",), hangover=True)
    from fenestra.compat import analyzer
    plan = analyzer.analyze(str(build_pe(tmp_path / "a.exe", bits=32)))
    assert plan.host == "hangover" and plan.host_ok
    assert "This PC:" in plan.summary()


def test_make_icns():
    data = runner.make_icns({128: b"\x89PNG-a", 256: b"\x89PNG-b"})
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    assert b"ic07" in data and b"ic08" in data


def test_package_app_bundle(tmp_path, qapp):
    src = tmp_path / "Game"
    src.mkdir()
    exe = build_pe(src / "game.exe", version={"ProductName": "Space Game"}, dlls=["kernel32.dll", "d3d11.dll"])
    (src / "engine.dll").write_bytes(b"MZ")
    app = runner.package_app(str(exe), str(tmp_path), log=lambda *_: None)
    contents = tmp_path / "Space Game.app" / "Contents"
    assert app.endswith("Space Game.app")
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "launcher" and info["CFBundleIconFile"] == "AppIcon"
    launcher = (contents / "MacOS" / "launcher").read_text()
    assert "wine-stable" in launcher and "Rosetta 2" in launcher and "game.exe" in launcher
    assert "winetricks -q dxvk" in launcher
    assert (contents / "Resources" / "app" / "engine.dll").exists()
    assert (contents / "Resources" / "AppIcon.icns").read_bytes()[:4] == b"icns"


def test_launcher_uses_runtime_env(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(runner, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(runner, "APPS_DIR", tmp_path / "apps")
    monkeypatch.setattr(runner, "ICONS_DIR", tmp_path / "icons")
    monkeypatch.setattr(hostos, "IS_MAC", False)
    from fenestra.compat import analyzer
    exe = build_pe(tmp_path / "t.exe", bits=32)
    rt = hosts.Runtime("hangover", ["/usr/bin/wine"], env={"HODLL": "libwow64fex.dll"})
    launcher, _ = runner.write_launcher("Tool", exe, tmp_path / "pfx", analyzer.analyze(str(exe)), rt)
    text = launcher.read_text()
    assert "export HODLL=libwow64fex.dll" in text and "exec /usr/bin/wine" in text
