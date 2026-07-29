"""Local-only web server for Pulse.

Binds to 127.0.0.1 by design: this interface shows personal work history and
must never be reachable from the network. No framework, no build step — the
standard library plus one static HTML file.
"""

import json
import logging
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent import paths
from agent.config import Config
from agent.web import api

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Local UI only: the browser page and this server are the same origin, so no
# cross-origin access is ever legitimate.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy":
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}


class PulseHandler(BaseHTTPRequestHandler):
    server_version = "Pulse"
    cfg: Config = Config({})

    def log_message(self, fmt, *args):  # quieter, and never logs query strings
        logger.debug("[web] %s", fmt % args)

    # ── plumbing ────────────────────────────────────────────────────────────
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _static(self, name: str) -> None:
        # Serve only files that actually live in the static directory.
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self._json({"error": "not_found"}, 404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), content_type)

    # ── routes ──────────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        one = lambda k, default=None: (query.get(k) or [default])[0]

        try:
            if route in ("/", "/index.html"):
                return self._static("index.html")
            if route.startswith("/static/"):
                return self._static(route[len("/static/"):])

            if route == "/api/status":
                return self._json(api.status(self.cfg))
            if route == "/api/briefing":
                return self._json(api.briefing(one("week")))
            if route == "/api/workstreams":
                return self._json(api.workstreams())
            if route == "/api/workstream":
                return self._json(api.workstream_detail(one("id", "")))
            if route == "/api/items":
                return self._json(api.items(kind=one("kind"), status_filter=one("status", "open")))
            if route == "/api/evidence":
                return self._json(api.evidence(query.get("id", [])))
            if route == "/api/item-history":
                return self._json(api.item_history(one("id", "")))
            if route == "/api/sync":
                return self._json(api.sync_history())
            if route == "/api/export":
                body = json.dumps(api.export(), indent=2, default=str).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", 'attachment; filename="pulse-export.json"')
                self.send_header("Content-Length", str(len(body)))
                for key, value in _SECURITY_HEADERS.items():
                    self.send_header(key, value)
                self.end_headers()
                return self.wfile.write(body)

            return self._json({"error": "not_found"}, 404)
        except Exception as exc:
            from agent.secrets import redact
            logger.error("[web] GET %s failed: %s", route, redact(str(exc)))
            return self._json({"error": "internal", "detail": redact(str(exc))[:200]}, 500)

    def do_POST(self) -> None:
        route = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 64_000)) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad_json"}, 400)

        try:
            if route == "/api/ask":
                question = str(payload.get("question", ""))[:1000]
                return self._json(api.ask(question, cfg=self.cfg))
            if route == "/api/test-connector":
                from agent.health import test_connector
                return self._json(test_connector(str(payload.get("source", "")), self.cfg))
            if route == "/api/purge":
                if payload.get("confirm") != "DELETE":
                    return self._json({"error": "confirmation_required"}, 400)
                return self._json(api.purge())
            return self._json({"error": "not_found"}, 404)
        except Exception as exc:
            from agent.secrets import redact
            logger.error("[web] POST %s failed: %s", route, redact(str(exc)))
            return self._json({"error": "internal", "detail": redact(str(exc))[:200]}, 500)


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8787) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Pulse's UI serves personal data and binds to localhost only.")
    PulseHandler.cfg = cfg
    httpd = ThreadingHTTPServer((host, port), PulseHandler)
    # ASCII only: Windows consoles default to cp1252 and raise UnicodeEncodeError
    # on arrows or middots, which would crash the server at startup.
    print(f"\n  Pulse UI -> http://{host}:{port}   (local only, Ctrl-C to stop)")
    print(f"  Data     -> {paths.DB_PATH}\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
    finally:
        httpd.server_close()
