"""bat2sh - translate Windows batch files (.bat/.cmd) into Bash scripts.

Supported: echo, rem/::, set (plain, /a, /p, quoted), variable expansion
(%VAR%, !VAR!, %1..%9, %*, %~dp0, %~n1-style modifiers, substrings and
replacement), if (exist/defined/errorlevel/==/EQU.../not//i, else, blocks),
for (plain, /l, /f, /d), goto/labels (via a case-based state machine),
call :label, exit /b, pushd/popd, common built-ins (copy, del, dir, ...),
redirections to nul, and the ``&``, ``&&``, ``||`` and ``|`` operators.
Anything the translator does not understand is executed with Wine's
``cmd.exe`` so the script still works.
"""

import re

# --- helpers ---------------------------------------------------------------

LOOPVAR = re.compile(r"%%(~[a-z]*)?([A-Za-z])")


def _label_id(name: str) -> str:
    name = name.strip().lstrip(":").split()[0] if name.strip() else "eof"
    return "L_" + re.sub(r"[^A-Za-z0-9_]", "_", name.lower())


def _varname(name: str) -> str:
    name = name.strip()
    mapped = {
        "USERPROFILE": "HOME", "HOMEPATH": "HOME", "CD": "PWD", "USERNAME": "USER",
        "COMPUTERNAME": "HOSTNAME", "RANDOM": "RANDOM", "ERRORLEVEL": "?",
        "TEMP": "__TEMP", "TMP": "__TEMP", "APPDATA": "__APPDATA", "LOCALAPPDATA": "__LOCALAPPDATA",
        "PROGRAMFILES": "__PROGRAMFILES", "PROGRAMFILES(X86)": "__PROGRAMFILES86",
        "SYSTEMROOT": "__WINDIR", "WINDIR": "__WINDIR", "SYSTEMDRIVE": "__SYSTEMDRIVE",
        "DATE": "__DATE", "TIME": "__TIME", "PATH": "PATH", "OS": "__OS",
        "NUMBER_OF_PROCESSORS": "__NPROC", "PROCESSOR_ARCHITECTURE": "__ARCH",
    }
    up = name.upper()
    if up in mapped:
        return mapped[up]
    return re.sub(r"[^A-Za-z0-9_]", "_", up) or "_"


def _modifier(mod: str, ref: str) -> str:
    """Translate %~dpnx style modifiers applied to the bash expression ``ref``."""
    mod = (mod or "").lstrip("~").lower()
    if not mod:
        return f"${{{ref}}}" if not ref.startswith("$") else ref
    val = f'"${{{ref}}}"' if not ref.startswith("$") else f'"{ref}"'
    if "f" in mod and not ({"d", "p", "n", "x"} & set(mod)):
        return f"$(realpath -m {val})"
    parts = []
    if "d" in mod or "p" in mod:
        parts.append(f"$(cd \"$(dirname {val})\" 2>/dev/null && pwd)/")
    if "n" in mod and "x" in mod:
        parts.append(f"$(basename {val})")
    elif "n" in mod:
        parts.append(f"$(__name {val})")
    elif "x" in mod:
        parts.append(f"$(__ext {val})")
    if "s" in mod and not parts:
        return f"${{{ref}}}"
    if "z" in mod:
        parts.append(f"$(stat -c %s {val} 2>/dev/null)")
    if "t" in mod:
        parts.append(f"$(date -r {val} '+%Y-%m-%d %H:%M' 2>/dev/null)")
    return "".join(parts) or f"${{{ref}}}"


def expand(text: str, paths: bool = False) -> str:
    """Convert cmd text into the *inside* of a bash double-quoted string."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "%":
            m = LOOPVAR.match(text, i)
            if m:
                out.append(_modifier(m.group(1), m.group(2)))
                i = m.end()
                continue
            m = re.match(r"%(~[a-z]*)?([0-9])", text[i:], re.I)
            if m:
                ref = "0" if m.group(2) == "0" else m.group(2)
                if m.group(1) and m.group(1).lower() == "~dp" and ref == "0":
                    out.append("${__DP0}")
                else:
                    out.append(_modifier(m.group(1), ref))
                i += m.end()
                continue
            if text.startswith("%*", i):
                out.append("$*")
                i += 2
                continue
            m = re.match(r"%([^%\s=:]+):~(-?\d+)(?:,(-?\d+))?%", text[i:])
            if m:
                v, start, length = _varname(m.group(1)), m.group(2), m.group(3)
                if start.startswith("-"):
                    start = f" {start}"
                out.append(f"${{{v}:{start}" + (f":{length}" if length else "") + "}")
                i += m.end()
                continue
            m = re.match(r"%([^%\s=:]+):([^=%]+)=([^%]*)%", text[i:])
            if m:
                v = _varname(m.group(1))
                pat = m.group(2).replace("/", "\\/")
                out.append(f"${{{v}//{pat}/{m.group(3)}}}")
                i += m.end()
                continue
            m = re.match(r"%([^%\s]+)%", text[i:])
            if m:
                v = _varname(m.group(1))
                out.append("$?" if v == "?" else f"${{{v}}}")
                i += m.end()
                continue
            out.append("%")
            i += 1
            continue
        if c == "!":
            m = re.match(r"!([^!\s]+)!", text[i:])
            if m:
                out.append(f"${{{_varname(m.group(1))}}}")
                i += m.end()
                continue
        if c == "^" and i + 1 < n:
            c = text[i + 1]
            i += 1
        if paths and c == "\\":
            out.append("/")
        elif paths and c.isalpha() and text[i + 1:i + 2] == ":" and (i == 0 or not text[i - 1].isalnum()) \
                and (i + 2 >= n or text[i + 2] in "\\/"):
            out.append(f"${{WINEPREFIX:-$HOME/.wine}}/dosdevices/{c.lower()}:")
            i += 2
            continue
        elif c in '"$`':
            out.append("\\" + c)
        elif c == "\\":
            out.append("\\\\")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def dq(text: str, paths: bool = False) -> str:
    return '"' + expand(text, paths) + '"'


def split_words(text: str) -> list:
    """Split a cmd command line on whitespace, honouring double quotes."""
    words, cur, inq = [], "", False
    for ch in text:
        if ch == '"':
            inq = not inq
            cur += ch
        elif ch in " \t" and not inq:
            if cur:
                words.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        words.append(cur)
    return words


def word(w: str, paths: bool = True) -> str:
    if w.startswith('"') and w.endswith('"') and len(w) >= 2:
        return dq(w[1:-1], paths)
    if ("*" in w or "?" in w) and '"' not in w:
        parts = re.split(r"([*?])", w)
        return "".join(p if p in "*?" else (dq(p, paths) if p else "") for p in parts)
    return dq(w.replace('"', ""), paths)


def split_ops(line: str) -> list:
    """Split on unquoted &, &&, ||, | . Returns [(cmd, op_after)]."""
    parts, cur, i, inq, depth = [], "", 0, False, 0
    while i < len(line):
        ch = line[i]
        if ch == "^" and i + 1 < len(line):
            cur += line[i:i + 2]
            i += 2
            continue
        if ch == '"':
            inq = not inq
        elif not inq and ch == "(":
            depth += 1
        elif not inq and ch == ")":
            depth -= 1
        elif not inq and depth == 0 and ch in "&|":
            if line.startswith("&&", i) or line.startswith("||", i):
                parts.append((cur.strip(), line[i:i + 2]))
                i += 2
                cur = ""
                continue
            if ch == "|":
                parts.append((cur.strip(), "|"))
            elif cur.rstrip().endswith((">", "<")) or cur.endswith(">"):
                cur += ch  # 2>&1
                i += 1
                continue
            else:
                parts.append((cur.strip(), ";"))
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    parts.append((cur.strip(), ""))
    return [(c, op) for c, op in parts if c or op]


def match_paren(s: str, start: int) -> int:
    depth, inq = 0, False
    for i in range(start, len(s)):
        ch = s[i]
        if ch == '"':
            inq = not inq
        elif not inq:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
    return -1


# --- condition translation -------------------------------------------------

CMP_OPS = {"equ": "-eq", "neq": "-ne", "lss": "-lt", "leq": "-le", "gtr": "-gt", "geq": "-ge"}


def parse_condition(rest: str):
    """Return (bash_condition, remaining_text)."""
    s = rest.lstrip()
    neg = ""
    icase = False
    while True:
        low = s.lower()
        if low.startswith("/i "):
            icase, s = True, s[3:].lstrip()
        elif low.startswith("not "):
            neg, s = ("" if neg else "! "), s[4:].lstrip()
        else:
            break
    low = s.lower()
    if low.startswith("exist "):
        ws = split_words(s[6:])
        target = ws[0] if ws else ""
        remaining = s[6:].lstrip()[len(target):]
        return f"{neg}[ -e {word(target)} ]", remaining
    if low.startswith("defined "):
        ws = split_words(s[8:])
        remaining = s[8:].lstrip()[len(ws[0]):]
        return f'{neg}[ -n "${{{_varname(ws[0])}+x}}" ]', remaining
    if low.startswith("errorlevel "):
        ws = split_words(s[11:])
        remaining = s[11:].lstrip()[len(ws[0]):]
        return f"{neg}[ $? -ge {ws[0]} ]", remaining
    # a==b  or  a OP b
    m = re.match(r'("[^"]*"|[^\s=]+)\s*==\s*("[^"]*"|\S+)', s)
    if m:
        a, b = word(m.group(1), False), word(m.group(2), False)
        cond = f"__ieq {a} {b}" if icase else f"[ {a} = {b} ]"
        return neg + cond, s[m.end():]
    m = re.match(r'("[^"]*"|\S+)\s+(equ|neq|lss|leq|gtr|geq)\s+("[^"]*"|\S+)', s, re.I)
    if m:
        a, op, b = word(m.group(1), False), CMP_OPS[m.group(2).lower()], word(m.group(3), False)
        if icase and op in ("-eq", "-ne"):
            cond = f"{'' if op == '-eq' else '! '}__ieq {a} {b}"
        else:
            cond = f"__cmp {a} {op} {b}"
        return neg + cond, s[m.end():]
    return None, rest


# --- command translation ---------------------------------------------------

SIMPLE = {
    "cls": "clear", "ver": "uname -a", "vol": "df -h .", "whoami": "whoami", "hostname": "hostname",
    "tasklist": "ps aux", "ipconfig": "ip addr", "systeminfo": "uname -a; lscpu; free -h",
    "setlocal": ":", "endlocal": ":", "color": ":", "chcp": ":", "break": ":",
    "popd": "popd >/dev/null", "date": "date", "time": "date +%T", "path": 'echo "$PATH"',
    "pause": 'read -rsn1 -p "Press any key to continue . . . "; echo',
}

WINE_TOOLS = {"reg", "regedit", "msiexec", "regsvr32", "rundll32", "wscript", "cscript", "notepad",
              "control", "taskmgr", "explorer", "winecfg", "sc", "net", "netsh", "wmic", "icacls", "attrib",
              "assoc", "ftype", "mklink", "setx", "bcdedit", "certutil", "runas", "schtasks"}


def _flags(words):
    return [w for w in words if w.startswith("/")], [w for w in words if not w.startswith("/")]


def _redirects(text: str) -> str:
    text = re.sub(r"(\d?>>?)\s*nul\b", r"\1/dev/null", text, flags=re.I)
    text = re.sub(r"<\s*nul\b", "</dev/null", text, flags=re.I)
    return text


def _split_redirect(cmd: str):
    """Separate trailing redirections (>file, 2>&1) from the command."""
    m = re.search(r"\s(\d?>>?&?\S*.*)$", " " + cmd)
    if not m:
        return cmd, ""
    idx = m.start(1) - 1
    redir = cmd[idx:].strip()
    tokens = re.findall(r"\d?>>?\s*(?:&\d|\"[^\"]*\"|\S+)|<\s*\S+", redir)
    out = []
    for t in tokens:
        mm = re.match(r"(\d?>>?|<)\s*(.*)", t)
        op, target = mm.group(1), mm.group(2)
        if target.startswith("&") or target.startswith("/dev/"):
            out.append(op + target)
        else:
            out.append(op + word(target))
    return cmd[:idx].rstrip(), " ".join(out)


def command(cmd: str) -> str:
    cmd = _redirects(cmd.strip())
    if not cmd:
        return ":"
    if cmd.startswith("@"):
        cmd = cmd[1:].lstrip()
    low = cmd.lower()
    head = re.split(r"[\s(]", low, maxsplit=1)[0]

    if head in ("rem",) or low.startswith("::"):
        return "# " + cmd[3:].strip() if head == "rem" else "# " + cmd[2:].strip()
    if head == "echo" or low.startswith(("echo.", "echo(", "echo:")):
        if low in ("echo off", "echo on"):
            return ":"
        body, redir = _split_redirect(cmd[5:] if len(cmd) > 4 else "")
        if low.startswith(("echo.", "echo(", "echo:")) and not body.strip():
            return ("echo " + redir).strip()
        if not body.strip():
            return "echo" + (" " + redir if redir else "")
        return f"echo {dq(body.rstrip())}" + (f" {redir}" if redir else "")

    cmd, redir = _split_redirect(cmd)
    low = cmd.lower()
    words = split_words(cmd)
    if not words:
        return redir or ":"
    head = words[0].lower()
    args = words[1:]
    tail = (" " + redir) if redir else ""

    def a(ws, paths=True):
        return " ".join(word(w, paths) for w in ws)

    if head in ("setlocal", "endlocal", "color", "chcp", "break", "@echo"):
        return ":"
    if head in SIMPLE and not args:
        return SIMPLE[head] + tail
    if head == "set":
        return _set(cmd[3:].strip()) + tail
    if head in ("cd", "chdir"):
        flags, rest = _flags(args)
        if not rest:
            return "pwd" + tail
        return f"cd {word(' '.join(rest).strip(chr(34)) if len(rest) > 1 else rest[0])}" + tail
    if re.fullmatch(r"[a-z]:", head):
        return f"cd {dq(head + chr(92), True)}"
    if head == "pushd":
        return f"pushd {a(args)} >/dev/null" + tail
    if head in ("copy", "xcopy", "robocopy"):
        flags, rest = _flags(args)
        rec = "-r " if head != "copy" else ""
        if len(rest) == 1:
            rest.append(".")
        return f"cp {rec}{a(rest)}" + tail
    if head in ("move",):
        flags, rest = _flags(args)
        return f"mv -f {a(rest)}" + tail
    if head in ("ren", "rename"):
        flags, rest = _flags(args)
        if len(rest) == 2:
            return f"mv {word(rest[0])} \"$(dirname {word(rest[0])})\"/{word(rest[1])}" + tail
        return f"mv {a(rest)}" + tail
    if head in ("del", "erase"):
        flags, rest = _flags(args)
        return f"rm -f {a(rest)}" + tail
    if head in ("rd", "rmdir"):
        flags, rest = _flags(args)
        if any(f.lower() == "/s" for f in flags):
            return f"rm -rf {a(rest)}" + tail
        return f"rmdir {a(rest)}" + tail
    if head in ("md", "mkdir"):
        return f"mkdir -p {a(args)}" + tail
    if head == "type":
        return f"cat {a(args)}" + tail
    if head == "more":
        return (f"less {a(args)}" if args else "cat") + tail
    if head == "dir":
        flags, rest = _flags(args)
        fl = {f.lower() for f in flags}
        if "/b" in fl:
            return (f"ls -1 {a(rest)}" if "/s" not in fl else f"find {a(rest) or '.'}") + tail
        return f"ls -la {a(rest)}" + tail
    if head == "title":
        return f"printf '\\033]0;%s\\007' {dq(' '.join(args))}" + tail
    if head == "timeout":
        flags = [w.lower() for w in args]
        secs = next((args[i + 1] for i, w in enumerate(flags) if w == "/t" and i + 1 < len(args)), args[0] if args else "1")
        return f"sleep {secs.lstrip('/')}" + tail if secs not in ("-1",) else 'read -rsn1' + tail
    if head == "ping" and "-n" in [w.lower() for w in args]:
        return "ping -c " + " ".join(args[args.index(next(w for w in args if w.lower() == "-n")) + 1:]) + tail
    if head in ("findstr", "find"):
        flags, rest = _flags(args)
        opts = ""
        fl = {f.lower() for f in flags}
        if "/i" in fl:
            opts += "i"
        if "/v" in fl:
            opts += "v"
        if "/n" in fl:
            opts += "n"
        if "/c" in fl and head == "find":
            opts += "c"
        if not rest:
            return "grep" + tail
        pat = rest[0].strip('"')
        if head == "find":
            return f"grep -F{opts} {dq(pat)} {a(rest[1:])}".rstrip() + tail
        return f"grep -E{opts} {dq(pat.replace(' ', '|'))} {a(rest[1:])}".rstrip() + tail
    if head == "start":
        rest = list(args)
        if rest and rest[0].startswith('"'):
            rest = rest[1:]  # window title
        rest = [w for w in rest if w.lower() not in ("/b", "/wait", "/min", "/max")]
        if not rest:
            return "x-terminal-emulator &"
        target = rest[0].strip('"').lower()
        if target.endswith((".exe", ".msi", ".bat", ".cmd")):
            return f"fenestra-compat run {a(rest)} &" + tail
        return f"xdg-open {a(rest[:1])} >/dev/null 2>&1 &" + tail
    if head == "taskkill":
        lw = [w.lower() for w in args]
        if "/im" in lw:
            name = args[lw.index("/im") + 1]
            return f"pkill -f {word(name, False)}" + tail
        if "/pid" in lw:
            return f"kill -9 {args[lw.index('/pid') + 1]}" + tail
    if head == "shutdown":
        lw = [w.lower() for w in args]
        if "/r" in lw:
            return "systemctl reboot" + tail
        if "/l" in lw:
            return "loginctl terminate-user \"$USER\"" + tail
        if "/a" in lw:
            return "shutdown -c" + tail
        return "systemctl poweroff" + tail
    if head == "choice":
        lw = [w.lower() for w in args]
        choices = args[lw.index("/c") + 1] if "/c" in lw else "YN"
        msg = args[lw.index("/m") + 1].strip('"') if "/m" in lw else ""
        return (f"__choice {dq(choices)} {dq(msg)}") + tail
    if head == "exit":
        lw = [w.lower() for w in args]
        code = next((w for w in args if w.isdigit() or w.startswith("%")), "")
        code = expand(code) if code else ("$?" if "/b" in lw else "")
        return f"exit {code}".rstrip()
    if head == "goto":
        target = args[0] if args else ":eof"
        if target.lower().lstrip(":") == "eof":
            return "exit"
        return f"__label={_label_id(target)}; continue 99"
    if head == "call":
        if args and args[0].startswith(":"):
            return f"\"$BASH\" \"$0\" __fenestra_call {_label_id(args[0])} {a(args[1:], False)}".rstrip() + tail
        if args:
            return command(" ".join(args)) + tail
    if head in ("powershell", "powershell.exe", "pwsh"):
        return f"pwsh {a(args, False)}" + tail
    if head in ("cmd", "cmd.exe"):
        lw = [w.lower() for w in args]
        if "/c" in lw or "/k" in lw:
            idx = lw.index("/c") if "/c" in lw else lw.index("/k")
            inner = " ".join(args[idx + 1:]).strip()
            if inner.startswith('"') and inner.endswith('"'):
                inner = inner[1:-1]
            return translate_line(inner) + tail
    if head.endswith((".bat", ".cmd")):
        return f"fenestra-compat run {a(words)}" + tail
    if head.endswith((".exe", ".com", ".msi")):
        return f"wine {a(words)}" + tail
    if head in WINE_TOOLS:
        return f"wine {head} {a(args, False)}".rstrip() + tail
    if head in ("if", "for"):
        return translate_line(cmd) + tail
    # Unknown: if it looks like a Linux command run it, else defer to Wine's cmd.
    return f"__wincmd {dq(cmd)}" + tail


def _set(rest: str) -> str:
    low = rest.lower()
    if not rest:
        return "env"
    if low.startswith("/a"):
        expr = rest[2:].strip().strip('"')
        expr = re.sub(r"%([^%]+)%", lambda m: _varname(m.group(1)), expr)
        expr = re.sub(r"!([^!]+)!", lambda m: _varname(m.group(1)), expr)
        expr = re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda m: _varname(m.group(0)), expr)
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*([+\-*/%]?=)(.*)", expr)
        if m and m.group(2) == "=":
            return f"{m.group(1)}=$(( {m.group(3).strip()} ))"
        return f"(( {expr} ))"
    if low.startswith("/p"):
        body = rest[2:].strip()
        if body.startswith('"') and body.endswith('"'):
            body = body[1:-1]
        name, _, prompt = body.partition("=")
        return f"read -rp {dq(prompt)} {_varname(name)}"
    body = rest
    if body.startswith('"'):
        end = body.rfind('"')
        body = body[1:end] if end > 0 else body[1:]
    if "=" not in body:
        return f"env | grep -i {dq('^' + body)}"
    name, _, value = body.partition("=")
    name = _varname(name)
    if value == "":
        return f"unset {name}"
    return f"{name}={dq(value)}"


# --- statements: if / for ---------------------------------------------------

def _for_header(text: str):
    """Parse 'for [/l|/f|/d|/r] [opts] %%v in (set) do REST' -> (bash header, rest)."""
    m = re.match(r'for\s+(?:(/[lfdr])\s+)?(?:("[^"]*")\s+)?%%?([A-Za-z])\s+in\s*\(', text, re.I)
    if not m:
        return None, None
    flag = (m.group(1) or "").lower()
    opts = (m.group(2) or "").strip('"').lower()
    var = m.group(3)
    open_idx = m.end() - 1
    close = match_paren(text, open_idx)
    if close < 0:
        return None, None
    items = text[open_idx + 1:close].strip()
    after = text[close + 1:].lstrip()
    dm = re.match(r"do\s*", after, re.I)
    if not dm:
        return None, None
    rest = after[dm.end():]
    if flag == "/l":
        nums = [x.strip() for x in items.split(",")]
        start, step, end = (nums + ["1", "1", "1"])[:3]
        return f"for {var} in $(seq {expand(start)} {expand(step)} {expand(end)}); do", rest
    if flag == "/f":
        delims = re.search(r"delims=([^\s]*)", opts)
        ifs = delims.group(1) if delims else " \t"
        tokens = re.search(r"tokens=([^\s]+)", opts)
        rd = f"read -r {var}" if not tokens or tokens.group(1) in ("*", "1*") else f"read -r {var} __rest"
        if items.startswith("'") and items.endswith("'"):
            src = f"< <({translate_line(items[1:-1])})"
        elif items.startswith('"') and items.endswith('"') and "usebackq" not in opts:
            return f"for {var} in {dq(items[1:-1])}; do", rest
        else:
            src = f"< {word(items)}"
        return f"while IFS={dq(ifs) if ifs else chr(39) * 2} {rd}; do", rest + f"\x00{src}"
    if flag == "/d":
        return f"for {var} in {' '.join(word(w) for w in split_words(items))}; do [ -d \"${var}\" ] || continue;", rest
    if flag == "/r":
        return f"for {var} in $(find . -name {dq(items)}); do", rest
    return f"for {var} in {' '.join(word(w) for w in split_words(items))}; do", rest


class Translator:
    def __init__(self):
        self.out = []
        self.stack = []  # closers: 'fi', 'done', '}'

    def emit(self, line: str):
        self.out.append("  " * len(self.stack) + line)

    def close(self, closer):
        if "\x00" in closer:
            word_, src = closer.split("\x00", 1)
            self.emit(f"{word_} {src}")
        else:
            self.emit(closer)

    def statement(self, text: str):
        s = text.strip()
        if not s:
            return
        if s.startswith("@"):
            s = s[1:].lstrip()
        low = s.lower()
        if s.startswith(")"):
            rest = s[1:].strip()
            closer = self.stack.pop() if self.stack else "fi"
            m = re.match(r"else\s*(.*)$", rest, re.I)
            if m and closer == "fi":
                body = m.group(1).strip()
                if body.lower().startswith("if "):
                    cond, after = parse_condition(body[3:])
                    after = after.strip()
                    if after == "(":
                        self.emit(f"elif {cond}; then")
                        self.stack.append("fi")
                        return
                if body == "(":
                    self.emit("else")
                    self.stack.append("fi")
                    return
                self.emit("else")
                self.stack.append("fi")
                self.statement(body)
                self.close(self.stack.pop())
                return
            self.close(closer)
            if rest:
                self.statement(rest)
            return
        if s == "(":
            self.emit("{")
            self.stack.append("}")
            return
        if low.startswith("if "):
            self._if(s)
            return
        if low.startswith("for "):
            self._for(s)
            return
        self.emit(translate_ops(s))

    def _if(self, s):
        cond, rest = parse_condition(s[3:])
        if cond is None:
            self.emit(f"__wincmd {dq(s)}")
            return
        rest = rest.strip()
        if rest == "(":
            self.emit(f"if {cond}; then")
            self.stack.append("fi")
            return
        if rest.startswith("("):
            close = match_paren(rest, 0)
            if close < 0:  # block continues on following lines
                self.emit(f"if {cond}; then")
                self.stack.append("fi")
                self.statement(rest[1:])
                return
            then_part = rest[1:close]
            after = rest[close + 1:].strip()
            self.emit(f"if {cond}; then")
            self.stack.append("fi")
            for part in then_part.split("\n"):
                self.statement(part)
            m = re.match(r"else\s*(.*)$", after, re.I)
            if m:
                body = m.group(1).strip()
                self.stack.pop()
                self.emit("else")
                self.stack.append("fi")
                if body == "(":
                    return
                if body.startswith("("):
                    c2 = match_paren(body, 0)
                    if c2 < 0:
                        self.statement(body[1:])
                        return
                    self.statement(body[1:c2])
                else:
                    self.statement(body)
            self.close(self.stack.pop())
            return
        m = re.match(r"(.*?)\s+else\s+(.*)$", rest, re.I)
        self.emit(f"if {cond}; then")
        self.stack.append("fi")
        if m:
            self.statement(m.group(1))
            self.stack.pop()
            self.emit("else")
            self.stack.append("fi")
            self.statement(m.group(2))
        else:
            self.statement(rest)
        self.close(self.stack.pop())

    def _for(self, s):
        header, rest = _for_header(s)
        if header is None:
            self.emit(f"__wincmd {dq(s)}")
            return
        src = ""
        if "\x00" in rest:
            rest, src = rest.split("\x00", 1)
        closer = "done" + (f"\x00{src}" if src else "")
        rest = rest.strip()
        self.emit(header)
        self.stack.append(closer)
        if rest == "(":
            return
        if rest.startswith("("):
            close = match_paren(rest, 0)
            if close < 0:
                self.statement(rest[1:])
                return
            self.statement(rest[1:close])
        else:
            self.statement(rest)
        self.close(self.stack.pop())


def translate_ops(s: str) -> str:
    parts = split_ops(s)
    out = []
    for cmd, op in parts:
        if cmd.lower().startswith(("if ", "for ")):
            t = Translator()
            t.statement(cmd)
            while t.stack:
                t.close(t.stack.pop())
            out.append("; ".join(x.strip() for x in t.out))
        else:
            out.append(command(cmd))
        if op:
            out.append(op)
    return " ".join(out).replace(" ;", ";")


def translate_line(s: str) -> str:
    t = Translator()
    t.statement(s)
    while t.stack:
        t.close(t.stack.pop())
    return "; ".join(x.strip() for x in t.out)


HEADER = r'''#!/usr/bin/env bash
# Translated from {src} by Fenestra bat2sh.
# Unsupported commands are forwarded to Wine's cmd.exe via __wincmd.
if [ "${{BASH_VERSINFO[0]:-0}}" -lt 4 ]; then
  echo "This script needs bash 4 or newer (macOS: brew install bash)" >&2; exit 1
fi
__DP0="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)/"
__TEMP="${{TMPDIR:-/tmp}}"; __APPDATA="$HOME/.config"; __LOCALAPPDATA="$HOME/.local/share"
__WINEROOT="${{WINEPREFIX:-$HOME/.wine}}/drive_c"
__PROGRAMFILES="$__WINEROOT/Program Files"; __PROGRAMFILES86="$__WINEROOT/Program Files (x86)"
__WINDIR="$__WINEROOT/windows"; __SYSTEMDRIVE="C:"; __OS="Windows_NT"
USER="${{USER:-$(id -un)}}"; __NPROC="$(nproc)"; __ARCH="$(uname -m | sed 's/x86_64/AMD64/')"
__DATE="$(date +%Y-%m-%d)"; __TIME="$(date +%H:%M:%S.00)"
__name() {{ local b; b="$(basename "$1")"; echo "${{b%.*}}"; }}
__ext() {{ local b; b="$(basename "$1")"; [[ "$b" == *.* ]] && echo ".${{b##*.}}"; }}
__ieq() {{ [[ "${{1,,}}" == "${{2,,}}" ]]; }}
__cmp() {{ if [[ "$1" =~ ^-?[0-9]+$ && "$3" =~ ^-?[0-9]+$ ]]; then [ "$1" "$2" "$3" ];
  else case "$2" in -eq) [[ "$1" == "$3" ]];; -ne) [[ "$1" != "$3" ]];; -lt) [[ "$1" < "$3" ]];;
  -gt) [[ "$1" > "$3" ]];; -le) [[ "$1" < "$3" || "$1" == "$3" ]];; -ge) [[ "$1" > "$3" || "$1" == "$3" ]];; esac; fi; }}
__choice() {{ local c k i; while :; do read -rsn1 -p "$2 [${{1//?/&,}}]? " k; echo;
  for ((i=0;i<${{#1}};i++)); do c="${{1:i:1}}"; if [[ "${{c,,}}" == "${{k,,}}" ]]; then return $((i+1)); fi; done; done; }}
__wincmd() {{ if command -v wine >/dev/null; then wine cmd /c "$1"; else echo "bat2sh: unsupported: $1" >&2; return 1; fi; }}
'''


def translate(source: str, src_name: str = "script.bat") -> str:
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    # join ^ line continuations
    text = re.sub(r"\^\n", "", text)
    lines = text.split("\n")

    has_labels = any(re.match(r"\s*:[^:\s]", l) for l in lines)
    blocks = [("L___start", [])]
    for line in lines:
        m = re.match(r"\s*:([^:\s][^\s]*)", line)
        if m and has_labels:
            blocks.append((_label_id(m.group(1)), []))
        else:
            blocks[-1][1].append(line)

    body = []
    for label, blines in blocks:
        t = Translator()
        for line in blines:
            t.statement(line)
        while t.stack:
            t.close(t.stack.pop())
        body.append((label, t.out))

    out = [HEADER.format(src=src_name)]
    if not has_labels:
        out.extend(body[0][1])
        out.append("")
        return "\n".join(out)

    out.append('__label=L___start')
    out.append('if [ "$1" = "__fenestra_call" ]; then __label="$2"; shift 2; fi')
    out.append("while :; do")
    out.append('  case "$__label" in')
    for i, (label, lines_) in enumerate(body):
        out.append(f"  {label})")
        for l in lines_:
            out.append("    " + l)
        out.append("    ;&" if i < len(body) - 1 else "    break ;;")
    out.append("  *) echo \"bat2sh: unknown label $__label\" >&2; exit 1 ;;")
    out.append("  esac")
    out.append("done")
    out.append("")
    return "\n".join(out)
