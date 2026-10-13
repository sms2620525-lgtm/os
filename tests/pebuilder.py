"""Build small but valid PE32/PE32+ files for tests (imports, version info, icon)."""

import struct
import zlib

RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16


def _align(n, a):
    return (n + a - 1) // a * a


def tiny_png(w=2, h=2, rgba=(0, 120, 215, 255)):
    raw = b"".join(b"\0" + bytes(rgba) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _vblock(key, value=b"", text=False, children=b""):
    k = (key + "\0").encode("utf-16-le")
    out = bytearray(6) + k
    while len(out) % 4:
        out += b"\0"
    if text and value:
        v = (value + "\0").encode("utf-16-le")
        vlen = len(v) // 2
    elif text:
        v, vlen = b"", 0
    else:
        v = value
        vlen = len(v)
    out += v
    if children:
        while len(out) % 4:
            out += b"\0"
        out += children
    struct.pack_into("<HHH", out, 0, len(out), vlen, 1 if text else 0)
    return bytes(out)


def _pad4(b):
    return b + b"\0" * (-len(b) % 4)


def version_resource(strings):
    entries = b"".join(_pad4(_vblock(k, v, text=True)) for k, v in strings.items())
    table = _vblock("040904b0", children=entries, text=True)
    sfi = _vblock("StringFileInfo", children=_pad4(table), text=True)
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, 0x00010002, 0, 0x00010002, 0, 0x3F, 0, 4, 1, 0, 0, 0)
    return _vblock("VS_VERSION_INFO", fixed, children=_pad4(sfi))


def build_rsrc(resources, base_rva):
    """resources: {type_id: {name_id: bytes}} -> section bytes (single language 0x409)."""
    types = sorted(resources)
    # sizes
    dir_size = lambda n: 16 + 8 * n  # noqa: E731
    root = dir_size(len(types))
    name_dirs = [dir_size(len(resources[t])) for t in types]
    total_names = sum(len(resources[t]) for t in types)
    lang_dirs = total_names * dir_size(1)
    data_entries = total_names * 16
    header = root + sum(name_dirs) + lang_dirs + data_entries
    buf = bytearray(header)
    blobs = bytearray()
    off_name = root
    off_lang = root + sum(name_dirs)
    off_data = off_lang + lang_dirs
    struct.pack_into("<IIHHHH", buf, 0, 0, 0, 0, 0, 0, len(types))
    for ti, t in enumerate(types):
        struct.pack_into("<II", buf, 16 + 8 * ti, t, 0x80000000 | off_name)
        names = sorted(resources[t])
        struct.pack_into("<IIHHHH", buf, off_name, 0, 0, 0, 0, 0, len(names))
        for ni, n in enumerate(names):
            struct.pack_into("<II", buf, off_name + 16 + 8 * ni, n, 0x80000000 | off_lang)
            struct.pack_into("<IIHHHH", buf, off_lang, 0, 0, 0, 0, 0, 1)
            struct.pack_into("<II", buf, off_lang + 16, 0x409, off_data)
            data = resources[t][n]
            rva = base_rva + header + len(blobs)
            struct.pack_into("<IIII", buf, off_data, rva, len(data), 0, 0)
            blobs += data + b"\0" * (-len(data) % 8)
            off_lang += dir_size(1)
            off_data += 16
        off_name += dir_size(len(names))
    return bytes(buf + blobs)


def build_imports(dlls, base_rva):
    n = len(dlls)
    desc = bytearray(20 * (n + 1))
    thunk_off = len(desc)
    thunks = b"\0" * 16
    names = bytearray()
    names_off = thunk_off + len(thunks)
    for i, d in enumerate(dlls):
        name_rva = base_rva + names_off + len(names)
        names += d.encode() + b"\0"
        struct.pack_into("<IIIII", desc, 20 * i, base_rva + thunk_off, 0, 0, name_rva, base_rva + thunk_off)
    return bytes(desc + thunks + names)


def build_pe(path, bits=64, subsystem=2, dlls=("kernel32.dll", "user32.dll"), version=None, icon=True,
             dll=False, dotnet=False, machine=None, extra=b""):
    file_align, sect_align = 0x200, 0x1000
    imp_rva, rsrc_rva = 0x1000, 0x2000
    imports = build_imports(list(dlls), imp_rva)
    res = {}
    if version:
        res[RT_VERSION] = {1: version_resource(version)}
    if icon:
        png = tiny_png()
        res[RT_ICON] = {1: png}
        res[RT_GROUP_ICON] = {101: struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHIH", 2, 2, 0, 0, 1, 32, len(png), 1)}
    rsrc = build_rsrc(res, rsrc_rva) if res else b""
    sections = [(b".idata", imp_rva, imports, 0xC0000040)]
    if rsrc:
        sections.append((b".rsrc", rsrc_rva, rsrc, 0x40000040))

    opt_size = 240 if bits == 64 else 224
    headers_size = _align(0x40 + 4 + 20 + opt_size + 40 * len(sections), file_align)
    raw_ptr = headers_size
    table = b""
    body = b""
    for name, rva, data, chars in sections:
        raw = data + b"\0" * (-len(data) % file_align)
        table += struct.pack("<8sIIIIIIHHI", name, len(data), rva, len(raw), raw_ptr + len(body), 0, 0, 0, 0, chars)
        body += raw
    image_size = _align(max(rva + len(d) for _, rva, d, _ in sections), sect_align)

    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    mach = machine if machine is not None else (0x8664 if bits == 64 else 0x14C)
    chars = 0x0022 | (0x2000 if dll else 0) | (0 if bits == 64 else 0x0100)
    coff = struct.pack("<HHIIIHH", mach, len(sections), 0x60000000, 0, 0, opt_size, chars)
    dirs = [(0, 0)] * 16
    dirs[1] = (imp_rva, len(imports))
    if rsrc:
        dirs[2] = (rsrc_rva, len(rsrc))
    if dotnet:
        dirs[14] = (imp_rva + 0x100, 72)
    if bits == 64:
        opt = struct.pack("<HBBIIIII", 0x20B, 14, 0, 0, 0, 0, 0x1000, 0x1000)
        opt += struct.pack("<QII", 0x140000000, sect_align, file_align)
        opt += struct.pack("<HHHHHHI", 6, 0, 0, 0, 6, 0, 0)
        opt += struct.pack("<IIIHH", image_size, headers_size, 0, subsystem, 0x8160)
        opt += struct.pack("<QQQQII", 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    else:
        opt = struct.pack("<HBBIIIIII", 0x10B, 14, 0, 0, 0, 0, 0x1000, 0x1000, 0)
        opt += struct.pack("<III", 0x400000, sect_align, file_align)
        opt += struct.pack("<HHHHHHI", 6, 0, 0, 0, 6, 0, 0)
        opt += struct.pack("<IIIHH", image_size, headers_size, 0, subsystem, 0x8140)
        opt += struct.pack("<IIIIII", 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    opt += b"".join(struct.pack("<II", *d) for d in dirs)
    assert len(opt) == opt_size, len(opt)
    header = bytes(dos) + b"PE\0\0" + coff + opt + table
    header += b"\0" * (headers_size - len(header))
    with open(path, "wb") as fh:
        fh.write(header + body + extra)
    return path
