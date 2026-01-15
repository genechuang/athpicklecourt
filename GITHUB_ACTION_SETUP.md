# GitHub Actions Setup Guide

This guide explains how to set up automated daily court bookings using GitHub Actions.

## Important Notes

1. **Cron Precision**: GitHub Actions only supports minute-level precision (not seconds). The closest to 12:00:15 AM is 12:00:00 AM.
2. **Timezone**: GitHub Actions runs in UTC. Adjust the cron schedule based on your local timezone.
3. **Headless Mode**: The workflow runs in headless mode (no browser window).

## Setup Steps

### 1. Configure GitHub Secrets and Variables

#### Secrets (Sensitive Credentials)

Go to your GitHub repository → Settings → Secrets and variables → Actions → Secrets tab → New repository secret

Add the following **secrets** (these contain sensitive credentials):

| Secret Name | Example Value | Description |
|-------------|---------------|-------------|
| `ATHENAEUM_USERNAME` | `your_username` | Your Athenaeum login username |
| `ATHENAEUM_PASSWORD` | `your_password` | Your Athenaeum login password |

⚠️ **Security**: Never commit credentials to your repository. Always use GitHub Secrets for sensitive data.

#### Variables (Non-Sensitive Configuration)

Go to your GitHub repository → Settings → Secrets and variables → Actions → Variables tab → New repository variable

Add the following **variables** (these are configuration settings, not secrets):

| Variable Name | Example Value | Description |
|---------------|---------------|-------------|
| `BOOKING_DATE` | `01/20/2026` | Default booking date (MM/DD/YYYY) |
| `BOOKING_TIME` | `10:00 AM` | Default booking time |
| `COURT_NAME` | `South Pickleball Court` | Default court name (or "both" for both courts) |
| `BOOKING_DURATION` | `120` | Default duration (60 or 120 minutes) |
| `SLEEP_SECONDS` | `15` | (Optional) Seconds to sleep before login for precise timing |
| `SAFETY_MODE` | `False` | Set to "False" to complete bookings (or "True" for dry-run) |
| `HEADLESS` | `True` | Set to "True" to run without browser window |

**Note on SLEEP_SECONDS**: This is useful if you want to delay the login and booking process. For example, if the cron job triggers at 12:00:00 AM but you want to book at exactly 12:00:15 AM, set `SLEEP_SECONDS=15`. This helps you time your booking more precisely since GitHub Actions only supports minute-level cron precision.

**Why use Variables instead of Secrets?**
- Variables are easier to view and edit without re-entering them
- Variables can be referenced in workflow files more transparently
- Secrets should only be used for sensitive data like passwords and API keys
- Configuration settings like dates, times, and court names are not sensitive

### 2. Adjust Timezone in Cron Schedule

The workflow file uses UTC time. To convert your local time to UTC:

- **Pacific Time (PST/PDT)**: 12:00 AM PST = 8:00 AM UTC
  ```yaml
  - cron: '0 8 * * *'
  ```

- **Eastern Time (EST/EDT)**: 12:00 AM EST = 5:00 AM UTC
  ```yaml
  - cron: '0 5 * * *'
  ```

- **Central Time (CST/CDT)**: 12:00 AM CST = 6:00 AM UTC
  ```yaml
  - cron: '0 6 * * *'
  ```

Edit [.github/workflows/daily-booking.yml](.github/workflows/daily-booking.yml) and update the cron schedule:

```yaml
on:
  schedule:
    - cron: '0 8 * * *'  # Change this line
```

### 3. Enable GitHub Actions

1. Go to your repository → Actions tab
2. Click "I understand my workflows, go ahead and enable them"
3. The workflow will now run automatically based on the cron schedule

### 4. Manual Trigger (Optional)

You can manually trigger a booking with custom parameters:

1. Go to Actions tab → "Daily Court Booking" workflow
2. Click "Run workflow"
3. Fill in optional parameters (date, time, court, duration)
4. Click "Run workflow"

### 5. Monitor Execution

After each run:
1. Go to Actions tab → Click on the workflow run
2. View logs to see booking status
3. Download screenshot artifacts under "Artifacts" section
4. Screenshots are kept for 7 days

## Cron Schedule Format

```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of the month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of the week (0 - 6) (Sunday to Saturday)
│ │ │ │ │
│ │ │ │ │
* * * * *
```

### Common Schedules

| Schedule | Cron Expression | Description |
|----------|-----------------|-------------|
| Daily at midnight (UTC) | `0 0 * * *` | Every day at 12:00 AM UTC |
| Daily at 8 AM (UTC) | `0 8 * * *` | Every day at 8:00 AM UTC |
| Weekdays at 6 AM (UTC) | `0 6 * * 1-5` | Monday-Friday at 6:00 AM UTC |
| Every Monday at 9 AM (UTC) | `0 9 * * 1` | Every Monday at 9:00 AM UTC |

## Troubleshooting

### Booking fails silently
- Check GitHub Actions logs for error messages
- Download screenshot artifacts to see what happened
- Verify all secrets are set correctly

### Wrong timezone
- Recalculate cron schedule based on UTC offset
- Remember to account for Daylight Saving Time changes

### Rate limiting
- GitHub Actions has usage limits on free tier
- Each run uses ~2-3 minutes of compute time

### Playwright installation fails
- This is rare but can happen with Ubuntu updates
- Workflow includes `playwright install-deps` to handle dependencies

## Cost Considerations

- **GitHub Free tier**: 2,000 minutes/month for private repos
- **This workflow**: ~2-3 minutes per run
- **Daily execution**: ~60-90 minutes per month
- **Verdict**: Well within free tier limits

## Dynamic Date Booking

If you want to book "7 days from today" instead of a fixed date, you would need to modify the Python script to calculate dates dynamically. Let me know if you need this feature.

## Notifications

To get notified on booking failures, you can:
1. Watch the repository to get email notifications on workflow failures
2. Use a third-party GitHub App for Slack/Discord/Email notifications
3. Modify the workflow to call a webhook service

## Security Best Practices

✅ **Do:**
- Use GitHub Secrets for all credentials
- Keep `.env` in `.gitignore`
- Enable branch protection rules
- Review workflow logs regularly

❌ **Don't:**
- Commit `.env` file to repository
- Share repository with untrusted users
- Hardcode credentials in workflow file
- Disable `HEADLESS=True` in GitHub Actions

## Testing the Workflow

Before relying on the scheduled run, test manually:

1. Go to Actions → Daily Court Booking
2. Click "Run workflow"
3. Leave inputs blank to use default secrets
4. Check if booking succeeds
5. Download and review screenshots

If successful, the scheduled cron will work the same way.
