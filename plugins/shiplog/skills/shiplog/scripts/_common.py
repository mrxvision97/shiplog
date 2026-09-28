"""Shared helpers for Shiplog scripts. Standard library only (Python 3.10+)."""
import json
import os
import re
import subprocess
import sys

CONFIG_FILE = ".shiplog.json"
ENTRY_TYPES = ["added", "changed", "fixed", "deprecated", "removed", "security"]
TYPE_LABELS = {
    "added": "Added",
    "changed": "Changed",
    "fixed": "Fixed",
    "deprecated": "Deprecated",
    "removed": "Removed",
    "security": "Security",
}
EVERYONE = "everyone"
# Where editors fetch the schemas from ("$schema" in release files and .shiplog.json).
SCHEMA_BASE_URL = "https://raw.githubusercontent.com/mrxvision97/shiplog/main/plugins/shiplog/skills/shiplog/schema/"
RELEASE_SCHEMA_URL = SCHEMA_BASE_URL + "release.schema.json"
CONFIG_SCHEMA_URL = SCHEMA_BASE_URL + "config.schema.json"

# Page labels. Override any of them per app with "strings" in .shiplog.json.
DEFAULT_STRINGS = {
    "skip_link": "Skip to changelog",
    "title": "{name} changelog",
    "internal_suffix": " (internal)",
    "intro": "New features, improvements and fixes in {name}.",
    "logo_alt": "{name} logo",
    "follow": "Follow updates:",
    "feed_link": "Atom/RSS feed",
    "json_link": "JSON",
    "audience_feeds": "Feeds by audience:",
    "filter_heading": "Filter changes",
    "type_legend": "Type of change",
    "affects": "Affects",
    "anyone": "Anyone",
    "search": "Search",
    "action_only": "Action required only",
    "showing_all": "Showing all {n} changes.",
    "showing_some": "Showing {shown} of {total} changes.",
    "no_releases": "No releases yet.",
    "withdrawn": "(withdrawn)",
    "breaking": "Breaking change",
    "action_required": "Action required",
    "whos_affected": "Who's affected:",
    "what_to_do": "What you need to do",
    "deadline": "Deadline:",
    "internal_notes": "Internal notes",
    "refs": "Refs:",
    "internal_banner": "Internal view. Includes support notes and references. Do not share publicly.",
    "last_release": "Last release {date}.",
    "published_with": "Published with {link}.",
    "archive": "Older releases",
    "latest": "Latest",
    "everyone": "Everyone",
    "types": dict(TYPE_LABELS),
    "months": ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"],
    "date_format": "{month} {day}, {year}",
}


def ui_strings(app):
    """DEFAULT_STRINGS merged with the app's "strings" overrides (cached on the app)."""
    if "_strings" not in app:
        s = dict(DEFAULT_STRINGS)
        custom = app.get("strings") or {}
        s.update(custom)
        s["types"] = dict(DEFAULT_STRINGS["types"], **(custom.get("types") or {}))
        app["_strings"] = s
    return app["_strings"]


SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

# Uppercase-dash-number tokens that are standards, not tickets (UTF-8, ISO-8601, SHA-256...).
NOT_TICKETS = {"UTF", "ISO", "SHA", "MD", "RFC", "CVE", "GHSA", "COVID", "HTTP", "TLS", "SSL",
               "IPV", "WCAG", "PCI", "SOC", "ES", "ECMA", "IEEE", "X"}

APP_DEFAULTS = {
    "path": ".",
    "tag_prefix": "v",
    "base_url": "",
    "changelog_md": True,
    "audiences": [],
    "theme": {},
}


def die(msg, code=2):
    print("shiplog: " + msg, file=sys.stderr)
    sys.exit(code)


def git_toplevel(start="."):
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def find_root(root=None):
    """The directory to work in. An explicit --root wins. Otherwise the nearest
    folder with a .shiplog.json (walking up from the current one), then the git
    top level, then the current folder. Returned relative to the current folder."""
    if root:
        return root
    here = os.path.abspath(".")
    top = git_toplevel(here)
    d = here
    while True:
        if os.path.exists(os.path.join(d, CONFIG_FILE)):
            return os.path.relpath(d)
        parent = os.path.dirname(d)
        if parent == d or (top and os.path.samefile(d, top)):
            break
        d = parent
    return os.path.relpath(top) if top else "."


def _toml_section(text, section):
    """Minimal TOML reader for simple `key = "value"` lines in one [section]."""
    m = re.search(r"^\[%s\]\s*$(.*?)(?=^\[|\Z)" % re.escape(section), text, re.M | re.S)
    if not m:
        return {}
    return dict(re.findall(r'^\s*(\w+)\s*=\s*"([^"]*)"', m.group(1), re.M))


# Package names that say nothing about the product (workspace roots, starters).
GENERIC_NAMES = {"web", "app", "frontend", "front-end", "client", "server", "backend", "api", "root", "site",
                 "website", "monorepo", "workspace", "main", "my-app", "project"}
# Versions that starter templates put in manifests; not evidence of a release.
PLACEHOLDER_VERSIONS = {"0.0.0", "0.0.1", "0.1.0", "1.0.0"}


def detect_project(root="."):
    """Best-effort name, description and version from common manifests.
    Keys are missing when nothing was found."""
    def read(name):
        try:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return None
    info = {}
    text = read("package.json")
    if text:
        try:
            pkg = json.loads(text)
        except ValueError:
            pkg = {}
        if isinstance(pkg, dict):
            info = {k: pkg[k] for k in ("name", "description", "version") if isinstance(pkg.get(k), str) and pkg[k]}
            if "name" in info:
                info["name"] = info["name"].split("/")[-1]  # drop npm scope
    for fname, sections in (("pyproject.toml", ("project", "tool.poetry")), ("Cargo.toml", ("package",))):
        text = read(fname)
        for sec in sections if text and not info.get("name") else ():
            found = _toml_section(text, sec)
            if found.get("name"):
                info = {k: found[k] for k in ("name", "description", "version") if found.get(k)}
                break
    text = read("go.mod")
    if text and not info.get("name"):
        m = re.search(r"^module\s+(\S+)", text, re.M)
        if m:
            info["name"] = m.group(1).rstrip("/").split("/")[-1]
    if not info.get("name") or info["name"].lower() in GENERIC_NAMES:
        try:
            r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root, capture_output=True, text=True)
            m = re.search(r"([^/:]+?)(?:\.git)?/?$", r.stdout.strip()) if r.returncode == 0 else None
            if m:
                info["name"] = m.group(1)
        except OSError:
            pass
    if not info.get("name") or info["name"].lower() in GENERIC_NAMES:
        top = git_toplevel(root)
        if top:
            info["name"] = os.path.basename(top)
    if not info.get("name"):
        info["name"] = os.path.basename(os.path.abspath(root))
    if info.get("version") and (not parse_semver(info["version"]) or info["version"] in PLACEHOLDER_VERSIONS):
        del info["version"]
    return info


def semver_tags(root="."):
    """[(prefix, version, tag)] for every tag that ends in a SemVer version."""
    try:
        r = subprocess.run(["git", "tag", "--list"], cwd=root, capture_output=True, text=True)
    except OSError:
        return []
    out = []
    for tag in r.stdout.split():
        m = re.match(r"^(.*?)(\d+\.\d+\.\d+.*)$", tag)
        if m and parse_semver(m.group(2)):
            out.append((m.group(1), m.group(2), tag))
    return out


def detect_tag_prefix(root="."):
    """The most common prefix of existing version tags ("v", "", "release-"), or None."""
    counts = {}
    for prefix, _, _ in semver_tags(root):
        counts[prefix] = counts.get(prefix, 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=lambda p: counts[p])


GENERATED_MARKER = "Generated by Shiplog"


def is_generated(path):
    """True if PATH was written by Shiplog (so it's safe to overwrite)."""
    try:
        with open(path, encoding="utf-8") as f:
            return GENERATED_MARKER in f.read(4096)
    except (OSError, UnicodeDecodeError):
        return False


def load_config(root="."):
    path = os.path.join(root, CONFIG_FILE)
    if not os.path.exists(path):
        die("no %s found in %s. Run init.py first." % (CONFIG_FILE, os.path.abspath(root)))
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        die("%s is not valid JSON: %s" % (CONFIG_FILE, e))
    if "apps" not in cfg:
        # Single-app shorthand: the whole file describes one app.
        cfg = {"apps": [cfg]}
    apps = []
    for raw in cfg["apps"]:
        app = dict(APP_DEFAULTS)
        app.update(raw)
        if "id" not in app or "name" not in app:
            die("every app in %s needs an 'id' and a 'name'" % CONFIG_FILE)
        app.setdefault("releases_dir", os.path.join(".changelog", app["id"]))
        app.setdefault("output_dir", os.path.join("changelog", app["id"]))
        apps.append(app)
    cfg["apps"] = apps
    return cfg


def select_app(cfg, app_id=None):
    apps = cfg["apps"]
    if app_id is None:
        if len(apps) == 1:
            return apps[0]
        die("this config has several apps; pass --app one of: " + ", ".join(a["id"] for a in apps))
    for a in apps:
        if a["id"] == app_id:
            return a
    die("unknown app '%s'. Known: %s" % (app_id, ", ".join(a["id"] for a in apps)))


def audience_ids(app):
    return [a["id"] for a in app.get("audiences", [])] + [EVERYONE]


def audience_label(app, aid):
    if aid == EVERYONE:
        return ui_strings(app)["everyone"]
    for a in app.get("audiences", []):
        if a["id"] == aid:
            return a.get("label", aid)
    return aid


def parse_semver(v):
    m = SEMVER_RE.match(v or "")
    if not m:
        return None
    major, minor, patch, pre, _ = m.groups()
    return (int(major), int(minor), int(patch), pre)


def semver_key(v):
    """Sort key. Pre-releases sort before the matching release."""
    p = parse_semver(v)
    if not p:
        return (-1, -1, -1, 0, "")
    major, minor, patch, pre = p
    if pre is None:
        return (major, minor, patch, 1, "")
    parts = []
    for part in pre.split("."):
        parts.append("%010d" % int(part) if part.isdigit() else part)
    return (major, minor, patch, 0, ".".join(parts))


def load_releases(app, root="."):
    """Return (releases, load_errors). Releases sorted newest first."""
    rdir = os.path.join(root, app["releases_dir"])
    releases, errors = [], []
    if not os.path.isdir(rdir):
        return releases, errors
    for name in sorted(os.listdir(rdir)):
        # Dotfiles (e.g. .notified.json) hold Shiplog state, not releases.
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(rdir, name)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append((path, "invalid JSON: %s" % e))
            continue
        if not isinstance(data, dict):
            errors.append((path, "top level must be an object"))
            continue
        data["_file"] = path
        releases.append(data)
    releases.sort(key=lambda r: semver_key(str(r.get("version", ""))), reverse=True)
    return releases, errors


def app_for_tag(cfg, tag):
    """The app whose tag_prefix matches TAG (longest prefix wins), or None."""
    matches = [a for a in cfg["apps"] if tag.startswith(a.get("tag_prefix", "v"))
               and parse_semver(tag[len(a.get("tag_prefix", "v")):])]
    if not matches:
        return None
    return max(matches, key=lambda a: len(a.get("tag_prefix", "v")))
