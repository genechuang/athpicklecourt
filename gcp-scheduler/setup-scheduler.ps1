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

    gcloud scheduler jobs delete poll-creation --project=$PROJECT_ID --location=$REGION --quiet 2>$null
    gcloud scheduler jobs delete vote-payment-reminders --project=$PROJECT_ID --location=$REGION --quiet 2>$null
    gcloud scheduler jobs delete gmail-watch-renewal --project=$PROJECT_ID --location=$REGION --quiet 2>$null
    gcloud scheduler jobs delete court-booking --project=$PROJECT_ID --location=$REGION --quiet 2>$null
    # Also delete old job names for cleanup
    gcloud scheduler jobs delete weekly-poll-creation --project=$PROJECT_ID --location=$REGION --quiet 2>$null
    gcloud scheduler jobs delete daily-payment-reminders --project=$PROJECT_ID --location=$REGION --quiet 2>$null
    gcloud scheduler jobs delete daily-court-booking --project=$PROJECT_ID --location=$REGION --quiet 2>$null

    Write-Host "Done!" -ForegroundColor Green
    exit 0
}

# Test action - triggers workflows with dry_run=true via GitHub API directly
if ($Action -eq "test") {
    Write-Host "Testing Cloud Scheduler -> GitHub API integration (DRY RUN MODE)..." -ForegroundColor Yellow
    Write-Host ""

    # Get GitHub token
    $GITHUB_TOKEN = gcloud secrets versions access latest --secret=github-actions-token --project=$PROJECT_ID
    if ([string]::IsNullOrEmpty($GITHUB_TOKEN)) {
        Write-Host "Error: Could not retrieve GitHub token" -ForegroundColor Red
        exit 1
    }

    $Headers = @{
        "Authorization" = "Bearer $GITHUB_TOKEN"
        "Accept" = "application/vnd.github.v3+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    Write-Host "1. Testing poll-creation (dry-run)..."
    $Body = '{"ref":"main","inputs":{"dry_run":"true"}}'
    try {
        Invoke-RestMethod -Uri "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/poll-creation.yml/dispatches" -Method POST -Headers $Headers -Body $Body -ContentType "application/json"
        Write-Host "   Triggered!" -ForegroundColor Green
    } catch {
        Write-Host "   Failed: $_" -ForegroundColor Red
    }

    Write-Host "2. Testing vote-payment-reminders (dry-run)..."
    $Body = '{"ref":"main","inputs":{"dry_run":"true"}}'
    try {
        Invoke-RestMethod -Uri "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/vote-payment-reminders.yml/dispatches" -Method POST -Headers $Headers -Body $Body -ContentType "application/json"
        Write-Host "   Triggered!" -ForegroundColor Green
    } catch {
        Write-Host "   Failed: $_" -ForegroundColor Red
    }

    Write-Host "3. Testing gmail-watch-renewal..."
    Write-Host "   (No dry-run mode - skipping to avoid unnecessary renewal)" -ForegroundColor Yellow

    Write-Host "4. Testing court-booking..."
    Write-Host "   (No dry-run mode - skipping to avoid booking courts)" -ForegroundColor Yellow

    Write-Host ""
    Write-Host "Done! Check GitHub Actions for triggered workflows (should show DRY RUN)." -ForegroundColor Green
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

# Write JSON bodies to temp files (avoids PowerShell escaping issues)
$TempDir = [System.IO.Path]::GetTempPath()

# Job 1: Poll Creation (Sunday 10:00 AM PST)
Write-Host "1. Creating poll-creation (Sunday 10:00 AM PST)..."
$URI = "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/poll-creation.yml/dispatches"
$BodyFile1 = Join-Path $TempDir "body1.json"
'{"ref":"main","inputs":{"dry_run":"false"}}' | Out-File -FilePath $BodyFile1 -Encoding ASCII -NoNewline

gcloud scheduler jobs delete poll-creation --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs delete weekly-poll-creation --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs create http poll-creation `
    --project=$PROJECT_ID `
    --location=$REGION `
    --schedule="0 10 * * 0" `
    --time-zone="America/Los_Angeles" `
    --uri=$URI `
    --http-method=POST `
    --headers=$HEADERS `
    --message-body-from-file=$BodyFile1 `
    --description="Triggers weekly availability poll creation on Sundays at 10am PST"

Write-Host "   Created!" -ForegroundColor Green

# Job 2: Vote & Payment Reminders (Daily 8:00 AM PST)
Write-Host "2. Creating vote-payment-reminders (Daily 8:00 AM PST)..."
$URI = "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/vote-payment-reminders.yml/dispatches"
$BodyFile2 = Join-Path $TempDir "body2.json"
'{"ref":"main","inputs":{"dry_run":"false"}}' | Out-File -FilePath $BodyFile2 -Encoding ASCII -NoNewline

gcloud scheduler jobs delete vote-payment-reminders --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs delete daily-payment-reminders --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs create http vote-payment-reminders `
    --project=$PROJECT_ID `
    --location=$REGION `
    --schedule="0 8 * * *" `
    --time-zone="America/Los_Angeles" `
    --uri=$URI `
    --http-method=POST `
    --headers=$HEADERS `
    --message-body-from-file=$BodyFile2 `
    --description="Triggers daily vote and payment reminders at 8:00am PST"

Write-Host "   Created!" -ForegroundColor Green

# Job 3: Gmail Watch Renewal (6:00 PM PST on days 1,7,13,19,25)
Write-Host "3. Creating gmail-watch-renewal (6:00 PM PST on days 1,7,13,19,25)..."
$URI = "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/gmail-watch-renewal.yml/dispatches"
$BodyFile3 = Join-Path $TempDir "body3.json"
'{"ref":"main"}' | Out-File -FilePath $BodyFile3 -Encoding ASCII -NoNewline

gcloud scheduler jobs delete gmail-watch-renewal --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs create http gmail-watch-renewal `
    --project=$PROJECT_ID `
    --location=$REGION `
    --schedule="0 18 1,7,13,19,25 * *" `
    --time-zone="America/Los_Angeles" `
    --uri=$URI `
    --http-method=POST `
    --headers=$HEADERS `
    --message-body-from-file=$BodyFile3 `
    --description="Renews Gmail watch subscription every 6 days (before 7-day expiry)"

Write-Host "   Created!" -ForegroundColor Green

# Job 4: Court Booking (11:55 PM PST - early trigger for GHA warm-up)
# Script waits until BOOKING_TARGET_TIME (00:01:00) before booking
Write-Host "4. Creating court-booking (Daily 11:55 PM PST)..."
$URI = "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/court-booking.yml/dispatches"
$BodyFile4 = Join-Path $TempDir "body4.json"
'{"ref":"main"}' | Out-File -FilePath $BodyFile4 -Encoding ASCII -NoNewline

gcloud scheduler jobs delete court-booking --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs delete daily-court-booking --project=$PROJECT_ID --location=$REGION --quiet 2>$null
gcloud scheduler jobs create http court-booking `
    --project=$PROJECT_ID `
    --location=$REGION `
    --schedule="55 23 * * *" `
    --time-zone="America/Los_Angeles" `
    --uri=$URI `
    --http-method=POST `
    --headers=$HEADERS `
    --message-body-from-file=$BodyFile4 `
    --description="Triggers court booking at 11:55 PM PST (warm-up), script waits until 00:01 AM"

Write-Host "   Created!" -ForegroundColor Green

# Cleanup temp files
Remove-Item $BodyFile1, $BodyFile2, $BodyFile3, $BodyFile4 -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== All Cloud Scheduler jobs created successfully! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Jobs created:"
gcloud scheduler jobs list --project=$PROJECT_ID --location=$REGION

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Test jobs: .\setup-scheduler.ps1 test"
Write-Host "2. Check GitHub Actions for triggered workflows"
