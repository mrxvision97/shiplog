#!/usr/bin/env python3
"""Convert a Keep a Changelog CHANGELOG.md into Shiplog release files.

Legacy entries don't say who is affected or whether anyone must act, so every
imported entry gets audiences ["everyone"], action_required false and
"_needs_review": true. The validator warns about each one until a person
confirms the impact and deletes the flag. Nothing is silently assumed.

Usage:
  import_changelog.py [--app ID] [--file CHANGELOG.md] [--force] [--dry-run] [--root DIR]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import RELEASE_SCHEMA_URL, die, find_root, load_config, parse_semver, select_app  # noqa: E402

VERSION_RE = re.compile(r"^##\s+\[?v?(?P<version>[0-9][^\]\s]*)\]?(?:\([^)]*\))?\s*"
                        r"(?:[-–—]\s*|\(\s*)?(?P<date>\d{4}-\d{2}-\d{2})?\)?\s*(?P<rest>.*)$")
SECTION_TYPES = {
    "added": "added", "new": "added", "features": "added", "new features": "added",
    "changed": "changed", "changes": "changed", "improved": "changed", "improvements": "changed",
    "updated": "changed", "breaking changes": "changed", "performance": "changed",
    "deprecated": "deprecated", "deprecations": "deprecated",
    "removed": "removed", "removals": "removed",
    "fixed": "fixed", "fixes": "fixed", "bug fixes": "fixed", "bugfixes": "fixed",
    "security": "security",
}
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
REF_RE = re.compile(r"\(?\[?#(\d+)\]?(?:\([^)]*\))?\)?")
TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


def clean_item(text):
    """Markdown bullet text -> (plain text, links, refs)."""
    links, refs = [], []
    for m in REF_RE.finditer(text):
        refs.append("#" + m.group(1))
    text = REF_RE.sub("", text)

    def link(m):
        if not re.match(r"^[0-9a-f]{7,40}$", m.group(1)):  # skip commit-hash links
            links.append({"label": m.group(1), "url": m.group(2)})
        return m.group(1)
    text = MD_LINK_RE.sub(link, text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"\s+", " ", text).strip().rstrip(",;")
    return text, links, sorted(set(refs), key=refs.index)


def make_title(text):
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0].rstrip(".")
    if len(first) > 100:
        first = first[:99].rsplit(" ", 1)[0] + "…"
    return first


def parse_changelog(md):
    """Return a list of releases (dicts) parsed from Keep a Changelog markdown."""
    releases, rel, etype, item, heading = [], None, None, None, ""

    def flush():
        nonlocal item
        if rel is not None and item:
            text, links, refs = clean_item(" ".join(item))
            if text:
                e = {"type": etype or "changed", "title": make_title(text), "description": text,
                     "audiences": ["everyone"], "action_required": False, "_needs_review": True}
                if heading == "breaking changes":
                    e["internal_notes"] = "Imported from a 'Breaking changes' section: set breaking and action."
                if links:
                    e["links"] = links
                if refs:
                    e["refs"] = refs
                rel["entries"].append(e)
        item = None

    for line in md.splitlines():
        m = VERSION_RE.match(line) if line.startswith("## ") else None
        if line.startswith("## "):
            flush()
            rel = None
            if m and parse_semver(m.group("version")):
                rel = {"$schema": RELEASE_SCHEMA_URL, "version": m.group("version"),
                       "date": m.group("date") or "", "entries": []}
                if "yanked" in (m.group("rest") or "").lower():
                    rel["yanked"] = True
                releases.append(rel)
            etype = None
            continue
        if line.startswith("### "):
            flush()
            heading = line[4:].strip().lower()
            etype = SECTION_TYPES.get(heading, "changed")
            continue
        if rel is None:
            continue
        bullet = re.match(r"^[-*+]\s+(.*)", line)
        if bullet:
            flush()
            item = [bullet.group(1)]
        elif item is not None and line.strip() and line.startswith((" ", "\t")):
            item.append(re.sub(r"^\s*[-*+]\s+", "", line))  # continuation or nested bullet
        elif not line.strip():
            continue
        elif item is None and line.strip() and not line.startswith(("[", "<!--")):
            rel.setdefault("summary", line.strip()[:120])
    flush()
    return [r for r in releases if r["entries"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--file", help="CHANGELOG.md to import (default: <app path>/CHANGELOG.md)")
    ap.add_argument("--force", action="store_true", help="overwrite existing release files")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written")
    ap.add_argument("--root", help="repo root (default: found from the current folder)")
    args = ap.parse_args(argv)
    args.root = find_root(args.root)
    app = select_app(load_config(args.root), args.app)
    src = args.file or os.path.join(args.root, app.get("path", "."), "CHANGELOG.md")
    if not os.path.exists(src):
        die("no changelog at %s (pass --file)" % src)
    with open(src, encoding="utf-8") as f:
        releases = parse_changelog(f.read())
    if not releases:
        die("found no '## [x.y.z] - YYYY-MM-DD' version sections in %s" % src)

    rdir = os.path.join(args.root, app["releases_dir"])
    written = skipped = entries = 0
    undated = []
    for r in releases:
        path = os.path.join(rdir, r["version"] + ".json")
        if os.path.exists(path) and not args.force:
            print("  exists, skipped %s (use --force)" % os.path.relpath(path, args.root))
            skipped += 1
            continue
        if not r["date"]:
            undated.append(r["version"])
        entries += len(r["entries"])
        body = json.dumps(r, indent=2, ensure_ascii=False) + "\n"
        if args.dry_run:
            print("--- %s\n%s" % (os.path.relpath(path, args.root), body))
        else:
            os.makedirs(rdir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        written += 1
    verb = "would write" if args.dry_run else "wrote"
    print("%s %d release(s), %d entries; skipped %d." % (verb, written, entries, skipped))
    if entries:
        print("Every entry is marked _needs_review: confirm audiences and action_required, "
              "then delete the flag. validate.py lists them.")
    if undated:
        print("No date found for: %s. Add a date to each before validating." % ", ".join(undated))


if __name__ == "__main__":
    main()
