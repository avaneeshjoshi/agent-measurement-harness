"""Terminal styling for the caliper CLI — zero-dependency ANSI.

Colors engage only on a TTY and honor NO_COLOR; piped/captured output stays
plain so scripts and tests never see escape codes."""

from __future__ import annotations

import os
import sys


def _enabled() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


class _S:
    def __init__(self):
        on = _enabled()
        def code(c):
            return (lambda t: f"\033[{c}m{t}\033[0m") if on else (lambda t: str(t))
        self.bold = code("1")
        self.dim = code("2")
        self.red = code("31")
        self.green = code("32")
        self.yellow = code("33")
        self.blue = code("34")
        self.magenta = code("35")
        self.cyan = code("36")
        self.bcyan = code("1;36")
        self.bgreen = code("1;32")
        self.byellow = code("1;33")
        self.bred = code("1;31")
        # violet accent (256-color); the interactive/identity color
        self.accent = code("38;5;105")
        self.baccent = code("1;38;5;105")


S = _S()

# geometric bullets: filled hex = a completed step, hollow hex = a child item
DONE = "⬢"
ITEM = "⬡"


def visible_len(s: str) -> int:
    """Display width ignoring ANSI escapes."""
    import re
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def sep(*parts) -> str:
    """Join non-empty parts with a dim middle dot, reference-style."""
    dot = S.dim(" · ")
    return dot.join(str(p) for p in parts if p)


def box(*lines: str, pad: int = 1) -> str:
    """Bordered panel like the reference's title/prompt boxes."""
    width = max((visible_len(l) for l in lines), default=0) + pad * 2
    top = S.dim("┌" + "─" * width + "┐")
    bot = S.dim("└" + "─" * width + "┘")
    body = []
    for l in lines:
        fill = " " * (width - pad - visible_len(l) - pad)
        body.append(S.dim("│") + " " * pad + l + fill + " " * pad + S.dim("│"))
    return "\n".join([top, *body, bot])


def step(text: str) -> str:
    """A completed top-level step: filled hex + text."""
    return f"{DONE} {text}"


def child(name: str, *details) -> str:
    """An indented child line: accent hollow hex, bold name, dim details."""
    tail = sep(*details)
    line = f"  {S.accent(ITEM)} {S.bold(name)}"
    return f"{line}{S.dim(' · ') + tail if tail else ''}"


import contextlib
import threading
import time


@contextlib.contextmanager
def spinner(text: str):
    """Hex-pulse activity indicator (⬡→⬢) while a slow step runs. TTY-only:
    piped output sees nothing. The line is cleared on exit so the completed
    ⬢ step line replaces it."""
    if not _enabled():
        yield
        return
    stop = threading.Event()

    def run():
        i = 0
        frames = (ITEM, DONE)
        while not stop.is_set():
            f = S.accent(frames[i % 2])
            sys.stdout.write(f"\r{f} {S.dim(text)}")
            sys.stdout.flush()
            stop.wait(0.4)
            i += 1

    t = threading.Thread(target=run, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=1)
        sys.stdout.write("\r\033[2K")
        sys.stdout.flush()


def count(n: int, kind: str) -> str | None:
    """A colored count. Zero returns None — silence means clean; callers
    filter Nones so '0 invalid 0 skipped' noise never prints."""
    if not n:
        return None
    styles = {"new": S.green, "updated": S.yellow, "unchanged": S.dim,
              "invalid": S.bred, "skipped": S.yellow, "solved": S.bgreen,
              "failed": S.red, "unclassified": S.yellow}
    return styles.get(kind, str)(f"{n} {kind}")


def relpath(p, root) -> str:
    """Repo-relative (or ~-relative) path — the absolute prefix is never
    useful on screen."""
    import os
    from pathlib import Path
    p, root = Path(p), Path(root)
    try:
        return str(p.relative_to(root))
    except ValueError:
        home = Path.home()
        try:
            return "~/" + str(p.relative_to(home))
        except ValueError:
            return str(p)
