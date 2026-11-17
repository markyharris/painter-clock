# setupface.py - the Wi-Fi setup screen (Nov 16, 2026, v22):
# what the panel shows while the clock sits in its setup
# portal.
#
# WHY (Mark's field report, Nov 16, 2026): he moved the clock
# to a new home, powered it up with no valid Wi-Fi for the
# place, and the screen stayed BLACK for the whole portal
# session - the portal worked (he set it up from his phone),
# but the clock looked dead. Nothing in the portal path ever
# composed a frame, and with the RTC battery-less there was
# no face to draw anyway. His ask: when the Wi-Fi can't
# connect, the display should come up with a stylized message
# on how to set the Wi-Fi up.
#
# WHAT: the clock's own frosted dial (clockface.draw_dial at
# the owner's backlight strength - the same static layer the
# face wears), with the instructions painted on the glass in
# the project's lettering: clockface.text_strip glyphs blitted
# KEYED over the dial (display.blit_sprite), so the lettering
# sits on the glass like the hands and the date do, ticks
# showing through the gaps. The network name and the fallback
# address are read from prov's own constants at render time,
# so the screen can never drift from what the portal actually
# runs. There is deliberately no figure: three legible steps
# plus the fallback fill a 480 px round dial, and the empty
# glass is the honest picture anyway - nobody is home until
# he is connected.
#
# WHEN: main._enter_portal() renders this ONCE into the frame
# canvas and shows it, BEFORE prov.run_portal() starts - the
# owner sees life within seconds of plugging in, and the
# static frame then sits untouched for the whole portal
# session (no animation loop competing with the portal's
# sockets; the panel holds a static image for free). Setup
# completing reboots into the normal face, as before.
import clockface
import display
import prov

# The strip ground doubles as the blit key: a magenta the dial
# never wears, so only glyph pixels land on the glass.
KEY = clockface.rgb565(255, 0, 255)

HEADLINE = "Wi-Fi setup"

# The layout: (text, scale, y) - glyph boxes, centred on CX.
# Scales are clockface.text_strip scales (glyph box 8*scale
# px); the words are kept short enough that every line's ink
# stays inside the cream disc (desk-verified: no ink pixel
# beyond r=230 of centre - the disc edge is 233, the tick
# annulus 203-227, and like the hands the lettering may cross
# a tick, never the rim). The two values the owner must copy
# exactly - the network name and the fallback address - get
# the big scale and their own lines.
_LINES = (
    (HEADLINE, 4, 124),
    ("1. On your phone, join", 2, 176),
    ("@SSID@", 3, 200),                # prov.AP_SSID
    ("2. A setup page opens", 2, 240),
    ("by itself. Pick your", 2, 264),
    ("network, type password", 2, 288),
    ("3. This clock restarts", 2, 320),
    ("and connects itself", 2, 344),
    ("No page? Browse to", 2, 376),
    ("@IP@", 3, 398),                  # prov.AP_IP
)


def _lines():
    """The layout with the two placeholders resolved from
    prov's constants - the name the owner must join and the
    fallback address, exactly as the portal runs them."""
    out = []
    for text, scale, y in _LINES:
        if text == "@SSID@":
            text = prov.AP_SSID
        elif text == "@IP@":
            text = prov.AP_IP
        out.append((text, scale, y))
    return out


def render(canvas, backlight=50):
    """Draw the setup screen into canvas (the frame canvas -
    the caller shows it). One static frame: the dial, then
    the lettering keyed over it. backlight is the config's
    painted-glow strength, applied the way main applies it
    for the face, so the glass matches the clock's own."""
    clockface.set_backlight(backlight)
    clockface.draw_dial(canvas)
    ink = clockface.INK
    for text, scale, y in _lines():
        strip, w, h = clockface.text_strip(text, ink, KEY,
                                           scale)
        display.blit_sprite(canvas, strip, w, h,
                            clockface.CX - w // 2, y, KEY)
    return canvas
