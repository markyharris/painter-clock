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
# surface is a display.Canvas. The dial and hands are drawn with
# genuine C framebuf primitives (fill/ellipse/poly) inside band
# windows - Canvas.band_windows() - because the Python-loop drawing
# measured 54 s (dial) / 20 s (hands) on the board (Nov 15 bench;
# SPEC addendum). thick_line() below stays on the Canvas primitives:
# figure.py still uses it, and the figure is a slow path by design.
#
# show.py decides WHAT is revealed during a show; the helpers here
# know HOW a hand looks - 14 segments, fixed hand-painted wobble,
# tapering width - exactly as the prototype settled it (SPEC.md 3.2).
import math
from array import array

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


def _hand_coords(angle_deg, length, base_width, reveal):
    """The visible part of a hand as one filled polygon, in canvas
    coords (flat array('h')): the wobbled centreline from the same
    14-segment math as ever (_seg_point), offset perpendicular by
    half the local width - the same taper and the same radius
    (w//2) the old disc-stamped thick_line used, so the silhouette
    matches to ~a pixel. Reveal semantics are the old ones: whole
    segments up to the stroke frontier, the frontier segment
    partial, nothing beyond it."""
    visible = reveal * SEG
    # centreline samples: (f, governing segment) - segment i's width
    # comes from its start f0 = i/SEG, exactly as the old code had it
    samples = [(0.0, 0)]
    i = 0
    while i < SEG:
        if i + 1 > visible + 0.001:
            frac = visible - i
            if frac <= 0:
                break
            samples.append(((i + frac) / SEG, i))
            break
        samples.append(((i + 1) / SEG, i))
        i += 1
    pts = [_seg_point(angle_deg, length, f) for f, _s in samples]
    hws = []
    for _f, s in samples:
        w = max(3, int(base_width * (1 - (s / SEG) * 0.45)))
        hws.append(max(1, w // 2))
    n = len(pts)
    left = []
    right = []
    for j in range(n):
        xa, ya = pts[max(0, j - 1)]
        xb, yb = pts[min(n - 1, j + 1)]
        tx, ty = xb - xa, yb - ya
        d = math.sqrt(tx * tx + ty * ty)
        if d < 0.001:
            a = math.radians(angle_deg)
            nx, ny = math.cos(a), math.sin(a)
        else:
            nx, ny = -ty / d, tx / d
        x, y = pts[j]
        left.append((x + nx * hws[j], y + ny * hws[j]))
        right.append((x - nx * hws[j], y - ny * hws[j]))
    flat = left + right[::-1]
    coords = array("h", [int(round(v)) for xy in flat for v in xy])
    return coords


def draw_hand(fb, angle_deg, length, base_width, reveal, colour=INK):
    """Draw the visible part of a hand. reveal 0..1 = stroke
    progress; the frontier segment is drawn partially, the rest not
    at all. During wipe the caller passes the OLD angle with reveal
    shrinking; during paint the NEW angle with reveal growing.
    Drawn as ONE filled polygon (framebuf.poly) per band window -
    the old disc-stamped version cost ~10 s per hand on the board."""
    if reveal <= 0.003:
        return
    coords = _hand_coords(angle_deg, length, base_width, reveal)
    # centre boss
    r = int(base_width * 0.85)
    for win, y0 in fb.band_windows():
        win.poly(0, -y0, coords, colour, True)
        win.ellipse(CX, CY - y0, r, r, colour, True)


def _tick_coords(ang, r0, r1, w):
    """One tick as a filled polygon (canvas coords): the old shape
    was a capsule - thick_line discs of radius w//2 along the
    segment - so the polygon is the segment widened by that radius
    and lengthened by it at both ends (square caps for round ones;
    the silhouette matches to ~a pixel)."""
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


def draw_dial(fb):
    """The static layer: rim, cream face, ticks - 60 minute ticks,
    longer hour ticks, longest at the quarters. Ticks only (see
    NUMERALS above). Rendered ONCE into the dial canvas at boot (or
    on a face switch) and copied under every frame - it never
    changes while this face is selected. Drawn band by band with C
    framebuf primitives (fill/ellipse/poly) through band_windows();
    the same drawing in Python loops took 54 s on the board."""
    r1 = DIAL_R - 8
    ticks = []
    i = 0
    while i < 60:
        ang = i * 6
        if i % 15 == 0:        # quarter hours: longest, fattest
            r0, w = DIAL_R - 28, 4
        elif i % 5 == 0:       # hours
            r0, w = DIAL_R - 22, 3
        else:                  # minutes
            r0, w = DIAL_R - 16, 2
        ticks.append(_tick_coords(ang, r0, r1, w))
        i += 1
    for win, y0 in fb.band_windows():
        win.fill(RIM)
        win.ellipse(CX, CY - y0, DIAL_R + 6, DIAL_R + 6,
                    CREAM_SHADE, True)
        win.ellipse(CX, CY - y0, DIAL_R, DIAL_R, CREAM, True)
        for coords in ticks:
            win.poly(0, -y0, coords, TICK, True)


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
