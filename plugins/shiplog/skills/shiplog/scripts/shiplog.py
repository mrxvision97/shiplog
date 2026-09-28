#!/usr/bin/env python3
"""Shiplog: one entry point for every step.

Usage:
  shiplog.py init     --name "Acme Web" [--with-ci] ...   set up .shiplog.json
  shiplog.py collect  [--app ID] [--full]                 changes since the last tag
  shiplog.py validate [--app ID | --all] [--tag TAG]      check release files
  shiplog.py render   [--app ID | --all] [--internal]     write page, feeds, CHANGELOG.md
  shiplog.py release  --version X.Y.Z [--app ID]          validate + render in one step
  shiplog.py notify   [--app ID] [--version X] [--dry-run] post to Slack
  shiplog.py import   [--app ID] [--file CHANGELOG.md]    convert Keep a Changelog

Run `shiplog.py <command> --help` for a command's options.
"""
import argparse
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

COMMANDS = {
    "init": "init",
    "collect": "collect_changes",
    "validate": "validate",
    "render": "render",
    "import": "import_changelog",
}


def release(argv):
    """Validate one release (and the rest of the app), then render. One short report."""
    from _common import app_for_tag, load_config, select_app
    import render
    import validate
    ap = argparse.ArgumentParser(prog="shiplog.py release", description=release.__doc__)
    ap.add_argument("--version", required=True, help="X.Y.Z, or a tag like v1.2.3")
    ap.add_argument("--app")
    ap.add_argument("--internal", action="store_true", help="also write internal.html")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    cfg = load_config(args.root)
    app = (not args.app and app_for_tag(cfg, args.version)) or select_app(cfg, args.app)
    prefix = app.get("tag_prefix", "v")
    version = args.version[len(prefix):] if prefix and args.version.startswith(prefix) else args.version

    n_err, n_warn, lines = validate.check_app(app, args.root, version, args.strict)
    target = os.path.join(os.path.normpath(app["releases_dir"]), version + ".json")
    shown = [ln for ln in lines if ln.startswith("ERROR") or target in ln]
    others = sum(1 for ln in lines if ln.startswith("warning") and target not in ln)
    status = "FAILED" if n_err else "ok"
    print("%s %s %s: %s (%d error(s), %d warning(s))" % ("✗" if n_err else "✓", app["name"], version,
                                                       status, n_err, n_warn))
    for ln in shown:
        print("  " + ln)
    if others:
        print("  (%d warning(s) in older releases; run `shiplog.py validate` to see them)" % others)
    if n_err:
        sys.exit(1)
    written = render.render_app(app, args.root, args.internal, quiet=True)
    print("  rendered %d file(s): %s" % (len(written), ", ".join(os.path.relpath(p, args.root) for p in written)))
    if args.internal:
        print("  internal.html contains support notes: don't deploy it publicly.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "release":
        return release(rest)
    if cmd not in COMMANDS:
        print("shiplog: unknown command %r\n\n%s" % (cmd, __doc__.strip()), file=sys.stderr)
        return 2
    sys.argv[0] = "shiplog.py " + cmd  # argparse uses it as the program name
    return importlib.import_module(COMMANDS[cmd]).main(rest)


if __name__ == "__main__":
    sys.exit(main())
