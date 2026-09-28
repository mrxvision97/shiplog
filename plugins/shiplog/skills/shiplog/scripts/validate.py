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
from _common import (ENTRY_TYPES, NOT_TICKETS, app_for_tag, audience_ids, load_config,  # noqa: E402
                     load_releases, parse_semver, select_app)

TITLE_MAX = 100
DESC_MIN = 20
DESC_MAX = 800
ALLOWED_RELEASE_KEYS = {"$schema", "version", "date", "summary", "entries", "yanked", "_file"}
ALLOWED_ENTRY_KEYS = {"type", "title", "description", "audiences", "action_required", "action",
                      "action_deadline", "breaking", "links", "internal_notes", "refs", "media",
                      "_needs_review"}

TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+)-\d+\b")
# "#1 priority" is not a PR; "(#12)", "PR #12", "fixes #12" and "#1234" are.
PR_REF_RE = re.compile(r"(?:\b(?:PR|pull request|issue|fix(?:e[sd])?|close[sd]?|resolve[sd]?|see|refs?)\s+"
                       r"|\()#\d+\b|(?<![\w/&])#\d{3,}\b", re.I)
JARGON_WORD_RE = re.compile(r"\b(refactor(ed|ing)?|codebase|middleware|monkey.?patch|nit|wip|hotfix)\b", re.I)
JARGON_PATTERNS = [
    (PR_REF_RE, "looks like a PR/issue number; move it to refs"),
    (re.compile(r"`[^`]+`"), "contains code formatting; is this meaningful to the reader?"),
    (re.compile(r"\b[\w-]+/[\w./-]+\.(py|ts|tsx|js|jsx|go|rb|java|rs|php|cs|kt|swift)\b"),
     "mentions a source file path"),
    (re.compile(r"^(fix(ed)?|update[ds]?|misc|various|minor)\b[^.]{0,25}\.?$", re.I),
     "is vague; say what the reader will notice"),
    (re.compile(r"\b[a-z]+[A-Z][a-zA-Z]*\(\)"), "mentions a function name"),
]
REPLACEMENT_RE = re.compile(r"\b(instead|replace[sd]?|replacement|use|switch(?:ing)? to|migrat\w*|"
                            r"move to|upgrade to|successor|alternative)\b", re.I)


def valid_date(s):
    try:
        datetime.date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def is_proper_noun(text, start):
    """True for a capitalized word that isn't starting a sentence, or that is
    followed by another capitalized word ("Hotfix Manager")."""
    if not text[start].isupper():
        return False
    before = text[:start].rstrip()
    if before and before[-1] not in ".!?:\n":
        return True
    nxt = re.match(r"\w+\s+(\w)", text[start:])
    return bool(nxt and nxt.group(1).isupper())


def check_text(label, field, text, warns, allowed_terms=()):
    for term in allowed_terms:
        text = re.sub(re.escape(term), " ", text, flags=re.I)
    if any(m.group(1) not in NOT_TICKETS for m in TICKET_RE.finditer(text)):
        warns.append("%s: %s looks like it has a ticket ID; move it to refs" % (label, field))
    for rx, why in JARGON_PATTERNS:
        if rx.search(text):
            warns.append("%s: %s %s" % (label, field, why))
    if any(not is_proper_noun(text, m.start()) for m in JARGON_WORD_RE.finditer(text)):
        warns.append("%s: %s uses engineering jargon" % (label, field))


def entry_label(e, idx):
    title = e.get("title") if isinstance(e, dict) else None
    if isinstance(title, str) and title.strip():
        t = title.strip()
        return '"%s"' % (t if len(t) <= 50 else t[:49] + "…")
    return "entries[%d]" % idx


def validate_entry(e, idx, app, errs, warns):
    p = entry_label(e, idx)
    if not isinstance(e, dict):
        errs.append("%s must be an object" % p)
        return
    allowed = app.get("allowed_terms") or []
    review = e.get("_needs_review") is True
    for k in e:
        if k not in ALLOWED_ENTRY_KEYS:
            warns.append("%s: unknown field '%s' (ignored)" % (p, k))
    if review:
        warns.append("%s: imported entry needs review; confirm audiences and action_required, "
                     "then delete _needs_review" % p)

    t = e.get("type")
    if t not in ENTRY_TYPES:
        errs.append("%s: type must be one of %s (got %r)" % (p, ", ".join(ENTRY_TYPES), t))

    title = e.get("title")
    if not isinstance(title, str) or not title.strip():
        errs.append("%s: title is required" % p)
    else:
        if len(title) > TITLE_MAX:
            errs.append("%s: title is %d chars; keep it under %d" % (p, len(title), TITLE_MAX))
        check_text(p, "title", title, warns, allowed)

    desc = e.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errs.append("%s: description (what changed, in plain language) is required" % p)
        desc = ""
    else:
        n = len(desc.strip())
        if n < DESC_MIN:
            # Imported legacy entries are often one-liners; the review warning covers them.
            (warns if review else errs).append(
                "%s: description is too short (%d chars); explain what the reader will notice" % (p, n))
        if n > DESC_MAX:
            warns.append("%s: description is long (%d chars); consider linking to docs" % (p, n))
        check_text(p, "description", desc, warns, allowed)

    auds = e.get("audiences")
    if not isinstance(auds, list) or not auds:
        errs.append("%s: audiences (who is affected) is required: a non-empty list" % p)
    else:
        known = audience_ids(app)
        for a in auds:
            if a not in known:
                errs.append("%s: unknown audience %r. Known: %s" % (p, a, ", ".join(known)))
        if "everyone" in auds and len(auds) > 1:
            warns.append("%s: 'everyone' plus specific audiences is redundant" % p)

    ar = e.get("action_required")
    if not isinstance(ar, bool):
        errs.append("%s: action_required must be true or false" % p)
    action = e.get("action")
    if ar is True and (not isinstance(action, str) or len(action.strip()) < 10):
        errs.append("%s: action must describe what readers need to do (action_required is true)" % p)
    if ar is False and action:
        warns.append("%s: has an action but action_required is false" % p)
    if isinstance(action, str) and action:
        check_text(p, "action", action, warns, allowed)

    dl = e.get("action_deadline")
    if dl is not None and not valid_date(dl):
        errs.append("%s: action_deadline must be YYYY-MM-DD" % p)

    breaking = e.get("breaking", False)
    if not isinstance(breaking, bool):
        errs.append("%s: breaking must be true or false" % p)
    elif breaking and ar is not True:
        errs.append("%s: is breaking, so action_required must be true with an action" % p)
    if t == "removed" and ar is False:
        warns.append("%s: removes something but requires no action; double-check" % p)

    links = e.get("links", [])
    if not isinstance(links, list):
        errs.append("%s: links must be a list" % p)
        links = []
    else:
        for j, ln in enumerate(links):
            if not isinstance(ln, dict) or not ln.get("url") or not ln.get("label"):
                errs.append("%s: links[%d] needs 'label' and 'url'" % (p, j))
            elif not re.match(r"^https?://", ln["url"]):
                errs.append("%s: links[%d].url must be http(s)" % (p, j))
    if t == "deprecated":
        if not dl:
            warns.append("%s: deprecation without action_deadline; readers need to know when" % p)
        said = desc + " " + (action if isinstance(action, str) else "")
        if not links and not REPLACEMENT_RE.search(said):
            warns.append("%s: deprecation should name the replacement (\"use X instead\") or add a link" % p)
    v = e.get("refs")
    if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
        errs.append("%s: refs must be a list of strings" % p)
    if "internal_notes" in e and not isinstance(e["internal_notes"], str):
        errs.append("%s: internal_notes must be a string" % p)


def validate_release(r, app, newest=False, today=None):
    errs, warns = [], []
    today = today or datetime.date.today()
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
    elif datetime.date.fromisoformat(d) > today + datetime.timedelta(days=60):
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
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("title"), str):
                key = e["title"].strip().lower()
                if key in titles:
                    warns.append("%s: duplicate title" % entry_label(e, i))
                titles.add(key)
            dl = e.get("action_deadline")
            if newest and not r.get("yanked") and valid_date(dl) and datetime.date.fromisoformat(dl) < today:
                warns.append("%s: action_deadline %s has already passed; update it or the action text"
                             % (entry_label(e, i), dl))
    return errs, warns


def check_app(app, root=".", require_version=None, strict=False, today=None):
    """Validate one app. Returns (error_count, warning_count, report_lines)."""
    releases, load_errors = load_releases(app, root)
    lines = []
    n_err = n_warn = 0
    for path, msg in load_errors:
        lines.append("ERROR   %s: %s" % (os.path.relpath(path, root), msg))
        n_err += 1
    seen = {}
    for i, r in enumerate(releases):
        errs, warns = validate_release(r, app, newest=(i == 0), today=today)
        v = r.get("version")
        if v in seen:
            errs.append("duplicate version %s (also in %s)" % (v, seen[v]))
        seen[v] = r["_file"]
        rel = os.path.relpath(r["_file"], root)
        lines += ["ERROR   %s: %s" % (rel, e) for e in errs]
        lines += ["%s %s: %s" % ("ERROR  " if strict else "warning", rel, w) for w in warns]
        n_err += len(errs) + (len(warns) if strict else 0)
        n_warn += 0 if strict else len(warns)

    # Newer versions should not have older dates.
    dated = [r for r in releases if valid_date(r.get("date")) and parse_semver(str(r.get("version")))]
    for newer, older in zip(dated, dated[1:]):
        if newer["date"] < older["date"]:
            lines.append("warning %s is dated before %s" % (newer["version"], older["version"]))
            n_warn += 1

    if require_version:
        want = require_version
        prefix = app.get("tag_prefix", "v")
        if prefix and want.startswith(prefix):
            want = want[len(prefix):]
        if want not in seen:
            lines.append("ERROR   no release file for version %s (expected %s/%s.json)"
                         % (want, app["releases_dir"], want))
            n_err += 1
    if not releases and not load_errors and not require_version:
        lines.append("(no releases yet)")
    return n_err, n_warn, lines


def validate_app(app, root, require_version, strict):
    n_err, n_warn, lines = check_app(app, root, require_version, strict)
    print("== %s (%s) ==" % (app["name"], app["releases_dir"]))
    for ln in lines:
        print("  " + ln)
    print("  %d error(s), %d warning(s)" % (n_err, n_warn))
    return n_err


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--all", action="store_true", help="validate every app in the config")
    ap.add_argument("--require-version")
    ap.add_argument("--tag")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    cfg = load_config(args.root)
    if args.tag:
        app = app_for_tag(cfg, args.tag)
        if not app:
            print("shiplog: tag %s matches no app's tag_prefix; nothing to check" % args.tag)
            sys.exit(0)
        sys.exit(1 if validate_app(app, args.root, args.tag, args.strict) else 0)
    apps = cfg["apps"] if args.all else [select_app(cfg, args.app)]
    errors = sum(validate_app(a, args.root, args.require_version, args.strict) for a in apps)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
