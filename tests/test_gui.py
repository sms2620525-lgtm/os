"""Smoke tests: every window can be constructed and painted off-screen."""

import pytest

from fenestra.common import icons, theme


@pytest.fixture
def palette(qapp):
    return theme.apply(qapp)


def test_icons_render(qapp):
    for name in list(icons.COLOR_ICONS) + list(icons.GLYPHS) + ["start", "search"]:
        pm = icons.pixmap(name, 32)
        assert not pm.isNull()


def test_task_manager(palette, qapp):
    from fenestra.taskmgr.app import TaskManager
    w = TaskManager(palette)
    w.tick()
    for i in range(len(w.pages)):
        w.show_page(i)
    assert w.pages[0].bg_root.childCount() > 0
    assert not w.grab().isNull()
    w.timer.stop()
    w.close()


def test_explorer(palette, qapp, tmp_path):
    from fenestra.explorer.app import ExplorerWindow, SHELL_PC, SHELL_TRASH
    (tmp_path / "file.txt").write_text("x")
    w = ExplorerWindow(palette, str(tmp_path))
    w.new_tab(SHELL_PC)
    w.tab.navigate(SHELL_TRASH)
    w.tab.back()
    assert w.tab.location == SHELL_PC
    w.close_tab(1)
    w.tab.search("file")
    assert w.tab.search_view.topLevelItemCount() == 1
    for mode in ("details", "large", "small", "list", "tiles"):
        w.set_view(mode)
    assert not w.grab().isNull()
    w.close()


def test_settings(palette, qapp):
    from fenestra.settings.app import SettingsWindow
    w = SettingsWindow(palette, "system")
    for key in w.builders:
        w.show_page(key)
    assert not w.grab().isNull()
    w.close()


def test_compat_gui(palette, qapp, tmp_path):
    from fenestra.compat.gui import ConverterWindow
    from pebuilder import build_pe
    exe = build_pe(tmp_path / "app.exe", version={"ProductName": "Demo"})
    w = ConverterWindow(palette, str(exe))
    assert w.name_edit.text() == "Demo"
    assert w.convert_btn.isEnabled()
    w.close()


def test_shell_components(palette, qapp):
    from fenestra.shell.desktop import Desktop
    from fenestra.shell.flyouts import NotificationCenter, QuickSettings
    from fenestra.shell.startmenu import StartMenu
    from fenestra.shell.taskbar import Taskbar
    screen = qapp.primaryScreen()
    tb = Taskbar(palette, screen)
    sm = StartMenu(palette, tb)
    sm.on_search("file")
    assert sm.results.count() >= 1
    QuickSettings(palette)
    nc = NotificationCenter(palette)
    nc.add("Test", "Hello", "World")
    assert nc.list.count() == 1
    Desktop(palette, screen)
    tb.timer.stop()


def test_wallpaper(qapp):
    from fenestra.shell import wallpaper
    img = wallpaper.render(320, 180)
    assert img.width() == 320 and not img.isNull()


def test_windowed_shell(qapp):
    """The whole desktop inside one window (macOS / non-X11 mode)."""
    from fenestra.shell.main import Shell
    sh = Shell(qapp, windowed=True)
    sh.host.resize(1200, 800)
    qapp.processEvents()
    assert sh.taskbar.parent() is sh.host and sh.desktop.parent() is sh.host
    assert sh.taskbar.geometry().bottom() == sh.host.height() - 1
    x, y, w, h = sh._avail()
    assert w == 1200 and h == 800 - 48
    sh.taskbar.timer.stop()
    sh.server.close()
    sh.host.hide()
