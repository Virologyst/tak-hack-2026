"""Audio in, CoT out, events to the browser. The bit with the threads in it.

    source -> transcriber -> pipeline.process() -> TAK senders
                                                -> SSE subscribers

Two sources, and the second one matters more than it looks:

- **mic** - a sound input, which at the venue is the 2-way radio's audio-out
  plugged into a line-in or a USB adapter.
- **wav** - a file, fed at wall-clock speed as though someone were speaking it.

The wav source is the demo insurance. A loud room, a radio that will not pair,
a venue network that is down, a laptop with no audio stack - none of those stop
you showing the whole idea working, end to end, on demand. Twenty lines for the
one thing most likely to save the demo.

Capture runs on its own thread. Recognition takes seconds and speech does not
wait: share a thread and every busy period pushes the map further behind
reality, which at demo time reads as the system ignoring you rather than being
slow. `UtteranceStream` already handles that, dropping the OLDEST clip when it
cannot keep up - during a fast-moving incident the newest transmission is the
one that matters, and an acknowledged gap beats a silent lag.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import pipeline  # noqa: E402

#: None means "let taklib.voice choose", which walks BACKEND_NAMES most
#: accurate first: faster-whisper small.en, then moonshine. Pinning a name here
#: would silently override an operator who installed the better engine.
DEFAULT_BACKEND = None


class Engine:
    """Owns the capture thread, the recogniser, and the senders.

    Everything public is safe to call from the HTTP threads. `publish` is
    handed in rather than imported so this module never needs to know that SSE
    exists.
    """

    def __init__(self, publish: Callable[[str, dict], None],
                 store, get_server: Callable[[], dict]):
        self.publish = publish
        self.store = store              # VocabStore - vocabulary comes from here
        self.get_server = get_server    # returns the active server row as a dict
        self.state = "stopped"
        self.error = ""
        self.detail = {}
        self.seq = 0
        self.recent: List[dict] = []    # last 20, so a fresh tab is not empty
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._sa = None
        self._chat = None
        self._stream = None

    # -- lifecycle -----------------------------------------------------------

    def status(self) -> dict:
        return {"state": self.state, "error": self.error, "seq": self.seq,
                **self.detail}

    def start(self, *, source: str = "mic", device: Optional[int] = None,
              wav: Optional[str] = None, service: Optional[str] = None,
              gain: float = 1.0, threshold: Optional[float] = None,
              silence: float = 0.8, backend: Optional[str] = None,
              loop: bool = False) -> dict:
        if self.state == "running":
            return {"ok": False, "error": "already running"}
        self._stop.clear()
        self.error = ""
        self.detail = {"source": source, "device": device, "wav": wav,
                       "service": service, "gain": gain}
        self.state = "starting"
        self._emit_engine()
        self._thread = threading.Thread(
            target=self._run, daemon=True,
            kwargs=dict(source=source, device=device, wav=wav, service=service,
                        gain=gain, threshold=threshold, silence=silence,
                        backend=backend, loop=loop))
        self._thread.start()
        return {"ok": True}

    def stop(self) -> dict:
        self._stop.set()
        # Wake the capture loop. Without this it only notices the stop flag
        # between utterances, so on a quiet channel the console sits at
        # "stopping" until somebody happens to speak - which reads as a hang.
        stream = getattr(self, "_stream", None)
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
        self.state = "stopping"
        self._emit_engine()
        return {"ok": True}

    # -- the worker ----------------------------------------------------------

    def _run(self, *, source, device, wav, service, gain, threshold, silence,
             backend, loop):
        stt = None
        mic = None
        try:
            from taklib.voice import get_transcriber
            from taklib.voice.interpret import DEFAULT_KEYTERMS

            vocab = self.store.load()
            # Bias the recogniser toward the words this service actually says.
            # The dictionary the operator typed IS the language model hint.
            keyterms = list(vocab.keyterms(service)) or list(DEFAULT_KEYTERMS)

            # No name unless the caller gave one: taklib.voice picks the most
            # accurate installed engine. On radio-shaped audio that is
            # faster-whisper small.en at 9.2% WER against moonshine TINY's
            # 34.2%, which is the difference between a transcript and a guess.
            backend = backend or DEFAULT_BACKEND
            self._set_state("loading", model=backend)
            stt = get_transcriber(backend, keyterms=keyterms)
            stt.load()

            self._open_senders()
            self._set_state("running", model=getattr(stt, "model_arch", stt.name),
                            backend=stt.name)

            clips = (self._wav_clips(wav, loop) if source == "wav"
                     else self._mic_clips(device, gain, threshold, silence))
            for clip, mic_ref in clips:
                mic = mic_ref
                if self._stop.is_set():
                    break
                self._handle(clip, stt, service)

        except Exception as exc:
            self.error = "%s: %s" % (type(exc).__name__, exc)
            self._set_state("error")
        finally:
            try:
                if mic is not None:
                    mic.close()
            except Exception:
                pass
            try:
                if stt is not None:
                    stt.close()
            except Exception:
                pass
            self._close_senders()
            if self.state != "error":
                self._set_state("stopped")

    def _handle(self, clip, stt, service):
        """One utterance, all the way to the wire and the browser."""
        started = time.time()
        try:
            text = stt.transcribe(clip.samples, clip.sample_rate)
        except Exception as exc:
            self.error = "transcribe failed: %s" % exc
            self._emit_engine()
            return
        asr = time.time() - started
        if not (text or "").strip():
            return                       # VAD fired on something wordless

        with self._lock:
            self.seq += 1
            seq = self.seq

        # The vocabulary is re-read per utterance. That is one indexed row from
        # the meta table, and it means a term typed on the Vocabulary page is
        # live on the very next transmission with no restart.
        vocab = self.store.load()
        server = self.get_server() or {}

        event = pipeline.process(
            text, vocab=vocab, service=service, server=server, seq=seq,
            clip={"duration": round(clip.duration, 2),
                  "asr": round(asr, 2),
                  "realtime": round(clip.duration / asr, 1) if asr else 0})

        event["sent"] = self._send(event)
        with self._lock:
            self.recent.append(event)
            del self.recent[:-20]
        self.publish("utterance", event)

    # -- senders -------------------------------------------------------------

    def _open_senders(self):
        """SA and GeoChat go to DIFFERENT multicast groups on the mesh.

        Chat sent to the SA group does not error, it simply never appears in
        anyone's chat window - so this opens two, and a failure to open either
        is reported rather than swallowed.
        """
        from taklib import TAKSender
        server = self.get_server() or {}
        sa_url = server.get("url") or "udp://239.2.3.1:6969"
        chat_url = server.get("chat_url") or "udp://224.10.10.1:17012"
        try:
            self._sa = TAKSender(sa_url)
        except Exception as exc:
            self._sa = None
            self.error = "SA sender (%s): %s" % (sa_url, exc)
        try:
            self._chat = TAKSender(chat_url)
        except Exception as exc:
            self._chat = None
            self.error = (self.error + " | " if self.error else "") + \
                         "chat sender (%s): %s" % (chat_url, exc)

    def _close_senders(self):
        for attr in ("_sa", "_chat"):
            sender = getattr(self, attr, None)
            if sender is not None:
                try:
                    sender.close()
                except Exception:
                    pass
            setattr(self, attr, None)

    def _send(self, event) -> dict:
        """Put it on the wire. A send failure is reported, never fatal."""
        out = {"sa": False, "chat": False, "url": None, "error": ""}
        if not event.get("cot"):
            return out
        server = self.get_server() or {}
        out["url"] = server.get("url") or "udp://239.2.3.1:6969"
        try:
            if self._sa is not None:
                self._sa.send(event["cot"].encode("utf-8"))
                out["sa"] = True
        except Exception as exc:
            out["error"] = str(exc)
        try:
            if self._chat is not None:
                from taklib import cot
                unit = (event.get("report") or {}).get("unit") or "UNKNOWN"
                self._chat.send(cot.geochat(
                    "%s: %s" % (unit, event["sanitised"]),
                    sender_uid="voice-bot", sender_callsign="VOICE"))
                out["chat"] = True
        except Exception as exc:
            out["error"] = (out["error"] + " | " if out["error"] else "") + str(exc)
        return out

    # -- sources -------------------------------------------------------------

    def _mic_clips(self, device, gain, threshold, silence):
        from taklib.voice.mic import MicCapture, UtteranceStream
        mic = MicCapture(device=device, gain=gain, silence_seconds=silence)
        mic.open()
        if threshold:
            mic.threshold = float(threshold)
        else:
            mic.calibrate()
        self.detail["threshold"] = round(mic.threshold, 5)
        self._emit_engine()
        stream = UtteranceStream(mic).start()
        self._stream = stream            # so stop() can wake this loop
        try:
            for clip, stats in stream:
                if self._stop.is_set():
                    break
                if stats.get("dropped"):
                    self.detail["dropped"] = stats["dropped"]
                yield clip, mic
        finally:
            stream.stop()
            self._stream = None

    def _wav_clips(self, path, loop):
        """Feed a wav at wall-clock speed, as if it were being spoken.

        Deliberately paced rather than fired all at once: the panes should fill
        the way they will on the day, and a demo that dumps twenty events in
        one frame teaches the viewer nothing about the latency.
        """
        from taklib.voice.base import AudioClip, load_wav
        from taklib.voice.mic import MicCapture

        if not path or not os.path.exists(path):
            raise FileNotFoundError("wav not found: %s" % path)

        source = load_wav(path)
        detector = MicCapture(sample_rate=source.sample_rate)
        detector.threshold = 0.008

        while not self._stop.is_set():
            for clip in _split_on_silence(source, detector.threshold):
                if self._stop.is_set():
                    break
                # Wait out the clip's own duration so playback is realtime.
                deadline = time.time() + clip.duration
                while time.time() < deadline and not self._stop.is_set():
                    time.sleep(0.05)
                yield clip, None
            if not loop:
                break

    # -- plumbing ------------------------------------------------------------

    def _set_state(self, state, **detail):
        self.state = state
        self.detail.update(detail)
        self._emit_engine()

    def _emit_engine(self):
        self.publish("engine", self.status())


def _split_on_silence(clip, threshold, block_seconds=0.03,
                      silence_seconds=0.5, min_speech=0.35):
    """Chop a wav into utterances the same way the live VAD would.

    Same energy rule as `MicCapture`, so a recording behaves like the radio
    rather than arriving as one enormous block.
    """
    from taklib.voice.base import AudioClip

    rate = clip.sample_rate
    block = max(1, int(rate * block_seconds))
    silence_limit = max(1, int(silence_seconds / block_seconds))
    samples = clip.samples

    out: List[AudioClip] = []
    buf: List[float] = []
    quiet = 0
    speaking = False

    for i in range(0, len(samples), block):
        chunk = samples[i:i + block]
        if not chunk:
            break
        rms = (sum(s * s for s in chunk) / len(chunk)) ** 0.5
        loud = rms >= threshold
        if not speaking:
            if loud:
                speaking, buf, quiet = True, list(chunk), 0
            continue
        buf.extend(chunk)
        quiet = 0 if loud else quiet + 1
        if quiet >= silence_limit:
            speaking = False
            if len(buf) / rate >= min_speech:
                out.append(AudioClip(buf, rate))
            buf = []

    if speaking and len(buf) / rate >= min_speech:
        out.append(AudioClip(buf, rate))
    return out
