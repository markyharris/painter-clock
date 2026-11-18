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
#      - always via _enter_portal(), which begins the panel
#      first on the BOOT-hold path (stage 2 not reached yet)
#      and puts setupface's setup screen on it before the
#      portal starts (v22: a moved clock used to sit black
#      for the whole portal session and look dead)
#   5. NTP sync - the authority; non-fatal if it fails (the RTC
#      carries the clock, and the loop re-syncs when it can)
#   5b. The Connected splash (v23): the dial wearing the admin
#      page's address, rendered once and held ~35 s (servicing
#      admin) before the loop - boot joins only, never a
#      mid-run reconnect
#   6. The face's render_static() into the dial layer (plus
#      its render_night() into the night layer, if it has
#      one) -> figure.prepare() (body rects over the dial -
#      the PAINTER face only; the classic/digital faces have
#      no figure, and in the loop they repaint on change -
#      each second awake, each minute asleep - where the
#      painter's show engine drives the frames below)
#   7. admin server + the updater's after-boot check (flag only)
#   8. The run loop: show.Show driven by REAL local time
#
# The loop: while he is AWAKE, show.update() composes frames
# continuously - he is always moving a little (the weight rock
# and the breathing between shows, the shows and routines
# themselves), so the standing scene is animated, not held.
# During sleep hours (v15: the sleep scene - he lies down and
# the hands snap pale each minute) the loop composes on the
# sleep cadence - about a frame a second, which the breathing
# swell and the drifting Z's are drawn for - plus the usual
# event terms (a minute boundary crossed, a try-it queued, a
# short settle window after activity). Either way the loop
# sleeps in small slices and services the admin server every
# slice, so the page stays responsive. Housekeeping (update
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
import connectface
import display
import figure as figmod
import metar as metarmod
import prov
import setupface
import show as showmod
import timekeep
import updater

VERSION = "1.0"

# Face selection (SPEC Nov 15 addendum): the admin "face" key
# names a module with render_static()/compose(). All five
# faces are built (the classic and digital landed in v26,
# the METAR analog in v28, the attitude maneuvers in v29);
# unknown names fall back to the painter (bench_first_frame
# uses the same map).
FACES = {
    "painter": "clockface",
    "classic": "classicface",
    "digital": "digitalface",
    "metar": "metarface",
    "attitude": "attface",
}

JOIN_TIMEOUT_MS = 15000   # ~15 s, then the portal (rehoming)
SPLASH_MS = 35000         # v23: the Connected screen's hold -
                          # the middle of Mark's "30-45 seconds"
LOOP_MS = 25              # idle slice; admin is serviced per slice
SETTLE_MS = 1500          # keep framing this long after activity
HOUSEKEEP_MS = 5000       # housekeeping cadence while idle
SLEEP_FRAME_MS = 1000     # sleep-scene cadence (v15): a frame
                          # about every second all night - the
                          # breathing and Z cycles are drawn in
                          # steps sized for it, and the minute
                          # snap lands within a second of the
                          # boundary


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


def _enter_portal(reason):
    """Setup mode (v22): put the setup screen on the panel
    FIRST, then run the portal (which never returns - it
    reboots on a save).

    The screen is setupface's static frame - the frosted dial
    with the how-to painted on it - rendered once and left up
    for the whole portal session. Before v22 nothing in the
    portal path ever composed a frame, so a moved clock sat
    black from plug-in to setup-done and looked dead (Mark's
    field report, Nov 16, 2026).

    The display is begun here when boot has not reached stage
    2 yet (the BOOT-hold path enters before it): init() is a
    no-op when the panel is already live, and beginning the
    panel before the portal's radio also honours the stage-2
    panel-first rule on every path. Fail soft: a screen that
    cannot be drawn must never cost the owner the portal."""
    print("main: %s - setup portal" % reason)
    try:
        cfg = admin.load_config()
        display.init()
        display.set_backlight(cfg["brightness"])
        setupface.render(display.canvas(),
                         cfg.get("backlight", 50))
        display.show()
        print("main: setup screen on the panel - join '%s', "
              "or browse to %s" % (prov.AP_SSID, prov.AP_IP))
    except Exception as exc:
        print("main: setup screen failed:", exc)
    prov.run_portal()  # never returns (reboots on save)


def _show_connected(cfg, wlan, ssid):
    """The Connected splash (v23): paint the admin page's
    address on the dial and show it. Called once per boot,
    right after the NTP sync, so the clock behind the splash
    is already time-true. Returns the ticks_ms the frame went
    up (the caller holds it for SPLASH_MS), or None if the
    render failed - fail-soft: boot continues to the face
    exactly as before v23. The IP is read from the WLAN's
    live ifconfig; the SSID is the one just joined."""
    try:
        ip = wlan.ifconfig()[0]
        connectface.render(display.canvas(), ssid, ip,
                           cfg.get("backlight", 50))
        display.show()
        print("main: connected - admin page at http://%s/ "
              "(on the panel for %d s)"
              % (ip, SPLASH_MS // 1000))
        return time.ticks_ms()
    except Exception as exc:
        print("main: connected screen failed:", exc)
        return None


def _hold_splash(splash_from, app):
    """Hold the Connected screen until SPLASH_MS has passed
    since it went up, servicing admin in LOOP_MS slices - the
    address on the glass must answer in a browser while it is
    still displayed. Anything admin queues meanwhile (a
    try-it, a config change) sits in the app dict and the run
    loop picks it up on its first pass, exactly as if it had
    arrived a moment later."""
    while time.ticks_diff(time.ticks_ms(), splash_from) \
            < SPLASH_MS:
        admin.step(app)
        time.sleep_ms(LOOP_MS)
    print("main: connected screen done - the face takes over")


def _face_module(name):
    mod_name = FACES.get(name)
    if mod_name is None:
        print("main: unknown face %r - using the painter"
              % (name,))
        mod_name = FACES["painter"]
    return __import__(mod_name)


def _apply_date(face_mod, cfg):
    """Hand the admin "show_date" setting to the face module -
    the face contract's date convention (clockface.py header):
    every face exposes set_show_date(on) and honours it in
    compose(). A face without the setter simply has no date."""
    setter = getattr(face_mod, "set_show_date", None)
    if setter is not None:
        setter(cfg.get("show_date", True))


def _apply_backlight(face_mod, cfg):
    """Hand the admin "backlight" setting to the face module
    (v18) - the same convention as the date: the painter
    exposes set_backlight(value) and bakes the glow into its
    static layer at the next render_static(). The figure's
    rim half of the effect is handed over separately, via
    figure.prepare()'s backlight argument. A face without
    the setter simply has no glow."""
    setter = getattr(face_mod, "set_backlight", None)
    if setter is not None:
        setter(cfg.get("backlight", 50))


def _render_night(face_mod):
    """Render the face's NIGHT static layer into display's
    night canvas, if the face has one (v26): every face with
    a sleep treatment exposes render_night(canvas). The
    painter always had it - figure's sleep path renders it
    lazily too; rendering it here as well keeps the one
    shared night canvas wearing the SELECTED face's night
    after a switch (the canvas is shared, the layers are
    per-face, and a stale layer from the previous face must
    never survive into this face's sleep). A face without
    render_night simply has no night layer."""
    render = getattr(face_mod, "render_night", None)
    if render is not None:
        render(display.night_dial())


def _apply_sleep(show, cfg):
    """Hand the config's sleep hours to the show: in the window
    the sleep scene owns the display (v15 - he lies down, the
    hands snap pale, routines and shows stop)."""
    def mins(s):
        try:
            return int(s[0:2]) * 60 + int(s[3:5])
        except Exception:
            return 0
    show.set_sleep(cfg.get("sleep_enabled", False),
                   mins(cfg.get("sleep_start", "22:00")),
                   mins(cfg.get("sleep_end", "06:00")))


def _apply_cuckoo(show, cfg):
    """Hand the config's cuckoo switch to the show (v20): the
    hourly ritual can be silenced in admin without code."""
    show.set_cuckoo(cfg.get("cuckoo_enabled", True))


def _switch_face(name, cfg):
    """Put a face on the dial - THE face-switch path
    (v29.1): resolve the module, hand it the admin
    date/backlight settings, render its static layer,
    re-render the night layer (the shared night canvas
    must wear the SELECTED face's night, never a stale
    one), and - for the painter - prepare the figure's
    rects over the new dial. Returns (module, frost,
    backlight); the caller owns the loop's face_name /
    drawn_total / face_key state. An admin pick and a
    rotation advance both come through here, so the two
    can never drift apart."""
    frost = cfg.get("frost", 55)
    backlight = cfg.get("backlight", 50)
    face_mod = _face_module(name)
    _apply_date(face_mod, cfg)
    _apply_backlight(face_mod, cfg)
    face_mod.render_static(display.dial())
    _render_night(face_mod)
    if name == "painter":
        figmod.prepare(display.dial(), frost, backlight)
    print("main: face changed to %s" % name)
    return face_mod, frost, backlight


def _rotate_ms(cfg):
    """The face-rotation interval in ms (v29.1): the
    admin rotate_minutes key, 1..240; anything else
    falls back to the 15-minute default - the same
    fall-back spirit as the admin save path."""
    try:
        mins = int(cfg.get("rotate_minutes", 15))
    except Exception:
        mins = 15
    if mins < 1 or mins > 240:
        mins = 15
    return mins * 60000


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
        _enter_portal("BOOT held just after power-up")

    cfg = admin.load_config()
    app = {"config": cfg, "time_str": "--:--:--",
           "time_source": timekeep.time_source(), "wifi": "",
           "display_state": "starting", "uptime": "00:00:00",
           "version": VERSION, "changed": False, "tryit": None,
           "trycuckoo": False, "idle_str": "-"}

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
        _enter_portal("no saved Wi-Fi credentials")
    wlan = join_wifi(ssid, password)
    if wlan is None:
        _enter_portal("Wi-Fi join failed")
    app["wifi"] = _wifi_str(wlan, ssid)

    # 5. NTP - authority, but non-fatal: the RTC carries us.
    timekeep.sync_ntp()
    app["time_source"] = timekeep.time_source()

    # 5b. The Connected splash (v23) - boot joins only. The
    # updater's reboot and the portal-save reboot both arrive
    # here through this same boot, so they splash too; nothing
    # later in the run can re-enter this path.
    splash_from = _show_connected(cfg, wlan, ssid)

    # 6. Dial layer, figure rects.
    face_name = cfg.get("face", "painter")
    frost_now = cfg.get("frost", 55)
    backlight_now = cfg.get("backlight", 50)
    date_now = cfg.get("show_date", True)
    airport_now = cfg.get("metar_airport", "KFLG")
    metarmod.set_airport(airport_now)
    face_mod = _face_module(face_name)
    _apply_date(face_mod, cfg)
    _apply_backlight(face_mod, cfg)
    face_mod.render_static(display.dial())
    _render_night(face_mod)
    print("main: dial rendered (face: %s)" % face_name)
    if face_name == "painter":
        # the figure's body rects bake over the PAINTER's
        # dial only (v26): on another face they would stamp
        # the man onto a dial that has no man in it.
        figmod.prepare(display.dial(), frost_now, backlight_now)
        print("main: figure prepared (frost %s, backlight %s)"
              % (frost_now, backlight_now))

    # 7. Admin + after-boot update check (flags only).
    admin.start()
    updater.check()
    if face_name == "metar":
        # one METAR fetch up front (v28): the face's first
        # frames already wear real weather instead of NO
        # DATA while the Connected splash holds; the loop's
        # housekeeping keeps it fresh from here.
        metarmod.poll(force=True)

    fig = figmod.Figure()
    show = showmod.Show(fig, display.dial())
    _apply_sleep(show, cfg)
    _apply_cuckoo(show, cfg)
    canvas = display.canvas()

    # 8. The run loop. First, the splash's remaining hold
    # (stages 6-7 spent part of it): the face's first frame is
    # composed only once the address has had its ~35 s, and it
    # paints the true time - the Show accounts from its first
    # tick (its last_total starts None), so a late loop entry
    # owes no show and skips none, and the midnight/monotonic
    # invariants are untouched.
    print("main: running")
    if splash_from is not None:
        _hold_splash(splash_from, app)
    drawn_total = None      # total-minutes of the last drawn frame
    face_key = None         # (total, second, night) of the last
                            # frame a NON-painter face drew (v26);
                            # None forces its next frame
    night_now = False       # the current frame's sleep state,
                            # for the non-painter compose below
    last_active_ms = boot_ms
    last_housekeep = boot_ms
    last_sleep_ms = boot_ms  # last frame composed while asleep
    last_status_s = -1
    tick_ms = None          # the current face's TICK_MS
                            # opt-in (v29.1), refreshed per
                            # iteration for non-painter faces
    rot_due_ms = None       # ticks_ms of the next rotation
                            # advance (v29.1); None = unarmed
                            # (rotation off, asleep, or just
                            # switched - it arms afresh)
    while True:
        now_ms = time.ticks_ms()
        loc = timekeep.now_tuple()
        total = loc[3] * 60 + loc[4]

        # Compose a frame when: he is awake (the standing rock
        # and breathing animate him between shows - v10), a show
        # or idle routine is in progress, a routine is due or a
        # try-it queued (the scheduler must be serviced on its
        # own timing, not only in post-show settle windows), a
        # minute boundary crossed since the last drawn frame, or
        # the settle window after activity (he is still easing
        # home). During sleep hours the event terms apply, plus
        # the sleep cadence (v15): the sleeping scene breathes
        # and drifts its Z's on a ~1 s frame rhythm.
        if face_name == "painter":
            active = (not show.sleeping_at(total)
                      or show.running or show.idle is not None
                      or show.cuckoo is not None or show.trycuckoo
                      or show.tryit is not None
                      or (show.next_idle_at is not None
                          and time.ticks_diff(now_ms,
                                              show.next_idle_at) >= 0)
                      or total != drawn_total
                      or time.ticks_diff(now_ms, last_active_ms)
                      < SETTLE_MS
                      or (show.sleeping_at(total)
                          and time.ticks_diff(now_ms, last_sleep_ms)
                          >= SLEEP_FRAME_MS))
        else:
            # A non-painter face (v26) has no shows, routines
            # or cuckoo to service - it repaints only when what
            # it displays changes: every second while awake
            # (both new faces carry seconds; TICK_SECONDS is
            # the face's own say-so), and on the minute in the
            # sleep window (the night treatment snaps each
            # minute, nothing animates). A face may instead
            # opt into sub-second repaints with TICK_MS
            # (v29.1: the attitude face, 200 ms) - its day
            # tick is then a ticks bucket, not the wall
            # second; the night rule is unchanged.
            night_now = show.sleeping_at(total)
            tick_ms = getattr(face_mod, "TICK_MS", None)
            if night_now:
                tick = 0
            elif tick_ms:
                tick = now_ms // tick_ms
            elif getattr(face_mod, "TICK_SECONDS", False):
                tick = loc[5]
            else:
                tick = 0
            active = face_key != (total, tick, night_now)
            if active:
                face_key = (total, tick, night_now)
        if active:
            try:
                if face_name == "painter":
                    show.update(canvas, now_ms, loc)
                elif night_now:
                    face_mod.compose(
                        canvas, loc,
                        {"night": True,
                         "dial": display.night_dial()})
                else:
                    # A TICK_MS face also gets the loop's
                    # ticks in its state dict (v29.1): its
                    # phase advances by real milliseconds
                    # between the sub-second frames. Every
                    # other face is called exactly as before
                    # (state None, as a bare two-arg call).
                    face_mod.compose(
                        canvas, loc,
                        {"ms": now_ms} if tick_ms else None)
                display.show()
            except Exception as exc:
                print("main: frame failed:", exc)
            drawn_total = total
            if show.sleeping_at(total):
                last_sleep_ms = now_ms
            if show.running or show.idle is not None \
                    or show.cuckoo is not None:
                last_active_ms = now_ms

        # Status strings for the admin page, refreshed ~1/s.
        if loc[5] != last_status_s:
            last_status_s = loc[5]
            app["time_str"] = "%02d:%02d:%02d" % (loc[3], loc[4],
                                                  loc[5])
            app["time_source"] = timekeep.time_source()
            app["uptime"] = _uptime_str(boot_ms)
            app["wifi"] = _wifi_str(wlan, ssid)
            app["idle_str"] = show.idle_status(now_ms)

        admin.step(app)
        if app.get("tryit") is not None:
            # an admin Try-it press: queue the routine; it runs
            # at the next gap where it fits before the boundary.
            # Routines are the painter's (v26): on another face
            # the press is simply dropped, never queued - a
            # stale queue must not fire if the owner switches
            # back to the painter later.
            if face_name == "painter":
                show.queue_idle(app["tryit"])
            app["tryit"] = None
        if app.get("trycuckoo"):
            # an admin "Try the cuckoo" press: queue the ritual;
            # it runs at the next gap (sleep defers it, exactly
            # like a routine try-it). Painter-only, like the
            # routines above.
            if face_name == "painter":
                show.queue_cuckoo()
            app["trycuckoo"] = False
        if app["changed"]:
            app["changed"] = False
            cfg = admin.load_config()
            app["config"] = cfg
            _apply_sleep(show, cfg)
            _apply_cuckoo(show, cfg)
            display.set_backlight(cfg["brightness"])
            if cfg.get("show_date", True) != date_now:
                # date toggled: the painter draws it per frame,
                # so this is just the flag - the next composed
                # frame shows it or drops it, no re-render, no
                # reboot, no ghost (frames are rebuilt whole)
                date_now = cfg.get("show_date", True)
                _apply_date(face_mod, cfg)
                drawn_total = None  # force a repaint
                face_key = None     # (a non-painter face too)
                print("main: show_date changed to %s" % date_now)
            if cfg.get("face", "painter") != face_name:
                face_name = cfg.get("face", "painter")
                face_mod, frost_now, backlight_now = \
                    _switch_face(face_name, cfg)
                drawn_total = None  # force a repaint
                face_key = None
                rot_due_ms = None   # a manual pick restarts
                                    # the rotation interval
                                    # (v29.1): the rotator
                                    # below re-arms it fresh
            elif face_name == "painter" and \
                    (cfg.get("frost", 55) != frost_now
                     or cfg.get("backlight", 50) != backlight_now):
                # frost and/or backlight: the rects are re-baked
                # with the new strengths (prepare is keyed on
                # both). A backlight change ALSO re-renders the
                # dial - the glow is baked into the static layer
                # - while a frost-only change leaves the dial
                # and the panel untouched, as before.
                frost_now = cfg.get("frost", 55)
                if cfg.get("backlight", 50) != backlight_now:
                    backlight_now = cfg.get("backlight", 50)
                    _apply_backlight(face_mod, cfg)
                    face_mod.render_static(display.dial())
                    print("main: backlight changed to %s"
                          % backlight_now)
                figmod.prepare(display.dial(), frost_now,
                               backlight_now)
                drawn_total = None  # force a repaint
                print("main: frost changed to %s" % frost_now)
            if cfg.get("metar_airport", "KFLG") != airport_now:
                # the METAR face's station changed (v28): the
                # fetcher drops the old station's record and
                # refetches promptly, not at the next cadence;
                # the face re-renders on the new snapshot by
                # itself (its static layer is data-keyed).
                airport_now = cfg.get("metar_airport", "KFLG")
                metarmod.set_airport(airport_now)
                if wlan is not None and wlan.isconnected():
                    metarmod.poll(force=True)
                face_key = None     # force a repaint
                print("main: metar airport changed to %s"
                      % airport_now)

        # Face rotation (v29.1): while rotation is on and
        # the clock is AWAKE, advance to the next face in
        # the owner's set every rotate_minutes. The sleep
        # window owns the display overnight - rotation
        # simply does not advance there, and the deadline
        # is dropped every sleeping iteration, so the
        # interval re-arms fresh at wake. The schedule is
        # a ticks deadline set at each switch - monotonic,
        # midnight-safe, no wall-clock modulo. A switch
        # goes through _switch_face, the very path an
        # admin pick takes; a manual pick (the handler
        # above) drops the deadline, so the interval
        # restarts from the pick. A rotate_minutes edit
        # applies from the next interval: the pending
        # deadline stands. Rotation off costs this block
        # one dict lookup a slice - nothing else changes.
        rot_cfg = app["config"]
        if rot_cfg.get("rotate_enabled", False) \
                and not show.sleeping_at(total):
            members = [f for f in rot_cfg.get(
                "rotate_faces", list(FACES)) if f in FACES]
            if len(members) >= 2:
                if rot_due_ms is None:
                    rot_due_ms = now_ms + _rotate_ms(rot_cfg)
                elif time.ticks_diff(now_ms, rot_due_ms) >= 0:
                    if face_name in members:
                        nxt = members[
                            (members.index(face_name) + 1)
                            % len(members)]
                    else:
                        # the current face is not in the
                        # set: the first advance joins it
                        nxt = members[0]
                    if nxt != face_name:
                        print("main: rotation -> %s" % nxt)
                        face_mod, frost_now, backlight_now = \
                            _switch_face(nxt, rot_cfg)
                        face_name = nxt
                        drawn_total = None  # force a repaint
                        face_key = None
                    rot_due_ms = now_ms + _rotate_ms(rot_cfg)
            else:
                # an empty or single-face set has nowhere
                # to go: no switching, no spinning
                rot_due_ms = None
        else:
            rot_due_ms = None

        # Housekeeping, only while he is idle - never mid-show.
        if not show.running and \
                time.ticks_diff(now_ms, last_housekeep) > HOUSEKEEP_MS:
            last_housekeep = now_ms
            if wlan is not None and wlan.isconnected():
                updater.maybe_check()
                if face_name == "metar":
                    metarmod.poll()
                timekeep.maybe_resync()
            gc.collect()

        time.sleep_ms(LOOP_MS)


main()
