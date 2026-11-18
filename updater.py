# updater.py - GitHub self-update for the Painter Clock, ported
# from LS Lite Micro / metar-micro (the v6.1 manifest design,
# including their proven chunked-stream HTTPS reader below).
#
# The board has no git, so this is the file-based equivalent of
# pull-and-restart:
#   * CHECK (after boot, then hourly): fetch update_files.txt
#     FRESH from the repo, compare each listed file's git blob
#     SHA with GitHub's contents listing, and only FLAG "update
#     available". The manifest is read fresh every time - a
#     frozen built-in list stranded a new module on the ticker
#     once. The built-in UPDATE_FILES is only the fallback when
#     the manifest read fails.
#   * APPLY (only when Mark presses Update now in the admin
#     page): download each changed file, verify its blob SHA,
#     swap it in (old copy kept as .bak), reboot.
# wifi_cfg.py (credentials) and config.json (settings) are NEVER
# in the manifest - they belong to the board.
import binascii
import hashlib
import json
import socket
import ssl
import time

GITHUB_REPO = "markyharris/painter-clock"
UPDATE_FILES = ("main.py", "display.py", "clockface.py", "figure.py",
                "show.py", "timekeep.py", "prov.py", "updater.py",
                "admin.py", "setupface.py", "connectface.py",
                "classicface.py", "digitalface.py", "metar.py",
                "metarface.py", "smoothfont.py", "fontdata.py",
                "attface.py", "attdata.py", "attlabels.py")
MANIFEST_URL = ("https://raw.githubusercontent.com/%s/main/"
                "update_files.txt" % GITHUB_REPO)
RAW_URL = "https://raw.githubusercontent.com/%s/main/" % GITHUB_REPO
API_URL = "https://api.github.com/repos/%s/contents/" % GITHUB_REPO
CHECK_MS = 3600 * 1000
TIMEOUT_S = 20
USER_AGENT = "painter-clock/1.0 (personal ESP32-S3 clock)"
STATE = {"available": False, "files": 0, "failed": "",
         "applying": False, "checked": False}
_last_check = None


def blob_sha(data):
    """git blob SHA-1 of a byte string: sha1('blob <len>\\0' + data)."""
    h = hashlib.sha1()
    h.update(b"blob ")
    h.update(str(len(data)).encode())
    h.update(b"\x00")
    h.update(data)
    return binascii.hexlify(h.digest()).decode()


def local_sha(path):
    try:
        with open(path, "rb") as f:
            return blob_sha(f.read())
    except OSError:
        return None  # missing file counts as "different" -> will fetch


# --- HTTPS transport: raw socket + ssl, chunked-stream reader ---
# Ported from metar-micro's updater.py, which is board-proven in
# Mark's fleet. urequests is NOT in the firmware; do not use it.

class _ChunkedStream:
    """readinto() wrapper that decodes HTTP chunked encoding."""

    def __init__(self, sock):
        self._s = sock
        self._buf = bytearray()
        self._left = -1
        self._eof = False

    def _readline(self):
        line = bytearray()
        while not line.endswith(b"\r\n"):
            ch = self._s.read(1)
            if not ch:
                break
            line += ch
        return bytes(line)

    def readinto(self, b):
        if self._eof:
            return 0
        while not self._buf:
            if self._left == -1:
                line = self._readline()
                try:
                    self._left = int(line.strip().split(b";")[0], 16)
                except (ValueError, IndexError):
                    self._eof = True
                    return 0
                if self._left == 0:
                    while True:
                        t = self._readline()
                        if t in (b"\r\n", b"\n", b""):
                            break
                    self._eof = True
                    return 0
            data = self._s.read(min(self._left, 4096))
            if not data:
                self._eof = True
                return 0
            self._left -= len(data)
            self._buf += data
            if self._left == 0:
                self._readline()
                self._left = -1
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        # Slice-rebind, not del buf[:n]: MicroPython bytearray has
        # no item deletion.
        self._buf = self._buf[n:]
        return n


def _https_get(url, max_bytes, depth=0):
    """Small HTTPS GET: body bytes, or None on any failure.
    Follows up to 2 redirects."""
    if depth > 2 or not url.startswith("https://"):
        return None
    rest = url[len("https://"):]
    host, _, p = rest.partition("/")
    path = "/" + p
    try:
        addr = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0][-1]
        sock = socket.socket()
        sock.settimeout(TIMEOUT_S)
        sock.connect(addr)
        if hasattr(ssl, "wrap_socket"):
            sock = ssl.wrap_socket(sock, server_hostname=host)
        else:
            sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=host)
        try:
            req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\n"
                   "Accept-Encoding: identity\r\n"
                   "Connection: close\r\n\r\n"
                   % (path, host, USER_AGENT))
            sock.write(req.encode())
            head = bytearray()
            while not head.endswith(b"\r\n\r\n"):
                ch = sock.read(1)
                if not ch:
                    return None
                head += ch
                if len(head) > 8192:
                    return None
            lines = bytes(head).decode().split("\r\n")
            status = int(lines[0].split(" ")[1])
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            if status in (301, 302, 303, 307, 308):
                return _https_get(headers.get("location", ""),
                                  max_bytes, depth + 1)
            if status != 200:
                print("updater: GET %s -> HTTP %d" % (path, status))
                return None
            if "chunked" in headers.get("transfer-encoding", ""):
                body = _ChunkedStream(sock)
            else:
                body = sock
            out = bytearray()
            buf = bytearray(2048)
            while len(out) <= max_bytes:
                n = body.readinto(buf)
                if not n:
                    break
                out += buf[:n]
            if len(out) > max_bytes:
                print("updater: GET %s: body too large" % path)
                return None
            return bytes(out)
        finally:
            try:
                sock.close()
            except OSError:
                pass
    except Exception as exc:
        print("updater: GET failed:", exc)
        return None


def _fetch(url, max_bytes):
    """Body bytes of a GET, or OSError - the check/apply logic
    below treats transport trouble as an exception, per the
    original design."""
    data = _https_get(url, max_bytes)
    if data is None:
        raise OSError("fetch failed: " + url)
    return data


def _remote_manifest():
    """update_files.txt from the repo, fresh. Fallback: built-in."""
    try:
        data = _fetch(MANIFEST_URL, 8192)
        names = []
        for line in data.decode().split("\n"):
            name = line.strip()
            if name and not name.startswith("#"):
                names.append(name)
        if names:
            return names
    except Exception as exc:
        print("updater: manifest fetch failed:", exc)
    return list(UPDATE_FILES)


def _remote_shas():
    """{filename: blob sha} from the GitHub contents API."""
    data = _fetch(API_URL, 65536)
    out = {}
    for item in json.loads(data):
        if item.get("type") == "file":
            out[item["name"]] = item["sha"]
    return out


def check():
    """Compare local vs remote. Sets STATE; returns True if an
    update is available. Cheap to call; main.py paces it hourly."""
    global _last_check
    _last_check = time.ticks_ms()
    try:
        remote = _remote_shas()
        names = _remote_manifest()
        changed = 0
        for name in names:
            if name in remote and local_sha(name) != remote[name]:
                changed += 1
        STATE["available"] = changed > 0
        STATE["files"] = changed
        STATE["failed"] = ""
    except Exception as exc:
        STATE["failed"] = str(exc)
        print("updater: check failed:", exc)
    STATE["checked"] = True
    return STATE["available"]


def maybe_check():
    if _last_check is None or \
            time.ticks_diff(time.ticks_ms(), _last_check) > CHECK_MS:
        check()


def apply():
    """Update now. Only ever called from the admin page, on Mark's
    press. Downloads, SHA-verifies, swaps with .bak, reboots.
    A failure mid-apply propagates (no reboot): files already
    swapped stay swapped, each was verified before its swap."""
    import machine
    import os
    STATE["applying"] = True
    try:
        remote = _remote_shas()
        for name in _remote_manifest():
            if name not in remote:
                continue
            if local_sha(name) == remote[name]:
                continue
            data = _fetch(RAW_URL + name, 262144)
            if blob_sha(data) != remote[name]:
                raise OSError("SHA mismatch on " + name)
            try:
                os.rename(name, name + ".bak")
            except OSError:
                pass
            with open(name, "wb") as f:
                f.write(data)
            print("updater: updated", name)
    finally:
        STATE["applying"] = False
    machine.reset()
