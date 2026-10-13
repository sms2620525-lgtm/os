"""Decide how a Windows program should be run on Linux.

Given a file (``.exe``, ``.msi``, ``.bat``, ``.ps1``, ``.reg``, ``.lnk``...)
produce a :class:`Plan`: which runtime to use, which Wine components to
install (winetricks verbs), a compatibility rating and human readable notes.
"""

import os
import re
from dataclasses import dataclass, field

from . import hosts, pe

# DLL name (regex, lower-case) -> winetricks verbs it hints at.
DLL_HINTS = [
    (r"^msvcp140.*|^vcruntime140.*|^concrt140|^vccorlib140", ["vcrun2022"]),
    (r"^msvc[pr]120", ["vcrun2013"]),
    (r"^msvc[pr]110", ["vcrun2012"]),
    (r"^msvc[pr]100", ["vcrun2010"]),
    (r"^msvc[pr]90", ["vcrun2008"]),
    (r"^msvc[pr]80", ["vcrun2005"]),
    (r"^mfc140.*", ["vcrun2022", "mfc140"]),
    (r"^mfc120.*", ["vcrun2013"]),
    (r"^mfc100.*", ["vcrun2010", "mfc100"]),
    (r"^mfc42.*", ["mfc42"]),
    (r"^d3dx9_\d+", ["d3dx9"]),
    (r"^d3dx10.*", ["d3dx10"]),
    (r"^d3dx11.*", ["d3dx11_43"]),
    (r"^d3dcompiler_47", ["d3dcompiler_47"]),
    (r"^d3dcompiler_43", ["d3dcompiler_43"]),
    (r"^xinput1_3", ["xinput"]),
    (r"^x3daudio.*|^xaudio2_[0-7]", ["xact"]),
    (r"^d3d11|^dxgi|^d3d10.*", ["dxvk"]),
    (r"^d3d12", ["vkd3d"]),
    (r"^d3d9", ["dxvk"]),
    (r"^gdiplus", ["gdiplus"]),
    (r"^msxml3", ["msxml3"]),
    (r"^msxml6", ["msxml6"]),
    (r"^riched20|^riched32|^msftedit", ["riched20"]),
    (r"^mshtml|^ieframe", ["ie8"]),
    (r"^webview2loader", ["webview2"]),
    (r"^vb6|^msvbvm60", ["vb6run"]),
    (r"^msvbvm50", ["vb5run"]),
    (r"^physxloader|^physx3.*", ["physx"]),
    (r"^dsound", []),
    (r"^quartz", ["quartz"]),
    (r"^wmvcore|^wmasf", ["wmp10"]),
    (r"^mf\.dll|^mfplat|^mfreadwrite", ["mf"]),
    (r"^openal32", ["openal"]),
    (r"^vulkan-1", []),
    (r"^corefonts|^usp10", ["corefonts"]),
]

# Imports that signal things Wine fundamentally cannot do.
BLOCKERS = {
    "ntoskrnl.exe": "Kernel-mode driver: Linux cannot load Windows drivers.",
    "hal.dll": "Kernel-mode component (HAL).",
    "fltmgr.sys": "File-system filter driver.",
    "ndis.sys": "Network driver.",
    "easyanticheat.dll": "EasyAntiCheat: works only if the developer enabled Linux/Proton support.",
    "easyanticheat_x64.dll": "EasyAntiCheat: works only if the developer enabled Linux/Proton support.",
    "beclient.dll": "BattlEye: works only if the developer enabled Proton support.",
    "beclient_x64.dll": "BattlEye: works only if the developer enabled Proton support.",
    "vgk.sys": "Riot Vanguard kernel anti-cheat is not supported.",
}

SCRIPT_TYPES = {
    ".bat": "batch", ".cmd": "batch",
    ".ps1": "powershell",
    ".reg": "registry",
    ".vbs": "vbscript", ".js": "jscript",
    ".lnk": "shortcut",
    ".msi": "msi",
    ".msix": "msix", ".appx": "msix",
    ".com": "dos",
}


@dataclass
class Plan:
    path: str
    kind: str                       # exe | dll | msi | batch | powershell | registry | dos | ...
    runtime: str                    # wine | wine64 | mono | dotnet | bash | pwsh | dosbox | none
    rating: str                     # platinum | gold | silver | bronze | borked
    name: str = ""
    verbs: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    pe: "pe.PEInfo | None" = None
    is_installer: bool = False
    host: str = ""                  # runtime on this machine: wine | hangover | muvm-fex | box64 | rosetta | none
    host_ok: bool = True
    host_notes: list = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"File:      {self.path}",
                 f"Name:      {self.name}",
                 f"Type:      {self.kind}",
                 f"Runtime:   {self.runtime}",
                 f"Rating:    {self.rating}"]
        if self.pe:
            lines.append(f"Arch:      {self.pe.machine} ({self.pe.bits}-bit, {self.pe.subsystem})")
            if self.pe.installer:
                lines.append(f"Installer: {self.pe.installer}")
            if self.pe.imports:
                lines.append(f"Imports:   {', '.join(self.pe.imports[:20])}"
                             + (" ..." if len(self.pe.imports) > 20 else ""))
        if self.verbs:
            lines.append(f"Install:   winetricks {' '.join(self.verbs)}")
        if self.host:
            lines.append(f"This PC:   {hosts.describe_host()} -> {self.host}{'' if self.host_ok else ' (not ready)'}")
            for n in self.host_notes:
                lines.append(f"           {n}")
        for n in self.notes:
            lines.append(f"Note:      {n}")
        return "\n".join(lines)


RATING_ORDER = ["platinum", "gold", "silver", "bronze", "borked"]


def _downgrade(rating: str, to: str) -> str:
    return to if RATING_ORDER.index(to) > RATING_ORDER.index(rating) else rating


def winetricks_for(imports) -> list:
    verbs = []
    for dll in imports:
        for pattern, hint in DLL_HINTS:
            if re.match(pattern, dll):
                for v in hint:
                    if v not in verbs:
                        verbs.append(v)
    return verbs


def analyze(path: str) -> Plan:
    ext = os.path.splitext(path)[1].lower()
    name = os.path.splitext(os.path.basename(path))[0]

    if ext in SCRIPT_TYPES and ext not in (".com",):
        kind = SCRIPT_TYPES[ext]
        if kind == "batch":
            return Plan(path, kind, "bash", "gold", name,
                        notes=["Batch file will be translated to a Bash script (bat2sh). "
                               "Unsupported commands fall back to running inside Wine's cmd.exe."])
        if kind == "powershell":
            return Plan(path, kind, "pwsh", "silver", name,
                        notes=["Runs with PowerShell for Linux (pwsh). Windows-only cmdlets "
                               "(registry, WMI, COM) may not be available."])
        if kind == "registry":
            return Plan(path, kind, "wine", "gold", name,
                        notes=["Imported into the Wine registry with 'wine regedit'."])
        if kind == "msi":
            return Plan(path, kind, "wine", "silver", name, is_installer=True,
                        notes=["Installed with 'wine msiexec /i' into a dedicated prefix."])
        if kind == "msix":
            return Plan(path, kind, "none", "borked", name,
                        notes=["MSIX/AppX packages (Microsoft Store) are not supported by Wine."])
        if kind in ("vbscript", "jscript"):
            return Plan(path, kind, "wine", "bronze", name,
                        notes=["Executed with Wine's wscript.exe."])
        if kind == "shortcut":
            return Plan(path, kind, "wine", "silver", name,
                        notes=["Windows shortcut; resolved with 'wine start'."])

    try:
        info = pe.parse(path)
    except pe.PEError as exc:
        if ext == ".com" or "16-bit" in str(exc):
            return Plan(path, "dos", "dosbox", "gold", name,
                        notes=["16-bit DOS program: runs in DOSBox."])
        return Plan(path, "unknown", "none", "borked", name, notes=[f"Not a Windows executable: {exc}"])
    except OSError as exc:
        return Plan(path, "unknown", "none", "borked", name, notes=[str(exc)])

    plan = Plan(path, "dll" if info.is_dll else "exe",
                "wine64" if info.bits == 64 else "wine", "gold", info.display_name, pe=info)

    if info.machine in ("arm64", "arm"):
        plan.notes.append("ARM Windows binary: requires Wine built for ARM (or an x86 build via box64 on ARM hardware).")
        plan.rating = _downgrade(plan.rating, "bronze")
    elif info.machine not in ("x86", "x64"):
        plan.notes.append(f"Unsupported CPU architecture {info.machine}.")
        plan.rating = "borked"

    if info.subsystem == "native" or any(i.endswith(".sys") for i in info.imports):
        plan.notes.append("This is a Windows driver / native NT binary and cannot run on Linux.")
        plan.rating = "borked"
        plan.runtime = "none"

    for dll in info.imports:
        if dll in BLOCKERS:
            plan.notes.append(BLOCKERS[dll])
            plan.rating = _downgrade(plan.rating, "borked" if dll.endswith(".sys") or dll in ("ntoskrnl.exe", "hal.dll") else "bronze")

    if info.is_dotnet:
        plan.kind = "dotnet-dll" if info.is_dll else "dotnet"
        plan.notes.append(".NET assembly: Wine Mono is used automatically; install 'dotnet48' for "
                          "WPF/WinForms apps that fail under Mono.")
        if not info.imports or info.imports == ["mscoree.dll"]:
            plan.runtime = "wine"
        plan.rating = _downgrade(plan.rating, "silver")

    plan.verbs = winetricks_for(info.imports)
    if any(v in plan.verbs for v in ("dxvk", "vkd3d")):
        plan.notes.append("Direct3D 9-12 is translated to Vulkan by DXVK/VKD3D; requires a Vulkan-capable GPU driver.")
    if info.installer:
        plan.is_installer = True
        plan.notes.append(f"Detected {info.installer} installer: it will be installed into its own Wine prefix "
                          "and the installed program gets a Linux launcher.")
    if info.requires_admin:
        plan.notes.append("Requests administrator rights; under Wine it runs as a normal user (usually fine).")
    if info.is_dll:
        plan.notes.append("DLL files are libraries and cannot be launched directly.")
        plan.runtime = "none"
        plan.rating = _downgrade(plan.rating, "bronze")
    if info.subsystem == "console":
        plan.notes.append("Console program: launched inside a terminal window.")
    if plan.runtime != "none":
        rt = hosts.find_runtime(info.machine, info.bits)
        plan.host, plan.host_ok, plan.host_notes = rt.name, rt.ok, list(rt.notes)
        if rt.install_hint and not rt.ok and not any(rt.install_hint in n for n in rt.notes):
            plan.host_notes.append(f"Fix: {rt.install_hint}")
    return plan
