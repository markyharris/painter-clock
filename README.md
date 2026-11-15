# Painter Clock

A desktop clock after Maarten Baas's Schiphol Clock: a little man in
blue overalls behind a frosted round dial who, every minute, wipes
the old minute hand away and paints the new one — dip, bend, dabs
and all. On the hour he leans in and wipes a clear circle in the
frost, and for a moment his face is in focus.

MicroPython port of the web prototype (Space
`wipe-and-paint-prototype`). Design, choreography, rig math and the
display-driver research live in **SPEC.md** — read that first.

## Hardware

Waveshare ESP32-S3 round display board — the ESP32-S3-Touch-LCD-2.1
(2.1") or ESP32-S3-Touch-LCD-2.8C (2.8"); same platform either way:
ESP32-S3R8, 16 MB flash, 8 MB PSRAM, 480×480 round IPS, ST7701 RGB
panel, PCF85063 RTC, USB-C.

## Status — groundwork (Nov 13, 2026)

- SPEC.md: complete design + port plan, incl. driver research.
- Code skeleton compiles under MicroPython v1.29 (mpy-cross):
  state machine, rig math, timekeeping, provisioning, updater and
  admin structure are in place.
- **The display layer is implemented and bench-proven** (Nov 15):
  custom firmware v2 lights the panel, and `display.py` composes
  frames in plain bytearray canvases and ships them via
  `draw_bitmap` in **bands of 120 lines** — the bench-proven route
  (large single transfers wedge the chip; see SPEC.md Nov 15
  addendum and firmware/API_NOTES.md). First frame:
  `bench_first_frame.py` (dial + hands at a fixed 10:09 demo time).
- Board arrived **Saturday Nov 14, 2026** (a day early); factory demo verified the same day — panel, backlight, touch, IMU, RTC and 16 MB flash all good (see SPEC.md, Nov 14 entry).

## Sunday bring-up checklist

Work through it in order, one step at a time (Thonny 5 on the
Chromebook; for ESP32-S3 firmware the family must be ESP32-S3 so it
lands at address 0x0):

1. **Identify the board** that arrived (2.1 vs 2.8C) and note it in
   SPEC.md §8 — it decides which pin-map branch to verify.
2. **Run Waveshare's own demo first** (Arduino or ESP-IDF, their
   wiki) — proves the panel, backlight and expander before any of
   our code is in question.
3. **Pick the firmware route** (SPEC.md §2): primary is a custom
   MicroPython build with Espressif's ESP32_Display_Panel
   (mpy_support). Flash it; confirm Thonny connects and the REPL
   answers. — **DONE Nov 14–15:** `firmware/painter-firmware_v2.bin`
   (v1 had no board config compiled in; use v2), REPL live.
4. **Probe the driver's Python API** at the REPL: what object does
   it expose? Can our `framebuf` be its scanout buffer? Record the
   answers in SPEC.md §2, then implement `display._driver_init()`.
   — **DONE Nov 15:** the binding exposes `Board` with our added
   `draw_bitmap`; our framebuf can NOT be the scanout buffer (a
   full-size FrameBuffer wedges the chip). Display route is
   bench-proven: compose in bytearray canvases, present via
   `draw_bitmap` in **bands of 120 lines** (SPEC.md Nov 15
   addendum; firmware/API_NOTES.md has the full bench log).
5. **First frame:** run `bench_first_frame.py` in Thonny — it
   renders the dial and puts both hands on the glass at a fixed
   10:09 demo time. Check colours (RGB565 byte order), orientation,
   and that the picture is steady with Wi-Fi on.
6. **Frame rate:** time the full compose loop during a minute show.
   If a full-frame copy is involved, measure it; pick optimisations
   from SPEC.md §4.4 as needed.
7. **Time:** with Wi-Fi joined, confirm NTP sets the clock and the
   PCF85063 reads back the same time after a power cycle with Wi-Fi
   off (RTC fallback).
8. **Rehome round-trip:** forget the network via the BOOT-hold
   gesture (hold just AFTER power-up, never during plug-in), join
   `PainterClock-Setup`, save the real network, confirm it rejoins.
9. **Updater:** once Mark has created the GitHub repo and
   `GITHUB_REPO` in `updater.py` matches it, run a check from the
   admin page and confirm it reports clean; then change one file in
   the repo and confirm the flag appears (install stays manual).
10. **First full minute on the glass**, then the hour ritual when
    the prototype version of it has settled.

## Operating it (once built)

- **Admin page:** http://\<clock-ip\>/ — status, settings, Update
  now, rehome instructions, restart.
- **Rehome:** unplug, plug in, hold BOOT just after start →
  `PainterClock-Setup` captive portal.
- **Updates:** the clock checks the repo after boot and hourly and
  only *flags* an update in the admin page; installing is always a
  deliberate Update now press. `wifi_cfg.py` and `config.json` are
  never overwritten.
