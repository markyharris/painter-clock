# main.py - Painter Clock: the conductor.
#
# Boot order (each stage logs a "main:" line, so a Thonny console
# shows the whole boot story):
#   1. BOOT sample - the rehoming gesture, BEFORE anything that
#      can hang (prov.run_portal() never returns)
#   2. display.init() - MUST precede the RTC and Wi-Fi stages:
#      board-proven Nov 15, 2026 that Board.begin() fails if
#      other hardware activity (the I2C bus, the radio) has run
#      first; every successful bench run began the panel first.
#      (timekeep also uses SoftI2C for the same reason.)
#   3. timekeep.init_rtc() - system clock from the PCF85063, so
#      the first painted frame already shows local time
#   4. Wi-Fi join from wifi_cfg.py; no usable creds OR a failed
#      join drops into the PainterClock-Setup portal (rehoming)
#   5. NTP sync - the authority; non-fatal if it fails (the RTC
#      carries the clock, and the loop re-syncs when it can)
#   6. The face's render_static() into the dial layer ->
#      figure.prepare() (body rects over the dial)
#   7. admin server + the updater's after-boot check (flag only)
#   8. The run loop: show.Show driven by REAL local time
#
# The loop: show.update() composes a frame only when something
# changed - a show running, an idle routine active, a minute
# boundary crossed, or a short settle window after activity
# (he eases home). Between routines the standing scene simply
# holds on the panel; the loop sleeps in small slices and
# services the admin server every slice, so the page stays
# responsive without burning frames. Housekeeping (update
# check, NTP re-sync, gc) runs only while he is idle.
#
# Fail soft everywhere: no NTP -> run from the RTC; display not
# live -> keep painting into the canvases and serving admin.
#
# Settings persist in config.json on the board; credentials in
# wifi_cfg.py. Neither is ever touched by the updater.
import gc
import time

import network

import admin
import display
import figure as figmod
import prov
import show as showmod
import timekeep
import updater

VERSION = "1.0"

# Face selection (SPEC Nov 15 addendum): the admin "face" key
# names a module with render_static()/compose(). Only the
# painter exists so far; classic/digital plug in here later,
# and unknown names fall back to the painter (bench_first_frame
# uses the same map).
FACES = {
    "painter": "clockface",
    # "classic": "face_classic",
    # "digital": "face_digital",
}

JOIN_TIMEOUT_MS = 15000   # ~15 s, then the portal (rehoming)
LOOP_MS = 25              # idle slice; admin is serviced per slice
SETTLE_MS = 1500          # keep framing this long after activity
HOUSEKEEP_MS = 5000       # housekeeping cadence while idle


def join_wifi(ssid, password):
    """Join the saved network, one ~15 s window. Returns the
    WLAN object or None."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        print("main: Wi-Fi already up:", wlan.ifconfig())
        return wlan
    try:
        wlan.connect(ssid, password)
    except Exception as exc:
        print("main: Wi-Fi connect error:", exc)
        return None
    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > JOIN_TIMEOUT_MS:
            print("main: Wi-Fi join timed out after %d ms"
                  % JOIN_TIMEOUT_MS)
            return None
        time.sleep_ms(200)
    print("main: Wi-Fi up:", wlan.ifconfig())
    return wlan


def _face_module(name):
    mod_name = FACES.get(name)
    if mod_name is None:
        print("main: face %r not built yet - using the painter"
              % (name,))
        mod_name = FACES["painter"]
    return __import__(mod_name)


def _apply_sleep(show, cfg):
    """Hand the config's sleep hours to the show (idle life v1:
    the hours suppress random idle routines; the sleep
    behaviour itself is a later phase)."""
    def mins(s):
        try:
            return int(s[0:2]) * 60 + int(s[3:5])
        except Exception:
            return 0
    show.set_sleep(cfg.get("sleep_enabled", False),
                   mins(cfg.get("sleep_start", "22:00")),
                   mins(cfg.get("sleep_end", "06:00")))


def _wifi_str(wlan, ssid):
    try:
        if wlan is not None and wlan.isconnected():
            return "%s - %s" % (ssid, wlan.ifconfig()[0])
    except Exception:
        pass
    return "not connected"


def _uptime_str(boot_ms):
    s = time.ticks_diff(time.ticks_ms(), boot_ms) // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return "%dd %02d:%02d:%02d" % (d, h, m, s)
    return "%02d:%02d:%02d" % (h, m, s)


def main():
    boot_ms = time.ticks_ms()
    print("main: Painter Clock booting (code %s)" % VERSION)

    # 1. Rehoming gesture first - before anything that can hang.
    if prov.boot_button_held():
        print("main: BOOT held just after power-up - setup portal")
        prov.run_portal()  # never returns (reboots on save)

    cfg = admin.load_config()
    app = {"config": cfg, "time_str": "--:--:--",
           "time_source": timekeep.time_source(), "wifi": "",
           "display_state": "starting", "uptime": "00:00:00",
           "version": VERSION, "changed": False, "tryit": None}

    # 2. Display FIRST (see the header: begin() refuses if the
    # RTC bus or the radio has run before it). The panel sits
    # begun and dark until the loop's first composed frame.
    live = display.init()
    app["display_state"] = "live" if live else "not live - headless"
    if not live:
        print("main: display not live - running headless "
              "(admin still served)")
    display.set_backlight(cfg["brightness"])

    # 3. RTC -> system clock (local time from the first frame).
    timekeep.init_rtc()

    # 4. Wi-Fi. No usable creds, or a failed join, means the
    # setup portal - that is the rehoming contract.
    ssid, password = prov.load_creds()
    if not prov.creds_usable(ssid):
        print("main: no saved Wi-Fi credentials - setup portal")
        prov.run_portal()  # never returns
    wlan = join_wifi(ssid, password)
    if wlan is None:
        print("main: Wi-Fi join failed - setup portal")
        prov.run_portal()  # never returns
    app["wifi"] = _wifi_str(wlan, ssid)

    # 5. NTP - authority, but non-fatal: the RTC carries us.
    timekeep.sync_ntp()
    app["time_source"] = timekeep.time_source()

    # 6. Dial layer, figure rects.
    face_name = cfg.get("face", "painter")
    frost_now = cfg.get("frost", 55)
    face_mod = _face_module(face_name)
    face_mod.render_static(display.dial())
    print("main: dial rendered (face: %s)" % face_name)
    figmod.prepare(display.dial(), frost_now)
    print("main: figure prepared (frost %s)" % frost_now)

    # 7. Admin + after-boot update check (flags only).
    admin.start()
    updater.check()

    fig = figmod.Figure()
    show = showmod.Show(fig, display.dial())
    _apply_sleep(show, cfg)
    canvas = display.canvas()

    # 8. The run loop.
    print("main: running")
    drawn_total = None      # total-minutes of the last drawn frame
    last_active_ms = boot_ms
    last_housekeep = boot_ms
    last_status_s = -1
    while True:
        now_ms = time.ticks_ms()
        loc = timekeep.now_tuple()
        total = loc[3] * 60 + loc[4]

        # Compose only when something changed: a show or idle
        # routine in progress, a routine due or a try-it queued
        # (the scheduler must be serviced on its own timing, not
        # only in post-show settle windows), a minute boundary
        # crossed since the last drawn frame, or the settle
        # window after activity (he is still easing home).
        active = (show.running or show.idle is not None
                  or show.tryit is not None
                  or (show.next_idle_at is not None
                      and time.ticks_diff(now_ms,
                                          show.next_idle_at) >= 0)
                  or total != drawn_total
                  or time.ticks_diff(now_ms, last_active_ms)
                  < SETTLE_MS)
        if active:
            try:
                show.update(canvas, now_ms, loc)
                display.show()
            except Exception as exc:
                print("main: frame failed:", exc)
            drawn_total = total
            if show.running or show.idle is not None:
                last_active_ms = now_ms

        # Status strings for the admin page, refreshed ~1/s.
        if loc[5] != last_status_s:
            last_status_s = loc[5]
            app["time_str"] = "%02d:%02d:%02d" % (loc[3], loc[4],
                                                  loc[5])
            app["time_source"] = timekeep.time_source()
            app["uptime"] = _uptime_str(boot_ms)
            app["wifi"] = _wifi_str(wlan, ssid)

        admin.step(app)
        if app.get("tryit") is not None:
            # an admin Try-it press: queue the routine; it runs
            # at the next gap where it fits before the boundary
            show.queue_idle(app["tryit"])
            app["tryit"] = None
        if app["changed"]:
            app["changed"] = False
            cfg = admin.load_config()
            app["config"] = cfg
            _apply_sleep(show, cfg)
            display.set_backlight(cfg["brightness"])
            if cfg.get("face", "painter") != face_name:
                face_name = cfg.get("face", "painter")
                frost_now = cfg.get("frost", 55)
                face_mod = _face_module(face_name)
                face_mod.render_static(display.dial())
                figmod.prepare(display.dial(), frost_now)
                drawn_total = None  # force a repaint
                print("main: face changed to %s" % face_name)
            elif cfg.get("frost", 55) != frost_now:
                # frost only: the rects are re-baked with the new
                # strength (prepare is keyed on it); the dial and
                # the panel are untouched
                frost_now = cfg.get("frost", 55)
                figmod.prepare(display.dial(), frost_now)
                drawn_total = None  # force a repaint
                print("main: frost changed to %s" % frost_now)

        # Housekeeping, only while he is idle - never mid-show.
        if not show.running and \
                time.ticks_diff(now_ms, last_housekeep) > HOUSEKEEP_MS:
            last_housekeep = now_ms
            if wlan is not None and wlan.isconnected():
                updater.maybe_check()
                timekeep.maybe_resync()
            gc.collect()

        time.sleep_ms(LOOP_MS)


main()
