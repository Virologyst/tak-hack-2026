"""Watch an area and raise the alarm when something enters it.

The "react to the map" pattern. Draws the geofence so everyone can see it,
then watches traffic and fires a GeoChat message plus a marker when anything
crosses in.

    python examples/04_geofence_alert.py --url udp://10.0.0.42:6969

Locally:
    terminal 1: python examples/04_geofence_alert.py --url udp://127.0.0.1:6969 \
                    --listen-url udp://0.0.0.0:6969
    terminal 2: python tak.py send --url udp://127.0.0.1:6969 \
                    --lat -27.4705 --lon 153.0260
"""

import _path  # noqa: F401  (lets this run without installing the package)
import argparse
import time

from taklib import TAKListener, TAKSender, cot, geo
from taklib.config import resolve_url

BOT_UID = "taklib-geofence"
BOT_CALLSIGN = "GEOFENCE"

# The area of interest. Any list of (lat, lon) works — this one is a circle,
# but swap in a hand-drawn polygon or something computed from your data.
CENTRE = (-27.4705, 153.0260)
RADIUS_M = 400
FENCE = geo.circle_points(CENTRE[0], CENTRE[1], RADIUS_M, segments=24)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="where to SEND alerts")
    ap.add_argument("--listen-url", help="where to LISTEN (default: same as --url)")
    ap.add_argument("--redraw", type=float, default=60,
                    help="seconds between redrawing the fence")
    args = ap.parse_args()

    send_url = resolve_url(args.url)
    listen_url = args.listen_url or send_url
    tak = TAKSender(send_url)

    def draw_fence():
        # Long stale, redrawn periodically, so it never quietly expires.
        tak.send(cot.polygon(
            f"{BOT_UID}-fence", FENCE, name="WATCH AREA",
            stroke_colour=cot.YELLOW, fill_colour=cot.argb(40, 255, 200, 0),
            stale=args.redraw * 3,
            remarks=f"{RADIUS_M} m watch radius",
        ))

    draw_fence()
    last_draw = time.time()
    print(f"watching a {RADIUS_M} m area at {CENTRE[0]}, {CENTRE[1]}")
    print(f"listening on {listen_url}, alerting to {send_url}\n")

    inside: set[str] = set()          # who is currently in the fence

    for evt in TAKListener(listen_url, timeout=5):
        if time.time() - last_draw > args.redraw:
            draw_fence()
            last_draw = time.time()

        # Ignore chat and our own output, or we alert on our own alerts.
        if evt["is_chat"] or evt["uid"].startswith(BOT_UID):
            continue
        if not (evt["lat"] or evt["lon"]):
            continue

        uid = evt["uid"]
        who = evt["callsign"] or uid
        now_inside = geo.point_in_polygon(evt["lat"], evt["lon"], FENCE)
        dist = geo.haversine(CENTRE[0], CENTRE[1], evt["lat"], evt["lon"])

        if now_inside and uid not in inside:
            inside.add(uid)
            msg = f"{who} ENTERED the watch area ({geo.format_distance(dist)} from centre)"
            print(f"  ALERT  {msg}")
            tak.send(cot.geochat(msg, sender_uid=BOT_UID, sender_callsign=BOT_CALLSIGN))
            # Drop a visible marker where the breach happened.
            tak.send(cot.marker(
                f"{BOT_UID}-breach-{uid}", evt["lat"], evt["lon"],
                label=f"BREACH: {who}", colour=cot.RED,
                remarks=msg, stale=600,
            ))

        elif not now_inside and uid in inside:
            inside.discard(uid)
            msg = f"{who} left the watch area"
            print(f"  clear  {msg}")
            tak.send(cot.geochat(msg, sender_uid=BOT_UID, sender_callsign=BOT_CALLSIGN))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
