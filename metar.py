# metar.py - the METAR data half of the METAR analog face
# (Nov 17, 2026, v28): fetch one station's current METAR
# from aviationweather.gov (the public API, no key), parse
# it into the handful of plain-language lines the face
# prints, and cache the last good record.
#
# The split is deliberate: this module knows nothing about
# drawing, and metarface.py knows nothing about the network.
# The face reads display_state() - (record, stale) - and a
# version counter that bumps whenever what it should draw
# changes (a new record, a different airport).
#
# TRANSPORT: the updater's proven raw-socket HTTPS GET
# (updater._https_get - urequests is not in the firmware).
# poll() is called from main.py's housekeeping, never from
# a compose path, and self-gates on a ~5-minute cadence of
# ATTEMPTS (a failed fetch waits the full cadence too - a
# sick network must not be hammered once per loop). The
# worst-case stall is one bounded GET, the same class as
# the updater's own hourly check.
#
# CATEGORY: the API's fltCat when it carries a valid one;
# otherwise computed from the ceiling (lowest BKN/OVC/VV
# base) and the visibility with the standard thresholds -
# LIFR: vis < 1 SM or ceiling < 500 ft; IFR: vis 1-<3 or
# ceiling 500-<1000; MVFR: vis 3-5 or ceiling 1000-3000;
# VFR beyond both. (Boundary cases follow the FAA bands:
# vis exactly 3 or 5 is MVFR, a 1,000 ft ceiling is MVFR,
# a 500 ft ceiling is IFR.)
#
# STALE: a record is stale when its observation is more
# than ~75 minutes old - but only once the clock's time is
# NTP-proven (timekeep.time_source() == "ntp"). Before
# that the clock's own epoch cannot be trusted, so nothing
# is ever flagged: a fresh boot on RTC time shows the data
# unflagged until NTP confirms the hour. The epoch math:
# the board's system clock holds LOCAL time (UTC-7) in the
# MicroPython 2000-01-01 epoch frame, so the Unix epoch is
# time.time() + 946684800 (2000->1970) + 25200 (local->UTC).
import json
import time

import updater

API_URL = ("https://aviationweather.gov/api/data/metar"
           "?ids=%s&format=json")
FETCH_MS = 5 * 60 * 1000        # ~5 minutes between attempts
STALE_S = 75 * 60               # obs older than this = STALE
MAX_BYTES = 32768               # one station's JSON is ~700 B

_CATS = ("VFR", "MVFR", "IFR", "LIFR")
_CEILING_COVERS = ("BKN", "OVC", "VV")

_airport = None       # normalised station id, or None
_record = None        # the last good parsed record (dict)
_version = 0          # bumps when the face should re-render
_last_try = None      # ticks_ms of the last fetch attempt
_due = True           # a fetch is owed (boot / airport change)


def _ticks():
    try:
        return time.ticks_ms()
    except AttributeError:      # the desk harness (CPython)
        return int(time.time() * 1000)


def _ticks_diff(a, b):
    try:
        return time.ticks_diff(a, b)
    except AttributeError:
        return a - b


# --- the airport config value ---

def normalise_airport(s):
    """'kflg ' -> 'KFLG'; a 3-4 character alphanumeric id or
    None. (No str.isalnum on MicroPython - the alphabet is
    spelled out.) admin.py validates with this same door, so
    the page and the fetcher can never disagree."""
    if not isinstance(s, str):
        return None
    s = s.strip().upper()
    if len(s) < 3 or len(s) > 4:
        return None
    for ch in s:
        if ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            return None
    return s


def set_airport(code):
    """Point the fetcher at a station. A real change drops
    the old station's record (its weather must never wear
    the new station's name) and owes an immediate fetch.
    Returns the normalised code, or None if rejected (the
    old station is kept)."""
    global _airport, _record, _version, _due
    norm = normalise_airport(code)
    if norm is None:
        return None
    if norm != _airport:
        _airport = norm
        _record = None
        _version += 1
        _due = True
    return norm


def airport():
    return _airport


def version():
    return _version


def record():
    return _record


# --- parsing (pure: dict in, display record out) ---

def _vis_value(v):
    """visib as statute miles (float), or None. The API
    gives a number (2, 10) or a string: '10+', '1/2',
    'M1/4' (M = less than), occasionally a mixed '1 1/2'."""
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().rstrip("+")
    if s.startswith("M"):
        s = s[1:]
    if not s:
        return None
    total = 0.0
    try:
        for part in s.split():
            if "/" in part:
                a, b = part.split("/", 1)
                total += float(a) / float(b)
            else:
                total += float(part)
    except (ValueError, ZeroDivisionError):
        return None
    return total


def _vis_text(v):
    """visib as printed: the API's own string verbatim
    ('10+', '1/2', 'M1/4' are honest METAR notation), a
    number trimmed, a bare fraction spelled as one."""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        f = float(v)
        if f == int(f):
            return str(int(f))
        for num, den in ((1, 4), (1, 2), (3, 4)):
            if abs(f - num / den) < 0.01:
                return "%d/%d" % (num, den)
        whole = int(f)
        frac = f - whole
        for num, den in ((1, 4), (1, 2), (3, 4)):
            if whole and abs(frac - num / den) < 0.01:
                return "%d %d/%d" % (whole, num, den)
        return str(f)
    return "?"


def _ceiling(m):
    """(cover, base_ft) of the ceiling - the lowest BKN,
    OVC or VV layer - or (None, None)."""
    cover = None
    base = None
    for c in m.get("clouds") or ():
        if c.get("cover") in _CEILING_COVERS \
                and c.get("base") is not None:
            if base is None or c["base"] < base:
                cover, base = c["cover"], c["base"]
    return cover, base


def flight_category(vis, ceil_ft):
    """The category from visibility (SM, float or None) and
    ceiling (ft, or None = no ceiling): the standard bands
    in the header. A missing input simply doesn't vote."""
    if (vis is not None and vis < 1) \
            or (ceil_ft is not None and ceil_ft < 500):
        return "LIFR"
    if (vis is not None and vis < 3) \
            or (ceil_ft is not None and ceil_ft < 1000):
        return "IFR"
    if (vis is not None and vis <= 5) \
            or (ceil_ft is not None and ceil_ft <= 3000):
        return "MVFR"
    return "VFR"


def _fmt_ft(n):
    """6500 -> '6,500' (MicroPython's str.format has no
    thousands grouping - group by hand)."""
    s = str(int(n))
    out = ""
    while len(s) > 3:
        out = "," + s[-3:] + out
        s = s[:-3]
    return s + out


def wind_line(m):
    """'Wind 270° at 8 G14 kt' - calm and VRB spelled out,
    the gust riding before the unit, as decoded METARs
    print it."""
    spd = m.get("wspd")
    if spd is None:
        return "Wind ---"
    if spd == 0:
        return "Wind calm"
    d = m.get("wdir")
    if isinstance(d, str):
        head = "Wind %s at %d" % (d, spd)        # "VRB"
    elif d is None:
        head = "Wind VRB at %d" % spd
    else:
        head = "Wind %03d° at %d" % (d, spd)
    gst = m.get("wgst")
    if gst:
        head += " G%d" % gst
    return head + " kt"


def cloud_line(m):
    """The ceiling when there is one ('Ceiling BKN 6,500
    ft'); otherwise the significant cover - Scattered
    outranks Few, the lower layer wins a tie - or
    'Sky clear'."""
    cover, base = _ceiling(m)
    if base is not None:
        return "Ceiling %s %s ft" % (cover, _fmt_ft(base))
    best = None
    for c in m.get("clouds") or ():
        cov = c.get("cover")
        if cov in ("SCT", "FEW") and c.get("base") is not None:
            key = (0 if cov == "SCT" else 1, c["base"])
            if best is None or key < best[0]:
                best = (key, cov, c["base"])
    if best is not None:
        word = "Scattered" if best[1] == "SCT" else "Few"
        return "%s %s" % (word, _fmt_ft(best[2]))
    return "Sky clear"


def parse_record(m, station):
    """One API object -> the face's display record:
    {station, cat, wind, vis, cloud, obs (Unix epoch),
    obs_z ('2323Z')}. Pure arithmetic for the Zulu time -
    no gmtime, so the desk and the board agree exactly."""
    _cov, ceil_ft = _ceiling(m)
    cat = m.get("fltCat")
    if cat not in _CATS:
        cat = flight_category(_vis_value(m.get("visib")),
                              ceil_ft)
    obs = m.get("obsTime")
    if not isinstance(obs, (int, float)):
        obs = 0
    obs = int(obs)
    return {
        "station": m.get("icaoId") or station,
        "cat": cat,
        "wind": wind_line(m),
        "vis": "Vis %s SM" % _vis_text(m.get("visib")),
        "cloud": cloud_line(m),
        "obs": obs,
        "obs_z": "%02d%02dZ" % ((obs // 3600) % 24,
                                (obs // 60) % 60),
    }


# --- staleness ---

def is_stale(rec, now_unix, ntp_synced):
    """Pure: an observation is stale past STALE_S - and
    only when the clock's time is NTP-proven (see the
    header). A future obs (clock still wrong) is never
    stale."""
    if rec is None or not ntp_synced:
        return False
    age = now_unix - rec["obs"]
    return 0 <= age and age > STALE_S


def _now_unix():
    """The current Unix epoch from the board's clock (see
    the header for the frame conversion)."""
    return int(time.time()) + 946684800 + 25200


def _ntp_synced():
    try:
        import timekeep
        return timekeep.time_source() == "ntp"
    except Exception:
        return False


def stale(now_unix=None):
    """The board-facing stale flag for the cached record."""
    if _record is None:
        return False
    if now_unix is None:
        now_unix = _now_unix()
    return is_stale(_record, now_unix, _ntp_synced())


def display_state():
    """(record, stale) - what metarface draws by."""
    return _record, stale()


# --- the fetch ---

def poll(force=False):
    """Fetch if a fetch is owed or the cadence has elapsed.
    Called from main.py's housekeeping (and once at boot /
    on an airport change with force=True). Returns True if
    a new record landed. Fail-soft: any trouble keeps the
    last good record and waits for the next cadence."""
    global _record, _version, _last_try, _due
    if _airport is None:
        return False
    now = _ticks()
    if not force and not _due and _last_try is not None \
            and _ticks_diff(now, _last_try) < FETCH_MS:
        return False
    _last_try = now
    _due = False
    try:
        data = updater._https_get(API_URL % _airport,
                                  MAX_BYTES)
    except Exception as exc:
        print("metar: fetch failed:", exc)
        return False
    if not data:
        print("metar: no data for", _airport)
        return False
    try:
        arr = json.loads(data)
    except Exception as exc:
        print("metar: bad JSON:", exc)
        return False
    if isinstance(arr, dict):
        arr = [arr]
    best = None
    for m in arr or ():
        if isinstance(m, dict) and m.get("obsTime") is not None:
            if best is None or m["obsTime"] > best["obsTime"]:
                best = m
    if best is None:
        print("metar: empty response for", _airport)
        return False
    rec = parse_record(best, _airport)
    if rec != _record:
        _record = rec
        _version += 1
        print("metar: %s %s - %s, %s, %s (%s)"
              % (rec["station"], rec["cat"], rec["wind"],
                 rec["vis"], rec["cloud"], rec["obs_z"]))
    return True
