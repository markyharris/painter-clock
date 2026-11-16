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
# DRAWING (Nov 15, 2026, v2 - the rect path; SPEC addendum):
# the v1 keyed-sprite path cost ~4 s a frame on the board: its
# per-frame blit was ~330 Python slice copies, and on this board
# a Python-level drawing op costs ~5-10 ms. So the body is now
# PRE-COMPOSITED at boot (prepare()) into OPAQUE RECTANGLES: for
# each body pose (standing, dip) and each point of a small snap
# grid, one cropped rect holds the dial region it covers with the
# body already drawn over it (the bucket baked in too, where the
# rect reaches it - see the bucket split at the snap grids), all
# composited with C
# framebuf primitives (band blits + poly/ellipse). pose() snaps
# the drawn body to the same grid and derives the arm anchors
# from the SNAPPED body, so the arms stay glued to the visible
# torso. Per frame, draw() is then: a few framebuf->framebuf
# band blits (C) for the rect, plus the two arms as filled
# polygons through the frame canvas's band windows, plus the
# tool. No Python-loop drawing anywhere in the per-frame path.
#
# Contract: prepare() composites over the CURRENT static dial
# layer - the dial must be rendered first (bench_painter and
# main both render_static() before the first frame). prepare()
# fingerprints the dial, so a face switch / dial re-render is
# picked up on the next draw() and the rects rebuilt. The bucket
# is baked into the rects at BUCKET's home place: moving
# figure.bucket_x at runtime (the future rearrangement idle)
# needs a prepare() rebuild to move the drawn bucket - the dip
# TARGET follows bucket_x immediately, the picture would not.
#
# FROSTED GLASS (Nov 15, 2026; SPEC addendum): he stands BEHIND
# frosted glass - the hands are painted ON it and stay crisp
# (show.py composes figure-then-hands, so they always land on
# top). The frost is baked into the rects at prepare(): a pale
# halo pass (the whole silhouette re-drawn at compass offsets in
# a pale frost colour) under the body drawn in veiled colours
# (every body colour mixed toward a pale cool tint). The arms
# and tool, drawn per frame, get the same treatment in draw().
# Strength is the "frost" config key, 0..100, default 55;
# frost=0 skips the halo and uses the raw palette, reproducing
# the sharp v2 picture pixel-for-pixel (the A/B escape hatch,
# and the cuckoo's clear-circle patch will draw the head sharp
# the same way - see _draw_head).
#
# IDLE LIFE (Nov 15, 2026): show.py's routines drive both hands
# through intent tip_l / tip_r (full hang-to-hang paths) and hang
# props on them (intent prop_l / prop_r, cap_off, behind, core,
# watch_min, mug_home, apple_bites, hanky_puff - all copied into
# the pose). Props draw per frame in the veiled palette - they
# are behind his glass too. The one exception is the flyby
# plane (draw_plane): it is in the room, in front of the glass,
# drawn raw and crisp by show.py after the hands.
import math
from array import array

import clockface
import display

# --- rig constants (480-scale, px) ---
HOME_FEET = (240, 446)
SHOULDER_H = 221                 # shoulder height above feet
HEAD_H = 266                     # head centre height above feet
HOME_SHOULDER = (244, HOME_FEET[1] - SHOULDER_H)
BUCKET = (332, 436)
SHOULDER_CLAMP_X = 106           # shoulder may stray this far from home x
HIP_H = 116                      # hip pivot height above feet (the
                                 # bend). v13: was 90 - the hips
                                 # rise (y 356 -> 330), the legs
                                 # lengthen and the torso shortens
                                 # inside the v10 height (see the
                                 # proportions note below)
ARM_L1 = 64                      # upper arm
ARM_L2 = 82                      # forearm + hand - total reach 146
                                 # v14: re-split from v13's 74/72
                                 # at Mark's note - on a human the
                                 # rig's second bone ends at the
                                 # hand holding the tool, and
                                 # elbow-to-fingertips runs ~25-40%
                                 # longer than shoulder-to-elbow
                                 # (the artist canons; bone-for-bone
                                 # the radius alone is ~74% of the
                                 # humerus). 82/64 = +28%. Total
                                 # reach and the clamp are v13's,
                                 # unchanged - only the elbow moves.
REACH_MAX = ARM_L1 + ARM_L2 - 2  # clamp targets to 144
ARM_FLOOR_D = 30                 # update() keeps the drawn
                                 # anchor at least this far from
                                 # the working target: ARM_MIN_D
                                 # plus the rect grid's snap error,
                                 # so the inner clamp below stays
                                 # out of the frontier's way (v14)
ARM_MIN_D = abs(ARM_L1 - ARM_L2)  # 18: targets closer than this
                                 # to the shoulder are inside the
                                 # bones' difference - unreachable;
                                 # ik() lands the hand at this
                                 # distance along the ray instead
BEND_RAD = 0.66                  # waist fold at bend == 1 (~38 deg;
                                 # v10: was 1.02 / ~58 deg - with
                                 # the taller torso's longer lever
                                 # (176 px hip-to-head vs 106) the
                                 # old angle threw his head past
                                 # the bucket and read as a fall,
                                 # not a bend. At 0.66 the head
                                 # lands over the bucket and both
                                 # dips still reach - test_reach)
                                 # v13: kept as-is - the lever is
                                 # 150 px at the new HIP_H and both
                                 # floor grabs re-prove at 0.0.
BODY_RISE = 39                   # the drawn body may rise this far
                                 # toward high work (feet leave the
                                 # floor line upward)...
BODY_SINK = 26                   # ...and sink this far toward low
                                 # work (see update()'s clamp).
                                 # v13: was 20 in v10 (6 in v9).
                                 # The sink is the low frontier's
                                 # only travel: with the shorter
                                 # v13 arms the 6 o'clock distance
                                 # is closed by the body crouching
                                 # the last 6 px, not by arm length
                                 # (see the proportions note).

# TALLER FIGURE (Nov 15, 2026, v10 - Mark: "make him taller. The
# center of the clock arms should be on his chest, not his face."):
# the v9 figure stood 212 px cap-to-boots with his face centre at
# y 259 - the dial pivot (240, 240) landed INSIDE the face ellipse
# (236..282), so the hands' boss sat on his forehead. The growth
# is torso + legs + arms, head art untouched (same ellipse, cap
# and face offsets - the character Mark approved): HEAD_H
# 187 -> 266 (face centre y 259 -> 180), SHOULDER_H 152 -> 221
# (shoulders y 294 -> 225, so the pivot crosses his UPPER CHEST,
# 15 px below the shoulder line), HIP_H 81 -> 90 (hips y 365 ->
# 356), arms 48/47 -> 82/78 (he is taller; his arms grew with
# him - and the longer reach is what lets the cloth and brush
# actually touch the hand tips: the v9 sweep's worst settled
# hand-to-frontier gap was 73 px at the 12 o'clock minute tip,
# the new sweep's is a few px - test_reach.py). Feet and bucket
# do not move: the floor is where it was. Cap top lands at
# y 158 and total height at 291 px: the brief's ~130 / ~340
# estimates would need the head itself ~1.5x taller, which
# would break the approved head - face/shoulders/hips/pivot
# were the priorities and all land on target.
#
# PROPORTIONS REBALANCE (Nov 15, 2026, v13 - Mark, on the v10
# glass: "the proportions are off. The legs need to be taller
# and the torso shorter. Similarly the arms need to be
# shortened to a more appropriate length."): same overall
# height - cap top 158, face centre 180, shoulders 225, feet
# and bucket unmoved - rebalanced inside it. HIP_H 90 -> 116:
# hips y 356 -> 330, torso 131 -> 105 px, legs 90 -> 116 px
# (the leg quads and pelvis in _draw_torso ride on HIP_H, and
# the bend pivot IS HIP_H, so the art and the rig move
# together). Arms 82/78 -> 74/72 (reach 160 -> 146) and
# HANG_DY 152 -> 135: the hanging hands land at mid-thigh
# (y ~360 - hips 330, knees ~390) at ~94% extension.
#
# The honest reach trade: truly natural arms (~115-125 reach)
# were swept first and CANNOT hold the frontier proof - the
# 6 o'clock minute frontier sits ~153 px from the best drawn
# shoulder (the sink clamp is the wall: the boots leave the
# dial below +26), so a 114-reach arm lands 41 px short there
# and the dip/sip floor grabs fail with it. 74/72 is the
# SHORTEST pair that holds the invariant: worst frontier
# error 9.2 px (minute, bottom arc at 168-180 deg, full
# reveal; everything else 0.0), both floor grabs 0.0 at full
# bend - desk-proven in test_reach.py by the v10 method. The
# last 6 px of the low reach come from BODY_SINK 20 -> 26,
# not from bone. BEND_RAD stays 0.66: at the shorter torso's
# 150 px hip-to-head lever the dip re-proves at 0.0 with the
# head landing where v10's dip put it.

# arm anchors and rest targets, relative to the DRAWN body: the
# anchors sit just inside the torso's top corners (the sprite's
# torso spans feet +-24), so the shirt sleeve emerges at the
# shoulder seam and shows against the dial; the hands hang just
# outside the thigh silhouette (legs end at feet +-20) at
# upper-thigh height, on their OWN side. (v1 anchored the arms
# +-10 about the centre with the hands +-36 out: the sleeves lay
# invisibly on the shirt torso, the IK picked the inward elbow,
# and both skin forearms speared out of the belly in an X - the
# scarecrow in Mark's bench photo, Nov 15.)
SHOULDER_DX = 19                 # anchor |x| from the body centre
HANG_OUT = 8                     # hand target this far outboard
                                 # of its shoulder anchor...
HANG_DY = 135                    # ...and this far below it (v13:
                                 # was 152 in v10 - with the hips
                                 # raised to y 330 this puts the
                                 # hanging hands at MID-THIGH,
                                 # ~94% of the shorter arm's
                                 # reach, a soft elbow)

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

# idle-routine prop colours (Nov 15, 2026 - idle life v1). All
# but the plane go through the palette, so the frost veils them
# like the rest of him (they are behind his glass too). The
# plane is in the ROOM, in front of the glass: it is drawn from
# the raw constant below, never the palette, so it stays crisp
# at any frost strength.
HAIR = clockface.rgb565(96, 78, 62)        # grey-brown, cap off
MUG = clockface.rgb565(226, 233, 238)      # pale enamel
MUG_DK = clockface.rgb565(70, 90, 120)     # enamel rim / band
APPLE = clockface.rgb565(196, 48, 40)
APPLE_STEM = clockface.rgb565(90, 64, 40)
PHONE = clockface.rgb565(38, 40, 46)
WATCH_CASE = clockface.rgb565(90, 90, 96)
WATCH_FACE = clockface.rgb565(238, 240, 235)
CORE = clockface.rgb565(222, 205, 165)     # apple core flesh
PLANE_COL = clockface.rgb565(52, 58, 66)   # raw - outside glass

MUG_HOME = (292, 443)   # the enamel mug lives on the floor by
                        # the bucket (bucket spans x 315..349);
                        # drawn there per frame until the sip
                        # routine's hand takes it (see draw())

# --- the palette the draw functions consume ---
# _draw_body / _draw_bucket / Figure.draw never touch the raw
# constants above directly; they index a palette tuple, so
# prepare() can hand them the raw palette (sharp), a veiled one
# (frosted), or a flat halo-colour one (the halo pass).
_P_OV = 0        # overalls
_P_OVDK = 1      # overalls dark (legs)
_P_SHIRT = 2
_P_SKIN = 3
_P_CAP = 4
_P_CAPDK = 5
_P_BOOT = 6
_P_BCOL = 7      # bucket body
_P_BDK = 8       # bucket rim / dark
_P_PAINT = 9     # paint (bucket surface, brush tip)
_P_WOOD = 10     # brush handle
_P_CLOTH = 11    # wiping cloth
_P_HAIR = 12     # idle props (appended - existing indices are
_P_MUG = 13      # baked into the rect code above and must not
_P_MUGDK = 14    # move)
_P_APPLE = 15
_P_STEM = 16
_P_PHONE = 17
_P_WCASE = 18
_P_WFACE = 19
_P_CORE = 20
_RAW_PALETTE = (OVERALLS, OVERALLS_DK, SHIRT, SKIN, CAP, CAP_DK,
                BOOT, BUCKET_COL, BUCKET_DK, PAINT, BRUSH_WOOD,
                CLOTH, HAIR, MUG, MUG_DK, APPLE, APPLE_STEM,
                PHONE, WATCH_CASE, WATCH_FACE, CORE)

# --- frosted glass ---
DEFAULT_FROST = 55               # config "frost" default
FROST_TINT = (224, 235, 246)     # pale cool white, 888 - the veil
                                 # mixes toward this
FROST_HALO = clockface.rgb565(238, 244, 250)   # the halo colour:
                                 # the tint lifted toward white
_HALO_PALETTE = (FROST_HALO,) * len(_RAW_PALETTE)
_VEIL = 0.65                     # colour mix reached at frost=100

_frost = DEFAULT_FROST           # current strength, 0..100
_pal = _RAW_PALETTE              # palette for _frost (set by
                                 # prepare() via _frost_state)
_halo_r = 0                      # halo dilation radius, px


def _mix565(colour, f):
    """A RGB565 colour mixed toward FROST_TINT by f (0..1). The
    mix happens in 888 and converts back through rgb565(); the
    raw palette was built with that same function, so the mix is
    hue-true to the original colours (checked on skin / shirt /
    overalls in the desk previews - they pale and cool, they do
    not shift hue)."""
    if f <= 0.0:
        return colour
    r5 = (colour >> 11) & 0x1F
    g6 = (colour >> 5) & 0x3F
    b5 = colour & 0x1F
    r8 = (r5 << 3) | (r5 >> 2)
    g8 = (g6 << 2) | (g6 >> 4)
    b8 = (b5 << 3) | (b5 >> 2)
    return clockface.rgb565(
        int(r8 + (FROST_TINT[0] - r8) * f + 0.5),
        int(g8 + (FROST_TINT[1] - g8) * f + 0.5),
        int(b8 + (FROST_TINT[2] - b8) * f + 0.5))


def _frost_state(frost):
    """(palette, halo radius) for a frost strength 0..100. At 0:
    the raw palette and no halo - the sharp v2 look, reproduced
    exactly. The radius steps 1 px up to strength 74, 2 px above:
    a 1-2 px soft edge, the prototype's ~2.6 px blur at 880
    scale."""
    if frost <= 0:
        return _RAW_PALETTE, 0
    f = frost / 100.0 * _VEIL
    return tuple(_mix565(c, f) for c in _RAW_PALETTE), \
        (1 if frost < 75 else 2)

# --- the snap grids (drawn-body offsets from HOME_FEET, px) ---
# pose() snaps the eased body offset to the nearest grid point;
# prepare() pre-composites one rect per grid point. Standing gets
# a full grid (he follows the hands all over the dial); the dip
# only ever happens on the short trajectory from the wipe's end
# (near home) to the bucket, so its grid stays small.
#
# SMOOTHNESS PASS (Nov 15, 2026): the v2 steps (30 px x, 26 px
# y) read as teleports on the board - the body visibly jumped
# between snap points mid-stroke. The steps are halved (15 px x,
# 13 px y standing; the dip refined in proportion), capping the
# snap error at 7.5 / 6.5 px. The grid grows 25 -> 74 rects, and
# the memory stays in budget through the BUCKET SPLIT: a
# standing rect whose (halo-padded) body box does not reach the
# bucket box no longer bakes the bucket in - the bucket is
# composited ONCE into a shared rect that draw() stamps first
# (the two boxes never overlap, so the stamp order cannot
# interact). Rects that do reach the bucket - the dip, the
# rightmost standing columns - keep the union compositing.
STAND_XS = (-90, -75, -60, -45, -30, -15, 0, 15, 30, 45, 60, 75, 90)
STAND_YS = (-39, -26, -13, 0, 13, 26)
DIP_XS = (0, 13, 26)
DIP_YS = (-11, 5, 18, 26)
# v10: STAND_YS gains the +13 row and DIP_YS the +18 row - the
# drawn body may now SINK toward low work (BODY_SINK in update())
# as well as rise toward high work, and the grids must cover the
# clamp range or the snap would pin him a row short. The sink is
# half of how the taller figure's brush reaches the 6 o'clock
# frontier (see the rig note at the constants). DIP_YS drops its
# -26 row in exchange: during a fold-in the body has already
# eased most of the way down from any wipe height before the
# bend crosses 0.5 and the dip sprite takes over, and the counts
# land back on v9's (65 stand + 9 dip) - the taller rects cost
# ~1 MB more cache, but prepare() stays at v9's ~4.2 s.
# v13: both grids gain the +26 row for the deeper BODY_SINK -
# the stand goes to 78 rects, the dip to 12, and the dip's
# floor grabs (bucket, mug) re-prove at 0.0 with the body
# allowed all the way down (see the proportions note above).
_GRIDS = {"stand": (STAND_XS, STAND_YS), "dip": (DIP_XS, DIP_YS)}


def _snap(v, grid):
    """Nearest grid value (ties go to the one nearer zero)."""
    best = grid[0]
    bd = abs(v - best)
    for g in grid[1:]:
        d = abs(v - g)
        if d < bd or (d == bd and abs(g) < abs(best)):
            best = g
            bd = d
    return best


def ik(sx, sy, tx, ty, cx=None, hint=None):
    """Two-bone IK. Returns (elbow_x, elbow_y, hand_x, hand_y) with
    the target clamped to REACH_MAX - the arm cannot stretch.
    cx is the body centreline x for the elbow choice (defaults to
    the dial centre): the score prefers the LOWER elbow, with the
    outward term strong enough that a near-vertical hang picks
    the elbow bowing AWAY from the body - at v1's 0.15 weight the
    inward candidate won hanging arms by a few px of "lower" (the
    inward perpendicular dips lower when the arm line leans
    outward), which is half of how the rest pose crossed.

    hint (v10): the arm's previous elbow point. When given, the
    candidate NEARER the hint wins instead of the scored one -
    elbow continuity. The score alone flips its choice whenever
    a moving target carries the two candidates' scores past each
    other, and the elbow then teleports by ~2h in one frame
    (measured up to ~160 px: during the plain minute show, and
    in most idle routines - the hand never jumps, only the fold,
    which is why stills never showed it). Tracking the previous
    elbow keeps one fold branch per arm; the branches only meet
    where the arm is straight (h ~ 0), where switching is free.
    pose() re-seeds with the scored choice at the plain hang, so
    the rest pose is always the approved outward bow."""
    if cx is None:
        cx = clockface.CX
    dx = tx - sx
    dy = ty - sy
    d = math.sqrt(dx * dx + dy * dy)
    if d < 1:
        if dx == 0 and dy == 0:
            dx = 1.0     # target on the anchor: pick a ray
        d = 1
    if d > REACH_MAX:
        tx = sx + dx / d * REACH_MAX
        ty = sy + dy / d * REACH_MAX
        dx = tx - sx
        dy = ty - sy
        d = REACH_MAX
    elif d < ARM_MIN_D:
        # inside the reachable annulus: with unequal bones the
        # hand cannot come closer than |L1 - L2| to the shoulder
        # (v9's 48/47 bones hid this inside 1 px; the v10 bones
        # differ by 4, and the watch routine's wrist target sits
        # ~5 px from its anchor - one step nearer and the cosine
        # rule's h went imaginary and the elbow teleported)
        tx = sx + dx / d * ARM_MIN_D
        ty = sy + dy / d * ARM_MIN_D
        dx = tx - sx
        dy = ty - sy
        d = ARM_MIN_D
    a = (ARM_L1 * ARM_L1 - ARM_L2 * ARM_L2 + d * d) / (2 * d)
    h2 = ARM_L1 * ARM_L1 - a * a
    h = math.sqrt(h2) if h2 > 0 else 0
    ux = dx / d
    uy = dy / d
    mx = sx + ux * a
    my = sy + uy * a
    # two elbow candidates; score like the prototype: prefer the
    # lower elbow, with a real outward bias from the body centre
    e1 = (mx - uy * h, my + ux * h)
    e2 = (mx + uy * h, my - ux * h)

    def score(e):
        return e[1] + abs(e[0] - cx) * 0.5

    if hint is not None:
        d1 = (e1[0] - hint[0]) ** 2 + (e1[1] - hint[1]) ** 2
        d2 = (e2[0] - hint[0]) ** 2 + (e2[1] - hint[1]) ** 2
        elbow = e1 if d1 <= d2 else e2
    else:
        elbow = e1 if score(e1) >= score(e2) else e2
    return (elbow[0], elbow[1], tx, ty)


# --- band-window shape helpers (per-frame arms) ---

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


# --- view-list shape helpers (prepare()-time body drawing) ---
# A "view" is (framebuffer, vx, vy, vh): a real FrameBuffer whose
# (0, 0) sits at canvas coords (vx, vy), vh px tall. The helpers
# take canvas coords and translate per view, skipping views the
# shape doesn't touch - the same band-limiting as _band_poly, but
# over any view list (an empty list while measuring extents,
# a rect's band views at composite time).

# prepare() measures each shape set's extent by calling the
# helpers with an empty view list and _track set: the helpers
# accumulate the union of the shapes' own bounding boxes (a
# filled poly rasterises inside its vertex bbox, an ellipse
# inside cx+-rx / cy+-ry), which is exact for sizing the rects -
# and needs no scratch canvas and no pixel scan at all.
_track = None          # [x0, y0, x1, y1] while measuring


def _track_ext(x0, y0, x1, y1):
    if _track is None:
        return
    if x0 < _track[0]:
        _track[0] = x0
    if y0 < _track[1]:
        _track[1] = y0
    if x1 > _track[2]:
        _track[2] = x1
    if y1 > _track[3]:
        _track[3] = y1


def _poly_v(views, coords, colour):
    minx = 9999
    maxx = -9999
    miny = 9999
    maxy = -9999
    i = 0
    while i < len(coords):
        vx_ = coords[i]
        vy_ = coords[i + 1]
        if vx_ < minx:
            minx = vx_
        if vx_ > maxx:
            maxx = vx_
        if vy_ < miny:
            miny = vy_
        if vy_ > maxy:
            maxy = vy_
        i += 2
    _track_ext(minx, miny, maxx, maxy)
    for fb, vx, vy, vh in views:
        if maxy < vy or miny >= vy + vh:
            continue
        fb.poly(-vx, -vy, coords, colour, True)


def _ellipse_v(views, cx, cy, rx, ry, colour):
    cx = int(round(cx))
    cy = int(round(cy))
    _track_ext(cx - rx, cy - ry, cx + rx, cy + ry)
    for fb, vx, vy, vh in views:
        if cy + ry < vy or cy - ry >= vy + vh:
            continue
        fb.ellipse(cx - vx, cy - vy, rx, ry, colour, True)


def _fill_rect_v(views, x, y, w, h, colour):
    _track_ext(x, y, x + w - 1, y + h - 1)
    for fb, vx, vy, vh in views:
        if y + h <= vy or y >= vy + vh:
            continue
        fb.fill_rect(x - vx, y - vy, w, h, colour)


# --- the body, drawn into a view list (prepare() only) ---
# All three take a palette (see _P_* above): the raw palette
# draws him sharp, a veiled palette frosts him, and the flat
# halo palette draws the frost's halo pass.

def _draw_torso(views, fig, feet, bend, pal, sil=False):
    """The armless body below the neck at `feet` with the given
    bend, in canvas coords. Flat-shaded: boots, legs, overalls +
    bib + straps over a shirt torso - all C framebuf primitives
    through the views. Deterministic in (feet, bend): prepare()
    bakes exactly this into the rects, and pose() derives the
    arm anchors from the same feet/bend, so the arms land on
    the drawn torso.

    sil=True draws ONLY the silhouette: the shapes whose edges
    are the body's outline (boots, legs, pelvis, the shirt
    quad). The overalls bib and the straps lie wholly inside
    that outline, so the frost halo pass - which re-draws the
    silhouette at offsets, per rect - skips them (see the halo
    note at _build_rect)."""
    fx, fy = feet

    def bp(x, y):
        return fig._bend_point(x, y, bend, feet)

    # boots and legs - never bent (the bend is at the waist).
    # The leg tops and the pelvis ride on HIP_H (v10: they were
    # literals cut for HIP_H 81/90-era geometry; deriving them
    # keeps the pelvis on the hip pivot whatever HIP_H is).
    _ellipse_v(views, fx - 10, fy - 2, 12, 5, pal[_P_BOOT])
    _ellipse_v(views, fx + 13, fy - 2, 12, 5, pal[_P_BOOT])
    _poly_v(views, _quad(fx - 19, fy - HIP_H + 4, fx - 5,
                         fy - HIP_H + 4, fx - 6, fy - 2,
                         fx - 20, fy - 2),
            pal[_P_OVDK])
    _poly_v(views, _quad(fx + 5, fy - HIP_H + 4, fx + 19,
                         fy - HIP_H + 4, fx + 20, fy - 2,
                         fx + 6, fy - 2),
            pal[_P_OVDK])
    # pelvis (the torso's bent bottom edge overlaps this)
    _fill_rect_v(views, int(fx) - 20, int(fy) - HIP_H, 40, 14,
                 pal[_P_OV])
    # torso: shirt everywhere, overalls over the lower part, with
    # the bib line at 30% and two straps up to the shoulders
    tl = bp(fx - 24, fy - SHOULDER_H)
    tr = bp(fx + 24, fy - SHOULDER_H)
    bl = bp(fx - 20, fy - HIP_H)
    br = bp(fx + 20, fy - HIP_H)
    _poly_v(views, _quad(tl[0], tl[1], tr[0], tr[1],
                         br[0], br[1], bl[0], bl[1]), pal[_P_SHIRT])
    if sil:
        return
    ml = _lerp(tl, bl, 0.30)
    mr = _lerp(tr, br, 0.30)
    _poly_v(views, _quad(ml[0], ml[1], mr[0], mr[1],
                         br[0], br[1], bl[0], bl[1]), pal[_P_OV])
    for f0 in (0.08, 0.74):     # straps, as fractions along the top
        s0 = _lerp(tl, tr, f0)
        s1 = _lerp(tl, tr, f0 + 0.14)
        b0 = _lerp(ml, mr, f0 + 0.02)
        b1 = _lerp(ml, mr, f0 + 0.12)
        _poly_v(views, _quad(s0[0], s0[1], s1[0], s1[1],
                             b1[0], b1[1], b0[0], b0[1]),
            pal[_P_OV])


def _draw_head(views, fig, feet, bend, pal, sil=False):
    """Neck, head and cap at `feet` with the given bend, drawn
    through the bend transform (the cap tilts with the head in
    the dip - an axis-aligned ellipse there read as a detached
    blob in v1).

    Kept SEPARATE from _draw_torso on purpose, with the palette
    as a parameter: the cuckoo's clear-circle patch (a future
    phase - he leans in and wipes a porthole in the frost) must
    be able to draw the head SHARP whatever the configured
    frost, and this is that path: call it with _RAW_PALETTE and
    no halo pass - exactly the frost=0 treatment - inside the
    wiped circle.

    sil=True draws only the silhouette (neck, head, cap, brim)
    for the frost halo pass - the face is interior detail."""
    fx, fy = feet

    def bp(x, y):
        return fig._bend_point(x, y, bend, feet)

    # neck - bridges head and torso, bends with the torso group
    n0 = bp(fx - 6, fy - HEAD_H + 10)
    n1 = bp(fx + 6, fy - HEAD_H + 10)
    n2 = bp(fx + 7, fy - SHOULDER_H + 8)
    n3 = bp(fx - 7, fy - SHOULDER_H + 8)
    _poly_v(views, _quad(n0[0], n0[1], n1[0], n1[1],
                         n2[0], n2[1], n3[0], n3[1]), pal[_P_SKIN])
    # head and cap (baked into the rects - v1 has no separate
    # head tracking). The cap sits HIGH (Mark, Nov 15): the band
    # ends 8 px above the head centre and the brim 5, so a real
    # forehead shows under it.
    hx, hy = bp(fx, fy - HEAD_H)
    _ellipse_v(views, hx, hy, 20, 23, pal[_P_SKIN])
    c0 = bp(fx - 19, fy - HEAD_H - 22)
    c1 = bp(fx + 19, fy - HEAD_H - 22)
    c2 = bp(fx + 19, fy - HEAD_H - 8)
    c3 = bp(fx - 19, fy - HEAD_H - 8)
    _poly_v(views, _quad(c0[0], c0[1], c1[0], c1[1],
                         c2[0], c2[1], c3[0], c3[1]), pal[_P_CAP])
    b0 = bp(fx - 19, fy - HEAD_H - 8)
    b1 = bp(fx + 20, fy - HEAD_H - 8)
    b2 = bp(fx + 20, fy - HEAD_H - 5)
    b3 = bp(fx - 19, fy - HEAD_H - 5)
    _poly_v(views, _quad(b0[0], b0[1], b1[0], b1[1],
                         b2[0], b2[1], b3[0], b3[1]), pal[_P_CAPDK])
    if sil:
        return
    # the face (Mark, Nov 15): two bold eyes and a simple mouth,
    # in the palette's paint colour - near-black, so it reads at
    # 480 across the dial and still reads through the frost
    # (the veiled paint sits far darker than the veiled skin;
    # on the sharp path it is pure INK). Every point goes
    # through bp, so the face turns with the head in the dip.
    e_l = bp(fx - 7, fy - HEAD_H + 3)
    e_r = bp(fx + 7, fy - HEAD_H + 3)
    _ellipse_v(views, e_l[0], e_l[1], 2, 3, pal[_P_PAINT])
    _ellipse_v(views, e_r[0], e_r[1], 2, 3, pal[_P_PAINT])
    mpts = (bp(fx - 6, fy - HEAD_H + 10), bp(fx, fy - HEAD_H + 12),
            bp(fx + 6, fy - HEAD_H + 10), bp(fx + 6, fy - HEAD_H + 13),
            bp(fx, fy - HEAD_H + 15), bp(fx - 6, fy - HEAD_H + 13))
    _poly_v(views, array("h", [int(round(v)) for p in mpts
                               for v in p]), pal[_P_PAINT])


def _draw_body(views, fig, feet, bend, pal, sil=False):
    """The whole armless body: torso + head, one palette.
    sil=True: silhouette only (the frost halo pass)."""
    _draw_torso(views, fig, feet, bend, pal, sil)
    _draw_head(views, fig, feet, bend, pal, sil)


def _draw_bucket(views, pal, dx=0, dy=0, sil=False):
    bx, by = BUCKET[0] + dx, BUCKET[1] + dy
    _poly_v(views, _quad(bx - 17, by - 12, bx + 17, by - 12,
                         bx + 13, by + 12, bx - 13, by + 12),
            pal[_P_BCOL])
    _ellipse_v(views, bx, by - 12, 17, 5, pal[_P_BDK])
    if not sil:
        # the paint surface sits inside the rim's outline -
        # interior detail, skipped by the halo pass
        _ellipse_v(views, bx, by - 13, 14, 4, pal[_P_PAINT])


# --- rect pre-compositing (once per dial, at boot) ---

_rects = None          # {"stand": {(ox, oy): (bands, baked)},
                       #  "dip": {...}} - bands maps band index ->
                       # (source_fb, blit_x, blit_y); baked says
                       # the bucket is composited into the rect
                       # (False -> draw() stamps _bucket_bands
                       # first; see the grid note above)
_bucket_bands = None   # the shared bucket-only rect's bands
_prep_key = None       # (id(dial canvas), dial fingerprint, frost)


def _dial_fingerprint(dial):
    """A few dial pixels, sampled wide - enough to notice a face
    switch / dial re-render (the painter dial is cream at all of
    these only where nothing is drawn; any other face differs)."""
    p = dial.pixel
    return (p(240, 240), p(100, 100), p(240, 60),
            p(60, 240), p(420, 240), p(240, 430))


def _padded_box(pad=2):
    """The tracked extent, padded and clamped to the dial. The
    pad is 2 px sharp, 2 + the halo radius when frosted, so the
    halo pass is never clipped by the rect's own edge."""
    return (max(0, _track[0] - pad), max(0, _track[1] - pad),
            min(display.WIDTH - 1, _track[2] + pad),
            min(display.HEIGHT - 1, _track[3] + pad))


def _rect_views(dial, rx, ry, w, h):
    """Band views over a fresh rect buffer at canvas (rx, ry),
    with the dial blitted in. Returns (views, bands): the views
    for the shape helpers, and the {band: (fb, bx, by)} mapping
    draw() consumes. Each view's spanned bytes stay far under
    display.py's proven 115,200 B window cap."""
    data = bytearray(w * h * 2)
    views = []
    bands = {}
    b = 0
    while b < display.BANDS:
        y0 = b * display.BAND_H
        r0 = max(ry, y0) - ry
        r1 = min(ry + h, y0 + display.BAND_H) - ry
        if r0 < r1:
            seg = memoryview(data)[r0 * w * 2:r1 * w * 2]
            fb = display.make_framebuffer(seg, w, r1 - r0, w)
            views.append((fb, rx, ry + r0, r1 - r0))
            bands[b] = (fb, rx, (ry + r0) - y0)
        b += 1
    # the dial underneath (C blit from the dial's band windows)
    for fb, vx, vy, vh in views:
        band_y = (vy // display.BAND_H) * display.BAND_H
        win = dial.window(0, band_y, display.WIDTH, display.BAND_H)
        fb.blit(win, -rx, band_y - vy)
    return views, bands


def _build_rect(dial, fig, bend, ox, oy, body_box, bucket_box,
                with_bucket=True):
    """One opaque rect for one grid point: the body shifted by
    (ox, oy), composited as dial -> halo -> [bucket ->] body
    with C primitives only. with_bucket=True (the union path)
    covers the union region of the shifted body and the bucket
    at home; with_bucket=False (the bucket split - the shifted
    body box does not reach the bucket box) makes a body-only
    rect, and draw() stamps the shared bucket rect separately.
    Returns {band_index: (source_fb, blit_x, blit_y)}."""
    bx0, by0, bx1, by1 = body_box
    if with_bucket:
        kx0, ky0, kx1, ky1 = bucket_box
        rx = min(bx0 + ox, kx0)
        ry = min(by0 + oy, ky0)
        w = max(bx1 + ox, kx1) - rx + 1
        h = max(by1 + oy, ky1) - ry + 1
    else:
        rx, ry = bx0 + ox, by0 + oy
        w = bx1 - bx0 + 1
        h = by1 - by0 + 1
    views, bands = _rect_views(dial, rx, ry, w, h)
    # the frost halo: the silhouette drawn at the four CARDINAL
    # offsets in the flat halo colour, so the veiled figure
    # sits in a soft pale glow - the scattered-light edge of a
    # figure behind frosted glass. Prepare-time only. The
    # first frost build drew the WHOLE figure (details and
    # all) at eight compass offsets; with the finer snap grid
    # (74 rects) that took prepare() to 8,763 ms on the board.
    # The halo only needs the outline: sil=True skips every
    # interior shape (bib, straps, face, bucket paint), and
    # four offsets dilate the edge the same at r=1-2 px - the
    # corners give up a single diagonal pixel.
    if _halo_r:
        r = _halo_r
        for dx, dy in ((-r, 0), (r, 0), (0, -r), (0, r)):
            if with_bucket:
                _draw_bucket(views, _HALO_PALETTE, dx, dy, True)
            _draw_body(views, fig,
                       (HOME_FEET[0] + ox + dx,
                        HOME_FEET[1] + oy + dy), bend,
                       _HALO_PALETTE, True)
    # bucket at its home place, then the body at the grid point
    if with_bucket:
        _draw_bucket(views, _pal)
    _draw_body(views, fig, (HOME_FEET[0] + ox, HOME_FEET[1] + oy),
               bend, _pal)
    return bands


def _build_bucket_rect(dial, bucket_box):
    """The shared bucket-only rect for the bucket split: dial ->
    halo -> bucket over the bucket box, composited once per
    prepare() and stamped by draw() under every split body rect
    (their boxes never reach it - see the grid note)."""
    kx0, ky0, kx1, ky1 = bucket_box
    views, bands = _rect_views(dial, kx0, ky0,
                               kx1 - kx0 + 1, ky1 - ky0 + 1)
    if _halo_r:
        r = _halo_r
        for dx, dy in ((-r, 0), (r, 0), (0, -r), (0, r)):
            _draw_bucket(views, _HALO_PALETTE, dx, dy, True)
    _draw_bucket(views, _pal)
    return bands


def prepare(dial=None, frost=None):
    """Pre-composite the body rects (both poses x the snap grid)
    over the current dial layer. Idempotent per dial + frost:
    keyed on the dial canvas, a pixel fingerprint AND the frost
    strength, so a re-rendered dial (face switch) or a frost
    change rebuilds on the next call. Called explicitly by the
    bench runner / boot flow after render_static(), and lazily
    by draw().

    frost: the frosted-glass strength 0..100 (the "frost"
    config key); None keeps the current value. The palette and
    halo radius for the strength are (re)derived on EVERY call,
    cache hit or not, so draw()'s per-frame arms always match
    the baked rects."""
    global _rects, _bucket_bands, _prep_key, _track, _frost, \
        _pal, _halo_r
    if dial is None:
        dial = display.dial()
    if frost is not None:
        if frost < 0:
            frost = 0
        if frost > 100:
            frost = 100
        _frost = int(frost)
    _pal, _halo_r = _frost_state(_frost)
    key = (id(dial), _dial_fingerprint(dial), _frost)
    if _rects is not None and _prep_key == key:
        return
    # content bboxes first: body per pose + bucket, measured at
    # home by extent tracking (no drawing, no scratch canvas);
    # the pad leaves room for the halo pass around the shapes
    pad = 2 + _halo_r
    fig = Figure()
    body_box = {}
    for name, bend in (("stand", 0.0), ("dip", 1.0)):
        _track = [9999, 9999, -9999, -9999]
        _draw_body((), fig, HOME_FEET, bend, _RAW_PALETTE)
        body_box[name] = _padded_box(pad)
    _track = [9999, 9999, -9999, -9999]
    _draw_bucket((), _RAW_PALETTE)
    bucket_box = _padded_box(pad)
    _track = None
    rects = {}
    bucket_bands = None
    for name, bend in (("stand", 0.0), ("dip", 1.0)):
        xs, ys = _GRIDS[name]
        bb = body_box[name]
        per = {}
        for oy in ys:
            for ox in xs:
                # the bucket split: bake the bucket into the
                # rect only when the shifted (halo-padded) body
                # box reaches the bucket box - always true for
                # the dip (he leans over the bucket), and for
                # the rightmost standing columns
                baked = name == "dip" or (
                    bb[0] + ox <= bucket_box[2]
                    and bucket_box[0] <= bb[2] + ox
                    and bb[1] + oy <= bucket_box[3]
                    and bucket_box[1] <= bb[3] + oy)
                per[(ox, oy)] = (_build_rect(dial, fig, bend,
                                             ox, oy, bb,
                                             bucket_box, baked),
                                 baked)
                if not baked and bucket_bands is None:
                    bucket_bands = _build_bucket_rect(dial,
                                                      bucket_box)
        rects[name] = per
    _rects = rects
    _bucket_bands = bucket_bands
    _prep_key = key


class Figure:
    """Holds the smoothed body state. show.py feeds intent; update()
    advances the easing; pose() returns every joint (with the
    drawn body SNAPPED to the rect grid); draw() paints."""

    def __init__(self):
        self.feet_x, self.feet_y = HOME_FEET
        self.body_x, self.body_y = HOME_FEET  # drawn body origin
        self.sh_x, self.sh_y = HOME_SHOULDER
        self._elb_hint = {"l": None, "r": None}  # elbow continuity
                                 # (see ik's hint): the last elbow
                                 # point per arm, tracked by pose()
        self.bend = 0.0          # 0..1, waist bend envelope (dip)
        self.bob = 0.0           # breathing bob, px
        self.bucket_x = BUCKET[0]  # the bucket can be rearranged
        self.dial = None         # the static-layer canvas, if a
                                 # caller (Show) knows it; prepare()
                                 # falls back to display.dial()
        self.intent = {
            "tip": None,         # (x, y) the working hand must reach
            "tool": None,        # "brush" (right hand) | "cloth" |
                                 # "hand" (bare left hand) | None
            "sway_x": 0.0,       # standing weight-rock offset, px
                                 # (v10: show.py's oscillator feeds
                                 # this between shows; the desired
                                 # shoulder shifts by it, so the
                                 # body rocks leg to leg and the
                                 # arms re-hang off the shoulders)
            "follow": 0.0,
            "tau_ms": 380,
            "bend": 0.0,
            "head_tilt": 0.0,    # -1..1 (carried; head is baked in
                                 # the rects in v1 - not rendered)
            "lean_in": 0.0,      # 0..1, cuckoo (not in v1 shows)
            # idle-life fields (Nov 15, 2026): show.py's routines
            # drive BOTH hands explicitly and hang props on them.
            # tip_l / tip_r override the hang (and the show tip)
            # per hand; the rest is draw state pose() copies out.
            "tip_l": None,       # explicit left-hand target
            "tip_r": None,       # explicit right-hand target
            "prop_l": None,      # in the left hand: "watch" |
                                 # "apple" | "hanky" | None
            "prop_r": None,      # in the right hand: "cap" |
                                 # "mug" | "phone" | None
            "cap_off": False,    # hair patch over the baked cap
            "behind": None,      # "l" | "r": that arm is drawn
                                 # BEFORE the body rect, so the
                                 # torso occludes it (rear scratch)
            "core": None,        # tossed apple core (x, y) | None
            "watch_min": None,   # total minutes for the wristwatch
            "mug_home": True,    # the mug sits on the floor
            "apple_bites": 0,    # 0..2 notches punched in the apple
            "hanky_puff": 0.0,   # 0..1, the nose-blow pulse
        }

    def set_intent(self, **kw):
        self.intent.update(kw)

    def update(self, dt_ms, now_ms):
        """Ease the shoulder (and with it the feet) toward
        home + (tip - home) * follow. Exponential lag, tau per phase."""
        tip = self.intent["tip"]
        if tip is None:
            # idle routines drive the hands through tip_r / tip_l:
            # the body still leans toward the working hand (the
            # sip's step toward the bucket rides on this)
            tip = self.intent["tip_r"] or self.intent["tip_l"]
        if tip is not None:
            f = self.intent["follow"]
            des_x = HOME_SHOULDER[0] + (tip[0] - HOME_SHOULDER[0]) * f
            des_y = HOME_SHOULDER[1] + (tip[1] - HOME_SHOULDER[1]) * f
        else:
            des_x, des_y = HOME_SHOULDER
        des_x += self.intent["sway_x"]
        # keep him on the dial
        lo = clockface.CX - SHOULDER_CLAMP_X
        hi = clockface.CX + SHOULDER_CLAMP_X
        if des_x < lo:
            des_x = lo
        if des_x > hi:
            des_x = hi
        if tip is not None:
            # v14: keep the working arm out of its own dead
            # zone. The arm's reachable set is the annulus
            # [ARM_MIN_D, REACH_MAX]; v13's near-equal bones
            # (74/72) made the inner edge 2 px and invisible,
            # but the 64/82 re-split puts it at 18 - and the
            # follow happily parks the shoulder ON a near
            # frontier (mid-stroke targets sit close to the
            # dial centre), where ik() must push the hand out
            # to 18 px along the ray and it overshoots the
            # frontier by that much (sweep: 15.9 px at reveal
            # 0.5, 9-10 o'clock). So the BODY keeps its
            # distance instead: predict the drawn anchor from
            # the desired body (bend is 0 wherever a frontier
            # matters; routines lean at small follow with far
            # targets) and push the desired body straight away
            # from the tip until the anchor is ARM_FLOOR_D
            # out - the margin over ARM_MIN_D covers the rect
            # grid's snap error (~10 px worst case).
            if self.intent["tip"] is not None:
                sdx = SHOULDER_DX if self.intent["tool"] == "brush" \
                    else -SHOULDER_DX
            elif self.intent["tip_r"] is not None:
                sdx = SHOULDER_DX
            else:
                sdx = -SHOULDER_DX
            pdy = des_y - HOME_SHOULDER[1]
            if pdy < -BODY_RISE:
                pdy = -BODY_RISE
            if pdy > BODY_SINK:
                pdy = BODY_SINK
            ax = des_x - 4 + sdx
            ay = HOME_FEET[1] + pdy - SHOULDER_H
            dx = tip[0] - ax
            dy = tip[1] - ay
            d = math.sqrt(dx * dx + dy * dy)
            if d < ARM_FLOOR_D:
                if d < 0.1:
                    des_y -= ARM_FLOOR_D   # on the tip: rise off it
                else:
                    push = (ARM_FLOOR_D - d) / d
                    des_x -= dx * push
                    des_y -= dy * push
        tau = self.intent["tau_ms"]
        k = dt_ms / (tau + dt_ms)  # frame-rate independent-ish easing
        self.sh_x += (des_x - self.sh_x) * k
        self.sh_y += (des_y - self.sh_y) * k
        # The drawn body follows the eased shoulder horizontally
        # in full (he steps sideways), but vertically only within
        # a clamp: the body is rigid, so it rises toward high work
        # by at most BODY_RISE px and sinks toward low work by at
        # most BODY_SINK (v13: 26 px - the 6 o'clock frontier
        # needs the crouch even more with the shorter arms; at
        # full sink his boot soles just cross the cream's edge
        # into the shade ring, transiently, while he works the
        # lowest strokes). pose() derives the arm
        # anchors from this drawn body (snapped to the rect grid),
        # so the arms stay glued to the visible shoulders at any
        # reach; the IK clamp absorbs whatever travel the clamp
        # withheld.
        moving = abs(des_x - self.sh_x) + abs(des_y - self.sh_y)
        step_bob = 2.0 if moving > 6 else 0.0
        self.bob = math.sin(now_ms / 900.0) * 1.0 + step_bob  # breathing
        dy = self.sh_y - HOME_SHOULDER[1]
        if dy < -BODY_RISE:
            dy = -BODY_RISE
        if dy > BODY_SINK:
            dy = BODY_SINK
        self.body_x = self.sh_x - 4
        self.body_y = HOME_FEET[1] + dy + self.bob
        self.feet_x = self.body_x
        self.feet_y = self.body_y
        # bend eases like the body (its envelope comes from show.py)
        target_bend = self.intent["bend"]
        self.bend += (target_bend - self.bend) * min(1.0, dt_ms / 120.0)

    def _bend_point(self, x, y, bend=None, feet=None):
        """Rotate a torso/head point about the hip pivot by
        bend * BEND_RAD, leaning toward the bucket side (+x), plus
        the crouch drop. Legs/feet are never passed through here.
        `feet` is the body the point belongs to (the snapped drawn
        body in pose(), the grid body in prepare())."""
        if bend is None:
            bend = self.bend
        if feet is None:
            feet = (self.feet_x, self.feet_y)
        if bend <= 0.001:
            return (x, y)
        hip_x = feet[0]
        hip_y = feet[1] - HIP_H
        ang = bend * BEND_RAD
        crouch = bend * 14
        dx = x - hip_x
        dy = y - hip_y
        ca = math.cos(ang)
        sa = math.sin(ang)
        return (hip_x + dx * ca - dy * sa, hip_y + dx * sa + dy * ca + crouch)

    def pose(self):
        """All joints for this frame, as a dict of points. The
        drawn body is SNAPPED to the rect grid (the (ox, oy) in
        "snap"); the arm anchors sit on the snapped torso - each
        shoulder anchor bend-transformed from its own corner, so
        it tracks the drawn top edge - and the IK targets stay
        continuous (the working hand still tracks the stroke
        frontier exactly). The eased bend is reported alongside
        its snapped draw value."""
        bd = 1.0 if self.bend >= 0.5 else 0.0
        sprite = "dip" if bd >= 1.0 else "stand"
        xs, ys = _GRIDS[sprite]
        sox = _snap(self.body_x - HOME_FEET[0], xs)
        soy = _snap(self.body_y - HOME_FEET[1], ys)
        feet = (HOME_FEET[0] + sox, HOME_FEET[1] + soy)
        fx, fy = feet
        # shoulders: working side +x is 'right' (brush), left cloth
        sh_r = self._bend_point(fx + SHOULDER_DX,
                                fy - SHOULDER_H, bd, feet)
        sh_l = self._bend_point(fx - SHOULDER_DX,
                                fy - SHOULDER_H, bd, feet)
        head = self._bend_point(fx, fy - HEAD_H, bd, feet)
        tip = self.intent["tip"]
        tool = self.intent["tool"]
        # default hands: hanging at his sides - just outboard of
        # each shoulder anchor, at upper-thigh height, so the arm
        # hangs nearly straight with a soft outward elbow, hands
        # hugging his own thighs
        hang_r = (sh_r[0] + HANG_OUT, sh_r[1] + HANG_DY)
        hang_l = (sh_l[0] - HANG_OUT, sh_l[1] + HANG_DY)
        if bd >= 1.0:
            # knee brace: on the thigh above the knee (derived
            # from HIP_H - the thigh's upper third)
            hang_l = (fx - 18, fy - HIP_H + 30)
        hand_r = hang_r
        hand_l = hang_l
        if tip is not None and tool == "brush":
            hand_r = tip
        elif tip is not None and tool in ("cloth", "hand"):
            hand_l = tip
        # idle routines override per hand (their targets span the
        # whole routine, hang to hang, so nothing ever teleports)
        over_r = tip is not None and tool == "brush"
        over_l = tip is not None and tool in ("cloth", "hand")
        if self.intent["tip_r"] is not None:
            hand_r = self.intent["tip_r"]
            over_r = True
        if self.intent["tip_l"] is not None:
            hand_l = self.intent["tip_l"]
            over_l = True
        # elbow continuity (ik's hint): track each arm's fold
        # branch while it is working; at the plain hang (no
        # override, no bend) re-seed from the score, so the rest
        # pose always returns to the approved outward bow
        hint_r = self._elb_hint["r"] if over_r or bd >= 1.0 \
            else None
        hint_l = self._elb_hint["l"] if over_l or bd >= 1.0 \
            else None
        elb_r = ik(sh_r[0], sh_r[1], hand_r[0], hand_r[1], fx,
                   hint_r)
        elb_l = ik(sh_l[0], sh_l[1], hand_l[0], hand_l[1], fx,
                   hint_l)
        self._elb_hint["r"] = (elb_r[0], elb_r[1])
        self._elb_hint["l"] = (elb_l[0], elb_l[1])
        return {
            "feet": feet,
            "shoulder_r": sh_r, "shoulder_l": sh_l,
            "elbow_r": (elb_r[0], elb_r[1]), "hand_r": (elb_r[2], elb_r[3]),
            "elbow_l": (elb_l[0], elb_l[1]), "hand_l": (elb_l[2], elb_l[3]),
            "head": head,
            "tool": tool, "bend": self.bend, "bend_draw": bd,
            "sprite": sprite,
            "snap": (sox, soy),
            "bucket_x": self.bucket_x,
            "head_tilt": self.intent["head_tilt"],
            "lean_in": self.intent["lean_in"],
            # idle draw state, copied through for draw()
            "prop_l": self.intent["prop_l"],
            "prop_r": self.intent["prop_r"],
            "cap_off": self.intent["cap_off"],
            "behind": self.intent["behind"],
            "core": self.intent["core"],
            "watch_min": self.intent["watch_min"],
            "mug_home": self.intent["mug_home"],
            "apple_bites": self.intent["apple_bites"],
            "hanky_puff": self.intent["hanky_puff"],
        }

    # --- drawing ---

    def _draw_arm(self, canvas, pose, side, pal, hr):
        """One arm: [halo,] upper = shirt sleeve, forearm = skin,
        hand a disc - all in the given palette."""
        sh = pose["shoulder_" + side]
        el = pose["elbow_" + side]
        ha = pose["hand_" + side]
        if hr:
            _band_poly(canvas, _seg_coords(sh[0], sh[1],
                                           el[0], el[1],
                                           11 + 2 * hr),
                       FROST_HALO)
            _band_poly(canvas, _seg_coords(el[0], el[1],
                                           ha[0], ha[1],
                                           9 + 2 * hr),
                       FROST_HALO)
        _band_poly(canvas, _seg_coords(sh[0], sh[1],
                                       el[0], el[1], 11),
                   pal[_P_SHIRT])
        _band_poly(canvas, _seg_coords(el[0], el[1],
                                       ha[0], ha[1], 9),
                   pal[_P_SKIN])
        _band_ellipse(canvas, ha[0], ha[1], 5, 5, pal[_P_SKIN])

    def draw(self, canvas, pose):
        """One frame of the man onto the frame canvas: the
        pre-composited body rect for the pose's snapped grid
        point (framebuf->framebuf band blits, C), then the arms
        and the tool in the working hand - band-window polygons
        over the blit. Upper arm is the shirt sleeve, forearm and
        hand are skin. Frost: a halo poly (segment widened by the
        halo radius each side, flat frost colour) under each arm
        segment, and every colour from the veiled palette
        prepare() selected - at frost=0 the halo pass vanishes
        and the palette is the raw one, so the frame is v2's.

        Idle-life order (Nov 15, 2026): the "behind" arm and the
        floor mug go down BEFORE the bucket stamp and body rect,
        so the opaque rect occludes them (the rear scratch hides
        behind his torso; the mug hides behind his boots when he
        stands where it lives). Then the hair patch (cap off),
        the front arm(s), the tool, and the held props."""
        prepare(self.dial)
        pal = _pal
        hr = _halo_r
        behind = pose["behind"]
        if behind is not None:
            self._draw_arm(canvas, pose, behind, pal, hr)
        if pose["mug_home"]:
            _draw_mug(canvas, MUG_HOME[0], MUG_HOME[1], pal)
        bands, baked = _rects[pose["sprite"]][pose["snap"]]
        if not baked:
            # bucket split: this rect is body-only - stamp the
            # shared bucket rect first (the two boxes are
            # disjoint, so the stamp cannot interact with the
            # body rect that follows)
            for win, y0 in canvas.band_windows():
                hit = _bucket_bands.get(y0 // display.BAND_H)
                if hit is not None:
                    src, bx, by = hit
                    win.blit(src, bx, by)
        for win, y0 in canvas.band_windows():
            hit = bands.get(y0 // display.BAND_H)
            if hit is not None:
                src, bx, by = hit
                win.blit(src, bx, by)
        if pose["cap_off"]:
            # hair over the baked cap: an ellipse patch on the
            # head's cap zone (cap band + brim live at head
            # centre -22..-5, +-20 wide - see _draw_head)
            hx, hy = pose["head"]
            _band_ellipse(canvas, hx, hy - 10, 20, 13, pal[_P_HAIR])
            _band_ellipse(canvas, hx, hy - 13, 15, 9, pal[_P_HAIR])
        for side in ("l", "r"):
            if side != behind:
                self._draw_arm(canvas, pose, side, pal, hr)
        # the tool in the working hand (veiled like the rest)
        if pose["tool"] == "brush":
            hx, hy = pose["hand_r"]
            _band_poly(canvas, _seg_coords(hx, hy, hx - 4, hy - 13, 4),
                       pal[_P_WOOD])
            _band_ellipse(canvas, hx - 5, hy - 15, 3, 5, pal[_P_PAINT])
        elif pose["tool"] == "cloth":
            hx, hy = pose["hand_l"]
            _band_ellipse(canvas, hx, hy, 9, 7, pal[_P_CLOTH])
        # idle props, in the hands (and one on the wrist)
        if pose["prop_l"] == "watch":
            _draw_watch(canvas, pose, pal)
        elif pose["prop_l"] == "apple":
            _draw_apple(canvas, pose["hand_l"], pose["apple_bites"],
                        pal)
        elif pose["prop_l"] == "hanky":
            _draw_hanky(canvas, pose["hand_l"], pose["hanky_puff"],
                        pal)
        if pose["prop_r"] == "cap":
            hx, hy = pose["hand_r"]
            _draw_cap_prop(canvas, hx, hy + 6, pal)
        elif pose["prop_r"] == "mug":
            _draw_mug(canvas, pose["hand_r"][0],
                      pose["hand_r"][1] - 2, pal)
        elif pose["prop_r"] == "phone":
            hx, hy = pose["hand_r"]
            _band_poly(canvas, _quad(hx - 3, hy - 13, hx + 6, hy - 11,
                                     hx + 8, hy + 3, hx - 1, hy + 1),
                       pal[_P_PHONE])
        if pose["core"] is not None:
            cx, cy = pose["core"]
            _band_ellipse(canvas, cx, cy, 3, 5, pal[_P_CORE])
            _band_poly(canvas, _seg_coords(cx, cy - 4, cx + 1,
                                           cy - 8, 2),
                       pal[_P_STEM])


# --- idle prop drawing (per frame, palette colours - veiled) ---

def _draw_mug(canvas, x, y, pal):
    """The enamel mug, its base at (x, y): body, rim, handle.
    Used on the floor at MUG_HOME and in the right hand."""
    x = int(round(x))
    y = int(round(y))
    for win, y0 in canvas.band_windows():
        if y < y0 or y - 13 >= y0 + display.BAND_H:
            continue
        win.fill_rect(x - 6, y - 12 - y0, 12, 12, pal[_P_MUG])
        win.ellipse(x, y - 12 - y0, 6, 2, pal[_P_MUGDK], True)
    _band_poly(canvas, _seg_coords(x + 7, y - 10, x + 7, y - 3, 3),
               pal[_P_MUGDK])


def _draw_watch(canvas, pose, pal):
    """The wristwatch on the left wrist: case + face at the
    wrist (a little up the forearm from the hand), and two
    hands showing the PAINTED time - pose["watch_min"] is the
    dial's total minutes, so his watch agrees with the clock
    he is painting (the prototype's joke)."""
    hx, hy = pose["hand_l"]
    ex, ey = pose["elbow_l"]
    dx = hx - ex
    dy = hy - ey
    d = math.sqrt(dx * dx + dy * dy)
    if d < 1:
        d = 1
    wx = hx - dx / d * 11
    wy = hy - dy / d * 11
    _band_ellipse(canvas, wx, wy, 7, 7, pal[_P_WCASE])
    _band_ellipse(canvas, wx, wy, 5, 5, pal[_P_WFACE])
    total = pose["watch_min"]
    if total is not None:
        for ang, ln in ((clockface.hour_angle_stepped(total), 3),
                        (clockface.minute_angle(total), 4)):
            a = math.radians(ang)
            _band_poly(canvas,
                       _seg_coords(wx, wy, wx + math.sin(a) * ln,
                                   wy - math.cos(a) * ln, 1),
                       pal[_P_PAINT])


def _draw_apple(canvas, hand, bites, pal):
    """The apple in the left hand, with 0..2 bite notches
    punched in dial cream over its upper edge (the punches are
    clockface.CREAM - the dial's own colour)."""
    hx, hy = hand
    _band_ellipse(canvas, hx, hy - 4, 7, 6, pal[_P_APPLE])
    _band_poly(canvas, _seg_coords(hx, hy - 9, hx + 2, hy - 13, 2),
               pal[_P_STEM])
    if bites >= 1:
        _band_ellipse(canvas, hx - 6, hy - 8, 3, 3,
                      clockface.CREAM)
    if bites >= 2:
        _band_ellipse(canvas, hx + 5, hy - 9, 3, 3,
                      clockface.CREAM)


def _draw_hanky(canvas, hand, puff, pal):
    """The hanky at the left hand: a soft white blob that
    swells with the blow (puff 0..1), with a hanging corner."""
    hx, hy = hand
    r = 8 + int(4 * puff + 0.5)
    _band_ellipse(canvas, hx, hy - 2, r, r - 2, pal[_P_CLOTH])
    _band_poly(canvas, _quad(hx - 4, hy + 3, hx + 3, hy + 3,
                             hx + 1, hy + 10, hx - 2, hy + 10),
               pal[_P_CLOTH])


def _draw_cap_prop(canvas, x, y, pal):
    """His cap, held in the right hand at (x, y): the band as a
    shallow dome with the brim sticking out front."""
    x = int(round(x))
    y = int(round(y))
    _band_ellipse(canvas, x, y, 11, 6, pal[_P_CAP])
    _band_poly(canvas, _quad(x - 11, y, x + 12, y, x + 12, y + 3,
                             x - 11, y + 3), pal[_P_CAPDK])


def draw_plane(canvas, x, y):
    """The flyby plane, drawn by show.py AFTER the hands: it is
    in the room, in front of the glass, so it uses the raw
    PLANE_COL and stays crisp at any frost. A small high-wing
    silhouette ~36 px wide, nose to the right, prop disc at the
    nose. (x, y) is the fuselage centre."""
    _band_ellipse(canvas, x, y, 17, 4, PLANE_COL)
    _band_poly(canvas, _quad(x - 4, y - 3, x + 6, y - 3,
                             x + 9, y - 9, x - 1, y - 9), PLANE_COL)
    _band_poly(canvas, _quad(x - 17, y - 1, x - 12, y - 1,
                             x - 10, y - 7, x - 15, y - 7), PLANE_COL)
    _band_ellipse(canvas, x + 18, y, 2, 6, PLANE_COL)
