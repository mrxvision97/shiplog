---
name: shiplog
description: Write and publish structured, plain-language changelogs for any app or monorepo, with an accessible changelog web page, Atom feed, CHANGELOG.md and CI enforcement. Every entry records what changed, who is affected, and what action they need to take. Use this skill whenever the user mentions a changelog, release notes, "what's new", "what shipped", preparing or tagging a release, bumping a version, writing up changes since the last tag, or setting up a changelog page, even if they don't say "changelog" explicitly (e.g. "we're releasing 2.4 today", "summarize what changed for customers", "support needs to know what's shipping").
---

# Shiplog

Shiplog turns raw git history into release notes that customers, support, and internal teams can actually use. Each release is stored as a small JSON file in the repo (the source of truth). Scripts validate it and generate the outputs: `CHANGELOG.md`, an accessible static HTML page, Atom feeds and a JSON feed.

The scripts are Python 3.10+ and use only the standard library. They work in any git repository, from any folder inside it: the repo root is found automatically. Every step is one command: `python SCRIPTS/shiplog.py <command>`, where `SCRIPTS` is this skill's `scripts/` directory. Below, `shiplog` is short for that.

## Why the structure matters

Changelogs usually fail in two ways. They get skipped, or they're written for engineers ("refactor auth middleware") instead of the people affected. Shiplog requires four things for every entry: **what changed** in plain language, **who is affected**, **whether they need to act**, and **what the action is**. Support teams answer tickets from these entries, and customers decide whether to care. So accuracy about impact matters more than polish.

## Be fast

- **Don't re-ask.** If the user already gave the version, date, audiences or impact details, use them.
- **Batch questions.** Ask everything you need in ONE message, as a numbered list, never one question per turn.
- **Read diffs only when impact is genuinely unclear.** The summary line plus PR title/body is enough for most changes.
- **Fast path (up to ~15 user-facing changes):** collect → draft all entries in one pass → show the drafts and all open questions together in one message → write, then `release`. That's two turns with the user at most.

## Workflow

### 1. Find or create the config

Look for `.shiplog.json` at the repo root.

- **Found:** read it. Note the apps, their `path`, `tag_prefix`, `releases_dir`, and the defined audiences.
- **Not found:** run `shiplog init`. It detects the name and description (package.json, pyproject.toml, Cargo.toml, go.mod, git remote) and the tag prefix from existing version tags (`v1.2.3`, `1.2.3`, `release-1.2.3`). Pass `--name`, `--base-url` or `--tag-prefix` to override. Show the user what was detected, then tailor the `audiences` list with them. Audiences are the groups entries target, e.g. admins, end users, API consumers, support. Ask who they are rather than guessing: a wrong audience list makes every entry's impact wrong.
- **Existing hand-written CHANGELOG.md:** Shiplog keeps it. Each new release is added above the newest one in the file's own format (headings, dates, section names, bullets, PR links), and existing lines are never changed. Read its latest entries so your wording matches its tone too. `shiplog import` is only needed to show the old history on the changelog page.
- **Monorepo:** one `apps[]` item per app, each with its own `path`, `tag_prefix` and `releases_dir`. See `references/config.md`.

If the user wants CI enforcement, run `shiplog init --with-ci`. It vendors the scripts into `.shiplog/scripts/` and adds a GitHub Actions workflow, so CI never depends on Claude.

### 2. Collect the changes

```bash
shiplog collect --app <id>                   # since the app's last tag
shiplog collect --app <id> --from v2.3.0     # explicit range
```

The output is compact: a header with the range and **suggested** version, notes, then one line per change:

```
feat!(api)  #212  Require API keys on all endpoints  [PROJ-9]  (3 commits)  {breaking-change}
    > PR body excerpt…
```

Act on the notes before drafting, and fold any questions into your one batched message:

- **"You're on branch X":** releases come from the main branch. Re-run with `--to main` (or `origin/main`) unless the user says otherwise.
- **"No starting point… whole history":** there are no tags yet. Ask where this release starts (a date, tag or commit), then re-run with `--since YYYY-MM-DD` or `--from <ref>`. Never draft a changelog from years of history.
- **"found version tags like …":** the configured `tag_prefix` doesn't match the repo's tags; offer to fix it.

`!` means breaking. Commits are grouped by PR (merge commits and squash merges). When the GitHub CLI is available, PR titles, bodies and labels are fetched in one call. `--full` gives JSON with every commit, if you really need it. Read the notes: they cover first releases, shallow clones and unconventional commit messages.

Only for changes whose user impact is unclear from the line, look deeper: `git show <sha> --stat`, or `gh pr view <n>`.

### 3. Decide the version

Start from the suggested version and give the reason in one line, e.g. "1 breaking change → 3.0.0". If the user already named a version, use it, but flag a breaking change without a major bump (pre-1.0 projects conventionally bump minor). Never publish a version the user didn't agree to. Ask about the version in the same message as the impact questions.

### 4. Draft the entries

Turn changes into **user-facing entries**. Grouping several changes into one entry is normal. Read `references/writing-guide.md` before your first draft in a session.

- **Skip internal work** (refactors, tests, CI, dependency bumps, `chore`/`style`/`build`) unless users notice it: performance, compatibility, new minimum versions.
- **Type** from Keep a Changelog: `added`, `changed`, `fixed`, `deprecated`, `removed`, `security`.
- **`description`** is plain language about the outcome. No ticket IDs, file paths, function names or codenames: those go in `refs` and `internal_notes`, which stay off the public page.
- **`audiences`** use ids from the config, or `everyone`.
- **`action_required` / `action`:** if readers must do something, say exactly what and by when. Breaking changes always require an action. Deprecations name the replacement and a deadline.
- **`internal_notes`** is for support: talking points, known issues, rollback, flag names.
- **The release reads like a product post:** a `title` headline led by the biggest change, a one or two sentence `summary`, and 1 to 3 entries marked `"highlight": true` (optionally with an `image` and alt text). Everything else stays short. See "The release" in the writing guide.

**Don't invent impact.** If you can't tell who is affected or whether action is needed, ask with specific questions ("Does the new rate limit apply to free-tier keys too?"). A confidently wrong "no action required" is the most damaging mistake this tool can make.

Show the drafts in a compact readable form (not raw JSON) with your questions, and get confirmation before writing files.

### 5. Write the release file

Write `<releases_dir>/<version>.json`. Format: `references/schema.md`. Minimal example:

```json
{
  "$schema": "https://raw.githubusercontent.com/mrxvision97/shiplog/main/plugins/shiplog/skills/shiplog/schema/release.schema.json",
  "version": "2.4.0",
  "date": "2026-09-28",
  "title": "Bulk export and faster search",
  "summary": "Export whole reports in one step, and find records in large workspaces in about a second.",
  "entries": [
    {
      "type": "added",
      "title": "Export up to 50,000 rows at once",
      "description": "You can now export large reports as CSV in one step from the Reports page. Previously exports were limited to 5,000 rows.",
      "audiences": ["admins"],
      "action_required": false,
      "highlight": true,
      "refs": ["#412"]
    }
  ]
}
```

Copy `$schema` from an existing release file if there is one. Use today's date unless the user gives a release date.

### 6. Validate and render in one step

```bash
shiplog release --app <id> --version 2.4.0            # add --internal for the support page
```

It checks the release file (and the rest of the app), then writes `index.html`, per-year archive pages, `feed.xml`, per-audience feeds, `changelog.json` and `CHANGELOG.md`. Fix every **error**. Review the **warnings** (jargon, ticket IDs in public text, past deadlines, deprecations without a replacement). Fix them, or tell the user which you left and why. `--internal` also writes `internal.html` with support notes: remind the user **not** to deploy it publicly.

(`shiplog validate` and `shiplog render` still exist for running the steps separately.)

### 7. Offer to announce in Slack

If the app's config has `notify.slack`, offer to announce the release. Run `shiplog notify --app <id> --version <v> --dry-run` first and show the user, per channel, which entries will be posted. Send (`shiplog notify --app <id> --version <v>`) **only after the user confirms**. If a channel fails, report the error. Don't retry with `--force` unless asked. Setup help is in `references/slack.md`. If nothing is configured, mention the option in one line and move on.

### 8. Wrap up

Tell the user briefly what was written and where, and the next steps: commit the release file and outputs, tag the release commit (`git tag v2.4.0 <commit>`, so the next `collect` starts there), deploy `output_dir`. Don't create tags, push or deploy unless asked.

## Other tasks

- **Edit a past release:** edit its JSON, then `shiplog release --version <v>`. Never edit generated files; they get overwritten.
- **Import an existing CHANGELOG.md:** `shiplog import --app <id> --dry-run`, then without `--dry-run`. Every entry gets `everyone`, `action_required: false` and `_needs_review: true`, and the validator warns about each. Review them with the user in one batched list, fix the impact fields, and delete the flag.
- **Change the look of the page:** set `theme` (`accent_color`, `logo_url`), `page_size` or translated `strings` in the config (`references/config.md`). For deeper changes, edit `assets/templates/page.html`.
- **CI check on release:** the workflow from `init --with-ci` fails a tag build if the matching release file is missing or invalid (`validate --tag <tag>`).
