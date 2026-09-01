# Instagram Ingestion — ⛔ Do Not Attempt (settled 2026-08-27)

**Reading venue Instagram posts through the Graph API is a dead end. Don't re-open it without
new information from Meta.** `REVIEW.md` §6 designed this and never mentioned the access tier,
which is exactly why it got picked up and cost an evening.

## What's blocked, and how we know

- **Posts:** `business_discovery` returns `(#10) Application does not have permission for this
  action` — **including against WYXR's own `@wyxr_memphis`**. That control is what makes it a
  diagnosis: a wrong handle and a personal-account target are both ruled out, so it is the
  app's *access tier* being refused, not the target. It needs **Advanced Access** to
  `instagram_basic`, granted only by Meta App Review — which expects business verification, a
  data-deletion endpoint, and a screencast of a per-user OAuth consent flow this tool does not
  have and would have to build purely to pass review.
- **The "add the venue as an Instagram Tester" workaround does not work,** and the same
  evidence proves it. Standard Access covers accounts holding a role on the app;
  `@wyxr_memphis` holds the *owner* role and still failed. Don't spend a venue relationship
  finding this out.
- **Stories have never been automatable** — no Meta API exposes another account's stories, and
  the alternatives require a logged-in bot session that breaches Instagram's ToS and risks the
  station's account.

## Why it was dropped rather than pursued

The Slack image pipeline (`dev/slack-pipeline.md`) *already* puts these venues on the calendar.
Instagram ingestion would have removed a DJ's screenshot step, not added a capability — a poor
trade for weeks of Meta verification.

## If Meta's policy ever changes

The Meta app itself is fine (`WYXR Concert Calendar`, Business account linked to the WYXR Page,
`instagram_basic` granted) — the block is purely the access tier. Re-test the whole chain in
one command:

```bash
python scripts/check_instagram_access.py --username <handle>
```

It runs the control call itself and names which layer is at fault.
`scripts/instagram_setup_helper.py --write-env` regenerates the credentials.

⚠️ **Use `--write-env`, never `--show-token`** — the latter put a live 60-day token on screen,
which is how one got leaked into a screenshot.
