"""File operations for File Explorer: copy/move with progress, trash, zip."""

import os
import shutil
import time
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path

DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
TRASH = DATA_HOME / "Trash"


def unique_name(target: Path) -> Path:
    """'file.txt' -> 'file - Copy.txt', 'file - Copy (2).txt' ... like Windows."""
    if not target.exists():
        return target
    stem, suffix = (target.name, "") if target.is_dir() else (target.stem, target.suffix)
    cand = target.with_name(f"{stem} - Copy{suffix}")
    n = 2
    while cand.exists():
        cand = target.with_name(f"{stem} - Copy ({n}){suffix}")
        n += 1
    return cand


def new_name(folder: Path, base: str, suffix: str = "") -> Path:
    cand = folder / f"{base}{suffix}"
    n = 2
    while cand.exists():
        cand = folder / f"{base} ({n}){suffix}"
        n += 1
    return cand


def total_size(paths) -> int:
    total = 0
    for p in paths:
        p = Path(p)
        if p.is_symlink() or p.is_file():
            try:
                total += p.lstat().st_size
            except OSError:
                pass
        elif p.is_dir():
            for root, _, files in os.walk(p):
                for f in files:
                    try:
                        total += os.lstat(os.path.join(root, f)).st_size
                    except OSError:
                        pass
    return total


def transfer(sources, dest_dir, move=False, progress=None, cancelled=lambda: False):
    """Copy or move ``sources`` into ``dest_dir``. progress(done_bytes, total, current_name)."""
    dest_dir = Path(dest_dir)
    total = max(1, total_size(sources))
    done = 0
    for src in map(Path, sources):
        if cancelled():
            break
        target = dest_dir / src.name
        if target.resolve() == src.resolve():
            if move:
                continue
            target = unique_name(target)
        elif target.exists():
            target = unique_name(target)
        if move:
            try:
                os.rename(src, target)
                done += total_size([target])
                progress and progress(done, total, src.name)
                continue
            except OSError:
                pass  # cross-device: copy then delete
        if src.is_dir() and not src.is_symlink():
            for root, dirs, files in os.walk(src):
                rel = Path(root).relative_to(src)
                (target / rel).mkdir(parents=True, exist_ok=True)
                for f in files:
                    if cancelled():
                        return
                    s = Path(root) / f
                    d = target / rel / f
                    done += _copy_file(s, d, lambda n: progress and progress(done + n, total, f))
                    progress and progress(done, total, f)
        else:
            done += _copy_file(src, target, lambda n: progress and progress(done + n, total, src.name))
            progress and progress(done, total, src.name)
        if move:
            if src.is_dir() and not src.is_symlink():
                shutil.rmtree(src, ignore_errors=True)
            else:
                src.unlink(missing_ok=True)


def _copy_file(src: Path, dst: Path, cb) -> int:
    if src.is_symlink():
        os.symlink(os.readlink(src), dst)
        return 0
    size = 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            chunk = fi.read(1024 * 1024)
            if not chunk:
                break
            fo.write(chunk)
            size += len(chunk)
            cb(size)
    shutil.copystat(src, dst, follow_symlinks=False)
    return size


# --- freedesktop.org trash (Recycle Bin) ---------------------------------

def trash(path) -> Path:
    path = Path(path).absolute()
    files, info = TRASH / "files", TRASH / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    name = path.name
    target = files / name
    n = 1
    while target.exists() or (info / f"{target.name}.trashinfo").exists():
        n += 1
        target = files / f"{path.stem}.{n}{path.suffix}"
    (info / f"{target.name}.trashinfo").write_text(
        "[Trash Info]\n"
        f"Path={urllib.parse.quote(str(path))}\n"
        f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
    try:
        os.rename(path, target)
    except OSError:
        if path.is_dir():
            shutil.copytree(path, target, symlinks=True)
            shutil.rmtree(path)
        else:
            shutil.copy2(path, target)
            path.unlink()
    return target


def trash_items():
    """Yield (trashed_path, original_path, deletion_date)."""
    info = TRASH / "info"
    if not info.is_dir():
        return []
    out = []
    for f in sorted(info.glob("*.trashinfo")):
        orig, date = "", ""
        for line in f.read_text(errors="replace").splitlines():
            if line.startswith("Path="):
                orig = urllib.parse.unquote(line[5:])
            elif line.startswith("DeletionDate="):
                date = line[13:]
        out.append((TRASH / "files" / f.name[:-10], orig, date))
    return out


def restore(trashed: Path):
    info = TRASH / "info" / f"{trashed.name}.trashinfo"
    orig = None
    for line in info.read_text().splitlines():
        if line.startswith("Path="):
            orig = Path(urllib.parse.unquote(line[5:]))
    if orig is None:
        return
    orig.parent.mkdir(parents=True, exist_ok=True)
    target = orig if not orig.exists() else unique_name(orig)
    shutil.move(str(trashed), str(target))
    info.unlink(missing_ok=True)


def empty_trash():
    for sub in ("files", "info"):
        d = TRASH / sub
        if d.is_dir():
            for p in d.iterdir():
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)


def delete_permanently(path):
    p = Path(path)
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()


# --- archives ------------------------------------------------------------

def compress(paths, dest_zip: Path):
    paths = [Path(p) for p in paths]
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            if p.is_dir():
                for root, _, files in os.walk(p):
                    for f in files:
                        full = Path(root) / f
                        zf.write(full, full.relative_to(p.parent))
            else:
                zf.write(p, p.name)
    return dest_zip


def extract(archive: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                target = (dest / member).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise ValueError(f"unsafe path in archive: {member}")
            zf.extractall(dest)
    else:
        shutil.unpack_archive(str(archive), str(dest), filter="data") if _supports_filter() else \
            shutil.unpack_archive(str(archive), str(dest))
    return dest


def _supports_filter():
    import sys
    return sys.version_info >= (3, 12)


def fmt_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %I:%M %p", time.localtime(ts))


def type_name(path: Path, is_dir: bool) -> str:
    if is_dir:
        return "File folder"
    ext = path.suffix.lower().lstrip(".")
    names = {
        "txt": "Text Document", "md": "Markdown File", "pdf": "PDF Document", "png": "PNG File", "jpg": "JPG File",
        "jpeg": "JPEG File", "gif": "GIF File", "zip": "Compressed (zipped) Folder", "exe": "Application",
        "msi": "Windows Installer Package", "bat": "Windows Batch File", "cmd": "Windows Command Script",
        "sh": "Shell Script", "py": "Python File", "deb": "Debian Package", "mp3": "MP3 File", "mp4": "MP4 Video",
        "docx": "Word Document", "xlsx": "Excel Worksheet", "pptx": "PowerPoint Presentation", "odt": "OpenDocument Text",
        "html": "HTML Document", "json": "JSON File", "desktop": "Shortcut", "lnk": "Shortcut", "iso": "Disc Image File",
    }
    return names.get(ext, f"{ext.upper()} File" if ext else "File")
