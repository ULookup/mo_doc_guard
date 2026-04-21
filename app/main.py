"""Minimal entrypoint for local and container health checks."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            payload = {"status": "ok", "service": "docs-agent-ops"}
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        if os.getenv("ACCESS_LOG_ENABLED", "0") == "1":
            super().log_message(format, *args)


def _resolve_port() -> int:
    raw_port = os.getenv("PORT", "8080")
    try:
        port = int(raw_port)
    except ValueError:
        return 8080

    return port if 1 <= port <= 65535 else 8080


def run() -> None:
    port = _resolve_port()
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


if __name__ == "__main__":
    run()
