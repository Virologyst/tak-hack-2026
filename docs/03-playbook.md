# Hackathon playbook

## Before you walk in

- [ ] `python tak.py selftest` passes on every laptop
- [ ] `git clone` works on every laptop, everyone has pushed a test branch
- [ ] Everyone has read `CLAUDE.md` and knows `COT_URL` is the one knob
- [ ] `TAK_CALLSIGN` set per machine so we're not one dot
- [ ] ATAK-CIV installed on at least one Android device (needs a tak.gov
      account — register early, approval lags)
- [ ] Phone charger, USB cable, and a hotspot as a backup LAN

## First 60 minutes on the day

1. **Get the endpoint.** IP and port for the UDP feed. Write it in
   `docs/PROBLEM.md` so nobody has to ask twice.
2. **`export COT_URL=udp://THEIR_IP:PORT`** on every machine.
3. **`python tak.py status udp://THEIR_IP:PORT`** — confirm datagrams leave cleanly.
4. **`python tak.py send`** and get someone with ATAK to confirm they see the
   marker. This is the only real proof the pipe works. Do not skip it and do
   not defer it — everything else is built on this assumption.
5. **Read the problem statement twice.** Write the actual goal in one sentence
   at the top of `docs/PROBLEM.md`.
6. **Pick the closest thing in `examples/`** and get an ugly end-to-end version
   emitting real CoT. A crude thing on the map beats an elegant thing in a
   terminal, and it de-risks the demo before you've spent any cleverness.

## Choosing what to build

Nearly every TAK problem is one of two shapes:

**Get data onto the shared map** — a feed, a sensor, a model output, an API,
a spreadsheet. Start from `examples/02_feed_bridge.py`. This is the reliable
scoring path: visible, fast, obviously useful.

**React to what's already on the map** — chat bots, geofence alarms, nearest-
asset queries, automatic tasking. Start from `examples/03_geochat_bot.py` or
`04_geofence_alert.py`. Higher wow factor because the map talks back, and it
demos beautifully.

The strongest entries usually do a small version of both: bring something new
onto the map, then have it react.

### Idea seeds

| Idea | Effort | Notes |
|---|---|---|
| Public feed → CoT markers | Low | Weather, ADS-B, AIS, traffic, fire/flood alerts. Instant payoff |
| Vision model → detections | Medium | Camera or drone feed, emit contacts with confidence |
| GeoChat assistant | Medium | "nearest medic", "summarise activity here". Pairs well with an LLM |
| Geofence / proximity alerts | Low | Alarm when anything enters an area — `geo.point_in_polygon` |
| Ops dashboard | Low | We already have one; extend `taklib/dashboard.py` |
| Route / task optimiser | Medium | Compute and push a `cot.route()` back to the operators |
| CASEVAC coordinator | Medium | `cot.casevac()` plus nearest-asset logic |

## Demo craft

The build is half of it. Judges see four minutes.

- **Have the map on the big screen**, not a terminal. `python tak.py dashboard`
  is designed exactly for this, and works offline with no CDN.
- **Record a good run** with `python -m taklib.server --record demo.cot` and
  keep `--replay demo.cot --loop` ready. If the live feed dies during judging,
  you switch to replay and keep talking. This has saved more demos than any
  amount of clean code.
- **Seed the map before you present.** An empty map with one dot is a weak
  opening. Have context on screen when you start.
- **Say the problem in one sentence, then show the map.** Not architecture
  first. Architecture is the last thirty seconds, if at all.
- **Name the honest limitation** before a judge finds it. It reads as
  competence, not weakness.

## Working across several machines

See `BRANCHING.md`. The rules that stop the pain:

- Never commit to `main`. It stays demo-ready at all times.
- One branch per idea, push early and often.
- Namespace your CoT uids (`craig-drone-01`) so parallel testing doesn't
  collide on the shared map.
- If two people need to test simultaneously, use different `TAK_CALLSIGN`
  values and different uid prefixes.

## When something breaks

`docs/04-troubleshooting.md`. The three that account for most of it:

- **Markers pile up instead of moving** → your `uid` is changing between sends.
- **Markers appear then vanish** → `stale` is shorter than your send interval.
- **Nothing appears at all** → verify locally first
  (`python tak.py listen --url udp://127.0.0.1:6969`), then check the address.
  UDP will never tell you it failed.
