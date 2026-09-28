"""Add new releases to an existing, hand-written CHANGELOG.md in its own format.

The file's style is learned from its existing entries: the version heading
(brackets, "v", links, where the date goes and how it's written), section names
("### Added" or "### 🐛 Bug Fixes"), bullet character, how long items are, how PRs
are referenced, and blank-line spacing. New releases are inserted above the
newest existing one. Existing lines are never changed, and a version that is
already in the file is never added again.
"""
import datetime
import re

from _common import TYPE_LABELS, parse_semver, semver_key

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
VERSION_RE = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?![\w.])")
BULLET_RE = re.compile(r"^([-*+])\s+(.*)$")
LINK_REF_RE = re.compile(r"^\[([^\]]+)\]:\s*\S+")
PR_LINK_RE = re.compile(r"\(\[#(\d+)\]\((https?://[^)\s]+)\)\)")
PR_PLAIN_RE = re.compile(r"\(#\d+\)")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
_M = "|".join(MONTHS)
_MS = "|".join(m[:3] for m in MONTHS)
# (regex, formatter) for the date styles changelogs commonly use.
DATE_STYLES = [
    (r"\d{4}-\d{2}-\d{2}", lambda d: d.isoformat()),
    (r"\d{4}/\d{2}/\d{2}", lambda d: d.strftime("%Y/%m/%d")),
    (r"\d{2}\.\d{2}\.\d{4}", lambda d: d.strftime("%d.%m.%Y")),
    (r"(?:%s) \d{1,2}, \d{4}" % _M, lambda d: "%s %d, %d" % (MONTHS[d.month - 1], d.day, d.year)),
    (r"\d{1,2} (?:%s) \d{4}" % _M, lambda d: "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)),
    (r"(?:%s) \d{1,2}, \d{4}" % _MS, lambda d: "%s %d, %d" % (MONTHS[d.month - 1][:3], d.day, d.year)),
]
# Section names used in the wild, mapped to Shiplog's types.
SECTION_TYPES = {
    "added": "added", "new": "added", "features": "added", "feature": "added", "new features": "added",
    "whats new": "added", "enhancements": "changed", "changed": "changed", "changes": "changed",
    "improved": "changed", "improvements": "changed", "updated": "changed", "performance": "changed",
    "performance improvements": "changed", "breaking changes": "changed", "breaking": "changed",
    "deprecated": "deprecated", "deprecations": "deprecated", "removed": "removed", "removals": "removed",
    "fixed": "fixed", "fixes": "fixed", "bug fixes": "fixed", "bugfixes": "fixed", "bug fix": "fixed",
    "security": "security", "security fixes": "security",
}
DEFAULT_ORDER = ["added", "changed", "deprecated", "removed", "fixed", "security"]


def norm(label):
    return " ".join(re.sub(r"[^a-z ]+", " ", label.lower()).split())


def version_headings(lines):
    """[(index, level, version)] for headings that name a SemVer version."""
    out = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line.rstrip("\r\n"))
        if not m:
            continue
        v = VERSION_RE.search(m.group(2))
        if v and parse_semver(v.group(1)):
            out.append((i, len(m.group(1)), v.group(1)))
    if not out:
        return []
    level = min(lvl for _, lvl, _ in out)  # sections may mention versions too
    return [h for h in out if h[1] == level]


def count_blanks(lines, start, end):
    n = 0
    while start + n < end and not lines[start + n].strip():
        n += 1
    return n


def merge_order(seen):
    """The file's own section order, with missing types slotted in where Keep a Changelog puts them."""
    order = list(seen)
    for t in DEFAULT_ORDER:
        if t in order:
            continue
        rank = DEFAULT_ORDER.index(t)
        later = [i for i, x in enumerate(order) if DEFAULT_ORDER.index(x) > rank]
        order.insert(later[0] if later else len(order), t)
    return order


def detect_style(text):
    """What the existing file looks like. None when it has no version sections."""
    lines = text.splitlines(keepends=True)
    heads = version_headings(lines)
    if not heads:
        return None
    first, level, latest = heads[0]
    prev = heads[1][2] if len(heads) > 1 else None
    heading = lines[first].rstrip("\r\n")
    style = {"level": level, "latest": latest, "insert_at": first,
             "newline": "\r\n" if lines[first].endswith("\r\n") else "\n"}

    # Heading template: version, previous version (compare links) and date become slots.
    date_fmt = None
    for rx, fmt in DATE_STYLES:
        if re.search(rx, heading):
            heading = re.sub(rx, "{date}", heading, count=1)
            date_fmt = fmt
            break
    ver = r"(?<![\d.])%s(?!\d|\.\d|-\w)"  # "v1.2.0" and "1.2.0...", not "11.2.0" or "1.2.0-rc"
    heading = re.sub(ver % re.escape(latest), "{version}", heading)
    if prev:
        heading = re.sub(ver % re.escape(prev), "{prev}", heading)
    style["heading"] = heading
    style["date_fmt"] = date_fmt

    # Sections, bullets and spacing, learned from the version sections.
    labels, order, bullets, breaking = {}, [], [], None
    blanks_after_heading, blanks_before_section, blanks_after_section = 1, 1, 1
    for n, (i, _, _) in enumerate(heads[:10]):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        if n == 0:
            blanks_after_heading = count_blanks(lines, i + 1, end)
        for j in range(i + 1, end):
            raw = lines[j].rstrip("\r\n")
            m = HEADING_RE.match(raw)
            if m and len(m.group(1)) > level:
                t = SECTION_TYPES.get(norm(m.group(2)))
                if t and "breaking" in norm(m.group(2)):
                    breaking = breaking or (m.group(1), m.group(2))
                    t = None
                if t and t not in labels:
                    labels[t] = (m.group(1), m.group(2))
                if t and n == 0 and t not in order:
                    order.append(t)
                if n == 0 and len(order) == 1:
                    blanks_after_section = count_blanks(lines, j + 1, end)
                if n == 0 and len(order) == 2:
                    k, gap = j - 1, 0
                    while k > i and not lines[k].strip():
                        k, gap = k - 1, gap + 1
                    blanks_before_section = gap
                continue
            b = BULLET_RE.match(raw)
            if b:
                bullets.append(b)
    section_prefix = next(iter(labels.values()))[0] if labels else "#" * (level + 1)
    style["sections"] = {t: labels.get(t, (section_prefix, TYPE_LABELS[t])) for t in DEFAULT_ORDER}
    style["order"] = merge_order(order)
    style["blanks"] = (blanks_after_heading, blanks_before_section, blanks_after_section)
    style["bullet"] = bullets[0].group(1) if bullets else "-"
    texts = [b.group(2) for b in bullets]
    style["breaking_section"] = breaking
    plain = [PR_LINK_RE.sub("", PR_PLAIN_RE.sub("", t)).strip() for t in texts]
    style["bold"] = bool(texts) and sum(t.startswith("**") for t in texts) * 2 > len(texts)
    # Short labels ("Team invites.") get the entry title; sentences get the description.
    style["short"] = bool(plain) and sum(len(t) for t in plain) / len(plain) < 60
    style["period"] = bool(plain) and sum(t.endswith(".") for t in plain) * 2 > len(plain)
    pr_link = next((m for t in texts for m in [PR_LINK_RE.search(t)] if m), None)
    if pr_link:
        style["pr_ref"] = "([#{n}](%s))" % pr_link.group(2).replace(pr_link.group(1), "{n}")
    elif any(PR_PLAIN_RE.search(t) for t in texts):
        style["pr_ref"] = "(#{n})"
    else:
        style["pr_ref"] = None

    # A link reference for the newest version ("[1.2.0]: https://.../compare/v1.1.0...v1.2.0").
    for i, line in enumerate(lines):
        m = LINK_REF_RE.match(line)
        if m and VERSION_RE.search(m.group(1)) and VERSION_RE.search(m.group(1)).group(1) == latest:
            ref = line.rstrip("\r\n")
            ref = re.sub(ver % re.escape(latest), "{version}", ref)
            if prev:
                ref = re.sub(ver % re.escape(prev), "{prev}", ref)
            style["link_ref"], style["link_ref_at"] = ref, i
            break
    return style


def entry_lines(e, style, in_breaking_section=False):
    b = style["bullet"]
    desc = " ".join((e.get("description") or "").split())
    title = " ".join((e.get("title") or "").split())
    if style["bold"]:
        text = "**%s**: %s" % (title, desc)
    elif style["short"]:
        text = title + ("." if style["period"] and not title.endswith((".", "!", "?")) else "")
    else:
        text = desc
    if e.get("breaking") and not in_breaking_section:
        text = "**Breaking:** " + text
    prs = [r[1:] for r in e.get("refs") or [] if re.match(r"^#\d+$", r)]
    if style["pr_ref"] and prs:
        text += " " + " ".join(style["pr_ref"].replace("{n}", n) for n in prs)
    out = ["%s %s" % (b, text)]
    if e.get("action_required") and e.get("action"):
        act = " ".join(e["action"].split())
        if e.get("action_deadline"):
            act += " (by %s)" % e["action_deadline"]
        out.append("  %s **Action required:** %s" % (b, act))
    return out


def release_block(r, prev, style):
    nl = style["newline"]
    date = ""
    if style["date_fmt"]:
        try:
            date = style["date_fmt"](datetime.date.fromisoformat(r.get("date", "")))
        except ValueError:
            date = r.get("date", "")
    heading = style["heading"].replace("{version}", r["version"]).replace("{date}", date)
    heading = heading.replace("{prev}", prev or r["version"])
    after_heading, before_section, after_section = style["blanks"]
    out = [heading] + [""] * after_heading
    entries = r.get("entries", [])
    groups = []
    if style["breaking_section"]:
        groups.append((style["breaking_section"], [e for e in entries if e.get("breaking")], True))
        entries = [e for e in entries if not e.get("breaking")]
    for t in style["order"]:
        groups.append((style["sections"][t], [e for e in entries if e.get("type") == t], False))
    first = True
    for (prefix, label), items, is_breaking in groups:
        if not items:
            continue
        if not first:
            out += [""] * before_section
        first = False
        out.append("%s %s" % (prefix, label))
        out += [""] * after_section
        for e in items:
            out += entry_lines(e, style, is_breaking)
    out.append("")
    return nl.join(out) + nl


def insert_releases(text, releases):
    """Return (new_text, added_versions, notes). TEXT is only ever added to."""
    style = detect_style(text)
    if style is None:
        return text, [], ["no version sections found, so its format can't be matched; nothing was added"]
    latest = style["latest"]
    present = {v for _, _, v in version_headings(text.splitlines(keepends=True))}
    new = sorted((r for r in releases if r.get("version") not in present and not r.get("yanked")
                  and semver_key(r["version"]) > semver_key(latest)),
                 key=lambda r: semver_key(r["version"]), reverse=True)
    notes = ["%s is older than %s and missing from the file; left out so existing history isn't reordered"
             % (r["version"], latest) for r in releases
             if r.get("version") not in present and semver_key(r.get("version", "")) < semver_key(latest)]
    if not new:
        return text, [], notes
    lines = text.splitlines(keepends=True)
    chain = [r["version"] for r in new] + [latest]
    block = "".join(release_block(r, chain[i + 1], style) for i, r in enumerate(new))
    at = style["insert_at"]
    out = lines[:at] + [block] + lines[at:]
    if style.get("link_ref"):
        refs = "".join(style["link_ref"].replace("{version}", v).replace("{prev}", chain[i + 1])
                       + style["newline"] for i, v in enumerate(chain[:-1]))
        pos = style["link_ref_at"] + (1 if style["link_ref_at"] >= at else 0)  # the block shifted it
        out = out[:pos] + [refs] + out[pos:]
    return "".join(out), [r["version"] for r in new], notes
