"""Hello world: put a moving marker on the map.

    python examples/01_send_marker.py
    python examples/01_send_marker.py --url udp://10.0.0.42:6969

The smallest complete thing. If this shows up on someone's ATAK, the pipe
works and everything else is just building on top.
"""

import _path  # noqa: F401  (lets this run without installing the package)
import argparse
import time

from taklib import TAKSender, cot
from taklib.config import identity, resolve_url


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="udp://IP:PORT (else $COT_URL, else config.ini)")
    ap.add_argument("--lat", type=float, default=-27.4705)
    ap.add_argument("--lon", type=float, default=153.0260)
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()

    me = identity()
    url = resolve_url(args.url)
    lat, lon = args.lat, args.lon

    # The context manager just opens the socket up front; UDP has no handshake.
    with TAKSender(url) as tak:
        print(f"sending as {me['callsign']} to {url}  (Ctrl-C to stop)")
        step = 0
        while True:
            # Same uid every time, so the marker MOVES rather than multiplying.
            tak.send(cot.unit(
                uid=me["uid"],
                lat=lat + step * 0.0002,
                lon=lon + step * 0.0002,
                callsign=me["callsign"],
                team=me["team"],
                remarks=f"hello from taklib, tick {step}",
                stale=120,          # comfortably longer than our 5s interval
            ))
            print(f"  tick {step}: {lat + step * 0.0002:.5f}, {lon + step * 0.0002:.5f}")
            step += 1
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
