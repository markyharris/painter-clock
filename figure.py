# figure.py - the little man: body-follow rig, two-bone IK arms,
# pose computation, and drawing.
#
# The geometry is the prototype's, scaled 880 -> 480 (SPEC.md 3.3).
# The rules that make him read as a person rather than a puppet:
#   * his ARM NEVER CHANGES LENGTH - fixed bones, cosine-rule elbow
#   * his BODY does the travelling - the shoulder eases toward the
#     work by a per-phase follow factor, so the residual reach is
#     always short and the elbow always keeps its bend
#   * poses are DERIVED from intent each frame, never keyframed
#
# DRAWING (Nov 15, 2026 - the sprite/arm split; SPEC addendum):
# per-frame Python drawing is far too slow on the board, so the
# body is pre-rendered ONCE at boot (prepare()) into two keyed
# sprites - standing, and the full dip (waist fold 1.02 rad) -
# drawn with C framebuf primitives inside band windows of a scratch
# canvas, head and cap baked in (v1: no separate head tracking, so
# head_tilt is carried in the pose but not rendered). The bucket is
# a third small sprite. Per frame, draw() is then just: two sprite
# blits plus the two arms as filled polygons through the frame
# canvas's band windows. The blits use per-sprite OPAQUE-RUN LISTS
# precomputed in prepare() - a per-frame key scan of ~59k sprite
# pixels in Python (display.blit_sprite's job) would eat the
# frame budget; with runs precomputed, a blit is a few hundred
# slice copies and nothing else. The torso switches sprite at
# bend >= 0.5, and the arm shoulder anchors snap to the same bend
# so the arms stay glued to the visible torso. Shoulders in the
# sprites sit at the HOME pose; the whole figure's travel is the
# blit offset (drawn body - home feet).
import math
from array import array

import clockface
import display

# --- rig constants (480-scale, px) ---
HOME_FEET = (240, 446)
SHOULDER_H = 152                 # shoulder height above feet
HEAD_H = 199                     # head centre height above feet
HOME_SHOULDER = (244, HOME_FEET[1] - SHOULDER_H)
BUCKET = (332, 436)
SHOULDER_CLAMP_X = 106           # shoulder may stray this far from home x
HIP_H = 81                       # hip pivot height above feet (the bend)
ARM_L1 = 48                      # upper arm
ARM_L2 = 47                      # forearm - total reach 95
REACH_MAX = ARM_L1 + ARM_L2 - 2  # clamp targets to 93
BEND_RAD = 1.02                  # waist fold at bend == 1 (~58 deg)

# colours (RGB565 via clockface.rgb565)
OVERALLS = clockface.rgb565(51, 80, 126)
OVERALLS_DK = clockface.rgb565(38, 60, 96)
SHIRT = clockface.rgb565(116, 132, 150)     # chambray work shirt
SKIN = clockface.rgb565(201, 161, 137)
CAP = clockface.rgb565(39, 66, 102)
CAP_DK = clockface.rgb565(30, 50, 78)
BOOT = clockface.rgb565(43, 34, 28)
CLOTH = clockface.rgb565(216, 212, 204)
BRUSH_WOOD = clockface.rgb565(138, 107, 69)
BUCKET_COL = clockface.rgb565(107, 111, 117)
BUCKET_DK = clockface.rgb565(84, 88, 94)
PAINT = clockface.INK
KEY = clockface.rgb565(255, 0, 255)         # sprite transparent key

# sprite geometry: one region (canvas coords at the home pose) for
# both body sprites, so they blit at the same offset. It must cover
# the dipped head: at full bend the head centre lands near
# (340, 317) and the cap reaches x ~ 378.
SPR_X = 168
SPR_Y = 192
SPR_W = 216
SPR_H = 272                     # bottom edge 464 (boots end ~457)
# bucket sprite region (bucket at home); bucket centre x is
# BUCKET[0] - BKT_X = 26 = BKT_W // 2, so it blits centred on
# bucket_x.
BKT_X = 306
BKT_Y = 416
BKT_W = 52
BKT_H = 42


def ik(sx, sy, tx, ty):
    """Two-bone IK. Returns (elbow_x, elbow_y, hand_x, hand_y) with
    the target clamped to REACH_MAX - the arm cannot stretch."""
    dx = tx - sx
    dy = ty - sy
    d = math.sqrt(dx * dx + dy * dy)
    if d < 1:
        d = 1
    if d > REACH_MAX:
        tx = sx + dx / d * REACH_MAX
        ty = sy + dy / d * REACH_MAX
        dx = tx - sx
        dy = ty - sy
        d = REACH_MAX
    a = (ARM_L1 * ARM_L1 - ARM_L2 * ARM_L2 + d * d) / (2 * d)
    h2 = ARM_L1 * ARM_L1 - a * a
    h = math.sqrt(h2) if h2 > 0 else 0
    ux = dx / d
    uy = dy / d
    mx = sx + ux * a
    my = sy + uy * a
    # two elbow candidates; score like the prototype: prefer the
    # lower elbow with a slight outward bias
    e1 = (mx - uy * h, my + ux * h)
    e2 = (mx + uy * h, my - ux * h)

    def score(e):
        return e[1] + abs(e[0] - clockface.CX) * 0.15

    elbow = e1 if score(e1) >= score(e2) else e2
    return (elbow[0], elbow[1], tx, ty)


# --- band-window shape helpers (boot sprites AND per-frame arms) ---

def _quad(x0, y0, x1, y1, x2, y2, x3, y3):
    return array("h", [int(round(v)) for v in
                       (x0, y0, x1, y1, x2, y2, x3, y3)])


def _seg_coords(x0, y0, x1, y1, w):
    """A thick segment as one filled polygon: the segment widened
    by w//2 and lengthened by the same at both ends (square caps
    for the old disc stamps' round ones - same trick, and same
    silhouette to ~a pixel, as clockface's ticks)."""
    r = max(1, w // 2)
    dx = x1 - x0
    dy = y1 - y0
    d = math.sqrt(dx * dx + dy * dy)
    if d < 0.5:
        ux, uy = 1.0, 0.0
    else:
        ux, uy = dx / d, dy / d
    px, py = -uy, ux
    return _quad(x0 - ux * r + px * r, y0 - uy * r + py * r,
                 x1 + ux * r + px * r, y1 + uy * r + py * r,
                 x1 + ux * r - px * r, y1 + uy * r - py * r,
                 x0 - ux * r - px * r, y0 - uy * r - py * r)


def _band_poly(canvas, coords, colour):
    """framebuf.poly a canvas-coords polygon into a Canvas, one
    call per band window the polygon's y-extent touches."""
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
    for win, y0 in canvas.band_windows():
        if maxy < y0 or miny >= y0 + display.BAND_H:
            continue
        win.poly(0, -y0, coords, colour, True)


def _band_ellipse(canvas, cx, cy, rx, ry, colour):
    """Filled framebuf.ellipse, band-limited like _band_poly."""
    cx = int(round(cx))
    cy = int(round(cy))
    for win, y0 in canvas.band_windows():
        if cy + ry < y0 or cy - ry >= y0 + display.BAND_H:
            continue
        win.ellipse(cx, cy - y0, rx, ry, colour, True)


def _lerp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


# --- sprite preparation (once, at boot) ---

_sprites = None          # {"stand": (bytes, runs), "dip": ...}
_bucket_sprite = None    # (bytes, runs)


def _extract(canvas, x, y, w, h):
    out = bytearray(w * h * 2)
    buf = canvas.buf
    row = 0
    while row < h:
        so = ((y + row) * display.WIDTH + x) * 2
        do = row * w * 2
        out[do:do + w * 2] = buf[so:so + w * 2]
        row += 1
    return bytes(out)


def _runs(data, w, h):
    """The sprite's opaque runs as (row, start_px, len_px) tuples -
    computed once so the per-frame blit is pure slice copies."""
    key_lo = KEY & 0xFF
    key_hi = (KEY >> 8) & 0xFF
    runs = []
    row = 0
    while row < h:
        base = row * w * 2
        sx = 0
        while sx < w:
            while sx < w and data[base + sx * 2] == key_lo \
                    and data[base + sx * 2 + 1] == key_hi:
                sx += 1
            if sx >= w:
                break
            start = sx
            while sx < w and not (data[base + sx * 2] == key_lo
                                  and data[base + sx * 2 + 1] == key_hi):
                sx += 1
            runs.append((row, start, sx - start))
        row += 1
    return runs


def _blit_runs(canvas, data, runs, sw, x, y):
    """Blit a sprite by its precomputed opaque runs: one slice
    copy per run, clipped to the canvas. Returns runs drawn."""
    dst = canvas.buf
    src = memoryview(data)
    n = 0
    for row, start, ln in runs:
        dy = y + row
        if dy < 0 or dy >= display.HEIGHT:
            continue
        cx0 = x + start
        s = start
        if cx0 < 0:
            s += -cx0
            ln += cx0
            cx0 = 0
        if cx0 + ln > display.WIDTH:
            ln = display.WIDTH - cx0
        if ln <= 0:
            continue
        so = (row * sw + s) * 2
        do = (dy * display.WIDTH + cx0) * 2
        dst[do:do + ln * 2] = src[so:so + ln * 2]
        n += 1
    return n


def _draw_body(scratch, fig):
    """The armless body at the home pose, in canvas coords, with
    fig.bend preset to the sprite's bend (0 or 1). Flat-shaded:
    boots, legs, overalls + bib + straps over a shirt torso, head
    and cap - all through band-window C primitives."""
    pose = fig.pose()
    fx, fy = pose["feet"]
    head = pose["head"]

    def bp(x, y):
        return fig._bend_point(x, y, fig.bend)

    # boots and legs - never bent (the bend is at the waist)
    _band_ellipse(scratch, fx - 10, fy - 2, 12, 5, BOOT)
    _band_ellipse(scratch, fx + 13, fy - 2, 12, 5, BOOT)
    _band_poly(scratch, _quad(fx - 19, fy - 86, fx - 5, fy - 86,
                              fx - 6, fy - 2, fx - 20, fy - 2),
               OVERALLS_DK)
    _band_poly(scratch, _quad(fx + 5, fy - 86, fx + 19, fy - 86,
                              fx + 20, fy - 2, fx + 6, fy - 2),
               OVERALLS_DK)
    # pelvis (the torso's bent bottom edge overlaps this)
    scratch.fill_rect(int(fx) - 20, int(fy) - 90, 40, 14, OVERALLS)
    # torso: shirt everywhere, overalls over the lower part, with
    # the bib line at 30% and two straps up to the shoulders
    tl = bp(fx - 24, fy - SHOULDER_H)
    tr = bp(fx + 24, fy - SHOULDER_H)
    bl = bp(fx - 20, fy - HIP_H)
    br = bp(fx + 20, fy - HIP_H)
    _band_poly(scratch, _quad(tl[0], tl[1], tr[0], tr[1],
                              br[0], br[1], bl[0], bl[1]), SHIRT)
    ml = _lerp(tl, bl, 0.30)
    mr = _lerp(tr, br, 0.30)
    _band_poly(scratch, _quad(ml[0], ml[1], mr[0], mr[1],
                              br[0], br[1], bl[0], bl[1]), OVERALLS)
    for f0 in (0.08, 0.74):     # straps, as fractions along the top
        s0 = _lerp(tl, tr, f0)
        s1 = _lerp(tl, tr, f0 + 0.14)
        b0 = _lerp(ml, mr, f0 + 0.02)
        b1 = _lerp(ml, mr, f0 + 0.12)
        _band_poly(scratch, _quad(s0[0], s0[1], s1[0], s1[1],
                                  b1[0], b1[1], b0[0], b0[1]),
                   OVERALLS)
    # neck - bridges head and torso, bends with the torso group
    n0 = bp(fx - 6, fy - HEAD_H + 10)
    n1 = bp(fx + 6, fy - HEAD_H + 10)
    n2 = bp(fx + 7, fy - SHOULDER_H + 8)
    n3 = bp(fx - 7, fy - SHOULDER_H + 8)
    _band_poly(scratch, _quad(n0[0], n0[1], n1[0], n1[1],
                              n2[0], n2[1], n3[0], n3[1]), SKIN)
    # head and cap (baked in - v1 has no separate head tracking).
    # The cap is a band across the top of the head, drawn through
    # the bend transform so it tilts with the head in the dip -
    # an axis-aligned ellipse there read as a detached blob.
    hx, hy = head
    _band_ellipse(scratch, hx, hy, 20, 23, SKIN)
    c0 = bp(fx - 19, fy - HEAD_H - 22)
    c1 = bp(fx + 19, fy - HEAD_H - 22)
    c2 = bp(fx + 19, fy - HEAD_H - 3)
    c3 = bp(fx - 19, fy - HEAD_H - 3)
    _band_poly(scratch, _quad(c0[0], c0[1], c1[0], c1[1],
                              c2[0], c2[1], c3[0], c3[1]), CAP)
    b0 = bp(fx - 19, fy - HEAD_H - 3)
    b1 = bp(fx + 20, fy - HEAD_H - 3)
    b2 = bp(fx + 20, fy - HEAD_H + 1)
    b3 = bp(fx - 19, fy - HEAD_H + 1)
    _band_poly(scratch, _quad(b0[0], b0[1], b1[0], b1[1],
                              b2[0], b2[1], b3[0], b3[1]), CAP_DK)


def _draw_bucket(scratch):
    bx, by = BUCKET
    _band_poly(scratch, _quad(bx - 17, by - 12, bx + 17, by - 12,
                              bx + 13, by + 12, bx - 13, by + 12),
               BUCKET_COL)
    _band_ellipse(scratch, bx, by - 12, 17, 5, BUCKET_DK)
    _band_ellipse(scratch, bx, by - 13, 14, 4, PAINT)


def prepare():
    """Pre-render the body sprites (standing + dip) and the bucket
    sprite into keyed RGB565 bytes. Idempotent; called lazily by
    draw() and explicitly by the bench runner / main at boot.
    Renders into a scratch full-size Canvas (freed on return) -
    sprites are the only survivors."""
    global _sprites, _bucket_sprite
    if _sprites is not None:
        return
    scratch = display.Canvas(bytearray(display.FRAME_BYTES))
    fig = Figure()
    out = {}
    for name, bend in (("stand", 0.0), ("dip", 1.0)):
        scratch.fill(KEY)
        fig.bend = bend
        _draw_body(scratch, fig)
        data = _extract(scratch, SPR_X, SPR_Y, SPR_W, SPR_H)
        out[name] = (data, _runs(data, SPR_W, SPR_H))
    scratch.fill(KEY)
    _draw_bucket(scratch)
    bdata = _extract(scratch, BKT_X, BKT_Y, BKT_W, BKT_H)
    _bucket_sprite = (bdata, _runs(bdata, BKT_W, BKT_H))
    _sprites = out


class Figure:
    """Holds the smoothed body state. show.py feeds intent; update()
    advances the easing; pose() returns every joint; draw() paints."""

    def __init__(self):
        self.feet_x, self.feet_y = HOME_FEET
        self.body_x, self.body_y = HOME_FEET  # drawn body origin
        self.sh_x, self.sh_y = HOME_SHOULDER
        self.bend = 0.0          # 0..1, waist bend envelope (dip)
        self.bob = 0.0           # breathing bob, px
        self.bucket_x = BUCKET[0]  # the bucket can be rearranged
        self.intent = {
            "tip": None,         # (x, y) the working hand must reach
            "tool": None,        # "brush" (right hand) | "cloth" |
                                 # "hand" (bare left hand) | None
            "follow": 0.0,
            "tau_ms": 380,
            "bend": 0.0,
            "head_tilt": 0.0,    # -1..1 (carried; head is baked in
                                 # the sprites in v1 - not rendered)
            "lean_in": 0.0,      # 0..1, cuckoo (not in v1 shows)
        }

    def set_intent(self, **kw):
        self.intent.update(kw)

    def update(self, dt_ms, now_ms):
        """Ease the shoulder (and with it the feet) toward
        home + (tip - home) * follow. Exponential lag, tau per phase."""
        tip = self.intent["tip"]
        if tip is not None:
            f = self.intent["follow"]
            des_x = HOME_SHOULDER[0] + (tip[0] - HOME_SHOULDER[0]) * f
            des_y = HOME_SHOULDER[1] + (tip[1] - HOME_SHOULDER[1]) * f
        else:
            des_x, des_y = HOME_SHOULDER
        # keep him on the dial
        lo = clockface.CX - SHOULDER_CLAMP_X
        hi = clockface.CX + SHOULDER_CLAMP_X
        if des_x < lo:
            des_x = lo
        if des_x > hi:
            des_x = hi
        tau = self.intent["tau_ms"]
        k = dt_ms / (tau + dt_ms)  # frame-rate independent-ish easing
        self.sh_x += (des_x - self.sh_x) * k
        self.sh_y += (des_y - self.sh_y) * k
        # The drawn body follows the eased shoulder horizontally
        # in full (he steps sideways), but vertically only within
        # a clamp: the sprite is rigid, so the body rises toward
        # high work by at most 52 px (feet stay on the dial) and
        # never sinks through the floor. pose() derives the arm
        # anchors from this drawn body, so the arms stay glued to
        # the visible shoulders at any reach; the IK clamp absorbs
        # whatever vertical travel the clamp withheld.
        moving = abs(des_x - self.sh_x) + abs(des_y - self.sh_y)
        step_bob = 2.0 if moving > 6 else 0.0
        self.bob = math.sin(now_ms / 900.0) * 1.0 + step_bob  # breathing
        dy = self.sh_y - HOME_SHOULDER[1]
        if dy < -52:
            dy = -52
        if dy > 6:
            dy = 6
        self.body_x = self.sh_x - 4
        self.body_y = HOME_FEET[1] + dy + self.bob
        self.feet_x = self.body_x
        self.feet_y = self.body_y
        # bend eases like the body (its envelope comes from show.py)
        target_bend = self.intent["bend"]
        self.bend += (target_bend - self.bend) * min(1.0, dt_ms / 120.0)

    def _bend_point(self, x, y, bend=None):
        """Rotate a torso/head point about the hip pivot by
        bend * BEND_RAD, leaning toward the bucket side (+x), plus
        the crouch drop. Legs/feet are never passed through here."""
        if bend is None:
            bend = self.bend
        if bend <= 0.001:
            return (x, y)
        hip_x = self.feet_x
        hip_y = self.feet_y - HIP_H
        ang = bend * BEND_RAD
        crouch = bend * 14
        dx = x - hip_x
        dy = y - hip_y
        ca = math.cos(ang)
        sa = math.sin(ang)
        return (hip_x + dx * ca - dy * sa, hip_y + dx * sa + dy * ca + crouch)

    def pose(self):
        """All joints for this frame, as a dict of points. Drawing
        geometry uses the SNAPPED bend (0 or 1 - whichever body
        sprite is on show) so the arm anchors sit exactly on the
        visible torso; the eased bend is reported alongside."""
        bd = 1.0 if self.bend >= 0.5 else 0.0
        # arm anchors sit on the DRAWN body (see update()'s clamp)
        sx, sy = self._bend_point(self.body_x + 4,
                                  self.body_y - SHOULDER_H, bd)
        # shoulders: working side +6x is 'right' (brush), left cloth
        sh_r = (sx + 6, sy)
        sh_l = (sx - 14, sy)
        head = self._bend_point(self.feet_x, self.feet_y - HEAD_H, bd)
        tip = self.intent["tip"]
        tool = self.intent["tool"]
        # default hands: hanging at his sides, at thigh length -
        # ~85 px below and ~35 out from the shoulders, so the
        # fixed arm hangs nearly straight with a soft elbow, hands
        # clear of the legs (a +62 target is only 65 from the
        # shoulder and forces a hard, crossed bend)
        hang_r = (sx + 34, sy + 84)
        hang_l = (sx - 38, sy + 84)
        if bd >= 1.0:
            hang_l = (self.feet_x - 18, self.feet_y - 60)  # knee brace
        hand_r = hang_r
        hand_l = hang_l
        if tip is not None and tool == "brush":
            hand_r = tip
        elif tip is not None and tool in ("cloth", "hand"):
            hand_l = tip
        elb_r = ik(sh_r[0], sh_r[1], hand_r[0], hand_r[1])
        elb_l = ik(sh_l[0], sh_l[1], hand_l[0], hand_l[1])
        return {
            "feet": (self.feet_x, self.feet_y),
            "shoulder_r": sh_r, "shoulder_l": sh_l,
            "elbow_r": (elb_r[0], elb_r[1]), "hand_r": (elb_r[2], elb_r[3]),
            "elbow_l": (elb_l[0], elb_l[1]), "hand_l": (elb_l[2], elb_l[3]),
            "head": head,
            "tool": tool, "bend": self.bend, "bend_draw": bd,
            "sprite": "dip" if bd >= 1.0 else "stand",
            "bucket_x": self.bucket_x,
            "head_tilt": self.intent["head_tilt"],
            "lean_in": self.intent["lean_in"],
        }

    # --- drawing ---

    def draw(self, canvas, pose):
        """One frame of the man onto the frame canvas: bucket
        sprite, body sprite (standing or dip, at the body's current
        offset), then the arms and the tool in the working hand -
        band-window polygons over the blits."""
        prepare()
        # bucket first - he stands in front of it
        bdata, bruns = _bucket_sprite
        _blit_runs(canvas, bdata, bruns, BKT_W,
                   int(pose["bucket_x"]) - BKT_W // 2, BKT_Y)
        # body sprite at the figure's travel offset from home
        ox = int(round(pose["feet"][0])) - HOME_FEET[0]
        oy = int(round(pose["feet"][1])) - HOME_FEET[1]
        data, runs = _sprites[pose["sprite"]]
        _blit_runs(canvas, data, runs, SPR_W, SPR_X + ox, SPR_Y + oy)
        # arms: upper = shirt sleeve, forearm = skin, hand a disc
        for side in ("l", "r"):
            sh = pose["shoulder_" + side]
            el = pose["elbow_" + side]
            ha = pose["hand_" + side]
            _band_poly(canvas, _seg_coords(sh[0], sh[1],
                                           el[0], el[1], 11), SHIRT)
            _band_poly(canvas, _seg_coords(el[0], el[1],
                                           ha[0], ha[1], 9), SKIN)
            _band_ellipse(canvas, ha[0], ha[1], 5, 5, SKIN)
        # the tool in the working hand
        if pose["tool"] == "brush":
            hx, hy = pose["hand_r"]
            _band_poly(canvas, _seg_coords(hx, hy, hx - 4, hy - 13, 4),
                       BRUSH_WOOD)
            _band_ellipse(canvas, hx - 5, hy - 15, 3, 5, PAINT)
        elif pose["tool"] == "cloth":
            hx, hy = pose["hand_l"]
            _band_ellipse(canvas, hx, hy, 9, 7, CLOTH)
