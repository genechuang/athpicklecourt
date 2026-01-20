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

# Configuration - Google Sheets (reuse from smad-sheets.py)
SPREADSHEET_ID = os.environ.get('SMAD_SPREADSHEET_ID', '1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY')
SHEET_NAME = os.environ.get('SMAD_SHEET_NAME', '2026 Pickleball')
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'smad-credentials.json')
HOURLY_RATE = float(os.environ.get('SMAD_HOURLY_RATE', '4.0'))

# Column indices (0-based) - must match smad-sheets.py
COL_FIRST_NAME = 0
COL_LAST_NAME = 1
COL_EMAIL = 2
COL_MOBILE = 3
COL_VENMO = 4
COL_ZELLE = 5
COL_BALANCE = 6
COL_PAID = 7
COL_INVOICED = 8
COL_2026_HOURS = 9
COL_2025_HOURS = 10
COL_LAST_PAID = 11
COL_LAST_VOTED = 12
COL_FIRST_DATE = 13

# Google Sheets scopes (need write access for updating Last Voted and poll responses)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Configuration - Firestore (for poll vote tracking)
GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID', '')
FIRESTORE_COLLECTION = 'smad_polls'

# Configuration - Poll tracking (for legacy poll before webhook was set up)
POLL_CREATED_DATE = os.environ.get('POLL_CREATED_DATE', '')  # Format: M/DD/YY

# Firestore client (lazy initialization)
_firestore_client = None

def get_firestore_client():
    """Initialize and return Firestore client."""
    global _firestore_client
    if _firestore_client is None:
        try:
            from google.cloud import firestore
            if GCP_PROJECT_ID:
                _firestore_client = firestore.Client(project=GCP_PROJECT_ID)
            else:
                # Try to use default credentials
                _firestore_client = firestore.Client()
        except ImportError:
            print("ERROR: Firestore library not installed.")
            print("Run: pip install google-cloud-firestore")
            sys.exit(1)
        except Exception as e:
            print(f"ERROR: Failed to initialize Firestore: {e}")
            print("Make sure GCP_PROJECT_ID is set and you have valid credentials.")
            sys.exit(1)
    return _firestore_client


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
    Inserts columns right after COL_LAST_VOTED (column M), newest first.

    Args:
        sheets: Google Sheets service
        date_options: List of date strings like ["Wed 1/22/26 7pm-9pm", "Fri 1/24/26 7pm-9pm"]

    Returns:
        True if successful, False otherwise.
    """
    if not date_options:
        return True

    try:
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

        # Insert columns after COL_LAST_VOTED (index 12 = column M)
        # We need to insert len(date_options) columns at position COL_FIRST_DATE
        num_cols = len(date_options)

        # Insert columns
        requests = [{
            'insertDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'COLUMNS',
                    'startIndex': COL_FIRST_DATE,  # Column N (0-indexed = 13)
                    'endIndex': COL_FIRST_DATE + num_cols
                },
                'inheritFromBefore': False
            }
        }]

        sheets.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': requests}
        ).execute()

        # Set header row with date labels (newest first is already how options are ordered)
        # Convert column index to letter
        def col_to_letter(col_idx):
            result = ""
            while col_idx >= 0:
                result = chr(col_idx % 26 + ord('A')) + result
                col_idx = col_idx // 26 - 1
            return result

        start_col = col_to_letter(COL_FIRST_DATE)
        end_col = col_to_letter(COL_FIRST_DATE + num_cols - 1)
        range_str = f"'{SHEET_NAME}'!{start_col}1:{end_col}1"

        # Write headers
        sheets.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_str,
            valueInputOption='RAW',
            body={'values': [date_options]}
        ).execute()

        print(f"[OK] Added {num_cols} date columns to sheet: {', '.join(date_options)}")
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
            'last_game_date': last_game_date
        })

    return players


def find_player(players: List[Dict], name: str) -> Optional[Dict]:
    """Find a player by name (case-insensitive)."""
    name_lower = name.lower().strip()
    for player in players:
        if player['name'].lower() == name_lower:
            return player
    return None


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

This is a friendly reminder that you have an outstanding balance with SMAD Pickleball:

*Balance Due: ${player['balance']:.2f}*

{last_game_text}

Please send payment via Venmo to @gene-chuang or Zelle to genechuang@gmail.com at your earliest convenience.

Thanks for playing! 🏓"""

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
        message = "🏓 *SMAD Pickleball Balance Update*\n\nNo outstanding balances! Everyone is paid up! 🎉"
    else:
        total = sum(p['balance'] for p in players_with_balance)
        message = f"🏓 *SMAD Pickleball Balance Update*\n\n"
        message += f"*{len(players_with_balance)} players with outstanding balances:*\n\n"

        for player in sorted(players_with_balance, key=lambda x: x['balance'], reverse=True):
            message += f"• {player['name']}: ${player['balance']:.2f}\n"

        message += f"\n*Total Outstanding: ${total:.2f}*\n\n"
        message += "Please send payment via Venmo to @gene-chuang or Zelle to genechuang@gmail.com."

    if dry_run:
        print(f"[DRY RUN] Would send to group ({SMAD_GROUP_ID}):")
        print(message)
        return True

    try:
        response = wa_client.sending.sendMessage(SMAD_GROUP_ID, message)
        if response.code == 200:
            print(f"[OK] Balance summary sent to group")
            return True
        else:
            print(f"[ERROR] Failed to send to group: {response.data}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to send to group: {e}")
        return False


def create_availability_poll(wa_client, dry_run: bool = False) -> bool:
    """Create a poll in the group asking about availability for upcoming games."""
    if not SMAD_GROUP_ID:
        print("ERROR: SMAD_WHATSAPP_GROUP_ID not configured.")
        return False

    # Generate time slot options for the upcoming week
    today = datetime.now()
    options = []

    # Find next Tuesday, Wednesday, Friday, Saturday, Sunday with time slots
    days_of_interest = {
        1: ("Tues", "7pm-9pm"),   # Tuesday
        2: ("Wed", "7pm-9pm"),    # Wednesday
        4: ("Fri", "7pm-9pm"),    # Friday
        5: ("Sat", "10am-12pm"),  # Saturday
        6: ("Sun", "10am-12pm")   # Sunday
    }

    for i in range(1, 8):  # Next 7 days
        future_date = today + timedelta(days=i)
        weekday = future_date.weekday()

        if weekday in days_of_interest:
            day_abbrev, time_slot = days_of_interest[weekday]
            year_short = future_date.year % 100
            date_str = f"{day_abbrev} {future_date.month}/{future_date.day}/{year_short} {time_slot}"
            options.append({"optionName": date_str})

    # Add "Can't play this week" option
    options.append({"optionName": "Can't play this week"})

    poll_question = "🥒🏓🤖 When can you play pickleball this week? (Select all that apply)"

    if dry_run:
        print(f"[DRY RUN] Would create poll in group ({SMAD_GROUP_ID}):")
        print(f"Question: {poll_question}")
        print("Options:")
        for opt in options:
            print(f"  - {opt['optionName']}")
        return True

    try:
        response = wa_client.sending.sendPoll(
            SMAD_GROUP_ID,
            poll_question,
            options,
            multipleAnswers=True
        )
        if response.code == 200:
            print(f"[OK] Availability poll created in group")
            print(f"Poll ID: {response.data.get('idMessage', 'N/A')}")

            # Add date columns to the sheet (exclude "Can't play this week" option)
            date_options = [opt['optionName'] for opt in options if "can't play" not in opt['optionName'].lower()]
            try:
                sheets = get_sheets_service()
                add_poll_date_columns(sheets, date_options)
            except Exception as e:
                print(f"[WARNING] Failed to add date columns to sheet: {e}")

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

        print(f"Question: {poll['question']}")
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
                print(f"  [{date_str}] {p['question'][:60]}{'...' if len(p['question']) > 60 else ''}")

        return poll

    except Exception as e:
        print(f"[ERROR] Failed to retrieve poll: {e}")
        return None


def get_poll_votes_from_firestore(poll_id: str = None, players: List[Dict] = None) -> Optional[Dict]:
    """
    Retrieve poll votes from Firestore.

    Args:
        poll_id: Specific poll ID to retrieve. If None, gets the most recent poll.
        players: List of player dicts for name resolution.

    Returns:
        Dict with poll data and votes, or None if not found.
    """
    try:
        db = get_firestore_client()
        polls_ref = db.collection(FIRESTORE_COLLECTION)

        if poll_id:
            # Get specific poll
            poll_doc = polls_ref.document(poll_id).get()
            if not poll_doc.exists:
                return None
            polls = [(poll_doc.id, poll_doc.to_dict())]
        else:
            # Get most recent poll
            polls_query = polls_ref.order_by('created_at', direction='DESCENDING').limit(1)
            polls = [(doc.id, doc.to_dict()) for doc in polls_query.stream()]

        if not polls:
            return None

        poll_id, poll_data = polls[0]

        # Get votes subcollection
        votes_ref = polls_ref.document(poll_id).collection('votes')
        votes = {}
        for vote_doc in votes_ref.stream():
            voter_id = vote_doc.id
            vote_data = vote_doc.to_dict()
            votes[voter_id] = vote_data

        # Build phone lookup for name resolution
        phone_to_player = {}
        if players:
            for player in players:
                phone = player.get('mobile', '')
                if phone:
                    digits = ''.join(c for c in phone if c.isdigit())
                    if len(digits) == 10:
                        digits = '1' + digits
                    phone_to_player[digits] = player

        return {
            'poll_id': poll_id,
            'question': poll_data.get('question', 'Unknown'),
            'options': poll_data.get('options', []),
            'created_at': poll_data.get('created_at'),
            'votes': votes,
            'phone_to_player': phone_to_player
        }

    except Exception as e:
        print(f"[ERROR] Failed to retrieve votes from Firestore: {e}")
        return None


def show_poll_votes(poll_id: str = None, players: List[Dict] = None) -> Optional[Dict]:
    """
    Display poll votes from Firestore with player names.
    """
    poll_data = get_poll_votes_from_firestore(poll_id, players)

    if not poll_data:
        print("No poll data found in Firestore.")
        print("\nMake sure:")
        print("1. The webhook is deployed and configured")
        print("2. Votes have been cast since the webhook was set up")
        print("3. GCP_PROJECT_ID is set correctly in .env")
        return None

    phone_to_player = poll_data.get('phone_to_player', {})
    votes = poll_data.get('votes', {})
    options = poll_data.get('options', [])

    def get_name(phone: str) -> str:
        player = phone_to_player.get(phone)
        if player:
            return player['name']
        if len(phone) == 11 and phone.startswith('1'):
            return f"({phone[1:4]}) {phone[4:7]}-{phone[7:]}"
        return phone

    print(f"\n=== Poll Votes ===\n")
    print(f"Question: {poll_data['question']}")
    print(f"Poll ID: {poll_data['poll_id']}")

    if poll_data.get('created_at'):
        created = poll_data['created_at']
        if hasattr(created, 'strftime'):
            print(f"Created: {created.strftime('%Y-%m-%d %I:%M %p')}")

    print(f"Total voters: {len(votes)}")

    # Group votes by option
    option_voters = {opt: [] for opt in options}
    cannot_play_voters = []
    no_response_yet = []

    # Phrases that indicate "cannot play"
    cannot_play_phrases = ["cannot play", "can't play", "cant play", "not available", "unavailable"]

    for voter_id, vote_data in votes.items():
        selected = vote_data.get('selected', [])
        voter_name = get_name(voter_id)

        if not selected:
            # Empty selection (removed all votes)
            no_response_yet.append(voter_name)
            continue

        # Check if this is a "cannot play" response
        is_cannot_play = any(
            any(phrase in opt.lower() for phrase in cannot_play_phrases)
            for opt in selected
        )

        if is_cannot_play:
            cannot_play_voters.append(voter_name)
        else:
            for opt in selected:
                if opt in option_voters:
                    option_voters[opt].append(voter_name)
                else:
                    # Option not in our list, add it
                    option_voters[opt] = [voter_name]

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
        voted_phones = set(votes.keys())
        not_voted = []
        for player in players:
            phone = player.get('mobile', '')
            if phone:
                digits = ''.join(c for c in phone if c.isdigit())
                if len(digits) == 10:
                    digits = '1' + digits
                if digits not in voted_phones:
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
    Get the poll creation date from Firestore (most recent poll) or POLL_CREATED_DATE env var.
    Returns datetime object or None if not found.
    """
    # First try Firestore
    try:
        db = get_firestore_client()
        polls_ref = db.collection(FIRESTORE_COLLECTION)
        polls_query = polls_ref.order_by('created_at', direction='DESCENDING').limit(1)
        polls = list(polls_query.stream())
        if polls:
            poll_data = polls[0].to_dict()
            created_at = poll_data.get('created_at')
            if created_at:
                # Convert to datetime if it's a Firestore timestamp
                if hasattr(created_at, 'date'):
                    return datetime(created_at.year, created_at.month, created_at.day)
                return created_at
    except Exception as e:
        print(f"[WARNING] Could not get poll date from Firestore: {e}")

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
        print("Make sure there's a poll in Firestore or POLL_CREATED_DATE is set.")
        return 0

    print(f"\n=== Vote Reminders (Poll created: {poll_created.month}/{poll_created.day}/{poll_created.year % 100}) ===\n")

    # Find players who haven't voted (Last Voted < poll created date, or empty)
    not_voted = []
    for player in players:
        last_voted_str = player.get('last_voted', '')
        last_voted = parse_date_string(last_voted_str)

        # Player hasn't voted if:
        # 1. Last Voted is empty (None)
        # 2. Last Voted is before poll created date
        if last_voted is None or last_voted < poll_created:
            not_voted.append(player)

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

        message = f"""Hi {player['first_name']}! 🥒

This is a friendly reminder to vote in this week's SMAD pickleball availability poll.

Please open the SMAD WhatsApp group and vote so I can plan the games for this week.

Thanks! 🏓🤖"""

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


def cmd_show_votes(args):
    """Command: Show poll votes from Firestore."""
    sheets = get_sheets_service()
    players = get_player_data(sheets)
    show_poll_votes(poll_id=args.poll_id if hasattr(args, 'poll_id') else None, players=players)


def cmd_send_vote_reminders(args):
    """Command: Send reminders to players who haven't voted."""
    wa_client = get_whatsapp_client()
    sheets = get_sheets_service()
    players = get_player_data(sheets)

    send_vote_reminders(wa_client, players, dry_run=args.dry_run)


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
    # Redirect to the new Firestore-based implementation
    cmd_send_vote_reminders(args)


def main():
    parser = argparse.ArgumentParser(
        description='SMAD Pickleball WhatsApp Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list-chats                       List all chats to find group IDs
  %(prog)s show-poll                        Show the most recent poll (from WhatsApp)
  %(prog)s show-votes                       Show poll votes (from Firestore webhook)
  %(prog)s send-vote-reminders              Send DM reminders to non-voters
  %(prog)s send-balance-dm "John Doe"       Send balance reminder to John
  %(prog)s send-balance-dm all              Send reminders to all with balances
  %(prog)s send-balance-summary             Post balance summary to group
  %(prog)s create-poll                      Create weekly availability poll
  %(prog)s list-group-members               List WhatsApp group members

Environment variables:
  GREENAPI_INSTANCE_ID      GREEN-API instance ID
  GREENAPI_API_TOKEN        GREEN-API API token
  SMAD_WHATSAPP_GROUP_ID    WhatsApp group ID (e.g., 123456789@g.us)
  GCP_PROJECT_ID            Google Cloud project ID (for Firestore)

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

    # show-votes (from Firestore)
    show_votes_parser = subparsers.add_parser('show-votes',
                                               help='Show poll votes from Firestore webhook')
    show_votes_parser.add_argument('--poll-id', dest='poll_id',
                                    help='Specific poll ID (default: most recent)')
    show_votes_parser.set_defaults(func=cmd_show_votes)

    # send-vote-reminders
    vote_reminder_parser = subparsers.add_parser('send-vote-reminders',
                                                  help='Send DM reminders to players who haven\'t voted')
    vote_reminder_parser.add_argument('--poll-id', dest='poll_id',
                                       help='Specific poll ID (default: most recent)')
    vote_reminder_parser.set_defaults(func=cmd_send_vote_reminders)

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
