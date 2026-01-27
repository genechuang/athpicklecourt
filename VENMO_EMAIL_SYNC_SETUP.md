# Venmo Email-Triggered Sync Setup Guide

This guide explains how to set up **real-time Venmo payment sync** using Gmail email forwarding and Google Cloud Functions.

## Overview

When someone pays you on Venmo:
1. **Venmo** sends you an email ("@username paid you $X.XX")
2. **Gmail** forwards that email to a Cloud Function
3. **Cloud Function** triggers `venmo-sync`
4. **venmo-api** fetches recent transactions and matches by @username
5. **Payment Log** is updated automatically

**Result:** Payments appear in your sheet within **seconds** instead of waiting for the hourly/daily batch sync.

---

## Architecture

```
┌─────────┐      ┌─────────┐      ┌──────────────┐      ┌─────────────┐      ┌──────────────┐
│  Venmo  │─────>│  Gmail  │─────>│Cloud Function│─────>│  venmo-api  │─────>│ Payment Log  │
│ Payment │      │ Forward │      │  (trigger)   │      │ (username   │      │(Google Sheets)│
└─────────┘      └─────────┘      └──────────────┘      │  matching)  │      └──────────────┘
                                                          └─────────────┘
```

**Why this is better than email parsing:**
- ✅ Doesn't parse email content (robust to Venmo format changes)
- ✅ Matches by Venmo @username (handles "Gabe vs Gabriel", duplicate names)
- ✅ Reuses existing venmo-sync logic (same code as CLI)
- ✅ Automatic deduplication via transaction IDs
- ✅ Free (Google Cloud Functions free tier)

---

## Quick Start

### 1. Deploy Cloud Function

> **Note**: The Cloud Function is automatically deployed via CI/CD when changes are pushed to main.
> Infrastructure (Pub/Sub, IAM, function definition) is managed by Terraform.
> See [infra/terraform/README.md](infra/terraform/README.md) for details.

**Automatic Deployment (Recommended):**
- Push changes to `webhook/venmo-trigger/` on the `main` branch
- GitHub Actions workflow `deploy-webhook.yml` deploys automatically

**Manual Deployment (if needed):**
```bash
cd webhook/venmo-trigger

# Deploy to Google Cloud
gcloud functions deploy venmo-sync-trigger \
  --gen2 \
  --runtime=python311 \
  --region=us-west1 \
  --source=. \
  --entry-point=venmo_email_trigger \
  --trigger-topic=venmo-payment-emails \
  --set-env-vars SMAD_SPREADSHEET_ID=1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY \
  --set-secrets VENMO_ACCESS_TOKEN=VENMO_ACCESS_TOKEN:latest,SMAD_GOOGLE_CREDENTIALS_JSON=SMAD_GOOGLE_CREDENTIALS_JSON:latest
```

Get the function URL from Cloud Console or run:
```bash
gcloud functions describe venmo-sync-trigger --gen2 --region=us-west1 --format='value(serviceConfig.uri)'
```

### 2. Set Up Gmail Forwarding

**Option A: Gmail Filter + Apps Script** (Recommended)

1. Create a new Google Apps Script at [script.google.com](https://script.google.com)
2. Paste this code:

```javascript
function forwardVenmoToCloudFunction() {
  var CLOUD_FUNCTION_URL = 'https://YOUR-CLOUD-FUNCTION-URL';  // ← Update this
  var searchQuery = 'from:venmo@venmo.com subject:"paid you" is:unread';
  var threads = GmailApp.search(searchQuery, 0, 5);

  threads.forEach(function(thread) {
    var messages = thread.getMessages();
    messages.forEach(function(message) {
      // Trigger Cloud Function
      try {
        UrlFetchApp.fetch(CLOUD_FUNCTION_URL, {
          method: 'post',
          contentType: 'application/json',
          payload: JSON.stringify({
            from: message.getFrom(),
            subject: message.getSubject(),
            date: message.getDate().toISOString()
          }),
          muteHttpExceptions: true
        });

        // Mark as read to avoid reprocessing
        message.markRead();
        console.log('Forwarded: ' + message.getSubject());
      } catch (e) {
        console.error('Failed to forward: ' + e.toString());
      }
    });
  });
}
```

3. Set up a **trigger**:
   - Click ⏰ Triggers (left sidebar)
   - Add Trigger
   - Function: `forwardVenmoToCloudFunction`
   - Event source: **Time-driven**
   - Type: **Minutes timer**
   - Interval: **Every 5 minutes**
   - Save

4. Authorize the script when prompted

**Option B: n8n/Zapier** (Easiest, but costs $)

1. Create workflow in n8n or Zapier
2. **Trigger**: Gmail - New email matching filter
   - From: `venmo@venmo.com`
   - Subject contains: `paid you`
3. **Action**: HTTP Request
   - Method: POST
   - URL: Your Cloud Function URL
   - Body: `{"from": "{{trigger.from}}", "subject": "{{trigger.subject}}"}`

Cost: ~$5-20/month depending on provider

### 3. Test the Setup

Send yourself a Venmo payment, or trigger manually:

```bash
# Manual test
curl -X POST https://YOUR-CLOUD-FUNCTION-URL \
  -H "Content-Type: application/json" \
  -d '{"test": "manual trigger"}'

# Check logs
gcloud functions logs read venmo-sync-trigger --gen2 --region=us-west1 --limit=20
```

You should see:
```
[INFO] Venmo payment email received, triggering sync...
[INFO] Connecting to Venmo API...
[OK] Connected as: YOUR-USERNAME
[INFO] Found X existing transactions in Payment Log
[INFO] Fetching up to 50 recent transactions...
[OK] Recorded payment: John Doe - $8.00 (venmo)

=== Venmo Sync Summary ===
  Recorded: 1
  Skipped (already exists): 21
  Unmatched (no Venmo in sheet): 0
```

---

## Files Created

```
webhook/
├── shared/
│   ├── __init__.py              # Package init
│   └── venmo_sync.py            # Shared sync logic (reusable)
└── venmo-trigger/
    ├── main.py                  # Cloud Function entry point
    ├── requirements.txt         # Python dependencies
    └── README.md                # Detailed deployment docs
```

---

## Configuration

### Required Secrets (Google Secret Manager)

> **Note**: Secret structure and IAM bindings are managed by Terraform.
> Only secret *values* need to be added manually via the commands below.

1. **VENMO_ACCESS_TOKEN** - Add secret value:
   ```bash
   echo -n "YOUR_TOKEN" | gcloud secrets versions add VENMO_ACCESS_TOKEN --data-file=-
   ```

2. **SMAD_GOOGLE_CREDENTIALS_JSON** - Add secret value:
   ```bash
   gcloud secrets versions add SMAD_GOOGLE_CREDENTIALS_JSON --data-file=smad-credentials.json
   ```

IAM bindings for secret access are automatically configured by Terraform.

---

## Comparison: Email-Triggered vs Batch Sync

| Feature | Batch Sync (Current) | Email-Triggered (New) |
|---------|---------------------|----------------------|
| **Delay** | 1-24 hours (cron) | Seconds |
| **Trigger** | GitHub Actions cron | Gmail forward |
| **Cost** | Free | Free |
| **Setup** | Already done ✅ | New setup required |
| **Reliability** | High | High |
| **Maintenance** | None | Gmail script renewal |
| **Name Matching** | @username (good) | @username (good) |

**Recommendation:** Use **both**
- Email-triggered for real-time updates
- Daily batch as backup (catches anything missed)

---

## Monitoring

### View Recent Syncs

```bash
# Last 50 logs
gcloud functions logs read venmo-sync-trigger --gen2 --region=us-west1 --limit=50

# Follow logs in real-time
gcloud functions logs tail venmo-sync-trigger --gen2 --region=us-west1

# Filter for errors only
gcloud functions logs read venmo-sync-trigger --gen2 --region=us-west1 --limit=100 | grep ERROR
```

### Check Payment Log

Open your [Google Sheet](https://docs.google.com/spreadsheets/d/1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY/edit) and look at the "Payment Log" tab. Recent payments should have:
- **Recorded By**: `venmo-sync`
- **Recorded At**: Timestamp within seconds of payment

---

## Troubleshooting

### Issue: Emails not triggering function

**Check:**
1. Gmail script is running: [script.google.com](https://script.google.com) → Executions
2. Gmail filter is correct: `from:venmo@venmo.com subject:"paid you"`
3. Cloud Function URL is correct in script
4. Test manually: `curl -X POST https://YOUR-URL`

### Issue: "VENMO_ACCESS_TOKEN not configured"

**Fix:**
```bash
# Verify secret exists
gcloud secrets list | grep VENMO_ACCESS_TOKEN

# Check versions
gcloud secrets versions list VENMO_ACCESS_TOKEN

# Redeploy function
cd webhook/venmo-trigger
gcloud functions deploy venmo-sync-trigger --gen2 --region=us-west1
```

### Issue: Payments not matching players

**Check:**
- Player has Venmo username in Column F (e.g., `@john-doe`)
- Username matches exactly (case-insensitive)
- Look for `[UNMATCHED]` lines in logs

**Fix:**
1. Add missing Venmo usernames to sheet Column F
2. Run manual sync to catch up: `python payments-management.py sync-venmo`

---

## Cost

**Cloud Function:**
- Invocations: ~30/month (1 per payment)
- Duration: ~2-3 seconds each
- Memory: 256MB
- **Cost: $0/month** (Free tier: 2M invocations/month)

**Gmail Apps Script:** Free

**Total: $0/month** ✅

---

## Next Steps

1. ✅ Deploy Cloud Function (5 minutes)
2. ✅ Set up Gmail forwarding (10 minutes)
3. ✅ Test with manual trigger (1 minute)
4. ✅ Wait for next Venmo payment and verify auto-sync

---

## Maintenance

### Update Cloud Function

**Automatic (Recommended):**
Push changes to `main` branch - CI/CD deploys automatically via `deploy-webhook.yml`.

**Manual:**
```bash
cd webhook/venmo-trigger
gcloud functions deploy venmo-sync-trigger --gen2 --region=us-west1
```

### Rotate Venmo Token

```bash
# Get new token
python payments-management.py setup-venmo

# Update secret (new version is automatically used)
echo -n "NEW_TOKEN" | gcloud secrets versions add VENMO_ACCESS_TOKEN --data-file=-
```

No redeployment needed - the function uses `VENMO_ACCESS_TOKEN:latest`.

### Gmail Script Maintenance

Gmail Apps Script triggers may stop working after 6 months of inactivity. If this happens:
1. Go to [script.google.com](https://script.google.com)
2. Open your Venmo forwarder script
3. Re-enable the trigger

---

## Support

For issues:
1. Check logs: `gcloud functions logs read venmo-sync-trigger --gen2 --limit=50`
2. Test locally: `python payments-management.py sync-venmo`
3. Review detailed docs: `webhook/venmo-trigger/README.md`
