#!/usr/bin/env python3
"""Regression tests for the nightly health check's noise filtering.

The check previously reported false positives that trained us to ignore it:
a venue rename left a "ghost" source name that aged into a staleness warning,
and a scraper whose events all fell outside the build's date window looked like
a scraper that had parsed nothing. These tests pin both behaviours, plus the
requirement that genuinely-broken scrapers still get flagged.

Runs offline — no database, no network. Uses docs/log.json (a real build log
committed by every build) as the fixture.

Usage:
    python scripts/test_health_check.py
"""
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import backend.app as app_mod  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "nightly_health_check", os.path.join(ROOT, "scripts", "nightly_health_check.py")
)
nhc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nhc)

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def load_fixture_sources():
    """docs/log.json's per-source shape, translated to the DB details shape.

    The build writes the post-filter count as events_after_filter in
    docs/log.json but as events in scrape_logs.details (src/main.py).
    """
    with open(os.path.join(ROOT, "docs", "log.json")) as fh:
        log = json.load(fh)
    return [
        {
            "name": s["name"],
            "success": s["success"],
            "events": s.get("events_after_filter"),
            "events_found": s.get("events_found"),
            "events_filtered": s.get("events_filtered"),
            "error": s.get("error"),
        }
        for s in log["sources"]
    ]


def scrapers_from(builds):
    """builds: list of (sources, hours_ago), newest first."""
    now = datetime.now(timezone.utc)
    rows = [
        {
            "started_at": now - timedelta(hours=hours_ago),
            "status": "success",
            "details": {"sources": sources},
        }
        for sources, hours_ago in builds
    ]
    app_mod.health_recent_build_logs = lambda limit=30: rows
    return app_mod._health_scrapers()


def report_for(scrapers, incomplete=None):
    blocks = {
        "events_14d": {
            "total": 138,
            "by_day": [{"date": "2026-07-26", "count": 5}],
            "incomplete": incomplete or {"total": 0, "by_source": []},
        },
        "scrapers": scrapers,
        "submissions": {"pending_count": 0, "oldest_pending_age_hours": None},
        "ticketmaster": {"errors_24h": 0, "last_successful_run_at": None},
    }
    text, _ = nhc.format_report(200, blocks, None, 200, nhc.FRONTEND_URL, None)
    return text


def expected_count():
    from src.config import VENUES
    return len([v for v in VENUES.values() if v.get("scraper") != "manual_only"]) + 2


# ---------------------------------------------------------------------------
def test_rename_does_not_look_like_an_outage():
    """A venue's old logged name must fold into its current one.

    Renaming a venue changes the "Venue: <name>" string written to build logs.
    The old name used to survive as its own entry, frozen at the last build that
    used it, and tripped the >14h staleness rule every day until it aged out.
    """
    print("\nrename folds into the current name")
    current = load_fixture_sources()
    # Same venue under its previous display name, in an older build.
    ghost = [dict(s, name="Venue: Horseshoe Casino's Bluesville")
             for s in current if s["name"] == "Venue: Bluesville at Horseshoe"]
    assert ghost, "fixture no longer contains the Bluesville venue"

    scr = scrapers_from([(current, 2.0), (ghost, 46.4)])
    names = {s["name"] for s in scr}

    check("old name is gone", "Venue: Horseshoe Casino's Bluesville" not in names)
    check("current name present", "Venue: Bluesville at Horseshoe" in names)
    bv = next(s for s in scr if s["name"] == "Venue: Bluesville at Horseshoe")
    check("takes the newest run, not the stale one",
          bv["hours_since_last_run"] < 14, f"{bv['hours_since_last_run']}h")
    check("not counted twice", len(scr) == expected_count(), str(len(scr)))
    check("no staleness warning in the report",
          "46.4h" not in report_for(scr))


def test_removed_venue_stays_visible():
    """A name that maps to no configured venue must not be silently dropped.

    Folding by alias is what makes renames quiet; it must not also hide a
    scraper that genuinely disappeared.
    """
    print("\nremoved venue is reported, not hidden")
    sources = load_fixture_sources() + [{
        "name": "Venue: Some Closed Venue", "success": True,
        "events": 3, "events_found": 3, "events_filtered": 0, "error": None,
    }]
    scr = scrapers_from([(sources, 2.0)])
    retired = [s for s in scr if s.get("retired")]

    check("flagged retired", [s["name"] for s in retired] == ["Venue: Some Closed Venue"])
    check("excluded from the scraper tally",
          len([s for s in scr if not s.get("retired")]) == expected_count())
    text = report_for(scr)
    check("named in the report", "Some Closed Venue" in text)
    # The fixture build has its own real failures, so don't assert all-clean —
    # the invariant is that the retired entry stays out of the denominator.
    check("not added to the scraper denominator",
          f"/{expected_count()} clean" in text,
          next(l for l in text.splitlines() if "clean" in l).strip())
    check("retired entry is not itself a warning",
          not any("Some Closed Venue" in l for l in text.splitlines()
                  if l.startswith("⚠️")))


def test_all_filtered_out_is_not_a_failure():
    """Parsed fine but every show outside the date window != parsed nothing.

    The check reads events_found (pre-filter). Reading the post-filter count
    made a healthy venue whose only listing had just passed look broken.
    """
    print("\nevents outside the date window are not a failure")
    sources = [{
        "name": "Venue: South Main Sounds", "success": True,
        "events": 0, "events_found": 1, "events_filtered": 1, "error": None,
    }]
    scr = scrapers_from([(sources, 2.0)])
    sms = next(s for s in scr if s["name"] == "Venue: South Main Sounds")

    check("counted pre-filter", sms["last_result_count"] == 1)
    check("post-filter count still exposed", sms["last_result_count_after_filter"] == 0)
    text = report_for(scr)
    check("no warning emitted", "⚠️ Venue: South Main Sounds" not in text)
    check("shown as informational instead",
          "Venue: South Main Sounds — 1 parsed, none in date range" in text)


def test_real_breakage_still_flagged():
    """De-noising must not swallow actual failures."""
    print("\nreal failures still surface")
    sources = [
        {"name": "Venue: Lafayette's Music Room", "success": False, "events": 0,
         "events_found": 0, "events_filtered": 0,
         "error": "Request failed: 403 Client Error: Forbidden"},
        {"name": "scraper:ticketmaster", "success": True, "events": 0,
         "events_found": 0, "events_filtered": 0, "error": None},
        {"name": "artifact", "success": True, "events": 0,
         "events_found": 0, "events_filtered": 0, "error": "No artifacts/ folder found"},
    ]
    text = report_for(scrapers_from([(sources, 2.0)]))
    warns = [l for l in text.splitlines() if l.startswith("⚠️")]

    check("failed scraper flagged", any("Lafayette" in w for w in warns))
    check("zero-parse scraper flagged", any("ticketmaster" in w for w in warns))
    check("artifact zero is still tolerated", not any("artifact" in w for w in warns))
    check("summary points at the scrapers", "need attention" in text)


def test_incomplete_line_reconciles():
    """The headline total must equal the parts shown beside it.

    It used to print an all-source total next to a scraper-only breakdown, so
    the numbers looked like an arithmetic error.
    """
    print("\nincomplete records line adds up")
    incomplete = {
        "total": 49,
        "by_source": [
            {"source": "scraper:lafayette_s_music_room", "incomplete_count": 12, "total_count": 20},
            {"source": "scraper:hernando_s_hideaway", "incomplete_count": 4, "total_count": 12},
            {"source": "artifact", "incomplete_count": 19, "total_count": 40},
            {"source": "manual", "incomplete_count": 5, "total_count": 20},
        ],
    }
    text = report_for(scrapers_from([(load_fixture_sources(), 2.0)]), incomplete)
    line = next(l for l in text.splitlines() if "Incomplete records" in l)

    check("headline total shown", "49" in line, line.strip())
    check("scraper subtotal shown", "16 from scrapers" in line)
    check("remainder named", "33 manual/artifact" in line)
    check("biggest offender listed first",
          line.index("lafayette") < line.index("hernando"))


def test_provides_narrows_the_completeness_rule():
    """Venues that never publish a field must not be flagged for it forever."""
    print("\nper-venue provides declarations")
    from src.config import COMPLETENESS_FIELDS, SOURCE_PROVIDES, venue_source_tag

    check("Hi Tone not expected to supply a time",
          "start_time" not in SOURCE_PROVIDES[venue_source_tag("Hi Tone")])
    check("Hi Tone still expected to supply a ticket link",
          "ticket_url" in SOURCE_PROVIDES[venue_source_tag("Hi Tone")])
    check("B.B. King's not expected to supply a ticket link",
          "ticket_url" not in SOURCE_PROVIDES[venue_source_tag("B.B. King's Blues Club")])
    check("Growlers expected to supply both (no declaration)",
          set(SOURCE_PROVIDES[venue_source_tag("Growlers")]) == set(COMPLETENESS_FIELDS))
    check("every venue has an entry", len(SOURCE_PROVIDES) >= expected_count() - 2)


def main():
    print("Health check regression tests (offline)")
    for fn in (
        test_rename_does_not_look_like_an_outage,
        test_removed_venue_stays_visible,
        test_all_filtered_out_is_not_a_failure,
        test_real_breakage_still_flagged,
        test_incomplete_line_reconciles,
        test_provides_narrows_the_completeness_rule,
    ):
        fn()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("All health check regression tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
