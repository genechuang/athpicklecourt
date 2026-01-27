# SMAD WhatsApp Poll Webhook

This webhook tracks poll votes from the SMAD WhatsApp group, storing them in Google Sheets.

> **Note**: GCP infrastructure (APIs, Cloud Functions, IAM) is managed by Terraform.
> Deployment is automated via CI/CD (`deploy-webhook.yml`).
> See [infra/terraform/README.md](../infra/terraform/README.md) for infrastructure details.

## Features

- **Tracks poll votes** - Captures who voted for what options in the "Pickle Poll Log" sheet
- **Handles vote changes** - When someone changes their vote, a new audit entry is created
- **Updates player sheets** - Automatically updates Last Voted date and y/n values in date columns
- **"Cannot play" override** - If someone selects both play dates AND "I cannot play this week", only the "cannot play" option is kept
- **Sunday cleanup** - Automatically deletes poll log entries older than 7 days every Sunday
- **Poll age validation** - Ignores votes from polls older than 7 days

## Prerequisites

1. **Google Cloud account** with a project
2. **gcloud CLI** installed and authenticated
3. **GREEN-API account** (you should already have this for smad-whatsapp.py)
4. **Google Sheets** with service account access (already configured in smad-sheets.py)

## Setup Instructions

### Step 1: Infrastructure (Terraform)

GCP APIs and Cloud Function definitions are managed by Terraform:

```bash
cd infra/terraform
terraform init
terraform apply
```

This enables required APIs (cloudfunctions, cloudbuild, etc.) and creates the function infrastructure.

### Step 2: Deploy the Cloud Function

**Automatic Deployment (Recommended):**
Push changes to `webhook/` on the `main` branch. GitHub Actions (`deploy-webhook.yml`) deploys automatically.

**Manual Deployment (if needed):**

**Windows (PowerShell or Command Prompt):**
```cmd
cd webhook

REM Deploy using the batch file
deploy.bat smad-pickleball us-west1

REM Or run gcloud directly:
gcloud functions deploy smad-whatsapp-webhook ^
    --project=smad-pickleball ^
    --region=us-west1 ^
    --runtime=python311 ^
    --trigger-http ^
    --allow-unauthenticated ^
    --entry-point=webhook ^
    --source=. ^
    --memory=256MB ^
    --timeout=60s ^
    --gen2
```

**Linux/Mac:**
```bash
cd webhook
chmod +x deploy.sh
./deploy.sh YOUR_PROJECT_ID us-west1
```

After deployment, you'll get a webhook URL like:
```
https://smad-whatsapp-webhook-xxxxx.a.run.app
```

### Step 3: Configure GREEN-API Webhooks

1. Go to [GREEN-API Console](https://console.green-api.com/)
2. Select your instance (ID from your `.env` file)
3. Go to **Instance Settings** or **Webhooks**
4. Set the **Webhook URL** to your Cloud Function URL
5. Enable these webhook notifications:
   - `incomingMessageReceived` - For incoming poll votes
   - `outgoingMessageReceived` - For polls you create

### Step 4: Ensure Google Sheets Access

The webhook uses the same service account as smad-sheets.py. Make sure:

1. Your Google Sheet is shared with the service account email
2. The service account has Editor permissions
3. The SMAD_SPREADSHEET_ID environment variable is set (already configured)

The webhook will automatically create the "Pickle Poll Log" sheet if it doesn't exist.

## Data Model

### Google Sheets Structure

**Sheet: Pickle Poll Log**
| Column | Header | Description |
|--------|--------|-------------|
| A | Poll ID | WhatsApp message ID (stanza ID) |
| B | Poll Created Date | When the poll was created (M/D/YY HH:MM:SS) |
| C | Poll Question | The poll question text |
| D | Player Name | Full name of voter |
| E | Vote Timestamp | When the vote was cast (M/D/YY HH:MM:SS) |
| F | Vote Options | Comma-separated selected options |
| G | Vote Raw JSON | Full vote data as JSON (audit trail) |

**Sheet: 2026 Pickleball (Main Sheet)**
- **Last Voted** (Column M): Updated with current date when player votes
- **Date Columns** (Column N+): Updated with 'y' or 'n' based on vote selections

### Vote Processing

1. Vote received → Record in Pickle Poll Log
2. Update Last Voted date in main sheet
3. Match poll options to date columns (by label, first match left-to-right)
4. Update date columns with 'y' (voted) or 'n' (not voted)
5. On Sundays: Delete entries older than 7 days

## Troubleshooting

### "No poll data found in Google Sheets"

- Make sure the webhook is deployed and the URL is configured in GREEN-API
- Check that at least one vote has been cast since the webhook was set up
- Verify the Google Sheet is shared with the service account

### Webhook not receiving events

1. Check GREEN-API dashboard for webhook delivery status
2. Look at Cloud Function logs:
   ```bash
   gcloud functions logs read smad-whatsapp-webhook --region=us-west1 --limit=50
   ```

### Authentication errors

- Make sure the service account has access to the Google Sheet
- The webhook uses default credentials (service account attached to Cloud Function)
- For local testing: `gcloud auth application-default login`

### Votes not updating date columns

- Check that poll is less than 7 days old (older polls are ignored)
- Verify date column labels match poll option names exactly
- Check Cloud Function logs for matching errors

## Cost

This setup should stay within Google Cloud's free tier:
- Cloud Functions: 2 million invocations/month free
- Google Sheets API: Free (subject to quota limits)

For a small group like SMAD, costs should be $0.

## Important Notes

1. **Only tracks future votes** - Votes cast before the webhook was set up cannot be retrieved
2. **Poll age limit** - Votes from polls older than 7 days are ignored
3. **Sunday cleanup** - Poll log entries older than 7 days are automatically deleted every Sunday
4. **Vote changes create new rows** - Full audit trail is maintained in Pickle Poll Log
5. **Column matching** - Date columns are matched by exact label match (first match from left to right)
