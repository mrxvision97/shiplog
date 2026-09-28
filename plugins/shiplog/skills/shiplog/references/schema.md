# Release file format

One file per release: `<releases_dir>/<version>.json`. The file name must equal the version.

## Release

| Field | Required | Notes |
|---|---|---|
| `version` | yes | SemVer, e.g. `2.4.0`, `3.0.0-beta.1`. No `v` prefix. |
| `date` | yes | `YYYY-MM-DD`, the day it reached users. |
| `summary` | no | One-line headline, under 120 chars. Shown under the version and in the feed title. |
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
| `links` | no | yes | `[{"label": "Migration guide", "url": "https://..."}]` |
| `internal_notes` | no | **internal only** | Support talking points, known issues, rollback, flag names. |
| `refs` | no | **internal only** | PR numbers, ticket IDs, commit SHAs. |

Fields marked internal only appear only in `internal.html` and `changelog.internal.json` (rendered with `--internal`).

## Full example

```json
{
  "version": "3.0.0",
  "date": "2026-10-01",
  "summary": "New API authentication and saved filters",
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
      "audiences": ["end-users"],
      "action_required": false
    }
  ]
}
```
