# digitalface.py - the DIGITAL face (Nov 17, 2026, v26):
# the time as big painted numerals on the clock's own
# ground - the same cream field and rim as the dial, the
# same ink, the date line shared with every face. No
# figure, no ticks: a clean field, HH:MM as the hero at
# the biggest clean scale the disc takes, and a sub-line
# with the seconds and the AM/PM marker (the project's
# 12-hour convention, like the painter's dial).
#
# FACE MODULE CONTRACT (clockface.py header): render_static
# draws the static layer once into display.dial(); compose
# copies it into the frame canvas and draws what moves.
# Extras, same conventions as the painter: set_show_date
# (the date is clockface.draw_date itself - identical on
# all three faces) and render_night(canvas).
#
# TICK_SECONDS: main.py reads this flag - while awake the
# face wants a fresh frame every second for the seconds in
# the sub-line. In the sleep window main drops to the
# minute and the night compose drops the seconds with it:
# PALE hero and date on the night ground, the AM/PM alone
# in the sub-line, nothing moving - the standing rule's
# night treatment, snapping each minute.
#
# Frost and Backlight are painter-face effects: no
# set_backlight setter here, so main's convention leaves
# them off this face.
#
# TEXT: the glyphs are clockface.text_strip's 8x8 font,
# scaled - but NOT its cache. That cache is keyed per
# string forever, which suits a date (one string a day);
# a digital face mints a new hero string every minute and
# a new sub-line every second, and an unbounded cache of
# 77 KB hero strips would eat the PSRAM in a day. This
# module keeps its own strip builder (the same scratch-
# FrameBuffer construction) behind a small bounded cache:
# at most _CACHE_MAX strips, cleared whole when it fills -
# a rebuild is ~1,500 slice writes, once a minute at most
# for the hero, and the seconds line is small.
#
# Drawing discipline: the static field is C framebuf
# primitives through band windows; compose is slice copies
# only (the static copy, the date's 24 rows, the strips'
# rows) - zero framebuf prims, zero per-byte writes.
import framebuf

import clockface

NAME = "digital"
TICK_SECONDS = True

CX = clockface.CX
CY = clockface.CY
DIAL_R = clockface.DIAL_R

# The painter's palette, shared by reference.
CREAM = clockface.CREAM
CREAM_SHADE = clockface.CREAM_SHADE
RIM = clockface.RIM
INK = clockface.INK
PALE = clockface.PALE
NIGHT_GROUND = clockface.NIGHT_GROUND
NIGHT_SHADE = clockface.NIGHT_SHADE
NIGHT_RIM = clockface.NIGHT_RIM

# The layout: glyph boxes, centred on CX. The hero at
# scale 11 is 88 px tall and at most 440 px wide ("12:59")
# - its corners sit at r ~230, inside the 233 ground disc,
# and the strip's ground IS the field colour, so the box
# is invisible against the field. The sub-line at scale 5
# ("%02d PM", 240x40) rides below it.
HERO_SCALE = 11
HERO_Y = 172
SUB_SCALE = 5
SUB_Y = 292
AMPMS_SCALE = 4        # the night sub-line: the marker alone
AMPM_Y = 300

_show_date = True        # admin "show_date" key; main.py drives


def set_show_date(on):
    """The face-contract date convention (see classicface /
    clockface): main.py drives it; compose() honours it."""
    global _show_date
    _show_date = bool(on)


def show_date():
    return _show_date


# --- text strips (bounded cache - see the header) ---

_CACHE_MAX = 8
_strips = {}


def _pat(colour):
    return bytes((colour & 0xFF, (colour >> 8) & 0xFF))


def _strip(s, colour, ground, scale):
    """A string as an opaque strip (bytes, width, height) -
    clockface.text_strip's construction (8x8 font drawn
    once into a small scratch FrameBuffer, each set pixel
    grown to a scale-square by slice writes), behind this
    module's bounded cache."""
    key = (s, colour, ground, scale)
    hit = _strips.get(key)
    if hit is not None:
        return hit
    if len(_strips) >= _CACHE_MAX:
        _strips.clear()
    w1 = len(s) * 8
    sfb = framebuf.FrameBuffer(bytearray(w1 * 16), w1, 8,
                               framebuf.RGB565)
    sfb.fill(ground)
    sfb.text(s, 0, 0, colour)
    w = w1 * scale
    h = 8 * scale
    strip = bytearray(_pat(ground) * (w * h))
    ink = _pat(colour) * scale
    for sy in range(8):
        for sx in range(w1):
            if sfb.pixel(sx, sy) == colour:
                for dy in range(scale):
                    do = ((sy * scale + dy) * w
                          + sx * scale) * 2
                    strip[do:do + scale * 2] = ink
    _strips[key] = (bytes(strip), w, h)
    return _strips[key]


def _centred(canvas, s, colour, ground, scale, y):
    """Blit one strip centred on CX at rows y..y+h-1: row
    slice copies into the frame buffer, the draw_date
    pattern."""
    strip, w, h = _strip(s, colour, ground, scale)
    x = CX - w // 2
    buf = canvas.buf
    row = w * 2
    for r in range(h):
        do = ((y + r) * 480 + x) * 2
        buf[do:do + row] = strip[r * row:(r + 1) * row]
    return w


# --- the field (static layer) ---

def draw_field(fb, night=False):
    """The static layer: the dial's rim, shade ring and
    ground disc with NO ticks - a clean field for the
    numerals, in the day or night palette."""
    if night:
        rim, shade, ground = NIGHT_RIM, NIGHT_SHADE, NIGHT_GROUND
    else:
        rim, shade, ground = RIM, CREAM_SHADE, CREAM
    for win, y0 in fb.band_windows():
        win.fill(rim)
        win.ellipse(CX, CY - y0, DIAL_R + 6, DIAL_R + 6,
                    shade, True)
        win.ellipse(CX, CY - y0, DIAL_R, DIAL_R, ground, True)


# --- the face-module API (contract in clockface's header) ---

_static = None
_night_static = None


def render_static(canvas):
    """Draw the DAY static layer into canvas
    (display.dial()); remembered for compose()."""
    global _static
    draw_field(canvas)
    _static = canvas
    return canvas


def render_night(canvas):
    """Draw the NIGHT static layer into canvas
    (display.night_dial()) - the sleep treatment's field.
    The day layer is never touched."""
    global _night_static
    draw_field(canvas, night=True)
    _night_static = canvas
    return canvas


def compose(canvas, time_tuple, state=None):
    """One frame of the digital face at time_tuple: field
    copied in, the date (when show_date is on), the hero
    HH:MM (12-hour, unpadded hour - the date line's own
    convention), and the sub-line. state follows the
    painter's convention: {"night": True, "dial": canvas}
    for a sleep frame - PALE on the night ground, and the
    sub-line carries the AM/PM marker alone (no seconds at
    night: nothing on a sleeping face moves inside the
    minute)."""
    if state is None:
        state = {}
    night = state.get("night", False)
    src = state.get("dial", _night_static if night else _static)
    if src is not None and src is not canvas:
        canvas.copy_from(src)
    elif src is None:
        draw_field(canvas, night=night)  # render_static never ran
    if _show_date:
        if night:
            clockface.draw_date(canvas, time_tuple, PALE,
                                NIGHT_GROUND)
        else:
            clockface.draw_date(canvas, time_tuple)
    ink = PALE if night else INK
    ground = NIGHT_GROUND if night else CREAM
    h24 = time_tuple[3]
    ampm = "AM" if h24 < 12 else "PM"
    hero = "%d:%02d" % (h24 % 12 or 12, time_tuple[4])
    _centred(canvas, hero, ink, ground, HERO_SCALE, HERO_Y)
    if night:
        _centred(canvas, ampm, ink, ground, AMPMS_SCALE, AMPM_Y)
    else:
        _centred(canvas, "%02d %s" % (time_tuple[5], ampm),
                 ink, ground, SUB_SCALE, SUB_Y)
    return canvas
