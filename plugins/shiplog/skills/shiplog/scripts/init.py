#!/usr/bin/env python3
"""Set up Shiplog in a repository.

Usage:
  init.py [--name "Acme Web"] [--id web] [--path .] [--tag-prefix v]
          [--base-url https://acme.com/changelog] [--with-ci] [--root DIR] [--force]

Creates .shiplog.json at the repo root (or adds an app to an existing multi-app
config) and the releases directory. Without --name, the name and description
come from package.json, pyproject.toml, Cargo.toml, go.mod, the git remote or the
folder name. Without --tag-prefix, the prefix of existing version tags is used. --with-ci vendors the scripts into .shiplog/scripts/ and
writes .github/workflows/shiplog.yml so CI works without Claude installed.
"""
import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
CONFIG_FILE = ".shiplog.json"
sys.path.insert(0, HERE)
from _common import (CONFIG_SCHEMA_URL, detect_project, detect_tag_prefix, find_changelog,  # noqa: E402
                     find_root, is_generated)

DEFAULT_AUDIENCES = [
    {"id": "end-users", "label": "End users"},
    {"id": "admins", "label": "Account admins"},
    {"id": "developers", "label": "API & integration developers"},
    {"id": "support", "label": "Support team"},
]


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "app"


def humanize(name):
    """acme-dashboard -> Acme Dashboard; leaves names with capitals alone."""
    if name != name.lower():
        return name
    return " ".join(w.capitalize() for w in re.split(r"[-_\s]+", name) if w) or name


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="display name (default: detected from the project)")
    ap.add_argument("--id")
    ap.add_argument("--path", default=".")
    ap.add_argument("--tag-prefix", default=None)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--with-ci", action="store_true")
    ap.add_argument("--root", help="repo root (default: found from the current folder)")
    ap.add_argument("--force", action="store_true", help="overwrite existing vendored files")
    args = ap.parse_args(argv)
    args.root = find_root(args.root)

    project = detect_project(os.path.join(args.root, args.path))
    name = args.name or humanize(project["name"])
    app_id = args.id or slugify(args.name or project["name"])
    prefix = args.tag_prefix
    if prefix is None:
        detected = detect_tag_prefix(args.root) if args.path == "." else None
        prefix = detected if detected is not None else ("v" if args.path == "." else app_id + "-v")
    cfg_path = os.path.join(args.root, CONFIG_FILE)
    app = {
        "id": app_id,
        "name": name,
        "description": project.get("description", ""),
        "path": args.path,
        "tag_prefix": prefix,
        "releases_dir": os.path.join(".changelog", app_id).replace(os.sep, "/"),
        "output_dir": os.path.join("changelog", app_id).replace(os.sep, "/"),
        "base_url": args.base_url,
        "changelog_md": True,
        "audiences": DEFAULT_AUDIENCES,
        "theme": {"accent_color": "#4f46e5"},
    }

    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        apps = cfg["apps"] if "apps" in cfg else [cfg]
        if any(a.get("id") == app_id for a in apps):
            print("shiplog: app '%s' already in %s; leaving config unchanged" % (app_id, CONFIG_FILE))
        else:
            apps.append(app)
            cfg = {"$schema": cfg.get("$schema", CONFIG_SCHEMA_URL), "apps": apps}
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
                f.write("\n")
            print("  added app '%s' to %s" % (app_id, cfg_path))
    else:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"$schema": CONFIG_SCHEMA_URL, "apps": [app]}, f, indent=2)
            f.write("\n")
        print("  wrote %s" % cfg_path)

    rdir = os.path.join(args.root, app["releases_dir"])
    os.makedirs(rdir, exist_ok=True)
    keep = os.path.join(rdir, ".gitkeep")
    if not os.listdir(rdir):
        open(keep, "w").close()
    print("  releases go in %s/<version>.json" % app["releases_dir"])
    print("  app: %s (id %s), version tags look like %s1.2.3" % (name, app_id, prefix))
    existing = find_changelog(os.path.join(args.root, args.path))
    md = os.path.join(args.root, args.path, existing or "CHANGELOG.md")
    if existing and not is_generated(md):
        print("  found a hand-written %s. Shiplog keeps it and adds each new release in the file's own\n"
              "  format, without changing existing entries. To show its history on the changelog page too, run\n"
              "    shiplog.py import --app %s" % (os.path.relpath(md, args.root), app_id))

    if args.with_ci:
        vend = os.path.join(args.root, ".shiplog", "scripts")
        os.makedirs(vend, exist_ok=True)
        for name in sorted(n for n in os.listdir(HERE) if n.endswith(".py")):
            dst = os.path.join(vend, name)
            if os.path.exists(dst) and not args.force:
                print("  exists, skipped %s (use --force to update)" % dst)
                continue
            shutil.copy2(os.path.join(HERE, name), dst)
            print("  vendored %s" % dst)
        tpl_dst = os.path.join(vend, "page.html")
        if not os.path.exists(tpl_dst) or args.force:
            shutil.copy2(os.path.join(SKILL_DIR, "assets", "templates", "page.html"), tpl_dst)
            print("  vendored %s" % tpl_dst)
        wf_dir = os.path.join(args.root, ".github", "workflows")
        os.makedirs(wf_dir, exist_ok=True)
        wf = os.path.join(wf_dir, "shiplog.yml")
        if os.path.exists(wf) and not args.force:
            print("  exists, skipped %s" % wf)
        else:
            shutil.copy2(os.path.join(SKILL_DIR, "assets", "github-workflow.yml"), wf)
            print("  wrote %s" % wf)

    print("\nNext: edit the 'audiences' list in %s to match who your users really are." % CONFIG_FILE)


if __name__ == "__main__":
    sys.exit(main())
