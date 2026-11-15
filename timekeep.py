# timekeep.py - time for the Painter Clock.
#
# Two sources, in order:
#   1. The onboard PCF85063 RTC (I2C 0x51) - read at boot, before
#      Wi-Fi, so the first painted frame already shows ~right time.
#   2. NTP (stdlib ntptime) once Wi-Fi is up - the authority; every
#      successful sync writes the RTC back and re-arms in 6 hours.
#
# Local time is UTC + tz_offset_h from config.json. Default -7:
# America/Phoenix is UTC-7 all year (no DST), so a fixed offset is
# the whole story - no tz database on a microcontroller.
#
# machine.RTC is the system clock everything else reads; this module
# is the only place that sets it.
import time

import machine

try:
    import ntptime
except ImportError:  # ntptime is stdlib on the ESP32 port; guard anyway
    ntptime = None

# PCF85063 on the boards' shared I2C bus (2.1 wiki: SDA GPIO15,
# SCL GPIO7 - the 2.8C community template uses the same pair).
I2C_SDA = 15
I2C_SCL = 7
PCF85063_ADDR = 0x51
_REG_SECONDS = 0x04  # PCF85063 time registers start at 0x04

_i2c = None
_source = "none"     # "rtc" | "ntp" | "none"
_last_sync = None    # time.time() of last NTP success
RESYNC_S = 6 * 3600


def _bcd2dec(v):
    return (v >> 4) * 10 + (v & 0x0F)


def _dec2bcd(v):
    return ((v // 10) << 4) + (v % 10)


def _get_i2c():
    global _i2c
    if _i2c is None:
        _i2c = machine.I2C(0, sda=machine.Pin(I2C_SDA),
                           scl=machine.Pin(I2C_SCL), freq=400000)
    return _i2c


def rtc_present():
    """True if a PCF85063 answers on the bus. Sunday-verifiable."""
    try:
        return PCF85063_ADDR in _get_i2c().scan()
    except Exception:
        return False


def rtc_read_utc():
    """(year, month, day, hour, minute, second) UTC from the
    PCF85063, or None if absent/garbled."""
    try:
        i2c = _get_i2c()
        raw = i2c.readfrom_mem(PCF85063_ADDR, _REG_SECONDS, 7)
        sec = _bcd2dec(raw[0] & 0x7F)
        minute = _bcd2dec(raw[1] & 0x7F)
        hour = _bcd2dec(raw[2] & 0x3F)
        day = _bcd2dec(raw[3] & 0x3F)
        month = _bcd2dec(raw[5] & 0x1F)
        year = 2000 + _bcd2dec(raw[6])
        if not (1 <= month <= 12 and 1 <= day <= 31 and hour < 24
                and minute < 60 and sec < 60 and year >= 2025):
            return None
        return (year, month, day, hour, minute, sec)
    except Exception:
        return None


def rtc_write_utc(t):
    """t = (year, month, day, hour, minute, second) UTC."""
    try:
        i2c = _get_i2c()
        data = bytes((_dec2bcd(t[5]), _dec2bcd(t[4]), _dec2bcd(t[3]),
                      _dec2bcd(t[2]), 0, _dec2bcd(t[1]),
                      _dec2bcd(t[0] - 2000)))
        # register 0x07 is weekday - written as 0, unused by us
        i2c.writeto_mem(PCF85063_ADDR, _REG_SECONDS, data)
        return True
    except Exception:
        return False


def _set_system_from_utc(t):
    # time.mktime on the ESP32 port treats the tuple as UTC when the
    # RTC is the reference; we keep the system clock in UTC always
    # and apply tz offset only when READING local time (now_local).
    epoch = time.mktime((t[0], t[1], t[2], t[3], t[4], t[5], 0, 0))
    machine.RTC().datetime((t[0], t[1], t[2], 0, t[3], t[4], t[5], 0))
    return epoch


def boot_set_from_rtc():
    """Call before Wi-Fi. True if the RTC gave us a sane time."""
    global _source
    t = rtc_read_utc()
    if t is None:
        return False
    _set_system_from_utc(t)
    _source = "rtc"
    print("timekeep: system time set from PCF85063:", t)
    return True


def ntp_sync():
    """Try NTP once. On success: system clock set (ntptime does it),
    RTC written back, source = 'ntp'. Returns True/False."""
    global _source, _last_sync
    if ntptime is None:
        return False
    try:
        ntptime.settime()  # sets machine.RTC from pool.ntp.org, UTC
    except Exception as exc:
        print("timekeep: NTP failed:", exc)
        return False
    now = time.gmtime(time.time())
    rtc_write_utc((now[0], now[1], now[2], now[3], now[4], now[5]))
    _source = "ntp"
    _last_sync = time.time()
    print("timekeep: NTP sync ok")
    return True


def maybe_resync():
    """Called from the main loop; cheap when not due."""
    if _last_sync is None or time.time() - _last_sync > RESYNC_S:
        return ntp_sync()
    return True


def source():
    return _source


def now_local(tz_offset_h):
    """(year, month, day, hour, minute, second) in local time."""
    return time.gmtime(time.time() + int(tz_offset_h) * 3600)
