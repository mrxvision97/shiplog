#!/usr/bin/env python3
"""Collect commits for the next release of an app and suggest a SemVer version.

Prints JSON to stdout. Parses Conventional Commits when present but works with
any commit style; unparsed commits get type "other".

Usage:
  collect_changes.py [--app ID] [--from REF] [--to REF] [--root DIR]
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_config, parse_semver, select_app, semver_key  # noqa: E402

CC_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<subject>.+)$")
REF_RE = re.compile(r"(?<![\w/])#(\d+)\b")
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
INTERNAL_TYPES = {"chore", "ci", "test", "tests", "build", "style", "refactor", "docs"}
SEP = "\x1e"  # record separator
FSEP = "\x1f"  # field separator


def git(args, root):
    r = subprocess.run(["git"] + args, cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git %s failed" % " ".join(args))
    return r.stdout


def find_last_tag(root, prefix):
    try:
        tags = git(["tag", "--list", prefix + "*", "--merged", "HEAD"], root).split()
    except RuntimeError:
        return None, None
    versioned = []
    for t in tags:
        v = t[len(prefix):]
        if parse_semver(v):
            versioned.append((semver_key(v), t, v))
    if not versioned:
        return None, None
    versioned.sort(reverse=True)
    _, tag, version = versioned[0]
    return tag, version


def bump(version, level):
    major, minor, patch, _ = parse_semver(version)
    if level == "major":
        if major == 0:  # pre-1.0 convention: breaking -> minor
            return "0.%d.0" % (minor + 1)
        return "%d.0.0" % (major + 1)
    if level == "minor":
        return "%d.%d.0" % (major, minor + 1)
    return "%d.%d.%d" % (major, minor, patch + 1)


def parse_commit(sha, author, date, subject, body):
    c = {
        "sha": sha[:10],
        "author": author,
        "date": date,
        "subject": subject,
        "type": "other",
        "scope": None,
        "breaking": False,
        "likely_internal": False,
        "refs": [],
    }
    m = CC_RE.match(subject)
    if m:
        c["type"] = m.group("type").lower()
        c["scope"] = m.group("scope")
        c["breaking"] = bool(m.group("bang"))
        c["subject"] = m.group("subject").strip()
    if re.search(r"^BREAKING[ -]CHANGE:", body, re.MULTILINE):
        c["breaking"] = True
    c["likely_internal"] = c["type"] in INTERNAL_TYPES and not c["breaking"]
    text = subject + "\n" + body
    refs = ["#" + n for n in REF_RE.findall(text)] + TICKET_RE.findall(text)
    c["refs"] = sorted(set(refs), key=refs.index)
    if body.strip():
        c["body"] = body.strip()[:1500]
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--from", dest="from_ref", help="start ref (exclusive). Default: last tag for the app")
    ap.add_argument("--to", dest="to_ref", default="HEAD")
    ap.add_argument("--root", default=".")
    ap.add_argument("--include-merges", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.root)
    app = select_app(cfg, args.app)
    prefix = app.get("tag_prefix", "v")

    try:
        git(["rev-parse", "--git-dir"], args.root)
    except RuntimeError:
        print("shiplog: not a git repository: %s" % os.path.abspath(args.root), file=sys.stderr)
        sys.exit(2)

    last_tag, last_version = find_last_tag(args.root, prefix)
    from_ref = args.from_ref or last_tag
    rng = "%s..%s" % (from_ref, args.to_ref) if from_ref else args.to_ref

    log_args = ["log", rng, "--format=" + SEP + "%H" + FSEP + "%an" + FSEP + "%ad" + FSEP + "%s" + FSEP + "%b",
                "--date=short"]
    if not args.include_merges:
        log_args.append("--no-merges")
    path = app.get("path", ".")
    if path and path != ".":
        log_args += ["--", path]
    try:
        raw = git(log_args, args.root)
    except RuntimeError as e:
        print("shiplog: %s" % e, file=sys.stderr)
        sys.exit(2)

    commits = []
    for rec in raw.split(SEP):
        if not rec.strip():
            continue
        parts = rec.split(FSEP)
        if len(parts) < 5:
            continue
        sha, author, date, subject, body = parts[0], parts[1], parts[2], parts[3], FSEP.join(parts[4:])
        commits.append(parse_commit(sha.strip(), author, date, subject.strip(), body))

    level = "patch"
    if any(c["breaking"] for c in commits):
        level = "major"
    elif any(c["type"] == "feat" for c in commits):
        level = "minor"

    base = last_version or "0.0.0"
    suggested = bump(base, level) if commits else base
    if not last_version and commits:
        suggested = "0.1.0" if level != "major" else "1.0.0"

    counts = {}
    for c in commits:
        counts[c["type"]] = counts.get(c["type"], 0) + 1

    out = {
        "app": app["id"],
        "range": rng,
        "last_tag": last_tag,
        "last_version": last_version,
        "bump": level if commits else None,
        "suggested_version": suggested,
        "suggested_tag": prefix + suggested,
        "commit_count": len(commits),
        "counts_by_type": counts,
        "breaking_count": sum(1 for c in commits if c["breaking"]),
        "likely_user_facing": [c for c in commits if not c["likely_internal"]],
        "likely_internal": [c for c in commits if c["likely_internal"]],
        "notes": [],
    }
    if not last_tag:
        out["notes"].append("No version tag with prefix '%s' found; range covers full history." % prefix)
    if not commits:
        out["notes"].append("No commits in range; nothing to release.")
    if counts.get("other"):
        out["notes"].append("%d commit(s) don't follow Conventional Commits; read them to classify."
                            % counts["other"])
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
