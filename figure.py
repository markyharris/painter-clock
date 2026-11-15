# figure.py - the little man's rig: body-follow, two-bone IK arms,
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
# Drawing here is deliberately plain (rects/ellipses/lines in body
# colours). The production look - a pre-blurred body sprite with
# bend-angle variants, pre-blurred brush/cloth sprites, and the one
# sharp face sprite for the cuckoo porthole - drops into draw()
# where the TODOs sit, once Sunday's frame-rate numbers are known
# (SPEC.md 4.2/4.3). Plain keyed blits only when sprites land:
# framebuf palette blits draw nothing on v1.29 ESP32.
import math

import clockface

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

# colours (RGB565 via clockface.rgb565)
OVERALLS = clockface.rgb565(51, 80, 126)
OVERALLS_DK = clockface.rgb565(38, 60, 96)
SKIN = clockface.rgb565(201, 161, 137)
CAP = clockface.rgb565(39, 66, 102)
CLOTH = clockface.rgb565(216, 212, 204)
BRUSH_WOOD = clockface.rgb565(138, 107, 69)
BUCKET_COL = clockface.rgb565(107, 111, 117)
PAINT = clockface.INK


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


class Figure:
    """Holds the smoothed body state. show.py feeds intent; update()
    advances the easing; pose() returns every joint; draw() paints."""

    def __init__(self):
        self.feet_x, self.feet_y = HOME_FEET
        self.sh_x, self.sh_y = HOME_SHOULDER
        self.bend = 0.0          # 0..1, waist bend envelope (dip/cuckoo)
        self.bob = 0.0           # breathing bob, px
        self.intent = {
            "tip": None,         # (x, y) the working hand must reach
            "tool": None,        # "brush" | "cloth" | None
            "follow": 0.0,
            "tau_ms": 380,
            "bend": 0.0,
            "head_tilt": 0.0,    # -1..1
            "lean_in": 0.0,      # 0..1, cuckoo: head toward the glass
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
        # feet follow the shoulder - he steps; add the stepping bob
        self.feet_x = self.sh_x - 4
        moving = abs(des_x - self.sh_x) + abs(des_y - self.sh_y)
        step_bob = 2.0 if moving > 6 else 0.0
        self.bob = math.sin(now_ms / 900.0) * 1.0 + step_bob  # breathing
        self.feet_y = HOME_FEET[1] + self.bob
        # bend eases like the body (its envelope comes from show.py)
        target_bend = self.intent["bend"]
        self.bend += (target_bend - self.bend) * min(1.0, dt_ms / 120.0)

    def _bend_point(self, x, y):
        """Rotate a torso/head point about the hip pivot by
        bend * 1.02 rad, leaning toward the bucket side (+x), plus
        the crouch drop. Legs/feet are never passed through here."""
        if self.bend <= 0.001:
            return (x, y)
        hip_x = self.feet_x
        hip_y = self.feet_y - HIP_H
        ang = self.bend * 1.02
        crouch = self.bend * 14
        dx = x - hip_x
        dy = y - hip_y
        ca = math.cos(ang)
        sa = math.sin(ang)
        return (hip_x + dx * ca - dy * sa, hip_y + dx * sa + dy * ca + crouch)

    def pose(self):
        """All joints for this frame, as a dict of points."""
        sx, sy = self._bend_point(self.sh_x, self.sh_y)
        # shoulders: working side +4x is 'right' (brush), left is cloth
        sh_r = (sx + 6, sy)
        sh_l = (sx - 14, sy)
        head = self._bend_point(self.feet_x, self.feet_y - HEAD_H)
        tip = self.intent["tip"]
        tool = self.intent["tool"]
        # default hands: hanging at his sides
        hang_r = (self.sh_x + 26, self.sh_y + 62)
        hang_l = (self.sh_x - 30, self.sh_y + 62)
        if self.bend > 0.5:
            hang_l = (self.feet_x - 18, self.feet_y - 60)  # knee brace
        hand_r = hang_r
        hand_l = hang_l
        if tip is not None and tool == "brush":
            hand_r = tip
        elif tip is not None and tool == "cloth":
            hand_l = tip
        elb_r = ik(sh_r[0], sh_r[1], hand_r[0], hand_r[1])
        elb_l = ik(sh_l[0], sh_l[1], hand_l[0], hand_l[1])
        return {
            "feet": (self.feet_x, self.feet_y),
            "shoulder_r": sh_r, "shoulder_l": sh_l,
            "elbow_r": (elb_r[0], elb_r[1]), "hand_r": (elb_r[2], elb_r[3]),
            "elbow_l": (elb_l[0], elb_l[1]), "hand_l": (elb_l[2], elb_l[3]),
            "head": head,
            "tool": tool, "bend": self.bend,
            "head_tilt": self.intent["head_tilt"],
            "lean_in": self.intent["lean_in"],
        }

    # --- drawing (placeholder shapes; sprites land Sunday) ---

    def draw(self, fb, pose):
        fx, fy = pose["feet"]
        # bucket first - he stands in front of it
        fb.fill_rect(BUCKET[0] - 16, BUCKET[1] - 12, 32, 24, BUCKET_COL)
        fb.fill_rect(BUCKET[0] - 16, BUCKET[1] - 12, 32, 5, PAINT)
        # legs (never bent - the bend is at the waist)
        fb.fill_rect(int(fx) - 16, int(fy) - 62, 13, 62, OVERALLS_DK)
        fb.fill_rect(int(fx) + 4, int(fy) - 62, 13, 62, OVERALLS_DK)
        # TODO(Sunday): body = pre-blurred sprite blit here, picked
        # from the bend-angle variant set when bend > 0 (SPEC 4.2).
        # Torso: shoulder line down to the hip pivot
        hip_y = fy - HIP_H
        sx = (pose["shoulder_l"][0] + pose["shoulder_r"][0]) / 2
        sy = (pose["shoulder_l"][1] + pose["shoulder_r"][1]) / 2
        clockface.thick_line(fb, int(sx), int(sy), int(fx), int(hip_y),
                             34, OVERALLS)
        # arms: upper = sleeve blue, forearm = skin
        for side in ("r", "l"):
            sh = pose["shoulder_" + side]
            el = pose["elbow_" + side]
            ha = pose["hand_" + side]
            clockface.thick_line(fb, int(sh[0]), int(sh[1]),
                                 int(el[0]), int(el[1]), 11, OVERALLS)
            clockface.thick_line(fb, int(el[0]), int(el[1]),
                                 int(ha[0]), int(ha[1]), 9, SKIN)
        # head + cap (tilt shifts the cap a touch)
        hx, hy = pose["head"]
        tilt = pose["head_tilt"] * 4
        fb.ellipse(int(hx), int(hy), 17, 19, SKIN, True)
        fb.ellipse(int(hx + tilt), int(hy) - 12, 18, 8, CAP, True)
        # TODO(Sunday): sharp face variant of the head sprite, drawn
        # ONLY inside the cuckoo porthole (SPEC 4.3).
        # tools in the working hand
        if pose["tool"] == "brush":
            hx2, hy2 = pose["hand_r"]
            fb.line(int(hx2), int(hy2), int(hx2) + 4, int(hy2) - 12,
                    BRUSH_WOOD)
            fb.fill_rect(int(hx2) + 2, int(hy2) - 16, 5, 6, PAINT)
        elif pose["tool"] == "cloth":
            hx2, hy2 = pose["hand_l"]
            fb.ellipse(int(hx2), int(hy2), 9, 7, CLOTH, True)
