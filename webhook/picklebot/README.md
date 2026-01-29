# SMAD Picklebot Chatbot

WhatsApp chatbot for SMAD Pickleball group management. Triggered by `/pb` or `/picklebot` commands in WhatsApp.

## Architecture

```
WhatsApp Groups
      │
      │ "/pb book 2/4 7pm 2hrs"
      ▼
GREEN-API Webhook ──> smad-whatsapp-webhook
      │
      │ Detects /pb command
      ▼
smad-picklebot Cloud Function
      │
      ├── Parse intent with Claude Haiku
      ├── Execute command
      └── Send response to WhatsApp
```

## Access Levels

### Admin Dinkers Group (Full Access)
All commands available including:
- Court booking (`/pb book`)
- Job management (`/pb jobs cancel`)
- Poll creation (`/pb poll create`)
- Reminders (`/pb reminders`)

### SMAD Pickleball Group (Read-Only)
Limited to read-only commands:
- `/pb help`, `/pb deadbeats`, `/pb balance`
- `/pb status`, `/pb jobs`
- `/pb joke`, `/pb meme`

Action commands return "command not available here" message.

## Commands

### Read-Only Commands

| Command | Description |
|---------|-------------|
| `/pb help` | Show available commands |
| `/pb deadbeats` | Show players with outstanding balances |
| `/pb balance [name]` | Show all balances or specific player |
| `/pb status` | Show system status |
| `/pb jobs` | List scheduled court bookings |

### Fun Commands

| Command | Description |
|---------|-------------|
| `/pb joke` | Tell a pickleball joke (AI-generated) |
| `/pb meme` | Post a pickleball meme with AI caption |

### Action Commands (Admin Only)

| Command | Description |
|---------|-------------|
| `/pb book <date> <time> [duration]` | Book court |
| `/pb jobs cancel <job_id>` | Cancel a scheduled booking |
| `/pb poll create` | Create weekly availability poll |
| `/pb reminders` | Send vote reminders |

## Smart Scheduling

When booking a court more than 7 days in advance:
1. Picklebot automatically creates a Cloud Scheduler job
2. Job runs at 12:01 AM PST, 7 days before the booking date
3. Triggers the court-booking GitHub Action workflow

Example:
```
/pb book 2/15 7pm 2hrs
```
If today is 2/1, this creates a scheduled job for 2/8 at 12:01 AM.

## Natural Language

Commands support natural language via Claude Haiku:
- `/pb tell me a joke`
- `/pb book next Tuesday at 7pm`
- `/pb who owes money`

## Options

| Flag | Description |
|------|-------------|
| `--dry-run` | Test command without executing |

Example: `/pb book 2/4 7pm --dry-run`

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key for intent parsing |
| `GREENAPI_INSTANCE_ID` | GREEN-API instance ID |
| `GREENAPI_API_TOKEN` | GREEN-API API token |
| `ADMIN_DINKERS_WHATSAPP_GROUP_ID` | Admin group ID |
| `SMAD_SPREADSHEET_ID` | Google Sheets ID |
| `SMAD_SHEET_NAME` | Sheet name (e.g., "2026 Pickleball") |
| `GITHUB_REPO` | Repository for workflow dispatch |
| `GITHUB_TOKEN` | GitHub token for API calls |

## Deployment

Deployed automatically via GitHub Actions when files in `webhook/picklebot/` change.

Cloud Function specs:
- **Name**: smad-picklebot
- **Runtime**: Python 3.11
- **Memory**: 512MB
- **Timeout**: 60s
- **Region**: us-west1

## Cost

- Claude Haiku: ~$0.01 per command
- Cloud Function: Free tier
- Cloud Scheduler: Covered by existing quota
