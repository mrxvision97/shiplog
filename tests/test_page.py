"""Page output: archive pages, meta tags, i18n, per-audience feeds, accessibility."""
import os
import re
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from helpers import RepoCase, entry, run

ATOM = "{http://www.w3.org/2005/Atom}"


class A11yParser(HTMLParser):
    """Collects what the structural accessibility checks need."""

    def __init__(self):
        super().__init__()
        self.lang = None
        self.headings, self.ids, self.imgs_without_alt, self.inputs, self.labels_for = [], [], 0, [], set()
        self.label_depth = 0
        self.wrapped_inputs = set()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        if re.match(r"^h[1-6]$", tag):
            self.headings.append(int(tag[1]))
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "img" and not a.get("alt"):
            self.imgs_without_alt += 1
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.labels_for.add(a["for"])
        if tag in ("input", "select", "textarea"):
            self.inputs.append(a.get("id"))
            if self.label_depth:
                self.wrapped_inputs.add(len(self.inputs) - 1)
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1


def check_a11y(test, page_html):
    p = A11yParser()
    p.feed(page_html)
    test.assertTrue(p.lang, "html needs lang")
    test.assertEqual(p.headings.count(1), 1, "exactly one h1")
    for prev, cur in zip(p.headings, p.headings[1:]):
        test.assertLessEqual(cur, prev + 1, "heading level skipped: h%d -> h%d" % (prev, cur))
    test.assertEqual(len(p.ids), len(set(p.ids)), "duplicate ids")
    test.assertEqual(p.imgs_without_alt, 0, "images need alt text")
    for i, iid in enumerate(p.inputs):
        test.assertTrue(i in p.wrapped_inputs or iid in p.labels_for, "form control %s has no label" % iid)
    test.assertIn("#main", p.hrefs)
    test.assertIn("main", p.ids)


def release(v, date, **kw):
    return dict({"version": v, "date": date, "entries": [
        entry(title="Admin change in %s" % v),
        entry(type="fixed", title="Fix for everyone in %s" % v, audiences=["everyone"]),
        entry(type="changed", title="User change in %s" % v, audiences=["end-users"],
              action_required=True, action="Update the mobile app.", action_deadline="2027-01-31")]}, **kw)


class PageTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.config(base_url="https://acme.test/changelog", page_size=3,
                    theme={"accent_color": "#4f46e5", "logo_url": "https://acme.test/logo.png"})
        versions = [("1.%d.0" % i, "20%d-0%d-15" % (24 + i // 3, 1 + i % 3)) for i in range(7)]
        for v, d in versions:
            self.write_release(release(v, d))
        r = run("render.py", "--internal", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.out = os.path.join(self.d, "changelog", "demo")

    def read(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            return f.read()

    def test_archive_pages(self):
        files = sorted(os.listdir(self.out))
        self.assertIn("2025.html", files)
        self.assertIn("2024.html", files)
        index = self.read("index.html")
        self.assertEqual(index.count('<article class="release"'), 3)
        self.assertIn("1.6.0", index)
        self.assertNotIn(">1.2.0<", index)
        y2024 = self.read("2024.html")
        self.assertIn(">1.2.0<", y2024)
        self.assertIn('<a href="2024.html" aria-current="page">2024</a>', y2024)
        self.assertIn('<a href="index.html">Latest</a>', y2024)
        self.assertEqual(self.read("internal.html").count('<article class="release"'), 7)
        with open(os.path.join(self.d, "CHANGELOG.md")) as f:
            md = f.read()
        self.assertIn("[1.0.0]: https://acme.test/changelog/2024.html#v1-0-0", md)
        self.assertIn("[1.6.0]: https://acme.test/changelog/#v1-6-0", md)

    def test_stale_archive_pages_removed(self):
        self.config(base_url="https://acme.test/changelog", page_size=0)
        run("render.py", cwd=self.d)
        self.assertNotIn("2024.html", os.listdir(self.out))

    def test_meta_tags(self):
        index = self.read("index.html")
        self.assertIn('<link rel="canonical" href="https://acme.test/changelog/">', index)
        self.assertIn('<meta property="og:title" content="Demo changelog">', index)
        self.assertIn('<meta property="og:image" content="https://acme.test/logo.png">', index)
        self.assertIn('<meta property="og:url" content="https://acme.test/changelog/2024.html">', self.read("2024.html"))
        internal = self.read("internal.html")
        self.assertIn("noindex", internal)
        self.assertNotIn("og:title", internal)

    def test_audience_feeds(self):
        admins = ET.fromstring(self.read("feed-admins.xml"))
        text = ET.tostring(admins, encoding="unicode")
        self.assertIn("Admin change in 1.6.0", text)
        self.assertIn("Fix for everyone in 1.6.0", text)
        self.assertNotIn("User change", text)
        self.assertIn("(Account admins)", admins.find(ATOM + "title").text)
        self.assertEqual(admins.find(ATOM + "id").text, "https://acme.test/changelog/feed-admins.xml")
        links = [e.find(ATOM + "link").get("href") for e in admins.findall(ATOM + "entry")]
        self.assertIn("https://acme.test/changelog/2024.html#v1-0-0", links)
        support = ET.fromstring(self.read("feed-support.xml"))
        self.assertEqual(len(support.findall(ATOM + "entry")), 7)  # "everyone" entries reach all
        index = self.read("index.html")
        self.assertIn('href="feed-admins.xml">Account admins</a>', index)
        self.assertIn('type="application/atom+xml" title="Demo changelog (Account admins)" href="feed-admins.xml"', index)

    def test_translated_strings(self):
        self.config(lang="de", strings={
            "title": "{name} Änderungsprotokoll", "heading": "Änderungsprotokoll", "whos_affected": "Betrifft:", "skip_link": "Zum Inhalt",
            "showing_all": "Alle {n} Änderungen.", "types": {"fixed": "Behoben"},
            "months": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
                       "September", "Oktober", "November", "Dezember"], "date_format": "{day}. {month} {year}"})
        run("render.py", cwd=self.d)
        index = self.read("index.html")
        self.assertIn('<html lang="de">', index)
        self.assertIn("<title>Demo Änderungsprotokoll</title>", index)
        self.assertIn("<h1>Änderungsprotokoll</h1>", index)
        self.assertIn("Zum Inhalt", index)
        self.assertIn("Betrifft:", index)
        self.assertIn(">Behoben</h3>", index)
        self.assertIn('data-all="Alle {n} Änderungen."', index)
        self.assertRegex(index, r"15\. (Januar|Februar|März) 2026")
        self.assertIn(">Improvements</h3>", index)  # untranslated keys fall back to English

    def test_template_placeholders_in_content_are_not_expanded(self):
        self.write_release(release("1.9.0", "2026-09-01", summary="Literal {{lang}} and {{releases}}"))
        run("render.py", cwd=self.d)
        self.assertIn("Literal {{lang}} and {{releases}}", self.read("index.html"))

    def test_structural_accessibility(self):
        for name in ("index.html", "2024.html", "internal.html"):
            with self.subTest(page=name):
                check_a11y(self, self.read(name))


@unittest.skipUnless(os.environ.get("SHIPLOG_AXE"), "set SHIPLOG_AXE=1 (needs Playwright + axe-core, dev only)")
class AxeTest(RepoCase):
    """Optional: runs axe-core in a real browser. Needs `pip install playwright`,
    `playwright install chromium`, and axe.min.js (SHIPLOG_AXE_JS or npx cache)."""

    def test_axe_finds_no_violations(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")
        axe_js = os.environ.get("SHIPLOG_AXE_JS") or os.path.join(os.getcwd(), "node_modules", "axe-core", "axe.min.js")
        if not os.path.exists(axe_js):
            self.skipTest("axe.min.js not found; set SHIPLOG_AXE_JS")
        self.write_release(release("1.1.0", "2026-09-01"))
        run("render.py", "--internal", cwd=self.d)
        out = os.path.join(self.d, "changelog", "demo")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scheme in ("light", "dark"):
                for name in ("index.html", "internal.html"):
                    page = browser.new_page(color_scheme=scheme)
                    page.goto("file://" + os.path.join(out, name))
                    page.add_script_tag(path=axe_js)
                    result = page.evaluate("axe.run(document, {runOnly: ['wcag2a', 'wcag2aa']})")
                    self.assertEqual([v["id"] for v in result["violations"]], [], "%s (%s)" % (name, scheme))
            browser.close()


if __name__ == "__main__":
    unittest.main()


class LayoutTest(RepoCase):
    """The production layout: headline, action box, highlights, then compact lists."""

    def render(self, rel):
        self.write_release(rel)
        r = run("render.py", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.d, "changelog", "demo", "index.html"), encoding="utf-8") as f:
            return f.read()

    def test_structure(self):
        page = self.render({
            "version": "2.0.0", "date": "2026-09-28", "title": "Bulk export and faster search",
            "summary": "Export whole reports at once.",
            "image": {"url": "https://x.test/hero.png", "alt": "The new export dialog"},
            "entries": [
                entry(type="fixed", title="Fixed duplicate emails", audiences=["everyone"]),
                entry(type="changed", title="Keys expire", audiences=["developers"], breaking=True,
                      action_required=True, action="Create a new key in Settings.", action_deadline="2027-03-31"),
                entry(title="Bulk export", links=[{"label": "Read the guide", "url": "https://x.test/g"}]),
                entry(title="Small new thing", highlight=False),
            ]})
        self.assertIn('<a href="#v2-0-0">Bulk export and faster search</a></h2>', page)
        self.assertIn('<p class="intro">Export whole reports at once.</p>', page)
        self.assertIn('<img src="https://x.test/hero.png" alt="The new export dialog"', page)
        body = page[page.index('<main id="main">'):]
        # Action box first, then highlights (new features), then sections in order.
        order = [body.index(x) for x in ('class="callout"', 'class="entry highlight"', ">Improvements</h3>",
                                         ">Fixes</h3>")]
        self.assertEqual(order, sorted(order))
        self.assertIn("Deadline: <time", body)
        self.assertIn('Read the guide <span aria-hidden="true">→</span>', body)
        # Audience labels only for targeted changes, never "Everyone".
        self.assertIn('<span class="tag">API &amp; integration developers</span>', body)
        self.assertNotIn('<span class="tag">Everyone</span>', body)
        check_a11y(self, page)

    def test_explicit_highlight_wins(self):
        page = self.render({"version": "2.0.0", "date": "2026-09-28", "entries": [
            entry(title="New A"), entry(title="New B"),
            entry(type="changed", title="Big change", highlight=True)]})
        self.assertIn('<h3 id="v2-0-0-h1">Big change</h3>', page)
        self.assertNotIn(">New A</h3>", page)
        self.assertIn("<strong>New A</strong>", page)
        self.assertIn('<a href="#v2-0-0">2.0.0</a></h2>', page)  # no title or summary: the version

    def test_subscribe_button(self):
        page = self.render({"version": "2.0.0", "date": "2026-09-28", "entries": [entry()]})
        self.assertIn('<a class="btn" href="feed.xml"><svg', page)  # default: the RSS feed
        self.assertNotIn('class="plain" href="feed.xml"', page)

        self.config(subscribe_url="https://buttondown.com/acme")
        page = self.render({"version": "2.0.0", "date": "2026-09-28", "entries": [entry()]})
        self.assertIn('<a class="btn" href="https://buttondown.com/acme">', page)
        self.assertIn('<a class="plain" href="feed.xml">Atom/RSS feed</a>', page)

        self.config(subscribe_url="javascript:alert(1)")
        self.write_release({"version": "2.0.0", "date": "2026-09-28", "entries": [entry()]})
        r = run("render.py", cwd=self.d)
        self.assertIn("subscribe_url must start with", r.stderr)
        with open(os.path.join(self.d, "changelog", "demo", "index.html")) as f:
            page = f.read()
        self.assertNotIn("javascript:", page)
        self.assertIn('<a class="btn" href="feed.xml">', page)

    def test_image_needs_alt_text(self):
        self.write_release({"version": "2.0.0", "date": "2026-09-28", "title": "X",
                            "image": {"url": "https://x.test/a.png"}, "entries": [entry()]})
        r = run("validate.py", cwd=self.d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("image needs 'alt' text", r.stdout)
