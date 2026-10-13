"""Choose how to execute a Windows binary on *this* machine.

Host / guest matrix handled here:

=====================  =================  ===========================================
Host                   Windows binary     Runtime
=====================  =================  ===========================================
Linux x86-64           x86 / x64          Wine (native)
Linux ARM64            ARM64              Wine built for aarch64 (native)
(Asahi on M1, UTM VM,  x86 / x64          1. Hangover (Wine + FEX/box64 WoW64 emulation)
 Raspberry Pi ...)                        2. muvm + FEX (Asahi Linux, 16K-page kernels)
                                          3. box64 + an x86-64 Wine build
macOS Apple Silicon    x86 / x64          Wine/CrossOver/GPTK x86-64 build under Rosetta 2
macOS Intel            x86 / x64          Wine (native)
=====================  =================  ===========================================
"""

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..common import platform as hostos

MAC_WINE_CANDIDATES = [
    "/opt/homebrew/bin/wine64", "/opt/homebrew/bin/wine",
    "/usr/local/bin/wine64", "/usr/local/bin/wine",
    "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine64",
    "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine",
    "/Applications/Wine Crossover.app/Contents/Resources/wine/bin/wine64",
    "/Applications/Wine Crossover.app/Contents/Resources/wine/bin/wine",
    "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine",
    os.path.expanduser("~/Library/Application Support/com.isaacmarovitz.Whisky/Libraries/Wine/bin/wine64"),
]

X86_WINE_CANDIDATES = [
    os.environ.get("FENESTRA_X86_WINE", ""),
    "/opt/wine-x86_64/bin/wine64", "/opt/wine-x86_64/bin/wine",
    os.path.expanduser("~/wine-x86_64/bin/wine64"), os.path.expanduser("~/wine/bin/wine64"),
]


@dataclass
class Runtime:
    name: str                       # wine | hangover | muvm-fex | box64 | rosetta | none
    argv: list                      # command prefix; the .exe path and args are appended
    env: dict = field(default_factory=dict)
    ok: bool = True
    notes: list = field(default_factory=list)
    install_hint: str = ""
    speed: str = "native"           # native | translated | emulated

    @property
    def wine(self) -> str:
        """Path of the wine binary (for winetricks' WINE variable)."""
        for a in self.argv:
            if os.path.basename(a).startswith("wine"):
                return a
        return "wine"


def _which(*names):
    for n in names:
        if n and (os.path.isabs(n) and os.access(n, os.X_OK) or shutil.which(n)):
            return n if os.path.isabs(n) else shutil.which(n)
    return None


def rosetta_installed() -> bool:
    if not hostos.IS_MAC:
        return False
    if os.path.exists("/Library/Apple/usr/libexec/oah/libRosettaRuntime"):
        return True
    try:
        return subprocess.run(["arch", "-x86_64", "/usr/bin/true"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def hangover_installed() -> bool:
    patterns = ["/usr/lib/wine/aarch64-windows/libwow64fex.dll", "/usr/lib/wine/aarch64-windows/libarm64ecfex.dll",
                "/usr/lib/aarch64-linux-gnu/wine/aarch64-windows/libwow64fex.dll",
                "/opt/hangover/lib/wine/aarch64-windows/libwow64fex.dll",
                "/usr/lib/wine/aarch64-windows/box64cpu.dll", "/usr/lib/wine/aarch64-windows/wowbox64.dll"]
    return any(glob.glob(p) for p in patterns)


def _arm_wine_kind(bits: int) -> dict:
    """Pick Hangover's emulator DLLs (FEX preferred, box64 as fallback)."""
    env = {}
    dlls = " ".join(glob.glob("/usr/lib/wine/aarch64-windows/*") + glob.glob("/opt/hangover/lib/wine/aarch64-windows/*"))
    if bits == 32:
        env["HODLL"] = "libwow64fex.dll" if "libwow64fex" in dlls else ("wowbox64.dll" if "wowbox64" in dlls else "box64cpu.dll")
    else:
        env["HODLL64"] = "libarm64ecfex.dll"
    return env


def find_runtime(machine: str = "x64", bits: int = 64) -> Runtime:
    """machine: PE machine ("x86", "x64", "arm64"); bits: 32/64."""
    guest_arm = machine in ("arm64", "arm")

    # ---------------- macOS ----------------
    if hostos.IS_MAC:
        wine = _which(*MAC_WINE_CANDIDATES)
        if guest_arm:
            return Runtime("none", [], ok=False, notes=["ARM64 Windows programs are not supported by Wine on macOS yet."])
        if not wine:
            return Runtime("none", [], ok=False, install_hint="brew install --cask --no-quarantine wine-stable",
                           notes=["Wine is not installed. Install it with Homebrew: "
                                  "brew install --cask --no-quarantine wine-stable (or CrossOver)."])
        if hostos.IS_ARM64:
            rt = Runtime("rosetta", [wine], speed="translated",
                         notes=["Apple Silicon: x86/x64 Windows code is translated by Rosetta 2 "
                                "(typically 70-80% of native speed). DirectX goes through DXVK/MoltenVK or D3DMetal."])
            if not rosetta_installed():
                rt.ok = False
                rt.install_hint = "softwareupdate --install-rosetta --agree-to-license"
                rt.notes.append("Rosetta 2 is not installed: run 'softwareupdate --install-rosetta --agree-to-license'.")
            return rt
        return Runtime("wine", [wine])

    # ---------------- Linux x86-64 ----------------
    if not hostos.IS_ARM64:
        if guest_arm:
            return Runtime("none", [], ok=False, notes=["ARM Windows binaries need an ARM64 machine."])
        wine = _which("wine64", "wine") if bits == 64 else _which("wine", "wine64")
        if not wine:
            return Runtime("none", [], ok=False, install_hint="sudo apt install wine wine64 winetricks",
                           notes=["Wine is not installed: sudo apt install wine wine64 winetricks"])
        return Runtime("wine", [wine])

    # ---------------- Linux ARM64 (Asahi on M1/M2, UTM VM, Raspberry Pi, ...) ----------------
    wine = _which("wine", "wine64")
    if guest_arm:
        if wine:
            return Runtime("wine", [wine], notes=["Native ARM64 Windows program: runs at full speed."])
        return Runtime("none", [], ok=False, install_hint="sudo apt install wine",
                       notes=["Install Wine for ARM64: sudo apt install wine (Debian/Ubuntu) or sudo dnf install wine (Fedora Asahi)."])

    if wine and hangover_installed():
        return Runtime("hangover", [wine], env=_arm_wine_kind(bits), speed="emulated",
                       notes=["ARM64 host: x86/x64 code is emulated by Hangover (Wine + FEX). "
                              "Expect roughly 40-70% of native speed; Windows system DLLs themselves run natively."])
    if hostos.page_size() != 4096 and shutil.which("muvm") and (shutil.which("FEXBash") or shutil.which("FEXInterpreter")):
        return Runtime("muvm-fex", ["muvm", "--", "FEXBash", "-c", 'exec wine "$@"', "wine"], speed="emulated",
                       notes=["Asahi Linux: the 16K-page kernel cannot run x86 code directly, so Wine runs inside a "
                              "4K-page micro-VM (muvm) with the FEX emulator - the same path Steam uses on Asahi."])
    box64 = _which("box64")
    x86_wine = _which(*X86_WINE_CANDIDATES)
    if box64 and x86_wine:
        return Runtime("box64", [box64, x86_wine], speed="emulated",
                       notes=["ARM64 host: x86-64 Wine is run through the box64 dynamic recompiler."])
    hint = ("sudo dnf install fex-emu muvm wine   # Fedora Asahi Remix" if hostos.is_asahi()
            else "sudo fenestra-compat setup-arm   # installs Hangover (Wine + FEX) from its GitHub releases")
    return Runtime("none", [], ok=False, install_hint=hint,
                   notes=["This is an ARM64 computer and the program is x86/x64. An x86 emulator for Wine is needed: "
                          + hint.split("#")[0].strip()])


def describe_host() -> str:
    return hostos.host_description()


def setup_arm_script() -> str:
    """Shell script that installs Hangover on Debian/Ubuntu ARM64 (used by `fenestra-compat setup-arm`)."""
    return Path(__file__).with_name("setup-arm64.sh").read_text()
