from fenestra.compat import analyzer
from pebuilder import build_pe


def test_winetricks_mapping():
    verbs = analyzer.winetricks_for(["msvcp140.dll", "vcruntime140_1.dll", "d3dx9_43.dll", "xinput1_3.dll",
                                     "d3d11.dll", "gdiplus.dll", "msvcr100.dll"])
    for v in ("vcrun2022", "d3dx9", "xinput", "dxvk", "gdiplus", "vcrun2010"):
        assert v in verbs
    assert len(verbs) == len(set(verbs))


def test_plan_for_game(tmp_path):
    exe = build_pe(tmp_path / "game.exe", dlls=["kernel32.dll", "d3d11.dll", "xinput1_3.dll"],
                   version={"ProductName": "Space Game"})
    plan = analyzer.analyze(str(exe))
    assert plan.runtime == "wine64"
    assert plan.name == "Space Game"
    assert "dxvk" in plan.verbs
    assert plan.rating in ("gold", "platinum")
    assert "Space Game" in plan.summary()


def test_anticheat_and_driver(tmp_path):
    ac = analyzer.analyze(str(build_pe(tmp_path / "a.exe", dlls=["kernel32.dll", "easyanticheat_x64.dll"])))
    assert ac.rating == "bronze"
    drv = analyzer.analyze(str(build_pe(tmp_path / "d.sys", subsystem=1, dlls=["ntoskrnl.exe"])))
    assert drv.rating == "borked" and drv.runtime == "none"


def test_dotnet(tmp_path):
    plan = analyzer.analyze(str(build_pe(tmp_path / "n.exe", bits=32, dlls=["mscoree.dll"], dotnet=True)))
    assert plan.kind == "dotnet"
    assert plan.rating == "silver"


def test_arm64(tmp_path):
    plan = analyzer.analyze(str(build_pe(tmp_path / "arm.exe", machine=0xAA64)))
    assert plan.pe.machine == "arm64" and plan.rating == "bronze"


def test_script_types(tmp_path):
    for name, kind, runtime in (("a.bat", "batch", "bash"), ("b.ps1", "powershell", "pwsh"),
                                ("c.reg", "registry", "wine"), ("d.msi", "msi", "wine"), ("e.msix", "msix", "none")):
        f = tmp_path / name
        f.write_text("x")
        plan = analyzer.analyze(str(f))
        assert (plan.kind, plan.runtime) == (kind, runtime)
