Release History
===============

dev
---

- \[Short description of non-trivial change.\]


2.34.2 (2026-05-14)
-------------------
- Moved `headers` input type back to `Mapping` to avoid invariance issues
  with `MutableMapping`. (#7441)


2.34.1 (2026-05-13)
-------------------

**Bugfixes**
- Widened `json` input type from `dict` and `list` to `Mapping`. (#7436)

**Improvements**
- Faster header parsing on large responses. (#7430)
