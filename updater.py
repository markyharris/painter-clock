# updater.py - GitHub self-update for the Painter Clock, ported in
# design from LS Lite Micro / metar-micro (the v6.1 manifest design).
#
# The board has no git, so this is the file-based equivalent of
# pull-and-restart:
#   * CHECK (after boot, then hourly): fetch update_files.txt FRESH
#     from the repo, compare each listed file's git blob SHA with
#     GitHub's contents listing, and only FLAG "update available".
#     The manifest is read fresh every time - a frozen built-in list
#     stranded a new module on the ticker once. The built-in
#     UPDATE_FILES is only the fallback when the read fails.
#   * APPLY (only when Mark presses Update now in the admin page):
#     download each changed file, verify its blob SHA, swap it in
#     (old copy kept as .bak), reboot.
# wifi_cfg.py (credentials) and config.json (settings) are NEVER in
# the manifest - they belong to the board.
#
# SKELETON STATUS: structure and SHA logic mirror the proven builds;
# the HTTPS plumbing here is a compact stand-in for their chunked
# stream reader and gets replaced by that proven code during the
# engine build-out, then board-tested before it is trusted.
import binascii
import hashlib
import json
import time

# TODO(Mark): repo name is his to choose - he creates GitHub repos
# himself (SPEC.md sec.8, open question 1). Placeholder until then.
GITHUB_REPO = "markyharris/painter-clock"
UPDATE_FILES = ("main.py", "display.py", "clockface.py", "figure.py",
                "show.py", "timekeep.py", "prov.py", "updater.py",
                "admin.py")
MANIFEST_URL = ("https://raw.githubusercontent.com/%s/main/"
                "update_files.txt" % GITHUB_REPO)
API_URL = "https://api.github.com/repos/%s/contents/" % GITHUB_REPO
CHECK_MS = 3600 * 1000
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


def _fetch(url, max_bytes):
    # TODO(build-out): replace with the proven chunked-stream HTTPS
    # reader from metar-micro's updater.py (raw socket + ssl wrap).
    # urequests is NOT in the stock firmware; do not rely on it.
    raise OSError("updater transport not built yet")


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
    press. Downloads, SHA-verifies, swaps with .bak, reboots."""
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
            data = _fetch("https://raw.githubusercontent.com/%s/main/%s"
                          % (GITHUB_REPO, name), 262144)
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
