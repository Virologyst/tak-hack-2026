"""The contract every speech backend implements, plus stdlib WAV helpers.

Audio is passed around as a plain list of floats in [-1.0, 1.0] at a known
sample rate. Not numpy: this module has to be importable with nothing
installed, and the backends that want numpy can convert internally.
"""

from __future__ import annotations

import wave
from typing import Dict, List, Optional, Sequence, Tuple

# 16 kHz mono is what every one of these models wants.
SAMPLE_RATE = 16000


class TranscriberUnavailable(RuntimeError):
    """A backend was asked for but cannot run on this machine."""


class AudioClip:
    """Samples plus their rate. Thin, but it stops rate/sample mix-ups."""

    __slots__ = ("samples", "sample_rate")

    def __init__(self, samples: Sequence[float], sample_rate: int = SAMPLE_RATE):
        self.samples = samples
        self.sample_rate = int(sample_rate)

    @property
    def duration(self) -> float:
        return len(self.samples) / float(self.sample_rate or 1)

    def __len__(self) -> int:
        return len(self.samples)

    def __repr__(self) -> str:
        return "AudioClip(%.2fs @ %dHz)" % (self.duration, self.sample_rate)


class Transcriber:
    """Base class for speech backends.

    Subclasses must set `name` and implement `available()` and `transcribe()`.
    `interpret()` is optional and returns None by default - only a backend that
    can go from audio straight to structured output (currently just phi4)
    overrides it. Callers should try `interpret()` first and fall back to
    `transcribe()` plus a text interpreter, which is what
    `taklib.voice.interpret.understand()` does for you.
    """

    name = "base"
    #: Domain words worth biasing the recogniser toward. Callsigns, agencies,
    #: the vocabulary of the incident. Backends use this where they can.
    keyterms: Sequence[str] = ()

    def __init__(self, keyterms: Optional[Sequence[str]] = None, **_kwargs):
        if keyterms:
            self.keyterms = tuple(keyterms)
        self._loaded = False

    # -- lifecycle ----------------------------------------------------------

    def available(self) -> Tuple[bool, str]:
        """(can this run here, human-readable reason). Must not load models."""
        raise NotImplementedError

    def load(self) -> None:
        """Load models. Idempotent. Backends also self-load on first use."""
        raise NotImplementedError

    def close(self) -> None:
        self._loaded = False

    def __enter__(self) -> "Transcriber":
        self.load()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- the actual work ----------------------------------------------------

    def transcribe(self, samples: Sequence[float],
                   sample_rate: int = SAMPLE_RATE) -> str:
        """Audio in, text out. The one method every backend must have."""
        raise NotImplementedError

    def interpret(self, samples: Sequence[float],
                  sample_rate: int = SAMPLE_RATE) -> Optional[Dict]:
        """Audio straight to a structured dict, skipping the text stage.

        Returns None if this backend can't do it, which is the honest answer
        for every recogniser that is only a recogniser. Do not fake it by
        transcribing and regex-ing in here - that is the caller's fallback and
        it should stay visible.
        """
        return None

    def transcribe_file(self, path) -> str:
        clip = load_wav(path)
        return self.transcribe(clip.samples, clip.sample_rate)

    def __repr__(self) -> str:
        return "<%s loaded=%s>" % (type(self).__name__, self._loaded)


def clean_text(text: str) -> str:
    """Flatten a transcript to one printable ASCII-safe line.

    Recognisers emit newlines, carriage returns and the odd control byte.
    A stray \\r overwrites the line you just printed, so output looks
    truncated mid-word and the run appears broken when it is fine. Windows
    consoles are cp1252 too, so non-encodable characters are dropped rather
    than allowed to raise mid-demo.
    """
    if not text:
        return ""
    flat = "".join(
        (ch if (ch.isprintable() or ch == " ") else " ") for ch in text
    )
    flat = " ".join(flat.split())            # collapse runs of whitespace
    try:
        flat.encode("cp1252")
    except UnicodeEncodeError:
        flat = flat.encode("ascii", "replace").decode("ascii")
    return flat.strip()


# --- WAV in and out, stdlib only --------------------------------------------
#
# `wave` handles the container; we do the PCM conversion by hand rather than
# pull in numpy, because these run on machines where the pip install failed.

def load_wav(path) -> AudioClip:
    """Read a mono 16-bit PCM WAV into floats. Downmixes stereo if it has to."""
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())

    if width != 2:
        raise ValueError(
            "expected 16-bit PCM WAV, got %d-bit. Convert it first: "
            "ffmpeg -i in.wav -ar 16000 -ac 1 -sample_fmt s16 out.wav" % (width * 8)
        )

    import array
    pcm = array.array("h")
    pcm.frombytes(raw)
    import sys
    if sys.byteorder == "big":          # WAV is little-endian
        pcm.byteswap()

    samples: List[float] = [s / 32768.0 for s in pcm]
    if channels > 1:                     # average the channels down to mono
        samples = [
            sum(samples[i:i + channels]) / channels
            for i in range(0, len(samples) - channels + 1, channels)
        ]
    return AudioClip(samples, rate)


def write_wav(path, samples: Sequence[float], sample_rate: int = SAMPLE_RATE) -> None:
    """Write floats out as mono 16-bit PCM. Used to hand audio to whisper-cli."""
    import array
    clipped = array.array(
        "h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples)
    )
    import sys
    if sys.byteorder == "big":
        clipped.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(clipped.tobytes())
