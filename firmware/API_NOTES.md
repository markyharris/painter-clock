# Painter Clock firmware — API notes & build recipe

Built Nov 14, 2026. **Status: builds and links clean; NOT yet flashed
or run on hardware** (no board attached to the build VM). First bench
session settles the open questions at the bottom.

## v2 (Nov 15, 2026) — use `painter-firmware_v2.bin`, not v1

v1 was flashed at the bench: REPL alive, I2C scan perfect, but
`Board().init()` returns False **by construction** — no board
configuration was compiled in (the supported-board conf header was
never included by any TU, and its own enable flag was 0). v2 fixes
both: the panel wrapper component now puts the clone root on the
include path, and `esp_panel_board_supported_conf.h` (clone root)
has `ESP_PANEL_BOARD_DEFAULT_USE_SUPPORTED` flipped to (1) — note
for the recipe in step 1 below: that flip is required, and a `-D`
compile definition does NOT substitute (the file's unconditional
`#define` overrides it). Verified from the build artifacts: the
default-config dep files list the conf, the ELF contains
`ESP_PANEL_BOARD_DEFAULT_CONFIG`, and the merged bin contains the
string `Waveshare:ESP32_S3_TOUCH_LCD_2_8_C`. Artifact:
`painter-firmware_v2.bin` (1,886,960 B, flash at 0x0). Library
logging was investigated but NOT enabled — no clean macro gate
exists (the utils conf already selects printf at INFO); the v1
silence is most plausibly console routing. Full narrative:
`../firmware-build/build_log.md`, v2 section.

## Artifact

- `painter-firmware.bin` (this directory) — combined image,
  1,877,056 bytes, flash at **0x0**:
  `esptool --chip esp32s3 write_flash 0x0 painter-firmware.bin`
  (flash mode dio, 80 MHz, size 16 MB are baked into the image
  headers). Thonny 5's flasher with family **ESP32-S3** and a local
  image works too.
- Or flash the three parts from
  `firmware-build/micropython/ports/esp32/build-PAINTER_S3-SPIRAM_OCT/`:
  `bootloader/bootloader.bin` @ 0x0 (19,232 B),
  `partition_table/partition-table.bin` @ 0x8000 (3,072 B),
  `micropython.bin` @ 0x10000 (1,811,520 B; 2,382,784 B free in the
  4 MiB factory partition).

Partition layout (verified from the built table): nvs 0x9000/24K,
phy_init 0xf000/4K, factory app 0x10000/4M, vfs (FAT) 0x410000/12224K.

## What it is

Stock MicroPython **v1.29.0** (GENERIC_S3 feature set, SPIRAM_OCT
variant: octal PSRAM, 240 MHz) on ESP-IDF **v5.5.2**, plus Espressif's
**ESP32_Display_Panel v1.0.5** with its MicroPython binding, configured
for the **Waveshare ESP32-S3-Touch-LCD-2.8C** via the library's own
board definition
(`esp32_display_panel/src/board/supported/waveshare/BOARD_WAVESHARE_ESP32_S3_TOUCH_LCD_2_8_C.h`:
ST7701 over RGB, 480×480 RGB565, PCLK 18 MHz, bounce buffer = width×10,
3-wire SPI panel control via the TCA9554 expander, GT911 touch on I2C,
backlight GPIO6 PWM). Board selection is the
`BOARD_WAVESHARE_ESP32_S3_TOUCH_LCD_2_8_C` define in
`esp_panel_board_supported_conf.h`.

## Python API — module `esp_panel`

Source: `esp32_display_panel/mpy_support/esp_panel_mp_module.c`
(module registration, lines 15–27) and `esp_panel_mp_board.cpp`
(methods and locals table, lines 25–132). Upstream exposes exactly one
class and — critically — **no way to push pixels**:

```python
from esp_panel import Board
b = Board()
b.init()           -> bool   # allocate/configure the board object
b.begin()          -> bool   # start panel, touch, backlight
b.deinit()         -> bool
b.color_bar_test() -> bool   # built-in colour-bar pattern; first-light test
```

### Painter Clock additions (ours, not upstream)

Added to `esp_panel_mp_board.cpp` (marked "Painter Clock additions",
lines 67–121), wrapping the library's C++ API
(`src/drivers/lcd/esp_panel_lcd.hpp:441` `drawBitmap`,
`:635` `getFrameBufferByIndex`; `src/board/esp_panel_board.hpp:140`
`getBacklight`; `src/drivers/backlight/esp_panel_backlight.hpp:75`
`setBrightness`):

```python
b.draw_bitmap(x, y, w, h, buf) -> bool
    # buf: any buffer object (bytes / bytearray / memoryview) of
    # RGB565 pixels, row-major; raises ValueError if len < w*h*2.
    # The guaranteed-correct pixel path (copies into the scanout
    # frame buffer via the driver).

addr = b.frame_buffer_addr() -> int
    # Address of the driver's frame buffer 0, or 0 if unavailable.
    # Zero-copy path for display.py:
    #   import uctypes
    #   fb_mem = uctypes.bytearray_at(addr, 480*480*2)
    #   fb = framebuf.FrameBuffer(fb_mem, 480, 480, framebuf.RGB565)

b.set_backlight(level) -> bool
    # level 0..255 (clamped), mapped to the driver's 0..100 percent.
```

### Mapping onto display.py's contract

| display.py | Implementation |
|---|---|
| `init()` | `Board()`, `init()`, `begin()`; keep the object alive |
| `framebuffer()` | `framebuf.FrameBuffer` over `uctypes.bytearray_at(frame_buffer_addr(), 460800)`, RGB565 |
| `show()` | Zero-copy: nothing to call (bench must confirm — see below). Copy path: `draw_bitmap(0, 0, 480, 480, fb_buffer)` |
| `set_backlight(v)` | `set_backlight(v)` |
| `is_live()` | Board object exists and `frame_buffer_addr() != 0` |

## Build recipe (exact, reproducible)

Tree: everything under `~/workspace/painter-clock/firmware-build/`
(clones: `esp-idf/` v5.5.2, `micropython/` v1.29.0,
`esp32_display_panel/` v1.0.5, `esp-lib-utils/` 0.3.0,
`ESP32_IO_Expander/` 1.1.1). Full narrative in `../firmware-build/build_log.md`.

1. **Panel library prep** (in the clone):
   - Enable `BOARD_WAVESHARE_ESP32_S3_TOUCH_LCD_2_8_C` in
     `src/board/esp_panel_board_supported_conf.h`.
   - `esp_panel_drivers_conf.h`: `BUS_USE_ALL` 1→0 (upstream mpy doc
     warns `begin()` crashes with USE_ALL), `BUS_USE_RGB=1`,
     `BUS_USE_I2C=1`, `LCD_USE_ST7701=1`, `TOUCH_USE_GT911=1`,
     `EXPANDER_USE_TCA95XX_8BIT=1`, all `*_COMPILE_UNUSED_DRIVERS`→0.
   - Prune unused LCD/touch driver sources to `firmware-build/pruned/`
     (71 files moved; 31 kept) — also keeps command lines short.
   - Relax the `esp-lib-utils` version constraint in the panel's and
     expander's `idf_component.yml` (`0.2.*` → `>=0.2`; clone is 0.3.0).
   - Extend `mpy_support/esp_panel_mp_board.cpp` with the three
     methods above (note: v1.29 spells the 4-arg macro
     `MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN`, py/obj.h:405).
   - Do **NOT** do the upstream doc's step 5 (copying esp_lcd headers
     into `mpy_support/`): on IDF 5.5 those headers use `#pragma once`,
     the copies double-define against the real ones, and the binding
     TU fails with conflicting declarations. The real headers are
     reachable without copies.
2. **Custom board** `micropython/ports/esp32/boards/PAINTER_S3`
   (copy of ESP32_GENERIC_S3): `sdkconfig.board` sets
   FLASHSIZE_16MB; `partitions-16MiB.csv` in the board dir (layout
   above); `mpconfigboard.cmake` appends `sdkconfig.board` and
   `EXTRA_COMPONENT_DIRS` (see step 3).
3. **Integration — components, not usermods.** The upstream route
   (libraries as usermod INTERFACE libs) cannot work here: MicroPython
   feeds every usermod source to the QSTR preprocessor in ONE shell
   command, and the baseline build already sits within ~2 KB of the
   kernel's 131,072-char MAX_ARG_STRLEN cap — any usermod addition
   overflows it ("Argument list too long"). Instead:
   - Wrapper components in `firmware-build/components/`
     (`esp32_display_panel/`, `esp32_io_expander/`, `esp-lib-utils/`):
     each is ONLY a CMakeLists.txt globbing its clone's sources with
     plain-name REQUIRES (panel → `driver esp_lcd esp32_io_expander
     esp-lib-utils`; expander → `driver esp-lib-utils`; utils →
     `PRIV_REQUIRES pthread`). **No `idf_component.yml` in the
     wrappers**, so the component manager never sees them — its
     `espressif__*` name mangling is what killed the path-dependency
     route (attempts 3–4 in the build log).
   - `micropython/ports/esp32/esp32_common.cmake`: append the three
     names to `IDF_COMPONENTS` just before "# Register the main IDF
     component", so `main` requires them.
   - `firmware-build/micropython.cmake` (the USER_C_MODULES file):
     binding-only usermod lib — sources are just
     `esp_panel_mp_module.c` + `esp_panel_mp_board.cpp`; include dirs
     panel/src, panel/mpy_support, esp-lib-utils/src,
     ESP32_IO_Expander/src; `-DESP_PLATFORM`, gnu++17.
   - `main/idf_component.yml` stays stock.
4. **The /fb bind mount (required).** Even with the component route,
   the QSTR command was 132,766 chars from the deep workspace path.
   Bind-mounting the tree at `/fb` for the MicroPython side cut it to
   97,281. Mounts do not persist across sessions here — recreate each
   time, and note the generated files (micropython.cmake, wrapper
   CMakeLists, board cmake) contain `/fb` paths:
   ```
   mount --bind /home/hatch/workspace/painter-clock/firmware-build /fb
   ```
   **Caveat:** export ESP-IDF from the REAL path, not /fb —
   `idf_tools.py` refuses activation from /fb ("tool
   riscv32-esp-elf-gdb has no installed versions"). Order matters:
   ```
   cd /home/hatch/workspace/painter-clock/firmware-build
   . ./esp-idf/export.sh
   make -C /fb/micropython/ports/esp32 BOARD=PAINTER_S3 \
     BOARD_VARIANT=SPIRAM_OCT USER_C_MODULES=/fb/micropython.cmake -j4
   ```
   After changing the component source set, wipe
   `micropython/ports/esp32/build-PAINTER_S3-SPIRAM_OCT` first (stale
   CMake globs reference pruned files).
5. Merge (already done for the artifact):
   ```
   python -m esptool --chip esp32s3 merge_bin \
     -o painter-firmware.bin --flash_mode dio --flash_freq 80m \
     --flash_size 16MB 0x0 bootloader/bootloader.bin \
     0x8000 partition_table/partition-table.bin \
     0x10000 micropython.bin
   ```

## Bench results — Nov 15, 2026 (board-tested, Mark at the bench)

- `begin()` lights the panel: `color_bar_test()` True and clean
  color bars confirmed by photo. init()/begin() log their success
  lines; the two ST7701 3Ah/36h warnings and the GT911 address
  warning are benign (touch config reads fine right after).
- Zero-copy is DEAD: `fb.fill()` over `uctypes.bytearray_at(
  frame_buffer_addr(), ...)` wedged the chip hard (no Ctrl-C, reset
  required). A full-size `framebuf.FrameBuffer` over a plain
  bytearray also wedged. Do not use either.
- A single full-frame `draw_bitmap(0, 0, 480, 480, ...)` (460,800 B)
  also wedges the chip. Large single transfers are the poison;
  the cliff sits between 115 KB and 460 KB.
- What works, all instant and photo-confirmed: `draw_bitmap` of a
  100×100 tile, and of a 480×120 band (115,200 B).
- **Display route for display.py: compose the frame in a plain
  full-frame bytearray (no full-size FrameBuffer), ship it with
  `draw_bitmap` in 120-line bands — 4 calls per frame.**
- Sustained animation proven the same session: a REPL loop flipped
  six full frames (red/blue alternating, 24 band draws total,
  0.5 s apart) with no wedge and a clean return to the prompt.
  Full red and full blue frames photo-confirmed.
- Frame rate of a full Python redraw at 480×480, and tearing with the
  width×10 bounce buffer.
- GT911 touch and the TCA9554 expander responding at their expected
  I2C addresses under this config (not needed by the clock's display
  path, but `begin()` initialises them).
