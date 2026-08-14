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

    #: Measured on an Intel Core Ultra 7 255H with a 4.1s clip, 15 Aug 2026:
    #:
    #:   TINY_STREAMING    1.48s   2.8x realtime   5/6 key phrases
    #:   MEDIUM_STREAMING  4.70s   0.9x realtime   5/6 key phrases
    #:
    #: Same accuracy, 3.2x the speed. MEDIUM is the library default and it is
    #: *slower than realtime*, so under continuous chatter it can never catch
    #: up. We default to TINY_STREAMING instead. Override per machine with
    #: $TAK_STT_MODEL, e.g. MEDIUM_STREAMING if accuracy matters more than lag.
    #:
    #: Only the streaming architectures accept keyterms; TINY and BASE raise
    #: MoonshineError, which is caught rather than allowed to kill a demo.
    DEFAULT_ARCH = "TINY_STREAMING"

    def __init__(self, language: str = "en",
                 keyterms: Optional[Sequence[str]] = None,
                 model_arch: Optional[str] = None, **kwargs):
        import os
        super().__init__(keyterms=keyterms, **kwargs)
        self.language = language
        self.model_arch = (model_arch or os.environ.get("TAK_STT_MODEL")
                           or self.DEFAULT_ARCH).strip().upper()
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
        from moonshine_voice.moonshine_api import ModelArch
        from moonshine_voice.transcriber import Transcriber as MoonshineCore

        wanted = getattr(ModelArch, self.model_arch, None)
        if wanted is None:
            raise ValueError(
                "unknown TAK_STT_MODEL %r - expected one of %s"
                % (self.model_arch, ", ".join(a.name for a in ModelArch))
            )

        # Downloads on first run. Everything after is local.
        try:
            path, arch = mv.get_model_for_language(self.language, wanted)
        except ValueError:
            # Not every arch is published for every language - BASE_STREAMING
            # has no English build, for instance. Fall back to the default
            # rather than refuse to start.
            path, arch = mv.get_model_for_language(self.language)
        self.model_arch = arch.name
        self._tr = MoonshineCore(path, arch)

        if self.keyterms:
            # Biases decoding toward domain words. Helps with callsigns; it is
            # not magic and will still occasionally mishear small words.
            # Only the streaming architectures support this - the others raise
            # MoonshineError, and losing keyterms beats losing the process.
            try:
                self._tr.set_keyterms(list(self.keyterms))
            except Exception:
                self.keyterms = ()
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
