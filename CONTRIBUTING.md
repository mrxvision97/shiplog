# Contributing

Thanks for helping improve Shiplog.

- **Scripts stay dependency-free.** Python 3.10+ standard library only, so the skill runs anywhere Claude Code does and CI needs no installs.
- **Run the tests** before opening a PR: `python -m unittest discover tests`.
- **Skill instructions** live in `plugins/shiplog/skills/shiplog/SKILL.md`. Keep it under ~200 lines and move detail into `references/`. If you change behavior, update the matching reference file.
- **Accessibility is a requirement,** not a nice-to-have. Changes to `page.html` must keep keyboard navigation, visible focus, WCAG AA contrast in both themes, and a readable no-JavaScript experience.
- **Release file format changes** need a migration note in the PR and a validator update.

Ideas we'd welcome: GitLab CI template, i18n for page strings, per-audience feeds, importing an existing Keep a Changelog file.
