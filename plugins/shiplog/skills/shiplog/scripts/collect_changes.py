#!/usr/bin/env python3
"""Collect changes for the next release of an app and suggest a SemVer version.

Commits are grouped by pull request: merge commits ("Merge pull request #N")
contribute their PR title and the commits they brought in, and squash merges
("Subject (#N)") become one change each. Other commits stand alone.
Conventional Commits are parsed when present; other commits get type "other".

By default prints a compact summary, one line per change:
  <type>[!][(scope)]  <PR or sha>  <subject>  [refs]  (N commits)  {labels}
"!" marks a breaking change. --full prints everything as JSON.

If the GitHub CLI is installed and authenticated, PR titles, bodies (truncated)
and labels are fetched in one batched GraphQL call. Skipped silently otherwise,
or with --no-gh / SHIPLOG_NO_GH=1.

Usage:
  collect_changes.py [--app ID] [--from REF | --since DATE] [--to REF] [--full] [--no-gh] [--root DIR]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (NOT_TICKETS, detect_project, die, find_root, load_config,  # noqa: E402
                     load_releases, parse_semver, select_app, semver_key, semver_tags)

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
PR_BODY_MAX = 500
BIG_RANGE = 60  # more changes than this without a starting point: ask where the release starts
SUMMARY_MAX = 150  # summary lines per section; --full has everything
GH_MAX_PRS = 100
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
    refs = ["#" + n for n in REF_RE.findall(text)] + [
        t for t in TICKET_RE.findall(text) if t.split("-")[0] not in NOT_TICKETS]
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


def pr_members(root, rng, limit=()):
    """Map commit sha -> (pr ref, merge commit) for commits brought in by PR merges.

    Walks the first-parent (mainline) history oldest first. Each merge owns the
    commits reachable from its side parents that no earlier mainline commit owns.
    Two git calls in total, however many PRs there are.
    """
    graph = {}
    for line in git(["rev-list", "--parents", rng] + list(limit), root).splitlines():
        shas = line.split()
        if shas:
            graph[shas[0]] = shas[1:]
    mainline = list(reversed(git(["rev-list", "--first-parent", rng] + list(limit), root).split()))
    merges = {m["sha"]: m for m in read_log(root, [rng, "--merges", "--first-parent"] + list(limit))}
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


def gh_enrich(changes, root):
    """Add pr_title, pr_body and labels to PR changes with ONE gh GraphQL call.
    Returns True if enrichment ran. Any failure is silent: this is optional."""
    if os.environ.get("SHIPLOG_NO_GH") or not shutil.which("gh"):
        return False
    nums = sorted({int(c["pr"][1:]) for c in changes if (c.get("pr") or "").startswith("#")})[:GH_MAX_PRS]
    if not nums:
        return False
    fields = " ".join("p%d: pullRequest(number: %d) { title body labels(first: 10) { nodes { name } } }"
                      % (n, n) for n in nums)
    query = ("query($owner: String!, $repo: String!) { repository(owner: $owner, name: $repo) { %s } }"
             % fields)
    try:
        # gh fills {owner}/{repo} from the current repository's remote.
        r = subprocess.run(["gh", "api", "graphql", "-F", "owner={owner}", "-F", "repo={repo}",
                            "-f", "query=" + query], cwd=root, capture_output=True, text=True, timeout=20)
        # Missing PR numbers produce GraphQL errors (non-zero exit) but the rest still has data.
        repo = (json.loads(r.stdout or "{}").get("data") or {}).get("repository") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    for c in changes:
        node = repo.get("p" + (c.get("pr") or "")[1:]) if (c.get("pr") or "").startswith("#") else None
        if not node:
            continue
        body = re.sub(r"```.*?```|<!--.*?-->", " ", node.get("body") or "", flags=re.S)
        body = re.sub(r"^\s*(#+|---+|[-*]\s*\[[ x]\])\s*", "", body, flags=re.M)
        body = " ".join(body.replace("`", "").replace("**", "").split())
        title = node.get("title") or ""
        m = CC_RE.match(title)
        if m:
            title = m.group("subject").strip()
            if c["type"] == "other":
                c["type"], c["scope"] = m.group("type").lower(), m.group("scope")
            c["breaking"] = c["breaking"] or bool(m.group("bang"))
        c["pr_title"] = title
        c["pr_body"] = body if len(body) <= PR_BODY_MAX else body[:PR_BODY_MAX - 1] + "…"
        c["labels"] = [x["name"] for x in (node.get("labels") or {}).get("nodes") or []]
        if any("breaking" in x.lower() for x in c["labels"]):
            c["breaking"] = True
            c["likely_internal"] = False
    return bool(repo)


def latest_release_file(app, root):
    releases, _ = load_releases(app, root)
    versions = [r.get("version") for r in releases if parse_semver(str(r.get("version")))]
    return versions[0] if versions else None


def collect(app, root=".", from_ref=None, to_ref="HEAD", use_gh=True, since=None):
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
    limit = ["--since=" + since] if since else []

    path = app.get("path", ".")
    pathspec = ["--", path] if path and path != "." else []
    try:
        commits = read_log(root, [rng, "--no-merges"] + limit + pathspec)
        owner = pr_members(root, rng, limit)
    except RuntimeError as e:
        die("%s%s" % (e, (" " + SHALLOW_HINT) if shallow else ""))
    changes = group_changes(commits, owner)
    enriched = gh_enrich(changes, root) if use_gh else False

    level = "patch"
    if any(c["breaking"] for c in changes):
        level = "major"
    elif any(c["type"] == "feat" for c in changes):
        level = "minor"

    base = last_version
    if to_ref == "HEAD":
        try:
            branch = git(["rev-parse", "--abbrev-ref", "HEAD"], root).strip()
        except RuntimeError:
            branch = ""
        if branch and branch not in ("main", "master", "trunk", "develop", "HEAD") and not branch.startswith("release"):
            notes.append("You're on branch '%s', so this includes unreleased work. Releases usually come from "
                         "the main branch: pass --to main (or origin/main)." % branch)
    if not last_tag:
        others = sorted({t for p, _, t in semver_tags(root) if p != prefix})
        if others:
            example = others[-1]
            other_prefix = next(p for p, _, t in semver_tags(root) if t == example)
            notes.append("No '%s*' tags, but found version tags like '%s'. If those are your releases, set "
                         "\"tag_prefix\": %s in .shiplog.json." % (prefix, example, json.dumps(other_prefix)))
    if not base:
        base = latest_release_file(app, root)
        manifest = detect_project(os.path.join(root, app.get("path", "."))).get("version")
        if base:
            notes.append("No '%s*' tag found; using the latest release file (%s) as the base version."
                         % (prefix, base))
        elif manifest:
            base = manifest
            notes.append("No '%s*' tag or release files; using the project manifest's version (%s) as the "
                         "base. Confirm it's the last version users got." % (prefix, base))
        else:
            notes.append("No '%s*' tag and no release files: this is the first release. "
                         "0.1.0 is suggested; use 1.0.0 if the product is already stable." % prefix)
    if not from_ref and not since and len(changes) > BIG_RANGE:
        notes.append("No starting point, so this covers the whole history (%d changes). Ask the user where "
                     "this release starts, then pass --from <tag or commit> or --since YYYY-MM-DD."
                     % len(changes))
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
        "pr_details": enriched,
        "breaking_count": sum(1 for c in changes if c["breaking"]),
        "likely_user_facing": [c for c in changes if not c["likely_internal"]],
        "likely_internal": [c for c in changes if c["likely_internal"]],
        "notes": notes,
    }


def change_line(c, width=None):
    head = c["type"] + ("!" if c["breaking"] else "") + ("(%s)" % c["scope"] if c.get("scope") else "")
    subject = c.get("pr_title") or c["subject"]
    if width and len(subject) > width:
        subject = subject[:width - 1] + "…"
    parts = [head, c.get("pr") or c["sha"][:7], subject]
    refs = [r for r in c["refs"] if r != c.get("pr")]
    if refs:
        parts.append("[%s]" % ",".join(refs))
    if len(c.get("commits", [])) > 1:
        parts.append("(%d commits)" % len(c["commits"]))
    if c.get("labels"):
        parts.append("{%s}" % ",".join(c["labels"]))
    line = "  ".join(parts)
    if c.get("pr_body") and not width:
        line += "\n    > " + (c["pr_body"][:160] + ("…" if len(c["pr_body"]) > 160 else ""))
    return line


def summarize(out):
    """Compact text for the skill: a header, notes, then one line per change."""
    lines = ["%s  %s  last=%s  suggest=%s (%s)  changes=%d commits=%d breaking=%d" % (
        out["app"], out["range"], out["last_version"] or "-", out["suggested_version"] or "-",
        out["bump"] or "-", out["change_count"], out["commit_count"], out["breaking_count"])]
    lines += ["note: " + n for n in out["notes"]]
    if out["likely_user_facing"]:
        lines.append("USER-FACING:")
        lines += [change_line(c) for c in out["likely_user_facing"][:SUMMARY_MAX]]
        if len(out["likely_user_facing"]) > SUMMARY_MAX:
            lines.append("…%d more (narrow with --from/--since, or use --full)"
                         % (len(out["likely_user_facing"]) - SUMMARY_MAX))
    if out["likely_internal"]:
        lines.append("LIKELY INTERNAL (skip unless users notice):")
        lines += [change_line(c, width=60) for c in out["likely_internal"][:SUMMARY_MAX]]
        if len(out["likely_internal"]) > SUMMARY_MAX:
            lines.append("…%d more" % (len(out["likely_internal"]) - SUMMARY_MAX))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--from", dest="from_ref", help="start ref (exclusive). Default: last tag for the app")
    ap.add_argument("--to", dest="to_ref", default="HEAD")
    ap.add_argument("--since", help="only commits after this date (YYYY-MM-DD), e.g. for a first release")
    ap.add_argument("--root", help="repo root (default: found from the current folder)")
    ap.add_argument("--full", action="store_true", help="print the full JSON instead of the summary")
    ap.add_argument("--no-gh", action="store_true", help="don't fetch PR details with the GitHub CLI")
    ap.add_argument("--include-merges", action="store_true", help=argparse.SUPPRESS)  # obsolete: merges are grouped
    args = ap.parse_args(argv)
    args.root = find_root(args.root)
    app = select_app(load_config(args.root), args.app)
    out = collect(app, args.root, args.from_ref, args.to_ref, use_gh=not args.no_gh, since=args.since)
    if args.full:
        json.dump(out, sys.stdout, indent=2)
        print()
    else:
        print(summarize(out))


if __name__ == "__main__":
    main()
