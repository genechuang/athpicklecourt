"""
SMAD WhatsApp Poll Vote Webhook - Google Cloud Function

Receives webhook notifications from GREEN-API when users vote on WhatsApp polls.
Stores vote data in Google Sheets 'Pickle Poll Log' sheet.

Data Model in Google Sheets:
    Sheet: Pickle Poll Log
    Columns:
        - Poll ID (stanza ID)
        - Poll Created Date (M/D/YY HH:MM:SS)
        - Poll Question
        - Player Name
        - Vote Timestamp (M/D/YY HH:MM:SS)
        - Vote Options (comma-separated selected options)
        - Vote Raw JSON (full vote data as JSON)

    Each vote creates a new row (one row per vote per player).
    Vote changes create additional rows (audit trail maintained).

Special Logic:
    - If user selects "I cannot play this week" (or similar), it overrides all other selections
    - Vote changes create new rows (audit trail is kept)

Note:
    This webhook directly updates Google Sheets using smad-sheets.py functions.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

import functions_framework
import pytz

# PST timezone for all date/time operations
PST = pytz.timezone('America/Los_Angeles')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Google Sheets imports and initialization
try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    logger.error("Google API libraries not installed")
    sys.exit(1)

# Configuration
SPREADSHEET_ID = os.environ.get('SMAD_SPREADSHEET_ID', '1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY')
POLL_LOG_SHEET_NAME = os.environ.get('POLL_LOG_SHEET_NAME', 'Pickle Poll Log')
MAIN_SHEET_NAME = os.environ.get('SMAD_SHEET_NAME', '2026 Pickleball')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# WhatsApp group ID to process votes from (only process votes from SMAD group, not Admin Dinkers)
SMAD_WHATSAPP_GROUP_ID = os.environ.get('SMAD_WHATSAPP_GROUP_ID', '')

# Column indices for main sheet (to find player names by phone)
COL_FIRST_NAME = 0
COL_LAST_NAME = 1
COL_MOBILE = 4
COL_LAST_VOTED = 12

# Sheets service (lazy init)
_sheets_service = None

def get_sheets_service():
    """Initialize and return Google Sheets API service."""
    global _sheets_service
    if _sheets_service is None:
        try:
            # Try credentials from environment variable first (for Cloud Functions)
            if os.environ.get('GOOGLE_CREDENTIALS_JSON'):
                creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS_JSON'])
                creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
            else:
                # Fall back to default credentials
                from google.auth import default
                creds, _ = default(scopes=SCOPES)

            service = build('sheets', 'v4', credentials=creds)
            _sheets_service = service.spreadsheets()
        except Exception as e:
            logger.error(f"Failed to initialize Sheets service: {e}")
            raise

    return _sheets_service

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


def process_cannot_play_override(selected_options: list) -> list:
    """
    If user selected a 'cannot play' option along with play dates,
    return only the 'cannot play' option (they forgot to unselect dates).
    """
    cannot_play_options = [opt for opt in selected_options if is_cannot_play_option(opt)]

    if cannot_play_options and len(selected_options) > len(cannot_play_options):
        # User selected both "cannot play" AND some dates - keep only "cannot play"
        logger.info(f"Override: User selected both dates and 'cannot play'. Keeping only: {cannot_play_options}")
        return cannot_play_options

    return selected_options


def get_player_name_by_phone(sheets, phone: str) -> str:
    """
    Look up player name in the main sheet by phone number.
    Returns "First Last" or "Unknown" if not found.
    """
    try:
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{MAIN_SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        # Normalize phone number
        phone_normalized = ''.join(c for c in phone if c.isdigit())
        if len(phone_normalized) == 10:
            phone_normalized = '1' + phone_normalized

        for row in data[1:]:  # Skip header
            if len(row) > COL_MOBILE:
                cell_phone = row[COL_MOBILE] if COL_MOBILE < len(row) else ''
                cell_digits = ''.join(c for c in str(cell_phone) if c.isdigit())
                if len(cell_digits) == 10:
                    cell_digits = '1' + cell_digits

                if cell_digits == phone_normalized:
                    first_name = row[COL_FIRST_NAME] if COL_FIRST_NAME < len(row) else ''
                    last_name = row[COL_LAST_NAME] if COL_LAST_NAME < len(row) else ''
                    return f"{first_name} {last_name}".strip()

        return "Unknown"

    except Exception as e:
        logger.error(f"Failed to lookup player by phone: {e}")
        return "Unknown"


def ensure_poll_log_sheet(sheets):
    """
    Ensure the Pickle Poll Log sheet exists with proper headers.
    Creates the sheet if it doesn't exist.
    """
    try:
        # Get spreadsheet metadata
        spreadsheet = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()

        # Check if sheet exists
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
            logger.info(f"Created '{POLL_LOG_SHEET_NAME}' sheet")

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

        return True

    except Exception as e:
        logger.error(f"Failed to ensure poll log sheet: {e}")
        return False


def cleanup_old_poll_logs(sheets):
    """
    Clean up old poll log entries on Sundays.
    Deletes rows where vote timestamp is more than 7 days old.
    Only runs on Sundays.
    """
    try:
        # Check if today is Sunday (weekday == 6) in PST
        now = datetime.now(PST)
        if now.weekday() != 6:
            return False

        logger.info("Sunday detected - checking for old poll logs to clean up")

        # Read all rows from Pickle Poll Log
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{POLL_LOG_SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        if len(data) < 2:  # Only header or empty
            logger.info("No poll logs to clean up")
            return False

        # Find rows to delete (vote timestamp more than 7 days old)
        rows_to_delete = []
        cutoff_date = now - timedelta(days=7)

        for row_idx, row in enumerate(data[1:], start=1):  # Skip header, start at row index 1
            if len(row) >= 5:  # Make sure Vote Timestamp column exists
                vote_timestamp_str = row[4]  # Column 4 = Vote Timestamp
                try:
                    vote_timestamp = datetime.strptime(vote_timestamp_str, '%m/%d/%y %H:%M:%S')
                    if vote_timestamp < cutoff_date:
                        rows_to_delete.append(row_idx)
                        logger.info(f"Marking row {row_idx + 1} for deletion (vote from {vote_timestamp_str})")
                except ValueError as e:
                    logger.warning(f"Could not parse timestamp '{vote_timestamp_str}' at row {row_idx + 1}: {e}")
                    continue

        if not rows_to_delete:
            logger.info("No old poll logs found to clean up")
            return False

        # Get the sheet ID
        spreadsheet = sheets.get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_id = None
        for sheet in spreadsheet['sheets']:
            if sheet['properties']['title'] == POLL_LOG_SHEET_NAME:
                sheet_id = sheet['properties']['sheetId']
                break

        if sheet_id is None:
            logger.error(f"Could not find sheet ID for '{POLL_LOG_SHEET_NAME}'")
            return False

        # Delete rows in reverse order (so indices don't shift)
        requests = []
        for row_idx in sorted(rows_to_delete, reverse=True):
            # row_idx is 1-based (we started enumerate at 1)
            # Google Sheets API uses 0-based indices, and row_idx + 1 accounts for header row
            sheet_row_idx = row_idx  # This is already correct: data row 1 = sheet row 1 (0-indexed)
            requests.append({
                'deleteDimension': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': sheet_row_idx,
                        'endIndex': sheet_row_idx + 1
                    }
                }
            })

        # Execute batch delete
        if requests:
            batch_update_body = {'requests': requests}
            sheets.batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body=batch_update_body
            ).execute()
            logger.info(f"Deleted {len(rows_to_delete)} old poll log entries")
            return True

        return False

    except Exception as e:
        logger.error(f"Failed to clean up old poll logs: {e}")
        return False


def record_poll_vote_to_sheet(sheets, poll_id: str, poll_date: str, poll_question: str,
                               player_name: str, vote_timestamp: str, vote_options: str,
                               vote_raw_json: str):
    """
    Record a poll vote in the Pickle Poll Log sheet.
    Performs Sunday cleanup of old entries (>7 days) before recording new votes.
    """
    try:
        # Ensure sheet exists
        if not ensure_poll_log_sheet(sheets):
            return False

        # Clean up old entries on Sundays
        cleanup_old_poll_logs(sheets)

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

        logger.info(f"Recorded vote for {player_name} in poll {poll_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to record poll vote: {e}")
        return False


def update_last_voted_date(sheets, phone: str):
    """
    Update the Last Voted column in the main sheet for a player.
    """
    try:
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{MAIN_SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        # Normalize phone number
        phone_normalized = ''.join(c for c in phone if c.isdigit())
        if len(phone_normalized) == 10:
            phone_normalized = '1' + phone_normalized

        # Find player row
        for row_idx, row in enumerate(data[1:], start=2):  # Start at row 2
            if len(row) > COL_MOBILE:
                cell_phone = row[COL_MOBILE] if COL_MOBILE < len(row) else ''
                cell_digits = ''.join(c for c in str(cell_phone) if c.isdigit())
                if len(cell_digits) == 10:
                    cell_digits = '1' + cell_digits

                if cell_digits == phone_normalized:
                    # Update Last Voted column with ISO date format
                    # Using USER_ENTERED so Sheets parses it as a date value
                    today = datetime.now(PST)
                    last_voted_str = today.strftime('%Y-%m-%d')  # ISO format: YYYY-MM-DD

                    # Column M (index 12) is Last Voted
                    col_letter = chr(ord('A') + COL_LAST_VOTED)
                    range_name = f"'{MAIN_SHEET_NAME}'!{col_letter}{row_idx}"

                    sheets.values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=range_name,
                        valueInputOption='USER_ENTERED',  # Parse as date, not text
                        body={'values': [[last_voted_str]]}
                    ).execute()

                    logger.info(f"Updated Last Voted for player at row {row_idx}")
                    return True

        return False

    except Exception as e:
        logger.error(f"Failed to update last voted date: {e}")
        return False


def get_poll_creation_date(sheets, poll_id: str) -> datetime:
    """
    Look up poll creation date from Pickle Poll Log sheet.
    Returns the earliest vote timestamp for this poll_id.
    """
    try:
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{POLL_LOG_SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        if len(data) < 2:
            return None

        # Find earliest date for this poll_id (column 0 = Poll ID, column 1 = Poll Created Date)
        earliest_date = None
        for row in data[1:]:  # Skip header
            if len(row) >= 2 and row[0] == poll_id:
                date_str = row[1]
                try:
                    poll_date = datetime.strptime(date_str, '%m/%d/%y %H:%M:%S')
                    if earliest_date is None or poll_date < earliest_date:
                        earliest_date = poll_date
                except ValueError:
                    continue

        return earliest_date

    except Exception as e:
        logger.error(f"Failed to get poll creation date: {e}")
        return None


def update_poll_date_columns(sheets, phone: str, poll_id: str, selected_options: list, all_options: list):
    """
    Update the date columns in the main sheet with 'y' or 'n' based on votes.
    Only updates if poll is 7 days old or less. Matches columns by date label (first match left to right).

    Args:
        sheets: Google Sheets service
        phone: Voter's phone number
        poll_id: Poll ID (for age checking)
        selected_options: List of options the voter selected
        all_options: All poll options (to find date columns)
    """
    try:
        # Check poll age - ignore votes from polls older than 7 days
        poll_creation_date = get_poll_creation_date(sheets, poll_id)
        if poll_creation_date:
            days_old = (datetime.now(PST).replace(tzinfo=None) - poll_creation_date).days
            if days_old > 7:
                logger.info(f"Ignoring vote from expired poll (poll is {days_old} days old)")
                return False

        # Get sheet data
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{MAIN_SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        if len(data) < 2:
            logger.warning("Sheet has less than 2 rows")
            return False

        # Row 1 (index 0) contains date option headers
        header_row = data[0] if len(data) > 0 else []

        # Match poll options to columns by date label (first match from left to right)
        # Date columns start at COL_LAST_VOTED + 1
        poll_columns = {}  # {option_name: col_index}

        for option_name in all_options:
            # Skip "Can't play" options - these don't have date columns
            if any(phrase in option_name.lower() for phrase in CANNOT_PLAY_PHRASES):
                continue

            # Find first matching column (left to right scan)
            for col_idx in range(COL_LAST_VOTED + 1, len(header_row)):
                if header_row[col_idx] == option_name:
                    poll_columns[option_name] = col_idx
                    break  # Use first match

        if not poll_columns:
            logger.warning(f"No matching date columns found for poll options: {all_options}")
            return False

        logger.info(f"Found {len(poll_columns)} matching date columns: {list(poll_columns.keys())}")

        # Normalize phone number
        phone_normalized = ''.join(c for c in phone if c.isdigit())
        if len(phone_normalized) == 10:
            phone_normalized = '1' + phone_normalized

        # Find player row
        player_row_idx = None
        for row_idx, row in enumerate(data[1:], start=2):  # Start at row 2 (skip header)
            if len(row) > COL_MOBILE:
                cell_phone = row[COL_MOBILE] if COL_MOBILE < len(row) else ''
                cell_digits = ''.join(c for c in str(cell_phone) if c.isdigit())
                if len(cell_digits) == 10:
                    cell_digits = '1' + cell_digits

                if cell_digits == phone_normalized:
                    player_row_idx = row_idx
                    break

        if player_row_idx is None:
            logger.warning(f"Player not found for phone {phone}")
            return False

        # Prepare updates for each poll column
        updates = []
        for option_name, col_idx in poll_columns.items():
            # Determine value: 'y' if selected, 'n' if not
            if option_name in selected_options:
                value = 'y'
            else:
                value = 'n'

            # Convert column index to letter
            col_letter = ''
            col_num = col_idx
            while col_num >= 0:
                col_letter = chr(ord('A') + (col_num % 26)) + col_letter
                col_num = col_num // 26 - 1

            range_name = f"'{MAIN_SHEET_NAME}'!{col_letter}{player_row_idx}"
            updates.append({
                'range': range_name,
                'values': [[value]]
            })

        # Batch update all columns
        if updates:
            batch_update_body = {
                'valueInputOption': 'RAW',
                'data': updates
            }
            sheets.values().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body=batch_update_body
            ).execute()

            logger.info(f"Updated {len(updates)} date columns for player at row {player_row_idx}")
            return True

        return False

    except Exception as e:
        logger.error(f"Failed to update poll date columns: {e}")
        return False


def handle_poll_update(data: dict) -> dict:
    """
    Handle a poll update webhook from GREEN-API.

    Expected webhook payload structure for pollUpdateMessage:
    {
        "typeWebhook": "incomingMessageReceived",
        "instanceData": {...},
        "timestamp": 1234567890,
        "idMessage": "...",
        "senderData": {
            "chatId": "120363401568722062@g.us",
            "sender": "16265551234@c.us",
            "senderName": "John Doe"
        },
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollUpdateMessage": {
                "stanzaId": "3ADC47CA8A9698ABFD00",  # Poll ID
                "pollName": "Can you play this week?",
                "votes": [
                    {"optionName": "Sat 1/25", "voters": ["16265551234@c.us"]},
                    {"optionName": "Sun 1/26", "voters": []}
                ]
            }
        }
    }
    """
    try:
        # Extract relevant fields
        sender_data = data.get('senderData', {})
        message_data = data.get('messageData', {})

        chat_id = sender_data.get('chatId', '')
        voter_id = sender_data.get('sender', '').replace('@c.us', '').replace('@s.whatsapp.net', '')
        voter_name = sender_data.get('senderName', '')

        # GREEN-API uses 'pollMessageData' for poll updates (not 'pollUpdateMessage')
        poll_update = message_data.get('pollMessageData', {}) or message_data.get('pollUpdateMessage', {})
        poll_id = poll_update.get('stanzaId', '')
        poll_name = poll_update.get('name', poll_update.get('pollName', ''))
        votes_data = poll_update.get('votes', [])
        webhook_timestamp = data.get('timestamp', 0)

        if not poll_id or not voter_id:
            logger.warning(f"Missing poll_id or voter_id: poll_id={poll_id}, voter_id={voter_id}")
            logger.warning(f"messageData keys: {list(message_data.keys())}")
            logger.warning(f"poll_update contents: {poll_update}")
            return {'status': 'error', 'message': 'Missing poll_id or voter_id'}

        # Extract this voter's selections from the votes array
        # The votes array shows ALL votes for the poll, we need to find this voter's
        selected_options = []
        all_options = []

        for vote_option in votes_data:
            option_name = vote_option.get('optionName', '')
            # GREEN-API uses 'optionVoters' (not 'voters')
            voters = vote_option.get('optionVoters', vote_option.get('voters', []))
            all_options.append(option_name)

            # Check if this voter is in the voters list for this option
            voter_ids_in_option = [v.replace('@c.us', '').replace('@s.whatsapp.net', '') for v in voters]
            if voter_id in voter_ids_in_option:
                selected_options.append(option_name)

        # Apply "cannot play" override logic
        selected_options = process_cannot_play_override(selected_options)

        # Get Google Sheets service
        sheets = get_sheets_service()

        # Look up player name by phone number
        player_name = get_player_name_by_phone(sheets, voter_id)
        if player_name == "Unknown":
            player_name = voter_name  # Fall back to WhatsApp name

        # Record vote to Pickle Poll Log sheet (use PST timezone)
        now = datetime.now(PST)
        vote_timestamp = now.strftime('%m/%d/%y %H:%M:%S')

        # Get existing poll creation date, or use current time for first vote
        existing_poll_date = get_poll_creation_date(sheets, poll_id)
        if existing_poll_date:
            poll_date = existing_poll_date.strftime('%m/%d/%y %H:%M:%S')
        else:
            poll_date = vote_timestamp  # First vote on this poll
        vote_options_str = ', '.join(selected_options) if selected_options else '(removed all votes)'

        # Create raw JSON for audit
        vote_raw_json = json.dumps({
            'voter_id': voter_id,
            'voter_name': voter_name,
            'selected': selected_options,
            'all_options': all_options,
            'webhook_timestamp': webhook_timestamp
        })

        # Record to sheet
        record_poll_vote_to_sheet(
            sheets,
            poll_id=poll_id,
            poll_date=poll_date,
            poll_question=poll_name,
            player_name=player_name,
            vote_timestamp=vote_timestamp,
            vote_options=vote_options_str,
            vote_raw_json=vote_raw_json
        )

        # Update Last Voted column in main sheet
        update_last_voted_date(sheets, voter_id)

        # Update date columns with 'y' or 'n' based on votes
        update_poll_date_columns(sheets, voter_id, poll_id, selected_options, all_options)

        return {
            'status': 'ok',
            'poll_id': poll_id,
            'voter': voter_id,
            'player_name': player_name,
            'selected': selected_options
        }

    except Exception as e:
        logger.error(f"Error processing poll update: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


def handle_poll_message(data: dict) -> dict:
    """
    Handle a new poll creation webhook from GREEN-API.
    Poll creation is logged but not stored (we only store votes in Pickle Poll Log).

    Expected structure for pollMessage:
    {
        "typeWebhook": "outgoingMessageReceived",
        "messageData": {
            "typeMessage": "pollMessage",
            "pollMessageData": {
                "stanzaId": "...",
                "name": "Can you play this week?",
                "options": [{"optionName": "Sat 1/25"}, ...],
                "multipleAnswers": true
            }
        },
        "senderData": {
            "chatId": "120363401568722062@g.us"
        }
    }
    """
    try:
        message_data = data.get('messageData', {})
        poll_data = message_data.get('pollMessageData', {})

        poll_id = data.get('idMessage', poll_data.get('stanzaId', ''))
        poll_name = poll_data.get('name', '')
        options_raw = poll_data.get('options', [])

        # Extract option names
        options = []
        for opt in options_raw:
            if isinstance(opt, dict):
                options.append(opt.get('optionName', ''))
            else:
                options.append(str(opt))

        logger.info(f"Poll created: {poll_id} - {poll_name} with {len(options)} options")

        return {
            'status': 'ok',
            'poll_id': poll_id,
            'options': options
        }

    except Exception as e:
        logger.error(f"Error processing poll message: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


@functions_framework.http
def webhook(request):
    """
    HTTP Cloud Function entry point.
    Receives webhooks from GREEN-API.
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    # Only accept POST
    if request.method != 'POST':
        return {'error': 'Method not allowed'}, 405

    try:
        data = request.get_json(silent=True)
        if not data:
            return {'error': 'No JSON payload'}, 400

        # Use print for Cloud Run logs (flushes immediately)
        print(f"Received webhook: {data.get('typeWebhook', 'unknown')}", flush=True)
        print(f"Full payload: {json.dumps(data, default=str)}", flush=True)

        # Check webhook type
        type_webhook = data.get('typeWebhook', '')
        message_data = data.get('messageData', {})
        type_message = message_data.get('typeMessage', '')

        # Filter by group ID - only process votes from SMAD group (not Admin Dinkers)
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId', '')
        if SMAD_WHATSAPP_GROUP_ID and chat_id != SMAD_WHATSAPP_GROUP_ID:
            print(f"Ignoring message from non-SMAD group: {chat_id}", flush=True)
            return {'status': 'ignored', 'reason': 'non-SMAD group'}, 200

        # Handle poll update (vote cast/changed)
        if type_message == 'pollUpdateMessage':
            result = handle_poll_update(data)
            return result, 200

        # Handle new poll creation
        if type_message == 'pollMessage':
            result = handle_poll_message(data)
            return result, 200

        # Log other message types (not ignoring silently so we can debug)
        logger.info(f"Unhandled message type: {type_message}, webhook type: {type_webhook}")
        return {'status': 'ignored', 'type': type_message}, 200

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {'error': str(e)}, 500


# For local testing
if __name__ == '__main__':
    # Test with sample data
    test_poll_update = {
        "typeWebhook": "incomingMessageReceived",
        "senderData": {
            "chatId": "120363401568722062@g.us",
            "sender": "16265551234@c.us",
            "senderName": "Test User"
        },
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollUpdateMessage": {
                "stanzaId": "TEST_POLL_123",
                "pollName": "Can you play this week?",
                "votes": [
                    {"optionName": "Sat 1/25", "voters": ["16265551234@c.us"]},
                    {"optionName": "Sun 1/26", "voters": ["16265551234@c.us"]},
                    {"optionName": "I cannot play this week", "voters": []}
                ]
            }
        }
    }

    result = handle_poll_update(test_poll_update)
    print(f"Result: {result}")
