"""A minimal CoT router — a stand-in TAK server for local development.

This exists so nobody on the team is ever blocked on "we don't have the server
IP yet" or "the venue wifi is down". It accepts TCP connections on 8087, and
fans every CoT event it receives out to all the other connected clients, which
is the only behaviour most hackathon code actually depends on.

    python -m taklib.server                 # listen on 0.0.0.0:8087
    python -m taklib.server --record log.cot
    python -m taklib.server --replay log.cot --loop

It is NOT a TAK server: no auth, no certs, no federation, no protobuf, no data
packages. Point ATAK at a real TAK Server / FreeTAKServer for that. For
"does my bridge emit sane CoT and does everyone see it", this is enough and it
starts in a quarter of a second.
"""

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional, Set

from .cot import cot_time
from .listen import CoTStream, parse_cot

log = logging.getLogger("taklib.server")

EVENT_SEPARATOR = b"\n"


class CoTRouter:
    """Tracks connected clients and rebroadcasts events between them."""

    def __init__(self, echo: bool = False, record: Optional[Path] = None,
                 quiet: bool = False):
        self.clients: Set[asyncio.StreamWriter] = set()
        self.echo = echo
        self.quiet = quiet
        self.entities: Dict[str, dict] = {}   # uid -> last parsed event
        self.count = 0
        self._record_fh = open(record, "ab") if record else None

    async def handle(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.clients.add(writer)
        log.info("+ client %s (%d connected)", peer, len(self.clients))

        # Replay current state so a client joining late still sees the picture.
        await self._send_state(writer)

        stream = CoTStream()
        try:
            while True:
                chunk = await reader.read(8192)
                if not chunk:
                    break
                for raw in stream.feed(chunk):
                    await self.dispatch(raw, source=writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.clients.discard(writer)
            writer.close()
            log.info("- client %s (%d connected)", peer, len(self.clients))

    async def dispatch(self, raw: bytes, source: Optional[asyncio.StreamWriter] = None):
        """Record, log, and fan one event out to the other clients."""
        self.count += 1
        parsed = parse_cot(raw)
        if parsed:
            self.entities[parsed["uid"]] = parsed
            if not self.quiet:
                log.info(
                    "%-22s %-14s %10.5f,%-10.5f  %s",
                    (parsed["callsign"] or parsed["uid"])[:22],
                    parsed["type"][:14],
                    parsed["lat"], parsed["lon"],
                    (parsed["remarks"] or "")[:40],
                )
        if self._record_fh:
            self._record_fh.write(raw + EVENT_SEPARATOR)
            self._record_fh.flush()

        targets = [w for w in self.clients if self.echo or w is not source]
        for w in targets:
            try:
                w.write(raw + EVENT_SEPARATOR)
                await w.drain()
            except (ConnectionError, RuntimeError):
                self.clients.discard(w)

    async def _send_state(self, writer: asyncio.StreamWriter) -> None:
        for evt in list(self.entities.values()):
            try:
                writer.write(evt["raw"] + EVENT_SEPARATOR)
            except (ConnectionError, RuntimeError):
                return
        try:
            await writer.drain()
        except (ConnectionError, RuntimeError):
            pass

    def close(self) -> None:
        if self._record_fh:
            self._record_fh.close()


async def serve(host: str = "0.0.0.0", port: int = 8087, **kwargs) -> None:
    """Run the router until cancelled."""
    router = CoTRouter(**kwargs)
    server = await asyncio.start_server(router.handle, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    log.info("CoT router listening on %s  (started %s)", addrs, cot_time())
    log.info("point your bridge at tcp://127.0.0.1:%d", port)
    try:
        async with server:
            await server.serve_forever()
    finally:
        router.close()


async def replay(path: Path, host: str, port: int, speed: float = 1.0,
                 loop_forever: bool = False, interval: float = 1.0, **kwargs) -> None:
    """Serve a recorded .cot file back out, so demos are reproducible.

    Useful when your data source only exists at the venue, or when you want the
    same scenario every time you rehearse the demo.
    """
    events = [e for e in path.read_bytes().split(EVENT_SEPARATOR) if e.strip()]
    log.info("replaying %d events from %s", len(events), path)

    router = CoTRouter(echo=True, **kwargs)
    server = await asyncio.start_server(router.handle, host, port)
    log.info("replay server on %s:%s", host, port)

    async with server:
        while True:
            for raw in events:
                await router.dispatch(raw)
                await asyncio.sleep(interval / max(speed, 0.01))
            if not loop_forever:
                break
            log.info("--- replay loop ---")
    router.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Minimal local CoT router for development")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8087)
    ap.add_argument("--echo", action="store_true",
                    help="also send events back to the client that sent them")
    ap.add_argument("--record", type=Path, help="append every event to this file")
    ap.add_argument("--replay", type=Path, help="serve a recorded file instead of listening")
    ap.add_argument("--loop", action="store_true", help="replay forever")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="seconds between replayed events")
    ap.add_argument("--quiet", action="store_true", help="don't log every event")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    try:
        if args.replay:
            asyncio.run(replay(args.replay, args.host, args.port, args.speed,
                               args.loop, args.interval, quiet=args.quiet))
        else:
            asyncio.run(serve(args.host, args.port, echo=args.echo,
                              record=args.record, quiet=args.quiet))
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
