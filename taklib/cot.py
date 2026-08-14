"""Build Cursor-on-Target events.

Every builder here returns **bytes** — a serialized `<event>` ready to hand to
a sender or `put_queue()`. That is deliberate: at 2am you want
`tak.send(cot.unit(...))` to just work, with no "did this return an Element or
bytes?" step in between.

If you need to hand-roll something exotic, use `event()` (returns an
ElementTree Element), mutate it, then `to_bytes()`.

Every builder also takes `extra=` for detail children the helper does not cover
— pass an XML string, a dict, an Element, or a list of any of those::

    cot.unit("alpha", lat, lon, extra='<__video url="rtsp://..."/>')
    cot.unit("alpha", lat, lon, extra={"status": {"battery": "87"}})

Nothing in this module imports a third-party package.
"""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple, Union

from . import types as t

ISO_8601_UTC = "%Y-%m-%dT%H:%M:%S.%fZ"

LatLon = Tuple[float, float]
Extra = Union[str, Mapping[str, Any], ET.Element, Sequence[Any], None]


# --------------------------------------------------------------------------
# time
# --------------------------------------------------------------------------

def cot_time(offset_seconds: float = 0) -> str:
    """Current UTC as a CoT timestamp, optionally offset into the future.

    `cot_time()` for now, `cot_time(120)` for the stale time two minutes out.
    Matches pytak's format, so the two are interchangeable.
    """
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime(
        ISO_8601_UTC
    )


def parse_cot_time(value: str) -> Optional[datetime]:
    """Parse a CoT timestamp back to an aware datetime; None if unparseable."""
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------

def to_bytes(element: ET.Element) -> bytes:
    """Serialize an Element to the bytes a TAK server expects."""
    return ET.tostring(element, encoding="utf-8", xml_declaration=False)


def _str(value: Any) -> str:
    """Attributes must be strings; bools must be lowercase for ATAK."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def sub(parent: ET.Element, tag: str, /, _text: Optional[str] = None, **attrs) -> ET.Element:
    """Add a child element with attributes.

    `parent`/`tag` are positional-only and the element text is `_text`, so that
    every ordinary word — including CoT's own `parent`, `tag`, `type` and
    `text` attributes — stays free for use as an attribute name.

    Trailing underscores in kwargs are stripped (`type_="a-f-G"`), and dashed
    attribute names go through `**{"some-attr": value}`.
    """
    el = ET.SubElement(parent, tag)
    for k, v in attrs.items():
        if v is None:
            continue
        el.set(k.rstrip("_"), _str(v))
    if _text is not None:
        el.text = _text
    return el


def apply_extra(detail: ET.Element, extra: Extra) -> None:
    """Merge user-supplied detail children into a `<detail>` element."""
    if extra is None:
        return
    if isinstance(extra, ET.Element):
        detail.append(extra)
    elif isinstance(extra, str):
        # Wrap so multiple sibling fragments parse as one document.
        for child in ET.fromstring(f"<x>{extra}</x>"):
            detail.append(child)
    elif isinstance(extra, Mapping):
        for tag, attrs in extra.items():
            if isinstance(attrs, Mapping):
                sub(detail, tag, **attrs)
            else:
                sub(detail, tag, _text=_str(attrs))
    elif isinstance(extra, (list, tuple, set)):
        for item in extra:
            apply_extra(detail, item)
    else:
        raise TypeError(f"don't know how to add {type(extra)!r} to <detail>")


def event(
    uid: str,
    cot_type: str,
    lat: float,
    lon: float,
    *,
    hae: float = 0.0,
    ce: float = 9999999.0,
    le: float = 9999999.0,
    how: str = t.HOW_GPS,
    stale: float = 120,
    start_offset: float = 0,
    access: Optional[str] = None,
    qos: Optional[str] = None,
    opex: Optional[str] = None,
) -> ET.Element:
    """The low-level builder — an `<event>` with `<point>` and empty `<detail>`.

    `ce`/`le` default to 9999999 which is CoT for "unknown accuracy"; pass real
    metres if your source knows them, because ATAK draws the error ring from it.
    """
    evt = ET.Element("event")
    evt.set("version", "2.0")
    evt.set("uid", uid)
    evt.set("type", cot_type)
    evt.set("how", how)
    evt.set("time", cot_time())
    evt.set("start", cot_time(start_offset))
    evt.set("stale", cot_time(stale))
    if access:
        evt.set("access", access)
    if qos:
        evt.set("qos", qos)
    if opex:
        evt.set("opex", opex)

    sub(evt, "point", lat=lat, lon=lon, hae=hae, ce=ce, le=le)
    ET.SubElement(evt, "detail")
    return evt


def detail_of(evt: ET.Element) -> ET.Element:
    """Get (or create) the `<detail>` child of an event."""
    d = evt.find("detail")
    return d if d is not None else ET.SubElement(evt, "detail")


# --------------------------------------------------------------------------
# the builders you will actually call
# --------------------------------------------------------------------------

def unit(
    uid: str,
    lat: float,
    lon: float,
    *,
    callsign: Optional[str] = None,
    cot_type: str = t.FRIENDLY_UNIT,
    team: str = "Cyan",
    role: str = "Team Member",
    hae: float = 0.0,
    ce: float = 9999999.0,
    le: float = 9999999.0,
    stale: float = 120,
    how: str = t.HOW_GPS,
    remarks: str = "",
    course: Optional[float] = None,
    speed: Optional[float] = None,
    battery: Optional[float] = None,
    colour: Optional[int] = None,
    icon: Optional[str] = None,
    video_url: Optional[str] = None,
    extra: Extra = None,
) -> bytes:
    """A thing on the map: person, vehicle, sensor, detection, track.

    Reuse the same `uid` on every update and the marker *moves* instead of
    multiplying. That is the single most important rule in CoT.

    `course`/`speed` (degrees true, m/s) make ATAK draw a heading vector.
    """
    evt = event(uid, cot_type, lat, lon, hae=hae, ce=ce, le=le, how=how, stale=stale)
    d = detail_of(evt)

    sub(d, "contact", callsign=callsign or uid)
    sub(d, "__group", name=team, role=role)
    if battery is not None:
        sub(d, "status", battery=round(float(battery)))
    if course is not None or speed is not None:
        sub(d, "track", course=course if course is not None else 0.0,
            speed=speed if speed is not None else 0.0)
    if colour is not None:
        sub(d, "color", argb=colour)
    if icon:
        sub(d, "usericon", iconsetpath=icon)
    if video_url:
        _video(d, video_url, callsign or uid)
    if remarks:
        sub(d, "remarks", _text=remarks)
    # Only claim GPS precision when the fix actually came from GPS.
    if ce < 9999999 and how == t.HOW_GPS:
        sub(d, "precisionlocation", altsrc="GPS", geopointsrc="GPS")

    apply_extra(d, extra)
    return to_bytes(evt)


def marker(
    uid: str,
    lat: float,
    lon: float,
    *,
    label: Optional[str] = None,
    cot_type: str = t.WAYPOINT,
    remarks: str = "",
    colour: Optional[int] = None,
    icon: Optional[str] = None,
    stale: float = 3600,
    how: str = t.HOW_HUMAN_GIGO,
    hae: float = 0.0,
    extra: Extra = None,
) -> bytes:
    """A pin: waypoint, point of interest, hazard, objective.

    Longer default stale than `unit()` — markers are meant to sit there.
    """
    evt = event(uid, cot_type, lat, lon, hae=hae, how=how, stale=stale)
    d = detail_of(evt)
    sub(d, "contact", callsign=label or uid)
    if colour is not None:
        sub(d, "color", argb=colour)
    sub(d, "archive")
    if icon:
        sub(d, "usericon", iconsetpath=icon)
    if remarks:
        sub(d, "remarks", _text=remarks)
    apply_extra(d, extra)
    return to_bytes(evt)


def detection(
    uid: str,
    lat: float,
    lon: float,
    *,
    label: str,
    confidence: Optional[float] = None,
    cot_type: str = t.UNKNOWN_GROUND,
    source: str = "",
    image_url: Optional[str] = None,
    stale: float = 120,
    ce: float = 50.0,
    extra: Extra = None,
    **kwargs,
) -> bytes:
    """A machine-generated contact — vision model, classifier, anomaly detector.

    Confidence goes in the remarks (where an operator reads it) *and* in a
    custom `<detection>` element (where your own dashboard can parse it).
    """
    note = label
    if confidence is not None:
        note = f"{label} ({confidence:.0%} confidence)"
    if source:
        note = f"{note} — {source}"

    det = {"detection": {
        "label": label,
        "confidence": f"{confidence:.4f}" if confidence is not None else "",
        "source": source,
    }}
    extras = [det]
    if image_url:
        extras.append({"__imageurl": {"url": image_url}})
    if extra is not None:
        extras.append(extra)

    return unit(
        uid, lat, lon,
        callsign=label,
        cot_type=cot_type,
        how=t.HOW_MACHINE_ESTIMATED,
        remarks=note,
        ce=ce,
        stale=stale,
        extra=extras,
        **kwargs,
    )


def geochat(
    message: str,
    *,
    sender_uid: str,
    sender_callsign: str,
    lat: float = 0.0,
    lon: float = 0.0,
    chatroom: str = "All Chat Rooms",
    to_uid: Optional[str] = None,
    stale: float = 86400,
    message_id: Optional[str] = None,
    extra: Extra = None,
) -> bytes:
    """A GeoChat message — the way to talk to operators from code.

    Broadcast to everyone::

        cot.geochat("Bridge is up", sender_uid="bot-1", sender_callsign="BOT")

    Reply privately to whoever messaged you — pass their uid as `to_uid` and
    their callsign as `chatroom`::

        cot.geochat(reply, sender_uid="bot-1", sender_callsign="BOT",
                    to_uid=msg["sender_uid"], chatroom=msg["sender_callsign"])
    """
    mid = message_id or str(uuid.uuid4())
    dest = to_uid or chatroom
    uid = f"GeoChat.{sender_uid}.{dest}.{mid}"

    evt = event(uid, t.GEOCHAT, lat, lon, how=t.HOW_HUMAN_GIGO, stale=stale)
    d = detail_of(evt)

    chat = sub(
        d, "__chat",
        parent="RootContactGroup",
        groupOwner="false",
        messageId=mid,
        chatroom=chatroom,
        id=dest,
        senderCallsign=sender_callsign,
    )
    sub(chat, "chatgrp", uid0=sender_uid, uid1=dest, id=dest)

    sub(d, "link", uid=sender_uid, type=t.FRIENDLY_UNIT, relation="p-p")
    sub(d, "remarks", _text=message,
        source=f"BAO.F.TAKBRIDGE.{sender_uid}", to=dest, time=cot_time())
    sub(d, "__serverdestination", destinations="")

    apply_extra(d, extra)
    return to_bytes(evt)


def route(
    uid: str,
    points: Sequence[LatLon],
    *,
    name: str = "Route",
    colour: int = -1,
    stroke: int = 3,
    method: str = "Driving",
    stale: float = 86400,
    remarks: str = "",
    extra: Extra = None,
) -> bytes:
    """An ordered path drawn on everyone's map. `points` is [(lat, lon), ...]."""
    if len(points) < 2:
        raise ValueError("a route needs at least two points")

    evt = event(uid, t.ROUTE, points[0][0], points[0][1],
                how=t.HOW_HUMAN_GIGO, stale=stale)
    d = detail_of(evt)

    sub(d, "contact", callsign=name)
    sub(d, "__routeinfo")
    sub(d, "link_attr",
        planningmethod="Infil", color=colour, method=method, prefix="CP",
        type="On Foot", stroke=stroke, direction="Infil", routetype="Primary",
        order="Ascending Check Points")
    for lat, lon in points:
        sub(d, "link", point=f"{lat},{lon}")
    sub(d, "strokeColor", value=colour)
    sub(d, "strokeWeight", value=stroke)
    sub(d, "strokeStyle", value="solid")
    sub(d, "labels_on", value="false")
    sub(d, "archive")
    if remarks:
        sub(d, "remarks", _text=remarks)

    apply_extra(d, extra)
    return to_bytes(evt)


def polygon(
    uid: str,
    points: Sequence[LatLon],
    *,
    name: str = "Area",
    stroke_colour: int = -65536,   # opaque red (ARGB as a signed int)
    fill_colour: int = 0x33FF0000,
    stroke: int = 3,
    closed: bool = True,
    stale: float = 86400,
    remarks: str = "",
    extra: Extra = None,
) -> bytes:
    """An area: geofence, AO, search box, exclusion zone, coverage footprint.

    Colours are ARGB ints. ATAK reads them signed, so -65536 is solid red;
    `taklib.cot.argb()` will build one from parts for you.
    """
    if len(points) < 3 and closed:
        raise ValueError("a closed polygon needs at least three points")

    lat0 = sum(p[0] for p in points) / len(points)
    lon0 = sum(p[1] for p in points) / len(points)

    evt = event(uid, t.SHAPE_POLYGON, lat0, lon0,
                how=t.HOW_HUMAN_GIGO, stale=stale)
    d = detail_of(evt)

    sub(d, "contact", callsign=name)
    for lat, lon in points:
        sub(d, "link", point=f"{lat},{lon},0")
    if closed:
        sub(d, "link", point=f"{points[0][0]},{points[0][1]},0")

    sub(d, "strokeColor", value=stroke_colour)
    sub(d, "strokeWeight", value=stroke)
    sub(d, "strokeStyle", value="solid")
    if closed:
        sub(d, "fillColor", value=_signed32(fill_colour))
    sub(d, "labels_on", value="false")
    sub(d, "archive")
    if remarks:
        sub(d, "remarks", _text=remarks)

    apply_extra(d, extra)
    return to_bytes(evt)


def circle(
    uid: str,
    lat: float,
    lon: float,
    radius_m: float,
    *,
    name: str = "Circle",
    stroke_colour: int = -65536,
    fill_colour: int = 0x33FF0000,
    stroke: int = 3,
    stale: float = 86400,
    remarks: str = "",
    extra: Extra = None,
) -> bytes:
    """A range ring / radius of interest around a point."""
    evt = event(uid, t.SHAPE_CIRCLE, lat, lon, how=t.HOW_HUMAN_GIGO, stale=stale)
    d = detail_of(evt)

    sub(d, "contact", callsign=name)
    shape = sub(d, "shape")
    sub(shape, "ellipse", major=radius_m, minor=radius_m, angle=0)
    sub(d, "strokeColor", value=stroke_colour)
    sub(d, "strokeWeight", value=stroke)
    sub(d, "strokeStyle", value="solid")
    sub(d, "fillColor", value=_signed32(fill_colour))
    sub(d, "archive")
    if remarks:
        sub(d, "remarks", _text=remarks)

    apply_extra(d, extra)
    return to_bytes(evt)


def casevac(
    uid: str,
    lat: float,
    lon: float,
    *,
    callsign: str = "CASEVAC",
    patients_urgent: int = 0,
    patients_priority: int = 0,
    patients_routine: int = 0,
    freq: str = "",
    security: int = 0,          # 0 none, 1 possible, 2 probable, 3 armed escort
    hlz_marking: int = 0,       # 0 none, 1 panels, 2 pyro, 3 smoke, 4 lights
    equipment: str = "None",
    terrain_slope: bool = False,
    remarks: str = "",
    stale: float = 86400,
    extra: Extra = None,
) -> bytes:
    """A 9-line medevac request. Renders as a CASEVAC card inside ATAK."""
    evt = event(uid, t.CASEVAC, lat, lon, how=t.HOW_HUMAN_GIGO, stale=stale)
    d = detail_of(evt)

    sub(d, "contact", callsign=callsign)
    sub(d, "_medevac_",
        title=callsign,
        casevac="true",
        freq=freq,
        urgent=patients_urgent,
        priority=patients_priority,
        routine=patients_routine,
        security=security,
        hlz_marking=hlz_marking,
        equipment_detail=equipment,
        terrain_slope=terrain_slope,
        zone_prot_selection=0)
    sub(d, "archive")
    if remarks:
        sub(d, "remarks", _text=remarks)

    apply_extra(d, extra)
    return to_bytes(evt)


def emergency(
    uid: str,
    lat: float,
    lon: float,
    *,
    callsign: str = "ALERT",
    emergency_type: str = "911 Alert",
    cancel: bool = False,
    stale: float = 3600,
    extra: Extra = None,
) -> bytes:
    """Ring the bell — a 911 / troops-in-contact alert on everyone's screen.

    Send with `cancel=True` and the same uid to clear it.
    """
    cot_type = t.EMERGENCY_CANCEL if cancel else t.EMERGENCY
    evt = event(uid, cot_type, lat, lon, how=t.HOW_HUMAN_GIGO, stale=stale)
    d = detail_of(evt)
    sub(d, "contact", callsign=callsign)
    # ATAK reads the alert label from the element text, the kind from @type.
    sub(d, "emergency", _text=callsign, type=emergency_type,
        cancel="true" if cancel else None)
    sub(d, "link", uid=uid, type=t.FRIENDLY_UNIT, relation="p-p")
    apply_extra(d, extra)
    return to_bytes(evt)


def _video(detail: ET.Element, url: str, name: str) -> ET.Element:
    """Attach a video feed an operator can tap into from the marker."""
    v = sub(detail, "__video", url=url, uid=f"video-{name}")
    sub(v, "ConnectionEntry", networkTimeout="12000", uid=f"video-{name}",
        path="", protocol=url.split(":", 1)[0], bufferTime="-1",
        address=url, port="-1", roverPort="-1", rtspReliable="0",
        ignoreEmbeddedKLV="false", alias=name)
    return v


def video(uid: str, lat: float, lon: float, url: str, *, callsign: str = "FEED",
          cot_type: str = t.SENSOR, **kwargs) -> bytes:
    """A marker with a tappable video stream attached (RTSP/RTMP/HLS URL)."""
    return unit(uid, lat, lon, callsign=callsign, cot_type=cot_type,
                video_url=url, **kwargs)


# --------------------------------------------------------------------------
# colours
# --------------------------------------------------------------------------

def argb(alpha: int, red: int, green: int, blue: int) -> int:
    """Build the signed 32-bit ARGB int ATAK expects for colour values."""
    value = ((alpha & 0xFF) << 24) | ((red & 0xFF) << 16) | ((green & 0xFF) << 8) | (blue & 0xFF)
    return _signed32(value)


def _signed32(value: int) -> int:
    """Wrap an unsigned 32-bit colour into the signed int ATAK parses."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


# Ready-made, already signed.
RED = argb(255, 255, 0, 0)
GREEN = argb(255, 0, 255, 0)
BLUE = argb(255, 0, 0, 255)
YELLOW = argb(255, 255, 255, 0)
ORANGE = argb(255, 255, 140, 0)
WHITE = argb(255, 255, 255, 255)
MAGENTA = argb(255, 255, 0, 255)
CYAN = argb(255, 0, 255, 255)


# --------------------------------------------------------------------------
# backwards compatibility with the original starter script
# --------------------------------------------------------------------------

def make_cot(uid: str, lat: float, lon: float, cot_type: str = t.FRIENDLY_UNIT,
             callsign: str = "PYBRIDGE-01", hae: float = 0.0, ce: float = 10.0,
             le: float = 10.0, stale_seconds: int = 120, remarks: str = "",
             how: str = t.HOW_GPS) -> bytes:
    """The original starter signature, kept so old snippets keep running."""
    return unit(uid, lat, lon, callsign=callsign, cot_type=cot_type, hae=hae,
                ce=ce, le=le, stale=stale_seconds, remarks=remarks, how=how)
