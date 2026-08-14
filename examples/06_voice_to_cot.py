"""Speak a radio call, get a marker on the map.

The "rapidly evolving incident" pattern: nobody is typing during one, and every
agency is on a different radio net. This turns speech into structured CoT that
lands on the shared map.

    python examples/06_voice_to_cot.py --selftest        # no mic, no network
    python examples/06_voice_to_cot.py --backends        # what's installed
    python examples/06_voice_to_cot.py --say "ambulance seven on scene, two patients"
    python examples/06_voice_to_cot.py --wav clip.wav --url udp://239.2.3.1:6969

Swap recogniser without touching code:

    $env:TAK_STT="whisper"      # PowerShell
    set TAK_STT=moonshine       # Windows cmd

Mesh note: chat and SA go to *different* multicast groups, so this opens two
senders. Sending GeoChat to the SA group is silently invisible - it does not
error, it just never appears in anyone's chat window.
"""

import _path  # noqa: F401  (lets this run without installing the package)
import argparse
import sys

from taklib import TAKSender
from taklib.config import resolve_url
from taklib.voice import available_backends, get_transcriber, load_wav
from taklib.voice.interpret import (
    DEFAULT_KEYTERMS,
    LLMInterpreter,
    interpret_text,
    to_cot,
    understand,
)
from taklib import cot

UID_PREFIX = "voice"            # namespace ours so laptops don't collide
BOT_CALLSIGN = "VOICE"

SA_URL = "udp://239.2.3.1:6969"        # positions, markers, shapes
CHAT_URL = "udp://224.10.10.1:17012"   # GeoChat only - different group

# Where a report lands when we have no GPS. Brisbane; southern hemisphere is
# negative, and getting that sign wrong puts you in the sea off Japan.
DEFAULT_LAT, DEFAULT_LON = -27.4705, 153.0260

# Sentences to prove the pipeline without a microphone.
SELFTEST_LINES = [
    "Ambulance 7 on scene at the main stage, 2 patients, requesting backup.",
    "Police unit 3 responding to gate 4, crowd surge reported.",
    "Fire 12 is committed at the north concourse, we are unavailable.",
    "Mayday mayday, officer down at the south gate, urgent assistance.",
    "SES 2 clear of the incident and available.",
]


def show_report(report):
    print("  text       : %s" % report.get("text", ""))
    print("  intent     : %-16s agency: %s (team %s)"
          % (report["intent"], report["agency"], report["team"]))
    print("  unit       : %-16s count : %s"
          % (report.get("unit"), report.get("count")))
    print("  location   : %-16s prio  : %s"
          % (report.get("location"), report["priority"]))
    print("  source     : %-16s conf  : %.2f"
          % (report.get("source", "?"), report.get("confidence", 0.0)))


def run_mic(args, llm) -> None:
    """Listen until Ctrl-C, sending one CoT event per utterance."""
    from taklib.voice.mic import MicCapture

    ok, reason = MicCapture.available()
    if not ok:
        raise SystemExit("microphone unavailable: %s" % reason)

    stt = get_transcriber(args.backend, keyterms=DEFAULT_KEYTERMS)
    print("backend: %s - loading model ..." % stt.name)
    stt.load()

    sa_url = resolve_url(args.url) if args.url else SA_URL
    sa = None if args.dry_run else TAKSender(sa_url)
    chat = None if args.dry_run else TAKSender(args.chat_url)

    import time

    from taklib.voice.mic import UtteranceStream

    with MicCapture(device=args.device, gain=args.gain,
                    silence_seconds=args.silence) as mic:
        if args.gain != 1.0:
            print("mic gain: %.1fx" % args.gain)
        if args.threshold:
            mic.threshold = args.threshold
            print("VAD threshold: %.4f (fixed)" % mic.threshold)
        else:
            print("calibrating - stay quiet for a moment ...")
            print("VAD threshold: %.4f (from room noise)" % mic.calibrate())

        if args.dry_run:
            print("\ndry run - nothing will be sent")
        else:
            print("\nSA   -> %s" % sa_url)
            print("chat -> %s" % args.chat_url)
        print("listening. Ctrl-C to stop.\n")

        heard = 0
        last_dropped = 0
        with UtteranceStream(mic) as stream:
            for clip, stats in stream:
                t0 = time.time()
                report = understand(clip.samples, clip.sample_rate, stt, llm)
                asr = time.time() - t0
                if not report.get("text"):
                    continue                 # VAD fired on something wordless

                heard += 1
                # Realtime factor under 1.0 means recognition is slower than
                # speech, which is the number that decides whether this holds
                # up under continuous chatter.
                rtf = clip.duration / asr if asr else 0.0
                flags = ""
                if stats["backlog"]:
                    flags += "  backlog %d" % stats["backlog"]
                if stats["dropped"] > last_dropped:
                    flags += "  DROPPED %d" % (stats["dropped"] - last_dropped)
                    last_dropped = stats["dropped"]

                print("[%2d] %.1fs audio, %.1fs asr (%.1fx)%s"
                      % (heard, clip.duration, asr, rtf, flags))
                print("     %s" % report["text"])
                print("     %s / %s / %s  conf %.2f"
                      % (report["intent"], report["agency"],
                         report.get("unit") or "-",
                         report.get("confidence", 0.0)))

                event = to_cot(report, args.lat, args.lon,
                               uid_prefix=UID_PREFIX)
                if sa is not None:
                    sa.send(event)
                    chat.send(cot.geochat(
                        "%s: %s" % (report.get("unit") or "UNKNOWN",
                                    report["text"]),
                        sender_uid="%s-bot" % UID_PREFIX,
                        sender_callsign=BOT_CALLSIGN))
                    print("     sent %d bytes\n" % len(event))
                else:
                    print("     would send %d bytes\n" % len(event))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", help="moonshine | whisper | phi4 (default: $TAK_STT)")
    ap.add_argument("--backends", action="store_true",
                    help="list backends and whether they can run here")
    ap.add_argument("--selftest", action="store_true",
                    help="run the rules over canned sentences - no mic, no network")
    ap.add_argument("--say", help="interpret this text directly, skipping speech")
    ap.add_argument("--wav", help="transcribe and interpret a 16-bit PCM wav")
    ap.add_argument("--mic", action="store_true",
                    help="listen on the microphone and send a CoT per utterance")
    ap.add_argument("--device", type=int, help="input device index (see --devices)")
    ap.add_argument("--devices", action="store_true", help="list input devices")
    ap.add_argument("--meter", action="store_true",
                    help="show a live input level bar - run this when the mic "
                         "seems deaf, before touching --threshold")
    ap.add_argument("--threshold", type=float,
                    help="VAD threshold; default is calibrated from the room")
    ap.add_argument("--gain", type=float, default=1.0,
                    help="digital gain on the mic, for when the OS input level "
                         "is low and locked (managed laptop, cheap USB mic)")
    ap.add_argument("--silence", type=float, default=0.8,
                    help="seconds of quiet that ends an utterance. Lower it "
                         "for clipped radio traffic, raise it if one sentence "
                         "keeps splitting in two (default: 0.8)")
    ap.add_argument("--url", help="where to SEND (default: the mesh SA group)")
    ap.add_argument("--chat-url", default=CHAT_URL,
                    help="GeoChat multicast group (default: %s)" % CHAT_URL)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--llm", action="store_true",
                    help="use a local Ollama to rescue low-confidence reports")
    ap.add_argument("--llm-model", default="qwen3:1.7b")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the CoT and print it, send nothing")
    args = ap.parse_args()

    if args.backends:
        print("speech backends:")
        for name, ok, reason in available_backends():
            print("  %-10s %-5s %s" % (name, "OK" if ok else "-", reason))
        return

    if args.devices:
        from taklib.voice.mic import MicCapture
        ok, reason = MicCapture.available()
        print("audio: %s" % reason)
        if ok:
            MicCapture.list_devices()
        return

    if args.meter:
        from taklib.voice.mic import MicCapture
        with MicCapture(device=args.device, gain=args.gain) as mic:
            if args.threshold:
                mic.threshold = args.threshold
            peak = mic.meter()
        print("peak rms: %.5f  (gain %.1fx)" % (peak, args.gain))
        if peak < 0.0005:
            print("\nThat is silence - audio is not reaching Python at all.")
            print("Gain will not help; it multiplies zero. Check:")
            print("  1. Settings > Privacy & security > Microphone")
            print("     - 'Microphone access' on")
            print("     - 'Let desktop apps access your microphone' on")
            print("  2. Try another device index from --devices")
        elif peak < 0.02:
            suggested = round(min(200.0, 0.08 / max(peak, 1e-6)), 1)
            print("\nToo quiet for reliable detection.")
            print("If you cannot raise the OS input level, amplify here:")
            print("  --gain %.1f --threshold %.4f"
                  % (suggested, max(0.002, peak * suggested * 0.25)))
        else:
            print("\nHealthy. Speech peaks here are normally 0.02-0.20.")
            print("Auto-calibration should cope; pin --threshold %.4f if not."
                  % max(0.005, peak * 0.25))
        return

    # --- rules only, no audio, no network -----------------------------------
    if args.selftest:
        print("interpreting canned radio traffic (rules only)\n")
        for line in SELFTEST_LINES:
            report = interpret_text(line)
            report.setdefault("team", "White")
            from taklib.voice.interpret import _normalise
            report = _normalise(report)
            show_report(report)
            event = to_cot(report, args.lat, args.lon, uid_prefix=UID_PREFIX)
            print("  cot        : %d bytes\n" % len(event))
        print("rules pipeline OK - no speech backend was needed")
        return

    llm = None
    if args.llm:
        llm = LLMInterpreter(model=args.llm_model)
        if not llm.available():
            print("warning: no Ollama on 127.0.0.1:11434 - continuing with rules")
            llm = None

    # --- live microphone: run until Ctrl-C ----------------------------------
    if args.mic:
        run_mic(args, llm)
        return

    # --- get a report -------------------------------------------------------
    if args.say:
        from taklib.voice.interpret import _normalise
        report = _normalise(interpret_text(args.say))
        if llm and report["confidence"] < 0.75:
            better = llm.interpret(args.say)
            if better:
                report = _normalise(better)
    elif args.wav:
        stt = get_transcriber(args.backend, keyterms=DEFAULT_KEYTERMS)
        print("backend: %s" % stt.name)
        clip = load_wav(args.wav)
        print("audio  : %.2fs @ %dHz" % (clip.duration, clip.sample_rate))
        report = understand(clip.samples, clip.sample_rate, stt, llm)
    else:
        ap.error("give me --selftest, --say TEXT, --wav FILE, or --backends")
        return

    print()
    show_report(report)

    event = to_cot(report, args.lat, args.lon, uid_prefix=UID_PREFIX)
    chat_text = "%s: %s" % (report.get("unit") or "UNKNOWN",
                            report.get("text", ""))
    chat = cot.geochat(chat_text, sender_uid="%s-bot" % UID_PREFIX,
                       sender_callsign=BOT_CALLSIGN)

    if args.dry_run:
        print("\n--- CoT event ---")
        print(event.decode("utf-8", "replace"))
        print("--- GeoChat ---")
        print(chat.decode("utf-8", "replace"))
        return

    sa_url = resolve_url(args.url) if args.url else SA_URL
    print("\nsending SA   -> %s" % sa_url)
    with TAKSender(sa_url) as sa:
        sa.send(event)
    print("sending chat -> %s" % args.chat_url)
    with TAKSender(args.chat_url) as ch:
        ch.send(chat)
    print("done - remember a successful send only means the datagram left here")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
    except Exception as exc:
        print("error: %s" % exc, file=sys.stderr)
        sys.exit(1)
