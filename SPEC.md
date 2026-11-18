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

## Addendum — Nov 15, 2026 (v14: rock de-rhythmed, date scaled, arm re-split)

Three refinements from Mark's time with the v13 build on glass: the rock is "way too rhythmic", the date is "way too small to read", and "for proportion purposes, the forearms should be longer than the upper arms".

**Rock — random dwells.** The fixed 4.6 s phase clock (`ROCK_CYCLE_MS`, `_rock_t`) is gone. `Show` now runs a two-phase machine (`_rock_side` / `_rock_shift` / `_rock_left`): dwell on a side for a span drawn fresh each time, uniform in **[3.0, 9.0] s** (`ROCK_DWELL_MIN` 3000 + `ROCK_DWELL_RAND` 6000), then the shift — v10's ease and duration kept exactly (`ROCK_SHIFT_MS` 920 = 0.20 of the old cycle), ±15 px as ever. Pauses during shows/routines/sleep unchanged (the machine advances only in the standing branch of `_run_idle`). Desk evidence (`probe_rock_v14.py`, scheduler disarmed to isolate the machine): **67 dwells in 8 standing minutes, every one in [3.0, 9.0] s, 27 distinct values**, shifts 800–1000 ms at a 200 ms tick. (The probe's first cut measured wall-clock and reported dwells to 11.7 s — routines freezing the machine mid-phase, which is the pause working as designed, not a dwell.) `test_loop`'s rock assertions (visits −15/0/+15, sway 0 during shows) are unchanged and green.

**Date — 3x.** `clockface` grows every glyph pixel of the built-in 8x8 font to a 3×3 square: `DATE_SCALE` 3, glyph box **24 px tall** (`DATE_H`), 24 px per char (`DATE_CW`), `DATE_Y` 104→**88** — the box (rows 88..111) still sits in open cream, clear of the tick inner edge (y 35) and of his cap at maximum rise (119). Rendering: the string is drawn once at 1x into a small scratch FrameBuffer and grown into a cached **opaque strip** whose ground is CREAM (pixel-exact: the box's farthest corner is ~194 px from centre, inside the 233 cream disc), copied into the frame as 24 row slices per frame and rebuilt only when the string changes. Still per-frame, still dial ink unveiled by frost, still live under the `show_date` toggle with no ghost. `test_date` adaptations: its bbox now derives from `DATE_CW`/`DATE_H`, and its stored baseline was re-based (`v14base/`, `make_v14base.py`) because the baseline encodes the figure and the arm re-split moved it — the same adaptation v13 made; every date assertion is unchanged in substance and passes, midnight rollover pixel-exact at the new size.

**Arm re-split — forearm longer.** `ARM_L1`/`ARM_L2` 74/72 → **64/82**: the rig's second bone ends at the hand holding the tool, and elbow-to-fingertips runs ~25–40% longer than shoulder-to-elbow in the artist canons (bone-for-bone the radius alone is ~74% of the humerus); 82/64 = +28%. Total reach 146 and the 144 clamp are unchanged — only the elbow moves. Hanging hands still land at mid-thigh (y ≈ 360). The split exposed a real flaw: `ARM_MIN_D` went 2→**18**, and the body-follow happily parked the shoulder on near frontiers (mid-stroke targets at 9–10 o'clock sit ~2 px from the followed shoulder), where `ik()`'s inner clamp pushed the hand out to 18 px along the ray — a **15.9 px overshoot** past the paint frontier at reveal 0.5. Fix in `figure.update()`: the desired body is floored so the predicted drawn anchor stays at least `ARM_FLOOR_D` (**30** = 18 + the rect grid's snap margin) from the working target — the body keeps its distance instead of the hand overshooting. The reach proof then restores v13's numbers **exactly**: minute worst **9.2 px** (bottom arc 168–180°, full reveal only), **0.0** at reveals 0.9/0.5, hour **0.0 everywhere**, dip brush-to-bucket **0.0**, sip grab **0.0**; the 12-o'clock capture again has the hand exactly on the tip (240,158) at reveal 0.5.

**Cost.** Nothing: prepare is unchanged (7,449 prims; rect cache 3.62 MB / 91 rects — the arms are not in the rect cache and no grid moved), and the census is unchanged (worst routine frame **33** fb calls, watch; standing rest 27).

**Desk verification (all deterministic).** Full suite green: `test_suite.py`, `test_show_bands.py`, `test_idle.py` (all ten routines under the new split — durations in budget, exact return-to-rest), `test_reach.py` (proof above), `test_loop.py` (cadence + rock invariants), `test_date.py` (re-based, above), `test_rollover.py` + `test_rollover_48h.py` (2,880 shows, both midnights — untouched), plus the rock probe. mpy-cross (v1.29.0) clean on figure.py, show.py, clockface.py — the only modules this build touches; main.py untouched. Previews at frost 55, eyeballed: standing (the longer forearm run reads on the hanging arms, hands at mid-thigh; the 3x date is bold and clear of tick and cap, and still legible downscaled to ~120 px), the 12-o'clock mid-paint (hand dead on the frontier), watch (watch visible on the raised forearm, elbow below the wrist).

## Addendum — Nov 15, 2026 (v15: sleep mode — the lights-out scene)

**The gap.** The sleep *settings* shipped with the working clock (admin: `sleep_enabled` / `sleep_start` / `sleep_end`, defaults 22:00–06:00) and the idle life already quieted in the window — but the sleep *behaviour* was never built. Mark turned sleep on in admin on Nov 15 and nothing changed. This build is the scene the Nov 13 addendum designed: in the window the room goes dark and he lies down; the hands keep time in pale ink.

**The scene.** A second, lazy static layer: `display.night_dial()` (a full 480×480 canvas, **460,800 B, allocated only on the first sleep frame**) carries `clockface.render_night()` — the dial redrawn in the night palette: ground `NIGHT_GROUND` rgb565(10,13,26) (deep blue-black), shade ring `NIGHT_SHADE` (19,24,42), rim `NIGHT_RIM` (3,4,8), ticks faint in `NIGHT_TICK` (54,66,100). The day dial and the figure's rect cache are never touched by the night, so the wake is instant and the day baselines stay byte-safe. Frost does **not** veil the night scene — the lying figure is drawn in its raw palette, like the cuckoo's sharp face. On it he **lies along the bottom of the dial**, a new baked pose in the rect-compositing discipline (`figure.prepare_sleep()`, extent-measured and baked exactly like `prepare()`): head on a pillow at the left (head centre (170,396), skin `SLP_SKIN` (186,148,124) — a touch deeper than the day skin, hair over the top of the turned head, one closed eye and a small mouth), **cap OFF** — the cap sits on the floor beside the pillow (dome at (94,432), brim toward the pillow), neck and a shirt shoulder, then the body horizontal under a rust blanket (`BLANKET` (166,74,44), shaded `BLANKET_DK` (120,51,31)) with his **boots sticking out at the far end** (toes at (405,418) and (407,431)).

**Per-frame life (kept cheap).** Two draws over the baked scene. *Breathing:* a blanket-coloured swell ellipse on the blanket's top edge, centre (258, 404 − b), ry 9 + 3b, where b is a 4 s raised-cosine cycle (`BREATH_MS` 4000) — only the silhouette moves, ~3 px, no seam. *Zzz:* three Z's on a 4.8 s cycle (`ZZZ_CYCLE_MS` 4800, staggered 1,600 ms), each rising 60 px and drifting right from above his head, growing 8→16→24 px (the built-in font at scales 1–3, offsets cached once) and fading down the night palette — `PALE` → (148,152,166) → (78,86,116) — drawn per frame like the date.

**Timekeeping while asleep.** `Show.tick()` gains a sleep path. At each minute boundary the hands **snap**: both hands are set to the boundary total's angles with reveal 1.0 (`_snap_hands()` — the same helper the first-frame branch uses), the hour hand keeping its stepped behaviour, drawn in **pale ink #e9e2cf** (`PALE` rgb565(233,226,207)); the date, when `show_date` is on, renders pale on the night ground (the date strip cache is keyed (string, colour, ground), so the day and night strips coexist and neither ghosts the other). No shows, no idle routines — sleep owns the display. A try-it queued in-window is **deferred**, not dropped: it stays queued and fires at the first gap after the wake. (That reverses v9's documented try-it bypass of the sleep suppression — the one existing-test adaptation this build makes, in `test_idle.py`, stated here plainly.) The idle due-time re-arm (+30 s, so main's loop is not held awake by a due routine) moved from `update()` into tick's sleep path, where it now also covers the snap bookkeeping. The v12 invariant carries the night: totals are day-extended, so midnight inside the window is an ordinary +1 step — 00:00 snaps to 0°/0° and the date rolls, no reboot. `demo()` refuses while asleep.

**Transitions (kept simple).** Entering — window start, enabling mid-window, or a cold boot inside the window — cancels any running show or routine, parks him at rest intent, snaps the hands, and the next composed frame is the night scene. Exiting — window end or disabling mid-window — just falls through to the normal flow: the day palette is already intact underneath, and the wake boundary runs a normal show. No wake-up routine. Sleep is a painter-face behaviour (the night render lives in clockface, the lying pose in figure, the window logic in Show); the future classic/digital faces are untouched by it.

**Loop cadence.** main.py's gating gains one term: while `sleeping_at`, compose when ~1 s has passed since the last sleep frame (`SLEEP_FRAME_MS` 1000) — the rhythm the breathing and Z cycles are drawn for, and the minute snap lands within a second of the boundary. All existing gating terms are unchanged (test_loop's source pins still pass), and housekeeping stays idle-only.

**Cost.** Night canvas 460,800 B (lazy, once); night dial render **252 prims** (once); sleep bake **19 prims**, sleep rect **49,824 B**; a sleep frame's census is **11 fb calls** — the cheapest frame the clock draws (standing rest 27, worst routine 33). Day prepare (7,449 prims / 3.62 MB) and every day census are unchanged.

**Desk verification (all deterministic).** New `desktest-painter/test_sleep.py`: **A** enter at 22:00 (the 21:58/21:59 shows are the last; night ground, faint tick, pale boss/tip/date, pillow/head/blanket/boots/cap pixels, Z's present, day layer + rect cache untouched); **B** the whole night by tick — **480 minute snaps, correct angles at every minute**, no show or routine, midnight composing "Mon 16 Nov" in pale with hands at 0°; **C** exit at 06:00 — the wake boundary runs a normal show, 06:01 another, day scene restored; **D** try-it deferred + the Idle line reads `suppressed (sleep hours)`; **F** a non-wrapping 13:00–14:00 window enters/snaps/exits; **G** mid-window enable/disable at the next frame, boot-in-window wakes asleep; **E** `sleep_enabled` off — the same evening behaves exactly as before v15 (22:00 show fires, day scene); **H** **48 h with sleep on**: a show at every awake boundary (**1,920**), a snap at every sleep boundary (**960**, both midnights snapped to 00:00), nothing fires in-window; **I** the costs above + aliveness (breath and Z regions move between phases; same-ms frames byte-identical). Full suite green: test_suite, test_show_bands, test_idle (the try-it adaptation above; the re-arm section passes unchanged), test_reach, test_loop, test_date, test_rollover, test_rollover_48h. mpy-cross (v1.29.0) clean on display.py, clockface.py, figure.py, show.py, main.py, admin.py.

**Previews, eyeballed** (`previews/preview_sleep.png`, `preview_wake.png`): the sleep frame at 23:47 reads — dark room, pale date and hands, the horizontal figure on its pillow under the rust blanket, boots out, Z's rising. The cap on the floor needed one iteration: first cut it sat half under the pillow's tip and read as a dark blob; moved clear and given a taller dome and longer brim, it reads as its own small silhouette on the floor line. The wake frame is the ordinary standing rest under the new day's date. **Bench note (as ever): cold boot — cable out a full 10 s. Do NOT use admin Restart; the warm-reboot dark-panel bug is still open and a chip-only reset would bring the clock up dark.**

## Addendum — Nov 16, 2026 (v16: the setup portal actually serves)

**The bug (hardware, Nov 15).** When the board fell back to the `PainterClock-Setup` AP — on Nov 15 via the failed join to the mis-spelled SSID — a phone could join the AP, but http://192.168.4.1 served nothing: no page, no captive pop-up. Rehoming was dead. The code that failed is byte-identical to what shipped in the initial push (prov.py has had one implementation since daa4256), so the audit below is of exactly the failing code.

**Root cause — stated with its confidence.** No single line is provable from the desk; what the audit proves is that the v1–v15 serve core had three independent defects, each capable of producing part or all of the observed shape, and that the core was a from-scratch rewrite of a pattern that had already been proven on two other boards — diverging from it in exactly the load-bearing places.

1. **The DNS reply was malformed for real phone queries — PROVEN from the code.** The old reply mutated the query buffer (flip flags, set ANCOUNT=1, append an A record). Phones send DNS with an EDNS OPT record in the additional section (ARCOUNT=1); the mutated packet keeps the OPT bytes in place, so the appended A record lands in the ADDITIONAL section and the ANSWER section's first record is the phone's own OPT (type 41). `desktest-painter/test_portal.py` demonstrates it with a strict parser: on a `connectivitycheck.gstatic.com` query with EDNS, the old construction's answer[0] parses as type 41; the new builder's parses as A 192.168.4.1 with exact counts. A strict resolver drops the malformed reply, the phone's captive-portal detection stalls, and Android in particular may abandon a "no internet" AP — from the user's seat, the setup page never appears. The old code also answered AAAA questions with a bare A record glued to whatever question was asked.
2. **The serve setup was unguarded — the AP can outlive the server.** Between the "AP up" print and the serve loop sat an unguarded DNS bind, HTTP bind/listen, STA re-activation and a scan. Any exception there kills main.py with a console traceback — while the AP and its DHCP, being driver-level, stay up. The phone joins a live AP with no user code behind it: the observed shape exactly. Whether this is what fired on Nov 15 is unprovable (nobody captured the console), but the architecture guaranteed the failure mode was silent and total.
3. **The portal was entered from a failed join without disconnecting the STA.** metar-micro's field note (learned on LS Lite Micro, Nov 5) is explicit: a radio still retrying a failed join scans empty and serves badly. The painter port never disconnected — and the Nov 15 observation was precisely a failed-join entry, with the radio still hammering a non-existent SSID while the portal tried to scan and serve. Compounding it, the serve loop itself was a `settimeout(0.2)` round-robin (DNS pump, then HTTP pump) instead of the proven `uselect.poll` over non-blocking sockets — the one structural element never hardware-tested anywhere.

**The fix (prov.py only; main.py untouched).** The serve core is now metar-micro's hardware-proven pattern, in painter dress: `sta.disconnect()` first; scan (up to 3 attempts) *before* the AP; AP up with guarded config; DNS and HTTP sockets **non-blocking**, multiplexed by `uselect.poll(250)`; the DNS reply **built** (header + echoed question + one A record, all other counts zero, malformed queries dropped); the HTTP reader loops to the end of the headers and honours Content-Length for the body; responses carry Content-Length with Connection: close; any path other than `/`, `/rescan`, `/save` gets a **302 to http://192.168.4.1/** (where the phones' connectivity probes land); a bad POST re-serves the form with the error instead of a bare 400. Portal mode is dedicated: setup runs in staged steps, each printing its line, and a setup failure prints `prov: portal setup FAILED (attempt N)` and retries in place — the portal never silently falls through, and the serve loop's per-request work is guarded so one bad request cannot kill it. Unchanged contracts: BOOT-hold and no-creds/failed-join entry, writes ONLY `wifi_cfg.py`, `config.json` untouched, normal boot byte-for-byte the same (main.py not modified).

**Diagnostics map (what the bench console shows, in order).** `prov: setup portal starting` → `prov: scan found N network(s)` → `prov: AP up: PainterClock-Setup (192.168.4.1, ...)` → `prov: DNS catch-all listening on port 53` → `prov: HTTP listening on port 80 - join 'PainterClock-Setup' and open http://192.168.4.1/` → per query (first five) `prov dns: <name> -> 192.168.4.1` → per request `prov http: GET /` / `prov http: POST /save` → every 15 s `prov: portal alive - N dns, M http, up T s` → on save `prov: saved Wi-Fi for <ssid>` then `prov: saved - rebooting now`. A stage that never prints is the stage that is broken; the heartbeat distinguishes "loop alive, no phone traffic" from "loop dead".

**Desk verification.** New `desktest-painter/test_portal.py` (stub machine/network/socket/uselect/time at the MicroPython surface): the old-vs-new DNS demonstration above; `dns_reply` on plain + AAAA queries answered, garbage and zero-question queries dropped; `run_portal()` walked end to end — disconnect called, AP configured, both binds on 0.0.0.0 (53/80), GET / served with headers split across chunks (form contains the picker, all three fields, and the scanned SSIDs), GET /generate_204 → 302 to the portal root, bad POST re-serves the form and writes nothing, 70 idle polls produce the heartbeat line, good POST with the body split across chunks writes ONLY wifi_cfg.py (manual field wins, url-decoded) and reboots via the stubbed reset; `load_creds` round-trips the saved pair. Full desk suite green: test_suite, test_show_bands, test_idle, test_reach, test_loop, test_date, test_rollover, test_rollover_48h (2,880 shows, both midnights), test_sleep — all unchanged, as expected: nothing but prov.py moved. mpy-cross (v1.29.0) clean on prov.py. **Still bench-only, as ever: the portal round-trip on the real board** — the bench protocol in the v16 delivery walks Mark through it, and his console read-back closes this item.

## Addendum — Nov 16, 2026 (v17: warm-reboot recovery — the panel comes back by itself)

**The bug (board-proven, Nov 15).** The panel keeps power across a chip-only reset. On the next boot `Board.begin()` returns False — the panel was already begun by the previous run — and the clock runs dark/headless until ~10 s fully unplugged resets the panel. This stranded the clock after every admin Restart and every updater post-update reboot: both reboot the chip only. The standing bench instruction ("cold boot — cable out a full 10 s; do NOT use admin Restart") was the workaround, not a fix.

**Lever inventory (what the binding actually exposes).** From `firmware/API_NOTES.md` and the binding source: `Board()` / `init()` / `begin()` / `deinit()` / `color_bar_test()`, plus the project's own `draw_bitmap()` / `frame_buffer_addr()` / `set_backlight()`. That is all. There is **no** reset call, no LCD object, no expander handle, and no panel-power control reachable from Python. The board config confirms there is nothing to pulse even in principle: `ESP_PANEL_BOARD_LCD_RST_IO` is **-1** (this board wires no LCD reset line; the ST7701 is reset by its power-on circuit), the backlight is plain PWM on GPIO6, and the TCA9554 expander carries only the ST7701's 3-wire-SPI chip-select — poking it from Python via SoftI2C while the driver owns I2C host 0 would risk corrupting the panel's own init channel, so the expander is deliberately **not** touched. Drawing without a successful `begin()` has no basis in the API notes (the driver's frame buffer exists only after begin; `frame_buffer_addr()` returns 0 before it) and was not attempted.

**The fix (display.py only).** `init()` keeps the cold-boot sequence byte-for-byte — `Board()` → `init()` → `begin()` → `set_backlight()` → live print, factored unchanged into `_try_bring_up()` — and only when that first bring-up fails does `_recover()` run, trying the binding's own teardown cycles, cheapest first, each guarded and named on the console:

1. `deinit()` + `init()` + `begin()` on the same object — unwinds whatever the failed `begin()` half-started (a sub-driver begun then abandoned is the most plausible warm-boot wedge).
2. A brand-new `Board()` object — drops any wedged C++ board state wholesale.
3. A fresh object cycled twice (`init`, `deinit`, `init`, `begin`) — a second teardown pass for a panel/driver left mid-init.

Bounded and fail-safe: exactly those three attempts (4 `begin()` calls total worst case, two 100 ms settles), then recovery prints `display: recovery exhausted` and `init()` returns False — the clock runs headless exactly as it did before v17. Recovery failure cannot wedge the chip or loop; boot order is unchanged (display still first); RTC/Wi-Fi paths untouched. The one residual risk is inherent: `deinit()` after a failed `begin()` is the library's own teardown API (Espressif's examples use it exactly this way), but it has never run on this board — if it misbehaved, the failure shape is the same dark panel as today, never worse.

**Confidence per lever — honest.** Lever 1 (deinit cycle): *moderate* — it is the only lever that directly addresses "previous run left driver state behind," and it is the standard recovery idiom for this library. Lever 2 (fresh object): *low-moderate* — helps if the wedge lives in the C++ board object rather than the hardware. Lever 3 (double cycle): *low* — cheap insurance, same mechanism as 1 with an extra pass. If the wedge is purely in the panel silicon (ST7701 left in a state only power-on-reset clears), none of the three can work and the 10-second unplug remains the cure — the bench test is what settles which world we're in.

**Desk verification.** New `desktest-painter/test_display_recovery.py` (scripted fake `esp_panel` Board): cold boot succeeds with the exact pre-v17 call sequence and no recovery attempted; warm boot saved by recovery 1 (call trace `init, begin, deinit, init, begin`) and by recovery 2 (fresh object); `begin()` raising instead of returning False still recovers; total failure makes exactly 4 bounded `begin()` attempts, returns False, and `show()` stays safely headless; no-driver firmware unchanged. Desk suite in this run: test_suite, test_show_bands, test_idle, test_reach, test_loop, test_date green; the rollover/sleep sims were still running on the throttled build cell at push time — they exercise display only via the no-driver init path (no `esp_panel` exists on the desk path, so `init()` takes the preserved ImportError branch) and Canvas code this change does not touch, and test_portal does not import display at all. mpy-cross (v1.29.0) clean on display.py. **Bench-only, as ever:** upload display.py, cold boot (face lit), then admin Restart and watch whether the face returns by itself — the console's `display: recovery N/3 worked` line names the lever that did it.

## Addendum — Nov 16, 2026 (v18: backlight — painted light behind the man)

**The ask (Mark, on the v17 glass).** "Does the system allow for playing with lighting? I'm wondering if the man could be back lit a bit, similar to the real clock?" The Schiphol clock's case is lit from within; the man is a presence behind glowing glass. v18 paints that light in software — no hardware change: the panel's own backlight stays the plain brightness control it already was. Built the way Frost went in: one admin slider, tuned live by eye.

**Design — two halves, one slider.** Config key `backlight`, 0..100, **default 50**, in admin's form directly under Frost, parsed and clamped exactly like it. main.py applies it live on save (`_apply_backlight` to the face + `figure.prepare(dial, frost, backlight)`), no reboot: the dial re-renders with the new glow and the rects re-bake over it — a one-time seconds-scale cost on the change, **zero per-frame cost** (frames copy the finished layers, as ever).

1. **The glow (clockface).** A warm pool baked into the DAY dial: centre (240, 290) — behind his torso — radius 180, warm target (255, 234, 192), peak mix 0.85 at strength 100. The geometry is *contained*: the farthest glow point is 230 px from the dial centre, inside DIAL_R (233), so the glow can never tint the shade ring or rim; the date box's nearest pixel sits at falloff ~0.0001, so the ground under the date strip stays CREAM to the bit; the ticks are drawn after the glow, in their own ink, on top of it.
2. **The rim (figure).** A warm silhouette pass on the man, built from the frost halo's own mechanics — silhouette-only shapes at the four cardinal offsets in a flat colour, under the body — layered *inside* the halo (cool scatter outermost, warm rim hugging the edge, body on top), in the rect bake, the shared bucket rect, and the per-frame arm pass (`_draw_arm`'s widened-segment trick). Colour mixes from CREAM toward RIM_WARM (255, 216, 150) by the strength; radius steps 1 px below 75, 2 px at 75+, the halo's own step points. The held props get no rim (small, and mostly inside the body's rim zone); the rect pad grew to `2 + max(halo_r, rim_r)` so a rim wider than the halo is never clipped by a rect edge.

**The banding lesson (why the glow is per-pixel).** The first cut drew the glow as concentric filled ellipses — the dial's usual C primitives. The desk preview read as a *target*: the whole journey from cream to warm is only ~5 blue / ~2 red / ~2 green LSBs of RGB565, so solid-colour rings at ANY fineness round into a handful of hard-edged bands. Finer steps cannot fix a quantisation problem. The shipped glow is computed per pixel into the dial buffer (`_paint_glow`): ideal colours as floats in 565 space, falloff (1 − t²)² over the squared distance (zero slope at centre and edge, one sqrt per row for the chord), quantised through a 4×4 Bayer ordered dither so each step dissolves into texture the eye blends back into a gradient. ~102k pixels, render-time only. The second preview reads as a smooth warm pool with no rings — the "lit from within" read lands; at 50 it is a gentle brightening, at 100 he stands in lamplight with a faint gold edge on his arms (previews/preview_backlight_{0,50,100}.png, frost 55, 10:09 standing).

**Invariants (all desk-proven in the new `test_backlight.py`).** At backlight=0 the clock renders *exactly* as v17 — the standing frame at frost 55 is byte-identical to the stored v14 baseline (both module defaults are 0 until main applies the config, so any path that never sets it gets the old picture; every strength-gated draw is behind `> 0`). Hands and date keep their exact ink at every strength (composed-frame diffs vs strength 0 are confined to the glow disc). The painted-hand rule from Frost is untouched — the glow lives in the dial layer, under everything, and the hands are drawn over it in INK by compose(). The night dial is byte-identical at backlight 0 and 100: backlight is a day behaviour, the sleep scene (raw night palette, no rim) is untouched, and the cuckoo's sharp-face path (`_draw_head` with the raw palette) is unaffected. Config round-trips through admin save/load; re-rendering 100 → 0 restores the plain dial bytes exactly.

**Costs.** Dial render gains the ~102k-pixel dither pass (desk ~0.1 s; on the board it rides inside the existing re-render + ~4 s prepare that a face/frost change already pays). Rect bake gains up to 8 silhouette draws per rect (rim pass, both poses) — same order as the halo pass it mirrors. Per-frame cost: two extra widened polys per arm when the rim is on; the frame census is otherwise unchanged. Memory unchanged (no new canvases; the rim palette is one tuple).

**Desk verification.** Full suite green — all 11 prior files (test_suite, test_show_bands, test_idle, test_reach, test_loop, test_date, test_rollover, test_rollover_48h, test_sleep, test_display_recovery, test_portal) plus the new test_backlight (config round-trip, source-pinned wiring, strength-0 byte identity, glow confinement to its disc, all 2,336 tick pixels colour-exact, night identity, rim state 0/1/2, re-render hygiene). mpy-cross (v1.29.0) clean on clockface.py, figure.py, admin.py, main.py. **Bench-only, as ever:** upload clockface.py, figure.py, admin.py, main.py; open admin, move the Backlight slider next to Frost, save, and watch the dial re-render — Mark's eye settles the number, the way 55 settled Frost.

## Addendum — Nov 16, 2026 (v19: the backlight hang — both v18 costs cut back to v17's numbers)

**The hardware report (Mark, Nov 16, hours after v18 went on the board).** Two hangs, both cured only by unplugging USB: (1) admin **Restart** — the warm reboot v17 had bench-verified that same morning, before v18; (2) changing **Backlight** in admin and saving. The two paths share exactly one thing: both re-render the day dial and re-run `figure.prepare()` in full (boot does render + prepare before the first frame; a slider save does both live). v17's Restart worked; v18's hangs sit in what v18 added to those two paths. Both additions had been flagged in the v18 addendum as unmeasured on hardware — the ~102k per-pixel glow pass ("on the board it rides inside the existing re-render") and the rim bake ("same order as the halo pass it mirrors"). "Same order" turned out to be the problem in both cases.

**Measured op deltas (desk harness, `profile_v19.py` — framebuf prim counter + a counting bytearray on the dial buffer; prim counts are the board-honest currency, since prims are C calls and Python loop iterations are what the board is slow at).**

| path | v17 | v18 (as shipped) | v19 |
|---|---|---|---|
| dial render @ backlight 100 | 252 prims, 0 byte writes | 252 prims **+ 101,765 Python loop iterations, 141,458 byte writes / 121,542 byte reads** into the dial buffer | **2,546 prims, 0 byte writes** |
| figure.prepare() @ frost 55, backlight 50 | 7,449 prims | **12,627 prims (1.70×)** — the rim pass duplicated the halo silhouette pass prim for prim (+4,914 body, +264 bucket) | **7,449 prims at backlight 0, 50 and 100 (1.00×)** |

Desk wall time for the render's glow pass fell 0.29 s → 0.02 s of Python (the rest is stub rasterisation); on the board the ratio is far wider, because the v18 loop was float math per pixel in interpreted MicroPython. A render or bake that runs tens of seconds on the S3 is indistinguishable from a hang — and if a watchdog fires mid-render, the reboot starts the same render again. That is the whole failure shape: nothing in v18 was wrong on the desk, it was simply priced in a currency the board pays ~100× slower.

**The glow, rebuilt as spans (clockface).** Same colour math as v18 — same endpoints (CREAM → (255, 234, 192)), same (1 − t²)² falloff, same peak 0.85 — but each row is solved analytically instead of iterated per pixel. With one dither threshold per row, each channel's rounded value is a step function of the falloff f, and the journey is only ~+1 red / −2 green / −4 blue LSBs, so a row splits at ≤ ~8 channel-crossing f-values into a handful of constant-colour runs; each run is one `fill_rect` per side through the band windows (2,294 fills for the whole glow at strength 100). The threshold cycles per row from the same 4×4 Bayer matrix (16-row period), so neighbouring rows place their steps at different x and the eye reads texture, not rings — v18's dither trick at row granularity. Runs whose colour is the ground are never drawn, which also keeps the date rows (88–111) bit-exact: at their distance from the glow centre the mix provably never reaches a rounding boundary. Zero per-pixel Python writes; the loop is 361 rows of small float work.

*Fidelity vs the v18 renders* (stored references in `desktest-painter/backlight/`, compared pixel by pixel): dial @50 — mean |Δ| 0.07/0.10/0.11 LSB per channel, radial blue profile within 0.03 LSB at every radius, ≥2-LSB pixels 0.01% scattered (dither-vs-span rounding noise, no coherent bands); dial @100 — mean |Δ| ~0.11 LSB, profile within 0.05 LSB, ≥2-LSB 0.02%. The pool reads the same; no target.

**The rim, restructured (figure).** The baked rim pass is gone — all 5,178 prims of it. The rim survives where it costs per frame instead of per bake: the per-frame arm pass (`_draw_arm`'s widened polys in the rim colour, unchanged from v18). The baked body's warm edge now comes from the halo mechanism itself: when backlight > 0, `prepare()` tints the halo palette from FROST_HALO toward RIM_WARM by the strength (`_halo_pal`), so the frost scatter around him glows warm instead of cool; at backlight 0 the palette is `_HALO_PALETTE` itself and the bake is v17's, byte for byte. The honest visual trade, measured against v18's standing frames at frost 55: at backlight 50 the frames differ by at most 2 LSB anywhere (mean ~0.09); at 100, ~934 edge-ring pixels (0.41%) carry the simpler one-tone warm edge where v18 had a two-tone cool-outside/warm-inside ring. The glow — the dominant half of the effect — is numerically unchanged. prepare()'s prim count is now *identical at every backlight strength*: the slider can tint the bake, never grow it.

**The guard (`desktest-painter/test_opcounts.py`, new).** Pins the budgets so this cannot regress silently: `RENDER_PRIMS_MAX = 5000` (v19 measures 2,546 at strength 100), `RENDER_BYTE_WRITES_MAX = 0` (any per-byte write into the dial buffer during a render fails the suite — that is the v18 hang shape), `PREPARE_PRIMS_MAX = 8500` (v17/v19 measure 7,449; v18's 12,627 would fail loudly), plus the strength-invariance assertion on prepare() above.

**Invariants — all still desk-proven.** `test_backlight.py` passes *unmodified*: backlight=0 standing frame byte-identical to the pre-v18 baseline; glow confined to its disc; all 2,336 tick pixels colour-exact at strength 100; composed-frame diffs confined to the disc (hands/date ink exact); night dial byte-identical at 0 and 100; rim state 0/1/2 and the frost-0 frame difference (now carried by the arm rim + glow) intact; re-render 100 → 0 restores the plain dial exactly.

**Desk verification.** Full suite green — all 12 prior files (test_suite, test_show_bands, test_idle, test_reach, test_loop, test_date, test_rollover, test_rollover_48h, test_sleep, test_display_recovery, test_portal, test_backlight) plus the new test_opcounts. mpy-cross (v1.29.0) clean on clockface.py and figure.py. **Bench-only, as ever:** upload clockface.py and figure.py; cold boot (or the updater) — boot, admin Restart, and a Backlight save should now each complete in the v17 time class (dial render ~250 prims of C + ~2.3k span fills; prepare at the old 7,449). If a hang survives, it is not these two paths — the counts above are the alibi.

## Addendum — Nov 16, 2026 (v20: the cuckoo — §3.4's ritual, built)

**What shipped.** The hourly ritual §3.4 designed and §4.3 carried state for: ~0.7 s after the on-hour minute show completes, he leans in toward the glass, his cloth traces a circle, and inside that circle — 112 px diameter, centred on his face — the frost clears to reveal his face SHARP; he holds a beat, the circle fogs back, and he steps back. Total 7,200 ms (the phase split as built: lean 0–1000, wipe 1000–2500, hold 2500–3960, fog 3960–5472, retreat 5472–7200 — the settled v20 numbers supersede §3.4's prototype-era "about five seconds").

**The chain.** The cuckoo is chained off the show, never scheduled: when a show completes, `Show._chain_cuckoo` checks whether its target total was an hour boundary; if so (and enabled, and awake) the ritual is due 700 ms later, once per hour total. During the beat and the ritual the stage is held — the idle scheduler stands down exactly as it does for a show, and a boundary crossing mid-ritual would pre-empt it (the fit rule makes that a try-it-only theoretical case). It is *not* an idle routine: `IDLE_DUR` has no "cuckoo", the random picker cannot choose it, and when it ends it re-arms the idle gap like a show does, so the cadence bookkeeping is undisturbed beyond the occupied slot. A **Try the cuckoo** button in admin queues it like a routine try-it (fit check applies; a pending try is satisfied by any firing, chained or queued — never two back to back), and a `cuckoo_enabled` checkbox (default on, mirroring `sleep_enabled`) silences it without code; turning it off drops a pending due and un-queues a try, while a running ritual finishes.

**The sleep rule (Mark, Nov 16, 2026: no cuckoo when he's asleep).** The ritual is suppressed entirely inside the sleep window, on v15's semantics — sleep owns the display. An hour boundary in-window just snaps; nothing is queued for later. Sleep entry cancels a running ritual with everything else and clears a chained due outright: *skipped, not deferred*. The one deferral is the admin try-it, which behaves exactly like the idle try-its — queued during sleep, it fires at the first gap after the wake show. Desk-proven both ways (`test_cuckoo.py` C1–C3).

**Frost and backlight.** At frost=0 the same choreography plays — lean, cloth circle, hold — with only the clear/fog contrast absent (the porthole envelope still runs; there is simply no veil to lift). The scene composes over the normal day dial as-is, backlight glow and all; nothing is special-cased.

**The sharp patch (figure).** The clear circle is a composite, built inside the existing discipline — no new full-canvas pass, no per-pixel Python. While the figure intent's `cuckoo_clear` > 0, `Figure.draw()` builds a small patch in a lazy 120×120 scratch canvas (28,800 B, allocated on first use like the night layer): the dial region is blitted in (one `blit` through a 120×120 dial window — span 114,480 B, under the 115,200 B cap), the torso top and a sharp head are drawn over it in the RAW palette (the head by a dedicated `_draw_head_sharp` — `_draw_head`'s art verbatim at the lean scale, head grown ×(1 + 0.2·lean_in), so the face in the porthole is the bigger, closer one the lean promises), and the patch is composited onto the frame through a circular mask: rows in groups of 4, each group copied at its narrowest row's span, as C slice copies on the canvas buffer — zero framebuf calls, ~28 slice copies in the worst (fully open) frame. The patch draws *under* the arms, so the cloth hand wipes in front of the face it reveals. `prepare()` and the dial render are untouched — `_draw_head_sharp` is per-frame-only code the bake never calls — so the v19 op-count guard passes **unmodified** (render 2,546 prims / 0 byte writes, prepare 7,449).

**Costs (desk census, frost 55 / backlight 0 — the conditions of test_idle's family numbers).** Worst cuckoo frame: **38 framebuf calls** in `Figure.draw` (hold/fog), wipe 35, lean 28, retreat 27 — against standing rest 29 and the worst idle routine's 33 at the same conditions; the patch itself adds ~9. At backlight 50 the v19 per-frame arm rim inflates every frame type alike (rest 37) and the cuckoo's delta over its own baseline is the same ~9 (worst 46). No new per-pixel loops anywhere; the mask's Python work is ~30 rows of span arithmetic per frame.

**Desk verification (`desktest-painter/test_cuckoo.py`, new; full suite green incl. the unmodified guard).** The chain fires once after the 11:00 show (delay measured 700 ms, duration 7,200 ms, envelope peaking at exactly 1.0) and not after 11:01/11:02; no routine runs in the beat or the ritual. Pixels: in a hold frame the eye and skin inside the circle are the raw palette values where a cuckoo-less twin run carries the veiled colours, and the whole-frame diff (2,101 px) is confined to the circle's bounding box — 0 px outside. Sleep: the 21:00 chain fires awake; 22:00 and 23:00 snap with no cuckoo and no due pending; a try-it queued at 06:29:40 (window to 06:30) fires once after the wake show; a hand-set due swallowed by sleep entry is cleared and never fires. Six tick-level hours of idle life run 362 routines, none of them the cuckoo, with exactly the 6 hour chains. Disabled: the 11:00 show runs bare and the queue refuses; re-enabled, the try-it fires. The 48-h sim (sleep 22:00–06:00, 5 s ticks): 1,920 awake shows, 960 sleep snaps, exactly **31** cuckoos — one per completed awake hour show (day-14 12:00 is the boot snap and day-16's 12:00 show starts on the final tick, so neither chains inside the sim) — none in-window, no due ever pending in-window, midnight invariants intact. Frost=0: the ritual plays and the hold frame's head is the grown sharp head. Storyboard previews at frost 55 / backlight 50: `previews/preview_cuckoo_{lean,wipe,hold,fog}.png` — the half-open disc at mid-wipe reads unmistakably (saturated cap, warm skin inside; pale veil outside), the hold is a clean clear porthole with the bigger sharp face, and the fog frame's shrunken disc reads as the glass misting back over. mpy-cross (v1.29.0) clean on figure.py, show.py, admin.py, main.py.

**Bench-only, as ever:** upload figure.py, show.py, admin.py, main.py (clockface.py and display.py unchanged); cold boot or admin Restart. On the hour he should lean in about a second after the repaint finishes, wipe his circle, and show his face sharp for a beat. The admin page gains the **Cuckoo on the hour** checkbox and a **Try the cuckoo** button under the idle try-its — the try-it is the bench shortcut, no need to wait for an hour boundary.

## Addendum — Nov 16, 2026 (v21: the cuckoo choreography, revised on Mark's bench verdict)

**The verdict.** Mark, on v20's first bench run: "Seems to work but it doesn't last, and his arm is in the way of the face the whole time. It should wipe, then arm goes down and there should be a 3-5 delay before the fog comes back." Both halves were fair. The clear hold was 1,460 ms — a beat, not a look — and through the lean and the wipe (2.5 of the 7.2 s) the cloth arm works across and around the disc, so the only unobstructed moment was that short hold; at its end the hand target simply released and the hand was redrawn at the hang, a jump cut with no travel.

**The new phase table** (`show.py` only; figure.py untouched — the patch, mask and sharp head are v20's): lean 0–1000, wipe 1000–2500 (both unchanged), **arm-down 2500–3300**, **hold 3300–7300**, fog 7300–8800, retreat 8800–10500. Total 10,500 ms. In the arm-down the hand sweeps down the LEFT rim of the circle it opened — staying on the hand radius (62, just outside the 56 porthole), so the revealed face is never crossed — then drops from the rim's bottom to the hang at his side, the porthole fully open throughout. The hold is a full **4.0 s** (the middle of Mark's 3–5) with the arm down; at its start the intent simply releases, and the released hang is where the arm-down parked the hand, so nothing jumps. The fog keeps v20's ~1.5 s creep, now with the arm still down; the retreat releases the lean as before. All v20 rules stand: chained +700 ms after the on-hour show, once per hour, never in the random mix, suppressed entirely in the sleep window (dues skipped, not deferred; the admin try-it defers), `cuckoo_enabled` + Try button as built, frost=0 plays the same choreography.

**Costs.** Unchanged in kind: worst cuckoo frame still **38 framebuf calls** in `Figure.draw` at the family conditions (frost 55 / backlight 0; test_cuckoo G) — the arm-down frames cost what the wipe frames cost, the hold frames what v20's hold cost. The v19 op-count guard passes **unmodified** (render 2,546 prims / 0 byte writes; prepare 7,449 at every backlight): `prepare()` and the dial render are untouched, and the new phase is pure intent choreography in `_run_cuckoo`. No new per-pixel loops.

**Desk verification (`desktest-painter/test_cuckoo.py`, updated; full suite green).** Section A re-pinned to the new duration (chain delay 700 ms, duration measured 10,500 ms). New section **A2** verifies the v21 shape at 40 ms steps: mid-arm-down the hand is on the rim sweeping down the left side; from `CUCKOO_DOWN_MS` on, the hand is below the porthole in every sampled frame through hold and fog; the fully-open stretch (hand down, clear = 1.0) measures **2,880 → 7,320 ms — 4.44 s**, over the 3.5 s floor; clear never drops before the hold ends and is gone by the fog's end. The hold frame's cloth hand sits outside the porthole circle, and its face region (head ±26 px) is **pixel-identical to an arm-suppressed twin** of the same run (3,560 diff px in the whole frame, 0 in the face box) — no arm colours cross the face while it shows. Every v20 case kept and passing: B's sharp-in-circle pixels (now sampled in the true hold), sleep C1–C3, the random-mix D, disabled E, frost=0 H, admin wiring, and the 48-h sim F — 1,920 awake shows, 960 sleep snaps, exactly **31** cuckoos, none in-window. Storyboards re-rendered at frost 55 / backlight 50 (`previews/preview_cuckoo_{lean,wipe,armdown,hold,fog}.png`): the armdown frame shows the arm descending the disc's left rim with the face already clear beside it; the hold frame is byte-identical to v20's hold frame — the same settled picture, now reached by travel instead of a jump and held for 4 s. (At 11:00 both clock hands point up through the disc in these frames — the real time display, inherent, as noted in v20.) mpy-cross (v1.29.0) clean on show.py.

**Bench-only, as ever:** upload **show.py only** (figure.py, admin.py, main.py unchanged from v20); cold boot or admin Restart. On the hour — or via **Try the cuckoo** — he should wipe his circle, bring the cloth arm down its rim to his side, and hold his sharp face clear for a count of four before it fogs.

## Addendum — Nov 16, 2026 (v22: the setup screen — a moved clock no longer sits black)

**The field report.** Mark moved the clock to a new place and powered it up with no valid Wi-Fi for the location: the saved network failed to join, the setup portal came up — and the screen stayed BLACK for the whole portal session. He completed the setup from his phone, but the clock looked dead. His ask: "when the wifi can't be connected, the display should come up with a stylized message on how to setup the wifi."

**Why it was black (confirmed in code).** Every portal entry in main.py called `prov.run_portal()` directly, and nothing in that path ever composed a frame — the frame canvas sat at its power-on zeros from plug-in to setup-done. Compounding it, the PCF85063 has no backup battery, so after a move the RTC holds no valid time and there is no face to draw anyway. The portal itself was never the problem (v16, bench-verified the same morning).

**What shipped.** A setup screen, rendered once and left up for the whole portal session:

- `main._enter_portal(reason)` is now the ONLY way into the portal — the BOOT-hold, no-credentials, and failed-join entries all route through it. It loads the config, begins the display (on the BOOT-hold path stage 2 has not run yet; `display.init()` is a no-op when the panel is already live, and beginning the panel before the portal's radio also honours the panel-first rule on every path), applies the panel brightness, renders the screen, shows it, and only then calls `prov.run_portal()` — which is byte-for-byte v16's, serve loop untouched. The render is fail-soft: a screen that cannot be drawn prints and the portal still runs. Setup completing behaves exactly as before (portal writes wifi_cfg.py, reboots, normal face on the new network). Scope is portal mode only: a clock with good credentials that loses its router mid-run keeps today's behaviour — no new screens there.
- `setupface.py` (new) draws the screen into the frame canvas: the clock's OWN frosted dial — `clockface.draw_dial` at the config's backlight strength, glow and all, so the glass is the one the owner knows — with the instructions painted on it in the project's lettering. The lettering is `clockface.text_strip` (below) blitted KEYED over the dial via `display.blit_sprite`, so it sits on the glass like the hands and the date, ticks showing through the gaps. The wording as shipped:

  > **Wi-Fi setup**
  > 1. On your phone, join
  > **PainterClock-Setup**
  > 2. A setup page opens / by itself. Pick your / network, type password
  > 3. This clock restarts / and connects itself
  > No page? Browse to
  > **192.168.4.1**

  Headline at scale 4, the two values the owner must copy exactly (network name, fallback address) at scale 3 on their own lines, the steps at scale 2. The name and the address are read from `prov.AP_SSID` / `prov.AP_IP` at render time — the screen cannot drift from what the portal actually runs (the portal's DNS catch-all and redirect use the same constants; the address is the AP's 192.168.4.1).
- **No figure, deliberately.** Three legible steps plus a fallback fill a 480 px round dial; the standing figure would leave the words nowhere readable to live. The empty glass is also the honest picture — nobody is home until he is connected. The dial, the rim, the ticks and the painted lettering carry the clock's identity without him.
- `clockface.text_strip(s, colour, ground, scale)` generalises the date's strip builder (the project's one text renderer: 8×8 font into a small scratch FrameBuffer, each set pixel grown to a scale-square, cached); `_date_strip` now delegates at DATE_SCALE and produces byte-identical strips — `test_date.py` passes unmodified. setupface passes a magenta key as the strip ground, which is what makes the keyed blit work.
- `update_files.txt` and updater.py's fallback list both gain `setupface.py`, so the self-updater can deliver it like any other module.

**Costs (desk census, `test_setup_screen.py` §A, backlight 50).** The setup frame: **1,331 framebuf draw prims** (the dial render at backlight 50 — the same class as the guard's ordinary dial numbers — plus the strips' fill/text calls), **0 per-byte writes** into the frame buffer (the v18 hang shape, absent), and 11,776 pixel READS on the strips' tiny scratch buffers — the date builder's established mechanism, exactly 64 per character × 184 characters, bounded by the copy. The keyed blits are slice copies, no prims. It renders ONCE per portal entry; there is no repaint loop and nothing competes with the portal's sockets. The v19 op-count guard passes **unmodified** (render 2,546 prims / 0 byte writes; prepare 7,449 at every backlight) — neither the dial render nor prepare() changed cost.

**Desk verification (`desktest-painter/test_setup_screen.py`, new; full suite green).** §A: the census above; the frame differs from a no-render control by 230,400 non-black pixels; 17,475 INK pixels with max radius 219.8 (disc edge 233 — lettering may cross a tick, like the hands do, never the rim); the SSID line carries 3,150 ink pixels, the address line 1,773, the headline 2,960; a second render is byte-identical. §B drives main.py's real boot end to end under stubs (test_portal's pattern, plus stub admin/timekeep/updater): **B1** absent wifi_cfg → portal entered once, the frame canvas pixel-exact equal to a control setup render, and the portal still completes a scripted save + reboot; **B2** BOOT-hold with valid creds → same screen, same completion; **B3** saved network fails to join (Mark's moved clock) → same; **B4** valid creds, join succeeds → NO portal, NO setup render, the normal face path runs (frame composed, dial layer rendered, frame ≠ the setup screen). Full suite green: all 14 prior files (incl. test_portal unmodified, test_opcounts unmodified, both rollover sims and the 48-h) plus the new one. mpy-cross (v1.29.0) clean on main.py, clockface.py, setupface.py, updater.py. Storyboard: `previews/preview_setup.png` (backlight 50) — the frosted dial with the words painted on, the network name and address big; it reads as this clock's glass, not a router page.

**Bench-only, as ever:** upload **main.py, clockface.py, setupface.py (new), updater.py, update_files.txt**; cold boot. Then: power the clock up away from its saved network (or Rehome it) — within seconds of plug-in the dial should light with the setup words and stay lit while the phone does the setup; saving still reboots it onto the new network with the normal face. (The board's self-updater will also flag v22, since all five files are in the manifest.)

## Addendum — Nov 16, 2026 (v23: the Connected screen — the clock announces its admin address)

**The ask.** Minutes after the v22 setup screen bench-verified ("That worked nicely"), Mark set the clock up on his Flagstaff network — and the face came up with no word of what address the clock had landed on, so the admin page might as well not have existed. His ask, in substance: "once its connected it can display what the IP is for the admin page, say for 30-45 seconds."

**What shipped.**

- `connectface.py` (new): the same painted glass as setupface — `clockface.draw_dial` at the config's backlight strength, the lettering `clockface.text_strip` blitted KEYED over the dial, ticks showing through. The wording as shipped:

  > **Connected**
  > Admin page - type this / in a browser
  > **192.168.1.42**
  > Your network:
  > FlagstaffNet

  (network name and address shown are the storyboard's stand-ins). The address — the one thing the owner must copy exactly — gets the big scale and its own line: scale 4 while it fits (≤ 13 chars, the common 192.168.x.x shapes), scale 3 for the longest dotted quads. The network name is smaller underneath and display-capped at 26 chars, so a long SSID cannot push ink at the rim; the join itself is untouched. admin.py serves on port 80, so the bare IP *is* the whole admin address — no port, no path, and no hostname invented for the occasion. The SSID and IP are passed in from the live network state at render time (the joined SSID; `wlan.ifconfig()[0]`) — the screen cannot drift from the truth it reports.
- `main.py`: `_show_connected()` runs once per boot, immediately after the NTP sync (stage 5b), so the clock behind the splash is already time-true. It renders into the frame canvas and shows it, fail-soft exactly like the setup screen — a failed render prints, returns None, and boot continues to the face as before v23. Before the run loop, `_hold_splash()` holds the frame until **35 s** have passed since it went up (`SPLASH_MS = 35000`, the middle of Mark's 30–45), servicing admin in `LOOP_MS` slices: the address on the glass answers in a browser while it is still displayed, and anything admin queues meanwhile (a try-it, a config change) sits in the app dict and is picked up by the loop's first pass, as if it had arrived a moment later. The face's first frame then paints the true time — the Show accounts from its first tick (its `last_total` starts None), so the late loop entry owes no show and skips none, and the midnight/monotonic invariants are untouched.
- **Trigger — boot joins only.** Every boot join splashes: a plain power-cycle, the reboot right after a portal setup saves (Mark's case — the setup screen's job ends, the reboot joins, the splash names the address), and the updater's reboot, all of which arrive through this same boot path. A mid-run router blip can never splash: the splash is a boot-stage function, not a connection-state one, and the run loop has no rejoin path that could reach it — the face is never interrupted.
- `update_files.txt` and updater.py's fallback list both gain `connectface.py`, so the self-updater can deliver it like any other module.

**Costs (desk census, `test_connected_screen.py` §A, backlight 50).** The Connected frame: **1,327 framebuf draw prims** (the dial render plus the strips' fill/text calls — the setup screen's class, 1,331), **0 per-byte writes** into the frame buffer, and 5,120 pixel READS on the strips' tiny scratch buffers — exactly 64 per character × 80 characters, bounded by the copy. It renders ONCE per boot; the hold is a static frame (the panel holds it for free) with admin serviced in slices — no repaint loop. The v19 op-count guard passes **unmodified** (render 2,546 prims / 0 byte writes; prepare 7,449 at every backlight) — neither the dial render nor prepare() changed cost.

**Desk verification (`desktest-painter/test_connected_screen.py`, new; full suite green).** §A: the census above; 10,716 INK pixels with max radius 203.0 at the common shape (the scale-4 address line alone carries 3,504 ink pixels) and max radius 216.0 at the worst shape (15-char address at scale 3, 30-char SSID capped) — lettering may cross a tick, like the hands do, never the rim; a second render is byte-identical. §B drives main.py's real boot end to end under stubs (test_setup_screen's pattern), recording every `display.show()`: **B1** good creds → the splash is the first frame shown, the first face frame lands at exactly **+35,000 ms** of fake time, admin is serviced throughout the hold, and a mid-run disconnect/reconnect (admin steps 2000/3200) produces no second render and no second splash; **B2** portal save + reboot → the reboot's boot joins the just-saved network and its first shown frame is the splash wearing that network's name and this clock's address; **B3** a forced splash-render failure logs and boots to the face exactly as before v23. Full suite green: all 15 prior files (incl. test_opcounts unmodified, both rollover sims and the 48-h; test_setup_screen's module-reset list gained "connectface" — the one-line harness update a new main.py import requires, so a stale module cannot keep an earlier boot's display binding) plus the new one. mpy-cross (v1.29.0) clean on main.py, connectface.py, updater.py. Storyboard: `previews/preview_connected.png` (backlight 50).

**Bench-only, as ever:** upload **main.py, connectface.py (new), updater.py, update_files.txt** (clockface.py, setupface.py, display.py unchanged); cold boot or admin Restart. On any boot that joins, the dial should light with "Connected" and the admin address for ~35 s — long enough to type it into a browser, which should answer while the address is still up — and then the face takes over, already showing the right time. (The board's self-updater will also flag v23, since all four files are in the manifest.)

## Addendum — Nov 16, 2026 (v24: the admin UX pass — sliders, sections, an icon, and no more landing pages)

**The ask.** Mark, that evening, in substance: "clean up the admin page. Add more sophisticated controls like sliders, create a pointer clock icon for the tab and put it next to the title in the header of admin. create appropriate sections and use different colors to denote each, similar to the vislog. when save, update etc is pressed have it stay/refresh the admin page rather than landing page." (The pass had been queued since the afternoon; this made it fully specified.)

**What shipped (admin.py only).** Presentation and responses; the config keys, the POST handlers' semantics, the apply-live paths and the render pipeline are untouched.

- **Sliders.** Brightness (0–255), frost (0–100) and backlight (0–100) are real `<input type="range">` controls built by one helper (`_slider`), each with a live numeric readout that tracks the drag (a one-line `oninput`). Same field names, same ranges, same clamping in the handler — a slider submits exactly what the old number box did.
- **The icon.** A pointer clock — cream disc, brown rim and ticks, two hands at the classic 10:10 — drawn once as an inline SVG (`ICON_SVG`, in the dial's own cream #fff8ea and ink #5b4636). It is the browser tab's favicon via a data URI derived from that same literal (the pair can never drift, and no extra file ships or rides the manifest), and it sits inline beside "Painter Clock" in the header — the Visual Logbook admin's arrangement.
- **Sections.** Seven fieldsets in the Visual Logbook admin's manner, a legend and a pastel tint each: **Status** #e9f1fd (blue), **Display** #e7f6ec (green), **Frost & backlight** #e2f5f7 (teal), **Sleep** #e9e4f5 (lavender), **Cuckoo & idle life** #fff6d9 (warm yellow), **Update** #fdeee2 (soft orange), **System** #fdeaea (soft red). Every control, label and explanation from the old page survives, including the Baas credit footer verbatim. The settings still post as one form to /settings with one Save; the Try-it and Try-cuckoo buttons live inside that form and post via `formaction` to their old endpoints, whose handlers read only their own fields — semantics identical.
- **No more landing pages.** Save, Try-it and Try-cuckoo answer with the admin page itself plus a `.msg` note in the vislog style ("Settings saved.", "Queued: …"). The two rebooting actions — Update now and Restart — answer with a minimal auto-refreshing page (meta refresh to `/`: 60 s for update, 30 s for restart; a manual link if it stalls), so the flow ends on the admin page once the clock is back. During the v23 splash hold the admin server already answers, so the refresh lands on a live page.

**Costs.** None on the render pipeline: no display/figure/clockface code touched, and the v19 op-count guard passes **unmodified**. The page itself is ~5.6 KB of HTML, built per request as before; no external assets, no frameworks.

**Desk verification (`desktest-painter/test_admin.py`, new; full suite green — all 16 prior files plus this one, both rollover sims and the 48-h included).** The page: exactly three range inputs carrying a stub config's values (brightness 123 / frost 34 / backlight 78) with the config's own maxima, a readout span and an oninput each; the favicon link (data URI, the SVG encoded) and the same SVG inline in the `<h1>`; all seven section classes and legends, in order; every old control, label and the Baas line present; no `.msg` note on a plain GET. Driven end-to-end through `step()` with a fake socket server: POST /settings saves (config.json on disk carries the new values, `app["changed"]` set) and answers with the admin page already wearing them; /tryit and /trycuckoo queue as before and answer with the page plus the queue note (a bogus routine queues nothing); /restart and /update perform their act (stubbed reset / apply recorded) and answer with the refresh page pointing back at `/`. Two old assertions were updated for the reshuffle: test_cuckoo's trycuckoo form action is now the button's `formaction`, and test_backlight's source pin names the `_slider("backlight")` call rather than the literal field attribute (the rendered `name="backlight"` field is asserted in test_admin). mpy-cross (v1.29.0) clean on admin.py. Preview: `previews/preview_admin_v24.html` — a static render of the page as served (default settings, with a "Settings saved." note showing).

**Bench-only, as ever:** upload **admin.py only** — it is in `update_files.txt`, so the board's self-updater will also flag v24; press Update now and the new page is what answers after the reboot. Then: the tab should wear the little pointer clock, the sliders should track their numbers as they drag, Save should leave you on the page with the green "Settings saved." note, and Restart should bring the admin page back by itself.

## Addendum — Nov 17, 2026 (v25: proportions pass 2, the bucket move, arms crossed, the cuckoo step-aside)

**The ask.** Mark, that day: shorten the arms further at the same forearm:upper ratio; at rest the arms hang straighter, hands still close beside his sides; shorten the neck a bit more; the head more oval (subtly taller than wide); overall ~5% taller; torso shorter and legs longer by the same amount. Plus three behaviour items: build the deferred bucket-move idle (he carries the paint bucket to the other side and it STAYS there — dip target and the mug's home follow it); a new arms-crossed idle with an impatient foot tap; and a cuckoo fix — at 12 the minute hand obstructs him, so before the lean/wipe he steps to the side opposite the hour hand.

**Proportions (figure.py; feet and bucket floor line unmoved).** The package, before → after:

| Measure | v14 | v25 |
|---|---|---|
| Arms (upper / forearm+hand) | 64 / 82 (reach 146) | **62 / 80 (reach 142)** — ratio 1.290 vs 1.281, integer rounding |
| Shoulders | y 225 (SHOULDER_H 221) | **y 222 (SHOULDER_H 224)** |
| Face centre | y 180 (HEAD_H 266) | **y 172 (HEAD_H 274)** |
| Head ellipse | 20 × 23 | **19 × 25 (HEAD_RX × HEAD_RY)** — oval; cap top rides −(HEAD_RY−1) |
| Hips | y 330 (HIP_H 116) | **y 316 (HIP_H 130)** |
| Torso (shoulder→hip) | 105 px | **94 px** |
| Legs (hip→foot) | 116 px | **130 px** |
| Visible neck | 22 px | **19 px** (gap 45→50, eaten by the taller ellipse +2 and the new COLLAR: the torso's drawn top edge rides 6 px above the anchor line) |
| Total height (cap top → boot sole) | 291 px | **301 px (+3.4%)** |
| Rest hang | hands fx ±27, elbow bow ~27 px | **hands fx ±25 (HANG_OUT 6), bow ~22 px, ~95% extension** — straighter, hands still mid-thigh (y ≈ 357) |
| BODY_SINK | 26 | **33** (STAND_YS / DIP_YS deep row; at full sink the boot soles reach the dial's bottom edge, transiently) |
| Pivot (240,240) | 15 px below shoulders | 18 px below shoulders, still on the upper chest, face bottom (197) clears it |

The full 5% height and a 10–12% arm cut are **not** jointly reachable, and the desk proves why: the reach budget is one pool shared by height, neck and arm length (probe_v25.py swept the candidates through test_reach's own method). A ~130-reach arm measures a 19–22 px shortfall on the bottom-arc minute frontier at every sink the dial allows — the brush would visibly miss the minute tip. What shipped is the largest arm cut that keeps the proof, with BODY_SINK 26 → 33 as the compensation (the body crouches the difference — the established v13 mechanism, never longer bones). Reach results, test_reach's method: **minute worst 9.3 px** (bottom arc, full reveal; v14's 9.2), **0.0 at reveals 0.9 / 0.5, hour 0.0 everywhere, show dip 0.0, sip grab 0.0**. Landmark pins in test_reach moved to the new spec; the ≤10 px invariant is unchanged.

**The bucket move (show.py `_idle_bucket`, 6.0 s, weight 2).** Dip-grab at the current side (the proven dip: bend envelope, follow 0.30, hand to the rim), rise carrying, walk across, dip again at the far side, release. State: `fig.bucket_x` flips at the set-down and persists — the show's dip target already reads it, and the mug's home now derives from it (`figure.mug_home(bucket_x)`; MUG_HOME_L mirrors MUG_HOME). Consistency machinery, all desk-proven:

- **The bucket is no longer baked into any body rect.** prepare() builds two shared bucket stamps (one per floor side, BUCKET_L = (148, 436) mirroring BUCKET) and draw() stamps the current side over the body rect every frame — so a move takes effect with no prepare() rebuild. The carried bucket is drawn per frame at the right hand (no halo pass — a swinging bucket has no frost contact to fake, and the pass would have cost ~18 fb calls on carry frames; the floor stamp keeps its halo).
- **The mirrored dip is a real sprite** ("dipL", DIP_XS_L = (−26, −13, 0)): pose() picks the lean's sign from the intent's `bend_dir`, defaulting to the bucket's current side. Two latent traps were found and fixed on the way: `_bend_point`'s early-out (`bend <= 0.001`) silently un-bent every −1 lean (the mirrored dip stood upright and missed by 47 px), and its crouch term needed `abs(bend)`.
- **The mirrored dip lands 6.8 px** (the dip's tolerance is 12; the snap grids are not perfectly symmetric about his centre). **The mirrored sip changes hands**: leaning left, the right shoulder rides ~23 px higher than it does leaning right (a rigid torso rotating about the hips), and a right-handed grab at the left floor measured 18 px short. So with the bucket on his left, `_idle_sip` works the LEFT hand (tip_l, prop_l = "mug", the knee-brace hand follows the working hand in pose()) and lands **0.0 px**. The bucket routine's own far grab keeps the right hand — its 6.8 px is inside the dip tolerance the design already accepts.

**Arms crossed (show.py `_idle_crossed`, 4.2 s, weight 2).** Hands tuck to opposite sides of his chest (right hand to his left chest, left under it) and hold ~2.4 s while the right boot taps: figure.draw() erases the baked boot with a dial window and redraws it lifted 3 px in steps (~9 taps, the cuckoo patch's erase trick at boot scale). No head motion — the baked head cannot turn.

**The cuckoo step-aside (show.py, CUCKOO_SHIFT = 80).** At `_start_cuckoo` the shift is chosen from the struck hour's hour-hand angle: hand in the left half → step right (+80), right half → step left (−80); near-vertical hands (12 and 6, |sin| ≤ 0.25) have no side — **the default is RIGHT**. The sway rides the existing intent through the ritual (in over the lean, held through the fog, out over the retreat); every phase target reads the eased body and the porthole follows pose["head"], so lean, wipe, arm-down, the 4 s hold and the fog all happen at the shifted stance. On glass the body snaps to the +75 grid column: the hold head sits at x ≈ 315, the porthole's near edge 19 px right of the centre line, clear of the minute hand's strip. Timing (10.5 s), chaining, sleep suppression and the never-in-the-idle-mix rule are unchanged; the 48-h count is still exactly 31.

**Admin.** TRYIT gains ("bucket", "Move the paint bucket") and ("crossed", "Arms crossed") in the Cuckoo & idle life section — the v24 layout, sections, colours and return-to-admin behaviour are untouched (test_admin iterates TRYIT generically).

**Costs.** The v19 op-count guard passes **unmodified**: render 2,546 prims (max 5,000), 0 per-byte writes; prepare 7,449 → **8,267 prims (max 8,500)**, still identical at backlight 0/50/100. The arithmetic: +12 dipL rects (~+1,118 at the build's per-rect average) − the bucket un-baked from the ~27 rects that used to carry it (~−300). Frame census: rest 27 → 28 (the per-frame bucket stamp), worst routine still 33 (test_idle's bound 36 unmoved — the carried bucket's halo was dropped to keep it there: with it, carry frames measured 45), worst cuckoo frame 38 (budget 40 unmoved).

**Desk verification (full suite green — all 18 test files, both rollover sims and the 48-h standalone included).** test_reach: landmarks at the new pins, the sweep above, plus the mirrored dip (6.8, sprite dipL asserted) and mirrored sip (0.0, left hand). test_idle: both new routines in the per-routine loop (bucket: dips at both ends, carried seen, bucket_x flipped after; crossed: hands crossed + tap seen; v25 intent fields clean after) and a persistence section — two moves toggle the bucket 332 ↔ 148, mug_home follows, the sip's mug hand follows the side. test_cuckoo: new section I (shift direction for all 12 hours; at 12:00 the driven hold's disc clears the centre strip); section B's twin is now a patch-suppressed run of the same shifted choreography (a cuckoo-less twin would differ by the whole step-aside) — 3,071 diff px, all inside the porthole box; section H's grown-head pin follows the shifted head (skin at x=335). test_date / test_backlight re-based to v25base (make_v25base.py). One process note: a single test_cuckoo run failed section B (12,260 stray diffs) while two heavy diagnostics ran concurrently against the same harness; the identical file passed clean twice solo (truncated A+A2+B and the full run) — recorded here so a recurrence is recognised. mpy-cross (v1.29.0) clean on figure.py, show.py, admin.py. Previews: `previews/preview_v25_pose_sidebyside.png` (v14 left, v25 right, date off both), `preview_v25_pose.png`, `preview_v25_crossed.png` (mid-tap), `preview_v25_bucket_left.png` (bucket and mug on the left), `preview_v25_cuckoo12.png` (the 12:00 hold, stepped right, face clear of the vertical minute hand).

**Bench-only, as ever:** upload **figure.py, show.py, admin.py** — all three are in `update_files.txt`, so the board's self-updater flags v25 as one Update now (the clock must already be on v21+ choreography for the cuckoo phases the step-aside rides; the v25 files supersede v21's show.py wholesale). Then: judge the new figure against the side-by-side; Try-it "Move the paint bucket" and watch the dip and the mug follow the bucket to its new side (and a later sip use his left hand); Try-it "Arms crossed" for the foot tap; and at the next hour boundary — clearest at 12 — watch him step aside before the lean so the minute hand never crosses his face.

## Addendum (Nov 17, 2026, evening) — v26: the classic and digital faces, built

Mark's word: *"I believe we have most of the painter handled. Please put together the analog and digital versions and make them selectable on the admin page."* The admin pulldown and the `face` config key existed since the Nov 15 addendum; classic/digital fell back to the painter. v26 replaces the fallback with two real faces behind the same face-generic contract, in two new modules — **`classicface.py`** (the analog) and **`digitalface.py`** (the digital) — both in `update_files.txt` and in `updater.py`'s fallback `UPDATE_FILES`, so one **Update now** delivers the whole version. Selecting a face in admin + Save switches the clock **live, no reboot** (the loop's config-change branch re-renders the statics and the next frame wears the new face; desk-proven byte-exact in test_faces §D, painter → classic → digital through the real `main.py`).

**The classic analog (`classicface.py`).** The painter's own dial, minus the man: the same cream ground, shade and rim discs (`clockface.draw_dial`'s palette and radii, shared by reference — the constants are imported, not copied), all sixty minute ticks (longer and heavier at the hours, longest at the quarters — the painter's dial draws only the quarters), and straight tapered hands in the painter's INK drawn as filled polygons through the same band-window machinery as the painted hands. Hour and minute **creep continuously** (a classic movement: the minute angle carries the seconds fraction, the hour carries the minutes) where the painter's hands step. **The second hand SHIPPED**: slim, in a muted rust (172, 84, 52 — the sleep blanket's family), with a counterweight dot and an ink boss with a rust centre. It steps once per second — the decision was measured, not guessed: a steady-state day compose is **12 framebuf prims** (three band-split hand polygons + two boss dots + the date strip's keyed blit; the static dial render is 252 prims, once) against the painter's 2,546-prim static render and 8,267-prim prepare, so per-second frames are nowhere near any budget the clock has. On the board each frame is additionally one 480×120×4 band presentation, the same as any painter frame. Centre dot: the boss. No figure, no frost (there is no glass and no man behind it), no halo.

**The digital (`digitalface.py`).** The same field (rim, shade, ground — no ticks), and the time as the hero: **HH:MM at scale 11** (88 px glyphs; the widest string, "12:59", is 440 px and its strip corners stay inside the dial disc), the codebase's own 8×8 font blown up — the Connected screen's scale 4 was the floor the brief set; scale 11 is the largest that fits the disc. 12-hour, unpadded hour, matching the painter's convention. Below it, a sub-line at scale 5: **seconds and AM/PM** ("%02d %s" — "35 AM"). A compose is **zero framebuf prims** — the static copy plus row-slice copies of three cached strips — and its static render is 12 prims. One engineering note that matters: `clockface.text_strip`'s cache is unbounded (fine for a date that changes daily), but a digital hero mints a new ~77 KB strip every minute, so digitalface builds its strips with the same scratch-FrameBuffer construction behind its **own bounded cache** (8 entries, cleared whole when full; desk-asserted after a full minute of seconds).

**The standing rules, kept.** (a) **Date on every face**: both faces draw `clockface.draw_date` — the same "Sun 15 Nov" — gated by the same `show_date` key, live on toggle. On the classic it sits at the shared top position (the dial's ticks are drawn well clear of its box); on the digital it tops the field in scale 3. (b) **Sleep**: both faces have a night treatment in the painter's own — each exposes `render_night(canvas)` into the shared night layer: the classic re-draws its dial in the night palette (deep ground, ghost ticks) and composes PALE hour/minute hands, minute-stepped, **no second hand**; the digital draws its field dark and sets the hero in PALE with the AM/PM marker alone beneath (seconds dropped — nothing moves inside a sleeping minute). The loop hands a sleeping non-painter face its night layer through the same `state["night"]` convention the painter's sleep path uses, and repaints it on the minute. Exiting the window restores the day face. (c) **Brightness** is the panel's and applies to all faces untouched. **Frost and Backlight stay painter-only** — they are effects of the man behind glass; main now gates the re-bake branch (and `figure.prepare`) on the painter face explicitly, and the new faces expose no `set_backlight`, so the existing `getattr` convention leaves them alone. Nothing is faked onto the new faces. (d) **Cuckoo, idle routines and shows are painter-only**: the loop's show engine only drives the painter face; on another face a Try-it or Try-cuckoo press is **dropped, never queued** (a stale queue must not fire if the owner switches back later). (e) The Connected screen, setup screen, portal and updater are untouched and face-independent.

**One integration subtlety worth recording**: `display.night_dial()` is a single shared canvas, and the painter's night layer is rendered into it lazily by figure and cached. With per-face night layers, main now renders the **selected** face's night layer at boot and on **every** face switch (`_render_night`), so a painter sleep after a classic stint can never wake wearing the classic's night dial (the painter's own lazy render would have skipped, believing its layer already drawn). The painter's sleep frames are pixel-identical either way — `clockface.render_night` re-draws the same pixels figure's path does.

**Admin**: unchanged v24 page; the pulldown's labels now read **Painter / Classic analog / Digital** (values unchanged — `painter` / `classic` / `digital` — so saved configs and the settings handler are untouched).

**Desk verification.** New `test_faces.py`: §A dispatch (FACES map, face contract, both delivery lists), §B classic (second hand present at :35 and gone at :36 at its mid-point pixel, date gate by centre-span, night = PALE on NIGHT_GROUND with zero rust and seconds ignored), §C digital (hero ink census, per-second change with byte-identical repeats, AM/PM confined to the sub-line rows, date gate, night snap, bounded cache), §D the real loop switching faces live with byte-exact frames. Prim census: classic static 252, classic compose 12 (day) / 6 (night), digital static 12, digital compose 0 — all steady-state; a first compose on a new day also builds that face's date strip once (~640 stub pixel writes, cached, the painter's own pattern). The **v19 op-count guard passes unmodified** and the full suite is green — every prior test file plus test_faces, both rollover sims and the 48-h standalone included. mpy-cross (v1.29.0) clean on classicface.py, digitalface.py, main.py, admin.py, updater.py. Previews: `previews/preview_v26_analog_day.png`, `preview_v26_analog_sleep.png`, `preview_v26_digital_day.png`, `preview_v26_digital_sleep.png` (10:09:35 day / 23:09 sleep, date on).

**Bench-only, as ever:** press **Update now** once (v26 rides the manifest: main.py, admin.py, updater.py, classicface.py, digitalface.py), then pick **Classic analog** or **Digital** in the admin face pulldown and Save — the clock should change faces in front of you, no reboot. Judge: the analog's tick ring and rust second hand; the digital's hero size; both faces' date line; and after the sleep window starts, each face's night treatment (and the day face back in the morning). Frost/Backlight sliders remain painter-face settings — on the other faces they simply have no effect, by design.

## Addendum (Nov 17, 2026, night) — v27: the smooth font

Mark's words, minutes after bench-verifying v26: *"the two clocks work really well — is there a way to get a font that is much smoother rather than the block that we have now?"* — and, on the same call: *"can we also use that font for the boot up showing the IP?"* v26's text was the firmware's 8×8 bitmap grown by integer scaling (the digital hero at scale 11: every glyph pixel an 11 px block). v27 replaces the letterforms themselves, everywhere text appears: the digital face's hero and sub-line, the shared date line on all three faces, the Connected boot screen (explicitly in scope — the IP is the one thing read off it), and the setup screen (included because its strings are all fixed, so it fell out of the same work).

**The route: anti-aliased bitmap strikes from a real typeface** — not vector outlines (filled outlines without coverage still staircase at 1 px steps; at these sizes the steps would read as a finer block, not as smooth) and not a filter over the 8×8 shapes (that smooths the blocks' corners, never their letterforms). The typeface is **Liberation Sans** (SIL Open Font License 1.1), rasterised offline at full size by `desktest-painter/gen_smoothfont.py` (PIL/freetype) into **4-bit coverage masks** — 16 levels, so an edge pixel paints ink blended over ground in 1/15 steps. Liberation over DejaVu, decided at the desk: at hero size DejaVu Bold's "12:59" is 458 px wide and crowds the 233-radius disc; Liberation Bold's is 368, its digits are tabular, and the Bold hero / Regular small-text pairing reads as one family.

**The machinery: `smoothfont.py` + `fontdata.py`** (both new, both in `update_files.txt` and the updater's fallback list — one Update now delivers v27 whole). fontdata.py is generated data only: per strike, a base64 blob — `[ascent][descent][cap_off][count]`, a 6-byte index per glyph, then the glyphs' coverage nibbles as one continuous stream. Six strikes, each subset to its duty: **hero** Bold 152 (digits + colon; line box 108), **sub** Bold 48 (digits, space, A/M/P; 33), **date** Regular 36 (the weekday/month letters + digits + space; 33), **conn_l** Bold 52 (boot headlines + the IP; 49), **conn_m** Bold 40 (boot mid lines; 37), **conn_s** Regular 27 (**full printable ASCII**; 26) — full because the Connected screen prints the owner's SSID, which is arbitrary text. Every strike also carries a **.notdef hollow box** (code 0): a character outside a subset draws the box, alone — no line ever falls back to blocks or breaks (desk-proven with an SSID of "Café ~Net!": the é is the box, the rest of the line is smooth, and the box differs from a real '?'). Total font data: 87,392 raw bytes, 118,504 bytes as fontdata.py — inside the updater's 262,144 per-file cap with room to spare. smoothfont has two doors: **`strip()`** — an opaque strip on a known flat ground (date, digital), cached, composed by row-slice copies exactly as the block strips were; and **`draw()`** — composite straight onto a non-flat ground (the boot screens letter over the dial: ticks, shade, the backlight glow), reading each glyph row's canvas segment, blending against what's actually there, writing it back as one slice. Both doors keep the project's invariants: zero framebuf prims and zero per-byte writes in every compose path; the boot screens' census actually *improved* (1,321 prims — the dial alone — 0 writes, 0 scratch reads, where the keyed-blit build spent ~2,546 + blits).

**Per surface.** *Digital*: hero "12:59" is 391×108 (was 440×88 of blocks), strip 84,456 B (was ~77 KB — same class); the bounded-cache discipline is unchanged (digitalface caches over `build_strip`, 8 entries); compose is still **0 prims** steady-state. Build cost, counted in covered pixels written: hero 18,450 (once a minute), sub-line 2,322 (the per-second worst case), date 1,635 (once a day). The hero strip carries **16 distinct colours**; the blocky strip it replaces carries exactly 2 — that difference is the whole feature, and test_faces §E asserts it. *Date*: same position and ink on all three faces, now the date strike; the line box moved to rows 83–116 (`DATE_Y = 116 − DATE_H`, `DATE_H` read from the strike's own metrics) so the descenders of "May"/"Sep" stay inside the v11 cap clearance (bottom ≤ 116 < 119). All 366 possible date strings fit the old per-character width bound (asserted). *Connected*: lines are (text, strike, cap-top) — headline + IP in conn_l, a >13-char IP drops to conn_m, prose + SSID in conn_s; the SSID is capped at 26 chars **and** fitted to 400 px of true rendered width (proportional type made the char cap the wrong tool — 26 wide capitals measure 468 px). *Setup*: same strikes; its "SSID" line is the clock's own AP name, a fixed string the conn_m subset carries whole. *Classic*: no numerals, as before — only its date line smooths, via the shared `draw_date`. `clockface.text_strip` is retired (kept for the desk's before/after comparisons; no shipped caller remains).

**One bug worth recording**: the first desk render sheared every odd-width glyph (a "5" like a landslide). Cause: the generator packs coverage as one continuous nibble stream, while the first reader assumed each glyph row started on a fresh byte. Fix: continuous-stream indexing in both readers (`build_strip`, `draw`). Even-width glyphs had masked it — the hero's "9" looked perfect while its "5" slid.

**Desk verification — full suite green, all 19 test files**, the v19 op-count guard **unmodified** (render 2,546 ≤ 5,000, prepare 8,267 ≤ 8,500, identical at backlight 0/50/100 — the painter's paths never touch the font except through `draw_date`'s slice copies, which were never prims). New checks: test_faces §E (delivery lists carry both new files; hero strip ≠ the raw scale-11 render, 16 colours vs 2; DATE_H from the strike, box inside the cap clearance, all-366 width bound; all three faces provably route their date through smoothfont — a counting wrapper — with 802 AA shade pixels measured in each face's date box); test_connected_screen §A3 (one `smoothfont.draw` per line, 776 headline AA shades counted outside the glow disc so the glow's gradient can't fake them, the Café SSID case); test_setup_screen §A2 (10 draw calls, 267 shades). The screens' prior censuses and ink thresholds passed **unchanged** — the smooth lettering puts *more* pure ink in every measured box than the blocks did (IP line 2,907 vs the 1,200 threshold). mpy-cross (v1.29.0) clean on smoothfont.py, fontdata.py, clockface.py, digitalface.py, classicface.py, connectface.py, setupface.py, updater.py. Previews: `previews/preview_v27_digital_day.png`, `preview_v27_digital_sleep.png` (pale hero, AM/PM only, date pale — the v26 night treatment in the new type), `preview_v27_connected.png` (FlagstaffNet / 192.168.1.42 stand-ins), `preview_v27_date_closeup.png` (the classic's date line at 2×), `preview_v27_before_after.png` (the same "10:09": blocks above, smooth below).

**Bench-only, as ever:** press **Update now** once (v27 rides the manifest: smoothfont.py, fontdata.py, clockface.py, digitalface.py, connectface.py, setupface.py, updater.py, update_files.txt). The update's own reboot shows the Connected screen in the new type — the IP is the first thing to judge. Then: the digital face's hero, the date line on whichever face is up, and the night treatments after the sleep window starts. Frost/Backlight remain painter-only; the classic still has no numerals, by design.

## Addendum (Nov 17, 2026, late) — v28: the METAR analog face

Mark's idea, pitched back to him and approved as drawn (*"Build it as v28 — KFLG default"*): *"I'd like to add a fourth Clock. I'd like to combine an airports flight category with an analog clock. For instance if KFLG was VFR the background color would be Green, with 'VFR' and minimal decoded info, such as winds, vis, cloud cover with the arms in the foreground."* Two new modules — **`metar.py`** (fetch/parse/cache; knows nothing about drawing) and **`metarface.py`** (the face; knows nothing about the network) — both in `update_files.txt` and in `updater.py`'s fallback `UPDATE_FILES`, so one **Update now** delivers the whole version. Face value `metar`, admin pulldown label **METAR analog**; selecting + Save switches live, no reboot, through the same dispatch contract as v26 (desk-proven byte-exact through the real `main.py`, §E below).

**The face.** The classic analog's geometry — same dial radii, same 60 ticks, creeping hour/minute — recoloured: the dial field IS the flight category. Base colours are the LiveSectional set; the field wears each at **80%** (deepened ~20%, as pitched, so it reads as a clock face and not an alarm light) and the shade ring at **64%**: VFR base (44,160,44) → field **(35,128,35)**; MVFR (36,86,214) → **(28,68,171)**; IFR (214,39,40) → **(171,31,32)**; LIFR (224,51,208) → **(179,40,166)**; NO DATA grey (128,128,128) → **(102,102,102)**. Ticks in cream. The **hands are the foreground**, as pitched: each hand drawn twice — a wider pass in the painter's INK under a cream pass — so it carries a dark edge and stays legible on all four fields; the boss is ink with a cream heart. **Second-hand decision: shipped, cream with the same ink edge** — the classic's rust is deliberately NOT carried over (rust on the IFR red would vanish; on LIFR it would fight). Header **"KFLG - VFR"** and, in the bottom arc, three decoded lines — wind (`Wind 240° at 8 kt`, gusts riding before the unit, calm and VRB spelled out), visibility (`Vis 10+ SM` — the API's own string verbatim, so `1/2` and `M1/4` stay honest), clouds (`Ceiling BKN 3,300 ft` when a BKN/OVC/VV ceiling exists, else the significant cover — Scattered outranks Few — else `Sky clear`) — plus the observation's Zulu time (`2323Z`) so staleness is visible at a glance. The text is lettered onto the static layer with `smoothfont.draw` (the boot screens' door), in two new strikes generated for this duty: **metar_h** Bold 46 (caps/digits/space/hyphen) and **metar_t** Regular 30 (the decoded vocabulary, incl. `°` — chr(176), which fits the font blob's one-byte glyph codes; the header's dash is a hyphen for the same reason an em dash can never ride them). Regenerating `fontdata.py` reproduced all six v27 strikes **byte-identical** (verified strike by strike against the v27 file); the two new strikes take fontdata.py to 154,992 bytes, inside the updater's 262,144 per-file cap. The static layer is data-keyed — `(metar.version(), stale, airport)` — and re-renders in place when the snapshot moves (a landed fetch, a stale flip, an airport change), never per frame. **Sleep**: no saturated field floods a dark room — the night layer is the shared night dial with the category demoted to a thin ring in the shade band at full base strength, pale hands stepping by the minute, no second hand, header and decoded lines in a dim pale (148,154,168); day returns in the morning. The date shows on this face too (standing rule), drawn by `draw_date` with the field colour as its ground — the box sits on flat field, clear of the ticks, so the opaque strip stays pixel-exact. Frost/Backlight/cuckoo/idle remain painter-only, exactly as on the classic and digital.

**The data.** Source: **aviationweather.gov's public API, no key** — `GET /api/data/metar?ids=<STN>&format=json`, verified from the desk before coding (a JSON array; the fields used are `icaoId`, `obsTime` (Unix epoch), `wdir`/`wspd`/`wgst`, `visib` (a number, or a string: `10+`, `1/2`, `M1/4`), `clouds[]` (`cover`/`base`), and `fltCat`). Category: the API's `fltCat` when it carries a valid one, otherwise computed from ceiling (lowest BKN/OVC/VV) and visibility with the standard bands — LIFR vis <1 SM or ceiling <500 ft; IFR vis 1–<3 or ceiling 500–<1000; MVFR vis 3–5 or ceiling 1000–3000; VFR beyond (boundaries desk-tested one by one). Transport is the updater's proven raw-socket HTTPS GET; the fetch runs only from main's housekeeping (plus one forced poll at boot when the METAR face is up, and one on an airport change), self-gated to a **~5-minute cadence of attempts** — a failure waits the full cadence and keeps the last good record; the clock loop and admin never wait on it beyond one bounded GET, the same class as the updater's own check. Failure behaviour: before the first success the face is the grey NO DATA dial (`KFLG - NO DATA`, `No report received`) and the clock is untouched; after a success the last good record stays up, and a small **STALE** joins the obs line when the observation passes **~75 minutes** — but only once the clock's time is NTP-proven (`timekeep.time_source() == "ntp"`); before NTP the board's epoch can't be trusted, so nothing is ever flagged. (Epoch math: the system clock holds local UTC-7 in the MicroPython 2000-epoch frame, so Unix = `time.time()` + 946684800 + 25200; the obs Zulu string itself is pure arithmetic on `obsTime`, identical on desk and board.)

**Admin/config.** New key `metar_airport`, default **KFLG**, edited in the Display section beside the face pulldown. Saving normalises through `metar.normalise_airport` itself (uppercase, 3–4 alphanumerics — no `str.isalnum` on MicroPython, the alphabet is spelled out): a junk entry keeps the saved value and the returned page says so. A real change makes main drop the old station's record and refetch promptly; the face re-renders on the new snapshot by itself.

**Costs.** Day static 252 prims (the classic's count — same discs + 60 ticks; the lettering is `smoothfont.draw` slice writes, not prims), night static 260 (the category ring is two more discs per band), steady compose **20 prims by day** (the edged hands: 6 band-split polys + 4 dots), **6 by night** — the classic's cost class, as required. The v19 op-count guard passes **unmodified** (the painter's paths are untouched).

**Desk verification.** New `test_metar.py`: §A dispatch/contract/admin field/delivery lists; §B the parser against fixtures (the KFLG and KMIA objects are the API's own live-captured words) — VFR/MVFR/IFR/LIFR, gusts, calm, VRB, `1/2` and `M1/4` visibility, SKC, FEW/SCT-only, lowest-of-layers ceilings, VV, `fltCat` honoured when valid and ignored when junk, and every category band boundary; §C the fetcher (cadence on attempts, identical record not bumping the version, airport change dropping + refetching, validation, the stale rule pure and NTP-gated); §D the face (field-colour pixels for VFR/IFR/NO DATA, smooth header shades, the date gate, the second hand's counterweight heart/ring and its centreline gone a second later, every printed line's ink proven inside r=230, the night treatment — dark field, zero field-colour pixels, the ring present, pale snap with seconds ignored — and the STALE flip re-rendering only the obs line's rows); §E the real `main.py` loop: painter → metar live with the fetched fixture byte-exact, then an admin airport change to KSEA refetching and landing byte-exact again. Full suite green — all 19 test files, both rollover sims and the 48-h standalone included. mpy-cross (v1.29.0) clean on metar.py, metarface.py, main.py, admin.py, updater.py, smoothfont.py, fontdata.py. Previews: `previews/preview_v28_metar_vfr.png` (KFLG, green), `preview_v28_metar_ifr.png` (KMIA, red), `preview_v28_metar_night.png` (the ring on the dark dial), `preview_v28_metar_nodata.png` (grey, waiting).

**Bench-only, as ever:** press **Update now** once (v28 rides the manifest: main.py, admin.py, updater.py, update_files.txt, metar.py, metarface.py, fontdata.py), then pick **METAR analog** in the admin face pulldown and Save. Judge: the green field and header against the preview; the decoded lines' fit in the bottom arc; the hands' dark edges on the colour; an airport change in admin (try KSEA or KMIA) landing within seconds; and after the sleep window starts, the ring on the dark dial instead of a flooded field. One honest note: the face fetches from the live aviationweather.gov API — in a hangar with no route to it, the grey NO DATA dial (or the last good report, flagged STALE once NTP agrees it's old) is the designed behaviour, not a fault.
