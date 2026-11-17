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
# TEXT (v27): the glyphs are smoothfont's strikes - real
# Liberation Sans letterforms, anti-aliased (the hero is
# the "hero" strike, the sub-line the "sub" strike) - where
# v26 grew the firmware's 8x8 font to scale 11 and Mark
# asked for smooth. The strips are still NOT
# smoothfont.strip's cache: that cache is keyed per string
# for slow-changing text (a date: one string a day), while
# a digital face mints a new hero string every minute and
# a new sub-line every second, and an unbounded cache of
# ~84 KB hero strips would eat the PSRAM in a day. This
# module keeps its own small bounded cache over
# smoothfont.build_strip: at most _CACHE_MAX strips,
# cleared whole when it fills - a rebuild is ~18,500
# covered-pixel writes for the hero (once a minute at
# most) and ~2,300 for the seconds line.
#
# Drawing discipline: the static field is C framebuf
# primitives through band windows; compose is slice copies
# only (the static copy, the date's rows, the strips'
# rows) - zero framebuf prims, zero per-byte writes.
import clockface
import smoothfont

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

# The layout: strike line boxes, centred on CX. The hero
# strike's line box is 108 px tall and its widest string
# ("12:59") is 391 px - its ink corners sit at r ~195,
# inside the 233 ground disc, and the strip's ground IS
# the field colour, so the box is invisible against the
# field. The sub-line ("%02d PM", ~139x33) rides below it;
# at night the sub-line carries the AM/PM marker alone, in
# the same strike.
HERO_STRIKE = "hero"
HERO_Y = 156
SUB_STRIKE = "sub"
SUB_Y = 284
AMPM_Y = 290           # the night sub-line: the marker alone

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


def _strip(s, colour, ground, strike):
    """A string as an opaque strip (bytes, width, height) -
    smoothfont.build_strip (real letterforms blended onto
    the ground through their coverage masks), behind this
    module's bounded cache."""
    key = (s, colour, ground, strike)
    hit = _strips.get(key)
    if hit is not None:
        return hit
    if len(_strips) >= _CACHE_MAX:
        _strips.clear()
    hit = smoothfont.build_strip(s, strike, colour, ground)
    _strips[key] = hit
    return hit


def _centred(canvas, s, colour, ground, strike, y):
    """Blit one strip centred on CX at rows y..y+h-1: row
    slice copies into the frame buffer, the draw_date
    pattern."""
    strip, w, h = _strip(s, colour, ground, strike)
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
    _centred(canvas, hero, ink, ground, HERO_STRIKE, HERO_Y)
    if night:
        _centred(canvas, ampm, ink, ground, SUB_STRIKE, AMPM_Y)
    else:
        _centred(canvas, "%02d %s" % (time_tuple[5], ampm),
                 ink, ground, SUB_STRIKE, SUB_Y)
    return canvas
