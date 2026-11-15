# display.py - THE DRIVER SEAM for the Painter Clock.
#
# Only file that knows the firmware route: the custom MicroPython
# v1.29 build with Espressif's ESP32_Display_Panel binding
# (`from esp_panel import Board`; see firmware/API_NOTES.md).
# Everything else draws into this module's Canvas surfaces and calls
# show(); nothing else may import a display driver.
#
#     WIDTH = HEIGHT = 480
#     init() -> bool        panel up, backlight on; False = no driver
#     canvas()              the frame Canvas (draw the next frame here)
#     dial()                the static-layer Canvas (rendered once)
#     show()                present the frame canvas (banded, below)
#     set_backlight(level)  0..255
#     is_live() -> bool     True once the real driver is running
#     board()               the esp_panel Board object (or None)
#
# ------------------------------------------------------------------
# BENCH-PROVEN CONSTRAINTS (Nov 15, 2026 - hardware-verified on the
# 2.8C; full log in firmware/API_NOTES.md). Do NOT "optimise" any of
# these away - each one cost a wedged chip and a reset at the bench:
#
#   * A full-size framebuf.FrameBuffer (480x480) WEDGES the chip.
#   * Writing through frame_buffer_addr()/uctypes WEDGES it.
#   * A single full-frame draw_bitmap (460,800 B) WEDGES it.
#   * What works, instantly: draw_bitmap of a 100x100 tile and of a
#     480x120 band (115,200 B); sustained full frames shipped as
#     4 bands of 120 lines (6-frame red/blue flip test, clean).
#
# So: frames are composed in plain bytearrays (this module's Canvas
# class draws into them with row-slice writes, never a full-size
# FrameBuffer), and show() ships the frame in 4 bands of 120 lines
# via memoryview slices - no copies, no big transfers.
#
# Second bench lesson (Nov 15, later): Python-loop drawing is far
# too slow on the board - Canvas-drawn dial render 54,410 ms, hand
# compose 20,365 ms, while show() is 40 ms. So clockface draws the
# dial and hands with genuine C framebuf primitives inside band
# windows (Canvas.band_windows(): 480x120 FrameBuffers, the proven
# size - a window fill_rect + show() was bench-verified instant).
# Canvas's Python primitives remain for figure/sprites (slow paths).
# ------------------------------------------------------------------
import framebuf
import math

WIDTH = 480
HEIGHT = 480
ROW_BYTES = WIDTH * 2            # RGB565
FRAME_BYTES = WIDTH * HEIGHT * 2  # 460,800

BAND_H = 120                     # lines per draw_bitmap call in show()
BANDS = HEIGHT // BAND_H         # 4

# Hard ceiling for any single driver transfer / FrameBuffer window:
# the 480x120 band size is the largest transfer proven safe at the
# bench (115,200 B). The failure cliff sits somewhere between this
# and a full frame (460,800 B) - stay at or under the proven size.
MAX_WINDOW_BYTES = BAND_H * ROW_BYTES  # 115,200


def _pat(colour):
    """One RGB565 pixel as 2 little-endian bytes (the byte order
    draw_bitmap and the panel expect - bench-verified Nov 15)."""
    return bytes((colour & 0xFF, (colour >> 8) & 0xFF))


class Canvas:
    """A drawing surface over a plain bytearray - the safe stand-in
    for framebuf.FrameBuffer, which cannot be used at full size on
    this firmware (see the constraints above).

    Implements the framebuf-style methods the project uses - fill,
    pixel, fill_rect, line, ellipse, blit - with row-slice writes
    and per-pixel writes only. Small regions that genuinely want
    real framebuf primitives can borrow window() (size-capped).
    """

    def __init__(self, buf):
        self.buf = buf

    # --- whole-surface ---

    def fill(self, colour):
        self.buf[:] = _pat(colour) * (WIDTH * HEIGHT)

    def copy_from(self, src):
        """Copy another Canvas (or raw 480x480 bytearray) over this
        one - how a frame starts from the pre-rendered dial layer."""
        self.buf[:] = getattr(src, "buf", src)

    # --- pixels and rects ---

    def pixel(self, x, y, colour=None):
        if colour is None:
            if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                i = (y * WIDTH + x) * 2
                return self.buf[i] | (self.buf[i + 1] << 8)
            return 0
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            i = (y * WIDTH + x) * 2
            self.buf[i] = colour & 0xFF
            self.buf[i + 1] = (colour >> 8) & 0xFF

    def fill_rect(self, x, y, w, h, colour):
        # clip to the canvas
        if x < 0:
            w += x
            x = 0
        if y < 0:
            h += y
            y = 0
        if x + w > WIDTH:
            w = WIDTH - x
        if y + h > HEIGHT:
            h = HEIGHT - y
        if w <= 0 or h <= 0:
            return
        row = _pat(colour) * w
        b = self.buf
        off = (y * WIDTH + x) * 2
        for _ in range(h):
            b[off:off + w * 2] = row
            off += ROW_BYTES

    # --- lines (Bresenham, direct byte writes) ---

    def line(self, x0, y0, x1, y1, colour):
        lo = colour & 0xFF
        hi = (colour >> 8) & 0xFF
        b = self.buf
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            if 0 <= x0 < WIDTH and 0 <= y0 < HEIGHT:
                i = (y0 * WIDTH + x0) * 2
                b[i] = lo
                b[i + 1] = hi
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    # --- ellipse (filled = row spans; outline = span endpoints) ---

    def ellipse(self, cx, cy, rx, ry, colour, fill=False):
        if rx <= 0 and ry <= 0:
            self.pixel(cx, cy, colour)
            return
        if ry <= 0:
            self.fill_rect(cx - rx, cy, 2 * rx + 1, 1, colour)
            return
        if rx <= 0:
            self.fill_rect(cx, cy - ry, 1, 2 * ry + 1, colour)
            return
        dy = -ry
        while dy <= ry:
            t = dy / ry
            dx = int(rx * math.sqrt(1.0 - t * t))
            if fill:
                self.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, colour)
            else:
                self.pixel(cx - dx, cy + dy, colour)
                self.pixel(cx + dx, cy + dy, colour)
            dy += 1
        if not fill:
            dx = -rx
            while dx <= rx:
                t = dx / rx
                dy2 = int(ry * math.sqrt(1.0 - t * t))
                self.pixel(cx + dx, cy - dy2, colour)
                self.pixel(cx + dx, cy + dy2, colour)
                dx += 1

    # --- blits ---

    def blit(self, src, x, y):
        """Opaque blit of another Canvas (same 480x480 geometry),
        clipped. Per-row slice copies - no full-frame anything."""
        sb = getattr(src, "buf", src)
        b = self.buf
        sy = 0
        while sy < HEIGHT:
            dy = y + sy
            if 0 <= dy < HEIGHT:
                sx0 = 0
                if x < 0:
                    sx0 = -x
                dx0 = x + sx0
                w = WIDTH - sx0
                if dx0 + w > WIDTH:
                    w = WIDTH - dx0
                if w > 0:
                    so = (sy * WIDTH + sx0) * 2
                    do = (dy * WIDTH + dx0) * 2
                    b[do:do + w * 2] = sb[so:so + w * 2]
            sy += 1

    # --- the stride-window helper ---

    def window(self, x, y, w, h):
        """A real framebuf.FrameBuffer over a small region of this
        canvas, via a memoryview window with stride=WIDTH - for code
        that needs genuine framebuf primitives (text, polygons) over
        a bounded area such as a hand's bounding box.

        The window's spanned bytes - (WIDTH*(h-1) + w) * 2 - must
        stay at or below MAX_WINDOW_BYTES (115,200 B, the bench-
        proven band size): a 480x120 window is the largest allowed.
        Raises ValueError past the cap or off the canvas edge."""
        if x < 0 or y < 0 or w <= 0 or h <= 0 \
                or x + w > WIDTH or y + h > HEIGHT:
            raise ValueError("window off canvas")
        span = (WIDTH * (h - 1) + w) * 2
        if span > MAX_WINDOW_BYTES:
            raise ValueError("window spans %d B > %d B cap"
                             % (span, MAX_WINDOW_BYTES))
        off = (y * WIDTH + x) * 2
        seg = memoryview(self.buf)[off:off + WIDTH * h * 2]
        if len(seg) < span:
            raise ValueError("window overruns canvas")
        return framebuf.FrameBuffer(seg, w, h, framebuf.RGB565, WIDTH)

    def band_windows(self):
        """Yield (window, y) for each horizontal band of the canvas:
        real framebuf.FrameBuffers, 480x120 with stride=WIDTH, over
        the band's rows - the same geometry show() ships. This is
        how clockface draws the dial and hands: genuine C framebuf
        primitives (fill/ellipse/poly) at C speed, band by band,
        never a full-size FrameBuffer (which wedges the chip).
        Window-local coordinates: subtract the yielded y from canvas
        y coordinates; framebuf clips at the band's edges."""
        y = 0
        while y < HEIGHT:
            yield self.window(0, y, WIDTH, BAND_H), y
            y += BAND_H


def blit_sprite(canvas, sprite, sw, sh, x, y, key):
    """Keyed sprite blit onto a Canvas: sprite is a bytes/bytearray
    of sw*sh RGB565 pixels (row-major); pixels equal to `key` are
    transparent. Per-row: only the opaque runs are slice-copied
    (plain keyed blits only - framebuf palette blits draw nothing
    on v1.29 ESP32, and a full-size FrameBuffer is banned anyway).
    Sprites are pre-rendered/pre-blurred per SPEC.md 4.2."""
    dst = canvas.buf
    src = memoryview(sprite)
    key_lo = key & 0xFF
    key_hi = (key >> 8) & 0xFF
    sy = 0
    while sy < sh:
        dy = y + sy
        if 0 <= dy < HEIGHT:
            row = sy * sw * 2
            sx = 0
            while sx < sw:
                # skip a transparent run
                while sx < sw and sprite[row + sx * 2] == key_lo \
                        and sprite[row + sx * 2 + 1] == key_hi:
                    sx += 1
                if sx >= sw:
                    break
                start = sx
                while sx < sw and not (sprite[row + sx * 2] == key_lo
                                       and sprite[row + sx * 2 + 1] == key_hi):
                    sx += 1
                # opaque run [start, sx) - clip against the canvas
                cx0 = x + start
                cx1 = x + sx
                if cx1 > 0 and cx0 < WIDTH:
                    if cx0 < 0:
                        start += -cx0
                        cx0 = 0
                    if cx1 > WIDTH:
                        sx -= cx1 - WIDTH
                        cx1 = WIDTH
                    n = (cx1 - cx0) * 2
                    so = row + start * 2
                    do = (dy * WIDTH + cx0) * 2
                    dst[do:do + n] = src[so:so + n]
        sy += 1


# --- module state ---

_board = None          # esp_panel Board object, kept alive
_live = False          # True once the real driver is running
_backlight = 255
_frame = None          # Canvas: the frame being composed
_dial = None           # Canvas: the pre-rendered static layer


def _ensure_canvases():
    global _frame, _dial
    if _frame is None:
        # 480 * 480 * 2 bytes = 460,800 each - PSRAM territory.
        _frame = Canvas(bytearray(FRAME_BYTES))
        _dial = Canvas(bytearray(FRAME_BYTES))


def init():
    """Bring the panel up through the esp_panel binding. Returns
    True if the real driver is live; False (with the canvases still
    fully usable) on stock firmware or any bring-up failure, so the
    rest of the app can run headless in Thonny."""
    global _board, _live
    _ensure_canvases()
    if _live:
        return True
    try:
        from esp_panel import Board
    except Exception as exc:
        print("display: no esp_panel in this firmware:", exc)
        return False
    try:
        b = Board()
        if not b.init():
            print("display: Board.init() returned False")
            return False
        if not b.begin():
            print("display: Board.begin() returned False")
            return False
    except Exception as exc:
        print("display: board bring-up failed:", exc)
        return False
    _board = b
    _live = True
    b.set_backlight(_backlight)
    print("display: live (esp_panel, banded show %dx%d)"
          % (BANDS, BAND_H))
    return True


def board():
    """The esp_panel Board object, or None before a live init().
    Other modules may need it (backlight is wrapped below; this is
    the escape hatch, not the routine path)."""
    return _board


def canvas():
    """The frame Canvas - draw the next frame here, then show()."""
    _ensure_canvases()
    return _frame


def dial():
    """The static-layer Canvas. A face's render_static() draws here
    once; compose() copies it into the frame canvas per frame."""
    _ensure_canvases()
    return _dial


def make_framebuffer(buf, w, h, stride=None):
    """A real framebuf.FrameBuffer over a caller-owned buffer -
    the seam for figure.py's pre-composited body rects (figure
    must not import the driver layer itself). Keep every
    buffer's spanned bytes at or under the proven band size;
    figure's per-band rect views are far under it."""
    return framebuf.FrameBuffer(buf, w, h, framebuf.RGB565,
                                w if stride is None else stride)


def frame_bytes():
    _ensure_canvases()
    return _frame.buf


def dial_bytes():
    _ensure_canvases()
    return _dial.buf


def framebuffer():
    """Back-compat name from the original SPEC sec.6 contract.
    NOTE: this returns the frame Canvas, NOT a framebuf.FrameBuffer
    - a full-size FrameBuffer wedges this firmware (see header).
    The contract was revised in the SPEC Nov 15 addendum."""
    return canvas()


# NOTE (Nov 15, 2026): a dirty-band show() lived here briefly -
# it kept a shadow frame, compared bands with memoryview == and
# re-sent only changed bands. The board probe killed it: the
# comparison alone cost 33 ms on an UNCHANGED frame (the ==
# does not reach a free memcmp in practice on this firmware),
# show() averaged 97 ms during a show against ~40 ms for the
# plain path, and show(force=True) - all four bands through the
# shadow bookkeeping - cost 146 ms. Plain 4-band show() below
# is the frost build's, restored verbatim. Do not retry
# dirty-band without a different mechanism (SPEC addendum).
def show():
    """Present the frame canvas: 4 draw_bitmap calls, one 480x120
    band each, memoryview slices (no copies). Returns True if the
    panel is live and every band was accepted."""
    if not _live or _board is None:
        return False
    buf = _frame.buf
    ok = True
    for band in range(BANDS):
        y = band * BAND_H
        seg = memoryview(buf)[y * ROW_BYTES:(y + BAND_H) * ROW_BYTES]
        if not _board.draw_bitmap(0, y, WIDTH, BAND_H, seg):
            ok = False
    return ok


def set_backlight(level):
    """0..255. Night mode / sleep face drives this."""
    global _backlight
    if level < 0:
        level = 0
    if level > 255:
        level = 255
    _backlight = level
    if _live and _board is not None:
        return bool(_board.set_backlight(level))
    return False


def backlight():
    return _backlight


def is_live():
    return _live
