# timekeep.py - time for the Painter Clock.
#
# Architecture (SPEC Nov 15 addendum): the system clock runs in
# LOCAL time, and the PCF85063 RTC stores LOCAL time too.
#   * Timezone is FIXED UTC-7 (America/Phoenix, no DST, ever), so
#     local is a constant offset - no tz database on a
#     microcontroller.
#   * At boot, init_rtc() reads the PCF85063 (I2C 0x51) and sets
#     the system clock from it: a Wi-Fi-less boot shows correct
#     local time from the first frame, no conversion anywhere.
#   * NTP (stdlib ntptime, pool.ntp.org) is the authority when
#     Wi-Fi is up: sync_ntp() takes the UTC answer, converts to
#     local, sets the system clock AND writes the RTC back in
#     local time. Re-sync every 6 hours (maybe_resync()).
#   * Implausible RTC contents (year < 2025, out-of-range fields,
#     or the oscillator-stop flag set) are rejected - the clock
#     then runs unset until NTP lands, and says so via
#     time_source() == "none".
#
# API: init_rtc(), now_tuple(), sync_ntp(), time_source().
# now_tuple() returns the localtime 8-tuple (year, month, day,
# hour, minute, second, weekday, yearday) that clockface/show
# read ([3]=hour, [4]=minute). machine.RTC is the system clock;
# this module is the only place that sets it.
import time

import machine

try:
    import ntptime
except ImportError:  # ntptime is stdlib on the ESP32 port; guard anyway
    ntptime = None

TZ_OFFSET_H = -7                 # America/Phoenix: UTC-7 all year
TZ_OFFSET_S = TZ_OFFSET_H * 3600

# PCF85063 on the boards' shared I2C bus (SPEC sec.1: SDA GPIO15,
# SCL GPIO7 on the 2.8C; bench scan Nov 14 found it at 0x51).
I2C_SDA = 15
I2C_SCL = 7
PCF85063_ADDR = 0x51
_REG_SECONDS = 0x04  # PCF85063 time registers start at 0x04
_MIN_YEAR = 2025     # anything older is the unset 1970/2000 epoch
RESYNC_S = 6 * 3600

_i2c = None
_source = "none"     # "rtc" | "ntp" | "none"
_last_sync = None    # time.time() of last NTP success


def _bcd2dec(v):
    return (v >> 4) * 10 + (v & 0x0F)


def _dec2bcd(v):
    return ((v // 10) << 4) + (v % 10)


def _weekday_sun0(y, m, d):
    """Day of week, 0 = Sunday (Sakamoto's algorithm). The
    PCF85063 weekday register is a free-running 0-6 counter;
    we keep it honest with the Sunday=0 convention."""
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    if m < 3:
        y -= 1
    return (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7


def _get_i2c():
    global _i2c
    if _i2c is None:
        # SoftI2C, NOT machine.I2C: the panel driver (esp_panel)
        # owns the hardware I2C controller for its expander, and
        # whoever installs that driver first locks the other out -
        # board-proven Nov 15, 2026 both ways (RTC-first made
        # Board.begin() return False; panel-first made every RTC
        # transaction fail). Bit-banging the same pins shares the
        # wires without touching the peripheral.
        _i2c = machine.SoftI2C(sda=machine.Pin(I2C_SDA),
                               scl=machine.Pin(I2C_SCL), freq=100000)
    return _i2c


def rtc_present():
    """True if a PCF85063 answers on the bus."""
    try:
        return PCF85063_ADDR in _get_i2c().scan()
    except Exception:
        return False


def rtc_read():
    """(year, month, day, hour, minute, second) LOCAL from the
    PCF85063, or None if absent / stopped / implausible."""
    try:
        raw = _get_i2c().readfrom_mem(PCF85063_ADDR, _REG_SECONDS, 7)
    except Exception:
        return None
    if raw[0] & 0x80:
        return None  # oscillator-stop flag: the time was lost
    sec = _bcd2dec(raw[0] & 0x7F)
    minute = _bcd2dec(raw[1] & 0x7F)
    hour = _bcd2dec(raw[2] & 0x3F)
    day = _bcd2dec(raw[3] & 0x3F)
    # raw[4] is the weekday register - counted, never read here
    month = _bcd2dec(raw[5] & 0x1F)
    year = 2000 + _bcd2dec(raw[6])
    if not (1 <= month <= 12 and 1 <= day <= 31 and hour < 24
            and minute < 60 and sec < 60 and year >= _MIN_YEAR):
        return None
    return (year, month, day, hour, minute, sec)


def rtc_write(t):
    """t = (year, month, day, hour, minute, second) LOCAL."""
    try:
        data = bytes((_dec2bcd(t[5]), _dec2bcd(t[4]),
                      _dec2bcd(t[3]), _dec2bcd(t[2]),
                      _weekday_sun0(t[0], t[1], t[2]),
                      _dec2bcd(t[1]), _dec2bcd(t[0] - 2000)))
        _get_i2c().writeto_mem(PCF85063_ADDR, _REG_SECONDS, data)
        return True
    except Exception:
        return False


def _set_system_local(t):
    """Set machine.RTC (the system clock) from a LOCAL tuple."""
    wd_mon0 = (_weekday_sun0(t[0], t[1], t[2]) + 6) % 7  # Mon=0
    machine.RTC().datetime((t[0], t[1], t[2], wd_mon0,
                            t[3], t[4], t[5], 0))


def _local_from_utc_epoch(epoch):
    """UTC epoch seconds -> LOCAL (y, mo, d, h, mi, s) tuple."""
    lt = time.gmtime(epoch + TZ_OFFSET_S)
    return (lt[0], lt[1], lt[2], lt[3], lt[4], lt[5])


def _apply_utc_epoch(epoch):
    """NTP gave us a UTC epoch: convert to local, set the system
    clock, write the RTC back (local). Returns the local tuple."""
    lt = _local_from_utc_epoch(epoch)
    _set_system_local(lt)
    rtc_write(lt)
    return lt


def init_rtc():
    """Boot: set the system clock from the PCF85063. True if the
    RTC held a plausible local time."""
    global _source
    t = rtc_read()
    if t is None:
        print("timekeep: no plausible RTC time (absent/unset)")
        return False
    _set_system_local(t)
    _source = "rtc"
    print("timekeep: system time set from PCF85063 (local):", t)
    return True


def sync_ntp():
    """Try NTP once. On success the system clock and the RTC
    both hold LOCAL time and the source becomes 'ntp'."""
    global _source, _last_sync
    if ntptime is None:
        return False
    try:
        ntptime.settime()  # sets the system clock from NTP, UTC
    except Exception as exc:
        print("timekeep: NTP failed:", exc)
        return False
    lt = _apply_utc_epoch(time.time())
    _source = "ntp"
    _last_sync = time.time()
    print("timekeep: NTP sync ok - local time:", lt)
    return True


def maybe_resync():
    """Called from the main loop; cheap when not due."""
    if _last_sync is None or time.time() - _last_sync > RESYNC_S:
        return sync_ntp()
    return True


def time_source():
    """"ntp" after a sync, "rtc" after a boot RTC set, else
    "none" (clock unset - running on the power-on epoch)."""
    return _source


def now_tuple():
    """Local time, 8-tuple: (year, month, day, hour, minute,
    second, weekday, yearday). The system clock IS local time
    in this design, so this is a plain localtime() read."""
    return time.localtime()
