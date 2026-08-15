"""Every term that goes into building a CoT XML package, and proof each is real.

There is no canonical "TAK dictionary" to copy from. TAK standardises *type
codes* - MIL-STD-2525D / APP-6D, thousands of them - not vocabulary. So the
allowed set has to be defined by what actually constructs the XML, which is
`taklib/cot.py` and `taklib/types.py`.

Two kinds of term end up in a package, and both belong here:

**Structural** - names that appear literally in the XML. The `<event>` and
`<point>` attributes, the twenty-odd `<detail>` children, the `type` codes, the
`how` codes, the ATAK team colours and roles. These are what the document is
made of.

**Semantic** - words the builders key off to decide *which* structure to emit
and what to put in it. "mayday" is not an element, but it is what turns a
`cot.unit()` into a `cot.emergency()`, so it constructs the package just as
surely as `_medevac_` does.

The rule this enforces: **a Tak word must do something.** One the pipeline does
not recognise is silently inert - substituted into the sanitised text, matched
by nothing, and no XML changes. No error, just an empty map. That is the
failure this module exists to prevent, and `verify()` proves every entry still
earns its place, so a regex edit in `interpret.py` or a rename in `cot.py`
breaks a test instead of quietly rotting the vocabulary.

It caught four dead words in our own seed data the day it was written -
`weapons free`, `crowd surge`, `casevac` and `sighting`. The last is the
instructive one: the pattern is `sighted|observ|spotted`, so the noun form
matches nothing while looking perfectly reasonable in a table.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional


class TakWord(NamedTuple):
    word: str
    category: str     # intent|agency|priority|casualty|cot-type|how|element|attribute|team|role
    effect: str       # what it does to the XML, shown in the picker


# --- semantic: words that decide what gets built ----------------------------
# Only forms that genuinely match interpret.py are listed - "sighted" is here,
# "sighting" is not, because only one of them matches.

_INTENT = [
    ("on scene", "arrived"), ("arrived", "arrived"), ("in position", "arrived"),
    ("at location", "arrived"),
    ("responding", "en route"), ("en route", "en route"),
    ("proceeding", "en route"), ("attending", "en route"),
    ("unavailable", "cannot be tasked"), ("committed", "cannot be tasked"),
    ("out of service", "cannot be tasked"),
    ("clear", "available again"), ("available", "available again"),
    ("back in service", "available again"), ("resuming", "available again"),
    ("request", "asking for support"), ("requesting", "asking for support"),
    ("backup", "asking for support"), ("assistance", "asking for support"),
    ("support", "asking for support"), ("need", "asking for support"),
    ("sighted", "something seen"), ("spotted", "something seen"),
    ("observed", "something seen"), ("visual on", "something seen"),
]

_AGENCY = [
    ("police", "Blue"), ("ambulance", "Green"), ("paramedic", "Green"),
    ("fire", "Red"), ("brigade", "Red"), ("ses", "Orange"),
    ("rescue", "Orange"), ("security", "Yellow"), ("transport", "Cyan"),
]

_PRIORITY_EMERGENCY = ["mayday", "emergency", "officer down",
                       "urgent assistance", "cardiac"]
_PRIORITY_URGENT = ["urgent", "priority", "immediate", "asap"]

_CASUALTY = ["patient", "patients", "casualty", "casualties", "injured",
             "victim", "wounded", "unconscious", "cpr"]

# --- structural: names that appear literally in the XML ---------------------
# Derived from the sub() calls in cot.py. verify() checks each still exists
# there, so a rename breaks a test rather than the vocabulary.

_EVENT_ATTRS = [
    ("uid", "<event uid> - the marker's identity. Same uid = it MOVES"),
    ("type", "<event type> - the CoT type code, drives the map symbol"),
    ("time", "<event time> - when it was observed"),
    ("start", "<event start> - validity window opens"),
    ("stale", "<event stale> - validity window closes; marker vanishes after"),
    ("how", "<event how> - where the data came from"),
]

_POINT_ATTRS = [
    ("lat", "<point lat> - WGS84 degrees, negative in the southern hemisphere"),
    ("lon", "<point lon> - WGS84 degrees"),
    ("hae", "<point hae> - height above ellipsoid, metres"),
    ("ce", "<point ce> - circular error, metres; ATAK draws the accuracy ring"),
    ("le", "<point le> - linear (vertical) error, metres"),
]

_ELEMENTS = [
    ("contact", "callsign shown on the map"),
    ("__group", "team colour and role - how an agency is told apart"),
    ("remarks", "free text on the marker"),
    ("status", "battery and similar"),
    ("track", "course and speed - draws a heading vector"),
    ("color", "marker colour, ARGB"),
    ("usericon", "custom icon"),
    ("precisionlocation", "declares the fix really came from GPS"),
    ("link", "relationship to another event"),
    ("link_attr", "route link attributes"),
    ("archive", "ask ATAK to persist it"),
    ("_medevac_", "the CASEVAC 9-line card"),
    ("emergency", "the alert that rings every screen"),
    ("chatgrp", "GeoChat participants"),
    ("__serverdestination", "which server/callsigns a chat is for"),
    ("__video", "attached video stream"),
    ("__routeinfo", "route metadata"),
    ("ConnectionEntry", "video connection details"),
    ("shape", "drawing geometry"),
    ("ellipse", "circle geometry"),
    ("strokeColor", "outline colour of a shape"),
    ("strokeWeight", "outline thickness"),
    ("strokeStyle", "outline style"),
    ("fillColor", "fill colour of a shape"),
    ("labels_on", "show labels on a shape"),
]


#: Reserved word meaning "delete this on sight". Needed for the case the whole
#: feature exists for: when SAS say "fire" they mean shoot, so the word must be
#: REMOVED rather than mapped - leaving it in place lets the agency matcher
#: turn a contact report into a fire-service marker. An empty tak word cannot
#: express that, because empty means "do not rewrite".
IGNORE = "(ignore)"


def _build() -> List[TakWord]:
    out: List[TakWord] = [
        TakWord(IGNORE, "control",
                "delete this word - it means something to this service that "
                "TAK must not act on"),
    ]
    for word, eff in _INTENT:
        out.append(TakWord(word, "intent", "intent: %s" % eff))
    for word, colour in _AGENCY:
        out.append(TakWord(word, "agency", "agency - %s on the map" % colour))
    for word in _PRIORITY_EMERGENCY:
        out.append(TakWord(word, "priority",
                           "EMERGENCY - builds cot.emergency(), alerts everyone"))
    for word in _PRIORITY_URGENT:
        out.append(TakWord(word, "priority", "raises priority to urgent"))
    for word in _CASUALTY:
        out.append(TakWord(word, "casualty",
                           "casualty report - with a count builds cot.casevac()"))
    for word, eff in _EVENT_ATTRS:
        out.append(TakWord(word, "attribute", eff))
    for word, eff in _POINT_ATTRS:
        out.append(TakWord(word, "attribute", eff))
    for word, eff in _ELEMENTS:
        out.append(TakWord(word, "element", "<%s> - %s" % (word, eff)))

    from .. import types as t
    seen = set()
    for name in sorted(dir(t)):
        if not name.isupper():
            continue
        value = getattr(t, name)
        if not isinstance(value, str) or not value or " " in value:
            continue
        if value in seen:
            continue
        seen.add(value)
        if name.startswith("HOW_"):
            out.append(TakWord(value, "how", "how=%s - %s" % (
                value, name[4:].lower().replace("_", " "))))
        elif "-" in value:
            out.append(TakWord(value, "cot-type", "type=%s - %s" % (
                value, t.describe(value))))
    for colour in t.TEAM_COLOURS:
        out.append(TakWord(colour, "team", "__group team colour"))
    for role in t.TEAM_ROLES:
        out.append(TakWord(role, "role", "__group role"))
    return out


CATALOGUE: List[TakWord] = _build()
_BY_WORD: Dict[str, TakWord] = {w.word.lower(): w for w in CATALOGUE}

#: Categories whose members are structural values rather than spoken words -
#: they are checked against the source, not through the matcher.
STRUCTURAL = {"cot-type", "how", "element", "attribute", "team", "role",
              "control"}


def is_valid(word: Optional[str]) -> bool:
    """True if this term participates in building a CoT package.

    Empty is allowed: a term with no tak word still biases the recogniser
    toward hearing the trigger, it just does not rewrite anything.

    Membership of CATALOGUE is the fast path, but it is not the definition.
    A PHRASE can be perfectly good without being listed - "requesting backup"
    is not an entry, yet both of its words match, so it sets intent just fine.
    Rejecting it would be the validator lying about what the pipeline can do.
    So anything not in the catalogue gets the real test: run it through the
    matcher and see whether the interpretation actually changes.
    """
    if not word or not word.strip():
        return True
    text = word.strip().lower()
    if text in _BY_WORD:
        return True
    return _changes_interpretation(text)


def _changes_interpretation(text: str) -> bool:
    """Does this text move intent, agency or priority off their defaults?"""
    from . import interpret as i
    report = i.interpret_text("unit seven %s" % text)
    return (report["intent"] != "other"
            or report["agency"] != "unknown"
            or report["priority"] != "routine")


def get(word: str) -> Optional[TakWord]:
    return _BY_WORD.get((word or "").strip().lower())


def search(prefix: str = "", limit: int = 12) -> List[TakWord]:
    """Prefix matches first, then substring - what a typeahead wants."""
    q = (prefix or "").strip().lower()
    if not q:
        return CATALOGUE[:limit]
    starts = [w for w in CATALOGUE if w.word.lower().startswith(q)]
    rest = [w for w in CATALOGUE
            if q in w.word.lower() and not w.word.lower().startswith(q)]
    return (starts + rest)[:limit]


def suggest(word: str, limit: int = 3) -> List[str]:
    """Nearest catalogue words to a rejected one, so the error is actionable."""
    import difflib
    return difflib.get_close_matches((word or "").strip().lower(),
                                     list(_BY_WORD), n=limit, cutoff=0.55)


def as_dicts() -> List[dict]:
    return [{"word": w.word, "category": w.category, "effect": w.effect}
            for w in CATALOGUE]


def verify() -> List[str]:
    """Prove every entry still does something. Empty list means honest.

    Spoken words are pushed through the real matcher. Structural names are
    checked against the source of `cot.py`, so renaming an element there
    fails a test instead of leaving a word here that builds nothing.
    """
    import inspect
    from . import interpret as i
    from .. import cot as cot_module

    failures: List[str] = []
    source = inspect.getsource(cot_module)
    baseline = i.interpret_text("nothing of interest here")

    for entry in CATALOGUE:
        if entry.category in ("element", "attribute"):
            if '"%s"' % entry.word not in source and \
               "%s=" % entry.word not in source and \
               "%s_=" % entry.word not in source:
                failures.append("%s (%s) no longer appears in cot.py"
                                % (entry.word, entry.category))
            continue
        if entry.category in STRUCTURAL:
            continue
        report = i.interpret_text("unit seven %s" % entry.word)
        if (report["intent"] == baseline["intent"]
                and report["agency"] == baseline["agency"]
                and report["priority"] == baseline["priority"]):
            failures.append("%s (%s) matches nothing in interpret.py"
                            % (entry.word, entry.category))
    return failures


if __name__ == "__main__":               # python -m taklib.voice.takwords
    from collections import Counter
    print("%d Tak words" % len(CATALOGUE))
    for category, n in Counter(w.category for w in CATALOGUE).most_common():
        print("  %-10s %d" % (category, n))
    print()
    bad = verify()
    if bad:
        print("DEAD TERMS - these would build nothing:")
        for line in bad:
            print("  " + line)
        raise SystemExit(1)
    print("verified: every term is real and does something")
