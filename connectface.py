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
# strength), lettering in smoothfont's strikes composited
# over the dial (smoothfont.draw blends each glyph against
# what's actually under it, so the lettering sits on the
# glass like the hands and the date do, ticks showing
# through the gaps). v27 (Mark's ask, minutes after v26
# bench-verified): the boot screen's lettering went smooth
# with the faces' - the IP is the one thing he reads off
# this screen, and it was the blockiest text on the clock.
# The words: "Connected", what the number is FOR
# ("Admin page - type this / in a browser"), the admin
# address itself BIG (admin.py serves on port 80, so the
# bare IP in a browser is the whole address - no port, no
# path), and the network it joined, small, underneath. The
# SSID and the IP are read from the live network state at
# render time (main passes wlan.ifconfig()[0] and the joined
# SSID), never hardcoded - the screen cannot drift from the
# truth it reports. The SSID is arbitrary owner text, which
# is why the small strike (conn_s) carries FULL printable
# ASCII; a character beyond even that draws smoothfont's
# .notdef box, alone - never a fallback to blocks.
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
import smoothfont

HEADLINE = "Connected"

# The layout: (text, strike, cap_y) - cap_y is where the
# line's capitals sit, centred on CX. Every line's ink
# stays inside the cream disc (desk-verified: no ink pixel
# beyond r=230 of centre - the disc edge is 233, the tick
# annulus 203-227, and like the hands the lettering may
# cross a tick, never the rim). The admin address - the
# one thing the owner must copy exactly - gets the big
# strike and its own line: conn_l while it fits (<= 13
# chars, the common 192.168.x.x shapes), conn_m for the
# longest dotted quads. The network name is display-only:
# capped at SSID_MAX chars AND at SSID_W pixels of actual
# rendered width (the smooth font is proportional - a run
# of wide capitals is what could push ink at the rim, not
# the character count), so a long SSID cannot escape the
# disc; the join itself is untouched.
SSID_MAX = 26
SSID_W = 400

_LINES = (
    (HEADLINE, "conn_l", 92),
    ("Admin page - type this", "conn_s", 148),
    ("in a browser", "conn_s", 172),
    ("@IP@", None, 212),              # wlan.ifconfig()[0]
    ("Your network:", "conn_s", 268),
    ("@SSID@", "conn_s", 292),        # the joined network
)


def _ip_strike(ip):
    return "conn_l" if len(ip) <= 13 else "conn_m"


def _ssid_fit(ssid):
    """The SSID as it will be shown: char-capped, then
    width-capped by its true rendered width."""
    if len(ssid) > SSID_MAX:
        ssid = ssid[:SSID_MAX]
    while len(ssid) > 1 and smoothfont.text_width(
            ssid, "conn_s") > SSID_W:
        ssid = ssid[:-1]
    return ssid


def _lines(ssid, ip):
    """The layout with the two placeholders resolved from the
    live network state the caller read off the WLAN."""
    ssid = _ssid_fit(ssid)
    out = []
    for text, strike, y in _LINES:
        if text == "@IP@":
            text = ip
            strike = _ip_strike(ip)
        elif text == "@SSID@":
            text = ssid
        out.append((text, strike, y))
    return out


def render(canvas, ssid, ip, backlight=50):
    """Draw the Connected screen into canvas (the frame
    canvas - the caller shows it and holds it). One static
    frame: the dial, then the lettering composited over it.
    backlight is the config's painted-glow strength, applied
    the way main applies it for the face, so the glass
    matches the clock's own."""
    clockface.set_backlight(backlight)
    clockface.draw_dial(canvas)
    ink = clockface.INK
    for text, strike, y in _lines(ssid, ip):
        smoothfont.draw(canvas, text, clockface.CX, y,
                        strike, ink)
    return canvas
