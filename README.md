# tak-bridge — Python CoT starter for the hackathon

A minimal, runnable Python project for streaming **Cursor-on-Target (CoT)**
to a TAK server. This is the fast-to-demo path: get data onto everyone's map
without touching Android.

## Files
| File | What it does |
|------|--------------|
| `cot.py` | Builds a CoT `<event>` (the one thing you'll reuse everywhere) |
| `send_cot.py` | Streams a single moving marker — your "hello world" |
| `feed_bridge.py` | **The template that wins.** Turn an external feed into CoT markers |
| `recv_cot.py` | Raw-socket listener to confirm the server is alive |
| `config.ini.example` | Server URL + TLS cert config |

## Setup (do this before Saturday)
```bash
cd tak-bridge
python -m venv .venv && source .venv/bin/activate     # optional but tidy
pip install -r requirements.txt
cp config.ini.example config.ini                       # then edit COT_URL
```

## Test it locally (no event server needed yet)
Stand up a throwaway server so you can see markers land:
```bash
pip install taky        # tiny CoT router
taky                    # listens on tcp 8087 by default
```
Then in another terminal:
```bash
python send_cot.py      # watch it connect + send ticks
python recv_cot.py 127.0.0.1 8087   # see the CoT come back
```
Point an ATAK client (or WebTAK) at the same server and your marker appears
on the map, moving every 5 seconds.

## On event day
1. Get the **server IP** and (for TLS) a **data package** with your certs.
2. Edit `config.ini` → set `COT_URL` to `tcp://THEIR_IP:8087`
   (or `tls://THEIR_IP:8089` + cert paths — see the extract commands in the config).
3. `python send_cot.py` → confirm your marker shows up on the shared map.
4. Open `feed_bridge.py`, replace `fetch_items()` with your real data source,
   and you've got your hackathon project skeleton.

## CoT type codes you'll use most
- `a-f-G-U-C` friendly ground unit · `a-h-G` hostile ground · `a-u-G` unknown ground
- `a-f-A` friendly air · `b-m-p-s-p-loc` waypoint · `b-t-f` GeoChat message

See the **TAK Hackathon Prep Pack** (the HTML brief) for the full protocol,
ports, and build-path rundown.
