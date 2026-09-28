"""Shared test helpers. Tests never touch the network: gh lookups are disabled
via SHIPLOG_NO_GH and Slack tests use --dry-run or a local HTTP server."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKILL = os.path.join(ROOT, "plugins", "shiplog", "skills", "shiplog")
SCRIPTS = os.path.join(SKILL, "scripts")
PY = sys.executable
sys.path.insert(0, SCRIPTS)

ENV = dict(os.environ, SHIPLOG_NO_GH="1")


def run(script, *args, cwd, env=None):
    return subprocess.run([PY, os.path.join(SCRIPTS, script)] + list(args), cwd=cwd,
                          capture_output=True, text=True, env=env or ENV)


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout


def entry(**kw):
    e = {"type": "added", "title": "Export up to 50,000 rows at once",
         "description": "Large CSV exports from the Reports page now complete in one step.",
         "audiences": ["admins"], "action_required": False}
    e.update(kw)
    return e


class RepoCase(unittest.TestCase):
    """A temp git repo with one tagged commit and `init.py --name Demo --id demo`."""
    tag = "v1.0.0"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        git(self.d, "init", "-q", "-b", "main")
        git(self.d, "config", "user.email", "t@t.t")
        git(self.d, "config", "user.name", "T")
        git(self.d, "config", "commit.gpgsign", "false")
        self.commit("a", "feat: first")
        r = run("init.py", "--name", "Demo", "--id", "demo", cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        git(self.d, "add", ".")
        git(self.d, "commit", "-qm", "chore: add shiplog")
        if self.tag:
            git(self.d, "tag", self.tag)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, fname, msg, body=None):
        with open(os.path.join(self.d, fname), "a") as f:
            f.write(fname + msg)
        git(self.d, "add", ".")
        git(self.d, *(["commit", "-qm", msg] + (["-m", body] if body else [])))

    def write_release(self, data, version=None):
        path = os.path.join(self.d, ".changelog", "demo", (version or data["version"]) + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def config(self, **app_fields):
        path = os.path.join(self.d, ".shiplog.json")
        with open(path) as f:
            cfg = json.load(f)
        cfg["apps"][0].update(app_fields)
        with open(path, "w") as f:
            json.dump(cfg, f)

    def collect(self, *args):
        r = run("collect_changes.py", "--full", *args, cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def validate(self, *args):
        return run("validate.py", *args, cwd=self.d)
