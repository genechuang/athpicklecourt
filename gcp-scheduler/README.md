# Google Cloud Scheduler Setup

This directory contains scripts to manage Google Cloud Scheduler jobs that trigger GitHub Actions workflows.

## Why Cloud Scheduler?

GitHub Actions cron schedules are unreliable for workflows created after the initial repository setup. Only the original `daily-booking.yml` has working scheduled triggers. Cloud Scheduler provides reliable, timezone-aware scheduling.

## Prerequisites

1. **Google Cloud CLI** installed and authenticated
2. **GCP Project**: `smad-pickleball`
3. **GitHub Personal Access Token (PAT)** with `Actions: Read and Write` permission

## Setup Instructions

### Step 1: Create GitHub PAT

1. Go to https://github.com/settings/tokens?type=beta
2. Click "Generate new token"
3. Configure:
   - **Token name**: `SMAD-PickleBot-CloudScheduler`
   - **Expiration**: 90 days (or longer)
   - **Repository access**: Only select repositories → `genechuang/SMADPickleBot`
   - **Permissions**:
     - Repository permissions → Actions: Read and write
4. Click "Generate token" and copy the token

### Step 2: Store PAT in GCP Secret Manager

```bash
# Create the secret
gcloud secrets create github-actions-token --project=smad-pickleball

# Add the token value
echo -n 'YOUR_GITHUB_PAT_HERE' | gcloud secrets versions add github-actions-token --data-file=- --project=smad-pickleball
```

### Step 3: Run Setup Script

```bash
cd gcp-scheduler
chmod +x setup-scheduler.sh
./setup-scheduler.sh
```

## Scheduled Jobs

| Job Name | Schedule | Description |
|----------|----------|-------------|
| `weekly-poll-creation` | Sunday 10:00 AM PST | Creates weekly availability poll |
| `daily-payment-reminders` | Daily 10:00 AM PST | Syncs Venmo, sends payment/vote reminders |
| `gmail-watch-renewal` | Days 1,7,13,19,25 at 6:00 PM PST | Renews Gmail watch (before 7-day expiry) |

## Commands

```bash
# Create all jobs
./setup-scheduler.sh

# Delete all jobs
./setup-scheduler.sh delete

# Manually run all jobs (for testing)
./setup-scheduler.sh test

# Run a single job manually
gcloud scheduler jobs run weekly-poll-creation --project=smad-pickleball --location=us-west1

# List all jobs
gcloud scheduler jobs list --project=smad-pickleball --location=us-west1

# View job details
gcloud scheduler jobs describe daily-payment-reminders --project=smad-pickleball --location=us-west1
```

## Updating the GitHub PAT

When the PAT expires:

```bash
# Update the secret with new token
echo -n 'NEW_GITHUB_PAT' | gcloud secrets versions add github-actions-token --data-file=- --project=smad-pickleball

# Re-run setup to update jobs with new token
./setup-scheduler.sh
```

## Troubleshooting

### Job fails with 401 Unauthorized
- GitHub PAT expired or invalid
- Update the secret and re-run setup

### Job fails with 404 Not Found
- Workflow file name changed
- Update the URI in the script and re-run setup

### View job execution history
```bash
gcloud scheduler jobs describe JOB_NAME --project=smad-pickleball --location=us-west1
```

## Cost

Google Cloud Scheduler free tier includes **3 jobs per month**. We use exactly 3 jobs.
