# Writing changelog entries people actually read

The reader is a customer, an admin, or a support agent skimming for one question: **does this affect me, and do I need to do anything?** Write for that person, not for the engineer who made the change.

## Principles

1. **Lead with the outcome.** Say what the reader can now do, or what behaves differently. Don't describe what the team did internally.
2. **Use the product's words.** Name screens, buttons and settings the way the UI names them ("Settings → Billing"). Don't use code names or table names.
3. **Be specific.** "Search is faster" is weak. "Search results on large workspaces now load in under a second (previously up to 8 seconds)" is useful. Include before/after numbers when you have them.
4. **One change per entry.** Merge commits that belong to one change. Split one PR that ships two unrelated user-visible changes.
5. **Don't hide bad news.** Removals, price-affecting changes, and new limits get their own entry, clearly titled. Don't bury them inside a feature entry.
6. **Actions are instructions.** Use the imperative mood. Name the exact place and the exact step. Include the deadline in the action text as well as in `action_deadline`.
7. **Second person, present tense, active voice.** "You can now…", "Exports include…". Avoid "We are excited to announce".

## Titles

- Start with the thing that changed. Keep it short, and don't end with a period.
- Good: "Export up to 50,000 rows at once", "Two-factor login now required for admins", "Fixed duplicate invoice emails"
- Avoid: "Improvements", "Bug fixes", "Update export service", "PROJ-482"

## Before → after

| Commit / PR text | Entry |
|---|---|
| `feat(export): stream CSV via worker queue, raise cap to 50k` | **Export up to 50,000 rows at once.** Large CSV exports from the Reports page now complete in one step. The previous limit was 5,000 rows. |
| `fix: dedupe webhook retries (#881)` | **Fixed duplicate "invoice paid" emails.** Some customers received the same payment confirmation two or three times. Each payment now sends exactly one email. |
| `refactor(auth)!: drop legacy session tokens` | **Signed-out sessions on older mobile app versions.** *(breaking)* Versions older than 4.2 of the mobile app can no longer sign in. Action: update the app from the App Store or Google Play. |
| `chore(deps): bump lodash` | *(skip, no user-visible change)* |
| `perf(search): add trigram index` | **Faster search in large workspaces.** Search results now appear in about a second in workspaces with over 100,000 records. |

## Choosing the type

- **added:** a new capability.
- **changed:** existing behavior works differently, including UI moves and new defaults.
- **fixed:** something that was wrong now works as expected.
- **deprecated:** still works, but will be removed. Always give a date and the replacement.
- **removed:** no longer available.
- **security:** a fix or hardening with security relevance.

## Audiences and actions

- Use `everyone` only when it's genuinely true. If only admins see a setting, the audience is admins.
- Ask: would a support agent reading this know which customers will call about it? If not, narrow or clarify the audience.
- `action_required: true` when *anyone* in the listed audiences must act to avoid disruption or to keep things working. Optional steps, like trying a new feature, are not required actions. Mention them in the description instead.
- Breaking changes are always action-required. If you can't state an action, the change probably isn't breaking, or it needs a migration path before shipping. Raise this with the user.

## Security fixes

- Describe the fix and who should act. Don't include exploit details, affected endpoints, or payloads in public text.
- Put CVE IDs in `links` if public. Put internal detail in `internal_notes`.
- Example: **Fixed an issue that could expose file names to other workspace members.** No action needed; the fix is applied automatically.

## Internal notes (support-facing)

Useful contents: how to tell whether a customer is affected, known issues, the workaround, the flag name, whether it can be rolled back, and who owns it. Keep these notes short. This field never appears on the public page.
