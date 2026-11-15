# clockface.py - the PAINTER face: the frosted dial and the painted
# hands. This is the flagship/default face module.
#
# FACE MODULE CONTRACT (SPEC.md, Nov 15 addendum): every clock face
# is a module exposing -
#
#     render_static(canvas)          draw the face's static layer
#                                    ONCE into display.dial()
#     compose(canvas, time_tuple,    copy the static layer into the
#             state=None)            frame canvas and draw whatever
#                                    moves, for time_tuple (a
#                                    localtime-style tuple; [3]=hour,
#                                    [4]=minute)
#
# - so face_classic.py / face_digital.py can plug into the same
# display layer with no display.py changes. The admin "face" config
# key picks the module; switching faces re-runs render_static once.
#
# Pure drawing + geometry: no driver imports (display.py owns the
# panel), no state beyond the remembered static canvas. The drawing
# surface is duck-typed - display.Canvas in production (a full-size
# framebuf.FrameBuffer WEDGES this firmware; see display.py), any
# object with fill/fill_rect/line/ellipse works.
#
# show.py decides WHAT is revealed during a show; the helpers here
# know HOW a hand looks - 14 segments, fixed hand-painted wobble,
# tapering width - exactly as the prototype settled it (SPEC.md 3.2).
import math

NAME = "painter"

CX = 240
CY = 240
DIAL_R = 233          # drawing radius inside the 480x480 canvas
MIN_LEN = 163
HOUR_LEN = 108
SEG = 14              # segments per hand
WOBBLE_AMP = 2.0      # px at 480 (prototype 1.6 @880 was sub-pixel here)
MIN_W = 9             # minute hand width at the base, px
HOUR_W = 12           # hour hand: shorter and fatter

# Face details (SPEC.md sec.8 Q3): ticks only, no numerals - the
# prototype's look. The flag exists so a numeral variant can land
# without restructuring draw_dial; glyphs are a future font pass,
# until then NUMERALS=True still draws the tick dial.
NUMERALS = False


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


CREAM = rgb565(246, 241, 231)     # the frosted dial
CREAM_SHADE = rgb565(232, 225, 208)
RIM = rgb565(58, 52, 44)          # dark rim ring
TICK = rgb565(120, 112, 96)
INK = rgb565(26, 24, 22)          # painted-hand black


def point_at(angle_deg, dist):
    """Point on the dial at clock-angle (0 = 12, clockwise) and
    distance from centre. The one angle convention for the project."""
    a = math.radians(angle_deg)
    return (CX + math.sin(a) * dist, CY - math.cos(a) * dist)


def hand_tip(angle_deg, reveal, length):
    """Where the frontier of a hand is at a given reveal fraction -
    the brush/cloth target during wipe and paint."""
    return point_at(angle_deg, length * reveal)


def _seg_point(angle_deg, length, f):
    # fixed wobble: perpendicular offset sin(f*22)*AMP - his handwriting
    a = math.radians(angle_deg)
    wob = math.sin(f * 22.0) * WOBBLE_AMP
    x = CX + math.sin(a) * length * f + math.cos(a) * wob
    y = CY - math.cos(a) * length * f + math.sin(a) * wob
    return (x, y)


def thick_line(fb, x0, y0, x1, y1, width, colour):
    """A solid line of the given width: filled discs of radius
    width//2 stamped along the segment, overlapping by half. (The
    naive version - parallel 1 px lines at perpendicular offsets -
    leaves a pinhole moire on diagonals after int() rounding; seen
    in desk tests Nov 15, 2026. Discs are solid at any angle.)"""
    dx = x1 - x0
    dy = y1 - y0
    dist = math.sqrt(dx * dx + dy * dy)
    r = max(1, width // 2)
    if dist < 0.5:
        fb.ellipse(int(x0), int(y0), r, r, colour, True)
        return
    n = int(dist / r) + 1
    i = 0
    while i <= n:
        t = i / n
        fb.ellipse(int(x0 + dx * t), int(y0 + dy * t), r, r, colour, True)
        i += 1


def draw_hand(fb, angle_deg, length, base_width, reveal, colour=INK):
    """Draw the visible part of a hand. reveal 0..1 = stroke
    progress; the frontier segment is drawn partially, the rest not
    at all. During wipe the caller passes the OLD angle with reveal
    shrinking; during paint the NEW angle with reveal growing."""
    if reveal <= 0.003:
        return
    visible = reveal * SEG
    i = 0
    while i < SEG:
        f0 = i / SEG
        if i + 1 > visible + 0.001:
            frac = visible - i
            if frac <= 0:
                break
            f1 = (i + frac) / SEG
            x0, y0 = _seg_point(angle_deg, length, f0)
            x1, y1 = _seg_point(angle_deg, length, f1)
            w = max(3, int(base_width * (1 - f0 * 0.45)))
            thick_line(fb, x0, y0, x1, y1, w, colour)
            break
        f1 = (i + 1) / SEG
        x0, y0 = _seg_point(angle_deg, length, f0)
        x1, y1 = _seg_point(angle_deg, length, f1)
        w = max(3, int(base_width * (1 - f0 * 0.45)))
        thick_line(fb, x0, y0, x1, y1, w, colour)
        i += 1
    # centre boss
    r = int(base_width * 0.85)
    fb.ellipse(CX, CY, r, r, colour, True)


def draw_dial(fb):
    """The static layer: rim, cream face, ticks - 60 minute ticks,
    longer hour ticks, longest at the quarters. Ticks only (see
    NUMERALS above). Rendered ONCE into the dial canvas at boot (or
    on a face switch) and copied under every frame - it never
    changes while this face is selected."""
    fb.fill(RIM)
    fb.ellipse(CX, CY, DIAL_R + 6, DIAL_R + 6, CREAM_SHADE, True)
    fb.ellipse(CX, CY, DIAL_R, DIAL_R, CREAM, True)
    r1 = DIAL_R - 8
    i = 0
    while i < 60:
        ang = i * 6
        if i % 15 == 0:        # quarter hours: longest, fattest
            r0, w = DIAL_R - 28, 4
        elif i % 5 == 0:       # hours
            r0, w = DIAL_R - 22, 3
        else:                  # minutes
            r0, w = DIAL_R - 16, 2
        x0, y0 = point_at(ang, r0)
        x1, y1 = point_at(ang, r1)
        thick_line(fb, x0, y0, x1, y1, w, TICK)
        i += 1


def minute_angle(total_minutes):
    return (total_minutes % 60) * 6.0


def hour_angle_stepped(total_minutes):
    """The hour hand moves in 6-degree steps every 12 minutes -
    stepped, not continuous (SPEC.md 3.2)."""
    return ((total_minutes // 12) % 60) * 6.0


# --- the face-module API (contract in the header) ---

_static = None        # the canvas render_static() last drew into


def render_static(canvas):
    """Draw this face's static layer into canvas (display.dial()).
    Called once at boot and again whenever the face is switched to.
    Remembers the canvas so compose() can copy from it."""
    global _static
    draw_dial(canvas)
    _static = canvas
    return canvas


def compose(canvas, time_tuple, state=None):
    """One frame of the painter face at time_tuple: static dial
    copied in, then the hour and minute hands. state (optional)
    overrides for the show engine: {"dial": canvas, "hour_angle",
    "min_angle", "hour_reveal", "min_reveal"} - angles default to
    the time, reveals default to fully painted (1.0)."""
    if state is None:
        state = {}
    src = state.get("dial", _static)
    if src is not None and src is not canvas:
        canvas.copy_from(src)
    elif src is None:
        draw_dial(canvas)      # render_static never ran - draw direct
    total = time_tuple[3] * 60 + time_tuple[4]
    draw_hand(canvas,
              state.get("hour_angle", hour_angle_stepped(total)),
              HOUR_LEN, HOUR_W, state.get("hour_reveal", 1.0))
    draw_hand(canvas,
              state.get("min_angle", minute_angle(total)),
              MIN_LEN, MIN_W, state.get("min_reveal", 1.0))
    return canvas
