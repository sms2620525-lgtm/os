# Fenestra OS - build & install
PREFIX   ?= /usr
DESTDIR  ?=
LIBDIR    = $(DESTDIR)$(PREFIX)/lib/fenestra
BINDIR    = $(DESTDIR)$(PREFIX)/bin
SHAREDIR  = $(DESTDIR)$(PREFIX)/share
PYTHON   ?= python3

.PHONY: all test lint install uninstall iso deb clean run

all: test

test:
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m pytest -q tests

lint:
	$(PYTHON) -m pyflakes fenestra tests || true

install:
	install -d $(LIBDIR) $(BINDIR) $(SHAREDIR)/fenestra $(SHAREDIR)/applications $(SHAREDIR)/xsessions \
	           $(SHAREDIR)/icons/hicolor $(SHAREDIR)/themes $(DESTDIR)/etc/skel $(DESTDIR)$(PREFIX)/lib/binfmt.d
	cp -r fenestra $(LIBDIR)/
	find $(LIBDIR) -name __pycache__ -prune -exec rm -rf {} +
	install -m 755 bin/* $(BINDIR)/
	install -m 644 data/applications/*.desktop $(SHAREDIR)/applications/
	install -m 644 data/xsessions/fenestra.desktop $(SHAREDIR)/xsessions/
	cp -r data/openbox data/picom $(SHAREDIR)/fenestra/
	install -m 644 data/xsettingsd.conf $(SHAREDIR)/fenestra/
	cp -r data/openbox/themes/Fenestra $(SHAREDIR)/themes/
	cp -rT data/skel $(DESTDIR)/etc/skel
	install -m 644 data/binfmt/fenestra-exe.conf $(DESTDIR)$(PREFIX)/lib/binfmt.d/
	QT_QPA_PLATFORM=offscreen PYTHONPATH=. $(PYTHON) -m fenestra.common.icons $(SHAREDIR)/icons/hicolor >/dev/null
	QT_QPA_PLATFORM=offscreen PYTHONPATH=. $(PYTHON) -m fenestra.shell.wallpaper 3840x2160 $(SHAREDIR)/fenestra/wallpaper.png >/dev/null
	QT_QPA_PLATFORM=offscreen PYTHONPATH=. $(PYTHON) -m fenestra.shell.wallpaper 3840x2160 $(SHAREDIR)/fenestra/wallpaper-dark.png --dark >/dev/null

uninstall:
	rm -rf $(LIBDIR) $(SHAREDIR)/fenestra $(SHAREDIR)/themes/Fenestra
	rm -f $(BINDIR)/fenestra-* $(BINDIR)/bat2sh $(SHAREDIR)/xsessions/fenestra.desktop
	rm -f $(SHAREDIR)/applications/fenestra-*.desktop $(DESTDIR)$(PREFIX)/lib/binfmt.d/fenestra-exe.conf
	rm -f $(SHAREDIR)/icons/hicolor/*/apps/fenestra-*.png

iso:
	cd distro && sudo ./build.sh

run:
	PYTHONPATH=. $(PYTHON) -m fenestra.shell

clean:
	rm -rf build dist .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +
