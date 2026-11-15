# main.py - Painter Clock: the conductor.
#
# Boot order matters and follows the other Micro builds:
#   1. Sample BOOT (rehoming gesture) BEFORE anything that can hang
#   2. RTC -> system clock (right time on the first frame)
#   3. Wi-Fi join (or the setup portal, if asked / no creds)
#   4. NTP sync (writes the RTC back)
#   5. Display init through the display.py seam
#   6. Admin server, updater pacing, then the animation loop:
#      dial layer -> figure -> hands -> present, ~30 fps target
#
# Settings persist in config.json on the board; credentials in
# wifi_cfg.py. Neither is ever touched by the updater.
import gc
import time

import machine
import network

import admin
import clockface
import display
import figure as figmod
import prov
import show as showmod
import timekeep
import updater

FRAME_MS = 33  # ~30 fps target during motion; loop idles cheaply


def join_wifi(ssid, password, tries=2):
    """Join the saved network. Retries the whole attempt - the
    radio can wedge after repeated soft reboots on these builds;
    a full unplug is the cure for a truly wedged radio, not code."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    for attempt in range(tries):
        if wlan.isconnected():
            return wlan
        try:
            wlan.connect(ssid, password)
        except Exception as exc:
            print("main: connect error:", exc)
        start = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), start) > 15000:
                break
            time.sleep_ms(250)
        if wlan.isconnected():
            print("main: Wi-Fi up:", wlan.ifconfig())
            return wlan
        print("main: join attempt", attempt + 1, "failed; retrying")
        try:
            wlan.disconnect()
        except Exception:
            pass
        time.sleep_ms(1000)
    return wlan if wlan.isconnected() else None


def main():
    # 1. rehoming gesture first - before anything that can hang
    ssid, password = prov.load_creds()
    if prov.boot_button_held() or not prov.creds_usable(ssid):
        prov.run_portal()  # never returns (reboots on save)

    # 2. RTC before Wi-Fi
    timekeep.boot_set_from_rtc()

    cfg = admin.load_config()
    app = {"config": cfg, "time_str": "", "time_source": "none",
           "display_state": "stub", "changed": False}

    # 3 + 4. network, then NTP
    wlan = join_wifi(ssid, password)
    if wlan is not None:
        timekeep.ntp_sync()
    app["time_source"] = timekeep.source()

    # 5. display (stub-tolerant: everything below runs regardless)
    live = display.init()
    app["display_state"] = "live" if live else "stub - no driver yet"
    fb = display.framebuffer()

    # static dial layer, rendered once
    import framebuf
    dial_buf = bytearray(480 * 480 * 2)
    dial = framebuf.FrameBuffer(dial_buf, 480, 480, framebuf.RGB565)
    clockface.draw_dial(dial)

    # 6. servers + the show
    admin.start()
    updater.check()  # after-boot check: flags only, never installs
    fig = figmod.Figure()
    show = showmod.Show(fig)

    last_ms = time.ticks_ms()
    last_housekeep = last_ms
    while True:
        now_ms = time.ticks_ms()
        dt = time.ticks_diff(now_ms, last_ms)
        last_ms = now_ms
        if dt < 0:
            dt = 0
        if dt > 250:
            dt = 250

        loc = timekeep.now_local(cfg["tz_offset_h"])
        total_minutes = loc[3] * 60 + loc[4]
        app["time_str"] = "%02d:%02d:%02d" % (loc[3], loc[4], loc[5])
        app["time_source"] = timekeep.source()

        # choreography + rig
        show.tick(now_ms, total_minutes)
        fig.update(dt, now_ms)
        pose = fig.pose()

        # compose: dial layer -> figure -> hands -> present
        fb.blit(dial, 0, 0)
        fig.draw(fb, pose)
        show.draw_hands(fb)
        display.show()

        # night mode (open question in SPEC sec.8 - wired, defaulted off)
        if cfg["night_mode"]:
            night = loc[3] >= 22 or loc[3] < 6
            display.set_backlight(cfg["night_dim"] if night else 255)

        admin.step(app)
        if app["changed"]:
            app["changed"] = False
            cfg = admin.load_config()
            app["config"] = cfg

        # housekeeping, only while he's idle - never mid-show
        if not show.running and \
                time.ticks_diff(now_ms, last_housekeep) > 5000:
            last_housekeep = now_ms
            if wlan is not None and wlan.isconnected():
                updater.maybe_check()
                timekeep.maybe_resync()
            gc.collect()

        # frame pacing
        spent = time.ticks_diff(time.ticks_ms(), now_ms)
        if spent < FRAME_MS:
            time.sleep_ms(FRAME_MS - spent)


main()
