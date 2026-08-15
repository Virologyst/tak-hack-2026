#!/usr/bin/env python
"""tak — one command for everything in this repo.

    python tak.py selftest                      prove the whole stack works locally
    python tak.py serve                         run a local CoT router (no venue server needed)
    python tak.py status 10.0.0.42              what's open on their server?
    python tak.py send --url tcp://IP:8087      put a moving marker on the map
    python tak.py listen --url tcp://IP:8087    tail everything on the network
    python tak.py chat "message"                broadcast to GeoChat
    python tak.py dashboard                     live web view for the big screen

Every command takes --url, falls back to $COT_URL, then to config.ini, then to
tcp://127.0.0.1:8087. So `export COT_URL=tcp://their-ip:8087` once and forget it.
"""

import argparse
import logging
import socket
import sys
import time

from taklib import TAKListener, TAKSender, cot, geo
from taklib.config import identity, load_config, resolve_url, sender_kwargs
from taklib.types import describe


def _sender(args) -> TAKSender:
    cfg = load_config()
    kwargs = sender_kwargs(cfg)
    if getattr(args, "insecure", False):
        kwargs["verify"] = False
    return TAKSender(resolve_url(args.url), **kwargs)


def _listener_kwargs(args) -> dict:
    kwargs = sender_kwargs(load_config())
    if getattr(args, "insecure", False):
        kwargs["verify"] = False
    return kwargs


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_send(args) -> int:
    """Stream a marker. Moves slightly each tick so you can see it's live."""
    me = identity()
    uid = args.uid or me["uid"]
    callsign = args.callsign or me["callsign"]
    lat, lon = args.lat, args.lon

    with _sender(args) as tak:
        print(f"sending as {callsign} ({uid}) -> {tak.target}")
        step = 0
        while True:
            ok = tak.send(cot.unit(
                uid, lat + step * args.drift, lon + step * args.drift,
                callsign=callsign, team=me["team"], cot_type=args.type,
                remarks=args.remarks or f"tick {step}", stale=args.stale,
            ))
            print(f"  [{'ok' if ok else 'FAIL'}] tick {step} "
                  f"{lat + step * args.drift:.5f},{lon + step * args.drift:.5f}")
            step += 1
            if args.once or (args.count and step >= args.count):
                return 0 if ok else 1
            time.sleep(args.interval)


def cmd_listen(args) -> int:
    """Print everything arriving on the network."""
    url = resolve_url(args.url)
    print(f"listening on {url} - Ctrl-C to stop\n")
    seen = set()
    for evt in TAKListener(url, **_listener_kwargs(args)):
        if args.chat_only and not evt["is_chat"]:
            continue
        if evt["is_chat"]:
            print(f"  CHAT  {evt.get('sender_callsign', '?'):<16} "
                  f"[{evt.get('chatroom', '')}] {evt['message']}")
        else:
            first = "NEW " if evt["uid"] not in seen else "    "
            seen.add(evt["uid"])
            print(f"  {first}{evt['callsign'] or evt['uid']:<20} "
                  f"{evt['type']:<16} {evt['lat']:>10.5f},{evt['lon']:<11.5f} "
                  f"{describe(evt['type'])}"
                  + (f" | {evt['remarks'][:40]}" if evt["remarks"] else ""))
        if args.count and len(seen) >= args.count:
            return 0
    return 0


def cmd_chat(args) -> int:
    """Broadcast a GeoChat message."""
    me = identity()
    with _sender(args) as tak:
        ok = tak.send(cot.geochat(
            args.message,
            sender_uid=me["uid"], sender_callsign=args.callsign or me["callsign"],
            chatroom=args.room,
        ))
    print("sent" if ok else "FAILED to send")
    return 0 if ok else 1


def cmd_serve(args) -> int:
    """Run the local development CoT router."""
    from taklib.server import main as server_main
    sys.argv = ["taklib.server", "--host", args.host, "--port", str(args.port)]
    if args.echo:
        sys.argv.append("--echo")
    server_main()
    return 0


def cmd_dashboard(args) -> int:
    from taklib.dashboard import main as dash_main
    sys.argv = ["taklib.dashboard", "--port", str(args.port)]
    if args.url:
        sys.argv += ["--url", args.url]
    dash_main()
    return 0


def cmd_status(args) -> int:
    """Probe the venue's server: is anything reachable, is CoT flowing?

    This is the first thing to run when they hand you an IP.

    Given a udp:// URL this does the UDP version of the check (see
    `_status_udp`); given a bare hostname it scans the TCP ports instead.
    """
    if "://" in args.host:
        return _status_udp(args)

    host = args.host
    ports = {
        8087: "CoT streaming, plain TCP",
        8089: "CoT streaming, TLS (client cert required)",
        8443: "web UI / cert enrollment (HTTPS)",
        8446: "cert enrollment (HTTPS)",
        8080: "web UI (plain HTTP)",
    }
    print(f"probing {host}\n")
    open_ports = []
    for port, what in ports.items():
        t0 = time.time()
        try:
            with socket.create_connection((host, port), timeout=args.timeout):
                ms = (time.time() - t0) * 1000
                print(f"  OPEN    {port:<6} {what}  ({ms:.0f} ms)")
                open_ports.append(port)
        except socket.timeout:
            print(f"  timeout {port:<6} {what}")
        except OSError as exc:
            print(f"  closed  {port:<6} {what}  ({exc.__class__.__name__})")

    if not open_ports:
        print("\nNothing answered. Check you're on their network / VPN, "
              "and that the IP is right.")
        return 1

    if 8087 in open_ports:
        print(f"\nlistening on tcp://{host}:8087 for {args.listen}s to see live traffic...")
        seen, chats = {}, 0
        listener = TAKListener(f"tcp://{host}:8087", reconnect=False,
                               timeout=2, stop_after=args.listen)
        try:
            for evt in listener:
                if evt["is_chat"]:
                    chats += 1
                else:
                    seen[evt["uid"]] = evt["callsign"] or evt["uid"]
        except (OSError, KeyboardInterrupt):
            pass
        finally:
            listener.close()

        if seen or chats:
            print(f"  {len(seen)} entities, {chats} chat messages:")
            for uid, cs in list(seen.items())[:15]:
                print(f"    {cs}  ({uid})")
        else:
            print("  connected fine, but nothing was broadcast in that window.")
            print("  (normal on a quiet server - try `python tak.py send` from "
                  "another terminal)")
    elif 8089 in open_ports:
        print("\nOnly the TLS port is open - you'll need the data package / client "
              "certs.\n  See docs/03-connection-playbook.md for the .p12 extraction.")
    return 0


def _status_udp(args) -> int:
    """Check a UDP target.

    UDP is fire-and-forget: nothing acknowledges you, so "did it arrive?" is
    not a question the network can answer. What this CAN tell you is
    (a) the datagrams left this machine without an OS-level error, and
    (b) whether anything is being broadcast back on that port, which is the
    case if the venue's server rebroadcasts or you're on the mesh group.

    Ground truth is still someone with ATAK open saying "yep, I see it".
    """
    import threading
    from taklib.send import _Target

    url = args.host
    target = _Target(url)
    print(f"target   : {target}")
    print(f"transport: UDP {'multicast (mesh)' if target.is_multicast else 'unicast'}")
    print("note     : UDP is unacknowledged - a clean send is not proof of delivery\n")

    seen = []

    def watch():
        try:
            for evt in TAKListener(f"udp://0.0.0.0:{target.port}", reconnect=False,
                                   stop_after=args.listen):
                seen.append(evt)
        except OSError as exc:
            print(f"  (could not bind UDP {target.port} to listen: {exc})")

    th = threading.Thread(target=watch, daemon=True)
    th.start()
    time.sleep(0.5)

    tak = TAKSender(url)
    me = identity()
    sent = 0
    for i in range(3):
        if tak.send(cot.unit(f"{me['uid']}-probe", -27.4705 + i * 0.0005, 153.0260,
                             callsign=f"{me['callsign']}-PROBE",
                             remarks=f"connectivity probe {i + 1}/3", stale=60)):
            sent += 1
        time.sleep(0.3)
    print(f"  sent {sent}/3 probe datagrams with no socket error"
          if sent == 3 else f"  WARNING: only {sent}/3 datagrams sent cleanly")

    print(f"  listening on udp/{target.port} for {args.listen:.0f}s...")
    th.join(timeout=args.listen + 3)

    others = [e for e in seen if not e["uid"].endswith("-probe")]
    if seen:
        print(f"  saw {len(seen)} events on that port "
              f"({len(others)} from someone other than us)")
        for e in list({e["uid"]: e for e in seen}.values())[:15]:
            who = e["callsign"] or e.get("sender_callsign") or e["uid"]
            print(f"    {who:<20} {e['type']:<14} {e['lat']:.5f},{e['lon']:.5f}")
        if others:
            print("\n  Traffic from other sources - you are on the right network.")
        else:
            print("\n  Only our own probes came back (normal for a straight "
                  "unicast feed).\n  Confirm with someone running ATAK.")
    else:
        print("  nothing received on that port.")
        print("  That's expected for a pure send-only unicast feed. If you "
              "expected\n  mesh traffic, check you're on their wifi and the "
              "port is right.")
    return 0


def cmd_selftest(args) -> int:
    """Prove the whole stack works on this machine, with no network at all.

    Run this on every laptop before the event. If it passes, that machine can
    build and demo.
    """
    import asyncio
    import threading

    print("TAK bridge self-test\n" + "-" * 46)
    ok = True

    def check(name, condition, detail=""):
        nonlocal ok
        ok = ok and condition
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))

    print(f"  python {sys.version.split()[0]}")

    # 1. build + parse
    from taklib.listen import parse_cot
    evt = cot.unit("selftest-1", -27.4705, 153.0260, callsign="SELFTEST",
                   remarks="hello", course=45, speed=2.0)
    parsed = parse_cot(evt)
    check("build and parse a CoT event", parsed is not None and parsed["callsign"] == "SELFTEST")
    check("geo helpers", round(geo.haversine(-27.47, 153.02, -27.48, 153.03)) == 1487,
          f"1487 m expected")

    # Vocabulary: prove the Tak-word catalogue is still honest. A word here that
    # no longer matches anything in interpret.py would be accepted into a
    # dictionary and then build nothing, silently - so a regex edit that orphans
    # one must fail a test rather than surface as an empty map at the venue.
    from taklib.voice import takwords, vocab
    dead = takwords.verify()
    check("tak word catalogue", not dead,
          f"{len(takwords.CATALOGUE)} terms" if not dead
          else f"{len(dead)} dead: {dead[0]}")
    v = vocab.Vocabulary(
        [vocab.Term(1, None, "ambo", "ambulance"),
         vocab.Term(2, "SAS", "fire", vocab.IGNORE),
         vocab.Term(3, "FIRE", "fire", "fire")])
    sas, _ = v.substitute("fire at the gate", "SAS")
    fire, _ = v.substitute("fire at the gate", "FIRE")
    check("per-service vocabulary", sas == "at the gate" and fire == "fire at the gate",
          "same word, different service, different meaning")

    # 2. optional third-party bits
    for mod, why in (("pytak", "alternative sender"), ("takproto", "protobuf/v1 servers")):
        try:
            __import__(mod)
            print(f"  [ ok ] {mod} installed ({why})")
        except ImportError:
            print(f"  [note] {mod} not installed - optional, needed for {why}")

    # 3. full loopback: router + sender + listener
    port = 18087
    loop = asyncio.new_event_loop()
    from taklib.server import serve

    def run_server():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(serve("127.0.0.1", port, quiet=True))
        except Exception:  # noqa: BLE001 — reported via the check below
            pass

    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(0.8)

    received = []

    def run_listener():
        for e in TAKListener(f"tcp://127.0.0.1:{port}", reconnect=False, timeout=6):
            received.append(e)
            if len(received) >= 2:
                return

    lt = threading.Thread(target=run_listener, daemon=True)
    lt.start()
    time.sleep(0.5)

    sent = 0
    try:
        with TAKSender(f"tcp://127.0.0.1:{port}") as tak:
            tak.send(cot.unit("selftest-a", -27.47, 153.02, callsign="ALPHA"))
            tak.send(cot.geochat("selftest", sender_uid="selftest",
                                 sender_callsign="SELFTEST"))
            sent = tak.sent
    except OSError as exc:
        print(f"  [FAIL] could not connect to the local router: {exc}")

    check("local CoT router accepts connections", sent == 2, f"{sent}/2 sent")
    lt.join(timeout=6)
    check("events route sender -> server -> listener", len(received) >= 2,
          f"{len(received)}/2 received")
    if received:
        check("chat message survives the round trip",
              any(r["is_chat"] for r in received))

    print("-" * 46)
    print("ALL GOOD - this machine is ready." if ok else
          "SOMETHING FAILED — see above before the event.")
    return 0 if ok else 1


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tak", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    subs = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--url", help="tcp://IP:8087 / tls://IP:8089 (else $COT_URL, config.ini)")
        p.add_argument("--insecure", action="store_true", help="skip TLS verification")
        return p

    s = common(subs.add_parser("send", help="stream a marker to the map"))
    s.add_argument("--lat", type=float, default=-27.4705)
    s.add_argument("--lon", type=float, default=153.0260)
    s.add_argument("--uid"), s.add_argument("--callsign")
    s.add_argument("--type", default="a-f-G-U-C", help="CoT type code")
    s.add_argument("--remarks", default="")
    s.add_argument("--interval", type=float, default=5.0)
    s.add_argument("--drift", type=float, default=0.0002, help="degrees moved per tick")
    s.add_argument("--stale", type=float, default=120)
    s.add_argument("--count", type=int, default=0, help="stop after N ticks")
    s.add_argument("--once", action="store_true")
    s.set_defaults(func=cmd_send)

    l = common(subs.add_parser("listen", help="print CoT arriving on the network"))
    l.add_argument("--chat-only", action="store_true")
    l.add_argument("--count", type=int, default=0, help="stop after N distinct uids")
    l.set_defaults(func=cmd_listen)

    c = common(subs.add_parser("chat", help="broadcast a GeoChat message"))
    c.add_argument("message")
    c.add_argument("--room", default="All Chat Rooms")
    c.add_argument("--callsign")
    c.set_defaults(func=cmd_chat)

    sv = subs.add_parser("serve", help="run a local CoT router for development")
    sv.add_argument("--host", default="0.0.0.0"), sv.add_argument("--port", type=int, default=8087)
    sv.add_argument("--echo", action="store_true")
    sv.set_defaults(func=cmd_serve)

    d = subs.add_parser("dashboard", help="live web view of the whole network")
    d.add_argument("--url"), d.add_argument("--port", type=int, default=8080)
    d.set_defaults(func=cmd_dashboard)

    st = subs.add_parser("status", help="probe the venue's server (UDP url or hostname)")
    st.add_argument("host", help="udp://IP:PORT for the UDP check, or a bare IP to scan TCP ports")
    st.add_argument("--timeout", type=float, default=3.0)
    st.add_argument("--listen", type=float, default=8.0, help="seconds to watch for traffic")
    st.set_defaults(func=cmd_status)

    stf = subs.add_parser("selftest", help="verify this machine end to end (no network)")
    stf.set_defaults(func=cmd_selftest)

    return ap


def main() -> int:
    # Windows consoles default to cp1252 and choke on anything typographic.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nbye")
        return 0


if __name__ == "__main__":
    sys.exit(main())
