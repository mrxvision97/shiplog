# .shiplog.json

Lives at the repo root. It holds either a single app object, or `{"apps": [...]}` for monorepos.

```json
{
  "apps": [
    {
      "id": "web",
      "name": "Acme Web",
      "description": "New features, improvements and fixes in Acme Web.",
      "path": "apps/web",
      "tag_prefix": "web-v",
      "releases_dir": ".changelog/web",
      "output_dir": "changelog/web",
      "base_url": "https://acme.com/changelog/web",
      "changelog_md": true,
      "lang": "en",
      "audiences": [
        { "id": "end-users", "label": "End users" },
        { "id": "admins", "label": "Account admins" },
        { "id": "developers", "label": "API & integration developers" },
        { "id": "support", "label": "Support team" }
      ],
      "theme": { "accent_color": "#0f766e", "logo_url": "https://acme.com/logo.svg" }
    }
  ]
}
```

| Field | Default | Meaning |
|---|---|---|
| `id` | required | Short slug used in `--app` and in default paths. |
| `name` | required | Display name. |
| `description` | generic | Intro text and meta description on the page. |
| `path` | `.` | Directory whose commits belong to this app. `collect_changes.py` limits `git log` to it. |
| `tag_prefix` | `v` | Tags look like `<prefix><version>`. Use distinct prefixes per app in a monorepo (`web-v`, `api-v`). |
| `releases_dir` | `.changelog/<id>` | Where release JSON files live. |
| `output_dir` | `changelog/<id>` | Where rendered files go. Deploy this folder. |
| `base_url` | `""` | Public URL of the page. Used for absolute feed links and CHANGELOG.md version links. |
| `changelog_md` | `true` | `true` writes `<path>/CHANGELOG.md`, a string sets a custom path, `false` disables it. |
| `lang` | `en` | Page language attribute (for screen readers). |
| `audiences` | `[]` | Groups entries can target. `everyone` is always available. |
| `theme.accent_color` | `#4f46e5` | Hex color for link underlines and controls. A contrast warning prints if it's too low. |
| `theme.logo_url` | none | Logo shown in the header. |
| `project_url` | Shiplog repo | Footer link target. |
| `allowed_terms` | `[]` | Words the jargon check accepts, e.g. a product called "Hotfix Hub". Capitalized mid-sentence words are already treated as names. |

## Choosing audiences

Four to seven audiences is usually right. They should match how your support team talks about customers, e.g. plan tiers, roles, or integration types. Too many audiences, and authors pick inconsistently. Too few, and everything becomes "everyone".
