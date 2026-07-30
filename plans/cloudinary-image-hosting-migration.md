# Migrate image hosting from git to Cloudinary

> **Status: complete.** Phase 1 shipped 2026-07-29 (`5843b74`) — `backend/images.py`, the
> four call sites, the `cldImg()` fix, size/type validation. Phase 2, the public submit-form
> image field, shipped 2026-07-30 (`0e47fbd`). Kept as the record of *why* image hosting is
> shaped this way; current mechanics live in `CLAUDE.md`.
>
> Two deviations from the plan as written:
>
> 1. A file with a valid extension but unreadable contents returns **400**
>    (`ImageUploadError`), not the 502 the plan implied — it's the caller's problem, not an
>    infrastructure failure.
> 2. Phase 2 does **not** upload submitted images to `{prefix}/submissions/` on submit and
>    delete them on reject, as sketched here. Anonymous writes to a 25-credit quota were too
>    exposed. Instead the bytes are held in `submissions.image_data` (BYTEA) and uploaded
>    only on admin approval, so rejection costs nothing and `delete_image()` is not on that
>    path at all.

## Context

Every image write in this project currently base64-encodes the bytes and `PUT`s them into
the **public GitHub repo** via the Contents API, under `docs/`. Vercel then serves those
paths, and `docs/index.html` proxies the resulting URLs through **Cloudinary's fetch
transform** to resize them. So the project already runs a real image CDN, but uses git as
the origin store — and pays for that twice over.

What git-as-store costs today:

- **~1 minute deploy lag** before any uploaded image resolves. Already worked around with
  blob-URL previews in the admin UI and documented at `CLAUDE.md:183`.
- **Permanent history.** Deleting a file doesn't remove the bytes. This is what made the
  public-submission image feature awkward enough to need a hold-in-Postgres design.
- **Monotonic growth, no cleanup.** `docs/event-images/` is 8.6 MB / 14 files,
  `docs/sponsors/` is 2.8 MB / 7 files, `.git` is 78 MB. Nothing ever prunes any of it.
  There is already measurable waste: **5 byte-identical copies** of the same 553 KB sponsor
  JPEG, plus 2 duplicate pairs in event-images.
- **A commit + Vercel redeploy per image.**
- **Four near-duplicate implementations that have drifted**: `admin_import_image`
  (`backend/app.py:894`), `admin_sponsors_upload_image` (`:1036`),
  `admin_calendar_sponsor_upload_image` (`:1165`), and the shared
  `_commit_image_bytes_to_github` (`:1458`) that only the Slack path actually calls. They
  disagree on error handling (502 vs fail-soft `None`), on unknown extensions (reject vs
  coerce to `.jpg`), and on filename sanitizing.
- **No size limit, no content validation, and no delete path anywhere.**

Moving uploads to Cloudinary removes all of it: no deploy lag, deletion actually deletes,
no repo growth, one helper instead of four, and a real `destroy()` API.

**Decisions made:** free tier, calendar-only cloud; **new uploads only** (existing repo
images stay put); submit-form image field deferred to a separate phase.

---

## Cost

**Verdict: $0/month, and it stays $0 at any traffic level this site is plausibly going to see.**

Cloudinary's free plan is **25 credits/month**, where 1 credit = 1,000 transformations
**or** 1 GB storage **or** 1 GB delivery bandwidth, flexibly pooled.

The counting rule that matters: transformations are billed **once when a derived asset is
first generated**, not per request. Repeat hits on the same transformation URL are free and
CDN-cached. Fetched remote images cost one transformation per unique transformation URL,
and Cloudinary re-validates the remote source by etag once every 7 days.

| Quota | Estimated monthly use | Credits |
|---|---|---|
| Transformations | ~200–1,500 new derived assets (3 widths × new images, plus fetch revalidation) | 0.2 – 1.5 |
| Storage | ~0.05 GB now, growing ~8 MB/mo (originals + cached derivatives) | <1 |
| Bandwidth | ~1–3 GB (the only real variable) | 1 – 3 |
| **Total** | | **~2–4 of 25** |

Bandwidth is the binding constraint. A calendar page delivers roughly 150–200 KB of image
bytes (15–25 thumbs at 96px source, `q_auto,f_auto`, plus the occasional 600px modal hero),
so **1 GB ≈ 5,000 pageviews**. Reserving a few credits for transformations and storage
leaves headroom for roughly **100,000 pageviews/month** before the free tier is threatened.

Two honest caveats:

1. That bandwidth figure is an estimate — I don't have your actual traffic. **Verify before
   cutover** against GA4 (`G-9866JXK4ND`) monthly pageviews and the Cloudinary console's
   usage dashboard, which shows current credit burn from the fetch delivery you already run.
2. **The free → paid cliff is steep**: the next tier is Plus at **$99/mo** (225 credits).
   There's no $10 step in between. So it's worth setting a usage alert in the Cloudinary
   console rather than discovering it at renewal.

This migration does **not** reduce spend — git hosting was also $0. The return is
operational: no deploy lag, real deletes, a bounded repo, one code path instead of four.

### Alternatives considered

| Option | Cost at this scale | Why not |
|---|---|---|
| **Cloudinary free** ✅ | $0 | Already the delivery layer. No new vendor, no new domain. |
| Cloudflare Images | ~$5/mo | Predictable with no cliff, but adds a vendor and replaces the transform layer already wired into `cldImg()`. |
| Cloudflare R2 + Cloudinary fetch | ~$0 (zero egress) | Cheapest ceiling, but two vendors and R2 needs its own public-bucket + custom-domain setup. |
| Vercel Blob | Free allowance, then usage-based | Couples image storage to the Vercel plan; no transform layer. |
| Status quo (git) | $0 | The operational costs listed above. |

Worth revisiting Cloudflare R2 only if bandwidth ever approaches the 25-credit line — the
helper introduced below keeps that a one-file swap.

---

## What changes

```
BEFORE                                    AFTER
admin upload  ┐                           admin upload  ┐
sponsor       ├→ 4 copies of GitHub  →    sponsor       ├→ backend/images.py
cal-sponsor   │   Contents API PUT        cal-sponsor   │   upload_image()
Slack         ┘   → docs/… → Vercel       Slack         ┘   → Cloudinary
                  (commit + ~60s lag)                       (instant, deletable)
```

`events.image_url` and the sponsor tables keep storing a plain URL string — just a
`res.cloudinary.com/…/image/upload/…` one instead of a `concert-calendar.wyxr.org/…` one.
No schema change. RSS enclosures (`src/generate_rss.py:123`) and the public API
(`docs/api.html:354`) are unaffected.

---

## 1. New module — `backend/images.py`

Single home for image hosting, replacing four inline copies.

```python
def upload_image(file_data: bytes, orig_filename: str, folder: str) -> str | None
def delete_image(image_url: str) -> bool
def is_cloudinary_url(url: str) -> bool
```

- **Dependency:** add `cloudinary>=1.40` to `backend/requirements.txt`. The SDK handles
  request signing; hand-rolling the SHA1 signature is possible but not worth owning.
- **Config:** one env var, `CLOUDINARY_URL` in the form
  `cloudinary://<api_key>:<api_secret>@wyxr` — the SDK picks it up automatically. Add to
  `.env.example` and to Render. A second optional `CLOUDINARY_FOLDER_PREFIX` (default
  `concert-calendar`, set to `concert-calendar-dev` locally) keeps local testing out of the
  production folder.
- **Folders:** `{prefix}/event-images/`, `{prefix}/sponsors/`, and later
  `{prefix}/submissions/` for phase 2.
- **`public_id`:** reuse the existing sanitizer — timestamp prefix, `[^a-zA-Z0-9-]` → `_`,
  collapse runs, strip, fallback basename. Keeps filenames recognizable in the console.
- **Validation the current code lacks:** reject if `len(file_data)` exceeds a
  `MAX_UPLOAD_BYTES = 10 * 1024 * 1024` cap, and reject extensions outside
  `{.jpg,.jpeg,.png,.webp,.gif}`. (I could not confirm Cloudinary's exact free-tier
  per-file limit — the support article 403s — so enforce our own rather than relying on
  theirs, and surface a clean error instead of a raw Cloudinary 400.)
- **Fail-soft**, matching `_commit_image_bytes_to_github`: return `None` on any failure so
  the Slack path keeps treating a missing image as non-fatal.
- **`delete_image()`** parses the `public_id` back out of a Cloudinary URL and calls
  `cloudinary.uploader.destroy()`. Not wired into much in phase 1 — it's the capability git
  never had, and phase 2's reject flow depends on it.

---

## 2. Backend call sites — `backend/app.py`

Replace the inline GitHub blocks with `upload_image(...)`; each shrinks to a few lines.

| Route / function | Line | Folder |
|---|---|---|
| `admin_import_image()` | 894 | `event-images` |
| `admin_sponsors_upload_image()` | 1036 | `sponsors` |
| `admin_calendar_sponsor_upload_image()` | 1165 | `sponsors` |
| `_process_slack_image()` call site | 1596 | `event-images` |

Standardize behavior while consolidating: 400 on bad extension or oversize, 502 on upload
failure, and the same `{"ok": true, "filename": ..., "image_url": ...}` response shape all
three admin routes already return — so **no admin frontend JS changes are required** for
upload. `docs/admin/edit.html:374` and `docs/admin/index.html:2342`/`:2548` keep working
as-is.

Then **delete `_commit_image_bytes_to_github()` (`:1458`)** — the Slack path was its only
caller, so it becomes dead code.

Also drop the now-pointless `GITHUB_PAT`-missing 500 branches from these three routes.
`GITHUB_PAT` is still needed elsewhere (artifact upload, build triggering), so the env var
stays.

---

## 3. Frontend — `docs/index.html`

**This is the one subtle change and the easiest thing to get wrong.**

`cldImg()` (`:1031-1041`) wraps any absolute URL in `/image/fetch/`. Once uploads return
`res.cloudinary.com` URLs, that would wrap Cloudinary in Cloudinary — a nested fetch that
double-counts transformations and produces a URL that may not resolve at all.

Teach it three cases:

```js
function cldImg(src, width) {
    if (!src) return '';
    const t = `w_${width},c_fill,g_auto,q_auto,f_auto`;
    // Relative/local paths can't be fetched by Cloudinary — pass through.
    if (!/^https?:\/\//i.test(src)) return src;
    // Already ours: splice the transformation into the delivery path rather
    // than fetch-wrapping it (which would double-count transformations).
    const m = src.match(/^https:\/\/res\.cloudinary\.com\/([^/]+)\/image\/upload\/(.+)$/i);
    if (m) return `https://res.cloudinary.com/${m[1]}/image/upload/${t}/${m[2]}`;
    // Remote source (scrapers, legacy repo URLs) — fetch delivery as today.
    return `https://res.cloudinary.com/${CLOUDINARY_CLOUD}/image/fetch/${t}/${encodeURIComponent(src)}`;
}
```

The existing two-step `onerror` fallback at all three call sites (`:1407` modal, `:1915`
presents thumb, `:1988` row thumb) needs no change — it already degrades to the raw URL and
then hides.

---

## 4. Docs and config

- `.env.example` — add `CLOUDINARY_URL` and optional `CLOUDINARY_FOLDER_PREFIX`.
- `CLAUDE.md` — replace the git-upload description and the `:183` deploy-lag caveat (no
  longer true for new uploads) with the Cloudinary model; note that legacy `docs/` images
  are still served from the repo.
- Project memory — same update.
- `backend/requirements.txt` — `cloudinary>=1.40`.

---

## Explicitly out of scope

- **`artifacts/` stays on GitHub.** It's a *build input*, not a delivery asset —
  `src/sources/artifacts.py:49` globs it off disk during the GitHub Actions checkout, and
  the daily workflow already auto-cleans it after 24h. Moving it to Cloudinary would mean
  downloading files back down during the build for no benefit. `admin_import_upload()`
  (`backend/app.py:726`) keeps its inline GitHub code.
- **Existing repo images**, per your call. The 26 event rows and the sponsor rows keep
  serving from `docs/`, and the `vercel.json` cache rules for `/event-images/` and
  `/sponsors/` stay. Consequence to accept: two storage paths coexist indefinitely, ~11 MB
  stays in the working tree, and the 5 duplicate Pat Metheny copies stay with it. If you
  change your mind later it's a ~30-line backfill script — upload the ~15 distinct files,
  `UPDATE` three tables, verify 200s, then `git rm`.
- **No git history rewrite.** Purging old blobs with `filter-repo`/BFG would shrink `.git`
  but rewrites shared history that GitHub Actions and any clone depend on. Not worth it for
  11 MB.
- **Public submit-form image field** — phase 2, on top of this.

---

## Verification

**Setup:** create a dev folder prefix and set `CLOUDINARY_URL` locally, then:

```bash
./run_local_backend.sh      # terminal 1
./run_local_frontend.sh     # terminal 2
```

1. Backend boots with the new dependency; confirm the Cloudinary config resolves (a startup
   log line, or `python -c "import cloudinary; print(cloudinary.config().cloud_name)"`).
2. **Admin event image** — `/admin/edit.html`, upload a JPG. Response `image_url` is a
   `res.cloudinary.com/.../image/upload/...` URL, it resolves **immediately** (no 60s wait
   — this is the headline win), and the preview renders.
3. **Oversize** — upload a >10MB file → clean 400 with a readable message, nothing created
   in Cloudinary.
4. **Bad type** — rename a `.txt` to `.jpg` and upload → 400 on the extension check;
   confirm a genuinely mislabeled file also fails gracefully rather than 500ing.
5. **Sponsor + calendar sponsor** uploads via the Sponsors tab — both land in the
   `sponsors/` folder and the banner renders.
6. **Slack path** — post a flyer for one show to #wyxr-concert-calendar with "add to
   calendar". Confirm `[slack] hosted image at https://res.cloudinary.com/...` in the logs
   and that the event carries it. Then post a venue's month schedule and confirm **no**
   image is attached.

   > **Superseded 2026-07-29.** This step originally described a `len(events) == 1` rule.
   > That was wrong: it skipped the image for a four-act bill on a single night. The rule
   > is now "all extracted events share the same canonical venue and date" — see
   > `_process_slack_image` in `backend/app.py`. Whatever guards this, it is easy to lose
   > while editing that block, so re-test it after any change there.
7. **`cldImg()` — the regression risk.** On the calendar, verify all three URL shapes
   render correctly and check the generated URLs in DevTools:
   - a **new Cloudinary upload** → `/image/upload/w_96,.../` , **not** a nested
     `/image/fetch/https%3A%2F%2Fres.cloudinary.com/...`
   - a **legacy repo image** (one of the 26) → still `/image/fetch/` wrapped, still renders
   - a **remote scraper image** (a `s1.ticketm.net` event) → unchanged
   Check row thumbs, the "WYXR Presents" thumbs, and the 600px modal hero.
8. Confirm no GitHub commits were created by any of the above —
   `git log --oneline -3` in the repo and the GitHub commit history should be untouched.
9. Confirm the RSS feed still emits a valid `<enclosure>` for an event with a Cloudinary
   image.
10. `./test_before_push.sh`, then push. Set `CLOUDINARY_URL` in the Render dashboard
    **before** the deploy finishes, or the first upload after cutover fails.
11. **Post-deploy on production:** repeat steps 2 and 7 live, then check the Cloudinary
    console usage dashboard to confirm real credit burn matches the estimate above, and set
    a usage alert.

## Rollback

Low-risk: no schema change, no data migration, and legacy URLs are untouched. If Cloudinary
uploads fail in production, revert the commit — `_commit_image_bytes_to_github` comes back
and the GitHub path resumes. Images uploaded to Cloudinary in the interim keep resolving
(the URLs are already stored in the DB and the reverted `cldImg()` would fetch-wrap them —
degraded and double-counted, but not broken).
