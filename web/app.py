"""Voice console server: one process, one port, one origin.

    python web/app.py                 # http://127.0.0.1:5001
    python web/app.py --host 0.0.0.0  # reachable from a phone on the venue LAN

Why not extend `api.py`: that one is a plain `HTTPServer`, single-threaded, and
a single Server-Sent Events connection wedges it permanently - the next slice
needs SSE for the live panes. It also belongs to Craig's trigger page, which
keeps working untouched. This is a sibling, not a replacement.

Why one origin rather than a second Vite proxy entry: at the venue the demo is
watched on a projector or a phone, not on localhost, so any hardcoded
`127.0.0.1` in the JS is a demo-killer. Serving the built app and the API from
the same port removes that whole class of problem and needs no Vite in
production.

**Two servers, one database.** If Craig's `api.py` is also running, both write
`triggers.db`. That is fine - the vocabulary revision lives in the `meta` table
rather than in memory precisely so neither process can hold a stale view. What
is NOT fine is both binding 5001, so this defaults to the same port on purpose:
you find out immediately rather than wondering why the other page is dead.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import schema                       # noqa: E402
from vocab_store import VocabStore  # noqa: E402
from taklib import types as tak_types  # noqa: E402

STORE = VocabStore()
STATIC_DIR = os.path.join(HERE, "dist")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TAKVoiceConsole/0.1"

    # -- plumbing ------------------------------------------------------------

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/"):
            sys.stderr.write("  %s %s\n" % (self.command, self.path))

    def _send(self, status: int, payload, content_type="application/json"):
        body = (json.dumps(payload).encode("utf-8")
                if content_type == "application/json" else payload)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Same-origin in production, but the Vite dev server is a different
        # origin, so allow it rather than making dev a special case.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- routes --------------------------------------------------------------

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/health":
            return self._send(200, {"ok": True, "revision": STORE.revision(),
                                    "db": os.path.basename(STORE.path)})
        if path == "/api/services":
            return self._send(200, {"services": STORE.list_services(),
                                    "teams": list(tak_types.TEAM_COLOURS)})
        if path == "/api/terms":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sid = qs.get("service_id", [None])[0]
            return self._send(200, {"terms": STORE.list_terms(
                int(sid) if sid else None)})
        if path == "/api/vocab":
            return self._send(200, STORE.export_json())
        if path.startswith("/api/"):
            return self._send(404, {"error": "no such endpoint"})

        return self._static(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._body()

        if path == "/api/services":
            svc = STORE.add_service(body.get("name", ""),
                                    body.get("team", "White"),
                                    int(body.get("sort_order", 100)))
            if svc is None:
                return self._send(409, {"error": "name is empty or already used"})
            return self._send(201, svc)

        if path == "/api/terms":
            try:
                service_id = int(body.get("service_id", schema.CORE_SERVICE_ID))
            except (TypeError, ValueError):
                return self._send(400, {"error": "service_id must be a number"})
            term = STORE.add_term(service_id, body.get("trigger", ""),
                                  body.get("tak_word", ""),
                                  body.get("comments", ""))
            if term is None:
                return self._send(409, {
                    "error": "empty trigger, or that trigger already exists in "
                             "this service (the same word in a DIFFERENT "
                             "service is fine)"})
            return self._send(201, term)

        if path == "/api/vocab/import":
            result = STORE.import_json(body.get("payload", body),
                                       replace=bool(body.get("replace")))
            return self._send(200, result)

        return self._send(404, {"error": "no such endpoint"})

    def do_PATCH(self):
        path = urllib.parse.urlparse(self.path).path
        parts = path.rstrip("/").split("/")
        body = self._body()

        if len(parts) == 4 and parts[2] == "terms":
            term = STORE.update_term(int(parts[3]), **body)
            if term is None:
                return self._send(409, {"error": "nothing to change, or that "
                                                 "trigger already exists here"})
            return self._send(200, term)

        if len(parts) == 4 and parts[2] == "services":
            svc = STORE.update_service(int(parts[3]), **body)
            if svc is None:
                return self._send(409, {"error": "nothing to change, or name taken"})
            return self._send(200, svc)

        return self._send(404, {"error": "no such endpoint"})

    def do_DELETE(self):
        parts = urllib.parse.urlparse(self.path).path.rstrip("/").split("/")

        if len(parts) == 4 and parts[2] == "terms":
            ok = STORE.delete_term(int(parts[3]))
            return self._send(200 if ok else 404, {"deleted": ok})

        if len(parts) == 4 and parts[2] == "services":
            sid = int(parts[3])
            if sid == schema.CORE_SERVICE_ID:
                return self._send(400, {
                    "error": "CORE cannot be deleted - it is the fallback every "
                             "service falls back to"})
            ok = STORE.delete_service(sid)
            return self._send(200 if ok else 404, {"deleted": ok})

        return self._send(404, {"error": "no such endpoint"})

    # -- static --------------------------------------------------------------

    def _static(self, path: str):
        """Serve the built React app, falling back to index.html for routes."""
        if not os.path.isdir(STATIC_DIR):
            return self._send(
                200,
                b"<!doctype html><meta charset=utf-8>"
                b"<title>TAK Voice Console</title>"
                b"<body style='font:15px system-ui;background:#0d1411;"
                b"color:#e6efe9;padding:40px'>"
                b"<h1 style='color:#5fd08a'>API is up</h1>"
                b"<p>The React app has not been built yet.</p>"
                b"<pre style='background:#131d19;border:1px solid #26362e;"
                b"padding:12px'>cd web\nnpm install\nnpm run dev</pre>"
                b"<p>Dev server proxies <code>/api</code> here. "
                b"For a single-origin build: <code>npm run build</code>, "
                b"then reload this page.</p>"
                b"<p><a style='color:#5fd08a' href='/api/services'>"
                b"/api/services</a></p></body>",
                "text/html; charset=utf-8")

        rel = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
        candidate = os.path.join(STATIC_DIR, rel)
        # Refuse anything that escapes the static root.
        if not os.path.abspath(candidate).startswith(os.path.abspath(STATIC_DIR)):
            return self._send(403, {"error": "nope"})
        if not rel or os.path.isdir(candidate):
            candidate = os.path.join(STATIC_DIR, "index.html")
        if not os.path.exists(candidate):
            candidate = os.path.join(STATIC_DIR, "index.html")
        if not os.path.exists(candidate):
            return self._send(404, {"error": "not built"})

        ctype = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
        with open(candidate, "rb") as fh:
            return self._send(200, fh.read(), ctype)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 to reach it from another device on the LAN")
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--db", help="override the sqlite path")
    ap.add_argument("--no-seed", action="store_true",
                    help="skip the starter vocabulary on a fresh database")
    args = ap.parse_args()

    global STORE
    if args.db:
        STORE = VocabStore(args.db)

    report = STORE.migrate(seed=not args.no_seed)
    print("schema v%d -> v%d" % (report["from_version"], report["to_version"]))
    if report["migrated_triggers"]:
        print("  carried %d phrase(s) over from the triggers table"
              % report["migrated_triggers"])
    if report["seeded"]:
        print("  seeded %d term(s)" % report["seeded"])
    for svc in STORE.list_services():
        print("  %-12s %-11s %2d terms"
              % (svc["name"], svc["team"], svc["term_count"]))

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    print("\nvoice console  http://%s:%d" % (shown, args.port))
    if not os.path.isdir(STATIC_DIR):
        print("  (no web/dist yet - run `npm run dev` in web/ for the UI)")
    print("  Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
