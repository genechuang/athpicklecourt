"""
SMAD WhatsApp Poll Vote Webhook - Google Cloud Function

Receives webhook notifications from GREEN-API when users vote on WhatsApp polls.
Stores vote data in Firestore, handling vote changes (user can flip their votes).

Data Model in Firestore:
    Collection: smad_polls
    Document ID: {poll_stanza_id}
    Fields:
        - question: str
        - chat_id: str
        - created_at: timestamp
        - options: list[str] (poll options, captured when first vote comes in)

    Subcollection: votes
    Document ID: {phone_number}
    Fields:
        - selected: list[str] (current selections - empty list means removed all votes)
        - updated_at: timestamp
        - vote_history: list[{selected: list, timestamp: str}] (optional audit trail)

Special Logic:
    - If user selects "I cannot play this week" (or similar), it overrides all other selections
    - Vote changes completely replace previous selections (WhatsApp sends full new selection)
"""

import json
import logging
import os
from datetime import datetime, timezone

import functions_framework
from google.cloud import firestore
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firestore client
db = firestore.Client()

# Collection name
POLLS_COLLECTION = 'smad_polls'

# Google Sheets configuration
SPREADSHEET_ID = os.environ.get('SMAD_SPREADSHEET_ID', '1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY')
SHEET_NAME = os.environ.get('SMAD_SHEET_NAME', '2026 Pickleball')

# Column indices (0-based) - must match smad-sheets.py
COL_FIRST_NAME = 0
COL_LAST_NAME = 1
COL_MOBILE = 3
COL_LAST_VOTED = 12
COL_FIRST_DATE = 13

# Lazy-loaded Sheets service
_sheets_service = None

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


def get_sheets_service():
    """Get or create Google Sheets service using Application Default Credentials."""
    global _sheets_service
    if _sheets_service is None:
        try:
            from google.auth import default
            credentials, project = default(scopes=['https://www.googleapis.com/auth/spreadsheets'])
            _sheets_service = build('sheets', 'v4', credentials=credentials).spreadsheets()
        except Exception as e:
            logger.error(f"Failed to initialize Sheets service: {e}")
            return None
    return _sheets_service


def col_to_letter(col_idx: int) -> str:
    """Convert column index (0-based) to letter (A, B, ..., Z, AA, AB, ...)."""
    result = ""
    while col_idx >= 0:
        result = chr(col_idx % 26 + ord('A')) + result
        col_idx = col_idx // 26 - 1
    return result


def update_sheet_vote(voter_phone: str, selected_options: list, all_options: list) -> bool:
    """
    Update Google Sheet with vote data.

    - Find the row for this voter by phone number
    - Update Last Voted column with current date
    - Update date columns with 'y' for selected, 'n' for unselected
    - If "cannot play" selected, set all date columns to 'n'

    Args:
        voter_phone: Phone number (digits only, e.g., "13106001023")
        selected_options: List of selected poll options
        all_options: All available poll options (for column matching)

    Returns:
        True if successful, False otherwise
    """
    try:
        sheets = get_sheets_service()
        if not sheets:
            logger.warning("Sheets service not available, skipping sheet update")
            return False

        # Get all sheet data to find voter row and column headers
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        if len(data) < 2:
            logger.warning("Sheet has no data rows")
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
            logger.warning(f"Voter with phone {voter_phone} not found in sheet")
            return False

        # Determine if "cannot play" was selected
        cannot_play_selected = any(is_cannot_play_option(opt) for opt in selected_options)

        # Build list of date columns that match poll options
        # Date columns start at COL_FIRST_DATE and go right
        updates = []

        # Update Last Voted column with current date (M/D/YY format)
        today = datetime.now(timezone.utc)
        last_voted_str = f"{today.month}/{today.day}/{today.year % 100}"
        last_voted_col = col_to_letter(COL_LAST_VOTED)
        updates.append({
            'range': f"'{SHEET_NAME}'!{last_voted_col}{voter_row}",
            'values': [[last_voted_str]]
        })

        # Match poll options to sheet columns
        # Headers are like "Wed 1/22/26 7pm-9pm" - need to match exactly or find similar
        for col_idx, header in enumerate(headers):
            if col_idx < COL_FIRST_DATE:
                continue  # Skip non-date columns

            # Check if this header matches any poll option (exact match or starts with same date)
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

                col_letter = col_to_letter(col_idx)
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
            logger.info(f"Updated sheet for voter {voter_phone}: {len(updates)} cells")
            return True

        return False

    except Exception as e:
        logger.error(f"Failed to update sheet: {e}", exc_info=True)
        return False


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

        # Store in Firestore
        now = datetime.now(timezone.utc)

        # Get or create poll document
        poll_ref = db.collection(POLLS_COLLECTION).document(poll_id)
        poll_doc = poll_ref.get()

        if not poll_doc.exists:
            # Create new poll document
            poll_ref.set({
                'question': poll_name,
                'chat_id': chat_id,
                'created_at': now,
                'options': all_options,
            })
            logger.info(f"Created new poll document: {poll_id}")
        elif all_options and not poll_doc.to_dict().get('options'):
            # Update options if we didn't have them before
            poll_ref.update({'options': all_options})

        # Update or create vote document
        vote_ref = poll_ref.collection('votes').document(voter_id)
        vote_doc = vote_ref.get()

        vote_data = {
            'selected': selected_options,
            'updated_at': now,
            'voter_name': voter_name,
        }

        if vote_doc.exists:
            # Keep vote history for audit trail
            existing = vote_doc.to_dict()
            history = existing.get('vote_history', [])
            history.append({
                'selected': existing.get('selected', []),
                'timestamp': existing.get('updated_at').isoformat() if existing.get('updated_at') else None
            })
            vote_data['vote_history'] = history
            vote_ref.update(vote_data)
            logger.info(f"Updated vote for {voter_id}: {selected_options}")
        else:
            vote_data['vote_history'] = []
            vote_ref.set(vote_data)
            logger.info(f"New vote from {voter_id}: {selected_options}")

        # Update Google Sheet with vote data
        try:
            update_sheet_vote(voter_id, selected_options, all_options)
        except Exception as e:
            logger.warning(f"Failed to update sheet (non-fatal): {e}")

        return {
            'status': 'ok',
            'poll_id': poll_id,
            'voter': voter_id,
            'selected': selected_options
        }

    except Exception as e:
        logger.error(f"Error processing poll update: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


def handle_poll_message(data: dict) -> dict:
    """
    Handle a new poll creation webhook from GREEN-API.
    This captures the poll options when a poll is first created.

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
        sender_data = data.get('senderData', {})
        message_data = data.get('messageData', {})

        chat_id = sender_data.get('chatId', '')
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

        if not poll_id:
            return {'status': 'error', 'message': 'Missing poll_id'}

        # Store poll document
        now = datetime.now(timezone.utc)
        poll_ref = db.collection(POLLS_COLLECTION).document(poll_id)

        poll_ref.set({
            'question': poll_name,
            'chat_id': chat_id,
            'created_at': now,
            'options': options,
            'multiple_answers': poll_data.get('multipleAnswers', True)
        }, merge=True)

        logger.info(f"Stored poll: {poll_id} - {poll_name} with {len(options)} options")

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
