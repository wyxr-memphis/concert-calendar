"""Unit tests for scripts/svgtools.py. Run: python3 -m unittest discover -s tools/svg-tools/tests
(or `python3 -m unittest` from inside tools/svg-tools/tests). Standard library only."""
import contextlib
import datetime
import io
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import svgtools as st  # noqa: E402

TODAY = "2026-11-04"
D = datetime.date.fromisoformat


def tool(**over):
    t = {
        "id": "demo", "name": "Demo", "category": "editor", "summary": "s", "homepage": "https://example.com/",
        "repo": None, "license": "MIT", "open_source": True, "price_tier": "free", "install": "i", "svg_notes": "n",
        "caveats": "c", "verified": True, "verified_on": "2026-11-01", "verification_level": "primary (test)",
        "evidence_url": "https://example.com/e", "local_dev_only": True, "tags": ["editor"], "base_weight": 5,
        "use_count": 0, "last_used": None, "notes": "",
    }
    t.update(over)
    return t


class Sandbox(unittest.TestCase):
    """Copies the real data + schema into a temp dir so CLI tests can mutate it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = self.tmp / "tools.json"
        shutil.copy(ROOT / "tools.json", self.data)
        shutil.copy(ROOT / "schema.json", self.tmp / "schema.json")

    def run_cli(self, *argv, today=TODAY):
        out, err = io.StringIO(), io.StringIO()
        full = ["--data", str(self.data), "--schema", str(self.tmp / "schema.json"), "--today", today, *argv]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = st.main(full)
        return code, out.getvalue(), err.getvalue()

    def tools(self):
        return {t["id"]: t for t in st.load(self.data)["tools"]}


class ScoringTests(unittest.TestCase):
    def test_never_used_has_no_bonus(self):
        self.assertEqual(st.usage_bonus(0, None, D(TODAY)), 0.0)
        self.assertEqual(st.score(tool(base_weight=7), D(TODAY)), 7)

    def test_log_scaling(self):
        d = D(TODAY)
        one = st.usage_bonus(1, TODAY, d)
        self.assertAlmostEqual(one, st.USAGE_SCALE * 1.0)
        self.assertAlmostEqual(st.usage_bonus(3, TODAY, d), st.USAGE_SCALE * 2.0)
        self.assertAlmostEqual(st.usage_bonus(7, TODAY, d), st.USAGE_SCALE * 3.0)
        # diminishing returns: the 10th use adds less than the 1st
        self.assertLess(st.usage_bonus(10, TODAY, d) - st.usage_bonus(9, TODAY, d), one)

    def test_bonus_is_capped(self):
        self.assertAlmostEqual(st.usage_bonus(10**9, TODAY, D(TODAY)), st.USAGE_CAP)

    def test_half_life(self):
        fresh = st.usage_bonus(7, TODAY, D(TODAY))
        later = D(TODAY) + datetime.timedelta(days=st.HALF_LIFE_DAYS)
        self.assertAlmostEqual(st.usage_bonus(7, TODAY, later), fresh / 2)
        much_later = D(TODAY) + datetime.timedelta(days=int(st.HALF_LIFE_DAYS * 4))
        self.assertAlmostEqual(st.usage_bonus(7, TODAY, much_later), fresh / 16)

    def test_use_after_as_of_counts_as_today(self):
        self.assertAlmostEqual(st.usage_bonus(3, "2026-12-01", D(TODAY)), st.usage_bonus(3, TODAY, D(TODAY)))

    def test_config_is_patchable(self):
        old = st.HALF_LIFE_DAYS
        try:
            st.HALF_LIFE_DAYS = 10
            later = D(TODAY) + datetime.timedelta(days=10)
            self.assertAlmostEqual(st.usage_bonus(1, TODAY, later), 0.5)
        finally:
            st.HALF_LIFE_DAYS = old

    def test_ranking_prior_then_usage_then_name(self):
        a, b, c = tool(id="a", name="Alpha", base_weight=5), tool(id="b", name="Beta", base_weight=5), tool(id="c", name="Gamma", base_weight=6)
        d = D(TODAY)
        self.assertEqual([t["id"] for t in st.ranked([b, a, c], d)], ["c", "a", "b"])  # tie broken by name
        b["use_count"], b["last_used"] = 3, TODAY
        self.assertEqual([t["id"] for t in st.ranked([a, b, c], d)], ["b", "c", "a"])  # usage lifts b over c

    def test_old_use_decays_back_towards_prior(self):
        hot = tool(id="hot", name="Hot", base_weight=5, use_count=7, last_used="2026-01-01")
        plain = tool(id="plain", name="Plain", base_weight=6)
        self.assertEqual(st.ranked([hot, plain], D("2026-01-01"))[0]["id"], "hot")
        self.assertEqual(st.ranked([hot, plain], D("2027-01-01"))[0]["id"], "plain")


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = st.load_schema()

    def errs(self, **over):
        t = tool(**over)
        return st.validate_schema(t, self.schema["$defs"]["tool"], self.schema)

    def test_valid_entry(self):
        self.assertEqual(self.errs(), [])
        self.assertEqual(self.errs(open_question="Confirm X"), [])
        self.assertEqual(self.errs(repo="https://github.com/a/b", last_used=TODAY, use_count=1), [])

    def test_rejections(self):
        for bad in (
            {"id": "Bad Id"}, {"id": ""}, {"category": "nonsense"}, {"price_tier": "cheap"},
            {"base_weight": 11}, {"base_weight": -1}, {"base_weight": "5"}, {"use_count": -1},
            {"use_count": 1.5}, {"use_count": True}, {"local_dev_only": False}, {"homepage": "ftp://x"},
            {"homepage": "not a url"}, {"repo": "nope"}, {"verified_on": "11/04/2026"}, {"last_used": "yesterday"},
            {"tags": ["A B"]}, {"tags": ["a", "a"]}, {"open_source": "yes"}, {"summary": ""}, {"open_question": ""},
        ):
            self.assertTrue(self.errs(**bad), bad)

    def test_unknown_and_missing_fields(self):
        self.assertTrue(self.errs(typo=1))
        t = tool()
        del t["caveats"]
        errs = st.validate_schema(t, self.schema["$defs"]["tool"], self.schema)
        self.assertTrue(any("caveats" in e for e in errs))

    def test_document_level(self):
        doc = {"schema_version": 1, "tools": [tool()]}
        self.assertEqual(st.validate_schema(doc, self.schema, self.schema), [])
        self.assertTrue(st.validate_schema({"schema_version": 2, "tools": []}, self.schema, self.schema))
        self.assertTrue(st.validate_schema({"tools": []}, self.schema, self.schema))


class CheckDataTests(unittest.TestCase):
    def setUp(self):
        self.schema = st.load_schema()

    def check(self, tools, max_age=180, today=TODAY):
        return st.check_data({"schema_version": 1, "tools": tools}, self.schema, D(today), max_age)

    def test_duplicate_ids(self):
        errors, _ = self.check([tool(), tool()])
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_stale_warning(self):
        old = tool(verified_on="2026-01-01")
        _, warnings = self.check([old], max_age=180)
        self.assertTrue(any(w.startswith("stale: demo") for w in warnings))
        _, warnings = self.check([old], max_age=400)
        self.assertEqual(warnings, [])
        _, warnings = self.check([old], max_age=0)
        self.assertEqual(warnings, [])
        _, warnings = self.check([tool(verified_on="2026-10-01")], max_age=180)
        self.assertEqual(warnings, [])

    def test_unverified_warning(self):
        _, warnings = self.check([tool(verified=False)])
        self.assertTrue(any(w.startswith("unverified: demo") for w in warnings))

    def test_future_and_impossible_dates(self):
        errors, _ = self.check([tool(verified_on="2027-01-01")])
        self.assertTrue(any("future" in e for e in errors))
        errors, _ = self.check([tool(verified_on="2026-13-45")])
        self.assertTrue(any("real date" in e for e in errors))

    def test_use_count_last_used_must_agree(self):
        errors, _ = self.check([tool(use_count=2, last_used=None)])
        self.assertTrue(errors)
        errors, _ = self.check([tool(use_count=0, last_used=TODAY)])
        self.assertTrue(errors)
        errors, _ = self.check([tool(use_count=2, last_used=TODAY)])
        self.assertEqual(errors, [])


class RealDataTests(unittest.TestCase):
    """Guards on the committed library itself."""

    @classmethod
    def setUpClass(cls):
        cls.data = st.load(st.DATA_FILE)
        cls.tools = cls.data["tools"]

    def test_valid(self):
        errors, _ = st.check_data(self.data, st.load_schema(), D(TODAY), 0)
        self.assertEqual(errors, [])

    def test_all_local_dev_only(self):
        self.assertTrue(all(t["local_dev_only"] is True for t in self.tools))

    def test_known_facts_preserved(self):
        by = {t["id"]: t for t in self.tools}
        self.assertEqual(len(by), 32)
        art = by["artcraft"]
        self.assertEqual(art["repo"], "https://github.com/storytold/artcraft")
        self.assertIn("MIT OR Apache-2.0", art["license"])
        self.assertIn("README does not mention SVG", art["svg_notes"])
        self.assertIn("Confirm", art["open_question"])
        self.assertFalse(by["svgcleaner"]["verified"])
        self.assertIn("deprecat", by["rlottie"]["caveats"].lower())
        self.assertIn("policy.xml", by["imagemagick"]["caveats"])
        self.assertIn("not an OSI licence", by["gsap"]["license"])
        self.assertFalse(by["gsap"]["open_source"])
        for i in ("figma", "lottiefiles", "boxy-svg", "svgator", "rive"):
            self.assertTrue(by[i].get("open_question"), i)

    def test_priors_follow_editorial_intent(self):
        by = {t["id"]: t["base_weight"] for t in self.tools}
        high = min(by[i] for i in ("imagemagick", "figma", "lottiefiles", "inkscape", "svgo", "gsap", "anime-js"))
        low = max(by[i] for i in ("rlottie", "svgcleaner", "snap-svg", "vivus"))
        self.assertGreater(high, low + 5)
        self.assertLess(low, st.LOW_WEIGHT + 0.01)

    def test_file_is_canonically_formatted(self):
        self.assertEqual(st.DATA_FILE.read_text(encoding="utf-8"), st.dumps(self.data))

    def test_generated_files_are_up_to_date(self):
        for rel, text in st.render_all(self.data).items():
            self.assertEqual((ROOT / rel).read_text(encoding="utf-8"), text, f"{rel} is stale: run svgtools.py render")


class CliTests(Sandbox):
    def test_list_ranked_and_filters(self):
        code, out, _ = self.run_cli("list", "--top", "3")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 4)  # header + 3
        self.assertIn("svgo", out.splitlines()[1])
        code, out, _ = self.run_cli("list", "--category", "optimizer")
        self.assertEqual(code, 0)
        self.assertNotIn("inkscape", out)
        code, _, err = self.run_cli("list", "--category", "nope")
        self.assertEqual(code, 2)

    def test_use_bumps_count_and_date(self):
        code, out, _ = self.run_cli("use", "svg-js")
        self.assertEqual(code, 0)
        t = self.tools()["svg-js"]
        self.assertEqual((t["use_count"], t["last_used"]), (1, TODAY))
        self.run_cli("use", "svg-js", "--times", "4", today="2026-11-10")
        t = self.tools()["svg-js"]
        self.assertEqual((t["use_count"], t["last_used"]), (5, "2026-11-10"))
        self.run_cli("use", "svg-js", "--date", "2026-11-05")  # an older back-dated log never moves last_used backwards
        self.assertEqual(self.tools()["svg-js"]["last_used"], "2026-11-10")

    def test_use_lifts_rank(self):
        self.run_cli("use", "svg-js", "--times", "31")
        _, out, _ = self.run_cli("list", "--top", "1")
        self.assertIn("svg-js", out)  # 5.5 + 5.0 bonus beats svgo 9.5

    def test_use_errors(self):
        self.assertEqual(self.run_cli("use", "nope")[0], 2)
        self.assertEqual(self.run_cli("use", "svgo", "--times", "0")[0], 2)

    def test_weight(self):
        self.assertEqual(self.run_cli("weight", "vivus", "7.5")[0], 0)
        self.assertEqual(self.tools()["vivus"]["base_weight"], 7.5)
        self.assertEqual(self.run_cli("weight", "vivus", "11")[0], 2)
        self.assertEqual(self.run_cli("weight", "nope", "1")[0], 2)
        self.assertEqual(self.tools()["vivus"]["base_weight"], 7.5)

    def flags(self, **over):
        base = dict(name="Demo Tool", category="editor", summary="s", homepage="https://example.com/", license="MIT",
                    price_tier="free", install="npm i demo", svg_notes="n", caveats="c", evidence_url="https://example.com/e")
        base.update(over)
        argv = ["add", "--open-source"]
        for k, v in base.items():
            argv += ["--" + k.replace("_", "-"), str(v)]
        return argv

    def test_add_from_flags(self):
        code, out, err = self.run_cli(*self.flags(base_weight=6.5))
        self.assertEqual(code, 0, err)
        t = self.tools()["demo-tool"]
        self.assertEqual((t["base_weight"], t["use_count"], t["last_used"], t["local_dev_only"]), (6.5, 0, None, True))
        self.assertFalse(t["verified"])  # a hand-added tool is never claimed as verified
        self.assertEqual(t["verified_on"], TODAY)
        self.assertEqual(t["tags"], ["editor", "free", "open-source"])
        self.assertEqual(self.run_cli("validate")[0], 0)
        self.assertEqual(len(self.tools()), 33)

    def test_add_rejects_bad_and_duplicate(self):
        self.assertEqual(self.run_cli(*self.flags(category="nonsense"))[0], 1)
        self.assertEqual(self.run_cli(*self.flags(base_weight=12))[0], 1)
        self.assertEqual(self.run_cli(*self.flags(homepage="not-a-url"))[0], 1)
        self.assertEqual(self.run_cli(*self.flags(id="svgo"))[0], 1)
        code, _, err = self.run_cli("add", "--name", "Only Name")
        self.assertEqual(code, 1)
        self.assertIn("missing required field", err)
        self.assertEqual(len(self.tools()), 32)

    def test_add_from_json_object_and_list(self):
        one = {"name": "From Json", "category": "library", "summary": "s", "homepage": "https://example.com/",
               "license": "MIT", "open_source": True, "price_tier": "free", "install": "i", "svg_notes": "n",
               "caveats": "c", "evidence_url": "https://example.com/e", "verified": True,
               "verification_level": "primary (test)", "base_weight": 3, "local_dev_only": False}
        f = self.tmp / "one.json"
        f.write_text(json.dumps(one))
        self.assertEqual(self.run_cli("add", "--json", str(f))[0], 0)
        t = self.tools()["from-json"]
        self.assertTrue(t["local_dev_only"])  # forced: nothing here is for production
        self.assertTrue(t["verified"])
        two = [dict(one, name="Json Two"), dict(one, name="Json Three")]
        f.write_text(json.dumps(two))
        self.assertEqual(self.run_cli("add", "--json", str(f))[0], 0)
        self.assertEqual(len(self.tools()), 35)
        f.write_text(json.dumps([dict(one, name="Json Four"), dict(one, name="Json Four")]))  # duplicate inside the batch
        self.assertEqual(self.run_cli("add", "--json", str(f))[0], 1)
        self.assertEqual(len(self.tools()), 35)  # nothing partially written

    def test_validate_and_stale_check(self):
        code, out, _ = self.run_cli("validate", "--max-age-days", "180")
        self.assertEqual(code, 0)
        self.assertNotIn("stale", out)
        code, out, _ = self.run_cli("validate", "--max-age-days", "180", today="2027-06-01")
        self.assertEqual(code, 0)
        self.assertIn("warning: stale: svgo", out)
        code, _, _ = self.run_cli("validate", "--max-age-days", "180", "--strict", today="2027-06-01")
        self.assertEqual(code, 1)
        code, out, _ = self.run_cli("validate", "--max-age-days", "0", today="2027-06-01")
        self.assertNotIn("stale", out)

    def test_validate_catches_corruption(self):
        d = st.load(self.data)
        d["tools"][0]["base_weight"] = 99
        self.data.write_text(json.dumps(d))
        code, out, _ = self.run_cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("base_weight", out)
        self.assertEqual(self.run_cli("render")[0], 1)  # refuses to render invalid data

    def test_render_is_idempotent_and_deterministic(self):
        self.assertEqual(self.run_cli("render")[0], 0)
        first = {p: (self.tmp / p).read_bytes() for p in ("RECOMMENDATIONS.md", "skill/SKILL.md")}
        code, out, _ = self.run_cli("render", today="2030-01-01")  # today must not leak into output
        self.assertEqual(code, 0)
        self.assertIn("unchanged RECOMMENDATIONS.md", out)
        for p, b in first.items():
            self.assertEqual((self.tmp / p).read_bytes(), b)
        self.assertEqual(self.run_cli("render", "--check")[0], 0)

    def test_render_check_detects_drift_and_usage_changes_output(self):
        self.run_cli("render")
        self.run_cli("use", "penpot", "--times", "7")
        code, _, err = self.run_cli("render", "--check")
        self.assertEqual(code, 1)
        self.assertIn("out of date", err)
        self.run_cli("render")
        text = (self.tmp / "RECOMMENDATIONS.md").read_text(encoding="utf-8")
        self.assertIn(f"as of {TODAY}", text)
        self.assertIn("uses 7 (last 2026-11-04)", text)

    def test_rendered_content(self):
        self.run_cli("render")
        rec = (self.tmp / "RECOMMENDATIONS.md").read_text(encoding="utf-8")
        skill = (self.tmp / "skill/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Local dev only", rec)
        self.assertIn("## Open questions", rec)
        self.assertIn("ArtCraft", rec.split("## How to read this")[0])
        self.assertIn("UNVERIFIED", rec)
        for t in st.load(self.data)["tools"]:
            self.assertIn(f"#### {t['name']}", rec)
            self.assertIn(f"`{t['id']}`", skill)
        self.assertTrue(skill.startswith("---\nname: svg-tools\ndescription: "))
        self.assertIn("svgtools.py use <id>", skill)
        self.assertIn("python3 tools/svg-tools/scripts/svgtools.py use", skill)
        self.assertNotIn("\r", rec + skill)
        self.assertTrue(rec.endswith("\n") and skill.endswith("\n"))

    def test_json_save_is_stable(self):
        before = self.data.read_bytes()
        self.run_cli("weight", "svgo", "9.5")  # no-op change rewrites identical bytes
        self.assertEqual(self.data.read_bytes(), before)


class HelperTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(st.slugify("Motion (motion.dev)"), "motion-motion-dev")
        self.assertEqual(st.slugify("  SVG Path Editor "), "svg-path-editor")

    def test_status_label(self):
        self.assertEqual(st.status_label(tool(verified=False)), "UNVERIFIED")
        self.assertIn("secondary source", st.status_label(tool(verification_level="secondary (npm)")))
        self.assertIn("partly secondary", st.status_label(tool(verification_level="primary for a; secondary for b")))
        self.assertEqual(st.status_label(tool()), "verified (primary)")

    def test_render_as_of(self):
        self.assertIsNone(st.render_as_of({"tools": [tool()]}))
        d = {"tools": [tool(use_count=1, last_used="2026-03-01"), tool(id="b", use_count=1, last_used="2026-05-01")]}
        self.assertEqual(st.render_as_of(d), D("2026-05-01"))


if __name__ == "__main__":
    unittest.main()
