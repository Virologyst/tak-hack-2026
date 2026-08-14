"""Where the server URL and certs come from.

Precedence, highest first: explicit argument > environment variable >
config.ini > default. That order means you can override the server on the
command line without editing a file that six machines are all syncing.

Set `COT_URL` in your shell and every script in this repo follows it.
"""

import logging
import os
from configparser import ConfigParser
from pathlib import Path
from typing import Optional

log = logging.getLogger("taklib.config")

# We stream out over UDP to the server the venue provides, so the default is
# the standard TAK mesh SA group: two laptops on the same wifi see each other
# with zero configuration. Override with $COT_URL on the day.
DEFAULT_URL = "udp://239.2.3.1:6969"
CONFIG_NAMES = ("config.ini", "config.local.ini")

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Optional[str] = None, section: str = "bridge") -> dict:
    """Read config.ini (if present) and overlay environment variables.

    Returns a plain dict — pass it straight to `TAKSender(**cfg)`-style code or
    hand `config` to pytak, which wants a mapping too.
    """
    cfg = ConfigParser()
    candidates = [Path(path)] if path else [REPO_ROOT / n for n in CONFIG_NAMES]
    found = [p for p in candidates if p.is_file()]
    if found:
        cfg.read(found)
        log.debug("loaded config from %s", ", ".join(str(p) for p in found))

    values = dict(cfg[section]) if cfg.has_section(section) else {}

    # Environment wins — this is the knob you turn on event day.
    for key in ("COT_URL", "PYTAK_TLS_CLIENT_CERT", "PYTAK_TLS_CLIENT_KEY",
                "PYTAK_TLS_CLIENT_PASSWORD", "PYTAK_TLS_CLIENT_CAFILE",
                "PYTAK_TLS_DONT_VERIFY", "TAK_CALLSIGN", "TAK_TEAM", "TAK_UID"):
        if os.environ.get(key):
            values[key] = os.environ[key]

    values.setdefault("COT_URL", DEFAULT_URL)
    return values


def resolve_url(override: Optional[str] = None, path: Optional[str] = None) -> str:
    """The server URL to use, honouring --url > COT_URL env > config.ini."""
    if override:
        return override
    return load_config(path).get("COT_URL", DEFAULT_URL)


def sender_kwargs(cfg: Optional[dict] = None) -> dict:
    """Translate config keys into `TAKSender(...)` keyword arguments."""
    cfg = cfg if cfg is not None else load_config()
    dont_verify = str(cfg.get("PYTAK_TLS_DONT_VERIFY", "")).lower() in (
        "1", "true", "yes", "on"
    )
    kwargs = {
        "cert": cfg.get("PYTAK_TLS_CLIENT_CERT"),
        "key": cfg.get("PYTAK_TLS_CLIENT_KEY"),
        "password": cfg.get("PYTAK_TLS_CLIENT_PASSWORD"),
        "ca": cfg.get("PYTAK_TLS_CLIENT_CAFILE"),
        "verify": not dont_verify,
    }
    return {k: v for k, v in kwargs.items() if v is not None}


def identity(cfg: Optional[dict] = None) -> dict:
    """Who this machine is on the map — callsign, team, uid.

    Set TAK_CALLSIGN per laptop so six teammates don't all appear as one
    marker fighting over the same uid.
    """
    cfg = cfg if cfg is not None else load_config()
    callsign = cfg.get("TAK_CALLSIGN") or f"BRIDGE-{os.getenv('COMPUTERNAME', 'DEV')}"
    return {
        "callsign": callsign,
        "team": cfg.get("TAK_TEAM", "Cyan"),
        "uid": cfg.get("TAK_UID") or f"taklib-{callsign.lower()}",
    }
