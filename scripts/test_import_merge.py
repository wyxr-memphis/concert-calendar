#!/usr/bin/env python3
"""Regression tests for update-on-duplicate imports.

Before this, every import path treated "this show is already on the calendar"
as "drop the incoming data": the Slack flyer flow skipped it silently, Admin →
Import → Confirm filed it under `skipped` next to bad dates, and Submission
Approve hit create_event's ON CONFLICT backstop and returned the existing row
while the UI said "Event created". A gig poster uploaded a week after the
venue's month schedule never reached the row it described.

Now a match has its BLANK fields filled from the import (image, time, ticket
link, price, description) — fill-only, nothing stored is replaced, `source`
and identity are never touched, and manual rows are filled like any other.

Runs offline. Every DB helper the handlers reach for is stubbed on the app
module — test_before_push.sh sources .env, so an unstubbed call would read or
write the production database. Nothing here needs DATABASE_URL.

Usage:
    python scripts/test_import_merge.py
"""
import os
import sys
import types
from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ADMIN_PASSWORD", "correct-horse-battery-staple")
os.environ.setdefault("ADMIN_SECRET_KEY", "test-only-secret-key")

import backend.app as app_mod  # noqa: E402
import backend.db as db_mod  # noqa: E402
from backend.auth import create_token  # noqa: E402
from backend.db import ENRICH_FIELDS, fields_to_fill  # noqa: E402

# The audit writer runs on every admin write via after_request; silence it
# for the whole module so nothing lands in the production audit log.
app_mod.log_admin_action = lambda **kwargs: None
app_mod.app.config["TESTING"] = True
app_mod.app.config["PROPAGATE_EXCEPTIONS"] = False

FAILURES = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def auth_headers():
    return {"Authorization": f"Bearer {create_token()}"}


@contextmanager
def stubbed(module, **replacements):
    """Swap module attributes for the duration of a test, restoring after."""
    originals = {name: getattr(module, name) for name in replacements}
    for name, value in replacements.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(module, name, value)


EXISTING_ID = "aaaaaaaa-0000-4000-8000-00000000000a"
IN_RANGE = date.today() + timedelta(days=7)


def existing_row(**overrides):
    row = {
        "id": EXISTING_ID,
        "title": "Sweet Darlin w/ Ibex Clone",
        "venue": "Bar DKDC",
        "date": IN_RANGE,
        "start_time": None,
        "doors_time": None,
        "ticket_url": None,
        "ticket_price": None,
        "image_url": None,
        "description": None,
        "genre": None,
        "neighborhood": "Cooper-Young",
        "source": "artifact",
        "is_active": True,
        "is_featured": False,
        "is_wyxr_presents": False,
        "dedup_key": "k",
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


def fake_enrich_factory(calls, existing):
    """An enrich_event stub that applies the real fill rule to `existing`."""
    def fake_enrich(event_id, incoming):
        fill = fields_to_fill(existing, incoming)
        calls.append((event_id, dict(fill)))
        row = dict(existing)
        row.update(fill)
        return row, sorted(fill)
    return fake_enrich


# ---------------------------------------------------------------------------
# 1. The merge rule itself
# ---------------------------------------------------------------------------

def test_fields_to_fill_rule():
    print("\nfields_to_fill — the fill-only rule")
    existing = existing_row(ticket_url="https://tix.example/keep", description="")
    incoming = {
        "title": "SWEET DARLIN",            # identity — must be ignored
        "venue": "Somewhere Else",          # identity — must be ignored
        "date": "2099-01-01",               # identity — must be ignored
        "source": "manual",                 # never changed by a merge
        "is_featured": True,                # flags are never merged
        "image_url": " https://res.cloudinary.com/x/flyer.jpg ",
        "start_time": "8:00 PM",
        "ticket_url": "https://tix.example/REPLACE-ATTEMPT",
        "description": "Doors at 7.",
        "ticket_price": "",                 # blank incoming — nothing to add
        "genre": None,
    }
    fill = fields_to_fill(existing, incoming)

    check("blank image_url is filled", fill.get("image_url") == "https://res.cloudinary.com/x/flyer.jpg",
          str(fill.get("image_url")))
    check("incoming strings are stripped", not fill.get("image_url", "").startswith(" "))
    check("blank start_time is filled", fill.get("start_time") == "8:00 PM")
    check("empty-string description counts as blank and is filled",
          fill.get("description") == "Doors at 7.")
    check("a stored ticket_url is never replaced", "ticket_url" not in fill, str(fill))
    check("blank incoming values add nothing", "ticket_price" not in fill and "genre" not in fill)
    for ident in ("title", "venue", "date", "source", "is_featured"):
        check(f"{ident} is never part of a merge", ident not in fill)
    check("only ENRICH_FIELDS columns appear", set(fill) <= set(ENRICH_FIELDS), str(set(fill)))

    manual = existing_row(source="manual")
    fill = fields_to_fill(manual, {"image_url": "https://img/x.jpg"})
    check("a manual row still gets its blanks filled", fill == {"image_url": "https://img/x.jpg"}, str(fill))

    check("nothing to fill → empty dict", fields_to_fill(existing_row(image_url="https://a"),
                                                          {"image_url": "https://b"}) == {})


# ---------------------------------------------------------------------------
# 2. Admin → Import → Confirm
# ---------------------------------------------------------------------------

def test_import_confirm_merges_duplicates():
    print("\nPOST /api/admin/import/confirm")
    existing = existing_row()
    enrich_calls, inserted_batches = [], []

    def fake_find(title, venue, date_str, threshold=0.8, lineup=None):
        return dict(existing) if title.lower().startswith("sweet darlin") else None

    def fake_bulk(events_list):
        inserted_batches.append(list(events_list))
        return [dict(e, id=f"new-{i}") for i, e in enumerate(events_list)]

    payload = {"events": [
        {"title": "Sweet Darlin w/ Ibex Clone", "venue": "Bar DKDC", "date": IN_RANGE.isoformat(),
         "start_time": "9 PM", "ticket_url": "https://tix.example/sd"},
        {"title": "Memphis Dyke Night", "venue": "Bar DKDC", "date": IN_RANGE.isoformat()},
        {"title": "Bad Date Show", "venue": "Bar DKDC", "date": "not a date"},
    ]}

    with stubbed(app_mod, find_fuzzy_duplicate=fake_find,
                 enrich_event=fake_enrich_factory(enrich_calls, existing),
                 bulk_insert_events=fake_bulk):
        c = app_mod.app.test_client()
        resp = c.post("/api/admin/import/confirm", json=payload)
        check("401 without auth", resp.status_code == 401, f"got {resp.status_code}")
        check("nothing reached the database unauthenticated", not enrich_calls and not inserted_batches)

        resp = c.post("/api/admin/import/confirm", json=payload, headers=auth_headers())
        body = resp.get_json() or {}
        check("200 with a Bearer header", resp.status_code == 200, f"got {resp.status_code}")
        check("one new event imported", body.get("imported") == 1, str(body))
        check("only the new event was inserted",
              [e["title"] for b in inserted_batches for e in b] == ["Memphis Dyke Night"],
              str(inserted_batches))
        check("the existing show was enriched, not inserted",
              enrich_calls and enrich_calls[0][0] == EXISTING_ID, str(enrich_calls))
        check("it was filled with time + ticket link",
              enrich_calls and enrich_calls[0][1] == {"start_time": "9 PM",
                                                      "ticket_url": "https://tix.example/sd"},
              str(enrich_calls))
        check("response lists it under `updated`", body.get("updated") == ["Sweet Darlin w/ Ibex Clone"],
              str(body.get("updated")))
        check("bad dates alone are `skipped`", body.get("skipped") == ["Bad Date Show"], str(body.get("skipped")))
        check("no stale `duplicates` entry", body.get("duplicates") == [], str(body.get("duplicates")))

    # Everything already present and complete: still a 200, reported as duplicates.
    full = existing_row(start_time="9 PM", ticket_url="https://tix.example/sd")
    enrich_calls.clear()
    inserted_batches.clear()
    with stubbed(app_mod, find_fuzzy_duplicate=lambda *a, **k: dict(full),
                 enrich_event=fake_enrich_factory(enrich_calls, full),
                 bulk_insert_events=fake_bulk):
        resp = app_mod.app.test_client().post(
            "/api/admin/import/confirm", json={"events": payload["events"][:1]}, headers=auth_headers())
        body = resp.get_json() or {}
        check("all-duplicates is 200, not 400", resp.status_code == 200, f"got {resp.status_code}")
        check("…with the show under `duplicates`", body.get("duplicates") == [full["title"]], str(body))
        check("…and nothing imported or updated", body.get("imported") == 0 and body.get("updated") == [],
              str(body))
        check("bulk insert not called for an empty batch", not inserted_batches)

    # Only bad dates → the original 400 still applies.
    with stubbed(app_mod, find_fuzzy_duplicate=lambda *a, **k: None,
                 enrich_event=lambda *a, **k: (None, []),
                 bulk_insert_events=fake_bulk):
        resp = app_mod.app.test_client().post(
            "/api/admin/import/confirm", json={"events": payload["events"][2:]}, headers=auth_headers())
        check("only-bad-dates is still a 400", resp.status_code == 400, f"got {resp.status_code}")


# ---------------------------------------------------------------------------
# 3. Admin → Submissions → Approve
# ---------------------------------------------------------------------------

def _submission(**overrides):
    sub = {
        "id": 7,
        "status": "pending",
        "artist_name": "Sweet Darlin w/ Ibex Clone",
        "venue": "Bar DKDC",
        "event_date": IN_RANGE,
        "event_time": None,
        "doors_time": None,
        "description": "Two sets, no cover.",
        "ticket_url": "https://tix.example/sd",
        "ticket_price": "$10",
        "genre": None,
        "has_image": True,
    }
    sub.update(overrides)
    return sub


def test_submission_approve_merges_into_existing():
    print("\nPOST /api/admin/submissions/<id>/approve")
    existing = existing_row()
    enrich_calls, promote_calls, status_calls, create_calls = [], [], [], []

    def fake_promote(submission_id, sub):
        promote_calls.append(submission_id)
        return "https://res.cloudinary.com/x/sub7.jpg"

    def fake_status(submission_id, status, created_event_id=None):
        status_calls.append((submission_id, status, created_event_id))

    def fake_create(data):
        create_calls.append(data)
        return dict(data, id="brand-new")

    common = dict(
        get_submission_by_id=lambda sid: _submission() if sid == 7 else None,
        normalize_venue_from_db=lambda v: ("Bar DKDC", "Cooper-Young"),
        _promote_submission_image=fake_promote,
        update_submission_status=fake_status,
        create_event=fake_create,
    )

    # a) existing row with NO image → image promoted and filled along with the rest
    with stubbed(app_mod, find_fuzzy_duplicate=lambda *a, **k: dict(existing),
                 enrich_event=fake_enrich_factory(enrich_calls, existing), **common):
        resp = app_mod.app.test_client().post("/api/admin/submissions/7/approve", headers=auth_headers())
        body = resp.get_json() or {}
        check("200 (merged), not 201 (created)", resp.status_code == 200, f"got {resp.status_code}")
        check("response flags the merge", body.get("merged_into_existing") is True, str(body))
        check("image was promoted because the row had none", promote_calls == [7], str(promote_calls))
        check("enrich filled image, ticket link, price, description",
              enrich_calls and set(enrich_calls[0][1]) == {"image_url", "ticket_url", "ticket_price",
                                                           "description"},
              str(enrich_calls))
        check("`filled` is reported", set(body.get("filled") or []) == {"image_url", "ticket_url",
                                                                        "ticket_price", "description"},
              str(body.get("filled")))
        check("submission marked approved → the EXISTING event id",
              status_calls == [(7, "approved", EXISTING_ID)], str(status_calls))
        check("create_event was not called", not create_calls)
        check("the response is the existing event", body.get("id") == EXISTING_ID, str(body.get("id")))

    # b) existing row already HAS an image → no Cloudinary upload (no orphan)
    has_img = existing_row(image_url="https://res.cloudinary.com/x/already.jpg")
    enrich_calls.clear(); promote_calls.clear(); status_calls.clear()
    with stubbed(app_mod, find_fuzzy_duplicate=lambda *a, **k: dict(has_img),
                 enrich_event=fake_enrich_factory(enrich_calls, has_img), **common):
        resp = app_mod.app.test_client().post("/api/admin/submissions/7/approve", headers=auth_headers())
        body = resp.get_json() or {}
        check("no image promoted when the existing row has one", promote_calls == [], str(promote_calls))
        check("stored image untouched", body.get("image_url") == has_img["image_url"], str(body.get("image_url")))
        check("other blanks still filled", "ticket_url" in (body.get("filled") or []), str(body.get("filled")))

    # c) no match → unchanged create path, 201
    enrich_calls.clear(); promote_calls.clear(); status_calls.clear()
    with stubbed(app_mod, find_fuzzy_duplicate=lambda *a, **k: None,
                 enrich_event=fake_enrich_factory(enrich_calls, existing), **common):
        resp = app_mod.app.test_client().post("/api/admin/submissions/7/approve", headers=auth_headers())
        body = resp.get_json() or {}
        check("201 when the show is new", resp.status_code == 201, f"got {resp.status_code}")
        check("create_event called once", len(create_calls) == 1, str(len(create_calls)))
        check("no merge flag on a create", "merged_into_existing" not in body)
        check("image promoted on the create path", promote_calls == [7], str(promote_calls))
        check("enrich not called", not enrich_calls)


# ---------------------------------------------------------------------------
# 4. Slack flyer upload
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, payload=None, status_code=200, content=b""):
        self._payload = payload or {}
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._payload


def _fake_http(posts):
    """http_requests stand-in: files.info, conversations.history, download, GitHub dispatch."""
    def get(url, **kwargs):
        if url.endswith("files.info"):
            return _Resp({"file": {"id": "F1", "url_private_download": "https://files/x.jpg",
                                   "mimetype": "image/jpeg", "name": "poster.jpg"}})
        if url.endswith("conversations.history"):
            return _Resp({"messages": [{"text": "add to calendar", "files": [{"id": "F1"}]}]})
        return _Resp(status_code=200, content=b"\xff\xd8fakejpeg")

    def post(url, **kwargs):
        posts.append(url)
        return _Resp(status_code=204)

    return types.SimpleNamespace(get=get, post=post)


def _vision_event(title, venue="Bar DKDC", when=IN_RANGE, time=None):
    return SimpleNamespace(artist=title, venue=venue, date=when, time=time, lineup=None, event_name=None)


def _run_slack(events, existing_rows, enrich_calls, inserted_batches, posts, messages, uploaded_url):
    """Drive _process_slack_image with every external surface stubbed."""
    import src.sources.artifacts as artifacts_mod

    def fake_find(title, venue, date_str, threshold=0.8, lineup=None):
        for row in existing_rows:
            if row["title"].lower() == title.lower():
                return dict(row)
        return None

    def fake_enrich(event_id, incoming):
        row = next(r for r in existing_rows if r["id"] == event_id)
        fill = fields_to_fill(row, incoming)
        enrich_calls.append((event_id, dict(fill)))
        merged = dict(row)
        merged.update(fill)
        return merged, sorted(fill)

    def fake_bulk(events_list):
        inserted_batches.append(list(events_list))
        return [dict(e, id=f"new-{i}") for i, e in enumerate(events_list)]

    original_extract = artifacts_mod.extract_events_from_image_bytes
    artifacts_mod.extract_events_from_image_bytes = lambda *a, **k: list(events)
    os.environ["GITHUB_PAT"] = "test-pat"
    try:
        with stubbed(app_mod,
                     http_requests=_fake_http(posts),
                     _slack_post_message=lambda channel, text: messages.append(text),
                     upload_image=lambda *a, **k: uploaded_url,
                     normalize_venue_from_db=lambda v: None,
                     is_fuzzy_duplicate=lambda *a, **k: False,
                     find_fuzzy_duplicate=fake_find,
                     enrich_event=fake_enrich,
                     bulk_insert_events=fake_bulk):
            app_mod._process_slack_image("F1", "C1")
    finally:
        artifacts_mod.extract_events_from_image_bytes = original_extract
        os.environ.pop("GITHUB_PAT", None)


def test_slack_poster_enriches_existing_show():
    print("\nSlack: one-night poster for a show already on the calendar")
    existing = existing_row()
    enrich_calls, inserted, posts, messages = [], [], [], []
    _run_slack([_vision_event("Sweet Darlin w/ Ibex Clone", time="9 PM")],
               [existing], enrich_calls, inserted, posts, messages,
               uploaded_url="https://res.cloudinary.com/x/poster.jpg")

    text = messages[-1] if messages else ""
    check("one reply posted", len(messages) == 1, str(messages))
    check("nothing inserted", not inserted, str(inserted))
    check("existing row enriched with image + time",
          enrich_calls == [(EXISTING_ID, {"image_url": "https://res.cloudinary.com/x/poster.jpg",
                                          "start_time": "9 PM"})], str(enrich_calls))
    check("reply has the 🔄 updated section", "🔄 *1 existing event updated:*" in text, text)
    check("reply says what was added", "(added image, time)" in text, text)
    check("reply links the EXISTING row's edit page", f"/admin/edit?id={EXISTING_ID}|" in text, text)
    check("no ✅ added section", "✅" not in text, text)
    check("no 'already in the calendar' bail-out", "No new events" not in text, text)
    check("rebuild dispatched even though nothing was inserted",
          any("actions/workflows/daily.yml/dispatches" in u for u in posts), str(posts))
    check("rebuild line in the reply", "rebuild triggered" in text, text)


def test_slack_month_schedule_mixed():
    print("\nSlack: month schedule — some new, one existing, one complete")
    complete = existing_row(id="bbbbbbbb-0000-4000-8000-00000000000b", title="Memphis Dyke Night",
                            start_time="8 PM")
    existing = existing_row()
    enrich_calls, inserted, posts, messages = [], [], [], []
    _run_slack([
        _vision_event("Jack Oblivian", when=IN_RANGE + timedelta(days=1)),
        _vision_event("Sweet Darlin w/ Ibex Clone", time="9 PM"),
        _vision_event("Memphis Dyke Night", when=IN_RANGE + timedelta(days=2), time="8 PM"),
    ], [existing, complete], enrich_calls, inserted, posts, messages,
        uploaded_url="https://res.cloudinary.com/x/SHOULD-NOT-ATTACH.jpg")

    text = messages[-1] if messages else ""
    check("one new event inserted", [e["title"] for b in inserted for e in b] == ["Jack Oblivian"], str(inserted))
    check("multi-date flyer image NOT attached to anything",
          all("image_url" not in e for b in inserted for e in b)
          and all("image_url" not in fill for _id, fill in enrich_calls), str((inserted, enrich_calls)))
    check("existing show got its time filled", (EXISTING_ID, {"start_time": "9 PM"}) in enrich_calls,
          str(enrich_calls))
    check("complete show: enrich found nothing to fill",
          (complete["id"], {}) in enrich_calls, str(enrich_calls))
    check("✅ section counts only the insert", "✅ *1 event added from image:*" in text, text)
    check("🔄 section counts only the filled one", "🔄 *1 existing event updated:*" in text, text)
    check("ℹ️ section counts the complete one", "ℹ️ 1 event already on the calendar" in text, text)


def test_slack_nothing_to_add():
    print("\nSlack: everything already present and complete")
    complete = existing_row(start_time="9 PM", image_url="https://res.cloudinary.com/x/have.jpg")
    enrich_calls, inserted, posts, messages = [], [], [], []
    _run_slack([_vision_event("Sweet Darlin w/ Ibex Clone", time="9 PM")],
               [complete], enrich_calls, inserted, posts, messages,
               uploaded_url="https://res.cloudinary.com/x/poster.jpg")
    text = messages[-1] if messages else ""
    check("one reply", len(messages) == 1, str(messages))
    check("reply says nothing new, counts the show", "Nothing new — 1 event" in text, text)
    check("no rebuild dispatched", not any("dispatches" in u for u in posts), str(posts))
    check("nothing inserted", not inserted)


# ---------------------------------------------------------------------------
# 5. Same show, different title — the lineup-aware match (2026-10-04)
# ---------------------------------------------------------------------------
#
# The first live test of update-on-duplicate failed: the Paws & Tunes poster
# for the Oct 4 Rescued Pack benefit at Bar DKDC did not match the row the
# venue's month schedule had already added, because the two titles score 0.53
# and the matcher wanted 0.8. A third row for the same show, from an earlier
# upload of the same poster, had been filed under "38104 Bar DKDC" (Vision
# read the zip code into the venue) and missed on venue similarity (0.73).

POSTER = "Paws & Tunes: A Benefit for The Rescued Pack: Mary Hatley, Alexis Jade, Kim Garmon"
SCHEDULE = "The Rescued Pack Benefit Concert: Alexis Jade, Mary Hatley, Kim Harmon"
OCT4_ROWS = [
    {"id": "sched", "title": SCHEDULE, "venue": "Bar DKDC"},
    {"id": "libra", "title": "Night of the Libra: DJ Larry, DJ Divje Babe, Kid Mestizo, DJ Automatic Black",
     "venue": "Bar DKDC"},
    {"id": "swap", "title": "Graham Winchesters Song Swap: Graham Winchester, Frank McLallen, Ben Church, Jeff Hulett",
     "venue": "Bar DKDC"},
    {"id": "elsewhere", "title": SCHEDULE, "venue": "Hi Tone"},
]


def test_split_title_acts():
    print("\nsplit_title_acts — reading the bill back out of a title")
    from src.models import split_title_acts
    check("named show + acts", split_title_acts(SCHEDULE) == ["Alexis Jade", "Mary Hatley", "Kim Harmon"],
          str(split_title_acts(SCHEDULE)))
    check("show name with its own colon keeps the acts",
          split_title_acts(POSTER) == ["Mary Hatley", "Alexis Jade", "Kim Garmon"], str(split_title_acts(POSTER)))
    check("headliner w/ openers", split_title_acts("Sweet Darlin w/ Ibex Clone") == ["Sweet Darlin", "Ibex Clone"])
    check("lone act", split_title_acts("Foxy Brown") == ["Foxy Brown"])
    check("'&' inside a band name is not a separator",
          split_title_acts("Dale Watson & His Lone Stars") == ["Dale Watson & His Lone Stars"])
    check("empty title → no acts", split_title_acts("") == [] and split_title_acts(None) == [])


def test_clean_venue_text():
    print("\nclean_venue_text — stripping address debris Vision reads into a venue")
    from src.models import clean_venue_text
    cases = {
        "38104 Bar DKDC": "Bar DKDC",
        "Bar DKDC 964 S Cooper St": "Bar DKDC",
        "Lamplighter Lounge, Memphis, TN 38104": "Lamplighter Lounge",
        "B-Side Memphis 38104": "B-Side Memphis",
        "1884 Lounge": "1884 Lounge",          # a real venue — a 4-digit number is not a zip
        "Hi Tone": "Hi Tone",
        "": "",
    }
    for raw, want in cases.items():
        got = clean_venue_text(raw)
        check(f"{raw!r} → {want!r}", got == want, repr(got))
    check("never empties a venue", clean_venue_text("38104") == "38104")


def test_lineup_aware_match():
    print("\n_best_fuzzy_match — same show, different title")
    from backend.db import _best_fuzzy_match, _fuzzy_norm
    from src.models import split_title_acts
    dkdc = {_fuzzy_norm("Bar DKDC")}
    acts = ["Mary Hatley", "Alexis Jade", "Kim Garmon"]

    m = _best_fuzzy_match(OCT4_ROWS, POSTER, dkdc, acts)
    check("poster matches the schedule row via the shared bill", m and m["id"] == "sched", str(m and m["id"]))
    check("…and not the Hi Tone row with the same title", m["id"] != "elsewhere")

    m = _best_fuzzy_match(OCT4_ROWS, POSTER, dkdc, split_title_acts(POSTER))
    check("works with acts read back out of the title (no Vision lineup)", m and m["id"] == "sched")

    m = _best_fuzzy_match(OCT4_ROWS, "Night of the Libra: DJ Larry", dkdc, ["DJ Larry"])
    check("ONE shared act is not enough", m is None, str(m and m["id"]))

    m = _best_fuzzy_match(OCT4_ROWS, "Song Swap: Graham Winchester, Ben Church", dkdc,
                          ["Graham Winchester", "Ben Church"])
    check("two shared acts under a different show name match", m and m["id"] == "swap", str(m and m["id"]))

    m = _best_fuzzy_match(OCT4_ROWS, POSTER, {_fuzzy_norm("Growlers")}, acts)
    check("same bill at a different venue is a different show", m is None, str(m and m["id"]))

    legacy = [{"id": "zip", "title": POSTER, "venue": "38104 Bar DKDC"}]
    m = _best_fuzzy_match(legacy, POSTER, dkdc, acts)
    check("a legacy row filed under the zip-code venue still matches", m and m["id"] == "zip", str(m and m["id"]))
    m = _best_fuzzy_match(legacy, POSTER, {_fuzzy_norm("Hi Tone")}, acts)
    check("…but containment needs the real venue name", m is None)

    both = [{"id": "sched", "title": SCHEDULE, "venue": "Bar DKDC"},
            {"id": "exact", "title": POSTER, "venue": "Bar DKDC"}]
    m = _best_fuzzy_match(both, POSTER, dkdc, acts)
    check("a title hit outranks a lineup-only hit", m and m["id"] == "exact", str(m and m["id"]))


def test_slack_passes_lineup_to_matcher():
    print("\nSlack: the Vision lineup reaches find_fuzzy_duplicate")
    import src.sources.artifacts as artifacts_mod
    seen = []

    def fake_find(title, venue, date_str, threshold=0.8, lineup=None):
        seen.append(lineup)
        return None

    original_extract = artifacts_mod.extract_events_from_image_bytes
    ev = SimpleNamespace(artist=POSTER, venue="Bar DKDC", date=IN_RANGE, time="3 PM",
                         lineup=["Mary Hatley", "Alexis Jade", "Kim Garmon"], event_name="Paws & Tunes")
    artifacts_mod.extract_events_from_image_bytes = lambda *a, **k: [ev]
    inserted = []
    try:
        with stubbed(app_mod,
                     http_requests=_fake_http([]),
                     _slack_post_message=lambda channel, text: None,
                     upload_image=lambda *a, **k: None,
                     normalize_venue_from_db=lambda v: None,
                     is_fuzzy_duplicate=lambda *a, **k: False,
                     find_fuzzy_duplicate=fake_find,
                     enrich_event=lambda *a, **k: (None, []),
                     bulk_insert_events=lambda rows: inserted.extend(rows) or [dict(r, id="n") for r in rows]):
            app_mod._process_slack_image("F1", "C1")
    finally:
        artifacts_mod.extract_events_from_image_bytes = original_extract
    check("lineup passed through", seen == [["Mary Hatley", "Alexis Jade", "Kim Garmon"]], str(seen))
    check("_lineup never reaches the insert allowlist",
          inserted and "_lineup" in inserted[0] and
          "_lineup" not in __import__("backend.db", fromlist=["bulk_insert_events"]).ENRICH_FIELDS)


def main():
    print("Import merge regression tests (offline)")
    for fn in (
        test_fields_to_fill_rule,
        test_split_title_acts,
        test_clean_venue_text,
        test_lineup_aware_match,
        test_slack_passes_lineup_to_matcher,
        test_import_confirm_merges_duplicates,
        test_submission_approve_merges_into_existing,
        test_slack_poster_enriches_existing_show,
        test_slack_month_schedule_mixed,
        test_slack_nothing_to_add,
    ):
        fn()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("All import merge regression tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
