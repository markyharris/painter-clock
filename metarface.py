# metarface.py - the METAR analog face (Nov 17, 2026,
# v28): the classic analog's geometry wearing the
# configured airport's flight category as its dial field.
# Mark's pitch, approved as drawn: "if KFLG was VFR the
# background color would be Green, with 'VFR' and minimal
# decoded info, such as winds, vis, cloud cover with the
# arms in the foreground."
#
# THE FIELD: the LiveSectional category colours, deepened
# to 80% so the dial reads as a clock face, not an alarm
# light (the shade ring deepens again, to 64%):
#   VFR  base (44,160,44)   field (35,128,35)
#   MVFR base (36,86,214)   field (28,68,171)
#   IFR  base (214,39,40)   field (171,31,32)
#   LIFR base (224,51,208)  field (179,40,166)
#   none base (128,128,128) field (102,102,102) - NO DATA
# Ticks in cream; the header ("KFLG - VFR", the metar_h
# strike) and the three decoded lines + obs time (metar_t)
# in cream, lettered onto the static layer with
# smoothfont.draw - the boot screens' door, paid once per
# data change, never per frame. The header's dash is a
# hyphen: an em dash (U+2014) cannot ride the font blob's
# one-byte glyph codes, and the hyphen reads the same at
# arm's length.
#
# THE HANDS are the foreground, as pitched: the classic's
# creeping hour/minute and a slim second hand, each drawn
# twice - a wider pass in the painter's INK under a cream
# pass - so the hand carries a dark edge and stays legible
# on green, blue, red and magenta alike. The classic's rust
# second hand is NOT carried over: rust on the IFR red
# field would vanish, and on LIFR it would fight. The
# second hand here is cream with the same ink edge;
# the boss is ink with a cream heart.
#
# THE STATIC LAYER is data, not just geometry: it is
# re-rendered in place whenever the display snapshot
# changes - (metar.version(), stale, airport) - which is
# at most a fetch cadence (5 min), a stale flip, or an
# airport change. Steady-state compose is the classic's
# cost class: a canvas copy, the date's slice copies, and
# the hands (each two band-split polys + dots).
#
# SLEEP: no saturated field floods a dark room. The night
# layer is the shared night dial with the category demoted
# to a thin ring in the shade band (full base colour - a
# ring, not a flood), pale hands stepping by the minute,
# no second hand, the header and decoded lines in a dim
# pale. Day returns with the morning.
#
# Frost and Backlight stay painter-only (no set_backlight
# here); cuckoo and idle routines never reach this face
# (main drops Try-it presses off the painter). The date
# shows, gated by show_date, drawn by clockface.draw_date
# with the field colour as its ground - the box sits on
# flat field, clear of the ticks, so the opaque strip is
# pixel-exact as on the painter.
import math

import clockface
import classicface
import metar
import smoothfont

NAME = "metar"
TICK_SECONDS = True

CX = clockface.CX
CY = clockface.CY
DIAL_R = clockface.DIAL_R

CREAM = clockface.CREAM
CREAM_SHADE = clockface.CREAM_SHADE
RIM = clockface.RIM
INK = clockface.INK
PALE = clockface.PALE
NIGHT_GROUND = clockface.NIGHT_GROUND
NIGHT_SHADE = clockface.NIGHT_SHADE
NIGHT_RIM = clockface.NIGHT_RIM
NIGHT_TICK = clockface.NIGHT_TICK

# The night text tone: pale, dimmed - lamplight paper at
# half strength against the deep ground.
DIM = clockface.rgb565(148, 154, 168)

# Category colours (see the header): the LiveSectional
# base set, the field at 80%, the shade ring at 64%.
BASE_888 = {
    "VFR": (44, 160, 44),
    "MVFR": (36, 86, 214),
    "IFR": (214, 39, 40),
    "LIFR": (224, 51, 208),
    None: (128, 128, 128),
}

HOUR_LEN = classicface.HOUR_LEN
MIN_LEN = classicface.MIN_LEN
SEC_LEN = classicface.SEC_LEN
HOUR_W = classicface.HOUR_W
MIN_W = classicface.MIN_W
TAIL = classicface.TAIL
EDGE = 5            # the ink edge's extra width per hand

# Text layout (cap-top rows; desk-verified in test_metar:
# every line's ink stays inside r=230 of centre).
HDR_Y = 150         # "KFLG - VFR" (metar_h, Bold 46)
L1_Y = 312          # wind      (metar_t, Regular 30)
L2_Y = 348          # visibility
L3_Y = 384          # clouds
OBS_Y = 424         # "2323Z" (+ " STALE")

_show_date = True        # admin "show_date" key; main.py drives


def set_show_date(on):
    """The face-contract date convention: main.py drives
    it; compose() honours it from the next frame."""
    global _show_date
    _show_date = bool(on)


def show_date():
    return _show_date


# --- colours ---

def _scaled(rgb, f):
    return clockface.rgb565(int(rgb[0] * f), int(rgb[1] * f),
                            int(rgb[2] * f))


def base_colour(cat):
    """The full-strength category colour (the night ring)."""
    return _scaled(BASE_888.get(cat, BASE_888[None]), 1.0)


def field_colour(cat):
    """The day dial's field: the base colour at 80%."""
    return _scaled(BASE_888.get(cat, BASE_888[None]), 0.8)


def shade_colour(cat):
    """The day dial's shade ring: the base colour at 64%."""
    return _scaled(BASE_888.get(cat, BASE_888[None]), 0.64)


# --- the dial geometry (the classic's, recoloured) ---

def _ticks():
    r1 = DIAL_R - 8
    out = []
    i = 0
    while i < 60:
        ang = i * 6
        if i % 15 == 0:
            r0, w = DIAL_R - 30, 5
        elif i % 5 == 0:
            r0, w = DIAL_R - 23, 3
        else:
            r0, w = DIAL_R - 16, 2
        out.append(classicface._tick_coords(ang, r0, r1, w))
        i += 1
    return out


def _header(rec):
    station = metar.airport()
    if station is None:
        station = rec["station"] if rec else "METAR"
    cat = rec["cat"] if rec else "NO DATA"
    return "%s - %s" % (station, cat)


def _lines(rec, stale_flag):
    """The text lines under the header: (text, cap_y) -
    the three decoded lines and the obs time, or the
    single waiting line before the first record."""
    if rec is None:
        return (("No report received", L2_Y),)
    obs = rec["obs_z"] + (" STALE" if stale_flag else "")
    return ((rec["wind"], L1_Y), (rec["vis"], L2_Y),
            (rec["cloud"], L3_Y), (obs, OBS_Y))


def _draw_day(fb, rec, stale_flag):
    """The DAY static layer: category field, cream ticks,
    the header and decoded lines lettered on in cream."""
    cat = rec["cat"] if rec else None
    field = field_colour(cat)
    shade = shade_colour(cat)
    for win, y0 in fb.band_windows():
        win.fill(RIM)
        win.ellipse(CX, CY - y0, DIAL_R + 6, DIAL_R + 6,
                    shade, True)
        win.ellipse(CX, CY - y0, DIAL_R, DIAL_R, field, True)
    for win, y0 in fb.band_windows():
        for coords in _ticks():
            win.poly(0, -y0, coords, CREAM, True)
    smoothfont.draw(fb, _header(rec), CX, HDR_Y, "metar_h",
                    CREAM)
    for text, y in _lines(rec, stale_flag):
        smoothfont.draw(fb, text, CX, y, "metar_t", CREAM)
    return fb


def _draw_night(fb, rec, stale_flag):
    """The NIGHT static layer: the shared night dial, the
    category as a thin ring in the shade band at full base
    strength, the lettering dimmed pale."""
    cat = rec["cat"] if rec else None
    ring = base_colour(cat)
    for win, y0 in fb.band_windows():
        win.fill(NIGHT_RIM)
        win.ellipse(CX, CY - y0, DIAL_R + 6, DIAL_R + 6,
                    NIGHT_SHADE, True)
        win.ellipse(CX, CY - y0, DIAL_R + 4, DIAL_R + 4,
                    ring, True)
        win.ellipse(CX, CY - y0, DIAL_R + 1, DIAL_R + 1,
                    NIGHT_SHADE, True)
        win.ellipse(CX, CY - y0, DIAL_R, DIAL_R,
                    NIGHT_GROUND, True)
    for win, y0 in fb.band_windows():
        for coords in _ticks():
            win.poly(0, -y0, coords, NIGHT_TICK, True)
    smoothfont.draw(fb, _header(rec), CX, HDR_Y, "metar_h",
                    PALE)
    for text, y in _lines(rec, stale_flag):
        smoothfont.draw(fb, text, CX, y, "metar_t", DIM)
    return fb


# --- hands ---

def _edged_hand(fb, ang, length, base_w, tail):
    """One hand, twice: the ink edge pass, then the cream
    face - the foreground treatment from the header."""
    classicface._draw_hand(fb, ang, length, base_w + EDGE,
                           tail, INK)
    classicface._draw_hand(fb, ang, length, base_w, tail,
                           CREAM)


def _hands_day(fb, time_tuple):
    hour_ang = ((time_tuple[3] % 12)
                + time_tuple[4] / 60.0) * 30.0
    _edged_hand(fb, hour_ang, HOUR_LEN, HOUR_W, TAIL)
    min_ang = (time_tuple[4] + time_tuple[5] / 60.0) * 6.0
    _edged_hand(fb, min_ang, MIN_LEN, MIN_W, TAIL)
    sec_ang = time_tuple[5] * 6.0
    _edged_hand(fb, sec_ang, SEC_LEN, 4, TAIL + 10)
    a = math.radians(sec_ang)
    tx = CX - math.sin(a) * (TAIL + 10)
    ty = CY + math.cos(a) * (TAIL + 10)
    classicface._dot(fb, tx, ty, 7, INK)
    classicface._dot(fb, tx, ty, 4, CREAM)
    classicface._dot(fb, CX, CY, 11, INK)
    classicface._dot(fb, CX, CY, 5, CREAM)


def _hands_night(fb, time_tuple):
    """Pale hour and minute, minute-stepped, no second
    hand - the classic's night treatment, unchanged."""
    hour_ang = ((time_tuple[3] % 12)
                + time_tuple[4] / 60.0) * 30.0
    classicface._draw_hand(fb, hour_ang, HOUR_LEN, HOUR_W,
                           TAIL, PALE)
    classicface._draw_hand(fb, time_tuple[4] * 6.0, MIN_LEN,
                           MIN_W, TAIL, PALE)
    classicface._dot(fb, CX, CY, 9, PALE)


# --- the face-module API (contract in clockface's header) ---

_static = None        # the canvas render_static() last drew into
_night_static = None  # the canvas render_night() last drew into
_day_key = None       # the snapshot the day layer now wears
_night_key = None     # the snapshot the night layer now wears


def _key():
    """The display snapshot's identity: a new record, a
    stale flip or an airport change all move it, and a
    moved key is what re-renders a static layer."""
    return (metar.version(), metar.stale(), metar.airport())


def render_static(canvas):
    """Draw the DAY static layer into canvas
    (display.dial()); remembered for compose()."""
    global _static, _day_key
    rec, stale_flag = metar.display_state()
    _draw_day(canvas, rec, stale_flag)
    _static = canvas
    _day_key = _key()
    return canvas


def render_night(canvas):
    """Draw the NIGHT static layer into canvas
    (display.night_dial()) - the sleep treatment's dial.
    The day layer is never touched."""
    global _night_static, _night_key
    rec, stale_flag = metar.display_state()
    _draw_night(canvas, rec, stale_flag)
    _night_static = canvas
    _night_key = _key()
    return canvas


def compose(canvas, time_tuple, state=None):
    """One frame of the METAR face at time_tuple: the
    static layer for the current snapshot copied in (and
    re-rendered in place first if the snapshot moved -
    a landed fetch, a stale flip, an airport change),
    the date, then the hands in the foreground. state
    follows the painter's convention: {"night": True,
    "dial": canvas} for a sleep frame."""
    global _static, _night_static, _day_key, _night_key
    if state is None:
        state = {}
    night = state.get("night", False)
    rec, stale_flag = metar.display_state()
    key = _key()
    if night:
        src = state.get("dial", _night_static)
        if src is not None and key != _night_key:
            _draw_night(src, rec, stale_flag)
            _night_static = src
            _night_key = key
        if src is not None and src is not canvas:
            canvas.copy_from(src)
        elif src is None:
            _draw_night(canvas, rec, stale_flag)
    else:
        src = _static
        if src is not None and key != _day_key:
            _draw_day(src, rec, stale_flag)
            _day_key = key
        if src is not None and src is not canvas:
            canvas.copy_from(src)
        elif src is None:
            _draw_day(canvas, rec, stale_flag)
    if _show_date:
        if night:
            clockface.draw_date(canvas, time_tuple, PALE,
                                NIGHT_GROUND)
        else:
            cat = rec["cat"] if rec else None
            clockface.draw_date(canvas, time_tuple, CREAM,
                                field_colour(cat))
    if night:
        _hands_night(canvas, time_tuple)
    else:
        _hands_day(canvas, time_tuple)
    return canvas
