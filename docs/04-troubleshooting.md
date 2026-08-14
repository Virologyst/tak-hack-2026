# Troubleshooting

Ordered by how often each one is actually the problem.

## Nothing shows up on the map

UDP never reports failure, so work inwards from your own machine.

**1. Is the CoT valid and is the code sending?**

```bash
# terminal 1
python tak.py listen --url udp://127.0.0.1:6969
# terminal 2
COT_URL=udp://127.0.0.1:6969 python your_script.py
```

Appears in terminal 1 → your events are well-formed and your code works. The
problem is addressing or network, not CoT.
Nothing → the problem is in your code. Print the bytes and look at them.

**2. Is the address right?**

```bash
python tak.py status udp://THEIR_IP:PORT
```

Check the port especially. UDP will happily send into a void forever.

**3. Are you on their network?** VPN, wifi SSID, captive portal. Multicast
(`239.x.x.x`) additionally needs everyone on the same LAN segment — it does not
cross most routers.

**4. Is your stale time in the past?** A marker with a stale timestamp already
gone is accepted and immediately hidden. Check your clock is right — a machine
whose clock is skewed by minutes emits events that are stale on arrival. This
one is genuinely hard to spot.

**5. Ask someone with ATAK.** It is the only ground truth for UDP.

## Markers multiply instead of moving

Your `uid` is changing between updates. Anything derived from a timestamp,
`uuid4()`, or a list index that shifts will do this.

```python
# wrong — a new marker every tick
cot.unit(f"contact-{time.time()}", lat, lon)
# right — the same thing, at a new place
cot.unit("contact-01", lat, lon)
```

## Markers appear then disappear

`stale` is shorter than your send interval. Send every 5s with `stale=120` and
you have plenty of headroom; `stale=3` with a 5s interval flickers.

Static markers can take a long stale (`cot.marker()` defaults to an hour).

## Markers are in the wrong place

- Southern hemisphere latitudes are **negative**. Brisbane is `-27.47, 153.02`.
  A missing minus sign puts you off the coast of Japan.
- Argument order is `(lat, lon)`. GeoJSON and many APIs use `(lon, lat)` —
  check which one your source hands you.
- Coordinates must be WGS84 decimal degrees, not degrees-minutes-seconds.
  `geo.parse_latlon()` handles common string forms.

## Chat messages don't arrive

- `sender_uid` should match a uid you actually emit as a unit, otherwise some
  clients won't render the sender properly.
- To reply privately, pass **both** `to_uid=` (their uid) and
  `chatroom=` (their callsign). Only setting one silently broadcasts.
- Broadcasts go to `All Chat Rooms`, which is the default.

## Events arrive garbled or truncated

- Over UDP, one event per datagram. Never concatenate.
- Keep events under ~1400 bytes or they fragment. Long `remarks` and embedded
  images are the usual culprits — put a URL in the detail instead of the data.

## The listener shows binary junk

The server is speaking TAK Protocol v1 (protobuf), not XML. Frames start with
`0xBF`. `pip install takproto` and `taklib` decodes them. We always *send* XML,
which every TAK server accepts, so this only affects reading.

## `python tak.py listen` hangs with no output

Usually correct behaviour — a quiet port. Use `--stop-after` style bounds in
code (`TAKListener(..., stop_after=10)`), or just confirm with a known-good
sender in another terminal.

## TLS errors on port 8089

- `CERTIFICATE_VERIFY_FAILED` → self-signed cert. Set
  `PYTAK_TLS_DONT_VERIFY = 1` for testing and say so in the demo.
- `SSLError: PEM lib` → the cert and key don't match, or the `.p12` extraction
  went wrong. Redo both openssl commands in `docs/02-connection.md`.
- Connection accepted then dropped → the server didn't like your client cert.
  You need one from *their* data package; a self-made cert won't authenticate.

## Windows specifics

- Console is cp1252 — non-ASCII in printed output shows as `?`. Keep runtime
  output ASCII; docstrings and docs are fine.
- Firewall prompts on first bind: allow on private networks, or nothing will
  reach you.
- Multicast loopback is sometimes disabled. Test between two machines rather
  than assuming your own send is broken.

## `pip install` fails at the venue

It doesn't matter. `taklib` is pure standard library — every command in
`tak.py` works with no third-party packages at all. `pytak` and `takproto` are
optional conveniences.

## Everything was working and now it isn't

```bash
git stash && python tak.py selftest
```

If selftest passes, the regression is in your working tree, not the toolkit.
`git diff` against the last commit you know was good — which is why we commit
often.
