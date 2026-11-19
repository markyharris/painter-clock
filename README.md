# Painter Clock

A desktop clock after Maarten Baas's Schiphol Clock: a little man in
blue overalls stands behind a frosted round dial and paints the time,
minute by minute — wiping the old minute hand away, dipping his
brush, and painting the new one. On the hour he leans in and wipes a
clear circle in the frost, and for a moment his face is in focus.

The clock runs on a Waveshare ESP32-S3 round touch board and is
written in MicroPython on a custom firmware build (see below). It
keeps time from an onboard RTC, corrected by NTP over Wi-Fi, and it
looks after itself: a web admin page for settings, a captive-portal
setup for moving it to a new Wi-Fi network, and self-updates it
downloads from this repository — verified, and only ever installed
when you press the button.

> *An homage to Maarten Baas and his Schiphol Clock (Amsterdam
> Airport Schiphol, 2016), from the Real Time series — the man
> behind the glass who paints the time, minute by minute. This
> clock is a tribute, built with admiration.*

## The faces

Five faces, switchable from the admin page (or rotated automatically
on a timer):

- **Painter** — the homage face described above. Between minutes he
  lives a small life: he checks his watch, sips from a mug, scratches
  his head, blows his nose, takes a phone call, watches a plane go
  by, moves his paint bucket (and then dips in the new spot). At
  night he lies down and sleeps under a blanket while the hands keep
  time in pale ink.
- **Classic analog** — a clean, plain analog dial.
- **Digital** — a large digital readout with an anti-aliased font.
- **METAR analog** — an analog dial whose colour ring wears an
  airport's current flight category (VFR / MVFR / IFR / LIFR), with
  decoded wind, visibility and cloud lines and the observation time
  in Zulu. The station is configurable (KFLG by default); data comes
  from aviationweather.gov about every five minutes and is marked
  STALE when it ages.
- **Attitude maneuvers** — a steam-gauge attitude indicator that
  endlessly flies three Cessna 182 training maneuvers — Lazy Eight,
  Chandelle, Eights on Pylons — with the maneuver's name curved
  along the bezel. The motion is smoothed and runs at five frames a
  second; there is deliberately no second hand on this face.

Every face shows the day and date (it can be turned off), and every
face has a dark night treatment during sleep hours.

## Living with it

- **Admin page** — status, face and display settings, sleep hours,
  frost and backlight, the cuckoo and idle-life switches, update and
  restart, all in the clock's own web page. After a boot the clock
  shows its admin address (its IP) on screen for about 35 seconds.
- **Rehoming** — if the saved network can't be joined at boot, the
  clock automatically starts its own `PainterClock-Setup` network;
  holding BOOT just after power-up forces the same setup mode
  immediately. Join it with a phone, enter the new Wi-Fi, done. No
  keyboard, monitor or reflash.
- **Updates** — the clock checks this repository after boot and
  hourly, and flags "update available" in the admin page. Installing
  is always a deliberate **Update now** press; each file is verified
  against its git blob SHA before it is swapped in. Your settings
  and Wi-Fi credentials are never touched by an update.
- **Sleep** — during the hours you set, the room goes dark, the
  painter lies down, and the hands snap to pale ink once a minute.

## Hardware in brief

One board does nearly everything: the **Waveshare
ESP32-S3-Touch-LCD-2.8C** (Waveshare SKU 30254) — ESP32-S3R8, 16 MB
flash, 8 MB PSRAM, 2.8″ round 480×480 IPS panel (ST7701), capacitive
touch, PCF85063 RTC, USB-C. Mind the name: Waveshare also sells a
rectangular 240×320 board called the ESP32-S3-Touch-LCD-2.8 (no
"C") — a different product that will not run this clock. You also
need a data-capable USB-C cable and a computer running Thonny 4.1 or
newer for the one-time firmware burn. The full list, with links, is
in [HOWTO.md](HOWTO.md).

## Why a custom firmware?

Stock MicroPython has no driver for this board's ST7701 RGB panel —
the panel is initialised over a 3-wire SPI link through the board's
I/O expander, and presented frames over a parallel RGB bus. The
firmware in this project is MicroPython v1.29.0 with Espressif's
ESP32_Display_Panel library and the 2.8C board definition compiled
in, plus a small `draw_bitmap` binding the clock uses to push
pixels. Burning it is a one-time, five-minute job — [HOWTO.md](HOWTO.md)
walks through it, and through everything else: loading the software,
the faces, the admin page, rehoming, updates and troubleshooting.

## Repository layout

The clock's software is the set of Python files at the repository
root (the same list as `update_files.txt`, which is the updater's
manifest): `main.py` runs the loop; `display.py` drives the panel;
`clockface.py`, `classicface.py`, `digitalface.py`, `metarface.py`
and `attface.py` are the faces; `figure.py` and `show.py` are the
painter and his choreography; `admin.py` is the admin page;
`prov.py` is the setup portal; `updater.py` is the self-updater;
`timekeep.py` keeps time; `smoothfont.py` / `fontdata.py` are the
anti-aliased font; `attdata.py` / `attlabels.py` are the attitude
face's flight data and bezel labels. `SPEC.md` is the full design
record — every decision and bench finding, kept as it was made.
`FACES.md` is a shortlist of face ideas for the future.

## Getting started

Read [HOWTO.md](HOWTO.md) — it takes you from a bare board to a
running clock, in order.
