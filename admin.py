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
# the updater). Saving settings sets app["changed"] = True; main.py
# notices and applies/restarts as needed.
import json
import socket

import updater

DEFAULT_CONFIG = {
    "tz_offset_h": -7,       # America/Phoenix: UTC-7, no DST
    "night_mode": False,     # OPEN QUESTION (SPEC sec.8): 22:00-06:00?
    "night_dim": 64,         # backlight level at night, if enabled
    # Clock face module (SPEC Nov 15 addendum): "painter" (default,
    # clockface.py) | "classic" (face_classic.py) | "digital"
    # (face_digital.py) - classic/digital not built yet; unknown
    # names fall back to the painter.
    "face": "painter",
}

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
<p>Time: %s (source: %s) &middot; Display: %s &middot; %s</p>
<form method="POST" action="/settings">
<p>UTC offset (hours): <input name="tz_offset_h" size="4"
value="%s"></p>
<p><label><input type="checkbox" name="night_mode" %s>
Night mode 22:00-06:00</label> &middot; night backlight:
<input name="night_dim" size="4" value="%s"></p>
<p><button type="submit">Save settings</button></p></form>
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
        app["time_str"], app["time_source"], app["display_state"],
        upd, cfg["tz_offset_h"],
        "checked" if cfg["night_mode"] else "", cfg["night_dim"])


def _parse_form(req):
    out = {}
    idx = req.find("\r\n\r\n")
    if idx < 0:
        return out
    for pair in req[idx + 4:].split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.replace("+", " ")] = v.replace("+", " ")
    return out


def step(app):
    """Service at most one request. app is main.py's shared state
    dict: config, time_str, time_source, display_state, changed."""
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
            try:
                cfg["tz_offset_h"] = int(form.get("tz_offset_h",
                                                  cfg["tz_offset_h"]))
                cfg["night_dim"] = int(form.get("night_dim",
                                                cfg["night_dim"]))
            except ValueError:
                pass
            cfg["night_mode"] = "night_mode" in form
            save_config(cfg)
            app["changed"] = True
            conn.send("HTTP/1.0 200 OK\r\n\r\nSaved.")
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
