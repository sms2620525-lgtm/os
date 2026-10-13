"""Pure-Python Portable Executable (PE/COFF) parser.

Reads just enough of a Windows ``.exe``/``.dll`` to decide how to run it on
Linux: architecture, GUI/console subsystem, imported DLLs, .NET (CLR) header,
version strings, embedded icons and the installer technology used.
No third-party dependencies.
"""

import struct
from dataclasses import dataclass, field

MACHINES = {
    0x014C: "x86",
    0x8664: "x64",
    0xAA64: "arm64",
    0x01C4: "arm",
    0x0200: "ia64",
}

SUBSYSTEMS = {
    1: "native",
    2: "gui",
    3: "console",
    5: "os2-console",
    7: "posix-console",
    9: "wince-gui",
    10: "efi-application",
    11: "efi-boot-driver",
    12: "efi-runtime-driver",
    14: "xbox",
    16: "boot-application",
}

RT_ICON, RT_GROUP_ICON, RT_VERSION, RT_MANIFEST = 3, 14, 16, 24

INSTALLER_SIGNATURES = [
    (b"Nullsoft Install System", "nsis"),
    (b"NullsoftInst", "nsis"),
    (b"Inno Setup Setup Data", "inno"),
    (b"Inno Setup", "inno"),
    (b"InstallShield", "installshield"),
    (b"WiX Toolset", "wix-burn"),
    (b".wixburn", "wix-burn"),
    (b"7-Zip SFX", "7zip-sfx"),
    (b"7zS.sfx", "7zip-sfx"),
    (b"WinRAR SFX", "rar-sfx"),
    (b"Squirrel", "squirrel"),
    (b"Electron", "electron"),
]

OLE_MAGIC = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"   # MSI / legacy Office


class PEError(ValueError):
    pass


@dataclass
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_size: int
    raw_pointer: int


@dataclass
class PEInfo:
    path: str
    machine: str
    bits: int
    subsystem: str
    is_dll: bool
    is_dotnet: bool
    timestamp: int
    imports: list = field(default_factory=list)          # lower-case DLL names
    sections: list = field(default_factory=list)
    version: dict = field(default_factory=dict)          # ProductName, CompanyName, ...
    installer: str | None = None
    manifest: str = ""
    has_icon: bool = False

    @property
    def requires_admin(self) -> bool:
        return "requireAdministrator" in self.manifest

    @property
    def display_name(self) -> str:
        import os
        for key in ("ProductName", "FileDescription", "InternalName"):
            v = self.version.get(key, "").strip()
            if v:
                return v
        return os.path.splitext(os.path.basename(self.path))[0]


class PEFile:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as fh:
            self.data = fh.read()
        self._parse_headers()

    # -- headers ---------------------------------------------------------
    def _u16(self, off):
        return struct.unpack_from("<H", self.data, off)[0]

    def _u32(self, off):
        return struct.unpack_from("<I", self.data, off)[0]

    def _parse_headers(self):
        d = self.data
        if len(d) < 0x40 or d[:2] != b"MZ":
            raise PEError("not an MZ executable")
        pe_off = self._u32(0x3C)
        if pe_off + 24 > len(d) or d[pe_off:pe_off + 4] != b"PE\0\0":
            raise PEError("MZ file without PE header (16-bit DOS program?)")
        coff = pe_off + 4
        (self.machine_id, nsect, self.timestamp, _, _, opt_size,
         self.characteristics) = struct.unpack_from("<HHIIIHH", d, coff)
        opt = coff + 20
        self.magic = self._u16(opt)
        if self.magic == 0x10B:
            self.bits, dd_count_off, dd_off = 32, 92, 96
        elif self.magic == 0x20B:
            self.bits, dd_count_off, dd_off = 64, 108, 112
        else:
            raise PEError(f"unknown optional header magic 0x{self.magic:x}")
        self.subsystem_id = self._u16(opt + 68)
        n_dirs = min(self._u32(opt + dd_count_off), 16)
        self.data_dirs = [struct.unpack_from("<II", d, opt + dd_off + 8 * i) for i in range(n_dirs)]
        self.data_dirs += [(0, 0)] * (16 - n_dirs)
        self.sections = []
        sec = opt + opt_size
        for i in range(nsect):
            off = sec + 40 * i
            if off + 40 > len(d):
                break
            name, vsize, va, rsize, rptr = struct.unpack_from("<8sIIII", d, off)
            self.sections.append(Section(name.rstrip(b"\0").decode("latin-1"), va, vsize, rsize, rptr))

    def rva_to_offset(self, rva: int) -> int | None:
        for s in self.sections:
            size = max(s.virtual_size, s.raw_size)
            if s.virtual_address <= rva < s.virtual_address + size:
                off = rva - s.virtual_address + s.raw_pointer
                return off if off < len(self.data) else None
        return None

    def _cstring(self, off, limit=256) -> str:
        end = self.data.find(b"\0", off, off + limit)
        if end < 0:
            end = off + limit
        return self.data[off:end].decode("latin-1")

    # -- imports ---------------------------------------------------------
    def imports(self) -> list:
        names = []
        rva, size = self.data_dirs[1]
        off = self.rva_to_offset(rva) if rva else None
        while off is not None and off + 20 <= len(self.data):
            oft, _, _, name_rva, ft = struct.unpack_from("<IIIII", self.data, off)
            if not (oft or name_rva or ft):
                break
            noff = self.rva_to_offset(name_rva)
            if noff is not None:
                names.append(self._cstring(noff).lower())
            off += 20
            if len(names) > 4096:
                break
        # delay-load imports
        rva, size = self.data_dirs[13]
        off = self.rva_to_offset(rva) if rva else None
        while off is not None and off + 32 <= len(self.data):
            attrs, name_rva = struct.unpack_from("<II", self.data, off)
            if not name_rva:
                break
            if attrs & 1 == 0:  # old style: VA instead of RVA
                image_base = self._image_base()
                name_rva -= image_base
            noff = self.rva_to_offset(name_rva)
            if noff is not None:
                names.append(self._cstring(noff).lower())
            off += 32
        seen = []
        for n in names:
            if n and n not in seen:
                seen.append(n)
        return seen

    def _image_base(self) -> int:
        pe_off = self._u32(0x3C)
        opt = pe_off + 24
        if self.bits == 64:
            return struct.unpack_from("<Q", self.data, opt + 24)[0]
        return self._u32(opt + 28)

    # -- resources -------------------------------------------------------
    def _resource_entries(self, dir_off, base):
        d = self.data
        if dir_off + 16 > len(d):
            return []
        named, ids = struct.unpack_from("<HH", d, dir_off + 12)
        out = []
        for i in range(min(named + ids, 2048)):
            e = dir_off + 16 + 8 * i
            if e + 8 > len(d):
                break
            name, target = struct.unpack_from("<II", d, e)
            if name & 0x80000000:
                soff = base + (name & 0x7FFFFFFF)
                ln = self._u16(soff)
                ident = d[soff + 2:soff + 2 + 2 * ln].decode("utf-16-le", "replace")
            else:
                ident = name
            out.append((ident, bool(target & 0x80000000), base + (target & 0x7FFFFFFF)))
        return out

    def resources(self) -> dict:
        """Return {type: {name: [bytes, ...per language]}}."""
        rva, size = self.data_dirs[2]
        base = self.rva_to_offset(rva) if rva else None
        result = {}
        if base is None:
            return result
        for rtype, is_dir, off in self._resource_entries(base, base):
            if not is_dir:
                continue
            for rname, is_dir2, off2 in self._resource_entries(off, base):
                if not is_dir2:
                    continue
                for _lang, is_dir3, off3 in self._resource_entries(off2, base):
                    if is_dir3 or off3 + 16 > len(self.data):
                        continue
                    data_rva, data_size = struct.unpack_from("<II", self.data, off3)
                    doff = self.rva_to_offset(data_rva)
                    if doff is None:
                        continue
                    result.setdefault(rtype, {}).setdefault(rname, []).append(
                        self.data[doff:doff + data_size])
        return result

    # -- version info ----------------------------------------------------
    @staticmethod
    def _parse_version_block(buf, off, end, out):
        while off + 6 <= end:
            length, value_len, vtype = struct.unpack_from("<HHH", buf, off)
            if length == 0:
                break
            block_end = min(off + length, end)
            k = off + 6
            kend = k
            while kend + 1 < block_end and buf[kend:kend + 2] != b"\0\0":
                kend += 2
            key = buf[k:kend].decode("utf-16-le", "replace")
            val = (kend + 2 + 3) & ~3
            if vtype == 1 and value_len:
                raw = buf[val:val + value_len * 2]
                text = raw.decode("utf-16-le", "replace").split("\0", 1)[0]
                if key and text:
                    out[key] = text
                children = (val + value_len * 2 + 3) & ~3
            else:
                children = (val + value_len + 3) & ~3
            if key in ("VS_VERSION_INFO", "StringFileInfo") or (len(key) == 8 and all(
                    c in "0123456789abcdefABCDEF" for c in key)):
                PEFile._parse_version_block(buf, children, block_end, out)
            off = (block_end + 3) & ~3

    def version_info(self, res=None) -> dict:
        res = res if res is not None else self.resources()
        out = {}
        for blobs in res.get(RT_VERSION, {}).values():
            for blob in blobs:
                self._parse_version_block(blob, 0, len(blob), out)
                if out:
                    return out
        return out

    # -- icons -----------------------------------------------------------
    def icon_ico(self, res=None) -> bytes | None:
        """Rebuild the first icon group as a standalone .ico file."""
        res = res if res is not None else self.resources()
        groups = res.get(RT_GROUP_ICON, {})
        images = res.get(RT_ICON, {})
        for blobs in groups.values():
            grp = blobs[0]
            if len(grp) < 6:
                continue
            _, itype, count = struct.unpack_from("<HHH", grp, 0)
            entries = []
            for i in range(count):
                o = 6 + 14 * i
                if o + 14 > len(grp):
                    break
                w, h, cc, rsv, planes, bpp, size, nid = struct.unpack_from("<BBBBHHIH", grp, o)
                img = images.get(nid)
                if img:
                    entries.append((w, h, cc, rsv, planes, bpp, img[0]))
            if not entries:
                continue
            header = struct.pack("<HHH", 0, 1, len(entries))
            offset = 6 + 16 * len(entries)
            dir_bytes, img_bytes = b"", b""
            for w, h, cc, rsv, planes, bpp, img in entries:
                dir_bytes += struct.pack("<BBBBHHII", w, h, cc, rsv, planes, bpp, len(img), offset)
                offset += len(img)
                img_bytes += img
            return header + dir_bytes + img_bytes
        return None

    def manifest(self, res=None) -> str:
        res = res if res is not None else self.resources()
        for blobs in res.get(RT_MANIFEST, {}).values():
            return blobs[0].decode("utf-8", "replace")
        return ""

    # -- installer detection -------------------------------------------
    def installer_type(self) -> str | None:
        window = self.data[:64 * 1024 * 1024]
        for sig, kind in INSTALLER_SIGNATURES:
            if sig in window:
                return kind
        return None

    def info(self) -> PEInfo:
        res = self.resources()
        return PEInfo(
            path=self.path,
            machine=MACHINES.get(self.machine_id, f"0x{self.machine_id:04x}"),
            bits=self.bits,
            subsystem=SUBSYSTEMS.get(self.subsystem_id, str(self.subsystem_id)),
            is_dll=bool(self.characteristics & 0x2000),
            is_dotnet=self.data_dirs[14][0] != 0,
            timestamp=self.timestamp,
            imports=self.imports(),
            sections=self.sections,
            version=self.version_info(res),
            installer=self.installer_type(),
            manifest=self.manifest(res),
            has_icon=bool(res.get(RT_GROUP_ICON)),
        )


def parse(path: str) -> PEInfo:
    return PEFile(path).info()


def is_msi(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(8) == OLE_MAGIC
    except OSError:
        return False
