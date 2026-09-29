# Contributing

Thanks for helping improve Shiplog.

- **Scripts stay dependency-free.** Python 3.10+ standard library only, so the skill runs anywhere Claude Code does and CI needs no installs.
- **Run the tests** before opening a PR: `python3 -m unittest discover tests`. Every change needs a test. Tests never touch the network: `gh` lookups are disabled and Slack tests use `--dry-run` or a local HTTP server.
- **Output must be deterministic.** Re-rendering unchanged releases must produce byte-identical files, so never put today's date or anything random into generated output.
- **Skill instructions** live in `plugins/shiplog/skills/shiplog/SKILL.md`. Keep it under ~200 lines and move detail into `references/`. If you change behavior, update the matching reference file.
- **Accessibility is a requirement,** not a nice-to-have. Changes to `page.html` must keep keyboard navigation, visible focus, WCAG AA contrast in both themes, and a readable no-JavaScript experience. Structural checks run with the tests. For a full axe-core check (dev only): `pip install playwright && playwright install chromium`, get `axe.min.js` (`npm i axe-core`), then run the tests with `SHIPLOG_AXE=1 SHIPLOG_AXE_JS=path/to/axe.min.js`.
- **New page labels** go in `DEFAULT_STRINGS` in `_common.py`, so they can be translated.
- **Release file format changes** need a migration note in the PR, a validator update, and a matching change to `schema/release.schema.json` (a test checks that they agree).
- **Changelog:** add your user-visible change to the next release file in `.changelog/shiplog/` and run `python3 plugins/shiplog/skills/shiplog/scripts/shiplog.py release --version <v>`.

Ideas we'd welcome: a GitLab CI template, Microsoft Teams or Discord announcements, and translated `strings` presets.
