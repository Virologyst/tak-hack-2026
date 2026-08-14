"""Send CoT to a TAK server.

Two senders, same idea:

* `TAKSender`      — blocking, dead simple, use it inside normal scripts
* `AsyncTAKSender` — asyncio, for when you're already in an event loop

Both speak `tcp://`, `tls://` and `udp://` (including mesh multicast), and both
reconnect on their own when the venue wifi drops — which it will.

Deliberately stdlib-only. `pytak` is excellent and you can absolutely use it
(see `docs/03-connection-playbook.md`), but a pip install failing on event
morning should never be what stops you demoing.
"""

import asyncio
import logging
import socket
import ssl
import struct
import time
import xml.etree.ElementTree as ET
from typing import Optional, Union
from urllib.parse import urlparse

log = logging.getLogger("taklib.send")

Event = Union[bytes, str, ET.Element]

DEFAULT_PORTS = {"tcp": 8087, "tls": 8089, "ssl": 8089, "udp": 6969}


def as_bytes(evt: Event) -> bytes:
    """Accept whatever the caller has — Element, str or bytes — return bytes."""
    if isinstance(evt, bytes):
        return evt
    if isinstance(evt, str):
        return evt.encode("utf-8")
    if isinstance(evt, ET.Element):
        return ET.tostring(evt, encoding="utf-8", xml_declaration=False)
    raise TypeError(f"cannot send a {type(evt).__name__}")


class _Target:
    """Parsed connection details from a COT_URL."""

    def __init__(self, url: str):
        if "://" not in url:
            url = f"tcp://{url}"
        p = urlparse(url)
        self.scheme = (p.scheme or "tcp").lower()
        self.host = p.hostname or "127.0.0.1"
        self.port = p.port or DEFAULT_PORTS.get(self.scheme, 8087)
        if self.scheme not in DEFAULT_PORTS:
            raise ValueError(
                f"unsupported scheme {self.scheme!r} — use tcp://, tls:// or udp://"
            )
        self.is_tls = self.scheme in ("tls", "ssl")
        self.is_udp = self.scheme == "udp"
        self.is_multicast = self.is_udp and _is_multicast(self.host)

    def __str__(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def _is_multicast(host: str) -> bool:
    try:
        first = int(host.split(".")[0])
    except (ValueError, IndexError):
        return False
    return 224 <= first <= 239


def build_tls_context(
    cert: Optional[str] = None,
    key: Optional[str] = None,
    password: Optional[str] = None,
    ca: Optional[str] = None,
    verify: bool = True,
) -> ssl.SSLContext:
    """TLS context for TAK's port 8089.

    `verify=False` is the "just get it working" escape hatch for the
    self-signed certs you'll meet at a hackathon. Say so out loud in the demo
    rather than shipping it.
    """
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
    if cert:
        ctx.load_cert_chain(certfile=cert, keyfile=key or cert, password=password)
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        log.warning("TLS certificate verification is OFF - testing only")
    return ctx


class TAKSender:
    """Blocking CoT sender with automatic reconnect.

    ::

        with TAKSender("tcp://10.0.0.42:8087") as tak:
            tak.send(cot.unit("alpha-01", -27.47, 153.02))

    Or without the context manager — it connects lazily on first `send()`.
    """

    def __init__(
        self,
        url: str,
        *,
        cert: Optional[str] = None,
        key: Optional[str] = None,
        password: Optional[str] = None,
        ca: Optional[str] = None,
        verify: bool = True,
        timeout: float = 10.0,
        retry: bool = True,
        max_backoff: float = 30.0,
    ):
        self.target = _Target(url)
        self.timeout = timeout
        self.retry = retry
        self.max_backoff = max_backoff
        self._sock: Optional[socket.socket] = None
        self._backoff = 1.0
        self.sent = 0

        self._tls_ctx = (
            build_tls_context(cert, key, password, ca, verify)
            if self.target.is_tls else None
        )

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> "TAKSender":
        """Open the socket. Safe to call repeatedly."""
        if self._sock is not None:
            return self
        tgt = self.target

        if tgt.is_udp:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if tgt.is_multicast:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            self._sock = s
            log.info("ready to send UDP to %s", tgt)
            return self

        raw = socket.create_connection((tgt.host, tgt.port), timeout=self.timeout)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = (
            self._tls_ctx.wrap_socket(raw, server_hostname=tgt.host)
            if self._tls_ctx else raw
        )
        self._backoff = 1.0
        log.info("connected to %s", tgt)
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self) -> "TAKSender":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- sending -----------------------------------------------------------
    def send(self, evt: Event) -> bool:
        """Send one event. Returns True if it went out.

        On a dropped connection this reconnects and retries once, so a flaky
        network shows up as a brief gap on the map rather than a dead script.
        """
        data = as_bytes(evt)
        for attempt in (1, 2):
            try:
                self.connect()
                if self.target.is_udp:
                    self._sock.sendto(data, (self.target.host, self.target.port))
                else:
                    self._sock.sendall(data)
                self.sent += 1
                return True
            except (OSError, ssl.SSLError) as exc:
                log.warning("send failed (%s): %s", attempt, exc)
                self.close()
                if attempt == 2 or not self.retry:
                    return False
                self._sleep_backoff()
        return False

    def send_many(self, events) -> int:
        """Send an iterable of events; returns how many made it."""
        return sum(1 for e in events if self.send(e))

    def _sleep_backoff(self) -> None:
        time.sleep(self._backoff)
        self._backoff = min(self._backoff * 2, self.max_backoff)


class AsyncTAKSender:
    """Same contract as `TAKSender`, for asyncio code.

    ::

        tak = AsyncTAKSender("tcp://10.0.0.42:8087")
        await tak.connect()
        await tak.send(cot.unit("alpha-01", -27.47, 153.02))
    """

    def __init__(self, url: str, **kwargs):
        self.target = _Target(url)
        self.timeout = kwargs.pop("timeout", 10.0)
        self.retry = kwargs.pop("retry", True)
        self.max_backoff = kwargs.pop("max_backoff", 30.0)
        verify = kwargs.pop("verify", True)
        self._tls_ctx = (
            build_tls_context(
                kwargs.pop("cert", None), kwargs.pop("key", None),
                kwargs.pop("password", None), kwargs.pop("ca", None), verify,
            )
            if self.target.is_tls else None
        )
        self._writer: Optional[asyncio.StreamWriter] = None
        self._udp: Optional[socket.socket] = None
        self._backoff = 1.0
        self._lock = asyncio.Lock()
        self.sent = 0

    async def connect(self) -> "AsyncTAKSender":
        if self.target.is_udp:
            if self._udp is None:
                self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                if self.target.is_multicast:
                    self._udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            return self
        if self._writer is not None:
            return self
        _, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.target.host, self.target.port,
                                    ssl=self._tls_ctx),
            timeout=self.timeout,
        )
        self._backoff = 1.0
        log.info("connected to %s", self.target)
        return self

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (OSError, ssl.SSLError):
                pass
            self._writer = None
        if self._udp is not None:
            self._udp.close()
            self._udp = None

    async def send(self, evt: Event) -> bool:
        data = as_bytes(evt)
        async with self._lock:
            for attempt in (1, 2):
                try:
                    await self.connect()
                    if self.target.is_udp:
                        self._udp.sendto(data, (self.target.host, self.target.port))
                    else:
                        self._writer.write(data)
                        await self._writer.drain()
                    self.sent += 1
                    return True
                except (OSError, ssl.SSLError, asyncio.TimeoutError) as exc:
                    log.warning("send failed (%s): %s", attempt, exc)
                    await self.close()
                    if attempt == 2 or not self.retry:
                        return False
                    await asyncio.sleep(self._backoff)
                    self._backoff = min(self._backoff * 2, self.max_backoff)
        return False


def multicast_socket(group: str = "239.2.3.1", port: int = 6969) -> socket.socket:
    """A socket joined to the TAK mesh SA multicast group, for listening.

    Mesh mode needs no server at all — handy if the venue network is locked
    down but everyone is on the same wifi.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    mreq = struct.pack("4sl", socket.inet_aton(group), socket.INADDR_ANY)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return s
