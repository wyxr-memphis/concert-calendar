# history branch

Shared memory for the Memphis Concert Calendar project. It records the rules, decisions and feature initiatives that Gabe, Robby and any assistant (Claude in Slack, Cursor, etc.) agree on, so everyone stays in sync no matter which tool or account they use.

**This repo is public. Never put secrets, tokens, passwords, personal data or private Slack content here.** Record decisions and rules, not conversations.

## Files
- `RULES.md` — standing rules for how we work on this project. Current state only; edit in place when a rule changes.
- `LOG.md` — append-only dated log of decisions, initiatives and open questions. Newest entry at the bottom. Never rewrite old entries; add a new one that supersedes.
- `INITIATIVES.md` — feature initiatives, each with status (proposed / active / done / dropped), owner and next step.

## How to use it
- Before starting work, read these three files (they are the baseline; `CLAUDE.md` and `dev/` on `main` still govern code).
- After any decision, rule change or new initiative (in Slack or anywhere else), add an entry to `LOG.md` and update `RULES.md` / `INITIATIVES.md` if affected. Commit to the `history` branch and push.
- Each LOG entry: `## YYYY-MM-DD — short title`, who decided, what, and why.
- Slack thread of record for the project baseline: #wp-ai-bot-testing, thread started 2026-11-04 by Gabe.
- The `history` branch is meant to live long-term and is not merged into `main`.
