"""Live streaming transcription - text appears while you are still talking.

Moonshine's headline feature, and the difference between a marker appearing
*after* someone finishes a transmission and one that grows *as they speak*.

    python examples/07_voice_stream.py --gain 50               # watch it work
    python examples/07_voice_stream.py --gain 50 --url udp://239.2.3.1:6969

How this differs from `06_voice_to_cot.py`:

| | 06 | 07 (this) |
|---|---|---|
| Segmentation | our energy VAD | moonshine's own |
| Recognition starts | after you stop | while you talk |
| Partial text | never | continuously |
| CoT sent | once, at the end | once, at the end |

Both send one event per completed line - CoT is not the place for half a
sentence. What you gain is that the *operator* sees the transmission forming,
and the recognition work is already done by the time the line closes.

The VAD is gone on this path. The streaming model decides where lines break
itself, and it does that better with continuous audio than with clips we have
already trimmed - handing it VAD output would throw away the context it uses.

**Measured, 15 Aug 2026, TINY_STREAMING, 4.11s clip fed at wall-clock speed:**

    1.00s  Ambulance.
    1.67s  Ambulance, seven.
    2.42s  Ambulance, 7-on-scene at
    3.87s  Ambulance 7-on-scene atomine stage to patients with
    6.38s  [closed] Ambulance 7-on-seen atomine stage 2 patients requires

First words at 1.00s against 4.11s of audio - text begins 3.1s before the
speaker stops. That part delivers.

**The catch: the final text is worse.** Non-streaming on the same clip gave
"Ambulance 7 on scene at the main stage to patients requesting backup";
streaming gave "7-on-seen atomine stage ... requires". The line also closed
2.3s *after* the audio ended, so the final answer is not faster - only the
partials are early. Curiously streaming got "2 patients" right where
non-streaming says "to patients", so neither strictly dominates.

Since CoT is built from the final text, **this path currently produces worse
markers than 06**. Use it for the live-captions effect in front of an
audience; use 06 when the marker matters. See --best-of-both, which shows the
partials from here and re-runs the closed line through the non-streaming
model for the event itself.

Ctrl-C to stop.
"""

import _path  # noqa: F401  (lets this run without installing the package)
import argparse
import sys
import threading
import time

from taklib import TAKSender, cot
from taklib.config import resolve_url
from taklib.voice.base import clean_text
from taklib.voice.interpret import (
    DEFAULT_KEYTERMS,
    LLMInterpreter,
    _normalise,
    interpret_text,
    to_cot,
)
from taklib.voice.mic import MicCapture

UID_PREFIX = "voice"
BOT_CALLSIGN = "VOICE"
SA_URL = "udp://239.2.3.1:6969"
CHAT_URL = "udp://224.10.10.1:17012"
DEFAULT_LAT, DEFAULT_LON = -27.4705, 153.0260


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gain", type=float, default=1.0,
                    help="digital mic gain (this laptop needs ~50)")
    ap.add_argument("--device", type=int, help="input device index")
    ap.add_argument("--model", default="TINY_STREAMING",
                    help="must be a *_STREAMING arch (default: TINY_STREAMING)")
    ap.add_argument("--update-interval", type=float, default=0.3,
                    help="seconds between partial updates. Lower feels more "
                         "live and costs more CPU (default: 0.3)")
    ap.add_argument("--url", help="where to SEND (default: mesh SA group)")
    ap.add_argument("--chat-url", default=CHAT_URL)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--best-of-both", action="store_true",
                    help="show live partials, but re-run each closed line "
                         "through the non-streaming model before building the "
                         "CoT - early feedback with the better final text")
    ap.add_argument("--llm", action="store_true",
                    help="use a local Ollama for low-confidence reports")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the CoT instead of sending it")
    args = ap.parse_args()

    import moonshine_voice as mv
    from moonshine_voice.moonshine_api import ModelArch
    from moonshine_voice.transcriber import (
        LineCompleted,
        LineStarted,
        LineUpdated,
    )
    from moonshine_voice.transcriber import Transcriber as MoonshineCore

    arch = getattr(ModelArch, args.model.upper(), None)
    if arch is None or "STREAMING" not in arch.name:
        ap.error("--model must be a streaming arch, e.g. TINY_STREAMING")

    print("loading %s ..." % arch.name)
    path, resolved = mv.get_model_for_language("en", arch)
    core = MoonshineCore(path, resolved, update_interval=args.update_interval)
    try:
        core.set_keyterms(list(DEFAULT_KEYTERMS))
    except Exception:
        pass                                  # streaming archs support it; be safe

    # A second, non-streaming transcriber for the final pass. Same weights,
    # different decode path - and on our test clip the non-streaming path is
    # markedly cleaner on the tail of a sentence.
    finaliser = None
    if args.best_of_both:
        print("loading finaliser (non-streaming pass) ...")
        finaliser = MoonshineCore(path, resolved)
        try:
            finaliser.set_keyterms(list(DEFAULT_KEYTERMS))
        except Exception:
            pass

    llm = None
    if args.llm:
        llm = LLMInterpreter()
        if not llm.available():
            print("no Ollama on 127.0.0.1:11434 - continuing with rules")
            llm = None

    sa = chat = None
    sa_url = resolve_url(args.url) if args.url else SA_URL
    if not args.dry_run:
        sa = TAKSender(sa_url)
        chat = TAKSender(args.chat_url)

    lock = threading.Lock()
    state = {"line": 0, "started": 0.0, "printed": 0}

    def on_event(event) -> None:
        """Called from moonshine's thread - keep it quick and thread-safe."""
        line = getattr(event, "line", None)
        if line is None:
            return
        text = clean_text(line.text or "")

        with lock:
            if isinstance(event, LineStarted):
                state["line"] += 1
                state["started"] = time.time()
                state["printed"] = 0
                print("\n[%02d] " % state["line"], end="", flush=True)
                return

            if isinstance(event, LineUpdated):
                # Print only what is new, so the line grows left to right the
                # way the words actually arrive.
                if len(text) > state["printed"]:
                    print(text[state["printed"]:], end="", flush=True)
                    state["printed"] = len(text)
                return

            if isinstance(event, LineCompleted):
                if len(text) > state["printed"]:
                    print(text[state["printed"]:], end="", flush=True)
                lag = time.time() - state["started"]
                print("\n     line closed after %.1fs" % lag, flush=True)

                if finaliser is not None:
                    audio = getattr(line, "audio_data", None)
                    if audio is not None and len(audio):
                        try:
                            res = finaliser.transcribe_without_streaming(
                                list(audio), 16000)
                            better = clean_text(
                                " ".join(l.text for l in (res.lines or [])))
                            if better and better != text:
                                print("     final: %s" % better, flush=True)
                                text = better
                        except Exception as exc:
                            print("     (finaliser failed: %s)" % exc)

                if not text:
                    return

                report = _normalise(interpret_text(text))
                if llm is not None and report["confidence"] < 0.75:
                    better = llm.interpret(text)
                    if better:
                        report = _normalise(better)

                print("     %s / %s / %s  conf %.2f"
                      % (report["intent"], report["agency"],
                         report.get("unit") or "-", report["confidence"]))

                event_bytes = to_cot(report, args.lat, args.lon,
                                     uid_prefix=UID_PREFIX)
                if sa is None:
                    print("     would send %d bytes" % len(event_bytes))
                else:
                    sa.send(event_bytes)
                    chat.send(cot.geochat(
                        "%s: %s" % (report.get("unit") or "UNKNOWN", text),
                        sender_uid="%s-bot" % UID_PREFIX,
                        sender_callsign=BOT_CALLSIGN))
                    print("     sent %d bytes" % len(event_bytes))

    stream = core.create_stream(update_interval=args.update_interval)
    stream.add_listener(on_event)
    stream.start()

    with MicCapture(device=args.device, gain=args.gain,
                    normalise=False) as mic:
        # normalise=False: that scaling is per-utterance, and on this path
        # there are no utterances - the model sees one continuous stream.
        if args.dry_run:
            print("dry run - nothing will be sent")
        else:
            print("SA   -> %s\nchat -> %s" % (sa_url, args.chat_url))
        print("speak - text appears as you talk. Ctrl-C to stop.")

        try:
            for block in mic.blocks():
                stream.add_audio(list(block), mic.sample_rate)
        except KeyboardInterrupt:
            print("\nstopping ...")
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            core.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
    except Exception as exc:
        print("error: %s" % exc, file=sys.stderr)
        sys.exit(1)
