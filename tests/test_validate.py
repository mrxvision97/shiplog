import datetime
import unittest

from helpers import entry

import validate

APP = {"id": "demo", "name": "Demo", "audiences": [{"id": "admins"}, {"id": "end-users"}]}


def warnings_for(text, field="description", app=APP):
    e = entry(**{field: text}) if field != "action" else entry(action_required=True, action=text)
    errs, warns = [], []
    validate.validate_entry(e, 0, app, errs, warns)
    return errs, warns


class JargonTest(unittest.TestCase):
    def test_rank_is_not_a_pr_ref(self):
        _, w = warnings_for("Reliability is our #1 priority, so exports now retry automatically.")
        self.assertFalse(any("PR/issue" in x for x in w), w)

    def test_real_pr_refs_still_flag(self):
        for text in ("Exports now retry automatically (#12) when they fail.",
                     "Exports now retry automatically, see PR #12 for more.",
                     "Exports now retry automatically. Tracked in #4521."):
            _, w = warnings_for(text)
            self.assertTrue(any("PR/issue" in x for x in w), text)

    def test_product_name_hotfix_is_fine(self):
        _, w = warnings_for("Our Hotfix Tracker app now syncs with your calendar every hour.")
        self.assertFalse(any("jargon" in x for x in w), w)

    def test_lowercase_hotfix_flags(self):
        _, w = warnings_for("We deployed a hotfix so exports finish again for everyone.")
        self.assertTrue(any("jargon" in x for x in w), w)

    def test_allowed_terms(self):
        app = dict(APP, allowed_terms=["hotfix"])
        _, w = warnings_for("We deployed a hotfix so exports finish again for everyone.", app=app)
        self.assertFalse(any("jargon" in x for x in w), w)

    def test_standards_are_not_ticket_ids(self):
        _, w = warnings_for("Exports now use UTF-8 and dates follow ISO-8601 everywhere.")
        self.assertFalse(any("ticket" in x for x in w), w)
        _, w = warnings_for("Exports now retry automatically, as requested in PROJ-12.")
        self.assertTrue(any("ticket" in x for x in w), w)

    def test_messages_name_the_entry(self):
        errs, _ = warnings_for("Too short")
        self.assertTrue(errs[0].startswith('"Export up to 50,000 rows at once": description'), errs)


class DeprecationTest(unittest.TestCase):
    def dep(self, **kw):
        errs, warns = [], []
        validate.validate_entry(entry(type="deprecated", action_deadline="2030-01-01", **kw), 0, APP, errs, warns)
        return warns

    def test_deprecation_without_replacement_warns(self):
        w = self.dep(description="The legacy CSV export will stop working next year.")
        self.assertTrue(any("replacement" in x for x in w), w)

    def test_deprecation_with_replacement_or_link_is_fine(self):
        w = self.dep(description="The legacy CSV export goes away next year. Use the new Export page instead.")
        self.assertFalse(any("replacement" in x for x in w), w)
        w = self.dep(description="The legacy CSV export will stop working next year.",
                     links=[{"label": "Guide", "url": "https://x.test/guide"}])
        self.assertFalse(any("replacement" in x for x in w), w)


class DeadlineTest(unittest.TestCase):
    def release(self, dl):
        return {"version": "1.0.0", "date": "2026-01-01",
                "entries": [entry(action_required=True, action="Update the app now.", action_deadline=dl)]}

    def test_past_deadline_warns_on_newest_release_only(self):
        today = datetime.date(2026, 9, 28)
        _, w = validate.validate_release(self.release("2026-03-01"), APP, newest=True, today=today)
        self.assertTrue(any("already passed" in x for x in w), w)
        _, w = validate.validate_release(self.release("2026-03-01"), APP, newest=False, today=today)
        self.assertFalse(any("already passed" in x for x in w), w)
        _, w = validate.validate_release(self.release("2026-12-01"), APP, newest=True, today=today)
        self.assertFalse(any("already passed" in x for x in w), w)


class NeedsReviewTest(unittest.TestCase):
    def test_needs_review_warns_and_relaxes_short_descriptions(self):
        errs, warns = [], []
        validate.validate_entry(entry(description="Fixed login", _needs_review=True), 0, APP, errs, warns)
        self.assertEqual(errs, [])
        self.assertTrue(any("needs review" in x for x in warns), warns)


if __name__ == "__main__":
    unittest.main()
