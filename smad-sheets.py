#!/usr/bin/env python3
"""
SMAD (San Marino Awesome Dinkers) Pickleball Google Sheets Automation

Automates:
- Game registration (add hours played for a player on a date)
- New date column creation (insert after "Last Paid" column)
- Payment reminder emails

Spreadsheet structure:
- Column A: First Name
- Column B: Last Name
- Column C: Balance
- Column D: 2026 Hours Played
- Column E: 2025 Hours Played
- Column F: Last Paid
- Column G+: Date columns (newest first, e.g., "Sun 1/18/26")

Usage:
    python smad-sheets.py register "John Doe" "Sun 1/19/26" 2
    python smad-sheets.py add-date "Tues 1/21/26"
    python smad-sheets.py send-reminders
    python smad-sheets.py list-players
    python smad-sheets.py show-balances
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

# Import common email service
from email_service import send_payment_reminder, send_balance_summary, is_email_configured

# Google Sheets API
try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("ERROR: Google API libraries not installed.")
    print("Run: pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)

# Configuration
SPREADSHEET_ID = os.environ.get('SMAD_SPREADSHEET_ID', '1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY')
SHEET_NAME = os.environ.get('SMAD_SHEET_NAME', '2026 Pickleball')
POLL_LOG_SHEET_NAME = os.environ.get('POLL_LOG_SHEET_NAME', 'Pickle Poll Log')
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'smad-credentials.json')
HOURLY_RATE = float(os.environ.get('SMAD_HOURLY_RATE', '4.0'))

# Email configuration is now handled by email_service.py
# Uses GMAIL_USERNAME, GMAIL_APP_PASSWORD, NOTIFICATION_EMAIL environment variables

# Column indices (0-based) - SINGLE SOURCE OF TRUTH
# Other files (smad-whatsapp.py, payments-management.py) import these from here
# Columns: First Name, Last Name, Vacation, Email, Mobile, Venmo, Zelle, Balance, Paid, Invoiced, 2026 Hours, Last Paid, Last Voted, [dates...]
COL_FIRST_NAME = 0
COL_LAST_NAME = 1
COL_VACATION = 2
COL_EMAIL = 3
COL_MOBILE = 4
COL_VENMO = 5
COL_ZELLE = 6
COL_BALANCE = 7
COL_PAID = 8
COL_INVOICED = 9
COL_2026_HOURS = 10
COL_LAST_PAID = 11
COL_LAST_VOTED = 12  # Last poll vote date
COL_FIRST_DATE = 13  # Date columns start here (newest first)

# Pickle Poll Log sheet column indices (0-based)
PPL_COL_POLL_ID = 0
PPL_COL_POLL_DATE = 1
PPL_COL_POLL_QUESTION = 2
PPL_COL_PLAYER_NAME = 3
PPL_COL_VOTE_TIMESTAMP = 4
PPL_COL_VOTE_OPTIONS = 5
PPL_COL_VOTE_RAW_JSON = 6

# Export all column constants for other modules
__all__ = [
    'COL_FIRST_NAME', 'COL_LAST_NAME', 'COL_VACATION', 'COL_EMAIL', 'COL_MOBILE',
    'COL_VENMO', 'COL_ZELLE', 'COL_BALANCE', 'COL_PAID',
    'COL_INVOICED', 'COL_2026_HOURS', 'COL_LAST_PAID', 'COL_LAST_VOTED', 'COL_FIRST_DATE',
    'PPL_COL_POLL_ID', 'PPL_COL_POLL_DATE', 'PPL_COL_POLL_QUESTION', 'PPL_COL_PLAYER_NAME',
    'PPL_COL_VOTE_TIMESTAMP', 'PPL_COL_VOTE_OPTIONS', 'PPL_COL_VOTE_RAW_JSON',
    'POLL_LOG_SHEET_NAME'
]

# Scopes for Google Sheets API
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Phrases that indicate "cannot play" - if any option contains these, it overrides others
CANNOT_PLAY_PHRASES = [
    "cannot play",
    "can't play",
    "cant play",
    "not available",
    "unavailable",
    "skip this week",
    "out this week",
]


def is_cannot_play_option(option: str) -> bool:
    """Check if an option indicates the user cannot play."""
    option_lower = option.lower()
    return any(phrase in option_lower for phrase in CANNOT_PLAY_PHRASES)


def get_sheets_service():
    """Initialize and return Google Sheets API service."""
    if os.path.exists(CREDENTIALS_FILE):
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    elif os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        # Support credentials as JSON string (for GitHub Actions)
        creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS_JSON'])
        creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    else:
        print(f"ERROR: Credentials file '{CREDENTIALS_FILE}' not found.")
        print("Either place the service account JSON file in this directory,")
        print("or set GOOGLE_CREDENTIALS_JSON environment variable.")
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


def update_sheet_data(sheets, range_name: str, values: List[List], value_input_option: str = 'USER_ENTERED'):
    """Update data in the spreadsheet."""
    range_name = f"'{SHEET_NAME}'!{range_name}"

    try:
        body = {'values': values}
        result = sheets.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption=value_input_option,
            body=body
        ).execute()
        return result
    except HttpError as e:
        print(f"ERROR: Failed to update sheet data: {e}")
        sys.exit(1)


def insert_column(sheets, column_index: int):
    """Insert a new column at the specified index."""
    try:
        # Get the sheet ID first
        spreadsheet = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_id = None
        for sheet in spreadsheet['sheets']:
            if sheet['properties']['title'] == SHEET_NAME:
                sheet_id = sheet['properties']['sheetId']
                break

        if sheet_id is None:
            print(f"ERROR: Sheet '{SHEET_NAME}' not found")
            sys.exit(1)

        request = {
            'requests': [{
                'insertDimension': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'COLUMNS',
                        'startIndex': column_index,
                        'endIndex': column_index + 1
                    },
                    'inheritFromBefore': False
                }
            }]
        }

        sheets.batchUpdate(spreadsheetId=SPREADSHEET_ID, body=request).execute()
        return True
    except HttpError as e:
        print(f"ERROR: Failed to insert column: {e}")
        return False


def col_index_to_letter(index: int) -> str:
    """Convert 0-based column index to letter (0=A, 1=B, 26=AA, etc.)."""
    result = ""
    while index >= 0:
        result = chr(index % 26 + ord('A')) + result
        index = index // 26 - 1
    return result


def update_vote_in_sheet(sheets, voter_phone: str, selected_options: list, all_options: list,
                         logger=None) -> bool:
    """
    Update Google Sheet with vote data.

    - Find the row for this voter by phone number
    - Update Last Voted column with current date
    - Update date columns with 'y' for selected, 'n' for unselected
    - If "cannot play" selected, set all date columns to 'n'

    Args:
        sheets: Google Sheets service
        voter_phone: Phone number (digits only, e.g., "13106001023")
        selected_options: List of selected poll options
        all_options: All available poll options (for column matching)
        logger: Optional logger for messages

    Returns:
        True if successful, False otherwise
    """
    def log_warning(msg):
        if logger:
            logger.warning(msg)
        else:
            print(f"[WARNING] {msg}")

    def log_info(msg):
        if logger:
            logger.info(msg)
        else:
            print(f"[INFO] {msg}")

    try:
        # Get all sheet data to find voter row and column headers
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        if len(data) < 2:
            log_warning("Sheet has no data rows")
            return False

        headers = data[0]

        # Find voter row by phone number
        voter_row = None
        for row_idx, row in enumerate(data[1:], start=2):  # Start at row 2 (1-indexed for Sheets)
            if len(row) > COL_MOBILE:
                cell_phone = row[COL_MOBILE] if COL_MOBILE < len(row) else ''
                # Normalize phone: remove non-digits
                cell_digits = ''.join(c for c in str(cell_phone) if c.isdigit())
                if len(cell_digits) == 10:
                    cell_digits = '1' + cell_digits
                if cell_digits == voter_phone:
                    voter_row = row_idx
                    break

        if voter_row is None:
            log_warning(f"Voter with phone {voter_phone} not found in sheet")
            return False

        # Determine if "cannot play" was selected
        cannot_play_selected = any(is_cannot_play_option(opt) for opt in selected_options)

        # Build list of date columns that match poll options
        updates = []

        # Update Last Voted column with current date (M/D/YY format)
        today = datetime.now()
        last_voted_str = f"{today.month}/{today.day}/{today.year % 100}"
        last_voted_col = col_index_to_letter(COL_LAST_VOTED)
        updates.append({
            'range': f"'{SHEET_NAME}'!{last_voted_col}{voter_row}",
            'values': [[last_voted_str]]
        })

        # Match poll options to sheet columns
        for col_idx, header in enumerate(headers):
            if col_idx < COL_FIRST_DATE:
                continue  # Skip non-date columns

            # Check if this header matches any poll option
            matched_option = None
            for opt in all_options:
                if is_cannot_play_option(opt):
                    continue  # Skip "cannot play" option for column matching
                # Try exact match first
                if header == opt or header.strip() == opt.strip():
                    matched_option = opt
                    break
                # Try matching just the date part (e.g., "Wed 1/22/26")
                header_date = ' '.join(header.split()[:2]) if header else ''
                opt_date = ' '.join(opt.split()[:2]) if opt else ''
                if header_date and opt_date and header_date == opt_date:
                    matched_option = opt
                    break

            if matched_option:
                # Determine value: 'n' if cannot play, else 'y' if selected, 'n' if not
                if cannot_play_selected:
                    value = 'n'
                elif matched_option in selected_options:
                    value = 'y'
                else:
                    value = 'n'

                col_letter = col_index_to_letter(col_idx)
                updates.append({
                    'range': f"'{SHEET_NAME}'!{col_letter}{voter_row}",
                    'values': [[value]]
                })

        # Execute batch update
        if updates:
            body = {'valueInputOption': 'RAW', 'data': updates}
            sheets.values().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body=body
            ).execute()
            log_info(f"Updated sheet for voter {voter_phone}: {len(updates)} cells")
            return True

        return False

    except Exception as e:
        log_warning(f"Failed to update sheet: {e}")
        return False


def find_player_row(data: List[List], first_name: str, last_name: str) -> Optional[int]:
    """Find the row index (0-based) for a player by name."""
    first_name_lower = first_name.lower().strip()
    last_name_lower = last_name.lower().strip()

    for i, row in enumerate(data):
        if len(row) >= 2:
            if row[COL_FIRST_NAME].lower().strip() == first_name_lower and \
               row[COL_LAST_NAME].lower().strip() == last_name_lower:
                return i
    return None


def find_date_column(headers: List[str], date_str: str) -> Optional[int]:
    """Find the column index for a date string."""
    date_str_normalized = normalize_date_str(date_str)

    for i, header in enumerate(headers):
        if i >= COL_FIRST_DATE:
            if normalize_date_str(header) == date_str_normalized:
                return i
    return None


def normalize_date_str(date_str: str) -> str:
    """Normalize date string for comparison (e.g., 'Sun 1/18/26' -> 'sun 1/18/26')."""
    return date_str.lower().strip()


def parse_date_from_header(header: str) -> Optional[datetime]:
    """Parse a date from column header like 'Sun 1/18/26'."""
    # Pattern: Day M/D/YY or Day MM/DD/YY
    match = re.match(r'^(Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)\s+(\d{1,2})/(\d{1,2})/(\d{2})$', header, re.IGNORECASE)
    if match:
        month = int(match.group(2))
        day = int(match.group(3))
        year = 2000 + int(match.group(4))
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return None


def get_headers(data: List[List]) -> List[str]:
    """Get the header row."""
    if data and len(data) > 0:
        return data[0]
    return []


def list_players(sheets):
    """List all players in the spreadsheet."""
    data = get_sheet_data(sheets)
    if not data or len(data) < 2:
        print("No players found.")
        return

    print("\n=== SMAD Players ===\n")
    print(f"{'Name':<25} {'Balance':>10} {'Invoiced':>10} {'Paid':>10} {'2026 Hours':>12} {'Last Paid':>12} {'Vacation':>12}")
    print("-" * 100)

    for row in data[1:]:  # Skip header
        if len(row) >= 2:
            first_name = row[COL_FIRST_NAME] if len(row) > COL_FIRST_NAME else ""
            last_name = row[COL_LAST_NAME] if len(row) > COL_LAST_NAME else ""
            balance = row[COL_BALANCE] if len(row) > COL_BALANCE else ""
            paid = row[COL_PAID] if len(row) > COL_PAID else ""
            invoiced = row[COL_INVOICED] if len(row) > COL_INVOICED else ""
            hours_2026 = row[COL_2026_HOURS] if len(row) > COL_2026_HOURS else ""
            last_paid = row[COL_LAST_PAID] if len(row) > COL_LAST_PAID else ""
            vacation = row[COL_VACATION] if len(row) > COL_VACATION else ""

            name = f"{first_name} {last_name}".strip()
            if name:
                print(f"{name:<25} {balance:>10} {invoiced:>10} {paid:>10} {hours_2026:>12} {last_paid:>12} {vacation:>12}")

    print()


def show_balances(sheets):
    """Show players with outstanding balances."""
    data = get_sheet_data(sheets)
    if not data or len(data) < 2:
        print("No players found.")
        return

    print("\n=== Outstanding Balances ===\n")
    print(f"{'Name':<25} {'Balance':>10} {'Last Paid':>12}")
    print("-" * 50)

    has_balances = False
    for row in data[1:]:  # Skip header
        if len(row) > COL_BALANCE:
            first_name = row[COL_FIRST_NAME] if len(row) > COL_FIRST_NAME else ""
            last_name = row[COL_LAST_NAME] if len(row) > COL_LAST_NAME else ""
            balance_str = row[COL_BALANCE] if len(row) > COL_BALANCE else "0"
            last_paid = row[COL_LAST_PAID] if len(row) > COL_LAST_PAID else ""

            # Parse balance (handle $, negative, etc.)
            try:
                balance = float(balance_str.replace('$', '').replace(',', '').strip() or '0')
            except ValueError:
                balance = 0

            if balance > 0:
                has_balances = True
                name = f"{first_name} {last_name}".strip()
                print(f"{name:<25} ${balance:>9.2f} {last_paid:>12}")

    if not has_balances:
        print("No outstanding balances!")

    print()


def register_player(sheets, player_name: str, date_str: str, hours: float):
    """Register a player for a game (add hours to a date column)."""
    # Parse player name
    name_parts = player_name.strip().split(' ', 1)
    if len(name_parts) < 2:
        print(f"ERROR: Please provide full name (First Last): '{player_name}'")
        return False

    first_name = name_parts[0]
    last_name = name_parts[1]

    data = get_sheet_data(sheets)
    if not data:
        print("ERROR: Could not fetch sheet data")
        return False

    headers = get_headers(data)

    # Find player row
    player_row = find_player_row(data, first_name, last_name)
    if player_row is None:
        print(f"ERROR: Player '{player_name}' not found in spreadsheet")
        print("Available players:")
        for row in data[1:]:
            if len(row) >= 2:
                print(f"  - {row[COL_FIRST_NAME]} {row[COL_LAST_NAME]}")
        return False

    # Find date column
    date_col = find_date_column(headers, date_str)
    if date_col is None:
        print(f"ERROR: Date column '{date_str}' not found")
        print("Available dates:")
        for i, header in enumerate(headers):
            if i >= COL_FIRST_DATE:
                print(f"  - {header}")
        print(f"\nTo add this date, run: python smad-sheets.py add-date \"{date_str}\"")
        return False

    # Update the cell
    cell_ref = f"{col_index_to_letter(date_col)}{player_row + 1}"
    update_sheet_data(sheets, cell_ref, [[hours]])

    print(f"[OK] Registered {first_name} {last_name} for {date_str}: {hours} hours")
    return True


def add_date_column(sheets, date_str: str):
    """Add a new date column after 'Last Paid' column."""
    data = get_sheet_data(sheets)
    if not data:
        print("ERROR: Could not fetch sheet data")
        return False

    headers = get_headers(data)

    # Check if date already exists
    existing_col = find_date_column(headers, date_str)
    if existing_col is not None:
        print(f"Date column '{date_str}' already exists at column {col_index_to_letter(existing_col)}")
        return False

    # Insert column at position COL_FIRST_DATE (after Last Paid)
    if not insert_column(sheets, COL_FIRST_DATE):
        return False

    # Set the header for the new column
    cell_ref = f"{col_index_to_letter(COL_FIRST_DATE)}1"
    update_sheet_data(sheets, cell_ref, [[date_str]])

    print(f"[OK] Added new date column: '{date_str}' at column {col_index_to_letter(COL_FIRST_DATE)}")
    return True

def send_reminders(sheets, min_balance: float = 0.01, send_summary: bool = True, send_individual: bool = False):
    """Send payment reminder emails to players with outstanding balances."""
    if not is_email_configured():
        print("ERROR: Email not configured. Set GMAIL_USERNAME and GMAIL_APP_PASSWORD environment variables.")
        return False

    data = get_sheet_data(sheets)
    if not data or len(data) < 2:
        print("No players found.")
        return False

    headers = get_headers(data)

    # Find the most recent date column with hours for each player
    date_columns = []
    for i, header in enumerate(headers):
        if i >= COL_FIRST_DATE:
            parsed_date = parse_date_from_header(header)
            if parsed_date:
                date_columns.append((i, header, parsed_date))

    # Sort by date descending (newest first)
    date_columns.sort(key=lambda x: x[2], reverse=True)

    # Collect players with balances
    players_to_remind = []

    for row in data[1:]:
        if len(row) > COL_BALANCE:
            first_name = row[COL_FIRST_NAME] if len(row) > COL_FIRST_NAME else ""
            last_name = row[COL_LAST_NAME] if len(row) > COL_LAST_NAME else ""
            email = row[COL_EMAIL] if len(row) > COL_EMAIL else ""
            balance_str = row[COL_BALANCE] if len(row) > COL_BALANCE else "0"
            hours_2026_str = row[COL_2026_HOURS] if len(row) > COL_2026_HOURS else "0"

            try:
                balance = float(balance_str.replace('$', '').replace(',', '').strip() or '0')
            except ValueError:
                balance = 0

            try:
                hours_2026 = float(hours_2026_str.replace('$', '').replace(',', '').strip() or '0')
            except ValueError:
                hours_2026 = 0

            # Find the most recent game date for this player
            last_game_date = None
            for col_idx, header, _ in date_columns:
                if col_idx < len(row):
                    try:
                        hours = float(row[col_idx] or 0)
                        if hours > 0:
                            last_game_date = header
                            break
                    except ValueError:
                        pass

            if balance >= min_balance:
                players_to_remind.append({
                    'name': f"{first_name} {last_name}",
                    'balance': balance,
                    'email': email.strip() if email else None,
                    'last_game_date': last_game_date,
                    'hours_2026': hours_2026
                })

    if not players_to_remind:
        print("No players with outstanding balances.")
        return True

    print(f"\n=== Players with Outstanding Balances ({len(players_to_remind)}) ===\n")
    for player in players_to_remind:
        email_status = f" ({player['email']})" if player['email'] else " (no email)"
        print(f"  {player['name']}: ${player['balance']:.2f}{email_status}")

    # Send summary email to admin
    if send_summary:
        print("\n[INFO] Sending balance summary to admin...")
        if send_balance_summary(players_to_remind):
            print("[OK] Summary email sent!")
        else:
            print("[WARN] Failed to send summary email")

    # Send individual reminders if requested
    if send_individual:
        print("\n[INFO] Sending individual reminders...")
        sent_count = 0
        skipped_count = 0
        for player in players_to_remind:
            if player['email']:
                if send_payment_reminder(
                    player['name'],
                    player['balance'],
                    player['email'],
                    last_game_date=player.get('last_game_date'),
                    hours_2026=player.get('hours_2026', 0)
                ):
                    print(f"  [OK] Sent to {player['name']} ({player['email']})")
                    sent_count += 1
                else:
                    print(f"  [WARN] Failed to send to {player['name']}")
            else:
                print(f"  [SKIP] {player['name']} - no email address")
                skipped_count += 1
        print(f"\n[OK] Sent {sent_count} reminders, skipped {skipped_count} (no email)")

    return True


def ensure_pickle_poll_log_sheet(sheets):
    """
    Ensure the Pickle Poll Log sheet exists with proper headers.
    Creates the sheet if it doesn't exist.

    Returns:
        True if sheet exists or was created, False on error
    """
    try:
        # Get spreadsheet metadata to check if sheet exists
        spreadsheet = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()

        # Check if Pickle Poll Log sheet exists
        sheet_exists = False
        for sheet in spreadsheet['sheets']:
            if sheet['properties']['title'] == POLL_LOG_SHEET_NAME:
                sheet_exists = True
                break

        if not sheet_exists:
            # Create the sheet
            request = {
                'requests': [{
                    'addSheet': {
                        'properties': {
                            'title': POLL_LOG_SHEET_NAME,
                            'gridProperties': {
                                'rowCount': 1000,
                                'columnCount': 7
                            }
                        }
                    }
                }]
            }
            sheets.batchUpdate(spreadsheetId=SPREADSHEET_ID, body=request).execute()
            print(f"[OK] Created '{POLL_LOG_SHEET_NAME}' sheet")

            # Add headers
            headers = [['Poll ID', 'Poll Created Date', 'Poll Question', 'Player Name',
                       'Vote Timestamp', 'Vote Options', 'Vote Raw JSON']]
            range_name = f"'{POLL_LOG_SHEET_NAME}'!A1:G1"
            body = {'values': headers}
            sheets.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            print(f"[OK] Added headers to '{POLL_LOG_SHEET_NAME}'")

        return True

    except HttpError as e:
        print(f"ERROR: Failed to ensure Pickle Poll Log sheet: {e}")
        return False


def record_poll_vote(sheets, poll_id: str, poll_date: str, poll_question: str,
                     player_name: str, vote_timestamp: str, vote_options: str,
                     vote_raw_json: str):
    """
    Record a poll vote in the Pickle Poll Log sheet.

    Args:
        sheets: Google Sheets service
        poll_id: Unique poll identifier (message ID from WhatsApp)
        poll_date: Date poll was created (M/D/YY HH:MM:SS format)
        poll_question: The poll question text
        player_name: Full name of voter (First Last)
        vote_timestamp: When the vote was cast (M/D/YY HH:MM:SS format)
        vote_options: Comma-separated list of selected options
        vote_raw_json: JSON string of full vote data

    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure sheet exists
        if not ensure_pickle_poll_log_sheet(sheets):
            return False

        # Append the vote row
        row = [[poll_id, poll_date, poll_question, player_name, vote_timestamp,
               vote_options, vote_raw_json]]

        range_name = f"'{POLL_LOG_SHEET_NAME}'!A:G"
        body = {'values': row}

        sheets.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()

        return True

    except HttpError as e:
        print(f"ERROR: Failed to record poll vote: {e}")
        return False


def get_latest_poll_info(sheets) -> Optional[Dict[str, str]]:
    """
    Get information about the most recent poll.

    Returns:
        Dict with keys: poll_id, poll_date, poll_question
        None if no polls found
    """
    try:
        # Ensure sheet exists
        if not ensure_pickle_poll_log_sheet(sheets):
            return None

        # Read all data from Pickle Poll Log
        range_name = f"'{POLL_LOG_SHEET_NAME}'"
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        data = result.get('values', [])

        if len(data) < 2:  # Only headers or empty
            return None

        # Find the row with the most recent poll date (skip header row)
        latest_poll = None
        latest_date = None

        for row in data[1:]:  # Skip header
            if len(row) >= 3:
                poll_date_str = row[PPL_COL_POLL_DATE]

                # Parse date to find latest (format: M/D/YY HH:MM:SS)
                try:
                    poll_date = datetime.strptime(poll_date_str, '%m/%d/%y %H:%M:%S')
                except ValueError:
                    try:
                        # Try without time
                        poll_date = datetime.strptime(poll_date_str, '%m/%d/%y')
                    except ValueError:
                        continue

                if latest_date is None or poll_date > latest_date:
                    latest_date = poll_date
                    latest_poll = {
                        'poll_id': row[PPL_COL_POLL_ID],
                        'poll_date': row[PPL_COL_POLL_DATE],
                        'poll_question': row[PPL_COL_POLL_QUESTION]
                    }

        return latest_poll

    except HttpError as e:
        print(f"ERROR: Failed to get latest poll info: {e}")
        return None


def get_poll_voters(sheets, poll_date: str) -> set:
    """
    Get the set of player names who voted in a poll on a specific date.

    Args:
        sheets: Google Sheets service
        poll_date: Poll date to filter by (M/D/YY HH:MM:SS format)

    Returns:
        Set of player names (strings) who voted
    """
    try:
        # Ensure sheet exists
        if not ensure_pickle_poll_log_sheet(sheets):
            return set()

        # Read all data from Pickle Poll Log
        range_name = f"'{POLL_LOG_SHEET_NAME}'"
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        data = result.get('values', [])

        if len(data) < 2:  # Only headers or empty
            return set()

        # Collect player names for this poll date
        voters = set()

        for row in data[1:]:  # Skip header
            if len(row) >= 4:
                row_poll_date = row[PPL_COL_POLL_DATE]
                player_name = row[PPL_COL_PLAYER_NAME]

                if row_poll_date == poll_date:
                    voters.add(player_name)

        return voters

    except HttpError as e:
        print(f"ERROR: Failed to get poll voters: {e}")
        return set()


def main():
    parser = argparse.ArgumentParser(
        description='SMAD Pickleball Google Sheets Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list-players                           List all players
  %(prog)s show-balances                          Show players with balances
  %(prog)s register "John Doe" "Sun 1/19/26" 2    Register 2 hours for John
  %(prog)s add-date "Tues 1/21/26"                Add new date column
  %(prog)s send-reminders                         Send payment reminders

Environment variables:
  SMAD_SPREADSHEET_ID      Google Sheets ID (default: your SMAD sheet)
  SMAD_SHEET_NAME          Sheet/tab name (default: 2026 Pickleball)
  GOOGLE_CREDENTIALS_FILE  Path to service account JSON (default: smad-credentials.json)
  GOOGLE_CREDENTIALS_JSON  Service account JSON as string (for CI/CD)
  SMAD_HOURLY_RATE         Cost per hour (default: 8.0)
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # list-players
    subparsers.add_parser('list-players', help='List all players')

    # show-balances
    subparsers.add_parser('show-balances', help='Show players with outstanding balances')

    # register
    register_parser = subparsers.add_parser('register', help='Register a player for a game')
    register_parser.add_argument('player_name', help='Player name (e.g., "John Doe")')
    register_parser.add_argument('date', help='Date column (e.g., "Sun 1/19/26")')
    register_parser.add_argument('hours', type=float, help='Hours played')

    # add-date
    add_date_parser = subparsers.add_parser('add-date', help='Add a new date column')
    add_date_parser.add_argument('date', help='Date string (e.g., "Tues 1/21/26")')

    # send-reminders
    reminder_parser = subparsers.add_parser('send-reminders', help='Send payment reminder emails')
    reminder_parser.add_argument('--min-balance', type=float, default=0.01,
                                 help='Minimum balance to trigger reminder (default: $0.01)')
    reminder_parser.add_argument('--send-individual', action='store_true',
                                 help='Send individual reminder emails to players with email addresses')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize Google Sheets service
    sheets = get_sheets_service()

    # Execute command
    if args.command == 'list-players':
        list_players(sheets)
    elif args.command == 'show-balances':
        show_balances(sheets)
    elif args.command == 'register':
        register_player(sheets, args.player_name, args.date, args.hours)
    elif args.command == 'add-date':
        add_date_column(sheets, args.date)
    elif args.command == 'send-reminders':
        send_reminders(sheets, args.min_balance, send_individual=args.send_individual)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
