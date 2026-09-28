"""Shared helpers for Shiplog scripts. Standard library only (Python 3.10+)."""
import json
import os
import re
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
# Replace YOUR_ORG with your fork so editors can fetch the schemas.
SCHEMA_BASE_URL = "https://raw.githubusercontent.com/YOUR_ORG/shiplog/main/plugins/shiplog/skills/shiplog/schema/"
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
