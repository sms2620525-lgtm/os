import os
import subprocess

import pytest

from fenestra.compat import batch

# bat2sh output needs bash >= 4 (macOS ships 3.2; Homebrew installs a newer one)
BASH = next((b for b in ("/opt/homebrew/bin/bash", "/usr/local/bin/bash", "/bin/bash") if os.path.exists(b)), "bash")

SCRIPT = r"""@echo off
rem demo
setlocal enabledelayedexpansion
set NAME=World
set /a COUNT=0
echo Hello %NAME%!
if exist "%~dp0demo.bat" (
  echo found myself
) else (
  echo missing
)
for %%i in (a b c) do echo item %%i
for /l %%n in (1,1,3) do (
  set /a COUNT+=1
)
echo count=%COUNT%
if %COUNT% GEQ 3 (echo big) else (echo small)
if /i "%NAME%"=="world" echo case-insensitive
if not defined MISSING echo undefined ok
set STR=abcdef
echo %STR:~1,3%
echo %STR:cd=XY%
call :sub foo
mkdir out 2>nul & echo made > out\x.txt
type out\x.txt
del out\x.txt
rd /s /q out
goto end
echo skipped
:sub
echo in sub %1
exit /b 0
:end
echo done
"""

EXPECTED = """Hello World!
found myself
item a
item b
item c
count=3
big
case-insensitive
undefined ok
bcd
abXYef
in sub foo
made
done
"""


def test_translate_and_run(tmp_path):
    bat = tmp_path / "demo.bat"
    bat.write_text(SCRIPT.replace("\n", "\r\n"))
    sh = tmp_path / "demo.sh"
    sh.write_text(batch.translate(bat.read_text(), "demo.bat"))
    out = subprocess.run([BASH, str(sh)], cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    assert out.stdout == EXPECTED


@pytest.mark.parametrize("line,expected", [
    ("copy a.txt b.txt", 'cp "a.txt" "b.txt"'),
    ("del /q *.tmp", 'rm -f *".tmp"'),
    ("dir /b", "ls -1"),
    ("cls", "clear"),
    ("echo off", ":"),
    ("timeout /t 5 /nobreak", "sleep 5"),
    ("taskkill /im notepad.exe /f", 'pkill -f "notepad.exe"'),
    ("setup.exe /S", 'wine "setup.exe" "/S"'),
    ("reg add HKCU\\Software\\X", 'wine reg "add" "HKCU\\\\Software\\\\X"'),
    ("echo hi > nul", 'echo "hi" >/dev/null'),
])
def test_commands(line, expected):
    assert batch.translate_line(line).strip() == expected


def test_paths_are_converted():
    out = batch.translate_line(r"type C:\Users\me\file.txt")
    assert out == 'cat "${WINEPREFIX:-$HOME/.wine}/dosdevices/c:/Users/me/file.txt"'


def test_unknown_command_goes_to_wine_cmd():
    assert batch.translate_line("frobnicate /x").startswith("__wincmd")


def test_bash_syntax_valid():
    script = batch.translate(SCRIPT)
    r = subprocess.run([BASH, "-n"], input=script, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
