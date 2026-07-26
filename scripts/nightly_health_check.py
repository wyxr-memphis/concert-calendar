#!/usr/bin/env python3
"""Nightly health check: call admin endpoint, post formatted report to Slack.

Designed to run from GitHub Actions — stdlib only, no external deps.

Env vars:
  HEALTH_CHECK_TOKEN   Bearer token for /api/admin/health-check
  SLACK_WEBHOOK_URL    Incoming webhook for #wyxr-ops

Exit codes:
  0  — ran to completion (including reports that contain 🚨 items)
  1  — missing env var, or unhandled crash
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

HEALTH_URL = "https://concert-calendar-api.onrender.com/api/admin/health-check"
FRONTEND_URL = "https://concert-calendar.wyxr.org"
HEALTH_TIMEOUT = 30  # Render warm-up can eat 10–15s
FRONTEND_TIMEOUT = 10
SLACK_TIMEOUT = 15
USER_AGENT = "wyxr-concert-calendar-health-check/1.0"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch_health(token):
    """Call /api/admin/health-check.

    Returns (status_code_or_None, json_body_or_None, error_message_or_None).
    - 200: status=200, body=parsed JSON, error=None
    - 500 with partial payload: status=500, body=parsed JSON, error=None
    - 401/503/etc: status=<code>, body=parsed JSON (if any), error=short text
    - network/timeout: status=None, body=None, error=short text
    """
    req = urllib.request.Request(
        HEALTH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), None
            except json.JSONDecodeError as e:
                return resp.status, None, f"invalid JSON from backend ({e})"
    except urllib.error.HTTPError as e:
        body = None
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
            body = json.loads(raw)
        except Exception:
            pass
        return e.code, body, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, None, f"network error: {e.reason}"
    except TimeoutError:
        return None, None, f"timeout after {HEALTH_TIMEOUT}s"
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def check_frontend():
    """HEAD the frontend, following redirects.

    Returns (status_or_None, final_url_or_None, error_or_None).
    """
    req = urllib.request.Request(
        FRONTEND_URL,
        method="HEAD",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=FRONTEND_TIMEOUT) as resp:
            return resp.status, resp.geturl(), None
    except urllib.error.HTTPError as e:
        return e.code, None, None
    except urllib.error.URLError as e:
        return None, None, f"network error: {e.reason}"
    except TimeoutError:
        return None, None, f"timeout after {FRONTEND_TIMEOUT}s"
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def post_to_slack(webhook_url, text):
    """POST {'text': text} to Slack. Raises on non-2xx."""
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=SLACK_TIMEOUT) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Slack webhook returned HTTP {resp.status}")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _today_label():
    """'Apr 17, 2026' in Central time — no leading zero on the day."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/Chicago"))
    except Exception:
        now = datetime.now()
    return f"{now.strftime('%b')} {now.day}, {now.year}"


def _fmt_day(iso_date_str):
    """'2026-04-20' -> 'Mon 4/20' (no leading zero on month or day)."""
    d = date.fromisoformat(iso_date_str)
    return f"{d.strftime('%a')} {d.month}/{d.day}"


def _is_mon_or_tue(iso_date_str):
    return date.fromisoformat(iso_date_str).weekday() in (0, 1)


def _parse_iso_z(s):
    """'2026-04-17T15:00:00Z' -> aware UTC datetime; None on failure."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_since(dt):
    """Hours between now and an aware UTC datetime; None if dt is None."""
    if dt is None:
        return None
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)


def _retired_line(retired):
    """One line naming source names that no longer map to a configured venue.

    These come from old build logs — a renamed or removed venue. They age out of
    the backend's 30-build lookback on their own; the point of naming them is
    that a rename also leaves event rows under the old source tag.
    """
    names = ", ".join(sorted(s.get("name") or "?" for s in retired))
    noun = "source" if len(retired) == 1 else "sources"
    return f"Retired {noun} still in build logs: {names}"


def format_report(health_status, health_data, health_error,
                  frontend_status, frontend_url, frontend_error):
    """Build the Slack mrkdwn report.

    Returns (text, is_critical).
    """
    today = _today_label()
    header = f"🎵 *Concert Calendar Health Check — {today}*"

    # --- Top-level short circuits (auth, config, unreachable) -------------
    if health_status == 401:
        return (
            f"🚨 {header}\n"
            f"Health-check request returned *401* — token drift. "
            f"Verify `HEALTH_CHECK_TOKEN` matches between the Render backend "
            f"env and the GitHub Actions repo secret."
        ), True

    if health_status == 503:
        return (
            f"🚨 {header}\n"
            f"Health endpoint returned *503* — "
            f"`HEALTH_CHECK_TOKEN` is not configured on the backend."
        ), True

    # Network error or unexpected HTTP status without a parsable body
    if health_data is None and health_status != 500:
        status_txt = f"HTTP {health_status}" if health_status else "no response"
        err_txt = health_error or "unknown error"
        return (
            f"🚨 {header}\n"
            f"Health-check request failed — {status_txt} ({err_txt})."
        ), True

    # --- Normal / partial -------------------------------------------------
    is_partial = (health_status == 500)
    partial_failed = []
    if is_partial:
        blocks = (health_data or {}).get("partial") or {}
        err_field = (health_data or {}).get("error", "") or ""
        partial_failed = [
            p.split(":")[0].strip()
            for p in err_field.split(";")
            if p.strip()
        ]
    else:
        blocks = health_data or {}

    crit = is_partial

    # Events 14d
    events_14d = blocks.get("events_14d") or {}
    total_events = events_14d.get("total")
    by_day = events_14d.get("by_day") or []
    empty_days = [d for d in by_day if d.get("count") == 0]

    if empty_days:
        parts = []
        for d in empty_days:
            iso = d.get("date") or ""
            label = _fmt_day(iso) if iso else "?"
            if iso and _is_mon_or_tue(iso):
                label += " (typical light day)"
            parts.append(label)
        empty_line = ", ".join(parts)
    else:
        empty_line = "none"

    incomplete = events_14d.get("incomplete") or {}
    inc_total = incomplete.get("total", 0) or 0
    inc_by_source = incomplete.get("by_source") or []
    flagged_sources = [
        s for s in inc_by_source
        if (s.get("incomplete_count") or 0) > 0
        and (
            (s.get("source") or "").startswith("scraper:")
            or (s.get("source") or "").startswith("Venue:")
        )
    ]
    # Only scraper sources get itemized, so name the remainder explicitly —
    # otherwise the headline total doesn't add up to the list beside it.
    scraper_inc = sum(s["incomplete_count"] for s in flagged_sources)
    other_inc = inc_total - scraper_inc
    if inc_total == 0:
        incomplete_line = "0"
    elif flagged_sources:
        src_parts = [
            f"{s['source']} — {s['incomplete_count']}"
            for s in sorted(
                flagged_sources,
                key=lambda s: -(s.get("incomplete_count") or 0),
            )
        ]
        incomplete_line = (
            f"{inc_total} — {scraper_inc} from scrapers "
            f"({', '.join(src_parts)})"
        )
        if other_inc > 0:
            incomplete_line += f", {other_inc} manual/artifact (expected)"
    else:
        # Only manual/artifact sources are incomplete — those are expected
        incomplete_line = f"{inc_total} (manual/artifact only — expected)"

    # Scrapers
    all_scrapers = blocks.get("scrapers") or []
    # Names left in old build logs by a renamed or removed venue. Nothing runs
    # them, so they'd age into a permanent staleness warning — report them once,
    # separately, and keep them out of the clean/total tally.
    retired = [s for s in all_scrapers if s.get("retired")]
    scrapers = [s for s in all_scrapers if not s.get("retired")]
    total_scrapers = len(scrapers)
    problem_lines = []
    note_lines = []  # informational, never counts against clean_count
    for s in scrapers:
        name = s.get("name") or "?"
        hours = s.get("hours_since_last_run")
        last_status = s.get("last_run_status")
        count = s.get("last_result_count")
        kept = s.get("last_result_count_after_filter")

        reasons = []
        if hours is None:
            reasons.append("never logged")
        elif hours > 14:
            reasons.append(f"{hours}h since last run")
        if last_status is not None and last_status != "success":
            reasons.append(f"status={last_status}")
        # Artifact scraper only produces events when images are uploaded —
        # zero is the common case, not a failure signal.
        if count == 0 and name != "artifact":
            reasons.append("0 events parsed")

        if reasons:
            problem_lines.append(f"⚠️ {name} — {', '.join(reasons)}")
        elif count and kept == 0:
            # Parsed fine, but every show fell outside the build's date window —
            # normal for a venue whose only listing has just passed.
            note_lines.append(
                f"· {name} — {count} parsed, none in date range"
            )

    clean_count = total_scrapers - len(problem_lines)

    # Submissions
    subs = blocks.get("submissions") or {}
    pending = subs.get("pending_count", 0) or 0
    oldest_age = subs.get("oldest_pending_age_hours")
    subs_critical = oldest_age is not None and oldest_age > 48
    if pending == 0:
        subs_age_line = "queue clear"
    elif oldest_age is None:
        subs_age_line = "unknown"
    elif subs_critical:
        subs_age_line = f"🚨 {oldest_age}h (over 48h threshold)"
        crit = True
    else:
        subs_age_line = f"{oldest_age}h"

    # Ticketmaster
    tm = blocks.get("ticketmaster") or {}
    tm_errors = tm.get("errors_24h", 0) or 0
    tm_last_success_iso = tm.get("last_successful_run_at")
    tm_age = _hours_since(_parse_iso_z(tm_last_success_iso))

    tm_error_line = f"{tm_errors} errors (24h)"
    if tm_errors > 0:
        tm_error_line = f"⚠️ {tm_error_line}"

    if tm_age is None:
        tm_age_line = "last success: unknown"
    elif tm_age > 14:
        tm_age_line = f"⚠️ last success: {tm_age}h ago"
    else:
        tm_age_line = f"last success: {tm_age}h ago"

    # Frontend
    if frontend_error:
        frontend_line = f"🚨 unreachable — {frontend_error}"
        crit = True
    elif frontend_status == 200:
        if frontend_url and frontend_url.rstrip("/") != FRONTEND_URL.rstrip("/"):
            frontend_line = f"✅ 200 OK (followed redirect → {frontend_url})"
        else:
            frontend_line = "✅ 200 OK"
    elif frontend_status in (301, 302):
        frontend_line = f"✅ {frontend_status} (redirect → {frontend_url or '?'})"
    elif frontend_status is None:
        frontend_line = "🚨 no response"
        crit = True
    else:
        frontend_line = f"❌ HTTP {frontend_status}"
        crit = True

    # --- All-green condensed form ---------------------------------------
    all_green = (
        not is_partial
        and not empty_days
        and inc_total == 0
        and not problem_lines
        and not subs_critical
        and tm_errors == 0
        and (tm_age is None or tm_age <= 14)
        and frontend_status == 200
        and frontend_error is None
    )
    if all_green:
        total_txt = total_events if total_events is not None else "?"
        text = (
            f"{header}\n"
            f"All checks passed 🟢 · {total_txt} events in next 14 days"
        )
        # Nothing is broken, but a leftover name still deserves a mention — it
        # means a rename left event rows under the old source tag.
        if retired:
            text += f"\n· {_retired_line(retired)}"
        return text, False

    # --- Full template ----------------------------------------------------
    total_txt = total_events if total_events is not None else "?"
    lines = [header]
    if is_partial:
        fail_txt = ", ".join(partial_failed) if partial_failed else "unknown"
        lines.append(f"⚠️ Partial data — failed blocks: {fail_txt}")

    lines += [
        "",
        f"*Events (next 14 days):* {total_txt} events",
        f"· Empty days: {empty_line}",
        f"· Incomplete records: {incomplete_line}",
        "",
        f"*Scrapers:* {clean_count}/{total_scrapers} clean",
    ]
    if problem_lines:
        lines += problem_lines
    else:
        lines.append(f"· All {total_scrapers} ran in last 14h")
    lines += note_lines
    if retired:
        lines.append(f"· {_retired_line(retired)}")
    lines += [
        "",
        f"*Community Submissions:* {pending} pending",
        f"· Oldest: {subs_age_line}",
        "",
        f"*Ticketmaster API:* {tm_error_line}",
        f"· {tm_age_line}",
        "",
        f"*Frontend:* {frontend_line}",
        "",
        "---",
        _summary_line(
            is_partial=is_partial,
            frontend_status=frontend_status,
            frontend_error=frontend_error,
            subs_critical=subs_critical,
            problem_lines=problem_lines,
            empty_days=empty_days,
            inc_total=inc_total,
            tm_errors=tm_errors,
            tm_age=tm_age,
        ),
    ]
    text = "\n".join(lines)
    if crit:
        text = "🚨 " + text
    return text, crit


def _summary_line(*, is_partial, frontend_status, frontend_error,
                  subs_critical, problem_lines, empty_days, inc_total,
                  tm_errors, tm_age):
    """One-sentence summary naming the most important issue."""
    if frontend_error or (frontend_status and frontend_status >= 400):
        return "Frontend is the top priority — visitors can't reach the calendar."
    if is_partial:
        return "Backend returned partial data — investigate the failed blocks."
    if subs_critical:
        return "Clear the submissions queue — oldest entry is over 48h old."
    if problem_lines:
        n = len(problem_lines)
        verb = "needs" if n == 1 else "need"
        return f"{n} scraper{'s' if n != 1 else ''} {verb} attention."
    if empty_days:
        n = len(empty_days)
        return f"{n} empty day{'s' if n != 1 else ''} in the next 14 — worth a look."
    if tm_errors > 0:
        return "Ticketmaster API had errors in the last 24h."
    if tm_age is not None and tm_age > 14:
        return "Ticketmaster hasn't succeeded in over 14h."
    if inc_total > 0:
        return f"{inc_total} incomplete record(s) to clean up."
    return "Minor items only — no blockers."


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    token = os.environ.get("HEALTH_CHECK_TOKEN")
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not token:
        print("ERROR: HEALTH_CHECK_TOKEN is not set", file=sys.stderr)
        return 1
    if not webhook:
        print("ERROR: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        return 1

    try:
        health_status, health_data, health_error = fetch_health(token)
        fe_status, fe_url, fe_error = check_frontend()
        text, is_critical = format_report(
            health_status, health_data, health_error,
            fe_status, fe_url, fe_error,
        )
        post_to_slack(webhook, text)
        print(f"Posted to Slack ({'CRITICAL' if is_critical else 'OK'})")
        return 0
    except Exception as e:
        # Try to surface the crash in Slack so it's not silent.
        try:
            post_to_slack(
                webhook,
                "🚨 *Concert Calendar Health Check* — script crashed: "
                f"`{type(e).__name__}: {e}`",
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    sys.exit(main())
