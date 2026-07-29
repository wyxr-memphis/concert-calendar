"""Cloudinary image hosting.

Single home for uploading and deleting images. Replaces four near-duplicate
GitHub Contents API blocks that had drifted apart on error handling, extension
validation, and filename sanitizing.

Uploads land in Cloudinary instead of the public repo, which means:
  - the URL resolves immediately (no commit + ~60s Vercel redeploy)
  - deletes actually delete (git history keeps the bytes forever)
  - the repo stops growing

Config: one env var, ``CLOUDINARY_URL`` in the form
``cloudinary://<api_key>:<api_secret>@wyxr``. The SDK reads it automatically.
``CLOUDINARY_FOLDER_PREFIX`` (default ``concert-calendar``) namespaces the
folders so local testing stays out of the production tree.

Legacy images already committed under ``docs/`` are untouched and keep serving
from Vercel — this only changes where *new* uploads go.
"""

import os
import re
from datetime import datetime

try:
    import cloudinary
    import cloudinary.exceptions
    import cloudinary.uploader
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - only when the dep is missing
    cloudinary = None
    _IMPORT_ERROR = exc

# Our own cap rather than Cloudinary's — surfaces a clean error instead of a
# raw provider 400, and doesn't depend on plan-specific limits.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_DEFAULT_PREFIX = "concert-calendar"


class ImageUploadError(Exception):
    """A caller-fixable problem (missing file, bad type, too large).

    Routes map this to HTTP 400. Infrastructure failures are *not* raised as
    this — they return None, so fail-soft callers (Slack) keep working.
    """


def is_configured() -> bool:
    """True when the SDK is importable and CLOUDINARY_URL is set."""
    return cloudinary is not None and bool(os.environ.get("CLOUDINARY_URL", "").strip())


def _ensure_config():
    """Resolve SDK config, re-reading env if it was set after import."""
    cfg = cloudinary.config()
    if not cfg.cloud_name:
        cloudinary.reset_config()
        cfg = cloudinary.config()
    return cfg


def _folder_prefix() -> str:
    return (os.environ.get("CLOUDINARY_FOLDER_PREFIX") or _DEFAULT_PREFIX).strip("/")


def _safe_public_id(orig_filename: str, fallback: str = "image") -> str:
    """Timestamped, sanitized basename — no extension.

    Same sanitizing the GitHub upload used, so names stay recognizable in the
    Cloudinary console. Cloudinary derives the format from the bytes, so the
    extension is only used for validation.
    """
    base = os.path.splitext(orig_filename or "")[0]
    clean = re.sub(r"[^a-zA-Z0-9-]", "_", base)
    clean = re.sub(r"_+", "_", clean).strip("_") or fallback
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{ts}_{clean}"


def validate(file_data: bytes, orig_filename: str) -> None:
    """Raise ImageUploadError if the upload should be rejected outright."""
    if not file_data:
        raise ImageUploadError("File is empty")

    if len(file_data) > MAX_UPLOAD_BYTES:
        mb = len(file_data) / (1024 * 1024)
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise ImageUploadError(
            f"Image is {mb:.1f} MB — the limit is {limit_mb} MB"
        )

    ext = os.path.splitext(orig_filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ImageUploadError(
            f"File type {ext or '(none)'} not allowed — use one of: {allowed}"
        )


def _is_bad_file_error(exc: Exception) -> bool:
    """True when Cloudinary rejected the *file* rather than failing on its end.

    Cloudinary signals this with a 400 (cloudinary.exceptions.BadRequest); the
    message check is a fallback in case the SDK surfaces it as a generic Error.
    """
    if cloudinary is not None:
        bad_request = getattr(cloudinary.exceptions, "BadRequest", None)
        if bad_request and isinstance(exc, bad_request):
            return True
    msg = str(exc).lower()
    return any(
        s in msg
        for s in ("invalid image file", "unsupported", "empty file", "invalid file")
    )


def upload_image(file_data: bytes, orig_filename: str, folder: str) -> str | None:
    """Upload bytes to Cloudinary and return the delivery URL.

    Args:
        file_data: raw image bytes
        orig_filename: original name, used for the public_id and validation
        folder: subfolder under the prefix, e.g. "event-images" or "sponsors"

    Returns the https://res.cloudinary.com/... secure URL, or None if the
    upload failed for infrastructure reasons (not configured, network, provider
    error). Raises ImageUploadError for bad input.
    """
    validate(file_data, orig_filename)

    if cloudinary is None:
        print(f"[images] cloudinary SDK unavailable: {_IMPORT_ERROR}", flush=True)
        return None

    if not os.environ.get("CLOUDINARY_URL", "").strip():
        print("[images] CLOUDINARY_URL not configured — skipping upload", flush=True)
        return None

    try:
        _ensure_config()
        fallback = folder.rstrip("s").replace("-", "_") or "image"
        public_id = f"{_folder_prefix()}/{folder}/{_safe_public_id(orig_filename, fallback)}"

        result = cloudinary.uploader.upload(
            file_data,
            public_id=public_id,
            resource_type="image",
            overwrite=True,
            invalidate=True,
        )
        url = result.get("secure_url")
        if not url:
            print(f"[images] upload returned no secure_url: {result}", flush=True)
            return None
        return url
    except ImageUploadError:
        raise
    except Exception as exc:
        # A file with a valid extension but junk contents (or an unsupported
        # format) is the caller's problem, not ours — surface it as such rather
        # than as an upload failure.
        if _is_bad_file_error(exc):
            raise ImageUploadError(
                "That file isn't a readable image — it may be corrupt or "
                "saved in an unsupported format"
            ) from exc
        print(f"[images] upload failed: {exc}", flush=True)
        return None


def is_cloudinary_url(url: str) -> bool:
    """True for a Cloudinary *upload* delivery URL (not a fetch-wrapped one)."""
    if not url:
        return False
    return bool(
        re.match(r"^https?://res\.cloudinary\.com/[^/]+/image/upload/", url, re.I)
    )


def public_id_from_url(url: str) -> str | None:
    """Extract the public_id from a Cloudinary upload URL.

    Strips the optional transformation segments and version prefix that may sit
    between /image/upload/ and the public_id, plus the format extension.
    """
    m = re.match(
        r"^https?://res\.cloudinary\.com/[^/]+/image/upload/(.+)$", url or "", re.I
    )
    if not m:
        return None

    parts = m.group(1).split("/")
    while parts:
        head = parts[0]
        is_version = re.fullmatch(r"v\d+", head)
        # Transformation segments are comma-joined `k_v` pairs (w_96,c_fill,...)
        # or a lone one. Our folder names never match that shape.
        is_transform = "," in head or re.fullmatch(r"[a-z]{1,3}_[a-zA-Z0-9.\-]+", head)
        if is_version or is_transform:
            parts.pop(0)
            continue
        break

    if not parts:
        return None

    public_id = "/".join(parts)
    return os.path.splitext(public_id)[0] or None


def delete_image(image_url: str) -> bool:
    """Delete an image from Cloudinary by its delivery URL.

    Returns True only if Cloudinary confirms the asset is gone. Non-Cloudinary
    URLs (legacy repo images, remote scraper images) return False without any
    API call — they aren't ours to delete.
    """
    if not is_cloudinary_url(image_url) or cloudinary is None:
        return False

    public_id = public_id_from_url(image_url)
    if not public_id:
        return False

    try:
        _ensure_config()
        result = cloudinary.uploader.destroy(public_id, invalidate=True)
        return result.get("result") in ("ok", "not found")
    except Exception as exc:
        print(f"[images] delete failed for {public_id}: {exc}", flush=True)
        return False
