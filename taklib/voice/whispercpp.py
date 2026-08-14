"""Whisper backend - the fallback everyone already knows how to debug.

Tries three routes, best first, and tells you which one it picked:

1. `faster-whisper` - pip-installable, CTranslate2, aarch64 wheels exist.
2. `pywhispercpp`   - bindings onto whisper.cpp proper.
3. `whisper-cli`    - the whisper.cpp binary on PATH, driven over a temp WAV.

Route 3 exists because it is the one that still works when a pip install has
gone wrong, which at a hackathon is a real state. It needs no Python packages
at all - just the compiled binary and a model file.

Whisper pads every input to 30 seconds regardless of how short the audio is, so
on two-second radio traffic it does roughly fifteen times more work than it
needs to. That is the whole reason moonshine is the default. Keep this one for
when you want output you can compare against something familiar.
"""

from __future__ import annotations

import os
import shutil
from typing import Optional, Sequence, Tuple

from .base import SAMPLE_RATE, Transcriber, write_wav


class WhisperTranscriber(Transcriber):
    """Whisper via whichever runtime is actually installed."""

    name = "whisper"

    def __init__(self, model: str = "base.en",
                 keyterms: Optional[Sequence[str]] = None,
                 binary: Optional[str] = None,
                 model_path: Optional[str] = None, **kwargs):
        super().__init__(keyterms=keyterms, **kwargs)
        self.model = model
        # Only used by the whisper-cli route.
        self.binary = binary or os.environ.get("WHISPER_CLI") or "whisper-cli"
        self.model_path = model_path or os.environ.get("WHISPER_MODEL")
        self._route = None
        self._impl = None

    # -- discovery ----------------------------------------------------------

    def _detect(self) -> Tuple[Optional[str], str]:
        try:
            import faster_whisper  # noqa: F401
            return "faster-whisper", "faster-whisper installed"
        except ImportError:
            pass
        try:
            import pywhispercpp  # noqa: F401
            return "pywhispercpp", "pywhispercpp installed"
        except ImportError:
            pass
        if shutil.which(self.binary):
            if not self.model_path:
                return None, ("%s found but no model - set WHISPER_MODEL to a "
                              "ggml-*.bin path" % self.binary)
            return "whisper-cli", "using binary %s" % self.binary
        return None, ("nothing installed - pip install faster-whisper, or put "
                      "whisper-cli on PATH and set WHISPER_MODEL")

    def available(self) -> Tuple[bool, str]:
        route, reason = self._detect()
        return (route is not None), reason

    def load(self) -> None:
        if self._loaded:
            return
        route, reason = self._detect()
        if route is None:
            from .base import TranscriberUnavailable
            raise TranscriberUnavailable(reason)
        self._route = route

        if route == "faster-whisper":
            from faster_whisper import WhisperModel
            # int8 keeps it honest on CPU and is plenty for short utterances.
            self._impl = WhisperModel(self.model, device="auto",
                                      compute_type="int8")
        elif route == "pywhispercpp":
            from pywhispercpp.model import Model
            self._impl = Model(self.model)
        self._loaded = True

    def close(self) -> None:
        self._impl = None
        self._route = None
        super().close()

    # -- the work -----------------------------------------------------------

    def transcribe(self, samples: Sequence[float],
                   sample_rate: int = SAMPLE_RATE) -> str:
        self.load()

        if self._route == "faster-whisper":
            import numpy as np
            audio = np.asarray(list(samples), dtype=np.float32)
            segments, _info = self._impl.transcribe(
                audio, language="en", vad_filter=True,
                initial_prompt=", ".join(self.keyterms) if self.keyterms else None,
            )
            return " ".join(s.text.strip() for s in segments).strip()

        if self._route == "pywhispercpp":
            import numpy as np
            audio = np.asarray(list(samples), dtype=np.float32)
            segments = self._impl.transcribe(audio)
            return " ".join(s.text.strip() for s in segments).strip()

        return self._transcribe_via_cli(samples, sample_rate)

    def _transcribe_via_cli(self, samples: Sequence[float],
                            sample_rate: int) -> str:
        """Shell out to whisper.cpp. Ugly, but it survives a broken pip."""
        import subprocess
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="taklib-voice-")
        wav = os.path.join(tmpdir, "clip.wav")
        try:
            write_wav(wav, samples, sample_rate)
            cmd = [self.binary, "-m", self.model_path, "-f", wav,
                   "--no-timestamps", "--output-txt", "-of",
                   os.path.join(tmpdir, "out")]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(
                    "whisper-cli failed (%d): %s"
                    % (proc.returncode, (proc.stderr or "").strip()[:400])
                )
            txt = os.path.join(tmpdir, "out.txt")
            if os.path.exists(txt):
                with open(txt, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read().strip()
            return (proc.stdout or "").strip()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
