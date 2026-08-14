"""Phi-4-multimodal backend - hears and reasons in one model.

This is the only backend that implements `interpret()`, and that is the entire
point of it. Every other recogniser turns audio into text and hands the text to
something else, which means the recogniser commits to a word before anything
knows what the sentence means. That is how "two patients" becomes "to
patients" - the acoustics are ambiguous and the recogniser has no idea it just
threw away the casualty count.

Phi-4-multimodal holds the audio and the meaning at the same time, so you can
ask it for structured output directly and skip the lossy text stage.

Cost of that: 5.6B parameters. Roughly 3 GB VRAM at 4-bit, ~11 GB at fp16, so a
6 GB laptop GPU wants `load_in_4bit=True` (the default here). Not viable on a
Raspberry Pi at all - run this on the laptop and let the Pi do capture.

**Verify before you depend on it:** quantized runtimes support Phi-4's text and
vision paths far better than the audio path. Run `python -m taklib.voice.phi4`
to check that audio actually works on your install before building a demo on
it. If the audio path is broken, fall back to moonshine plus the text
interpreter - the pipeline handles that automatically.
"""

from __future__ import annotations

import json
from typing import Dict, Optional, Sequence, Tuple

from .base import SAMPLE_RATE, Transcriber

MODEL_ID = "microsoft/Phi-4-multimodal-instruct"

#: Asking for JSON and nothing else. Small models pad answers with prose, so we
#: still defensively hunt for the first {...} block in the reply.
_JSON_INSTRUCTION = (
    "Listen to the radio transmission and return ONE JSON object, no prose.\n"
    'Keys: {"intent": one of [on_scene, responding, unavailable, clear, '
    'request_support, casualty_report, sighting, other], '
    '"agency": one of [police, ambulance, fire, ses, security, transport, '
    'unknown], "unit": callsign or null, "count": integer or null, '
    '"location": short string or null, "priority": one of [routine, urgent, '
    'emergency], "text": verbatim transcription}'
)


class Phi4Transcriber(Transcriber):
    """Audio straight to structured JSON. Heaviest and most capable backend."""

    name = "phi4"

    def __init__(self, model_id: str = MODEL_ID, load_in_4bit: bool = True,
                 device: Optional[str] = None,
                 keyterms: Optional[Sequence[str]] = None, **kwargs):
        super().__init__(keyterms=keyterms, **kwargs)
        self.model_id = model_id
        self.load_in_4bit = load_in_4bit
        self.device = device
        self._model = None
        self._processor = None

    def available(self) -> Tuple[bool, str]:
        try:
            import torch  # noqa: F401
        except ImportError:
            return False, "torch not installed - see pytorch.org for the CUDA build"
        try:
            import transformers  # noqa: F401
        except ImportError:
            return False, "transformers not installed - pip install transformers accelerate"
        if self.load_in_4bit:
            try:
                import bitsandbytes  # noqa: F401
            except ImportError:
                return False, ("bitsandbytes not installed (needed for 4-bit) - "
                               "pip install bitsandbytes, or pass load_in_4bit=False")
        import torch
        if torch.cuda.is_available():
            gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            return True, "CUDA %s, %.1f GB VRAM" % (
                torch.cuda.get_device_name(0), gb)
        return True, "CPU only - this will be slow, expect tens of seconds"

    def load(self) -> None:
        if self._loaded:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        kwargs = {"trust_remote_code": True, "torch_dtype": "auto"}
        if self.load_in_4bit and torch.cuda.is_available():
            from transformers import BitsAndBytesConfig
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
            )
            kwargs["device_map"] = "auto"
        elif self.device:
            kwargs["device_map"] = self.device

        self._processor = AutoProcessor.from_pretrained(
            self.model_id, trust_remote_code=True)
        self._model = AutoModelForCausalLM.from_pretrained(self.model_id, **kwargs)
        self._loaded = True

    def close(self) -> None:
        self._model = None
        self._processor = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        super().close()

    # -- generation ---------------------------------------------------------

    def _generate(self, prompt: str, samples: Sequence[float],
                  sample_rate: int, max_new_tokens: int) -> str:
        import numpy as np
        import torch

        audio = np.asarray(list(samples), dtype=np.float32)
        # Phi-4's chat template: <|audio_1|> marks where the clip is spliced in.
        text = ("<|user|><|audio_1|>%s<|end|><|assistant|>" % prompt)
        inputs = self._processor(
            text=text, audios=[(audio, sample_rate)], return_tensors="pt"
        )
        if hasattr(self._model, "device"):
            inputs = inputs.to(self._model.device)

        with torch.no_grad():
            out = self._model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False
            )
        # Drop the prompt tokens so we only decode what it actually said.
        generated = out[:, inputs["input_ids"].shape[1]:]
        return self._processor.batch_decode(
            generated, skip_special_tokens=True
        )[0].strip()

    def transcribe(self, samples: Sequence[float],
                   sample_rate: int = SAMPLE_RATE) -> str:
        self.load()
        return self._generate(
            "Transcribe this audio exactly. Output only the transcription.",
            samples, sample_rate, max_new_tokens=256,
        )

    def interpret(self, samples: Sequence[float],
                  sample_rate: int = SAMPLE_RATE) -> Optional[Dict]:
        """The reason this backend exists: audio in, structured dict out."""
        self.load()
        raw = self._generate(_JSON_INSTRUCTION, samples, sample_rate,
                             max_new_tokens=320)
        data = _first_json_object(raw)
        if data is None:
            # Better to fall back to the text pipeline than emit a bad CoT.
            return None
        data.setdefault("source", "phi4")
        return data


def _first_json_object(text: str) -> Optional[Dict]:
    """Pull the first {...} out of a reply. Small models like to add prose."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start:i + 1])
                    except ValueError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = text.find("{", start + 1)
    return None


if __name__ == "__main__":                      # quick capability check
    import sys
    t = Phi4Transcriber()
    ok, reason = t.available()
    print("phi4 available:", ok, "-", reason)
    if not ok:
        sys.exit(1)
    print("loading (first run downloads several GB) ...")
    t.load()
    print("loaded. Audio path is only proven once you run a real clip through")
    print("transcribe() - use examples/06_voice_to_cot.py --backend phi4.")
