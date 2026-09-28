import os
import subprocess
import unittest

from helpers import RepoCase, git, run

import collect_changes


class BumpTest(unittest.TestCase):
    def test_release_bumps(self):
        self.assertEqual(collect_changes.bump("1.2.3", "patch"), "1.2.4")
        self.assertEqual(collect_changes.bump("1.2.3", "minor"), "1.3.0")
        self.assertEqual(collect_changes.bump("1.2.3", "major"), "2.0.0")
        self.assertEqual(collect_changes.bump("0.4.1", "major"), "0.5.0")

    def test_prerelease_bumps_drop_the_suffix(self):
        self.assertEqual(collect_changes.bump("1.2.0-beta.1", "patch"), "1.2.0")
        self.assertEqual(collect_changes.bump("1.2.0-beta.1", "minor"), "1.2.0")
        self.assertEqual(collect_changes.bump("1.2.0-beta.1", "major"), "2.0.0")
        self.assertEqual(collect_changes.bump("2.0.0-rc.1", "major"), "2.0.0")
        self.assertEqual(collect_changes.bump("1.2.3-rc.1", "minor"), "1.3.0")


class CollectTest(RepoCase):
    def test_pre_release_tag(self):
        git(self.d, "tag", "v1.2.0-beta.1")
        self.commit("b", "fix: thing")
        out = self.collect()
        self.assertEqual(out["last_version"], "1.2.0-beta.1")
        self.assertEqual(out["suggested_version"], "1.2.0")

    def test_merge_commits_grouped_by_pr(self):
        git(self.d, "checkout", "-qb", "feature")
        self.commit("b", "wip on export")
        self.commit("c", "fix: export edge case", "Refs PROJ-9")
        git(self.d, "checkout", "-q", "main")
        self.commit("d", "docs: readme")
        git(self.d, "merge", "--no-ff", "-q", "feature", "-m", "Merge pull request #42 from acme/feature",
            "-m", "feat(export): bulk CSV export")
        self.commit("e", "Fix typo in footer (#43)")
        out = self.collect()
        prs = {c["pr"]: c for c in out["likely_user_facing"]}
        self.assertEqual(set(prs), {"#42", "#43"})
        self.assertEqual(prs["#42"]["subject"], "bulk CSV export")
        self.assertEqual(prs["#42"]["type"], "feat")
        self.assertEqual(len(prs["#42"]["commits"]), 2)
        self.assertIn("PROJ-9", prs["#42"]["refs"])
        self.assertEqual(prs["#43"]["subject"], "Fix typo in footer")
        self.assertEqual(out["commit_count"], 4)
        self.assertEqual(out["change_count"], 3)
        self.assertEqual(out["suggested_version"], "1.1.0")

    def test_merge_pr_title_type_falls_back_to_commits(self):
        git(self.d, "checkout", "-qb", "f")
        self.commit("b", "feat!: drop v1 API")
        git(self.d, "checkout", "-q", "main")
        git(self.d, "merge", "--no-ff", "-q", "f", "-m", "Merge pull request #7 from a/f", "-m", "New API")
        out = self.collect()
        self.assertTrue(out["likely_user_facing"][0]["breaking"])
        self.assertEqual(out["suggested_version"], "2.0.0")

    def test_ignores_tags_not_on_branch(self):
        git(self.d, "checkout", "-qb", "side")
        self.commit("s", "fix: side")
        git(self.d, "tag", "v5.0.0")
        git(self.d, "checkout", "-q", "main")
        self.commit("b", "fix: main")
        out = self.collect()
        self.assertEqual(out["last_tag"], "v1.0.0")
        self.assertEqual(out["suggested_version"], "1.0.1")

    def test_to_ref_decides_reachable_tags(self):
        self.commit("b", "fix: one")
        git(self.d, "tag", "v1.0.1")
        out = self.collect("--to", "v1.0.0")
        self.assertEqual(out["last_tag"], "v1.0.0")

    def test_no_commits(self):
        out = self.collect()
        self.assertIsNone(out["suggested_version"])
        self.assertTrue(any("nothing to release" in n for n in out["notes"]))


class RefsTest(unittest.TestCase):
    def test_standards_are_not_ticket_refs(self):
        self.assertEqual(collect_changes.find_refs("Use UTF-8 and ISO-8601, fixes PROJ-3 (#9)"), ["#9", "PROJ-3"])


class FirstReleaseTest(RepoCase):
    tag = None

    def test_first_release_without_tags(self):
        self.commit("b", "feat!: everything")
        out = self.collect()
        self.assertIsNone(out["last_tag"])
        self.assertEqual(out["suggested_version"], "0.1.0")
        self.assertTrue(any("first release" in n for n in out["notes"]))

    def test_untagged_release_files_are_the_base(self):
        self.write_release({"version": "2.3.0", "date": "2026-01-01", "entries": []})
        self.commit("b", "feat: more")
        out = self.collect()
        self.assertEqual(out["suggested_version"], "2.4.0")


class ShallowCloneTest(RepoCase):
    def test_shallow_clone_without_tags_explains_fetch_depth(self):
        for f in "bcd":
            self.commit(f, "fix: " + f)
        clone = os.path.join(self.d, "clone")
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + self.d, clone], check=True)
        with open(os.path.join(self.d, ".shiplog.json")) as src, open(os.path.join(clone, ".shiplog.json"), "w") as dst:
            dst.write(src.read())
        r = run("collect_changes.py", cwd=clone)
        self.assertEqual(r.returncode, 2)
        self.assertIn("fetch-depth: 0", r.stderr)


if __name__ == "__main__":
    unittest.main()
