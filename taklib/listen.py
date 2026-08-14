"""Read CoT off a TAK server and turn it into Python dicts.

Half the good hackathon ideas are *reactive*: watch what's on the map, then do
something. A GeoChat bot, a geofence alarm, a dashboard, an analytics feed —
all of them start here.

    for evt in TAKListener("tcp://10.0.0.42:8087"):
        print(evt["callsign"], evt["lat"], evt["lon"])

`parse_cot()` is also useful on its own for anything that hands you CoT XML.
"""

import logging
import socket
import ssl
import xml.etree.ElementTree as ET
from typing import Dict, Iterator, List, Optional, Union

from .cot import parse_cot_time
from .send import _Target, build_tls_context

log = logging.getLogger("taklib.listen")

TAK_PROTO_MAGIC = 0xBF  # 191 — first byte of a TAK Protocol v1 (protobuf) frame


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def parse_cot(raw: Union[bytes, str, ET.Element]) -> Optional[Dict]:
    """Flatten a CoT event into a dict of the things you usually want.

    Returns None if it isn't parseable CoT. The full `<detail>` element is kept
    under `"detail"` so you can dig for anything this doesn't surface, and the
    original XML under `"raw"`.
    """
    try:
        evt = raw if isinstance(raw, ET.Element) else ET.fromstring(raw)
    except ET.ParseError:
        return None
    if evt.tag != "event":
        return None

    point = evt.find("point")
    detail = evt.find("detail")

    out: Dict = {
        "uid": evt.get("uid", ""),
        "type": evt.get("type", ""),
        "how": evt.get("how", ""),
        "time": evt.get("time", ""),
        "start": evt.get("start", ""),
        "stale": evt.get("stale", ""),
        "lat": _float(point, "lat"),
        "lon": _float(point, "lon"),
        "hae": _float(point, "hae"),
        "ce": _float(point, "ce"),
        "le": _float(point, "le"),
        "callsign": "",
        "team": "",
        "role": "",
        "remarks": "",
        "detail": detail,
        "raw": raw if isinstance(raw, (bytes, str)) else ET.tostring(evt),
    }

    if detail is not None:
        contact = detail.find("contact")
        if contact is not None:
            out["callsign"] = contact.get("callsign", "")
            for key in ("endpoint", "phone"):
                if contact.get(key):
                    out[key] = contact.get(key)

        group = detail.find("__group")
        if group is not None:
            out["team"] = group.get("name", "")
            out["role"] = group.get("role", "")

        remarks = detail.find("remarks")
        if remarks is not None and remarks.text:
            out["remarks"] = remarks.text.strip()

        track = detail.find("track")
        if track is not None:
            out["course"] = _attr_float(track, "course")
            out["speed"] = _attr_float(track, "speed")

        status = detail.find("status")
        if status is not None and status.get("battery"):
            out["battery"] = _attr_float(status, "battery")

        # Our own detection payload from cot.detection()
        det = detail.find("detection")
        if det is not None:
            out["detection"] = dict(det.attrib)

        chat = detail.find("__chat")
        if chat is not None:
            out["is_chat"] = True
            out["chatroom"] = chat.get("chatroom", "")
            out["sender_callsign"] = chat.get("senderCallsign", "")
            out["message_id"] = chat.get("messageId", "")
            out["message"] = out["remarks"]
            grp = chat.find("chatgrp")
            if grp is not None:
                out["sender_uid"] = grp.get("uid0", "")
                out["recipient_uid"] = grp.get("uid1", "")

    out["is_chat"] = out.get("is_chat", False)
    out["stale_at"] = parse_cot_time(out["stale"])
    return out


def _float(el: Optional[ET.Element], key: str) -> float:
    if el is None:
        return 0.0
    return _attr_float(el, key)


def _attr_float(el: ET.Element, key: str) -> float:
    try:
        return float(el.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------
# framing
# --------------------------------------------------------------------------

class CoTStream:
    """Reassembles a byte stream into whole CoT events.

    TCP gives you arbitrary chunks; CoT events are XML documents jammed
    together with no length prefix. Feed bytes in, get complete events out.

    Also detects TAK Protocol v1 (protobuf) frames — they start with 0xBF — and
    decodes them if `takproto` is installed, so you notice immediately rather
    than staring at binary at 1am.
    """

    def __init__(self, max_buffer: int = 1 << 22):
        self.buffer = bytearray()
        self.max_buffer = max_buffer
        self._warned_proto = False

    def feed(self, chunk: bytes) -> List[bytes]:
        """Add received bytes, return any complete `<event>...</event>` blobs."""
        self.buffer.extend(chunk)
        events: List[bytes] = []

        while True:
            if not self.buffer:
                break

            if self.buffer[0] == TAK_PROTO_MAGIC:
                decoded, consumed = self._try_protobuf()
                if consumed == 0:
                    break            # incomplete frame — wait for more bytes
                del self.buffer[:consumed]
                if decoded:
                    events.append(decoded)
                continue

            end = self.buffer.find(b"</event>")
            if end == -1:
                # Drop leading junk so one bad byte can't wedge the stream.
                start = self.buffer.find(b"<event")
                if start > 0:
                    del self.buffer[:start]
                elif start == -1 and len(self.buffer) > self.max_buffer:
                    log.warning("buffer overflow with no event found - resetting")
                    self.buffer.clear()
                break

            end += len(b"</event>")
            chunk_bytes = bytes(self.buffer[:end])
            del self.buffer[:end]
            start = chunk_bytes.find(b"<event")
            if start != -1:
                events.append(chunk_bytes[start:])

        return events

    def _try_protobuf(self):
        """Decode one TAK Protocol v1 frame. Returns (xml_bytes|None, consumed).

        Framing (see docs/03-connection-playbook.md):
          stream: 0xBF <varint payload-length> <protobuf payload>
          mesh:   0xBF 0x01 0xBF <protobuf payload>   (one per datagram)

        `consumed == 0` means "incomplete, come back with more bytes".
        """
        buf = self.buffer

        # Mesh framing is a fixed 3-byte header and runs to the end of the datagram.
        if len(buf) >= 3 and buf[1] == 0x01 and buf[2] == TAK_PROTO_MAGIC:
            payload, consumed = bytes(buf[3:]), len(buf)
        else:
            length, header_len = _read_varint(buf, 1)
            if length is None:
                return None, 0                      # varint not fully arrived
            end = header_len + length
            if len(buf) < end:
                return None, 0                      # payload not fully arrived
            payload, consumed = bytes(buf[header_len:end]), end

        xml = _proto_to_xml(payload)
        if xml is None and not self._warned_proto:
            log.warning(
                "this server speaks TAK Protocol v1 (protobuf). Install the decoder "
                "with: pip install takproto  — otherwise these events are skipped."
            )
            self._warned_proto = True
        return xml, consumed


# --------------------------------------------------------------------------
# the listener
# --------------------------------------------------------------------------

class TAKListener:
    """Iterate parsed CoT events from a TAK server.

    ::

        for evt in TAKListener("tcp://10.0.0.42:8087"):
            if evt["is_chat"]:
                print(evt["sender_callsign"], ":", evt["message"])

    Reconnects on its own. Set `raw=True` to get bytes instead of dicts.
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
        timeout: float = 30.0,
        reconnect: bool = True,
        raw: bool = False,
        announce: Optional[bytes] = None,
        stop_after: Optional[float] = None,
    ):
        self.target = _Target(url)
        self.timeout = timeout
        self.reconnect = reconnect
        self.raw = raw
        # Wall-clock limit on the whole iteration. Without this, a quiet server
        # parks you in recv() forever, because the loop only regains control
        # when an event actually arrives.
        self.stop_after = stop_after
        self._deadline: Optional[float] = None
        # Some TAK servers stay silent until the client identifies itself.
        self.announce = announce
        self._tls_ctx = (
            build_tls_context(cert, key, password, ca, verify)
            if self.target.is_tls else None
        )
        self._sock: Optional[socket.socket] = None
        self.received = 0

    def __iter__(self) -> Iterator:
        import time as _time
        backoff = 1.0
        if self.stop_after is not None:
            self._deadline = _time.monotonic() + self.stop_after
        while True:
            if self._expired():
                return
            try:
                self._connect()
                backoff = 1.0
                yield from self._read_loop()
            except (OSError, ssl.SSLError) as exc:
                log.warning("listener connection problem: %s", exc)
            finally:
                self.close()

            if not self.reconnect:
                return
            log.info("reconnecting in %.0fs", backoff)
            _sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def _connect(self) -> None:
        tgt = self.target
        if tgt.is_udp:
            from .send import multicast_socket
            self._sock = (
                multicast_socket(tgt.host, tgt.port) if tgt.is_multicast
                else _udp_bound(tgt.port)
            )
            log.info("listening on %s", tgt)
            return

        raw_sock = socket.create_connection((tgt.host, tgt.port), timeout=self.timeout)
        self._sock = (
            self._tls_ctx.wrap_socket(raw_sock, server_hostname=tgt.host)
            if self._tls_ctx else raw_sock
        )
        self._sock.settimeout(self.timeout)
        log.info("listening on %s", tgt)
        if self.announce:
            self._sock.sendall(self.announce)

    def _expired(self) -> bool:
        import time as _time
        return self._deadline is not None and _time.monotonic() >= self._deadline

    def _read_loop(self) -> Iterator:
        stream = CoTStream()
        # Never block past the deadline, so `stop_after` is honoured even on a
        # server that never says anything.
        if self._deadline is not None:
            import time as _time
            self._sock.settimeout(
                max(0.1, min(self.timeout, self._deadline - _time.monotonic()))
            )
        while True:
            if self._expired():
                return
            try:
                if self.target.is_udp:
                    chunk, _ = self._sock.recvfrom(65535)
                else:
                    chunk = self._sock.recv(8192)
            except socket.timeout:
                continue          # quiet server is fine; keep waiting
            if not chunk:
                log.info("server closed the connection")
                return
            for evt_bytes in stream.feed(chunk):
                self.received += 1
                if self.raw:
                    yield evt_bytes
                else:
                    parsed = parse_cot(evt_bytes)
                    if parsed:
                        yield parsed

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


def _read_varint(buf, offset: int):
    """Decode a protobuf varint. Returns (value, next_offset), or (None, offset)
    if the buffer ends mid-varint."""
    result = shift = 0
    pos = offset
    while pos < len(buf):
        byte = buf[pos]
        result |= (byte & 0x7F) << shift
        pos += 1
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            return None, offset          # absurd length; treat as corrupt
    return None, offset


def _proto_to_xml(payload: bytes):
    """Best-effort protobuf -> CoT XML using takproto, if it's installed.

    takproto's helper has moved around between releases, so try the known
    entry points rather than pinning to one that may not exist.
    """
    try:
        import takproto
    except ImportError:
        return None

    for name in ("parse_proto", "proto2xml"):
        fn = getattr(takproto, name, None)
        if fn is None:
            continue
        try:
            result = fn(payload)
        except Exception:  # noqa: BLE001 — a decoder failure is not fatal here
            continue
        if result is None:
            continue
        if isinstance(result, bytes):
            return result
        if isinstance(result, str):
            return result.encode("utf-8")
        # A TakMessage object — render it if takproto can.
        for render in ("proto2xml", "msg2xml"):
            rfn = getattr(takproto, render, None)
            if rfn is not None and rfn is not fn:
                try:
                    out = rfn(result)
                    if isinstance(out, (bytes, str)):
                        return out if isinstance(out, bytes) else out.encode("utf-8")
                except Exception:  # noqa: BLE001
                    pass
    return None


def _udp_bound(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    return s


def _sleep(seconds: float) -> None:
    import time
    time.sleep(seconds)
