#!/usr/bin/env python3
"""svgtools: manage the weighted library of local-dev SVG tools (tools.json).

Python 3 standard library only. Run from anywhere:

    python3 tools/svg-tools/scripts/svgtools.py list --top 10
    python3 tools/svg-tools/scripts/svgtools.py use svgo
    python3 tools/svg-tools/scripts/svgtools.py weight inkscape 9.5
    python3 tools/svg-tools/scripts/svgtools.py add --json new-tool.json
    python3 tools/svg-tools/scripts/svgtools.py validate --max-age-days 180
    python3 tools/svg-tools/scripts/svgtools.py render

Everything here is for LOCAL DEVELOPMENT ONLY: nothing in tools/svg-tools is deployed,
imported by the app, or run in CI.

Scoring (see README.md):

    score = base_weight + usage_bonus
    usage_bonus = min(USAGE_CAP, USAGE_SCALE * log2(1 + use_count)) * 0.5 ** (days_since_last_used / HALF_LIFE_DAYS)

The editorial prior (base_weight, 0-10) is the floor; real use adds a log-scaled bonus that is
capped so it can never swamp the prior, and that halves every HALF_LIFE_DAYS without a new use.
"""
import argparse
import datetime
import json
import math
import re
import sys
from pathlib import Path

# ---- scoring configuration (edit here) -------------------------------------------------
USAGE_SCALE = 1.0        # bonus points per doubling of use_count: 1 use = 1.0, 3 = 2.0, 7 = 3.0, 31 = 5.0
USAGE_CAP = 5.0          # the usage bonus never exceeds this, however often a tool is used
HALF_LIFE_DAYS = 90.0    # the bonus halves for every 90 days since last_used
STALE_DAYS_DEFAULT = 180  # `validate` warns when verified_on is older than this
LOW_WEIGHT = 2.0         # tools below this are kept as warnings, and the skill says not to start new work on them
# ----------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "tools.json"
SCHEMA_FILE = ROOT / "schema.json"

KEY_ORDER = [
    "id", "name", "category", "summary", "homepage", "repo", "license", "open_source",
    "price_tier", "install", "svg_notes", "caveats", "verified", "verified_on",
    "verification_level", "evidence_url", "local_dev_only", "tags", "base_weight",
    "use_count", "last_used", "notes", "open_question",
]
SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---- dates ------------------------------------------------------------------------------

def parse_date(value):
    return datetime.date.fromisoformat(value)


def today_default():
    return datetime.date.today()


# ---- scoring ----------------------------------------------------------------------------

def usage_bonus(use_count, last_used, as_of):
    """Log-scaled, capped usage bonus with exponential recency decay. 0 if never used."""
    if not use_count or not last_used or as_of is None:
        return 0.0
    days = max((as_of - parse_date(last_used)).days, 0)  # a use "after" as_of counts as today
    raw = min(USAGE_CAP, USAGE_SCALE * math.log2(1 + use_count))
    return raw * 0.5 ** (days / HALF_LIFE_DAYS)


def score(tool, as_of):
    return tool["base_weight"] + usage_bonus(tool["use_count"], tool["last_used"], as_of)


def ranked(tools, as_of):
    """Highest score first; ties by base_weight desc then name, so order is deterministic."""
    return sorted(tools, key=lambda t: (-round(score(t, as_of), 6), -t["base_weight"], t["name"].lower(), t["id"]))


def render_as_of(data):
    """render is deterministic: it decays relative to the newest logged use, not to 'today'."""
    dates = [t["last_used"] for t in data["tools"] if t["last_used"]]
    return parse_date(max(dates)) if dates else None


# ---- schema validation (small JSON Schema subset, driven by schema.json) -----------------

def _type_ok(value, name):
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    return False


def validate_schema(value, schema, root, path="$"):
    """Return a list of error strings (empty = valid)."""
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return validate_schema(value, node, root, path)
    if "anyOf" in schema:
        if any(not validate_schema(value, s, root, path) for s in schema["anyOf"]):
            return []
        return [f"{path}: does not match any allowed form"]
    errs = []
    if "const" in schema and value != schema["const"]:
        return [f"{path}: must be {json.dumps(schema['const'])}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: must be one of {', '.join(map(str, schema['enum']))}"]
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            return [f"{path}: expected {'/'.join(types)}, got {type(value).__name__}"]
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: must be <= {schema['maximum']}")
    if isinstance(value, list):
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errs.append(f"{path}: items must be unique")
        if "items" in schema:
            for i, item in enumerate(value):
                errs += validate_schema(item, schema["items"], root, f"{path}[{i}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{path}: missing required field '{key}'")
        props = schema.get("properties", {})
        for key, sub in value.items():
            if key in props:
                errs += validate_schema(sub, props[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unknown field '{key}'")
    return errs


def load_schema(path=SCHEMA_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_data(data, schema, today, max_age_days=STALE_DAYS_DEFAULT):
    """Return (errors, warnings) for a whole tools.json document."""
    errors = validate_schema(data, schema, schema)
    warnings = []
    if errors:
        return errors, warnings
    seen = set()
    for t in data["tools"]:
        label = t["id"]
        if t["id"] in seen:
            errors.append(f"duplicate id '{t['id']}'")
        seen.add(t["id"])
        for field in ("verified_on", "last_used"):
            if t[field] is None:
                continue
            try:
                d = parse_date(t[field])
            except ValueError:
                errors.append(f"{label}: {field} {t[field]!r} is not a real date")
                continue
            if d > today:
                errors.append(f"{label}: {field} {t[field]} is in the future")
        if (t["last_used"] is None) != (t["use_count"] == 0):
            errors.append(f"{label}: use_count and last_used disagree (both unset, or both set)")
        if errors and errors[-1].startswith(label):
            continue
        if max_age_days and max_age_days > 0:
            age = (today - parse_date(t["verified_on"])).days
            if age > max_age_days:
                warnings.append(f"stale: {label} was verified {age} days ago ({t['verified_on']}); re-check it and update verified_on")
        if not t["verified"]:
            warnings.append(f"unverified: {label} ({t['verification_level']})")
    return errors, warnings


# ---- load / save --------------------------------------------------------------------------

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ordered(tool):
    known = {k: tool[k] for k in KEY_ORDER if k in tool}
    known.update({k: tool[k] for k in sorted(tool) if k not in known})
    return known


def dumps(data):
    out = {"$schema": "./schema.json", "schema_version": data.get("schema_version", 1)}
    out["tools"] = [_ordered(t) for t in sorted(data["tools"], key=lambda t: t["id"])]
    return json.dumps(out, indent=2, ensure_ascii=False) + "\n"


def save(path, data):
    Path(path).write_text(dumps(data), encoding="utf-8")


def find(data, tool_id):
    for t in data["tools"]:
        if t["id"] == tool_id:
            return t
    return None


# ---- rendering ----------------------------------------------------------------------------

def slugify(name):
    return SLUG_RE.sub("-", name.lower()).strip("-")


def status_label(t):
    level = t["verification_level"].lower()
    if not t["verified"]:
        return "UNVERIFIED"
    if level.startswith("secondary"):
        return "secondary source - re-check"
    if "secondary" in level:
        return "verified, partly secondary - re-check"
    return "verified (primary)"


def _fmt_score(x):
    return f"{x:.2f}"


def _used(t):
    return f"{t['use_count']} (last {t['last_used']})" if t["use_count"] else "never logged"


def _as_of_text(as_of):
    """Short phrase: 'as of 2026-11-04' or 'base weights only (no usage logged yet)'."""
    return f"as of {as_of}" if as_of else "base weights only (no usage logged yet)"


def category_title(c):
    return c.replace("-", " ").title()


def render_recommendations(data, as_of):
    tools = data["tools"]
    rank = ranked(tools, as_of)
    pos = {t["id"]: i + 1 for i, t in enumerate(rank)}
    L = []
    a = L.append
    a("# SVG tools: recommendations (local dev only)")
    a("")
    a("> **Local dev only. Do not ship these tools, add them to the deployed site (`docs/`), "
      "or wire them into CI or GitHub Actions.** Nothing in `tools/svg-tools/` is imported by the app.")
    a("")
    a("_Generated by `scripts/svgtools.py render` from `tools.json`. Do not edit by hand: "
      "change `tools.json` through the CLI (see README.md) and re-render._")
    a("")
    a("## Open questions")
    a("")
    qs = sorted((t for t in tools if t.get("open_question")), key=lambda t: t["id"])
    if qs:
        for t in qs:
            a(f"- **{t['name']}**: {t['open_question']}")
    else:
        a("None.")
    a("")
    a("## How to read this")
    a("")
    a(f"Score = editorial base weight (0-10) + a usage bonus that grows with logged use and fades with time "
      f"(half-life {HALF_LIFE_DAYS:g} days, capped at +{USAGE_CAP:g}). "
      f"Ranks below are **{_as_of_text(as_of)}**; `svgtools.py list` ranks as of today.")
    a("")
    a("Verification markers: **verified (primary)** = read from the project's own repo, licence or registry; "
      "**partly secondary** and **secondary source** = at least some facts come from search snippets or "
      "third-party sites, so re-check (prices especially) before relying on them; "
      "**UNVERIFIED** = research could not confirm the tool's status. "
      "Every entry carries `verified_on`; `svgtools.py validate` warns when it gets old.")
    a("")
    a("## Top picks")
    a("")
    a("| Rank | Tool | Category | Score | Verification |")
    a("|---:|---|---|---:|---|")
    for t in rank[:10]:
        a(f"| {pos[t['id']]} | {t['name']} | {t['category']} | {_fmt_score(score(t, as_of))} | {status_label(t)} |")
    a("")
    a("## By category")
    cats = {}
    for t in rank:
        cats.setdefault(t["category"], []).append(t)
    for cat in sorted(cats, key=lambda c: (-round(max(score(t, as_of) for t in cats[c]), 6), c)):
        a("")
        a(f"### {category_title(cat)}")
        for t in cats[cat]:
            a("")
            a(f"#### {t['name']}")
            a("")
            a(f"- **Rank {pos[t['id']]} of {len(rank)}** | score {_fmt_score(score(t, as_of))} "
              f"(base {t['base_weight']:g}, uses {_used(t)}) | id `{t['id']}`")
            a(f"- **Verification:** {status_label(t)}; verified on {t['verified_on']}. {t['verification_level']}.")
            a(f"- **Good for:** {t['summary']}")
            repo = t["repo"] or "none listed"
            a(f"- **Links:** [homepage]({t['homepage']}) | repo: {repo} | [evidence]({t['evidence_url']})")
            a(f"- **License:** {t['license']} | open source: {'yes' if t['open_source'] else 'no'} | price: {t['price_tier']}")
            a(f"- **Install:** {t['install']}")
            a(f"- **SVG notes:** {t['svg_notes']}")
            a(f"- **Caveats:** {t['caveats']}")
            if t["notes"]:
                a(f"- **Notes:** {t['notes']}")
            if t.get("open_question"):
                a(f"- **Open question:** {t['open_question']}")
    a("")
    return "\n".join(L)


def render_skill(data, as_of):
    tools = data["tools"]
    rank = ranked(tools, as_of)
    L = []
    a = L.append
    a("---")
    a("name: svg-tools")
    a("description: Ranked, weighted list of local-dev tools for working with SVG graphics (editing, animating, "
      "optimizing, converting, rasterizing). Use when a task involves creating, animating, optimizing, converting "
      "or rasterizing SVG, or when choosing a tool for it. Local development only; never for the deployed site or CI.")
    a("---")
    a("")
    a("<!-- Generated by tools/svg-tools/scripts/svgtools.py render. Do not edit by hand. -->")
    a("")
    a("# SVG tools (local dev only)")
    a("")
    a("Use this when a task involves SVG: editing, animating, optimizing, converting or rasterizing. "
      "These tools are for **local development only**: never add them to the deployed site (`docs/`), "
      "to CI or GitHub Actions, or to `requirements.txt`.")
    a("")
    a("## How to choose")
    a("")
    a("1. Pick the highest-ranked tool below that fits the job (same category or the same task). "
      "Rank already combines the editorial weight with how much each tool has actually been used.")
    a(f"2. Tools with a base weight under {LOW_WEIGHT:g} are kept as warnings (stale, deprecated, unverified or "
      "not SVG tools). Do not start new work with them.")
    a("3. Read the tool's caveats first (`tools/svg-tools/RECOMMENDATIONS.md`, or below for the top 8). "
      "Tools marked UNVERIFIED or secondary have facts that need re-checking, prices especially. "
      "Do not state a price as fact without re-checking it.")
    a("4. After you actually use a tool, log it so the ranking learns:")
    a("")
    a("```bash")
    a("python3 tools/svg-tools/scripts/svgtools.py use <id>            # add --times N for several uses")
    a("python3 tools/svg-tools/scripts/svgtools.py list --top 10       # current ranking (as of today)")
    a("```")
    a("")
    a("Only change weights (`svgtools.py weight <id> <0-10>`) when the user asks. "
      "Do not edit `tools.json` by hand; use the CLI, then `svgtools.py render`.")
    a("")
    a(f"## Ranked tools ({_as_of_text(as_of)})")
    a("")
    a("| Rank | id | Tool | Category | Score | Verification |")
    a("|---:|---|---|---|---:|---|")
    for i, t in enumerate(rank, 1):
        a(f"| {i} | `{t['id']}` | {t['name']} | {t['category']} | {_fmt_score(score(t, as_of))} | {status_label(t)} |")
    a("")
    qs = sorted((t for t in tools if t.get("open_question")), key=lambda t: t["id"])
    if qs:
        a("## Open questions (do not assume)")
        a("")
        for t in qs:
            a(f"- **{t['name']}** (`{t['id']}`): {t['open_question']}")
        a("")
    a("## Caveats for the top 8")
    a("")
    for t in rank[:8]:
        a(f"- **{t['name']}** (`{t['id']}`): {t['caveats']}")
    a("")
    return "\n".join(L)


def render_all(data, as_of=None):
    as_of = as_of if as_of is not None else render_as_of(data)
    return {
        "RECOMMENDATIONS.md": render_recommendations(data, as_of),
        "skill/SKILL.md": render_skill(data, as_of),
    }


# ---- CLI ---------------------------------------------------------------------------------

def _die(msg, code=1):
    print(msg, file=sys.stderr)
    return code


def cmd_list(args, ctx):
    data = load(ctx["data"])
    as_of = parse_date(args.as_of) if args.as_of else ctx["today"]
    rows = ranked(data["tools"], as_of)
    if args.category:
        rows = [t for t in rows if t["category"] == args.category]
        if not rows:
            return _die(f"no tools in category '{args.category}'", 2)
    if args.top:
        rows = rows[: args.top]
    print(f"{'#':>2}  {'score':>5}  {'id':<16} {'category':<13} {'base':>4}  {'uses':>4}  last_used")
    for i, t in enumerate(rows, 1):
        print(f"{i:>2}  {_fmt_score(score(t, as_of)):>5}  {t['id']:<16} {t['category']:<13} "
              f"{t['base_weight']:>4g}  {t['use_count']:>4}  {t['last_used'] or '-'}")
    return 0


def cmd_use(args, ctx):
    if args.times < 1:
        return _die("--times must be >= 1", 2)
    data = load(ctx["data"])
    t = find(data, args.id)
    if not t:
        return _die(f"unknown tool id '{args.id}' (see: svgtools.py list)", 2)
    when = parse_date(args.date) if args.date else ctx["today"]
    t["use_count"] += args.times
    t["last_used"] = max(when, parse_date(t["last_used"])).isoformat() if t["last_used"] else when.isoformat()
    save(ctx["data"], data)
    print(f"{t['id']}: use_count={t['use_count']}, last_used={t['last_used']}")
    return 0


def cmd_weight(args, ctx):
    if not 0 <= args.base_weight <= 10:
        return _die("base_weight must be between 0 and 10", 2)
    data = load(ctx["data"])
    t = find(data, args.id)
    if not t:
        return _die(f"unknown tool id '{args.id}'", 2)
    old, t["base_weight"] = t["base_weight"], args.base_weight
    save(ctx["data"], data)
    print(f"{t['id']}: base_weight {old:g} -> {args.base_weight:g}")
    return 0


ADD_FIELDS = [
    ("id", str), ("name", str), ("category", str), ("summary", str), ("homepage", str), ("repo", str),
    ("license", str), ("price_tier", str), ("install", str), ("svg_notes", str), ("caveats", str),
    ("verified_on", str), ("verification_level", str), ("evidence_url", str), ("notes", str),
    ("open_question", str), ("base_weight", float),
]


def build_entry(raw, today):
    """Fill defaults for a new entry. Required text fields are NOT defaulted: validation reports them."""
    t = dict(raw)
    if "name" in t and "id" not in t:
        t["id"] = slugify(t["name"])
    t.setdefault("repo", None)
    t.setdefault("verified", False)
    t.setdefault("verification_level", "unverified: added by hand")
    t.setdefault("verified_on", today.isoformat())
    t["local_dev_only"] = True
    t.setdefault("base_weight", 5)
    t.setdefault("use_count", 0)
    t.setdefault("last_used", None)
    t.setdefault("notes", "")
    if "tags" not in t and all(k in t for k in ("category", "price_tier", "open_source")):
        t["tags"] = [t["category"], t["price_tier"], "open-source" if t["open_source"] else "proprietary"]
    return t


def cmd_add(args, ctx):
    raws = []
    if args.json:
        loaded = json.loads(Path(args.json).read_text(encoding="utf-8"))
        raws = loaded if isinstance(loaded, list) else [loaded]
    else:
        raw = {k: getattr(args, k) for k, _ in ADD_FIELDS if getattr(args, k) is not None}
        for flag in ("open_source", "verified"):
            if getattr(args, flag) is not None:
                raw[flag] = getattr(args, flag)
        if args.tags is not None:
            raw["tags"] = [s.strip() for s in args.tags.split(",") if s.strip()]
        raws = [raw]
    data = load(ctx["data"])
    schema = load_schema(ctx["schema"])
    added = []
    for raw in raws:
        entry = build_entry(raw, ctx["today"])
        errs = validate_schema(entry, schema["$defs"]["tool"], schema, f"$.{entry.get('id', '?')}")
        if find(data, entry.get("id")) or any(e["id"] == entry.get("id") for e in added):
            errs.append(f"id '{entry.get('id')}' already exists")
        if errs:
            for e in errs:
                print(f"error: {e}", file=sys.stderr)
            return 1
        added.append(entry)
    data["tools"].extend(added)
    save(ctx["data"], data)
    for e in added:
        print(f"added {e['id']} (base_weight {e['base_weight']:g}). Run: svgtools.py render")
    return 0


def cmd_validate(args, ctx):
    data = load(ctx["data"])
    schema = load_schema(ctx["schema"])
    errors, warnings = check_data(data, schema, ctx["today"], args.max_age_days)
    for e in errors:
        print(f"error: {e}")
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        print(f"INVALID: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    if args.strict and warnings:
        print(f"OK with {len(warnings)} warning(s), failing because of --strict")
        return 1
    print(f"OK: {len(data['tools'])} tools, {len(warnings)} warning(s)")
    return 0


def cmd_render(args, ctx):
    data = load(ctx["data"])
    schema = load_schema(ctx["schema"])
    errors, _ = check_data(data, schema, ctx["today"], 0)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return _die("refusing to render invalid data (run: svgtools.py validate)", 1)
    outputs = render_all(data, parse_date(args.as_of) if args.as_of else None)
    base = Path(ctx["data"]).parent
    stale = []
    for rel, text in outputs.items():
        p = base / rel
        if args.check:
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                stale.append(rel)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_text(encoding="utf-8") != text:
            p.write_text(text, encoding="utf-8")
            print(f"wrote {rel}")
        else:
            print(f"unchanged {rel}")
    if args.check:
        if stale:
            return _die("out of date, run `svgtools.py render`: " + ", ".join(stale), 1)
        print("render is up to date")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="svgtools", description="Manage the weighted local-dev SVG tools library.")
    p.add_argument("--data", default=str(DATA_FILE), help="path to tools.json (default: next to scripts/)")
    p.add_argument("--schema", default=str(SCHEMA_FILE), help="path to schema.json")
    p.add_argument("--today", help=argparse.SUPPRESS)  # YYYY-MM-DD override, for tests
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="ranked list")
    s.add_argument("--category")
    s.add_argument("--top", type=int)
    s.add_argument("--as-of", help="rank as of this date (default: today)")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("use", help="log that you used a tool")
    s.add_argument("id")
    s.add_argument("--times", type=int, default=1)
    s.add_argument("--date", help="YYYY-MM-DD (default: today)")
    s.set_defaults(fn=cmd_use)

    s = sub.add_parser("weight", help="set a tool's editorial base weight (0-10)")
    s.add_argument("id")
    s.add_argument("base_weight", type=float)
    s.set_defaults(fn=cmd_weight)

    s = sub.add_parser("add", help="add a tool from flags or --json FILE (object or list)")
    s.add_argument("--json", help="JSON file with one tool object or a list of them")
    for key, typ in ADD_FIELDS:
        s.add_argument("--" + key.replace("_", "-"), dest=key, type=typ)
    s.add_argument("--tags", help="comma separated; default: category, price tier, open-source|proprietary")
    s.add_argument("--open-source", dest="open_source", action=argparse.BooleanOptionalAction)
    s.add_argument("--verified", dest="verified", action=argparse.BooleanOptionalAction)
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("validate", help="check tools.json against schema.json and sanity rules")
    s.add_argument("--max-age-days", type=int, default=STALE_DAYS_DEFAULT,
                   help=f"warn when verified_on is older than this (default {STALE_DAYS_DEFAULT}; 0 disables)")
    s.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("render", help="regenerate RECOMMENDATIONS.md and skill/SKILL.md")
    s.add_argument("--as-of", help="rank as of this date (default: the newest last_used, so output is deterministic)")
    s.add_argument("--check", action="store_true", help="do not write; exit 1 if the files are out of date")
    s.set_defaults(fn=cmd_render)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        today = parse_date(args.today) if args.today else today_default()
    except ValueError:
        return _die("--today must be YYYY-MM-DD", 2)
    ctx = {"data": args.data, "schema": args.schema, "today": today}
    try:
        return args.fn(args, ctx)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return _die(f"error: {e}", 2)


if __name__ == "__main__":
    sys.exit(main())
