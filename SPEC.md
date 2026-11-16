# Painter Clock — SPEC

A desktop clock after Maarten Baas's Schiphol Clock: a little man in blue
overalls stands behind a frosted round dial and, every minute, wipes the
old minute hand away and paints the new one. MicroPython port of the web
prototype (Space `wipe-and-paint-prototype`) to a Waveshare round
ESP32-S3 display board.

Status: **groundwork** (Fri Nov 13, 2026). Hardware ordered, arrives
Sun Nov 15. The animation engine is NOT written yet — this spec, a
compiling skeleton, and the driver research below are the running start
for Sunday.

---

## 1. Hardware

Both candidate boards are the same platform; either runs this design
unchanged. Mark ordered one of them (the 2.8C was last discussed).

| | ESP32-S3-Touch-LCD-2.1 | ESP32-S3-Touch-LCD-2.8C |
|---|---|---|
| MCU | ESP32-S3R8, 240 MHz | ESP32-S3R8, 240 MHz |
| Flash / PSRAM | 16 MB / 8 MB OPI | 16 MB / 8 MB OPI |
| Panel | 2.1" round IPS, 480×480 | 2.8" round IPS, 480×480 |
| LCD controller | ST7701, 16-bit RGB (DPI) + 3-wire SPI init | ST7701, same arrangement |
| Touch | CST820 (I2C) | GT911 (community template) — confirm Sunday |
| RTC | PCF85063 (I2C) | PCF85063 (expected) — confirm Sunday |
| IO expander | TCA9554 @ I2C 0x20 | TCA9554 @ I2C 0x20 |
| Also onboard | QMI8658 IMU, TF slot, buzzer, battery charger | same class |
| USB | USB-C (native USB + CH343P UART bridge on the 2.1) | USB-C |

Panel facts that shape the whole port (Waveshare 2.1 wiki):

- The panel is a **parallel RGB (DPI) panel**, not SPI. Pixel data is
  streamed continuously by the ESP32-S3's RGB LCD peripheral from a
  framebuffer in PSRAM. There is no "send this frame" command in the
  SPI-panel sense; whoever owns the framebuffer owns the picture.
- The ST7701 still needs a vendor init sequence, sent over a 3-wire SPI
  side channel before the RGB stream starts. On the 2.1 that side
  channel is GPIO1 (SDA) / GPIO2 (SCL), with CS on the IO expander
  (EXIO3) and panel reset on EXIO1. Backlight is GPIO6.
- RGB pin map (2.1, from the wiki): PCLK 41, DE 40, VSYNC 39, HSYNC 38;
  R1–R5 = 46, 3, 8, 18, 17; G0–G5 = 14, 13, 12, 11, 10, 9;
  B1–B5 = 5, 45, 48, 47, 21 (RGB565; R0/B0 not connected).
- Shared I2C bus for touch / RTC / IMU / expander: SDA GPIO15,
  SCL GPIO7 (2.1 wiki; the 2.8C community template uses the same pair).
- Community C projects run the panel at ~18 MHz pixel clock with
  ESP-IDF "bounce buffers" (a small internal-RAM strip buffer) to keep
  the picture steady while Wi-Fi is busy.

The clock needs no touch, no IMU, no buzzer. Touch is noted only
because the two boards differ (CST820 vs GT911) if we ever want a
tap-to-wake; nothing in v1 depends on it.

---

## 2. Display driver research (Nov 13, 2026) — the honest picture

**Headline: stock MicroPython cannot light this panel.** Every route
below ends at a *custom firmware build*; none is a `.py` file we can
drop onto the v1.29 GENERIC_S3-SPIRAM_OCT image Mark flashes with
Thonny today. Sunday's first job is picking and proving one route.
All of the Python code in this repo is written against the
`display.py` contract (section 6) precisely so the choice can be made
on the bench without touching the animation code.

1. **Stock MicroPython v1.29 GENERIC_S3-SPIRAM_OCT — no.**
   Mainline MicroPython has no RGB/DPI LCD driver and no ST7701
   module; `framebuf` exists but nothing in the stock build feeds a
   parallel panel. Waveshare's own wiki for the 2.1 lists exactly two
   supported frameworks — **Arduino IDE and ESP-IDF** — and offers no
   MicroPython firmware or examples for the board.

2. **Espressif ESP32_Display_Panel — the official route (primary plan).**
   Espressif's display library explicitly supports MicroPython through
   an `mpy_support/` directory and a `micropython.cmake`: it is a C
   component compiled *into* a custom MicroPython firmware. Its
   supported-board list names **both** the ESP32-S3-Touch-LCD-2.1 and
   the ESP32-S3-Touch-LCD-2.8C, and its controller list includes the
   ST7701 and CST820. No prebuilt firmware download was found — plan
   on building firmware once (ESP-IDF toolchain, Docker image is the
   tidy way), then treating that `.bin` as this project's standard
   image, exactly like the stock `.bin` is for the other Micro builds.
   What its MicroPython binding exposes (class names, whether we get a
   raw framebuffer or an LVGL surface) was not documented in what we
   could read from here — **Sunday question #1**.

3. **lvgl_micropython (the LVGL-org MicroPython) — possible, riskier.**
   A custom firmware whose `lcd_bus.RGBBus` drives RGB panels from
   Python. Its supported-chip list marks **ST7701S "WIP"**, and a
   recent (Oct 2026) issue against a sibling Waveshare RGB board shows
   the failure mode to expect: without bounce buffers the driver
   copies the full ~1.2 MB frame through PSRAM every frame and the
   picture can shake/tear while Wi-Fi runs; a community patch adds
   `bounce_buffer_lines=10` to `lcd_bus.RGBBus`. Viable fallback, but
   expect to carry a patched firmware.

4. **lbuque/lcd_binding_micropython — possible, more porting.**
   A thin C binding over `esp_lcd` supporting ST7701 and DPI/RGB,
   modelled on `st7789_mpy`'s API. Documented boards are LILYGO
   (T-DisplayS3, T-RGB); the Waveshare pin maps and expander handling
   would be ours to port. Also a custom firmware build.

5. **CircuitPython — works today, wrong ecosystem (noted, not planned).**
   CircuitPython has official board support for the 2.1 with
   `board.DISPLAY` ready at boot. Everything else in Mark's Micro
   fleet — updater, provisioning, Thonny workflow — is MicroPython,
   so this stays a fallback data point only.

Sources: Waveshare ESP32-S3-Touch-LCD-2.1 wiki (frameworks, pin maps);
Espressif ESP32_Display_Panel repo + ESP Component Registry listing
(MicroPython support, board/controller lists); lvgl_micropython repo
and its issue #610 (RGBBus bounce buffers, ST7701S WIP);
lbuque/lcd_binding_micropython repo; circuitpython.org board page for
the 2.1; community C references for panel timing (stefankn's
esp32-s3-lcd-2.8c-template; murr2k's esp32-s3-touch-lcd-2.1 demos).

### Only the hardware can settle these (Sunday list)

- Which firmware route actually initialises THIS panel, and what its
  Python API hands us (raw RGB565 framebuffer? LVGL only?).
- The 2.8C's exact RGB pin map, ST7701 init side-channel pins, and
  touch chip — from its wiki/schematic, then proven on the bench.
- Whether our Python `framebuf` can *be* the panel's scanout buffer,
  or the C driver keeps its own and we pay a full-frame copy per
  frame (460,800 bytes at 480×480×2 — the difference between easy
  20 fps and a fight).
- Real frame rate for a full Python redraw at 480×480, and whether
  bounce buffers are in play. The show is mostly stillness with ~4 s
  of motion a minute, so even 12–15 fps during shows is acceptable —
  but it must not tear.
- PCF85063 present and at I2C 0x51 on the unit that arrives.

### Firmware build outcome — Nov 14, 2026 (appended)

The custom-firmware route **built successfully**. MicroPython v1.29.0
+ ESP-IDF v5.5.2 (the panel doc's pinned IDF v5.2.2 is stale; MP
v1.29 supports IDF v5.3–v5.5.4) + ESP32_Display_Panel v1.0.5, using
the library's own board definition for this exact board
(`BOARD_WAVESHARE_ESP32_S3_TOUCH_LCD_2_8_C` — ST7701/RGB pin map,
init sequence, GT911, TCA9554 all match §1). Artifact:
`firmware/painter-firmware.bin`, a combined image flashable at 0x0
(16 MB layout: factory app 4 MiB @0x10000, FAT vfs ~12 MiB
@0x410000). Full recipe, failure history, and API:
`firmware/API_NOTES.md` and `firmware-build/build_log.md`.

The Python API is `from esp_panel import Board` with
`init()/begin()/deinit()/color_bar_test()` — and a catch the research
above predicted: **upstream's binding exposes no pixel pushing at
all**. The binding in our build is extended (in the library clone's
`mpy_support/esp_panel_mp_board.cpp`, marked "Painter Clock
additions") with the three methods display.py needs, wrapping the
C++ `drawBitmap` / `getFrameBufferByIndex` / backlight APIs:

- `draw_bitmap(x, y, w, h, buf) -> bool` — RGB565 buffer, the
  guaranteed-correct copy path.
- `frame_buffer_addr() -> int` — address of the driver's frame
  buffer 0 for the zero-copy path
  (`uctypes.bytearray_at(addr, 460800)` + `framebuf.FrameBuffer`).
- `set_backlight(level) -> bool` — 0..255.

Two build gotchas worth remembering: (1) the libraries must be
integrated as plain IDF components, not usermods — MicroPython's
QSTR scan runs every usermod source through one shell command and
the stock build already sits within ~2 KB of the kernel's
128 KiB argument cap; the build also has to run through a `/fb`
bind mount of the tree for the same reason (recipe in API_NOTES).
(2) The upstream doc's step of copying esp_lcd headers into
mpy_support must be skipped on IDF 5.5 — `#pragma once` makes the
copies double-define against the real headers.

Still open (bench only, added to the Sunday list above): whether
`begin()` lights this panel as configured (first test:
`color_bar_test()`), and whether direct writes to
`frame_buffer_addr()` reach the screen without a flush or whether
frames must go through `draw_bitmap`.

---

## 3. The animation system

Canvas is 480×480, centre (240, 240). Everything is drawn, nothing is
video. One parameter — **stroke progress** `p` ∈ [0, 1] — drives each
wipe/paint: the revealed fraction of the hand, the brush/cloth tip
position, and (through the tip) the figure's arm pose and body
position all derive from the same `p`, so they cannot drift apart.

### 3.1 The minute show (~4.0 s; ~5.2 s when the hour hand moves)

Timings are the prototype's, in milliseconds. The show runs once per
minute, on the minute.

| Step | Dur | What happens |
|---|---|---|
| glance | 300 | He notices. Head tilts toward the minute hand; body starts stepping toward the work (follow 0.35). |
| wipe (minute) | 950 | Cloth follows the OLD minute angle tip→centre; the hand un-reveals segment by segment behind the cloth. |
| wipe (hour) | 600 | Only when the hour hand steps (every 12 min): same, for the hour hand. |
| dip | 1050 | Step toward the bucket (follow 0.30), bend at the waist — fold in over 0–32%, **hold** the stoop 32–68% with two brush dabs (dabbing across 38–68%), straighten 68–100%. Bend peaks at ~1.02 rad (~58°) with a ~14 px crouch (480-scale). |
| paint (hour) | 650 | Only when the hour hand steps: brush paints the new hour angle centre→tip. |
| paint (minute) | 1150 | Brush paints the new minute angle centre→tip; hand reveals behind the brush. |
| inspect | 520 | Step back toward home (follow 0.05), head tilt, small nod. Show over. |

Sequence order: glance → wipe minute → wipe hour (if due) → dip →
paint hour (if due) → paint minute → inspect. (The prototype builds
the step list in exactly this order.)

### 3.2 Hands

- Minute hand length 163 px, hour hand 108 px (480-scale).
- Drawn in **14 segments**. Reveal fraction = stroke progress; the
  frontier segment is drawn partially. Segment width tapers
  `1 − 0.45·f` along the hand.
- **Fixed wobble:** each segment is offset perpendicular to the hand
  by `sin(f·22)·a` where `f` is the fraction along the hand and `a`
  the wobble amplitude (1.6 px at prototype scale ≈ 0.9 px at 480 —
  sub-pixel in RGB565, so use `a` ≈ 1.5–2 px on-device; tune on the
  panel). Same wobble every time = his "handwriting".
- Centre boss: filled circle, radius ≈ 0.85 × hand width.
- **The hour hand moves in 6° steps every 12 minutes**, not
  continuously — that's when its wipe/paint runs. On the hour both
  hands are wiped and repainted (and see §3.4).
- **No second hand.** By design — he couldn't keep up, and the concept
  is truer without one.

### 3.3 The figure rig (480-scale numbers)

Prototype geometry scaled by 480/880 = 0.5455. All values in pixels,
origin top-left, y down.

| Quantity | Value |
|---|---|
| Home feet position | (240, 446) |
| Shoulder height above feet | 152 → home shoulder ≈ (244, 294) |
| Head centre height above feet | ≈ 199 → home head ≈ (240, 247) |
| Bucket position | (332, 436) (92 right of home feet, 10 above) |
| Shoulder x clamp | home ± 106 |
| Hip pivot height above feet | ≈ 81 (bend rotates torso+head about this) |
| Arm bones | upper 48, forearm 47 — total reach 95, clamped to 93 |
| Blur (prototype) | figure rendered offscreen, composited at ~3.5/880 ≈ 2 px blur, alpha 0.95 |

**Body-follow.** The figure does not stand still and stretch. A
desired shoulder point is computed each frame as
`home + (activeTip − home) × follow`, with `follow` per phase
(glance 0.35, wipe/paint 0.68, dip 0.30 toward the bucket, inspect
0.05). The actual shoulder eases toward the desired point with an
exponential lag (time constant τ per phase: glance 300 ms,
wipe/paint 170 ms, dip 200 ms, inspect 320 ms, idle default 380 ms).
Feet follow the shoulder (he steps), clamped inside the dial, with a
small stepping bob while moving.

**Two-bone IK.** Shoulder S, target T (brush or cloth tip). With bone
lengths L1=48, L2=47: clamp |ST| to ≤ 93; standard cosine-rule elbow;
choose the elbow solution that scores best on (lower elbow preferred,
slight outward bias) — the prototype's scoring is
`elbow.y + 0.15·|elbow.x − CX| + 0.1·(side-signed x)`. Because the body
follows the tip, the residual reach after following is ~76 px worst
case (12 o'clock tip) — comfortably inside 93, so the elbow always
keeps a natural bend and the arm never changes length.

**Poses per phase** (all derived, none keyframed by hand):
- *Idle:* arms hang, breathing sway (slow ±1 px vertical bob of the
  whole figure), occasional weight shift.
- *Glance:* head tilt toward the active tip, proportional to its
  horizontal offset.
- *Wipe:* cloth hand at the frontier point of the old hand
  (`tip(angle, reveal, len)`); brush hand hangs.
- *Dip:* torso/head group rotates about the hip pivot by
  bend × 1.02 rad, plus crouch; brush hand targets inside the bucket;
  the bend envelope is fold-in / hold / straighten (never a sine
  hump — a peaked-for-an-instant bend reads as no bend; that lesson
  is already paid for). Cloth hand braces on his knee at full bend —
  the old side-hang target is outside the fixed arm's reach there.
- *Paint:* brush hand at the frontier point of the new hand.
- *Inspect:* both hands down, slight backward step, head nod
  (two small dips).

### 3.4 The hourly ritual — "cuckoo" (PROTOTYPE-PENDING)

Designed Nov 13 at Mark's request; a prototype edit is landing in
parallel, so timings/details below are the design intent and get
reconciled with the prototype before the port hardens.

On the hour, after both hands have been wiped and repainted:

1. He steps to centre, below the hub, and **leans his head in toward
   the glass** (~1 s) — head and shoulders come forward, scaling up
   slightly as if closer to the viewer.
2. With the cloth he **wipes a clear circle in the frost** centred on
   his face: a small circular wiping motion (~1–1.5 s) opens a
   porthole roughly face-sized (design target ≈ 96 px diameter at
   480-scale).
3. **His face is briefly visible in focus** through the cleared
   circle (~1.2 s hold) — the one moment in the hour he is sharp
   instead of a frosted blur. A nod or a blink here is prototype
   tuning, not spec.
4. **The frost creeps back** (~1.5 s): the circle clouds over from
   the rim inward until the glass is uniform again.
5. He steps back to home and resumes — idle, until the next minute
   show. Total added time ≈ 4–5 s, once an hour.

Rendering consequences are in §4.3. Like the driver, this is marked
prototype-pending: the S3 implementation follows whatever the
prototype settles on.

### 3.5 Idle routines

Between shows he is alive but quiet. Routines fire at random
intervals (prototype: weighted random pick when idle long enough);
durations from the prototype:

| Routine | Dur (ms) | Notes |
|---|---|---|
| wristwatch check | 2100 | The man inside the clock checks the time. |
| brow wipe | 2100 | Back of the cloth hand across the forehead. |
| shoulder roll | 2100 | Both shoulders, one slow roll. |
| mug sip | 2100 | Mug appears from beside the bucket; sip; gone. |
| cap-off forehead wipe | 4000 | Held phases: grab cap 0–.22, lift clear .26–.42, hold cap at his side (hair visible, brush hidden — that hand holds the cap), cloth hand makes two forehead passes, cap back on. |
| hanky nose-blow | 3600 | Cloth becomes the hanky: up to the nose, head dip, **two** short blows (hanky puffs/bobs with each), final dab. |

Every idle target is checked against the same fixed arm reach — the
prototype hand-verified each routine's extremes stay inside it, and
the port keeps that rule: no pose may ask the arm to stretch.

---

## 4. Rendering strategy (ESP32-S3)

### 4.1 Framebuffer

One full framebuffer, 480×480 RGB565 = **460,800 bytes**, allocated
in PSRAM (`display.py` owns it). The S3R8 has 8 MB PSRAM; one buffer
is comfortable, two (921,600 B) are affordable if the chosen driver
wants double buffering — but see the copy-cost warning in §2: whether
our buffer can be the scanout buffer is a Sunday measurement, not an
assumption.

Dial, figure and hands are composited into this buffer in Python with
`framebuf` primitives plus our own polygon/line code (`clockface.py`,
`figure.py`). No per-frame blur, no per-frame alpha over the full
screen — both are far too slow in interpreted Python at 480×480.

### 4.2 The frosted-glass figure without per-frame blur

The prototype blurs the whole figure every frame (canvas filter).
The port bakes the blur in, in three parts:

- **Body sprite, pre-blurred.** The figure's body (overalls, legs,
  head, cap) is drawn once — either at first boot or, better,
  generated on the desktop and shipped as sprite data — then blurred
  ONCE with a small box blur (radius ≈ 2 px at 480) and stored as an
  RGB565 sprite with a transparent key colour. Each frame it's a
  plain keyed blit (per the standing lesson: **plain keyed blits
  only — framebuf palette blits draw nothing on v1.29 ESP32**).
  Body movement (stepping, leaning, bob) is just the blit position;
  the bend is the one hard case — see below.
- **Arms drawn soft, not blurred.** The arms move every frame, so
  they are drawn per-frame as tapered polygons in the body's blue
  with slightly soft (pre-blended edge) colours — at 2 px of intended
  blur, a 1 px mid-tone edge reads the same from arm's length. The
  brush and cloth are small sprites, also pre-blurred.
- **The bend.** Rotating a pre-blurred sprite per frame is not
  available in `framebuf`. Options, in order of preference:
  (a) pre-render the torso+head sprite at a handful of bend angles
  (e.g. 0°, 15°, 30°, 45°, 58°), each pre-blurred, and pick/blend by
  nearest angle during the 1.05 s dip — five small sprites, cheap;
  (b) draw the torso as polygons per frame like the arms.
  The skeleton assumes (a) — `figure.py` exposes pose angles and a
  TODO marks the sprite set as a Sunday decision once frame rate is
  known.

### 4.3 Frost layer and the cuckoo porthole

The dial's default state IS the frost: the figure is behind frosted
glass at all times (§4.2's blur is the frost). The hourly ritual
needs a *clearer-than-default* hole, so it is implemented as a
regional effect, never a full-screen pass:

- A **frost overlay patch**: a pre-rendered frost-texture buffer the
  size of the porthole's bounding square (≈ 110×110 px at 480).
- During the ritual, only that patch is recomposited per frame:
  draw the sharp scene into the patch (dial + **in-focus face
  variant** of the figure sprite — a second, unblurred head/face
  sprite, shipped alongside the blurred set), then blend the frost
  texture back over it with a circular mask whose radius/opacity
  follows the wipe/clear/creep envelope.
- Per-frame cost is bounded by the patch (~12k pixels), trivial next
  to a full frame. The mask is applied per scanline (circle spans
  precomputed), the same trick the hand segments use.
- The face variant is the only sharp artwork in the project; it
  exists only inside the porthole and only during the ritual.

### 4.4 Frame loop and performance posture

- Target: redraw at ~20 fps during shows/idle routines, drop to a
  near-static 1 fps (breathing bob only — in practice redraw on bob
  phase steps) when nothing is happening. A clock that is still 56 s
  of every minute should not burn the panel or the CPU.
- Optimisation ladder if full redraws are too slow (measure Sunday):
  (1) pre-rendered static dial layer blitted first each frame
  (already the plan); (2) dirty-rectangle redraws around the figure
  and the active hand only; (3) fewer, larger animation steps during
  wipe/paint (the segment reveal tolerates 8–10 fps gracefully);
  (4) move the figure blit + hand drawing into the driver's LVGL
  surface if the firmware route forces LVGL (last resort — the
  drawing code is deliberately driver-shaped to make this possible).

---

## 5. Timekeeping

- **NTP first:** after Wi-Fi joins, `ntptime.settime()` (stdlib),
  re-sync every 6 h and after any Wi-Fi reconnect. Mark is in
  America/Phoenix — UTC−7 year-round, no DST — so local time is a
  fixed offset from `config.json` (`tz_offset_h`, default −7); no
  tz database needed.
- **PCF85063 RTC as the fallback and the boot source:** the RTC is on
  the shared I2C bus (addr 0x51). A tiny pure-Python driver
  (`timekeep.py`, ~40 lines of BCD register reads/writes — well
  inside stdlib `machine.I2C`) reads it at boot *before* Wi-Fi, so
  the clock shows the right time from the first frame; every
  successful NTP sync writes the RTC back. If Wi-Fi is down at boot,
  he paints RTC time and corrects himself when the network returns.
- The internal `machine.RTC` is set from whichever source wins, and
  the show scheduler keys off it: a show is due when the minute
  changes; the hour ritual when the hour changes.

---

## 6. Code layout and the display contract

```
main.py       boot, Wi-Fi, time, scheduler, admin — the conductor
display.py    THE DRIVER SEAM. Only file that knows the firmware route.
clockface.py  dial layer + hand drawing (segments, wobble, reveal)
figure.py     rig math (follow, IK), pose computation, sprite blits
show.py       choreography state machine (shows, idles, cuckoo ritual)
timekeep.py   NTP + PCF85063
prov.py       rehoming: setup-AP captive portal (PainterClock-Setup)
updater.py    GitHub update check/apply (blob-SHA verified)
admin.py      port-80 admin page (started by main.py)
wifi_cfg.py   SSID/PASSWORD — board-local, NEVER in the update list
config.json   board-local settings, NEVER in the update list
update_files.txt  the updater manifest, read fresh on every check
```

`display.py` contract — the rest of the code uses only this:

```python
WIDTH = HEIGHT = 480
def init() -> bool          # panel up, backlight on; False = no driver
def framebuffer()           # framebuf.FrameBuffer, RGB565, ours to draw in
def show()                  # present the framebuffer (driver-dependent)
def set_backlight(level)    # 0..255 (night mode)
def is_live() -> bool       # False while the stub is in place
```

While the stub is in place (until Sunday), `init()` returns False,
drawing still runs against a PSRAM buffer, and `main.py` serves the
admin page and logs "no display driver yet" — so every non-display
path (Wi-Fi, provisioning, updater, admin, timekeeping, the whole
state machine) can be exercised in Thonny before the panel lights.

---

## 7. Mark's standing build rules, baked in

Same machinery as LS Lite Micro / metar-micro, same file names and
behaviour, so this device is operated like the others:

1. **Rehoming (`prov.py`).** Holding BOOT *just after* power-up
   (never during plug-in — that is download mode on the S3) — or
   booting with no usable credentials — drops the join and starts
   the `PainterClock-Setup` access point with a captive portal
   (DNS redirect to 192.168.4.1, network scan + pick-or-type SSID,
   show-password peek). Saving writes **only** `wifi_cfg.py` and
   reboots. Pattern copied from metar-micro's `prov.py`.
2. **Update-available (`updater.py`).** Git-less self-update against
   this project's GitHub repo: after boot and then hourly, fetch
   `update_files.txt` **fresh from the repo** (built-in list is only
   a fallback — a frozen list stranded a module once), compare each
   listed file's git blob SHA with GitHub's, and **only flag**
   "Update available" in the admin page. Install happens only when
   Mark presses **Update now**: download each changed file, verify
   its blob SHA, swap in with `.bak` kept, reboot. `wifi_cfg.py` and
   `config.json` are never in the manifest.
3. **Admin page (`admin.py`, port 80).** Status (time source, Wi-Fi,
   update flag), settings (tz offset, night mode — see open
   questions), Update now, Rehome instructions, Restart. Mirrors the
   other builds' admin shape.

Repo: to be created by Mark (the GitHub integration can't create
repos). `updater.py` carries `GITHUB_REPO = "markyharris/painter-clock"`
as a **placeholder** until he names it — see open questions.

---

## 8. Open questions for Mark

1. **GitHub repo name** — `markyharris/painter-clock`? He creates the
   repo himself; the updater placeholder gets corrected to match.
2. **Night mode, 22:00–06:00** (the ticker dims then): dim the
   backlight (to what — the ticker's 25%?), and does he slow down /
   skip idle routines at night, or paint on as usual, just dimmer?
   Does the cuckoo ritual still run at night?
3. **Face details** — ticks only (the prototype's current look), or
   faint numerals? Hand colour/weight are tuned on the panel, but
   ticks-vs-numerals changes the pre-rendered dial.
4. **Which board actually arrives** — 2.1 or 2.8C? Same code either
   way; the bring-up checklist has one branch (touch chip / pin map
   confirmation) that depends on it.
5. **Cuckoo ritual tuning** — once the prototype version lands:
   porthole size, how long his face stays clear, nod/blink or
   straight-faced?

---

## 9. What "done" looks like on Sunday

Firmware route chosen and panel lit → first frame from
`clockface.py` → the minute show running at an acceptable frame
rate → NTP + RTC agree → provisioning round-trip (forget Wi-Fi,
rejoin via PainterClock-Setup) → updater check against the real
repo flags clean. Then, and only then, the animation engine gets
built out for real. See README.md for the step-by-step checklist.

---

## Addendum — Nov 13, 2026 (Mark's night-mode decision)

Mark settled the §8 night-mode question with a better idea than dimming: for the hours set in the admin (start/end), the little room's light goes off — the scene darkens — and the painter lies down and sleeps, Zzz drifting up from him, while the clock keeps telling time (hands still advance; no paint show while he sleeps). The prototype is implementing this first (admin-set hours on the prototype's panel); the port follows the prototype's final behaviour. Remaining detail for the port: whether he wakes for the on-the-hour cuckoo moment during sleep hours (prototype behaviour governs).

## Credit (required, standing)

The admin page carries a credit line: an homage to **Maarten Baas** and his **Schiphol Clock** (Amsterdam Airport Schiphol, 2016), from the *Real Time* series. Added to admin.py's page footer Nov 13, 2026 at Mark's request — keep it in any rewrite of the admin page.

## Board CONFIRMED — Nov 13, 2026

Mark confirmed the ordered board (arriving Sun Nov 15): **Waveshare ESP32-S3-Touch-LCD-2.8C** — https://www.waveshare.com/esp32-s3-touch-lcd-2.8c.htm
Verified from the product page (read Nov 13): ESP32-S3R8, 16MB flash, 8MB PSRAM; 2.8in IPS 480x480, RGB interface, **ST7701** driver; touch **GT911** over I2C; **PCF85063 RTC** onboard (matches timekeep.py's plan); TCA9554PWR GPIO expander; QMI8658 6-axis IMU; TF slot; CH343P USB-UART; buzzer; MX1.25 battery header. This closes §8 question 4: it is the 2.8C, not the 2.1 — same 480x480 canvas the port numbers assume; touch chip is GT911 (only relevant if touch is ever used; the design does not need it). Sunday bring-up still starts with the firmware question (ESP32_Display_Panel mpy_support route).

## Board ARRIVED + factory demo verified — Nov 14, 2026

The 2.8C arrived a day early (Sat Nov 14, not Nov 15). Mark powered it on USB-C and the factory demo (an LVGL "Onboard" test app) runs: panel lights evenly, backlight slider works, touch responds (he scrolled the page), QMI8658 IMU reports live angular deflection, the PCF85063 RTC is alive (counting up from the 1970 epoch, unset), wireless scan found Wi-Fi/BLE devices, and the demo reports **Flash Size 16 MB** as spec'd. Panel, backlight, expander and touch are therefore proven good before any of our firmware touches the board — bring-up checklist steps 1–2 done.

Waveshare's demo package (ESP32-S3-Touch-LCD-2.8C-Demo.zip, downloaded Nov 14) contains only Arduino and ESP-IDF examples plus a single full-flash factory image — **no MicroPython firmware for this board exists from Waveshare**, and none was found elsewhere (CircuitPython covers only the non-C 240x320 namesake). The factory restore image is saved at `factory/ESP32-S3-Touch-LCD-2.8C-factory.bin` (16 MiB, flash at 0x0 to return the board to as-shipped state). The firmware route therefore stands as §2's primary: a custom MicroPython build with Espressif's ESP32_Display_Panel (mpy_support). Buster takes the first build attempt on the VM; Mark's next bench session starts by flashing the resulting image (Thonny 5, family ESP32-S3, address 0x0).

---

## Addendum — Nov 15, 2026 (display architecture + multi-face)

**Display route: BENCH-PROVEN and implemented.** The Nov 15 bench session (full results in `firmware/API_NOTES.md`) settled §2's open questions the hard way: v2 firmware lights the panel (`init()`/`begin()`/`color_bar_test()` all True, colour bars photographed), but **large single transfers wedge the chip hard** — a full-size `framebuf.FrameBuffer`, writes via `frame_buffer_addr()`, and a single full-frame `draw_bitmap` (460,800 B) each hang it past Ctrl-C, reset required. What works instantly: `draw_bitmap` of a 100×100 tile and of a 480×120 band (115,200 B), and sustained animation of full frames shipped as **4 bands of 120 lines** (6-frame red/blue flip test, clean). The cliff sits between 115 KB and 460 KB; the design stays at the proven size.

`display.py` is therefore built as:

- **Two plain-bytearray canvases** (frame + pre-rendered static layer, 460,800 B each in PSRAM), drawn through a `Canvas` class implementing the framebuf-style methods the project uses (`fill`, `pixel`, `fill_rect` via row-pattern slice writes, `line` Bresenham, filled `ellipse` via row spans, opaque `blit` via per-row slice copies). **No full-size FrameBuffer anywhere; `frame_buffer_addr()` is never called.**
- **`show()`** ships the frame canvas with 4 `draw_bitmap` calls of 480×120, memoryview slices — no copies.
- **Keyed sprite blits** (`display.blit_sprite`): per-row, only opaque runs are slice-copied (plain keyed blits per the standing lesson — framebuf palette blits draw nothing on v1.29 ESP32).
- **Stride-window helper** (`Canvas.window(x, y, w, h)`): a real `framebuf.FrameBuffer` over a memoryview window of the canvas with stride 480, for code needing genuine framebuf primitives over a bounded region (a hand's bounding box, text). **Hard cap: spanned bytes ≤ 115,200** (the proven band size); it raises past the cap.
- §6's contract is revised accordingly: `display.framebuffer()` survives as a compat alias but returns the frame **Canvas**, not a FrameBuffer. `init()` still returns False (canvases usable) when the driver is absent, so headless Thonny runs still work.

One drawing fix from desk tests the same day: `clockface.thick_line` now stamps filled discs along the segment — the skeleton's parallel-offset-lines version left a pinhole moiré on diagonals after int() rounding. Hands are solid at any angle.

**First frame:** `bench_first_frame.py` (Thonny bench runner, no Wi-Fi/updater/admin) renders the dial and composes one frame with the hands at **10:09 — a fixed demo time**, labelled as such in the file; real timekeeping arrives with `timekeep.py` in the main path.

**Multi-face decision (Mark, Nov 15):** the clock ships **multiple selectable faces**, the painter as flagship/default. The plumbing is face-generic from now on:

- A face is a module exposing **`render_static(canvas)`** (draw the static layer once into `display.dial()`) and **`compose(canvas, time_tuple, state=None)`** (copy the static layer in, draw what moves). `clockface.py` is the painter face (`NAME = "painter"`); future `face_classic.py` (classic analog) and `face_digital.py` plug into the same display layer with **no display.py changes**.
- Selection is the **`face` key in admin config** (`admin.py` DEFAULT_CONFIG, default `"painter"`; options painter/classic/digital). Switching faces re-renders the static layer once; per-frame cost is one canvas copy plus the face's own drawing.
- Headroom is ample: the two canvases total ~0.92 MB of 8 MB PSRAM and the filesystem has ~12 MB — and the painter (sprites, figure, shows) is the most expensive face by far; classic and digital are strictly cheaper. `bench_first_frame.py` already reads the `face` key and falls back to the painter for unbuilt faces; main.py adopts the same selection when its compose loop moves to the face API.

## Addendum — Nov 15, 2026 (band-window drawing: dial + hands in C)

The first-frame bench run exposed the real bottleneck, and it was not shipping frames: **`show()` takes 40 ms** (4 band `draw_bitmap` calls), but the Python-loop drawing measured **54,410 ms for `render_static`** (the dial) and **20,365 ms for `compose`** (dial copy + two hands) on the board. Per-row ellipse loops, disc-stamped `thick_line`, and float-heavy geometry per primitive are simply too slow in interpreted MicroPython at 480×480 — a full minute-plus for one frame. (The run was interruptible, not a wedge; Ctrl-C landed inside `Canvas.ellipse`.)

**Fix — all dial and hand drawing now runs as genuine C `framebuf` primitives inside band windows:**

- `display.Canvas.band_windows()` yields a real `framebuf.FrameBuffer` (480×120, stride 480 — the bench-proven band geometry) over each band of the canvas. Drawing uses window-local coordinates (canvas y − band y); framebuf clips at band edges. A 480×120 window `fill_rect` + `show()` was bench-verified instant and pixel-correct before this rewrite was built on it. The full-size FrameBuffer ban stands untouched.
- **Dial** (`clockface.draw_dial`): per band — `fill(RIM)`, filled `ellipse` for the shade ring and cream face (centre translated per band), and each of the 60 ticks as one filled `poly` (a quad widened/lengthened by the old capsule radius, same r0/r1/width table as before).
- **Hands** (`clockface.draw_hand`): each hand is built ONCE as a single filled polygon — the wobbled centreline from the unchanged 14-segment `sin(f*22)` math, offset perpendicular by half the local width (same taper, same `w//2` radius the disc stamps used) — and drawn with one `framebuf.poly(..., fill=True)` per band. Reveal semantics are preserved exactly, including the frontier segment's partial polygon and the no-boss-below-0.003 rule; the centre boss is a filled `ellipse` per band. `show.py`'s wipe/paint choreography is unaffected.
- `Canvas`'s Python primitives and `thick_line` remain for the figure and sprite paths (figure.py depends on them); only the dial/hand hot path moved.

**Desk verification (CPython, stub framebuf ported from v1.29 `modframebuf.c`):** old vs new renders of the dial and the 10:09 frame differ in 2,433 / 2,829 pixels of 230,400 (1.1% / 1.2%) — every differing pixel lies within 2 px of a drawn feature (tick edges, hand edges, ellipse rim), **zero structural differences**; reveal assertions (0 = dial exactly, ≤0.003 = nothing, partial = monotonic and confined past the frontier) pass on both versions. All 11 root modules compile under mpy-cross. Expected board effect: dial render and per-frame compose drop from tens of seconds to the tens-of-milliseconds class of `show()` — to be confirmed at the next bench session by re-running the stage timings.

## Addendum — Nov 15, 2026 (the painter: figure + show, sprite/arm split)

`figure.py` and `show.py` are now real implementations (bench runner: `bench_painter.py` — paints 10:09, runs the 10:10 show once in real time, prints per-frame timings). Board-confirmed budget going in: dial render 109 ms, compose 120 ms, `show()` 40 ms; the design target is a full animated frame (dial copy + figure + hands + show) at or under ~200 ms.

**The sprite/arm split (§4.2, settled as option (a) with two angles).** Per-frame Python drawing is too slow, so:

- **Two body sprites**, pre-rendered once at boot (`figure.prepare()`) into keyed RGB565 bytes via band-window C primitives on a scratch canvas: **standing** and **full dip** (waist fold 1.02 rad about the hip, +14 px crouch). Legs/boots, overalls + bib + straps over a chambray shirt, neck, head and cap are baked in — v1 has **no separate head tracking** (`head_tilt` is carried in the pose but not rendered; the inspect nod and glance tilt are state-only for now). The cap is drawn as a band through the bend transform so it tilts with the head in the dip. The **bucket** is a third small sprite (52×42) blitted at `figure.bucket_x`, so a future bucket-rearrange idle only moves a number.
- **Blits use precomputed opaque-run lists** (301 runs standing / 253 dip / 30 bucket), computed in `prepare()`: a per-frame key scan of the ~59k sprite pixels in Python (`display.blit_sprite`'s job) would eat the frame budget, so a frame's blit is ~330 slice copies and nothing else. Desk-verified pixel-identical to `display.blit_sprite`.
- **Arms are per-frame**: two-bone IK (bones 48/47, reach clamped to 93 — the arm never stretches), each segment one filled polygon through the frame's band windows; hands are small discs; brush/cloth drawn at the working hand. The torso switches sprite at eased bend ≥ 0.5, and **the arm anchors snap to the same bend** so the arms stay glued to the visible torso.
- **The drawn body vs the follow rig:** the eased shoulder follows the tip per §3.3, but a rigid sprite can't stretch like the prototype's procedural torso. The drawn body therefore follows the shoulder's x in full (he steps sideways) and its y only within **−52/+6 px** (he rises toward high work, never sinks through the floor); `pose()` derives the arm anchors from the *drawn* body, and the IK clamp absorbs the withheld travel — worst case a transient ~76 px shortfall at a wipe's first instants while he is still stepping to the work, the same character as the prototype's easing lag. Feet stay inside the dial at all times.

**Show timings — the laborious set (prototype, Nov 13) replaces §3.1's table:** glance 300, wipe minute **2,600**, wipe hour **1,750**, dip **1,550**, paint hour **1,950**, paint minute **3,200**, inspect 520. Wipe/paint progress runs through `work_ease()`: piecewise-linear with two stalls — 28–38% and 62–72% of the stroke's time each buy only 5% progress; the same eased progress drives the hand reveal and (through it) the tool tip. The dip keeps the trapezoid envelope (fold 0–32%, hold 32–68% with two brush dabs, straighten 68–100%); at full bend the free hand braces on his knee. The hour hand still steps 6° every 12 minutes with its own wipe/paint; on the hour both hands are redone. **The cuckoo ritual (§3.4) is not scheduled in v1** — its frost patch and sharp face sprite don't exist yet; `frost_clear` and the `lean_in` intent are carried so it drops in without an API change. Idle routines keep the prototype's durations; only the wristwatch sketch moves a hand (bare left hand — a `"hand"` tool mode), the rest are timelines for the idle build-out.

**API:** `Show(fig, dial=None)`; `update(canvas, now_ms, time_tuple)` composes one frame (dial copy → figure → hands via `clockface.compose` state overrides) and returns the pose; `tick()` still advances without drawing for main.py's loop; `demo(now_ms)` runs one full minute step on demand. The scheduler is forward-only, so a demo minute or a backward time step never rewinds the show.

**Desk verification:** IK over 3,580 targets — bone lengths exact, in-reach targets hit exactly, out-of-reach clamped to exactly 93, never over-extended; `work_ease` monotonic with stalls buying exactly 0.05 each; state machine visits stages in order for a plain minute (glance → wipe_min → dip → paint_min → inspect) and an hour-step minute (hour wipe/paint inserted in order), ending with the correct hand angles/reveals; a full simulated 10:09→10:10 show audits bone lengths and reach on every frame. **Per-frame primitive count (mid-paint, desk-counted): 1 canvas copy + 2 run-blits (331 slice copies) + 16 `poly` + 11 `ellipse`** — against the board's 120 ms compose (copy + hands alone), the figure's share estimates at ~10–25 ms, putting a full frame at ~170–190 ms including `show()`; `bench_painter.py` prints the real numbers at the next bench session. Pose previews (standing 10:09, mid-wipe, dip hold, mid-paint) rendered and eyeballed against the prototype's look — flat shading, correct proportions and rig.

## Addendum — Nov 15, 2026 (figure v2: rect pre-compositing, and the arm fix)

The first `bench_painter` run on the board gave the split plainly: dial render 105 ms, compose (copy + hands) 120 ms, `show()` 40 ms — but **figure sprite prepare 6,288 ms** (tolerable, once) and **per-frame update+show averaging 3,979 ms** (whole 10:10 show: 23,904 ms over 6 frames). The show logic was right; the figure's per-frame path was the cost — ~330 Python slice copies for the run-list blits plus the arm polygons, and on this board a Python-level drawing op runs ~5–10 ms. The fix is the same lesson as the dial rewrite: per-frame Python-op count near zero, everything C.

**Rect pre-compositing.** `figure.prepare()` now builds **opaque rectangles**: for each body pose (standing, dip) and each point of a small snap grid, one cropped rect holds the dial region it covers with the bucket and body already drawn over it. Compositing is C-only: the dial is blitted in from the dial canvas's band windows, then bucket and body are drawn with `framebuf` primitives through per-band views over the rect (each view's spanned bytes stay far under display.py's proven 115,200 B window cap; the largest rect is ~62k px). The body's content extent per pose is measured by shape-extent tracking in the draw helpers — no scratch canvas, no pixel scan (the scan was half of v1's prepare cost). The snap grids: standing x ∈ {−90, −60, −30, 0, 30, 60, 90}, y ∈ {−52, −26, 0}; dip x ∈ {0, 26}, y ∈ {−26, +5} (the dip only travels the short wipe-end → bucket trajectory) — **25 rects, 1.63 MB total** in PSRAM. `pose()` snaps the drawn-body offset to the same grid and derives the arm anchors from the SNAPPED body, so the arms stay glued to the visible torso; the IK targets stay continuous, so the working hand still tracks the stroke frontier exactly. Per frame, `draw()` is: one `framebuf` blit per band the rect touches (3), the two arms as band-window polygons, hand discs, and the tool — **desk-counted census: standing 11 C calls, mid-paint 14 C calls, zero Canvas drawing primitives, zero slice-copy loops** (plus ≤6 `Canvas.pixel` reads for prepare()'s dial fingerprint). Estimated full frame on the board: ~170 ms (copy ~10 + figure ~10–15 + hands ~105 + show 40), to be confirmed by `bench_painter.py`, which now also prints a figure-only draw time. `prepare()` is keyed on the dial canvas + a pixel fingerprint, so a face switch / dial re-render rebuilds the rects on the next draw; the contract is unchanged — the dial is rendered first (bench and main both do). One caveat carried from v1, now sharper: the bucket is baked into the rects at its home place, so the future bucket-rearrangement idle needs a `prepare()` rebuild to move the drawn bucket (the dip target already follows `bucket_x`).

**The arm fix (Mark's bench photo, same day).** The held 10:10 frame showed both arms as long, straight, uniformly skin-coloured bars crossing the torso in an X, hands heading for the opposite hips. Desk diagnosis of the shipped v1 found three stacked causes: (1) the shoulder anchors sat ±10 px about the centre — at the neck, not the torso corners — so the shirt-sleeve segments lay invisibly on top of the shirt torso and only skin ever showed; (2) the IK elbow score's outward term (0.15) was too weak: for an outward-leaning hang the inward elbow candidate sits a few px lower, and "prefer the lower elbow" picked it — both elbows bowed into the belly; (3) the hang targets put the hands ±36 px out, so the forearms speared diagonally out of the belly to reach them. The fix: **anchors at ±19**, just inside the drawn torso's top corners (±24), each bend-transformed from its own corner so the sleeve emerges at the shoulder seam and reads against the dial; **hang targets at shoulder + (±8, +84)** — hands at body centre ±27, just outside the thigh silhouette, on their own side; **IK outward weight 0.5 about the body's own centreline** (passed in by `pose()`), which flips hanging elbows outward while leaving every working pose's elbow choice unchanged (verified numerically across the wipe/paint/dip poses). Desk assertions now pin the rest pose: each hand on the same side of the centreline as its shoulder, within 6 px of the torso silhouette edge, elbow bowed outward of the shoulder→hand line.

**Desk verification (v1 vs v2, same deterministic sim):** composed-frame pixel diffs — standing 3,390 (arm fix only; body snap is exactly (0,0)), mid-wipe 8,861 (snap error +11.9 x / −2.7 y), dip-hold 2,479 (snap error 0.2 / 0.0; arm anchors only), mid-paint 8,202 (snap error −9.9 / −2.8) — **every differing pixel lies inside the union figure region; zero unexplained diffs**; the working hand (cloth/brush/bucket/knee targets) is pixel-exact between versions in all four frames. Snap error over a full simulated show: max 14.9 px x, 12.5 px y (the grid half-steps). IK re-verified over 41,616 targets (bone error 0.0000 px); `work_ease` and both state-machine sequences unchanged; all modules compile under mpy-cross. Pose previews regenerated and eyeballed: at rest the sleeves show at his shoulders, forearms hang skin-side down with a soft outward elbow, hands at his own thighs — the prototype's stance.

## Addendum — Nov 15, 2026 (working clock: time, Wi-Fi, self-running main)

The clock now runs itself: `main.py` is a real conductor (replacing the skeleton), `timekeep.py` / `prov.py` / `updater.py` are real, and `admin.py` is reconciled. Idles beyond the wristwatch sketch, the cuckoo ritual, the sleep pose, and battery mode remain later phases.

**Time architecture (supersedes §5's config-offset framing).** The timezone is **fixed UTC−7** (America/Phoenix, no DST) — a constant in `timekeep.py`, and the `tz_offset_h` config key is retired. The **system clock runs in local time and the PCF85063 stores local time**: `init_rtc()` reads the RTC at boot (before Wi-Fi) and sets the system clock directly, so a Wi-Fi-less boot shows correct local time from the first frame with no conversion anywhere. **NTP is the authority** when Wi-Fi is up: `sync_ntp()` takes ntptime's UTC answer, converts UTC→local, sets the system clock, and **writes the RTC back in local time**; re-sync every 6 h. RTC plausibility: year ≥ 2025, in-range fields, and the oscillator-stop flag clear — anything else is treated as unset (the factory-fresh RTC counting from 1970 is exactly that case) and the clock runs on the power-on epoch until NTP lands, with `time_source()` reporting `"none"` / `"rtc"` / `"ntp"` for the admin status block. `now_tuple()` is a plain `localtime()` read in the 8-tuple shape clockface/show consume.

**Boot order (main.py, each stage logs a `main:` line).** 1) BOOT sample (rehoming gesture, before anything that can hang) → 2) `init_rtc()` → 3) Wi-Fi join from `wifi_cfg.py` (~15 s window) → 4) NTP sync (non-fatal) → 5) `display.init()` → face `render_static()` → `figure.prepare()` → 6) admin server + after-boot updater check (flag only) → 7) the run loop. **Rehoming reconciliation:** no usable credentials *or a failed boot join* drops into the `PainterClock-Setup` portal (the standing contract — a clock that cannot join at boot needs setup, and the portal is the recovery); the fail-soft rule covers the rest — NTP failure or a mid-run Wi-Fi drop leaves the clock running from the RTC, and a non-live display leaves it painting into the canvases and serving admin.

**The run loop.** `show.Show` is driven by real local time: at each minute boundary the show performs that minute's routine (the 12-minute hour steps and the on-the-hour both-hands redo come from show.py's scheduler as built). Frames are composed **only when something changed** — a show running, an idle routine active, a minute boundary crossed, or a 1.5 s settle window after activity while he eases home; between routines the standing scene holds on the panel and no frames burn. The loop sleeps in 25 ms slices and services the admin server every slice; housekeeping (hourly update check, 6 h NTP re-sync, gc) runs only while he is idle.

**Admin reconciliation.** Config keys are now exactly: `face`, `brightness` (0–255, applied live), `sleep_enabled`, `sleep_start`, `sleep_end` — replacing the skeleton's `night_mode`/`night_dim`. The sleep keys + UI are in now (defaults 22:00–06:00, disabled); the lights-out **behaviour** lands next phase. The status block shows current time + source, Wi-Fi SSID/IP, display state, uptime, and code version; the Update section (status line + Update now) is wired to the real updater; the Baas credit footer is verbatim as ever.

**Updater.** The transport is no longer a stub: `_fetch` is metar-micro's board-proven raw-socket + ssl reader with the chunked-stream decoder, a User-Agent header (the GitHub API 403s without one), redirect following, and size caps. Check/apply semantics are unchanged (fresh manifest every check, blob-SHA verify before every swap, `.bak` kept, reboot only on a clean apply; a SHA mismatch aborts without swapping that file). `update_files.txt` is verified to list exactly the nine runtime modules — `main.py display.py clockface.py figure.py show.py timekeep.py prov.py updater.py admin.py` — with `wifi_cfg.py`, `config.json`, and the `bench_*.py` runners staying out.

**Desk verification (CPython, stub worlds):** RTC BCD register round-trip incl. the exact register image and the Sunday weekday; `init_rtc` accept (2026) / reject (2024, oscillator-stop); NTP offset math UTC 18:00 → local 11:00 with the RTC written back in local time; portal form decode + `wifi_cfg.py` write→load round-trip in a subprocess; updater fixture — flag set only when a SHA differs (2 of 3, incl. a module present only in the fresh manifest), `.bak` written on apply, SHA-mismatch aborts without swapping, `wifi_cfg.py`/`config.json` untouched; admin key set + HH:MM validation + page contents; and a simulated main loop (stub display/figure/show/network, scripted time) — frames flow at boot and through the settle window, **stop mid-minute**, the 10:09→10:10 boundary invokes the show, and the loop goes quiet again after the show settles. All 12 root modules compile under mpy-cross. Still bench-only: the portal round-trip on this board, real NTP/RTC agreement on hardware, and the updater against the live repo from the board.

## Addendum — Nov 15, 2026 (frosted glass, and the head: shorter neck, a face, higher cap)

**Frosted glass.** In the prototype he stands *behind* frosted glass — softened and slightly milky — while the hands, painted ON the glass, stay crisp. The board port now has the same read. The layering needed no change: `show.update()` already composes dial → figure → hands (verified in code and by pixel audit — the hands' INK pixel counts are identical at frost 0 and 55 in every pose; the only INK that changes is the figure's *own* paint, the bucket surface and brush tip, which veil with him as they should).

**How it's baked (zero per-frame image cost).** The frost lives in `figure.prepare()`'s pre-composited rects, in two passes over the existing compositing (dial → halo → bucket → body): (1) a **halo pass** — the whole silhouette (bucket + body) re-drawn at the eight compass offsets in a flat pale frost colour (`FROST_HALO`, the tint lifted toward white), dilating the shape by the halo radius; (2) the **veiled pass** — body and bucket drawn in a palette whose every colour is mixed toward a pale cool tint (`FROST_TINT` (224, 235, 246)) by `frost/100 × 0.65`. The mix is done in 888 and converted back through `rgb565()`, the same function the raw palette was built with, so hues pale and cool without shifting (skin, chambray and denim verified in the previews). The rect padding grows by the halo radius so the halo is never clipped by a rect edge; rect memory 1.63 → 1.67 MB. The **arms and tool** are drawn per frame, so they get the same treatment there: one halo poly (segment widened by the halo radius each side, flat halo colour) under each arm segment, and veiled sleeve/skin/tool colours — the hand disc and the tool are veiled but carry no halo of their own.

**Configuration.** Config key **`frost`, 0–100, default 55**; an admin field next to Brightness (parsed and clamped like brightness). `main.py` passes `cfg["frost"]` into `figure.prepare(dial, frost)` at boot and re-prepares live when it changes (the settings-changed path, alongside the face switch); `prepare()`'s cache key is now (dial canvas, dial fingerprint, **frost**), and the palette/halo state is re-derived on every `prepare()` call so the per-frame arms always match the baked rects. Halo radius: 1 px up to strength 74, 2 px above (≈ the prototype's 2.6 px blur at 880 scale).

**frost=0 is the sharp look, exactly.** At 0 the halo pass is skipped and the palette is the raw one — desk-verified **byte-identical frames** to the pushed v2 figure in all four poses (the A/B escape hatch). One evolution since that check: the head art below applies at *every* frost level including 0, so today's frost=0 differs from v2 only inside the head/neck zones (938–1,463 px per pose, zero unexplained diffs by the union-figure-region method).

**Census (desk-counted framebuf calls in `Figure.draw`).** Standing 11 → **17**, mid-paint 14 → **21** at frost 55 (+6 / +7 — the two arm-halo polys per frame, plus extra band-crossing calls where a widened halo poly straddles a band edge). Still zero Canvas drawing primitives, zero `pixel`/`line`; against the board's measured 22 ms figure draw at 14 calls, the frame stays ≈140 ms. At frost 0 the census is v2's 11 / 14 exactly.

**The cuckoo constraint (future phase — noted, not built).** The hourly cuckoo wipes a *clear* circle in the frost and his face shows **sharp** inside it, whatever the configured frost. The frost work therefore keeps a sharp-head path: `_draw_head()` is split out of the body drawing as its own function taking a palette — the patch will draw the head with `_RAW_PALETTE` and no halo pass (exactly the frost=0 treatment) inside its circular mask, while everything around it stays frosted. The face features below are drawn inside `_draw_head`, so the sharp head carries them too.

**Head art (Mark's notes from the live clock, same pass).** (1) **Shorter neck:** `HEAD_H` 199 → 187 — the head sits 12 px closer to the shoulders in both poses; the dip head follows the same bend transform as before. (2) **A face:** two bold eyes (2×3 ellipses) and a simple mouth (a shallow smile sliver), drawn in the palette's paint colour — pure INK sharp, veiled to a still-dark grey under frost, far darker than the veiled skin either way — with every point bend-transformed, so the face turns with the head in the dip. Baked into the rects like the cap: no per-frame cost. (3) **Cap higher:** the band now ends 8 px above the head centre and the brim at 5 (was 3 / −1), so a real forehead shows under the brim. Previews regenerated at frost 55 and 0 (standing, mid-wipe, dip-hold, mid-paint) and eyeballed: milky veil, pale halo fringe on the silhouette, hands crisp black on top; the new proportions read at a glance — head down on the shoulders, face visible through the veil, forehead under the raised cap.

## Addendum — Nov 15, 2026 (smoothness pass: finer snap grid, dirty-band show)

Mark, watching the live clock: "he's very jumpy — not intermediate movements." Two causes, both mechanical: the drawn body **teleported between snap points** 30 px apart (x) / 26 px (y), and frames landed at ~7.5 fps (board-measured 132 ms: compose ≈ 92 + `show()` 40). This pass fixes both without touching a single show timing, the IK, `work_ease`, or the state machine.

**Finer snap grid.** Standing steps halved — x ∈ {−90, −75, …, +90} (**15 px**), y ∈ {−52, −39, −26, −13, 0} (**13 px**); the dip refined in proportion (x {0, 13, 26}, y {−26, −11, +5}). Desk-measured over the full simulated 10:10 show, the **max snap error fell from 14.9 / 12.5 px to 7.5 / 7.5 px** (the y figure includes the ±1–3 px breathing/step bob the drawn body rides on). Grid count 25 → **74 rects**.

**The bucket split (how the memory stays in budget).** Naively, 74 union rects would have cost ~5 MB. Instead: a standing rect whose (halo-padded) body box does not reach the bucket box is now composited **body-only**, and the bucket is composited **once** into a shared rect (~3 KB) that `draw()` stamps first — the two boxes are disjoint by construction, so the stamp can never interact with the body rect, and the composited pixels are identical (desk-diffed, below). Rects that do reach the bucket — the dip (he leans over it) and the rightmost standing columns — keep the v2 union compositing unchanged. Measured: **74 rects, 2.08 MB total at frost 55** (standing 65 rects 1.72 MB, dip 9 rects 0.46 MB, shared bucket 2,952 B), against 1.58 MB before and the ~4.5 MB budget (canvases ~0.92 MB + the new 0.46 MB show() shadow leave the 8 MB PSRAM comfortable). `prepare()`'s fb-primitive count grows 5,249 → 14,140 at frost 55 (×2.7 — the halo pass is per-rect); the absolute board prepare time is whatever `bench_painter.py` prints on the next run (it printed 951 ms for the 25-rect sharp v2 build) — watch that line at the bench.

**Dirty-band presentation (`display.show()`).** `show()` keeps a **shadow copy of the last presented frame** and ships only the bands whose bytes changed. The comparison is `memoryview == memoryview`, which this firmware's MicroPython resolves to a C memcmp over the buffers (`py/objarray.c` `array_binary_op` → `mp_seq_cmp_bytes` — verified in the firmware source, not assumed): no copies, no Python pixel loops. A band whose `draw_bitmap` fails stays stale in the shadow and is retried on the next `show()`; `show(force=True)` re-sends all four bands and re-syncs. While he works, the figure and the moving hand touch 2–3 of the 4 bands, so the untouched band (often the top) is no longer re-sent 8 times a second. Desk-verified against a fake board: first show sends 4, unchanged frame sends 0, single-band change sends 1, a failed band is retried alone, headless `show()` still returns False and sends nothing.

**Compose audit.** `clockface.draw_hand` called `poly` + `ellipse` into **all four** band windows per hand (16 fb calls/frame for two hands) and let framebuf clip the misses. It now computes the hand polygon's y-extent once and calls only into the bands it intersects (the boss ellipse by its own extent) — the same band-limiting figure's helpers already used, pixel-identical by construction (a missed band could only clip to nothing). Hands census: **16 → 8 fb calls** in the standing/mid-wipe/mid-paint poses, 8 → 4 at dip-hold. Figure census is essentially unchanged (standing 17 → 18 at frost 55: +1 for the bucket stamp, offset by smaller blit data; mid-paint 21 → 20).

**Estimated frame time (desk estimate, NOT a board measurement).** Compose: dial copy (C memcpy) + hands (~8 calls) + figure (~20 calls, less blit data than v2's union rects) ≈ 55–65 ms; `show()`: 4 band memcmps (460 KB at C speed) + 2–3 band transfers ≈ 25–35 ms → **≈ 85–95 ms/frame all-in, ~11–12 fps** during a show, against the board-measured 132 ms / 7.5 fps before. `bench_painter.py` prints the real frame avg + figure draw on Mark's next run; that number supersedes this estimate.

**Desk verification.** Same deterministic sim, baseline (frost build) vs this build, at frost 0 **and** 55, four standard poses, union-figure-region method: **zero unexplained diffs** everywhere; standing and dip-hold are pixel-identical (their snap points exist in both grids); mid-wipe / mid-paint differ only inside the figure region (the body sits up to one old snap step closer to its true eased position). At frost 55 — where INK is the hands alone — **hand INK counts are identical in all four poses** (2,269 / 1,787 / 1,234 / 1,773); at frost 0 the small INK deltas (±26 px) are the figure's own paint-coloured features (eyes, mouth, bucket surface) shifting with the body inside the region. Full v2 suite re-passed: IK bone error 0.0000 px over 41,616 targets, `work_ease` stalls exact, rest-pose arm assertions, minute + hour state-machine sequences unchanged, no Canvas drawing primitives in the frame path. All touched modules compile under mpy-cross.

## Addendum — Nov 15, 2026 (smoothness regressions fixed: dirty-band reverted, halo slimmed)

The smoothness pass above was bench-measured the same day (`bench_profile.py`, Mark on the real board) and **two of its three legs regressed**:

| measure | frost build | smoothness build |
|---|---|---|
| `update()` avg (compose) | ≈92 ms | **87 ms** — healthy; the band-limited hands are fine |
| `show()` avg during a show | ≈40 ms | **97 ms** |
| `show()` on an unchanged frame | — | **33 ms** |
| `show(force=True)` (all 4 bands, new path) | ≈40 ms | **146 ms** |
| frame avg / frames per show | 132 ms / 65 | **182 ms / 47** |
| `rect prepare` | (25 rects, unmeasured) | **8,763 ms** (74 rects) |

**The dirty-band lesson (do not retry without a different mechanism).** The design assumed `memoryview == memoryview` reaches a C memcmp for free. In the firmware source it does — but on the board the comparison *itself* costs **33 ms on a frame where nothing changed**: slicing and comparing 460 KB through the memoryview machinery is not free in practice, whatever the C path underneath. Worse, the shadow bookkeeping slow-paths the draw itself: four bands through the new path cost **146 ms against ~40 ms** for the plain frost-build path (~3.5×). Net: `show()` averaged 97 ms while *saving* at most one band per frame. Dirty-band presentation via memoryview compare is a dead end on this firmware.

**Fix 1 — `display.show()` reverted.** `show()` is the frost build's implementation again, restored verbatim (plus a warning comment at the site): four `draw_bitmap` calls from the live canvas, every frame, no shadow canvas, no comparison, no `force=` — all deleted. No runtime caller ever passed `force` (`main.py` / `bench_painter.py` call plain `show()`; only the one-off probe did, and its numbers are the ones in the table above). A new desk regression test pins the behaviour against a fake board: every `show()` — changed frame or not — attempts exactly 4 band draws in order, a failed band returns False with all 4 attempted, headless still returns False and draws nothing.

**Fix 2 — the halo pass slimmed.** The 8,763 ms prepare was the frost halo at 74 rects: the whole figure (details and all) re-drawn at **eight** compass offsets per rect. It now draws at the **four cardinal offsets** and **silhouette-only**: the draw functions take a `sil` flag that skips every interior shape — the overalls bib and straps (wholly inside the shirt quad's outline), the face (inside the head), the bucket's paint surface (inside the rim). The halo is an edge effect; interior shapes never extended it. Prepare's fb-primitive count at frost 55: **14,140 → 5,926 (−58%)**; at frost 0 it is unchanged (1,735 — the halo path is skipped entirely). Expected board prepare ≈ 3–4 s (estimate from the primitive ratio; `bench_painter.py`'s `rect prepare ms` line supersedes it).

**What did NOT change:** the finer snap grid (15 / 13 px steps, 74 rects, 2.08 MB — its halved snap error was real and stays), the band-limited hands (compose actually improved to 87 ms), `Figure.draw()` and its census, and — as ever — the show timings, IK, `work_ease`, and the state machine. Expected frame after the fix: update 87 (measured) + show ≈40 (the frost build's measured path) ≈ **~127 ms**, with the body stepping at half the old snap error; the bench run confirms.

**Desk verification.** Same deterministic sim, this build vs the smoothness build: **frost 0 — pixel-identical, 0 diffs in all four poses** (the sharp path, the cuckoo's source, is untouched — the `sil` flag only affects halo draws, which frost 0 never makes). **Frost 55 — 96–196 diff px per pose, zero unexplained**: every differing pixel lies inside the union figure region *and* within 2 px of a halo-coloured pixel — the halo's edge shape only (four-offset dilation gives up the diagonal corner pixels); hand INK counts identical in all four poses. Suite: IK bone error 0 over 6,321 targets with the reach clamp exact, `work_ease` endpoints/monotonic/both stalls exactly 0.05, `bend_env` plateau, both state-machine sequences (plain minute; hour-step with hour wipe/paint inserted), rest-pose arm assertions (hands at own thighs ±27, elbows bowed out), plus the new `show()` band test above. `display.py` / `figure.py` compile under mpy-cross; `display.py` diffs against the frost build's file only by the warning comment.

## Addendum — Nov 15, 2026 (idle life v1: the between-minutes routines)

The idle build-out §3.5 promised. Ten routines run between minute shows, all driven through figure intent: both hands follow full hang-to-hang waypoint paths (`tip_l` / `tip_r` in figure.py, eased per leg — a hand never teleports), props hang off the hands as draw state (`prop_l` / `prop_r`, `cap_off`, `behind`, `core`, `watch_min`, `mug_home`, `apple_bites`, `hanky_puff`), and every prop draws in figure's veiled palette — they are behind his glass too. The breathing sway is unchanged (it lives in `Figure.update`).

| Routine | Dur (ms) | Weight | Choreography |
|---|---|---|---|
| shoulder roll | 2100 | 4 | The lightest filler: both hands ride one slow roll (±3 px sway, −5 px lift). Deliberately near-still in a single frame; it reads as motion, not pose. |
| wristwatch check | 2500 | 3 | LEFT arm rises bare-handed; the watch on its wrist shows the **painted** time (`watch_min` = the dial's total minutes — his watch agrees with the clock he is painting). Brush arm stays at his side. |
| head scratch | 2000 | 3 | Right hand to the cap's side, three small rubs. |
| mug sip | 3400 | 2 | The enamel mug **lives on the floor by the bucket** (`MUG_HOME` (292, 443), stamped per frame under the body rect). It is out of hanging reach, so he steps toward it (follow rides `tip_r`) and **dips** for it — the proven dip machinery — comes up with it, sips (small contented bob), and dips it back down. |
| cap-off brow wipe | 3000 | 2 | Right hand takes the cap off and holds it at his side; a **hair patch** (two ellipses) covers the baked cap region; the left hand makes two passes across the forehead; cap back on. |
| hanky nose-blow | 3000 | 2 | Hanky to the nose, two blows, two dabs. No buzzer honk. |
| rear-end scratch | 2000 | 2 | The right arm is drawn **before** the body rect (`behind`), so the opaque rect occludes it: the forearm emerges at his far hip and rubs there. |
| apple snack | 4000 | 2 | Apple to the mouth twice; a bite notch (dial-cream punch) appears each time; the core is tossed and arcs off the bottom of the dial. |
| phone call | 5000 | 1 | Phone to his right ear; two nods; one gesture from the free hand mid-call. |
| plane flyby | 5000 | 1 | A small high-wing silhouette crosses the **top** of the dial (~5 s, slight bob) while he shades his eyes with the working hand. Mark's invention from the prototype. |

**Rig limits, stated plainly.** The head is **baked into the body rects — it cannot turn**, and every routine above is choreographed to read without a head turn: the hanky's head-bob is carried by the hanky swelling (`hanky_puff`) and the hand dipping with each blow; the phone's nods are the phone hand bobbing at his ear. The legs are baked too — no walking. **Deferred, not built:** the heel click, the bucket rearrange (the dip rects assume the bucket's side), and the full inspection stroll.

**The plane is OUTSIDE the glass.** It is in the room, in front of the clock, so `figure.draw_plane` draws it from a raw colour (never the veiled palette) and `Show.update` composites it **after the hands** — crisp at any frost strength, where everything of his veils.

**Scheduler rules (as built).** Routines run only between shows. A routine may start only if it **fits**: its duration + a 1 s margin must end before the next minute boundary (whole-second time makes the sub-second part unknowable; the margin absorbs exactly that). The minute show **pre-empts** at the boundary regardless (`start_show` clears the idle and its intent fields). Picks are weighted random (table above), **never the same routine twice in a row**, on a gap clock of 100–220 s after the last routine (first routine 45–90 s after boot) — roughly one every 2–4 minutes, fit retries included; if nothing fits late in a minute, the attempt retries just after the next show. **Sleep hours** (config `sleep_enabled` / `sleep_start` / `sleep_end`, handed to the show by main as minutes of day) suppress random starts entirely; the sleep behaviour itself is still a later phase. Two cadence details from the audit pass: a routine cut short by a show re-arms the gap clock (the next routine is a full gap away, not due again as the show ends), and during sleep hours a past-due gap clock re-arms 30 s at a time. `main.py`'s loop frames while a routine is due or a try-it is queued, so the scheduler is serviced on its own timing rather than only in post-show settle windows.

**Admin Try-it.** The admin page gains a button per routine (`POST /tryit` → `app["tryit"]` → main calls `show.queue_idle()`). A queued routine bypasses the gap clock and the sleep suppression — it is an explicit request — but still respects the fit check and pre-emption: pressed late in a minute, it fires just after the next show.

**Census (desk-counted framebuf calls in `Figure.draw`, frost 55).** Standing rest frame 21 (the floor mug adds ~4 over the frost build's 17–18); worst routine frames: watch 29, cap 29, apple 27 — all ≤ 30, against the board's ~87 ms compose + ~40 ms show; frames stay ≲150 ms by the same arithmetic the bench confirmed for the frost build. `bench_painter.py` does not exercise idles; the board's own frame timing while a routine runs is Mark's to spot-check.

**Desk verification** (`desktest-painter/test_idle.py`, deterministic sim at 40 ms ticks). Every routine: starts from rest on a try-it queue, measured duration within its budget + 2 ticks, visible hand travel (shoulder roll > 4 px by design; the rest > 15 px; the sip's bend exceeds 0.9; the plane crosses), and **returns to the rest pose** (hands within 2 px, intent fully clean — no prop, patch, or core left behind). Scheduler: a 5 s try-it queued with 4 s left in the minute does not start and is not dropped — it fires at second 8 of the next minute, after the boundary show; a routine running at a boundary is pre-empted by the show; 24 consecutive picks contain no repeat and cover all ten routines; sleep hours suppress every random start (wrap-midnight window arithmetic checked) while a try-it still runs. One key frame per routine was desk-rendered at frost 55 and eyeballed (previews/preview_idle_*.png): nine read at a glance. **Flagged:** the rear-end scratch's still is the weakest — in a single frame it reads as his hand at his far hip; the rub and the torso occlusion carry it in motion. The shoulder roll's still is near-identical to rest, as designed.

## Addendum — Nov 15, 2026 (v10: taller figure, the weight rock, idle diagnosability)

Three changes from Mark's first idle-life bench watch: the figure is taller (the hands' centre sat on his face), a weight rock between shows ("at minimum, he needs to rock from one leg to the other as if impatiently waiting"), and an answer to his report that **no idle routines fired** while he watched.

**Taller figure.** Growth is torso + legs + arms; the head art (ellipse, cap, face offsets — the character Mark approved in the frost build) is untouched, and feet and bucket do not move (the floor is where it was). Landmarks, rest pose, y in px:

| Landmark | v9 | v10 | Target |
|---|---|---|---|
| Face centre | 259 | **180** | 175–185 |
| Shoulders | 294 | **225** | ~225 |
| Hips | 365 | **356** | 355–365 |
| Cap top | 237 | 158 | ~130 (see note) |
| Height, cap→boots | 212 | 291 | ~335–345 (see note) |

The pivot (240, 240) now crosses his **upper chest**, 15 px below the shoulder line; the face ellipse spans 157–203, so the hands' boss clears the face entirely. Note on the two missed targets: cap top ~130 and height ~340 are not reachable with a proportionate head — the cap rides 22 px above the face centre in the approved head art, so a 130 cap top would put the face at ~152, contradicting the face target; the brief's numbers were estimates, and face / shoulders / hips / pivot — the substance of Mark's complaint — all land. Constants: `HEAD_H` 187→266, `SHOULDER_H` 152→221, `HIP_H` 81→90 (legs/pelvis in `_draw_torso` now derive from `HIP_H`), arms 48/47→82/78 (reach 95→160, clamp 158), `HANG_DY` 84→152 (hands hang at upper thigh again). Body travel clamps are named (`BODY_RISE` 39, `BODY_SINK` 20 — v9's rise was 52, sink 6): the sink is new travel, and the grids grew a row each to cover it (`STAND_YS` +13, `DIP_YS` +18, `DIP_YS` −26 dropped; counts land back on v9's 65 stand + 9 dip rects). Half-step rock columns (±8) were considered and **not** taken: the cache is already +1 MB (below), and the rock's steps stay one grid step (15 px) with eased timing. `BEND_RAD` 1.02→0.66: the taller torso's longer hip-to-head lever (176 vs 106 px) threw the head past the bucket at 58° and read as a fall; at ~38° the head lands over the bucket and the dip reads as a bend again. The sip's grab follow drops 0.55→0.30 throughout — bent at the waist his shoulder lands ~95 px right of his feet, and stepping hard toward the mug carried the shoulder past it; the moderate follow lets the body sink do the reaching. Routine landmarks that were hardcoded pixels (rear-scratch hip, phone gesture) now derive from `HIP_H` / `SHOULDER_H`. Cost: rect cache 2.18→**3.14 MB** (75 rects — the taller rects are bigger), prepare 5,926→**6,043 prims** (board ≈4.3 s, v9's 4,232 ms + ~2%). Census: worst routine frame 33 fb calls in `Figure.draw` (watch — the longer arm segments span more band windows; same shapes, more splits), rest frame 25.

**Reachability (the invariant, now proven).** `desktest-painter/test_reach.py` settles the real figure on the wipe/paint intent for every angle (60 per hand, both tools) and measures |hand − frontier| from `pose()`. v9 by the same method: minute worst **73.1 px** at the 12 o'clock tip (the design's residual-reach math in §3.3 assumed the unclamped eased shoulder; the drawn body's rise clamp never let it get there), hour worst 20.5 px. v10: minute worst **8.1 px** — only at the 6 o'clock tip, where the frontier sits beside his boots and the fully extended arm lands a brush-width short; hour **0.0 everywhere**; everything at reveal ≤ 0.9 is 0.0. Both dips (show bucket, sip grab) measure 0.0 at full bend. Two IK robustness fixes came with the longer bones: targets inside the bones' difference (|L1−L2| = 4 px — the reachable annulus's inner edge, invisible at v9's 48/47) now land the hand at that distance along the ray instead of sending the cosine rule's `h` imaginary, and **`ik()` takes an elbow hint** — `pose()` tracks each arm's previous elbow and picks the nearer candidate while the arm works, re-seeding from the score at the plain hang. The hint measurably reduces fold flips (phone 8→2, shows 13→10 by the flip counter) and visibly repairs the cap routine's fold. **Known characteristic, documented not fixed:** near the pivot (early paint / late wipe, hand within a few px of the shoulder anchor) the elbow swings widely as the folded arm's geometry rotates — present in every build including the board-approved v9 shows, larger now in proportion to the arms; the HAND never jumps, only the fold churns for the ~1 s the frontier crosses the pivot's neighbourhood. The watch routine's wrist target also moved (head+(−14,+44) → head+(−64,+52)): at ~5 px from the v10 anchor the doubled fold threw the elbow across his chest and buried the watch behind the boss; out at his left the elbow hangs below the wrist and the watch sits visible on the raised forearm.

**The weight rock.** Between shows the standing body target sways on a 4.6 s cycle (`ROCK_CYCLE_MS`): dwell at −15 px (0–.30), eased shift across (.30–.50), dwell at +15 (.50–.80), eased shift back (.80–1) — one snap-grid step each way, crossing centre mid-shift, so the drawn body steps −15 → 0 → +15 → 0 with dwells: a man shifting his weight, not a dance. It is an intent (`sway_x` on the figure's desired shoulder), not a pose: the arms re-hang off the moving shoulders by themselves, and the breathing bob is unchanged underneath. The phase clock lives in `Show._run_idle`'s rest path and advances only while standing — paused during shows (the show clears `sway_x`) and routines, still during sleep hours. Because a standing animation is only visible if frames are composed, **`main.py` now frames continuously while he is awake** (`not show.sleeping_at(total)` joins the gating terms); during sleep hours the loop falls back to the v9 event-driven gating. `Show.sleeping_at(total)` is the shared wrap-aware window test both use. The desk tests pin the rock off (`Show.rock_on = False`) where a still rest pose is asserted; the board rocks.

**Idle diagnosability + the loop-level verdict.** The admin status block gains an **Idle line** (`Show.idle_status(now_ms)`, wrap-safe countdown): `Idle: <name> running` / `Idle: last <name> at HH:MM, next in ~Ns` / `Idle: suppressed (sleep hours)` (plus `none yet` before the first and `try-it queued: <name>` when one is). And the integration gap is closed: `desktest-painter/test_loop.py` replays main.py's actual compose gating (its terms pinned to main.py's source by assertion) with the real Show/Figure over 10 simulated minutes — **9 shows, 4 routines (68 s, 233 s, 381 s, 575 s), the rock visiting all three steps, sway 0 during every show**. The same sim under the **v9 gating fires the same 4 routines**: the shipped scheduler was never the problem on the desk. Mark's empty minutes are therefore not reproducible from the code — the board was most likely still executing the pre-idle build from RAM (files uploaded to flash do not change a running program until a cold boot), or the watch window simply fell between routines 2–4 minutes apart. The Idle line makes any recurrence diagnosable at a glance, and the v10 bench notes make the cold boot unmissable.

**Desk verification (all deterministic).** `test_suite.py` (IK annulus exact over 6,321 targets incl. the inner edge, work_ease, bend_env, both state machines, rest-pose arm assertions), `test_show_bands.py` (show() regression), `test_idle.py` (all routines under the new landmarks — durations, travel, return-to-rest; the settle window is success-based up to ~3 s because the taller figure's post-dip shoulder ease legitimately takes ~1.5 s to straighten — a man standing back up, not a snap), `test_reach.py` (landmarks + sweep + both dips), `test_loop.py` (above). Previews re-rendered at frost 55 and eyeballed (previews/preview_pose_*.png, preview_idle_*.png, preview_1010.png — the 10:10 frame: boss on the upper chest, face clear — and preview_rock*.png): standing, wipe, dip (a bend again, brush in the bucket), paint, watch (watch visible on the raised forearm), cap (forearm across the brow, hair showing), sip, apple, phone, plane all read. mpy-cross clean on figure.py, show.py, main.py, admin.py.

## Addendum — Nov 15, 2026 (v11: the date on the dial, and the show_date switch)

**The requirement (Mark, Nov 15).** Every face shows the date — day and month — and the admin page gets a selector to turn it off. Only the painter exists, so it is built there, in the shared way the future faces inherit: the face-module contract (clockface.py header) now includes a **date convention** — main.py hands each face the setting via `set_show_date(on)` at boot and on every settings change, and the face honours it in `compose()`. Classic/digital will implement the same two pieces when they land (FACES.md holds the per-face placement notes).

**What the painter draws.** `clockface.date_string()` — **"Sun 15 Nov"**: weekday abbreviation, unpadded day of month, month abbreviation. The weekday is *computed* from the date fields with Sakamoto's algorithm — the same computation timekeep.py keeps the RTC's weekday register honest with — never read off the tuple's own weekday slot, so the printed weekday cannot disagree with the printed date. `draw_date()` centres the string at **DATE_Y = 104** (glyph rows 104–111) in the dial's INK, through the band windows like every other primitive, band-limited the draw_hand way (the glyphs live entirely in the top band: one `text()` call per frame). Placement: open cream, clear of the rim ticks (inner edge y 35 at the top) and of his cap even at the body's maximum rise (cap top 158 − 39 = 119). Glyphs are the firmware framebuf's built-in 8×8 font — the only text the firmware offers; at this size it reads as a quiet maker's line on the dial, which suits the tick-only face. A hand (or his raised arm) sweeping across it briefly is normal — it is painted on the glass, like the hands.

**Mechanism: per frame, not the static layer.** compose() draws the date every frame between the dial copy and the hands. The alternatives were weighed: baking it into the dial layer would need a static re-render at midnight and on every toggle (plus a figure re-prepare if the bake order ever changed), and any stale bake is a ghost risk. Per-frame costs one band-limited text call, and the invariants fall out for free: the date is read off the live time tuple each frame (midnight rollover with no reboot and no day-change bookkeeping in main), toggling is just the flag (frames are rebuilt whole from the dial copy, so off leaves **no ghost pixels** — desk-proven byte-exact), and the figure/hands are untouched (date-off renders are byte-identical to the v10 pose renders; date-on diffs are confined to the glyph box in all four standard poses).

**Frost: the date is NOT veiled.** figure.py's veil is for the man *behind* the glass; the date is painted *on* the glass with the hands, so it stays crisp at any frost strength — desk-proven: the glyph box is byte-identical at frost 0 and frost 55.

**Admin + config.** `show_date` joins DEFAULT_CONFIG (default **True**). The settings form gains a **Show date** on/off selector right under the Face selector; the POST handler validates it like the face. main.py applies it live through the existing changed path (`_apply_date()` at boot, on face change, and on a date-only change, which just flips the flag and forces a repaint) — no reboot, and no manifest change: `update_files.txt` already lists clockface.py, and no module was added.

**Desk verification (all deterministic).** New `desktest-painter/test_date.py`: the string exact over **800 consecutive days** (leap February 2028, month/year boundaries, single-digit days, every weekday) with the tuple's weekday field deliberately wrong; the four standard poses at frost 55 — date off byte-identical to the v10 renders, date on confined to the glyph box (200, 104)–(280, 112); on→off ghost check byte-exact; frost invariance of the glyph box; **midnight rollover driven through the real Show.update** — the frame composed at 00:00:30 after living through midnight carries a date box pixel-exact against the "Sun 15 Nov" reference rendering (and the 23:59:30 frame equals a fresh boot byte for byte); admin/main wiring pinned by source assertions. The desk framebuf stub gained a faithful `text()` port (framebuf_text over font_petme128_8x8, extracted from the firmware tree) to make the pixel tests honest. All prior suites still pass (test_suite, test_show_bands, test_idle, test_reach, test_loop). Previews at frost 55 with the date on, eyeballed: previews/preview_date_standing.png, previews/preview_date_1010.png — the line sits centred in the open cream above his cap and reads as part of the clock. mpy-cross clean on clockface.py, admin.py, main.py.

**Flagged, out of scope (found by the rollover test):** the show machine's forward-only minute totals wrap at midnight — `total` goes 1439 → 0, which is not `> last_total`, so no show fires at 00:00 and, totals never again exceeding the evening's `last_total`, **no show would fire again until a reboot**: after its first midnight the clock's hands would stay at 23:59 (the date, drawn per frame, still rolls over correctly). Desk-proven both ways (23:58/23:59 shows fire; nothing from 00:00 on). This is pre-v11 behaviour in show.py/main.py's total accounting, untouched by this build; it wants its own fix (a day-extended total or a wrap-aware comparison) with its own verification.

## Addendum — Nov 15, 2026 (v12: the midnight fix — day-extended totals)

**The bug (flagged in the v11 addendum, desk-proven there).** `Show.tick` is forward-only on minute-of-day totals: a show fires when `total > last_total`. At midnight the total wraps 1439 → 0 — not greater — and no later total ever exceeds the evening's `last_total`, so after the clock's first midnight **no show would ever fire again until a reboot**: the hands stay at 23:59 while the rest of the clock (the per-frame date, admin) keeps living.

**The fix (show.py only; main.py untouched).** `update()` now builds a **day-extended total** — `_days_from_civil(y, m, d) * 1440 + minute-of-day` (Hinnant's algorithm, pure arithmetic; show.py stays clock-free) — and the show accounting (`last_total`, `start_show`, `demo()`) runs on it. Within a day the extension is a constant, so every existing behaviour is unchanged; across midnight the total steps +1 like any other minute. The epoch is fixed (1970-01-01), so the extension is consistent within a run whatever date the RTC/NTP hands the first frame. `Show._total` stays **minute-of-day** (`total % 1440` in tick): the sleep window, the watch routine and the idle status clock all read time-of-day. clockface's angle functions are exact on extended totals — 1440 is a whole number of hour steps (`minute_angle` mods by 60; `hour_angle_stepped` by 12-minute steps) — desk-verified identical to the minute-of-day equivalents over full days.

**Semantics preserved.** Forward-only still guards rewinds: an NTP backward step lowers the extended total, so already-shown minutes never re-fire and shows resume at the next new minute; a forward jump produces exactly one catch-up show, as before; `demo()`'s +1 accounting is in the same extended units; the idle scheduler's `_sec` (seconds within the minute) is untouched.

**Invariant (new, standing): totals inside Show are monotonic within a run.** Anything that stores or compares minute totals uses day-extended totals; minute-of-day is for sleep/display only.

**Desk verification (deterministic).** New `desktest-painter/test_rollover.py` + `test_rollover_48h.py`: days-from-civil exact against `datetime` over boundary dates (leap February 2028, the year turn); angle equivalence over full days; shows at **23:58, 23:59, 00:00, 00:01** with hands ending at 00:01; a **48-hour run** through the real `Show.update` (Sat 12:00 → Mon 12:00, 5 s frames) — one show at **every one of the 2,880 minute boundaries, both midnights included**, hands ending at Mon 12:00; an NTP backward step of 3 minutes mid-evening (nothing re-fires; shows resume at the next new minute); a forward jump of 3 minutes (exactly one catch-up show); `demo()` on demand, refused while running, its minute not re-shown when real time arrives. `test_date.py` §6 updated to the fixed behaviour: its after-midnight reference now expects the 00:00 hands (it previously encoded the frozen 23:59 hands as out-of-scope) — the date assertions are unchanged. All prior suites pass (test_suite, test_show_bands, test_idle, test_reach, test_loop, test_date). mpy-cross clean on show.py — the only module this build touches.

## Addendum — Nov 15, 2026 (v13: proportions rebalance, idle cadence)

**Mark's notes on the v10 glass** (the height itself approved): "the proportions are off. The legs need to be taller and the torso shorter. Similarly the arms need to be shortened to a more appropriate length." Plus: the idle routines should fire more often.

**Proportions — same overall height, rebalanced inside it.** Cap top 158, face centre 180, shoulders 225, feet and bucket unmoved, height 291 px, the pivot still on his upper chest. What moved: `HIP_H` 90→**116** — hips y 356→**330**, torso 131→**105 px**, legs 90→**116 px** (the `_draw_torso` leg quads and pelvis ride on `HIP_H`, and the bend pivot IS `HIP_H`, so art and rig move together; the dip's knee brace already derived from it). Arms 82/78→**74/72** (reach 160→**146**, clamp 144), `HANG_DY` 152→**135** — the hanging hands land at **mid-thigh** (y ≈ 360: hips 330, knees ≈ 390) at ~94% extension, a soft elbow. `BEND_RAD` stays 0.66 (the hip-to-head lever is 150 px now; both floor grabs re-prove at 0.0 and the head lands where v10's dip put it). Idle landmarks needed no edits: the routines already anchor off the live pose (`_anchors()`), `HIP_H` (rear scratch) and `SHOULDER_H` (phone gesture).

**The reach trade, stated plainly.** Truly natural arms (reach ~114–125) were swept first, by the v10 method, and **cannot hold the frontier invariant**: the 6 o'clock minute frontier sits ~153 px from the best drawn shoulder, and the wall is the sink clamp, not the follow — below `BODY_SINK` +26 the boots leave the dial. At reach 114 the bottom arc measures **41.2 px** short, the bucket dip 12.0 and the sip grab 30.2. So the build ships the **shortest arms that hold the proof**: 74/72 with `BODY_SINK` 20→**26** (the last 6 px of low reach come from the crouch, not from bone; at full sink the boot soles just cross the cream's edge into the shade ring, transiently, on the lowest strokes). Both snap grids gain the +26 row (`STAND_YS` 65→**78** rects, `DIP_YS` 9→**12**). Proven numbers (test_reach, v10 method): minute worst **9.2 px** — the bottom arc at 168–180°, full reveal only; hour **0.0 everywhere**; everything at reveal ≤ 0.9 is 0.0; the 12-o'clock mid-paint capture has the hand **exactly on** the frontier (hand (240,158) = tip (240,158) at reveal 0.5); show dip brush-to-bucket **0.0**, sip grab **0.0** at full bend.

**Idle cadence.** `IDLE_EVERY_MIN/RAND` 100 s + 0–120 s → **35 s + 0–40 s** (35–75 s — roughly one routine a minute). First routine after boot unchanged (45–90 s); fit-before-boundary, no-repeat, sleep suppression, try-it and the pre-emption re-arm all unchanged (they read the same constants). The loop sim now fires **9 routines in 10 minutes, max gap 77 s**, interleaved with 9 shows and no collisions; test_loop pins the cadence (≥ 6 routines, max gap ≤ 100 s).

**Cost.** prepare() 6,043→**7,449 prims** (board ≈ 5.3 s by v10's prim-to-ms ratio — the two +26 grid rows), rect cache 3.14→**3.62 MB** (91 rects incl. the shared bucket). Census: worst routine frame **33 fb calls** (watch — unchanged), standing rest frame 27 (was 25).

**Desk verification (all deterministic).** Full suite green: `test_suite.py` (state machines, rest-pose arms), `test_show_bands.py`, `test_idle.py` (all ten routines under the new landmarks — durations in budget, travel, exact return-to-rest; scheduler rules incl. the re-arm reading the new constants), `test_reach.py` (updated: hips band 325–335, minute full-reveal limit tightened 12→**10 px**), `test_loop.py` (cadence assertions added, above), `test_date.py` (**re-baselined**: its stored baseline encodes the figure, so the v10 frames were replaced by the v13 figure's date-off renders — `desktest-painter/v13base/`, made by `make_v13base.py`; every date assertion is unchanged in substance and passes), `test_rollover.py` + `test_rollover_48h.py` (midnight behaviour untouched). Previews at frost 55, eyeballed: standing (longer legs, shorter torso, hands at mid-thigh — the rebalance reads), dip hold (a waist bend, brush in the bucket, free hand braced on the thigh), the 12-o'clock mid-paint, watch (watch visible on the raised forearm, elbow below the wrist). mpy-cross clean on figure.py and show.py — the only modules this build touches.
