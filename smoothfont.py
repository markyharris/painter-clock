# smoothfont.py - the SMOOTH font (Nov 17, 2026, v27):
# real typeface glyphs where v26 grew the firmware's 8x8
# bitmap to scale 11 and Mark asked for "a font that is
# much smoother rather than the block that we have now".
#
# The typeface is Liberation Sans (SIL Open Font License
# 1.1), rasterised OFFLINE at full size by the desk
# generator (desktest-painter/gen_smoothfont.py) into
# 4-bit coverage masks - fontdata.py, one strike per text
# duty, each subset to the glyphs that duty can print:
#
#   hero    Bold 152   the digital face's HH:MM
#   sub     Bold 48    its seconds + AM/PM sub-line
#   date    Regular 36 the shared date line (all faces)
#   conn_l  Bold 52    boot screens: headlines, the IP
#   conn_m  Bold 40    boot screens: mid lines
#   conn_s  Regular 27 boot screens: prose + the SSID -
#                      FULL printable ASCII, because the
#                      SSID is arbitrary owner text
#
# Every strike also carries a .notdef hollow box (code 0):
# a character outside a subset draws the box, alone - a
# line never falls back to the block font, never breaks.
#
# Rendering is blending, not growing pixels: a glyph pixel
# with coverage c paints ink mixed with what's under it in
# proportion c/15, so curves and diagonals step through 14
# intermediate shades instead of staircasing. Two doors:
#
#   strip(s, strike, ink, ground) -> (bytes, w, h)
#       an OPAQUE strip on a known flat ground (the date,
#       the digital face) - the draw_date pattern: cached,
#       composed into the frame by row-slice copies, so a
#       steady frame costs zero prims and zero per-byte
#       writes, exactly as the block strips did.
#   draw(canvas, s, cx, cap_y, strike, ink) -> width
#       composite straight onto a canvas whose ground is
#       NOT flat (the boot screens letter over the dial -
#       ticks, glow and all): per glyph row, the canvas's
#       own row segment is read, blended in a scratch
#       bytearray, and written back as ONE slice - still
#       zero per-byte writes into the frame buffer. These
#       screens render once per boot, so the per-pixel
#       blend is paid once, never per frame.
#
# Blob layout (fontdata.STRIKES[name], base64, joined and
# decoded on first use of the strike):
#   [ascent][descent][cap_off][count]
#   count x [code][advance][w][h][xoff+32][yoff]
#   glyph data in index order: w*h coverage nibbles,
#   row-major, high nibble first.
# ascent/descent are the strike's line box measured from
# its own glyphs, so every strip of a strike is exactly
# ascent+descent tall and shares one baseline.
import binascii

import fontdata

_STRIKE_MAX = 12         # the strip cache's bound (below)
_strikes = {}
_cache = {}

build_writes = 0         # covered pixels written by the
                         # last build_strip (the desk tests
                         # read it; the board never does)


def _pat(colour):
    """One RGB565 pixel as 2 little-endian bytes - the
    project's byte order (display.py's, kept local)."""
    return bytes((colour & 0xFF, (colour >> 8) & 0xFF))


def _blend(ink, bg, cov):
    """ink over bg at coverage cov/15, in RGB565 component
    space, rounded - cov 15 is exactly ink, cov 0 exactly
    bg (the +7 rounding preserves both endpoints)."""
    r = (((ink >> 11) & 31) * cov
         + ((bg >> 11) & 31) * (15 - cov) + 7) // 15
    g = (((ink >> 5) & 63) * cov
         + ((bg >> 5) & 63) * (15 - cov) + 7) // 15
    b = ((ink & 31) * cov + (bg & 31) * (15 - cov) + 7) // 15
    return (r << 11) | (g << 5) | b


def _strike(name):
    """The parsed strike: header, glyph index (code ->
    (advance, w, h, xoff, yoff, data offset)) and the raw
    blob the offsets index into. Parsed once, lazily."""
    st = _strikes.get(name)
    if st is not None:
        return st
    raw = binascii.a2b_base64("".join(fontdata.STRIKES[name]))
    count = raw[3]
    glyphs = {}
    pos = 4
    off = 4 + count * 6
    for _ in range(count):
        code, adv, w, h, xb, yoff = raw[pos:pos + 6]
        glyphs[code] = (adv, w, h, xb - 32, yoff, off)
        off += (w * h + 1) // 2
        pos += 6
    st = {"asc": raw[0], "desc": raw[1], "cap_off": raw[2],
          "glyphs": glyphs, "data": raw}
    _strikes[name] = st
    return st


def metrics(name):
    """(ascent, descent, cap_off) - the strike's line box
    and where capitals sit inside it."""
    st = _strike(name)
    return st["asc"], st["desc"], st["cap_off"]


def strike_height(name):
    st = _strike(name)
    return st["asc"] + st["desc"]


def _glyph(st, ch):
    """The glyph record for ch, or the strike's .notdef
    box when the subset doesn't carry it."""
    g = st["glyphs"].get(ord(ch))
    if g is None:
        g = st["glyphs"][0]
    return g


def text_width(s, name):
    """The advance width of s in the named strike -
    unknown characters measure as the .notdef box they
    will draw as."""
    st = _strike(name)
    w = 0
    for ch in s:
        w += _glyph(st, ch)[0]
    return w


def build_strip(s, name, ink, ground):
    """s as an opaque strip (bytes, width, height) on
    ground, ink blended through the coverage masks.
    Uncached - callers with a per-second string keep their
    own bounded cache (digitalface does); strip() below
    is the cached door for slow-changing strings."""
    global build_writes
    st = _strike(name)
    h = st["asc"] + st["desc"]
    gs = []
    w = 0
    for ch in s:
        g = _glyph(st, ch)
        gs.append(g)
        w += g[0]
    strip = bytearray(_pat(ground) * (w * h))
    shades = [_pat(_blend(ink, ground, c)) for c in range(16)]
    data = st["data"]
    writes = 0
    pen = 0
    for adv, gw, gh, xoff, yoff, off in gs:
        if gw and gh:
            nib0 = off * 2     # the glyph's first coverage
                               # nibble: the mask is one
                               # continuous stream, rows
                               # packed end to end
            for r in range(gh):
                nrow = nib0 + r * gw
                drow = ((yoff + r) * w + pen + xoff) * 2
                for cx in range(gw):
                    nib = nrow + cx
                    byte = data[nib >> 1]
                    cov = (byte >> 4) if not (nib & 1) \
                        else (byte & 15)
                    if cov:
                        do = drow + cx * 2
                        strip[do:do + 2] = shades[cov]
                        writes += 1
        pen += adv
    build_writes = writes
    return bytes(strip), w, h


def strip(s, name, ink, ground):
    """build_strip behind a small bounded cache (the
    date's pattern: a day string and a night string are
    the whole working set; cleared whole when it fills,
    never grown past _STRIKE_MAX entries)."""
    key = (s, name, ink, ground)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    if len(_cache) >= _STRIKE_MAX:
        _cache.clear()
    hit = build_strip(s, name, ink, ground)
    _cache[key] = hit
    return hit


def draw(canvas, s, cx, cap_y, name, ink):
    """Composite s onto canvas, centred on cx, with the
    capitals' tops at cap_y - for grounds that are not
    flat (the boot screens' dial). Per glyph row: read the
    canvas's row segment, blend the covered pixels against
    what's actually there, write the segment back as one
    slice. Returns the advance width drawn."""
    st = _strike(name)
    w = 0
    gs = []
    for ch in s:
        g = _glyph(st, ch)
        gs.append(g)
        w += g[0]
    top = cap_y - st["cap_off"]
    buf = canvas.buf
    data = st["data"]
    pen = cx - w // 2
    for adv, gw, gh, xoff, yoff, off in gs:
        gx = pen + xoff
        if gw and gh:
            nib0 = off * 2
            x0 = gx if gx > 0 else 0
            x1 = gx + gw
            if x1 > 480:
                x1 = 480
            if x1 > x0:
                for r in range(gh):
                    y = top + yoff + r
                    if y < 0 or y > 479:
                        continue
                    nrow = nib0 + r * gw
                    do = (y * 480 + x0) * 2
                    seg = bytearray(buf[do:do + (x1 - x0) * 2])
                    for cx in range(x0 - gx, x1 - gx):
                        nib = nrow + cx
                        byte = data[nib >> 1]
                        cov = (byte >> 4) if not (nib & 1) \
                            else (byte & 15)
                        if cov:
                            so = cx * 2
                            bg = seg[so] | (seg[so + 1] << 8)
                            out = _blend(ink, bg, cov)
                            seg[so] = out & 0xFF
                            seg[so + 1] = (out >> 8) & 0xFF
                    buf[do:do + len(seg)] = seg
        pen += adv
    return w
