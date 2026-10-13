from pathlib import Path

from fenestra.explorer import fileops


def test_unique_name(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert fileops.unique_name(f).name == "a - Copy.txt"
    (tmp_path / "a - Copy.txt").write_text("x")
    assert fileops.unique_name(f).name == "a - Copy (2).txt"
    assert fileops.new_name(tmp_path, "New folder").name == "New folder"


def test_transfer_copy_and_move(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "f.txt").write_text("hello")
    dst = tmp_path / "dst"
    dst.mkdir()
    progress = []
    fileops.transfer([src], dst, progress=lambda d, t, n: progress.append(d))
    assert (dst / "src" / "sub" / "f.txt").read_text() == "hello"
    assert progress
    fileops.transfer([src], dst, move=True)
    assert not src.exists()
    assert (dst / "src - Copy" / "sub" / "f.txt").exists()


def test_trash_restore_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(fileops, "TRASH", tmp_path / "Trash")
    f = tmp_path / "doc.txt"
    f.write_text("data")
    trashed = fileops.trash(f)
    assert not f.exists() and trashed.exists()
    items = fileops.trash_items()
    assert len(items) == 1 and items[0][1] == str(f)
    fileops.restore(trashed)
    assert f.read_text() == "data"
    fileops.trash(f)
    fileops.empty_trash()
    assert fileops.trash_items() == []


def test_zip_roundtrip(tmp_path):
    d = tmp_path / "folder"
    d.mkdir()
    (d / "a.txt").write_text("A")
    z = fileops.compress([d], tmp_path / "folder.zip")
    out = fileops.extract(z, tmp_path / "out")
    assert (Path(out) / "folder" / "a.txt").read_text() == "A"


def test_type_names():
    assert fileops.type_name(Path("x.exe"), False) == "Application"
    assert fileops.type_name(Path("x"), True) == "File folder"
    assert fileops.type_name(Path("x.abc"), False) == "ABC File"
