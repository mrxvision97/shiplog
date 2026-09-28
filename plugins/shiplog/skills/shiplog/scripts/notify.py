#!/usr/bin/env python3
"""Post a release announcement to Slack.

Channels are configured per app in .shiplog.json under notify.slack. The config
holds only environment variable NAMES; secrets never live in the repo:

  "notify": {"slack": [
    {"name": "customer-updates", "webhook_env": "SLACK_WEBHOOK_UPDATES",
     "audiences": ["end-users", "admins"], "include_internal": false},
    {"name": "support", "token_env": "SLACK_BOT_TOKEN", "channel": "C0123456789",
     "audiences": ["everyone"], "include_internal": true, "mention": "@here"}
  ]}

Webhook channels get one message. Bot-token channels (chat.postMessage) get the
summary and action items as the main message and the details in a thread.
Each channel only gets entries for its audiences; "everyone" entries go to all.
Sent notifications are recorded in <releases_dir>/.notified.json and skipped
next time unless --force.

Usage:
  notify.py [--app ID | --tag TAG] [--version X.Y.Z] [--channel NAME]... [--dry-run] [--force]
"""
import argparse
import datetime
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import (ENTRY_TYPES, app_for_tag, audience_label, find_root, load_config,  # noqa: E402
                     load_releases, select_app)
import render  # noqa: E402
import validate  # noqa: E402

MAX_BLOCKS = 50
MAX_TEXT = 3000
ITEM_MAX = 600
RETRY_AFTER_MAX = 30
STATE_FILE = ".notified.json"
TYPE_EMOJI = {"added": ":sparkles:", "changed": ":arrows_counterclockwise:", "fixed": ":white_check_mark:",
              "deprecated": ":hourglass:", "removed": ":wastebasket:", "security": ":lock:"}
MENTIONS = {"@here": "<!here>", "@channel": "<!channel>", "@everyone": "<!everyone>"}


class SendError(Exception):
    pass


# Message building ----------------------------------------------------------

def mrkdwn(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": clip_block(text)}}


def clip_block(text):
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


def for_channel(release, channel):
    auds = set(channel.get("audiences") or ["everyone"])
    if "everyone" in auds:
        return list(release.get("entries", []))
    return [e for e in release.get("entries", [])
            if auds & set(e.get("audiences", [])) or "everyone" in e.get("audiences", [])]


def urgent(e):
    return bool(e.get("action_required") or e.get("breaking"))


def urgent_text(e, app, channel):
    flags = " _(breaking change)_" if e.get("breaking") else ""
    lines = ["*%s*%s" % (mrkdwn(e.get("title")), flags), mrkdwn(clip(e.get("description"), ITEM_MAX))]
    if e.get("action"):
        lines.append("*What to do:* " + mrkdwn(clip(e["action"], ITEM_MAX)))
    if e.get("action_deadline"):
        lines.append("*Deadline:* " + mrkdwn(html.unescape(render.fmt_date(e["action_deadline"], app))))
    lines.append("_Affects: %s_" % mrkdwn(", ".join(audience_label(app, a) for a in e.get("audiences", []))))
    if channel.get("include_internal") and e.get("internal_notes"):
        lines.append(":memo: _Internal:_ " + mrkdwn(clip(e["internal_notes"], ITEM_MAX)))
    return "\n".join(lines)


def item_text(e, channel):
    line = "• *%s*: %s" % (mrkdwn(e.get("title")), mrkdwn(clip(e.get("description"), ITEM_MAX)))
    if channel.get("include_internal") and e.get("internal_notes"):
        line += "\n    :memo: _Internal:_ " + mrkdwn(clip(e["internal_notes"], ITEM_MAX))
    return line


def group_blocks(entries, channel, labels):
    """One section per type; long groups split so no block exceeds MAX_TEXT.
    Returns [(block, entries_in_block)] so truncation can count what's left out."""
    out = []
    for t in ENTRY_TYPES:
        items = [e for e in entries if e.get("type") == t]
        if not items:
            continue
        head, text, count = "%s *%s*" % (TYPE_EMOJI[t], labels[t]), None, 0
        for e in items:
            line = item_text(e, channel)
            if text is not None and len(text) + 1 + len(line) > MAX_TEXT:
                out.append((section(text), count))
                text, count = None, 0
            text = (text + "\n" + line) if text is not None else head + "\n" + line
            count += 1
        out.append((section(text), count))
    return out


def fit(blocks_with_counts, tail, link):
    """Keep blocks within MAX_BLOCKS, ending with a "…and N more" note if cut."""
    room = MAX_BLOCKS - len(tail)
    if len(blocks_with_counts) <= room:
        return [b for b, _ in blocks_with_counts] + tail
    keep = blocks_with_counts[:room - 1]
    dropped = sum(c for _, c in blocks_with_counts[room - 1:])
    more = "…and %d more. " % dropped + ("<%s|See the full changelog>" % link if link else "See the full changelog.")
    return [b for b, _ in keep] + [section(more)] + tail


def build(app, release, entries, channel, url, threaded):
    """Return the list of payloads: [main] for webhooks, [main, thread] for bot mode."""
    labels = {t: render.ui_strings(app)["types"][t] for t in ENTRY_TYPES}
    version = release["version"]
    title = clip("%s %s" % (app["name"], version), 150)
    summary = release.get("summary") or "%d change%s" % (len(entries), "" if len(entries) == 1 else "s")
    mention = channel.get("mention")
    mention = MENTIONS.get(mention, mention if (mention or "").startswith("<") else mrkdwn(mention)) if mention else ""
    first = [{"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
             section(("%s " % mention if mention else "") + mrkdwn(summary))]
    act = [e for e in entries if urgent(e)]
    rest = [e for e in entries if not urgent(e)]
    act_blocks = []
    if act:
        act_blocks.append((section(":warning: *Action required*"), 0))
        act_blocks += [(section(urgent_text(e, app, channel)), 1) for e in act]
    link_block = [{"type": "context", "elements": [{"type": "mrkdwn", "text": "<%s|See the full changelog>" % url}]}] \
        if url else []

    fallback = "%s: %s" % (title, summary)
    if act:
        fallback += " | Action required: " + "; ".join(clip(e.get("title"), 80) for e in act)
    if url:
        fallback += " | " + url
    fallback = clip(fallback, MAX_TEXT)

    rest_blocks = group_blocks(rest, channel, labels)
    if threaded and rest_blocks:
        main = fit([(b, 0) for b in first] + act_blocks, link_block, url)
        if not act:
            main = first + [section("Details in the thread :thread:")] + link_block
        thread = fit(rest_blocks, link_block, url)
        return [{"text": fallback, "blocks": main},
                {"text": "%s: details" % title, "blocks": thread}]
    divider = [({"type": "divider"}, 0)] if act_blocks and rest_blocks else []
    return [{"text": fallback, "blocks": fit([(b, 0) for b in first] + act_blocks + divider + rest_blocks,
                                             link_block, url)}]


# Sending ---------------------------------------------------------------------

def http_post(url, payload, token=None):
    """POST JSON; one retry on HTTP 429 honoring Retry-After. Returns the response body."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    for attempt in (1, 2):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            if e.code == 429 and attempt == 1:
                try:
                    wait = float(e.headers.get("Retry-After") or 1)
                except ValueError:
                    wait = 1
                time.sleep(min(max(wait, 0), RETRY_AFTER_MAX))
                continue
            if e.code == 429:
                raise SendError("rate limited by Slack (HTTP 429) twice; try again later")
            raise SendError("Slack returned HTTP %d: %s" % (e.code, body or e.reason))
        except urllib.error.URLError as e:
            raise SendError("could not reach Slack: %s" % e.reason)
    raise SendError("unreachable")


def send(channel, payloads):
    if channel.get("token_env"):
        token = os.environ.get(channel["token_env"])
        if not token:
            raise SendError("environment variable %s is not set" % channel["token_env"])
        if not channel.get("channel"):
            raise SendError("bot-token channels need a 'channel' (Slack channel ID)")
        api = os.environ.get("SHIPLOG_SLACK_API", "https://slack.com/api").rstrip("/")
        thread_ts = None
        for p in payloads:
            body = dict(p, channel=channel["channel"], unfurl_links=False)
            if thread_ts:
                body["thread_ts"] = thread_ts
            try:
                resp = json.loads(http_post(api + "/chat.postMessage", body, token=token))
            except ValueError:
                raise SendError("Slack returned a non-JSON response")
            if not resp.get("ok"):
                raise SendError("Slack API error: %s" % resp.get("error", "unknown"))
            thread_ts = thread_ts or resp.get("ts")
        return
    env = channel.get("webhook_env")
    if not env:
        raise SendError("set webhook_env (incoming webhook) or token_env + channel (bot token)")
    url = os.environ.get(env)
    if not url:
        raise SendError("environment variable %s is not set" % env)
    for p in payloads:
        http_post(url, p)


# State -------------------------------------------------------------------------

def state_path(app, root):
    return os.path.join(root, app["releases_dir"], STATE_FILE)


def load_state(app, root):
    try:
        with open(state_path(app, root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(app, root, state):
    path = state_path(app, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


# CLI ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--tag", help="pick the app and version from a tag like web-v1.2.3")
    ap.add_argument("--version", help="release to announce (default: newest)")
    ap.add_argument("--channel", action="append", help="only this channel name (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="print the Slack payloads; send nothing")
    ap.add_argument("--force", action="store_true", help="send even if already sent")
    ap.add_argument("--root", help="repo root (default: found from the current folder)")
    args = ap.parse_args(argv)
    args.root = find_root(args.root)
    cfg = load_config(args.root)
    version = args.version
    if args.tag:
        app = app_for_tag(cfg, args.tag)
        if not app:
            print("shiplog: tag %s matches no app's tag_prefix; nothing to announce" % args.tag)
            return 0
        version = args.tag[len(app.get("tag_prefix", "v")):]
    else:
        app = select_app(cfg, args.app)

    channels = ((app.get("notify") or {}).get("slack")) or []
    if args.channel:
        channels = [c for c in channels if c.get("name") in args.channel]
    if not channels:
        print("shiplog: no Slack channels configured for %s (notify.slack in .shiplog.json)" % app["id"],
              file=sys.stderr)
        return 1

    releases, _ = load_releases(app, args.root)
    if not version:
        live = [r for r in releases if not r.get("yanked")]
        version = live[0]["version"] if live else None
    release = next((r for r in releases if r.get("version") == version), None)
    if not release:
        print("shiplog: no release file for version %s" % version, file=sys.stderr)
        return 1
    errs, _ = validate.validate_release(release, app)
    if errs:
        print("shiplog: %s has validation errors; run `shiplog.py validate` first" % version, file=sys.stderr)
        return 1

    url = render.release_url(app, releases, version) if app.get("base_url") else ""
    state = load_state(app, args.root)
    failed = 0
    for ch in channels:
        name = ch.get("name") or "?"
        entries = for_channel(release, ch)
        if not entries:
            print("- %s: skipped (nothing for its audiences)" % name)
            continue
        sent_at = state.get(version, {}).get(name)
        threaded = bool(ch.get("token_env"))
        payloads = build(app, release, entries, ch, url, threaded)
        if args.dry_run:
            how = ("bot token $%s -> %s" % (ch.get("token_env"), ch.get("channel")) if threaded
                   else "webhook $%s" % ch.get("webhook_env"))
            print("== %s (%s, %d entries) ==" % (name, how, len(entries)))
            env = ch.get("token_env") or ch.get("webhook_env")
            if env and not os.environ.get(env):
                print("note: %s is not set; a real send would fail" % env)
            if sent_at:
                print("note: already sent %s; a real run skips it unless --force" % sent_at)
            for i, p in enumerate(payloads):
                if i:
                    print("-- thread reply --")
                print(json.dumps(p, indent=2, ensure_ascii=False))
            continue
        if sent_at and not args.force:
            print("- %s: skipped (already sent %s; --force to resend)" % (name, sent_at))
            continue
        try:
            send(ch, payloads)
        except SendError as e:
            print("✗ %s: %s" % (name, e))
            failed += 1
            continue
        state.setdefault(version, {})[name] = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        save_state(app, args.root, state)
        print("✓ %s: sent %s (%d entries)" % (name, version, len(entries)))
    if failed:
        print("shiplog: %d channel(s) failed" % failed, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
