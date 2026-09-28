"""Adding releases to an existing hand-written CHANGELOG.md in its own format."""
import difflib
import os
import unittest

from helpers import entry

import changelog_md as cm

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
RELEASE = {"version": "1.3.0", "date": "2026-09-28", "entries": [
    entry(title="Bulk CSV export", description="Export whole reports as CSV in one step from the Reports page.",
          refs=["#42"]),
    entry(type="fixed", title="Login redirect loop",
          description="Signing in no longer sends you back to the login page.", refs=["#43"]),
    entry(type="changed", title="API keys expire", description="API keys now expire after a year.",
          action_required=True, breaking=True, action="Rotate your keys in Settings.", action_deadline="2027-03-31"),
]}


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8", newline="") as f:
        return f.read()


def added_lines(old, new):
    diff = list(difflib.ndiff(old.splitlines(), new.splitlines()))
    assert not [d for d in diff if d.startswith("- ")], "an existing line changed"
    return [d[2:] for d in diff if d.startswith("+ ")]


class InsertTest(unittest.TestCase):
    def check(self, fixture, expected):
        old = load(fixture)
        new, added, notes = cm.insert_releases(old, [RELEASE])
        self.assertEqual(added, ["1.3.0"])
        self.assertEqual(notes, [])
        lines = added_lines(old, new)
        for line in expected:
            self.assertIn(line, lines)
        again, added2, _ = cm.insert_releases(new, [RELEASE])
        self.assertEqual((again, added2), (new, []))  # never added twice
        return new

    def test_keep_a_changelog(self):
        new = self.check("kac.md", [
            "## [1.3.0] - 2026-09-28", "### Added", "- Bulk CSV export.", "- Login redirect loop.",
            "- **Breaking:** API keys expire.",
            "  - **Action required:** Rotate your keys in Settings. (by 2027-03-31)",
            "[1.3.0]: https://github.com/acme/app/compare/v1.2.0...v1.3.0"])
        # Below Unreleased, above the newest release; sections in Keep a Changelog order.
        self.assertLess(new.index("## [Unreleased]"), new.index("## [1.3.0]"))
        self.assertLess(new.index("## [1.3.0]"), new.index("## [1.2.0]"))
        self.assertLess(new.index("### Changed"), new.index("- Login redirect loop."))

    def test_conventional_changelog(self):
        self.check("conventional.md", [
            "## [1.3.0](https://github.com/acme/app/compare/v1.2.0...v1.3.0) (2026-09-28)",
            "### ⚠ BREAKING CHANGES", "* **API keys expire**: API keys now expire after a year.",
            "### Features", "### Bug Fixes",
            "* **Bulk CSV export**: Export whole reports as CSV in one step from the Reports page. "
            "([#42](https://github.com/acme/app/issues/42))"])

    def test_custom_format(self):
        self.check("custom.md", [
            "## v1.3.0 — September 28, 2026", "### 🚀 New", "### 🐛 Fixes",
            "* Export whole reports as CSV in one step from the Reports page.",
            "* Signing in no longer sends you back to the login page."])

    def test_crlf_and_older_versions(self):
        old = load("kac.md").replace("\n", "\r\n")
        older = dict(RELEASE, version="1.0.5")
        new, added, notes = cm.insert_releases(old, [RELEASE, older, dict(RELEASE, version="1.2.0")])
        self.assertEqual(added, ["1.3.0"])
        self.assertNotIn("\n", new.replace("\r\n", ""))
        self.assertTrue(any("1.0.5 is older" in n for n in notes))

    def test_no_versions_means_no_guessing(self):
        old = "# Changelog\n\n## [Unreleased]\n- Pending thing\n"
        new, added, notes = cm.insert_releases(old, [RELEASE])
        self.assertEqual((new, added), (old, []))
        self.assertIn("can't be matched", notes[0])


if __name__ == "__main__":
    unittest.main()
