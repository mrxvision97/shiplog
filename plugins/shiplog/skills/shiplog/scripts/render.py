#!/usr/bin/env python3
"""Render Shiplog release files into CHANGELOG.md, an accessible HTML page,
an Atom feed and a JSON feed.

Usage:
  render.py [--app ID | --all] [--internal] [--root DIR] [--skip-validate]

Outputs go to the app's output_dir (index.html, feed.xml, changelog.json, and
internal.html with --internal). CHANGELOG.md goes to <app path>/CHANGELOG.md
unless changelog_md is false or a string path.
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
from _common import (ENTRY_TYPES, TYPE_LABELS, audience_label, load_config,  # noqa: E402
                     load_releases, select_app)
import validate  # noqa: E402

PROJECT_URL = "https://github.com/YOUR_ORG/shiplog"  # set to your fork's URL
TEMPLATE_CANDIDATES = [
    os.path.join(HERE, "..", "assets", "templates", "page.html"),  # inside the skill
    os.path.join(HERE, "page.html"),  # vendored copy in .shiplog/scripts/
]
PUBLIC_ENTRY_KEYS = ["type", "title", "description", "audiences", "action_required", "action",
                     "action_deadline", "breaking", "links"]
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


def fmt_date(d):
    try:
        dt = datetime.date.fromisoformat(d)
        return dt.strftime("%B %d, %Y").replace(" 0", " ")
    except (TypeError, ValueError):
        return esc(d)


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


def render_entry(e, app, internal):
    auds = e.get("audiences", [])
    badges = []
    if e.get("breaking"):
        badges.append('<span class="badge breaking">Breaking change</span>')
    if e.get("action_required"):
        badges.append('<span class="badge action">Action required</span>')
    badge_html = '<span class="badges">%s</span>' % "".join(badges) if badges else ""
    parts = [
        '<li class="entry" data-type="%s" data-audiences="%s" data-action="%s">'
        % (esc(e.get("type")), esc(" ".join(auds)), "true" if e.get("action_required") else "false"),
        "<h4>%s %s</h4>" % (esc(e.get("title")), badge_html),
        text_to_html(e.get("description")),
        '<p class="meta"><span>Who\'s affected:</span> %s</p>'
        % esc(", ".join(audience_label(app, a) for a in auds)),
    ]
    if e.get("action_required"):
        dl = ""
        if e.get("action_deadline"):
            dl = ' <span>Deadline: <time datetime="%s">%s</time>.</span>' % (
                esc(e["action_deadline"]), fmt_date(e["action_deadline"]))
        parts.append('<div class="action-box"><strong>What you need to do</strong>%s%s</div>'
                     % (text_to_html(e.get("action")), dl))
    links = e.get("links") or []
    links = [ln for ln in links if isinstance(ln, dict) and SAFE_URL_RE.match(str(ln.get("url", "")))]
    if links:
        parts.append('<p class="links">%s</p>' % " ".join(
            '<a href="%s">%s</a>' % (esc(ln["url"]), esc(ln["label"])) for ln in links))
    if internal and (e.get("internal_notes") or e.get("refs")):
        inner = text_to_html(e.get("internal_notes", ""))
        if e.get("refs"):
            inner += "<p>Refs: %s</p>" % esc(", ".join(e["refs"]))
        parts.append('<details class="internal"><summary>Internal notes</summary>%s</details>' % inner)
    parts.append("</li>")
    return "\n".join(parts)


def render_release(r, app, internal):
    v = r["version"]
    sid = slug(v)
    head = ('<header><h2 id="%s"><a href="#%s">%s</a> <time datetime="%s">%s</time>%s</h2>'
            % (sid, sid, esc(v), esc(r.get("date")), fmt_date(r.get("date")),
               ' <span class="yanked">(withdrawn)</span>' if r.get("yanked") else ""))
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
                      % (gid, gid, TYPE_LABELS[t], "\n".join(render_entry(e, app, internal) for e in items)))
    return '<article class="release" aria-labelledby="%s">%s%s</article>' % (sid, head, "\n".join(groups))


def render_html(app, releases, internal):
    theme = app.get("theme") or {}
    accent = theme.get("accent_color", "#4f46e5")
    if not re.match(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", accent):
        print("shiplog: theme.accent_color must be a hex color; using default", file=sys.stderr)
        accent = "#4f46e5"
    accent_fg = "#ffffff" if contrast(accent, "#ffffff") >= contrast(accent, "#000000") else "#000000"
    if contrast(accent, "#ffffff") < 3 and contrast(accent, "#111114") < 3:
        print("shiplog: warning: accent color %s has low contrast in both themes" % accent, file=sys.stderr)
    logo = ('<img src="%s" alt="%s logo">' % (esc(theme["logo_url"]), esc(app["name"]))
            if theme.get("logo_url") else "")
    used_types = [t for t in ENTRY_TYPES if any(e.get("type") == t for r in releases for e in r.get("entries", []))]
    type_filters = "".join('<label><input type="checkbox" name="type" value="%s" checked> %s</label>'
                           % (t, TYPE_LABELS[t]) for t in used_types)
    audience_options = "".join('<option value="%s">%s</option>' % (esc(a["id"]), esc(a.get("label", a["id"])))
                               for a in app.get("audiences", []))
    body = "\n".join(render_release(r, app, internal) for r in releases) or "<p>No releases yet.</p>"
    title_suffix = " (internal)" if internal else ""
    repl = {
        "lang": esc(app.get("lang", "en")),
        "page_title": esc("%s changelog%s" % (app["name"], title_suffix)),
        "heading": esc("%s changelog%s" % (app["name"], title_suffix)),
        "meta_description": esc(app.get("description") or "What's new in %s." % app["name"]),
        "intro": esc(app.get("description") or "New features, improvements and fixes in %s." % app["name"]),
        "app_name": esc(app["name"]),
        "accent": accent,
        "accent_fg": accent_fg,
        "logo": logo,
        "robots": '<meta name="robots" content="noindex, nofollow">' if internal else "",
        "internal_banner": ('<p class="banner" role="note"><strong>Internal view.</strong> Includes support '
                            'notes and references. Do not share publicly.</p>' if internal else ""),
        "type_filters": type_filters,
        "audience_options": audience_options,
        "releases": body,
        # The latest release date, never today's: re-rendering unchanged data is byte-identical.
        "updated": ('Last release <time datetime="%s">%s</time>. ' % (esc(releases[0].get("date")),
                    fmt_date(releases[0].get("date")))) if releases else "",
        "project_url": esc(app.get("project_url", PROJECT_URL)),
    }
    out = load_template()
    for k, v in repl.items():
        out = out.replace("{{%s}}" % k, v)
    return out


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
    base = app.get("base_url", "").rstrip("/")
    if base:
        for r in releases:
            lines.append("[%s]: %s/#%s" % (r["version"], base, slug(r["version"])))
    return "\n".join(lines).rstrip() + "\n"


def render_atom(app, releases):
    base = app.get("base_url", "").rstrip("/")
    feed_id = base + "/" if base else "urn:shiplog:%s" % app["id"]
    updated = (releases[0]["date"] if releases else "1970-01-01") + "T00:00:00Z"
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<feed xmlns="http://www.w3.org/2005/Atom">',
           "<title>%s changelog</title>" % esc(app["name"]),
           "<id>%s</id>" % esc(feed_id),
           "<updated>%s</updated>" % updated]
    if base:
        out.append('<link rel="alternate" type="text/html" href="%s/"/>' % esc(base))
        out.append('<link rel="self" type="application/atom+xml" href="%s/feed.xml"/>' % esc(base))
    for r in releases[:50]:
        sid = slug(r["version"])
        link = "%s/#%s" % (base, sid) if base else ""
        title = r["version"] + (" – " + r["summary"] if r.get("summary") else "")
        content = []
        for t in ENTRY_TYPES:
            items = [e for e in r.get("entries", []) if e.get("type") == t]
            if not items:
                continue
            content.append("<h3>%s</h3><ul>" % TYPE_LABELS[t])
            for e in items:
                extra = ""
                if e.get("action_required"):
                    extra = "<p><strong>Action required:</strong> %s</p>" % esc(e.get("action"))
                content.append("<li><strong>%s</strong> %s<p>Affects: %s</p>%s</li>" % (
                    esc(e.get("title")), text_to_html(e.get("description")),
                    esc(", ".join(audience_label(app, a) for a in e.get("audiences", []))), extra))
            content.append("</ul>")
        out += ["<entry>",
                "<title>%s</title>" % esc(title),
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


def write(path, content):
    path = os.path.normpath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("  wrote %s" % path)


def render_app(app, root, internal):
    releases, errors = load_releases(app, root)
    if errors:
        for p, m in errors:
            print("shiplog: %s: %s" % (p, m), file=sys.stderr)
        sys.exit(1)
    print("== %s ==" % app["name"])
    out_dir = os.path.join(root, app["output_dir"])
    write(os.path.join(out_dir, "index.html"), render_html(app, releases, internal=False))
    write(os.path.join(out_dir, "feed.xml"), render_atom(app, releases))
    write(os.path.join(out_dir, "changelog.json"), render_json(app, releases, internal=False))
    if internal:
        write(os.path.join(out_dir, "internal.html"), render_html(app, releases, internal=True))
        write(os.path.join(out_dir, "changelog.internal.json"), render_json(app, releases, internal=True))
    md = app.get("changelog_md", True)
    if md:
        md_path = md if isinstance(md, str) else os.path.join(app.get("path", "."), "CHANGELOG.md")
        write(os.path.join(root, md_path), render_markdown(app, releases))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--internal", action="store_true", help="also write internal.html with internal notes")
    ap.add_argument("--skip-validate", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    cfg = load_config(args.root)
    apps = cfg["apps"] if args.all else [select_app(cfg, args.app)]
    if not args.skip_validate:
        if sum(validate.validate_app(a, args.root, None, False) for a in apps):
            sys.exit("shiplog: validation failed; fix errors before rendering (or --skip-validate)")
    for app in apps:
        render_app(app, args.root, args.internal)


if __name__ == "__main__":
    main()
