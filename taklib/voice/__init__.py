"""taklib.voice - speech into CoT.

**Moonshine is the speech engine.** Not one option among several, not selected
at runtime from whatever happens to be installed: the choice is made. Measured
on a Core Ultra 7, `TINY_STREAMING` transcribes a 4.11 s clip in 1.48 s - 2.8x
realtime - from a ~30 MB download, no GPU, and at the same accuracy as the
library's own much slower default.

The alternatives were tried and are gone rather than parked. whisper.cpp pads
every clip to 30 seconds, so on 2-4 second radio traffic it does roughly ten
times more work than the audio warrants. Phi-4-multimodal was genuinely
appealing - it reasons on the audio itself, skipping the transcribe-then-parse
step that turns "two patients" into "to patients" - but the int4 build needed to
fit a laptop GPU is 5.1 GB and produced looping, hallucinated output. Both
write-ups are kept in `docs/PROBLEM.md`; the code and the weights are not, so
nothing can accidentally select them and nothing ships that we do not use.

Nothing here is imported by `taklib/__init__.py`. That is deliberate: `import
taklib` must keep working on a machine with no third-party packages at all, so
the backend imports its dependencies inside the methods that need them. A
missing install gives a clear message from `available()`, not an ImportError at
start-up.

    from taklib.voice import get_transcriber

    stt = get_transcriber()
    stt.load()
    print(stt.transcribe(audio, 16000))
"""

from .base import (  # noqa: F401
    AudioClip,
    Transcriber,
    TranscriberUnavailable,
    clean_text,
    load_wav,
    write_wav,
)

#: One engine. The tuple survives so callers that iterate still work.
BACKEND_NAMES = ("moonshine",)

__all__ = [
    "AudioClip",
    "Transcriber",
    "TranscriberUnavailable",
    "BACKEND_NAMES",
    "get_transcriber",
    "available_backends",
    "clean_text",
    "load_wav",
    "write_wav",
]


def _backend_class(name: str):
    """Import the backend. Lazy, so a missing package never breaks import."""
    if name == "moonshine":
        from .moonshine import MoonshineTranscriber
        return MoonshineTranscriber
    raise ValueError(
        "unknown STT backend %r - this project uses moonshine only" % name)


def available_backends() -> "list[tuple[str, bool, str]]":
    """(name, usable, reason). Cheap - checks imports, loads no models."""
    out = []
    for name in BACKEND_NAMES:
        try:
            ok, reason = _backend_class(name)().available()
        except Exception as exc:                      # a broken install
            ok, reason = False, "%s: %s" % (type(exc).__name__, exc)
        out.append((name, ok, reason))
    return out


def get_transcriber(name: "str | None" = None, **kwargs) -> Transcriber:
    """The transcriber. `name` and `$TAK_STT` exist only to be explicit.

    Does not load the model - call `.load()`, or just use it and it loads on
    first need. Raises TranscriberUnavailable with an actionable message rather
    than failing later at the moment someone presses a button.
    """
    import os

    chosen = (name or os.environ.get("TAK_STT") or "moonshine").strip().lower()
    backend = _backend_class(chosen)(**kwargs)
    ok, reason = backend.available()
    if not ok:
        raise TranscriberUnavailable(
            "moonshine is not available here: %s\n\n"
            "  pip install -r requirements.txt\n\n"
            "If the console serves pages but cannot hear, it is almost always "
            "the wrong interpreter - moonshine lives in the project venv. "
            "Start it with `python console.py`, which picks the right one."
            % reason)
    return backend
