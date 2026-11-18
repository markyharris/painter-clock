# Painter Clock — HOWTO

Build one, run it, and live with it: the hardware, the one-time
firmware burn, loading the software, every face, the admin page,
rehoming, updates, and what to do when something looks wrong.
For the short version, see [README.md](README.md).

## 1. What you need

### Hardware

| Item | Notes |
|---|---|
| **Waveshare ESP32-S3-Touch-LCD-2.8C** (SKU 30254) | The whole computer and screen in one round board: ESP32-S3R8 (dual-core 240 MHz), 16 MB flash, 8 MB PSRAM, 2.8″ round 480×480 IPS panel (ST7701), GT911 capacitive touch, PCF85063 RTC, QMI8658 IMU, two USB-C ports, a 12-pin GPIO/power header and an MX1.25 battery connector. [Waveshare's documentation for the board](https://docs.waveshare.com/ESP32-S3-LCD-2.8C) |
| **USB-C cable — data-capable** | For flashing and power. A charge-only cable will light the board's power LED but the computer will never see it; if no serial port appears, suspect the cable first. |
| **5 V USB power source** | Any phone-charger-class supply, or 5 V fed to the board's 12-pin header (pin 2 = VBus 5 V in, pin 1 = GND). |
| **A computer** | Windows, macOS or Linux, for the one-time firmware burn and file upload. |

**Mind the board name.** Waveshare sells two different "2.8 inch"
boards: this clock needs the **round** one, the ESP32-S3-Touch-LCD-**2.8C**
(480×480, ST7701). The rectangular ESP32-S3-Touch-LCD-2.8 (240×320,
no "C") is a different product and will not run this firmware.

Optional, for a finished build:

- **A case or stand.** The board's rear mounting studs are **M2**.
  A printed stand designed for this board:
  [Stand for round Waveshare 2.8″ display with ESP32-S3 (Printables 1841805)](https://www.printables.com/model/1841805-pouzdro-pro-kulaty-waveshare-28-displej-s-esp32-s3).
  For a case build, a panel-mount USB-C extension lead brought to
  the case wall keeps the board's own ports reachable — land its
  inner end on the board's **UART** port and leave a little slack.
- **An external reset button** (optional): a normally-open momentary
  pushbutton between the board's **EN** pin and **GND** works exactly
  like the onboard RST button.
- **A 3.7 V LiPo** with an MX1.25 plug fits the board's battery
  header (the board has charge management). Note the clock's
  software has no battery-saving mode yet — on battery it simply
  runs normally until the battery is flat.

### Software tools

- **Thonny 4.1 or newer** — [thonny.org](https://thonny.org/).
  This is a hard floor, not a suggestion: Thonny 3.x has no
  chip-family selector and writes ESP32-S3 firmware at the
  classic-ESP32 address (0x1000) instead of 0x0. The burn reports
  success and the board then boot-loops forever. In 4.1+ the
  flasher's family field drives the correct address.
- *Alternative to Thonny for the burn only:* `esptool`
  (Espressif's command-line flasher).

## 2. The custom firmware — why, and which file

Stock MicroPython cannot run this clock. It has no driver for the
board's ST7701 RGB panel: the panel is initialised through a 3-wire
SPI link via the board's TCA9554 I/O expander and then fed over a
parallel RGB bus, and neither the initialisation nor a way to push
pixels exists in a stock build.

The project's firmware is a custom build:

- MicroPython **v1.29.0** (the GENERIC_S3-SPIRAM_OCT feature set:
  octal PSRAM, 240 MHz) on ESP-IDF v5.5.2,
- plus Espressif's **ESP32_Display_Panel** library (v1.0.5) with its
  MicroPython binding and the Waveshare 2.8C board definition
  compiled in,
- plus one small addition of ours, a `draw_bitmap` binding — the
  upstream binding could initialise the board but exposed no way to
  present a frame, and presenting frames is the clock's whole job.

**Use `painter-firmware_v2.bin`, from this repository's
[Releases](https://github.com/markyharris/painter-clock/releases).**
(There is also a v1 image around — do not use it. It was built
without the board configuration compiled in, so on v1 the panel
never lights even though the REPL answers.)

The image is a single merged binary (bootloader, partition table
and application) and is written at address **0x0**. Burning it
erases whatever is on the board, including Waveshare's factory
demo.

## 3. Burning the firmware

Connect the board to the computer with the USB-C cable, using the
board's **UART** USB-C port (the one served by its CH343P
USB-serial bridge — flashing and Thonny both happen there; the
other port is the ESP32-S3's native USB). If no serial port shows
up at all: try the other port, then a different cable (see §1),
then check whether your system needs the CH343 driver — Waveshare's
documentation (§1) links it.

### With Thonny (the route this project uses)

1. Open **Tools → Options → Interpreter** and choose the
   MicroPython (ESP32) interpreter and the board's serial port.
2. Open the install/update MicroPython dialog (the button at the
   bottom of that options page).
3. Set the **family to ESP32-S3**. This is the step that decides
   the write address — ESP32-S3 images go at 0x0.
4. In the same dialog, open the **☰ menu → "Select local
   MicroPython image"** and pick `painter-firmware_v2.bin`.
5. Install, and wait for the burn to finish and verify.
6. Back in Thonny's shell, press Stop/Restart and confirm the
   MicroPython v1.29.0 REPL banner answers.

### With esptool

With only the one board attached, esptool finds the port itself:

```
esptool --chip esp32s3 write_flash 0x0 painter-firmware_v2.bin
```

## 4. Loading the clock software

1. Download this repository (the green **Code → Download ZIP**
   button on
   [github.com/markyharris/painter-clock](https://github.com/markyharris/painter-clock),
   or `git clone` it).
2. In Thonny, open **View → Files**. The top pane is your computer,
   the bottom pane is the board.
3. Upload the twenty files listed in **`update_files.txt`** (in the
   repository root) to the board's root directory. That list is the
   clock's whole runtime — faces, painter, admin, updater and all.
4. Do **not** create `wifi_cfg.py` or `config.json` by hand. The
   clock creates both itself: the first from the setup portal
   (next step), the second the first time you save settings.
5. Restart the board (unplug/replug, the RST button, or
   Stop/Restart in Thonny).

### First boot

With no Wi-Fi configured, the clock paints its setup screen and
starts its own network, **`PainterClock-Setup`**:

1. Join `PainterClock-Setup` with a phone. The captive portal opens
   by itself (if it doesn't, browse to the address the portal page
   names).
2. Pick your Wi-Fi network, type the password (there is a
   *Show password* peek box), and save.
3. The clock restarts, joins your network, and shows the
   **Connected screen**: your network's name and the clock's
   **IP address**, held on screen for about 35 seconds.

Write that IP address down — it is the clock's admin address
(`http://` + the IP, port 80). If you miss the screen, the address
is also in your router's client list, and it is shown again on
every subsequent boot for the same 35 seconds.

## 5. The faces

Pick a face in the admin page (Display section); the change is
live, no restart. Every face shows the day and date at the top
unless **Show date** is off, and every face switches to a dark
night treatment during sleep hours (§7).

### Painter

The homage face — §6 is devoted to it.

### Classic analog

A plain, clean analog dial with hour, minute and second hands.
Nothing to configure beyond Show date.

### Digital

A large digital readout (hours and minutes, with seconds and the
date as a sub-line), set in the anti-aliased font the project uses
for all its text. Non-painter faces draw text with this font too —
it is noticeably softer than a bitmap font at this size.

### METAR analog

An analog clock whose dial ring is coloured by an airport's
current flight category, in the colours a LiveSectional map uses:

- **VFR** green, **MVFR** blue, **IFR** red, **LIFR** magenta,
  **NO DATA** grey.

Under the dial, decoded lines give the wind (with gusts when
reported, e.g. "Wind 240° at 10 G18 kt"), the visibility (shown
verbatim — `1/2` and `M1/4` stay as reported), the ceiling or sky
condition, and the observation time in Zulu. Data comes from
aviationweather.gov about every five minutes. If no fresh report
arrives for about 75 minutes the face marks itself **STALE** rather
than letting old weather pose as current. Set the station in the
admin page's **METAR airport** field (default **KFLG**); an entry
that doesn't parse as a station identifier is rejected and the
saved value kept.

### Attitude maneuvers

A steam-gauge attitude indicator — black bezel, screws, sky over
ground, pitch ladder, fixed miniature aircraft — that flies three
Cessna 182 commercial-training maneuvers endlessly, in order, on a
roughly five-minute cycle:

1. **Lazy Eight** — two opposite 180° turns through climbing and
   descending banks.
2. **Chandelle** — a maximum-performance climbing 180° turn, left
   then right, rolling out just above the stall.
3. **Eights on Pylons** — turns about ground points at the pivotal
   altitude, the horizon rising and falling as groundspeed changes.

The maneuver's name fades in curved along the bottom bezel at the
start of each segment and out before the next. The motion runs at
five frames a second with a smoothing pass over the flight data.
There is **no second hand on this face, deliberately**: a
once-a-second hand made the frame cadence's unevenness visible, and
the gauge reads better without it. The hour and minute hands are
there, stepping by the minute over the ball.

### Face rotation

The admin page's **Face rotation** section can cycle the face
automatically: enable it, choose the interval in minutes (1–240,
15 by default) and tick which faces take part. Rotation only runs
while the clock is awake — lights-out hours keep the sleeping
face — and picking a face by hand restarts the interval.

## 6. The painter, in detail

- **The minute show.** As each minute arrives he wipes the old
  minute hand away with his sponge, dips his brush in the paint
  bucket, and paints the new hand — the hour hand gets the same
  treatment when it moves. If he has moved the bucket (see below),
  he dips where the bucket actually is.
- **Frost.** The dial is frosted glass; the **Frost** slider
  (0–100, default 55) sets how heavy the frosting is. The hands he
  paints are always sharp; the frost softens everything behind the
  glass. At 0 the glass is clear.
- **Backlight.** The **Backlight** slider (0–100, default 50) is
  the light painted behind him — the dial's glow. **Brightness**
  (in Display, 0–255) is the panel's own brightness; the two are
  independent.
- **The cuckoo.** On the hour, once both hands are repainted, he
  leans in and wipes a clear circle in the frost and his face is
  sharp for a few seconds — stepping aside first if a hand would
  cross his face. It never happens during sleep hours (it is
  skipped, not postponed). Turn it off, or rehearse it any time
  with **Try the cuckoo**, in the admin page.
- **Idle life.** At a gap, roughly once a minute, he does one of
  his small routines: wristwatch check, cap-off brow wipe, mug sip,
  head scratch, rear scratch, apple snack, hanky nose-blow, phone
  call, plane flyby, a shoulder roll — and two with props: he
  **moves the paint bucket** to the other side (and dips there, and
  sips with the other hand, until he moves it back), and folds his
  arms for a **foot-tapping** wait. Every routine has a **Try-it**
  button in the admin page; a press queues it for the next gap.
  The Status section's **Idle** line shows the last routine and
  when the next is due.
- **Sleep.** In the hours you set (default 22:00–06:00) the room
  goes dark: he lies down — pillow, blanket, cap off on the floor —
  and breathes slowly while Z's drift up. The hands keep time,
  snapping to pale ink once a minute; there are no shows, no
  routines and no cuckoo until morning.

## 7. The admin page

Open the clock's IP address in any browser (port 80). The page is
one form: change anything, then press **Save settings** — it lives
at the bottom of the Status section, and it saves the whole page's
settings at once. Every action on the page returns you to the page
itself; the two rebooting actions (Update now, Restart) return via
a small auto-refreshing page once the clock is back.

- **Status** — the time and its source (`ntp` when network-synced,
  `rtc` when running on the onboard clock), Wi-Fi network and IP,
  display state, uptime, the Idle line, and the update line
  (§9). **Save settings** sits here.
- **Display** — the face picker, the METAR airport field,
  **Brightness** (0–255 slider) and the **Show date** toggle.
- **Face rotation** — §5.
- **Painter Clock** — the **Frost** and **Backlight** sliders, the
  cuckoo switch, and the idle-life Try-it buttons (§6).
- **Sleep** — the lights-out switch and the from/to times
  (HH:MM, 24-hour).
- **Update** — the update status and **Update now** (§9).
- **System** — **Restart**, and the rehoming instructions (§8).

Two things that are normal, not faults: saving Frost or Backlight
pauses the clock for a few seconds while it re-renders the dial;
and a Try-it press discards any unsaved slider changes on the page
(the routine is queued from the button alone — save first if you
had changes).

Settings are stored on the board in `config.json` and survive
updates and power cuts.

## 8. Rehoming — new Wi-Fi or new owner

The clock never needs a keyboard, monitor or reflash to move:

1. Unplug the clock.
2. Plug it back in and, **just after** it starts, hold the **BOOT**
   button for about a second.
   Timing matters: hold it *after* power-up begins. Holding BOOT
   while you plug in puts the chip in firmware-download mode
   instead — nothing is harmed, just unplug and try again.
3. The clock starts the **`PainterClock-Setup`** network with the
   painted setup screen. Join it with a phone and use the captive
   portal to enter the new network, exactly as at first boot (§4).
4. The clock restarts onto the new network and shows its new IP
   address on the Connected screen for about 35 seconds.

## 9. Updates

The clock updates its own software from this repository:

- **Checking** is automatic and flag-only: after boot and then
  hourly, the clock reads `update_files.txt` fresh from the
  repository, and compares each listed file's git blob SHA with
  GitHub's. If anything differs, the admin page's Status and
  Update sections say **UPDATE AVAILABLE**. Nothing is downloaded
  or changed by a check.
- **Installing** is always your press: **Update now** downloads
  each changed file, verifies its blob SHA, swaps it in (the old
  copy is kept alongside as a `.bak`), and reboots.
- **Never touched by an update:** `wifi_cfg.py` (your Wi-Fi
  credentials) and `config.json` (your settings). They are not in
  the manifest and the updater has no path to them.
- **If an update is interrupted** (power cut mid-apply), just
  press Update now again once the clock is back — files already
  swapped verify as current and are skipped. If the clock will not
  boot at all after an interrupted update, re-upload the files via
  Thonny from a fresh repository download (§4) — the firmware
  itself is never touched by an update.
- One historical wrinkle: on builds older than v30.1 an hourly
  check could fail with `memory allocation failed` after long
  uptimes. The cure was, and is, **Restart** from the admin page,
  then **Update now** promptly on the fresh boot. Current builds
  collect garbage before fetching and hash local files in chunks,
  and the check no longer trips over this.

## 10. Timekeeping

The board's PCF85063 RTC keeps time while the clock is powered;
there is no battery backup, so after a power cut the clock
re-syncs. When Wi-Fi is up, NTP is the authority and the RTC is
re-set from it (and re-checked every six hours); the admin Status
line shows which source the displayed time came from. The clock
runs on a fixed UTC−7 offset (Mountain Standard Time, no daylight
saving) — set in `timekeep.py`, it is a build-time choice, not a
setting.

## 11. Troubleshooting

| Symptom | Likely cause and cure |
|---|---|
| Board boot-loops after flashing; serial log shows `invalid header: 0xffffffff` | The firmware was written at the classic-ESP32 address. Reflash with Thonny 4.1+ and the family set to **ESP32-S3** (§3). Thonny 3.x cannot do this at all. |
| No serial port when the board is plugged in | Charge-only USB-C cable (power LED lit, no data), the native-USB port instead of the UART port, or a missing CH343 driver. §1, §3. |
| REPL answers but the panel never lights | The v1 firmware image (no board configuration compiled in). Burn `painter-firmware_v2.bin`. |
| Panel picture frozen or scrambled after a crash, and a restart doesn't clear it | A chip reset does not reset the panel. Unplug the clock completely for a full **10 seconds**, then plug back in. (Admin **Restart** is safe for ordinary use — the warm-reboot path was fixed in v17 — the 10-second unplug is for a genuinely wedged panel.) |
| Setup screen at every boot | The saved Wi-Fi credentials don't work (network changed, password changed). Rehome it (§8). |
| `Update check failed: memory allocation failed…` | §9 — Restart, then Update now on the fresh boot. |
| METAR face shows STALE | No fresh report for ~75 minutes: check the clock's Wi-Fi, then aviationweather.gov. The face recovers by itself when data flows. |
| Time wrong after a power cut | No RTC battery (§10) — it corrects itself from NTP as soon as Wi-Fi joins. Check the Status line's source. |
| Filesystem looks corrupted on a brand-new board (`OSError: 84` in Thonny) | Occasionally a board ships with an unformatted filesystem. Format it once at the REPL: `from flashbdev import bdev`, then `os.VfsLfs2.mkfs(bdev)`, then reset — and re-upload the files (§4). If files subsequently vanish after uploads, the board itself is faulty; exchange it. |

## 12. Building the firmware yourself

You only need this if you want to change the firmware itself;
normal builds use the released image (§2). The ingredients:

- MicroPython **v1.29.0** source, built for the
  **GENERIC_S3-SPIRAM_OCT** board variant, on ESP-IDF **v5.5.2**.
- Espressif's **ESP32_Display_Panel v1.0.5** with its MicroPython
  support (`mpy_support`), and the board define
  `BOARD_WAVESHARE_ESP32_S3_TOUCH_LCD_2_8_C` selected.
- The project's `draw_bitmap` addition to the binding (in the
  project's firmware tree): it wraps the panel driver's bitmap
  window call so Python can present a composed frame.

Two build gotchas, both learned the hard way:

1. The library's supported-board configuration header must
   actually be **included by a translation unit**, and
   `ESP_PANEL_BOARD_DEFAULT_USE_SUPPORTED` must be flipped to
   `(1)` **in that header** — passing it as a `-D` compile
   definition does not substitute, because the header's own
   unconditional `#define` wins. Get this wrong and the build
   succeeds, the REPL works, and `Board().init()` returns False
   forever (that was v1).
2. Merge the bootloader, partition table and application into a
   single image and flash at **0x0**; the partition layout is
   nvs at 0x9000, phy_init at 0xf000, a 4 MB factory app at
   0x10000 and the FAT filesystem in the remaining ~12 MB.

`SPEC.md` in this repository is the project's full design and
bench record, including the firmware bring-up.
