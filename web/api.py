"""Minimal JSON API for trigger phrases. Pure stdlib, no pip needed.

    python web/api.py              # serves on :5001
    python web/api.py --port 5002  # pick a port

Vite proxies /api/* here during dev. In production, serve the built
React app from the same process or behind any reverse proxy.
"""

import json
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler

import db


class Handler(BaseHTTPRequestHandler):

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        if self.path == "/api/triggers":
            self._json(200, db.all_triggers())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/triggers":
            body = self._read_body()
            phrase = body.get("phrase", "").strip()
            category = body.get("category", "custom").strip()
            if not phrase:
                self._json(400, {"error": "phrase is required"})
                return
            result = db.add_trigger(phrase, category)
            if result is None:
                self._json(409, {"error": "phrase already exists"})
            else:
                self._json(201, result)
        else:
            self.send_error(404)

    def do_DELETE(self):
        # /api/triggers/123
        parts = self.path.rstrip("/").split("/")
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "triggers":
            try:
                tid = int(parts[3])
            except ValueError:
                self.send_error(400)
                return
            if db.delete_trigger(tid):
                self._json(200, {"deleted": tid})
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        print("[api] " + (fmt % args))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=5001)
    args = ap.parse_args()

    db.init()
    print("triggers.db: %d phrases" % len(db.all_triggers()))

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print("api listening on http://127.0.0.1:%d" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
