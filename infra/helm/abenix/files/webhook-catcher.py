"""Dev webhook catcher: keeps the last requests in memory so tests can read them back."""

import json
import threading
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

KEEP = 500
_seen: deque = deque(maxlen=KEEP)
_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def _capture(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        text = raw.decode("utf-8", "replace")
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            parsed = None
        with _lock:
            _seen.appendleft(
                {
                    "method": self.command,
                    "path": urlparse(self.path).path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": text,
                    "json": parsed,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        self._send(200, "ok", "text/plain")

    do_POST = _capture
    do_PUT = _capture
    do_PATCH = _capture

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/healthz":
            return self._send(200, "ok", "text/plain")
        if u.path == "/api/requests":
            want = (parse_qs(u.query).get("path") or [""])[0]
            with _lock:
                items = [r for r in _seen if not want or r["path"] == want]
            return self._send(200, json.dumps({"items": items}))
        with _lock:
            rows = "".join(
                f"<tr><td>{r['received_at']}</td><td>{r['path']}</td><td><pre>{r['body'][:2000]}</pre></td></tr>"
                for r in list(_seen)[:100]
            )
        page = (
            "<!doctype html><title>Webhook catcher</title>"
            "<h1>Webhook catcher</h1><p>Newest first. JSON at /api/requests?path=/your/path</p>"
            f"<table border=1 cellpadding=4><tr><th>When</th><th>Path</th><th>Body</th></tr>{rows}</table>"
        )
        return self._send(200, page, "text/html")

    def do_DELETE(self):
        if urlparse(self.path).path == "/api/requests":
            with _lock:
                _seen.clear()
        self._send(200, json.dumps({"cleared": True}))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
