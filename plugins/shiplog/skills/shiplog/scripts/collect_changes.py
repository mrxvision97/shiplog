#!/usr/bin/env python3
"""Collect changes for the next release of an app and suggest a SemVer version.

Commits are grouped by pull request: merge commits ("Merge pull request #N")
contribute their PR title and the commits they brought in, and squash merges
("Subject (#N)") become one change each. Other commits stand alone.
Conventional Commits are parsed when present; other commits get type "other".

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
from _common import (die, load_config, load_releases, parse_semver,  # noqa: E402
                     select_app, semver_key)

CC_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<subject>.+)$")
REF_RE = re.compile(r"(?<![\w/])#(\d+)\b")
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
MERGE_PR_RES = [
    re.compile(r"^Merge pull request #(\d+)\b"),         # GitHub
    re.compile(r"^Merged in \S+ \(pull request #(\d+)\)"),  # Bitbucket
]
GITLAB_MR_RE = re.compile(r"^See merge request \S*!(\d+)", re.MULTILINE)
SQUASH_PR_RE = re.compile(r"\s*\(#(\d+)\)\s*$")
INTERNAL_TYPES = {"chore", "ci", "test", "tests", "build", "style", "refactor", "docs"}
TYPE_PRIORITY = ["feat", "fix", "perf", "revert", "security", "deprecate"]
SEP = "\x1e"  # record separator
FSEP = "\x1f"  # field separator
LOG_FORMAT = "--format=" + SEP + FSEP.join(["%H", "%P", "%an", "%ad", "%s", "%b"])
SHALLOW_HINT = ("In GitHub Actions set `fetch-depth: 0` on actions/checkout; "
                "locally run `git fetch --unshallow --tags`.")


def git(args, root):
    r = subprocess.run(["git"] + args, cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git %s failed" % " ".join(args))
    return r.stdout


def read_log(root, args):
    out = []
    for rec in git(["log", LOG_FORMAT, "--date=short"] + args, root).split(SEP):
        parts = rec.split(FSEP)
        if len(parts) < 6:
            continue
        out.append({"sha": parts[0].strip(), "parents": parts[1].split(), "author": parts[2],
                    "date": parts[3], "subject": parts[4].strip(), "body": FSEP.join(parts[5:]).strip()})
    return out


def is_shallow(root):
    try:
        return git(["rev-parse", "--is-shallow-repository"], root).strip() == "true"
    except RuntimeError:
        return False


def find_last_tag(root, prefix, to_ref="HEAD"):
    """Newest SemVer tag with PREFIX that is an ancestor of TO_REF."""
    try:
        tags = git(["tag", "--list", prefix + "*", "--merged", to_ref], root).split()
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
    """SemVer increment. From a pre-release, the first bump that the pre-release
    already covers just drops the suffix (1.2.0-beta.1 + minor -> 1.2.0)."""
    major, minor, patch, pre = parse_semver(version)
    if level == "major" and major == 0:  # pre-1.0 convention: breaking -> minor
        level = "minor"
    if level == "major":
        if pre and minor == 0 and patch == 0:
            return "%d.0.0" % major
        return "%d.0.0" % (major + 1)
    if level == "minor":
        if pre and patch == 0:
            return "%d.%d.0" % (major, minor)
        return "%d.%d.0" % (major, minor + 1)
    if pre:
        return "%d.%d.%d" % (major, minor, patch)
    return "%d.%d.%d" % (major, minor, patch + 1)


def find_refs(text):
    refs = ["#" + n for n in REF_RE.findall(text)] + TICKET_RE.findall(text)
    return sorted(set(refs), key=refs.index)


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
    c["refs"] = find_refs(subject + "\n" + body)
    if body.strip():
        c["body"] = body.strip()[:1500]
    return c


def merge_pr_number(merge):
    for rx in MERGE_PR_RES:
        m = rx.match(merge["subject"])
        if m:
            return "#" + m.group(1)
    m = GITLAB_MR_RE.search(merge["body"])
    if m:
        return "!" + m.group(1)
    return None


def pr_members(root, rng):
    """Map commit sha -> (pr ref, merge commit) for commits brought in by PR merges.

    Walks the first-parent (mainline) history oldest first. Each merge owns the
    commits reachable from its side parents that no earlier mainline commit owns.
    Two git calls in total, however many PRs there are.
    """
    graph = {}
    for line in git(["rev-list", "--parents", rng], root).splitlines():
        shas = line.split()
        if shas:
            graph[shas[0]] = shas[1:]
    mainline = list(reversed(git(["rev-list", "--first-parent", rng], root).split()))
    merges = {m["sha"]: m for m in read_log(root, [rng, "--merges", "--first-parent"])}
    owner, seen = {}, set()
    for sha in mainline:
        seen.add(sha)
        merge = merges.get(sha)
        pr = merge_pr_number(merge) if merge else None
        stack = list(graph.get(sha, [])[1:])
        while stack:
            c = stack.pop()
            if c in seen or c not in graph:
                continue
            seen.add(c)
            if pr:
                owner[c] = (pr, merge)
            stack.extend(graph[c])
    return owner


def pick_type(commits):
    types = [c["type"] for c in commits]
    for t in TYPE_PRIORITY:
        if t in types:
            return t
    for t in types:
        if t not in INTERNAL_TYPES and t != "other":
            return t
    return types[0] if types else "other"


def pr_change(pr, merge, members):
    lines = [ln.strip() for ln in merge["body"].splitlines()
             if ln.strip() and not GITLAB_MR_RE.match(ln.strip())]
    title = lines[0] if lines else merge["subject"]
    c = parse_commit(merge["sha"], merge["author"], merge["date"], title, "")
    if c["type"] == "other":
        c["type"] = pick_type(members)
        c["scope"] = None
    c["breaking"] = c["breaking"] or any(m["breaking"] for m in members)
    c["likely_internal"] = c["type"] in INTERNAL_TYPES and not c["breaking"]
    refs = [pr] + c["refs"] + [r for m in members for r in m["refs"]]
    c["refs"] = sorted(set(refs), key=refs.index)
    c.update(kind="pr", pr=pr, commits=[{"sha": m["sha"], "subject": m["subject"], "type": m["type"]}
                                        for m in members])
    return c


def group_changes(commits, owner):
    """Turn path-filtered commits into user-level changes (one per PR)."""
    changes, by_pr = [], {}
    for raw in commits:
        c = parse_commit(raw["sha"], raw["author"], raw["date"], raw["subject"], raw["body"])
        if raw["sha"] in owner:
            pr, merge = owner[raw["sha"]]
            if pr not in by_pr:
                by_pr[pr] = (merge, [])
                changes.append(pr)
            by_pr[pr][1].append(c)
            continue
        m = SQUASH_PR_RE.search(c["subject"])
        c["kind"] = "commit"
        c["pr"] = None
        if m:
            c["kind"] = "pr"
            c["pr"] = "#" + m.group(1)
            c["subject"] = c["subject"][:m.start()].rstrip()
        changes.append(c)
    return [pr_change(x, *by_pr[x]) if isinstance(x, str) else x for x in changes]


def latest_release_file(app, root):
    releases, _ = load_releases(app, root)
    versions = [r.get("version") for r in releases if parse_semver(str(r.get("version")))]
    return versions[0] if versions else None


def collect(app, root=".", from_ref=None, to_ref="HEAD"):
    prefix = app.get("tag_prefix", "v")
    try:
        git(["rev-parse", "--git-dir"], root)
    except RuntimeError:
        die("not a git repository: %s" % os.path.abspath(root))
    notes = []
    shallow = is_shallow(root)
    last_tag, last_version = find_last_tag(root, prefix, to_ref)
    if shallow and not (from_ref or last_tag):
        die("this is a shallow clone and no '%s*' tag is reachable, so the release range is unknown. %s"
            % (prefix, SHALLOW_HINT))
    if shallow:
        notes.append("Shallow clone: history may be incomplete. " + SHALLOW_HINT)
    from_ref = from_ref or last_tag
    rng = "%s..%s" % (from_ref, to_ref) if from_ref else to_ref

    path = app.get("path", ".")
    pathspec = ["--", path] if path and path != "." else []
    try:
        commits = read_log(root, [rng, "--no-merges"] + pathspec)
        owner = pr_members(root, rng)
    except RuntimeError as e:
        die("%s%s" % (e, (" " + SHALLOW_HINT) if shallow else ""))
    changes = group_changes(commits, owner)

    level = "patch"
    if any(c["breaking"] for c in changes):
        level = "major"
    elif any(c["type"] == "feat" for c in changes):
        level = "minor"

    base = last_version
    if not base:
        base = latest_release_file(app, root)
        if base:
            notes.append("No '%s*' tag found; using the latest release file (%s) as the base version. "
                         "The range covers full history; pass --from to narrow it." % (prefix, base))
        else:
            notes.append("No '%s*' tag and no release files: this is the first release. "
                         "0.1.0 is suggested; use 1.0.0 if the product is already stable." % prefix)
    if not changes:
        suggested = None
        notes.append("No commits in range; nothing to release.")
    elif base:
        suggested = bump(base, level)
    else:
        suggested = "0.1.0"

    counts = {}
    for c in changes:
        counts[c["type"]] = counts.get(c["type"], 0) + 1
    if counts.get("other"):
        notes.append("%d change(s) don't follow Conventional Commits; read them to classify." % counts["other"])
    return {
        "app": app["id"],
        "range": rng,
        "last_tag": last_tag,
        "last_version": last_version,
        "bump": level if changes else None,
        "suggested_version": suggested,
        "suggested_tag": prefix + suggested if suggested else None,
        "commit_count": len(commits),
        "change_count": len(changes),
        "pr_count": sum(1 for c in changes if c.get("pr")),
        "counts_by_type": counts,
        "breaking_count": sum(1 for c in changes if c["breaking"]),
        "likely_user_facing": [c for c in changes if not c["likely_internal"]],
        "likely_internal": [c for c in changes if c["likely_internal"]],
        "notes": notes,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--from", dest="from_ref", help="start ref (exclusive). Default: last tag for the app")
    ap.add_argument("--to", dest="to_ref", default="HEAD")
    ap.add_argument("--root", default=".")
    ap.add_argument("--full", action="store_true", help="print the full JSON (default)")
    ap.add_argument("--include-merges", action="store_true", help=argparse.SUPPRESS)  # obsolete: merges are grouped
    args = ap.parse_args(argv)
    app = select_app(load_config(args.root), args.app)
    out = collect(app, args.root, args.from_ref, args.to_ref)
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
