"""The JSON Schemas must agree with validate.py (the source of truth) on sample files.

Uses a tiny draft-07 subset validator so the test needs no dependencies."""
import copy
import json
import os
import re
import unittest

from helpers import ROOT, SKILL, entry

import validate
from _common import load_config

SCHEMA_DIR = os.path.join(SKILL, "schema")


def load(name):
    with open(os.path.join(SCHEMA_DIR, name)) as f:
        return json.load(f)


TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "number": (int, float)}


def errors(inst, sch, root):
    """Return a list of error strings (empty = valid)."""
    if "$ref" in sch:
        node = root
        for part in sch["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return errors(inst, node, root)
    out = []
    if "type" in sch:
        types = sch["type"] if isinstance(sch["type"], list) else [sch["type"]]
        if not any(isinstance(inst, TYPES[t]) and not (t != "boolean" and isinstance(inst, bool)) for t in types):
            return ["type %s" % sch["type"]]
    if "enum" in sch and inst not in sch["enum"]:
        out.append("enum")
    if "const" in sch and inst != sch["const"]:
        out.append("const")
    if isinstance(inst, str):
        if len(inst) < sch.get("minLength", 0) or len(inst) > sch.get("maxLength", 1 << 30):
            out.append("length")
        if "pattern" in sch and not re.search(sch["pattern"], inst):
            out.append("pattern")
    if isinstance(inst, list):
        if len(inst) < sch.get("minItems", 0):
            out.append("minItems")
        for x in inst:
            out += errors(x, sch.get("items", {}), root)
    if isinstance(inst, dict):
        out += ["required %s" % k for k in sch.get("required", []) if k not in inst]
        for k, sub in sch.get("properties", {}).items():
            if k in inst:
                out += errors(inst[k], sub, root)
    for sub in sch.get("allOf", []):
        out += errors(inst, sub, root)
    if "anyOf" in sch and all(errors(inst, s, root) for s in sch["anyOf"]):
        out.append("anyOf")
    if "if" in sch:
        branch = "then" if not errors(inst, sch["if"], root) else "else"
        out += errors(inst, sch.get(branch, {}), root)
    return out


APP = {"id": "demo", "name": "Demo", "audiences": [{"id": "admins"}, {"id": "end-users"}]}
GOOD = {"version": "1.1.0", "date": "2026-09-28", "entries": [
    entry(refs=["#412"], internal_notes="note"),
    entry(type="changed", title="Older apps can no longer sign in", audiences=["end-users"],
          action_required=True, breaking=True, action="Update the app to version 4.2.",
          action_deadline="2026-12-01", links=[{"label": "Help", "url": "https://x.test"}]),
    entry(title="Imported", description="Fixed login", _needs_review=True)]}


def mutate(fn):
    r = copy.deepcopy(GOOD)
    fn(r)
    return r


BAD = {
    "bad version": mutate(lambda r: r.update(version="v1.1")),
    "bad date": mutate(lambda r: r.update(date="28/09/2026")),
    "no entries": mutate(lambda r: r.update(entries=[])),
    "long summary": mutate(lambda r: r.update(summary="x" * 121)),
    "bad type": mutate(lambda r: r["entries"][0].update(type="feature")),
    "no audiences": mutate(lambda r: r["entries"][0].pop("audiences")),
    "empty audiences": mutate(lambda r: r["entries"][0].update(audiences=[])),
    "short description": mutate(lambda r: r["entries"][0].update(description="Too short")),
    "long title": mutate(lambda r: r["entries"][0].update(title="x" * 101)),
    "no action": mutate(lambda r: r["entries"][0].update(action_required=True)),
    "breaking without action": mutate(lambda r: r["entries"][1].update(action_required=False)),
    "bad link": mutate(lambda r: r["entries"][1].update(links=[{"label": "x", "url": "ftp://x"}])),
    "bad deadline": mutate(lambda r: r["entries"][1].update(action_deadline="soon")),
    "refs not strings": mutate(lambda r: r["entries"][0].update(refs=[1])),
}


class SchemaAgreesWithValidator(unittest.TestCase):
    def setUp(self):
        self.schema = load("release.schema.json")

    def check(self, release):
        v_errs, _ = validate.validate_release(release, APP)
        s_errs = errors(release, self.schema, self.schema)
        return v_errs, s_errs

    def test_good_samples_pass_both(self):
        with open(os.path.join(ROOT, "examples", ".changelog", "web", "2.0.0.json")) as f:
            example = json.load(f)
        example_app = load_config(os.path.join(ROOT, "examples"))["apps"][0]
        self.assertEqual(validate.validate_release(example, example_app)[0], [])
        self.assertEqual(errors(example, self.schema, self.schema), [])
        v, s = self.check(GOOD)
        self.assertEqual((v, s), ([], []))

    def test_bad_samples_fail_both(self):
        for name, release in BAD.items():
            v, s = self.check(release)
            self.assertTrue(v, "validator accepted: " + name)
            self.assertTrue(s, "schema accepted: " + name)

    def test_config_schema_accepts_samples(self):
        schema = load("config.schema.json")
        for path in (os.path.join(ROOT, "examples", ".shiplog.json"), os.path.join(ROOT, ".shiplog.json")):
            if os.path.exists(path):
                with open(path) as f:
                    self.assertEqual(errors(json.load(f), schema, schema), [], path)
        self.assertTrue(errors({"apps": [{"id": "x"}]}, schema, schema))

    def test_schema_version_pattern_matches_common(self):
        from _common import SEMVER_RE
        self.assertEqual(self.schema["properties"]["version"]["pattern"], SEMVER_RE.pattern)


if __name__ == "__main__":
    unittest.main()
