# bench_first_frame.py - BENCH RUNNER: the first real frame.
#
# Run this file in Thonny on the board (painter-firmware_v2.bin).
# It brings the panel up through display.py, renders the selected
# face's static dial, composes ONE frame and shows it. No Wi-Fi, no
# updater, no admin server - display layer only.
#
# The hands are set to 10:09 - a FIXED DEMO TIME (the classic
# clock-advertising position), not the real time. Real timekeeping
# arrives with timekeep.py in the main.py path; this file exists to
# prove dial + hands + banded show() on the glass.
import admin
import display

# Face selection: the admin "face" config key picks the module
# (SPEC Nov 15 addendum). Only the painter exists so far; classic
# and digital plug in here as face_classic / face_digital later.
FACES = {
    "painter": "clockface",
    # "classic": "face_classic",
    # "digital": "face_digital",
}

# 10:09, fixed demo time: (year, month, day, hour, minute, second,
# weekday, yearday) - compose() reads [3] and [4].
DEMO_TIME = (2026, 11, 15, 10, 9, 0, 6, 319)


def pick_face():
    cfg = admin.load_config()
    name = cfg.get("face", "painter")
    mod_name = FACES.get(name)
    if mod_name is None:
        print("bench: face %r not built yet - using the painter"
              % (name,))
        name, mod_name = "painter", FACES["painter"]
    print("bench: face =", name)
    return __import__(mod_name)


def main():
    face = pick_face()
    live = display.init()
    print("bench: display live:", live)
    face.render_static(display.dial())
    face.compose(display.canvas(), DEMO_TIME)
    shown = display.show()
    print("bench: first frame shown:", shown,
          "- dial + hands at 10:09 (fixed demo time)")


main()
