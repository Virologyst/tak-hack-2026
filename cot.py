"""Helpers for building Cursor-on-Target (CoT) events.

A CoT event is just an XML <event> with a <point> (where) and a <detail>
(everything else). Build one, serialize it, hand the bytes to pytak.
"""
import xml.etree.ElementTree as ET
import pytak


def make_cot(
    uid: str,
    lat: float,
    lon: float,
    cot_type: str = "a-f-G-U-C",   # friendly ground unit; see the prep pack for codes
    callsign: str = "PYBRIDGE-01",
    hae: float = 0.0,              # height above ellipsoid (m)
    ce: float = 10.0,             # circular error (m)
    le: float = 10.0,             # linear error (m)
    stale_seconds: int = 120,     # how long before it drops off the map
    remarks: str = "",
    how: str = "m-g",             # m-g = machine / GPS derived
) -> bytes:
    """Return a serialized CoT <event> ready to send to a TAK server."""
    evt = ET.Element("event")
    evt.set("version", "2.0")
    evt.set("uid", uid)
    evt.set("type", cot_type)
    evt.set("how", how)
    evt.set("time", pytak.cot_time())
    evt.set("start", pytak.cot_time())
    evt.set("stale", pytak.cot_time(stale_seconds))

    pt = ET.SubElement(evt, "point")
    pt.set("lat", str(lat))
    pt.set("lon", str(lon))
    pt.set("hae", str(hae))
    pt.set("ce", str(ce))
    pt.set("le", str(le))

    detail = ET.SubElement(evt, "detail")
    ET.SubElement(detail, "contact", attrib={"callsign": callsign})
    ET.SubElement(detail, "__group", attrib={"name": "Cyan", "role": "Team Member"})
    if remarks:
        r = ET.SubElement(detail, "remarks")
        r.text = remarks

    return ET.tostring(evt)
