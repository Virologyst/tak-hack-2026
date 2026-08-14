# CLAUDE.md — read this first

Context for any agent or teammate working in this repo. Several machines work
here at once during the hackathon, so keep this file accurate: it is the
shared brain.

## What this is

A Python toolkit for a TAK (Team Awareness Kit) hackathon, 15–17 Aug 2026.
The problem statement is **not released yet**. Everything here exists so that
when it drops we build the actual idea instead of plumbing.

## The one architectural fact

**We stream CoT out over UDP to a server the venue provides.** We are not
running a TAK server and we do not need one. There is no handshake, no
certificates, no connection to maintain — we build a Cursor-on-Target XML
event and fire the datagram at their IP and port.

```
our code ──> cot.unit(...) ──> UDP datagram ──> venue's server ──> everyone's map
```

Set the target once and everything in the repo follows it:

```bash
export COT_URL=udp://THEIR_IP:6969      # bash
set COT_URL=udp://THEIR_IP:6969         # Windows cmd
$env:COT_URL="udp://THEIR_IP:6969"      # PowerShell
```

Consequences of UDP that shape how we work:

- **Nothing acknowledges us.** A successful `send()` means the datagram left
  the machine, not that anyone received it. Ground truth is a person with ATAK
  saying "I see it".
- **One event per datagram.** Never batch; keep events under ~1400 bytes so
  they don't fragment. `taklib` already does this.
- **Malformed XML fails silently.** With TCP a server might complain; over UDP
  a bad event just vanishes. So validate locally before blaming the network —
  `python tak.py listen --url udp://127.0.0.1:6969` in another terminal.
- Re-sending is cheap and normal. Repeat position updates on an interval
  rather than assuming one send landed.

TCP (8087) and TLS (8089) are still fully supported in `taklib` in case the
venue turns out to want them — change the URL scheme and nothing else.

## Commands

```bash
python tak.py selftest                        # verify a machine works, no network needed
python tak.py send --url udp://IP:6969        # put a moving marker out there
python tak.py listen --url udp://0.0.0.0:6969 # see what's arriving
python tak.py status udp://IP:6969            # event-morning connectivity check
python tak.py chat "message"                  # broadcast to GeoChat
python tak.py dashboard --url udp://0.0.0.0:6969   # live web view, http://127.0.0.1:8080
python tak.py serve                           # local TCP CoT router, for offline dev
```

`python tak.py selftest` is the first thing to run on any new machine. If it
passes, that laptop can build and demo.

## Layout

| Path | What it is |
|---|---|
| `tak.py` | CLI front door — every command above |
| `taklib/cot.py` | **Build CoT events.** The module you'll touch most |
| `taklib/send.py` | `TAKSender` / `AsyncTAKSender` — udp/tcp/tls, auto-reconnect |
| `taklib/listen.py` | `TAKListener` + `parse_cot()` — read CoT as dicts |
| `taklib/types.py` | CoT type codes (`FRIENDLY_UNIT`, `HOSTILE_GROUND`, …) |
| `taklib/geo.py` | distance, bearing, destination, point-in-polygon, nearest |
| `taklib/server.py` | Local CoT router for offline development |
| `taklib/dashboard.py` | Live browser view — the judge-facing second screen |
| `taklib/config.py` | URL/cert/identity resolution |
| `examples/` | Runnable patterns — start here when the problem drops |
| `docs/` | CoT reference, connection playbook, hackathon playbook |

`taklib` is **pure standard library**. `pytak` and `takproto` are optional and
only used if installed. A failed `pip install` on event morning must never be
what stops us demoing.

## Writing CoT

```python
from taklib import TAKSender, cot

with TAKSender("udp://10.0.0.42:6969") as tak:
    tak.send(cot.unit("alpha-01", -27.4705, 153.0260, callsign="ALPHA"))
```

Builders in `taklib/cot.py`, all returning ready-to-send `bytes`:

`unit()` moving things · `marker()` pins · `detection()` machine contacts with
confidence · `geochat()` chat messages · `route()` paths · `polygon()` areas
and geofences · `circle()` range rings · `casevac()` 9-line medevac ·
`emergency()` alerts · `video()` marker with a stream attached

Every builder takes `extra=` for custom `<detail>` children — XML string, dict,
or Element. CoT's `<detail>` has no fixed schema, so arbitrary payloads ride
along fine and other clients ignore what they don't understand.

## Conventions that matter

- **UID stability is everything.** Same `uid` on every update = the marker
  moves. New `uid` each time = the map fills with duplicate ghosts. This is the
  single most common CoT mistake.
- **Namespace your uids** — `craig-drone-01`, not `drone-01`. Several machines
  are emitting at once and colliding uids overwrite each other.
- **Set `TAK_CALLSIGN` per laptop** so we don't all appear as one dot.
- **Stale time is a promise.** `stale=120` means the marker vanishes in two
  minutes; re-send more often than that or it flickers out mid-demo.
- Lat/lon are WGS84 decimal degrees. Southern hemisphere is negative — Brisbane
  is `-27.47, 153.02`. Getting the sign wrong puts you in the sea off Japan.
- `ce`/`le` default to 9999999 ("unknown"). Pass real metres when the source
  knows them; ATAK draws the accuracy ring from it.

## Git — several machines, one repo

Read `BRANCHING.md`. Short version: **never commit to `main` directly.**

```
main                    always demo-ready, protected
feat/<what>             one branch per idea
<machine>/<what>        when it's machine-specific
```

Commit and push often — a laptop dying at 3am should cost minutes, not hours.
`config.ini`, `certs/`, `*.p12` and `.idea/` are gitignored; keep it that way.

## When the problem statement drops

1. Re-read it and write the actual goal at the top of `docs/PROBLEM.md`.
2. Pick the pattern from `examples/` closest to it — most TAK problems reduce
   to *get this data onto the shared map* or *react to what's on the map*.
3. Get the ugliest end-to-end version emitting real CoT within the first hour.
   A crude thing on the map beats an elegant thing in a terminal.
4. Only then make it good.

## Gotchas

- Windows consoles are cp1252; keep runtime output ASCII.
- A quiet UDP port is not an error. It usually means nobody is rebroadcasting.
- Sending to a multicast group (239.x.x.x) needs everyone on the same LAN;
  `239.2.3.1:6969` is the TAK mesh convention and works with no server at all —
  a good fallback if the venue's server misbehaves.
- If markers appear then vanish, your `stale` is shorter than your send interval.
- If markers pile up instead of moving, your `uid` is changing between sends.
