#!/bin/bash
# Deploy SMAD WhatsApp Poll Webhook to Google Cloud Functions
#
# Prerequisites:
# 1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
# 2. Authenticate: gcloud auth login
# 3. Set project: gcloud config set project YOUR_PROJECT_ID
# 4. Enable APIs:
#    gcloud services enable cloudfunctions.googleapis.com
#    gcloud services enable firestore.googleapis.com
#    gcloud services enable cloudbuild.googleapis.com
#
# Usage:
#   ./deploy.sh [PROJECT_ID] [REGION]
#
# Example:
#   ./deploy.sh my-gcp-project us-west1

set -e

# Configuration
PROJECT_ID="${1:-$(gcloud config get-value project)}"
REGION="${2:-us-west1}"
FUNCTION_NAME="smad-whatsapp-webhook"

if [ -z "$PROJECT_ID" ]; then
    echo "ERROR: No project ID specified and none set in gcloud config."
    echo "Usage: ./deploy.sh PROJECT_ID [REGION]"
    exit 1
fi

echo "=== Deploying SMAD WhatsApp Poll Webhook ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo ""

# Check if Firestore is initialized
echo "Checking Firestore..."
FIRESTORE_DB=$(gcloud firestore databases list --project="$PROJECT_ID" 2>/dev/null | grep "(default)" || true)
if [ -z "$FIRESTORE_DB" ]; then
    echo "Firestore not initialized. Creating database..."
    gcloud firestore databases create --project="$PROJECT_ID" --location="$REGION" --type=firestore-native
    echo "Firestore database created."
else
    echo "Firestore already initialized."
fi

# Deploy the function
echo ""
echo "Deploying Cloud Function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --runtime=python311 \
    --trigger-http \
    --allow-unauthenticated \
    --entry-point=webhook \
    --source=. \
    --memory=256MB \
    --timeout=60s \
    --gen2

# Get the function URL
echo ""
echo "=== Deployment Complete ==="
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --gen2 \
    --format='value(serviceConfig.uri)')

echo ""
echo "Webhook URL: $FUNCTION_URL"
echo ""
echo "=== Next Steps ==="
echo "1. Go to GREEN-API dashboard: https://console.green-api.com/"
echo "2. Select your instance (ID: check your .env file)"
echo "3. Go to 'Webhooks' or 'Instance Settings'"
echo "4. Set webhook URL to: $FUNCTION_URL"
echo "5. Enable these webhook types:"
echo "   - incomingMessageReceived (for incoming poll votes)"
echo "   - outgoingMessageReceived (for polls you create)"
echo ""
echo "6. Add to your .env file:"
echo "   GCP_PROJECT_ID=$PROJECT_ID"
echo ""
