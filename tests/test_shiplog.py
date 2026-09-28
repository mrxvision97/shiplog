"""End-to-end tests for Shiplog scripts. Run: python -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "plugins", "shiplog", "skills", "shiplog", "scripts")
PY = sys.executable

GOOD_RELEASE = {
    "version": "1.1.0",
    "date": "2026-09-28",
    "entries": [
        {"type": "added", "title": "Export up to 50,000 rows at once",
         "description": "Large CSV exports from the Reports page now complete in one step.",
         "audiences": ["admins"], "action_required": False,
         "internal_notes": "SECRET-NOTE", "refs": ["#412"]},
        {"type": "changed", "title": "Older mobile apps can no longer sign in",
         "description": "Versions of the mobile app older than 4.2 can no longer sign in.",
         "audiences": ["end-users"], "action_required": True, "breaking": True,
         "action": "Update the app to version 4.2 or later."},
    ],
}


def run(script, *args, cwd):
    return subprocess.run([PY, os.path.join(SCRIPTS, script)] + list(args), cwd=cwd,
                          capture_output=True, text=True)


def git(cwd, *args):
    subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True)


class ShiplogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        git(self.d, "init", "-q")
        git(self.d, "config", "user.email", "t@t.t")
        git(self.d, "config", "user.name", "T")
        self.commit("a", "feat: first")
        git(self.d, "tag", "v1.0.0")
        r = run("init.py", "--name", "Demo", "--id", "demo", "--with-ci", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, fname, msg, body=None):
        with open(os.path.join(self.d, fname), "w") as f:
            f.write(fname)
        git(self.d, "add", ".")
        args = ["commit", "-qm", msg] + (["-m", body] if body else [])
        git(self.d, *args)

    def write_release(self, data, version=None):
        path = os.path.join(self.d, ".changelog", "demo", (version or data["version"]) + ".json")
        with open(path, "w") as f:
            json.dump(data, f)

    def collect(self):
        r = run("collect_changes.py", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    # collect_changes -------------------------------------------------------
    def test_suggests_patch_for_fixes(self):
        self.commit("b", "fix: thing")
        self.assertEqual(self.collect()["suggested_version"], "1.0.1")

    def test_suggests_minor_for_feat(self):
        self.commit("b", "feat(ui): thing (#12)")
        out = self.collect()
        self.assertEqual(out["suggested_version"], "1.1.0")
        self.assertEqual(out["likely_user_facing"][0]["refs"], ["#12"])

    def test_suggests_major_for_breaking_footer(self):
        self.commit("b", "refactor: x", "BREAKING CHANGE: removed y")
        out = self.collect()
        self.assertEqual(out["suggested_version"], "2.0.0")
        self.assertEqual(out["breaking_count"], 1)
        self.assertEqual(out["likely_internal"], [])  # breaking refactor is user-facing

    def test_internal_commits_separated(self):
        self.commit("b", "chore(deps): bump")
        self.commit("c", "Some freeform message")
        out = self.collect()
        self.assertEqual(len(out["likely_internal"]), 1)
        self.assertEqual(out["likely_user_facing"][0]["type"], "other")

    # validate ------------------------------------------------------------
    def test_valid_release_passes(self):
        self.write_release(GOOD_RELEASE)
        r = run("validate.py", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_missing_impact_fields_fail(self):
        bad = {"version": "1.1.0", "date": "2026-09-28",
               "entries": [{"type": "added", "title": "X", "description": "Something reasonably long here."}]}
        self.write_release(bad)
        r = run("validate.py", cwd=self.d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("audiences", r.stdout)
        self.assertIn("action_required", r.stdout)

    def test_breaking_requires_action(self):
        rel = json.loads(json.dumps(GOOD_RELEASE))
        rel["entries"][1]["action_required"] = False
        del rel["entries"][1]["action"]
        self.write_release(rel)
        self.assertEqual(run("validate.py", cwd=self.d).returncode, 1)

    def test_unknown_audience_and_bad_version(self):
        rel = json.loads(json.dumps(GOOD_RELEASE))
        rel["entries"][0]["audiences"] = ["martians"]
        rel["version"] = "v1.1"
        self.write_release(rel, version="v1.1")
        r = run("validate.py", cwd=self.d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("martians", r.stdout)
        self.assertIn("SemVer", r.stdout)

    def test_jargon_is_warning_unless_strict(self):
        rel = json.loads(json.dumps(GOOD_RELEASE))
        rel["entries"][0]["description"] = "Refactored the export middleware, see PROJ-12."
        self.write_release(rel)
        r = run("validate.py", cwd=self.d)
        self.assertEqual(r.returncode, 0)
        self.assertIn("warning", r.stdout)
        self.assertEqual(run("validate.py", "--strict", cwd=self.d).returncode, 1)

    def test_tag_mode(self):
        self.write_release(GOOD_RELEASE)
        self.assertEqual(run("validate.py", "--tag", "v1.1.0", cwd=self.d).returncode, 0)
        self.assertEqual(run("validate.py", "--tag", "v9.9.9", cwd=self.d).returncode, 1)

    # render ----------------------------------------------------------------
    def test_render_outputs_and_no_internal_leak(self):
        self.write_release(GOOD_RELEASE)
        r = run("render.py", "--internal", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = os.path.join(self.d, "changelog", "demo")
        for name in ("index.html", "feed.xml", "changelog.json"):
            with open(os.path.join(out, name)) as f:
                content = f.read()
            self.assertNotIn("SECRET-NOTE", content, name)
            self.assertNotIn("{{", content, name)
        with open(os.path.join(out, "internal.html")) as f:
            self.assertIn("SECRET-NOTE", f.read())
        with open(os.path.join(self.d, "CHANGELOG.md")) as f:
            md = f.read()
        self.assertIn("## [1.1.0] - 2026-09-28", md)
        self.assertIn("**Action required:**", md)

    def test_render_escapes_html(self):
        rel = json.loads(json.dumps(GOOD_RELEASE))
        rel["entries"][0]["title"] = "<script>alert(1)</script> title"
        self.write_release(rel)
        run("render.py", cwd=self.d)
        with open(os.path.join(self.d, "changelog", "demo", "index.html")) as f:
            self.assertNotIn("<script>alert(1)</script>", f.read())

    def test_render_blocked_by_invalid_release(self):
        self.write_release({"version": "1.1.0", "date": "nope", "entries": []})
        self.assertNotEqual(run("render.py", cwd=self.d).returncode, 0)

    def test_render_is_deterministic(self):
        """Re-rendering unchanged data on another day must be byte-identical."""
        self.write_release(GOOD_RELEASE)
        out = os.path.join(self.d, "changelog", "demo")
        # Run render.py with datetime.date.today() faked to two different days.
        shim = ("import datetime, runpy, sys\n"
                "real = datetime.date\n"
                "class D(real):\n"
                "    @classmethod\n"
                "    def today(cls): return real(2030, 1, DAY)\n"
                "DAY = int(sys.argv.pop())\n"
                "datetime.date = D\n"
                "sys.argv = sys.argv[1:]\n"
                "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        snapshots = []
        for day in ("1", "2"):
            r = subprocess.run([PY, "-c", shim, os.path.join(SCRIPTS, "render.py"), "--internal", day],
                               cwd=self.d, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            snap = {}
            for name in sorted(os.listdir(out)) + ["../../CHANGELOG.md"]:
                with open(os.path.join(out, name), "rb") as f:
                    snap[name] = f.read()
            snapshots.append(snap)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertNotIn(b"2030", snapshots[0]["index.html"])
        self.assertIn(b"2026-09-28", snapshots[0]["index.html"])

    def test_vendored_scripts_work(self):
        self.write_release(GOOD_RELEASE)
        vend = os.path.join(self.d, ".shiplog", "scripts")
        r = subprocess.run([PY, os.path.join(vend, "render.py")], cwd=self.d, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.d, ".github", "workflows", "shiplog.yml")))


if __name__ == "__main__":
    unittest.main()
