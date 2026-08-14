"""Moonshine backend - the fast one.

Verified working against moonshine-voice 0.1.2. Notes from actually running it,
so nobody rediscovers these at 3am:

- `get_model_for_language("en")` returns a `(path, ModelArch)` **tuple**, not a
  model object. Feed both to `Transcriber(path, arch)`.
- The result is `Transcript(lines=[TranscriptLine(...)])`. Read
  `transcript.lines[i].text`. Do **not** `str()` the Transcript - you get
  "[0.00s] " timestamp prefixes baked into the string.
- Models download from a CDN on first use into a per-user cache, *not* into the
  package. Run once on good wifi before the venue or you will be pulling
  ~15 MB over contested conference wifi.
- Measured ~1.5x realtime on a laptop CPU with `medium-streaming-en`. A Pi will
  be slower - measure before betting the demo on one.
- Spoken numbers come out as digits ("gate four" -> "Gate 4"), which is exactly
  what you want for callsigns and grids.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from .base import SAMPLE_RATE, Transcriber, clean_text


class MoonshineTranscriber(Transcriber):
    """Fast on-device recognition. Best default for short radio traffic."""

    name = "moonshine"

    def __init__(self, language: str = "en",
                 keyterms: Optional[Sequence[str]] = None, **kwargs):
        super().__init__(keyterms=keyterms, **kwargs)
        self.language = language
        self._tr = None

    def available(self) -> Tuple[bool, str]:
        try:
            import moonshine_voice  # noqa: F401
        except ImportError:
            return False, "not installed - pip install moonshine-voice"
        return True, "ready"

    def load(self) -> None:
        if self._loaded:
            return
        import moonshine_voice as mv
        from moonshine_voice.transcriber import Transcriber as MoonshineCore

        # Downloads on first run. Everything after is local.
        path, arch = mv.get_model_for_language(self.language)
        self._tr = MoonshineCore(path, arch)
        if self.keyterms:
            # Biases decoding toward domain words. Helps with callsigns; it is
            # not magic and will still occasionally mishear small words.
            self._tr.set_keyterms(list(self.keyterms))
        self._loaded = True

    def close(self) -> None:
        if self._tr is not None:
            try:
                self._tr.close()
            except Exception:
                pass                      # closing a dead handle is not news
            self._tr = None
        super().close()

    def transcribe(self, samples: Sequence[float],
                   sample_rate: int = SAMPLE_RATE) -> str:
        self.load()
        transcript = self._tr.transcribe_without_streaming(
            list(samples), sample_rate
        )
        lines = getattr(transcript, "lines", None) or []
        return clean_text(" ".join(ln.text for ln in lines if ln.text))
