from fenestra.compat import analyzer, pe
from pebuilder import build_pe


def test_parse_pe64_with_imports_version_and_icon(tmp_path):
    exe = build_pe(tmp_path / "app.exe", bits=64,
                   dlls=["KERNEL32.dll", "msvcp140.dll", "d3dx9_43.dll", "d3d11.dll"],
                   version={"ProductName": "Demo App", "CompanyName": "Acme", "ProductVersion": "2.5.1"})
    info = pe.parse(str(exe))
    assert info.machine == "x64" and info.bits == 64
    assert info.subsystem == "gui"
    assert not info.is_dll and not info.is_dotnet
    assert info.imports == ["kernel32.dll", "msvcp140.dll", "d3dx9_43.dll", "d3d11.dll"]
    assert info.version["ProductName"] == "Demo App"
    assert info.version["CompanyName"] == "Acme"
    assert info.display_name == "Demo App"
    assert info.has_icon


def test_icon_is_rebuilt_as_ico(tmp_path):
    exe = build_pe(tmp_path / "app.exe")
    ico = pe.PEFile(str(exe)).icon_ico()
    assert ico[:4] == b"\0\0\x01\0"
    assert b"\x89PNG" in ico


def test_pe32_console_and_dll_flags(tmp_path):
    info = pe.parse(str(build_pe(tmp_path / "tool.exe", bits=32, subsystem=3, icon=False)))
    assert info.machine == "x86" and info.bits == 32 and info.subsystem == "console"
    dll = pe.parse(str(build_pe(tmp_path / "lib.dll", dll=True, icon=False)))
    assert dll.is_dll


def test_installer_detection(tmp_path):
    exe = build_pe(tmp_path / "setup.exe", extra=b"\0" * 64 + b"Inno Setup Setup Data (6.2.0)")
    assert pe.parse(str(exe)).installer == "inno"


def test_not_pe(tmp_path):
    f = tmp_path / "x.exe"
    f.write_bytes(b"hello")
    plan = analyzer.analyze(str(f))
    assert plan.rating == "borked"


def test_dos_program(tmp_path):
    f = tmp_path / "game.exe"
    f.write_bytes(b"MZ" + b"\0" * 0x3A + b"\x00\x01\0\0" + b"\0" * 300)
    assert analyzer.analyze(str(f)).runtime == "dosbox"
