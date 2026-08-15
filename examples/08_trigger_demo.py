"""Safeword — say your word three times, broadcast an SOS beacon on TAK.

    python examples/08_trigger_demo.py --gain 50
    python examples/08_trigger_demo.py --gain 50 --word phoenix
    python examples/08_trigger_demo.py --gain 50 --word phoenix --url udp://239.2.3.1:6969

Open http://127.0.0.1:8888 in a browser to see the UI.

The user picks a safeword. When the system hears it three times, it
broadcasts an emergency beacon onto the TAK map with the user's position.
Three times prevents accidental triggers in noisy environments.

Ctrl-C to stop.
"""

import _path  # noqa: F401
import sys
sys.stdout.reconfigure(line_buffering=True)  # unbuffer prints on Windows

import argparse
import json
import queue
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from taklib import TAKSender, cot
from taklib.config import resolve_url

# --- shared state ---

_count = 0
_required = 3
_safeword = "safeword"
_fired = False
_lock = threading.Lock()
_subscribers: list[queue.Queue] = []

DEFAULT_LAT, DEFAULT_LON = -27.4705, 153.0260
UID_PREFIX = "safeword"


def _publish(payload: dict) -> None:
    with _lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


# --- web ---

PAGE = r"""<!doctype html>
<meta charset="utf-8"><title>SAFEWORD</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--ink:#e6edf3;--mut:#8b949e;
      --red:#f85149;--green:#3fb950;--mono:ui-monospace,Consolas,Menlo,monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif;
     display:flex;flex-direction:column;align-items:center;justify-content:center;
     min-height:100vh;gap:40px}
h1{font-size:14px;color:var(--mut);letter-spacing:.15em;text-transform:uppercase;font-family:var(--mono)}
.safeword{font:bold 72px var(--mono);color:var(--mut);text-transform:uppercase;
          letter-spacing:.06em;transition:color .3s ease}
.safeword.hot{color:var(--red)}
.dots{display:flex;gap:24px;margin:8px 0}
.dot{width:40px;height:40px;border-radius:50%;border:3px solid var(--line);
     background:transparent;transition:all .35s ease}
.dot.lit{background:var(--red);border-color:var(--red);
         box-shadow:0 0 20px rgba(248,81,73,.5)}
.counter{font:18px var(--mono);color:var(--mut)}
#alert{font:bold 28px var(--mono);color:#fff;padding:24px 48px;
       border-radius:16px;background:var(--red);display:none;text-align:center;
       letter-spacing:.04em}
#alert.show{display:block;animation:sos 0.6s ease-in-out infinite alternate}
@keyframes sos{from{box-shadow:0 0 30px rgba(248,81,73,.3);transform:scale(1)}
               to{box-shadow:0 0 80px rgba(248,81,73,.7);transform:scale(1.02)}}
#transcript{font:16px var(--mono);color:var(--mut);max-width:700px;text-align:center;
            min-height:24px;padding:12px}
#status{font:12px var(--mono);color:var(--mut);position:fixed;bottom:16px}
.armed{font:13px var(--mono);color:var(--green);border:1px solid var(--green);
       border-radius:999px;padding:4px 14px;margin-top:4px}
</style>
<h1>SAFEWORD</h1>
<div class="safeword" id="word">%WORD%</div>
<div class="dots" id="dots"></div>
<div class="counter" id="counter">0 / %REQUIRED%</div>
<div class="armed">ARMED</div>
<div id="alert">SOS BEACON TRANSMITTED</div>
<div id="transcript">listening...</div>
<div id="status">connecting...</div>
<script>
const REQUIRED = %REQUIRED%;
let count = 0;

const dotsDiv = document.getElementById('dots');
for (let i = 0; i < REQUIRED; i++) {
  const d = document.createElement('div');
  d.className = 'dot';
  d.id = 'dot-' + i;
  dotsDiv.appendChild(d);
}

function setCount(n) {
  count = n;
  document.getElementById('counter').textContent = n + ' / ' + REQUIRED;
  for (let i = 0; i < REQUIRED; i++) {
    document.getElementById('dot-' + i).classList.toggle('lit', i < n);
  }
  document.getElementById('word').classList.toggle('hot', n > 0);
  document.getElementById('alert').className = (n >= REQUIRED) ? 'show' : '';
}

const es = new EventSource('/stream');
es.onopen = () => document.getElementById('status').textContent = 'listening...';
es.onerror = () => document.getElementById('status').textContent = 'reconnecting...';
es.onmessage = m => {
  const d = JSON.parse(m.data);
  if (d.type === 'count') setCount(d.count);
  if (d.transcript) {
    document.getElementById('transcript').textContent = d.transcript;
  }
};
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass

    def do_GET(self):
        if self.path == "/":
            body = (PAGE
                    .replace("%WORD%", _safeword.upper())
                    .replace("%REQUIRED%", str(_required))
                    .encode())
            self._send(200, "text/html; charset=utf-8", body)
        elif self.path == "/stream":
            self._stream()
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q: queue.Queue = queue.Queue(maxsize=200)
        with _lock:
            _subscribers.append(q)
        try:
            while True:
                try:
                    item = q.get(timeout=15)
                    self.wfile.write(("data: %s\n\n" % json.dumps(item)).encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _lock:
                if q in _subscribers:
                    _subscribers.remove(q)


def start_web(port: int) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("  dashboard : http://127.0.0.1:%d" % port)
    httpd.serve_forever()


# --- voice ---

def voice_loop(gain: float, device: int | None,
               sa_url: str | None, chat_url: str | None,
               lat: float, lon: float, callsign: str) -> None:
    global _count, _fired

    from taklib.voice.base import clean_text
    from taklib.voice.mic import MicCapture

    import moonshine_voice as mv
    from moonshine_voice.moonshine_api import ModelArch
    from moonshine_voice.transcriber import LineCompleted, LineStarted, LineUpdated
    from moonshine_voice.transcriber import Transcriber as MoonshineCore

    print("loading moonshine ...")
    path, resolved = mv.get_model_for_language("en", ModelArch.TINY_STREAMING)
    core = MoonshineCore(path, resolved, update_interval=0.3)
    try:
        core.set_keyterms([_safeword])
    except Exception:
        pass

    pat = re.compile(r"\b%s\b" % re.escape(_safeword), re.I)

    # Track how many times we've seen the word in the *current* line
    # so partial updates don't double-count within one utterance
    line_hits = {"count": 0, "last_seen": 0}

    sa = TAKSender(sa_url) if sa_url else None
    chat = TAKSender(chat_url) if chat_url else None

    def fire_sos() -> None:
        uid = "%s-%s" % (UID_PREFIX, callsign.lower())
        print("\n  >>> SOS BEACON FIRED <<<")
        print("  callsign: %s" % callsign)
        print("  position: %.4f, %.4f" % (lat, lon))
        if sa:
            sa.send(cot.emergency(
                uid, lat, lon,
                callsign=callsign,
                emergency_type="911 Alert",
                stale=3600,
            ))
            print("  sent emergency to %s" % sa_url)
        if chat:
            chat.send(cot.geochat(
                "SOS — %s has activated their safeword" % callsign,
                sender_uid="%s-bot" % UID_PREFIX,
                sender_callsign="SAFEWORD",
            ))
            print("  sent chat alert to %s" % chat_url)
        if not sa and not chat:
            print("  (dry run — no URL configured)")

    def check_word(text: str) -> None:
        global _count, _fired
        if _fired:
            return

        hits = len(pat.findall(text))
        if hits <= line_hits["last_seen"]:
            return

        new_hits = hits - line_hits["last_seen"]
        line_hits["last_seen"] = hits
        _count = min(_count + new_hits, _required)

        print("  [%d/%d] heard '%s'" % (_count, _required, _safeword))
        _publish({"type": "count", "count": _count, "transcript": text})

        if _count >= _required and not _fired:
            _fired = True
            fire_sos()

    def on_event(event) -> None:
        line = getattr(event, "line", None)
        if line is None:
            return
        text = clean_text(line.text or "")

        if isinstance(event, LineStarted):
            line_hits["count"] = 0
            line_hits["last_seen"] = 0
            return

        if isinstance(event, (LineUpdated, LineCompleted)):
            if text:
                check_word(text)

    stream = core.create_stream(update_interval=0.3)
    stream.add_listener(on_event)
    stream.start()

    with MicCapture(device=device, gain=gain, normalise=False) as mic:
        print("  say '%s' %d times to trigger SOS. Ctrl-C to stop.\n"
              % (_safeword, _required))
        try:
            for block in mic.blocks():
                stream.add_audio(list(block), mic.sample_rate)
        except KeyboardInterrupt:
            print("\nstopping ...")
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            core.close()


def main() -> None:
    global _safeword

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--word", default="pineapple",
                    help="your chosen safeword (default: pineapple)")
    ap.add_argument("--gain", type=float, default=1.0,
                    help="digital mic gain (this laptop needs ~50)")
    ap.add_argument("--device", type=int, help="input device index")
    ap.add_argument("--port", type=int, default=8888, help="web port")
    ap.add_argument("--url", help="SA CoT URL (default: none / dry run)")
    ap.add_argument("--chat-url", default=None,
                    help="GeoChat URL (default: none)")
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--callsign", default="SAFEWORD",
                    help="callsign on the SOS beacon")
    args = ap.parse_args()

    _safeword = args.word.lower().strip()

    sa_url = resolve_url(args.url) if args.url else None
    chat_url = args.chat_url

    print("  safeword  : %s" % _safeword.upper(), flush=True)
    print("  required  : %d repetitions" % _required, flush=True)
    print("  callsign  : %s" % args.callsign, flush=True)
    print("  SA URL    : %s" % (sa_url or "(dry run)"), flush=True)
    print("  chat URL  : %s" % (chat_url or "(none)"), flush=True)

    t = threading.Thread(target=start_web, args=(args.port,), daemon=True)
    t.start()

    voice_loop(args.gain, args.device, sa_url, chat_url,
               args.lat, args.lon, args.callsign)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
