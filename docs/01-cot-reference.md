# CoT reference — the only protocol you need to learn

Cursor-on-Target is one XML shape. Every position, marker, chat message,
detection and drawing in the TAK ecosystem is an `<event>`. Learn this and you
can talk to the whole system.

## The shape

```xml
<event version="2.0"
       uid="alpha-01"                       <!-- stable id; reuse it to MOVE the marker -->
       type="a-f-G-U-C"                     <!-- what it is; see the table below -->
       how="m-g"                            <!-- where the data came from -->
       time="2026-08-15T02:10:00.000000Z"   <!-- when it was generated -->
       start="2026-08-15T02:10:00.000000Z"  <!-- when it becomes valid -->
       stale="2026-08-15T02:12:00.000000Z"> <!-- when it drops off the map -->
  <point lat="-27.4705" lon="153.0260"
         hae="25.0"                         <!-- height above ellipsoid, metres -->
         ce="9999999" le="9999999"/>        <!-- circular/linear error; 9999999 = unknown -->
  <detail>
    <contact callsign="ALPHA"/>
    <__group name="Cyan" role="Team Member"/>
    <remarks>anything you like</remarks>
  </detail>
</event>
```

Three rules carry most of the weight:

1. **`uid` is identity.** Same uid on the next event and the marker moves.
   Different uid and you get a second marker. Duplicate ghosts on the map are
   always this.
2. **`stale` is a deadline.** The marker disappears at that timestamp. Send
   updates more often than your stale interval.
3. **`<detail>` has no fixed schema.** Put whatever you want in there. Clients
   that don't understand a child element ignore it. This is where your custom
   payload rides.

## Type codes

`a-` = an atom, something that exists in the world.
Format is `a-<affiliation>-<domain>-…`

| Code | Meaning |
|---|---|
| `a-f-G-U-C` | Friendly ground combat unit — the default blue dot |
| `a-f-G` | Friendly ground |
| `a-h-G` | Hostile ground |
| `a-n-G` | Neutral ground |
| `a-u-G` | Unknown ground |
| `a-f-A` / `a-h-A` | Friendly / hostile air |
| `a-f-A-M-F-Q` | Friendly UAV |
| `a-f-S` / `a-h-S` | Friendly / hostile sea surface |

Affiliation: `f` friendly · `h` hostile · `n` neutral · `u` unknown ·
`p` pending · `s` suspect · `a` assumed friend.
Domain: `G` ground · `A` air · `S` sea surface · `U` subsurface · `P` space.

`b-` = "bits", a report rather than a thing:

| Code | Meaning |
|---|---|
| `b-m-p-s-p-loc` | Waypoint / point of interest |
| `b-m-p-s-p-i` | Sensor point of interest (SPI) |
| `b-m-r` | Route |
| `b-t-f` | GeoChat message |
| `b-r-f-h-c` | CASEVAC / 9-line medevac |
| `b-a-o-tbl` | Emergency alert |

`u-d-` = drawings: `u-d-f` polygon or polyline, `u-d-c-c` circle, `u-d-r` rectangle.

In code, don't memorise these — use `taklib.types`:

```python
from taklib import types as t
t.HOSTILE_GROUND          # 'a-h-G'
t.atom("hostile", "air")  # 'a-h-A'
t.with_affiliation("a-u-G", "hostile")   # 'a-h-G' — reclassify as confidence changes
t.describe("a-h-A")       # 'Hostile air' — for dashboards and logs
```

## `how` — provenance

| Code | Meaning |
|---|---|
| `m-g` | Machine, GPS derived |
| `m-e` | Machine, estimated or calculated |
| `h-g-i-g-o` | Human, entered via GUI (chat, hand-placed markers) |
| `h-e` | Human, entered |

Use `m-g` for real sensor positions and `m-e` for anything your code inferred.
It is a small honesty signal that operators actually read.

## Building events

Every builder returns ready-to-send `bytes`.

```python
from taklib import cot, geo, types as t

# a thing that moves — reuse the uid to update it
cot.unit("alpha-01", -27.4705, 153.0260,
         callsign="ALPHA", team="Cyan",
         course=90, speed=3.5,        # draws a heading vector
         battery=87, remarks="on patrol", stale=120)

# a pin
cot.marker("rv-1", -27.47, 153.02, label="RV POINT", remarks="link up here")

# a machine-generated contact, with confidence
cot.detection("det-9", -27.48, 153.03,
              label="vehicle", confidence=0.82, source="yolov8",
              cot_type=t.HOSTILE_GROUND, ce=50)

# talk to operators
cot.geochat("Bridge online", sender_uid="bot-1", sender_callsign="BOT")

# geometry
cot.route("r-1", [(-27.47, 153.02), (-27.48, 153.03)], name="INFIL")
cot.polygon("ao-1", geo.circle_points(-27.47, 153.02, 500), name="AO ALPHA")
cot.circle("ring-1", -27.47, 153.02, 800, name="RANGE")

# specialist reports
cot.casevac("cv-1", -27.47, 153.02, patients_urgent=2, freq="31.55")
cot.emergency("e-1", -27.47, 153.02, callsign="ALPHA")
cot.video("cam-1", -27.47, 153.02, "rtsp://10.0.0.5:8554/cam", callsign="CAM-1")
```

### Custom payloads

`<detail>` is open, so carry whatever your idea needs:

```python
cot.unit("sensor-3", lat, lon, extra={
    "sensor": {"type": "acoustic", "db": "84.2"},
    "myteam": {"score": "0.93", "model": "v2"},
})

cot.unit("drone-1", lat, lon, extra='<__video url="rtsp://10.0.0.9/live"/>')
```

`extra=` accepts an XML string, a dict, an ElementTree Element, or a list
mixing them.

### Hand-rolling

```python
from taklib.cot import event, detail_of, sub, to_bytes

evt = event("weird-1", "a-f-G", lat, lon, stale=300)
d = detail_of(evt)
sub(d, "contact", callsign="WEIRD")
sub(d, "mything", _text="body text", someattr="value")
payload = to_bytes(evt)
```

`sub()` takes the element text as `_text` so that every ordinary word —
including CoT's own `type`, `parent` and `text` attributes — stays usable as an
attribute name.

## Reading events

```python
from taklib import TAKListener, parse_cot

for evt in TAKListener("udp://0.0.0.0:6969"):
    evt["uid"], evt["callsign"], evt["lat"], evt["lon"], evt["type"]
    evt["remarks"], evt["team"], evt["speed"], evt["course"]
    if evt["is_chat"]:
        evt["message"], evt["sender_callsign"], evt["sender_uid"]
    evt["detail"]     # the raw <detail> Element, for anything not surfaced
```

`parse_cot(xml_bytes)` does the same for CoT you got some other way, returning
`None` if it isn't valid CoT.

## GeoChat, specifically

Chat is a normal event with a `<__chat>` block, and it's the easiest way for
code to talk to operators. Broadcast:

```python
cot.geochat("Three contacts north of the river",
            sender_uid="bot-1", sender_callsign="BOT")
```

Reply privately to whoever messaged you — pass their uid and callsign back:

```python
for evt in TAKListener(url):
    if evt["is_chat"] and "status" in evt["message"].lower():
        tak.send(cot.geochat("All quiet.",
                             sender_uid="bot-1", sender_callsign="BOT",
                             to_uid=evt["sender_uid"],
                             chatroom=evt["sender_callsign"]))
```

See `examples/03_geochat_bot.py` for a working loop.

## Colours

ARGB as a signed 32-bit int, which is an odd convention and easy to get wrong.
Use the helper:

```python
cot.argb(255, 255, 0, 0)     # opaque red
cot.RED, cot.GREEN, cot.BLUE, cot.YELLOW, cot.ORANGE, cot.CYAN, cot.MAGENTA
```

Team colours ATAK understands as `__group name`: White, Yellow, Orange,
Magenta, Red, Maroon, Purple, Dark Blue, Blue, Cyan, Teal, Green, Dark Green,
Brown.
