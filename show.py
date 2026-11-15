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
# The hourly cuckoo ritual (SPEC.md 3.4) is NOT scheduled in v1:
# its frost patch and sharp face sprite don't exist yet. The
# frost_clear state and lean_in intent are carried so the ritual
# drops in without an API change. On the hour both hands are still
# fully wiped and repainted (the hour hand steps then anyway).
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

IDLE_DUR = {  # ms, from the prototype
    "watch": 2100, "brow": 2100, "sip": 2100, "shoulder": 2100,
    "hat": 4000, "hanky": 3600,
}
IDLE_TYPES = ("watch", "brow", "shoulder", "sip", "hat", "hanky")
IDLE_GAP_MIN = 9000     # idle routines no more often than this...
IDLE_GAP_RAND = 20000   # ...plus a random extra wait


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
        self.last_total = None   # last total-minutes accounted for
        self.frost_clear = 0.0   # cuckoo porthole (not in v1 shows)
        self.idle = None         # {"type","start","dur"}
        self.next_idle = IDLE_GAP_MIN  # first routine isn't instant
        self._last_now = None

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
        self.idle = None

    def demo(self, now_ms):
        """Run one full minute step on demand, from the currently
        displayed minute to the next. Returns False if no time has
        been set yet (update() never called)."""
        if self.last_total is None or self.running:
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
        self.tick(now_ms, total)
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
        return pose

    # --- per-frame advance (no drawing) ---

    def tick(self, now_ms, total_minutes):
        """Advance the machine and the figure. Call every frame."""
        if self._last_now is None:
            dt = 0
        else:
            dt = now_ms - self._last_now
            if dt < 0:
                dt = 0
            if dt > 250:
                dt = 250     # a long stall eases in steps, not a leap
        self._last_now = now_ms
        if self.last_total is None:
            # first frame after boot: paint the current time, no show
            self.min_hand = {"angle": clockface.minute_angle(total_minutes),
                             "reveal": 1.0}
            self.hour_hand = {
                "angle": clockface.hour_angle_stepped(total_minutes),
                "reveal": 1.0}
            self.last_total = total_minutes
        elif total_minutes > self.last_total and not self.running:
            # forward only: a demo minute or an NTP step backwards
            # must not rewind the show
            self.start_show(self.last_total, total_minutes, now_ms)
            self.last_total = total_minutes
        if self.running:
            self._run_step(now_ms)
        else:
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
                self.next_idle = now_ms + IDLE_GAP_MIN
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

    # --- idle routines ---

    def _run_idle(self, now_ms):
        self.fig.set_intent(bend=0.0)
        if self.idle is None:
            if now_ms >= self.next_idle:
                t = random.choice(IDLE_TYPES)
                self.idle = {"type": t, "start": now_ms,
                             "dur": IDLE_DUR[t]}
            else:
                self.fig.set_intent(tip=None, tool=None, follow=0.0,
                                    tau_ms=380, head_tilt=0.0)
                return
        p = (now_ms - self.idle["start"]) / self.idle["dur"]
        if p >= 1:
            self.idle = None
            self.next_idle = now_ms + IDLE_GAP_MIN \
                + random.randint(0, IDLE_GAP_RAND)
            self.fig.set_intent(tip=None, tool=None, follow=0.0,
                                tau_ms=380, head_tilt=0.0)
            return
        self._idle_intent(self.idle["type"], p)

    def _idle_intent(self, t, p):
        # Each routine is an intent timeline. The wristwatch check
        # is sketched; the rest carry the prototype's durations and
        # get their full timelines in the engine build-out - every
        # target below was reach-checked in the prototype
        # (SPEC.md 3.5). v1 figure note: routines that would move
        # the head or hands beyond a hang read as stillness for now.
        fig = self.fig
        if t == "watch":
            # brush hand rises toward his face, head tilts down
            tip = (fig.feet_x + 30, fig.feet_y - figmod.HEAD_H + 26)
            env = math.sin(min(1.0, p * 1.15) * math.pi)
            if env > 0.05:
                fig.set_intent(tip=tip, tool="hand", follow=0.10,
                               tau_ms=200, head_tilt=-0.4 * env)
            else:
                fig.set_intent(tip=None, tool=None, follow=0.0,
                               tau_ms=380, head_tilt=0.0)
        else:
            # brow / shoulder / sip / hat / hanky - timelines land
            # with the idle build-out; he stands easy meanwhile.
            fig.set_intent(tip=None, tool=None, follow=0.0, tau_ms=380)

    # --- drawing helper for the older loop shape (main.py) ---

    def draw_hands(self, fb):
        clockface.draw_hand(fb, self.hour_hand["angle"],
                            clockface.HOUR_LEN, clockface.HOUR_W,
                            self.hour_hand["reveal"])
        clockface.draw_hand(fb, self.min_hand["angle"],
                            clockface.MIN_LEN, clockface.MIN_W,
                            self.min_hand["reveal"])
        # the cuckoo frost patch will composite here when it lands
        # (SPEC 4.3): frost_clear drives the circular mask.


def step_to_min_angle(show):
    """Minute angle the glance looks at: the hand about to be wiped
    is the currently painted one. (Kept from the skeleton; the
    glance step now carries its own "from" angle.)"""
    return show.min_hand["angle"]
