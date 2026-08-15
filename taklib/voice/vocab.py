"""Per-service vocabularies: what a team says, and what it means in TAK.

The problem this solves, in Steve's words: *"fire from SAS is different to fire
in the firefighters"*. A trigger word is whatever a particular service actually
says on the radio; the tak word is the canonical term we build the CoT from.
The same trigger can therefore mean different things to different services, and
a global phrase table cannot express that.

So the lookup key is **(service, trigger)**, never trigger alone.

    vocab = Vocabulary.default()
    sanitised, hits = vocab.substitute("ambo seven, we're here", "AMBULANCE")
    # -> "ambulance seven, on scene"

Pure standard library on purpose. This module is imported by `interpret.py`,
which is imported by anything doing voice work, and the repo's guarantee is
that `import taklib` works on a machine with nothing installed. The SQLite that
backs a real vocabulary lives in `web/vocab_store.py`, on the other side of
this boundary: `taklib` never learns that a database exists.

Two rules decide which term wins, and both matter:

- **A service term beats a core term on the same trigger.** Core is the shared
  fallback, the service is the specific. That is the SAS/firefighter case
  exactly, and `Hit.shadows_core` records when it happened so the UI can show
  the operator that a core term was overridden.
- **Longer triggers beat shorter ones.** Without this, "down" inside
  "officer down" matches first and the phrase is destroyed. Ties break on the
  lowest id, so a demo run twice gives the same answer twice.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: The service name reserved for terms that apply to everyone. Case-insensitive
#: everywhere; stored as the sentinel row id=1 on the database side.
CORE = "CORE"

#: A tak word of "(ignore)" deletes the trigger instead of replacing it. See
#: `takwords.IGNORE` - it exists for the SAS "fire" case, where the word must
#: not survive into the text for the agency matcher to find.
IGNORE = "(ignore)"


class Term:
    """One row of a vocabulary table: what they say, and what we call it."""

    __slots__ = ("id", "service", "trigger", "tak_word", "comments")

    def __init__(self, id: int, service: Optional[str], trigger: str,
                 tak_word: str, comments: str = ""):
        self.id = int(id)
        # None and "CORE" both mean core; normalise so callers can use either.
        self.service = None if _is_core(service) else str(service)
        self.trigger = (trigger or "").strip()
        self.tak_word = (tak_word or "").strip()
        self.comments = comments or ""

    @property
    def is_core(self) -> bool:
        return self.service is None

    def as_dict(self) -> dict:
        return {"id": self.id, "service": self.service or CORE,
                "trigger": self.trigger, "tak_word": self.tak_word,
                "comments": self.comments}

    def __repr__(self) -> str:
        return "Term(%d, %s, %r -> %r)" % (
            self.id, self.service or CORE, self.trigger, self.tak_word)


class Hit:
    """Where a trigger matched, and what replaced it.

    The UI renders these as highlights over the raw text, so the operator can
    see *why* the sanitised version says what it says. `shadows_core` is true
    when a service term won over a core term of the same trigger.
    """

    __slots__ = ("start", "end", "trigger", "tak_word", "service", "term_id",
                 "shadows_core")

    def __init__(self, start: int, end: int, trigger: str, tak_word: str,
                 service: Optional[str], term_id: int,
                 shadows_core: bool = False):
        self.start = start
        self.end = end
        self.trigger = trigger
        self.tak_word = tak_word
        self.service = service
        self.term_id = term_id
        self.shadows_core = shadows_core

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "trigger": self.trigger,
                "tak_word": self.tak_word, "service": self.service or CORE,
                "term_id": self.term_id, "shadows_core": self.shadows_core}

    def __repr__(self) -> str:
        return "Hit(%d:%d %r->%r%s)" % (
            self.start, self.end, self.trigger, self.tak_word,
            " shadows-core" if self.shadows_core else "")


def _is_core(service: Optional[str]) -> bool:
    return service is None or str(service).strip().upper() == CORE


def _norm(service: Optional[str]) -> Optional[str]:
    """Canonical service key: None for core, else the trimmed name."""
    return None if _is_core(service) else str(service).strip()


class Vocabulary:
    """An immutable snapshot of every term, indexed for fast substitution.

    Immutable on purpose: the engine reads it on a background thread while the
    UI edits the database on another. Swapping a whole new Vocabulary in is one
    atomic reference assignment; mutating a shared one is a race.
    """

    def __init__(self, terms: Sequence[Term], revision: int = 0):
        self.terms: Tuple[Term, ...] = tuple(terms)
        self.revision = int(revision)
        # service key (lowercased, None for core) -> compiled regex + lookup
        self._compiled: Dict[Optional[str], Tuple[Optional[re.Pattern], dict]] = {}

    # -- construction --------------------------------------------------------

    @classmethod
    def default(cls) -> "Vocabulary":
        """A starter vocabulary built from the literals already in interpret.py.

        Lets the engine run before anyone has typed a single term, and means
        the shipped defaults and the editable table can never disagree about
        what the baseline is - there is only one source.
        """
        from . import interpret as _i

        terms: List[Term] = []
        next_id = 1

        # Agency synonyms: every alternative maps to the canonical agency word.
        for agency, words in _i.AGENCY_WORDS.items():
            for word in words:
                if word == agency:
                    continue                    # identity mapping, no value
                terms.append(Term(next_id, None, word, agency))
                next_id += 1

        # A few high-value status phrases. Deliberately not the full regex set:
        # those are patterns, these are literal things people say.
        spoken = [
            ("we're here", "on scene"), ("were here", "on scene"),
            ("in position", "on scene"), ("arrived", "on scene"),
            ("en route", "responding"), ("enroute", "responding"),
            ("on our way", "responding"), ("attending", "responding"),
            ("tied up", "unavailable"), ("out of service", "unavailable"),
            ("committed", "unavailable"),
            ("back in service", "clear"), ("resuming", "clear"),
            ("all clear", "clear"),
        ]
        for trigger, tak_word in spoken:
            terms.append(Term(next_id, None, trigger, tak_word))
            next_id += 1

        return cls(terms, revision=0)

    # -- queries -------------------------------------------------------------

    def services(self) -> List[str]:
        """Every named service, sorted. Core is not a service and is excluded."""
        return sorted({t.service for t in self.terms if t.service})

    def for_service(self, service: Optional[str]) -> List[Term]:
        """Terms this service would actually use: its own, plus unshadowed core."""
        key = _norm(service)
        own = [t for t in self.terms
               if t.service and key and t.service.lower() == key.lower()]
        shadowed = {t.trigger.lower() for t in own}
        core = [t for t in self.terms
                if t.is_core and t.trigger.lower() not in shadowed]
        return own + core

    def resolve(self, trigger: str, service: Optional[str] = None) -> Optional[Term]:
        """The single term a trigger resolves to for this service, or None."""
        _pattern, lookup = self._index(service)
        return lookup.get((trigger or "").strip().lower(), (None, False))[0]

    def keyterms(self, service: Optional[str] = None,
                 limit: int = 64) -> Tuple[str, ...]:
        """Words to bias the recogniser toward.

        Triggers first, because those are what people actually say into the
        radio - the tak words may never be spoken at all. Tak words are added
        after, since they cost nothing and sometimes are spoken. Deduplicated
        case-insensitively, capped because backends have their own limits.
        """
        out: List[str] = []
        seen = set()
        for source in (0, 1):
            for term in self.for_service(service):
                word = term.trigger if source == 0 else term.tak_word
                key = word.lower()
                if not word or key in seen:
                    continue
                seen.add(key)
                out.append(word)
                if len(out) >= limit:
                    return tuple(out)
        return tuple(out)

    # -- the actual work -----------------------------------------------------

    def substitute(self, text: str,
                   service: Optional[str] = None) -> Tuple[str, List[Hit]]:
        """Rewrite service jargon into tak words. Returns (sanitised, hits).

        Offsets in the returned hits are into the ORIGINAL text, not the
        rewritten one, so the UI can highlight what the operator actually said.
        """
        if not text:
            return "", []
        pattern, lookup = self._index(service)
        if pattern is None:
            return text, []

        hits: List[Hit] = []
        out: List[str] = []
        last = 0

        for m in pattern.finditer(text):
            matched = m.group(0)
            entry = lookup.get(_collapse(matched).lower())
            if entry is None:
                continue                        # shouldn't happen; be safe
            term, shadows = entry
            out.append(text[last:m.start()])
            if term.tak_word == IGNORE:
                # Drop the word entirely, and the space it leaves behind, so
                # "fire at gate four" becomes "at gate four" rather than
                # "  at gate four".
                last = m.end()
                while last < len(text) and text[last] == " ":
                    last += 1
                hits.append(Hit(m.start(), m.end(), matched, "", term.service,
                                term.id, shadows))
                continue
            out.append(_match_case(matched, term.tak_word))
            last = m.end()
            hits.append(Hit(m.start(), m.end(), matched, term.tak_word,
                            term.service, term.id, shadows))

        out.append(text[last:])
        return "".join(out), hits

    # -- indexing ------------------------------------------------------------

    def _index(self, service: Optional[str]):
        """Compile (and cache) the alternation for one service."""
        key = _norm(service)
        cache_key = key.lower() if key else None
        cached = self._compiled.get(cache_key)
        if cached is not None:
            return cached

        own = [t for t in self.terms
               if t.service and key and t.service.lower() == key.lower()]
        own_triggers = {t.trigger.lower() for t in own}
        core = [t for t in self.terms if t.is_core]

        lookup: Dict[str, Tuple[Term, bool]] = {}
        # Core first, then service on top - so a service term overwrites the
        # core entry for the same trigger, and we record that it did.
        for term in core:
            if term.trigger:
                lookup[term.trigger.lower()] = (term, False)
        for term in own:
            if term.trigger:
                shadows = term.trigger.lower() in {c.trigger.lower() for c in core}
                lookup[term.trigger.lower()] = (term, shadows)

        # Longest first: "officer down" must be tried before "down", or the
        # shorter match eats the phrase and the meaning is lost.
        triggers = sorted(lookup, key=lambda s: (-len(s), s))
        usable = [t for t in triggers if lookup[t][0].tak_word]

        pattern = None
        if usable:
            alts = "|".join(_trigger_regex(t) for t in usable)
            pattern = re.compile(r"\b(?:%s)\b" % alts, re.IGNORECASE)

        result = (pattern, lookup)
        self._compiled[cache_key] = result
        return result

    def __len__(self) -> int:
        return len(self.terms)

    def __repr__(self) -> str:
        return "Vocabulary(%d terms, %d services, rev %d)" % (
            len(self.terms), len(self.services()), self.revision)


def _trigger_regex(trigger: str) -> str:
    """Escape a trigger, but let any run of whitespace match any other.

    Speech comes back with unpredictable spacing, and "on  scene" should still
    match a trigger stored as "on scene".
    """
    return r"\s+".join(re.escape(part) for part in trigger.split())


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _match_case(original: str, replacement: str) -> str:
    """Keep the shape of what was said: ALL CAPS in, ALL CAPS out."""
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def from_rows(rows: Iterable[dict], revision: int = 0) -> Vocabulary:
    """Build a Vocabulary from plain dicts - the DB adapter's entry point.

    Accepts `service` or `service_name`, and `trigger` or `phrase`, so a caller
    can hand over sqlite3.Row conversions without reshaping them first.
    """
    terms = []
    for row in rows:
        terms.append(Term(
            id=row.get("id", 0),
            service=row.get("service", row.get("service_name")),
            trigger=row.get("trigger", row.get("phrase", "")),
            tak_word=row.get("tak_word", ""),
            comments=row.get("comments", ""),
        ))
    return Vocabulary(terms, revision=revision)
