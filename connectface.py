# connectface.py - the "Connected" screen (Nov 16, 2026,
# v23): what the panel shows for ~35 s after the clock joins
# Wi-Fi at boot, before the face takes over.
#
# WHY (Mark's ask, Nov 16, 2026, minutes after the v22 setup
# screen bench-verified): he set the clock up on his Flagstaff
# network, the setup screen did its job - and then the face
# came up with no word of what address the clock had landed
# on, so the admin page might as well not have existed. His
# ask, in substance: "once its connected it can display what
# the IP is for the admin page, say for 30-45 seconds."
#
# WHAT: the same painted glass as setupface - the clock's own
# frosted dial (clockface.draw_dial at the owner's backlight
# strength), lettering via clockface.text_strip blitted KEYED
# over the dial (display.blit_sprite), ticks showing through
# the gaps. The words: "Connected", what the number is FOR
# ("Admin page - type this / in a browser"), the admin
# address itself BIG (admin.py serves on port 80, so the
# bare IP in a browser is the whole address - no port, no
# path), and the network it joined, small, underneath. The
# SSID and the IP are read from the live network state at
# render time (main passes wlan.ifconfig()[0] and the joined
# SSID), never hardcoded - the screen cannot drift from the
# truth it reports.
#
# WHEN: main renders this ONCE per boot, right after the NTP
# sync (so the clock is already time-true behind the splash),
# and holds it for SPLASH_MS while servicing admin - the
# address on the glass answers in a browser while it is
# still up. Boot joins only: a plain power-cycle, the reboot
# right after a portal setup saves, and the updater's reboot
# all come through main's boot, so they all splash; a mid-run
# router blip never re-enters this path (there is no mid-run
# rejoin in the loop - the splash is a boot-stage function,
# not a connection-state one), so the face is never
# interrupted. Fail-soft like the setup screen: a splash that
# cannot be drawn prints and boot continues to the face.
import clockface
import display

# The strip ground doubles as the blit key: a magenta the dial
# never wears, so only glyph pixels land on the glass.
KEY = clockface.rgb565(255, 0, 255)

HEADLINE = "Connected"

# The layout: (text, scale, y) - glyph boxes, centred on CX.
# Scales are clockface.text_strip scales (glyph box 8*scale
# px). Every line's ink stays inside the cream disc
# (desk-verified: no ink pixel beyond r=230 of centre - the
# disc edge is 233, the tick annulus 203-227, and like the
# hands the lettering may cross a tick, never the rim). The
# admin address - the one thing the owner must copy exactly -
# gets the big scale and its own line: scale 4 while it fits
# (<= 13 chars, the common 192.168.x.x shapes), scale 3 for
# the longest dotted quads. The network name is display-only
# and capped at 26 chars so a long SSID cannot push ink at
# the rim; the join itself is untouched.
SSID_MAX = 26

_LINES = (
    (HEADLINE, 4, 92),
    ("Admin page - type this", 2, 148),
    ("in a browser", 2, 172),
    ("@IP@", None, 212),              # wlan.ifconfig()[0]
    ("Your network:", 2, 268),
    ("@SSID@", 2, 292),               # the joined network
)


def _ip_scale(ip):
    return 4 if len(ip) <= 13 else 3


def _lines(ssid, ip):
    """The layout with the two placeholders resolved from the
    live network state the caller read off the WLAN."""
    if len(ssid) > SSID_MAX:
        ssid = ssid[:SSID_MAX]
    out = []
    for text, scale, y in _LINES:
        if text == "@IP@":
            text = ip
            scale = _ip_scale(ip)
        elif text == "@SSID@":
            text = ssid
        out.append((text, scale, y))
    return out


def render(canvas, ssid, ip, backlight=50):
    """Draw the Connected screen into canvas (the frame
    canvas - the caller shows it and holds it). One static
    frame: the dial, then the lettering keyed over it.
    backlight is the config's painted-glow strength, applied
    the way main applies it for the face, so the glass
    matches the clock's own."""
    clockface.set_backlight(backlight)
    clockface.draw_dial(canvas)
    ink = clockface.INK
    for text, scale, y in _lines(ssid, ip):
        strip, w, h = clockface.text_strip(text, ink, KEY,
                                           scale)
        display.blit_sprite(canvas, strip, w, h,
                            clockface.CX - w // 2, y, KEY)
    return canvas
