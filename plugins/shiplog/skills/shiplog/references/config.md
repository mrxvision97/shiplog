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
| `theme.logo_url` | none | Logo shown in the header. Also the Open Graph image unless `theme.og_image` is set. |
| `theme.og_image` | none | Image for link previews (`og:image`). |
| `page_size` | `20` | Releases on `index.html`. Older ones go to one archive page per year (`2025.html`, …). `0` puts everything on one page. |
| `strings` | English | Page labels, for translating the page. See below. |
| `project_url` | Shiplog repo | Footer link target. |
| `allowed_terms` | `[]` | Words the jargon check accepts, e.g. a product called "Hotfix Hub". Capitalized mid-sentence words are already treated as names. |

## Feeds

`feed.xml` has every release. Each audience also gets `feed-<id>.xml`, with only the entries for that audience plus `everyone` entries. The page links all of them.

## Translating the page

Override any label with `strings`. Keys you leave out stay English. `{name}`, `{n}`, `{shown}`, `{total}`, `{date}` and `{link}` are filled in by Shiplog.

```json
"lang": "de",
"strings": {
  "title": "{name} Änderungsprotokoll",
  "skip_link": "Zum Inhalt springen",
  "whos_affected": "Betrifft:",
  "what_to_do": "Das müssen Sie tun",
  "showing_all": "Alle {n} Änderungen.",
  "showing_some": "{shown} von {total} Änderungen.",
  "types": { "added": "Neu", "changed": "Geändert", "fixed": "Behoben" },
  "months": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
  "date_format": "{day}. {month} {year}"
}
```

The full list of keys is `DEFAULT_STRINGS` in `scripts/_common.py`. `CHANGELOG.md` stays in Keep a Changelog's English format.

## Choosing audiences

Four to seven audiences is usually right. They should match how your support team talks about customers, e.g. plan tiers, roles, or integration types. Too many audiences, and authors pick inconsistently. Too few, and everything becomes "everyone".
