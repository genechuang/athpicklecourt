# SMAD WhatsApp Poll Webhook

This webhook tracks poll votes from the SMAD WhatsApp group, storing them in Google Cloud Firestore.

## Features

- **Tracks poll votes** - Captures who voted for what options
- **Handles vote changes** - When someone changes their vote, their selection is updated
- **"Cannot play" override** - If someone selects both play dates AND "I cannot play this week", only the "cannot play" option is kept (assumes they forgot to unselect dates)
- **Vote history** - Keeps an audit trail of vote changes

## Prerequisites

1. **Google Cloud account** with a project
2. **gcloud CLI** installed and authenticated
3. **GREEN-API account** (you should already have this for smad-whatsapp.py)

## Setup Instructions

### Step 1: Set up Google Cloud

```bash
# Install gcloud CLI if not already installed
# https://cloud.google.com/sdk/docs/install

# Login to Google Cloud
gcloud auth login

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Enable required APIs
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable firestore.googleapis.com
gcloud services enable cloudbuild.googleapis.com
```

### Step 2: Deploy the Cloud Function

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

### Step 4: Update your .env file

Add the GCP project ID:

```bash
GCP_PROJECT_ID=your_gcp_project_id
```

### Step 5: Install Firestore client locally

To use `show-votes` and `send-vote-reminders` commands:

```bash
pip install google-cloud-firestore
```

Or add to requirements.txt:
```
google-cloud-firestore==2.*
```

## Usage

After the webhook is deployed and configured:

```bash
# Show votes for the current poll
python smad-whatsapp.py show-votes

# Show votes for a specific poll
python smad-whatsapp.py show-votes --poll-id 3ADC47CA8A9698ABFD00

# Send DM reminders to players who haven't voted
python smad-whatsapp.py send-vote-reminders

# Preview reminders without sending (dry run)
python smad-whatsapp.py send-vote-reminders --dry-run
```

## Data Model

### Firestore Structure

```
Collection: smad_polls
└── Document: {poll_id}
    ├── question: "Can you play this week?"
    ├── chat_id: "120363401568722062@g.us"
    ├── created_at: timestamp
    ├── options: ["Sat 1/25", "Sun 1/26", "I cannot play this week"]
    │
    └── Subcollection: votes
        └── Document: {phone_number}
            ├── selected: ["Sat 1/25"]
            ├── updated_at: timestamp
            ├── voter_name: "John Doe"
            └── vote_history: [{selected: [...], timestamp: "..."}]
```

## Troubleshooting

### "No poll data found in Firestore"

- Make sure the webhook is deployed and the URL is configured in GREEN-API
- Check that at least one vote has been cast since the webhook was set up
- Verify `GCP_PROJECT_ID` is set correctly in your `.env` file

### Webhook not receiving events

1. Check GREEN-API dashboard for webhook delivery status
2. Look at Cloud Function logs:
   ```bash
   gcloud functions logs read smad-whatsapp-webhook --region=us-west1 --limit=50
   ```

### Authentication errors

- Make sure you're authenticated: `gcloud auth application-default login`
- Check that the service account has Firestore access

## Cost

This setup should stay within Google Cloud's free tier:
- Cloud Functions: 2 million invocations/month free
- Firestore: 1 GB storage, 50K reads/day, 20K writes/day free

For a small group like SMAD, costs should be $0.

## Important Notes

1. **Only tracks future votes** - Votes cast before the webhook was set up cannot be retrieved
2. **Poll options captured on first vote** - The webhook learns the poll options when the first vote comes in
3. **Vote changes replace previous** - WhatsApp sends the complete new selection, not a diff
