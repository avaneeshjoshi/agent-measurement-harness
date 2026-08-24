"""caliper serve — the local interactive view (ADR-0016).

A read-only HTTP server bound to 127.0.0.1 on an ephemeral port. No
accounts, no network calls, no external assets, no telemetry — the trust
screen's promise stays literally true. It reads ~/.caliper through the same
load_data/summarize pair the static report uses and writes nothing
(enforced by test).

Freshness: pages re-read on every request THROUGH an mtime-keyed cache —
the bundle is cached against the source files' (path, mtime_ns, size)
signature plus the active filters, so a click after the hourly collector
writes sees fresh data, and a click that changes nothing re-parses nothing.
The page footer states when its bundle was loaded.
"""

from __future__ import annotations

import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from caliper.harness.report import views
from caliper.harness.report.generate import TOOLS, load_data, summarize


@dataclass(frozen=True)
class Locations:
    data_dir: Path
    classes_path: Path
    names_path: Path
    salt_file: Path


def default_locations() -> Locations:
    from .main import repo_root
    from .paths import extracted_dir, salt_path, state_dir, task_classes_path
    return Locations(
        data_dir=extracted_dir(),
        classes_path=task_classes_path(repo_root()),
        names_path=state_dir() / ".project_names.json",
        salt_file=salt_path(),
    )


class BundleCache:
    """load_data bundles keyed by (source mtime signature, filters)."""

    CAP = 8  # distinct (freshness, filter) states kept; oldest evicted

    def __init__(self, loc: Locations):
        self.loc = loc
        self._entries: dict = {}
        self._lock = threading.Lock()

    def _signature(self) -> tuple:
        files = [self.loc.classes_path, self.loc.names_path,
                 self.loc.data_dir / "git_history" / "production_signals.jsonl"]
        for tool in TOOLS:
            files.append(self.loc.data_dir / tool / "sessions.jsonl")
            files.append(self.loc.data_dir / tool / "prompt_units.jsonl")
        sig = []
        for p in files:
            try:
                st = p.stat()
                sig.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((str(p), None, None))
        return tuple(sig)

    def get(self, filters: dict) -> tuple[dict, str]:
        """-> (raw bundle, loaded-at stamp). Fresh whenever any source file
        changed; cached otherwise."""
        key = (self._signature(), tuple(sorted(filters.items())))
        with self._lock:
            hit = self._entries.get(key)
            if hit:
                return hit
        raw = load_data(self.loc.data_dir, self.loc.classes_path,
                        self.loc.names_path, self.loc.salt_file,
                        filters=filters, readonly=True)
        loaded = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            while len(self._entries) >= self.CAP:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = (raw, loaded)
        return raw, loaded


class ServeHandler(BaseHTTPRequestHandler):
    """Routes: / (overview), /repo/<ref>, /session/<id>, /coverage.
    No policy route (ADR-0014's gate stands), no writes anywhere."""

    cache: BundleCache  # set by serve()

    def log_message(self, *_a):  # no request logging — serve is quiet
        pass

    def _send(self, html: str, status: int = 200) -> None:
        data = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    RANGES = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        # ui = the URL state as given (what links and the form carry);
        # resolved = what load_data filters on. A range resolves to a from
        # date HERE, per request, so links stay relative ("last 7 days")
        # while the cache key holds the absolute date and naturally expires
        # at midnight.
        ui = {}
        for k in ("from", "to", "tool", "range", "split"):
            v = q.get(k, [""])[0]
            if not v:
                continue
            if k == "tool" and v not in TOOLS:
                continue
            if k == "range" and v not in (*self.RANGES, "all"):
                continue
            if k == "split" and v not in ("tool", "model"):
                continue
            if k in ("from", "to") and (len(v) != 10 or v[4] != "-"):
                continue
            ui[k] = v
        filters = {k: ui[k] for k in ("from", "to", "tool") if k in ui}
        days = self.RANGES.get(ui.get("range", ""))
        if days and "from" not in filters:  # an explicit date wins
            from datetime import date, timedelta
            filters["from"] = (date.today() - timedelta(days=days)).isoformat()
        try:
            raw, loaded = self.cache.get(filters)
            s = summarize(raw)
            path = u.path
            if path == "/":
                html = views.overview(raw, s, ui, loaded)
            elif path == "/coverage":
                html = views.coverage_view(raw, s, ui, loaded)
            elif path.startswith("/repo/"):
                html = views.repo_detail(raw, s, unquote(path[len("/repo/"):]),
                                         ui, loaded)
            elif path.startswith("/session/"):
                html = views.session_detail(
                    raw, s, unquote(path[len("/session/"):]), ui, loaded)
            else:
                html = None
            if html is None:
                self._send(views.not_found(path, ui, loaded), 404)
            else:
                self._send(html)
        except BrokenPipeError:
            pass
        except Exception as e:  # a failed render is said, not blank
            self._send("<!doctype html><meta charset='utf-8'>"
                       "<p>serve failed to render this view: "
                       f"{type(e).__name__}. The records on disk are "
                       "untouched — serve never writes.</p>", 500)


def serve(port: int | None = None, open_browser: bool = True,
          loc: Locations | None = None) -> int:
    from .style import S, sep, step

    ServeHandler.cache = BundleCache(loc or default_locations())
    httpd = ThreadingHTTPServer(("127.0.0.1", port or 0), ServeHandler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(step(sep("caliper serve", S.dim(url))))
    print(S.dim("  127.0.0.1 only · reads ~/.caliper read-only, writes "
                "nothing · Ctrl-C to stop"))
    if open_browser:
        threading.Timer(0.3, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
        print(step("serve stopped"))
    finally:
        httpd.server_close()
    return 0
