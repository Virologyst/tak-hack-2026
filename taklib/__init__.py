"""taklib — a small, dependency-light toolkit for talking Cursor-on-Target (CoT).

Designed for a weekend hackathon: everything you need to get data onto a TAK
map, and to read what everyone else is putting there.

Nothing in `cot`, `send`, `listen`, `server` or `geo` requires a third-party
package — they are pure standard library, so they keep working even if the
venue wifi eats your `pip install`. `pytak` / `takproto` are used only if
present, and only for the paths that genuinely benefit.

Typical use::

    from taklib import cot, TAKSender

    with TAKSender("tcp://10.0.0.42:8087") as tak:
        tak.send(cot.unit("alpha-01", -27.4705, 153.0260, callsign="ALPHA"))

See CLAUDE.md and docs/ for the wider picture.
"""

from . import cot, geo, types  # noqa: F401
from .config import load_config, resolve_url  # noqa: F401
from .listen import TAKListener, parse_cot  # noqa: F401
from .send import AsyncTAKSender, TAKSender  # noqa: F401

__all__ = [
    "cot",
    "geo",
    "types",
    "TAKSender",
    "AsyncTAKSender",
    "TAKListener",
    "parse_cot",
    "load_config",
    "resolve_url",
]

__version__ = "0.1.0"
