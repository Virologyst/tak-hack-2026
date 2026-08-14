"""A live web view of everything on the TAK network — the second screen.

Judges look at a phone screen for about four seconds. A browser window showing
every marker, every chat message and a running event count, projected on the
big screen, is worth a surprising number of points.

    python -m taklib.dashboard --url tcp://10.0.0.42:8087
    # then open http://127.0.0.1:8080

Standard library only, and no CDN: the map is drawn on a canvas from the CoT
positions themselves, so it works with the venue wifi captive-portalled or
entirely offline. No tiles, but you get relative geometry, tracks and labels,
which is what you're actually demoing.
"""

import argparse
import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List

from .config import resolve_url
from .listen import TAKListener
from .types import describe

log = logging.getLogger("taklib.dashboard")

_state: Dict[str, dict] = {}
_chat: List[dict] = []
_subscribers: List["queue.Queue"] = []
_lock = threading.Lock()
_stats = {"events": 0, "url": ""}


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


def _to_json(evt: dict) -> dict:
    """Only the fields the browser needs — the raw XML would be wasteful."""
    return {
        "uid": evt["uid"],
        "type": evt["type"],
        "label": describe(evt["type"]),
        "callsign": evt["callsign"] or evt.get("sender_callsign") or evt["uid"],
        "lat": evt["lat"],
        "lon": evt["lon"],
        "hae": evt["hae"],
        "team": evt["team"],
        "remarks": evt["remarks"],
        "time": evt["time"],
        "is_chat": evt["is_chat"],
        "speed": evt.get("speed"),
        "course": evt.get("course"),
        "detection": evt.get("detection"),
    }


def _ingest(url: str, **listener_kwargs) -> None:
    """Background thread: consume CoT and fan it out to browsers."""
    _stats["url"] = url
    for evt in TAKListener(url, **listener_kwargs):
        item = _to_json(evt)
        _stats["events"] += 1
        with _lock:
            if item["is_chat"]:
                _chat.append(item)
                del _chat[:-100]
            elif item["lat"] or item["lon"]:
                _state[item["uid"]] = item
        _publish(item)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):    # quieter than the default
        log.debug(fmt, *args)

    def do_GET(self):
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        elif self.path == "/state":
            with _lock:
                body = json.dumps({
                    "entities": list(_state.values()),
                    "chat": _chat[-40:],
                    "stats": _stats,
                }).encode()
            self._send(200, "application/json", body)
        elif self.path == "/stream":
            self._stream()
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        """Server-sent events — a websocket's simpler cousin, stdlib-friendly."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        q: queue.Queue = queue.Queue(maxsize=500)
        with _lock:
            _subscribers.append(q)
        try:
            while True:
                try:
                    item = q.get(timeout=15)
                    payload = json.dumps(item)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")   # stop proxies timing out
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _lock:
                if q in _subscribers:
                    _subscribers.remove(q)


PAGE = r"""<!doctype html>
<meta charset="utf-8"><title>TAK Live</title>
<style>
:root{--bg:#0d1411;--panel:#131d19;--line:#26362e;--ink:#e6efe9;--mut:#8fa89b;
      --acc:#5fd08a;--warn:#f2c14e;--hot:#f0736a;--blue:#79b8ff;
      --mono:ui-monospace,Consolas,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif;
     display:grid;grid-template-columns:1fr 380px;grid-template-rows:52px 1fr;height:100vh}
header{grid-column:1/-1;display:flex;align-items:center;gap:16px;padding:0 18px;
       border-bottom:1px solid var(--line);background:var(--panel)}
h1{font-size:15px;margin:0;letter-spacing:.02em}
.pill{font:11px var(--mono);color:var(--mut);border:1px solid var(--line);
      border-radius:999px;padding:3px 10px}
.pill b{color:var(--acc)}
#map{position:relative;background:
     linear-gradient(rgba(95,208,138,.05) 1px,transparent 1px) 0 0/40px 40px,
     linear-gradient(90deg,rgba(95,208,138,.05) 1px,transparent 1px) 0 0/40px 40px,#0a100d}
canvas{display:block;width:100%;height:100%}
aside{border-left:1px solid var(--line);background:var(--panel);overflow-y:auto;padding:14px}
h2{font:11px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--mut);
   margin:18px 0 8px;font-weight:600}
h2:first-child{margin-top:0}
.row{border-bottom:1px solid var(--line);padding:7px 0;font-size:13px}
.row .cs{font-weight:600}
.row .meta{color:var(--mut);font:11px var(--mono)}
.row .rm{color:var(--mut);font-size:12px}
.chat{border-left:2px solid var(--blue);padding:5px 0 5px 9px;margin:7px 0;font-size:12.5px}
.chat .who{color:var(--blue);font-weight:600}
.empty{color:var(--mut);font-size:12.5px;font-style:italic}
.legend{position:absolute;left:12px;bottom:12px;font:11px var(--mono);color:var(--mut);
        background:rgba(13,20,17,.85);border:1px solid var(--line);border-radius:8px;padding:8px 11px}
.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
</style>
<header>
  <h1>TAK LIVE</h1>
  <span class="pill">source <b id="src">—</b></span>
  <span class="pill">entities <b id="n">0</b></span>
  <span class="pill">events <b id="ev">0</b></span>
  <span class="pill" id="conn">connecting…</span>
</header>
<div id="map">
  <canvas id="c"></canvas>
  <div class="legend">
    <div><i style="background:#5fd08a"></i>friendly</div>
    <div><i style="background:#f0736a"></i>hostile</div>
    <div><i style="background:#f2c14e"></i>unknown / neutral</div>
    <div><i style="background:#79b8ff"></i>marker / other</div>
  </div>
</div>
<aside>
  <h2>Entities</h2><div id="list"><div class="empty">nothing on the map yet</div></div>
  <h2>GeoChat</h2><div id="chat"><div class="empty">no messages</div></div>
</aside>
<script>
const ents = new Map(); let chat = []; let events = 0;
const cv = document.getElementById('c'), ctx = cv.getContext('2d');

function colourFor(t){
  if(!t) return '#79b8ff';
  if(t.startsWith('a-f')) return '#5fd08a';
  if(t.startsWith('a-h')||t.startsWith('b-a')) return '#f0736a';
  if(t.startsWith('a-u')||t.startsWith('a-n')||t.startsWith('a-p')) return '#f2c14e';
  return '#79b8ff';
}
function resize(){
  const r = cv.parentElement.getBoundingClientRect(), d = window.devicePixelRatio||1;
  cv.width = r.width*d; cv.height = r.height*d; ctx.setTransform(d,0,0,d,0,0);
  draw();
}
addEventListener('resize', resize);

function draw(){
  const w = cv.clientWidth, h = cv.clientHeight;
  ctx.clearRect(0,0,w,h);
  const pts = [...ents.values()].filter(e=>e.lat||e.lon);
  if(!pts.length){
    ctx.fillStyle='#6f877b'; ctx.font='13px system-ui'; ctx.textAlign='center';
    ctx.fillText('waiting for CoT…', w/2, h/2); return;
  }
  // Auto-fit all entities, with a little breathing room.
  let la=pts.map(p=>p.lat), lo=pts.map(p=>p.lon);
  let minLa=Math.min(...la), maxLa=Math.max(...la);
  let minLo=Math.min(...lo), maxLo=Math.max(...lo);
  const padLa=Math.max((maxLa-minLa)*0.15, 0.002), padLo=Math.max((maxLo-minLo)*0.15, 0.002);
  minLa-=padLa; maxLa+=padLa; minLo-=padLo; maxLo+=padLo;
  const sx = w/(maxLo-minLo), sy = h/(maxLa-minLa), s = Math.min(sx,sy);
  const ox = (w-(maxLo-minLo)*s)/2, oy = (h-(maxLa-minLa)*s)/2;
  const X = lon => ox+(lon-minLo)*s, Y = lat => h-oy-(lat-minLa)*s;

  // scale bar (metres per degree latitude is ~111320)
  const metres = (h-2*oy)/s*111320;
  ctx.strokeStyle='#26362e'; ctx.fillStyle='#6f877b'; ctx.font='11px ui-monospace';
  ctx.textAlign='left';
  ctx.fillText(metres>2000 ? (metres/1000).toFixed(1)+' km tall' : metres.toFixed(0)+' m tall', 12, 20);

  for(const e of pts){
    const x=X(e.lon), y=Y(e.lat), col=colourFor(e.type);
    if(e.course!=null && e.speed){                 // heading vector
      const a=(e.course-90)*Math.PI/180;
      ctx.strokeStyle=col; ctx.globalAlpha=.6; ctx.lineWidth=1.5;
      ctx.beginPath(); ctx.moveTo(x,y); ctx.lineTo(x+Math.cos(a)*18,y+Math.sin(a)*18);
      ctx.stroke(); ctx.globalAlpha=1;
    }
    ctx.fillStyle=col; ctx.globalAlpha=.18;
    ctx.beginPath(); ctx.arc(x,y,11,0,7); ctx.fill(); ctx.globalAlpha=1;
    ctx.beginPath(); ctx.arc(x,y,5,0,7); ctx.fill();
    ctx.fillStyle='#e6efe9'; ctx.font='11px ui-monospace'; ctx.textAlign='center';
    ctx.fillText(e.callsign||e.uid, x, y-14);
  }
}

function render(){
  document.getElementById('n').textContent = ents.size;
  document.getElementById('ev').textContent = events;
  const list = document.getElementById('list');
  list.innerHTML = ents.size ? [...ents.values()]
    .sort((a,b)=>(a.callsign||'').localeCompare(b.callsign||''))
    .map(e=>`<div class="row">
      <div class="cs" style="color:${colourFor(e.type)}">${esc(e.callsign||e.uid)}</div>
      <div class="meta">${esc(e.type)} · ${e.lat.toFixed(5)}, ${e.lon.toFixed(5)}</div>
      ${e.remarks?`<div class="rm">${esc(e.remarks)}</div>`:''}
    </div>`).join('') : '<div class="empty">nothing on the map yet</div>';
  const ch = document.getElementById('chat');
  ch.innerHTML = chat.length ? chat.slice(-40).reverse()
    .map(m=>`<div class="chat"><span class="who">${esc(m.callsign)}</span> ${esc(m.remarks)}</div>`)
    .join('') : '<div class="empty">no messages</div>';
  draw();
}
const esc = s => String(s??'').replace(/[<>&"]/g, c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));

function accept(e){
  events++;
  if(e.is_chat) chat.push(e);
  else if(e.lat||e.lon) ents.set(e.uid, e);
}
fetch('/state').then(r=>r.json()).then(d=>{
  d.entities.forEach(e=>ents.set(e.uid,e)); chat = d.chat;
  events = d.stats.events; document.getElementById('src').textContent = d.stats.url||'—';
  resize(); render();
});
const es = new EventSource('/stream');
es.onopen = ()=>document.getElementById('conn').innerHTML='<b style="color:#5fd08a">live</b>';
es.onerror = ()=>document.getElementById('conn').innerHTML='<b style="color:#f0736a">reconnecting</b>';
es.onmessage = m => { accept(JSON.parse(m.data)); render(); };
resize();
</script>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Live web dashboard for a TAK CoT feed")
    ap.add_argument("--url", help="COT_URL to listen on (default: config/env)")
    ap.add_argument("--host", default="127.0.0.1", help="web bind address")
    ap.add_argument("--port", type=int, default=8080, help="web port")
    ap.add_argument("--cert"), ap.add_argument("--key")
    ap.add_argument("--insecure", action="store_true", help="skip TLS verification")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    url = resolve_url(args.url)

    kwargs = {"verify": not args.insecure}
    if args.cert:
        kwargs.update(cert=args.cert, key=args.key)

    threading.Thread(target=_ingest, args=(url,), kwargs=kwargs, daemon=True).start()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"  dashboard : http://{args.host}:{args.port}")
    print(f"  listening : {url}")
    print("  Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
