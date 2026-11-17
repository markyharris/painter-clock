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
# THE DATE (Nov 15, 2026, v11): every face shows the date - day
# and month - unless the admin "show_date" config key is off
# (Mark's requirement, FACES.md). The shared convention: main.py
# hands each face module the setting via set_show_date(on) at
# boot and on every settings change, and the face honours it in
# compose(). Future faces implement the same two pieces
# (set_show_date + honouring it in compose) and inherit the
# rule. The painter draws its date per frame (draw_date below),
# so midnight and toggles need no static re-render.
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
import framebuf
import math
from array import array

import smoothfont

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

# The date line (v11; v14: scaled up; v27: SMOOTH):
# "Sun 15 Nov" in the dial's ink, upper centre, drawn per
# frame by compose() when enabled - painted on the glass
# like the hands, so NOT frost-veiled (figure.py's veil is
# for the man behind the glass, not for what's painted on
# it). v11 drew the firmware framebuf's built-in 8x8 font
# at 1x and Mark found it "way too small to read"; v14 grew
# every glyph pixel to a 3x square - readable, but blocks.
# v27 renders the line in smoothfont's "date" strike
# (Liberation Sans at full size, anti-aliased - see
# smoothfont.py): same position, same ink, no blocks.
# Rows DATE_Y..DATE_Y+DATE_H-1 sit in open cream: clear of
# the rim ticks (their inner edge is y 35 at the top) and
# of his cap even at the body's maximum rise (cap top
# 158 - 39 = 119) - DATE_Y is chosen so the strike's line
# box ENDS at y 116, inside that clearance.
_DATE_ASC, _DATE_DESC, _DATE_CAP_OFF = smoothfont.metrics(
    "date")
DATE_H = _DATE_ASC + _DATE_DESC   # the strike's line box
DATE_Y = 116 - DATE_H
DATE_CW = 24       # an upper bound on the smooth strike's
                   # per-character advance - the desk
                   # tests' date-box width, as it was for
                   # the 3x blocks (the real strip is
                   # narrower and centred the same way)
_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_show_date = True        # admin "show_date" key; main.py drives


def set_show_date(on):
    """The face-module date convention (see the header): main.py
    calls this with the admin setting at boot and whenever it
    changes; compose() honours it from the next frame."""
    global _show_date
    _show_date = bool(on)


def show_date():
    return _show_date


# --- the backlight (Nov 16, 2026, v18) ---
# PAINTED light, not the panel's: a soft warm pool baked into
# the DAY dial behind the standing man, so he reads as lit
# from within the case, the way Baas's Schiphol figure is.
# The admin "backlight" key (0..100, config default 50) drives
# it through set_backlight() - the same convention as the date
# above: main.py applies the config at boot and on every
# change, and render_static() re-bakes the dial. The module
# default is 0 (no glow) until main applies the config, so
# any path that never sets it renders the pre-v18 dial
# exactly. figure.py's rim light reads the same setting via
# prepare()'s backlight argument - the two halves of the
# effect are tuned by the one slider.
_backlight = 0           # applied strength, 0..100


def set_backlight(value):
    """Apply the admin "backlight" strength (0..100). Takes
    effect at the next render_static() - the glow lives in
    the static layer, so per-frame cost never changes."""
    global _backlight
    try:
        v = int(value)
    except Exception:
        return
    if v < 0:
        v = 0
    if v > 100:
        v = 100
    _backlight = v


def backlight():
    return _backlight


def _weekday_sun0(y, m, d):
    """Day of week, 0 = Sunday - Sakamoto's algorithm, the same
    computation timekeep.py keeps the RTC honest with, so the
    printed weekday always agrees with the printed date (it is
    computed from the date fields, never read off the tuple's
    own weekday slot)."""
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    if m < 3:
        y -= 1
    return (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7


def date_string(time_tuple):
    """"Sun 15 Nov" for a localtime-style tuple ([0] year,
    [1] month, [2] day of month). The day is unpadded."""
    y, m, d = time_tuple[0], time_tuple[1], time_tuple[2]
    return "%s %d %s" % (_WEEKDAYS[_weekday_sun0(y, m, d)], d,
                         _MONTHS[m - 1])


_strips = {}         # (string, colour, ground, scale) ->
                     # (bytes, width, height): the day strip and
                     # the pale night strip are separate entries;
                     # each is rebuilt only when its string
                     # changes - once a day for the date


def _pat(colour):
    """One RGB565 pixel as 2 little-endian bytes - display.py's
    byte order (kept local: this module stays display-free)."""
    return bytes((colour & 0xFF, (colour >> 8) & 0xFF))


def text_strip(s, colour, ground, scale):
    """A string as an opaque strip (bytes, width, height) at
    the given scale - the project's ORIGINAL text renderer:
    the 8x8 font drawn once into a small scratch FrameBuffer
    (nowhere near the full-size FrameBuffer the firmware
    wedges on), then each set pixel grows to a scale-square.
    RETIRED in v27: every shipped text path (the date, the
    digital face, both boot screens) renders through
    smoothfont.py now. Kept because the desk harness still
    renders the old blocks for before/after comparisons -
    do not build new callers on it."""
    key = (s, colour, ground, scale)
    hit = _strips.get(key)
    if hit is not None:
        return hit
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


def _date_strip(s, colour, ground):
    """The date string as an opaque strip (bytes, width) -
    smoothfont's "date" strike, with the date's two-value
    return. The strip's ground is the dial colour under the
    box (CREAM by day, NIGHT_GROUND by night): the dial
    under the box is plain ground (the box's farthest
    corner sits ~194 px from centre, inside the 233 disc,
    clear of ticks and of his cap), so copying the strip in
    opaquely is pixel-exact - the anti-aliasing blends ink
    toward that ground, which is exactly what's there."""
    strip, w, _h = smoothfont.strip(s, "date", colour,
                                    ground)
    return strip, w


def draw_date(fb, time_tuple, colour=None, ground=None):
    """The date, centred at DATE_Y: the cached smooth strip
    copied into the frame buffer row by row (the Canvas.blit
    slice pattern - DATE_H slice copies, no window needed).
    The glyph box still lives entirely in the top band; the
    minute hand crosses it and is drawn after, exactly as
    before. By night the strip is PALE on NIGHT_GROUND -
    same box, same slices. (Defaults resolve in the body:
    INK/CREAM are defined below in the module, and def-time
    defaults would not see them.)"""
    if colour is None:
        colour = INK
    if ground is None:
        ground = CREAM
    s = date_string(time_tuple)
    strip, w = _date_strip(s, colour, ground)
    x = CX - w // 2
    buf = fb.buf
    row = w * 2
    for r in range(DATE_H):
        do = ((DATE_Y + r) * 480 + x) * 2
        buf[do:do + row] = strip[r * row:(r + 1) * row]


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


CREAM = rgb565(246, 241, 231)     # the frosted dial
CREAM_SHADE = rgb565(232, 225, 208)
RIM = rgb565(58, 52, 44)          # dark rim ring
TICK = rgb565(120, 112, 96)
INK = rgb565(26, 24, 22)          # painted-hand black

# The night dial (Nov 15, 2026, v15 - sleep mode): the same dial
# with the room's light off. Deep blue-black ground, a shade ring
# only just lighter, ticks faint blue-grey ghosts of themselves,
# and the hands + date in PALE - #e9e2cf, lamplight paper - the
# only bright thing in the room. render_night() draws this into
# display.night_dial(); the day layer is never touched, so dawn
# costs no re-render.
PALE = rgb565(233, 226, 207)          # #e9e2cf
NIGHT_GROUND = rgb565(10, 13, 26)     # deep blue-black
NIGHT_SHADE = rgb565(19, 24, 42)
NIGHT_RIM = rgb565(3, 4, 8)
NIGHT_TICK = rgb565(54, 66, 100)

# The backlight glow (v18): a warm-white pool in the day dial,
# centred behind the standing figure (his body spans roughly
# y 158..470, cap to boots, about x 240). The geometry is
# CONTAINED in the ground disc: centre (240, 290), radius 180 -
# the farthest glow point sits 50 + 180 = 230 px from the dial
# centre, inside DIAL_R (233), so the glow can never tint the
# shade ring or the rim. The date box (rows 88..111) is 179 px
# from the glow centre at its nearest - the raised-cosine
# falloff there is ~0.0001, so the ground under the date strip
# stays CREAM to the last bit and the strip's opaque ground
# stays pixel-exact. The ticks are drawn AFTER the glow, crisp
# on top of it, like the hands.
GLOW_CX = 240
GLOW_CY = 290
GLOW_R = 180
GLOW_WARM = (255, 234, 192)     # 888 warm white the ground
                                # mixes toward - the warmth is
                                # mostly the blue falling away
GLOW_PEAK = 0.85                # centre mix at strength 100

# 4x4 Bayer matrix: v19's glow takes its per-row dither
# threshold from it (see _paint_glow) - one threshold per
# row, cycling with a 16-row period, so the colour steps
# land at different x on neighbouring rows and read as
# texture rather than as rings.
_BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6),
           (3, 11, 1, 9), (15, 7, 13, 5))


def _glow_dx(f, dy, r2):
    """Chord half-width at falloff f on the row dy from the
    glow centre: f = (1 - (dx^2 + dy^2)/r2)^2 inverted."""
    v = (1.0 - math.sqrt(f)) * r2 - dy * dy
    if v <= 0.0:
        return 0.0
    return math.sqrt(v)


def _paint_glow(fb, strength):
    """Paint the glow into the day dial as horizontal span
    fills through the band windows - C framebuf primitives
    only, zero per-pixel Python work (v19).

    History: v18 computed the ideal colour per pixel in a
    Python loop (~102k iterations, ~141k byte writes into
    the dial buffer). On the desk that is 0.2 s; on the
    board it hung the clock outright - a slider save and a
    warm reboot both re-render the dial, and neither came
    back (Mark, Nov 16, 2026: unplug-the-USB hangs, both).
    The first v18 cut - concentric filled ellipses - is not
    the way back either: the whole cream-to-warm journey is
    only ~+1 red / -2 green / -4 blue LSBs of RGB565, so
    solid rings at any fineness round into a handful of
    hard-edged bands: a target, not a glow.

    The span construction keeps v18's colour math (same
    endpoints, same (1 - t^2)^2 falloff, same Bayer
    threshold idea) but solves each row analytically: with
    one threshold per row, each channel's rounded value is
    a step function of the falloff f, so the row splits
    into a handful of constant-colour runs at the channels'
    crossing f-values (at most ~8 crossings - the journey
    is a few LSBs). Each run is one fill_rect per side.
    The threshold cycles per row (Bayer, 16-row period),
    so neighbouring rows put their steps at different x
    and the eye reads texture, not rings - the same trick
    v18's per-pixel dither played, at row granularity.
    Runs whose colour is the ground itself are skipped
    (the ground pass already painted them) - which is also
    what keeps the date rows (88..111) bit-exact: at their
    distance the mix never reaches a rounding boundary.
    A few thousand fill_rects and ~361 rows of small float
    work per render, against v18's ~102k loop iterations."""
    s = strength / 100.0 * GLOW_PEAK
    r2 = float(GLOW_R * GLOW_R)
    # channel endpoints as floats in 565 units: the cream
    # ground (decoded from CREAM itself) and the warm target
    cr = (CREAM >> 11) & 0x1F
    cg = (CREAM >> 5) & 0x3F
    cb = CREAM & 0x1F
    dr = (GLOW_WARM[0] * 31.0 / 255.0 - cr) * s
    dg = (GLOW_WARM[1] * 63.0 / 255.0 - cg) * s
    db = (GLOW_WARM[2] * 31.0 / 255.0 - cb) * s
    chans = ((cr, dr), (cg, dg), (cb, db))
    bands = list(fb.band_windows())
    nb = len(bands)
    bi = 0
    while bi < nb:
        win, y0 = bands[bi]
        if bi + 1 < nb:
            ybot = bands[bi + 1][1] - 1
        else:
            ybot = GLOW_CY + GLOW_R
        y = max(GLOW_CY - GLOW_R, y0)
        yend = min(GLOW_CY + GLOW_R, ybot)
        while y <= yend:
            dy = y - GLOW_CY
            half = int(math.sqrt(GLOW_R * GLOW_R - dy * dy))
            f0 = 1.0 - (dy * dy) / r2
            f0 = f0 * f0
            thr = (_BAYER4[y & 3][(y >> 2) & 3] + 0.5) / 16.0
            # the f-values where a channel's rounded value
            # changes: value(f) = c0 + dc*f + thr crossing an
            # integer. Collect them all, plus the endpoints.
            cuts = [0.0, f0]
            for c0, dc in chans:
                if dc == 0.0:
                    continue
                va = c0 + thr
                vb = va + dc * f0
                k = int(math.floor(min(va, vb)))
                kend = int(math.ceil(max(va, vb)))
                while k <= kend:
                    fk = (k - thr - c0) / dc
                    if 0.0 < fk < f0:
                        cuts.append(fk)
                    k += 1
            cuts.sort()
            # intervals of constant colour, centre outward:
            # interval (flo, fhi] in f is dx in [dx(fhi),
            # dx(flo)) - mirrored spans at one colour each.
            i = len(cuts) - 1
            while i > 0:
                fhi = cuts[i]
                flo = cuts[i - 1]
                fmid = (fhi + flo) * 0.5
                col = ((int(cr + dr * fmid + thr) << 11)
                       | (int(cg + dg * fmid + thr) << 5)
                       | int(cb + db * fmid + thr))
                if col != CREAM:
                    lo_i = int(math.ceil(
                        _glow_dx(fhi, dy, r2) - 1e-6))
                    if flo > 0.0:
                        hi_i = int(math.ceil(
                            _glow_dx(flo, dy, r2) - 1e-6)) - 1
                    else:
                        hi_i = half
                    if hi_i > half:
                        hi_i = half
                    if lo_i <= hi_i:
                        if lo_i == 0:
                            win.fill_rect(GLOW_CX - hi_i,
                                          y - y0,
                                          2 * hi_i + 1, 1, col)
                        else:
                            w = hi_i - lo_i + 1
                            win.fill_rect(GLOW_CX + lo_i,
                                          y - y0, w, 1, col)
                            win.fill_rect(GLOW_CX - hi_i,
                                          y - y0, w, 1, col)
                i -= 1
            y += 1
        bi += 1


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
    # Band-limit both calls (figure's helpers do the same): a
    # band whose y-range the polygon's extent misses can only
    # clip to nothing, so calling into it is pure overhead -
    # skipping it changes no pixel. The centre boss is limited
    # by its own extent the same way. (The band height is read
    # off the window spacing - band_windows() bands are uniform,
    # and this module stays free of display imports.)
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
    # centre boss
    r = int(base_width * 0.85)
    wins = list(fb.band_windows())
    bh = wins[1][1] - wins[0][1] if len(wins) > 1 else 480
    for win, y0 in wins:
        if maxy >= y0 and miny < y0 + bh:
            win.poly(0, -y0, coords, colour, True)
        if CY + r >= y0 and CY - r < y0 + bh:
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


def draw_dial(fb, night=False):
    """The static layer: rim, cream face, ticks - 60 minute ticks,
    longer hour ticks, longest at the quarters. Ticks only (see
    NUMERALS above). Rendered ONCE into the dial canvas at boot (or
    on a face switch) and copied under every frame - it never
    changes while this face is selected. Drawn band by band with C
    framebuf primitives (fill/ellipse/poly) through band_windows();
    the same drawing in Python loops took 54 s on the board.
    night=True draws the same geometry in the night palette
    (v15): the sleep layer, rendered once into its own canvas.
    The day dial also carries the backlight glow (v18) at the
    applied strength - a backlight change re-runs this render,
    exactly like a face switch does."""
    if night:
        rim, shade, ground, tick = NIGHT_RIM, NIGHT_SHADE, \
            NIGHT_GROUND, NIGHT_TICK
    else:
        rim, shade, ground, tick = RIM, CREAM_SHADE, CREAM, TICK
    # the backlight glow is a DAY behaviour (v18): the night
    # dial is the room with its light off and never glows.
    # Strength 0 skips it entirely - the pre-v18 dial, byte
    # for byte. It is drawn as span fills BETWEEN the ground
    # pass and the tick pass (see _paint_glow for the
    # construction, and for why neither rings nor a per-pixel
    # loop would do).
    glow = not night and _backlight > 0
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
        win.fill(rim)
        win.ellipse(CX, CY - y0, DIAL_R + 6, DIAL_R + 6,
                    shade, True)
        win.ellipse(CX, CY - y0, DIAL_R, DIAL_R, ground, True)
    if glow:
        _paint_glow(fb, _backlight)
    for win, y0 in fb.band_windows():
        for coords in ticks:
            win.poly(0, -y0, coords, tick, True)


def minute_angle(total_minutes):
    return (total_minutes % 60) * 6.0


def hour_angle_stepped(total_minutes):
    """The hour hand moves in 6-degree steps every 12 minutes -
    stepped, not continuous (SPEC.md 3.2)."""
    return ((total_minutes // 12) % 60) * 6.0


# --- the face-module API (contract in the header) ---

_static = None        # the canvas render_static() last drew into
_night_static = None  # the canvas render_night() last drew into


def render_static(canvas):
    """Draw this face's static layer into canvas (display.dial()).
    Called once at boot and again whenever the face is switched to.
    Remembers the canvas so compose() can copy from it."""
    global _static
    draw_dial(canvas)
    _static = canvas
    return canvas


def render_night(canvas):
    """Draw the NIGHT static layer into canvas
    (display.night_dial()) - the sleep scene's dial (v15). A
    painter-face extra beyond the base contract: only the
    painter has a night, and only its sleep path calls this.
    The day layer is never touched."""
    global _night_static
    draw_dial(canvas, night=True)
    _night_static = canvas
    return canvas


def compose(canvas, time_tuple, state=None):
    """One frame of the painter face at time_tuple: static dial
    copied in, then the date (when show_date is on), then the
    hour and minute hands. state (optional)
    overrides for the show engine: {"dial": canvas, "hour_angle",
    "min_angle", "hour_reveal", "min_reveal"} - angles default to
    the time, reveals default to fully painted (1.0). The sleep
    path passes "night": True (v15): the date and the hands are
    drawn in PALE on the night ground instead of INK on cream -
    the caller has already laid the night layer + sleep scene
    and passes "dial": canvas as usual."""
    if state is None:
        state = {}
    src = state.get("dial", _static)
    if src is not None and src is not canvas:
        canvas.copy_from(src)
    elif src is None:
        draw_dial(canvas)      # render_static never ran - draw direct
    total = time_tuple[3] * 60 + time_tuple[4]
    night = state.get("night", False)
    if _show_date:
        if night:
            draw_date(canvas, time_tuple, PALE, NIGHT_GROUND)
        else:
            draw_date(canvas, time_tuple)
    ink = PALE if night else INK
    draw_hand(canvas,
              state.get("hour_angle", hour_angle_stepped(total)),
              HOUR_LEN, HOUR_W, state.get("hour_reveal", 1.0), ink)
    draw_hand(canvas,
              state.get("min_angle", minute_angle(total)),
              MIN_LEN, MIN_W, state.get("min_reveal", 1.0), ink)
    return canvas
