# Decision log (append-only)

## 2026-11-04 — Baseline thread and history branch
- Decided by: Gabe (asked Claude in Slack to create this branch).
- Context: Gabe and Robby may use different Claude accounts (or none), so Slack-only memory is not enough.
- Decisions:
  - The Slack thread started 2026-11-04 in #wp-ai-bot-testing is the starting point; the `history` branch is the source of truth going forward.
  - The `history` branch holds shared rules, decisions and feature initiatives (see README.md).
  - Claude (Slack) was given push access to wyxr-memphis/concert-calendar on 2026-11-04 at Gabe's request, so it can read issues/PRs, push branches and open PRs.
  - Cursor setup: Gabe is using a Cursor prompt prepared by Claude to set the project up locally; Cursor is to ask Gabe for any env vars/exports by name and stop on blockers (rule 1 and 2).
- Open questions raised while reading the repo (no answers yet):
  - Local frontend pages (`docs/admin/local.html`, `docs/admin/local_index.html`, `docs/local_index_home.html`) are gitignored; tracked pages hardcode the production API.
  - Docs disagree on expected test count (18/22/24; CLAUDE.md says 24/24) and local backend port (5000 vs 5001).
  - README/dev/security.md mention an `api/` directory and `UPLOAD_PASSWORD` that do not exist in the repo.
  - `GITHUB_PAT` scope in docs is inconsistent (contents:write vs actions:write).

## 2026-11-04 — SVG animation framework and local-dev SVG tools library
- Requested by: Gabe Martin (via Claude in Slack).
- Request: an SVG animation framework for the static site, plus a local-dev-only list of SVG tools compiled into a weighted skillset that Gabe can re-weight and update over time.
- Work done, as two separate draft PRs against `main` (neither touches `docs/`, the deploy path, or CI):
  - Branch `svg-animation-framework`, PR #57: `tools/svg-animation/`. A zero-dependency ES-module framework (Web Animations API with a requestAnimationFrame fallback; sequence/parallel/stagger timelines; easing incl. spring; stroke drawing; path morph; scroll triggers; `data-anim` auto-wiring; `prefers-reduced-motion` respected by default), a registry of named presets with a JSON manifest for adding more, an example page and 33 plain-node tests (33/33 pass).
  - Branch `svg-tools-library`, PR #58: `tools/svg-tools/`. `tools.json` (32 researched tools, validated by `schema.json`), a stdlib-only CLI, a generated `RECOMMENDATIONS.md` and a generated Claude skill (`skill/SKILL.md`, not installed anywhere). Ranking = editorial `base_weight` (0-10) plus a log-scaled, capped usage bonus with a 90-day recency half-life. 40 unit tests pass.
- How to update the tools library (run from the repo root on the `svg-tools-library` branch or after it merges):
  - `python3 tools/svg-tools/scripts/svgtools.py list --top 10`
  - `... use <id> [--times N]` to log a use, `... weight <id> <0-10>` to change a prior, `... add --json file.json` to add a tool
  - `... validate --max-age-days 180` warns about stale verifications; `... render` regenerates RECOMMENDATIONS.md and the skill (`render --check` verifies they are current)
  - To enable the skill, copy or symlink `tools/svg-tools/skill` to `.claude/skills/svg-tools` (README explains; not done automatically).
- To add an animation preset: add an entry to the registry in `tools/svg-animation/src/presets.js`, or drop a JSON file in `tools/svg-animation/presets/` and list it in `presets/index.json`; then `node --test tools/svg-animation/tests`.
- Status: both PRs are drafts awaiting Gabe's review and merge.
- Open questions:
  - Which "Artcraft" did Gabe mean? The library entry is ArtCraft (storytold/artcraft), matched by name only; it is an AI image/video app with no SVG or vector support.
  - Prices and some facts for Figma, LottieFiles, Boxy SVG, SVGator and the Rive editor come from secondary sources; re-check on the vendors' sites before relying on them.
  - The starting `base_weight` values are an editorial first pass; Gabe may want to adjust them.
  - Whether to adopt the animation framework into `docs/` is a separate decision (it is not wired in).
