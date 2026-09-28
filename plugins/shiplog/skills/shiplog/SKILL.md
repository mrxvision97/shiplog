---
name: shiplog
description: Write and publish structured, plain-language changelogs for any app or monorepo, with an accessible changelog web page, Atom feed, CHANGELOG.md and CI enforcement. Every entry records what changed, who is affected, and what action they need to take. Use this skill whenever the user mentions a changelog, release notes, "what's new", "what shipped", preparing or tagging a release, bumping a version, writing up changes since the last tag, or setting up a changelog page, even if they don't say "changelog" explicitly (e.g. "we're releasing 2.4 today", "summarize what changed for customers", "support needs to know what's shipping").
---

# Shiplog

Shiplog turns raw git history into release notes that customers, support, and internal teams can actually use. Each release is stored as a small JSON file in the repo (the source of truth). Scripts validate it and generate the outputs: `CHANGELOG.md`, an accessible static HTML page, an Atom feed and a JSON feed.

The scripts are Python 3.8+ and use only the standard library. Run them from the user's repository root. `SCRIPTS` below means this skill's `scripts/` directory.

## Why the structure matters

Changelogs usually fail in two ways. They get skipped, or they're written for engineers ("refactor auth middleware") instead of the people affected. Shiplog requires four things for every entry: **what changed** in plain language, **who is affected**, **whether they need to act**, and **what the action is**. Support teams answer tickets from these entries, and customers decide whether to care. So accuracy about impact matters more than polish.

## Workflow

### 1. Find or create the config

Look for `.shiplog.json` at the repo root.

- **Found:** read it. Note the apps, their `path`, `tag_prefix`, `releases_dir`, and the defined audiences.
- **Not found:** run `python SCRIPTS/init.py --name "<App name>"` (add `--id`, `--base-url`, `--tag-prefix` if known). Then open the generated `.shiplog.json` and tailor the `audiences` list with the user. Audiences are the groups that entries target, e.g. admins, end users, API consumers, support. Ask the user who their audiences are rather than guessing. A wrong audience list makes every entry's impact field wrong.
- **Monorepo:** use one `apps[]` item per app, each with its own `path`, `tag_prefix` and `releases_dir`. See `references/config.md`.

If the user wants CI enforcement, run `init.py --with-ci`. It vendors the scripts into `.shiplog/scripts/` and adds a GitHub Actions workflow, so CI never depends on Claude being present.

### 2. Collect the changes

```bash
python SCRIPTS/collect_changes.py --app <id>            # since last tag for that app
python SCRIPTS/collect_changes.py --app <id> --from v2.3.0 --to HEAD
```

This prints JSON with the commit range, the parsed Conventional Commits (type, scope, breaking flag, PR/issue refs), and a **suggested** SemVer version. If there are no tags yet, it collects the full history. In that case, ask the user whether to start from a specific commit or release everything as the first version.

Read the output, then read the actual diffs or PR descriptions for anything whose user-facing effect is unclear from the subject line. Use `git show <sha> --stat`, or `gh pr view <n>` if the GitHub CLI is available. Commit subjects routinely understate or misdescribe changes.

### 3. Decide the version

Start from `suggested_version`. Explain the reasoning in one line, e.g. "1 breaking change → 3.0.0". Then let the user confirm or override. Never silently publish a version the user didn't agree to. If the user already told you the version, use it. Still flag it if the commits contain a breaking change but the bump is not major. Pre-1.0 projects conventionally bump minor for breaking changes.

### 4. Draft the entries

Turn commits into **user-facing changes**. Grouping several commits into one entry is normal. Read `references/writing-guide.md` before drafting. It covers voice, before/after examples, and how to handle security fixes.

Rules of thumb:
- **Skip purely internal work:** refactors, tests, CI, dependency bumps with no behavior change, and `chore`/`style`/`build` commits. Include them only if they change what users experience (performance, compatibility, new minimum versions).
- **Choose a type** from Keep a Changelog: `added`, `changed`, `fixed`, `deprecated`, `removed`, `security`.
- **`description` is plain language.** Describe the outcome for the reader, not the implementation. No ticket IDs, file paths, function names, or internal codenames. Those go in `refs` and `internal_notes`, which are hidden from the public page.
- **`audiences`** must use ids from the config, or `everyone`.
- **`action_required` / `action`:** if readers must do something (update an integration, re-authenticate, change a setting, migrate before a date), say exactly what and by when. Breaking changes always require an action.
- **`internal_notes`** is for support: talking points, known issues, rollback info, feature flag names. It only appears on the internal page.

**Don't invent impact.** If you can't tell from the code who is affected, or whether action is needed, ask the user. A short list of specific questions works well: "Does the new rate limit apply to free-tier API keys too?" A confidently wrong "no action required" is the most damaging mistake this tool can make.

Show the user the drafted entries in a compact readable form (not raw JSON) and get confirmation before writing files.

### 5. Write the release file

Write `<releases_dir>/<version>.json`. The format is in `references/schema.md`. Minimal example:

```json
{
  "version": "2.4.0",
  "date": "2026-09-28",
  "summary": "Bulk export and faster search",
  "entries": [
    {
      "type": "added",
      "title": "Export up to 50,000 rows at once",
      "description": "You can now export large reports as CSV in one step from the Reports page. Previously exports were limited to 5,000 rows.",
      "audiences": ["admins"],
      "action_required": false,
      "refs": ["#412"]
    }
  ]
}
```

Use today's date unless the user gives a release date.

### 6. Validate

```bash
python SCRIPTS/validate.py --app <id>
```

Fix every **error**. It exits non-zero and CI will fail on errors. Review the **warnings**, which flag likely jargon, ticket IDs in public text, very short descriptions and similar issues. Fix them, or leave them if they're genuinely fine, and tell the user which ones you left and why.

### 7. Render

```bash
python SCRIPTS/render.py --app <id>
```

This writes `CHANGELOG.md` (if enabled), `index.html`, `feed.xml` and `changelog.json` to the app's `output_dir`. Add `--internal` to also write `internal.html`, which includes internal notes and refs. Remind the user **not** to deploy `internal.html` publicly. Put it behind auth, or render it in a separate job.

### 8. Wrap up

Tell the user briefly what was written, where, and the suggested next steps. For example: commit the release file and outputs, tag `v2.4.0`, and deploy `output_dir` to their docs host. Don't create tags, push, or deploy unless the user asks.

## Other tasks

- **Edit a past release:** edit its JSON, then validate and render again. Never edit generated files directly. They get overwritten.
- **Import an existing CHANGELOG.md:** convert each version into a release JSON. Existing entries usually lack audiences and actions. Use `everyone` + `action_required: false` only where that's clearly true. Otherwise ask, or tell the user which entries need review.
- **Change the look of the page:** set `theme` in the config (`accent_color`, `logo_url`) as described in `references/config.md`. For deeper changes, edit `assets/templates/page.html`. It uses `{{placeholders}}` filled by `render.py`.
- **CI check on release:** the workflow from `init.py --with-ci` fails a tag build if the matching release file is missing or invalid (`validate.py --require-version <version>`).
