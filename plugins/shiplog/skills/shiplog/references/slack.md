# Slack announcements

`shiplog notify` posts a release to one or more Slack channels. Each channel gets only the entries for its audiences. Action-required and breaking changes come first, with their action and deadline. A link to the changelog page closes the message.

## 1. Create an incoming webhook (simplest)

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**. Pick your workspace.
2. **Incoming Webhooks** → turn on → **Add New Webhook to Workspace** → choose the channel.
3. Copy the URL (`https://hooks.slack.com/services/...`). It's a secret: anyone with it can post to that channel.

One webhook posts to one channel. Repeat for each channel.

**Bot token (optional, for threads):** in the same app, under **OAuth & Permissions**, add the `chat:write` scope, install the app, and copy the **Bot User OAuth Token** (`xoxb-...`). Invite the bot to the channel (`/invite @YourApp`) and note the channel ID (channel details → bottom). Bot mode posts the summary and action items as the main message and the rest as a thread reply.

## 2. Store the secret, never in the repo

`.shiplog.json` holds only the **names** of environment variables:

```json
"notify": { "slack": [
  { "name": "customer-updates", "webhook_env": "SLACK_WEBHOOK_UPDATES",
    "audiences": ["end-users", "admins"], "include_internal": false },
  { "name": "support-internal", "webhook_env": "SLACK_WEBHOOK_SUPPORT",
    "audiences": ["everyone"], "include_internal": true, "mention": "@here" },
  { "name": "dev-announce", "token_env": "SLACK_BOT_TOKEN", "channel": "C0123456789",
    "audiences": ["developers"] }
]}
```

- **Locally:** `export SLACK_WEBHOOK_UPDATES=https://hooks.slack.com/services/...`
- **GitHub Actions:** repo **Settings → Secrets and variables → Actions → New repository secret**, named exactly like the env var. Then uncomment the "Announce release in Slack" step in `.github/workflows/shiplog.yml` and map each secret to its env var.

## 3. Routing

| Field | Meaning |
|---|---|
| `name` | Label used in output, `--channel` and `.notified.json`. |
| `webhook_env` | Env var with the webhook URL. |
| `token_env` + `channel` | Bot-token mode instead of a webhook. |
| `audiences` | Entries for these audiences are posted; entries for `everyone` go to every channel. `["everyone"]` gets all entries. A channel with nothing relevant is skipped. |
| `include_internal` | Also post `internal_notes`. Only for internal channels. |
| `mention` | `@here`, `@channel`, or a user group as `<!subteam^S0123ABCD>` (a plain `@team` name won't ping). |

## 4. Send

```bash
shiplog notify --app web --dry-run        # print the exact Slack JSON per channel; sends nothing
shiplog notify --app web                  # send the newest release
shiplog notify --tag web-v2.4.0           # what CI runs
shiplog notify --app web --channel support-internal --force   # resend one channel
```

- Sent notifications are recorded in `<releases_dir>/.notified.json` (version → channel → time) and skipped next time. `--force` resends. Commit this file if you notify from a laptop, so teammates don't double-post.
- A release with validation errors is never announced.
- Errors are per channel: a missing env var, a non-2xx response or a second rate limit (Slack's `Retry-After` is honored once) fails that channel only. The command exits non-zero if any channel failed.
- Long releases are trimmed to Slack's limits (50 blocks, 3000 characters per block) and end with "…and N more. See the full changelog".
