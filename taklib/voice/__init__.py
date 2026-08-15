"""taklib.voice - speech into CoT.

Two engines, chosen by measurement rather than by argument.

**`whisper` (faster-whisper small.en) is the accurate one, and the default.**
**`moonshine` is the fast, tiny one**, and the only one that could run on a Pi.

Measured on 20.6s of speech band-limited to 300-3400 Hz with noise and clipping
to approximate a handset - the condition that matters, since clean audio
flatters everything:

    engine                       WER      speed
    faster-whisper small.en      9.2%      2.2x    <- default
    moonshine MEDIUM_STREAMING  17.4%      1.2x
    faster-whisper base.en      25.2%      3.8x
    faster-whisper tiny.en      27.0%     11.3x
    moonshine TINY_STREAMING    34.2%      6.1x

Whisper had been deleted a day earlier on the reasoning that it pads every clip
to 30 seconds and therefore wastes ten times the work on short radio traffic.
That is true of the original OpenAI implementation and false of faster-whisper
with greedy decoding and timestamps off. Reinstated because the measurement
disagreed with the reasoning; the 34.2% figure is what "accurate enough" felt
like before anyone measured it.

Phi-4-multimodal stays deleted - it hears correctly then loops, and the write-up
is in `docs/PROBLEM.md`.

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

#: Accuracy first. `get_transcriber()` with no argument picks the head of this
#: list that is actually installed, so a machine without faster-whisper still
#: works - more slowly and less accurately, and it says so.
BACKEND_NAMES = ("whisper", "moonshine")

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
    if name == "whisper":
        from .whisper import WhisperTranscriber
        return WhisperTranscriber
    raise ValueError(
        "unknown STT backend %r - expected one of %s"
        % (name, ", ".join(BACKEND_NAMES)))


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
    """Pick a backend: explicit name, then `$TAK_STT`, then most accurate first.

    With no argument this walks BACKEND_NAMES in order, so a machine without
    faster-whisper still works - less accurately, and `available_backends()`
    says why.

    Does not load the model - call `.load()`, or just use it and it loads on
    first need. Raises TranscriberUnavailable with an actionable message rather
    than failing later at the moment someone presses a button.
    """
    import os

    chosen = (name or os.environ.get("TAK_STT") or "").strip().lower()
    if chosen:
        backend = _backend_class(chosen)(**kwargs)
        ok, reason = backend.available()
        if not ok:
            raise TranscriberUnavailable(
                "STT backend %r is not usable here: %s" % (chosen, reason))
        return backend

    problems = []
    for candidate in BACKEND_NAMES:
        backend = _backend_class(candidate)(**kwargs)
        ok, reason = backend.available()
        if ok:
            return backend
        problems.append("  %-10s %s" % (candidate, reason))

    raise TranscriberUnavailable(
        "no speech backend is installed. Tried:\n" + "\n".join(problems)
        + "\n\n  pip install -r requirements.txt\n\n"
        "If the console serves pages but cannot hear, it is almost always the "
        "wrong interpreter - the engines live in the project venv. Start it "
        "with `python console.py`, which picks the right one.")
