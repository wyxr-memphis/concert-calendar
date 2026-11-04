# Decision log (append-only)

## 2026-11-04 — Baseline thread and history branch
- Decided by: Gabe (asked Claude in Slack to create this branch).
- Context: Gabe and Robby may use different Claude accounts (or none), so Slack-only memory is not enough.
- Decisions:
  - The Slack thread started 2026-11-04 in #wp-ai-bot-testing is the baseline for the calendar project.
  - The `history` branch holds shared rules, decisions and feature initiatives (see README.md).
  - Claude (Slack) was given push access to wyxr-memphis/concert-calendar on 2026-11-04 at Gabe's request, so it can read issues/PRs, push branches and open PRs.
  - Cursor setup: Gabe is using a Cursor prompt prepared by Claude to set the project up locally; Cursor is to ask Gabe for any env vars/exports by name and stop on blockers (rule 1 and 2).
- Open questions raised while reading the repo (no answers yet):
  - Local frontend pages (`docs/admin/local.html`, `docs/admin/local_index.html`, `docs/local_index_home.html`) are gitignored; tracked pages hardcode the production API.
  - Docs disagree on expected test count (18/22/24; CLAUDE.md says 24/24) and local backend port (5000 vs 5001).
  - README/dev/security.md mention an `api/` directory and `UPLOAD_PASSWORD` that do not exist in the repo.
  - `GITHUB_PAT` scope in docs is inconsistent (contents:write vs actions:write).
