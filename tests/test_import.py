import json
import os

from helpers import RepoCase, run

CHANGELOG = """# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- Something not released yet

## [1.1.0] - 2024-03-02
### Added
- Bulk export of reports as CSV, up to 50,000 rows ([#12](https://github.com/a/b/pull/12))
- Dark mode for the dashboard. See the [guide](https://docs.example.com/dark)
  for how to switch it on.
### Bug Fixes
- Fixed login loop

## [1.0.0] - 2024-01-15 [YANKED]
### Removed
- **Legacy** API v1 endpoints (#3)

[1.1.0]: https://github.com/a/b/compare/v1.0.0...v1.1.0
"""


class ImportTest(RepoCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.d, "CHANGELOG.md"), "w") as f:
            f.write(CHANGELOG)

    def load(self, v):
        with open(os.path.join(self.d, ".changelog", "demo", v + ".json")) as f:
            return json.load(f)

    def test_import_marks_everything_for_review(self):
        r = run("import_changelog.py", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("wrote 2 release(s), 4 entries", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.d, ".changelog", "demo", "Unreleased.json")))
        rel = self.load("1.1.0")
        self.assertIn("$schema", rel)
        self.assertEqual(rel["date"], "2024-03-02")
        added = rel["entries"][0]
        self.assertEqual(added["description"], "Bulk export of reports as CSV, up to 50,000 rows")
        self.assertEqual(added["refs"], ["#12"])
        self.assertEqual(added["audiences"], ["everyone"])
        self.assertIs(added["action_required"], False)
        self.assertIs(added["_needs_review"], True)
        dark = rel["entries"][1]
        self.assertIn("for how to switch it on", dark["description"])
        self.assertEqual(dark["links"], [{"label": "guide", "url": "https://docs.example.com/dark"}])
        self.assertEqual(rel["entries"][2]["type"], "fixed")
        old = self.load("1.0.0")
        self.assertTrue(old["yanked"])
        self.assertEqual(old["entries"][0]["description"], "Legacy API v1 endpoints")

        v = self.validate()
        self.assertEqual(v.returncode, 0, v.stdout)  # warnings, not errors
        self.assertEqual(v.stdout.count("needs review"), 4)
        self.assertNotEqual(self.validate("--strict").returncode, 0)

    def test_existing_files_are_kept(self):
        run("import_changelog.py", cwd=self.d)
        r = run("import_changelog.py", cwd=self.d)
        self.assertIn("skipped 2", r.stdout)

    def test_dry_run_writes_nothing(self):
        r = run("import_changelog.py", "--dry-run", cwd=self.d)
        self.assertIn("would write 2", r.stdout)
        self.assertEqual(os.listdir(os.path.join(self.d, ".changelog", "demo")), [".gitkeep"])
