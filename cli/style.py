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


S = _S()


def header(title: str, sub: str = "") -> str:
    line = S.bold(f"◆ {title}")
    if sub:
        line += "  " + S.dim(sub)
    return line


def count(n: int, kind: str) -> str:
    """A colored count that goes quiet when zero."""
    styles = {"new": S.green, "updated": S.yellow, "unchanged": S.dim,
              "invalid": S.bred, "skipped": S.yellow, "solved": S.bgreen,
              "failed": S.red, "unclassified": S.yellow}
    style = styles.get(kind, str)
    label = f"{n} {kind}"
    return style(label) if n else S.dim(label)


def kv(key: str, value: str, pad: int = 14) -> str:
    return f"  {S.dim(key.ljust(pad))} {value}"


def path(p) -> str:
    return S.dim(str(p))


def arrow() -> str:
    return S.dim("→")


def rule(width: int = 56) -> str:
    return S.dim("─" * width)
