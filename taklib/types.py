"""CoT type codes, and helpers for building them.

A CoT `type` is a hierarchical dotted-by-hyphen string. The two you care about
most are the atom prefix `a-<affiliation>-<domain>-...` (things that exist in
the world) and the bits prefix `b-...` (reports, chat, drawings, alerts).

Rather than memorising codes at 2am, use `atom()` or pull one off the tables.
"""

# --- affiliation (the 2nd character of an `a-` type) ------------------------
FRIENDLY = "f"
HOSTILE = "h"
NEUTRAL = "n"
UNKNOWN = "u"
PENDING = "p"
ASSUMED_FRIEND = "a"
SUSPECT = "s"
JOKER = "j"
FAKER = "k"

AFFILIATIONS = {
    "friendly": FRIENDLY,
    "hostile": HOSTILE,
    "neutral": NEUTRAL,
    "unknown": UNKNOWN,
    "pending": PENDING,
    "assumed": ASSUMED_FRIEND,
    "suspect": SUSPECT,
}

# --- battle dimension / domain (the 3rd character) -------------------------
GROUND = "G"
AIR = "A"
SEA_SURFACE = "S"
SUBSURFACE = "U"
SPACE = "P"

DOMAINS = {
    "ground": GROUND,
    "air": AIR,
    "sea": SEA_SURFACE,
    "surface": SEA_SURFACE,
    "subsurface": SUBSURFACE,
    "space": SPACE,
}

# --- the codes you will actually type --------------------------------------
FRIENDLY_UNIT = "a-f-G-U-C"       # friendly ground combat unit — the default dot
FRIENDLY_GROUND = "a-f-G"
HOSTILE_GROUND = "a-h-G"
NEUTRAL_GROUND = "a-n-G"
UNKNOWN_GROUND = "a-u-G"
FRIENDLY_AIR = "a-f-A"
HOSTILE_AIR = "a-h-A"
UNKNOWN_AIR = "a-u-A"
FRIENDLY_SEA = "a-f-S"
HOSTILE_SEA = "a-h-S"
UNKNOWN_SEA = "a-u-S"

# vehicles / platforms worth knowing
FRIENDLY_UAV = "a-f-A-M-F-Q"      # friendly drone / UAV
HOSTILE_UAV = "a-h-A-M-F-Q"
FRIENDLY_VEHICLE = "a-f-G-E-V"
FRIENDLY_AIRCRAFT = "a-f-A-C-F"
FRIENDLY_HELO = "a-f-A-M-H"
SENSOR = "a-f-G-E-S"

# bits: markers, reports, drawings, chat
WAYPOINT = "b-m-p-s-p-loc"        # generic map marker / point of interest
WAYPOINT_GENERIC = "b-m-p-w"      # route waypoint
SPI = "b-m-p-s-p-i"               # sensor point of interest
ROUTE = "b-m-r"
GEOCHAT = "b-t-f"
CASEVAC = "b-r-f-h-c"             # medevac / 9-line
EMERGENCY = "b-a-o-tbl"           # 911 / troops-in-contact alert
EMERGENCY_RING = "b-a-o-pan"      # ring the bell
EMERGENCY_CANCEL = "b-a-o-can"    # cancel an emergency
DETECTION_ALARM = "b-d"           # generic detection / sensor report
BITS_IMAGE = "b-i-x-i"            # image / imagery report

# drawing shapes
SHAPE_POLYGON = "u-d-f"           # freeform shape / polygon / geofence
SHAPE_CIRCLE = "u-d-c-c"          # circle
SHAPE_LINE = "u-d-f"              # a polyline is an unclosed u-d-f
SHAPE_RECTANGLE = "u-d-r"

# --- how (data origin) ------------------------------------------------------
HOW_GPS = "m-g"                   # machine, GPS derived
HOW_MACHINE_ESTIMATED = "m-e"     # machine, estimated / calculated
HOW_HUMAN_GIGO = "h-g-i-g-o"      # human, entered (chat, hand-placed markers)
HOW_HUMAN_ENTERED = "h-e"
HOW_TRANSCRIBED = "h-t"

# --- team colours ATAK understands -----------------------------------------
TEAM_COLOURS = [
    "White", "Yellow", "Orange", "Magenta", "Red", "Maroon", "Purple",
    "Dark Blue", "Blue", "Cyan", "Teal", "Green", "Dark Green", "Brown",
]

TEAM_ROLES = [
    "Team Member", "Team Lead", "HQ", "Sniper", "Medic",
    "Forward Observer", "RTO", "K9",
]


def atom(affiliation: str = "unknown", domain: str = "ground", *suffix: str) -> str:
    """Build an `a-` atom type from readable words.

    >>> atom("hostile", "air")
    'a-h-A'
    >>> atom("friendly", "ground", "U", "C")
    'a-f-G-U-C'
    """
    aff = AFFILIATIONS.get(affiliation.lower(), affiliation)
    dom = DOMAINS.get(domain.lower(), domain)
    parts = ["a", aff, dom, *suffix]
    return "-".join(p for p in parts if p)


def with_affiliation(cot_type: str, affiliation: str) -> str:
    """Re-colour an existing atom type. Handy when confidence changes.

    >>> with_affiliation("a-u-G", "hostile")
    'a-h-G'
    """
    parts = cot_type.split("-")
    if len(parts) < 2 or parts[0] != "a":
        return cot_type
    parts[1] = AFFILIATIONS.get(affiliation.lower(), affiliation)
    return "-".join(parts)


def describe(cot_type: str) -> str:
    """Best-effort human label for a type code — for dashboards and logs."""
    known = {
        FRIENDLY_UNIT: "Friendly ground unit",
        FRIENDLY_GROUND: "Friendly ground",
        HOSTILE_GROUND: "Hostile ground",
        NEUTRAL_GROUND: "Neutral ground",
        UNKNOWN_GROUND: "Unknown ground",
        FRIENDLY_AIR: "Friendly air",
        HOSTILE_AIR: "Hostile air",
        UNKNOWN_AIR: "Unknown air",
        FRIENDLY_UAV: "Friendly UAV",
        HOSTILE_UAV: "Hostile UAV",
        WAYPOINT: "Waypoint",
        SPI: "Sensor point of interest",
        ROUTE: "Route",
        GEOCHAT: "GeoChat message",
        CASEVAC: "CASEVAC request",
        EMERGENCY: "Emergency alert",
        SHAPE_POLYGON: "Shape / polygon",
        SHAPE_CIRCLE: "Circle",
    }
    if cot_type in known:
        return known[cot_type]

    parts = cot_type.split("-")
    if parts[0] == "a" and len(parts) >= 3:
        aff = {v: k for k, v in AFFILIATIONS.items()}.get(parts[1], parts[1])
        dom = {v: k for k, v in DOMAINS.items()}.get(parts[2], parts[2])
        return f"{aff.title()} {dom}"
    if parts[0] == "b":
        return "Report / bits"
    if parts[0] == "u":
        return "Drawing"
    return cot_type
