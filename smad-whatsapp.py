#!/usr/bin/env python3
"""
SMAD (San Marino Awesome Dinkers) WhatsApp Automation

Integrates with the SMAD WhatsApp group for:
- Sending balance reminders as DMs to players
- Sending balance summary reports to the group
- Creating availability polls for upcoming games
- Sending poll reminders to non-respondents

Uses GREEN-API for WhatsApp integration.
Requires: pip install whatsapp-api-client-python

Setup:
1. Create account at https://green-api.com
2. Get your Instance ID and API Token from the dashboard
3. Scan QR code to link your WhatsApp
4. Set environment variables (see below)

Usage:
    python smad-whatsapp.py send-balance-dm "John Doe"
    python smad-whatsapp.py send-balance-summary
    python smad-whatsapp.py create-poll
    python smad-whatsapp.py send-poll-reminders
    python smad-whatsapp.py list-group-members
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timedelta
import pytz
from typing import Optional, List, Dict

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# GREEN-API WhatsApp client
try:
    from whatsapp_api_client_python import API
except ImportError:
    print("ERROR: GREEN-API library not installed.")
    print("Run: pip install whatsapp-api-client-python")
    sys.exit(1)

# Google Sheets API for player data
try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("ERROR: Google API libraries not installed.")
    print("Run: pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)

# Configuration - WhatsApp
GREENAPI_INSTANCE_ID = os.environ.get('GREENAPI_INSTANCE_ID', '')
GREENAPI_API_TOKEN = os.environ.get('GREENAPI_API_TOKEN', '')
SMAD_GROUP_ID = os.environ.get('SMAD_WHATSAPP_GROUP_ID', '')  # Format: 123456789@g.us
SMAD_GROUP_URL = os.environ.get('SMAD_WHATSAPP_GROUP_URL', '')  # Group invite link
ADMIN_GROUP_ID = os.environ.get('ADMIN_DINKERS_WHATSAPP_GROUP_ID', '')  # Admin group for summaries

# Configuration - Google Sheets (reuse from smad-sheets.py)
SPREADSHEET_ID = os.environ.get('SMAD_SPREADSHEET_ID', '1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY')
SHEET_NAME = os.environ.get('SMAD_SHEET_NAME', '2026 Pickleball')
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'smad-credentials.json')
HOURLY_RATE = float(os.environ.get('SMAD_HOURLY_RATE', '4.0'))

# Column indices - import from smad-sheets.py (single source of truth)
import importlib.util
_spec = importlib.util.spec_from_file_location("smad_sheets", os.path.join(os.path.dirname(__file__), "smad-sheets.py"))
_smad_sheets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_smad_sheets)
COL_FIRST_NAME = _smad_sheets.COL_FIRST_NAME
COL_LAST_NAME = _smad_sheets.COL_LAST_NAME
COL_VACATION = _smad_sheets.COL_VACATION
COL_EMAIL = _smad_sheets.COL_EMAIL
COL_MOBILE = _smad_sheets.COL_MOBILE
COL_VENMO = _smad_sheets.COL_VENMO
COL_ZELLE = _smad_sheets.COL_ZELLE
COL_BALANCE = _smad_sheets.COL_BALANCE
COL_PAID = _smad_sheets.COL_PAID
COL_INVOICED = _smad_sheets.COL_INVOICED
COL_2026_HOURS = _smad_sheets.COL_2026_HOURS
COL_LAST_PAID = _smad_sheets.COL_LAST_PAID
COL_LAST_VOTED = _smad_sheets.COL_LAST_VOTED
COL_FIRST_DATE = _smad_sheets.COL_FIRST_DATE

# Google Sheets scopes (need write access for updating Last Voted and poll responses)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Configuration - Poll tracking
POLL_CREATED_DATE = os.environ.get('POLL_CREATED_DATE', '')  # Format: M/DD/YY

# Configuration - Booking list (for poll options)
BOOKING_LIST = os.environ.get('BOOKING_LIST', '')  # Format: Monday 7:00 PM|Both,Tuesday 7:00 PM|Both,...

# Bot signature for all WhatsApp messages
PICKLEBOT_SIGNATURE = "SMAD Picklebot 🥒🏓🤖"


def get_whatsapp_client():
    """Initialize and return GREEN-API WhatsApp client."""
    if not GREENAPI_INSTANCE_ID or not GREENAPI_API_TOKEN:
        print("ERROR: GREEN-API credentials not configured.")
        print("Set GREENAPI_INSTANCE_ID and GREENAPI_API_TOKEN environment variables.")
        print("\nGet credentials from: https://green-api.com")
        sys.exit(1)

    return API.GreenAPI(GREENAPI_INSTANCE_ID, GREENAPI_API_TOKEN)


def get_sheets_service():
    """Initialize and return Google Sheets API service."""
    if os.path.exists(CREDENTIALS_FILE):
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    elif os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS_JSON'])
        creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    else:
        print(f"ERROR: Credentials file '{CREDENTIALS_FILE}' not found.")
        sys.exit(1)

    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()


def get_sheet_data(sheets, range_name: str = None) -> List[List]:
    """Fetch data from the spreadsheet."""
    if range_name is None:
        range_name = f"'{SHEET_NAME}'"
    else:
        range_name = f"'{SHEET_NAME}'!{range_name}"

    try:
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        return result.get('values', [])
    except HttpError as e:
        print(f"ERROR: Failed to fetch sheet data: {e}")
        sys.exit(1)


def add_poll_date_columns(sheets, date_options: List[str]) -> bool:
    """
    Add new date columns to the sheet for poll options.
    Inserts columns right after COL_LAST_VOTED (column O), newest first.
    Skips any date columns that already exist to avoid overwriting old poll data.

    Args:
        sheets: Google Sheets service
        date_options: List of date strings like ["Wed 1/22/26 7pm", "Fri 1/24/26 7pm"]

    Returns:
        True if successful, False otherwise.
    """
    if not date_options:
        return True

    try:
        # Reverse order so newest date appears on the left
        date_options_reversed = list(reversed(date_options))

        # Read existing headers to check for duplicates
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{SHEET_NAME}'!1:1"
        ).execute()
        existing_headers = result.get('values', [[]])[0] if result.get('values') else []

        # Filter out date options that already exist
        new_date_options = []
        skipped_dates = []
        for date_opt in date_options_reversed:
            if date_opt in existing_headers:
                skipped_dates.append(date_opt)
            else:
                new_date_options.append(date_opt)

        if skipped_dates:
            print(f"[INFO] Skipped {len(skipped_dates)} existing date columns: {', '.join(skipped_dates)}")

        if not new_date_options:
            print(f"[INFO] All date columns already exist, no new columns added")
            return True

        # Get spreadsheet ID for insertDimension request
        spreadsheet = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_id = None
        for sheet in spreadsheet.get('sheets', []):
            if sheet['properties']['title'] == SHEET_NAME:
                sheet_id = sheet['properties']['sheetId']
                break

        if sheet_id is None:
            print(f"[ERROR] Sheet '{SHEET_NAME}' not found")
            return False

        # Insert columns after COL_LAST_VOTED
        num_cols = len(new_date_options)

        # Insert columns
        requests = [{
            'insertDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'COLUMNS',
                    'startIndex': COL_FIRST_DATE,
                    'endIndex': COL_FIRST_DATE + num_cols
                },
                'inheritFromBefore': False
            }
        }]

        sheets.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': requests}
        ).execute()

        # Convert column index to letter
        def col_to_letter(col_idx):
            result = ""
            while col_idx >= 0:
                result = chr(col_idx % 26 + ord('A')) + result
                col_idx = col_idx // 26 - 1
            return result

        start_col = col_to_letter(COL_FIRST_DATE)
        end_col = col_to_letter(COL_FIRST_DATE + num_cols - 1)

        # Write headers to row 1
        range_str_row1 = f"'{SHEET_NAME}'!{start_col}1:{end_col}1"
        sheets.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_str_row1,
            valueInputOption='RAW',
            body={'values': [new_date_options]}
        ).execute()

        # Find or create Totals row
        # Read all data to find the last row
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        # Check if last row has "Totals" in column A
        totals_row_idx = None
        if len(data) > 0:
            last_row = data[-1]
            if len(last_row) > 0 and last_row[0] == "Totals":
                totals_row_idx = len(data)
            else:
                # Need to add Totals row
                totals_row_idx = len(data) + 1
                # Add "Totals" to column A
                sheets.values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{SHEET_NAME}'!A{totals_row_idx}",
                    valueInputOption='RAW',
                    body={'values': [["Totals"]]}
                ).execute()

        # Add COUNTIF formulas for each new date column in the totals row
        if totals_row_idx:
            formulas = []
            for j in range(num_cols):
                col_letter = col_to_letter(COL_FIRST_DATE + j)
                # Formula counts 'y' from row 2 to row before totals
                formula = f"=COUNTIF('{SHEET_NAME}'!{col_letter}2:{col_letter}{totals_row_idx-1}, \"y\")"
                formulas.append(formula)

            # Write formulas to totals row (single row with multiple columns)
            if formulas:
                range_str_totals = f"'{SHEET_NAME}'!{start_col}{totals_row_idx}:{end_col}{totals_row_idx}"
                sheets.values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=range_str_totals,
                    valueInputOption='USER_ENTERED',  # Parse formulas
                    body={'values': [formulas]}
                ).execute()

        print(f"[OK] Added {num_cols} new date columns (newest first): {', '.join(new_date_options)}")
        print(f"[OK] Added COUNTIF formulas to totals row")
        return True

    except Exception as e:
        print(f"[ERROR] Failed to add date columns: {e}")
        return False


def format_phone_for_whatsapp(phone: str) -> Optional[str]:
    """
    Convert phone number to WhatsApp format (e.g., 12345678901@c.us).
    Expects US numbers, strips formatting, adds country code if needed.
    """
    if not phone:
        return None

    # Remove all non-numeric characters
    digits = ''.join(c for c in phone if c.isdigit())

    # Handle US numbers
    if len(digits) == 10:
        # Add US country code
        digits = '1' + digits
    elif len(digits) == 11 and digits.startswith('1'):
        # Already has US country code
        pass
    else:
        # Unknown format
        return None

    return f"{digits}@c.us"


def get_player_data(sheets) -> List[Dict]:
    """Get all player data from the spreadsheet."""
    data = get_sheet_data(sheets)
    if not data or len(data) < 2:
        return []

    headers = data[0]
    players = []

    # Find date columns for last game tracking
    date_columns = []
    for i, header in enumerate(headers):
        if i >= COL_FIRST_DATE:
            date_columns.append((i, header))

    for row in data[1:]:
        if len(row) < 2:
            continue

        first_name = row[COL_FIRST_NAME] if len(row) > COL_FIRST_NAME else ""
        last_name = row[COL_LAST_NAME] if len(row) > COL_LAST_NAME else ""

        if not first_name or not last_name:
            continue

        # Parse balance
        balance_str = row[COL_BALANCE] if len(row) > COL_BALANCE else "0"
        try:
            balance = float(balance_str.replace('$', '').replace(',', '').strip() or '0')
        except ValueError:
            balance = 0

        # Parse 2026 hours
        hours_str = row[COL_2026_HOURS] if len(row) > COL_2026_HOURS else "0"
        try:
            hours_2026 = float(hours_str.replace('$', '').replace(',', '').strip() or '0')
        except ValueError:
            hours_2026 = 0

        # Find last game date
        last_game_date = None
        for col_idx, header in date_columns:
            if col_idx < len(row):
                try:
                    hours = float(row[col_idx] or 0)
                    if hours > 0:
                        last_game_date = header
                        break
                except ValueError:
                    pass

        # Check vacation status - stores return date in MM/DD/YYYY or MM/DD/YY format
        # Player is on vacation if return date exists and current date < return date
        vacation_str = row[COL_VACATION] if len(row) > COL_VACATION else ""
        vacation_return_date = None
        if vacation_str.strip():
            # Try parsing as MM/DD/YYYY date first, then MM/DD/YY
            for date_format in ['%m/%d/%Y', '%m/%d/%y']:
                try:
                    vacation_return_date = datetime.strptime(vacation_str.strip(), date_format)
                    break
                except ValueError:
                    continue
            # Legacy support: "1" means indefinite vacation (use far future date)
            if vacation_return_date is None and vacation_str.strip() == "1":
                vacation_return_date = datetime(2099, 12, 31)

        players.append({
            'first_name': first_name,
            'last_name': last_name,
            'name': f"{first_name} {last_name}",
            'email': row[COL_EMAIL] if len(row) > COL_EMAIL else "",
            'mobile': row[COL_MOBILE] if len(row) > COL_MOBILE else "",
            'venmo': row[COL_VENMO] if len(row) > COL_VENMO else "",
            'zelle': row[COL_ZELLE] if len(row) > COL_ZELLE else "",
            'balance': balance,
            'hours_2026': hours_2026,
            'last_paid': row[COL_LAST_PAID] if len(row) > COL_LAST_PAID else "",
            'last_voted': row[COL_LAST_VOTED] if len(row) > COL_LAST_VOTED else "",
            'last_game_date': last_game_date,
            'vacation_return_date': vacation_return_date
        })

    return players


def find_player(players: List[Dict], name: str) -> Optional[Dict]:
    """Find a player by name (case-insensitive)."""
    name_lower = name.lower().strip()
    for player in players:
        if player['name'].lower() == name_lower:
            return player
    return None


def is_on_vacation(player: Dict) -> bool:
    """
    Check if a player is currently on vacation.

    A player is on vacation if their vacation_return_date exists and
    the current date (PST) is before that return date.

    Args:
        player: Player dict with optional 'vacation_return_date' key

    Returns:
        True if player is on vacation, False otherwise
    """
    vacation_return = player.get('vacation_return_date')
    if not vacation_return:
        return False

    # Compare with current date in PST
    pst = pytz.timezone('America/Los_Angeles')
    today = datetime.now(pst).date()
    return today < vacation_return.date()


def send_balance_dm(wa_client, player: Dict, dry_run: bool = False) -> bool:
    """Send a balance reminder DM to a player via WhatsApp."""
    phone_id = format_phone_for_whatsapp(player['mobile'])
    if not phone_id:
        print(f"  [SKIP] {player['name']} - no valid phone number")
        return False

    # Determine last game text
    if player['hours_2026'] > 0 and player['last_game_date']:
        last_game_text = f"Your last game played was {player['last_game_date']}."
    else:
        last_game_text = "Your last game played was in 2025."

    message = f"""Hi {player['first_name']}!
You have an outstanding balance with SMAD Pickleball: *${player['balance']:.2f}*
{last_game_text}
Please Venmo @gene-chuang or Zelle genechuang@gmail.com
Thanks,
{PICKLEBOT_SIGNATURE}"""

    if dry_run:
        print(f"  [DRY RUN] Would send to {player['name']} ({phone_id}):")
        print(f"    {message[:100]}...")
        return True

    try:
        response = wa_client.sending.sendMessage(phone_id, message)
        if response.code == 200:
            print(f"  [OK] Sent to {player['name']} ({phone_id})")
            return True
        else:
            print(f"  [ERROR] Failed to send to {player['name']}: {response.data}")
            return False
    except Exception as e:
        print(f"  [ERROR] Failed to send to {player['name']}: {e}")
        return False


def send_balance_summary_to_group(wa_client, players: List[Dict], dry_run: bool = False) -> bool:
    """Send a balance summary to the SMAD WhatsApp group."""
    if not SMAD_GROUP_ID:
        print("ERROR: SMAD_WHATSAPP_GROUP_ID not configured.")
        return False

    # Filter players with balances
    players_with_balance = [p for p in players if p['balance'] > 0]

    if not players_with_balance:
        message = f"*SMAD Pickleball Balance Update*\n\nNo outstanding balances! Everyone is paid up!\n\n{PICKLEBOT_SIGNATURE}"
    else:
        total = sum(p['balance'] for p in players_with_balance)
        message = f"*SMAD Pickleball Balance Update*\n\n"
        message += f"*{len(players_with_balance)} players with outstanding balances:*\n\n"

        for player in sorted(players_with_balance, key=lambda x: x['balance'], reverse=True):
            message += f"• {player['name']}: ${player['balance']:.2f}\n"

        message += f"\n*Total Outstanding: ${total:.2f}*\n\n"
        message += f"Please send payment via Venmo to @gene-chuang or Zelle to genechuang@gmail.com.\n\n{PICKLEBOT_SIGNATURE}"

    if dry_run:
        print(f"[DRY RUN] Would send to SMAD Pickleball group ({SMAD_GROUP_ID}):")
        print(message)
        return True

    try:
        response = wa_client.sending.sendMessage(SMAD_GROUP_ID, message)
        if response.code == 200:
            print("[OK] Balance summary sent to SMAD Pickleball group")
            return True
        else:
            print(f"[ERROR] Failed to send to group: {response.data}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to send to group: {e}")
        return False


def send_admin_summary(wa_client, summary_type: str, details: str, dry_run: bool = False) -> bool:
    """
    Send a summary message to the Admin Dinkers group.

    Args:
        wa_client: WhatsApp API client
        summary_type: Type of summary (e.g., "Payment Reminders", "Vote Reminders")
        details: The summary details to send
        dry_run: If True, print message without sending

    Returns:
        True if sent successfully, False otherwise
    """
    if not ADMIN_GROUP_ID:
        # Admin group not configured, silently skip
        return True

    message = f"*{summary_type} Summary*\n\n{details}\n\n{PICKLEBOT_SIGNATURE}"

    if dry_run:
        print(f"\n[DRY RUN] Would send to Admin Dinkers group ({ADMIN_GROUP_ID}):")
        # Handle Windows console encoding issues with emojis
        try:
            print(message)
        except UnicodeEncodeError:
            print(message.encode('ascii', 'replace').decode('ascii'))
        return True

    try:
        response = wa_client.sending.sendMessage(ADMIN_GROUP_ID, message)
        if response.code == 200:
            print(f"\n[OK] Summary sent to Admin Dinkers group")
            return True
        else:
            print(f"\n[ERROR] Failed to send to admin group: {response.data}")
            return False
    except Exception as e:
        print(f"\n[ERROR] Failed to send to admin group: {e}")
        return False


def parse_booking_list() -> List[Dict]:
    """
    Parse BOOKING_LIST env var into a list of booking configs.

    Format: "Monday 7:00 PM|Both,Tuesday 7:00 PM|Both,..."

    Returns list of dicts with 'day', 'time', 'court' keys.
    """
    if not BOOKING_LIST:
        return []

    bookings = []
    for entry in BOOKING_LIST.split(','):
        entry = entry.strip()
        if not entry:
            continue

        # Split by | to get court info (optional)
        parts = entry.split('|')
        day_time = parts[0].strip()
        court = parts[1].strip() if len(parts) > 1 else 'Both'

        # Parse day and time (e.g., "Monday 7:00 PM")
        day_time_parts = day_time.split(' ', 1)
        if len(day_time_parts) >= 2:
            day = day_time_parts[0]
            time = day_time_parts[1]
            bookings.append({
                'day': day,
                'time': time,
                'court': court
            })

    return bookings


def format_time_for_poll(time_str: str, duration_hours: int = 2) -> str:
    """
    Convert time like "7:00 PM" to poll format like "7pm" (assumes 2-hour session).

    Args:
        time_str: Time string like "7:00 PM" or "10:00 AM"
        duration_hours: Duration in hours (default 2, not used but kept for compatibility)

    Returns:
        Formatted string like "7pm" or "10am"
    """
    try:
        # Parse the time
        time_obj = datetime.strptime(time_str.strip(), "%I:%M %p")
        start_hour = time_obj.hour

        # Format start time (shorter format without end time)
        if start_hour == 0:
            start_str = "12am"
        elif start_hour < 12:
            start_str = f"{start_hour}am"
        elif start_hour == 12:
            start_str = "12pm"
        else:
            start_str = f"{start_hour - 12}pm"

        return start_str
    except ValueError:
        # If parsing fails, return original
        return time_str


def get_day_abbreviation(day_name: str) -> str:
    """Convert full day name to abbreviation for poll."""
    abbreviations = {
        'monday': 'Mon',
        'tuesday': 'Tues',
        'wednesday': 'Wed',
        'thursday': 'Thurs',
        'friday': 'Fri',
        'saturday': 'Sat',
        'sunday': 'Sun'
    }
    return abbreviations.get(day_name.lower(), day_name[:3])


def get_weekday_number(day_name: str) -> int:
    """Convert day name to weekday number (Monday=0, Sunday=6)."""
    days = {
        'monday': 0,
        'tuesday': 1,
        'wednesday': 2,
        'thursday': 3,
        'friday': 4,
        'saturday': 5,
        'sunday': 6
    }
    return days.get(day_name.lower(), -1)


def create_availability_poll(wa_client, dry_run: bool = False) -> bool:
    """Create a poll in the group asking about availability for upcoming games."""
    if not SMAD_GROUP_ID:
        print("ERROR: SMAD_WHATSAPP_GROUP_ID not configured.")
        return False

    # Parse booking list from env
    bookings = parse_booking_list()

    if not bookings:
        print("ERROR: BOOKING_LIST not configured or empty.")
        print("Set BOOKING_LIST in .env (e.g., 'Monday 7:00 PM|Both,Tuesday 7:00 PM|Both')")
        return False

    # Generate time slot options for the upcoming week based on BOOKING_LIST
    # Use PST timezone to ensure consistent behavior regardless of server timezone
    pst = pytz.timezone('America/Los_Angeles')
    today = datetime.now(pst)
    options = []

    # Build a map of weekday -> list of bookings for that day
    bookings_by_weekday = {}
    for booking in bookings:
        weekday = get_weekday_number(booking['day'])
        if weekday >= 0:
            if weekday not in bookings_by_weekday:
                bookings_by_weekday[weekday] = []
            bookings_by_weekday[weekday].append(booking)

    # Find the next occurrence of each booking day in the next 7 days
    for i in range(1, 8):
        future_date = today + timedelta(days=i)
        weekday = future_date.weekday()

        if weekday in bookings_by_weekday:
            for booking in bookings_by_weekday[weekday]:
                day_abbrev = get_day_abbreviation(booking['day'])
                time_slot = format_time_for_poll(booking['time'])
                year_short = future_date.year % 100
                date_str = f"{day_abbrev} {future_date.month}/{future_date.day}/{year_short} {time_slot}"
                options.append({"optionName": date_str})

    # Add "Can't play this week" option
    options.append({"optionName": "Can't play this week"})

    # Calculate Monday of the week containing the poll dates
    # Since options start from tomorrow (today + 1), find the Monday of that week
    first_option_date = today + timedelta(days=1)
    days_since_monday = first_option_date.weekday()  # Monday=0, Sunday=6
    monday_of_week = first_option_date - timedelta(days=days_since_monday)
    monday_str = f"{monday_of_week.month}/{monday_of_week.day}/{monday_of_week.year % 100}"

    poll_question = f"Can you play the week of {monday_str}? {PICKLEBOT_SIGNATURE}"

    if dry_run:
        output = f"[DRY RUN] Would create poll in SMAD Pickleball group ({SMAD_GROUP_ID}):\n"
        output += f"Question: {poll_question}\n"
        output += "Options:\n"
        for opt in options:
            output += f"  - {opt['optionName']}\n"
        if ADMIN_GROUP_ID:
            output += f"\n[DRY RUN] Would also post poll to Admin Dinkers group ({ADMIN_GROUP_ID}) (votes not tracked)\n"
        try:
            print(output)
        except UnicodeEncodeError:
            # Windows console can't display emojis
            print(output.encode('ascii', 'replace').decode('ascii'))
        return True

    try:
        response = wa_client.sending.sendPoll(
            SMAD_GROUP_ID,
            poll_question,
            options,
            multipleAnswers=True
        )
        if response.code == 200:
            message_id = response.data.get('idMessage', '')
            print("[OK] Availability poll created in SMAD Pickleball group")
            print(f"Poll ID: {message_id}")

            # Add date columns to the sheet (exclude "Can't play this week" option)
            date_options = [opt['optionName'] for opt in options if "can't play" not in opt['optionName'].lower()]
            try:
                sheets = get_sheets_service()
                add_poll_date_columns(sheets, date_options)
            except Exception as e:
                print(f"[WARNING] Failed to add date columns to sheet: {e}")

            # Also post poll to Admin Dinkers group (for visibility, votes not tracked)
            if ADMIN_GROUP_ID:
                try:
                    admin_response = wa_client.sending.sendPoll(
                        ADMIN_GROUP_ID,
                        poll_question,
                        options,
                        multipleAnswers=True
                    )
                    if admin_response.code == 200:
                        print("[OK] Poll also posted to Admin Dinkers group (votes not tracked)")
                    else:
                        print(f"[WARNING] Failed to post poll to Admin Dinkers: {admin_response.data}")
                except Exception as e:
                    print(f"[WARNING] Failed to post poll to Admin Dinkers: {e}")

            return True
        else:
            print(f"[ERROR] Failed to create poll: {response.data}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to create poll: {e}")
        return False


def list_all_chats(wa_client) -> List[Dict]:
    """List all chats (groups and contacts) to find group IDs."""
    print("\n=== Finding WhatsApp Groups ===\n")

    # Method 1: Try getContacts
    groups = []
    try:
        response = wa_client.serviceMethods.getContacts()
        if response.code == 200 and response.data:
            contacts = response.data
            groups = [c for c in contacts if c.get('id', '').endswith('@g.us')]
    except Exception:
        pass

    # Method 2: Try getting recent messages to find chats
    chats_from_messages = {}
    try:
        response = wa_client.journals.lastIncomingMessages(100)
        if response.code == 200 and response.data:
            for msg in response.data:
                chat_id = msg.get('chatId', '')
                sender = msg.get('senderName', msg.get('chatId', ''))
                if chat_id and '@g.us' in chat_id and chat_id not in chats_from_messages:
                    chats_from_messages[chat_id] = sender
    except Exception:
        pass

    try:
        response = wa_client.journals.lastOutgoingMessages(100)
        if response.code == 200 and response.data:
            for msg in response.data:
                chat_id = msg.get('chatId', '')
                if chat_id and '@g.us' in chat_id and chat_id not in chats_from_messages:
                    chats_from_messages[chat_id] = chat_id
    except Exception:
        pass

    # Display results
    if groups:
        print(f"Groups from contacts ({len(groups)}):\n")
        for g in groups:
            chat_id = g.get('id', 'Unknown')
            name = g.get('name', 'Unknown')
            # Handle unicode characters that can't be printed
            try:
                print(f"  {name}")
            except UnicodeEncodeError:
                print(f"  {name.encode('ascii', 'replace').decode()}")
            print(f"    ID: {chat_id}")
            print()

    if chats_from_messages:
        print(f"Groups from recent messages ({len(chats_from_messages)}):\n")
        for chat_id, name in chats_from_messages.items():
            try:
                print(f"  {name}")
            except UnicodeEncodeError:
                print(f"  {name.encode('ascii', 'replace').decode()}")
            print(f"    ID: {chat_id}")
            print()

    if not groups and not chats_from_messages:
        print("No groups found yet.")
        print("\nTo find your SMAD group ID:")
        print("1. Send a message to the SMAD WhatsApp group from your phone")
        print("2. Wait a few seconds for GREEN-API to sync")
        print("3. Run this command again")
        print("\nAlternatively, you can find the group ID by:")
        print("1. Open WhatsApp Web")
        print("2. Go to the SMAD group")
        print("3. Look at the URL - it contains the group ID")
        print("   (Format: web.whatsapp.com/accept?code=XXXXX)")

    return groups


def list_group_members(wa_client, players: List[Dict] = None) -> List[Dict]:
    """List all members of the SMAD WhatsApp group with names from spreadsheet."""
    if not SMAD_GROUP_ID:
        print("ERROR: SMAD_WHATSAPP_GROUP_ID not configured.")
        print("Run 'list-chats' first to find your group ID.")
        return []

    # Build phone lookup from players list
    phone_to_player = {}
    if players:
        for player in players:
            phone = player.get('mobile', '')
            if phone:
                # Normalize phone to digits only
                digits = ''.join(c for c in phone if c.isdigit())
                if len(digits) == 10:
                    digits = '1' + digits  # Add US country code
                phone_to_player[digits] = player

    try:
        response = wa_client.groups.getGroupData(SMAD_GROUP_ID)
        if response.code == 200:
            participants = response.data.get('participants', [])
            group_name = response.data.get('subject', 'Unknown')

            print(f"\n=== {group_name} - Members ({len(participants)}) ===\n")
            print(f"{'Name':<25} {'Phone':<15} {'Admin':<8} {'In Sheet':<10}")
            print("-" * 60)

            matched = 0
            unmatched = 0

            for p in participants:
                participant_id = p.get('id', 'Unknown')
                is_admin = p.get('isAdmin', False)
                admin_str = "Yes" if is_admin else ""

                # Extract phone number from WhatsApp ID (e.g., "16262727719@c.us" -> "16262727719")
                phone_digits = participant_id.replace('@c.us', '')

                # Format phone for display (e.g., "16262727719" -> "(626) 272-7719")
                if len(phone_digits) == 11 and phone_digits.startswith('1'):
                    display_phone = f"({phone_digits[1:4]}) {phone_digits[4:7]}-{phone_digits[7:]}"
                else:
                    display_phone = phone_digits

                # Look up player name
                player = phone_to_player.get(phone_digits)
                if player:
                    name = player['name']
                    in_sheet = "Yes"
                    matched += 1
                else:
                    name = "(Unknown)"
                    in_sheet = "No"
                    unmatched += 1

                print(f"{name:<25} {display_phone:<15} {admin_str:<8} {in_sheet:<10}")

            print()
            print(f"Matched to spreadsheet: {matched}")
            print(f"Not in spreadsheet: {unmatched}")

            return participants
        else:
            print(f"[ERROR] Failed to get group data: {response.data}")
            return []
    except Exception as e:
        print(f"[ERROR] Failed to get group data: {e}")
        return []


def safe_print(text: str) -> None:
    """Print text safely, replacing unencodable characters."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('ascii', 'replace').decode('ascii'))


def show_recent_poll(players: List[Dict] = None) -> Optional[Dict]:
    """
    Find and display the most recent poll from the SMAD WhatsApp group.
    Uses the getChatHistory API to find poll messages.

    Note: GREEN-API doesn't expose poll options or vote counts directly.
    Poll data is extracted from quoted messages that reference polls.
    """
    if not SMAD_GROUP_ID:
        print("ERROR: SMAD_WHATSAPP_GROUP_ID not configured.")
        return None

    if not GREENAPI_INSTANCE_ID or not GREENAPI_API_TOKEN:
        print("ERROR: GREEN-API credentials not configured.")
        return None

    # Build phone lookup from players list for name resolution
    phone_to_player = {}
    if players:
        for player in players:
            phone = player.get('mobile', '')
            if phone:
                digits = ''.join(c for c in phone if c.isdigit())
                if len(digits) == 10:
                    digits = '1' + digits
                phone_to_player[digits] = player

    def phone_to_name(phone_id: str) -> str:
        """Convert phone ID to player name if known."""
        digits = phone_id.replace('@c.us', '').replace('@s.whatsapp.net', '')
        player = phone_to_player.get(digits)
        if player:
            return player['name']
        # Format as phone number
        if len(digits) == 11 and digits.startswith('1'):
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return digits

    base_url = f'https://api.green-api.com/waInstance{GREENAPI_INSTANCE_ID}'
    url = f'{base_url}/getChatHistory/{GREENAPI_API_TOKEN}'

    try:
        response = requests.post(url, json={'chatId': SMAD_GROUP_ID, 'count': 100})
        if response.status_code != 200:
            print(f"[ERROR] Failed to get chat history: {response.text}")
            return None

        messages = response.json()

        # Find poll messages (either direct or quoted)
        polls_found = []

        for msg in messages:
            # Check for quoted poll messages
            quoted = msg.get('quotedMessage', {})
            if quoted.get('typeMessage') == 'pollMessage':
                poll_data = quoted.get('pollMessageData', {})
                polls_found.append({
                    'question': poll_data.get('name', 'Unknown'),
                    'stanza_id': quoted.get('stanzaId', ''),
                    'timestamp': msg.get('timestamp', 0),
                    'reply_text': msg.get('extendedTextMessage', {}).get('text', ''),
                    'reply_sender': msg.get('senderName', phone_to_name(msg.get('senderId', ''))),
                    'multiple_answers': poll_data.get('multipleAnswers', False),
                    'type': 'quoted'
                })

            # Check for direct poll messages (typeMessage == 'pollMessage')
            if msg.get('typeMessage') == 'pollMessage':
                poll_data = msg.get('pollMessageData', {})
                polls_found.append({
                    'question': poll_data.get('name', 'Unknown'),
                    'stanza_id': msg.get('idMessage', ''),
                    'timestamp': msg.get('timestamp', 0),
                    'options': poll_data.get('options', []),
                    'multiple_answers': poll_data.get('multipleAnswers', False),
                    'type': 'direct'
                })

        if not polls_found:
            print("No polls found in recent chat history.")
            return None

        # Group by poll stanza_id to consolidate
        polls_by_id = {}
        for poll in polls_found:
            sid = poll['stanza_id']
            if sid not in polls_by_id:
                polls_by_id[sid] = poll
            else:
                # Merge reply info
                if poll.get('reply_text') and not polls_by_id[sid].get('reply_text'):
                    polls_by_id[sid]['reply_text'] = poll['reply_text']
                    polls_by_id[sid]['reply_sender'] = poll.get('reply_sender')

        # Sort by timestamp (most recent first)
        unique_polls = sorted(polls_by_id.values(), key=lambda x: x['timestamp'], reverse=True)

        # Display the most recent poll
        print("\n=== Most Recent Poll ===\n")
        poll = unique_polls[0]

        from datetime import datetime
        dt = datetime.fromtimestamp(poll['timestamp']) if poll['timestamp'] else None

        safe_print(f"Question: {poll['question']}")
        if dt:
            print(f"Date: {dt.strftime('%Y-%m-%d %I:%M %p')}")
        print(f"Multiple answers: {'Yes' if poll['multiple_answers'] else 'No'}")
        print(f"Poll ID: {poll['stanza_id']}")

        if poll.get('options'):
            print(f"\nOptions:")
            for opt in poll['options']:
                opt_name = opt.get('optionName', opt) if isinstance(opt, dict) else opt
                print(f"  - {opt_name}")

        if poll.get('reply_text'):
            print(f"\nLatest reply referencing this poll:")
            print(f"  From: {poll.get('reply_sender', 'Unknown')}")
            reply_text = poll['reply_text'][:500] + ('...' if len(poll.get('reply_text', '')) > 500 else '')
            safe_print(f"  Text: {reply_text}")

        # Show other recent polls if any
        if len(unique_polls) > 1:
            print(f"\n=== Other Recent Polls ({len(unique_polls) - 1}) ===\n")
            for p in unique_polls[1:5]:  # Show up to 4 more
                dt = datetime.fromtimestamp(p['timestamp']) if p['timestamp'] else None
                date_str = dt.strftime('%m/%d/%y') if dt else 'Unknown'
                safe_print(f"  [{date_str}] {p['question'][:60]}{'...' if len(p['question']) > 60 else ''}")

        return poll

    except Exception as e:
        print(f"[ERROR] Failed to retrieve poll: {e}")
        return None


def get_poll_votes_from_sheets(poll_date: str = None, players: List[Dict] = None) -> Optional[Dict]:
    """
    Retrieve poll votes from Google Sheets (Pickle Poll Log).

    Args:
        poll_date: Specific poll date to retrieve. If None, gets the most recent poll.
        players: List of player dicts for name resolution.

    Returns:
        Dict with poll data and votes, or None if not found.
    """
    try:
        sheets = get_sheets_service()

        # Get latest poll info if poll_date not specified
        if not poll_date:
            poll_info = _smad_sheets.get_latest_poll_info(sheets)
            if not poll_info:
                return None
            poll_date = poll_info.get('poll_date', '')
            poll_question = poll_info.get('poll_question', '')
            poll_id = poll_info.get('poll_id', '')
        else:
            poll_question = "Unknown"
            poll_id = "Unknown"

        # Read raw data from Pickle Poll Log to get vote details
        range_name = f"'{_smad_sheets.POLL_LOG_SHEET_NAME}'"
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        data = result.get('values', [])

        # Parse votes from rows matching this poll date
        votes = {}
        all_options = set()

        for row in data[1:]:  # Skip header
            if len(row) >= 6:
                row_poll_date = row[_smad_sheets.PPL_COL_POLL_DATE]
                if row_poll_date == poll_date:
                    player_name = row[_smad_sheets.PPL_COL_PLAYER_NAME]
                    vote_options_str = row[_smad_sheets.PPL_COL_VOTE_OPTIONS]

                    # Parse selected options
                    selected = [opt.strip() for opt in vote_options_str.split(',') if opt.strip()]

                    # Collect all options
                    all_options.update(selected)

                    # Store vote by player name
                    votes[player_name] = {
                        'selected': selected,
                        'voter_name': player_name
                    }

        # Build player name lookup
        name_to_player = {}
        if players:
            for player in players:
                name_to_player[player['name']] = player

        return {
            'poll_id': poll_id,
            'poll_date': poll_date,
            'question': poll_question,
            'options': list(all_options),
            'votes': votes,
            'name_to_player': name_to_player
        }

    except Exception as e:
        print(f"[ERROR] Failed to retrieve votes from Sheets: {e}")
        return None


def show_poll_votes(poll_date: str = None, players: List[Dict] = None) -> Optional[Dict]:
    """
    Display poll votes from Google Sheets with player names.
    """
    poll_data = get_poll_votes_from_sheets(poll_date, players)

    if not poll_data:
        print("No poll data found in Pickle Poll Log sheet.")
        print("\nMake sure:")
        print("1. The webhook is deployed and configured")
        print("2. Votes have been cast and recorded in the Pickle Poll Log sheet")
        return None

    votes = poll_data.get('votes', {})
    options = poll_data.get('options', [])

    print(f"\n=== Poll Votes ===\n")
    safe_print(f"Question: {poll_data['question']}")
    print(f"Poll Date: {poll_data.get('poll_date', 'Unknown')}")
    print(f"Total voters: {len(votes)}")

    # Group votes by option
    option_voters = {opt: [] for opt in options}
    cannot_play_voters = []
    no_response_yet = []

    # Phrases that indicate "cannot play"
    cannot_play_phrases = ["cannot play", "can't play", "cant play", "not available", "unavailable"]

    for player_name, vote_data in votes.items():
        selected = vote_data.get('selected', [])

        if not selected:
            # Empty selection (removed all votes)
            no_response_yet.append(player_name)
            continue

        # Check if this is a "cannot play" response
        is_cannot_play = any(
            any(phrase in opt.lower() for phrase in cannot_play_phrases)
            for opt in selected
        )

        if is_cannot_play:
            cannot_play_voters.append(player_name)
        else:
            for opt in selected:
                if opt in option_voters:
                    option_voters[opt].append(player_name)
                else:
                    # Option not in our list, add it
                    option_voters[opt] = [player_name]

    # Display by option
    print(f"\n--- Votes by Option ---\n")
    for option in options:
        # Skip "cannot play" options in main list
        if any(phrase in option.lower() for phrase in cannot_play_phrases):
            continue

        voters = option_voters.get(option, [])
        print(f"{option}: ({len(voters)} votes)")
        for voter in sorted(voters):
            print(f"  - {voter}")
        print()

    # Show cannot play
    if cannot_play_voters:
        print(f"Cannot play this week: ({len(cannot_play_voters)})")
        for voter in sorted(cannot_play_voters):
            print(f"  - {voter}")
        print()

    # Show who hasn't voted (from group members)
    if players:
        voted_names = set(votes.keys())
        not_voted = []
        for player in players:
            if player['name'] not in voted_names:
                not_voted.append(player['name'])

        if not_voted:
            print(f"Haven't voted yet: ({len(not_voted)})")
            for name in sorted(not_voted):
                print(f"  - {name}")
            print()

    return poll_data


def parse_date_string(date_str: str) -> Optional[datetime]:
    """Parse a date string like '1/20/26' into a datetime object."""
    if not date_str:
        return None
    try:
        # Try M/D/YY format
        parts = date_str.strip().split('/')
        if len(parts) == 3:
            month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
            # Handle 2-digit year
            if year < 100:
                year += 2000
            return datetime(year, month, day)
    except (ValueError, IndexError):
        pass
    return None


def get_poll_created_date() -> Optional[datetime]:
    """
    Get the poll creation date from Google Sheets (Pickle Poll Log) or POLL_CREATED_DATE env var.
    Returns datetime object or None if not found.
    """
    # First try Google Sheets
    try:
        sheets = get_sheets_service()
        poll_info = _smad_sheets.get_latest_poll_info(sheets)
        if poll_info:
            poll_date_str = poll_info.get('poll_date', '')
            # Parse date (format: M/D/YY HH:MM:SS or M/D/YY)
            if poll_date_str:
                try:
                    poll_date = datetime.strptime(poll_date_str, '%m/%d/%y %H:%M:%S')
                    return datetime(poll_date.year, poll_date.month, poll_date.day)
                except ValueError:
                    try:
                        poll_date = datetime.strptime(poll_date_str, '%m/%d/%y')
                        return poll_date
                    except ValueError:
                        pass
    except Exception as e:
        print(f"[WARNING] Could not get poll date from Sheets: {e}")

    # Fall back to POLL_CREATED_DATE env var
    if POLL_CREATED_DATE:
        parsed = parse_date_string(POLL_CREATED_DATE)
        if parsed:
            return parsed

    return None


def send_vote_reminders(wa_client, players: List[Dict], dry_run: bool = False) -> int:
    """
    Send DM reminders to players who haven't voted on the current poll.

    Uses the "Last Voted" column in the sheet to determine who hasn't voted.
    A player hasn't voted if their Last Voted date is before the poll created date
    (or if Last Voted is empty).

    Returns:
        Number of reminders sent.
    """
    poll_created = get_poll_created_date()
    if not poll_created:
        print("ERROR: Could not determine poll creation date.")
        print("Make sure there are votes in the Pickle Poll Log sheet or POLL_CREATED_DATE is set.")
        return 0

    print(f"\n=== Vote Reminders (Poll created: {poll_created.month}/{poll_created.day}/{poll_created.year % 100}) ===\n")

    # Find players who haven't voted (Last Voted < poll created date, or empty)
    # Skip players on vacation
    not_voted = []
    vacation_skipped = 0
    for player in players:
        # Skip players on vacation (current date < vacation return date)
        if is_on_vacation(player):
            vacation_skipped += 1
            continue

        last_voted_str = player.get('last_voted', '')
        last_voted = parse_date_string(last_voted_str)

        # Player hasn't voted if:
        # 1. Last Voted is empty (None)
        # 2. Last Voted is before poll created date
        if last_voted is None or last_voted < poll_created:
            not_voted.append(player)

    if vacation_skipped > 0:
        print(f"(Skipped {vacation_skipped} player(s) on vacation)\n")

    if not not_voted:
        print("Everyone has voted!")
        return 0

    print(f"Found {len(not_voted)} players who haven't voted yet:\n")

    sent = 0
    for player in not_voted:
        phone_id = format_phone_for_whatsapp(player.get('mobile', ''))
        if not phone_id:
            print(f"  [SKIP] {player['name']} - no valid phone number")
            continue

        # Build message with optional group link
        group_link_text = f"\n\n{SMAD_GROUP_URL}" if SMAD_GROUP_URL else ""
        message = f"""Hi {player['first_name']}!
REMINDER: Vote in this week's SMAD pickleball availability poll so Gene can plan the games for this week.
Check this week's poll pinned to the top of the group: {group_link_text}

If you don't want to receive these daily notifications, you can either vote when the new poll comes out on Sunday, or let me know you want to be put on vacation mode.

Thanks,
{PICKLEBOT_SIGNATURE}"""

        if dry_run:
            last_voted_str = player.get('last_voted', 'never')
            print(f"  [DRY RUN] Would send to {player['name']} (last voted: {last_voted_str})")
            sent += 1
            continue

        try:
            response = wa_client.sending.sendMessage(phone_id, message)
            if response.code == 200:
                print(f"  [OK] Sent to {player['name']}")
                sent += 1
            else:
                print(f"  [ERROR] Failed to send to {player['name']}: {response.data}")
        except Exception as e:
            print(f"  [ERROR] Failed to send to {player['name']}: {e}")

    print(f"\n[DONE] Sent {sent} reminders")
    return sent


def send_group_vote_reminder(wa_client, players: List[Dict], dry_run: bool = False) -> bool:
    """
    Send a vote reminder to the group listing players who haven't voted.

    This is an alternative to individual DMs when the GREEN-API quota is exceeded.
    Posts a message to the group with names of players who need to vote.

    Returns:
        True if message sent successfully.
    """
    if not SMAD_GROUP_ID:
        print("ERROR: SMAD_WHATSAPP_GROUP_ID not configured.")
        return False

    poll_created = get_poll_created_date()
    if not poll_created:
        print("ERROR: Could not determine poll creation date.")
        print("Make sure there are votes in the Pickle Poll Log sheet or POLL_CREATED_DATE is set.")
        return False

    # Find players who haven't voted (Last Voted < poll created date, or empty)
    not_voted = []
    for player in players:
        last_voted_str = player.get('last_voted', '')
        last_voted = parse_date_string(last_voted_str)

        if last_voted is None or last_voted < poll_created:
            not_voted.append(player)

    if not not_voted:
        print("Everyone has voted! No reminder needed.")
        return True

    # Build the group message with bold names for visibility
    names = [f"*{p['first_name']}*" for p in not_voted]
    names_list = ", ".join(names)

    message = f"""*Vote Reminder*

The following {len(not_voted)} players haven't voted in this week's poll yet:

{names_list}

Please vote in this week's poll pinned to the top of the group so I can plan the games for this week!

{PICKLEBOT_SIGNATURE}"""

    if dry_run:
        print(f"[DRY RUN] Would send to SMAD Pickleball group ({SMAD_GROUP_ID}):")
        print(message)
        return True

    try:
        response = wa_client.sending.sendMessage(SMAD_GROUP_ID, message)
        if response.code == 200:
            print(f"[OK] Vote reminder sent to SMAD Pickleball group ({len(not_voted)} players listed)")
            return True
        else:
            print(f"[ERROR] Failed to send to group: {response.data}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to send to group: {e}")
        return False


def get_available_poll_options(sheets) -> List[str]:
    """
    Get available date options from the current poll by reading sheet headers.
    Returns list of date column headers (e.g., ["Wed 1/29/26 7pm", "Fri 1/31/26 7pm"]).
    """
    try:
        # Read headers from the sheet
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{SHEET_NAME}'!1:1"
        ).execute()
        headers = result.get('values', [[]])[0] if result.get('values') else []

        # Return headers starting from COL_FIRST_DATE
        date_options = []
        for i, header in enumerate(headers):
            if i >= COL_FIRST_DATE and header:
                date_options.append(header)

        return date_options
    except Exception as e:
        print(f"[ERROR] Failed to get poll options: {e}")
        return []


def update_vote(sheets, player_name: str, vote_options: List[str], dry_run: bool = False) -> bool:
    """
    Manually record a poll vote for a player.

    This is used when GREEN-API fails to deliver pollUpdateMessage webhooks.

    Args:
        sheets: Google Sheets service
        player_name: Full name of the player (e.g., "Karan Keswani")
        vote_options: List of selected date options (e.g., ["Wed 1/29/26 7pm", "Fri 1/31/26 7pm"])
        dry_run: If True, preview changes without writing

    Returns:
        True if successful, False otherwise
    """
    # Get latest poll info
    poll_info = _smad_sheets.get_latest_poll_info(sheets)
    if not poll_info:
        print("[ERROR] No poll found in Pickle Poll Log sheet.")
        print("Make sure a poll has been created and at least one vote recorded.")
        return False

    poll_id = poll_info.get('poll_id', 'manual')
    poll_date = poll_info.get('poll_date', '')
    poll_question = poll_info.get('poll_question', '')

    print(f"\n=== Manual Vote Update ===\n")
    safe_print(f"Poll: {poll_question}")
    print(f"Poll Date: {poll_date}")
    print(f"Player: {player_name}")
    print(f"Selected Options: {', '.join(vote_options)}")

    # Read sheet data to find player row
    result = sheets.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{SHEET_NAME}'"
    ).execute()
    data = result.get('values', [])

    if len(data) < 2:
        print("[ERROR] Sheet appears empty.")
        return False

    headers = data[0]

    # Find player row
    name_parts = player_name.strip().split(' ', 1)
    if len(name_parts) < 2:
        print(f"[ERROR] Invalid player name format. Use 'First Last'.")
        return False

    first_name, last_name = name_parts[0], name_parts[1]
    player_row_idx = _smad_sheets.find_player_row(data, first_name, last_name)

    if player_row_idx is None:
        print(f"[ERROR] Player '{player_name}' not found in sheet.")
        return False

    # Row index in sheet (add 1 for 1-based, already includes header offset)
    sheet_row = player_row_idx + 1

    # Check if player already voted for this poll
    existing_voters = _smad_sheets.get_poll_voters(sheets, poll_date)
    already_voted = player_name in existing_voters

    if already_voted:
        print(f"\n[INFO] {player_name} already voted - this will replace their previous selections.")

    # Prepare updates
    updates = []

    # Update Last Voted column
    pst = pytz.timezone('America/Los_Angeles')
    now = datetime.now(pst)
    last_voted_str = f"{now.month}/{now.day}/{now.year % 100}"
    vote_timestamp = f"{now.month}/{now.day}/{now.year % 100} {now.hour}:{now.minute:02d}:{now.second:02d}"

    last_voted_col = _smad_sheets.col_index_to_letter(COL_LAST_VOTED)
    updates.append({
        'range': f"'{SHEET_NAME}'!{last_voted_col}{sheet_row}",
        'values': [[last_voted_str]]
    })
    print(f"\n[UPDATE] Last Voted -> {last_voted_str}")

    # Get all poll options for the current poll (from other voters in Pickle Poll Log)
    # This helps us know which columns to clear (set 'n') for non-selected options
    all_poll_options = set()
    try:
        poll_log_data = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{_smad_sheets.POLL_LOG_SHEET_NAME}'"
        ).execute().get('values', [])
        for row in poll_log_data[1:]:  # Skip header
            if len(row) > _smad_sheets.PPL_COL_VOTE_OPTIONS:
                row_poll_date = row[_smad_sheets.PPL_COL_POLL_DATE] if len(row) > _smad_sheets.PPL_COL_POLL_DATE else ''
                if row_poll_date == poll_date:
                    opts = row[_smad_sheets.PPL_COL_VOTE_OPTIONS].split(',')
                    for opt in opts:
                        opt = opt.strip()
                        if opt and "can't play" not in opt.lower():
                            all_poll_options.add(opt)
    except Exception:
        pass  # If we can't get poll options, just update selected ones

    # Update date columns - set 'y' for selected, 'n' for other poll options (trumps previous vote)
    for col_idx, header in enumerate(headers):
        if col_idx < COL_FIRST_DATE:
            continue

        # Check if this header matches any selected option
        is_selected = False
        for opt in vote_options:
            # Try exact match
            if header == opt or header.strip() == opt.strip():
                is_selected = True
                break
            # Partial match on date
            header_date = ' '.join(header.split()[:2]) if header else ''
            opt_date = ' '.join(opt.split()[:2]) if opt else ''
            if header_date and opt_date and header_date == opt_date:
                is_selected = True
                break

        # Check if this header matches any poll option (for clearing non-selected)
        is_poll_option = False
        for poll_opt in all_poll_options:
            if header == poll_opt or header.strip() == poll_opt.strip():
                is_poll_option = True
                break
            header_date = ' '.join(header.split()[:2]) if header else ''
            poll_opt_date = ' '.join(poll_opt.split()[:2]) if poll_opt else ''
            if header_date and poll_opt_date and header_date == poll_opt_date:
                is_poll_option = True
                break

        col_letter = _smad_sheets.col_index_to_letter(col_idx)
        if is_selected:
            updates.append({
                'range': f"'{SHEET_NAME}'!{col_letter}{sheet_row}",
                'values': [['y']]
            })
            print(f"[UPDATE] {header} -> y")
        elif is_poll_option:
            # Clear previous vote for this poll option
            updates.append({
                'range': f"'{SHEET_NAME}'!{col_letter}{sheet_row}",
                'values': [['n']]
            })
            print(f"[UPDATE] {header} -> n (clearing previous)")

    # Record in Pickle Poll Log
    vote_options_str = ', '.join(vote_options)
    vote_raw_json = json.dumps({'manual': True, 'options': vote_options, 'recorded_by': 'update-vote'})

    print(f"\n[UPDATE] Pickle Poll Log -> {vote_options_str}")

    if dry_run:
        print(f"\n[DRY RUN] Would update {len(updates)} cells and add 1 row to Pickle Poll Log")
        return True

    # Execute batch update for main sheet
    if updates:
        body = {'valueInputOption': 'RAW', 'data': updates}
        sheets.values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=body
        ).execute()

    # Record in Pickle Poll Log
    _smad_sheets.record_poll_vote(
        sheets,
        poll_id=poll_id,
        poll_date=poll_date,
        poll_question=poll_question,
        player_name=player_name,
        vote_timestamp=vote_timestamp,
        vote_options=vote_options_str,
        vote_raw_json=vote_raw_json
    )

    print(f"\n[OK] Vote recorded successfully for {player_name}")
    return True


def cmd_update_vote(args):
    """Command: Manually record a poll vote for a player."""
    sheets = get_sheets_service()

    # List options mode
    if args.list_options:
        print("\n=== Available Poll Options ===\n")
        options = get_available_poll_options(sheets)
        if not options:
            print("No date columns found. Poll may not have been created yet.")
            return

        for opt in options:
            print(f"  - {opt}")

        print(f"\nUsage: python smad-whatsapp.py update-vote \"{args.player_name}\" \"option1, option2\"")
        return

    # Validate vote_options provided
    if not args.vote_options:
        print("[ERROR] Vote options required. Use --list-options to see available options.")
        return

    # Parse comma-separated options
    vote_options = [opt.strip() for opt in args.vote_options.split(',') if opt.strip()]

    if not vote_options:
        print("[ERROR] No valid vote options provided.")
        return

    # Validate options against available ones
    available = get_available_poll_options(sheets)
    invalid_options = []
    for opt in vote_options:
        # Check for exact or partial match
        found = False
        for avail in available:
            if opt == avail or opt.strip() == avail.strip():
                found = True
                break
            # Partial match on date
            opt_date = ' '.join(opt.split()[:2]) if opt else ''
            avail_date = ' '.join(avail.split()[:2]) if avail else ''
            if opt_date and avail_date and opt_date == avail_date:
                found = True
                break
        if not found:
            invalid_options.append(opt)

    if invalid_options:
        print(f"[WARNING] These options don't match any date columns: {', '.join(invalid_options)}")
        print("Available options:")
        for opt in available:
            print(f"  - {opt}")
        print("\nProceeding anyway (options may match by date part)...")

    update_vote(sheets, args.player_name, vote_options, dry_run=args.dry_run)


def cmd_show_votes(args):
    """Command: Show poll votes from Pickle Poll Log sheet."""
    sheets = get_sheets_service()
    players = get_player_data(sheets)
    show_poll_votes(poll_date=args.poll_date if hasattr(args, 'poll_date') else None, players=players)


def cmd_send_vote_reminders(args):
    """Command: Send reminders to players who haven't voted."""
    wa_client = get_whatsapp_client()
    sheets = get_sheets_service()
    players = get_player_data(sheets)

    # Get non-voters for admin summary (same logic as send_vote_reminders)
    poll_created = get_poll_created_date()
    non_voters = []
    if poll_created:
        for player in players:
            # Skip players on vacation (current date < vacation return date)
            if is_on_vacation(player):
                continue
            last_voted_str = player.get('last_voted', '')
            last_voted = parse_date_string(last_voted_str)
            if last_voted is None or last_voted < poll_created:
                non_voters.append(player['name'])

    # Send the reminders
    send_vote_reminders(wa_client, players, dry_run=args.dry_run)

    # Send summary to admin group
    if non_voters:
        details = f"Sent vote reminders to {len(non_voters)} players:\n" + "\n".join(f"• {name}" for name in non_voters)
    else:
        details = "Everyone has voted! No reminders sent."
    send_admin_summary(wa_client, "Vote Reminders", details, dry_run=args.dry_run)


def cmd_send_group_vote_reminder(args):
    """Command: Send a vote reminder to the group listing non-voters."""
    wa_client = get_whatsapp_client()
    sheets = get_sheets_service()
    players = get_player_data(sheets)

    send_group_vote_reminder(wa_client, players, dry_run=args.dry_run)


def cmd_show_poll(args):
    """Command: Show the most recent poll from the group."""
    sheets = get_sheets_service()
    players = get_player_data(sheets)
    show_recent_poll(players)


def cmd_send_balance_dm(args):
    """Command: Send balance DM to a specific player or all players with balances."""
    wa_client = get_whatsapp_client()
    sheets = get_sheets_service()
    players = get_player_data(sheets)

    if args.player_name.lower() == 'all':
        # Send to all players with balances
        players_with_balance = [p for p in players if p['balance'] > 0]
        print(f"\n=== Sending Balance Reminders to {len(players_with_balance)} Players ===\n")

        sent = 0
        skipped = 0
        for player in players_with_balance:
            if send_balance_dm(wa_client, player, dry_run=args.dry_run):
                sent += 1
            else:
                skipped += 1

        print(f"\n[DONE] Sent: {sent}, Skipped: {skipped}")

        # Send summary to admin group
        if players_with_balance:
            total = sum(p['balance'] for p in players_with_balance)
            details = f"Sent payment reminders to {len(players_with_balance)} players:\n"
            details += "\n".join(f"• {p['name']}: ${p['balance']:.2f} (Last played: {p['last_game_date'] or 'Never'})" for p in players_with_balance)
            details += f"\n\n*Total Outstanding: ${total:.2f}*"
        else:
            details = "No outstanding balances! Everyone is paid up."
        send_admin_summary(wa_client, "Payment Reminders", details, dry_run=args.dry_run)
    else:
        # Send to specific player
        player = find_player(players, args.player_name)
        if not player:
            print(f"ERROR: Player '{args.player_name}' not found.")
            print("Available players:")
            for p in players:
                print(f"  - {p['name']}")
            return

        if player['balance'] <= 0 and not args.force:
            print(f"{player['name']} has no outstanding balance (${player['balance']:.2f}).")
            print("Use --force to send anyway.")
            return

        send_balance_dm(wa_client, player, dry_run=args.dry_run)


def cmd_send_balance_summary(args):
    """Command: Send balance summary to the group."""
    wa_client = get_whatsapp_client()
    sheets = get_sheets_service()
    players = get_player_data(sheets)

    print("\n=== Sending Balance Summary to Group ===\n")
    send_balance_summary_to_group(wa_client, players, dry_run=args.dry_run)


def cmd_create_poll(args):
    """Command: Create availability poll in the group."""
    wa_client = get_whatsapp_client()

    print("\n=== Creating Availability Poll ===\n")
    create_availability_poll(wa_client, dry_run=args.dry_run)


def cmd_list_chats(args):
    """Command: List all WhatsApp chats to find group IDs."""
    wa_client = get_whatsapp_client()
    list_all_chats(wa_client)


def cmd_list_group_members(args):
    """Command: List all members of the WhatsApp group."""
    wa_client = get_whatsapp_client()
    sheets = get_sheets_service()
    players = get_player_data(sheets)
    list_group_members(wa_client, players)


def cmd_send_poll_reminders(args):
    """Command: Send poll reminders to players who haven't responded."""
    # Redirect to the new Sheet-based implementation
    cmd_send_vote_reminders(args)


def main():
    parser = argparse.ArgumentParser(
        description='SMAD Pickleball WhatsApp Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list-chats                       List all chats to find group IDs
  %(prog)s show-poll                        Show the most recent poll (from WhatsApp)
  %(prog)s show-votes                       Show poll votes (from Pickle Poll Log sheet)
  %(prog)s send-vote-reminders              Send DM reminders to non-voters
  %(prog)s send-group-vote-reminder         Post vote reminder to group (lists non-voters)
  %(prog)s send-balance-dm "John Doe"       Send balance reminder to John
  %(prog)s send-balance-dm all              Send reminders to all with balances
  %(prog)s send-balance-summary             Post balance summary to group
  %(prog)s create-poll                      Create weekly availability poll
  %(prog)s list-group-members               List WhatsApp group members
  %(prog)s update-vote "John Doe" --list-options    Show available vote options
  %(prog)s update-vote "John Doe" "Wed 1/29/26 7pm, Fri 1/31/26 7pm"  Manually record vote

Environment variables:
  GREENAPI_INSTANCE_ID      GREEN-API instance ID
  GREENAPI_API_TOKEN        GREEN-API API token
  SMAD_WHATSAPP_GROUP_ID    WhatsApp group ID (e.g., 123456789@g.us)

  (Also uses SMAD Google Sheets config from smad-sheets.py)
        """
    )

    # Global options
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview actions without sending messages')

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # send-balance-dm
    dm_parser = subparsers.add_parser('send-balance-dm',
                                       help='Send balance reminder DM to player(s)')
    dm_parser.add_argument('player_name',
                           help='Player name or "all" for all players with balances')
    dm_parser.add_argument('--force', action='store_true',
                           help='Send even if player has no balance')
    dm_parser.set_defaults(func=cmd_send_balance_dm)

    # send-balance-summary
    summary_parser = subparsers.add_parser('send-balance-summary',
                                            help='Send balance summary to group')
    summary_parser.set_defaults(func=cmd_send_balance_summary)

    # create-poll
    poll_parser = subparsers.add_parser('create-poll',
                                         help='Create availability poll in group')
    poll_parser.set_defaults(func=cmd_create_poll)

    # send-poll-reminders
    reminder_parser = subparsers.add_parser('send-poll-reminders',
                                             help='Send reminders to poll non-responders')
    reminder_parser.set_defaults(func=cmd_send_poll_reminders)

    # list-chats
    chats_parser = subparsers.add_parser('list-chats',
                                          help='List all WhatsApp chats to find group IDs')
    chats_parser.set_defaults(func=cmd_list_chats)

    # show-poll
    show_poll_parser = subparsers.add_parser('show-poll',
                                              help='Show the most recent poll from the group')
    show_poll_parser.set_defaults(func=cmd_show_poll)

    # show-votes (from Pickle Poll Log sheet)
    show_votes_parser = subparsers.add_parser('show-votes',
                                               help='Show poll votes from Pickle Poll Log sheet')
    show_votes_parser.add_argument('--poll-date', dest='poll_date',
                                    help='Specific poll date (M/D/YY HH:MM:SS format, default: most recent)')
    show_votes_parser.set_defaults(func=cmd_show_votes)

    # send-vote-reminders
    vote_reminder_parser = subparsers.add_parser('send-vote-reminders',
                                                  help='Send DM reminders to players who haven\'t voted')
    vote_reminder_parser.add_argument('--poll-date', dest='poll_date',
                                       help='Specific poll date (M/D/YY HH:MM:SS format, default: most recent)')
    vote_reminder_parser.set_defaults(func=cmd_send_vote_reminders)

    # send-group-vote-reminder
    group_vote_reminder_parser = subparsers.add_parser('send-group-vote-reminder',
                                                        help='Post vote reminder to group listing non-voters')
    group_vote_reminder_parser.set_defaults(func=cmd_send_group_vote_reminder)

    # update-vote
    update_vote_parser = subparsers.add_parser('update-vote',
                                                help='Manually record a poll vote for a player')
    update_vote_parser.add_argument('player_name',
                                     help='Player name (e.g., "Karan Keswani")')
    update_vote_parser.add_argument('vote_options', nargs='?', default='',
                                     help='Comma-separated vote options (e.g., "Wed 1/29/26 7pm, Fri 1/31/26 7pm")')
    update_vote_parser.add_argument('--list-options', action='store_true', dest='list_options',
                                     help='List available poll options instead of recording a vote')
    update_vote_parser.set_defaults(func=cmd_update_vote)

    # list-group-members
    members_parser = subparsers.add_parser('list-group-members',
                                            help='List WhatsApp group members')
    members_parser.set_defaults(func=cmd_list_group_members)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
