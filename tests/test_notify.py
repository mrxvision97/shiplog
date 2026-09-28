"""Slack notifications. No network: --dry-run, or a local HTTP server standing in for Slack."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from helpers import ENV, RepoCase, entry, run

import notify

APP = {"id": "demo", "name": "Demo", "base_url": "https://acme.test/changelog",
       "audiences": [{"id": "admins", "label": "Admins"}, {"id": "end-users", "label": "End users"},
                     {"id": "developers", "label": "Developers"}]}
RELEASE = {"version": "2.0.0", "date": "2026-09-28", "summary": "Keys expire, exports grow", "entries": [
    entry(title="Bigger exports", internal_notes="SECRET-NOTE"),
    entry(type="fixed", title="Login works again", audiences=["everyone"]),
    entry(type="changed", title="API keys expire", audiences=["developers"], breaking=True,
          action_required=True, action="Create a new key in Settings, API.", action_deadline="2027-03-31"),
]}
CHANNELS = [
    {"name": "customer-updates", "webhook_env": "HOOK_A", "audiences": ["end-users", "admins"]},
    {"name": "support", "webhook_env": "HOOK_B", "audiences": ["everyone"], "include_internal": True,
     "mention": "@here"},
]


def texts(payload):
    out = []
    for b in payload["blocks"]:
        t = b.get("text", {}).get("text") if "text" in b else " ".join(e["text"] for e in b.get("elements", []))
        out.append(t or "")
    return "\n".join(out)


class BuildTest(unittest.TestCase):
    def test_routing_and_order(self):
        cust = notify.for_channel(RELEASE, CHANNELS[0])
        self.assertEqual([e["title"] for e in cust], ["Bigger exports", "Login works again"])
        self.assertEqual(len(notify.for_channel(RELEASE, CHANNELS[1])), 3)

        [msg] = notify.build(APP, RELEASE, notify.for_channel(RELEASE, CHANNELS[1]), CHANNELS[1],
                             "https://acme.test/changelog/#v2-0-0", threaded=False)
        body = texts(msg)
        self.assertEqual(msg["blocks"][0], {"type": "header", "text": {
            "type": "plain_text", "text": "Demo 2.0.0", "emoji": True}})
        self.assertTrue(msg["blocks"][1]["text"]["text"].startswith("<!here> Keys expire"))
        # Action-required/breaking entries come first, with action and deadline.
        self.assertLess(body.index("API keys expire"), body.index("Bigger exports"))
        self.assertIn("*What to do:* Create a new key", body)
        self.assertIn("*Deadline:* March 31, 2027", body)
        self.assertIn("SECRET-NOTE", body)
        self.assertIn("<https://acme.test/changelog/#v2-0-0|See the full changelog>", body)
        self.assertIn("Action required: API keys expire", msg["text"])

        [msg] = notify.build(APP, RELEASE, cust, CHANNELS[0], "", threaded=False)
        self.assertNotIn("SECRET-NOTE", json.dumps(msg))

    def test_threaded_bot_mode(self):
        main, thread = notify.build(APP, RELEASE, RELEASE["entries"], {"name": "x", "token_env": "T"}, "u",
                                    threaded=True)
        self.assertIn("API keys expire", texts(main))
        self.assertNotIn("Bigger exports", texts(main))
        self.assertIn("Bigger exports", texts(thread))

    def test_slack_limits(self):
        many = dict(RELEASE, entries=[entry(title="Change %d" % i, description="Long text. " * 80,
                                            action_required=(i % 2 == 0), action="Do the thing now.")
                                      for i in range(120)])
        [msg] = notify.build(APP, many, many["entries"], CHANNELS[1], "https://x.test/#v", threaded=False)
        self.assertLessEqual(len(msg["blocks"]), notify.MAX_BLOCKS)
        for b in msg["blocks"]:
            self.assertLessEqual(len(b.get("text", {}).get("text", "")), notify.MAX_TEXT)
        self.assertRegex(texts(msg), r"…and \d+ more\. <https://x.test/#v\|See the full changelog>")
        self.assertLessEqual(len(msg["text"]), notify.MAX_TEXT)

    def test_escapes_mrkdwn(self):
        rel = dict(RELEASE, entries=[entry(title="Use <b> & <!channel>")])
        [msg] = notify.build(APP, rel, rel["entries"], CHANNELS[1], "", threaded=False)
        self.assertIn("Use &lt;b&gt; &amp; &lt;!channel&gt;", texts(msg))


class FakeSlack(BaseHTTPRequestHandler):
    """Records requests. Path /fail -> 500, /limited -> 429 once, else 200."""
    calls = []
    limited = set()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeSlack.calls.append((self.path, body, self.headers.get("Authorization")))
        if self.path == "/fail":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"server_error")
        elif self.path == "/limited" and self.path not in FakeSlack.limited:
            FakeSlack.limited.add(self.path)
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.end_headers()
        elif self.path.endswith("chat.postMessage"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "ts": "111.222"}).encode())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class NotifyCliTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.server = HTTPServer(("127.0.0.1", 0), FakeSlack)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port
        FakeSlack.calls, FakeSlack.limited = [], set()
        self.config(base_url="https://acme.test/changelog", notify={"slack": CHANNELS + [
            {"name": "devs", "token_env": "BOT", "channel": "C1", "audiences": ["developers"]}]})
        self.write_release(RELEASE)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def env(self, **kw):
        return dict(ENV, SHIPLOG_SLACK_API=self.base, **kw)

    def test_dry_run_prints_payloads_and_sends_nothing(self):
        r = run("shiplog.py", "notify", "--dry-run", cwd=self.d, env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("== customer-updates (webhook $HOOK_A, 2 entries) ==", r.stdout)
        self.assertIn("note: HOOK_A is not set", r.stdout)
        self.assertIn("-- thread reply --", r.stdout)
        self.assertEqual(FakeSlack.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.d, ".changelog", "demo", ".notified.json")))

    def test_send_record_and_skip(self):
        env = self.env(HOOK_A=self.base + "/a", HOOK_B=self.base + "/limited", BOT="xoxb-test")
        r = run("notify.py", cwd=self.d, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("✓ customer-updates: sent 2.0.0", r.stdout)
        paths = [c[0] for c in FakeSlack.calls]
        self.assertEqual(paths.count("/limited"), 2)  # rate limited once, then retried
        bot = [c for c in FakeSlack.calls if c[0] == "/chat.postMessage"]
        self.assertEqual(len(bot), 2)  # main message + thread reply
        self.assertEqual(bot[0][2], "Bearer xoxb-test")
        self.assertEqual(bot[1][1]["thread_ts"], "111.222")
        with open(os.path.join(self.d, ".changelog", "demo", ".notified.json")) as f:
            state = json.load(f)
        self.assertEqual(sorted(state["2.0.0"]), ["customer-updates", "devs", "support"])
        # The state file is not mistaken for a release.
        self.assertEqual(run("validate.py", cwd=self.d).returncode, 0)

        FakeSlack.calls = []
        r = run("notify.py", cwd=self.d, env=env)
        self.assertIn("skipped (already sent", r.stdout)
        self.assertEqual(FakeSlack.calls, [])
        run("notify.py", "--force", "--channel", "customer-updates", cwd=self.d, env=env)
        self.assertEqual([c[0] for c in FakeSlack.calls], ["/a"])

    def test_one_failure_does_not_block_others(self):
        env = self.env(HOOK_A=self.base + "/fail", HOOK_B=self.base + "/b")  # BOT unset
        r = run("notify.py", cwd=self.d, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("✗ customer-updates: Slack returned HTTP 500: server_error", r.stdout)
        self.assertIn("✓ support: sent", r.stdout)
        self.assertIn("✗ devs: environment variable BOT is not set", r.stdout)
        with open(os.path.join(self.d, ".changelog", "demo", ".notified.json")) as f:
            self.assertEqual(list(json.load(f)["2.0.0"]), ["support"])

    def test_tag_mode_and_audience_skip(self):
        self.write_release(dict(RELEASE, version="2.1.0", entries=[entry(title="Admins only")]))
        r = run("notify.py", "--tag", "v2.1.0", "--dry-run", cwd=self.d, env=self.env())
        self.assertIn("- devs: skipped (nothing for its audiences)", r.stdout)
        self.assertIn("Demo 2.1.0", r.stdout)

    def test_invalid_release_is_not_announced(self):
        self.write_release(dict(RELEASE, version="2.2.0", entries=[entry(description="short")]))
        r = run("notify.py", "--version", "2.2.0", "--dry-run", cwd=self.d, env=self.env())
        self.assertEqual(r.returncode, 1)
        self.assertIn("validation errors", r.stderr)


if __name__ == "__main__":
    unittest.main()
