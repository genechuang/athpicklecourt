# GitHub Actions Setup Guide

This guide explains how to set up automated daily court bookings using GitHub Actions with a weekly recurring booking schedule.

## Overview

The booking system has two modes:

1. **Booking List Mode** (Automated via GitHub Actions):
   - Runs daily at 11:50 PM PST (primary) and 12:01 AM PST (backup)
   - Waits until exactly 12:00:15 AM PST
   - Books courts 7 days in advance based on your weekly schedule
   - Only books courts for the current day of the week

2. **Manual Single Booking Mode**:
   - Run manually with specific date/time parameters
   - Useful for one-off bookings

## Important Notes

1. **Timing Strategy**: Courts become available 7 days out at 12:00:15 AM PST. The workflow has two triggers:
   - **Primary**: 11:50 PM PST (10-minute buffer to avoid midnight contention)
   - **Backup**: 12:01 AM PST (fallback if primary didn't complete bookings)
   - Script waits until exactly 12:00:15 AM PST before booking
   - **10-minute grace period**: If script starts late (within 10 minutes past target time), it books immediately instead of waiting 24 hours

2. **Timezone**: All timestamps are in PST/PDT timezone. GitHub Actions generates the invoke timestamp using `TZ='America/Los_Angeles'` for consistency.

3. **Day of Week**: Use day names (Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday)

## Setup Steps

### 1. Configure GitHub Secrets and Variables

#### Secrets (Sensitive Credentials)

Go to your GitHub repository → Settings → Secrets and variables → Actions → Secrets tab → New repository secret

Add the following **secrets** (these contain sensitive credentials):

| Secret Name | Example Value | Description |
|-------------|---------------|-------------|
| `ATHENAEUM_USERNAME` | `your_username` | Your Athenaeum login username |
| `ATHENAEUM_PASSWORD` | `your_password` | Your Athenaeum login password |
| `GMAIL_USERNAME` | `your_email@gmail.com` | (Optional) Gmail address for booking notifications |
| `GMAIL_APP_PASSWORD` | `abcd efgh ijkl mnop` | (Optional) Gmail app password for SMTP |
| `NOTIFICATION_EMAIL` | `recipient@gmail.com` | (Optional) Email recipient (defaults to GMAIL_USERNAME) |

⚠️ **Security**: Never commit credentials to your repository. Always use GitHub Secrets for sensitive data.

**Email Notifications Setup (Optional):**
- Enable 2-Step Verification: https://myaccount.google.com/security
- Generate App Password: https://myaccount.google.com/apppasswords
- If not configured, script will skip email notifications and continue normally

#### Variables (Non-Sensitive Configuration)

Go to your GitHub repository → Settings → Secrets and variables → Actions → Variables tab → New repository variable

Add the following **variables** (these are configuration settings, not secrets):

| Variable Name | Example Value | Description |
|---------------|---------------|-------------|
| `BOOKING_LIST` | `Tuesday 7:00 PM\|Both,Wednesday 7:00 PM,Friday 4:00 PM\|North Pickleball Court` | Weekly recurring bookings: `<DayName> <Time>\|<Court>` pairs, comma-separated. Court specification is optional. |
| `BOOKING_TARGET_TIME` | `00:00:15` | Target time to wait for before booking (24-hour HH:MM:SS format). Default: `00:00:15` (12:00:15 AM PST) |
| `COURT_NAME` | `both` | Default court(s) to book: `both`, `North Pickleball Court`, or `South Pickleball Court`. Can be overridden per time slot in BOOKING_LIST. |
| `BOOKING_DURATION` | `120` | Duration in minutes (60 or 120) |
| `SAFETY_MODE` | `False` | Set to "False" to complete bookings (or "True" for dry-run) |
| `HEADLESS` | `True` | Set to "True" to run without browser window |

**BOOKING_LIST Format:**
- Format: `<DayName> <Time>|<Court>`, comma-separated
- Day names: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday (case-insensitive)
- Court specification is **optional** - if not specified, uses `COURT_NAME` environment variable
- Court options: `Both`, `North Pickleball Court`, or `South Pickleball Court`
- Examples:
  - `Tuesday 7:00 PM|Both,Wednesday 7:00 PM,Friday 4:00 PM|North Pickleball Court`
    - Tuesday at 7:00 PM: Books **both** courts
    - Wednesday at 7:00 PM: Uses `COURT_NAME` setting (e.g., both courts if `COURT_NAME=both`)
    - Friday at 4:00 PM: Books only **North Pickleball Court**
  - `Tuesday 7:00 PM,Wednesday 7:00 PM,Friday 4:00 PM,Sunday 10:00 AM`
    - All time slots use `COURT_NAME` setting (backward compatible)

**BOOKING_TARGET_TIME Format:**
- Format: `HH:MM:SS` in 24-hour format (PST timezone)
- Default: `00:00:15` (12:00:15 AM PST - when courts become available)
- For debugging timing issues:
  - Set to `00:00:00` to book exactly at midnight
  - Set to `00:01:00` to book at 12:01 AM
  - Adjust seconds to test different timing windows
- **Note:** This only affects when the script waits until before booking. The GitHub Actions cron schedule still needs to be adjusted separately.

**Why use Variables instead of Secrets?**
- Variables are easier to view and edit without re-entering them
- Variables can be referenced in workflow files more transparently
- Secrets should only be used for sensitive data like passwords and API keys
- Configuration settings like dates, times, and court names are not sensitive

### 2. Adjust Timezone in Cron Schedule

The workflow has two cron triggers:

**Primary Trigger: 11:50 PM PST (7:50 AM UTC during PST, 6:50 AM UTC during PDT)**
```yaml
- cron: '50 7 * * *'  # 11:50 PM PST
```

**Backup Trigger: 12:01 AM PST (8:01 AM UTC during PST, 7:01 AM UTC during PDT)**
```yaml
- cron: '01 8 * * *'  # 12:01 AM PST
```

**⚠️ IMPORTANT - Midnight Contention Issue:**
GitHub Actions has high contention at midnight (many users schedule jobs then). This can cause 2-5 minute delays in job start time. We schedule at **11:50 PM** (10 minutes early) to avoid this. The script includes a **10-minute grace period** - if it starts late (within 10 minutes past target time), it will book immediately instead of waiting 24 hours.

**Important:** You need to manually adjust these twice a year for Daylight Saving Time:

**During PST (November-March):**
```yaml
- cron: '50 7 * * *'  # 11:50 PM PST (primary)
- cron: '01 8 * * *'  # 12:01 AM PST (backup)
```

**During PDT (March-November):**
```yaml
- cron: '50 6 * * *'  # 11:50 PM PDT (primary)
- cron: '01 7 * * *'  # 12:01 AM PDT (backup)
```

Edit [.github/workflows/daily-booking.yml](.github/workflows/daily-booking.yml) and update both cron schedules based on PST/PDT.

**Timezone Conversion Reference:**
- **Pacific Time (PST)**: 11:50 PM PST = 7:50 AM UTC next day, 12:01 AM PST = 8:01 AM UTC
- **Pacific Time (PDT)**: 11:50 PM PDT = 6:50 AM UTC next day, 12:01 AM PDT = 7:01 AM UTC
- **Eastern Time (EST)**: 11:50 PM EST = 4:50 AM UTC next day
- **Eastern Time (EDT)**: 11:50 PM EDT = 3:50 AM UTC next day
- **Central Time (CST)**: 11:50 PM CST = 5:50 AM UTC next day
- **Central Time (CDT)**: 11:50 PM CDT = 4:50 AM UTC next day

### 3. Enable GitHub Actions

1. Go to your repository → Actions tab
2. Click "I understand my workflows, go ahead and enable them"
3. The workflow will now run automatically at 11:50 PM PST (primary) and 12:01 AM PST (backup) daily

### 4. Manual Trigger (Optional)

You can manually trigger a booking with custom parameters:

1. Go to Actions tab → "Daily Court Booking" workflow
2. Click "Run workflow"
3. Fill in optional parameters:
   - **booking_date_time**: Date and time in "MM/DD/YYYY HH:MM AM/PM" format (e.g., "01/20/2026 10:00 AM")
   - **court**: Court name or "both"
   - **duration**: Duration in minutes (60 or 120)
   - **booking_list**: Override BOOKING_LIST variable (e.g., "Tuesday 7:00 PM,Friday 4:00 PM")
   - **booking_target_time**: Override target time (e.g., "00:00:15")
   - **safety_mode**: Set to "True" for dry-run or "False" to complete booking
4. Click "Run workflow"

**Note:**
- If you provide `booking_date_time`, it uses single-booking mode
- If you leave inputs blank, it uses booking list mode with your configured variables

### 5. Monitor Execution

After each run:
1. Go to Actions tab → Click on the workflow run
2. View logs to see booking status
3. Download screenshot artifacts under "Artifacts" section
4. Screenshots are kept for 7 days
5. Check your email for booking status report (if email notifications are configured)

## How It Works

### Automated Daily Flow (with --invoke-time)

1. **11:50 PM PST**: GitHub Action triggers (primary) and captures current PST timestamp
2. **Script starts**: Receives `--invoke-time` and reads BOOKING_LIST from environment
3. **Day matching**: Filters BOOKING_LIST for today's day of week
4. **If no matches**: Script exits (nothing to book today)
5. **If matches found**:
   - Waits until exactly 12:00:15 AM PST (or books immediately if within 10-minute grace period)
   - Initializes browser and logs in
   - Calculates booking date (7 days from now)
   - Books court(s) based on `COURT_NAME` setting (single court or both if set to "both")
6. **Summary**: Reports successful and failed bookings
7. **Email notification**: Sends HTML status report with screenshots (if configured)
8. **Backup trigger**: If primary run didn't complete, 12:01 AM PST backup trigger runs as fallback

### Manual Booking List Mode (without --invoke-time)

If you run the script locally with BOOKING_LIST set but **without** `--invoke-time`:
1. **Script starts**: Uses current PST time for day-of-week matching
2. **Day matching**: Filters BOOKING_LIST for current day of week
3. **No wait**: Books immediately without waiting for 12:00:15 AM
4. **Calculates date**: Books 7 days from now
5. **Books court(s)**: Based on `COURT_NAME` setting (single court or both if set to "both")
6. **Useful for**: Testing or manual triggering of booking list

### Example Scenario

**Example 1: Using court specification in BOOKING_LIST**

**BOOKING_LIST**: `Tuesday 7:00 PM|Both,Wednesday 7:00 PM,Friday 4:00 PM|North Pickleball Court`
**COURT_NAME**: `South Pickleball Court` (fallback for Wednesday)

**Tuesday:**
- Script wakes up at 11:50 PM
- Finds match: "Tuesday 7:00 PM|Both"
- Waits until 12:00:15 AM
- Books **North Pickleball Court** at 7:00 PM (Tuesday, 7 days out)
- Books **South Pickleball Court** at 7:00 PM (Tuesday, 7 days out)
- Total: 2 court bookings
- Sends email notification with booking results

**Wednesday:**
- Script wakes up at 11:50 PM
- Finds match: "Wednesday 7:00 PM" (no court specified)
- Uses `COURT_NAME=South Pickleball Court` as fallback
- Waits until 12:00:15 AM
- Books **South Pickleball Court** at 7:00 PM (Wednesday, 7 days out)
- Total: 1 court booking
- Sends email notification with booking results

**Friday:**
- Script wakes up at 11:50 PM
- Finds match: "Friday 4:00 PM|North Pickleball Court"
- Waits until 12:00:15 AM
- Books **North Pickleball Court** at 4:00 PM (Friday, 7 days out)
- Total: 1 court booking
- Sends email notification with booking results

**Example 2: Using global COURT_NAME setting**

**BOOKING_LIST**: `Tuesday 7:00 PM,Wednesday 7:00 PM,Friday 4:00 PM,Sunday 10:00 AM`
**COURT_NAME**: `both`

**Tuesday:**
- Script wakes up at 11:50 PM
- Finds match: "Tuesday 7:00 PM"
- Waits until 12:00:15 AM
- Books **North Pickleball Court** at 7:00 PM (Tuesday, 7 days out)
- Books **South Pickleball Court** at 7:00 PM (Tuesday, 7 days out)
- Total: 2 court bookings
- Sends email notification with booking results

**Monday:**
- Script wakes up at 11:50 PM
- No matches in BOOKING_LIST
- Exits immediately (no email sent)

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
| Daily at 11:50 PM PST | `50 7 * * *` | Every day at 7:50 AM UTC (PST) |
| Daily at 11:50 PM PDT | `50 6 * * *` | Every day at 6:50 AM UTC (PDT) |
| Daily at 12:01 AM PST | `01 8 * * *` | Every day at 8:01 AM UTC (PST) |
| Daily at 12:01 AM PDT | `01 7 * * *` | Every day at 7:01 AM UTC (PDT) |
| Weekdays at 11:50 PM PST | `50 7 * * 1-5` | Monday-Friday at 11:50 PM PST |

## Troubleshooting

### Booking fails silently
- Check GitHub Actions logs for error messages
- Download screenshot artifacts to see what happened
- Verify all secrets and variables are set correctly
- Check if BOOKING_LIST format is correct

### Wrong timezone / booking at wrong time
- Verify cron schedule matches your current DST status (PST vs PDT)
- Check workflow logs for "Waiting for booking time" message
- Ensure `America/Los_Angeles` timezone in script matches your needs

### No bookings happen on expected day
- Verify day names in BOOKING_LIST (Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday)
- Check workflow logs to see if script found matches
- Remember: Script runs at 11:50 PM of the day BEFORE you want to book
  - To book Tuesday's court: Script runs Monday 11:50 PM → Tuesday 12:00:15 AM

### Rate limiting
- GitHub Actions has usage limits on free tier
- Each run uses ~2-3 minutes of compute time (mostly waiting)
- Daily execution: ~60-90 minutes per month (well within free tier)

### Playwright installation fails
- This is rare but can happen with Ubuntu updates
- Workflow includes `playwright install-deps` to handle dependencies

## Cost Considerations

- **GitHub Free tier**: 2,000 minutes/month for private repos, unlimited for public repos
- **This workflow**: ~2-3 minutes per run (includes 15 seconds wait time)
- **Daily execution**: ~60-90 minutes per month
- **Verdict**: Well within free tier limits

## Security Best Practices

✅ **Do:**
- Use GitHub Secrets for all credentials
- Keep `.env` in `.gitignore`
- Enable branch protection rules
- Review workflow logs regularly
- Use Variables for non-sensitive configuration

❌ **Don't:**
- Commit `.env` file to repository
- Share repository with untrusted users
- Hardcode credentials in workflow file
- Disable `HEADLESS=True` in GitHub Actions
- Put sensitive data in Variables (use Secrets instead)

## Testing the Workflow

Before relying on the scheduled run, test manually:

1. Go to Actions → Daily Court Booking
2. Click "Run workflow"
3. Leave inputs blank (will use default booking list mode if you pass `--invoke-time`)
4. Check if booking logic works
5. Download and review screenshots

**To test booking list mode locally:**
```bash
# With invoke_time (waits until 12:00:15 AM PST before booking)
python ath-booking.py --invoke-time "01-15-2026 07:58:30"

# Without invoke_time (books immediately, no wait)
# Just set BOOKING_LIST in your .env and run:
python ath-booking.py
```

**To test manual booking mode:**
```bash
# For manual single bookings (no BOOKING_LIST required)
python ath-booking.py --booking-date-time "01/22/2026 7:00 PM" --court "South Pickleball Court" --duration "120"
```

## Advanced Configuration

### Booking Multiple Courts

**Option 1: Per time slot court specification (most flexible)**
Add court specification directly in BOOKING_LIST:
```
BOOKING_LIST=Tuesday 7:00 PM|Both,Wednesday 7:00 PM|North Pickleball Court,Friday 4:00 PM
```
- Tuesday: Books both courts
- Wednesday: Books only North court
- Friday: Uses `COURT_NAME` fallback setting

**Option 2: Global COURT_NAME setting**
Set `COURT_NAME=both` to book both courts for all time slots:
- **Booking List Mode**: Set GitHub Variable `COURT_NAME=both`
- **Manual Single Booking**: Use `--court "both"` or set `COURT_NAME=both` in .env

To book a single specific court globally:
- Use `COURT_NAME=North Pickleball Court` or `COURT_NAME=South Pickleball Court`
- Or use command-line: `--court "North Pickleball Court"`

**Court specification priority:**
1. Court specified in BOOKING_LIST (e.g., `Tuesday 7:00 PM|Both`)
2. Falls back to `COURT_NAME` environment variable if no court specified

### Custom Wait Time
The script waits until 12:00:15 AM PST. To adjust:
- Edit `wait_until_booking_time()` call in `ath-booking.py`
- Change `target_second=15` to your desired second

### Different Timezone
To use a different timezone:
- Edit `timezone_name='America/Los_Angeles'` in `wait_until_booking_time()`
- Adjust cron schedule accordingly

## Dependencies

The script requires:
- `playwright` - Browser automation
- `python-dotenv` - Environment variable management
- `pytz` - Timezone handling

These are automatically installed by the GitHub Action workflow.
