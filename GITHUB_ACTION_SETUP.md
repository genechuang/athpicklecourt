# GitHub Actions Setup Guide

This guide explains how to set up automated daily court bookings using GitHub Actions with a weekly recurring booking schedule.

## Overview

The booking system has two modes:

1. **Booking List Mode** (Automated via GitHub Actions):
   - Runs daily at 11:59 PM PST
   - Waits until exactly 12:00:15 AM PST
   - Books courts 7 days in advance based on your weekly schedule
   - Only books courts for the current day of the week

2. **Manual Single Booking Mode**:
   - Run manually with specific date/time parameters
   - Useful for one-off bookings

## Important Notes

1. **Timing Strategy**: Courts become available 7 days out at 12:00:15 AM PST. The workflow triggers at 11:59 PM to allow ~30 seconds for GitHub Actions warm-up, then waits until exactly 12:00:15 AM before booking.

2. **Timezone**: GitHub Actions runs in UTC. The script automatically converts to PST/PDT for booking time calculations.

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

⚠️ **Security**: Never commit credentials to your repository. Always use GitHub Secrets for sensitive data.

#### Variables (Non-Sensitive Configuration)

Go to your GitHub repository → Settings → Secrets and variables → Actions → Variables tab → New repository variable

Add the following **variables** (these are configuration settings, not secrets):

| Variable Name | Example Value | Description |
|---------------|---------------|-------------|
| `BOOKING_LIST` | `Tuesday 7:00 PM,Wednesday 7:00 PM,Friday 4:00 PM,Sunday 10:00 AM` | Weekly recurring bookings: `<DayName> <Time>` pairs, comma-separated |
| `COURT_NAME` | `both` | Which court(s) to book: `both`, `North Pickleball Court`, or `South Pickleball Court` |
| `BOOKING_DURATION` | `120` | Duration in minutes (60 or 120) |
| `SAFETY_MODE` | `False` | Set to "False" to complete bookings (or "True" for dry-run) |
| `HEADLESS` | `True` | Set to "True" to run without browser window |

**Important:** Set `COURT_NAME=both` to book **BOTH** North and South Pickleball Courts for each time slot. This works in both Booking List Mode and Manual Single Booking Mode.

**BOOKING_LIST Format:**
- Format: `<DayName> <Time>`, comma-separated
- Day names: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday (case-insensitive)
- Example: `Tuesday 7:00 PM,Wednesday 7:00 PM,Friday 4:00 PM,Sunday 10:00 AM`
  - Books Tuesday at 7:00 PM
  - Books Wednesday at 7:00 PM
  - Books Friday at 4:00 PM
  - Books Sunday at 10:00 AM

**Why use Variables instead of Secrets?**
- Variables are easier to view and edit without re-entering them
- Variables can be referenced in workflow files more transparently
- Secrets should only be used for sensitive data like passwords and API keys
- Configuration settings like dates, times, and court names are not sensitive

### 2. Adjust Timezone in Cron Schedule

The workflow is pre-configured to run at **11:59 PM PST** (7:59 AM UTC during PST, 6:59 AM UTC during PDT).

**Current setting in workflow file:**
```yaml
- cron: '59 7 * * *'  # 11:59 PM PST
```

**Important:** You need to manually adjust this twice a year for Daylight Saving Time:
- **During PST (November-March)**: Use `'59 7 * * *'` (7:59 AM UTC = 11:59 PM PST)
- **During PDT (March-November)**: Use `'59 6 * * *'` (6:59 AM UTC = 11:59 PM PDT)

Edit [.github/workflows/daily-booking.yml](.github/workflows/daily-booking.yml) and update the cron schedule:

```yaml
on:
  schedule:
    - cron: '59 7 * * *'  # Change this line based on PST/PDT
```

**Timezone Conversion Reference:**
- **Pacific Time (PST)**: 11:59 PM PST = 7:59 AM UTC next day
- **Pacific Time (PDT)**: 11:59 PM PDT = 6:59 AM UTC next day
- **Eastern Time (EST)**: 11:59 PM EST = 4:59 AM UTC next day
- **Eastern Time (EDT)**: 11:59 PM EDT = 3:59 AM UTC next day
- **Central Time (CST)**: 11:59 PM CST = 5:59 AM UTC next day
- **Central Time (CDT)**: 11:59 PM CDT = 4:59 AM UTC next day

### 3. Enable GitHub Actions

1. Go to your repository → Actions tab
2. Click "I understand my workflows, go ahead and enable them"
3. The workflow will now run automatically at 11:59 PM PST daily

### 4. Manual Trigger (Optional)

You can manually trigger a booking with custom parameters:

1. Go to Actions tab → "Daily Court Booking" workflow
2. Click "Run workflow"
3. Fill in optional parameters (date, time, court, duration)
4. Click "Run workflow"

**Note:** Manual triggers use the old single-booking mode, not the booking list mode.

### 5. Monitor Execution

After each run:
1. Go to Actions tab → Click on the workflow run
2. View logs to see booking status
3. Download screenshot artifacts under "Artifacts" section
4. Screenshots are kept for 7 days

## How It Works

### Automated Daily Flow (with --invoke-time)

1. **11:59 PM PST**: GitHub Action triggers and captures current UTC timestamp
2. **Script starts**: Receives `--invoke-time` and reads BOOKING_LIST from environment
3. **Day matching**: Filters BOOKING_LIST for today's day of week
4. **If no matches**: Script exits (nothing to book today)
5. **If matches found**:
   - Waits until exactly 12:00:15 AM PST
   - Initializes browser and logs in
   - Calculates booking date (7 days from now)
   - Books court(s) based on `COURT_NAME` setting (single court or both if set to "both")
6. **Summary**: Reports successful and failed bookings

### Manual Booking List Mode (without --invoke-time)

If you run the script locally with BOOKING_LIST set but **without** `--invoke-time`:
1. **Script starts**: Uses current PST time for day-of-week matching
2. **Day matching**: Filters BOOKING_LIST for current day of week
3. **No wait**: Books immediately without waiting for 12:00:15 AM
4. **Calculates date**: Books 7 days from now
5. **Books court(s)**: Based on `COURT_NAME` setting (single court or both if set to "both")
6. **Useful for**: Testing or manual triggering of booking list

### Example Scenario

**BOOKING_LIST**: `Tuesday 7:00 PM,Wednesday 7:00 PM,Friday 4:00 PM,Sunday 10:00 AM`

**Tuesday with `COURT_NAME=both`:**
- Script wakes up at 11:59 PM
- Finds match: "Tuesday 7:00 PM"
- Waits until 12:00:15 AM
- Books **North Pickleball Court** at 7:00 PM (Tuesday, 7 days out)
- Books **South Pickleball Court** at 7:00 PM (Tuesday, 7 days out)
- Total: 2 court bookings

**Tuesday with `COURT_NAME=South Pickleball Court`:**
- Script wakes up at 11:59 PM
- Finds match: "Tuesday 7:00 PM"
- Waits until 12:00:15 AM
- Books **South Pickleball Court** at 7:00 PM (Tuesday, 7 days out)
- Total: 1 court booking

**Monday:**
- Script wakes up at 11:59 PM
- No matches in BOOKING_LIST
- Exits immediately

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
| Daily at 11:59 PM PST | `59 7 * * *` | Every day at 7:59 AM UTC (PST) |
| Daily at 11:59 PM PDT | `59 6 * * *` | Every day at 6:59 AM UTC (PDT) |
| Weekdays at 11:59 PM PST | `59 7 * * 1-5` | Monday-Friday at 11:59 PM PST |

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
- Verify day-of-week numbers in BOOKING_LIST (0=Sunday, 1=Monday, etc.)
- Check workflow logs to see if script found matches
- Remember: Script runs at 11:59 PM of the day BEFORE you want to book
  - To book Tuesday's court: Script runs Monday 11:59 PM → Tuesday 12:00:15 AM

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
python ath-booking.py --invoke-time "01-15-2026 07:59:30"

# Without invoke_time (books immediately, no wait)
# Just set BOOKING_LIST in your .env and run:
python ath-booking.py
```

**To test manual booking mode:**
```bash
# For manual single bookings (no BOOKING_LIST required)
python ath-booking.py --date "01/22/2026" --time "7:00 PM" --court "South Pickleball Court" --duration "120"
```

## Advanced Configuration

### Booking Multiple Courts

To book both courts, set `COURT_NAME=both` (works in all modes):
- **Booking List Mode**: Set GitHub Variable `COURT_NAME=both`
- **Manual Single Booking**: Use `--court "both"` or set `COURT_NAME=both` in .env

To book a single specific court:
- Use `COURT_NAME=North Pickleball Court` or `COURT_NAME=South Pickleball Court`
- Or use command-line: `--court "North Pickleball Court"`

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
