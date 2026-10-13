"""fenestra-compat command line interface.

    fenestra-compat analyze  FILE           show how FILE will run on Linux
    fenestra-compat run      FILE [ARGS]    run a .exe/.msi/.bat/.ps1/.reg directly
    fenestra-compat convert  FILE [--name]  install as a Linux app (launcher + menu entry)
    fenestra-compat package  FILE [-o DIR]  build a standalone .deb (Linux) or .app (macOS) from a portable .exe
    fenestra-compat host                    show which Windows runtime this machine uses
    fenestra-compat setup-arm               install Hangover (Wine + FEX) on Debian/Ubuntu ARM64
    fenestra-compat bat2sh   FILE [-o OUT]  translate a batch file to Bash
    fenestra-compat icon     FILE OUT.png   extract the icon of an .exe
    fenestra-compat prefixes                list per-application Wine prefixes
    fenestra-compat integrate               make .exe/.msi/.bat double-clickable
    fenestra-compat gui [FILE]              open the graphical converter
"""

import argparse
import json
import sys
from pathlib import Path

from ..common import platform as hostos
from . import analyzer, batch, hosts, runner


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fenestra-compat", description="Run and convert Windows programs on Linux.")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("analyze", help="analyse a Windows file")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("run", help="run a Windows file")
    p.add_argument("file")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p.add_argument("--wait", action="store_true")

    p = sub.add_parser("convert", help="convert into an installed Linux application")
    p.add_argument("file")
    p.add_argument("--name")

    p = sub.add_parser("package", help="build a .deb package")
    p.add_argument("file")
    p.add_argument("-o", "--output", default=".")
    p.add_argument("--name")
    p.add_argument("--version")
    p.add_argument("--format", choices=["auto", "deb", "app"], default="auto",
                   help="deb = Debian package, app = macOS application bundle (default: by host OS)")
    sub.add_parser("host", help="show the runtime used on this machine")
    sub.add_parser("setup-arm", help="install Hangover on ARM64 Debian/Ubuntu")

    p = sub.add_parser("bat2sh", help="translate .bat/.cmd to bash")
    p.add_argument("file")
    p.add_argument("-o", "--output")

    p = sub.add_parser("icon", help="extract icon")
    p.add_argument("file")
    p.add_argument("output")

    sub.add_parser("prefixes", help="list Wine prefixes")
    sub.add_parser("integrate", help="register MIME handlers")
    p = sub.add_parser("gui", help="graphical converter")
    p.add_argument("file", nargs="?")

    a = ap.parse_args(argv)
    if a.cmd is None or a.cmd == "gui":
        from . import gui
        return gui.main([a.file] if getattr(a, "file", None) else [])

    if a.cmd == "analyze":
        plan = analyzer.analyze(a.file)
        if a.json:
            d = {k: v for k, v in plan.__dict__.items() if k != "pe"}
            if plan.pe:
                d["pe"] = {k: v for k, v in plan.pe.__dict__.items() if k not in ("sections", "manifest")}
            print(json.dumps(d, indent=2, default=str))
        else:
            print(plan.summary())
        return 0 if plan.rating != "borked" else 2
    if a.cmd == "run":
        return runner.run(a.file, a.args, wait=a.wait)
    if a.cmd == "convert":
        try:
            res = runner.convert(a.file, a.name)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(res, indent=2))
        return 0
    if a.cmd == "package":
        fmt = a.format if a.format != "auto" else ("app" if hostos.IS_MAC else "deb")
        try:
            if fmt == "app":
                runner.package_app(a.file, a.output, a.name)
            else:
                runner.package_deb(a.file, a.output, a.name, a.version)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "bat2sh":
        src = Path(a.file)
        out = batch.translate(src.read_text(errors="replace"), src.name)
        if a.output:
            Path(a.output).write_text(out)
            Path(a.output).chmod(0o755)
        else:
            sys.stdout.write(out)
        return 0
    if a.cmd == "icon":
        from PyQt6.QtGui import QGuiApplication
        app = QGuiApplication.instance() or QGuiApplication(["x", "-platform", "offscreen"])
        app.processEvents()
        ok = runner.extract_icon(a.file, Path(a.output))
        print("ok" if ok else "no icon found")
        return 0 if ok else 1
    if a.cmd == "host":
        print(f"Host: {hosts.describe_host()}")
        print(f"Page size: {hostos.page_size()} bytes")
        for label, machine, bits in (("x86 (32-bit) programs", "x86", 32), ("x64 (64-bit) programs", "x64", 64),
                                     ("ARM64 programs", "arm64", 64)):
            rt = hosts.find_runtime(machine, bits)
            print(f"\n{label}: {rt.name}{'' if rt.ok else '  [not available]'}  ({rt.speed})")
            for n in rt.notes:
                print(f"  {n}")
        return 0
    if a.cmd == "setup-arm":
        import subprocess
        script = Path(__file__).with_name("setup-arm64.sh")
        return subprocess.call(["sh", str(script)])
    if a.cmd == "prefixes":
        for p in runner.list_prefixes():
            print(p)
        return 0
    if a.cmd == "integrate":
        runner.register_desktop_integration()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
