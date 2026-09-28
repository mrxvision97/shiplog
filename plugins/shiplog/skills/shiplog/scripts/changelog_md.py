"""Add new releases to an existing, hand-written changelog in its own format.

The file's style is learned from its existing entries:
- version headings: "## [1.2.0] - 2024-01-05", "## v1.2.0 (2024-01-05)", "## Version 1.2.0",
  links to compare views, or underlined ("1.2.0 (2024-01-05)" over "=====" or "-----")
- sections: "### Added", "### 🐛 Bug Fixes", "**Bugfixes**", "Bug fixes:", or none at all
- bullets, item length, PR reference style, blank-line spacing and line endings

New releases are inserted above the newest existing one. Existing lines are
never changed, and a version already in the file is never added again.
Works for Markdown, and for reStructuredText and plain-text files that use
underlined headings.
"""
import datetime
import re

from _common import TYPE_LABELS, parse_semver, semver_key

ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
UNDERLINE_RE = re.compile(r"^(=+|-+)\s*$")
VERSION_RE = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?![\w.])")
BULLET_RE = re.compile(r"^([-*+])\s+(.*)$")
BOLD_LABEL_RE = re.compile(r"^\*\*([^*]+?):?\*\*:?\s*$")
COLON_LABEL_RE = re.compile(r"^([A-Z][A-Za-z &/-]{2,40}):\s*$")
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
    "whats new": "added", "feature enhancements": "added", "enhancements": "changed", "changed": "changed",
    "changes": "changed", "improved": "changed", "improvements": "changed", "updated": "changed",
    "performance": "changed", "performance improvements": "changed", "breaking changes": "changed",
    "breaking": "changed", "deprecated": "deprecated", "deprecations": "deprecated", "removed": "removed",
    "removals": "removed", "fixed": "fixed", "fixes": "fixed", "bug fixes": "fixed", "bugfixes": "fixed",
    "bug fix": "fixed", "security": "security", "security fixes": "security",
}
DEFAULT_ORDER = ["added", "changed", "deprecated", "removed", "fixed", "security"]


def norm(label):
    return " ".join(re.sub(r"[^a-z ]+", " ", label.lower()).split())


def headings(lines):
    """[(index, level, text, underline)] for ATX ("## x") and underlined headings."""
    out = []
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        m = ATX_RE.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2), None))
            continue
        nxt = lines[i + 1].rstrip("\r\n") if i + 1 < len(lines) else ""
        u = UNDERLINE_RE.match(nxt)
        if u and line.strip() and not BULLET_RE.match(line) and len(u.group(1)) >= 3:
            out.append((i, 1 if u.group(1)[0] == "=" else 2, line.strip(), u.group(1)[0]))
    return out


def version_headings(lines):
    """[(index, level, version, underline_char)] for headings that name a SemVer version."""
    found = []
    for i, level, text, under in headings(lines):
        v = VERSION_RE.search(text)
        if v and parse_semver(v.group(1)):
            found.append((i, level, v.group(1), under))
    if not found:
        return []
    # The topmost version heading sets the level: files that changed style over the years
    # (axios: "## v1.19.0" on top of older "# [1.13.0]") keep the newer style.
    top = found[0][1]
    return [h for h in found if h[1] == top]


def section_label(line, level):
    """(template, label, type) if LINE starts a section like "### Fixed", "**Bugfixes**" or "Bug fixes:"."""
    m = ATX_RE.match(line)
    if m and len(m.group(1)) >= level and not VERSION_RE.search(m.group(2)):
        return m.group(1) + " {label}", m.group(2), SECTION_TYPES.get(norm(m.group(2)))
    m = BOLD_LABEL_RE.match(line)
    if m and norm(m.group(1)) in SECTION_TYPES:
        tpl = "**{label}:**" if line.rstrip().endswith(":**") else (
            "**{label}**:" if line.rstrip().endswith(":") else "**{label}**")
        return tpl, m.group(1), SECTION_TYPES[norm(m.group(1))]
    m = COLON_LABEL_RE.match(line)
    if m and norm(m.group(1)) in SECTION_TYPES:
        return "{label}:", m.group(1), SECTION_TYPES[norm(m.group(1))]
    return None


def count_blanks(lines, start, stop, step=1):
    """Blank lines from START towards STOP (exclusive)."""
    n, i = 0, start
    while i != stop and 0 <= i < len(lines) and not lines[i].strip():
        n, i = n + 1, i + step
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
    first, level, latest, under = heads[0]
    prev = heads[1][2] if len(heads) > 1 else None
    heading = lines[first].rstrip("\r\n")
    style = {"level": level, "latest": latest, "insert_at": first, "underline": under,
             "newline": "\r\n" if lines[first].endswith("\r\n") else "\n",
             "gap": count_blanks(lines, first - 1, -1, step=-1) if first else 1}

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
    style["heading"], style["date_fmt"] = heading, date_fmt

    # Sections, bullets and spacing, learned from the most recent releases.
    labels, order, bullets, breaking, seen_sections = {}, [], [], None, 0
    body = first + (2 if under else 1)
    blanks = [count_blanks(lines, body, len(lines)), 1, 0]
    for n, (i, _, _, u) in enumerate(heads[:10]):
        start = i + (2 if u else 1)
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        for j in range(start, end):
            raw = lines[j].rstrip("\r\n")
            sec = section_label(raw, level)
            if sec:
                tpl, label, t = sec
                seen_sections += 1
                if t and "breaking" in norm(label):
                    breaking = breaking or (tpl, label)
                    t = None
                if t and t not in labels:
                    labels[t] = (tpl, label)
                if t and n == 0 and t not in order:
                    order.append(t)
                if seen_sections == 1:
                    blanks[2] = count_blanks(lines, j + 1, end)
                elif seen_sections == 2 and n == 0:
                    blanks[1] = count_blanks(lines, j - 1, start - 1, step=-1)
                continue
            b = BULLET_RE.match(raw)
            if b:
                bullets.append(b)
    style["sectioned"] = seen_sections > 0
    template = next(iter(labels.values()))[0] if labels else "#" * (level + 1) + " {label}"
    style["sections"] = {t: labels.get(t, (template, TYPE_LABELS[t])) for t in DEFAULT_ORDER}
    style["order"] = merge_order(order)
    style["breaking_section"] = breaking
    style["blanks"] = tuple(blanks)
    style["bullet"] = bullets[0].group(1) if bullets else "-"
    texts = [b.group(2) for b in bullets]
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
        v = VERSION_RE.search(m.group(1)) if m else None
        if v and v.group(1) == latest:
            ref = re.sub(ver % re.escape(latest), "{version}", line.rstrip("\r\n"))
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
    out = [heading]
    if style["underline"]:
        out.append(style["underline"] * len(heading))
    out += [""] * after_heading
    entries = r.get("entries", [])
    if not style["sectioned"]:
        # The file lists changes straight under each version: do the same.
        for t in style["order"]:
            for e in entries:
                if e.get("type") == t:
                    out += entry_lines(e, style)
    else:
        groups = []
        if style["breaking_section"]:
            groups.append((style["breaking_section"], [e for e in entries if e.get("breaking")], True))
            entries = [e for e in entries if not e.get("breaking")]
        for t in style["order"]:
            groups.append((style["sections"][t], [e for e in entries if e.get("type") == t], False))
        first = True
        for (tpl, label), items, is_breaking in groups:
            if not items:
                continue
            if not first:
                out += [""] * before_section
            first = False
            out.append(tpl.replace("{label}", label))
            out += [""] * after_section
            for e in items:
                out += entry_lines(e, style, is_breaking)
    out += [""] * max(style["gap"], 1)
    return nl.join(out) + nl


def insert_releases(text, releases):
    """Return (new_text, added_versions, notes). TEXT is only ever added to."""
    style = detect_style(text)
    if style is None:
        return text, [], ["no version sections found, so its format can't be matched; nothing was added"]
    latest = style["latest"]
    present = {h[2] for h in version_headings(text.splitlines(keepends=True))}
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
