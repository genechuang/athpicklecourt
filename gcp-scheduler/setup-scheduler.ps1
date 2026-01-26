# Setup Google Cloud Scheduler jobs to trigger GitHub Actions workflows
#
# Prerequisites:
# 1. gcloud CLI installed and authenticated
# 2. GitHub PAT stored in GCP Secret Manager as 'github-actions-token'
# 3. Cloud Scheduler API enabled
#
# Usage:
#   .\setup-scheduler.ps1          # Create all jobs
#   .\setup-scheduler.ps1 delete   # Delete all jobs
#   .\setup-scheduler.ps1 test     # Test run all jobs

param(
    [string]$Action = "create"
)

$PROJECT_ID = "smad-pickleball"
$REGION = "us-west1"
$GITHUB_REPO = "genechuang/SMADPickleBot"

Write-Host "=== SMAD PickleBot Cloud Scheduler Setup ===" -ForegroundColor Green
Write-Host "Project: $PROJECT_ID"
Write-Host "Region: $REGION"
Write-Host ""

# Delete action
if ($Action -eq "delete") {
    Write-Host "Deleting all Cloud Scheduler jobs..." -ForegroundColor Yellow

    gcloud scheduler jobs delete weekly-poll-creation --project=$PROJECT_ID --location=$REGION --quiet 2>$null
    gcloud scheduler jobs delete daily-payment-reminders --project=$PROJECT_ID --location=$REGION --quiet 2>$null
    gcloud scheduler jobs delete gmail-watch-renewal --project=$PROJECT_ID --location=$REGION --quiet 2>$null

    Write-Host "Done!" -ForegroundColor Green
    exit 0
}

# Test action
if ($Action -eq "test") {
    Write-Host "Running all Cloud Scheduler jobs manually..." -ForegroundColor Yellow

    Write-Host "Running weekly-poll-creation..."
    gcloud scheduler jobs run weekly-poll-creation --project=$PROJECT_ID --location=$REGION

    Write-Host "Running daily-payment-reminders..."
    gcloud scheduler jobs run daily-payment-reminders --project=$PROJECT_ID --location=$REGION

    Write-Host "Running gmail-watch-renewal..."
    gcloud scheduler jobs run gmail-watch-renewal --project=$PROJECT_ID --location=$REGION

    Write-Host "Done! Check GitHub Actions for triggered workflows." -ForegroundColor Green
    exit 0
}

# Create action
Write-Host "Retrieving GitHub token from Secret Manager..."
$GITHUB_TOKEN = gcloud secrets versions access latest --secret=github-actions-token --project=$PROJECT_ID

if ([string]::IsNullOrEmpty($GITHUB_TOKEN)) {
    Write-Host "Error: Could not retrieve GitHub token from Secret Manager" -ForegroundColor Red
    Write-Host "Make sure you've created the secret:"
    Write-Host "  gcloud secrets create github-actions-token --project=$PROJECT_ID"
    Write-Host "  echo 'YOUR_GITHUB_PAT' | gcloud secrets versions add github-actions-token --data-file=- --project=$PROJECT_ID"
    exit 1
}

Write-Host "GitHub token retrieved successfully" -ForegroundColor Green
Write-Host ""

# Enable Cloud Scheduler API
Write-Host "Enabling Cloud Scheduler API..."
gcloud services enable cloudscheduler.googleapis.com --project=$PROJECT_ID

Write-Host ""
Write-Host "Creating Cloud Scheduler jobs..." -ForegroundColor Yellow
Write-Host ""

$HEADERS = "Authorization=Bearer $GITHUB_TOKEN,Accept=application/vnd.github.v3+json,X-GitHub-Api-Version=2022-11-28"

# Job 1: Weekly Poll Creation (Sunday 10:00 AM PST)
Write-Host "1. Creating weekly-poll-creation (Sunday 10:00 AM PST)..."
$URI = "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/weekly-poll-creation.yml/dispatches"
$BODY = '{"ref":"main","inputs":{"dry_run":"false"}}'

gcloud scheduler jobs delete weekly-poll-creation --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs create http weekly-poll-creation `
    --project=$PROJECT_ID `
    --location=$REGION `
    --schedule="0 10 * * 0" `
    --time-zone="America/Los_Angeles" `
    --uri=$URI `
    --http-method=POST `
    --headers=$HEADERS `
    --message-body=$BODY `
    --description="Triggers weekly availability poll creation on Sundays at 10am PST"

Write-Host "   Created!" -ForegroundColor Green

# Job 2: Daily Payment Reminders (Daily 10:00 AM PST)
Write-Host "2. Creating daily-payment-reminders (Daily 10:00 AM PST)..."
$URI = "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/daily-booking.yml/dispatches"
$BODY = '{"ref":"main","inputs":{"job_type":"payment-reminders","dry_run":"false"}}'

gcloud scheduler jobs delete daily-payment-reminders --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs create http daily-payment-reminders `
    --project=$PROJECT_ID `
    --location=$REGION `
    --schedule="0 10 * * *" `
    --time-zone="America/Los_Angeles" `
    --uri=$URI `
    --http-method=POST `
    --headers=$HEADERS `
    --message-body=$BODY `
    --description="Triggers daily payment and vote reminders at 10am PST"

Write-Host "   Created!" -ForegroundColor Green

# Job 3: Gmail Watch Renewal (6:00 PM PST on days 1,7,13,19,25)
Write-Host "3. Creating gmail-watch-renewal (6:00 PM PST on days 1,7,13,19,25)..."
$URI = "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/gmail-watch-renewal.yml/dispatches"
$BODY = '{"ref":"main"}'

gcloud scheduler jobs delete gmail-watch-renewal --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs create http gmail-watch-renewal `
    --project=$PROJECT_ID `
    --location=$REGION `
    --schedule="0 18 1,7,13,19,25 * *" `
    --time-zone="America/Los_Angeles" `
    --uri=$URI `
    --http-method=POST `
    --headers=$HEADERS `
    --message-body=$BODY `
    --description="Renews Gmail watch subscription every 6 days (before 7-day expiry)"

Write-Host "   Created!" -ForegroundColor Green

Write-Host ""
Write-Host "=== All Cloud Scheduler jobs created successfully! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Jobs created:"
gcloud scheduler jobs list --project=$PROJECT_ID --location=$REGION

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Test jobs: .\setup-scheduler.ps1 test"
Write-Host "2. Check GitHub Actions for triggered workflows"
