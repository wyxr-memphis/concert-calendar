# Standing rules

Source: Gabe, Slack thread of 2026-11-04 (the starting point; this branch is the source of truth).

1. **Never assume; never work around a blocker.** When an assistant or developer hits a blocker (missing access, missing env var, unclear docs, failing check), stop and resolve it with Gabe or Robby instead of improvising around it.
2. **Ask for exports and secrets by name.** Local setup needs env vars and data exports that only Gabe/Robby hold. Ask for each by exact name; never guess or invent values. Never commit or post secrets (this repo and the Slack channel are not private places for credentials).
3. **This branch is the shared record.** Gabe and Robby may use different Claude accounts, or no Claude at all, so decisions, rules and feature initiatives agreed in Slack are written to the `history` branch (see README.md).
4. **Ask before touching the production database.** `./test_before_push.sh` applies migrations to whatever `DATABASE_URL` points at (per CLAUDE.md). Get an explicit yes before any database-touching command.
5. **Code rules live on `main`.** `CLAUDE.md` and `dev/*.md` remain the authority for code tripwires; this branch covers project agreements and history.
