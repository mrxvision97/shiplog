#!/usr/bin/env python3
"""Render Shiplog release files into CHANGELOG.md, an accessible HTML page,
Atom feeds and a JSON feed.

Usage:
  render.py [--app ID | --all] [--internal] [--root DIR] [--skip-validate]

Outputs go to the app's output_dir: index.html (the latest page_size releases),
<year>.html archive pages for older ones, feed.xml, feed-<audience>.xml,
changelog.json, and internal.html with --internal. CHANGELOG.md goes to
<app path>/CHANGELOG.md unless changelog_md is false or a string path.
"""
import argparse
import datetime
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import (ENTRY_TYPES, TYPE_LABELS, audience_label, find_root, is_generated,  # noqa: E402
                     load_config, load_releases, select_app, ui_strings)
import validate  # noqa: E402

PROJECT_URL = "https://github.com/mrxvision97/shiplog"  # footer link; override with project_url
TEMPLATE_CANDIDATES = [
    os.path.join(HERE, "..", "assets", "templates", "page.html"),  # inside the skill
    os.path.join(HERE, "page.html"),  # vendored copy in .shiplog/scripts/
]
PUBLIC_ENTRY_KEYS = ["type", "title", "description", "audiences", "action_required", "action",
                     "action_deadline", "breaking", "links"]
DEFAULT_PAGE_SIZE = 20
FEED_MAX = 50
SAFE_URL_RE = re.compile(r"^https?://", re.I)
URL_RE = re.compile(r"(https?://[^\s<>\"']+[^\s<>\"'.,;:!?)])")


def esc(s):
    return html.escape(str(s or ""), quote=True)


def slug(v):
    return "v" + re.sub(r"[^0-9A-Za-z]+", "-", v).strip("-")


def text_to_html(text):
    """Plain text -> paragraphs; bare URLs become links. Everything else escaped."""
    out = []
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        if not para.strip():
            continue
        safe = esc(para)
        safe = URL_RE.sub(lambda m: '<a href="%s">%s</a>' % (m.group(1), m.group(1)), safe)
        out.append("<p>%s</p>" % safe.replace("\n", "<br>"))
    return "\n".join(out)


def fmt_date(d, app=None):
    s = ui_strings(app or {})
    try:
        dt = datetime.date.fromisoformat(d)
    except (TypeError, ValueError):
        return esc(d)
    return esc(s["date_format"].format(month=s["months"][dt.month - 1], day=dt.day, year=dt.year))


def relative_luminance(hex_color):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def ch(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def load_template():
    for p in TEMPLATE_CANDIDATES:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
    sys.exit("shiplog: page template not found (looked in %s)" % ", ".join(TEMPLATE_CANDIDATES))


# Pages -------------------------------------------------------------------

def paginate(app, releases):
    """[(filename, label, releases)]: the newest page_size releases on index.html,
    older ones on one page per year. page_size 0 puts everything on index.html."""
    size = app.get("page_size", DEFAULT_PAGE_SIZE)
    if not size or len(releases) <= size:
        return [("index.html", None, releases)]
    pages = [("index.html", None, releases[:size])]
    by_year = {}
    for r in releases[size:]:
        year = str(r.get("date") or "")[:4]
        by_year.setdefault(year if year.isdigit() else "undated", []).append(r)
    for year in sorted(by_year, reverse=True):
        pages.append(("%s.html" % year, year, by_year[year]))
    return pages


def page_of(app, releases):
    """version -> the page file it's rendered on."""
    return {r["version"]: name for name, _, rs in paginate(app, releases) for r in rs}


def release_url(app, releases, version, pages=None):
    """Absolute (or relative, without base_url) link to a release's anchor."""
    base = app.get("base_url", "").rstrip("/")
    page = (pages or page_of(app, releases)).get(version, "index.html")
    return "%s/%s#%s" % (base, "" if page == "index.html" else page, slug(version))


def audience_feeds(app):
    return [(a["id"], "feed-%s.xml" % a["id"], a.get("label", a["id"])) for a in app.get("audiences", [])]


# HTML --------------------------------------------------------------------

def render_entry(e, app, internal):
    s = ui_strings(app)
    auds = e.get("audiences", [])
    badges = []
    if e.get("breaking"):
        badges.append('<span class="badge breaking">%s</span>' % esc(s["breaking"]))
    if e.get("action_required"):
        badges.append('<span class="badge action">%s</span>' % esc(s["action_required"]))
    badge_html = '<span class="badges">%s</span>' % "".join(badges) if badges else ""
    parts = [
        '<li class="entry" data-type="%s" data-audiences="%s" data-action="%s">'
        % (esc(e.get("type")), esc(" ".join(auds)), "true" if e.get("action_required") else "false"),
        "<h4>%s %s</h4>" % (esc(e.get("title")), badge_html),
        text_to_html(e.get("description")),
        '<p class="meta"><span>%s</span> %s</p>'
        % (esc(s["whos_affected"]), esc(", ".join(audience_label(app, a) for a in auds))),
    ]
    if e.get("action_required"):
        dl = ""
        if e.get("action_deadline"):
            dl = ' <span>%s <time datetime="%s">%s</time>.</span>' % (
                esc(s["deadline"]), esc(e["action_deadline"]), fmt_date(e["action_deadline"], app))
        parts.append('<div class="action-box"><strong>%s</strong>%s%s</div>'
                     % (esc(s["what_to_do"]), text_to_html(e.get("action")), dl))
    links = [ln for ln in e.get("links") or [] if isinstance(ln, dict) and SAFE_URL_RE.match(str(ln.get("url", "")))]
    if links:
        parts.append('<p class="links">%s</p>' % " ".join(
            '<a href="%s">%s</a>' % (esc(ln["url"]), esc(ln["label"])) for ln in links))
    if internal and (e.get("internal_notes") or e.get("refs")):
        inner = text_to_html(e.get("internal_notes", ""))
        if e.get("refs"):
            inner += "<p>%s %s</p>" % (esc(s["refs"]), esc(", ".join(e["refs"])))
        parts.append('<details class="internal"><summary>%s</summary>%s</details>'
                     % (esc(s["internal_notes"]), inner))
    parts.append("</li>")
    return "\n".join(parts)


def render_release(r, app, internal):
    s = ui_strings(app)
    v = r["version"]
    sid = slug(v)
    head = ('<header><h2 id="%s"><a href="#%s">%s</a> <time datetime="%s">%s</time>%s</h2>'
            % (sid, sid, esc(v), esc(r.get("date")), fmt_date(r.get("date"), app),
               ' <span class="yanked">%s</span>' % esc(s["withdrawn"]) if r.get("yanked") else ""))
    if r.get("summary"):
        head += '<p class="summary">%s</p>' % esc(r["summary"])
    head += "</header>"
    groups = []
    for t in ENTRY_TYPES:
        items = [e for e in r.get("entries", []) if e.get("type") == t]
        if not items:
            continue
        gid = "%s-%s" % (sid, t)
        groups.append('<section class="group" aria-labelledby="%s"><h3 id="%s">%s</h3>'
                      '<ul class="entries">%s</ul></section>'
                      % (gid, gid, esc(s["types"][t]), "\n".join(render_entry(e, app, internal) for e in items)))
    return '<article class="release" aria-labelledby="%s">%s%s</article>' % (sid, head, "\n".join(groups))


def archive_nav(app, pages, current):
    if len(pages) < 2:
        return ""
    s = ui_strings(app)
    items = []
    for name, label, _ in pages:
        text = esc(label or s["latest"])
        cur = ' aria-current="page"' if name == current else ""
        items.append('<li><a href="%s"%s>%s</a></li>' % (name, cur, text))
    return ('<nav class="archive" aria-labelledby="archive-heading"><h2 id="archive-heading">%s</h2>'
            '<ul>%s</ul></nav>' % (esc(s["archive"]), "".join(items)))


def meta_tags(app, title, description, page, internal):
    if internal:
        return '<meta name="robots" content="noindex, nofollow">'
    base = app.get("base_url", "").rstrip("/")
    theme = app.get("theme") or {}
    url = "%s/%s" % (base, "" if page == "index.html" else page) if base else ""
    tags = ['<meta property="og:type" content="website">',
            '<meta property="og:site_name" content="%s">' % esc(app["name"]),
            '<meta property="og:title" content="%s">' % title,
            '<meta property="og:description" content="%s">' % description,
            '<meta name="twitter:card" content="summary">']
    if url:
        tags += ['<link rel="canonical" href="%s">' % esc(url), '<meta property="og:url" content="%s">' % esc(url)]
    image = theme.get("og_image") or theme.get("logo_url")
    if image:
        tags.append('<meta property="og:image" content="%s">' % esc(image))
    return "\n".join(tags)


def render_html(app, releases, internal, page="index.html", pages=None):
    """One HTML page. Public pages show their slice of releases; internal shows all."""
    s = ui_strings(app)
    pages = pages or [("index.html", None, releases)]
    shown = releases if internal else next((rs for name, _, rs in pages if name == page), releases)
    label = None if internal else next((lb for name, lb, _ in pages if name == page), None)
    theme = app.get("theme") or {}
    accent = theme.get("accent_color", "#4f46e5")
    if not re.match(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", accent):
        print("shiplog: theme.accent_color must be a hex color; using default", file=sys.stderr)
        accent = "#4f46e5"
    accent_fg = "#ffffff" if contrast(accent, "#ffffff") >= contrast(accent, "#000000") else "#000000"
    if contrast(accent, "#ffffff") < 3 and contrast(accent, "#111114") < 3 and page == "index.html":
        print("shiplog: warning: accent color %s has low contrast in both themes" % accent, file=sys.stderr)
    name = app["name"]
    logo = ('<img src="%s" alt="%s">' % (esc(theme["logo_url"]), esc(s["logo_alt"].format(name=name)))
            if theme.get("logo_url") else "")
    used_types = [t for t in ENTRY_TYPES if any(e.get("type") == t for r in shown for e in r.get("entries", []))]
    type_filters = "".join('<label><input type="checkbox" name="type" value="%s" checked> %s</label>'
                           % (t, esc(s["types"][t])) for t in used_types)
    audience_options = "".join('<option value="%s">%s</option>' % (esc(a["id"]), esc(a.get("label", a["id"])))
                               for a in app.get("audiences", []))
    feeds = audience_feeds(app)
    feed_links = "".join('<link rel="alternate" type="application/atom+xml" title="%s (%s)" href="%s">\n'
                         % (esc(s["title"].format(name=name)), esc(lbl), fname) for _, fname, lbl in feeds)
    feed_list = (" · %s %s" % (esc(s["audience_feeds"]), ", ".join(
        '<a href="%s">%s</a>' % (fname, esc(lbl)) for _, fname, lbl in feeds))) if feeds else ""
    body = "\n".join(render_release(r, app, internal) for r in shown) or "<p>%s</p>" % esc(s["no_releases"])
    title = s["title"].format(name=name) + (s["internal_suffix"] if internal else "")
    page_title = title + (" – %s" % label if label else "")
    description = app.get("description") or s["intro"].format(name=name)
    updated = ""
    if releases:
        updated = esc(s["last_release"]).replace("{date}", '<time datetime="%s">%s</time>' % (
            esc(releases[0].get("date")), fmt_date(releases[0].get("date"), app))) + " "
    project_url = app.get("project_url", PROJECT_URL)
    repl = {
        "lang": esc(app.get("lang", "en")),
        "page_title": esc(page_title),
        "heading": esc(page_title),
        "meta_description": esc(description),
        "meta_tags": meta_tags(app, esc(page_title), esc(description), page, internal),
        "feed_links": feed_links,
        "intro": esc(description),
        "app_name": esc(name),
        "accent": accent,
        "accent_fg": accent_fg,
        "logo": logo,
        "internal_banner": ('<p class="banner" role="note"><strong>%s</strong></p>' % esc(s["internal_banner"])
                            if internal else ""),
        "type_filters": type_filters,
        "audience_options": audience_options,
        "audience_feed_list": feed_list,
        "releases": body,
        "archive_nav": "" if internal else archive_nav(app, pages, page),
        # The latest release date, never today's: re-rendering unchanged data is byte-identical.
        "updated": updated,
        "published_with": esc(s["published_with"]).replace(
            "{link}", '<a href="%s">Shiplog</a>' % esc(project_url)),
    }
    for k, v in s.items():
        if isinstance(v, str):
            repl["s." + k] = esc(v.replace("{name}", name))
    # One pass over the template, so "{{...}}" inside release text is never expanded.
    return re.sub(r"\{\{([\w.]+)\}\}", lambda m: repl.get(m.group(1), m.group(0)), load_template())


# Markdown, feeds, JSON -----------------------------------------------------

def md_escape(s):
    return str(s or "").replace("\r", "").strip()


def render_markdown(app, releases):
    lines = ["# Changelog", "",
             "All notable changes to %s are documented here." % app["name"],
             "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),",
             "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).",
             "",
             "<!-- Generated by Shiplog from %s. Do not edit by hand. -->" % app["releases_dir"], ""]
    for r in releases:
        yank = " [YANKED]" if r.get("yanked") else ""
        lines.append("## [%s] - %s%s" % (r["version"], r.get("date", ""), yank))
        lines.append("")
        if r.get("summary"):
            lines += [md_escape(r["summary"]), ""]
        for t in ENTRY_TYPES:
            items = [e for e in r.get("entries", []) if e.get("type") == t]
            if not items:
                continue
            lines += ["### " + TYPE_LABELS[t], ""]
            for e in items:
                flags = []
                if e.get("breaking"):
                    flags.append("**Breaking.**")
                desc = " ".join(md_escape(e.get("description")).split())
                lines.append("- **%s** — %s%s" % (md_escape(e.get("title")),
                                                 (" ".join(flags) + " ") if flags else "", desc))
                lines.append("  - Affects: %s" % ", ".join(audience_label(app, a) for a in e.get("audiences", [])))
                if e.get("action_required"):
                    act = " ".join(md_escape(e.get("action")).split())
                    if e.get("action_deadline"):
                        act += " (by %s)" % e["action_deadline"]
                    lines.append("  - **Action required:** %s" % act)
                for ln in e.get("links") or []:
                    lines.append("  - [%s](%s)" % (md_escape(ln["label"]), ln["url"]))
            lines.append("")
    if app.get("base_url"):
        pages = page_of(app, releases)
        for r in releases:
            lines.append("[%s]: %s" % (r["version"], release_url(app, releases, r["version"], pages)))
    return "\n".join(lines).rstrip() + "\n"


def relevant(entry, audience):
    return audience is None or audience in entry.get("audiences", []) or "everyone" in entry.get("audiences", [])


def render_atom(app, releases, audience=None):
    """Atom feed of the newest releases; with AUDIENCE, only entries for that audience."""
    s = ui_strings(app)
    base = app.get("base_url", "").rstrip("/")
    fname = "feed.xml" if audience is None else "feed-%s.xml" % audience
    feed_id = base + "/" + ("" if audience is None else fname) if base else "urn:shiplog:%s%s" % (
        app["id"], "" if audience is None else ":" + audience)
    title = s["title"].format(name=app["name"])
    if audience:
        title += " (%s)" % audience_label(app, audience)
    items = []
    for r in releases:
        entries = [e for e in r.get("entries", []) if relevant(e, audience)]
        if entries:
            items.append((r, entries))
    items = items[:FEED_MAX]
    updated = (items[0][0]["date"] if items else "1970-01-01") + "T00:00:00Z"
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<feed xmlns="http://www.w3.org/2005/Atom">',
           "<title>%s</title>" % esc(title),
           "<id>%s</id>" % esc(feed_id),
           "<updated>%s</updated>" % updated]
    if base:
        out.append('<link rel="alternate" type="text/html" href="%s/"/>' % esc(base))
        out.append('<link rel="self" type="application/atom+xml" href="%s/%s"/>' % (esc(base), fname))
    pages = page_of(app, releases)
    for r, entries in items:
        link = release_url(app, releases, r["version"], pages) if base else ""
        entry_title = r["version"] + (" – " + r["summary"] if r.get("summary") else "")
        content = []
        for t in ENTRY_TYPES:
            group = [e for e in entries if e.get("type") == t]
            if not group:
                continue
            content.append("<h3>%s</h3><ul>" % esc(s["types"][t]))
            for e in group:
                extra = ""
                if e.get("action_required"):
                    extra = "<p><strong>%s:</strong> %s</p>" % (esc(s["action_required"]), esc(e.get("action")))
                content.append("<li><strong>%s</strong> %s<p>%s %s</p>%s</li>" % (
                    esc(e.get("title")), text_to_html(e.get("description")), esc(s["whos_affected"]),
                    esc(", ".join(audience_label(app, a) for a in e.get("audiences", []))), extra))
            content.append("</ul>")
        out += ["<entry>",
                "<title>%s</title>" % esc(entry_title),
                "<id>%s</id>" % esc(link or "%s:%s" % (feed_id, r["version"])),
                "<updated>%sT00:00:00Z</updated>" % esc(r.get("date")),
                ('<link rel="alternate" type="text/html" href="%s"/>' % esc(link)) if link else "",
                '<content type="html">%s</content>' % esc("".join(content)),
                "</entry>"]
    out.append("</feed>")
    return "\n".join(x for x in out if x) + "\n"


def render_json(app, releases, internal):
    data = {"app": {"id": app["id"], "name": app["name"], "url": app.get("base_url") or None},
            "audiences": app.get("audiences", []),
            "releases": []}
    for r in releases:
        rel = {k: r[k] for k in ("version", "date", "summary", "yanked") if k in r}
        entries = []
        for e in r.get("entries", []):
            keys = PUBLIC_ENTRY_KEYS + (["internal_notes", "refs"] if internal else [])
            entries.append({k: e[k] for k in keys if k in e})
        rel["entries"] = entries
        data["releases"].append(rel)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def changelog_conflict(path, releases):
    """Why an existing hand-written CHANGELOG.md must not be replaced, or None.
    It's safe once every version in it has a release file and nothing is unreleased."""
    if not os.path.exists(path) or is_generated(path):
        return None
    import import_changelog
    with open(path, encoding="utf-8") as f:
        text = f.read()
    have = {r.get("version") for r in releases}
    missing = [r["version"] for r in import_changelog.parse_changelog(text) if r["version"] not in have]
    unreleased = re.search(r"^##\s+\[?unreleased\]?.*?$(.*?)(?=^##\s|\Z)", text, re.I | re.M | re.S)
    if missing:
        return ("it's hand-written and has versions without release files (%s). Run `shiplog.py import` "
                "first, or set changelog_md to another path or false." % ", ".join(missing[:5]))
    if unreleased and re.search(r"^\s*[-*+]\s+\S", unreleased.group(1), re.M):
        return "its Unreleased section has notes that would be lost. Move them into a release file first."
    return None


def write(path, content):
    path = os.path.normpath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return path


def render_app(app, root, internal, quiet=False):
    """Write every output for APP. Returns the list of paths written."""
    releases, errors = load_releases(app, root)
    if errors:
        for p, m in errors:
            print("shiplog: %s: %s" % (p, m), file=sys.stderr)
        sys.exit(1)
    out_dir = os.path.join(root, app["output_dir"])
    pages = paginate(app, releases)
    files = {}
    for name, _, _ in pages:
        files[name] = render_html(app, releases, internal=False, page=name, pages=pages)
    files["feed.xml"] = render_atom(app, releases)
    for aid, fname, _ in audience_feeds(app):
        files[fname] = render_atom(app, releases, audience=aid)
    files["changelog.json"] = render_json(app, releases, internal=False)
    if internal:
        files["internal.html"] = render_html(app, releases, internal=True)
        files["changelog.internal.json"] = render_json(app, releases, internal=True)
    written = [write(os.path.join(out_dir, name), content) for name, content in files.items()]
    # Remove archive pages and audience feeds left over from an earlier layout.
    if os.path.isdir(out_dir):
        for name in os.listdir(out_dir):
            if name not in files and re.match(r"^((\d{4}|undated)\.html|feed-[\w-]+\.xml)$", name):
                os.remove(os.path.join(out_dir, name))
    md = app.get("changelog_md", True)
    if md:
        md_path = os.path.join(root, md if isinstance(md, str) else os.path.join(app.get("path", "."), "CHANGELOG.md"))
        problem = changelog_conflict(md_path, releases)
        if problem:
            print("shiplog: not writing %s: %s" % (os.path.normpath(md_path), problem), file=sys.stderr)
        else:
            written.append(write(md_path, render_markdown(app, releases)))
    if not quiet:
        print("== %s ==" % app["name"])
        for p in written:
            print("  wrote %s" % p)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--internal", action="store_true", help="also write internal.html with internal notes")
    ap.add_argument("--skip-validate", action="store_true")
    ap.add_argument("--root", help="repo root (default: found from the current folder)")
    args = ap.parse_args(argv)
    args.root = find_root(args.root)
    cfg = load_config(args.root)
    apps = cfg["apps"] if args.all else [select_app(cfg, args.app)]
    if not args.skip_validate:
        if sum(validate.validate_app(a, args.root, None, False) for a in apps):
            sys.exit("shiplog: validation failed; fix errors before rendering (or --skip-validate)")
    for app in apps:
        render_app(app, args.root, args.internal)


if __name__ == "__main__":
    main()
