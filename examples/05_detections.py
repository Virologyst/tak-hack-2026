"""Model output -> contacts on the map, with confidence.

The pattern for anything that *infers* rather than *measures*: a vision model,
a classifier, an anomaly detector, a fusion algorithm.

    python examples/05_detections.py --url udp://10.0.0.42:6969

Two things make this read as competent rather than a toy:

1. **Confidence drives affiliation.** A low-confidence contact is `unknown`
   (yellow), not `hostile` (red). Claiming certainty you don't have is the
   fastest way to lose a judge who knows the domain.
2. **Detections expire.** A contact you saw once, ten minutes ago, should not
   still be sitting on the map as though it were live. That's what `stale` is
   for.
"""

import _path  # noqa: F401  (lets this run without installing the package)
import argparse
import math
import time

from taklib import TAKSender, cot
from taklib import types as t
from taklib.config import resolve_url

UID_PREFIX = "det"

# Below this, we won't put it on the map at all.
MIN_CONFIDENCE = 0.35
# Above this, we're willing to call it what the model called it.
HIGH_CONFIDENCE = 0.75


def detect():
    """STUB — replace with your real model.

    Return dicts with at least id, lat, lon, label, confidence.

    Real version might look like:
        results = model(frame)
        return [{"id": f"{cls}-{i}", "lat": ..., "lon": ...,
                 "label": cls, "confidence": float(conf)}
                for i, (cls, conf, box) in enumerate(results)]

    Turning pixel coordinates into lat/lon needs the camera's position,
    heading and field of view — do that maths in here, not on the map.
    """
    now = time.time()
    wobble = math.sin(now / 5) * 0.001
    return [
        {"id": "vehicle-1", "lat": -27.4705 + wobble, "lon": 153.0260,
         "label": "vehicle", "confidence": 0.91},
        {"id": "person-3", "lat": -27.4730, "lon": 153.0290 + wobble,
         "label": "person", "confidence": 0.62},
        {"id": "unknown-7", "lat": -27.4760, "lon": 153.0230,
         "label": "unclassified", "confidence": 0.28},
    ]


def affiliation_for(confidence: float, label: str) -> str:
    """Let confidence choose the symbol, not wishful thinking.

    Note what this deliberately never returns: hostile. A detector saw a shape
    it thinks is a truck — that is not the same as knowing whose truck it is.
    Calling contacts hostile automatically is how you lose a judge who knows
    the domain. Escalating to hostile is a human's decision, and if the problem
    statement wants that, wire it to an explicit operator action.
    """
    if confidence < HIGH_CONFIDENCE:
        return t.atom("pending", "ground")   # a-p-G: something's there, unsure what
    return t.UNKNOWN_GROUND                  # a-u-G: confident it's a thing, not whose


def accuracy_for(confidence: float) -> float:
    """Lower confidence -> bigger error ring. ATAK draws this, and it reads well."""
    return max(15.0, 200.0 * (1.0 - confidence))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="udp://IP:PORT (else $COT_URL, else config.ini)")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--source", default="demo-model")
    args = ap.parse_args()

    url = resolve_url(args.url)
    print(f"detections -> {url}  (Ctrl-C to stop)\n")

    with TAKSender(url) as tak:
        while True:
            published = 0
            for d in detect():
                conf = float(d["confidence"])
                if conf < MIN_CONFIDENCE:
                    continue           # too weak to be worth anyone's attention

                tak.send(cot.detection(
                    uid=f"{UID_PREFIX}-{d['id']}",
                    lat=float(d["lat"]), lon=float(d["lon"]),
                    label=d["label"],
                    confidence=conf,
                    source=args.source,
                    cot_type=affiliation_for(conf, d["label"]),
                    ce=accuracy_for(conf),
                    # Short stale: if the model stops seeing it, it leaves the map.
                    stale=30,
                ))
                published += 1
                print(f"  {d['label']:<14} {conf:.0%}  "
                      f"{d['lat']:.5f},{d['lon']:.5f}  "
                      f"+/-{accuracy_for(conf):.0f}m")

            print(f"  -> {published} detections published\n")
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
