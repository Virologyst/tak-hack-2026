# tak-hack-2026

Python toolkit for the TAK hackathon, 15–17 August 2026. Built so that when the
problem statement drops we build the idea, not the plumbing.

**We stream Cursor-on-Target out over UDP to the server at the venue.** We don't
run a TAK server and don't need one — build a CoT event, fire the datagram,
it's on everyone's map.

## Sixty-second start

```bash
git clone https://github.com/Virologyst/tak-hack-2026.git
cd tak-hack-2026
python tak.py selftest              # no dependencies, no network required
```

If that passes, this machine is ready. On the day:

```bash
export COT_URL=udp://THEIR_IP:6969     # bash    (set COT_URL=... on Windows cmd)
python tak.py status udp://THEIR_IP:6969   # connectivity check
python tak.py send                         # marker on the map
```

Then get someone with ATAK to confirm they can see it. Over UDP that's the only
real proof the pipe works.

## Commands

| Command | What it does |
|---|---|
| `python tak.py selftest` | Verify a machine end to end. No network needed |
| `python tak.py send` | Put a moving marker on the map |
| `python tak.py listen` | Print CoT arriving on a port |
| `python tak.py status udp://IP:PORT` | Event-morning connectivity check |
| `python tak.py chat "message"` | Broadcast to GeoChat |
| `python tak.py dashboard` | Live browser view → `http://127.0.0.1:8080` |
| `python tak.py serve` | Local CoT router, for working with no venue server |

Every command takes `--url`; otherwise it uses `$COT_URL`, then `config.ini`.

## Writing code

```python
from taklib import TAKSender, cot

with TAKSender("udp://10.0.0.42:6969") as tak:
    tak.send(cot.unit("alpha-01", -27.4705, 153.0260, callsign="ALPHA"))
```

Builders: `unit()` `marker()` `detection()` `geochat()` `route()` `polygon()`
`circle()` `casevac()` `emergency()` `video()`. Full reference in
`docs/01-cot-reference.md`.

Reading is just as easy:

```python
from taklib import TAKListener

for evt in TAKListener("udp://0.0.0.0:6969"):
    print(evt["callsign"], evt["lat"], evt["lon"])
```

## Start here when the problem drops

| File | Pattern |
|---|---|
| `examples/01_send_marker.py` | Hello world |
| `examples/02_feed_bridge.py` | **Any external data → map markers.** The usual winner |
| `examples/03_geochat_bot.py` | The map answers questions |
| `examples/04_geofence_alert.py` | Watch an area, raise the alarm |
| `examples/05_detections.py` | Model output → contacts with confidence |

Most TAK problems are either *get this data onto the shared map* or *react to
what's on the map*. Pick the closest example and mutate it.

## Docs

| | |
|---|---|
| `CLAUDE.md` | **Read first.** Architecture, conventions, gotchas |
| `BRANCHING.md` | Git workflow across several machines |
| `docs/01-cot-reference.md` | The CoT protocol and every builder |
| `docs/02-connection.md` | UDP, multicast, TCP/TLS fallback, certs |
| `docs/03-playbook.md` | Pre-event checklist, first 60 minutes, demo craft |
| `docs/04-troubleshooting.md` | When it doesn't work |
| `docs/PROBLEM.md` | Fill this in on the day |
| `docs/tak-hackathon-prep.html` | Original prep pack (ecosystem, plugin path) |

## Dependencies

None. `taklib` is pure standard library, deliberately — a failed `pip install`
at the venue must never be what stops us demoing.

Optional extras: `pip install -r requirements.txt` gets you `pytak` (an
alternative async sender) and `takproto` (decoding protobuf-speaking servers).
Neither is needed for anything above.

## Layout

```
tak.py              CLI front door
taklib/             the library — cot, send, listen, geo, types, server, dashboard
examples/           runnable patterns to start from
docs/               reference and playbooks
config.ini.example  copy to config.ini (gitignored) and edit
```
