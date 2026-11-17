# admin.py - the Painter Clock admin page, port 80.
#
# Same shape as Mark's other Micro builds' admin pages: status,
# settings, Update (flag + Update now), rehome instructions,
# restart. Deliberately NON-blocking: the animation loop calls
# step() every frame and step() services at most one pending
# request with a zero-timeout accept - the little man never waits
# on a browser.
#
# Settings live in config.json on the board (never overwritten by
# the updater). Saving settings sets app["changed"] = True;
# main.py notices and applies what it can live (brightness, face,
# frost, backlight, show_date).
#
# Config keys (Nov 15, 2026): face, brightness, frost (the
# frosted-glass strength 0..100 - 0 is the sharp look), backlight
# (the painted light behind him, 0..100 - v18; 0 is the pre-v18
# dial), show_date
# (the date line every face draws - day and month; v11), and the
# sleep keys - sleep_enabled / sleep_start / sleep_end, whose
# behaviour (lights out, he lies down, the hands snap pale;
# SPEC Nov 13 addendum) landed in v15. cuckoo_enabled (v20)
# silences the hourly cuckoo ritual without code. The old skeleton's
# night_mode / night_dim checkbox fields are gone, and so is
# tz_offset_h: the timezone is fixed UTC-7 in timekeep.py.
#
# v24 (Nov 16, 2026): the admin UX pass. Presentation only - the
# config keys, the POST handlers' semantics and the apply-live
# paths are exactly as before. The page is organised into
# colour-tinted sections in the Visual Logbook admin's manner
# (a fieldset + legend per section, a pastel tint each); the
# three 0..255 / 0..100 settings are real range sliders with a
# live numeric readout; a pointer-clock icon (ICON_SVG below)
# is the browser tab's favicon and sits beside the title in the
# header; and every action lands back on the admin page itself -
# Save / Try-it / Try-cuckoo return the page with a .msg note,
# while the two rebooting actions (Update now, Restart) return
# a small auto-refreshing page that reloads the admin page once
# the clock is back, instead of the old bare-text landings.
import json
import socket

import show as showmod
import updater

# Idle-routine Try-it buttons (idle life v1, Nov 15, 2026):
# (routine name in show.IDLE_DUR, button label). A press queues
# the routine in the app dict ("tryit"); main.py hands it to
# show.queue_idle(), and it runs at the next safe gap.
TRYIT = (("watch", "Wristwatch check"), ("cap", "Cap-off brow wipe"),
         ("sip", "Mug sip"), ("scratch", "Head scratch"),
         ("rear", "Rear scratch"), ("apple", "Apple snack"),
         ("hanky", "Hanky nose-blow"), ("phone", "Phone call"),
         ("plane", "Plane flyby"), ("shoulder", "Shoulder roll"),
         ("bucket", "Move the paint bucket"),
         ("crossed", "Arms crossed"))

DEFAULT_CONFIG = {
    # Clock face module (SPEC Nov 15 addendum): "painter"
    # (clockface.py) | "classic" | "digital" - classic/digital
    # not built yet; unknown names fall back to the painter.
    "face": "painter",
    "brightness": 255,       # panel backlight, 0..255
    "frost": 55,             # frosted glass, 0..100 (0 = sharp)
    "backlight": 50,         # painted light behind him, 0..100
                             # (0 = the pre-v18 dial; v18)
    "show_date": True,       # the date on the face (v11)
    "cuckoo_enabled": True,  # the hourly cuckoo ritual (v20)
    "sleep_enabled": False,  # lights-out hours (v15 behaviour)
    "sleep_start": "22:00",
    "sleep_end": "06:00",
}

FACES = ("painter", "classic", "digital")

# The tab / header icon: an analog clock face, hands (pointers)
# at the classic 10:10, in the dial's own cream and ink. One
# SVG literal serves both spots - inline in the header, and as
# the favicon via a data URI derived from it - so the pair can
# never drift and no extra file ships.
ICON_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' "
            "viewBox='0 0 32 32'>"
            "<circle cx='16' cy='16' r='13' fill='#fff8ea' "
            "stroke='#5b4636' stroke-width='2.6'/>"
            "<path d='M16 5.5v2.4M16 24.1v2.4M5.5 16h2.4"
            "M24.1 16h2.4' stroke='#5b4636' stroke-width='1.7'/>"
            "<path d='M16 16L10.2 12.6M16 16L23.8 11.4' "
            "stroke='#5b4636' stroke-width='2.5' "
            "stroke-linecap='round' fill='none'/>"
            "<circle cx='16' cy='16' r='1.9' fill='#5b4636'/>"
            "</svg>")
ICON_URI = ("data:image/svg+xml;utf8,"
            + ICON_SVG.replace("#", "%23").replace("<", "%3C")
            .replace(">", "%3E"))

_srv = None


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open("config.json") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    with open("config.json", "w") as f:
        json.dump(cfg, f)


def start():
    global _srv
    if _srv is not None:
        return
    _srv = socket.socket()
    _srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _srv.bind(("0.0.0.0", 80))
    _srv.listen(2)
    _srv.settimeout(0)
    print("admin: listening on port 80")


def _valid_hhmm(s):
    """'HH:MM' with real ranges - the sleep hours' only shape."""
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        return False
    try:
        h = int(s[0:2])
        m = int(s[3:5])
    except ValueError:
        return False
    return 0 <= h < 24 and 0 <= m < 60


def _face_options(current):
    out = ""
    for name in FACES:
        sel = " selected" if name == current else ""
        out += '<option value="%s"%s>%s</option>' % (name, sel, name)
    return out


def _show_date_options(current):
    out = ""
    for name, val in (("on", True), ("off", False)):
        sel = " selected" if val == bool(current) else ""
        out += '<option value="%s"%s>%s</option>' % (name, sel, name)
    return out


def _tryit_buttons():
    # These live inside the settings <form> (the Cuckoo & idle
    # life section); formaction posts each to /tryit instead,
    # whose handler reads only the "routine" field - the same
    # semantics as the old separate form.
    out = ""
    for name, label in TRYIT:
        out += '<button name="routine" value="%s" ' \
            'formaction="/tryit">%s</button> ' % (name, label)
    return out


def _slider(name, label, top, value):
    """One range slider with a live numeric readout: dragging
    updates the number beside it (the oninput), and the field
    name / range are the config key's own, unchanged."""
    return ('<p>%s <input type="range" name="%s" min="0" '
            'max="%d" value="%s" oninput="document.'
            'getElementById(\'v_%s\').textContent=this.value"> '
            '<span class="val" id="v_%s">%s</span></p>'
            % (label, name, top, value, name, name, value))


def _page(app, msg=""):
    u = updater.STATE
    upd = "UPDATE AVAILABLE (%d file(s))" % u["files"] \
        if u["available"] else "Up to date"
    if u["failed"]:
        upd = "Update check failed: %s" % u["failed"]
    cfg = app["config"]
    msg_html = '<p class="msg">%s</p>' % msg if msg else ""
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Painter Clock</title>
<link rel="icon" href="%s">
<style>
body{font-family:sans-serif;margin:16px;max-width:860px}
fieldset{margin:12px 0;border:1px solid #bbb;border-radius:6px}
legend{font-weight:bold;padding:0 4px}
input{margin:2px}
input[type=range]{width:230px;vertical-align:middle}
.val{display:inline-block;min-width:2.2em;font-weight:bold}
.msg{background:#efe;border:1px solid #9c9;padding:6px}
.sec-status{background:#e9f1fd}
.sec-display{background:#e7f6ec}
.sec-frost{background:#e2f5f7}
.sec-sleep{background:#e9e4f5}
.sec-idle{background:#fff6d9}
.sec-update{background:#fdeee2}
.sec-system{background:#fdeaea}
h1 svg{height:30px;width:30px;vertical-align:-6px}
</style></head><body>
<h1>%s Painter Clock</h1>
%s
<fieldset class="sec-status"><legend>Status</legend>
<p>Time: %s (source: %s)<br>
Wi-Fi: %s<br>
Display: %s &middot; Uptime: %s &middot; Code: %s<br>
Idle: %s<br>
Update: %s</p></fieldset>
<form method="POST" action="/settings">
<fieldset class="sec-display"><legend>Display</legend>
<p>Face: <select name="face">%s</select></p>
%s
<p>Show date: <select name="show_date">%s</select></p>
</fieldset>
<fieldset class="sec-frost"><legend>Frost &amp; backlight</legend>
%s
%s
</fieldset>
<fieldset class="sec-sleep"><legend>Sleep</legend>
<p><label><input type="checkbox" name="sleep_enabled" %s>
Lights out - he sleeps</label> from
<input name="sleep_start" size="5" value="%s"> to
<input name="sleep_end" size="5" value="%s"> (HH:MM, 24h)<br>
<i>In those hours the room goes dark and he lies down to
sleep; the hands keep time in pale ink.</i></p>
</fieldset>
<fieldset class="sec-idle"><legend>Cuckoo &amp; idle life</legend>
<p><label><input type="checkbox" name="cuckoo_enabled" %s>
Cuckoo on the hour</label><br>
<i>On the hour, after he has repainted both hands, he leans
in and wipes a clear circle in the frost - his face, sharp,
for a moment. Never during lights-out hours.</i></p>
<p><button type="submit">Save settings</button></p>
<p>Idle routines - try one (it runs at the next gap):<br>
%s
<button formaction="/trycuckoo">Try the cuckoo</button></p>
</fieldset>
</form>
<fieldset class="sec-update"><legend>Update</legend>
<p>Update: %s</p>
<form method="POST" action="/update"><p>
<button type="submit">Update now</button></p></form>
</fieldset>
<fieldset class="sec-system"><legend>System</legend>
<form method="POST" action="/restart"><p>
<button type="submit">Restart</button></p></form>
<h3>Rehome (new Wi-Fi / new owner)</h3>
<p>Unplug. Plug back in and, just AFTER it starts, hold the BOOT
button for a second. The clock starts the <b>PainterClock-Setup</b>
network - join it with a phone and follow the captive portal.</p>
</fieldset>
<hr>
<p><i>An homage to Maarten Baas and his Schiphol Clock
(Amsterdam Airport Schiphol, 2016), from the Real Time series -
the man behind the glass who paints the time, minute by minute.
This clock is a tribute, built with admiration.</i></p>
</body></html>""" % (
        ICON_URI, ICON_SVG, msg_html,
        app["time_str"], app["time_source"], app["wifi"],
        app["display_state"], app["uptime"], app["version"],
        app.get("idle_str", "-"), upd,
        _face_options(cfg["face"]),
        _slider("brightness", "Brightness (0-255):", 255,
                cfg["brightness"]),
        _show_date_options(cfg.get("show_date", True)),
        _slider("frost", "Frosted glass (0-100):", 100,
                cfg["frost"]),
        _slider("backlight", "Backlight (0-100):", 100,
                cfg["backlight"]),
        "checked" if cfg["sleep_enabled"] else "",
        cfg["sleep_start"], cfg["sleep_end"],
        "checked" if cfg.get("cuckoo_enabled", True) else "",
        _tryit_buttons(), upd)


def _refresh_page(verb, delay):
    """The rebooting actions' answer: a minimal page that sends
    the browser back to the admin page once the clock is up
    again (meta refresh), with a manual link if it stalls. The
    flow still ends on the admin page, never a dead end."""
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="%d;url=/">
<title>Painter Clock</title></head><body>
<p><b>%s</b></p>
<p>The clock is rebooting - this page will reload the admin
page by itself in about %d seconds. If it doesn't,
<a href="/">tap here</a>.</p>
</body></html>""" % (delay, verb, delay)


def _send_page(conn, app, msg=""):
    conn.send("HTTP/1.0 200 OK\r\nContent-Type: text/html"
              "\r\n\r\n" + _page(app, msg))


def _urldecode(s):
    s = s.replace("+", " ")
    out = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except Exception:
                pass
        out += s[i]
        i += 1
    return out


def _parse_form(req):
    out = {}
    idx = req.find("\r\n\r\n")
    if idx < 0:
        return out
    for pair in req[idx + 4:].split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[_urldecode(k)] = _urldecode(v)
    return out


def step(app):
    """Service at most one request. app is main.py's shared state
    dict: config, time_str, time_source, wifi, display_state,
    uptime, version, changed."""
    if _srv is None:
        return
    try:
        conn, _ = _srv.accept()
    except OSError:
        return
    try:
        req = conn.recv(2048).decode("utf-8", "ignore")
        if "POST /settings" in req:
            form = _parse_form(req)
            cfg = app["config"]
            if form.get("face") in FACES:
                cfg["face"] = form["face"]
            if form.get("show_date") in ("on", "off"):
                cfg["show_date"] = form["show_date"] == "on"
            try:
                b = int(form.get("brightness", cfg["brightness"]))
                if b < 0:
                    b = 0
                if b > 255:
                    b = 255
                cfg["brightness"] = b
            except ValueError:
                pass
            try:
                fr = int(form.get("frost", cfg["frost"]))
                if fr < 0:
                    fr = 0
                if fr > 100:
                    fr = 100
                cfg["frost"] = fr
            except ValueError:
                pass
            try:
                bl = int(form.get("backlight", cfg["backlight"]))
                if bl < 0:
                    bl = 0
                if bl > 100:
                    bl = 100
                cfg["backlight"] = bl
            except ValueError:
                pass
            cfg["cuckoo_enabled"] = "cuckoo_enabled" in form
            cfg["sleep_enabled"] = "sleep_enabled" in form
            if _valid_hhmm(form.get("sleep_start", "")):
                cfg["sleep_start"] = form["sleep_start"]
            if _valid_hhmm(form.get("sleep_end", "")):
                cfg["sleep_end"] = form["sleep_end"]
            save_config(cfg)
            app["changed"] = True
            _send_page(conn, app, "Settings saved.")
        elif "POST /tryit" in req:
            form = _parse_form(req)
            name = form.get("routine", "")
            if name in showmod.IDLE_DUR:
                app["tryit"] = name
                _send_page(conn, app, "Queued: " + name +
                           " - it runs at the next gap.")
            else:
                _send_page(conn, app, "Unknown routine.")
        elif "POST /trycuckoo" in req:
            app["trycuckoo"] = True
            _send_page(conn, app, "Queued: cuckoo - "
                       "it runs at the next gap.")
        elif "POST /update" in req:
            conn.send("HTTP/1.0 200 OK\r\nContent-Type: text/html"
                      "\r\n\r\n" + _refresh_page(
                          "Updating and rebooting.", 60))
            conn.close()
            updater.apply()  # reboots on success
        elif "POST /restart" in req:
            conn.send("HTTP/1.0 200 OK\r\nContent-Type: text/html"
                      "\r\n\r\n" + _refresh_page("Restarting.", 30))
            conn.close()
            import machine
            machine.reset()
        else:
            _send_page(conn, app)
    except Exception as exc:
        print("admin: request error:", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass
