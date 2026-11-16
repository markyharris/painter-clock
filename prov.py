# prov.py - rehoming for the Painter Clock: the setup-AP captive
# portal, ported in shape from LS Lite Micro / metar-micro.
#
# Entered from main.py when:
#   * the BOOT button is held just AFTER power-up (holding it
#     DURING plug-in is S3 download mode - that must never be the
#     gesture; main.py samples the button in a short window after
#     boot instead), or
#   * no usable Wi-Fi credentials are stored, or
#   * the saved network fails to join at boot.
#
# Behaviour: the PainterClock-Setup AP comes up, a DNS catch-all
# answers every lookup with 192.168.4.1 (which is what makes a
# phone pop the setup page by itself), and the portal page offers
# a scanned-network picker (or type your own) with a show-
# password peek. Saving writes ONLY wifi_cfg.py and reboots.
# This module never touches config.json.
#
# v16 (Nov 16, 2026): the serve core was rebuilt on metar-micro's
# hardware-proven pattern - uselect.poll over NON-BLOCKING
# sockets, a properly built DNS reply, a request reader that
# honours Content-Length, Content-Length responses, and a 302
# redirect for any other path (the phones' connectivity probes).
# The v15-and-earlier core (settimeout round-robin pumps, a DNS
# reply made by mutating the query buffer, a single-recv HTTP
# read) never served a page on this board's hardware - see the
# SPEC v16 addendum for the audit. Every stage now prints a
# "prov:" line, and the serve loop prints a heartbeat, so a
# bench console shows exactly where it is (or isn't) working.
import socket
import time

import machine
import network
import uselect

AP_SSID = "PainterClock-Setup"
AP_IP = "192.168.4.1"
PLACEHOLDER_SSID = "YOUR_WIFI_NAME"

HEARTBEAT_MS = 15000     # "portal alive" console line cadence
SETUP_RETRIES = 0        # 0 = retry setup forever (portal IS
                         # the mode; it does not give up)


# ------------------------------------------------------------ creds
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
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') \
        .replace("\n", " ").replace("\r", " ") + '"'


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


# ------------------------------------------------------------- scan
def scan_networks(wlan):
    """(ssid, rssi) pairs, strongest first, hidden/blank skipped.
    Never raises."""
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


# ------------------------------------------------------------ forms
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


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


def parse_form(body):
    """urlencoded body (bytes or str) -> {name: value}."""
    form = {}
    if not body:
        return form
    if isinstance(body, bytes):
        body = body.decode("utf-8", "ignore")
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            form[_urldecode(k)] = _urldecode(v)
    return form


def validate(form):
    """(ssid, password) from the setup form; ValueError with a
    user-facing message when something is off. The manual field
    wins over the scanned-list pick (hidden networks)."""
    ssid = ((form.get("ssid_manual") or "").strip()
            or (form.get("ssid") or "").strip())
    password = form.get("password") or ""
    if not ssid:
        raise ValueError("Pick a network from the list, or type "
                         "its name in the box below it.")
    if len(ssid) > 32:
        raise ValueError("That network name is too long - Wi-Fi "
                         "names are at most 32 characters.")
    if len(password) > 64:
        raise ValueError("That password is too long - Wi-Fi "
                         "passwords are at most 64 characters.")
    return ssid, password


# -------------------------------------------------------------- DNS
def dns_reply(query):
    """Answer one DNS query packet with AP_IP, whatever name was
    asked - in setup mode every lookup lands on the board, which
    is what makes the phone open the setup page by itself. The
    reply is BUILT (header + the echoed question + one A record,
    all other counts zero), never mutated out of the query: a
    mutated query keeps the phone's own additional records (EDNS
    OPT) in the packet, which puts the answer in the wrong
    section and strict resolvers drop it. None for a malformed
    query (drop those)."""
    try:
        if len(query) < 12:
            return None
        if ((query[4] << 8) | query[5]) < 1:
            return None
        i = 12
        while True:
            if i >= len(query):
                return None
            n = query[i]
            i += 1
            if n == 0:
                break
            if n & 0xC0:
                return None
            i += n
        if i + 4 > len(query):
            return None
        question = query[12:i + 4]
        flags = 0x8000 | (query[2] & 0x79) | 0x0080
        resp = bytearray()
        resp += query[0:2]
        resp += bytes((flags >> 8, flags & 0xFF))
        resp += b"\x00\x01"          # QDCOUNT = 1
        resp += b"\x00\x01"          # ANCOUNT = 1
        resp += b"\x00\x00\x00\x00"  # NSCOUNT + ARCOUNT = 0
        resp += question
        resp += b"\xc0\x0c"          # name -> the question
        resp += b"\x00\x01"          # type A
        resp += b"\x00\x01"          # class IN
        resp += b"\x00\x00\x00\x3c"  # TTL 60
        resp += b"\x00\x04"          # RDLENGTH 4
        for part in AP_IP.split("."):
            resp.append(int(part))
        return bytes(resp)
    except Exception:
        return None


def _qname(query):
    """The name a DNS query asks for, for the console log only.
    '' when it doesn't parse simply."""
    try:
        labels = []
        i = 12
        while i < len(query):
            n = query[i]
            i += 1
            if n == 0:
                break
            if n & 0xC0:
                return ""
            labels.append(bytes(query[i:i + n]).decode("utf-8",
                                                       "ignore"))
            i += n
        return ".".join(labels)
    except Exception:
        return ""


# -------------------------------------------------------------- page
_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Painter Clock setup</title></head><body>
<h2>Painter Clock - Wi-Fi setup</h2>
%%ERR%%
<p>You are connected to the clock's own setup network,
<strong>PainterClock-Setup</strong>. Pick your network (or type
it), enter the password, Save. The clock saves, reboots and
joins - this setup network then disappears, so reconnect your
phone to your normal Wi-Fi afterwards.</p>
<form method="POST" action="/save">
<p><select name="ssid">%%OPTIONS%%</select></p>
<p>Or type it: <input name="ssid_manual" size="24"></p>
<p>Password: <input name="password" id="pw" type="password" size="24">
<label><input type="checkbox"
onclick="document.getElementById('pw').type=this.checked?'text':'password'">
Show password</label></p>
<p><button type="submit">Save and reboot</button></p>
</form>
<p><a href="/rescan">Rescan for networks</a></p>
</body></html>"""

_SAVED_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Saved</title></head><body>
<h2>Saved - rebooting</h2>
<p>The clock is rebooting and will join <strong>%%SSID%%</strong>.
This setup network is about to disappear; reconnect your phone
to your normal Wi-Fi.</p></body></html>"""


def page(nets, error=""):
    opts = ""
    for ssid, rssi in nets:
        opts += '<option value="%s">%s (%d dBm)</option>' % (
            _esc(ssid), _esc(ssid), rssi)
    if not opts:
        opts = '<option value="">(no networks found)</option>'
    err = ('<p style="color:#b00"><strong>%s</strong></p>'
           % _esc(error)) if error else ""
    return _PAGE.replace("%%ERR%%", err).replace("%%OPTIONS%%",
                                                 opts)


# ------------------------------------------------------------ server
def _write_all(conn, data):
    """Write every byte (MicroPython's stream write may take the
    buffer in pieces; a port that returns None took it all)."""
    view = memoryview(data)
    while len(view):
        n = conn.write(view)
        if n is None:
            return
        if n <= 0:
            raise OSError("write stalled")
        view = view[n:]


def _send(conn, status, ctype, body):
    if isinstance(body, str):
        body = body.encode()
    head = ("HTTP/1.1 %s\r\nContent-Type: %s\r\n"
            "Content-Length: %d\r\nConnection: close\r\n\r\n"
            % (status, ctype, len(body)))
    _write_all(conn, head.encode())
    if body:
        _write_all(conn, body)


def _redirect(conn):
    _write_all(conn, b"HTTP/1.1 302 Found\r\nLocation: http://"
               + AP_IP.encode()
               + b"/\r\nContent-Length: 0\r\n"
                 b"Connection: close\r\n\r\n")


def _handle_http(conn, sta, state):
    """One setup-mode HTTP request. Returns True when a save has
    been accepted and the board should reboot."""
    conn.settimeout(5)
    try:
        req = b""
        while b"\r\n\r\n" not in req:
            chunk = conn.recv(1024)
            if not chunk:
                return False
            req += chunk
            if len(req) > 16384:
                return False
        head, _, rest = req.partition(b"\r\n\r\n")
        lines = head.decode("utf-8", "ignore").split("\r\n")
        parts = lines[0].split(" ")
        method = parts[0]
        path = parts[1] if len(parts) > 1 else "/"
        clen = 0
        for ln in lines[1:]:
            if ln.lower().startswith("content-length:"):
                try:
                    clen = int(ln.split(":", 1)[1].strip())
                except ValueError:
                    clen = 0
        print("prov http:", method, path)
        if method == "POST" and path == "/save":
            body = rest
            while len(body) < clen:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                body += chunk
            try:
                ssid, password = validate(parse_form(body[:clen]))
            except ValueError as exc:
                _send(conn, "200 OK", "text/html",
                      page(state["nets"], str(exc)))
                return False
            save_wifi(ssid, password)
            _send(conn, "200 OK", "text/html",
                  _SAVED_PAGE.replace("%%SSID%%", _esc(ssid)))
            return True
        if path == "/" or path == "/rescan":
            if path == "/rescan":
                state["nets"] = scan_networks(sta)
                print("prov: rescan found %d network(s)"
                      % len(state["nets"]))
            _send(conn, "200 OK", "text/html", page(state["nets"]))
            return False
        # Anything else is a phone connectivity probe or a stray
        # path: land it on the form.
        _redirect(conn)
        return False
    except Exception as exc:
        print("prov http error:", exc)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _setup(sta):
    """Bring the portal up: scan, AP, DNS + HTTP sockets, poller.
    Returns (ap, poller, dns, web, nets). Raises on failure -
    run_portal retries, loudly."""
    # Drop any pending join first: on the failed-join entry the
    # radio is still retrying the old network, and a radio mid-
    # retry scans empty and serves badly (field lesson from LS
    # Lite Micro, Nov 5 - metar-micro disconnects for this).
    try:
        sta.disconnect()
    except Exception:
        pass
    sta.active(True)
    nets = []
    for _ in range(3):
        nets = scan_networks(sta)
        if nets:
            break
        time.sleep(1)
    print("prov: scan found %d network(s)" % len(nets))

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    try:
        ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
    except Exception:
        ap.config(essid=AP_SSID)
    start = time.ticks_ms()
    while ap.ifconfig()[0] == "0.0.0.0":
        if time.ticks_diff(time.ticks_ms(), start) > 3000:
            break
        time.sleep_ms(100)
    print("prov: AP up:", AP_SSID, ap.ifconfig())

    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("0.0.0.0", 53))
    dns.setblocking(False)
    print("prov: DNS catch-all listening on port 53")

    web = socket.socket()
    web.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    web.bind(("0.0.0.0", 80))
    web.listen(4)
    web.setblocking(False)
    print("prov: HTTP listening on port 80 - join '%s' and open "
          "http://%s/" % (AP_SSID, AP_IP))

    poller = uselect.poll()
    poller.register(dns, uselect.POLLIN)
    poller.register(web, uselect.POLLIN)
    return ap, poller, dns, web, nets


def run_portal():
    """Blocking captive portal - a dedicated mode. Returns only
    via reboot (a save) - setup failures retry in place, loudly,
    because there is nothing sensible to fall through to."""
    print("prov: setup portal starting")
    sta = network.WLAN(network.STA_IF)
    attempt = 0
    while True:
        attempt += 1
        try:
            _ap, poller, dns, web, nets = _setup(sta)
            break
        except Exception as exc:
            print("prov: portal setup FAILED (attempt %d): %s"
                  % (attempt, exc))
            if SETUP_RETRIES and attempt >= SETUP_RETRIES:
                raise
            time.sleep(2)
    state = {"nets": nets}
    boot_ms = time.ticks_ms()
    last_beat = boot_ms
    dns_count = 0
    http_count = 0
    while True:
        try:
            events = poller.poll(250)
        except Exception as exc:
            print("prov: poll error:", exc)
            time.sleep_ms(100)
            continue
        for obj, _ev in events:
            if obj is dns:
                try:
                    data, addr = dns.recvfrom(512)
                except OSError:
                    continue
                resp = dns_reply(data)
                if resp:
                    dns_count += 1
                    if dns_count <= 5:
                        print("prov dns: %s -> %s"
                              % (_qname(data) or "?", AP_IP))
                    try:
                        dns.sendto(resp, addr)
                    except OSError:
                        pass
            else:
                try:
                    conn, _addr = web.accept()
                except OSError:
                    continue
                http_count += 1
                if _handle_http(conn, sta, state):
                    print("prov: saved - rebooting now")
                    time.sleep(1)
                    machine.reset()
                    return  # unreachable on hardware
        now = time.ticks_ms()
        if time.ticks_diff(now, last_beat) >= HEARTBEAT_MS:
            last_beat = now
            print("prov: portal alive - %d dns, %d http, up %d s"
                  % (dns_count, http_count,
                     time.ticks_diff(now, boot_ms) // 1000))
