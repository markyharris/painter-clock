# show.py - the choreography state machine.
#
# Owns: the minute show (glance -> wipe -> dip -> paint -> inspect),
# the hour-hand steps every 12 minutes, the hourly cuckoo ritual,
# and the idle routines between shows. Emits, per frame:
#   * hand states (angle + reveal per hand) for clockface.draw_hand
#   * figure intent (tip / tool / follow / bend / ...) for figure.py
#   * frost_clear 0..1 for the cuckoo porthole (SPEC.md 3.4/4.3)
# One stroke-progress value per step drives reveal, tool tip and
# body together - they cannot drift apart (SPEC.md sec.3).
import math
import random

import clockface
import figure as figmod

# step durations, ms - the prototype's numbers (SPEC.md 3.1/3.4)
DUR = {
    "glance": 300,
    "wipe_min": 950,
    "wipe_hour": 600,
    "dip": 1050,
    "paint_hour": 650,
    "paint_min": 1150,
    "inspect": 520,
    # cuckoo ritual (PROTOTYPE-PENDING - reconcile when it lands)
    "lean_in": 1000,
    "wipe_circle": 1300,
    "face_hold": 1200,
    "frost_return": 1500,
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


def bend_env(p):
    """Dip bend envelope: fold in 0-.32, HOLD .32-.68, straighten
    .68-1. A held plateau, never a sine hump - a bend that only
    peaks for an instant reads as no bend at all."""
    if p < 0.32:
        return ease(p / 0.32)
    if p < 0.68:
        return 1.0
    return 1.0 - ease((p - 0.68) / 0.32)


class Show:
    def __init__(self, fig):
        self.fig = fig
        self.min_hand = {"angle": 0.0, "reveal": 1.0}
        self.hour_hand = {"angle": 0.0, "reveal": 1.0}
        self.steps = []          # current show's step list
        self.step_i = 0
        self.step_start = 0
        self.running = False
        self.last_total = None   # last total-minutes a show ran for
        self.frost_clear = 0.0   # cuckoo porthole: 0 frosted, 1 clear
        self.idle = None         # {"type","start","dur"}
        self.next_idle = 0

    # --- show construction ---

    def _build_show(self, from_total, to_total, on_hour):
        need_hour = (clockface.hour_angle_stepped(from_total)
                     != clockface.hour_angle_stepped(to_total))
        steps = [{"type": "glance"}]
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
        if on_hour:
            # the cuckoo ritual follows the repaint (SPEC.md 3.4)
            steps.append({"type": "lean_in"})
            steps.append({"type": "wipe_circle"})
            steps.append({"type": "face_hold"})
            steps.append({"type": "frost_return"})
        steps.append({"type": "inspect"})
        return steps

    def start_show(self, from_total, to_total, now_ms):
        on_hour = (to_total % 60 == 0)
        self.steps = self._build_show(from_total, to_total, on_hour)
        self.step_i = 0
        self.step_start = now_ms
        self.running = True
        self.idle = None

    # --- per-frame update ---

    def tick(self, now_ms, total_minutes):
        """Advance everything. Call every frame."""
        if self.last_total is None:
            # first frame after boot: paint the current time, no show
            self.min_hand = {"angle": clockface.minute_angle(total_minutes),
                             "reveal": 1.0}
            self.hour_hand = {
                "angle": clockface.hour_angle_stepped(total_minutes),
                "reveal": 1.0}
            self.last_total = total_minutes
        if total_minutes != self.last_total and not self.running:
            self.start_show(self.last_total, total_minutes, now_ms)
            self.last_total = total_minutes
        if self.running:
            self._run_step(now_ms)
        else:
            self._run_idle(now_ms)

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
        elif t == "wipe_circle":
            self.frost_clear = 1.0
        elif t == "frost_return":
            self.frost_clear = 0.0

    def _apply_step(self, step, p):
        t = step["type"]
        fig = self.fig
        if t == "glance":
            tip = clockface.hand_tip(step_to_min_angle(self), 1.0,
                                     clockface.MIN_LEN)
            fig.set_intent(tip=tip, tool=None, follow=0.35, tau_ms=300,
                           head_tilt=(tip[0] - clockface.CX)
                           / clockface.MIN_LEN)
        elif t in ("wipe_min", "wipe_hour"):
            hand = self.min_hand if t == "wipe_min" else self.hour_hand
            length = clockface.MIN_LEN if t == "wipe_min" \
                else clockface.HOUR_LEN
            hand["angle"] = step["from"]
            hand["reveal"] = 1.0 - ease(p)
            tip = clockface.hand_tip(step["from"], hand["reveal"], length)
            fig.set_intent(tip=tip, tool="cloth", follow=0.68,
                           tau_ms=170, head_tilt=0.0)
        elif t == "dip":
            bend = bend_env(p)
            dab = 0.0
            if 0.38 <= p < 0.68:
                dab = abs(math.sin((p - 0.38) / 0.30 * 2 * math.pi))
            tip = (figmod.BUCKET[0], figmod.BUCKET[1] - 14 + dab * 7)
            fig.set_intent(tip=tip, tool="brush", follow=0.30,
                           tau_ms=200, bend=bend, head_tilt=0.0)
        elif t in ("paint_min", "paint_hour"):
            hand = self.min_hand if t == "paint_min" else self.hour_hand
            length = clockface.MIN_LEN if t == "paint_min" \
                else clockface.HOUR_LEN
            hand["angle"] = step["to"]
            hand["reveal"] = ease(p)
            tip = clockface.hand_tip(step["to"], hand["reveal"], length)
            fig.set_intent(tip=tip, tool="brush", follow=0.68,
                           tau_ms=170, head_tilt=0.0)
        elif t == "lean_in":
            fig.set_intent(tip=None, tool=None, follow=0.05, tau_ms=320,
                           lean_in=ease(p), head_tilt=0.0)
        elif t == "wipe_circle":
            # cloth circles on the glass over his face (SPEC 3.4)
            head = (self.fig.feet_x, self.fig.feet_y - figmod.HEAD_H)
            a = p * 2 * math.pi * 1.5
            tip = (head[0] + math.cos(a) * 30, head[1] + math.sin(a) * 30)
            self.frost_clear = ease(p)
            fig.set_intent(tip=tip, tool="cloth", follow=0.10,
                           tau_ms=170, lean_in=1.0)
        elif t == "face_hold":
            self.frost_clear = 1.0
            fig.set_intent(tip=None, tool=None, follow=0.05, tau_ms=320,
                           lean_in=1.0)
        elif t == "frost_return":
            self.frost_clear = 1.0 - ease(p)
            fig.set_intent(tip=None, tool=None, follow=0.05, tau_ms=320,
                           lean_in=1.0 - ease(p))
        elif t == "inspect":
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
        # Each routine is an intent timeline. The wristwatch check is
        # sketched; the rest carry the prototype's durations and get
        # their full timelines in the engine build-out (TODO) - every
        # target below was reach-checked in the prototype (SPEC 3.5).
        fig = self.fig
        if t == "watch":
            # brush hand rises to his face height, head tilts down
            tip = (fig.feet_x + 30, fig.feet_y - figmod.HEAD_H + 26)
            env = math.sin(min(1.0, p * 1.15) * math.pi)
            if env > 0.05:
                fig.set_intent(tip=tip, tool=None, follow=0.10,
                               tau_ms=200, head_tilt=-0.4 * env)
            else:
                fig.set_intent(tip=None, tool=None, follow=0.0,
                               tau_ms=380, head_tilt=0.0)
        elif t == "hat":
            # TODO(engine): cap timeline - grab 0-.22, lift clear
            # .26-.42, hold (cap in brush hand, brush hidden), two
            # cloth passes over the forehead, cap back on (SPEC 3.5).
            fig.set_intent(tip=None, tool=None, follow=0.0, tau_ms=380)
        elif t == "hanky":
            # TODO(engine): cloth to nose, head dip, two blows with
            # hanky puff envelope, final dab (SPEC 3.5).
            fig.set_intent(tip=None, tool=None, follow=0.0, tau_ms=380)
        else:
            # brow / shoulder / sip - TODO(engine) timelines.
            fig.set_intent(tip=None, tool=None, follow=0.0, tau_ms=380)

    # --- drawing ---

    def draw_hands(self, fb):
        clockface.draw_hand(fb, self.hour_hand["angle"],
                            clockface.HOUR_LEN, clockface.HOUR_W,
                            self.hour_hand["reveal"])
        clockface.draw_hand(fb, self.min_hand["angle"],
                            clockface.MIN_LEN, clockface.MIN_W,
                            self.min_hand["reveal"])
        # TODO(Sunday): cuckoo frost patch composites HERE, over the
        # figure, under nothing else - see SPEC 4.3. frost_clear
        # drives the circular mask; the sharp face variant is drawn
        # by figure.draw inside the cleared circle only.


def step_to_min_angle(show):
    """Minute angle the glance should look at: the hand about to be
    wiped is the currently painted one."""
    return show.min_hand["angle"]
