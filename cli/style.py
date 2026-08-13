"""Terminal styling for the caliper CLI — zero-dependency ANSI.

Colors engage only on a TTY and honor NO_COLOR; piped/captured output stays
plain so scripts and tests never see escape codes."""

from __future__ import annotations

import os
import sys


def _enabled() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


# Pinned palette, Claude-Code-style: exact RGB per role so the look does NOT
# depend on the terminal theme's remapping of the 16 named ANSI colors. The
# background is never painted — only foregrounds are pinned. Roles: text,
# muted (all secondary/dim content), accent (identity/violet), semantic
# green/yellow/red, cyan (names/labels).
_PALETTES = {
    "dark": {"text": (232, 230, 224), "muted": (139, 137, 125),
             "accent": (129, 129, 245), "green": (99, 199, 119),
             "yellow": (222, 184, 106), "red": (224, 108, 117),
             "cyan": (108, 178, 202)},
    "light": {"text": (43, 43, 38), "muted": (128, 126, 116),
              "accent": (84, 84, 214), "green": (17, 119, 51),
              "yellow": (154, 103, 0), "red": (192, 44, 56),
              "cyan": (14, 116, 144)},
}
# Terminal.app and other non-truecolor terminals get the nearest 256-color.
_FALLBACK_256 = {
    "dark": {"text": 254, "muted": 245, "accent": 105, "green": 78,
             "yellow": 179, "red": 168, "cyan": 74},
    "light": {"text": 235, "muted": 243, "accent": 62, "green": 28,
              "yellow": 130, "red": 124, "cyan": 31},
}


def _theme() -> str:
    """CALIPER_THEME=dark|light wins; else infer from COLORFGBG (terminals
    export 'fg;bg', bg 0-6/8 = dark); else assume dark."""
    env = os.environ.get("CALIPER_THEME", "").lower()
    if env in ("dark", "light"):
        return env
    fgbg = os.environ.get("COLORFGBG", "")
    if ";" in fgbg:
        bg = fgbg.rsplit(";", 1)[-1]
        if bg.isdigit():
            return "dark" if int(bg) in (0, 1, 2, 3, 4, 5, 6, 8) else "light"
    return "dark"


def _truecolor() -> bool:
    ct = os.environ.get("COLORTERM", "").lower()
    return "truecolor" in ct or "24bit" in ct


class _S:
    def __init__(self):
        on = _enabled()
        theme = _theme()
        tc = _truecolor()

        def fg(role, bold=False):
            if not on:
                return lambda t: str(t)
            if tc:
                r, g, b = _PALETTES[theme][role]
                color = f"38;2;{r};{g};{b}"
            else:
                color = f"38;5;{_FALLBACK_256[theme][role]}"
            prefix = "1;" if bold else ""
            return lambda t: f"\033[{prefix}{color}m{t}\033[0m"

        self.bold = fg("text", bold=True)
        self.dim = fg("muted")            # pinned gray, not ANSI dim
        self.red = fg("red")
        self.green = fg("green")
        self.yellow = fg("yellow")
        self.blue = fg("accent")
        self.magenta = fg("accent")
        self.cyan = fg("cyan")
        self.bcyan = fg("cyan", bold=True)
        self.bgreen = fg("green", bold=True)
        self.byellow = fg("yellow", bold=True)
        self.bred = fg("red", bold=True)
        self.accent = fg("accent")
        self.baccent = fg("accent", bold=True)


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


_EIGHTHS = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]


def bar(frac: float, width: int = 24, color=None) -> str:
    """Horizontal bar with eighth-block precision on a dim track."""
    frac = max(0.0, min(1.0, frac))
    cells = frac * width
    full = int(cells)
    eighth = int((cells - full) * 8)
    fill = "█" * full + _EIGHTHS[eighth]
    paint = color or S.accent
    track = S.dim("░" * (width - full - (1 if eighth else 0)))
    return paint(fill) + track


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
