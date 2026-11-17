# classicface.py - the CLASSIC face (Nov 17, 2026, v26): a
# plain analog clock in the painter clock's own visual
# language - the same cream dial, rim and tick weights, the
# same brown-black ink, no figure and no frost. Where the
# painter's hands are hand-painted (wobble, taper, stepped
# hour), the classic's are honest clock hands: straight
# tapers, a smoothly creeping hour and minute, and a slim
# second hand in a muted rust - the one accent colour, from
# the sleep blanket's family.
#
# FACE MODULE CONTRACT (clockface.py header): render_static
# draws the static layer once into display.dial(); compose
# copies it into the frame canvas and draws what moves.
# Extras this face exposes, same conventions as the painter:
# set_show_date(on) (the date shows on EVERY face, gated by
# the admin key - drawn here by clockface.draw_date itself,
# so the line is identical on all three faces) and
# render_night(canvas) for the sleep treatment.
#
# TICK_SECONDS: main.py reads this flag - while awake the
# face wants a fresh frame every second (the second hand
# steps 1 Hz); in the sleep window main drops to the minute
# and this face's night compose ignores seconds entirely.
#
# SLEEP (standing rule): the night layer is the same dial in
# the painter's night palette - deep blue-black ground, faint
# ghost ticks - and the night frame carries PALE hour and
# minute hands only: no second hand, no motion, the time
# snapping each minute exactly as the painter's sleep does.
#
# Frost and Backlight are painter-face effects: this module
# has no set_backlight setter, so main's convention ("a face
# without the setter simply has no glow") leaves them off.
#
# Drawing discipline, same as clockface: C framebuf
# primitives through band windows only, zero per-byte writes.
# The static render is 252 prims (the painter dial's base
# count - same discs + 60 ticks); a day frame is a canvas
# copy plus <= 8 hand/boss prims.
import math
from array import array

import clockface

NAME = "classic"
TICK_SECONDS = True

CX = clockface.CX
CY = clockface.CY
DIAL_R = clockface.DIAL_R

# The painter's palette, shared by reference so the faces
# can never drift apart.
CREAM = clockface.CREAM
CREAM_SHADE = clockface.CREAM_SHADE
RIM = clockface.RIM
TICK = clockface.TICK
INK = clockface.INK
PALE = clockface.PALE
NIGHT_GROUND = clockface.NIGHT_GROUND
NIGHT_SHADE = clockface.NIGHT_SHADE
NIGHT_RIM = clockface.NIGHT_RIM
NIGHT_TICK = clockface.NIGHT_TICK

# The second hand's muted rust - the sleep scene's blanket
# colour (166, 74, 44), lifted a touch for a 2 px line.
ACCENT = clockface.rgb565(172, 84, 52)

HOUR_LEN = 122
MIN_LEN = 178
SEC_LEN = 188
HOUR_W = 14           # base widths; the taper does the rest
MIN_W = 10
TAIL = 26             # counterweight tail behind the centre

_show_date = True        # admin "show_date" key; main.py drives


def set_show_date(on):
    """The face-contract date convention: main.py calls this
    at boot and on every settings change; compose() honours
    it from the next frame."""
    global _show_date
    _show_date = bool(on)


def show_date():
    return _show_date


# --- the dial (static layer) ---

def _tick_coords(ang, r0, r1, w):
    """One tick as a filled polygon - the painter's own
    construction (clockface._tick_coords): the segment
    widened by its disc radius and lengthened by it at both
    ends, so the silhouette matches the capsule original."""
    r = max(1, w // 2)
    a = math.radians(ang)
    dx, dy = math.sin(a), -math.cos(a)     # outward along the tick
    px, py = math.cos(a), math.sin(a)     # perpendicular
    x0, y0 = CX + dx * (r0 - r), CY + dy * (r0 - r)
    x1, y1 = CX + dx * (r1 + r), CY + dy * (r1 + r)
    pts = (x0 + px * r, y0 + py * r,
           x1 + px * r, y1 + py * r,
           x1 - px * r, y1 - py * r,
           x0 - px * r, y0 - py * r)
    return array("h", [int(round(v)) for v in pts])


def draw_dial(fb, night=False):
    """The static layer: rim, ground, ticks - 60 minute
    ticks, longer hour ticks, longest and fattest at the
    quarters (the painter's weights, one notch bolder).
    Ticks only, no numerals - the brief's classic is the
    painter's dial with the man gone home. night=True draws
    the same geometry in the night palette."""
    if night:
        rim, shade, ground, tick = NIGHT_RIM, NIGHT_SHADE, \
            NIGHT_GROUND, NIGHT_TICK
    else:
        rim, shade, ground, tick = RIM, CREAM_SHADE, CREAM, TICK
    r1 = DIAL_R - 8
    ticks = []
    i = 0
    while i < 60:
        ang = i * 6
        if i % 15 == 0:        # quarter hours: longest, fattest
            r0, w = DIAL_R - 30, 5
        elif i % 5 == 0:       # hours
            r0, w = DIAL_R - 23, 3
        else:                  # minutes
            r0, w = DIAL_R - 16, 2
        ticks.append(_tick_coords(ang, r0, r1, w))
        i += 1
    for win, y0 in fb.band_windows():
        win.fill(rim)
        win.ellipse(CX, CY - y0, DIAL_R + 6, DIAL_R + 6,
                    shade, True)
        win.ellipse(CX, CY - y0, DIAL_R, DIAL_R, ground, True)
    for win, y0 in fb.band_windows():
        for coords in ticks:
            win.poly(0, -y0, coords, tick, True)


# --- hands ---

def _hand_coords(angle_deg, length, base_w, tail):
    """A straight-tapered hand as one filled polygon (canvas
    coords, flat array('h')): stations from the tail tip to
    the point - narrow tail, full width at the centre,
    halved by 70% of the length, a clean point at the tip.
    No wobble: that is the painter's handwriting, not this
    face's."""
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)
    px, py = math.cos(a), math.sin(a)
    bw = max(2, base_w // 2)
    stations = ((-tail, max(2, bw - 2)), (0, bw),
                (int(length * 0.7), max(1, bw // 2)),
                (length, 0))
    left = []
    right = []
    for d, hw in stations:
        left.append((CX + dx * d + px * hw, CY + dy * d + py * hw))
        right.append((CX + dx * d - px * hw, CY + dy * d - py * hw))
    flat = left + right[::-1]
    return array("h", [int(round(v)) for xy in flat for v in xy])


def _banded(fb, draw):
    """Run draw(win, y0) only on the bands whose y-range
    [y0, y0+bh) meets [lo, hi) - the painter's band-limiting:
    a band the shape misses can only clip to nothing."""
    wins = list(fb.band_windows())
    bh = wins[1][1] - wins[0][1] if len(wins) > 1 else 480
    return wins, bh


def _draw_hand(fb, angle_deg, length, base_w, tail, colour):
    coords = _hand_coords(angle_deg, length, base_w, tail)
    miny = 9999
    maxy = -9999
    i = 1
    while i < len(coords):
        v = coords[i]
        if v < miny:
            miny = v
        if v > maxy:
            maxy = v
        i += 2
    wins, bh = _banded(fb, None)
    for win, y0 in wins:
        if maxy >= y0 and miny < y0 + bh:
            win.poly(0, -y0, coords, colour, True)


def _dot(fb, x, y, r, colour):
    """A filled circle at (x, y), band-limited like the
    hands - the centre boss and the second hand's
    counterweight."""
    wins, bh = _banded(fb, None)
    for win, y0 in wins:
        if y + r >= y0 and y - r < y0 + bh:
            win.ellipse(int(x), int(y) - y0, r, r, colour, True)


# --- the face-module API (contract in clockface's header) ---

_static = None        # the canvas render_static() last drew into
_night_static = None  # the canvas render_night() last drew into


def render_static(canvas):
    """Draw the DAY static layer into canvas (display.dial()).
    Called once at boot and again whenever the face is
    switched to. Remembers the canvas so compose() can copy
    from it."""
    global _static
    draw_dial(canvas)
    _static = canvas
    return canvas


def render_night(canvas):
    """Draw the NIGHT static layer into canvas
    (display.night_dial()) - the sleep treatment's dial.
    The day layer is never touched."""
    global _night_static
    draw_dial(canvas, night=True)
    _night_static = canvas
    return canvas


def compose(canvas, time_tuple, state=None):
    """One frame of the classic face at time_tuple: static
    dial copied in, the date (when show_date is on - the
    painter's own draw_date, so the line is the same on
    every face), then the hands. state follows the painter's
    convention: {"night": True, "dial": canvas} for a sleep
    frame - pale hour and minute hands on the night layer,
    no second hand, seconds ignored (the snap is the
    minute). By day the hour and minute hands creep
    continuously (a classic movement, not the painter's
    12-minute hour steps) and the rust second hand steps
    once a second."""
    if state is None:
        state = {}
    night = state.get("night", False)
    src = state.get("dial", _night_static if night else _static)
    if src is not None and src is not canvas:
        canvas.copy_from(src)
    elif src is None:
        draw_dial(canvas, night=night)   # render_static never ran
    if _show_date:
        if night:
            clockface.draw_date(canvas, time_tuple, PALE,
                                NIGHT_GROUND)
        else:
            clockface.draw_date(canvas, time_tuple)
    ink = PALE if night else INK
    hour_ang = ((time_tuple[3] % 12)
                + time_tuple[4] / 60.0) * 30.0
    _draw_hand(canvas, hour_ang, HOUR_LEN, HOUR_W, TAIL, ink)
    if night:
        min_ang = time_tuple[4] * 6.0
        _draw_hand(canvas, min_ang, MIN_LEN, MIN_W, TAIL, ink)
        _dot(canvas, CX, CY, 9, ink)
        return canvas
    min_ang = (time_tuple[4] + time_tuple[5] / 60.0) * 6.0
    _draw_hand(canvas, min_ang, MIN_LEN, MIN_W, TAIL, ink)
    sec_ang = time_tuple[5] * 6.0
    _draw_hand(canvas, sec_ang, SEC_LEN, 4, TAIL + 10, ACCENT)
    a = math.radians(sec_ang)
    _dot(canvas, CX - math.sin(a) * (TAIL + 10),
         CY + math.cos(a) * (TAIL + 10), 6, ACCENT)
    _dot(canvas, CX, CY, 9, ink)
    _dot(canvas, CX, CY, 3, ACCENT)
    return canvas
