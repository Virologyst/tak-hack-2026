"""faster-whisper backend - the accurate one.

Reinstated on evidence, having been deleted a day earlier on reasoning. The
reasoning was that Whisper pads every clip to 30 seconds, so on 2-4 second
radio traffic it does roughly ten times more work than the audio warrants.
That is true of the original OpenAI implementation and false of
`faster-whisper` with the settings below - which is the difference between
arguing from architecture and measuring the thing.

**Measured on this laptop, 20.6s of TTS speech band-limited to 300-3400 Hz with
noise and clipping to approximate a handset - the condition that matters,
because clean audio flatters everything:**

    engine                       WER      speed
    moonshine TINY_STREAMING    34.2%      6.1x
    moonshine MEDIUM_STREAMING  17.4%      1.2x
    faster-whisper tiny.en      27.0%     11.3x
    faster-whisper base.en      25.2%      3.8x
    faster-whisper small.en      9.2%      2.2x     <- this

Nearly four times more accurate than what we were running, and still
comfortably faster than realtime on CPU alone. The failure it removes is not
cosmetic: moonshine rendered "crowd surge reported" as "crowd search report
to 4", which on a deconfliction console is a lost incident rather than a typo.

Caveat kept deliberately: that was synthetic radio degradation, not a real
handset. The ranking should hold; the absolute numbers will not.

The settings below are the ones benchmarked. They matter:

- `beam_size=1` - greedy. Large speedup, and on short domain-specific
  utterances the beam buys very little.
- `condition_on_previous_text=False` - Whisper's biggest failure mode on radio
  is looping a previous phrase into the next clip. This is what stops it.
- `without_timestamps=True` - fewer tokens to generate, and we have our own
  timing from the VAD.
- `language="en"` - skips language detection on every single clip.
- `vad_filter=False` - `MicCapture` already did the VAD; doing it twice trims
  real speech.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from .base import SAMPLE_RATE, Transcriber, clean_text

#: Measured sweet spot. base.en is 1.7x faster and 2.7x worse; medium.en needs
#: a GPU to stay near realtime.
DEFAULT_MODEL = "small.en"


class WhisperTranscriber(Transcriber):
    """faster-whisper (CTranslate2). Accurate, and fast enough on CPU."""

    name = "whisper"

    def __init__(self, model: str = DEFAULT_MODEL,
                 keyterms: Optional[Sequence[str]] = None,
                 device: Optional[str] = None,
                 compute_type: Optional[str] = None, **kwargs):
        import os
        super().__init__(keyterms=keyterms, **kwargs)
        self.model_arch = (model or os.environ.get("TAK_STT_MODEL")
                           or DEFAULT_MODEL)
        self.device = device or os.environ.get("TAK_STT_DEVICE") or "auto"
        self.compute_type = compute_type
        self._impl = None

    def available(self) -> Tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False, "not installed - pip install faster-whisper"
        return True, "ready (%s)" % self.model_arch

    @staticmethod
    def _add_cuda_dlls() -> None:
        """Put the pip-installed NVIDIA DLLs on Windows' search path.

        `pip install nvidia-cublas-cu12` drops cublas64_12.dll into
        site-packages/nvidia/cublas/bin, which Windows does not search. So
        ctranslate2 reports a CUDA device, builds the model happily, and then
        dies with "cublas64_12.dll is not found" on the first encode - long
        after anything is watching. Three lines here turn that into a working
        GPU path.
        """
        import os
        import sys
        if not sys.platform.startswith("win"):
            return
        candidates = []
        try:
            # `nvidia` is a NAMESPACE package, so __file__ is None and only
            # __path__ tells you where the wheels actually landed.
            import nvidia
            candidates.extend(list(nvidia.__path__))
        except ImportError:
            pass
        import site
        for sp in (site.getsitepackages() if hasattr(site, "getsitepackages")
                   else []):
            candidates.append(os.path.join(sp, "nvidia"))
        for root in candidates:
            if not os.path.isdir(root):
                continue
            for pkg in os.listdir(root):
                binv = os.path.join(root, pkg, "bin")
                if os.path.isdir(binv):
                    try:
                        os.add_dll_directory(binv)
                    except (OSError, AttributeError):
                        pass

    def _pick_device(self) -> Tuple[str, str]:
        """CUDA if ctranslate2 can really use it, else CPU.

        Asking ctranslate2 rather than nvidia-smi on purpose: a GPU can be
        present while the CUDA runtime DLLs are missing, and the failure
        surfaces mid-transcription instead of at load.
        """
        self._add_cuda_dlls()
        if self.device in ("cpu", "cuda"):
            chosen = self.device
        else:
            chosen = "cpu"
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    chosen = "cuda"
            except Exception:
                pass
        compute = self.compute_type or (
            "int8_float16" if chosen == "cuda" else "int8")
        return chosen, compute

    def load(self) -> None:
        if self._loaded:
            return
        from faster_whisper import WhisperModel

        device, compute = self._pick_device()

        def build(dev, ct):
            m = WhisperModel(self.model_arch, device=dev, compute_type=ct)
            # PROVE it before returning. Constructing a CUDA model succeeds
            # even when the runtime DLLs are missing; the failure surfaces on
            # the first encode, which in production is the first time somebody
            # speaks. One second of silence here moves that discovery from the
            # demo to start-up.
            import numpy as np
            list(m.transcribe(np.zeros(16000, dtype=np.float32),
                              language="en", beam_size=1,
                              without_timestamps=True)[0])
            return m

        try:
            self._impl = build(device, compute)
        except Exception as exc:
            if device != "cuda":
                raise
            self.cuda_error = str(exc).splitlines()[0][:120]
            self._impl = build("cpu", "int8")
            device, compute = "cpu", "int8"
        self.device_used = device
        self.compute_used = compute
        self._loaded = True

    def close(self) -> None:
        self._impl = None
        super().close()

    def transcribe(self, samples: Sequence[float],
                   sample_rate: int = SAMPLE_RATE) -> str:
        self.load()
        import numpy as np

        audio = np.asarray(list(samples), dtype=np.float32)
        if sample_rate != SAMPLE_RATE:
            n = int(len(audio) * SAMPLE_RATE / sample_rate)
            audio = np.interp(np.linspace(0, len(audio) - 1, n),
                              np.arange(len(audio)), audio).astype(np.float32)

        segments, _info = self._impl.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=False,
            without_timestamps=True,
            condition_on_previous_text=False,
            # The operator's own vocabulary, as a decoding bias. Same role as
            # moonshine's keyterms.
            initial_prompt=", ".join(self.keyterms) if self.keyterms else None,
        )
        return clean_text(" ".join(s.text for s in segments))
