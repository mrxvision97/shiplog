#!/usr/bin/env python3
"""Validate Shiplog release files. Exits 1 on any error (use in CI).

Usage:
  validate.py [--app ID | --all] [--require-version X.Y.Z] [--strict] [--root DIR]

--require-version  fail unless a release file for this version exists (accepts a
                   tag like v1.2.3 or web-v1.2.3; the app's tag_prefix is stripped)
--tag TAG          CI mode for tag builds: pick the app whose tag_prefix matches
                   TAG (longest prefix wins) and require its release file
--strict           treat warnings as errors
"""
import argparse
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ENTRY_TYPES, audience_ids, load_config, load_releases,  # noqa: E402
                     parse_semver, select_app)

TITLE_MAX = 100
DESC_MIN = 20
DESC_MAX = 800
ALLOWED_RELEASE_KEYS = {"version", "date", "summary", "entries", "yanked", "_file"}
ALLOWED_ENTRY_KEYS = {"type", "title", "description", "audiences", "action_required", "action",
                      "action_deadline", "breaking", "links", "internal_notes", "refs", "media"}

JARGON_PATTERNS = [
    (re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b"), "looks like a ticket ID; move it to refs"),
    (re.compile(r"(?<![\w/])#\d+\b"), "looks like a PR/issue number; move it to refs"),
    (re.compile(r"`[^`]+`"), "contains code formatting; is this meaningful to the reader?"),
    (re.compile(r"\b[\w-]+/[\w./-]+\.(py|ts|tsx|js|jsx|go|rb|java|rs|php|cs|kt|swift)\b"),
     "mentions a source file path"),
    (re.compile(r"\b(refactor(ed|ing)?|codebase|middleware|monkey.?patch|nit|wip|hotfix)\b", re.I),
     "uses engineering jargon"),
    (re.compile(r"^(fix(ed)?|update[ds]?|misc|various|minor)\b[^.]{0,25}\.?$", re.I),
     "is vague; say what the reader will notice"),
    (re.compile(r"\b[a-z]+[A-Z][a-zA-Z]*\(\)"), "mentions a function name"),
]


def valid_date(s):
    try:
        datetime.date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def check_text(label, text, warns):
    for rx, why in JARGON_PATTERNS:
        if rx.search(text):
            warns.append("%s %s" % (label, why))


def validate_entry(e, idx, app, errs, warns):
    p = "entries[%d]" % idx
    if not isinstance(e, dict):
        errs.append("%s must be an object" % p)
        return
    for k in e:
        if k not in ALLOWED_ENTRY_KEYS:
            warns.append("%s: unknown field '%s' (ignored)" % (p, k))

    t = e.get("type")
    if t not in ENTRY_TYPES:
        errs.append("%s.type must be one of %s (got %r)" % (p, ", ".join(ENTRY_TYPES), t))

    title = e.get("title")
    if not isinstance(title, str) or not title.strip():
        errs.append("%s.title is required" % p)
    else:
        if len(title) > TITLE_MAX:
            errs.append("%s.title is %d chars; keep it under %d" % (p, len(title), TITLE_MAX))
        check_text("%s.title" % p, title, warns)

    desc = e.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errs.append("%s.description (what changed, in plain language) is required" % p)
    else:
        n = len(desc.strip())
        if n < DESC_MIN:
            errs.append("%s.description is too short (%d chars); explain what the reader will notice" % (p, n))
        if n > DESC_MAX:
            warns.append("%s.description is long (%d chars); consider linking to docs" % (p, n))
        check_text("%s.description" % p, desc, warns)

    auds = e.get("audiences")
    if not isinstance(auds, list) or not auds:
        errs.append("%s.audiences (who is affected) is required: a non-empty list" % p)
    else:
        known = audience_ids(app)
        for a in auds:
            if a not in known:
                errs.append("%s.audiences: unknown audience %r. Known: %s" % (p, a, ", ".join(known)))
        if "everyone" in auds and len(auds) > 1:
            warns.append("%s.audiences: 'everyone' plus specific audiences is redundant" % p)

    ar = e.get("action_required")
    if not isinstance(ar, bool):
        errs.append("%s.action_required must be true or false" % p)
    action = e.get("action")
    if ar is True and (not isinstance(action, str) or len(action.strip()) < 10):
        errs.append("%s.action must describe what readers need to do (action_required is true)" % p)
    if ar is False and action:
        warns.append("%s has an action but action_required is false" % p)
    if isinstance(action, str) and action:
        check_text("%s.action" % p, action, warns)

    dl = e.get("action_deadline")
    if dl is not None and not valid_date(dl):
        errs.append("%s.action_deadline must be YYYY-MM-DD" % p)

    breaking = e.get("breaking", False)
    if not isinstance(breaking, bool):
        errs.append("%s.breaking must be true or false" % p)
    elif breaking and ar is not True:
        errs.append("%s is breaking, so action_required must be true with an action" % p)
    if t == "removed" and ar is False:
        warns.append("%s removes something but requires no action; double-check" % p)
    if t == "deprecated" and not dl:
        warns.append("%s is a deprecation without action_deadline; readers need to know when" % p)

    links = e.get("links", [])
    if not isinstance(links, list):
        errs.append("%s.links must be a list" % p)
    else:
        for j, ln in enumerate(links):
            if not isinstance(ln, dict) or not ln.get("url") or not ln.get("label"):
                errs.append("%s.links[%d] needs 'label' and 'url'" % (p, j))
            elif not re.match(r"^https?://", ln["url"]):
                errs.append("%s.links[%d].url must be http(s)" % (p, j))
    for key in ("refs",):
        v = e.get(key)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            errs.append("%s.%s must be a list of strings" % (p, key))
    if "internal_notes" in e and not isinstance(e["internal_notes"], str):
        errs.append("%s.internal_notes must be a string" % p)


def validate_release(r, app):
    errs, warns = [], []
    for k in r:
        if k not in ALLOWED_RELEASE_KEYS:
            warns.append("unknown top-level field '%s' (ignored)" % k)
    v = r.get("version")
    if not isinstance(v, str) or not parse_semver(v):
        errs.append("version must be SemVer like 1.4.0 (got %r)" % v)
    else:
        fname = os.path.basename(r.get("_file", ""))
        if fname and fname != v + ".json":
            errs.append("file name %s should be %s.json" % (fname, v))
    d = r.get("date")
    if not valid_date(d):
        errs.append("date must be YYYY-MM-DD (got %r)" % d)
    elif datetime.date.fromisoformat(d) > datetime.date.today() + datetime.timedelta(days=60):
        warns.append("date %s is far in the future" % d)
    s = r.get("summary")
    if s is not None and (not isinstance(s, str) or len(s) > 120):
        errs.append("summary must be a string under 120 chars")
    entries = r.get("entries")
    if not isinstance(entries, list) or not entries:
        errs.append("entries must be a non-empty list")
    else:
        titles = set()
        for i, e in enumerate(entries):
            validate_entry(e, i, app, errs, warns)
            if isinstance(e, dict) and isinstance(e.get("title"), str):
                key = e["title"].strip().lower()
                if key in titles:
                    warns.append("entries[%d]: duplicate title" % i)
                titles.add(key)
    return errs, warns


def validate_app(app, root, require_version, strict):
    releases, load_errors = load_releases(app, root)
    total_err = 0
    total_warn = 0
    print("== %s (%s) ==" % (app["name"], app["releases_dir"]))
    for path, msg in load_errors:
        print("  ERROR %s: %s" % (path, msg))
        total_err += 1
    seen = {}
    for r in releases:
        errs, warns = validate_release(r, app)
        v = r.get("version")
        if v in seen:
            errs.append("duplicate version %s (also in %s)" % (v, seen[v]))
        seen[v] = r["_file"]
        rel = os.path.relpath(r["_file"], root)
        for e in errs:
            print("  ERROR   %s: %s" % (rel, e))
        for w in warns:
            print("  %s %s: %s" % ("ERROR  " if strict else "warning", rel, w))
        total_err += len(errs) + (len(warns) if strict else 0)
        total_warn += 0 if strict else len(warns)

    # Newer versions should not have older dates.
    dated = [r for r in releases if valid_date(r.get("date")) and parse_semver(str(r.get("version")))]
    for newer, older in zip(dated, dated[1:]):
        if newer["date"] < older["date"]:
            print("  warning %s is dated before %s" % (newer["version"], older["version"]))
            total_warn += 1

    if require_version:
        want = require_version
        prefix = app.get("tag_prefix", "v")
        if prefix and want.startswith(prefix):
            want = want[len(prefix):]
        if want not in seen:
            print("  ERROR   no release file for version %s (expected %s/%s.json)"
                  % (want, app["releases_dir"], want))
            total_err += 1
    if not releases and not load_errors and not require_version:
        print("  (no releases yet)")
    print("  %d error(s), %d warning(s)" % (total_err, total_warn))
    return total_err


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--all", action="store_true", help="validate every app in the config")
    ap.add_argument("--require-version")
    ap.add_argument("--tag")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    cfg = load_config(args.root)
    if args.tag:
        matches = [a for a in cfg["apps"] if args.tag.startswith(a.get("tag_prefix", "v"))
                   and parse_semver(args.tag[len(a.get("tag_prefix", "v")):])]
        if not matches:
            print("shiplog: tag %s matches no app's tag_prefix; nothing to check" % args.tag)
            sys.exit(0)
        app = max(matches, key=lambda a: len(a.get("tag_prefix", "v")))
        sys.exit(1 if validate_app(app, args.root, args.tag, args.strict) else 0)
    apps = cfg["apps"] if args.all else [select_app(cfg, args.app)]
    errors = sum(validate_app(a, args.root, args.require_version, args.strict) for a in apps)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
