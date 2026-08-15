"""Turn a spoken sentence into a structured report, then into CoT.

Three layers, deliberately in this order:

1. **Rules** (`interpret_text`) - regex and keyword matching. Zero dependencies,
   instant, and completely predictable. Handles the phrasing responders
   actually use.
2. **LLM** (`LLMInterpreter`) - optional. Talks to a local Ollama over plain
   `urllib`, so it adds no pip dependency. Use it to rescue sentences the rules
   miss.
3. **Direct** - if the STT backend can go audio->JSON itself (phi4), skip
   straight to that. `understand()` handles the choice.

**Rules run first on purpose.** A demo that dies because a 1.7B model got
creative at 3am is a bad demo. The LLM enriches; it is never load-bearing.

**Nothing here generates XML.** The LLM emits JSON, we validate it, and
`taklib.cot` builds the event. CoT XML has to be exactly right or it vanishes
silently over UDP, and hand-rolled XML from a language model is precisely how
you spend an hour debugging an empty map.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Optional, Sequence

from .. import cot
from .. import types as t

# --- vocabulary --------------------------------------------------------------
#
# Agency -> the ATAK team colour it rides on. Affiliation cannot carry this:
# every civil responder is "friendly", so they would all render as identical
# blue rectangles. Team colour is the axis ATAK draws distinctly.

AGENCY_TEAMS = {
    "police": "Blue",
    "ambulance": "Green",
    "fire": "Red",
    "ses": "Orange",
    "security": "Yellow",
    "transport": "Cyan",
    "unknown": "White",
}

AGENCY_WORDS = {
    "police": ("police", "cop", "constable", "pd", "qps"),
    "ambulance": ("ambulance", "ambo", "paramedic", "medic", "qas", "ems"),
    "fire": ("fire", "fireys", "brigade", "qfes", "pumper"),
    "ses": ("ses", "state emergency", "rescue"),
    "security": ("security", "guard", "steward", "crowd control"),
    "transport": ("transport", "traffic", "translink", "bus", "rail"),
}

# Ordered: first match wins, so put the specific before the general.
INTENT_PATTERNS = (
    ("unavailable",     r"\b(unavailable|committed|tied up|out of service|off ?air)\b"),
    ("clear",           r"\b(clear|clearing|available|back in service|resuming)\b"),
    ("on_scene",        r"\b(on scene|onscene|arrived|at location|we'?re here|in position)\b"),
    ("responding",      r"\b(responding|en route|enroute|on our way|proceeding|attending)\b"),
    ("request_support", r"\b(request(ing)?|need|require|send|backup|assistance|support)\b"),
    # The stems here MUST carry \w*, not a bare \b. `casualt` inside \b...\b
    # only matches the literal string "casualt", which nobody says - so
    # "casualties" and "injured" fell through to intent=other while looking
    # perfectly well handled. Found by takwords.verify(), which is exactly the
    # job it exists to do.
    ("casualty_report", r"\b(patients?|casualt\w*|injur\w*|victims?|wounded|cpr|unconscious)\b"),
    ("sighting",        r"\b(sighted|observ\w*|spotted|visual on|contact with)\b"),
)

PRIORITY_PATTERNS = (
    ("emergency", r"\b(mayday|emergency|urgent assistance|officer down|code (one|1)|cardiac)\b"),
    ("urgent",    r"\b(urgent|priority|immediate|asap|rapid)\b"),
)

# "ambulance seven", "unit 3", "fire 12". Moonshine already turns spoken
# numbers into digits, which is why this is as simple as it is.
UNIT_RE = re.compile(
    r"\b(police|ambulance|ambo|fire|ses|security|unit|car|truck|crew|team)\s*"
    r"(?:unit\s*)?([0-9]{1,3}|[a-z]{1,2}[0-9]{1,3})\b", re.I)

COUNT_RE = re.compile(
    r"\b([0-9]{1,3})\s+(patient|casualt|injur|victim|person|people|pax)", re.I)

# Two passes. "on" and "by" are demoted because "on scene" is an intent, not a
# place - matching it greedily yields locations like "scene at the main stage".
_LOC_TAIL = (r"([a-z0-9][a-z0-9 '\-]{2,40}?)"
             r"(?=[,.]|\s+(?:we|and|requesting|with|for|is|are|to)\b|$)")
LOCATION_RE = re.compile(r"\b(?:at|near|to|outside|inside)\s+(?:the\s+)?"
                         + _LOC_TAIL, re.I)
LOCATION_FALLBACK_RE = re.compile(r"\b(?:on|by)\s+(?:the\s+)?" + _LOC_TAIL, re.I)

#: Words that mean "this is a status, not a place".
_NOT_A_PLACE = re.compile(r"^(scene|air|route|standby|station)\b", re.I)

#: Hand these to the recogniser as keyterms - it biases decoding toward them.
DEFAULT_KEYTERMS = (
    "police", "ambulance", "fire", "SES", "security",
    "on scene", "responding", "unavailable", "casualty", "patients",
    "concourse", "gate", "main stage", "RV point", "casevac", "medevac",
    "crowd surge", "backup",
)


def interpret_text(text: str) -> Dict:
    """Rules-only extraction. Always returns a dict; never raises.

    `confidence` is deliberately crude - it counts how many fields we actually
    resolved. Use it to decide whether to bother the LLM, not as a probability.
    """
    raw = (text or "").strip()
    low = raw.lower()
    out: Dict = {
        "text": raw, "intent": "other", "agency": "unknown", "unit": None,
        "count": None, "location": None, "priority": "routine",
        "source": "rules",
    }
    if not raw:
        return dict(out, confidence=0.0)

    for agency, words in AGENCY_WORDS.items():
        if any(re.search(r"\b%s" % re.escape(w), low) for w in words):
            out["agency"] = agency
            break

    for intent, pattern in INTENT_PATTERNS:
        if re.search(pattern, low):
            out["intent"] = intent
            break

    for priority, pattern in PRIORITY_PATTERNS:
        if re.search(pattern, low):
            out["priority"] = priority
            break

    m = UNIT_RE.search(raw)
    if m:
        out["unit"] = ("%s-%s" % (m.group(1), m.group(2))).upper()

    m = COUNT_RE.search(raw)
    if m:
        out["count"] = int(m.group(1))

    for pattern in (LOCATION_RE, LOCATION_FALLBACK_RE):
        for m in pattern.finditer(raw):
            candidate = m.group(1).strip(" ,.")
            if candidate and not _NOT_A_PLACE.match(candidate):
                out["location"] = candidate
                break
        if out["location"]:
            break

    resolved = sum(1 for k in ("agency", "intent", "unit", "location")
                   if out[k] not in (None, "unknown", "other"))
    out["confidence"] = round(resolved / 4.0, 2)
    return out


class LLMInterpreter:
    """Optional local-LLM pass, over Ollama's HTTP API using only `urllib`.

    Qwen3 1.7B is a good fit - small, fast, decent at structured output::

        ollama pull qwen3:1.7b

    One trap worth knowing: llama.cpp's default reasoning parser was written
    for DeepSeek, not Qwen, and Qwen's inline thinking tags can corrupt output
    when parsed by the wrong thing. Going through Ollama with `format=json`
    sidesteps it.
    """

    def __init__(self, model: str = "qwen3:1.7b",
                 host: str = "http://127.0.0.1:11434", timeout: float = 20.0):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(self.host + "/api/tags",
                                        timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def interpret(self, text: str) -> Optional[Dict]:
        """Returns None on any failure - the caller keeps the rules result."""
        import urllib.request

        prompt = (
            "Extract one JSON object from this emergency radio transmission. "
            "No prose, no markdown.\n"
            'Keys: intent (on_scene|responding|unavailable|clear|'
            "request_support|casualty_report|sighting|other), agency "
            "(police|ambulance|fire|ses|security|transport|unknown), unit "
            "(callsign string or null), count (integer or null), location "
            "(short string or null), priority (routine|urgent|emergency).\n\n"
            "Transmission: %s" % text
        )
        body = json.dumps({
            "model": self.model, "prompt": prompt, "stream": False,
            "format": "json", "options": {"temperature": 0},
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                self.host + "/api/generate", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            data = json.loads(payload.get("response", ""))
        except Exception:
            return None

        if not isinstance(data, dict):
            return None
        data["text"] = text
        data["source"] = "llm:%s" % self.model
        return data


def understand(samples: Sequence[float], sample_rate: int, stt,
               llm: Optional[LLMInterpreter] = None) -> Dict:
    """Audio to a structured report, by whatever route this backend supports.

    Order: the backend's own audio->JSON if it has one (phi4), otherwise
    transcribe and run the rules, optionally topped up by the LLM when the
    rules came back thin.
    """
    direct = stt.interpret(samples, sample_rate)
    if direct:
        direct.setdefault("confidence", 0.9)
        return _normalise(direct)

    text = stt.transcribe(samples, sample_rate)
    report = interpret_text(text)

    if llm is not None and report["confidence"] < 0.75:
        enriched = llm.interpret(text)
        if enriched:
            # Keep anything the rules found that the LLM left blank.
            for key, value in report.items():
                if enriched.get(key) in (None, "", "unknown", "other"):
                    enriched[key] = value
            enriched["confidence"] = max(report["confidence"], 0.8)
            return _normalise(enriched)

    return _normalise(report)


def _normalise(report: Dict) -> Dict:
    """Coerce whatever we got into the shape the CoT builder expects."""
    out = dict(report)
    out.setdefault("text", "")
    out.setdefault("intent", "other")
    out.setdefault("priority", "routine")
    out.setdefault("confidence", 0.0)

    agency = str(out.get("agency") or "unknown").lower()
    out["agency"] = agency if agency in AGENCY_TEAMS else "unknown"
    out["team"] = AGENCY_TEAMS[out["agency"]]

    count = out.get("count")
    if isinstance(count, str) and count.isdigit():
        count = int(count)
    out["count"] = count if isinstance(count, int) else None

    unit = out.get("unit")
    out["unit"] = str(unit).upper() if unit else None
    return out


def to_cot(report: Dict, lat: float, lon: float, *, uid_prefix: str,
           stale: float = 300) -> bytes:
    """Build the CoT event. `taklib.cot` writes the XML, never the model.

    UID is derived from the unit callsign so repeated reports from the same
    unit *move* one marker instead of littering the map - the single most
    common CoT mistake, per CLAUDE.md.
    """
    unit = report.get("unit") or "UNKNOWN"
    uid = "%s-%s" % (uid_prefix, re.sub(r"[^A-Za-z0-9-]", "-", unit).lower())
    callsign = unit

    bits = [report.get("text") or ""]
    if report.get("count"):
        bits.append("count: %d" % report["count"])
    if report.get("location"):
        bits.append("loc: %s" % report["location"])
    bits.append("via voice (%s, conf %.2f)"
                % (report.get("source", "?"), report.get("confidence", 0.0)))
    remarks = " | ".join(b for b in bits if b)

    # Casualties are a CASEVAC, emergencies ring the bell, everything else is a
    # unit that moves. Different symbols so the map reads at a glance.
    if report["intent"] == "casualty_report" and report.get("count"):
        return cot.casevac(uid, lat, lon, callsign=callsign,
                           patients_urgent=report["count"], remarks=remarks,
                           stale=stale)
    if report["priority"] == "emergency":
        # emergency() takes no remarks= - it rides in extra as a <remarks> child.
        return cot.emergency(uid, lat, lon, callsign=callsign, stale=stale,
                             extra={"remarks": remarks})

    return cot.unit(uid, lat, lon, callsign=callsign, team=report["team"],
                    role="Team Member", cot_type=t.FRIENDLY_UNIT,
                    remarks=remarks, stale=stale,
                    extra={"voicereport": {
                        "intent": report["intent"],
                        "agency": report["agency"],
                        "priority": report["priority"],
                        "confidence": "%.2f" % report.get("confidence", 0.0),
                        "source": str(report.get("source", "")),
                    }})
