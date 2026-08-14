"""A GeoChat bot: the map talks back.

Listens for chat messages and answers them. Demos extremely well, because a
judge can type a question on a phone and watch it get answered.

    python examples/03_geochat_bot.py --url udp://10.0.0.42:6969

IMPORTANT for UDP: to *hear* messages you need traffic coming back to you,
which means either the venue's server rebroadcasts, or you're on the mesh
multicast group. If it's a send-only unicast feed, pass --listen-url with a
port you do receive on, or run this against the mesh group.

Try it locally first:
    terminal 1: python examples/03_geochat_bot.py --url udp://127.0.0.1:6969 \
                    --listen-url udp://0.0.0.0:6969
    terminal 2: python tak.py chat "status" --url udp://127.0.0.1:6969
"""

import _path  # noqa: F401  (lets this run without installing the package)
import argparse

from taklib import TAKListener, TAKSender, cot, geo
from taklib.config import identity, resolve_url

BOT_UID = "taklib-bot"
BOT_CALLSIGN = "BOT"

# What the bot knows about. In a real build this would come from your feed,
# or from the entities you've been tracking off the network.
ASSETS = [
    {"name": "MEDIC-1", "lat": -27.4680, "lon": 153.0245, "kind": "medic"},
    {"name": "ALPHA-2", "lat": -27.4750, "lon": 153.0310, "kind": "patrol"},
    {"name": "SUPPLY", "lat": -27.4800, "lon": 153.0200, "kind": "logistics"},
]


def answer(message: str, sender_lat: float, sender_lon: float) -> str | None:
    """Work out a reply, or None to stay quiet.

    Keep the bot quiet by default — a bot that answers everything is noise,
    and noise on a shared map is actively harmful.
    """
    text = message.lower().strip()

    if text.startswith(("help", "?")):
        return "commands: status | nearest <kind> | assets"

    if text.startswith("status"):
        return f"bridge up, tracking {len(ASSETS)} assets"

    if text.startswith("assets"):
        return " | ".join(f"{a['name']} ({a['kind']})" for a in ASSETS)

    if text.startswith("nearest"):
        kind = text.replace("nearest", "").strip()
        pool = [a for a in ASSETS if not kind or a["kind"].startswith(kind)]
        if not pool:
            return f"nothing matching '{kind}'"
        if not (sender_lat or sender_lon):
            return "I don't have your position yet - send a location first"
        best, dist = geo.nearest(sender_lat, sender_lon, pool)
        return f"{best['name']} at {geo.format_distance(dist)}, bearing " \
               f"{geo.bearing(sender_lat, sender_lon, best['lat'], best['lon']):.0f} deg"

    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="where to SEND replies")
    ap.add_argument("--listen-url", help="where to LISTEN (default: same as --url)")
    args = ap.parse_args()

    send_url = resolve_url(args.url)
    listen_url = args.listen_url or send_url
    print(f"bot listening on {listen_url}, replying to {send_url}")
    print("say 'help' in GeoChat.  Ctrl-C to stop.\n")

    # Track where people are, so "nearest" can use the asker's own position.
    positions: dict[str, tuple[float, float]] = {}

    tak = TAKSender(send_url)
    for evt in TAKListener(listen_url):
        if not evt["is_chat"]:
            if evt["lat"] or evt["lon"]:
                positions[evt["uid"]] = (evt["lat"], evt["lon"])
            continue

        sender_uid = evt.get("sender_uid", "")
        if sender_uid == BOT_UID:
            continue                     # never reply to ourselves

        msg = evt.get("message", "")
        print(f"  <{evt.get('sender_callsign', '?')}> {msg}")

        lat, lon = positions.get(sender_uid, (evt["lat"], evt["lon"]))
        reply = answer(msg, lat, lon)
        if reply is None:
            continue

        # Reply privately to the asker: both to_uid AND chatroom are needed,
        # otherwise it silently broadcasts to everyone.
        tak.send(cot.geochat(
            reply,
            sender_uid=BOT_UID, sender_callsign=BOT_CALLSIGN,
            to_uid=sender_uid or None,
            chatroom=evt.get("sender_callsign") or "All Chat Rooms",
        ))
        print(f"  >{BOT_CALLSIGN}> {reply}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
