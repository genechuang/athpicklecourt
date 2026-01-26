#!/bin/bash
# Setup Google Cloud Scheduler jobs to trigger GitHub Actions workflows
#
# Prerequisites:
# 1. gcloud CLI installed and authenticated
# 2. GitHub PAT stored in GCP Secret Manager as 'github-actions-token'
# 3. Cloud Scheduler API enabled: gcloud services enable cloudscheduler.googleapis.com
#
# Usage:
#   ./setup-scheduler.sh          # Create all jobs
#   ./setup-scheduler.sh delete   # Delete all jobs
#   ./setup-scheduler.sh test     # Test run all jobs

set -e

PROJECT_ID="smad-pickleball"
REGION="us-west1"
GITHUB_REPO="genechuang/SMADPickleBot"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== SMAD PickleBot Cloud Scheduler Setup ===${NC}"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Check if we're deleting
if [ "$1" == "delete" ]; then
    echo -e "${YELLOW}Deleting all Cloud Scheduler jobs...${NC}"

    gcloud scheduler jobs delete weekly-poll-creation \
        --project=$PROJECT_ID \
        --location=$REGION \
        --quiet 2>/dev/null || echo "weekly-poll-creation not found"

    gcloud scheduler jobs delete daily-payment-reminders \
        --project=$PROJECT_ID \
        --location=$REGION \
        --quiet 2>/dev/null || echo "daily-payment-reminders not found"

    gcloud scheduler jobs delete gmail-watch-renewal \
        --project=$PROJECT_ID \
        --location=$REGION \
        --quiet 2>/dev/null || echo "gmail-watch-renewal not found"

    echo -e "${GREEN}Done!${NC}"
    exit 0
fi

# Check if we're testing
if [ "$1" == "test" ]; then
    echo -e "${YELLOW}Running all Cloud Scheduler jobs manually...${NC}"

    echo "Running weekly-poll-creation..."
    gcloud scheduler jobs run weekly-poll-creation \
        --project=$PROJECT_ID \
        --location=$REGION || echo "Failed"

    echo "Running daily-payment-reminders..."
    gcloud scheduler jobs run daily-payment-reminders \
        --project=$PROJECT_ID \
        --location=$REGION || echo "Failed"

    echo "Running gmail-watch-renewal..."
    gcloud scheduler jobs run gmail-watch-renewal \
        --project=$PROJECT_ID \
        --location=$REGION || echo "Failed"

    echo -e "${GREEN}Done! Check GitHub Actions for triggered workflows.${NC}"
    exit 0
fi

# Get GitHub token from Secret Manager
echo "Retrieving GitHub token from Secret Manager..."
GITHUB_TOKEN=$(gcloud secrets versions access latest --secret=github-actions-token --project=$PROJECT_ID)

if [ -z "$GITHUB_TOKEN" ]; then
    echo -e "${RED}Error: Could not retrieve GitHub token from Secret Manager${NC}"
    echo "Make sure you've created the secret:"
    echo "  gcloud secrets create github-actions-token --project=$PROJECT_ID"
    echo "  echo -n 'YOUR_GITHUB_PAT' | gcloud secrets versions add github-actions-token --data-file=- --project=$PROJECT_ID"
    exit 1
fi

echo -e "${GREEN}GitHub token retrieved successfully${NC}"
echo ""

# Enable Cloud Scheduler API
echo "Enabling Cloud Scheduler API..."
gcloud services enable cloudscheduler.googleapis.com --project=$PROJECT_ID

# Create jobs
echo ""
echo -e "${YELLOW}Creating Cloud Scheduler jobs...${NC}"
echo ""

# Job 1: Weekly Poll Creation (Sunday 10:00 AM PST)
echo "1. Creating weekly-poll-creation (Sunday 10:00 AM PST)..."
gcloud scheduler jobs create http weekly-poll-creation \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="0 10 * * 0" \
    --time-zone="America/Los_Angeles" \
    --uri="https://api.github.com/repos/$GITHUB_REPO/actions/workflows/weekly-poll-creation.yml/dispatches" \
    --http-method=POST \
    --headers="Authorization=Bearer $GITHUB_TOKEN,Accept=application/vnd.github.v3+json,X-GitHub-Api-Version=2022-11-28" \
    --message-body='{"ref":"main","inputs":{"dry_run":"false"}}' \
    --description="Triggers weekly availability poll creation on Sundays at 10am PST" \
    2>/dev/null || gcloud scheduler jobs update http weekly-poll-creation \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="0 10 * * 0" \
    --time-zone="America/Los_Angeles" \
    --uri="https://api.github.com/repos/$GITHUB_REPO/actions/workflows/weekly-poll-creation.yml/dispatches" \
    --http-method=POST \
    --headers="Authorization=Bearer $GITHUB_TOKEN,Accept=application/vnd.github.v3+json,X-GitHub-Api-Version=2022-11-28" \
    --message-body='{"ref":"main","inputs":{"dry_run":"false"}}' \
    --description="Triggers weekly availability poll creation on Sundays at 10am PST"

echo -e "${GREEN}   Created!${NC}"

# Job 2: Daily Payment Reminders (Daily 10:00 AM PST)
echo "2. Creating daily-payment-reminders (Daily 10:00 AM PST)..."
gcloud scheduler jobs create http daily-payment-reminders \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="0 10 * * *" \
    --time-zone="America/Los_Angeles" \
    --uri="https://api.github.com/repos/$GITHUB_REPO/actions/workflows/daily-booking.yml/dispatches" \
    --http-method=POST \
    --headers="Authorization=Bearer $GITHUB_TOKEN,Accept=application/vnd.github.v3+json,X-GitHub-Api-Version=2022-11-28" \
    --message-body='{"ref":"main","inputs":{"job_type":"payment-reminders","dry_run":"false"}}' \
    --description="Triggers daily payment and vote reminders at 10am PST" \
    2>/dev/null || gcloud scheduler jobs update http daily-payment-reminders \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="0 10 * * *" \
    --time-zone="America/Los_Angeles" \
    --uri="https://api.github.com/repos/$GITHUB_REPO/actions/workflows/daily-booking.yml/dispatches" \
    --http-method=POST \
    --headers="Authorization=Bearer $GITHUB_TOKEN,Accept=application/vnd.github.v3+json,X-GitHub-Api-Version=2022-11-28" \
    --message-body='{"ref":"main","inputs":{"job_type":"payment-reminders","dry_run":"false"}}' \
    --description="Triggers daily payment and vote reminders at 10am PST"

echo -e "${GREEN}   Created!${NC}"

# Job 3: Gmail Watch Renewal (6:00 PM PST on days 1,7,13,19,25)
echo "3. Creating gmail-watch-renewal (6:00 PM PST on days 1,7,13,19,25)..."
gcloud scheduler jobs create http gmail-watch-renewal \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="0 18 1,7,13,19,25 * *" \
    --time-zone="America/Los_Angeles" \
    --uri="https://api.github.com/repos/$GITHUB_REPO/actions/workflows/gmail-watch-renewal.yml/dispatches" \
    --http-method=POST \
    --headers="Authorization=Bearer $GITHUB_TOKEN,Accept=application/vnd.github.v3+json,X-GitHub-Api-Version=2022-11-28" \
    --message-body='{"ref":"main"}' \
    --description="Renews Gmail watch subscription every 6 days (before 7-day expiry)" \
    2>/dev/null || gcloud scheduler jobs update http gmail-watch-renewal \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="0 18 1,7,13,19,25 * *" \
    --time-zone="America/Los_Angeles" \
    --uri="https://api.github.com/repos/$GITHUB_REPO/actions/workflows/gmail-watch-renewal.yml/dispatches" \
    --http-method=POST \
    --headers="Authorization=Bearer $GITHUB_TOKEN,Accept=application/vnd.github.v3+json,X-GitHub-Api-Version=2022-11-28" \
    --message-body='{"ref":"main"}' \
    --description="Renews Gmail watch subscription every 6 days (before 7-day expiry)"

echo -e "${GREEN}   Created!${NC}"

echo ""
echo -e "${GREEN}=== All Cloud Scheduler jobs created successfully! ===${NC}"
echo ""
echo "Jobs created:"
gcloud scheduler jobs list --project=$PROJECT_ID --location=$REGION

echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Test jobs manually: ./setup-scheduler.sh test"
echo "2. Check GitHub Actions for triggered workflows"
echo "3. Remove redundant crons from GHA workflow files"
