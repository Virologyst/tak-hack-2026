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
rather than in memory precisely so neither process can hold a stale view.

**But two servers on one PORT is not fine, and Windows will not tell you.**
`HTTPServer` sets `allow_reuse_address`, which on Windows means SO_REUSEADDR
lets a second process bind a port that is already listening. No "address in
use" error is raised; the two sockets simply split incoming connections
between them at random. The symptom is a page that works, then does not, then
does again - and an API that appears to ignore code you just changed, because
half your requests are being answered by the older process.

Observed while building this: two `app.py` instances listening on 5001 at once,
and curl getting the stale one. `netstat -ano | grep :5001` shows more than one
LISTENING line when it happens. Kill by PID; a plain pkill may only get one.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import queue
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import schema                       # noqa: E402
import pipeline                    # noqa: E402
from engine import Engine          # noqa: E402
from vocab_store import InvalidTakWord, VocabStore  # noqa: E402
from taklib import types as tak_types  # noqa: E402
from taklib.voice import takwords    # noqa: E402

STORE = VocabStore()
STATIC_DIR = os.path.join(HERE, "dist")

# --- SSE fan-out -------------------------------------------------------------
# Lifted from taklib/dashboard.py, which has been working since day one. One
# bounded queue per connected browser, guarded by a lock.

_subscribers: "list[queue.Queue]" = []
_sub_lock = threading.Lock()


def publish(event: str, payload: dict) -> None:
    """Fan one event out to every browser. Never blocks, never raises.

    Backpressure is split by event type on purpose: a slow browser loses its
    `partial` and `stats` updates, which are invisible, but is dropped entirely
    rather than lose an `utterance`, which is not.
    """
    item = (event, payload)
    with _sub_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(item)
            except queue.Full:
                if event == "utterance":
                    dead.append(q)
        for q in dead:
            _subscribers.remove(q)


def _active_server() -> dict:
    """The server row the engine should send to, or the mesh defaults."""
    conn = STORE.connect()
    try:
        row = conn.execute(
            "SELECT * FROM servers WHERE active = 1 LIMIT 1").fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}
    finally:
        conn.close()


def _not_a_command() -> str:
    from taklib.voice.interpret import NOT_A_COMMAND
    return NOT_A_COMMAND


def _audio_devices() -> list:
    """Input devices, so the radio's line-in can be picked from the UI."""
    try:
        import sounddevice as sd
    except Exception as exc:
        return [{"error": "sounddevice not installed (%s)" % exc}]
    try:
        return [{"index": i, "name": d["name"],
                 "channels": d["max_input_channels"],
                 "rate": int(d["default_samplerate"])}
                for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0]
    except Exception as exc:
        return [{"error": str(exc)}]


ENGINE = Engine(publish, STORE, _active_server)


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
        if path == "/api/takwords":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = qs.get("q", [""])[0]
            limit = int(qs.get("limit", ["12"])[0])
            if q:
                return self._send(200, {"words": [
                    {"word": w.word, "category": w.category, "effect": w.effect}
                    for w in takwords.search(q, limit)]})
            # No query: the whole catalogue, so the page can validate offline
            # and never has to round-trip on a keystroke.
            return self._send(200, {"words": takwords.as_dicts(),
                                    "ignore": takwords.IGNORE})

        if path == "/api/vocab":
            return self._send(200, STORE.export_json())

        if path == "/api/engine":
            return self._send(200, ENGINE.status())

        if path == "/api/devices":
            return self._send(200, {"devices": _audio_devices()})

        if path == "/api/stream":
            return self._stream()

        if path.startswith("/api/"):
            return self._send(404, {"error": "no such endpoint"})

        return self._static(path)

    # -- server-sent events ---------------------------------------------------

    def _stream(self):
        """One long-lived response per browser. Needs ThreadingHTTPServer.

        The 15s keepalive is load-bearing, not cosmetic: it is the only thing
        that raises BrokenPipeError on a browser that has gone away, and so the
        only thing that ever reaps a dead subscriber thread.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")     # defeat proxy buffering
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q: "queue.Queue" = queue.Queue(maxsize=500)
        with _sub_lock:
            _subscribers.append(q)

        try:
            self._sse("hello", {
                "engine": ENGINE.status(),
                "services": [s["name"] for s in STORE.list_services()],
                "server": _active_server(),
                "recent": ENGINE.recent[-20:],
                "not_a_command": _not_a_command(),
            })
            while True:
                try:
                    event, payload = q.get(timeout=15)
                    self._sse(event, payload)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _sub_lock:
                if q in _subscribers:
                    _subscribers.remove(q)

    def _sse(self, event: str, payload: dict):
        body = json.dumps(payload)
        self.wfile.write(("event: %s\ndata: %s\n\n" % (event, body)).encode())
        self.wfile.flush()

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
            try:
                term = STORE.add_term(service_id, body.get("trigger", ""),
                                      body.get("tak_word", ""),
                                      body.get("comments", ""))
            except InvalidTakWord as bad:
                return self._send(422, {"error": str(bad),
                                        "suggestions": bad.suggestions})
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

        if path == "/api/engine/start":
            return self._send(200, ENGINE.start(
                source=body.get("source", "mic"),
                device=body.get("device"),
                wav=body.get("wav"),
                service=body.get("service") or None,
                gain=float(body.get("gain", 1.0)),
                threshold=body.get("threshold"),
                silence=float(body.get("silence", 0.8)),
                backend=body.get("backend") or None,
                loop=bool(body.get("loop"))))

        if path == "/api/engine/stop":
            return self._send(200, ENGINE.stop())

        if path == "/api/simulate":
            # Type a sentence and watch it run the whole pipeline. No mic, no
            # model, no network - the demo of last resort, and the fastest way
            # to check a vocabulary change did what you meant.
            ENGINE.seq += 1
            event = pipeline.process(
                body.get("text", ""), vocab=STORE.load(),
                service=body.get("service") or None,
                server=_active_server(), seq=ENGINE.seq,
                clip={"simulated": True})
            event["sent"] = {"sa": False, "chat": False, "url": None,
                             "error": "simulated - nothing was transmitted"}
            ENGINE.recent.append(event)
            del ENGINE.recent[:-20]
            publish("utterance", event)
            return self._send(200, event)

        return self._send(404, {"error": "no such endpoint"})

    def do_PATCH(self):
        path = urllib.parse.urlparse(self.path).path
        parts = path.rstrip("/").split("/")
        body = self._body()

        if len(parts) == 4 and parts[2] == "terms":
            try:
                term = STORE.update_term(int(parts[3]), **body)
            except InvalidTakWord as bad:
                return self._send(422, {"error": str(bad),
                                        "suggestions": bad.suggestions})
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
    ap.add_argument("--force", action="store_true",
                    help="start even if the port already answers")
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

    # Refuse to start if something already answers on this port. Windows will
    # happily let a second process bind it (SO_REUSEADDR), then split requests
    # between the two at random - so you edit code, restart, and half your
    # calls are still served by the old process. Bind order gives no error, so
    # this probe is the only thing that catches it.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.4)
    already = probe.connect_ex(("127.0.0.1", args.port)) == 0
    probe.close()
    if already and not args.force:
        print("ERROR: something is already listening on port %d." % args.port)
        print("  Windows allows a second bind and then splits traffic between")
        print("  them, which looks like your code changes being ignored.")
        print("  Find it:  netstat -ano | findstr :%d" % args.port)
        print("  Or start elsewhere:  --port %d" % (args.port + 1))
        print("  Or override:  --force")
        return 1

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
