"""Small geospatial helpers — pure stdlib, WGS84, metres.

Enough to answer the questions that come up in a TAK hack: how far apart are
these two things, what bearing, give me a point N metres that way, is this
inside the area of interest, draw me a circle.
"""

import math
from typing import Iterable, List, Sequence, Tuple

EARTH_RADIUS_M = 6371008.8  # mean radius

LatLon = Tuple[float, float]


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing in degrees true (0-360) from point 1 to point 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def destination(lat: float, lon: float, bearing_deg: float, distance_m: float) -> LatLon:
    """Point reached by travelling `distance_m` along `bearing_deg` from a start."""
    d = distance_m / EARTH_RADIUS_M
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> LatLon:
    """Half-way point along the great circle."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    l1 = math.radians(lon1)
    dl = math.radians(lon2 - lon1)
    bx = math.cos(p2) * math.cos(dl)
    by = math.cos(p2) * math.sin(dl)
    p3 = math.atan2(
        math.sin(p1) + math.sin(p2),
        math.sqrt((math.cos(p1) + bx) ** 2 + by ** 2),
    )
    l3 = l1 + math.atan2(by, math.cos(p1) + bx)
    return math.degrees(p3), (math.degrees(l3) + 540) % 360 - 180


def bbox(lat: float, lon: float, radius_m: float) -> Tuple[float, float, float, float]:
    """Bounding box (min_lat, min_lon, max_lat, max_lon) around a point."""
    dlat = math.degrees(radius_m / EARTH_RADIUS_M)
    dlon = math.degrees(radius_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)) or 1e-9))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def circle_points(lat: float, lon: float, radius_m: float, segments: int = 36) -> List[LatLon]:
    """Vertices approximating a circle — feed straight into `cot.polygon()`."""
    return [destination(lat, lon, i * 360 / segments, radius_m) for i in range(segments)]


def point_in_polygon(lat: float, lon: float, poly: Sequence[LatLon]) -> bool:
    """Ray-casting point-in-polygon. Good enough at hackathon scales.

    `poly` is a sequence of (lat, lon). Open or closed rings both work.
    """
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat):
            x_at = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_at:
                inside = not inside
        j = i
    return inside


def centroid(points: Iterable[LatLon]) -> LatLon:
    """Average position of a cloud of points (fine away from the antimeridian)."""
    pts = list(points)
    if not pts:
        raise ValueError("centroid() needs at least one point")
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def nearest(lat: float, lon: float, candidates: Iterable[dict],
            lat_key: str = "lat", lon_key: str = "lon"):
    """Closest item from an iterable of dicts. Returns (item, distance_m) or (None, inf).

    Built for the classic GeoChat question: "what's my nearest asset?"
    """
    best, best_d = None, float("inf")
    for c in candidates:
        try:
            d = haversine(lat, lon, float(c[lat_key]), float(c[lon_key]))
        except (KeyError, TypeError, ValueError):
            continue
        if d < best_d:
            best, best_d = c, d
    return best, best_d


def format_distance(metres: float) -> str:
    """Human string for logs and chat replies."""
    if metres < 1000:
        return f"{metres:.0f} m"
    return f"{metres / 1000:.2f} km"


def parse_latlon(text: str) -> LatLon:
    """Parse "lat,lon" / "lat lon" / "lat, lon, hae" into (lat, lon)."""
    parts = [p for p in text.replace(",", " ").split() if p]
    if len(parts) < 2:
        raise ValueError(f"cannot parse a lat/lon from {text!r}")
    return float(parts[0]), float(parts[1])
