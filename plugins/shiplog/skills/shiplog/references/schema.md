# Release file format

One file per release: `<releases_dir>/<version>.json`. The file name must equal the version.

## How a release is shown

The page follows the structure product teams like Linear, Raycast and Notion use:

1. **Date and version** in a column on the left (above the release on phones).
2. **Headline** (`title`), then the **intro** (`summary`) and an optional **hero image**.
3. **Action required**: every entry with `action_required`, with its action and deadline, in one box.
4. **Highlights**: entries with `highlight: true` as full sections with a heading, text, image and links.
5. **Compact lists** for the rest: New, Improvements, Fixes, Security, Deprecations, Removed.

Entries that affect specific audiences carry small audience labels; entries for `everyone` don't.

## Release

| Field | Required | Notes |
|---|---|---|
| `$schema` | no | Points editors at `schema/release.schema.json` for autocomplete. Ignored by the scripts. |
| `version` | yes | SemVer, e.g. `2.4.0`, `3.0.0-beta.1`. No `v` prefix. |
| `date` | yes | `YYYY-MM-DD`, the day it reached users. |
| `title` | no | The release headline, under 100 chars, led by the main feature: "Bulk export and faster search". Falls back to `summary`, then the version. |
| `summary` | no | One or two sentences introducing the release, under 280 chars. Shown under the headline (or as the headline when there's no `title`). |
| `image` | no | Hero image under the headline: `{"url": "https://…", "alt": "What it shows"}`. `alt` is required. |
| `entries` | yes | Non-empty list of entries. |
| `yanked` | no | `true` if the release was withdrawn. Keep the file; the page marks it as withdrawn. |

## Entry

| Field | Required | Public? | Notes |
|---|---|---|---|
| `type` | yes | yes | `added`, `changed`, `fixed`, `deprecated`, `removed`, `security` |
| `title` | yes | yes | Under 100 chars. Names the change from the reader's side. |
| `description` | yes | yes | Plain language, 20–800 chars. What changed and what the reader will notice. Blank lines make paragraphs; bare URLs become links. |
| `audiences` | yes | yes | List of audience ids from config, or `["everyone"]`. |
| `action_required` | yes | yes | `true` / `false`. |
| `action` | if action_required | yes | Exactly what to do. Imperative ("Regenerate your API key in Settings → API"). |
| `action_deadline` | no | yes | `YYYY-MM-DD`. Expected for deprecations. |
| `breaking` | no | yes | `true` forces `action_required: true`. |
| `links` | no | yes | `[{"label": "Migration guide", "url": "https://..."}]`. On highlights they read as "Migration guide →". |
| `highlight` | no | yes | `true` shows the entry as a full section with its own heading, above the lists. Without any, new features (up to 3) are highlighted. |
| `image` | no | yes | Screenshot for a highlight: `{"url": "https://…", "alt": "…"}`. `alt` is required. |
| `internal_notes` | no | **internal only** | Support talking points, known issues, rollback, flag names. |
| `refs` | no | **internal only** | PR numbers, ticket IDs, commit SHAs. |
| `_needs_review` | no | never shown | Set by `import_changelog.py`. The validator warns until you confirm `audiences` and `action_required` and delete it. |

Fields marked internal only appear only in `internal.html` and `changelog.internal.json` (rendered with `--internal`).

## JSON Schema

`schema/release.schema.json` and `schema/config.schema.json` give editors autocomplete and basic checks. `validate.py` is the source of truth: it also checks audiences against the config, jargon, deadlines and more.

## Full example

```json
{
  "$schema": "https://raw.githubusercontent.com/mrxvision97/shiplog/main/plugins/shiplog/skills/shiplog/schema/release.schema.json",
  "version": "3.0.0",
  "date": "2026-10-01",
  "title": "Saved filters and safer API keys",
  "summary": "Save and share any filter on the Orders page. API keys now expire, so plan a rotation before March 31, 2027.",
  "entries": [
    {
      "type": "changed",
      "title": "API keys now expire after 12 months",
      "description": "To keep accounts secure, API keys created from today expire 12 months after creation. Existing keys keep working until March 31, 2027.",
      "audiences": ["developers", "admins"],
      "action_required": true,
      "action": "Before March 31, 2027, create a new key in Settings → API and update your integrations to use it.",
      "action_deadline": "2027-03-31",
      "breaking": true,
      "links": [{"label": "API key guide", "url": "https://docs.example.com/api-keys"}],
      "internal_notes": "Customers can request a one-time 90-day extension via support. Flag: api_key_expiry.",
      "refs": ["#1893", "SEC-221"]
    },
    {
      "type": "added",
      "title": "Save and share filters on the Orders page",
      "description": "Save any combination of filters and share it with teammates using a link.",
      "highlight": true,
      "image": {"url": "https://docs.example.com/img/saved-filters.png", "alt": "The Orders page with the Save filter menu open"},
      "audiences": ["end-users"],
      "action_required": false
    }
  ]
}
```
