# svg-tools

A weighted, easy-to-update library of tools for working with SVG graphics (editing, animating,
optimizing, converting, rendering), for **local development only**.

> **Do not ship these tools, add them to the deployed site (`docs/`), or wire them into CI or
> GitHub Actions.** Nothing in `tools/svg-tools/` is imported by the app, deployed by Vercel, or
> run by the build. Every entry in `tools.json` is `local_dev_only: true`, and the schema refuses
> anything else.

Related: the zero-dependency SVG animation framework lives on the separate branch
**`svg-animation-framework`** (draft PR #57, `tools/svg-animation/`). This branch is the tool
*recommendations*; that one is code.

```
tools/svg-tools/
  tools.json            the data: one entry per tool (the only file you edit, via the CLI)
  schema.json           JSON Schema for tools.json
  scripts/svgtools.py   the CLI (Python 3, standard library only)
  RECOMMENDATIONS.md    GENERATED ranked list, grouped by category, with caveats and open questions
  skill/SKILL.md        GENERATED Claude skill: ranked tools + how to log usage
  tests/                python3 -m unittest
```

`RECOMMENDATIONS.md` and `skill/SKILL.md` are generated. Change `tools.json` through the CLI and
re-render; do not edit them by hand (a test fails if they are stale).

All commands run from the repo root:

```bash
S=tools/svg-tools/scripts/svgtools.py
python3 $S list --top 10
```

## Reading the ranking

```
score       = base_weight + usage_bonus
usage_bonus = min(USAGE_CAP, USAGE_SCALE * log2(1 + use_count)) * 0.5 ** (days_since_last_used / HALF_LIFE_DAYS)
```

- **`base_weight` (0-10)** is the editorial prior: how useful the tool is for SVG animation, editing
  and optimizing work, set by a human. Stale, deprecated, unverified or not-SVG tools are weighted
  low on purpose (the skill tells assistants not to start new work on anything under 2).
- **Usage bonus.** Each logged use raises the score, log-scaled so the 1st use matters more than the
  20th: 1 use = +1.0, 3 = +2.0, 7 = +3.0, 31 = +5.0 (the cap). The cap keeps real-world use from
  drowning out the prior.
- **Recency decay.** The bonus halves for every 90 days since `last_used`, so tools that were popular
  once but have gone quiet drift back to their prior, and the most-used-lately rise.
- Constants (`USAGE_SCALE`, `USAGE_CAP`, `HALF_LIFE_DAYS`, `STALE_DAYS_DEFAULT`, `LOW_WEIGHT`) are at
  the top of `scripts/svgtools.py`.
- Ties break by base weight, then name.
- `list` ranks as of **today**. `render` ranks as of the **newest `last_used`** in the data (or by
  base weight alone if nothing is logged yet), so re-rendering on a different day never changes the
  output and the generated files only change when `tools.json` does.

## Updating the library over time

| To... | Run |
|---|---|
| See the ranking | `python3 $S list [--category animator] [--top 10]` |
| Log that you used a tool | `python3 $S use svgo` (add `--times 3` for several uses) |
| Change a tool's prior | `python3 $S weight inkscape 9.5` |
| Add a tool | `python3 $S add --json new-tool.json` (an object or a list), or `add --name ... --category ... --summary ... --homepage ... --license ... --open-source --price-tier free --install ... --svg-notes ... --caveats ... --evidence-url ...` |
| Check the data | `python3 $S validate --max-age-days 180` |
| Regenerate the docs and skill | `python3 $S render` (`render --check` fails if they are out of date, without writing) |

After any change: `validate`, `render`, then commit `tools.json`, `RECOMMENDATIONS.md` and `skill/SKILL.md` together.
Run the tests with `python3 -m unittest discover -s tools/svg-tools/tests` (or `python3 -m unittest` inside `tests/`).

**Adding a tool.** `add` fills safe defaults: `verified: false`, `verified_on` = today,
`base_weight: 5`, `use_count: 0`, `last_used: null`, tags from category / price / licence, and
`local_dev_only: true` (always forced). Everything else (summary, homepage, licence, install,
`svg_notes`, `caveats`, `evidence_url`) must be supplied and is checked against `schema.json`.
Only set `verified: true` after reading the project's own repo, licence or registry, and say which
in `verification_level` (primary vs secondary). A new category needs one edit: add it to the
`category` enum in `schema.json`.

**Optional fields.** `open_question` (set it by hand-editing or via `--json`) is a short note about
something a human still has to confirm; every entry that has one is listed at the top of
`RECOMMENDATIONS.md` and in the skill.

**Keeping facts fresh.** Every entry has `verified_on`. `validate --max-age-days 180` (the default)
warns about stale verifications, and always warns about entries with `verified: false`. When you
re-check a tool, update the facts and `verified_on` together. Prices especially: entries whose
`verification_level` is secondary were read from search snippets and third-party sites, because
the vendors' own pages could not be reached when they were researched.

## Open questions (as of the first version)

- **ArtCraft.** The entry is `artcraft` (github.com/storytold/artcraft). It was matched on the name
  "Artcraft" alone, and it is an AI image/video app with **no SVG or vector support**. Gabe needs to
  confirm it is the tool he meant; weight it down or remove it if not.
- **Secondary-source facts.** Figma, LottieFiles, Boxy SVG, SVGator and the Rive editor were researched
  from search snippets and third-party sites. Re-check their prices before relying on them.
- **svgcleaner** is kept as a low-weight warning: its maintenance status could not be verified.

## Installing the skill (optional)

`skill/SKILL.md` is a Claude skill (`name: svg-tools`) that tells an assistant the ranked tools,
to prefer the top-weighted ones, and how to log usage with `svgtools.py use <id>`. It is not
installed automatically and this branch does not touch `.claude/skills/`. To enable it, copy or
symlink the `skill/` folder under the name `svg-tools`:

```bash
mkdir -p .claude/skills
ln -s ../../tools/svg-tools/skill .claude/skills/svg-tools      # follows re-renders
# or: cp -r tools/svg-tools/skill .claude/skills/svg-tools      # re-copy after each render
```

For a personal install, use `~/.claude/skills/svg-tools` instead.
