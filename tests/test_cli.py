"""shiplog.py entry point, release command, summary mode, gh enrichment, speed."""
import json
import os
import random
import stat
import tempfile
import time
import unittest

from helpers import ENV, RepoCase, entry, run

import collect_changes
import render
import validate
from _common import load_config, select_app


class CliTest(RepoCase):
    def test_help_and_dispatch(self):
        r = run("shiplog.py", cwd=self.d)
        self.assertEqual(r.returncode, 0)
        for cmd in ("init", "collect", "validate", "render", "release", "notify", "import"):
            self.assertIn(cmd, r.stdout)
        r = run("shiplog.py", "validate", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no releases yet", r.stdout)
        self.assertEqual(run("shiplog.py", "bogus", cwd=self.d).returncode, 2)

    def test_old_scripts_still_work(self):
        self.commit("b", "fix: thing")
        for script in ("collect_changes.py", "validate.py", "render.py"):
            self.assertEqual(run(script, cwd=self.d).returncode, 0, script)

    def test_release_validates_and_renders_in_one_step(self):
        self.write_release({"version": "1.1.0", "date": "2026-09-28", "entries": [entry()]})
        r = run("shiplog.py", "release", "--version", "v1.1.0", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("✓ Demo 1.1.0: ok"), r.stdout)
        self.assertIn("rendered", r.stdout)
        self.assertLessEqual(len(r.stdout.splitlines()), 4)
        self.assertTrue(os.path.exists(os.path.join(self.d, "changelog", "demo", "index.html")))

    def test_release_fails_for_missing_or_invalid(self):
        r = run("shiplog.py", "release", "--version", "9.9.9", cwd=self.d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no release file for version 9.9.9", r.stdout)
        self.write_release({"version": "1.1.0", "date": "2026-09-28", "entries": [entry(description="short")]})
        r = run("shiplog.py", "release", "--version", "1.1.0", cwd=self.d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("description is too short", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.d, "changelog", "demo", "index.html")))


class SummaryTest(RepoCase):
    def test_summary_is_compact(self):
        """A 100-commit release: the summary is at least 5x smaller than --full."""
        body = ("This change reworks the export pipeline so large reports stream to disk. "
                "It touches the worker queue, retries and the CSV writer. " * 4)
        kinds = ["feat", "fix", "chore", "refactor", "perf"]
        for i in range(100):
            self.commit("f%d" % (i % 7), "%s(area%d): change number %d (#%d)" % (kinds[i % 5], i % 3, i, 100 + i),
                        body + ("\nRefs PROJ-%d" % i))
        summary = run("collect_changes.py", cwd=self.d).stdout
        full = run("collect_changes.py", "--full", cwd=self.d).stdout
        self.assertEqual(len(summary.splitlines()), 1 + 100 + 2)  # header + changes + 2 section labels
        self.assertIn("feat(area0)  #100  change number 0  [PROJ-0]", summary)
        self.assertGreaterEqual(len(full) / len(summary), 5, (len(full), len(summary)))


class GhEnrichTest(RepoCase):
    def test_one_batched_gh_call(self):
        self.commit("b", "Add export (#5)")
        self.commit("c", "Fix login (#6)")
        fake = os.path.join(self.d, "bin")
        os.makedirs(fake)
        log = os.path.join(self.d, "gh.log")
        with open(os.path.join(fake, "gh"), "w") as f:
            f.write("#!/bin/sh\necho \"$@\" >> %s\n" % log)
            f.write("cat <<'JSON'\n%s\nJSON\n" % json.dumps({"data": {"repository": {
                "p5": {"title": "Bulk CSV export", "body": "Lets admins export " + "x" * 900,
                       "labels": {"nodes": [{"name": "breaking-change"}]}},
                "p6": None}}}))
        os.chmod(os.path.join(fake, "gh"), stat.S_IRWXU)
        env = dict(ENV, PATH=fake + os.pathsep + os.environ["PATH"])
        env.pop("SHIPLOG_NO_GH")
        out = json.loads(run("collect_changes.py", "--full", cwd=self.d, env=env).stdout)
        with open(log) as f:
            calls = f.read().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertIn("pullRequest(number: 5)", calls[0])
        self.assertIn("pullRequest(number: 6)", calls[0])
        pr5 = next(c for c in out["likely_user_facing"] if c["pr"] == "#5")
        self.assertEqual(pr5["pr_title"], "Bulk CSV export")
        self.assertLessEqual(len(pr5["pr_body"]), collect_changes.PR_BODY_MAX)
        self.assertTrue(pr5["breaking"])
        self.assertTrue(out["pr_details"])

    def test_missing_gh_is_silent(self):
        self.commit("b", "Add export (#5)")
        env = dict(ENV, PATH="/usr/bin:/bin")  # git, but no gh on macOS/typical Linux
        env.pop("SHIPLOG_NO_GH")
        r = run("collect_changes.py", cwd=self.d, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")


class PerformanceTest(unittest.TestCase):
    def test_500_releases_validate_and_render_under_a_second(self):
        rnd = random.Random(1)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".shiplog.json"), "w") as f:
                json.dump({"id": "big", "name": "Big", "base_url": "https://x.test/changelog",
                           "audiences": [{"id": "admins", "label": "Admins"}, {"id": "end-users"}]}, f)
            rdir = os.path.join(d, ".changelog", "big")
            os.makedirs(rdir)
            for i in range(500):
                v = "%d.%d.0" % (i // 20, i % 20)
                rel = {"version": v, "date": "20%02d-%02d-%02d" % (10 + i // 40, 1 + (i // 4) % 12, 1 + i % 4),
                       "summary": "Release %s" % v,
                       "entries": [entry(type=rnd.choice(["added", "changed", "fixed"]),
                                         title="Change %d in release %s" % (j, v),
                                         audiences=[rnd.choice(["admins", "end-users", "everyone"])])
                                   for j in range(5)]}
                with open(os.path.join(rdir, v + ".json"), "w") as f:
                    json.dump(rel, f)
            app = select_app(load_config(d))
            start = time.perf_counter()
            n_err, _, _ = validate.check_app(app, d)
            render.render_app(app, d, internal=True, quiet=True)
            elapsed = time.perf_counter() - start
            self.assertEqual(n_err, 0)
            self.assertLess(elapsed, 1.0, "took %.2fs" % elapsed)


if __name__ == "__main__":
    unittest.main()
