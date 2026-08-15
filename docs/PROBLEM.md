# The problem statement

> Everyone works from this file, so keep it current — it's cheaper than asking
> across a noisy room.

## The brief, verbatim

> "How might we use TAK to better enable multiple agencies & organisations to
> deconflict resources, coordinate response actions and maintain shared
> situational awareness during a rapidly evolving incident occurring within a
> major event precinct or densely populated urban gathering?"

— TAKHACK 2026, BeatenZone Venture Partners

### Reading it

Four verbs, and they are not equally hard:

| Phrase | What it actually demands |
|---|---|
| *multiple agencies & organisations* | Police, ambulance, fire, event security, council, transport, volunteers. Separate systems, separate radio nets, separate command. |
| **deconflict resources** | **The hard one.** Stop two agencies tasking the same asset; stop a sector going uncovered. |
| *coordinate response actions* | Task, assign, acknowledge — with the state visible to everyone. |
| *maintain shared situational awareness* | The easy one. This is TAK working as designed. |
| *rapidly evolving* | Nobody is typing. Input has to be faster than a keyboard. |
| *major event precinct / dense urban* | Bounded geography. Sectors are meaningful. Crowds constrain movement. |

**The differentiator is deconfliction.** Shared SA is table stakes — every team will
have markers on a map by lunchtime. TAK shows you everything and tells you
nothing: it will let two agencies commit the same ambulance and never raise a
word. The gap is the analysis layer on top of the common picture.

## Connection details

| | |
|---|---|
**Confirmed by the organisers: plain UDP multicast. No server, no certs.**
This is ATAK *mesh* mode, so the repo's original architectural assumption holds.

| | |
|---|---|
| **SA / position CoT** | `udp://239.2.3.1:6969` — the `taklib` default |
| **GeoChat** | `udp://224.10.10.1:17012` — **different group, see below** |
| Transport | UDP multicast (organisers confirm both tested) |
| Confirmed working? | ☐ someone with ATAK has seen our marker |
| Confirmed by | (name, time) |
| Data package / certs | not needed |

```bash
export COT_URL=udp://239.2.3.1:6969
```

> ### The two-group trap
>
> **Chat and SA go to different multicast groups.** Everything in this repo
> assumes one URL — `examples/04_geofence_alert.py` sends its `cot.geochat()`
> down the same sender as its markers, and `taklib/config.py` has no separate
> chat address. On a TAK *server* that works fine. On the mesh it does not:
> GeoChat sent to `239.2.3.1:6969` will not appear in anyone's chat window.
>
> Anything that talks needs **two senders**:
>
> ```python
> sa   = TAKSender("udp://239.2.3.1:6969")      # markers, tracks, polygons
> chat = TAKSender("udp://224.10.10.1:17012")   # geochat only
> ```
>
> Good news: multicast is already fully supported — `send.py` sets
> `IP_MULTICAST_TTL` and `multicast_socket()` handles `IP_ADD_MEMBERSHIP` for
> listening.
>
> **TTL is 1**, so everything stays on the local LAN and never crosses a router.
> That is correct for the venue, and it also means **you must be on their
> network** — none of this reaches anyone from a hotel wifi.

### Agency identity — decided

Agencies are distinguished by **`__group` team colour**, not by CoT affiliation.

Every civil responder is "friendly", so `a-f-*` types all render as identical
blue rectangles — affiliation cannot tell police from ambulance. Team colour is
the axis ATAK renders distinctly, and it already round-trips through our code:
`cot.unit(team="Red", role="HQ")` writes it, `evt["team"]` reads it back, and
the dashboard already shows it.

| Agency | Team colour |
|---|---|
| _(assign on the day — one per agency, keep them far apart visually)_ | |

## The problem, in one sentence

> _(PROPOSAL — argue with this before anyone writes code.)_
>
> An incident commander running a crowded precinct cannot see when two agencies
> have committed the same asset or when a sector has quietly gone uncovered, so
> we make the shared map say it out loud, in seconds, without anyone typing.

## What we're building

_(PROPOSAL)_

- **Shape:** both — voice puts data onto the map, the engine reacts to the map
- **Starting from:** `examples/04_geofence_alert.py` (sectors instead of one
  watch area, conflicts instead of breaches) + `examples/03_geochat_bot.py`
- **Data source:** 2-way radio audio into the laptop (USB adapter or line-in),
  transcribed locally + simulated agency asset feeds
- **What appears on the map:** sector polygons colour-coded by coverage,
  incident markers, and GeoChat alerts from a `DECONFLICT` bot

### The engine, concretely

Listens to every CoT event, holds state, and speaks up when:

| Rule | Output |
|---|---|
| Two agencies converge on one incident | GeoChat conflict alert + red marker |
| A sector drops to zero assigned assets | Sector polygon turns red for everyone |
| An incident is raised | `geo.nearest()` names the closest *available* unit |
| Too many units on one incident | Span-of-control warning |

Assets carry their agency and status in the CoT `<detail>` block via `extra=`,
so other clients ignore what they don't understand and nothing breaks.

## Success looks like

- [ ] Minimum: something real on the map, end to end
- [ ] Target: a spoken report becomes an incident marker, and the engine names
      the nearest available unit in GeoChat
- [ ] Target: two agencies tasking one asset raises a visible conflict alert
- [ ] Stretch: sector coverage recomputes live and repaints as units move
- [ ] Stretch: dashboard on the big screen as the "agency without ATAK" view


## Who's doing what

| Person | Machine | Branch | Callsign | UID prefix |
|---|---|---|---|---|
| | | | | |

## Demo plan

1. One sentence on the problem
2. Show the map (`python tak.py dashboard` on the big screen)
3. The moment that lands: _(PROPOSAL)_ voice report comes in → incident appears
   → engine names the nearest available unit → a second agency tasks that same
   unit → **conflict alert fires** → their sector drops to zero coverage →
   sector turns red on every screen
4. Honest limitation we name ourselves: _(PROPOSAL)_ we simulate the agency
   feeds. Real deployment needs each agency's CAD/dispatch system to emit CoT —
   which is the actual organisational problem, not the technical one

**Fallback:** record a good run with
`python -m taklib.server --record demo.cot`, keep
`python -m taklib.server --replay demo.cot --loop` ready in a spare terminal.

## Notes and decisions

_(Anything learned the hard way — put it here so nobody learns it twice.)_

### Speech-to-text: use moonshine. Phi-4 was tested and rejected.

`taklib.voice` supports three backends behind `$TAK_STT`. Only one earns its
place right now.

| Backend | Download | Result |
|---|---|---|
| **moonshine** | 15 MB + ~15 MB models | **Works.** ~1.5x realtime on the laptop CPU, clean transcriptions, spoken numbers arrive as digits ("gate four" → "Gate 4") |
| phi-4-multimodal (int4 ONNX) | **5.1 GB** | Hears correctly, then degenerates. See below |
| whisper | varies | Written as a fallback, never exercised |

**Phi-4-multimodal, int4 ONNX, DirectML, RTX 4050 6 GB — tested 15 Aug.**
The appeal was real: it reasons on the audio itself, so it should skip the
lossy transcribe-then-parse step that turns "two patients" into "to patients".
In practice the int4 quantization broke it. It transcribed the opening words
correctly and then looped the same phrase forever; damping the loop produced
fluent nonsense instead; asked for JSON it invented generic values from the
prompt while ignoring the audio. Loading the speech LoRA adapter explicitly
did not help. Full write-up in `taklib/voice/phi4.py`.

Worth revisiting only with the fp16 build (~11 GB VRAM, so not this laptop).

**Gotcha if anyone retries it:** the speech processor accepts 8 kHz or 16 kHz
only. Feed it 24 kHz and it silently produces garbage rather than resampling.

### Mic notes

- This laptop's input gain is ~100x below normal and the OS control is locked
  (managed device). Use `--gain 50`. `--meter` measures and suggests a value.
- Capture and recognition run on separate threads, with a bounded queue that
  drops the *oldest* clips under load — during a fast-moving incident the
  newest transmission is the one that matters, and a silently growing lag is
  worse than an acknowledged gap.
