# prov.py - rehoming for the Painter Clock: the setup-AP captive
# portal, ported in shape from LS Lite Micro / metar-micro.
#
# Entered from main.py when:
#   * the BOOT button is held just AFTER power-up (holding it
#     DURING plug-in is S3 download mode - that must never be the
#     gesture; main.py samples the button in a short window after
#     boot instead), or
#   * no usable Wi-Fi credentials are stored.
#
# Behaviour, same as the other builds: any saved creds are dropped,
# the PainterClock-Setup AP comes up, DNS answers everything with
# 192.168.4.1, and the portal page offers a scanned-network picker
# (or type your own) with a show-password peek. Saving writes ONLY
# wifi_cfg.py and reboots. This module never touches config.json.
#
# STATUS: the flow and page are real (form -> wifi_cfg.py write
# round-trip is desk-verified); the portal has NOT been
# round-trip tested on THIS board's hardware yet (the pattern
# has, on the other builds). The bench checklist includes a full
# forget/rejoin cycle.
import time

import machine
import network

AP_SSID = "PainterClock-Setup"
AP_IP = "192.168.4.1"
PLACEHOLDER_SSID = "YOUR_WIFI_NAME"


def load_creds():
    """(ssid, password) from wifi_cfg.py, or (None, None)."""
    try:
        import wifi_cfg
        return wifi_cfg.SSID, wifi_cfg.PASSWORD
    except Exception:
        return None, None


def creds_usable(ssid):
    return bool(ssid) and ssid != PLACEHOLDER_SSID


def _py_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_wifi(ssid, password):
    """Write ONLY wifi_cfg.py - the standing rule for all builds."""
    with open("wifi_cfg.py", "w") as f:
        f.write("# wifi_cfg.py - saved by the PainterClock-Setup "
                "portal.\n")
        f.write("SSID = %s\n" % _py_str(ssid))
        f.write("PASSWORD = %s\n" % _py_str(password))
    print("prov: saved Wi-Fi for", ssid)


def boot_button_held(window_ms=1200):
    """Sample BOOT (GPIO0) in a short window just after power-up.
    True if it is held at any sample. Main.py calls this FIRST,
    before anything that could hang."""
    pin = machine.Pin(0, machine.Pin.IN, machine.Pin.PULL_UP)
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < window_ms:
        if pin.value() == 0:
            return True
        time.sleep_ms(20)
    return False


def scan_networks(wlan):
    """(ssid, rssi) pairs, strongest first, hidden/blank skipped."""
    best = {}
    try:
        for entry in wlan.scan():
            try:
                ssid = entry[0].decode("utf-8").strip()
            except Exception:
                continue
            rssi = entry[3]
            if not ssid:
                continue
            if ssid not in best or rssi > best[ssid]:
                best[ssid] = rssi
    except Exception as exc:
        print("prov: scan failed:", exc)
    pairs = [(s, best[s]) for s in best]
    pairs.sort(key=lambda p: -p[1])
    return pairs


_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Painter Clock setup</title></head><body>
<h2>Painter Clock - Wi-Fi setup</h2>
<p>Pick your network (or type it), enter the password, Save.
The clock saves, reboots and joins.</p>
<form method="POST" action="/save">
<p><select name="ssid">%s</select></p>
<p>Or type it: <input name="ssid_manual" size="24"></p>
<p>Password: <input name="password" id="pw" type="password" size="24">
<label><input type="checkbox"
onclick="document.getElementById('pw').type=this.checked?'text':'password'">
Show password</label></p>
<p><button type="submit">Save and reboot</button></p>
</form></body></html>"""


def run_portal():
    """Blocking captive portal. Returns only via reboot."""
    import socket

    sta = network.WLAN(network.STA_IF)
    sta.active(False)
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
    while ap.ifconfig()[0] == "0.0.0.0":
        time.sleep_ms(100)
    print("prov: AP up:", AP_SSID, ap.ifconfig())

    # --- DNS: answer every A query with the AP IP ---
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("0.0.0.0", 53))
    dns.settimeout(0.2)

    # --- HTTP ---
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 80))
    srv.listen(2)
    srv.settimeout(0.2)

    sta.active(True)  # scan needs the STA radio up; AP+STA coexist
    networks = scan_networks(sta)

    def page():
        opts = ""
        for ssid, rssi in networks:
            opts += '<option value="%s">%s (%d dBm)</option>' % (
                ssid, ssid, rssi)
        return _PAGE % opts

    while True:
        # pump DNS
        try:
            data, addr = dns.recvfrom(512)
            if len(data) >= 12:
                resp = bytearray(data)
                resp[2] = 0x81
                resp[3] = 0x80
                resp[7] = 1  # answers = 1
                resp += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
                resp += bytes((192, 168, 4, 1))
                dns.sendto(bytes(resp), addr)
        except OSError:
            pass
        # pump HTTP
        try:
            conn, _ = srv.accept()
        except OSError:
            continue
        try:
            req = conn.recv(2048).decode("utf-8", "ignore")
            if "POST /save" in req:
                form = _parse_form(req)
                ssid = (form.get("ssid_manual") or
                        form.get("ssid") or "").strip()
                password = form.get("password") or ""
                if ssid and len(ssid) <= 32:
                    save_wifi(ssid, password)
                    conn.send("HTTP/1.0 200 OK\r\n\r\nSaved. "
                              "Rebooting - rejoin your network and "
                              "look for the clock.")
                    conn.close()
                    time.sleep(1)
                    machine.reset()
                conn.send("HTTP/1.0 400 Bad Request\r\n\r\nNo SSID.")
            else:
                body = page()
                conn.send("HTTP/1.0 200 OK\r\nContent-Type: "
                          "text/html\r\n\r\n" + body)
        except Exception as exc:
            print("prov: http error:", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass


def _parse_form(req):
    out = {}
    idx = req.find("\r\n\r\n")
    if idx < 0:
        return out
    body = req[idx + 4:]
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[_urldecode(k)] = _urldecode(v)
    return out


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
