"""Start the voice console with an interpreter that can actually hear.

    python console.py                    # http://127.0.0.1:5001
    python console.py --host 0.0.0.0     # reachable from a phone on the LAN

Why this exists rather than just running `web/app.py`: the speech backend lives
in the project venv, so starting the server with the system Python gives you a
console that serves every page, accepts typed transmissions, and cannot hear a
word - and only says so when somebody presses Start. That is a bad way to find
out at a venue.

So this re-executes itself under `.venv` when the current interpreter has no
speech backend and the venv does. If neither has one it starts anyway and says
what is missing: the vocabulary and settings pages are still useful, and typed
transmissions still run the whole pipeline.
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "web", "app.py")
VENV = os.path.join(HERE, ".venv", "Scripts", "python.exe")
VENV_POSIX = os.path.join(HERE, ".venv", "bin", "python")


def _has_backend(python: str) -> bool:
    """Ask an interpreter whether it can transcribe. Cheap: no models load."""
    probe = (
        "import sys; sys.path.insert(0, r'%s');"
        "from taklib.voice import available_backends;"
        "print(any(ok for _n, ok, _w in available_backends()))" % HERE
    )
    try:
        out = subprocess.run([python, "-c", probe], capture_output=True,
                             text=True, timeout=60)
        return out.stdout.strip().endswith("True")
    except Exception:
        return False


def main() -> int:
    args = sys.argv[1:]
    venv = VENV if os.path.exists(VENV) else (
        VENV_POSIX if os.path.exists(VENV_POSIX) else None)

    # Already inside the venv, or told not to switch.
    if "--no-venv" in args:
        args.remove("--no-venv")
    elif venv and os.path.abspath(venv) != os.path.abspath(sys.executable):
        if not _has_backend(sys.executable) and _has_backend(venv):
            print("switching to the venv interpreter - it has the speech backend")
            print("  %s" % venv)
            return subprocess.call([venv, APP] + args)

    return subprocess.call([sys.executable, APP] + args)


if __name__ == "__main__":
    raise SystemExit(main())
