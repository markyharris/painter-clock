# attface.py - the ATTITUDE face (Nov 17, 2026, v29):
# a steam-gauge attitude indicator flying the three
# commercial maneuvers on a loop - Lazy Eight, Chandelle,
# Eights on Pylons, at Cessna 182 pace - with the analog
# clock drawn over it (tick ring, creeping hands, stepping
# second hand), and the maneuver's name lettered in a
# curve on the bottom bezel. Mark's build order, the same
# evening the three maneuver videos were made from these
# very profiles: "Build it - maneuvers with the analog
# clock over it."
#
# THE ANIMATION IS DRAWN, NOT PLAYED: MicroPython has no
# video decoder, and it needs none - the videos were
# always just (bank, pitch) numbers over time. attdata.py
# carries those numbers (sampled every 0.1 s from the
# videos' own profile models; gen_attdata.py in the desk
# harness), and this face draws the gauge from them the
# way it draws everything else: C framebuf primitives
# through band windows, zero per-byte buffer writes.
# The cycle position is ELAPSED time accumulated inside
# this module from the time tuples compose() is handed
# (deltas, midnight-safe via a days-from-civil count) -
# never seconds-of-day modulo, so midnight cannot snap
# the phase, and a backward NTP step simply adds nothing.
#
# v29.1 (Nov 18, 2026) - SMOOTH MOTION. Mark's bench
# verdict on v29: the gauge "jumps quite a bit". It did:
# main keyed this face at whole seconds (TICK_SECONDS),
# so the ball stepped a full second of profile per
# frame - up to ~10 deg of bank at the fast points.
# Two changes: the face opts into sub-second keying
# (TICK_MS below - main repaints it every 200 ms by
# day), and main hands each day compose the loop's
# ticks_ms in the state dict, so the phase advances by
# real elapsed milliseconds between frames instead of
# whole tuple seconds. The tables were resampled at
# 0.1 s to match (attdata.DT - read from the data, not
# hard-coded here). The second hand is untouched: it
# reads the tuple's seconds, so it still steps once a
# second while the ball glides under it. Night frames
# carry no ms and keep the v29 tuple cadence exactly.
#
# v29.2 (Nov 18, 2026) - CADENCE. Mark's bench verdict
# on v29.1: VERY choppy, and even the second hand
# inconsistent. 5 fps was more than the board's
# compose+show path sustains: frames overran the
# 200 ms bucket, repaints landed irregularly, and the
# time-true second hand showed it first. TICK_MS is
# now 500 (2 fps) - real headroom in the bucket, so
# the cadence holds; the worst per-frame move is
# 10.5 deg of bank, still near half of v29's
# whole-second jump. (The v29.1 SPEC's 250-300
# fallback guess was not used: choppy at 200 says
# the frame cost sits well past that.)
#
# v29.3 (Nov 18, 2026) - DIAGNOSTIC, Mark's call:
# v29.2 at 2 fps is "still not much better" on the
# board. To isolate whether the second hand is part
# of the problem - its once-a-second step against
# the ball's twice-a-second move, or something in
# its drawing - this build draws NO second hand on
# the day face (SECOND_HAND below; the night face
# never had one). The hand's code stays in place;
# the bench verdict decides whether it returns, and
# in what form. Cadence unchanged (TICK_MS 500):
# one variable at a time.
#
# v29.4 (Nov 18, 2026): Mark's verdict on the
# handless build: "a little better." With the hand
# out of the picture he asked to push the frame
# rate back up, so TICK_MS 500 -> 250 (4 fps) - a
# doubling, but not all the way back to the 200 ms
# that slipped in v29.1 (that build still had the
# hand). The hand stays OFF for this step: one
# variable at a time, again. Worst per-frame step
# at 250 ms, measured on the data: 5.5 deg of bank,
# 1.8 of pitch.
#
# v29.5 (Nov 18, 2026): v29.4 is "still pretty
# jumpy" - and by then the experiments had cleared
# the drawing: handless at 4 fps the cadence holds,
# so what reads as jumpy is the step size itself
# (5.5 deg of bank moves the horizon's edge ~18 px
# in one frame; a real gyro moves continuously).
# Mark's pick: slow the flying to 60% speed and
# smooth it. RATE below scales every advance of
# the cycle, so a 250 ms frame now steps 0.15
# cycle-seconds - worst 3.5 deg of bank, 1.3 of
# pitch - and the full cycle stretches to ~8
# minutes. The profiles themselves are untouched
# (attdata is the C182 pace, flown slower), and
# the label fades stretch with the cycle. On top,
# _smooth() rounds the displayed attitude with a
# stateless binomial blur over +-SMOOTH_W
# cycle-seconds, so the corners - roll-in onsets,
# reversals - ease instead of kicking. The hand
# stays off.
#
# THE GAUGE (the videos' instrument, at clock scale):
# black bezel (r=237, grey rim line, four screws at the
# diagonals), glass r=192. The ball is drawn per frame
# as polygons: sky/ground split by the horizon chord,
# the white horizon strip, the +-10/+-20 pitch ladder
# (39 px per 10 deg, so pitch_px = pitch_deg x 3.9),
# all rotating by bank and translating by pitch, clipped
# to the glass by construction (chords and arcs of the
# glass circle itself). The gyro roll ticks ride the
# outermost glass band over the top arc, so the fixed
# orange index triangle at top centre reads the bank
# against them. The fixed miniature aircraft (yellow,
# ink-edged) sits at the centre under the hands.
#
# THE CLOCK OVER IT is the METAR face's treatment: 60
# cream ticks inside the glass, hands drawn twice (ink
# edge pass, cream pass), the second hand cream-edged -
# NOT the classic's rust, for the METAR reason: rust
# would vanish against the ground brown. The date shows
# (standing rule), smoothfont.drawn so it blends onto
# the moving ball instead of riding an opaque strip.
#
# THE NAME rides the bottom bezel arc (attlabels.py -
# coverage baked offline, stamped by blending through
# it, smoothfont.draw's row-slice pattern). It fades in
# over 1.5 s starting 1.0 s into a segment and out over
# the last 3.0 s (gone 1.5 s before the segment ends),
# exactly as the v3 video lettered it: the fade blends
# the ink toward the bezel black.
#
# SLEEP: the ball darkens (deep blue-black sky, dark
# earth), ladder/horizon/ticks/symbol/index dim to the
# metar DIM pale, clock ticks go NIGHT_TICK, hands pale
# and minute-stepped with no second hand, the name DIM,
# the date PALE. The ball keeps animating on main's
# night cadence (one frame a minute).
#
# Frost and Backlight stay painter-only; cuckoo and the
# idle routines never reach this face (main drops them
# off the painter).
import binascii
import math
from array import array

import attdata
import attlabels
import classicface
import clockface
import smoothfont

NAME = "attitude"
TICK_SECONDS = True
# v29.1: sub-second compose by day - main repaints this
# face every TICK_MS (and passes that ticks_ms to
# compose in the state dict, which is what advances
# the cycle phase smoothly). Night ignores it: the
# sleep treatment still snaps on the minute.
# 200 (v29.1) -> 500 (v29.2) -> 250 (v29.4, hand
# off) - see the header notes.
TICK_MS = 250

# v29.3 DIAGNOSTIC: no second hand on the day face -
# see the header note. The drawing code stays; flip
# to True to bring the hand back.
SECOND_HAND = False

CX = clockface.CX
CY = clockface.CY

CREAM = clockface.CREAM
INK = clockface.INK
PALE = clockface.PALE
NIGHT_TICK = clockface.NIGHT_TICK

# The metar face's dimmed pale (night lettering tone).
DIM = clockface.rgb565(148, 154, 168)

BEZEL = clockface.rgb565(16, 16, 20)      # the case black
RIMLINE = clockface.rgb565(96, 96, 102)   # the rim's grey line
SCREW = clockface.rgb565(110, 110, 116)
SCREW_SLOT = clockface.rgb565(38, 38, 42)
WHITE = clockface.rgb565(255, 255, 255)
SKY = clockface.rgb565(63, 143, 210)      # the videos' blue,
GROUND = clockface.rgb565(138, 90, 43)    # brown (brief values)
SKY_N = clockface.rgb565(16, 26, 48)      # night ball
GROUND_N = clockface.rgb565(44, 30, 18)
YELLOW = clockface.rgb565(242, 194, 48)   # the miniature aircraft
ORANGE = clockface.rgb565(255, 179, 64)   # the fixed index

GLASS_R = 192
BEZEL_R = 237
SCREW_R = 208
PITCH_PX = 3.9          # px per degree of pitch (39 per 10)
EDGE = 5                # the hands' ink edge (metarface's)

HOUR_LEN = classicface.HOUR_LEN
MIN_LEN = classicface.MIN_LEN
SEC_LEN = classicface.SEC_LEN
HOUR_W = classicface.HOUR_W
MIN_W = classicface.MIN_W
TAIL = classicface.TAIL

# The date's cap-top for smoothfont.draw: draw_date's
# line box ends at y=116; draw() positions by capitals,
# so the cap-top is the box top plus the strike's own
# cap offset - the same line, blended instead of stripped.
_DATE_CAP_Y = clockface.DATE_Y + smoothfont.metrics("date")[2]

_show_date = True        # admin "show_date" key; main.py drives


def set_show_date(on):
    """The face-contract date convention: main.py drives
    it; compose() honours it from the next frame."""
    global _show_date
    _show_date = bool(on)


def show_date():
    return _show_date


# --- the maneuver cycle ---

_TOTAL = attdata.DURATIONS[0] + attdata.DURATIONS[1] \
    + attdata.DURATIONS[2]
_elapsed = 0.0           # accumulated cycle seconds
_last_abs = None         # absolute seconds of the last compose
_last_ms = None          # ticks_ms of the last compose that
                         # carried one (v29.1 day frames)


def _abs_seconds(tup):
    """Absolute seconds for a localtime-style tuple, via
    days-from-civil (Hinnant) - the count is monotonic
    across midnights, month ends and leap days, which is
    all the cycle asks of it."""
    y, m, d = tup[0], tup[1], tup[2]
    yy = y - (1 if m <= 2 else 0)
    era = (yy if yy >= 0 else yy - 399) // 400
    yoe = yy - era * 400
    mp = (m + 9) % 12
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days = era * 146097 + doe - 719468
    return days * 86400 + tup[3] * 3600 + tup[4] * 60 + tup[5]


# v29.5: the cycle runs at 60% of real time - see
# the header note. One constant, applied to every
# advance below; attdata keeps the true C182 pace.
RATE = 0.6

# v29.5: _smooth's binomial half-window, in cycle
# seconds - the displayed attitude averages the
# profile at e-W, e and e+W, weighted 1-2-1.
SMOOTH_W = 0.3


def _advance(time_tuple, ms=None):
    """Accumulate the delta since the last compose into
    the cycle, scaled by RATE (v29.5: the cycle runs
    at 60% of real time). A backward step (an NTP
    correction) adds nothing - the phase never snaps.

    Day frames (v29.1) carry the loop's ticks_ms: the
    phase then advances by real milliseconds between
    frames, folded across the ticks wrap (2**30 on the
    board). A gap over 5 s - the face was away, a save
    hitched the loop - or a backward step re-anchors
    only: the frozen-while-away phase resumes where it
    left off rather than leaping. Frames without ms
    (the night cadence, the desk harness) keep the v29
    rule exactly: whole tuple-second deltas, scaled."""
    global _elapsed, _last_abs, _last_ms
    now = _abs_seconds(time_tuple)
    if ms is not None:
        if _last_ms is not None:
            d = (ms - _last_ms + 536870912) % 1073741824 \
                - 536870912
            if 0 < d <= 5000:
                _elapsed += d / 1000.0 * RATE
        _last_ms = ms
        _last_abs = now
        return _elapsed
    if _last_abs is not None:
        delta = now - _last_abs
        if delta > 0:
            _elapsed += delta * RATE
    _last_abs = now
    return _elapsed


def _smooth(elapsed):
    """The displayed (bank, pitch) at a cycle time:
    _position's values at elapsed-SMOOTH_W, elapsed
    and elapsed+SMOOTH_W blended 1-2-1 (v29.5).
    Stateless - the same elapsed always draws the
    same attitude - and the segment/local time stay
    the centre sample's, so the label keeps the true
    cycle position."""
    _s0, _t0, b0, p0 = _position(elapsed - SMOOTH_W)
    seg, local_t, b1, p1 = _position(elapsed)
    _s2, _t2, b2, p2 = _position(elapsed + SMOOTH_W)
    return seg, local_t, (b0 + 2.0 * b1 + b2) / 4.0, \
        (p0 + 2.0 * p1 + p2) / 4.0


def _position(elapsed):
    """(segment, local_t, bank_deg, pitch_deg) at an
    elapsed cycle time: the segment's samples, linearly
    interpolated between the attdata.DT posts."""
    pos = elapsed % _TOTAL
    seg = 0
    while pos >= attdata.DURATIONS[seg]:
        pos -= attdata.DURATIONS[seg]
        seg += 1
    banks = attdata.banks(seg)
    pitches = attdata.pitches(seg)
    f = pos / attdata.DT
    i = int(f)
    last = len(banks) - 1
    if i >= last:
        return seg, pos, (banks[last] - 128) / 2.0, \
            (pitches[last] - 128) / 2.0
    frac = f - i
    bank = ((banks[i] - 128)
            + (banks[i + 1] - banks[i]) * frac) / 2.0
    pitch = ((pitches[i] - 128)
             + (pitches[i + 1] - pitches[i]) * frac) / 2.0
    return seg, pos, bank, pitch


def _fade(local_t, dur):
    """The label's fade factor (the v3 video's timing):
    in over 1.5 s from 1.0 s into the segment, full
    through the middle, out over the last 3.0 s - gone
    1.5 s before the segment ends."""
    f = (local_t - 1.0) / 1.5
    back = (dur - 1.5 - local_t) / 1.5
    if back < f:
        f = back
    if f < 0.0:
        f = 0.0
    if f > 1.0:
        f = 1.0
    return f


# --- drawing helpers (band-limited, the classic's pattern) ---

def _bands(fb):
    wins = list(fb.band_windows())
    bh = wins[1][1] - wins[0][1] if len(wins) > 1 else 480
    return wins, bh


def _poly(fb, coords, colour):
    """One filled polygon, called only into the bands its
    y-extent touches (framebuf clips the rest anyway -
    a missed band is pure overhead, the painter's rule)."""
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
    wins, bh = _bands(fb)
    for win, y0 in wins:
        if maxy >= y0 and miny < y0 + bh:
            win.poly(0, -y0, coords, colour, True)


def _flat(pts):
    return array("h", [int(round(v)) for xy in pts for v in xy])


def _pt(ang_deg, r):
    """Point at clock-angle (0 = 12, clockwise), radius r."""
    a = math.radians(ang_deg)
    return (CX + math.sin(a) * r, CY - math.cos(a) * r)


# --- the ball ---

def _arc(th_from, th_to, th_mid):
    """Interior angles on the sweep from th_from to
    th_to that passes th_mid, ~10 degrees apart (the
    endpoints are the caller's chord points)."""
    two_pi = 2.0 * math.pi
    d = (th_to - th_from) % two_pi
    dm = (th_mid - th_from) % two_pi
    if dm > d:
        d -= two_pi
    steps = int(abs(d) / 0.17) + 1
    if steps < 2:
        steps = 2
    return [th_from + d * i / steps for i in range(1, steps)]


def _draw_ball(fb, bank, pitch, night):
    """Sky, ground, horizon strip and pitch ladder for
    one attitude, as polygons of the glass circle: the
    horizon is the chord at the pitch offset, the sky
    and ground are that chord closed by the circle's
    own arcs - so the ball can never paint outside the
    glass, at any bank the profiles reach."""
    sky = SKY_N if night else SKY
    gnd = GROUND_N if night else GROUND
    line_c = DIM if night else WHITE
    br = math.radians(bank)
    ux, uy = math.cos(br), -math.sin(br)     # along the horizon
    nx, ny = math.sin(br), math.cos(br)     # toward the ground
    o = pitch * PITCH_PX

    def chord(off):
        if off > GLASS_R:
            off = GLASS_R
        if off < -GLASS_R:
            off = -GLASS_R
        lc = math.sqrt(GLASS_R * GLASS_R - off * off)
        cxp, cyp = CX + nx * off, CY + ny * off
        return (cxp - ux * lc, cyp - uy * lc), \
            (cxp + ux * lc, cyp + uy * lc), lc

    A, B, _lc = chord(o)
    thA = math.atan2(A[1] - CY, A[0] - CX)
    thB = math.atan2(B[1] - CY, B[0] - CX)
    sky_mid = math.atan2(-ny, -nx)
    gnd_mid = math.atan2(ny, nx)
    sky_pts = [A, B]
    for th in _arc(thB, thA, sky_mid):
        sky_pts.append((CX + GLASS_R * math.cos(th),
                        CY + GLASS_R * math.sin(th)))
    _poly(fb, _flat(sky_pts), sky)
    gnd_pts = [B, A]
    for th in _arc(thA, thB, gnd_mid):
        gnd_pts.append((CX + GLASS_R * math.cos(th),
                        CY + GLASS_R * math.sin(th)))
    _poly(fb, _flat(gnd_pts), gnd)
    # the horizon strip: the chord fattened +-3 px
    strip = [(A[0] - nx * 3, A[1] - ny * 3),
             (B[0] - nx * 3, B[1] - ny * 3),
             (B[0] + nx * 3, B[1] + ny * 3),
             (A[0] + nx * 3, A[1] + ny * 3)]
    _poly(fb, _flat(strip), line_c)
    # the ladder: lines parallel to the horizon at the
    # +-10 / +-20 pitch marks, brief half-lengths,
    # clamped to their own chords
    for a_deg, half in ((10, 78), (20, 60), (-10, 78),
                        (-20, 60)):
        P, Q, lc = chord(o - a_deg * PITCH_PX)
        hh = half if half < lc else lc
        cxp = (P[0] + Q[0]) / 2.0
        cyp = (P[1] + Q[1]) / 2.0
        P = (cxp - ux * hh, cyp - uy * hh)
        Q = (cxp + ux * hh, cyp + uy * hh)
        strip = [(P[0] - nx * 2, P[1] - ny * 2),
                 (Q[0] - nx * 2, Q[1] - ny * 2),
                 (Q[0] + nx * 2, Q[1] + ny * 2),
                 (P[0] + nx * 2, P[1] + ny * 2)]
        _poly(fb, _flat(strip), line_c)


def _draw_gyro(fb, bank, night):
    """The roll ticks in the outermost glass band, top
    arc only, rotating with the gyro - the tick whose
    scale value equals the bank sits under the index."""
    line_c = DIM if night else WHITE
    for s in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45,
              60):
        coords = classicface._tick_coords(s - bank, 178,
                                          190, 3)
        _poly(fb, coords, line_c)


def _draw_index(fb, night):
    """The fixed index triangle at top centre, pointing
    down at the roll scale - orange by day, dimmed at
    night."""
    coords = _flat([(226, 20), (254, 20), (240, 44)])
    _poly(fb, coords, DIM if night else ORANGE)


def _draw_symbol(fb, night):
    """The fixed miniature aircraft at the centre: the
    videos' symbol (a wide bar with the centre hump and
    dot), ink-edged yellow by day, one dim pass at
    night. Drawn over the ball, under the hands."""
    def shape(ht):
        top = [(-76, 5 - ht), (-17, 5 - ht), (0, -8 - ht),
               (17, 5 - ht), (76, 5 - ht)]
        bot = [(76, 5 + ht), (17, 5 + ht), (0, -8 + ht),
               (-17, 5 + ht), (-76, 5 + ht)]
        return _flat([(CX + dx, CY + dy)
                      for dx, dy in top + bot])

    if night:
        _poly(fb, shape(5), DIM)
        classicface._dot(fb, CX, CY, 6, DIM)
        return
    _poly(fb, shape(7), INK)
    _poly(fb, shape(4), YELLOW)
    classicface._dot(fb, CX, CY, 10, INK)
    classicface._dot(fb, CX, CY, 6, YELLOW)


def _draw_ticks(fb, night):
    """The clock's 60 ticks inside the glass, over the
    ball - the brief's radii (outer 176; hours from
    154 w5, five-minutes 161 w3, minutes 168 w2)."""
    tick_c = NIGHT_TICK if night else CREAM
    i = 0
    while i < 60:
        ang = i * 6
        if i % 15 == 0:
            r0, w = 154, 5
        elif i % 5 == 0:
            r0, w = 161, 3
        else:
            r0, w = 168, 2
        _poly(fb, classicface._tick_coords(ang, r0, 176, w),
              tick_c)
        i += 1


# --- hands (the metar face's edged treatment) ---

def _edged_hand(fb, ang, length, base_w, tail):
    """One hand, twice: the ink edge pass, then the
    cream face - legible on sky and ground alike."""
    classicface._draw_hand(fb, ang, length, base_w + EDGE,
                           tail, INK)
    classicface._draw_hand(fb, ang, length, base_w, tail,
                           CREAM)


def _hands_day(fb, time_tuple):
    hour_ang = ((time_tuple[3] % 12)
                + time_tuple[4] / 60.0) * 30.0
    _edged_hand(fb, hour_ang, HOUR_LEN, HOUR_W, TAIL)
    min_ang = (time_tuple[4] + time_tuple[5] / 60.0) * 6.0
    _edged_hand(fb, min_ang, MIN_LEN, MIN_W, TAIL)
    if SECOND_HAND:
        sec_ang = time_tuple[5] * 6.0
        _edged_hand(fb, sec_ang, SEC_LEN, 4, TAIL + 10)
        a = math.radians(sec_ang)
        tx = CX - math.sin(a) * (TAIL + 10)
        ty = CY + math.cos(a) * (TAIL + 10)
        classicface._dot(fb, tx, ty, 7, INK)
        classicface._dot(fb, tx, ty, 4, CREAM)
    classicface._dot(fb, CX, CY, 11, INK)
    classicface._dot(fb, CX, CY, 5, CREAM)


def _hands_night(fb, time_tuple):
    """Pale hour and minute, minute-stepped, no second
    hand - the classic/metar night treatment."""
    hour_ang = ((time_tuple[3] % 12)
                + time_tuple[4] / 60.0) * 30.0
    classicface._draw_hand(fb, hour_ang, HOUR_LEN, HOUR_W,
                           TAIL, PALE)
    classicface._draw_hand(fb, time_tuple[4] * 6.0, MIN_LEN,
                           MIN_W, TAIL, PALE)
    classicface._dot(fb, CX, CY, 9, PALE)


# --- the bezel label ---

_label_cache = {}


def _label(name):
    hit = _label_cache.get(name)
    if hit is None:
        x0, y0, w, h, ch = attlabels.LABELS[name]
        hit = (x0, y0, w, h,
               binascii.a2b_base64("".join(ch)))
        _label_cache[name] = hit
    return hit


def _stamp_label(canvas, name, ink):
    """Blend the maneuver's name onto the bezel through
    its coverage mask - smoothfont.draw's pattern: per
    row, the canvas segment is read, the covered pixels
    blended in a scratch bytearray, and the segment
    written back as ONE slice. Zero per-byte writes
    into the frame buffer."""
    x0, y0, w, h, data = _label(name)
    buf = canvas.buf
    for r in range(h):
        do = ((y0 + r) * 480 + x0) * 2
        seg = bytearray(buf[do:do + w * 2])
        nrow = r * w
        changed = False
        for cx in range(w):
            nib = nrow + cx
            byte = data[nib >> 1]
            cov = (byte >> 4) if not (nib & 1) \
                else (byte & 15)
            if cov:
                so = cx * 2
                bg = seg[so] | (seg[so + 1] << 8)
                out = smoothfont._blend(ink, bg, cov)
                seg[so] = out & 0xFF
                seg[so + 1] = (out >> 8) & 0xFF
                changed = True
        if changed:
            buf[do:do + w * 2] = seg


# --- the static layer (the case: bezel, rim, screws) ---

def _draw_bezel(fb):
    """The case, drawn once per layer: near-black disc
    on near-black corners, the grey rim line at r=237,
    the glass bed black (the ball covers it every
    frame), four screws at the diagonals."""
    for win, y0 in fb.band_windows():
        win.fill(BEZEL)
        win.ellipse(CX, CY - y0, BEZEL_R, BEZEL_R, BEZEL,
                    True)
        win.ellipse(CX, CY - y0, BEZEL_R, BEZEL_R, RIMLINE,
                    False)
        win.ellipse(CX, CY - y0, GLASS_R, GLASS_R, 0, True)
    k = 0
    while k < 4:
        ang = 45 + 90 * k
        x, y = _pt(ang, SCREW_R)
        classicface._dot(fb, x, y, 9, SCREW)
        sa = math.radians(ang * 2 + 15)     # the slot's tilt
        dx, dy = math.cos(sa) * 5, math.sin(sa) * 5
        wins, bh = _bands(fb)
        for win, y0 in wins:
            if y + 6 >= y0 and y - 6 < y0 + bh:
                win.line(int(x - dx), int(y - dy) - y0,
                         int(x + dx), int(y + dy) - y0,
                         SCREW_SLOT)
        k += 1


# --- the face-module API (contract in clockface's header) ---

_static = None        # the canvas render_static() last drew into
_night_static = None  # the canvas render_night() last drew into


def render_static(canvas):
    """Draw the DAY static layer (the case) into canvas
    (display.dial()); remembered for compose()."""
    global _static
    _draw_bezel(canvas)
    _static = canvas
    return canvas


def render_night(canvas):
    """Draw the NIGHT static layer into canvas
    (display.night_dial()) - the same case; the night
    lives in the ball and hands, drawn per frame. The
    day layer is never touched."""
    global _night_static
    _draw_bezel(canvas)
    _night_static = canvas
    return canvas


def compose(canvas, time_tuple, state=None):
    """One frame of the attitude face at time_tuple: the
    case copied in, the ball at the cycle's current
    attitude, gyro ticks, the miniature aircraft, the
    index, the clock ticks, the date (when show_date is
    on), the hands in the foreground, and the maneuver's
    name on the bottom bezel at its fade. state follows
    the painter's convention: {"night": True, "dial":
    canvas} for a sleep frame."""
    if state is None:
        state = {}
    night = state.get("night", False)
    src = state.get("dial", _night_static if night
                    else _static)
    if src is not None and src is not canvas:
        canvas.copy_from(src)
    elif src is None:
        _draw_bezel(canvas)     # render_static never ran
    seg, local_t, bank, pitch = _smooth(
        _advance(time_tuple, state.get("ms")))
    _draw_ball(canvas, bank, pitch, night)
    _draw_gyro(canvas, bank, night)
    _draw_symbol(canvas, night)
    _draw_index(canvas, night)
    _draw_ticks(canvas, night)
    if _show_date:
        smoothfont.draw(canvas,
                        clockface.date_string(time_tuple),
                        CX, _DATE_CAP_Y, "date",
                        PALE if night else CREAM)
    if night:
        _hands_night(canvas, time_tuple)
    else:
        _hands_day(canvas, time_tuple)
    f = _fade(local_t, attdata.DURATIONS[seg])
    if f > 0.0:
        ink = smoothfont._blend(DIM if night else WHITE,
                                BEZEL, int(round(f * 15)))
        if ink != BEZEL:
            _stamp_label(canvas, attdata.NAMES[seg], ink)
    return canvas
