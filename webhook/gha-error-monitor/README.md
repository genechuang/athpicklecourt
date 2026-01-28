# GHA Error Monitor

Cloud Function that monitors GitHub Actions workflow failures and sends diagnostic reports via WhatsApp.

## Features

- **GitHub Webhook Integration**: Receives `workflow_run.completed` events
- **Intelligent Diagnosis**: Uses Claude API (Haiku) for error analysis
- **Fallback Parsing**: Simple pattern matching when Claude unavailable
- **WhatsApp Alerts**: Sends to Admin Dinkers group + personal DM
- **Cost Efficient**: ~$0.01-0.05 per failure using Claude Haiku
- **Booking Failure Detection**: Monitors Court Booking workflows for failed bookings even when workflow succeeds

## Architecture

```
GitHub Actions ─── webhook ───> Cloud Function ───> Claude API (diagnosis)
      │                              │
      │                              └───> GREEN-API (WhatsApp alerts)
      │                                        │
      └─── logs via API ─────────────────────┘
```

## Setup

### 1. Create Secrets in GCP Secret Manager

```powershell
# GitHub personal access token (repo scope for reading workflow logs)
gcloud secrets create GITHUB_TOKEN --replication-policy="automatic"
echo -n "ghp_your_token_here" | gcloud secrets versions add GITHUB_TOKEN --data-file=-

# GitHub webhook secret (for signature verification)
gcloud secrets create GITHUB_WEBHOOK_SECRET --replication-policy="automatic"
echo -n "your_webhook_secret" | gcloud secrets versions add GITHUB_WEBHOOK_SECRET --data-file=-

# Anthropic API key (for Claude diagnosis)
gcloud secrets create ANTHROPIC_API_KEY --replication-policy="automatic"
echo -n "sk-ant-your_key_here" | gcloud secrets versions add ANTHROPIC_API_KEY --data-file=-
```

### 2. Add GitHub Repository Variables

Go to **Settings > Secrets and variables > Actions > Variables** and add:

| Variable | Description | Example |
|----------|-------------|---------|
| `ADMIN_PHONE_ID` | Admin phone for personal DM | `16265551234@c.us` |

Note: `ADMIN_DINKERS_WHATSAPP_GROUP_ID` should already exist.

### 3. Deploy the Cloud Function

The function deploys automatically when you push changes to `webhook/gha-error-monitor/`.

Or deploy manually:

```powershell
gcloud functions deploy gha-error-monitor `
  --project=smad-pickleball `
  --region=us-west1 `
  --runtime=python311 `
  --gen2 `
  --source=./webhook/gha-error-monitor `
  --entry-point=gha_error_monitor `
  --trigger-http `
  --allow-unauthenticated `
  --memory=256MB `
  --timeout=60s `
  --set-env-vars "GITHUB_REPO=genechuang/SMADPickleBot" `
  --set-secrets "GITHUB_TOKEN=GITHUB_TOKEN:latest,GITHUB_WEBHOOK_SECRET=GITHUB_WEBHOOK_SECRET:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,GREENAPI_INSTANCE_ID=GREENAPI_INSTANCE_ID:latest,GREENAPI_API_TOKEN=GREENAPI_API_TOKEN:latest"
```

### 4. Configure GitHub Webhook

1. Go to your repository **Settings > Webhooks > Add webhook**
2. Configure:
   - **Payload URL**: Cloud Function URL (shown after deployment)
   - **Content type**: `application/json`
   - **Secret**: Same value as `GITHUB_WEBHOOK_SECRET`
   - **Events**: Select "Let me select individual events" > check "Workflow runs"
3. Click "Add webhook"

### 5. Apply Terraform (Optional)

If using Terraform to manage infrastructure:

```powershell
cd infra/terraform
terraform plan
terraform apply
```

## Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `GITHUB_TOKEN` | Secret Manager | GitHub PAT for API access |
| `GITHUB_WEBHOOK_SECRET` | Secret Manager | Webhook signature verification |
| `ANTHROPIC_API_KEY` | Secret Manager | Claude API key for diagnosis |
| `GREENAPI_INSTANCE_ID` | Secret Manager | GREEN-API instance |
| `GREENAPI_API_TOKEN` | Secret Manager | GREEN-API token |
| `GITHUB_REPO` | Environment | Repository name (e.g., `genechuang/SMADPickleBot`) |
| `ADMIN_DINKERS_WHATSAPP_GROUP_ID` | Environment | Admin group for alerts |
| `ADMIN_PHONE_ID` | Environment | Admin phone for personal DM |

## Cost

- **Claude API (Haiku)**: ~$0.01-0.05 per failure diagnosis
- **Cloud Function**: Free tier (2M invocations/month)
- **GREEN-API**: Existing subscription

Falls back to simple pattern matching if Claude API credits are exhausted or rate limited.

## Alert Formats

### Workflow Failure Alert

Sent when a GitHub Actions workflow crashes or exits with error:

```
[GHA ALERT] Workflow Failed

Workflow: Court Booking
Time: 01/28/26 12:05 AM PST

Failed Steps:
  - Book Court

Diagnosis:
DOM element detached - page likely changed during interaction.
The booking form may have reloaded. Add page.reload() before
interacting with elements.

Run: https://github.com/genechuang/SMADPickleBot/actions/runs/12345
```

### Booking Failure Alert

Sent when Court Booking workflow succeeds but one or more bookings fail (court unavailable):

```
[BOOKING ALERT] Court Booking Failed

Time: 01/28/26 12:05 AM PST
Results: 1 successful, 1 failed

Failed:
  - North Pickleball Court on 02/06/2026 at 9:00 AM

Reason: Court not yet released (>7 days out)

Run: https://github.com/genechuang/SMADPickleBot/actions/runs/12345
```

## Testing

Test locally with:

```python
python webhook/gha-error-monitor/main.py
```

Or trigger manually via GitHub Actions workflow dispatch.
