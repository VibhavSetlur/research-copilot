"""Terminal UI primitives — arrow keys, path autocomplete, multi-line paste.

Pure stdlib. On any POSIX terminal we drop into raw mode for the duration
of a single prompt so we can read arrow keys, Tab, Enter, Space, Esc, and
Ctrl+C without buffering. Outside a TTY (Windows, CI, piped stdin) we
transparently fall back to line-based prompts so the same call site works
in every environment.

Public API
----------
* ``select_one(label, options, default_index=0)``        — arrow-key list
* ``select_many(label, options, preselected=())``        — arrow + space
* ``text(label, default, completer=None, allow_empty=True)``
* ``multiline(label, sentinel="END")``                   — paste blob
* ``confirm(label, default=True)``                       — y/n with default
* ``raw_supported()``                                    — bool

All primitives respect ``NO_COLOR`` (per https://no-color.org/) and a
module-level ``disable_color()`` toggle. Ctrl+C raises ``KeyboardInterrupt``
to the caller so the wizard can show a clean "cancelled" message instead
of a traceback.
"""

from __future__ import annotations

import glob
import os
import sys
from typing import Callable, Iterable

# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------

try:  # POSIX raw-mode primitives. Missing on Windows; gracefully degrade.
    import select as _select
    import termios
    import tty
    _RAW_OK = True
except ImportError:  # pragma: no cover - Windows path
    _RAW_OK = False


def raw_supported() -> bool:
    """Whether we can drive arrow-key UIs (POSIX TTY + import succeeded)."""
    if not _RAW_OK:
        return False
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, OSError):
        return False


# ---------------------------------------------------------------------------
# ANSI
# ---------------------------------------------------------------------------


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return sys.stdout.isatty()
    except (AttributeError, OSError):
        return False


class _C:
    _on     = _supports_color()
    DIM     = "\033[2m"  if _on else ""
    BOLD    = "\033[1m"  if _on else ""
    RESET   = "\033[0m"  if _on else ""
    CYAN    = "\033[36m" if _on else ""
    GREEN   = "\033[32m" if _on else ""
    YELLOW  = "\033[33m" if _on else ""
    RED     = "\033[31m" if _on else ""
    MAGENTA = "\033[35m" if _on else ""
    BLUE    = "\033[34m" if _on else ""
    GREY    = "\033[90m" if _on else ""
    INVERT  = "\033[7m"  if _on else ""


def disable_color() -> None:
    for n in ("DIM", "BOLD", "RESET", "CYAN", "GREEN", "YELLOW",
              "RED", "MAGENTA", "BLUE", "GREY", "INVERT"):
        setattr(_C, n, "")


# ---------------------------------------------------------------------------
# Raw-mode key reader
# ---------------------------------------------------------------------------

KEY_UP    = "UP"
KEY_DOWN  = "DOWN"
KEY_LEFT  = "LEFT"
KEY_RIGHT = "RIGHT"
KEY_ENTER = "ENTER"
KEY_SPACE = "SPACE"
KEY_TAB   = "TAB"
KEY_ESC   = "ESC"
KEY_BACK  = "BACK"
KEY_PGUP  = "PGUP"
KEY_PGDN  = "PGDN"
KEY_HOME  = "HOME"
KEY_END   = "END"
KEY_DEL   = "DEL"


def _read_byte(timeout: float | None = None) -> str:
    """Read one byte from stdin's raw file descriptor.

    Bypasses Python's buffered text layer (``sys.stdin``) because in raw
    terminal mode multi-byte escape sequences for arrow keys arrive in a
    single OS-level read but the buffered layer can split them across
    calls, causing every arrow press to look like a bare ESC.

    Returns "" on a timeout (when ``timeout`` is set); raises EOFError
    on stream close.
    """
    fd = sys.stdin.fileno()
    if timeout is not None:
        if not _select.select([fd], [], [], timeout)[0]:
            return ""
    data = os.read(fd, 1)
    if not data:
        raise EOFError
    try:
        return data.decode(errors="replace")
    except UnicodeDecodeError:
        return ""


def _read_key() -> str:
    """Read a single keystroke from a POSIX TTY in raw mode. Returns the
    character itself for printable input, or one of the ``KEY_*`` symbols.

    Caller MUST have stdin in cbreak/raw mode (use ``_RawMode``). Blocks
    until a keystroke arrives.
    """
    ch = _read_byte()
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch == "\x04":
        raise EOFError
    if ch in ("\r", "\n"):
        return KEY_ENTER
    if ch == " ":
        return KEY_SPACE
    if ch == "\t":
        return KEY_TAB
    if ch in ("\x7f", "\b"):
        return KEY_BACK
    if ch != "\x1b":
        return ch

    # Escape sequence. Use select with a small (but not too small) timeout
    # to disambiguate a bare ESC press from a multi-byte sequence.
    # 50ms is comfortable for local PTYs + most ssh latency without
    # making bare Esc feel laggy.
    next_ch = _read_byte(timeout=0.05)
    if not next_ch:
        return KEY_ESC
    if next_ch != "[":
        return KEY_ESC
    # CSI sequence: read until a terminator letter.
    seq = ""
    while True:
        ch2 = _read_byte(timeout=0.05)
        if not ch2:
            break
        seq += ch2
        if ch2.isalpha() or ch2 == "~":
            break
    table = {
        "A":  KEY_UP,   "B":  KEY_DOWN, "C":  KEY_RIGHT, "D":  KEY_LEFT,
        "H":  KEY_HOME, "F":  KEY_END,
        "5~": KEY_PGUP, "6~": KEY_PGDN, "3~": KEY_DEL,
        "1~": KEY_HOME, "4~": KEY_END,
    }
    return table.get(seq, KEY_ESC)


class _RawMode:
    """Context manager that flips stdin into cbreak mode for the duration
    of a prompt. Restores the original termios state on exit so terminal
    behaviour is never left wedged."""

    def __init__(self) -> None:
        self.fd = sys.stdin.fileno()
        self.old = None
        self.hidden_cursor = False

    def __enter__(self) -> "_RawMode":
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        # Hide cursor while a list prompt redraws itself.
        if _supports_color():
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
            self.hidden_cursor = True
        return self

    def __exit__(self, *exc) -> None:
        if self.old is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        if self.hidden_cursor:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _clear_lines(n: int) -> None:
    """Move up N lines and clear from cursor to end of screen."""
    if n <= 0:
        return
    sys.stdout.write(f"\033[{n}A\033[J")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Single-select
# ---------------------------------------------------------------------------


def select_one(
    label: str,
    options: list[tuple[str, str]],
    default_index: int = 0,
    help_line: str = "",
) -> str:
    """Arrow-key single-select.

    ``options`` is a list of ``(value, label)``. Returns the selected value.
    Falls back to a numbered prompt on non-TTY environments.
    """
    if not raw_supported():
        return _select_one_fallback(label, options, default_index)

    idx = max(0, min(default_index, len(options) - 1))
    rendered = 0

    def _draw() -> int:
        lines = []
        lines.append(f"  {label}")
        if help_line:
            lines.append(f"  {_C.DIM}{help_line}{_C.RESET}")
        for i, (_, opt_label) in enumerate(options):
            if i == idx:
                marker = f"{_C.CYAN}{_C.BOLD}❯{_C.RESET}"
                text = f"{_C.CYAN}{_C.BOLD}{opt_label}{_C.RESET}"
            else:
                marker = " "
                text = opt_label
            lines.append(f"    {marker} {text}")
        lines.append(f"  {_C.GREY}↑/↓ navigate · Enter select · Esc cancel{_C.RESET}")
        out = "\n".join(lines)
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
        return len(lines)

    with _RawMode():
        rendered = _draw()
        while True:
            try:
                key = _read_key()
            except KeyboardInterrupt:
                _clear_lines(rendered)
                raise
            if key == KEY_UP:
                idx = (idx - 1) % len(options)
            elif key == KEY_DOWN:
                idx = (idx + 1) % len(options)
            elif key == KEY_HOME or key == "g":
                idx = 0
            elif key == KEY_END or key == "G":
                idx = len(options) - 1
            elif key == KEY_ENTER:
                break
            elif key == KEY_ESC:
                _clear_lines(rendered)
                raise KeyboardInterrupt
            else:
                # Number shortcut.
                if key.isdigit():
                    n = int(key) - 1
                    if 0 <= n < len(options):
                        idx = n
            _clear_lines(rendered)
            rendered = _draw()
    # Replace the menu with a single confirmation line so the chat history
    # stays clean when the user scrolls back.
    _clear_lines(rendered)
    sys.stdout.write(
        f"  {_C.GREEN}✓{_C.RESET} {label}  "
        f"{_C.GREY}→{_C.RESET} {_C.BOLD}{options[idx][1]}{_C.RESET}\n"
    )
    sys.stdout.flush()
    return options[idx][0]


def _select_one_fallback(label, options, default_index):
    print(f"  {label}")
    for i, (_, opt_label) in enumerate(options):
        mark = "❯" if i == default_index else " "
        print(f"    {mark} {i + 1}. {opt_label}")
    while True:
        try:
            raw = input(f"  Pick a number [{default_index + 1}] ").strip()
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt
        if not raw:
            return options[default_index][0]
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except ValueError:
            pass
        print(f"  {_C.YELLOW}Enter a number 1..{len(options)}.{_C.RESET}")


# ---------------------------------------------------------------------------
# Multi-select
# ---------------------------------------------------------------------------


def select_many(
    label: str,
    options: list[tuple[str, str, str]],
    preselected: Iterable[str] = (),
    help_line: str = "",
) -> list[str]:
    """Arrow-key multi-select. ``options`` is ``(value, label, hint)``.

    Space toggles, ``a`` toggles all, ``n`` clears, Enter confirms.
    """
    if not raw_supported():
        return _select_many_fallback(label, options, preselected)

    sel = set(preselected)
    idx = 0
    rendered = 0

    def _draw() -> int:
        lines = []
        lines.append(f"  {label}")
        if help_line:
            lines.append(f"  {_C.DIM}{help_line}{_C.RESET}")
        for i, (val, opt_label, hint) in enumerate(options):
            mark = f"{_C.GREEN}{_C.BOLD}■{_C.RESET}" if val in sel else f"{_C.GREY}□{_C.RESET}"
            cursor = f"{_C.CYAN}{_C.BOLD}❯{_C.RESET}" if i == idx else " "
            text = opt_label
            if i == idx:
                text = f"{_C.BOLD}{text}{_C.RESET}"
            suffix = f"  {_C.GREY}— {hint}{_C.RESET}" if hint else ""
            lines.append(f"    {cursor} {mark} {text}{suffix}")
        chosen = sum(1 for v, _, _ in options if v in sel)
        lines.append(
            f"  {_C.GREY}↑/↓ move · Space toggle · 'a' all · 'n' none · "
            f"Enter confirm ({chosen}/{len(options)} selected){_C.RESET}"
        )
        out = "\n".join(lines)
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
        return len(lines)

    with _RawMode():
        rendered = _draw()
        while True:
            try:
                key = _read_key()
            except KeyboardInterrupt:
                _clear_lines(rendered)
                raise
            if key == KEY_UP:
                idx = (idx - 1) % len(options)
            elif key == KEY_DOWN:
                idx = (idx + 1) % len(options)
            elif key == KEY_SPACE:
                v = options[idx][0]
                sel.discard(v) if v in sel else sel.add(v)
            elif key in ("a", "A"):
                if len(sel) == len(options):
                    sel.clear()
                else:
                    sel = {v for v, _, _ in options}
            elif key in ("n", "N"):
                sel.clear()
            elif key == KEY_ENTER:
                break
            elif key == KEY_ESC:
                _clear_lines(rendered)
                raise KeyboardInterrupt
            _clear_lines(rendered)
            rendered = _draw()
    _clear_lines(rendered)
    chosen_labels = [opt_label for v, opt_label, _ in options if v in sel]
    summary = ", ".join(chosen_labels) if chosen_labels else _C.YELLOW + "(none)" + _C.RESET
    sys.stdout.write(
        f"  {_C.GREEN}✓{_C.RESET} {label}  {_C.GREY}→{_C.RESET} {summary}\n"
    )
    sys.stdout.flush()
    return [v for v, _, _ in options if v in sel]


def _select_many_fallback(label, options, preselected):
    sel = set(preselected)
    print(f"  {label}")
    for i, (val, opt_label, hint) in enumerate(options):
        mark = "[x]" if val in sel else "[ ]"
        h = f"  — {hint}" if hint else ""
        print(f"    {mark} {i + 1}. {opt_label}{h}")
    print(f"  {_C.GREY}Type numbers to toggle (e.g. '1,3'), 'all', 'none', or Enter.{_C.RESET}")
    while True:
        try:
            raw = input("  › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt
        if not raw:
            return [v for v, _, _ in options if v in sel]
        if raw == "all":
            sel = {v for v, _, _ in options}
        elif raw == "none":
            sel = set()
        else:
            try:
                toks = [int(x.strip()) for x in raw.split(",") if x.strip()]
                for t in toks:
                    if 1 <= t <= len(options):
                        v = options[t - 1][0]
                        sel.discard(v) if v in sel else sel.add(v)
            except ValueError:
                print(f"  {_C.YELLOW}Could not parse.{_C.RESET}")


# ---------------------------------------------------------------------------
# Text input with optional path autocomplete
# ---------------------------------------------------------------------------


PathCompleter = Callable[[str], list[str]]


def path_completer(token: str) -> list[str]:
    """Return filesystem entries matching ``token`` as a glob prefix.

    Expands ``~``, handles relative + absolute paths, appends ``/`` to
    directory matches so successive Tabs descend cleanly.
    """
    expanded = os.path.expanduser(token) if token else ""
    if not expanded:
        candidates = sorted(p for p in os.listdir(".") if not p.startswith("."))
        return candidates[:50]
    if expanded.endswith(os.sep) or os.path.isdir(expanded):
        base = expanded.rstrip(os.sep) or expanded
        if not os.path.isdir(base):
            return []
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            return []
        # Don't show hidden files unless user typed a leading dot.
        entries = [e for e in entries if not e.startswith(".")]
        return [os.path.join(base, e) for e in entries[:50]]
    # Prefix match: glob expand.
    matches = sorted(glob.glob(expanded + "*"))
    return [m for m in matches if not os.path.basename(m).startswith(".")][:50]


def text(
    label: str,
    default: str = "",
    placeholder: str = "",
    completer: PathCompleter | None = None,
    allow_empty: bool = True,
) -> str:
    """Single-line text input. Honors Tab autocompletion when ``completer``
    is supplied. Backspace deletes; Enter submits; Esc cancels.

    The label is printed once and stays put — only the input line below
    it is redrawn on each keystroke, so the terminal doesn't fill with
    duplicate prompt lines as the user types.
    """
    if not raw_supported():
        return _text_fallback(label, default, placeholder, allow_empty)

    # Print the label + hint ONCE. From here on we only redraw the row
    # below it (the actual input line + any autocomplete candidates).
    suffix = ""
    if default:
        suffix = f"  {_C.GREY}[default: {default}]{_C.RESET}"
    elif placeholder:
        suffix = f"  {_C.GREY}({placeholder}){_C.RESET}"
    print(f"  {label}{suffix}")

    buf = ""
    cursor = 0
    # Lines printed BELOW the input row (autocomplete candidates) — we
    # clear them on the next redraw so old candidates don't linger.
    candidate_lines = 0

    def _common_prefix(strs: list[str]) -> str:
        if not strs:
            return ""
        s1 = min(strs)
        s2 = max(strs)
        for i, c in enumerate(s1):
            if i >= len(s2) or s2[i] != c:
                return s1[:i]
        return s1

    def _draw_input() -> None:
        """Redraw the input row (and clear any stale completer suggestions
        below it). Cursor stays inside the input line."""
        nonlocal candidate_lines
        # If we showed completer candidates last time, walk down past them
        # and clear from cursor to end of screen, then walk back up.
        if candidate_lines > 0:
            sys.stdout.write(f"\033[{candidate_lines}B\033[J")
            sys.stdout.write(f"\033[{candidate_lines}A")
            candidate_lines = 0
        # Clear the input row and rewrite it.
        sys.stdout.write("\r\033[K")
        sys.stdout.write(f"  {_C.CYAN}›{_C.RESET} {buf}")
        # Place cursor at position (5 + cursor) — 2 spaces + arrow + space.
        sys.stdout.write(f"\r\033[{5 + cursor}G")
        sys.stdout.flush()

    def _show_candidates(cands: list[str]) -> None:
        """Render up to 6 completer suggestions below the input row."""
        nonlocal candidate_lines
        preview_items = [os.path.basename(c.rstrip(os.sep)) or c for c in cands[:6]]
        preview = "  ".join(preview_items)
        suffix = f"  …+{len(cands) - 6}" if len(cands) > 6 else ""
        # Save cursor position, move down 1 line, write candidates, restore.
        sys.stdout.write(f"\n  {_C.DIM}{preview}{suffix}{_C.RESET}")
        sys.stdout.write("\033[A\r")  # back up to input row
        sys.stdout.write(f"\033[{5 + cursor}G")
        sys.stdout.flush()
        candidate_lines = 1

    with _RawMode():
        _draw_input()
        while True:
            try:
                key = _read_key()
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                raise
            if key == KEY_ENTER:
                if not buf and default:
                    buf = default
                if not buf and not allow_empty:
                    sys.stdout.write("\a")
                    continue
                break
            elif key == KEY_ESC:
                sys.stdout.write("\n")
                raise KeyboardInterrupt
            elif key == KEY_BACK:
                if cursor > 0:
                    buf = buf[: cursor - 1] + buf[cursor:]
                    cursor -= 1
            elif key == KEY_DEL:
                if cursor < len(buf):
                    buf = buf[:cursor] + buf[cursor + 1:]
            elif key == KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif key == KEY_RIGHT:
                cursor = min(len(buf), cursor + 1)
            elif key == KEY_HOME:
                cursor = 0
            elif key == KEY_END:
                cursor = len(buf)
            elif key == KEY_TAB and completer:
                cands = completer(buf)
                if len(cands) == 1:
                    buf = cands[0]
                    if os.path.isdir(os.path.expanduser(buf)) and not buf.endswith(os.sep):
                        buf += os.sep
                    cursor = len(buf)
                    _draw_input()
                    continue
                elif len(cands) > 1:
                    common = _common_prefix(cands)
                    if common and len(common) > len(buf):
                        buf = common
                        cursor = len(buf)
                        _draw_input()
                        continue
                    else:
                        _draw_input()
                        _show_candidates(cands)
                        continue
            elif key == KEY_SPACE:
                # Space is a regular character inside a text field.
                buf = buf[:cursor] + " " + buf[cursor:]
                cursor += 1
            elif len(key) == 1 and key.isprintable():
                buf = buf[:cursor] + key + buf[cursor:]
                cursor += 1
            _draw_input()
        # On commit: walk past any leftover candidates and write the newline.
        if candidate_lines:
            sys.stdout.write(f"\033[{candidate_lines}B\033[J")
            sys.stdout.write(f"\033[{candidate_lines}A")
            candidate_lines = 0
        sys.stdout.write("\n")
    return buf or default


def _text_fallback(label, default, placeholder, allow_empty):
    hint = f" [{default}]" if default else f" ({placeholder})" if placeholder else ""
    while True:
        try:
            raw = input(f"  {label}{hint} › ").strip()
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt
        val = raw or default
        if val or allow_empty:
            return val


# ---------------------------------------------------------------------------
# Secret (masked) input — for API keys, tokens, passwords
# ---------------------------------------------------------------------------


def secret(label: str, allow_empty: bool = True, mask_char: str = "•") -> str:
    """Single-line secret input with masked echo.

    On a POSIX TTY (raw mode), keystrokes are echoed as ``mask_char`` so
    onlookers cannot read the secret off the terminal. Backspace deletes
    the last character; Enter submits; Esc cancels. Outside a TTY
    (Windows, CI, piped stdin) we fall back to ``getpass.getpass`` which
    suppresses echo entirely.

    Used by the wizard's API-key collection step (W17) so freshly pasted
    keys never appear on screen.
    """
    if not raw_supported():
        import getpass
        while True:
            try:
                raw = getpass.getpass(f"  {label} › ")
            except (EOFError, KeyboardInterrupt):
                raise KeyboardInterrupt
            val = raw.strip()
            if val or allow_empty:
                return val

    print("  [secret input hidden]")

    buf = ""

    def _draw() -> None:
        sys.stdout.write("\r\033[K")
        sys.stdout.write(f"  {_C.CYAN}›{_C.RESET} {mask_char * len(buf)}")
        sys.stdout.flush()

    with _RawMode():
        _draw()
        while True:
            try:
                key = _read_key()
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                raise
            if key == KEY_ENTER:
                if not buf and not allow_empty:
                    sys.stdout.write("\a")
                    continue
                break
            elif key == KEY_ESC:
                sys.stdout.write("\n")
                raise KeyboardInterrupt
            elif key == KEY_BACK:
                if buf:
                    buf = buf[:-1]
            elif key == KEY_SPACE:
                buf += " "
            elif len(key) == 1 and key.isprintable():
                buf += key
            # Ignore arrow / nav keys — secrets are append-only.
            _draw()
        sys.stdout.write("\n")
    return buf


# ---------------------------------------------------------------------------
# Yes / No
# ---------------------------------------------------------------------------


def confirm(label: str, default: bool = True) -> bool:
    if not raw_supported():
        suffix = "[Y/n]" if default else "[y/N]"
        while True:
            try:
                raw = input(f"  {label} {suffix} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                raise KeyboardInterrupt
            if not raw:
                return default
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False
    # Raw mode: render as a 2-choice arrow-key prompt.
    options = [("y", "Yes"), ("n", "No")] if default else [("n", "No"), ("y", "Yes")]
    choice = select_one(label, options, default_index=0)
    return choice == "y"


# ---------------------------------------------------------------------------
# Multi-line paste capture
# ---------------------------------------------------------------------------


def multiline(label: str, sentinel: str = "END") -> str:
    """Capture multi-line input until the user types a line containing
    just ``sentinel`` (case-insensitive) or hits Ctrl+D.

    Always uses standard line-buffered input — raw mode would break
    line wrapping in pasted blocks.
    """
    print(f"  {label}")
    print(f"  {_C.DIM}Paste your text. Finish with a single line: "
          f"{_C.BOLD}{sentinel}{_C.RESET}{_C.DIM} (or Ctrl+D).{_C.RESET}")
    print(f"  {_C.GREY}{'─' * 60}{_C.RESET}")
    lines: list[str] = []
    while True:
        try:
            line = input("  ")
        except EOFError:
            break
        except KeyboardInterrupt:
            raise
        if line.strip().upper() == sentinel.upper():
            break
        lines.append(line)
    print(f"  {_C.GREY}{'─' * 60}{_C.RESET}")
    print(f"  {_C.GREEN}✓{_C.RESET} Captured {len(lines)} line(s).")
    return "\n".join(lines)
