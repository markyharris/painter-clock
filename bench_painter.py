# bench_painter.py - BENCH RUNNER: the painter himself, one show.
#
# Run this file in Thonny on the board (painter-firmware_v2.bin).
# It brings the panel up through display.py, renders the dial,
# pre-composites the figure body rects, paints the scene at
# 10:09, then
# runs the 10:10 minute show ONCE in real time - glance, wipe the
# old minute hand, step to the bucket and dip, paint the new hand,
# step back and inspect - printing per-frame timings at the end
# and holding the final 10:10 frame. No Wi-Fi, no updater, no
# admin server, no main.py (renamed main_app.py during bench work
# - this runner is self-contained like bench_first_frame.py).
#
# The show is wall-clock driven (show.py keys its stages off
# ticks_ms), so it takes its real ~8.2 s however fast frames land;
# the timings printed are per-frame update()+show() cost.
import time

import clockface
import display
import figure
import show as showmod

# Fixed demo time, as in bench_first_frame.py: the scene paints
# 10:09 and the show steps it to 10:10.
T_1009 = (2026, 11, 15, 10, 9, 0, 6, 319)
T_1010 = (2026, 11, 15, 10, 10, 0, 6, 319)


def main():
    live = display.init()
    print("bench: display live:", live)

    t0 = time.ticks_ms()
    clockface.render_static(display.dial())
    print("bench: dial render ms:",
          time.ticks_diff(time.ticks_ms(), t0))

    t0 = time.ticks_ms()
    figure.prepare(display.dial())
    print("bench: rect prepare ms:",
          time.ticks_diff(time.ticks_ms(), t0))

    fig = figure.Figure()
    sh = showmod.Show(fig, display.dial())
    canvas = display.canvas()

    # the scene at 10:09, then half a second of standing frames so
    # he settles naturally before the show
    sh.update(canvas, time.ticks_ms(), T_1009)
    print("bench: scene at 10:09 shown:", display.show())
    settle_end = time.ticks_add(time.ticks_ms(), 500)
    while time.ticks_diff(settle_end, time.ticks_ms()) > 0:
        sh.update(canvas, time.ticks_ms(), T_1009)
        display.show()
        time.sleep_ms(10)

    # one full minute step, in real time
    sh.demo(time.ticks_ms())
    print("bench: show running - glance, wipe, dip, paint, inspect")
    frames = []
    show_start = time.ticks_ms()
    while sh.running:
        t0 = time.ticks_ms()
        sh.update(canvas, t0, T_1009)
        display.show()
        frames.append(time.ticks_diff(time.ticks_ms(), t0))
        time.sleep_ms(5)
    wall = time.ticks_diff(time.ticks_ms(), show_start)

    # a few final frames at 10:10, then hold
    for _ in range(3):
        sh.update(canvas, time.ticks_ms(), T_1010)
        display.show()
        time.sleep_ms(30)

    if frames:
        avg = sum(frames) / len(frames)
        print("bench: show wall ms:", wall, "- frames:", len(frames))
        print("bench: frame update+show ms - min:", min(frames),
              "avg:", int(avg), "max:", max(frames))

    # figure-only draw cost (pose + draw, no hands, no show) -
    # the number the v2 rect path is judged by; drawn onto the
    # frame canvas without show(), then the held frame is
    # re-composed clean
    reps = []
    for _ in range(10):
        t0 = time.ticks_ms()
        fig.draw(canvas, fig.pose())
        reps.append(time.ticks_diff(time.ticks_ms(), t0))
    print("bench: figure draw ms - min:", min(reps),
          "avg:", int(sum(reps) / len(reps)), "max:", max(reps))
    sh.update(canvas, time.ticks_ms(), T_1010)
    display.show()
    print("bench: final frame held at 10:10")


main()
