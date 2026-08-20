#!/usr/bin/env python3
"""Regression tests for the iCalendar subscribe feed (src/generate_ics.py).

Offline — no database, no network. Run directly or via ./test_before_push.sh.

What these protect:
  * DST correctness — a summer show and a winter show must land on different
    UTC offsets, or half the year is off by an hour in every subscriber's app.
  * RFC 5545 line folding on *octets* at character boundaries — a split em dash
    is mojibake in every client, and titles containing em dashes are the norm
    here, not the exception.
  * Property escaping — a comma or semicolon in a title (common: "Band, The")
    would otherwise be read as a value separator and truncate the entry.
  * UID stability against the client-side per-event export, so subscribing
    after downloading one show does not double-book it.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.generate_ics import _esc, _fold, _http_url, generate_ics  # noqa: E402
from src.time_format import DEFAULT_START_HOUR, parse_start_time  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(label, actual, expected):
    CHECKS[0] += 1
    if actual != expected:
        FAILURES.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


def check_true(label, value):
    CHECKS[0] += 1
    if not value:
        FAILURES.append(f"{label}\n    expected truthy, got {value!r}")


BUILD = datetime(2026, 8, 20, 17, 30, 0, tzinfo=ZoneInfo("UTC"))


def _props(ics, name):
    """All values of a property, with folding undone."""
    unfolded = ics.replace("\r\n ", "")
    out = []
    for line in unfolded.split("\r\n"):
        if line.startswith(name + ":") or line.startswith(name + ";"):
            out.append(line.split(":", 1)[1])
    return out


# ---------------------------------------------------------------------------
# Start-time parsing
# ---------------------------------------------------------------------------

def test_start_time_parsing():
    cases = [
        ("7:30 PM", (19, 30)),
        ("7 PM", (19, 0)),
        ("8:00 pm", (20, 0)),
        ("12:00 AM", (0, 0)),
        ("12:30 PM", (12, 30)),
        ("11:59 PM", (23, 59)),
        # Narrow no-break space — 38 distinct start_time values in production
        # include this shape.
        ("10:00 PM", (22, 0)),
        ("6:30 PM", (18, 30)),
        # Range: the start wins.
        ("6:30 PM - 8:30 PM", (18, 30)),
        ("6:30 PM – 8:30 PM", (18, 30)),
        # Dotted meridiem.
        ("7:30 p.m.", (19, 30)),
        # No meridiem: a bare number on a concert listing is the evening.
        ("9", (21, 0)),
        ("9:15", (21, 15)),
        # Garbage and empties fall back rather than moving the show.
        (None, (DEFAULT_START_HOUR, 0)),
        ("", (DEFAULT_START_HOUR, 0)),
        ("TBA", (DEFAULT_START_HOUR, 0)),
        ("Doors at dusk", (DEFAULT_START_HOUR, 0)),
        # Out-of-range hour must not silently roll into the next day.
        ("29:00 PM", (DEFAULT_START_HOUR, 0)),
    ]
    for value, expected in cases:
        check(f"parse_start_time({value!r})", parse_start_time(value), expected)


# ---------------------------------------------------------------------------
# DST / UTC conversion
# ---------------------------------------------------------------------------

def test_dst_offsets():
    summer = generate_ics(
        [{"id": "a", "title": "Summer Show", "venue": "Hi Tone",
          "date": "2026-07-15", "start_time": "8:00 PM"}], BUILD)
    winter = generate_ics(
        [{"id": "b", "title": "Winter Show", "venue": "Hi Tone",
          "date": "2026-12-15", "start_time": "8:00 PM"}], BUILD)

    # 8 PM CDT (UTC-5) is 01:00Z the next day; 8 PM CST (UTC-6) is 02:00Z.
    check("summer DTSTART (CDT, UTC-5)", _props(summer, "DTSTART"), ["20260716T010000Z"])
    check("winter DTSTART (CST, UTC-6)", _props(winter, "DTSTART"), ["20261216T020000Z"])

    # Default 3-hour duration.
    check("summer DTEND", _props(summer, "DTEND"), ["20260716T040000Z"])


def test_default_time_and_day_boundary():
    ics = generate_ics(
        [{"id": "c", "title": "No Time", "venue": "Bar DKDC", "date": "2026-09-10"}],
        BUILD)
    # Default 8 PM CDT -> 01:00Z on the 11th.
    check("default start time", _props(ics, "DTSTART"), ["20260911T010000Z"])

    # An 11 PM show ends after midnight — the end date must roll forward.
    late = generate_ics(
        [{"id": "d", "title": "Late", "venue": "Hi Tone",
          "date": "2026-09-10", "start_time": "11:30 PM"}], BUILD)
    check("late show DTSTART", _props(late, "DTSTART"), ["20260911T043000Z"])
    check("late show DTEND rolls over", _props(late, "DTEND"), ["20260911T073000Z"])


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------

def test_escaping():
    check("backslash escaped once", _esc("a\\b"), "a\\\\b")
    check("comma escaped", _esc("Band, The"), "Band\\, The")
    check("semicolon escaped", _esc("a;b"), "a\\;b")
    check("newline escaped", _esc("a\nb"), "a\\nb")
    check("CRLF escaped once", _esc("a\r\nb"), "a\\nb")
    # Control characters are dropped: a stray one invalidates the file for
    # strict parsers and cannot be represented.
    check("control chars dropped", _esc("a\x07\x00b"), "ab")
    # Tab is a control character by this rule and goes too.
    check("tab dropped", _esc("a\tb"), "ab")

    ics = generate_ics(
        [{"id": "e", "title": 'Elizabeth Barraclough\'s "Hi", Live; Loud',
          "venue": "Lafayette's Music Room", "date": "2026-10-01",
          "start_time": "8 PM"}], BUILD)
    summary = _props(ics, "SUMMARY")[0]
    check_true("comma in title is escaped in SUMMARY", "\\," in summary)
    check_true("semicolon in title is escaped in SUMMARY", "\\;" in summary)
    check_true("quotes survive unescaped (legal in ICS text)", '"Hi"' in summary)


# ---------------------------------------------------------------------------
# Folding
# ---------------------------------------------------------------------------

def test_folding():
    short = "SUMMARY:Short"
    check("short line unfolded", _fold(short), short)

    long_ascii = "SUMMARY:" + ("A" * 200)
    folded = _fold(long_ascii)
    for i, line in enumerate(folded.split("\r\n")):
        limit = 75 if i == 0 else 76  # continuation lines carry a leading space
        check_true(
            f"folded ascii line {i} within octet limit (got {len(line.encode())})",
            len(line.encode("utf-8")) <= limit,
        )
        if i > 0:
            check_true(f"continuation line {i} starts with a space", line.startswith(" "))
    check("unfolding restores the ascii line", folded.replace("\r\n ", ""), long_ascii)

    # Em dashes are 3 bytes in UTF-8 and appear in nearly every SUMMARY here
    # ("Artist — Venue"). A fold that splits one produces mojibake.
    long_utf8 = "SUMMARY:" + ("Beale Street — Memphis — " * 8)
    folded_utf8 = _fold(long_utf8)
    check("unfolding restores the utf-8 line", folded_utf8.replace("\r\n ", ""), long_utf8)
    for i, line in enumerate(folded_utf8.split("\r\n")):
        limit = 75 if i == 0 else 76
        check_true(
            f"folded utf-8 line {i} within octet limit (got {len(line.encode())})",
            len(line.encode("utf-8")) <= limit,
        )
        # Round-tripping through decode would have replaced a split character.
        check_true(f"folded utf-8 line {i} has no replacement char", "�" not in line)


# ---------------------------------------------------------------------------
# Structure, UIDs, URL safety
# ---------------------------------------------------------------------------

def test_structure():
    events = [
        {"id": "11111111-1111-1111-1111-111111111111", "title": "Lucero",
         "venue": "Minglewood Hall", "date": "2026-11-05", "start_time": "8:00 PM",
         "doors_time": "7:00 PM", "ticket_price": "$25", "genre": "Rock",
         "description": "An evening with Lucero.",
         "ticket_url": "https://example.com/tix", "is_featured": True,
         "is_wyxr_presents": True, "updated_at": "2026-08-01T12:00:00+00:00"},
        {"id": "22222222-2222-2222-2222-222222222222", "title": "Open Mic",
         "venue": "", "date": "2026-11-06"},
    ]
    ics = generate_ics(events, BUILD)

    check("starts with BEGIN:VCALENDAR", ics.split("\r\n")[0], "BEGIN:VCALENDAR")
    check_true("ends with END:VCALENDAR", ics.rstrip().endswith("END:VCALENDAR"))
    check("two VEVENTs", ics.count("BEGIN:VEVENT"), 2)
    check("VEVENTs are closed", ics.count("END:VEVENT"), 2)
    check_true("CRLF line endings", "\r\n" in ics and "\n\r" not in ics)
    check_true("declares a refresh interval",
               "REFRESH-INTERVAL;VALUE=DURATION:PT12H" in ics)
    check_true("names the calendar", "X-WR-CALNAME" in ics)

    # UID must match the client-side per-event export in docs/index.html, or a
    # subscriber who already downloaded one show gets it twice.
    check("UID matches the client-side export format",
          _props(ics, "UID")[0],
          "wyxr-event-11111111-1111-1111-1111-111111111111@concert-calendar.wyxr.org")

    check("SUMMARY is 'Artist — Venue'", _props(ics, "SUMMARY")[0],
          "Lucero — Minglewood Hall")
    check("SUMMARY is bare title when venue is empty",
          _props(ics, "SUMMARY")[1], "Open Mic")
    check("LOCATION includes the city", _props(ics, "LOCATION")[0],
          "Minglewood Hall\\, Memphis\\, TN")
    check("LOCATION falls back to the city", _props(ics, "LOCATION")[1],
          "Memphis\\, TN")

    check("URL prefers the ticket link", _props(ics, "URL")[0],
          "https://example.com/tix")
    check("URL falls back to the event permalink", _props(ics, "URL")[1],
          "https://concert-calendar.wyxr.org/e/22222222-2222-2222-2222-222222222222")

    cats = _props(ics, "CATEGORIES")[0]
    check("badges and genre become categories", cats, "WYXR Presents,WYXR Pick,Rock")

    check("LAST-MODIFIED from updated_at", _props(ics, "LAST-MODIFIED"),
          ["20260801T120000Z"])

    desc = _props(ics, "DESCRIPTION")[0]
    check_true("description carries doors and show times",
               "Doors 7:00 PM / Show 8:00 PM" in desc)
    check_true("description carries the permalink",
               "concert-calendar.wyxr.org/e/11111111" in desc)
    check_true("description carries the ticket link",
               "Tickets: https://example.com/tix" in desc)


def test_url_safety():
    # Ticket URLs come from scrapers and from OCR of uploaded flyers.
    check("javascript: rejected", _http_url("javascript:alert(1)"), "")
    check("data: rejected", _http_url("data:text/html,<script>"), "")
    check("relative path rejected", _http_url("/event-images/x.jpg"), "")
    check("protocol-relative rejected", _http_url("//evil.example.com"), "")
    check("None rejected", _http_url(None), "")
    check("http kept", _http_url("http://a.example"), "http://a.example")
    check("https kept", _http_url(" https://a.example "), "https://a.example")

    ics = generate_ics(
        [{"id": "f", "title": "Bad Link", "venue": "Hi Tone", "date": "2026-10-02",
          "ticket_url": "javascript:alert(1)"}], BUILD)
    check_true("javascript: never reaches URL", "javascript:" not in ics)
    check("URL falls back to the permalink", _props(ics, "URL"),
          ["https://concert-calendar.wyxr.org/e/f"])


def test_bad_dates_skipped():
    ics = generate_ics(
        [{"id": "g", "title": "Good", "venue": "Hi Tone", "date": "2026-10-03"},
         {"id": "h", "title": "No Date", "venue": "Hi Tone", "date": ""},
         {"id": "i", "title": "Junk Date", "venue": "Hi Tone", "date": "not-a-date"},
         {"id": "j", "title": "Null Date", "venue": "Hi Tone", "date": None}],
        BUILD)
    # A broken DTSTART makes some clients reject the entire file, so unparseable
    # dates are dropped rather than emitted.
    check("only the parseable event is emitted", ics.count("BEGIN:VEVENT"), 1)
    check("empty feed is still a valid calendar",
          generate_ics([], BUILD).count("BEGIN:VCALENDAR"), 1)


def main():
    print("Testing iCalendar feed generation...\n")
    test_start_time_parsing()
    test_dst_offsets()
    test_default_time_and_day_boundary()
    test_escaping()
    test_folding()
    test_structure()
    test_url_safety()
    test_bad_dates_skipped()

    if FAILURES:
        print(f"❌ {len(FAILURES)} of {CHECKS[0]} checks failed:\n")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"✅ All {CHECKS[0]} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
