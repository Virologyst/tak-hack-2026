"""Live microphone capture, chopped into utterances by a simple VAD.

Deliberately backend-agnostic. It yields `AudioClip`s and does not care which
recogniser eats them, so swapping `$TAK_STT` keeps working with live audio.
(Moonshine ships its own `MicTranscriber` which is lower latency, but it only
helps moonshine - using it here would quietly break the swap.)

The VAD is energy-based, not a neural model. That is a deliberate trade: it is
instant, has no dependencies beyond the audio library, and is easy to reason
about at 3am. It will trigger on a slammed door.

**Calibrate on arrival.** A hackathon floor is loud, and a fixed threshold
tuned in a quiet room will either never trigger or never stop. `calibrate()`
samples the actual room and sets the threshold from it - call it once when the
venue is at its normal noise level, not during a quiet moment.

    from taklib.voice import get_transcriber
    from taklib.voice.mic import MicCapture

    stt = get_transcriber()
    with MicCapture() as mic:
        mic.calibrate()
        for clip in mic.utterances():
            print(stt.transcribe(clip.samples, clip.sample_rate))
"""

from __future__ import annotations

import queue
import time
from typing import Iterator, Optional

from .base import SAMPLE_RATE, AudioClip

BLOCK_SECONDS = 0.03            # 30 ms blocks - fine enough to catch onsets


class MicCapture:
    """Capture speech, emit one `AudioClip` per utterance.

    An utterance starts when RMS crosses `threshold` and ends after
    `silence_seconds` below it. Clips shorter than `min_speech` are dropped as
    coughs and door slams; clips are force-closed at `max_seconds` so one long
    monologue cannot stall the pipeline forever.
    """

    def __init__(self, device: Optional[int] = None,
                 sample_rate: int = SAMPLE_RATE,
                 threshold: float = 0.015,
                 silence_seconds: float = 0.8,
                 min_speech: float = 0.35,
                 max_seconds: float = 15.0,
                 pre_roll: float = 0.25,
                 gain: float = 1.0,
                 normalise: bool = True,
                 target_rms: float = 0.06):
        self.device = device
        self.sample_rate = int(sample_rate)
        # Digital gain, applied before the VAD sees anything. Needed when the
        # OS input level is low and you cannot raise it - a managed laptop, or
        # a Pi with a cheap USB mic. It amplifies noise too, so prefer fixing
        # the input level when you actually can.
        self.gain = float(gain)
        # Scale each finished utterance to a sane level before it reaches the
        # recogniser. Independent of `gain`: that one exists to make the VAD
        # trigger, this one exists because ASR models are trained on audio at
        # normal loudness and quietly lose accuracy on very quiet input.
        self.normalise = bool(normalise)
        self.target_rms = float(target_rms)
        self.threshold = float(threshold)
        self.silence_seconds = float(silence_seconds)
        self.min_speech = float(min_speech)
        self.max_seconds = float(max_seconds)
        # Speech onsets get clipped without this - the VAD only fires once the
        # sound is already loud, by which point the first consonant is gone.
        self.pre_roll = float(pre_roll)
        self._stream = None
        self._q: "queue.Queue" = queue.Queue()

    # -- lifecycle ----------------------------------------------------------

    @staticmethod
    def available() -> "tuple[bool, str]":
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            return False, "sounddevice not installed - pip install sounddevice"
        try:
            import sounddevice as sd
            inputs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        except Exception as exc:
            return False, "audio system error: %s" % exc
        if not inputs:
            return False, "no input devices found"
        return True, "%d input device(s)" % len(inputs)

    @staticmethod
    def list_devices() -> None:
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                print("  [%d] %-45s ch=%d rate=%d"
                      % (i, d["name"][:45], d["max_input_channels"],
                         d["default_samplerate"]))

    def open(self) -> "MicCapture":
        import sounddevice as sd

        blocksize = int(self.sample_rate * BLOCK_SECONDS)

        def callback(indata, _frames, _time_info, status):
            if status:                       # overflows are normal under load
                pass
            # Copy: sounddevice reuses the buffer under us.
            block = indata[:, 0].copy()
            if self.gain != 1.0:
                block = block * self.gain
            self._q.put(block)

        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            blocksize=blocksize, device=self.device, callback=callback,
        )
        self._stream.start()
        return self

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def __enter__(self) -> "MicCapture":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- the VAD ------------------------------------------------------------

    def suggest_gain(self, seconds: float = 3.0,
                     target_peak: float = 0.08) -> float:
        """Measure the room and return the gain that would make speech usable.

        Speak *while this runs* - it works off the loudest thing it hears, so
        measuring silence tells it nothing. Apply the result as `gain`, or pass
        --gain on the example.
        """
        import numpy as np

        if self._stream is None:
            self.open()
        while not self._q.empty():
            self._q.get_nowait()

        peak = 0.0
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                block = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            peak = max(peak, float(np.max(np.abs(block))))

        if peak < 1e-6:                      # nothing at all; gain can't help
            return 1.0
        return round(min(200.0, target_peak / peak), 1)

    def calibrate(self, seconds: float = 1.5, multiplier: float = 3.0,
                  floor: float = 0.0015) -> float:
        """Measure the room and set `threshold` from it. Returns the threshold.

        `multiplier` is how far above ambient a voice has to be. 3x is a decent
        start; raise it in a loud room, lower it if quiet speech gets missed.
        """
        import numpy as np

        if self._stream is None:
            self.open()
        while not self._q.empty():           # drop anything already buffered
            self._q.get_nowait()

        levels = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                block = self._q.get(timeout=0.5)
            except queue.Empty:
                break
            levels.append(float(np.sqrt(np.mean(np.square(block)))))

        ambient = sorted(levels)[len(levels) // 2] if levels else 0.0
        self.threshold = max(floor, ambient * multiplier)
        return self.threshold

    def meter(self, seconds: float = 20.0) -> float:
        """Print a live input-level bar. Returns the peak RMS seen.

        Run this first whenever "it isn't hearing me". A flat zero means the
        audio never reaches Python, and no amount of threshold tuning will
        help - the usual culprits on Windows are the per-app slider in
        Settings > System > Sound > Volume mixer, or microphone access being
        denied under Settings > Privacy & security > Microphone.
        """
        import numpy as np

        if self._stream is None:
            self.open()
        while not self._q.empty():
            self._q.get_nowait()

        peak = 0.0
        deadline = time.time() + seconds
        print("speak now - Ctrl-C to stop early")
        print("  level                                     rms      state")
        try:
            while time.time() < deadline:
                try:
                    block = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue
                rms = float(np.sqrt(np.mean(np.square(block))))
                peak = max(peak, rms)
                # Log-ish scale: speech sits around 0.02-0.2, so linear bars
                # are useless at the bottom where the interesting part is.
                filled = min(40, int((rms ** 0.5) * 90))
                state = "SPEECH" if rms >= self.threshold else ""
                print("  [%-40s] %.5f  %s" % ("#" * filled, rms, state),
                      end="\r", flush=True)
        except KeyboardInterrupt:
            pass
        print()
        return peak

    def utterances(self) -> Iterator[AudioClip]:
        """Yield one clip per detected utterance. Runs until interrupted."""
        import numpy as np

        if self._stream is None:
            self.open()

        speaking = False
        buffer: list = []
        pre: list = []
        pre_blocks = max(1, int(self.pre_roll / BLOCK_SECONDS))
        silent_blocks = 0
        silence_limit = max(1, int(self.silence_seconds / BLOCK_SECONDS))
        max_blocks = int(self.max_seconds / BLOCK_SECONDS)

        while True:
            try:
                block = self._q.get(timeout=1.0)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(np.square(block))))
            loud = rms >= self.threshold

            if not speaking:
                pre.append(block)
                if len(pre) > pre_blocks:
                    pre.pop(0)
                if loud:
                    speaking = True
                    buffer = list(pre)       # keep the onset we nearly missed
                    pre = []
                    silent_blocks = 0
                continue

            buffer.append(block)
            silent_blocks = 0 if loud else silent_blocks + 1

            done = silent_blocks >= silence_limit or len(buffer) >= max_blocks
            if not done:
                continue

            speaking = False
            samples = np.concatenate(buffer) if buffer else np.zeros(0)
            buffer = []
            duration = len(samples) / float(self.sample_rate)
            if duration < self.min_speech:
                continue      # a cough, a chair, a door. Dropped in silence.

            if self.normalise and len(samples):
                # Bring the clip up to a level the recogniser expects. ASR
                # models are trained on normally-loud speech and lose accuracy
                # on very quiet input, so this matters even when the VAD was
                # perfectly happy. Cap the boost so a near-silent clip does not
                # get amplified into pure noise.
                rms = float(np.sqrt(np.mean(np.square(samples))))
                if rms > 1e-6:
                    scale = min(50.0, self.target_rms / rms)
                    samples = np.clip(samples * scale, -1.0, 1.0)

            yield AudioClip(samples.tolist(), self.sample_rate)
