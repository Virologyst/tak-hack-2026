"""THE TEMPLATE: turn an external data source into markers on everyone's map.

This is the shape most TAK hackathon projects take, and it's the reliable
scoring path — visible, fast to build, obviously useful.

**Replace `fetch_items()` with your real source and you are done.** Everything
below it already works: identity, staleness, error handling, reconnection.

    python examples/02_feed_bridge.py --url udp://10.0.0.42:6969

Your source can be anything: an HTTP API, a serial GPS, a database, a CSV, a
model's output, a websocket, a directory of files. It just has to return a
list of dicts with a stable id and a position.
"""

import _path  # noqa: F401  (lets this run without installing the package)
import argparse
import time

from taklib import TAKSender, cot
from taklib.config import resolve_url
from taklib import types as t

# Prefix every uid we emit so parallel testing from several laptops doesn't
# collide on the shared map. Change this to something yours.
UID_PREFIX = "feed"

POLL_SECONDS = 10
STALE_SECONDS = 60      # must exceed POLL_SECONDS or markers flicker out


def fetch_items():
    """STUB — replace this with your real feed.

    Return a list of dicts. Only `id`, `lat` and `lon` are required.

    Keep `id` STABLE across polls for the same real-world thing: that is what
    makes a marker move instead of spawning a duplicate every cycle.
    """
    return [
        {"id": "sensor-01", "lat": -27.4705, "lon": 153.0260,
         "type": t.UNKNOWN_GROUND, "label": "Unknown contact",
         "note": "detected, 0.82 confidence"},
        {"id": "sensor-02", "lat": -27.4750, "lon": 153.0300,
         "type": t.FRIENDLY_UNIT, "label": "Friendly unit",
         "note": "on patrol"},
    ]

    # Sketches of real sources, for when you swap this out:
    #
    # import urllib.request, json
    # with urllib.request.urlopen("https://api.example.com/things") as r:
    #     return [{"id": d["callsign"], "lat": d["latitude"], "lon": d["longitude"],
    #              "label": d["callsign"], "note": d.get("status", "")}
    #             for d in json.load(r)["results"]]
    #
    # import csv
    # with open("data.csv") as fh:
    #     return [{"id": row["id"], "lat": float(row["lat"]),
    #              "lon": float(row["lon"]), "label": row["name"]}
    #             for row in csv.DictReader(fh)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="udp://IP:PORT (else $COT_URL, else config.ini)")
    ap.add_argument("--interval", type=float, default=POLL_SECONDS)
    ap.add_argument("--once", action="store_true", help="one batch then exit")
    args = ap.parse_args()

    url = resolve_url(args.url)
    print(f"feed bridge -> {url}  (Ctrl-C to stop)")

    with TAKSender(url) as tak:
        batch = 0
        while True:
            try:
                items = fetch_items()
            except Exception as exc:            # noqa: BLE001
                # A flaky source must never kill the bridge. Log, wait, retry.
                print(f"  ! fetch failed: {exc}")
                time.sleep(args.interval)
                continue

            for item in items:
                tak.send(cot.unit(
                    uid=f"{UID_PREFIX}-{item['id']}",
                    lat=float(item["lat"]),
                    lon=float(item["lon"]),
                    callsign=item.get("label", item["id"]),
                    cot_type=item.get("type", t.UNKNOWN_GROUND),
                    remarks=item.get("note", ""),
                    stale=STALE_SECONDS,
                ))

            batch += 1
            print(f"  batch {batch}: published {len(items)} items")
            if args.once:
                return
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
