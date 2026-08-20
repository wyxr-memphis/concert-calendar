#!/usr/bin/env python3
"""Regression tests for event identity: date, title and venue normalization.

These three functions together produce ``events.dedup_key`` — the persisted
identity of an event — so a silent change in any of them corrupts dedup for
every row it touches. Each test below pins a bug that actually shipped:

  * parse_date_text dropped Jan-Mar shows from every December build, because a
    year-less "Jan 15" resolved to the current year and then failed the
    START_DATE window filter.
  * normalize_text stripped noise words without word boundaries, eating the
    insides of real names ("Tourist" -> "ist", "Toliver" -> "to r",
    "afternoon" -> "a ernoon", "drafts" -> "dra s").
  * normalize_venue_name matched aliases as bidirectional substrings, rewriting
    unrelated venues to the wrong canonical name ("Live" -> Graceland
    Soundstage, "Nashoba Valley Ski Area" -> Nashoba).

Runs offline — no database, no network.

Usage:
    python scripts/test_normalization.py
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.config import normalize_venue_name  # noqa: E402
from src.date_utils import parse_date_text, resolve_yearless_date  # noqa: E402
from src.models import normalize_text  # noqa: E402
from src.normalize import _artists_match  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def eq(label, got, want):
    check(label, got == want, f"got {got!r}, want {want!r}" if got != want else "")


# ---------------------------------------------------------------------------
# 1.1  Year rollover
# ---------------------------------------------------------------------------

def test_december_build_keeps_january_shows():
    """The bug: a December build parsed "Jan 15" as *this* January and dropped it."""
    dec = date(2026, 12, 15)
    for text in ("Jan 15", "January 15", "1/15", "Wed Jan 15"):
        eq(f"December build: {text!r} -> next January",
           parse_date_text(text, dec), date(2027, 1, 15))
    eq("December build: 'Mar 3' -> next March",
       parse_date_text("Mar 3", dec), date(2027, 3, 3))


def test_near_dates_are_not_pushed_a_year_out():
    """A listing a few days stale must stay put, not jump 12 months."""
    dec = date(2026, 12, 15)
    eq("same month, days earlier, stays in current year",
       parse_date_text("Dec 2", dec), date(2026, 12, 2))
    eq("later this month stays in current year",
       parse_date_text("Dec 20", dec), date(2026, 12, 20))


def test_explicit_years_are_respected():
    dec = date(2026, 12, 15)
    eq("explicit year wins (abbrev month)",
       parse_date_text("Feb 12, 2026", dec), date(2026, 2, 12))
    eq("explicit year wins (ISO)",
       parse_date_text("2026-03-05", dec), date(2026, 3, 5))
    eq("explicit year wins (slashes)",
       parse_date_text("12/20/2026", date(2026, 6, 15)), date(2026, 12, 20))


def test_unparseable_and_impossible_dates():
    eq("junk returns None", parse_date_text("garbage", date(2026, 12, 15)), None)
    eq("empty returns None", parse_date_text("", date(2026, 12, 15)), None)
    eq("Feb 29 resolves to the leap year",
       resolve_yearless_date(2, 29, date(2027, 12, 1)), date(2028, 2, 29))


def test_admin_import_shares_the_rule():
    """backend/app.py's _normalize_date_iso must not re-implement the old bug."""
    os.environ.setdefault("ADMIN_PASSWORD", "test-only")
    import backend.app as app_mod

    today = date.today()
    got = app_mod._normalize_date_iso("Jan 15")
    check("admin import resolves a year-less date", got is not None, f"got {got!r}")
    if got:
        parsed = date.fromisoformat(got)
        check("admin import never lands in the past",
              parsed >= today, f"{parsed} < {today}")


# ---------------------------------------------------------------------------
# 1.2  Title normalization
# ---------------------------------------------------------------------------

def test_noise_words_only_strip_as_whole_words():
    """Every one of these was corrupted by the un-bounded strip regex."""
    for title, want in [
        ("Tourist", "tourist"),
        ("Showcase Showdown", "showcase showdown"),
        ("Olive Branch Boys", "olive branch boys"),
        ("Don Toliver: Octane", "don toliver octane"),
        ("An Afternoon in Havana", "an afternoon in havana"),
        ("Crafts & Drafts", "crafts drafts"),
        ("Blue Shift Ensemble", "blue shift ensemble"),
        ("Freakshow Open Stage", "freakshow open stage"),
        ("Mudshow", "mudshow"),
        ("PGA Tour: Masters Tournament", "pga masters tournament"),
        ("Greensky Afterparty", "greensky afterparty"),
        ("Loftys Comets", "loftys comets"),
    ]:
        eq(f"whole-word strip: {title!r}", normalize_text(title), want)


def test_noise_words_still_strip_when_standalone():
    """The feature the regex was there for must keep working."""
    eq("trailing 'Live' is dropped", normalize_text("The Beatles - Live"), "beatles")
    eq("'feat.' is dropped", normalize_text("Band feat. Guest"), "band guest")
    eq("'Presents' is dropped", normalize_text("Artist Presents Something"),
       "artist something")
    eq("bracketed room is dropped", normalize_text("Band [Small Room-Downstairs]"), "band")


def test_noise_strip_never_empties_a_title():
    """An event actually called "Live" must not normalize to the empty string."""
    for title in ("Live", "Show", "Concert", "Tour"):
        eq(f"{title!r} survives", normalize_text(title), title.lower())


# ---------------------------------------------------------------------------
# 1.2 (related)  Fuzzy artist matching
# ---------------------------------------------------------------------------

def test_placeholder_titles_do_not_swallow_real_acts():
    check("'Live Music' does not match a named act",
          not _artists_match("Live Music", "Memphis Music Collective"))
    check("'TBA' does not match a named act",
          not _artists_match("TBA", "Some Real Band"))
    check("identical placeholders still match",
          _artists_match("Live Music", "Live Music"))


def test_real_acts_still_match():
    check("guest-list suffix still matches",
          _artists_match("Lucero", "Lucero with special guests"))
    check("'Live' suffix still matches", _artists_match("Demola", "Demola Live"))
    check("spacing difference still matches", _artists_match("Slamhound", "Slam Hound"))
    check("distinct acts do not match",
          not _artists_match("The Beatles", "The Rolling Stones"))
    check("substring must land on a word boundary",
          not _artists_match("music", "musical youth"))


# ---------------------------------------------------------------------------
# 1.3  Venue canonicalization
# ---------------------------------------------------------------------------

def test_loose_names_are_not_rewritten():
    """Each of these was silently rewritten to an unrelated venue."""
    for name in ("Live", "Nashoba Valley Ski Area", "Bside Bistro",
                 "Some Brand New Venue"):
        eq(f"passes through: {name!r}", normalize_venue_name(name), name)


def test_known_venues_still_canonicalize():
    for name, want in [
        ("Hi-Tone", "Hi Tone"),
        ("hi tone café", "Hi Tone"),
        ("Hi-Tone Cafe, Memphis, TN", "Hi Tone"),
        ("Huey's (Midtown)", "Huey's"),
        ("Hueys (Downtown)", "Huey's"),
        ("Huey’s", "Huey's"),                       # curly apostrophe
        ("Grind City Amp", "Grind City Amphitheater"),
        ("Halloran Centre at The Orpheum", "Orpheum Theatre"),
        ("The Green Room at Crosstown Arts", "Crosstown Arts"),
        ("FedEx Forum", "FedExForum"),
        ("B.B. King's Blues Club", "B.B. King's Blues Club"),
        ("A Foreigners Journey To Boston LIVE @ Minglewood Hall Memphis",
         "Minglewood Hall"),
    ]:
        eq(f"canonicalizes: {name!r}", normalize_venue_name(name), want)


def test_empty_venue_is_safe():
    eq("empty string", normalize_venue_name(""), "")
    eq("None", normalize_venue_name(None), "")


def main():
    print("Normalization regression tests (offline)")
    for fn in (
        test_december_build_keeps_january_shows,
        test_near_dates_are_not_pushed_a_year_out,
        test_explicit_years_are_respected,
        test_unparseable_and_impossible_dates,
        test_admin_import_shares_the_rule,
        test_noise_words_only_strip_as_whole_words,
        test_noise_words_still_strip_when_standalone,
        test_noise_strip_never_empties_a_title,
        test_placeholder_titles_do_not_swallow_real_acts,
        test_real_acts_still_match,
        test_loose_names_are_not_rewritten,
        test_known_venues_still_canonicalize,
        test_empty_venue_is_safe,
    ):
        fn()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("All normalization regression tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
