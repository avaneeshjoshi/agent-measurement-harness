"""Arrow-key selection, reference-style: options live inside the question
box, ↑/↓ (or j/k) move the [x], Enter confirms. Zero-dep (termios); when
stdin isn't a TTY the caller's flag/text fallback applies instead."""

from __future__ import annotations

import sys

from .style import S, box, visible_len


def _apply_key(key: str, idx: int, n: int) -> tuple[int, bool | None]:
    """Pure key -> (new_index, decision). decision: True=confirm current,
    None=keep navigating. Testable without a terminal."""
    if key in ("up", "k"):
        return (idx - 1) % n, None
    if key in ("down", "j", "\t"):
        return (idx + 1) % n, None
    if key in ("enter",):
        return idx, True
    if key.isdigit() and 1 <= int(key) <= n:
        return int(key) - 1, True
    return idx, None


def _read_key(stdin) -> str:
    import select as _select
    ch = stdin.read(1)
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch == "\x1b":
        # arrow keys arrive as ESC [ A/B; a bare ESC has no follow-up bytes
        r, _, _ = _select.select([stdin], [], [], 0.05)
        if not r:
            return "esc"
        seq = stdin.read(1)
        if seq == "[":
            final = stdin.read(1)
            return {"A": "up", "B": "down"}.get(final, "")
        return ""
    return ch.lower()


def _render(title: str, prompt: str, options: list[str], idx: int) -> str:
    lines = [S.dim(title), "", S.bold(prompt), ""]
    for i, opt in enumerate(options):
        if i == idx:
            lines.append(f"  {S.accent('[x]')} {S.bold(opt)}")
        else:
            lines.append(f"  {S.dim('[ ]')} {S.dim(opt)}")
    return box(*lines)


def choose(title: str, prompt: str, options: list[str], default: int = 0) -> int | None:
    """Interactive pick; returns the chosen index, or None when stdin isn't
    interactive (caller falls back). Esc selects the last option (the safe
    'not yet' slot by convention)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    import termios
    import tty

    idx = default
    block_text = _render(title, prompt, options, idx)
    n_lines = block_text.count("\n") + 1
    sys.stdout.write("\x1b[?25l")  # hide cursor
    print(block_text)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            key = _read_key(sys.stdin)
            if key == "esc":
                idx = len(options) - 1
                break
            new_idx, decided = _apply_key(key, idx, len(options))
            if new_idx != idx:
                idx = new_idx
                sys.stdout.write(f"\x1b[{n_lines}A")
                for line in _render(title, prompt, options, idx).split("\n"):
                    sys.stdout.write(f"\x1b[2K{line}\n")
                sys.stdout.flush()
            if decided:
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
    return idx
