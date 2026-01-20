# SMAD Pickleball Google Sheets Automation Setup

This guide explains how to set up the SMAD (San Marino Awesome Dinkers) Pickleball automation script.

## Prerequisites

- Python 3.8+
- Google Cloud account
- Access to the SMAD Google Sheet

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

Or install Google Sheets dependencies separately:

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

## Step 2: Set Up Google Cloud Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)

2. **Create a new project** (or select an existing one):
   - Click the project dropdown at the top
   - Click "New Project"
   - Name it (e.g., "SMAD Pickleball")
   - Click "Create"

3. **Enable the Google Sheets API**:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Sheets API"
   - Click on it and click "Enable"

4. **Create a Service Account**:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "Service Account"
   - Name: `smad-pickleball-bot`
   - Click "Create and Continue"
   - Skip the optional steps, click "Done"

5. **Create a Key for the Service Account**:
   - Click on the service account you just created
   - Go to the "Keys" tab
   - Click "Add Key" > "Create new key"
   - Choose "JSON" format
   - Click "Create" - this downloads the key file

6. **Save the credentials file**:
   - Rename the downloaded file to `smad-credentials.json`
   - Place it in the same directory as `smad-sheets.py`
   - **IMPORTANT**: Never commit this file to git!

## Step 3: Share the Google Sheet with the Service Account

1. Open the downloaded JSON file and find the `client_email` field
   - It looks like: `smad-pickleball-bot@your-project.iam.gserviceaccount.com`

2. Open your SMAD Google Sheet

3. Click "Share" button (top right)

4. Paste the service account email

5. Give it "Editor" access

6. Click "Send" (uncheck "Notify people" since it's a service account)

## Step 4: Configure Environment (Optional)

Create a `.env` file or set environment variables:

```bash
# Google Sheets Configuration
SMAD_SPREADSHEET_ID=1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY
SMAD_SHEET_NAME=2026 Pickleball
GOOGLE_CREDENTIALS_FILE=smad-credentials.json
SMAD_HOURLY_RATE=4.0

# Email Configuration (for payment reminders)
GMAIL_USERNAME=your-email@gmail.com
GMAIL_APP_PASSWORD=your-16-char-app-password
NOTIFICATION_EMAIL=admin-email@gmail.com
```

## Usage

### List all players
```bash
python smad-sheets.py list-players
```

### Show players with outstanding balances
```bash
python smad-sheets.py show-balances
```

### Register a player for a game
```bash
python smad-sheets.py register "John Doe" "Sun 1/19/26" 2
```
This adds 2 hours for John Doe on the Sun 1/19/26 column.

### Add a new date column
```bash
python smad-sheets.py add-date "Tues 1/21/26"
```
This inserts a new column after "Last Paid" for the new date.

### Send payment reminders
```bash
python smad-sheets.py send-reminders
```
(Requires email configuration and player email addresses)

## Spreadsheet Structure

The script expects this column layout:

| Column | Header | Description |
|--------|--------|-------------|
| A | First Name | Player's first name |
| B | Last Name | Player's last name |
| C | Email | Player's email address |
| D | Mobile | Player's mobile number |
| E | Venmo | Player's Venmo handle |
| F | Zelle | Player's Zelle email/phone |
| G | Balance | Amount owed ($) |
| H | Paid | Total amount paid |
| I | Invoiced | Total amount invoiced |
| J | 2026 Hours Played | Total hours in 2026 |
| K | 2025 Hours Played | Total hours in 2025 |
| L | Last Paid | Date of last payment |
| M+ | Date columns | e.g., "Sun 1/18/26" (newest first) |

Date columns contain the number of hours played by each player on that date.

## GitHub Actions Integration

To use in GitHub Actions, add these secrets:

- `GOOGLE_CREDENTIALS_JSON`: The entire contents of your service account JSON file

Example workflow:
```yaml
- name: Run SMAD automation
  env:
    GOOGLE_CREDENTIALS_JSON: ${{ secrets.GOOGLE_CREDENTIALS_JSON }}
  run: python smad-sheets.py show-balances
```

## Troubleshooting

### "Credentials file not found"
- Ensure `smad-credentials.json` is in the same directory
- Or set `GOOGLE_CREDENTIALS_FILE` to the correct path
- Or set `GOOGLE_CREDENTIALS_JSON` with the JSON contents

### "Permission denied" errors
- Make sure you shared the Google Sheet with the service account email
- The service account needs "Editor" access

### "Sheet not found"
- Check that `SMAD_SHEET_NAME` matches exactly (including spaces)
- Default is "2026 Pickleball"

### "Player not found"
- Names are case-insensitive but must match exactly
- Use `list-players` to see all available names
