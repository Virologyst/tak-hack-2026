"""taklib.voice - speech into CoT, with swappable recognisers.

Nothing here is imported by `taklib/__init__.py`. That is deliberate: `import
taklib` must keep working on a machine with no third-party packages at all, so
every backend imports its dependencies *inside* the methods that need them. If
moonshine isn't installed you get a clear message from `available()`, not an
ImportError at start-up.

Three backends, at genuinely different points on the speed/accuracy curve:

| name        | needs                    | speed      | notes                       |
|-------------|--------------------------|------------|-----------------------------|
| `moonshine` | `pip install moonshine-voice` | fastest | short utterances, Pi-viable |
| `whisper`   | whisper.cpp / faster-whisper  | medium  | the fallback everyone knows |
| `phi4`      | transformers + torch          | slowest | audio -> JSON in one pass   |

Pick one at runtime::

    from taklib.voice import get_transcriber

    stt = get_transcriber()            # or get_transcriber("whisper")
    stt.load()
    print(stt.transcribe(audio, 16000))

`get_transcriber()` with no argument reads `$TAK_STT`, and failing that picks
the first backend that reports itself available. So swapping recogniser at 2am
is an environment variable, not a code change::

    set TAK_STT=whisper        # Windows cmd
    $env:TAK_STT="whisper"     # PowerShell

Why `phi4` is worth having despite being the slowest: it is the only backend
that hears the audio and reasons about it in one model. A two-stage pipeline
commits to a word before anything knows what the sentence means, which is how
"two patients" becomes "to patients". Phi-4 holds the acoustics and the meaning
at the same time, so it does not make that class of mistake.
"""

from .base import (  # noqa: F401
    AudioClip,
    Transcriber,
    TranscriberUnavailable,
    load_wav,
    write_wav,
)

BACKEND_NAMES = ("moonshine", "whisper", "phi4")

__all__ = [
    "AudioClip",
    "Transcriber",
    "TranscriberUnavailable",
    "BACKEND_NAMES",
    "get_transcriber",
    "available_backends",
    "load_wav",
    "write_wav",
]


def _backend_class(name: str):
    """Import one backend. Kept lazy so a missing package never breaks import."""
    if name == "moonshine":
        from .moonshine import MoonshineTranscriber
        return MoonshineTranscriber
    if name == "whisper":
        from .whispercpp import WhisperTranscriber
        return WhisperTranscriber
    if name == "phi4":
        from .phi4 import Phi4Transcriber
        return Phi4Transcriber
    raise ValueError(
        "unknown STT backend %r - expected one of %s"
        % (name, ", ".join(BACKEND_NAMES))
    )


def available_backends() -> "list[tuple[str, bool, str]]":
    """Every backend and whether it could run here: (name, ok, reason).

    Cheap - it only checks for importable packages and binaries on PATH, it
    does not load any models. Safe to call on start-up to print a status line.
    """
    out = []
    for name in BACKEND_NAMES:
        try:
            ok, reason = _backend_class(name)().available()
        except Exception as exc:                      # a broken install
            ok, reason = False, "%s: %s" % (type(exc).__name__, exc)
        out.append((name, ok, reason))
    return out


def get_transcriber(name: "str | None" = None, **kwargs) -> Transcriber:
    """Pick a backend: explicit argument, then `$TAK_STT`, then whatever works.

    Does not load the model - call `.load()` (or just use it, backends load on
    first use). Raises TranscriberUnavailable if the named backend can't run,
    so failures are loud and specific rather than a mystery at demo time.
    """
    import os

    chosen = name or os.environ.get("TAK_STT") or ""
    chosen = chosen.strip().lower()

    if chosen:
        backend = _backend_class(chosen)(**kwargs)
        ok, reason = backend.available()
        if not ok:
            raise TranscriberUnavailable(
                "STT backend %r is not usable here: %s" % (chosen, reason)
            )
        return backend

    problems = []
    for candidate in BACKEND_NAMES:
        try:
            backend = _backend_class(candidate)(**kwargs)
            ok, reason = backend.available()
        except Exception as exc:
            ok, reason = False, "%s: %s" % (type(exc).__name__, exc)
        if ok:
            return backend
        problems.append("  %-10s %s" % (candidate, reason))

    raise TranscriberUnavailable(
        "no speech backend is installed. Tried:\n" + "\n".join(problems)
        + "\n\nInstall one:\n"
        "  pip install moonshine-voice        (fastest, recommended)\n"
        "  pip install faster-whisper         (the familiar fallback)\n"
    )
