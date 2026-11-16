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
# SPEC Nov 13 addendum) landed in v15. The old skeleton's
# night_mode / night_dim checkbox fields are gone, and so is
# tz_offset_h: the timezone is fixed UTC-7 in timekeep.py.
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
         ("plane", "Plane flyby"), ("shoulder", "Shoulder roll"))

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
    "sleep_enabled": False,  # lights-out hours (v15 behaviour)
    "sleep_start": "22:00",
    "sleep_end": "06:00",
}

FACES = ("painter", "classic", "digital")

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
    out = ""
    for name, label in TRYIT:
        out += '<button name="routine" value="%s">%s</button> ' \
            % (name, label)
    return out


def _page(app):
    u = updater.STATE
    upd = "UPDATE AVAILABLE (%d file(s))" % u["files"] \
        if u["available"] else "Up to date"
    if u["failed"]:
        upd = "Update check failed: %s" % u["failed"]
    cfg = app["config"]
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Painter Clock</title></head><body>
<h2>Painter Clock</h2>
<p>Time: %s (source: %s)<br>
Wi-Fi: %s<br>
Display: %s &middot; Uptime: %s &middot; Code: %s<br>
Idle: %s<br>
Update: %s</p>
<form method="POST" action="/settings">
<p>Face: <select name="face">%s</select></p>
<p>Show date: <select name="show_date">%s</select></p>
<p>Brightness (0-255): <input name="brightness" size="4"
value="%s"></p>
<p>Frosted glass (0-100): <input name="frost" size="4"
value="%s"></p>
<p>Backlight (0-100): <input name="backlight" size="4"
value="%s"></p>
<p><label><input type="checkbox" name="sleep_enabled" %s>
Lights out - he sleeps</label> from
<input name="sleep_start" size="5" value="%s"> to
<input name="sleep_end" size="5" value="%s"> (HH:MM, 24h)<br>
<i>In those hours the room goes dark and he lies down to
sleep; the hands keep time in pale ink.</i></p>
<p><button type="submit">Save settings</button></p></form>
<h3>Idle routines - try one</h3>
<form method="POST" action="/tryit"><p>%s</p></form>
<form method="POST" action="/update"><p>
<button type="submit">Update now</button></p></form>
<form method="POST" action="/restart"><p>
<button type="submit">Restart</button></p></form>
<h3>Rehome (new Wi-Fi / new owner)</h3>
<p>Unplug. Plug back in and, just AFTER it starts, hold the BOOT
button for a second. The clock starts the <b>PainterClock-Setup</b>
network - join it with a phone and follow the captive portal.</p>
<hr>
<p><i>An homage to Maarten Baas and his Schiphol Clock
(Amsterdam Airport Schiphol, 2016), from the Real Time series -
the man behind the glass who paints the time, minute by minute.
This clock is a tribute, built with admiration.</i></p>
</body></html>""" % (
        app["time_str"], app["time_source"], app["wifi"],
        app["display_state"], app["uptime"], app["version"],
        app.get("idle_str", "-"), upd,
        _face_options(cfg["face"]),
        _show_date_options(cfg.get("show_date", True)),
        cfg["brightness"], cfg["frost"], cfg["backlight"],
        "checked" if cfg["sleep_enabled"] else "",
        cfg["sleep_start"], cfg["sleep_end"], _tryit_buttons())


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
            cfg["sleep_enabled"] = "sleep_enabled" in form
            if _valid_hhmm(form.get("sleep_start", "")):
                cfg["sleep_start"] = form["sleep_start"]
            if _valid_hhmm(form.get("sleep_end", "")):
                cfg["sleep_end"] = form["sleep_end"]
            save_config(cfg)
            app["changed"] = True
            conn.send("HTTP/1.0 200 OK\r\n\r\nSaved.")
        elif "POST /tryit" in req:
            form = _parse_form(req)
            name = form.get("routine", "")
            if name in showmod.IDLE_DUR:
                app["tryit"] = name
                conn.send("HTTP/1.0 200 OK\r\n\r\nQueued: "
                          + name + " - it runs at the next gap.")
            else:
                conn.send("HTTP/1.0 200 OK\r\n\r\n"
                          "Unknown routine.")
        elif "POST /update" in req:
            conn.send("HTTP/1.0 200 OK\r\n\r\nUpdating and rebooting.")
            conn.close()
            updater.apply()  # reboots on success
        elif "POST /restart" in req:
            conn.send("HTTP/1.0 200 OK\r\n\r\nRestarting.")
            conn.close()
            import machine
            machine.reset()
        else:
            conn.send("HTTP/1.0 200 OK\r\nContent-Type: text/html"
                      "\r\n\r\n" + _page(app))
    except Exception as exc:
        print("admin: request error:", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass
