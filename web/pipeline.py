"""Text in, one console event out. No threads, no sockets, no audio.

Everything the three panes show comes from `process()`, which is deliberately
pure: hand it a string and it hands back a dict. That makes the interesting
half of the system testable without a microphone, a network, or a model - the
selftest runs it over canned sentences.

The XML is built here, server-side, rather than in the browser. Two reasons.
The right-hand pane has to show the bytes that actually went on the wire or it
is decorative; and reimplementing longest-match substitution in JavaScript
would give two implementations that drift, with the drift surfacing in a demo.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, Optional
from xml.dom import minidom

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from taklib.voice import interpret as _i  # noqa: E402
from taklib.voice.vocab import Vocabulary  # noqa: E402

#: Where a report lands when nothing better is known. Brisbane; the southern
#: hemisphere is negative, and dropping the minus puts you in the sea off Japan.
DEFAULT_LAT, DEFAULT_LON = -27.4705, 153.0260


def process(raw_text: str, *, vocab: Optional[Vocabulary] = None,
            service: Optional[str] = None, server: Optional[Dict] = None,
            seq: int = 0, uid_prefix: str = "voice",
            clip: Optional[Dict] = None) -> Dict:
    """One transmission, fully worked through. Never raises.

    Returns the event the browser renders and the engine sends, including the
    exact CoT bytes as `cot` - or `cot: None` with `cot_reason` set, when the
    transmission was heard but is not a command.
    """
    server = server or {}
    text = (raw_text or "").strip()

    report = _i.interpret_text(text, vocab=vocab, service=service)
    report = _i._normalise(report)
    hits = report.get("hits", [])

    ok, reason = _i.constructable(report, hits)

    lat = _coerce(server.get("lat"), DEFAULT_LAT)
    lon = _coerce(server.get("lon"), DEFAULT_LON)
    stale = _coerce(server.get("stale"), 300.0)

    cot_xml = None
    cot_pretty = None
    if ok:
        try:
            raw_cot = _i.to_cot(report, lat, lon,
                                uid_prefix=server.get("uid_prefix") or uid_prefix,
                                stale=stale)
            cot_xml = raw_cot.decode("utf-8", "replace")
            cot_pretty = _pretty(cot_xml)
        except Exception as exc:
            # A builder blowing up must not take the engine with it. Show the
            # failure in the pane rather than dropping the transmission.
            ok = False
            reason = "could not build CoT: %s" % exc

    return {
        "id": "u-%04d" % seq,
        "seq": seq,
        "service": report.get("service"),
        "raw": text,
        "sanitised": report.get("sanitised", text),
        "hits": hits,
        "report": {k: report[k] for k in
                   ("intent", "agency", "unit", "count", "location",
                    "priority", "confidence", "team", "source")
                   if k in report},
        "cot": cot_xml,
        "cot_pretty": cot_pretty,
        "cot_reason": None if ok else reason,
        "audio": clip or {},
    }


def _coerce(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _pretty(xml: str) -> str:
    """Indented XML for the pane. Display only - never what gets sent.

    CoT goes on the wire as one line; pretty-printing it would add whitespace
    inside elements and change the bytes. So the pane shows this and the engine
    sends `cot`.
    """
    try:
        parsed = minidom.parseString(xml)
        out = parsed.toprettyxml(indent="  ")
        lines = [ln for ln in out.splitlines()
                 if ln.strip() and not ln.startswith("<?xml")]
        return "\n".join(lines)
    except Exception:
        return xml


if __name__ == "__main__":               # python web/pipeline.py
    from taklib.voice.vocab import IGNORE, Term
    v = Vocabulary([
        Term(1, "AMBULANCE", "ambo", "ambulance"),
        Term(2, "SAS", "fire", IGNORE),
        Term(3, None, "we're here", "on scene"),
    ])
    samples = [
        ("ambo 7, we're here, 2 patients", "AMBULANCE"),
        ("fire at gate four", "SAS"),
        ("yeah nah hang on", "AMBULANCE"),
    ]
    for n, (text, svc) in enumerate(samples, 1):
        ev = process(text, vocab=v, service=svc, seq=n)
        print("%-32r -> %r" % (text, ev["sanitised"]))
        print("   %s" % (ev["cot_reason"] or "CoT %d bytes" % len(ev["cot"])))
