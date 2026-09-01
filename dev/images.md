# Image Hosting (Cloudinary)

> Tripwires live in `CLAUDE.md`. This file is the detail behind them.

All **uploaded** images — admin event images, sponsor images, calendar sponsor images, and
Slack-pipeline images — are hosted on Cloudinary. `backend/images.py` is the only place that
writes them.

```python
upload_image(file_data, orig_filename, folder) -> str | None   # folder: "event-images" | "sponsors"
delete_image(image_url) -> bool
is_cloudinary_url(url) -> bool
```

- **Config:** `CLOUDINARY_URL` (`cloudinary://<key>:<secret>@wyxr`) — the SDK reads it
  automatically. Optional `CLOUDINARY_FOLDER_PREFIX` (default `concert-calendar`; set to
  `concert-calendar-dev` locally so test uploads stay out of the production folder).
- **Limits:** 10 MB max, extensions `.jpg .jpeg .png .webp .gif`. Enforced in `validate()` —
  see `dev/security.md` for the three-way check.
- **Error contract:** `ImageUploadError` → HTTP 400 (bad/oversized/corrupt file); `None` return
  → HTTP 502 (network or provider failure). The Slack path catches `ImageUploadError` and
  continues without an image — a bad image must never block event insertion.
- **Deletes actually delete.** The CDN edge may serve a cached copy for a few minutes after
  `delete_image()`; the Admin API is authoritative, not a browser request to the URL.
- **Upload timing:** uploads resolve immediately — no commit, no Vercel redeploy, no wait.
  (Before July 2026 sponsor images were committed to `docs/sponsors/` and took ~1 min.)

## Legacy images stay on the repo

Files already under `docs/event-images/` and `docs/sponsors/` are still served by Vercel and
were deliberately not migrated. Both URL shapes coexist, so **never assume `image_url` is a
Cloudinary URL** — use `is_cloudinary_url()` to branch.

`cldImg()` in `docs/index.html` must handle three URL shapes. Getting this wrong is the main
regression risk in this area:

| Source | Handling |
|---|---|
| `res.cloudinary.com/…/image/upload/…` (new uploads) | splice the transformation into the delivery path — **never** fetch-wrap. A nested URL still returns 200, so this fails silently; the cost is that each one bills as a separate derived asset |
| `concert-calendar.wyxr.org/…` (legacy) and remote scraper images | `/image/fetch/` wrapped, as before |
| relative paths | passed through untouched |

`artifacts/` is **not** on Cloudinary — it's a build input read off disk during GitHub Actions,
so `admin_import_upload()` still commits it to the repo via the Contents API. Render storage is
ephemeral, which is why. Auto-cleaned after 24h by the daily build.

## Public submit-form images

`/submit` accepts an optional flyer. **Anonymous uploads never reach Cloudinary** — that is the
design constraint, not an implementation detail. Bytes are held in `submissions.image_data`
(BYTEA) and only uploaded when an admin approves, so the free-tier quota is spent solely on
images someone chose to publish.

- **Browser downscales first** — canvas to 1600px max edge, JPEG q0.82. A 12 MB phone photo
  becomes a few hundred KB, so submitters never hit a size wall, and EXIF/GPS is dropped.
- **Server re-encodes anyway** — `sanitize_submitted_image()` decodes with Pillow and writes
  fresh JPEG bytes. Never store what was submitted: a file can carry a valid image header and
  be something else. Cap is 3 MB (`MAX_SUBMISSION_IMAGE_BYTES`), tighter than the 10 MB admin
  cap because this path is unauthenticated.
- **Rate limit:** 5 submissions/hour per hashed IP (`SUBMISSIONS_PER_HOUR`). Keyed on the
  leftmost `X-Forwarded-For` entry — `request.remote_addr` is Render's proxy, so using it would
  put every submitter in one bucket. IP is stored as a salted SHA-256 (`SUBMISSION_IP_SALT`),
  never in the clear.
- **Rights checkbox** is required when a file is attached, recorded in `image_rights_confirmed`.
- **Bytes are freed** on approve (after upload), on reject, and by a 90-day sweep
  (`purge_stale_submission_images()`) at the start of the daily build.

⚠️ `image_data` must never reach `jsonify` — psycopg2 returns it as a `memoryview` and
`serialize_event()` doesn't convert it, which would break the whole admin Submissions tab. All
submission queries select `_SUBMISSION_COLUMNS` (which exposes a derived `has_image` boolean
instead); the bytes come back only from `get_submission_image()`.

## Debugging display issues

Always check, in this order:
1. URL encoding (spaces, special characters)
2. CDN/Vercel caching of 404s
3. Aspect-ratio constraints

Never assume a fix worked without verifying the live URL.
