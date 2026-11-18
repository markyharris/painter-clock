# Painter Clock — face roadmap

The painter is the flagship face and ships first. Additional faces plug
into the same display layer (shared canvas, banded `draw_bitmap`
shipping) as small compose modules, selected from the admin page.
Mark's direction (Nov 15, 2026): get the painter nailed down first,
then include as many of these as practical.

## Built faces (all selectable live from the admin pulldown)

- **Painter** — the flagship (clockface.py; SPEC through v25).
- **Classic analog** — the painter's dial minus the man, rust second
  hand (classicface.py; v26).
- **Digital** — HH:MM hero, seconds + AM/PM sub-line (digitalface.py;
  v26; smooth type since v27).
- **METAR analog** — the classic recoloured by a live flight
  category, with decoded wind/vis/cloud lines (metarface.py +
  metar.py; v28, text lift v28.1).
- **Attitude maneuvers** — a steam-gauge attitude indicator flying
  the Lazy Eight, the Chandelle and Eights on Pylons on a loop at
  C182 pace, the analog clock drawn over it, the maneuver's name
  curved on the bottom bezel (attface.py + attdata.py +
  attlabels.py; v29). Mark's build, from the maneuver videos made
  the same evening — the profiles are the videos' own models,
  sampled; nothing is played back, the gauge is drawn from the
  numbers each frame.

Researched Nov 15, 2026; every entry verified against a real source.
Suggested build order after the painter: Sweeper's Clock, 24-hour
Airman GMT, mini ClockClock — then the rest roughly in list order.

## The shortlist

1. **Sweeper's Clock — Maarten Baas (2009) · Strong.** Two sweepers
   push debris piles that form the hands, re-swept each minute. Same
   Real Time series as the painter; round-native; reuses the
   wipe/paint choreography. Covered by the existing Baas credit.
   https://www.dezeen.com/2012/11/30/dezeen-book-of-ideas-sweeper-clock-by-maarten-baas/
   · https://en.wikipedia.org/wiki/Real_Time_(art_series)
2. **A Million Times / ClockClock — Humans Since 1982 · Strong.**
   A grid of mini clock faces whose hands form digital numerals, then
   dissolve into wave patterns. Ours: a circular array of mini-dials.
   Living studio's signature work — credited personal homage only.
   https://www.humanssince1982.com/pages/studio-story
   · https://clockforward.com/humans-since-1982/
3. **Plotclock — Johannes Heberlein (2014) · Strong.** Open-source
   servo-arm clock that writes the time with a whiteboard marker and
   erases it each minute. Ours: the painter's arm rig draws four big
   digits stroke-by-stroke, then wipes them. No homage friction.
   https://laughingsquid.com/plotclock-a-robotic-clock-that-writes-the-time-with-a-marker/
   · https://www.instructables.com/Plot-Clock-for-dummies/
4. **24-Hour GMT "Purist" dial — Glycine Airman (1953) · Strong.**
   True 24-hour dial, hour hand circles once a day, rotating bezel
   for a second zone (Zulu, settable in admin). Near-zero render cost.
   https://ottuhr.com/glycine-airman-gmt-automatic-24-hour/
   · https://www.curiocomp.com/watches/glycine-airman-1953-original-24-hour-dial-purist
5. **Orrery / astronomical dial · Strong.** Concentric orbits for
   Sun, Moon and the five visible planets from the date; nearly free
   to run; round-native.
   https://en.wikipedia.org/wiki/Plo%C3%ABrmel_astronomical_clock
   · https://www.haveyouseenthisclock.com/clock3.shtml
6. **Moon-phase centred clock · Plausible.** A full-face moon with a
   computed terminator (29.53-day cycle), time in a ring around it.
   One redraw a day; pairs with the painter's sleep mode.
   https://www.5dwatches.com/blog/moonphase-complication-explained-2026
   · https://braverywatch.com/en-us/glossary/moonphase
7. **Word clock (QLOCKTWO-style) — Biegert & Funk (2009) ·
   Plausible.** Letter matrix lighting up "IT IS HALF PAST SEVEN" in
   five-minute steps. Trivial compute; typographic work to fit the
   circle. Trademarked product — ship as a "word clock" homage under
   another name.
   https://newatlas.com/qlocktwo-typographic-clock/12620/
   · https://www.montreallighting.com/collections/qlocktwo
8. **Fibonacci Clock — Philippe Chrétien (2015) · Plausible.** Five
   squares (1, 1, 2, 3, 5) lit red/green/blue encode the time.
   Open source — adoptable outright with attribution. The spiral
   layout fits a circle better than its original rectangle.
   https://hackaday.com/2024/12/19/fibonacci-clock-looks-like-beautiful-modern-art/
   · https://www.adafruit.com/product/3117?hidden=yes&main_page=product_info&products_id=3117
9. **Berlin Clock (Mengenlehreuhr) — Dieter Binninger (1975) ·
   Plausible.** 24 lamps encode time in base-5; re-wrap the rows as
   concentric arcs. One change per minute plus a 1 Hz seconds blink.
   http://en.wikipedia.org/wiki/Mengenlehreuhr
   · https://europa-center-berlin.de/en/information-2/sights/?sub=1
10. **The Colour Clock — Jack Hughes (2010) · Plausible.** The time
    as a hex colour flooding the screen, shifting each second.
    Simplest possible face; ambient/nightstand option. (RGB565 shows
    65k colours; the code can still display the true 24-bit value.)
    https://laughingsquid.com/the-colour-clock-representing-time-as-a-hexadecimal-color-value/
    · https://www.digitaltrends.com/home/the-colour-clock-represents-time-in-hexadecimal-color/
11. **Split-flap (Solari) — Gino Valle Cifra 3 (1965) · Plausible.**
    Departure-board digits clattering through intermediate
    characters. Stack HH over MM (two rows of two) to fit the circle.
    https://en.wikipedia.org/wiki/Flap_display
    · https://italoamericano.org/solari-di-udine/
12. **Ferrolic — Zelf Koelman (2015) · Stretch.** Ferrofluid digits.
    Only the look is portable (blob-morphing digits) — hardest render
    here, least readable. Credit as an homage if built.
    https://www.dezeen.com/2015/08/26/zelf-koelman-ferrolic-clock-magnetic-ferrofluid/

Cut on fit (real, but wrong for a round flat screen): Nixie digits
(https://www.nixieboulevard.com/blog/) and the Congreve rolling-ball
clock, 1808 (https://en.wikipedia.org/wiki/Congreve_clock).

Plus the two basics already planned alongside these: a classic
12-hour analog face and a plain digital face.

**Requirement (Mark, Nov 15, 2026, revised same day): EVERY face —
painter included — shows the date (day and month) alongside the
time, and the admin page gets a selector to turn the date off**
(config `show_date`, default on; each face honours it). Digital: a
date line under the time. Classic analog: a date element on the dial
(window or text line) that suits the design. Painter: a small,
tasteful date on the dial that doesn't fight the figure or the
hands' sweep — placement proven in previews before it ships.
