# Connection playbook

## Our path: UDP out to the venue's server

We build a CoT event and fire it at their IP and port as a UDP datagram.
No handshake, no certificates, no session.

```python
from taklib import TAKSender, cot

tak = TAKSender("udp://10.0.0.42:6969")
tak.send(cot.unit("alpha-01", -27.4705, 153.0260, callsign="ALPHA"))
```

Set it once for every tool in the repo:

```bash
export COT_URL=udp://10.0.0.42:6969     # bash
set COT_URL=udp://10.0.0.42:6969        # Windows cmd
$env:COT_URL="udp://10.0.0.42:6969"     # PowerShell
```

Precedence is `--url` flag > `$COT_URL` > `config.ini` > built-in default.

### What UDP means for us

| | |
|---|---|
| **No acknowledgement** | `send()` returning True means the datagram left the machine. Nothing more. |
| **No error on bad data** | Malformed XML vanishes silently. Validate locally. |
| **One event per datagram** | Never batch. Keep under ~1400 bytes to avoid fragmentation. |
| **Cheap to repeat** | Re-send position updates on an interval instead of trusting one send. |
| **No back-channel by default** | You only receive if they rebroadcast or you're on a multicast group. |

The practical upshot: **the only real confirmation is someone with ATAK open
saying they can see your marker.** Get that confirmation early — first hour —
and then trust the pipe.

### Event-morning check

```bash
python tak.py status udp://THEIR_IP:6969
```

Sends three probe datagrams, watches the port for anything coming back, and
tells you what it can and can't prove. Then ask someone on ATAK to confirm
they see `<YOUR_CALLSIGN>-PROBE`.

### Unicast vs multicast

```
udp://10.0.0.42:6969        unicast — straight at their server
udp://239.2.3.1:6969        multicast — the TAK mesh SA group
```

`239.2.3.1:6969` is the standard TAK mesh convention: every device on the same
LAN listening for mesh traffic sees it, **with no server at all**. That is our
fallback if the venue's server is down or misconfigured — two laptops and a
phone on the same wifi still gives us a working demo. `TAKSender` detects the
multicast range and sets the socket options automatically.

## Verifying locally before you blame the network

Because UDP tells you nothing, prove your events are well-formed on your own
machine first.

Terminal 1:
```bash
python tak.py listen --url udp://127.0.0.1:6969
```

Terminal 2:
```bash
COT_URL=udp://127.0.0.1:6969 python your_bridge.py
```

If it appears in terminal 1, your CoT is valid and your code works; anything
after that is addressing or network. This takes ten seconds and saves an hour.

For a visual version, point the dashboard at the same port:

```bash
python tak.py dashboard --url udp://0.0.0.0:6969   # http://127.0.0.1:8080
```

## If they turn out to want TCP or TLS

Everything in `taklib` works over TCP and TLS too — change the URL scheme and
nothing else in your code.

| Path | Port | Notes |
|---|---|---|
| UDP (ours) | often 6969 | Fire-and-forget. Mesh group is `239.2.3.1:6969` |
| TCP plain | 8087 | Streaming, connection-oriented, gives you a back-channel |
| TLS + client cert | 8089 | Production TAK Server; needs certs from a data package |
| Web UI / cert enrollment | 8443 / 8446 | Where clients pull data packages |

```bash
python tak.py status 10.0.0.42     # bare IP scans the TCP ports instead
```

### TLS, if it comes to that

TAK data packages ship a `.p12` bundle. Extract it:

```bash
openssl pkcs12 -in truststore.p12 -out client.pem -clcerts -nokeys
openssl pkcs12 -in truststore.p12 -out client.key -nocerts -nodes
```

Then in `config.ini`:

```ini
COT_URL = tls://10.0.0.42:8089
PYTAK_TLS_CLIENT_CERT = ./certs/client.pem
PYTAK_TLS_CLIENT_KEY  = ./certs/client.key
PYTAK_TLS_DONT_VERIFY = 1     ; self-signed only — say so out loud in the demo
```

`certs/` and `*.p12` are gitignored. Never commit credentials.

## TAK Protocol v1 (protobuf)

Some servers speak protobuf rather than XML. Frames start with byte `0xBF`:

```
stream framing:  0xBF <varint length> <protobuf payload>
mesh framing:    0xBF 0x01 0xBF <protobuf payload>
```

`taklib`'s listener detects these and decodes them if `takproto` is installed,
and logs a clear warning if it isn't. We send XML, which every TAK server
accepts, so this only matters for reading.

## Working with no venue server at all

The local router stands in for one, over TCP:

```bash
python tak.py serve                    # listens on 8087, fans out to all clients
python -m taklib.server --record session.cot     # capture everything
python -m taklib.server --replay session.cot --loop   # reproducible demos
```

`--replay` is worth knowing about: record a good run, then replay it if the
live data source dies during judging.
