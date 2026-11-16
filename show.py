# show.py - the choreography state machine.
#
# Owns: the minute show (glance -> wipe -> dip -> paint -> inspect),
# the hour-hand steps every 12 minutes, and the idle routines
# between shows. Per frame it drives:
#   * hand states (angle + reveal per hand) into clockface.compose
#     via its state overrides
#   * figure intent (tip / tool / follow / bend / ...) for figure.py
# One stroke-progress value per step drives the hand reveal AND the
# tool tip (the tip is derived from the reveal), so brush, cloth
# and painted hand cannot drift apart (SPEC.md sec.3).
#
# Timings are the prototype's settled "laborious" ones (Nov 13,
# 2026): the minute wipe takes 2,600 ms, the dip 1,550 ms, the
# minute paint 3,200 ms - he works at it. Wipe/paint progress runs
# through work_ease(), whose two stalls (28-38% and 62-72% of the
# time buy only 5% progress each) are the effort in the stroke.
#
# API: Show(fig, dial=None); update(canvas, now_ms, time_tuple)
# composes ONE frame (dial copy -> figure -> hands) and returns the
# figure pose. tick(now_ms, total_minutes) remains for main.py's
# older loop shape: it advances the machine + figure without
# drawing. demo(now_ms) runs one full minute step on demand.
#
# The hourly cuckoo ritual (SPEC.md 3.4) landed in v20 (Nov 16,
# 2026): ~0.7 s after the on-hour show he leans in, wipes a
# clear circle in the frost with his cloth, and his face shows
# SHARP inside it (figure's raw-palette patch) before the
# circle fogs back. It is chained off the hour show only -
# never in the random idle mix - and it is suppressed entirely
# in the sleep window (Mark, Nov 16: no cuckoo when he's
# asleep; an hour boundary in-window just snaps, and a due
# cuckoo is skipped, not deferred). On the hour both hands are
# still fully wiped and repainted (the hour hand steps then
# anyway).
#
# SLEEP (Nov 15, 2026, v15): in the admin sleep hours (set_sleep)
# the scene is the night one - he lies down (figure.draw_sleep
# over clockface's night dial) and the machine's whole job is
# the minute SNAP: no shows, no routines, no rock; at each
# boundary both hands jump to the new time (drawn pale by
# compose's night state) and last_total follows, so the v12
# monotonic accounting holds through the night and the wake
# boundary starts a normal show. A queued try-it is DEFERRED
# by sleep - it stays queued and fires at the first gap after
# the wake. Entry cancels a running show/routine outright.
import math
import random

import clockface
import figure as figmod

# step durations, ms - the prototype's laborious numbers
DUR = {
    "glance": 300,
    "wipe_min": 2600,
    "wipe_hour": 1750,
    "dip": 1550,
    "paint_hour": 1950,
    "paint_min": 3200,
    "inspect": 520,
}

# Idle life v1 (Nov 15, 2026): the between-minutes routines.
# Durations are the task's settled ~seconds (the prototype's
# feel at 480 scale); weights are the random pick's odds.
IDLE_DUR = {  # ms
    "watch": 2500, "cap": 3000, "sip": 3400, "scratch": 2000,
    "rear": 2000, "apple": 4000, "hanky": 3000, "phone": 5000,
    "plane": 5000, "shoulder": 2100,
}
IDLE_WEIGHTS = (("shoulder", 4), ("watch", 3), ("scratch", 3),
                ("sip", 2), ("cap", 2), ("hanky", 2), ("rear", 2),
                ("apple", 2), ("phone", 1), ("plane", 1))
IDLE_FIRST_MIN = 45000    # first routine 45-90 s after boot...
IDLE_FIRST_RAND = 45000
IDLE_EVERY_MIN = 35000    # ...then one every ~35-75 s (v13:
IDLE_EVERY_RAND = 40000   # Mark asked for the routines more
                          # often - roughly one a minute, fit
                          # retries included; was ~100-220 s,
                          # the "every 2-4 minutes" band)
IDLE_MARGIN_MS = 1000     # a routine starts only if it ends at
                          # least this long before the boundary

# The cuckoo (Nov 16, 2026, v20): the hourly ritual, chained
# after the on-hour show. Phase lengths in ms - lean in, wipe
# the circle open, hold the sharp face, fog creeps back, step
# back - 7,200 total, the prototype's shape at the settled
# design (SPEC 3.4 reconciled with the task's numbers).
CUCKOO_DUR = 7200
CUCKOO_DELAY_MS = 700     # the beat between the hour show's
                          # end and the lean-in
CUCKOO_LEAN_MS = 1000
CUCKOO_WIPE_MS = 2500     # wipe ends (cumulative)
CUCKOO_HOLD_MS = 3960     # hold ends
CUCKOO_FOG_MS = 5472      # fog ends; the rest is the retreat
CUCKOO_HAND_R = 62        # the cloth hand's circle radius -
                          # just outside the porthole's 56, so
                          # the cloth rides the rim it opens

# The weight rock (Nov 15, 2026, v10 - Mark: "at minimum, he
# needs to rock from one leg to the other as if impatiently
# waiting"). Between shows the standing body target sways one
# snap step each way: dwell on one leg, an eased shift across,
# dwell on the other, shift back. It is an intent (figure's
# sway_x), not a pose: the arms re-hang off the moving shoulders
# by themselves. It runs only while he is standing between
# shows - paused during shows and routines, still during sleep
# hours - and main.py frames continuously while he is awake
# precisely so the rock is on the glass.
#
# v14: the v10-v13 rock ran on a fixed 4.6 s cycle and Mark
# called it "way too rhythmic". The dwells are now RANDOM -
# each side's dwell is drawn fresh, uniform in the range
# below - while the shift keeps its v10 ease and duration
# (0.20 of the old cycle). No period survives: two dwells in
# a row can be 3 s and 9 s.
ROCK_AMP = 15             # px each way = one snap-grid step
ROCK_SHIFT_MS = 920       # the eased shift across (v10: 0.20
                          # of the 4.6 s cycle)
ROCK_DWELL_MIN = 3000     # per-side dwell, drawn uniform in
ROCK_DWELL_RAND = 6000    # [MIN, MIN+RAND] = 3.0-9.0 s


def _days_from_civil(y, m, d):
    """Days since 1970-01-01 for a civil date (Hinnant's
    algorithm) - pure arithmetic, no clock import: show.py
    stays clock-free. update() builds the show machine's
    DAY-EXTENDED total from it (v12): days * 1440 + minute of
    day, which is monotonic across midnights within a run, so
    tick()'s forward-only comparison keeps firing shows after
    00:00. Minute-of-day alone wraps 1439 -> 0 - not greater
    than the evening's last_total, and no later total ever is,
    so before this fix no show fired again after the first
    midnight until a reboot and the hands froze at 23:59."""
    if m <= 2:
        y -= 1
    era = y // 400
    yoe = y - era * 400
    mp = m - 3 if m > 2 else m + 9
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def ease(p):
    if p < 0:
        p = 0
    if p > 1:
        p = 1
    return p * p * (3 - 2 * p)  # smoothstep


# work_ease breakpoints (time, progress): the two stalls are the
# flat segments - 10% of the time each buys only 5% progress; the
# working segments share one rate (0.90 progress over 0.80 time).
_WORK_EASE = ((0.0, 0.0), (0.28, 0.315), (0.38, 0.365),
              (0.62, 0.635), (0.72, 0.685), (1.0, 1.0))


def work_ease(p):
    """Stroke progress for wipe/paint: steady work with two stalls
    where he bears down and the hand barely moves (28-38% and
    62-72% of the stroke's time each advance progress by 0.05)."""
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    i = 0
    while i < len(_WORK_EASE) - 1:
        t0, v0 = _WORK_EASE[i]
        t1, v1 = _WORK_EASE[i + 1]
        if p <= t1:
            return v0 + (v1 - v0) * (p - t0) / (t1 - t0)
        i += 1
    return 1.0


def bend_env(p):
    """Dip bend envelope: fold in 0-.32, HOLD .32-.68 (with the two
    brush dabs show.py adds), straighten .68-1. A held plateau,
    never a sine hump - a bend that only peaks for an instant reads
    as no bend at all."""
    if p < 0.32:
        return ease(p / 0.32)
    if p < 0.68:
        return 1.0
    return 1.0 - ease((p - 0.68) / 0.32)


# --- idle routines: intent timelines ---
# Every routine drives BOTH hands along full hang-to-hang paths
# (waypoints eased per leg), so a hand never teleports: at p=0
# and p=1 every target is the rest hang. _run_idle resets the
# intent to _IDLE_NEUTRAL each frame before the routine's
# function overrides what it needs.

_IDLE_NEUTRAL = {
    "tip": None, "tool": None, "tip_l": None, "tip_r": None,
    "prop_l": None, "prop_r": None, "cap_off": False,
    "behind": None, "core": None, "watch_min": None,
    "mug_home": True, "apple_bites": 0, "hanky_puff": 0.0,
    "bend": 0.0, "follow": 0.0, "tau_ms": 200, "head_tilt": 0.0,
    "lean_in": 0.0, "sway_x": 0.0, "cuckoo_clear": 0.0,
}


def _path(p, pts):
    """Piecewise path through [(t, (x, y)), ...], t ascending
    0..1, smoothstep within each leg - the hand eases out of
    and into every waypoint."""
    if p <= pts[0][0]:
        return pts[0][1]
    for i in range(len(pts) - 1):
        t0, a = pts[i]
        t1, b = pts[i + 1]
        if p <= t1:
            f = ease((p - t0) / (t1 - t0)) if t1 > t0 else 1.0
            return (a[0] + (b[0] - a[0]) * f,
                    a[1] + (b[1] - a[1]) * f)
    return pts[-1][1]


def _path1(p, pts):
    """_path for a scalar (the sip's bend envelope)."""
    if p <= pts[0][0]:
        return pts[0][1]
    for i in range(len(pts) - 1):
        t0, a = pts[i]
        t1, b = pts[i + 1]
        if p <= t1:
            f = ease((p - t0) / (t1 - t0)) if t1 > t0 else 1.0
            return a + (b - a) * f
    return pts[-1][1]


def _lerp2(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _env(p, a, b, c, d):
    """Trapezoid envelope: 0 to a, ease up a..b, hold 1 to c,
    ease down c..d, 0 after."""
    if p <= a or p >= d:
        return 0.0
    if p < b:
        return ease((p - a) / (b - a))
    if p <= c:
        return 1.0
    return 1.0 - ease((p - c) / (d - c))


def _idle_watch(sh, p):
    # LEFT arm rises bare-handed, the wristwatch on its wrist;
    # the watch's hands show the painted time (sh._total). The
    # brush arm stays at his side. The wrist target sits out at
    # his left, forearm raised (v10: the original target was
    # ~5 px from the shoulder anchor - with the long v10 bones
    # the doubled-up fold threw the elbow across his chest and
    # buried the watch behind the hands' boss; out here the
    # elbow hangs below the wrist and the watch sits visible
    # on the raised forearm).
    fig = sh.fig
    _, head, hang_l, hang_r = sh._anchors()
    wrist = (head[0] - 64, head[1] + 52)
    e = _env(p, 0.0, 0.22, 0.78, 1.0)
    fig.set_intent(tip_l=_lerp2(hang_l, wrist, e), follow=0.12,
                   prop_l="watch", watch_min=sh._total)


def _idle_cap(sh, p):
    # The brush (right) hand takes the cap off and holds it at
    # his side - hair patch on - while the left hand makes two
    # passes across his forehead; then the cap goes back on.
    fig = sh.fig
    _, head, hang_l, hang_r = sh._anchors()
    cap_top = (head[0] + 8, head[1] - 20)
    side = (hang_r[0] + 12, hang_r[1] - 18)
    tip_r = _path(p, [(0.0, hang_r), (0.18, cap_top),
                      (0.28, cap_top), (0.48, side), (0.80, side),
                      (0.93, cap_top), (1.0, hang_r)])
    off = 0.28 <= p < 0.93
    fore = (head[0] - 13, head[1] - 3)
    if p < 0.45:
        tip_l = _path(p, [(0.0, hang_l), (0.34, hang_l),
                          (0.45, fore)])
    elif p <= 0.78:
        q = (p - 0.45) / 0.33
        tip_l = (head[0] - 13 * math.cos(q * 4 * math.pi),
                 head[1] - 3)
    else:
        tip_l = _path(p, [(0.78, fore), (0.92, hang_l),
                          (1.0, hang_l)])
    fig.set_intent(tip_r=tip_r, tip_l=tip_l, follow=0.10,
                   cap_off=off, prop_r="cap" if off else None)


def _idle_sip(sh, p):
    # The mug lives on the floor by the bucket, out of hanging
    # reach - so he steps toward it and DIPS for it (the proven
    # dip machinery), comes up with it, sips, and dips it back.
    fig = sh.fig
    _, head, hang_l, hang_r = sh._anchors()
    mx, my = figmod.MUG_HOME
    grab = (mx, my - 8)
    mouth = (head[0] - 2, head[1] + 13)
    bend = _path1(p, [(0.0, 0.0), (0.08, 0.0), (0.22, 1.0),
                      (0.30, 1.0), (0.48, 0.0), (0.70, 0.0),
                      (0.80, 1.0), (0.86, 1.0), (1.0, 0.0)])
    tip_r = _path(p, [(0.0, hang_r), (0.22, grab), (0.32, grab),
                      (0.55, mouth), (0.68, mouth),
                      (0.84, grab), (0.90, grab), (1.0, hang_r)])
    if 0.55 <= p <= 0.68:
        # a small contented bob while the mug is at his mouth
        tip_r = (tip_r[0], tip_r[1]
                 + math.sin((p - 0.55) / 0.13 * math.pi) * 2)
    held = 0.26 <= p < 0.84
    # v10: follow is 0.30 throughout (was 0.55 around the grabs).
    # Bent at the waist, his shoulder lands ~95 px right of his
    # feet; stepping hard toward the mug carries the shoulder
    # PAST it and out of arm's reach of the floor. The moderate
    # follow lets the body SINK instead (the sink row does the
    # reaching) - the grab is verified in test_reach.
    fig.set_intent(tip_r=tip_r, bend=bend, follow=0.30,
                   prop_r="mug" if held else None,
                   mug_home=not held)


def _idle_scratch(sh, p):
    # Right hand up to the cap's side, three small rubs.
    fig = sh.fig
    _, head, hang_l, hang_r = sh._anchors()
    side = (head[0] + 17, head[1] - 6)
    if p < 0.28:
        tip_r = _path(p, [(0.0, hang_r), (0.28, side)])
    elif p <= 0.75:
        q = (p - 0.28) / 0.47
        tip_r = (side[0] + math.sin(q * 6 * math.pi) * 4,
                 side[1] + math.sin(q * 12 * math.pi) * 2)
    else:
        tip_r = _path(p, [(0.75, side), (1.0, hang_r)])
    fig.set_intent(tip_r=tip_r, follow=0.12)


def _idle_rear(sh, p):
    # The right arm goes BEHIND him (figure draws it before the
    # body rect, so the torso occludes it): the forearm emerges
    # at his far hip and rubs up and down there.
    fig = sh.fig
    (fx, fy), head, hang_l, hang_r = sh._anchors()
    back = (fx - 34, fy - figmod.HIP_H + 6)   # at his far hip
    if p < 0.30:
        tip_r = _path(p, [(0.0, hang_r), (0.30, back)])
    elif p <= 0.75:
        q = (p - 0.30) / 0.45
        tip_r = (back[0], back[1] + math.sin(q * 5 * math.pi) * 5)
    else:
        tip_r = _path(p, [(0.75, back), (1.0, hang_r)])
    fig.set_intent(tip_r=tip_r, behind="r", follow=0.05)


def _idle_apple(sh, p):
    # An apple in the left hand: up to the mouth twice (a bite
    # notch appears each time), then the core is tossed away -
    # it arcs down and off the bottom of the dial.
    fig = sh.fig
    _, head, hang_l, hang_r = sh._anchors()
    mouth = (head[0] - 4, head[1] + 12)
    chest = (head[0] - 26, head[1] + 66)
    flick = (hang_l[0] - 16, hang_l[1] - 12)
    tip_l = _path(p, [(0.0, hang_l), (0.20, mouth), (0.30, mouth),
                      (0.45, chest), (0.52, chest), (0.62, mouth),
                      (0.70, mouth), (0.78, chest), (0.84, flick),
                      (1.0, hang_l)])
    bites = 0 if p < 0.28 else (1 if p < 0.60 else 2)
    core = None
    if p >= 0.84:
        t = (p - 0.84) / 0.16 * IDLE_DUR["apple"]  # ms of toss
        core = (flick[0] - 0.11 * t,
                flick[1] - 0.06 * t + 0.0004 * t * t)
    fig.set_intent(tip_l=tip_l, follow=0.12,
                   prop_l="apple" if p < 0.84 else None,
                   apple_bites=bites, core=core)


def _idle_hanky(sh, p):
    # The hanky to his nose, two blows (the hanky swells and
    # the hand dips with each - the head itself is baked and
    # cannot bob; the pulse carries the moment), then two dabs.
    fig = sh.fig
    _, head, hang_l, hang_r = sh._anchors()
    nose = (head[0], head[1] + 7)
    dab_l = (head[0] - 9, head[1] + 9)
    dab_r = (head[0] + 9, head[1] + 9)
    tip_l = _path(p, [(0.0, hang_l), (0.22, nose), (0.74, nose),
                      (0.80, dab_l), (0.86, dab_r), (0.91, nose),
                      (1.0, hang_l)])
    puff = 0.0
    for c in (0.38, 0.62):
        q = abs(p - c) / 0.09
        if q < 1:
            puff = max(puff, math.sin((1 - q) * math.pi * 0.5))
    if puff > 0:
        tip_l = (tip_l[0], tip_l[1] + puff * 4)
    fig.set_intent(tip_l=tip_l, follow=0.15,
                   prop_l="hanky" if p < 0.97 else None,
                   hanky_puff=puff)


def _idle_phone(sh, p):
    # Phone to his right ear for a few seconds: two nods (the
    # phone hand bobs - the baked head cannot nod) and one
    # gesture from the free hand mid-call.
    fig = sh.fig
    (fx, fy), head, hang_l, hang_r = sh._anchors()
    ear = (head[0] + 18, head[1] + 4)
    tip_r = _path(p, [(0.0, hang_r), (0.14, ear), (0.86, ear),
                      (1.0, hang_r)])
    if 0.2 < p < 0.82:
        tip_r = (tip_r[0], tip_r[1]
                 + math.sin((p - 0.2) / 0.62 * 4 * math.pi) * 2.5)
    gesture = (fx - 38, fy - figmod.SHOULDER_H + 55)  # chest height
    if 0.42 <= p <= 0.68:
        tip_l = _path(p, [(0.42, hang_l), (0.52, gesture),
                          (0.60, gesture), (0.68, hang_l)])
    else:
        tip_l = hang_l
    fig.set_intent(tip_r=tip_r, tip_l=tip_l, follow=0.10,
                   prop_r="phone" if p < 0.97 else None)


def _idle_plane(sh, p):
    # A small high-wing plane crosses the TOP of the dial; he
    # shades his eyes with the working hand for its pass. The
    # plane itself is drawn by update() after the hands (it is
    # in the room, not behind his glass).
    fig = sh.fig
    _, head, hang_l, hang_r = sh._anchors()
    brow = (head[0] + 13, head[1] - 11)
    tip_r = _path(p, [(0.0, hang_r), (0.12, brow), (0.82, brow),
                      (0.95, hang_r), (1.0, hang_r)])
    sh.plane_pos = (-40 + 560 * p,
                    62 + math.sin(p * 4 * math.pi) * 4)
    fig.set_intent(tip_r=tip_r, follow=0.12)


def _idle_shoulder(sh, p):
    # The lightest filler: both hands ride one slow roll.
    fig = sh.fig
    _, head, hang_l, hang_r = sh._anchors()
    roll = math.sin(p * 2 * math.pi)
    lift = -math.sin(p * math.pi) * 5
    fig.set_intent(
        tip_l=(hang_l[0] - roll * 3, hang_l[1] + lift + roll * 2),
        tip_r=(hang_r[0] + roll * 3, hang_r[1] + lift - roll * 2),
        follow=0.08)


_IDLE_FN = {"watch": _idle_watch, "cap": _idle_cap,
            "sip": _idle_sip, "scratch": _idle_scratch,
            "rear": _idle_rear, "apple": _idle_apple,
            "hanky": _idle_hanky, "phone": _idle_phone,
            "plane": _idle_plane, "shoulder": _idle_shoulder}


class Show:
    def __init__(self, fig, dial=None):
        self.fig = fig
        self.dial = dial
        if dial is not None:
            # figure's rects composite over this dial layer
            fig.dial = dial       # the static-layer canvas, if known
        self.min_hand = {"angle": 0.0, "reveal": 1.0}
        self.hour_hand = {"angle": 0.0, "reveal": 1.0}
        self.steps = []          # current show's step list
        self.step_i = 0
        self.step_start = 0
        self.running = False
        self.last_total = None   # last day-extended total-minutes
                                 # accounted for (v12)
        self.frost_clear = 0.0   # cuckoo porthole envelope 0..1
                                 # (v20: driven by _run_cuckoo and
                                 # mirrored into the figure intent)
        self.cuckoo = None       # {"start"} while the ritual runs
        self.cuckoo_enabled = True  # admin "cuckoo_enabled" key
        self.trycuckoo = False   # admin "Try the cuckoo" queued
        self._cuckoo_due = None  # ms tick when a chained cuckoo
                                 # starts (hour show end + delay)
        self._cuckoo_for = None  # the hour total already chained
                                 # (fires exactly once per hour)
        self._show_to = None     # the running show's target total
        self.idle = None         # {"type","start","dur"}
        self.next_idle_at = None  # ms tick when a routine may start
        self.last_idle_type = None  # never the same twice in a row
        self.tryit = None        # admin-queued routine name
        self.plane_pos = None    # flyby plane (x, y) while active
        self._total = 0          # time-of-day minutes, per tick
        self._sec = 0            # seconds into the minute, ditto
        self.sleep_enabled = False  # sleep hours suppress idles
        self.sleep_start = 0     # minutes of day (main.py sets)
        self.sleep_end = 0
        self.asleep = False      # v15: the sleep scene owns the
                                 # display while True (tick-driven)
        self._last_now = None
        self._dt = 0             # last tick's dt (the rock clock)
        # weight-rock state (v14): a two-phase machine - dwell
        # on a side for a randomly drawn span, then the eased
        # shift to the other side. Advances only while standing.
        self._rock_side = -1     # the side he rests on: -1/+1
        self._rock_shift = None  # ms into the shift, or None
                                 # while dwelling
        self._rock_left = ROCK_DWELL_MIN \
            + random.randint(0, ROCK_DWELL_RAND)
        self.rock_on = True      # the desk tests turn this off to
                                 # pin the rest pose; the board rocks
        self.last_idle_name = None   # admin status line (v10):
        self.last_idle_clock = None  # last routine + its HH:MM

    # --- show construction ---

    def _build_show(self, from_total, to_total):
        need_hour = (clockface.hour_angle_stepped(from_total)
                     != clockface.hour_angle_stepped(to_total))
        steps = [{"type": "glance",
                  "from": clockface.minute_angle(from_total)}]
        steps.append({"type": "wipe_min",
                      "from": clockface.minute_angle(from_total),
                      "to": clockface.minute_angle(to_total)})
        if need_hour:
            steps.append({"type": "wipe_hour",
                          "from": clockface.hour_angle_stepped(from_total),
                          "to": clockface.hour_angle_stepped(to_total)})
        steps.append({"type": "dip"})
        if need_hour:
            steps.append({"type": "paint_hour",
                          "from": clockface.hour_angle_stepped(from_total),
                          "to": clockface.hour_angle_stepped(to_total)})
        steps.append({"type": "paint_min",
                      "from": clockface.minute_angle(from_total),
                      "to": clockface.minute_angle(to_total)})
        steps.append({"type": "inspect"})
        return steps

    def start_show(self, from_total, to_total, now_ms):
        self.steps = self._build_show(from_total, to_total)
        self.step_i = 0
        self.step_start = now_ms
        self.running = True
        self._show_to = to_total
        # a show pre-empts the cuckoo too (a boundary crossing
        # mid-ritual - the fit check makes it a try-it-only
        # case, but an NTP jump could land here): the ritual
        # is cancelled outright, its envelope closed
        self.cuckoo = None
        self._cuckoo_due = None
        self.frost_clear = 0.0
        if self.idle is not None:
            # a routine was cut short by the boundary: keep the
            # cadence - the next routine is a full gap away, not
            # due again the moment this show ends
            self.next_idle_at = now_ms + IDLE_EVERY_MIN \
                + random.randint(0, IDLE_EVERY_RAND)
        self.idle = None
        self.plane_pos = None
        # the show pre-empts any routine: clear its intent fields
        # so the hands are the show's from the first frame (and
        # the weight rock stops - he stands still to work)
        self.fig.set_intent(tip_l=None, tip_r=None, prop_l=None,
                            prop_r=None, cap_off=False, behind=None,
                            core=None, watch_min=None, mug_home=True,
                            apple_bites=0, hanky_puff=0.0, sway_x=0.0,
                            lean_in=0.0, cuckoo_clear=0.0)

    # --- idle configuration (main.py / admin) ---

    def set_sleep(self, enabled, start_min, end_min):
        """Sleep hours, as minutes of day. While the window is
        active the sleep scene owns the display (v15): no shows,
        no routines, a queued try-it is deferred to the wake -
        see tick()'s sleep path."""
        self.sleep_enabled = bool(enabled)
        self.sleep_start = start_min
        self.sleep_end = end_min

    def queue_idle(self, name):
        """Admin Try-it: run this routine at the next safe gap
        (the fit check still applies - it fires early in the
        next minute if the current one is nearly over)."""
        if name in IDLE_DUR:
            self.tryit = name
            return True
        return False

    def set_cuckoo(self, enabled):
        """The admin "cuckoo_enabled" key (v20), mirroring
        set_sleep's pattern. Turning it off drops a chained
        cuckoo that hasn't started and un-queues a try-it; one
        already running finishes its 7.2 s."""
        self.cuckoo_enabled = bool(enabled)
        if not self.cuckoo_enabled:
            self._cuckoo_due = None
            self.trycuckoo = False

    def queue_cuckoo(self):
        """Admin "Try the cuckoo": run the ritual at the next
        safe gap, like an idle try-it (the fit check applies,
        and sleep defers it - see tick). Refused while the
        cuckoo is disabled in admin."""
        if not self.cuckoo_enabled:
            return False
        self.trycuckoo = True
        return True

    def sleeping_at(self, total_minutes):
        """True if the given minutes-of-day fall in the sleep
        window (wrap-midnight aware). main.py asks this BEFORE
        framing - it gates the loop's standing animation - so it
        takes the time as a parameter; _sleeping() is the same
        question for the last ticked time."""
        if not self.sleep_enabled:
            return False
        s, e, t = self.sleep_start, self.sleep_end, total_minutes
        if s == e:
            return False
        if s < e:
            return s <= t < e
        return t >= s or t < e

    def _sleeping(self):
        return self.sleeping_at(self._total)

    def idle_status(self, now_ms):
        """One line for the admin status block (v10), so an idle
        report is diagnosable at a glance: what is running, or
        what ran last and when the next is due, or why nothing
        is running. now_ms is a ticks_ms value; the countdown
        uses ticks_diff wrap semantics (2**30) without importing
        time - show.py stays clock-free."""
        if self.cuckoo is not None:
            return "cuckoo running"
        if self.idle is not None:
            return "%s running" % self.idle["type"]
        if self._sleeping():
            return "suppressed (sleep hours)"
        if self.tryit is not None:
            s = "try-it queued: %s" % self.tryit
        elif self.last_idle_name is not None:
            s = "last %s at %s" % (self.last_idle_name,
                                   self.last_idle_clock)
        else:
            s = "none yet"
        if self.next_idle_at is not None:
            d = (self.next_idle_at - now_ms) & 0x3FFFFFFF
            if d >= 0x20000000:
                d -= 0x40000000
            if d < 0:
                d = 0
            s += ", next in ~%ds" % (d // 1000)
        return s

    def demo(self, now_ms):
        """Run one full minute step on demand, from the currently
        displayed minute to the next. Returns False if no time has
        been set yet (update() never called) or he is asleep -
        no shows in the sleep window, not even bench ones."""
        if self.last_total is None or self.running or self.asleep \
                or self.cuckoo is not None:
            return False
        from_total = self.last_total
        self.start_show(from_total, from_total + 1, now_ms)
        # account for the demo minute so the scheduler (forward-
        # only) doesn't re-run it when real time catches up
        self.last_total = from_total + 1
        return True

    # --- the frame entry point ---

    def update(self, canvas, now_ms, time_tuple):
        """Advance the machine to now_ms and compose ONE frame:
        dial layer, then the figure, then the hands (painted on
        the glass, in front of him) via clockface.compose state
        overrides. Returns the figure pose used."""
        total = time_tuple[3] * 60 + time_tuple[4]
        self._sec = time_tuple[5]
        # the machine runs on the day-extended total (v12, see
        # _days_from_civil): monotonic across midnights within
        # the run. The tuple's date is the run's own clock, so
        # the extension is consistent from the first frame on.
        ext = _days_from_civil(time_tuple[0], time_tuple[1],
                               time_tuple[2]) * 1440 + total
        self.tick(now_ms, ext)
        if self.asleep:
            # the night frame (v15): the NIGHT static layer,
            # the lying scene over it (breath + Z's), then the
            # hands + date in pale ink (compose's night state).
            # The standing figure is not drawn at all.
            canvas.copy_from(figmod.sleep_night_canvas())
            self.fig.draw_sleep(canvas, now_ms)
            clockface.compose(canvas, time_tuple, {
                "dial": canvas, "night": True,
                "hour_angle": self.hour_hand["angle"],
                "min_angle": self.min_hand["angle"],
                "hour_reveal": self.hour_hand["reveal"],
                "min_reveal": self.min_hand["reveal"],
            })
            return self.fig.pose()
        # 1. the static dial layer
        if self.dial is not None:
            canvas.copy_from(self.dial)
        else:
            # lay the dial via compose with nothing revealed -
            # draw_hand at reveal <= 0.003 draws nothing at all
            clockface.compose(canvas, time_tuple,
                              {"hour_reveal": 0.0, "min_reveal": 0.0})
        # 2. the man
        pose = self.fig.pose()
        self.fig.draw(canvas, pose)
        # 3. the hands, driven by the machine's state ("dial":
        # canvas skips compose's own copy - the layer is laid)
        clockface.compose(canvas, time_tuple, {
            "dial": canvas,
            "hour_angle": self.hour_hand["angle"],
            "min_angle": self.min_hand["angle"],
            "hour_reveal": self.hour_hand["reveal"],
            "min_reveal": self.min_hand["reveal"],
        })
        # 4. the flyby plane, when one is crossing: it is in the
        # room, in front of the glass - drawn last, crisp
        if self.plane_pos is not None:
            figmod.draw_plane(canvas, self.plane_pos[0],
                              self.plane_pos[1])
        return pose

    def _snap_hands(self, total_minutes):
        """Both hands AT the given (day-extended) total's time,
        fully revealed: the first frame's paint, and the sleep
        hours' minute snap (v15). The angle functions are exact
        on extended totals - 1440 is a whole number of hour
        steps (v12)."""
        self.min_hand = {"angle": clockface.minute_angle(total_minutes),
                         "reveal": 1.0}
        self.hour_hand = {
            "angle": clockface.hour_angle_stepped(total_minutes),
            "reveal": 1.0}

    # --- per-frame advance (no drawing) ---

    def tick(self, now_ms, total_minutes):
        """Advance the machine and the figure. Call every frame.
        total_minutes is the DAY-EXTENDED total (v12): the show
        accounting (last_total, start_show) runs on it, so it
        must be monotonic within the run - update() builds it
        from the tuple's date. _total stays minute-of-day: the
        sleep window, the watch routine and the idle status
        clock all read time-of-day."""
        self._total = total_minutes % 1440
        if self.next_idle_at is None:
            self.next_idle_at = now_ms + IDLE_FIRST_MIN \
                + random.randint(0, IDLE_FIRST_RAND)
        if self._last_now is None:
            dt = 0
        else:
            dt = now_ms - self._last_now
            if dt < 0:
                dt = 0
            if dt > 250:
                dt = 250     # a long stall eases in steps, not a leap
        self._last_now = now_ms
        self._dt = dt
        # --- sleep (v15): transitions, then the night shift ---
        sleeping = self._sleeping()
        if sleeping and not self.asleep:
            # ENTER (window start, enabling mid-window, or a
            # boot inside the window): the scene replaces
            # whatever he was doing at this frame - a running
            # show or routine is cancelled outright, the intent
            # goes neutral, and the hands snap to now. No show
            # plays for the entry minute either.
            self.asleep = True
            self.running = False
            self.idle = None
            self.plane_pos = None
            # the cuckoo is suppressed in the window (v20): a
            # chained one that hasn't started is SKIPPED, not
            # deferred, and a running one is cancelled with
            # everything else. A queued try-it stays queued -
            # sleep defers try-its, as ever.
            self.cuckoo = None
            self._cuckoo_due = None
            self.frost_clear = 0.0
            self._rest_intent()
            self._snap_hands(total_minutes)
            self.last_total = total_minutes
        elif not sleeping and self.asleep:
            # EXIT (window end, or sleep switched off): the
            # hands are already correct - they snapped all
            # night and last_total tracked every boundary - so
            # normal operation simply resumes below; the next
            # boundary crossing starts a normal show.
            self.asleep = False
        if self.asleep:
            # The night's whole accounting: at each boundary
            # the hands SNAP to the new time and last_total
            # follows, so the v12 monotonic invariant holds
            # through the window and across midnight, the
            # date rolls over in compose as ever, and a
            # mid-sleep NTP step (either way) just re-snaps.
            # A due idle time is pushed out 30 s at a time -
            # main.py frames while a routine is due, and a due
            # time left in the past would keep its loop awake
            # all night (the v9 re-arm, moved here).
            if self.last_total is None:
                self._snap_hands(total_minutes)
                self.last_total = total_minutes
            elif total_minutes != self.last_total:
                self._snap_hands(total_minutes)
                self.last_total = total_minutes
            if self.next_idle_at is not None \
                    and now_ms >= self.next_idle_at:
                self.next_idle_at = now_ms + 30000
            self.fig.update(dt, now_ms)
            return
        if self.last_total is None:
            # first frame after boot: paint the current time, no show
            self._snap_hands(total_minutes)
            self.last_total = total_minutes
        elif total_minutes > self.last_total and not self.running:
            # forward only: a demo minute or an NTP step backwards
            # must not rewind the show
            self.start_show(self.last_total, total_minutes, now_ms)
            self.last_total = total_minutes
        if self.running:
            self._run_step(now_ms)
        elif self.cuckoo is not None:
            self._run_cuckoo(now_ms)
        elif not self._cuckoo_stage(now_ms):
            self._run_idle(now_ms)
        self.fig.update(dt, now_ms)

    def _run_step(self, now_ms):
        step = self.steps[self.step_i]
        dur = DUR[step["type"]]
        p = (now_ms - self.step_start) / dur
        if p >= 1:
            self._finish_step(step)
            self.step_i += 1
            self.step_start = now_ms
            if self.step_i >= len(self.steps):
                self.running = False
                self.fig.set_intent(tip=None, tool=None, follow=0.0,
                                    tau_ms=380, bend=0.0, head_tilt=0.0,
                                    lean_in=0.0)
                self._chain_cuckoo(now_ms)
            return
        self._apply_step(step, p)

    def _finish_step(self, step):
        t = step["type"]
        if t == "wipe_min":
            self.min_hand["reveal"] = 0.0
        elif t == "wipe_hour":
            self.hour_hand["reveal"] = 0.0
        elif t == "paint_min":
            self.min_hand = {"angle": step["to"], "reveal": 1.0}
        elif t == "paint_hour":
            self.hour_hand = {"angle": step["to"], "reveal": 1.0}

    def _apply_step(self, step, p):
        t = step["type"]
        fig = self.fig
        if t == "glance":
            tip = clockface.hand_tip(step["from"], 1.0,
                                     clockface.MIN_LEN)
            fig.set_intent(tip=tip, tool=None, follow=0.35, tau_ms=300,
                           bend=0.0,
                           head_tilt=(tip[0] - clockface.CX)
                           / clockface.MIN_LEN)
        elif t in ("wipe_min", "wipe_hour"):
            hand = self.min_hand if t == "wipe_min" else self.hour_hand
            length = clockface.MIN_LEN if t == "wipe_min" \
                else clockface.HOUR_LEN
            hand["angle"] = step["from"]
            hand["reveal"] = 1.0 - work_ease(p)
            tip = clockface.hand_tip(step["from"], hand["reveal"], length)
            fig.set_intent(tip=tip, tool="cloth", follow=0.68,
                           tau_ms=170, bend=0.0, head_tilt=0.0)
        elif t == "dip":
            bend = bend_env(p)
            dab = 0.0
            if 0.32 <= p < 0.68:
                # two brush dabs across the hold
                dab = abs(math.sin((p - 0.32) / 0.36 * 2 * math.pi))
            tip = (fig.bucket_x, figmod.BUCKET[1] - 14 + dab * 7)
            fig.set_intent(tip=tip, tool="brush", follow=0.30,
                           tau_ms=200, bend=bend, head_tilt=0.0)
        elif t in ("paint_min", "paint_hour"):
            hand = self.min_hand if t == "paint_min" else self.hour_hand
            length = clockface.MIN_LEN if t == "paint_min" \
                else clockface.HOUR_LEN
            hand["angle"] = step["to"]
            hand["reveal"] = work_ease(p)
            tip = clockface.hand_tip(step["to"], hand["reveal"], length)
            fig.set_intent(tip=tip, tool="brush", follow=0.68,
                           tau_ms=170, bend=0.0, head_tilt=0.0)
        elif t == "inspect":
            # step back, look at the work, small nod (the nod is in
            # head_tilt - carried, not rendered while the head is
            # baked into the sprites)
            fig.set_intent(tip=None, tool=None, follow=0.05, tau_ms=320,
                           bend=0.0, lean_in=0.0,
                           head_tilt=math.sin(p * math.pi) * 0.3)

    # --- the cuckoo: the hourly ritual (v20) ---

    def _chain_cuckoo(self, now_ms):
        """Called as a show completes: if it was the on-hour
        show (its target total is an hour boundary), the cuckoo
        is due CUCKOO_DELAY_MS later - once per hour, only when
        enabled and awake. The due time occupies the stage like
        a show does: _cuckoo_stage holds the idle scheduler off
        during the beat, so no routine jumps into the gap."""
        to = self._show_to
        if to is None or to % 60 != 0:
            return
        if not self.cuckoo_enabled or self._sleeping():
            return
        if self._cuckoo_for == to:
            return
        self._cuckoo_for = to
        self._cuckoo_due = now_ms + CUCKOO_DELAY_MS

    def _fits_cuckoo(self):
        """The idle fit rule, at the cuckoo's length: started
        now, it ends at least IDLE_MARGIN_MS before the next
        minute boundary."""
        return CUCKOO_DUR + IDLE_MARGIN_MS \
            <= (60 - self._sec) * 1000

    def _start_cuckoo(self, now_ms):
        self.cuckoo = {"start": now_ms}
        self._cuckoo_due = None
        # a pending try-it is satisfied by this firing, however
        # it was triggered - never two rituals back to back
        self.trycuckoo = False
        self.plane_pos = None

    def _cuckoo_stage(self, now_ms):
        """The stage between shows, cuckoo first: start a due
        (chained) or queued (try-it) ritual, or hold the stage
        during the chained beat. Returns True when the frame
        is the cuckoo's (or its beat) - the idle scheduler
        then stands down, exactly as it does for a show."""
        if self._cuckoo_due is not None:
            if now_ms >= self._cuckoo_due:
                self._start_cuckoo(now_ms)
                self._run_cuckoo(now_ms)
            else:
                self._rest_intent()
            return True
        if self.trycuckoo and self.idle is None:
            if self._fits_cuckoo():
                self._start_cuckoo(now_ms)
                self._run_cuckoo(now_ms)
            else:
                # too late in the minute - hold for the next
                # gap, the try-it discipline
                self._rest_intent()
            return True
        return False

    def _run_cuckoo(self, now_ms):
        """One frame of the ritual. The phases (ms from the
        start): lean in with the cloth hand rising to the
        circle's top (0-1000); the cloth traces the circle
        while the porthole opens behind it (1000-2500); the
        sharp face holds, hand down (2500-3960); the frost
        creeps back (3960-5472); he steps back (5472-7200).
        The porthole envelope is frost_clear - mirrored into
        the figure intent, where draw() composites the sharp
        patch; the lean rides lean_in, which scales the patch
        head. At frost=0 the same choreography plays - only
        the clear/fog contrast is absent, as designed."""
        fig = self.fig
        e = now_ms - self.cuckoo["start"]
        if e >= CUCKOO_DUR:
            self.cuckoo = None
            self.frost_clear = 0.0
            self._rest_intent()
            # the ritual occupied its slot like a show: the
            # next routine is a full gap away, not due at once
            self.next_idle_at = now_ms + IDLE_EVERY_MIN \
                + random.randint(0, IDLE_EVERY_RAND)
            return
        _, head, hang_l, _ = self._anchors()
        hx, hy = head
        if e < CUCKOO_LEAN_MS:
            lean = ease(e / CUCKOO_LEAN_MS)
            clear = 0.0
            top = (hx, hy - CUCKOO_HAND_R)
            tip = _lerp2(hang_l, top, ease(e / CUCKOO_LEAN_MS))
            tool = "cloth"
        elif e < CUCKOO_WIPE_MS:
            q = (e - CUCKOO_LEAN_MS) \
                / (CUCKOO_WIPE_MS - CUCKOO_LEAN_MS)
            lean = 1.0
            clear = ease(q)
            th = 2 * math.pi * ease(q)
            tip = (hx + CUCKOO_HAND_R * math.sin(th),
                   hy - CUCKOO_HAND_R * math.cos(th))
            tool = "cloth"
        elif e < CUCKOO_HOLD_MS:
            lean = 1.0
            clear = 1.0
            tip = None
            tool = None
        elif e < CUCKOO_FOG_MS:
            q = (e - CUCKOO_HOLD_MS) \
                / (CUCKOO_FOG_MS - CUCKOO_HOLD_MS)
            lean = 1.0
            clear = 1.0 - ease(q)
            tip = None
            tool = None
        else:
            q = (e - CUCKOO_FOG_MS) / (CUCKOO_DUR - CUCKOO_FOG_MS)
            lean = 1.0 - ease(q)
            clear = 0.0
            tip = None
            tool = None
        self.frost_clear = clear
        fig.set_intent(**_IDLE_NEUTRAL)
        fig.set_intent(tip=tip, tool=tool, follow=0.15,
                       tau_ms=200, lean_in=lean,
                       cuckoo_clear=clear)

    # --- idle routines: the scheduler ---

    def _fits(self, name):
        """True if the routine, started now, ends at least
        IDLE_MARGIN_MS before the next minute boundary. The
        seconds count is whole-second granular (the sub-second
        part is unknown), and the 1 s margin absorbs exactly
        that uncertainty."""
        return IDLE_DUR[name] + IDLE_MARGIN_MS \
            <= (60 - self._sec) * 1000

    def _pick_fitting(self):
        """Weighted random among the routines that fit in the
        rest of this minute, never the one that just ran."""
        cands = [(n, w) for n, w in IDLE_WEIGHTS
                 if n != self.last_idle_type and self._fits(n)]
        if not cands:
            return None
        tot = 0
        for _, w in cands:
            tot += w
        r = random.randint(0, tot - 1)
        for n, w in cands:
            if r < w:
                return n
            r -= w
        return cands[-1][0]

    def _start_idle(self, name, now_ms):
        self.idle = {"type": name, "start": now_ms,
                     "dur": IDLE_DUR[name]}
        self.last_idle_type = name
        self.last_idle_name = name
        self.last_idle_clock = "%02d:%02d" % (self._total // 60,
                                              self._total % 60)

    def _rest_intent(self):
        self.fig.set_intent(**_IDLE_NEUTRAL)
        self.fig.set_intent(tau_ms=380)

    def _rock_offset(self):
        """The weight rock's sway target right now: the resting
        side's -/+ROCK_AMP while dwelling; during a shift, the
        eased line from the old side to the new (v10's ease and
        duration). The shift crosses centre mid-way, so the
        drawn body steps -15 -> 0 -> +15 as the snap thresholds
        pass - a man shifting his weight, not a dance. figure's
        own easing (tau 380 at rest) rounds what the steps
        leave."""
        if self._rock_shift is None:
            return float(self._rock_side * ROCK_AMP)
        p = self._rock_shift / ROCK_SHIFT_MS
        return ROCK_AMP * self._rock_side * (1 - 2 * ease(p))

    def _advance_rock(self):
        """Consume this tick's dt in the rock machine (v14).
        Dwell expiry starts the shift; shift expiry lands him
        on the other side and draws the NEXT dwell fresh -
        uniform in [ROCK_DWELL_MIN, +ROCK_DWELL_RAND]. A long
        dt (a show boundary ate the frames) can cross several
        phases; the loop settles them in order."""
        t = self._dt
        while t > 0:
            if self._rock_left > t:
                self._rock_left -= t
                if self._rock_shift is not None:
                    self._rock_shift += t
                t = 0
            else:
                t -= self._rock_left
                if self._rock_shift is None:
                    self._rock_shift = 0
                    self._rock_left = ROCK_SHIFT_MS
                else:
                    self._rock_shift = None
                    self._rock_side = -self._rock_side
                    self._rock_left = ROCK_DWELL_MIN \
                        + random.randint(0, ROCK_DWELL_RAND)

    def _run_idle(self, now_ms):
        if self.idle is None:
            started = False
            if self.tryit is not None:
                # a queued try-it fires at the first gap where it
                # fits - usually just after the next show
                if self._fits(self.tryit):
                    self._start_idle(self.tryit, now_ms)
                    self.tryit = None
                    started = True
            elif self.next_idle_at is not None \
                    and now_ms >= self.next_idle_at:
                if self._sleeping():
                    # stay quiet - and re-arm a little way out:
                    # main.py frames while a routine is due, so a
                    # due time left in the past would keep the
                    # loop awake all night
                    self.next_idle_at = now_ms + 30000
                else:
                    name = self._pick_fitting()
                    if name is not None:
                        self._start_idle(name, now_ms)
                        started = True
                    else:
                        # too late in the minute for anything -
                        # retry just after the next show
                        self.next_idle_at = now_ms \
                            + (60 - self._sec) * 1000 + 2000
            if not started:
                self._rest_intent()
                # standing between shows: the weight rock. The
                # machine advances only here, so the rock pauses
                # for shows and routines and resumes where it
                # left off; sleep hours stand him still.
                if self.rock_on and not self._sleeping():
                    self._advance_rock()
                    self.fig.set_intent(sway_x=self._rock_offset())
                return
        p = (now_ms - self.idle["start"]) / self.idle["dur"]
        if p >= 1:
            self.idle = None
            self.plane_pos = None
            self.next_idle_at = now_ms + IDLE_EVERY_MIN \
                + random.randint(0, IDLE_EVERY_RAND)
            self._rest_intent()
            return
        self.fig.set_intent(**_IDLE_NEUTRAL)
        _IDLE_FN[self.idle["type"]](self, p)

    def _anchors(self):
        """(feet, head, hang_l, hang_r) from the figure's eased
        body - the routines' target frame. Targets are absolute
        canvas coords; pose() derives the IK anchors from the
        SNAPPED body, at most a snap step away, and every target
        in the routines was reach-checked against the unsnapped
        anchors with margin (SPEC 3.5's no-stretch rule)."""
        fig = self.fig
        fx, fy = fig.feet_x, fig.feet_y
        head = (fx, fy - figmod.HEAD_H)
        sh_y = fy - figmod.SHOULDER_H
        hang_l = (fx - figmod.SHOULDER_DX - figmod.HANG_OUT,
                  sh_y + figmod.HANG_DY)
        hang_r = (fx + figmod.SHOULDER_DX + figmod.HANG_OUT,
                  sh_y + figmod.HANG_DY)
        return (fx, fy), head, hang_l, hang_r

    # --- drawing helper for the older loop shape (main.py) ---

    def draw_hands(self, fb):
        clockface.draw_hand(fb, self.hour_hand["angle"],
                            clockface.HOUR_LEN, clockface.HOUR_W,
                            self.hour_hand["reveal"])
        clockface.draw_hand(fb, self.min_hand["angle"],
                            clockface.MIN_LEN, clockface.MIN_W,
                            self.min_hand["reveal"])
        # the cuckoo's sharp patch composites inside
        # figure.draw() (v20), driven by the cuckoo_clear
        # intent - this older loop shape predates it and
        # simply never sees a ritual (main.py uses update()).


def step_to_min_angle(show):
    """Minute angle the glance looks at: the hand about to be wiped
    is the currently painted one. (Kept from the skeleton; the
    glance step now carries its own "from" angle.)"""
    return show.min_hand["angle"]
