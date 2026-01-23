# Gmail Watch Setup Guide

Complete guide to set up Gmail API watch for instant Venmo payment notifications.

---

## Overview

This sets up **true push notifications** from Gmail → Cloud Pub/Sub → Cloud Function:

```
Venmo email arrives → Gmail → Gmail API watch → Cloud Pub/Sub → Cloud Function → venmo-sync → Payment Log
                               (instant)         (instant)      (instant)        (<5 sec)
```

**Total delay: <5 seconds** ⚡

---

## Prerequisites

✅ Cloud Function deployed (already done)
✅ Cloud Pub/Sub topic created (already done)
✅ Gmail API enabled (already done)

---

## Step 1: Create OAuth Credentials (One-time Setup)

1. **Go to Google Cloud Console - Credentials**
   https://console.cloud.google.com/apis/credentials?project=smad-pickleball

2. **Configure OAuth Consent Screen** (if not already done):
   - Click **"OAuth consent screen"** (left sidebar)
   - User Type: **External** (or Internal if you have Google Workspace)
   - App name: `SMAD Gmail Watch`
   - User support email: `genechuang@gmail.com`
   - Developer contact: `genechuang@gmail.com`
   - Scopes: Click **"Add or Remove Scopes"**
     - Search for `gmail.readonly`
     - Check the box
     - Click **"Update"**
   - Test users: Add `genechuang@gmail.com`
   - Click **"Save and Continue"**

3. **Create OAuth Client ID**:
   - Go back to **"Credentials"** tab
   - Click **"+ CREATE CREDENTIALS"** → **"OAuth client ID"**
   - Application type: **Desktop app**
   - Name: `SMAD Gmail Watch Desktop`
   - Click **"CREATE"**

4. **Download Credentials**:
   - Click the download icon (⬇️) next to your newly created OAuth client
   - Save the file as `gmail-credentials.json` in the project root:
     ```bash
     # Move downloaded file to project
     mv ~/Downloads/client_secret_*.json d:/code/SMADPickleBot/gmail-credentials.json
     ```

---

## Step 2: Run Initial Gmail Watch Setup

```bash
cd d:/code/SMADPickleBot
python setup-gmail-watch.py
```

**What happens:**
1. Script opens your browser
2. You sign in to Gmail (genechuang@gmail.com)
3. You grant permission to "See your email messages and settings"
4. Script sets up the watch
5. Watch is active for 7 days

**Expected output:**
```
[INFO] Setting up Gmail watch...
  Topic: projects/smad-pickleball/topics/venmo-payment-emails
  Labels: INBOX

[OK] Gmail watch configured successfully!
  History ID: 123456
  Expires: 2026-01-30 02:15:00 (7 days from now)

[NOTE] Watch will expire in ~7 days. Run this script again to renew.
```

**Files created:**
- `gmail-token.json` - Contains OAuth refresh token (NEVER commit this!)

---

## Step 3: Add Secrets to GitHub

The GitHub Actions workflow needs these secrets to renew the watch automatically.

### 3a. Get gmail-credentials.json content

```bash
cat gmail-credentials.json | jq -c
```

Copy the entire JSON output (should be one line).

### 3b. Get gmail-token.json content

```bash
cat gmail-token.json | jq -c
```

Copy the entire JSON output.

### 3c. Add to GitHub Secrets

1. Go to **GitHub Repository Settings**:
   https://github.com/genechuang/SMADPickleBot/settings/secrets/actions

2. Click **"New repository secret"**

3. Add **GMAIL_OAUTH_CLIENT_JSON**:
   - Name: `GMAIL_OAUTH_CLIENT_JSON`
   - Value: Paste the `gmail-credentials.json` content
   - Click **"Add secret"**

4. Add **GMAIL_OAUTH_TOKEN_JSON**:
   - Name: `GMAIL_OAUTH_TOKEN_JSON`
   - Value: Paste the `gmail-token.json` content
   - Click **"Add secret"**

---

## Step 4: Test the Setup

### Test 1: Manual test with Pub/Sub

```bash
# Publish a test message to Pub/Sub (simulates Gmail notification)
gcloud pubsub topics publish venmo-payment-emails --message='{"emailAddress":"genechuang@gmail.com","historyId":"12345"}'

# Check Cloud Function logs
gcloud functions logs read venmo-sync-trigger --gen2 --region=us-west1 --limit=20
```

### Test 2: Real Venmo payment

1. Send yourself a small Venmo payment ($1)
2. Wait a few seconds
3. Check Payment Log sheet
4. Should see the payment appear within 5-10 seconds

### Test 3: Check Gmail watch status

```bash
python setup-gmail-watch.py --status
```

---

## Step 5: Verify GitHub Actions Workflow

The workflow runs automatically every 6 days, but you can test it manually:

1. Go to **GitHub Actions**:
   https://github.com/genechuang/SMADPickleBot/actions/workflows/gmail-watch-renewal.yml

2. Click **"Run workflow"** → **"Run workflow"**

3. Wait for it to complete (~30 seconds)

4. Check the logs to ensure watch was renewed

---

## Maintenance

### Watch Expiration

Gmail watches expire after **7 days**. The GitHub Actions workflow renews it every 6 days automatically.

**Schedule:**
- Runs on days: 1, 7, 13, 19, 25 of every month
- Time: 2:00 AM UTC (6:00 PM PST previous day)

### Manual Renewal

If the watch expires (or you want to renew it early):

```bash
python setup-gmail-watch.py --renew
```

### Stop the Watch

If you need to stop the watch:

```bash
python setup-gmail-watch.py --stop
```

---

## Troubleshooting

### Issue: "Gmail API has not been used"

**Fix:**
```bash
gcloud services enable gmail.googleapis.com
# Wait 5 minutes, then try again
```

### Issue: "Token has been expired or revoked"

**Cause:** OAuth token expired (refresh token no longer valid)

**Fix:**
1. Delete `gmail-token.json`
2. Run `python setup-gmail-watch.py` again
3. Re-authorize in browser
4. Update `GMAIL_OAUTH_TOKEN_JSON` secret in GitHub

### Issue: "Pub/Sub topic not found"

**Fix:**
```bash
# Verify topic exists
gcloud pubsub topics list

# Recreate if needed
gcloud pubsub topics create venmo-payment-emails

# Grant Gmail permission
gcloud pubsub topics add-iam-policy-binding venmo-payment-emails \
  --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
  --role=roles/pubsub.publisher
```

### Issue: Watch not triggering on Venmo emails

**Check:**
1. Watch is active: `python setup-gmail-watch.py --status`
2. Venmo emails are arriving in inbox (not spam)
3. Cloud Function is deployed: `gcloud functions describe venmo-sync-trigger --gen2 --region=us-west1`
4. Pub/Sub subscription exists: `gcloud pubsub subscriptions list`

**Debug:**
```bash
# Check recent Pub/Sub messages
gcloud logging read "resource.type=pubsub_topic AND resource.labels.topic_id=venmo-payment-emails" --limit=20 --format=json

# Check Cloud Function invocations
gcloud functions logs read venmo-sync-trigger --gen2 --region=us-west1 --limit=50
```

### Issue: "OAuth consent screen not configured"

This happens if you haven't set up the OAuth consent screen.

**Fix:** Follow Step 1 above to configure the consent screen.

---

## Architecture Details

### Components

1. **Gmail API Watch**
   - Monitors inbox for new emails
   - Publishes notifications to Cloud Pub/Sub
   - Expires after 7 days (must be renewed)

2. **Cloud Pub/Sub Topic** (`venmo-payment-emails`)
   - Receives notifications from Gmail
   - Triggers Cloud Function

3. **Cloud Function** (`venmo-sync-trigger`)
   - Triggered by Pub/Sub messages
   - Runs venmo-sync to fetch and match payments

4. **GitHub Actions Workflow**
   - Renews Gmail watch every 6 days
   - Runs on schedule: days 1, 7, 13, 19, 25 of each month

### Data Flow

```
1. Venmo sends payment email to Gmail
2. Gmail detects new email matching watch filter (INBOX)
3. Gmail publishes notification to Pub/Sub topic
   {
     "emailAddress": "genechuang@gmail.com",
     "historyId": "123456"
   }
4. Cloud Pub/Sub delivers message to Cloud Function
5. Cloud Function triggers venmo-sync
6. venmo-sync fetches recent transactions from Venmo API
7. Matches transactions by @username to players in sheet
8. Updates Payment Log sheet
```

### Security

- ✅ OAuth credentials stored in GitHub Secrets (encrypted)
- ✅ Gmail read-only access (can't send or delete emails)
- ✅ Pub/Sub topic has restricted IAM permissions
- ✅ Cloud Function runs with dedicated service account
- ✅ Token file never committed to git (.gitignore)

---

## Cost

**Gmail API:** Free (unlimited watches)
**Cloud Pub/Sub:** Free tier covers this (~30 messages/month)
**Cloud Functions:** Free tier covers this (~30 invocations/month)
**GitHub Actions:** Free (2000 minutes/month, uses <1 minute/month)

**Total: $0/month** ✅

---

## Alternative: Filter by Venmo Emails Only

Currently, the watch monitors the entire INBOX. To reduce noise, you can create a Gmail label and watch only that label:

### Step 1: Create Gmail Label

1. Go to Gmail → Settings → Filters
2. Create filter:
   - From: `venmo@venmo.com`
   - Subject: `paid you`
3. Action: Apply label `VenmoPayments` (create new)

### Step 2: Get Label ID

```bash
# List all labels and find the ID
python -c "
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

creds = Credentials.from_authorized_user_file('gmail-token.json')
service = build('gmail', 'v1', credentials=creds)
labels = service.users().labels().list(userId='me').execute()

for label in labels.get('labels', []):
    if 'Venmo' in label['name']:
        print(f\"{label['name']}: {label['id']}\")
"
```

### Step 3: Update Watch

```bash
python setup-gmail-watch.py --labels LABEL_ID_HERE --renew
```

This reduces notifications to only Venmo payment emails.

---

## Support

For issues:
1. Check logs: `gcloud functions logs read venmo-sync-trigger --gen2 --limit=50`
2. Test locally: `python setup-gmail-watch.py --status`
3. Manual trigger: `python setup-gmail-watch.py --renew`
4. Review [Gmail API Push Notifications Docs](https://developers.google.com/workspace/gmail/api/guides/push)
