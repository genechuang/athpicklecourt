#!/usr/bin/env python3
"""
SMAD Pickleball Payment Management

Tracks and manages payments from SMAD group members. Supports:
- Manual payment recording
- Venmo API integration (using unofficial venmo-api library)
- Payment history and listing
- Google Sheets integration for Payment Log

Usage:
    python payments-management.py record "John Doe" 50.00 --method venmo
    python payments-management.py sync-venmo [--dry-run] [--no-thank-you]
    python payments-management.py list [--player "John Doe"] [--days 30]
    python payments-management.py history "John Doe"
    python payments-management.py setup-venmo
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

# Timezone support
try:
    import pytz
    PACIFIC_TZ = pytz.timezone('America/Los_Angeles')
except ImportError:
    PACIFIC_TZ = None

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
MAIN_SHEET_NAME = os.environ.get('SMAD_SHEET_NAME', '2026 Pickleball')
PAYMENT_LOG_SHEET_NAME = os.environ.get('PAYMENT_LOG_SHEET_NAME', 'Payment Log')
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'smad-credentials.json')
VENMO_ACCESS_TOKEN = os.environ.get('VENMO_ACCESS_TOKEN', '')

# WhatsApp Configuration
GREENAPI_INSTANCE_ID = os.environ.get('GREENAPI_INSTANCE_ID', '')
GREENAPI_API_TOKEN = os.environ.get('GREENAPI_API_TOKEN', '')
PICKLEBOT_SIGNATURE = "Picklebot🥒🏓🤖"

# Column indices for main sheet - import from smad-sheets.py (single source of truth)
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
COL_LAST_VOTED = _smad_sheets.COL_LAST_VOTED

# Payment Log sheet columns (0-based)
PL_COL_DATE = 0          # A: Date
PL_COL_PLAYER_NAME = 1   # B: Player Name
PL_COL_VENMO_USERNAME = 2  # C: Venmo Username
PL_COL_AMOUNT = 3        # D: Amount
PL_COL_METHOD = 4        # E: Method
PL_COL_TRANSACTION_ID = 5  # F: Transaction ID
PL_COL_NOTES = 6         # G: Notes
PL_COL_RECORDED_BY = 7   # H: Recorded By
PL_COL_RECORDED_AT = 8   # I: Recorded At

PAYMENT_LOG_HEADERS = ['Date', 'Player Name', 'Venmo Username', 'Amount', 'Method', 'Transaction ID', 'Notes', 'Recorded By', 'Recorded At']

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def get_sheets_service():
    """Initialize and return Google Sheets API service."""
    if os.path.exists(CREDENTIALS_FILE):
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    elif os.environ.get('GOOGLE_CREDENTIALS_JSON'):
        creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS_JSON'])
        creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    else:
        print(f"ERROR: Credentials file '{CREDENTIALS_FILE}' not found.")
        print("Either place the service account JSON file in this directory,")
        print("or set GOOGLE_CREDENTIALS_JSON environment variable.")
        sys.exit(1)

    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()


def col_index_to_letter(index: int) -> str:
    """Convert 0-based column index to letter (0=A, 1=B, 26=AA, etc.)."""
    result = ""
    while index >= 0:
        result = chr(index % 26 + ord('A')) + result
        index = index // 26 - 1
    return result


def get_sheet_data(sheets, sheet_name: str, range_name: str = None) -> List[List]:
    """Fetch data from a specific sheet."""
    if range_name:
        full_range = f"'{sheet_name}'!{range_name}"
    else:
        full_range = f"'{sheet_name}'"

    try:
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=full_range
        ).execute()
        return result.get('values', [])
    except HttpError as e:
        if 'Unable to parse range' in str(e) or 'not found' in str(e).lower():
            return []  # Sheet doesn't exist
        print(f"ERROR: Failed to fetch sheet data: {e}")
        sys.exit(1)


def append_to_sheet(sheets, sheet_name: str, values: List[List]):
    """Append rows to a sheet."""
    range_name = f"'{sheet_name}'!A:H"

    try:
        body = {'values': values}
        result = sheets.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        return result
    except HttpError as e:
        print(f"ERROR: Failed to append to sheet: {e}")
        return None


def update_sheet_cell(sheets, sheet_name: str, cell_ref: str, value):
    """Update a single cell in a sheet."""
    range_name = f"'{sheet_name}'!{cell_ref}"

    try:
        body = {'values': [[value]]}
        result = sheets.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        return result
    except HttpError as e:
        print(f"ERROR: Failed to update cell: {e}")
        return None


def ensure_payment_log_sheet(sheets):
    """Ensure Payment Log sheet exists with proper headers."""
    data = get_sheet_data(sheets, PAYMENT_LOG_SHEET_NAME)

    if not data:
        # Sheet might not exist or is empty, try to create headers
        print(f"[INFO] Initializing '{PAYMENT_LOG_SHEET_NAME}' sheet with headers...")
        result = append_to_sheet(sheets, PAYMENT_LOG_SHEET_NAME, [PAYMENT_LOG_HEADERS])
        if result:
            print(f"[OK] Created headers in '{PAYMENT_LOG_SHEET_NAME}'")
        else:
            print(f"[WARN] Could not create headers. Please create '{PAYMENT_LOG_SHEET_NAME}' sheet manually.")
        return True

    # Check if first row is headers
    if data[0] != PAYMENT_LOG_HEADERS:
        print(f"[WARN] Payment Log headers don't match expected format.")
        print(f"  Expected: {PAYMENT_LOG_HEADERS}")
        print(f"  Found: {data[0]}")

    return True


def find_player_by_name(data: List[List], player_name: str) -> Optional[Tuple[int, str, str]]:
    """Find player row by full name. Returns (row_index, first_name, last_name) or None."""
    name_parts = player_name.strip().split(' ', 1)
    if len(name_parts) < 2:
        # Try to match first name only
        first_name_lower = name_parts[0].lower().strip()
        for i, row in enumerate(data[1:], start=1):
            if len(row) >= 2 and row[COL_FIRST_NAME].lower().strip() == first_name_lower:
                return (i, row[COL_FIRST_NAME], row[COL_LAST_NAME])
        return None

    first_name_lower = name_parts[0].lower().strip()
    last_name_lower = name_parts[1].lower().strip()

    for i, row in enumerate(data[1:], start=1):
        if len(row) >= 2:
            if row[COL_FIRST_NAME].lower().strip() == first_name_lower and \
               row[COL_LAST_NAME].lower().strip() == last_name_lower:
                return (i, row[COL_FIRST_NAME], row[COL_LAST_NAME])
    return None


def find_player_by_venmo(data: List[List], venmo_username: str) -> Optional[Tuple[int, str, str]]:
    """Find player row by Venmo username. Returns (row_index, first_name, last_name) or None."""
    # Normalize venmo username (remove @ if present, lowercase)
    venmo_normalized = venmo_username.lower().strip().lstrip('@')

    for i, row in enumerate(data[1:], start=1):
        if len(row) > COL_VENMO:
            row_venmo = row[COL_VENMO].lower().strip().lstrip('@') if row[COL_VENMO] else ''
            if row_venmo == venmo_normalized:
                return (i, row[COL_FIRST_NAME], row[COL_LAST_NAME])
    return None


def get_existing_transaction_ids(sheets) -> set:
    """Get set of existing transaction IDs from Payment Log to avoid duplicates."""
    data = get_sheet_data(sheets, PAYMENT_LOG_SHEET_NAME)
    if not data or len(data) < 2:
        return set()

    transaction_ids = set()
    for row in data[1:]:
        if len(row) > PL_COL_TRANSACTION_ID and row[PL_COL_TRANSACTION_ID]:
            transaction_ids.add(row[PL_COL_TRANSACTION_ID].strip())

    return transaction_ids


def record_payment(sheets, player_name: str, amount: float, method: str = 'venmo',
                   transaction_id: str = '', notes: str = '', recorded_by: str = 'manual',
                   payment_date: str = None, venmo_username: str = '',
                   _cached_main_data: List[List] = None,
                   _cached_existing_ids: set = None, _skip_ensure_sheet: bool = False) -> bool:
    """
    Record a payment in the Payment Log sheet and update Last Paid in main sheet.

    Args:
        sheets: Google Sheets service
        player_name: Full name of player
        amount: Payment amount
        method: Payment method (venmo, zelle, cash, check)
        transaction_id: Optional transaction ID
        notes: Optional notes
        recorded_by: Who recorded this (manual, venmo-sync, etc.)
        payment_date: Payment date (MM/DD/YYYY format), defaults to today
        venmo_username: Venmo username (e.g., @john-doe) for matching
        _cached_main_data: Optional cached main sheet data (for batch operations)
        _cached_existing_ids: Optional cached existing transaction IDs (for batch operations)
        _skip_ensure_sheet: Skip the ensure_payment_log_sheet call (for batch operations)

    Returns:
        True if successful, False otherwise
    """
    # Get main sheet data to validate player (use cache if provided)
    if _cached_main_data is not None:
        main_data = _cached_main_data
    else:
        main_data = get_sheet_data(sheets, MAIN_SHEET_NAME)
        if not main_data:
            print("ERROR: Could not fetch main sheet data")
            return False

    # Find player - try by Venmo username first if provided, then by name
    player_info = None
    if venmo_username:
        player_info = find_player_by_venmo(main_data, venmo_username)
    if not player_info:
        player_info = find_player_by_name(main_data, player_name)

    if not player_info:
        print(f"ERROR: Player '{player_name}' not found in spreadsheet")
        print("Available players:")
        for row in main_data[1:]:
            if len(row) >= 2:
                print(f"  - {row[COL_FIRST_NAME]} {row[COL_LAST_NAME]}")
        return False

    _, first_name, last_name = player_info
    full_name = f"{first_name} {last_name}"

    # Prepare payment date (MM/DD/YYYY format)
    if payment_date:
        date_str = payment_date
    else:
        today = datetime.now()
        date_str = f"{today.month:02d}/{today.day:02d}/{today.year}"

    # Prepare recorded timestamp
    now = datetime.now()
    recorded_at = now.strftime("%Y-%m-%d %H:%M:%S")

    # Ensure Payment Log sheet exists (skip if caller already did this)
    if not _skip_ensure_sheet:
        ensure_payment_log_sheet(sheets)

    # Check for duplicate transaction ID (use cache if provided)
    if transaction_id:
        if _cached_existing_ids is not None:
            existing_ids = _cached_existing_ids
        else:
            existing_ids = get_existing_transaction_ids(sheets)
        if transaction_id in existing_ids:
            print(f"[WARN] Transaction ID '{transaction_id}' already exists, skipping")
            return False

    # For Zelle payments without a venmo_username, construct "zelle-LastName"
    if method.lower() == 'zelle' and not venmo_username:
        # Extract last name from full_name (last token after splitting by space)
        name_parts = full_name.split()
        if name_parts:
            last_name_part = name_parts[-1]
            venmo_username = f"zelle-{last_name_part}"

    # Append to Payment Log
    payment_row = [
        date_str,           # Date
        full_name,          # Player Name
        venmo_username,     # Venmo Username (or zelle-LastName for Zelle payments)
        f"${amount:.2f}",   # Amount
        method,             # Method
        transaction_id,     # Transaction ID
        notes,              # Notes
        recorded_by,        # Recorded By
        recorded_at         # Recorded At
    ]

    result = append_to_sheet(sheets, PAYMENT_LOG_SHEET_NAME, [payment_row])
    if not result:
        print("ERROR: Failed to append payment to log")
        return False

    print(f"[OK] Recorded payment: {full_name} - ${amount:.2f} ({method})")
    return True


def list_payments(sheets, player_name: str = None, days: int = None):
    """List payments from the Payment Log sheet."""
    data = get_sheet_data(sheets, PAYMENT_LOG_SHEET_NAME)

    if not data or len(data) < 2:
        print("No payments found in Payment Log.")
        return

    headers = data[0]
    payments = data[1:]

    # Filter by player name if specified
    if player_name:
        player_name_lower = player_name.lower().strip()
        payments = [p for p in payments if len(p) > PL_COL_PLAYER_NAME and
                    player_name_lower in p[PL_COL_PLAYER_NAME].lower()]

    # Filter by days if specified
    if days:
        cutoff_date = datetime.now() - timedelta(days=days)
        filtered_payments = []
        for p in payments:
            if len(p) > PL_COL_DATE and p[PL_COL_DATE]:
                try:
                    # Parse date (M/D/YY format)
                    parts = p[PL_COL_DATE].split('/')
                    if len(parts) == 3:
                        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
                        if year < 100:
                            year += 2000
                        payment_date = datetime(year, month, day)
                        if payment_date >= cutoff_date:
                            filtered_payments.append(p)
                except (ValueError, IndexError):
                    filtered_payments.append(p)  # Include if can't parse date
        payments = filtered_payments

    if not payments:
        print("No payments match the filter criteria.")
        return

    # Display payments
    print(f"\n=== Payment Log ({len(payments)} payments) ===\n")
    print(f"{'Date':<12} {'Player':<20} {'Amount':>10} {'Method':<10} {'Transaction ID':<20}")
    print("-" * 75)

    total = 0.0
    for p in payments:
        date = p[PL_COL_DATE] if len(p) > PL_COL_DATE else ""
        name = p[PL_COL_PLAYER_NAME] if len(p) > PL_COL_PLAYER_NAME else ""
        amount_str = p[PL_COL_AMOUNT] if len(p) > PL_COL_AMOUNT else ""
        method = p[PL_COL_METHOD] if len(p) > PL_COL_METHOD else ""
        txn_id = p[PL_COL_TRANSACTION_ID] if len(p) > PL_COL_TRANSACTION_ID else ""

        # Parse amount for total
        try:
            amount = float(amount_str.replace('$', '').replace(',', '').strip() or '0')
            total += amount
        except ValueError:
            amount = 0

        # Truncate long transaction IDs
        if len(txn_id) > 18:
            txn_id = txn_id[:15] + "..."

        print(f"{date:<12} {name:<20} {amount_str:>10} {method:<10} {txn_id:<20}")

    print("-" * 75)
    print(f"{'Total:':<33} ${total:>9.2f}")
    print()


def show_payment_history(sheets, player_name: str):
    """Show payment history for a specific player."""
    list_payments(sheets, player_name=player_name)


def get_whatsapp_client():
    """Initialize and return WhatsApp GREEN-API client."""
    if not GREENAPI_INSTANCE_ID or not GREENAPI_API_TOKEN:
        return None

    try:
        from whatsapp_api_client_python import API
        return API.GreenAPI(GREENAPI_INSTANCE_ID, GREENAPI_API_TOKEN)
    except (ImportError, Exception):
        return None


def format_phone_for_whatsapp(phone: str) -> str:
    """Convert phone number to WhatsApp format (digits only + @c.us)."""
    if not phone:
        return ''
    # Remove all non-digit characters
    digits = ''.join(c for c in phone if c.isdigit())
    if not digits:
        return ''
    # WhatsApp format: phone@c.us
    return f"{digits}@c.us"


def send_whatsapp_thank_you(wa_client, player_name: str, first_name: str, mobile: str, amount: float) -> bool:
    """
    Send a WhatsApp thank you DM to a player for their payment.

    Args:
        wa_client: GREEN-API client
        player_name: Full player name
        first_name: Player's first name
        mobile: Player's mobile number
        amount: Payment amount

    Returns:
        True if successful, False otherwise
    """
    if not wa_client:
        return False

    phone_id = format_phone_for_whatsapp(mobile)
    if not phone_id:
        print(f"  [SKIP WhatsApp] {player_name} - no valid phone number")
        return False

    message = f"""Hi {first_name}!

Thank you for your payment of *${amount:.2f}*!

Your payment has been recorded.

Thanks,
{PICKLEBOT_SIGNATURE}"""

    try:
        response = wa_client.sending.sendMessage(phone_id, message)
        if response.code == 200:
            print(f"  [OK WhatsApp] Sent thank you to {player_name} ({phone_id})")
            return True
        else:
            print(f"  [WARN WhatsApp] Failed to send to {player_name}: {response.data}")
            return False
    except Exception as e:
        print(f"  [WARN WhatsApp] Failed to send to {player_name}: {e}")
        return False


def setup_venmo_token():
    """Interactive setup for Venmo access token."""
    print("\n=== Venmo Access Token Setup ===\n")
    print("This uses the unofficial venmo-api library to get an access token.")
    print("You'll need to complete 2FA verification.\n")

    try:
        from venmo_api import Client
    except ImportError:
        print("ERROR: venmo-api library not installed.")
        print("Run: pip install venmo-api")
        return False

    print("Enter your Venmo credentials:")
    username = input("  Venmo username or email: ").strip()
    password = input("  Venmo password: ").strip()

    if not username or not password:
        print("ERROR: Username and password are required")
        return False

    try:
        # This will trigger 2FA
        access_token = Client.get_access_token(username=username, password=password)

        print("\n[OK] Successfully obtained access token!")
        print("\nAdd this to your .env file:")
        print(f"VENMO_ACCESS_TOKEN={access_token}")
        print("\nNote: This token never expires unless you revoke it.")
        return True
    except Exception as e:
        print(f"\nERROR: Failed to get access token: {e}")
        return False


def sync_venmo_payments(sheets, dry_run: bool = False, limit: int = 50, send_thank_you: bool = True):
    """
    Sync payments from Venmo to the Payment Log sheet.

    Matches Venmo senders by username to the Venmo column in the main sheet.
    Optionally sends WhatsApp thank you messages to payers.

    Args:
        sheets: Google Sheets service
        dry_run: If True, don't record payments or send messages
        limit: Max transactions to fetch
        send_thank_you: If True, send WhatsApp thank you DMs to payers
    """
    if not VENMO_ACCESS_TOKEN:
        print("ERROR: VENMO_ACCESS_TOKEN not set.")
        print("Run: python payments-management.py setup-venmo")
        return False

    try:
        from venmo_api import Client
    except ImportError:
        print("ERROR: venmo-api library not installed.")
        print("Run: pip install venmo-api")
        return False

    print("[INFO] Connecting to Venmo API...")

    try:
        client = Client(access_token=VENMO_ACCESS_TOKEN)
        my_profile = client.my_profile()
        print(f"[OK] Connected as: {my_profile.username}")
    except Exception as e:
        print(f"ERROR: Failed to connect to Venmo: {e}")
        return False

    # Get main sheet data for matching
    main_data = get_sheet_data(sheets, MAIN_SHEET_NAME)
    if not main_data:
        print("ERROR: Could not fetch main sheet data")
        return False

    # Get existing transaction IDs and ensure Payment Log sheet exists
    ensure_payment_log_sheet(sheets)
    existing_ids = get_existing_transaction_ids(sheets)
    print(f"[INFO] Found {len(existing_ids)} existing transactions in Payment Log")

    # Fetch transactions
    print(f"[INFO] Fetching up to {limit} recent transactions...")

    try:
        transactions = client.user.get_user_transactions(user_id=my_profile.id, limit=limit)
    except Exception as e:
        print(f"ERROR: Failed to fetch transactions: {e}")
        return False

    if not transactions:
        print("No transactions found.")
        return True

    print(f"[INFO] Found {len(transactions)} transactions")

    # Process transactions (only payments TO us, not requests or payments from us)
    payments_recorded = 0
    payments_skipped = 0
    payments_unmatched = 0
    recorded_payment_details = []  # Track (player_name, first_name, mobile, amount) for thank you messages

    for txn in transactions:
        # Skip if already recorded
        txn_id = str(txn.id)
        if txn_id in existing_ids:
            payments_skipped += 1
            continue

        # Determine payment direction
        # In venmo-api, transactions have 'actor' (who initiated) and 'target' (recipient)
        # For a payment: actor pays target
        # For a charge: actor requests from target

        # Get actor and target info
        actor = txn.actor if hasattr(txn, 'actor') else None
        target = txn.target if hasattr(txn, 'target') else None

        if not actor or not target:
            continue

        # Get amount (positive = payment received, negative = payment sent)
        amount = getattr(txn, 'amount', 0)
        if not amount:
            continue

        # Determine if we received this payment
        # target is the User who receives the payment
        target_id = getattr(target, 'id', None)
        actor_id = getattr(actor, 'id', None)

        if target_id == my_profile.id:
            # We are the target - someone paid us
            payer = actor
        elif actor_id == my_profile.id and amount < 0:
            # We paid someone (amount is negative from our perspective)
            continue  # Skip outgoing payments
        else:
            # Other transaction type
            continue

        # Make amount positive for recording
        amount = abs(amount)

        if not payer or amount <= 0:
            continue

        # Match payer to SMAD player by Venmo username
        payer_username = payer.username
        player_info = find_player_by_venmo(main_data, payer_username)

        if not player_info:
            print(f"  [UNMATCHED] @{payer_username}: ${amount:.2f} - '{txn.note or 'No note'}'")
            payments_unmatched += 1
            continue

        row_index, first_name, last_name = player_info
        full_name = f"{first_name} {last_name}"

        # Get mobile number for thank you message (if available)
        player_row = main_data[row_index]
        mobile = player_row[COL_MOBILE] if len(player_row) > COL_MOBILE else ''

        # Parse transaction date (Unix timestamp in seconds) - MM/DD/YYYY format
        # Venmo API returns timestamps that appear to be local time stored as UTC
        # (i.e., 8 hours ahead of actual Pacific Time), so we interpret directly as local
        txn_timestamp = txn.date_completed or txn.date_created
        if txn_timestamp:
            # Interpret timestamp directly as local time (Venmo quirk)
            txn_date = datetime.fromtimestamp(txn_timestamp)
            # Subtract the UTC offset to get actual Pacific Time
            # This accounts for Venmo storing local time as if it were UTC
            if PACIFIC_TZ:
                # Get the PT offset for the transaction date (handles DST correctly)
                # Localize the naive datetime to PT to get the correct offset for that date
                txn_date_pt = PACIFIC_TZ.localize(txn_date)
                utc_offset_hours = txn_date_pt.utcoffset().total_seconds() / 3600
                txn_date = txn_date + timedelta(hours=utc_offset_hours)
            else:
                # Fallback: subtract 8 hours for PST
                txn_date = txn_date - timedelta(hours=8)
            date_str = f"{txn_date.month:02d}/{txn_date.day:02d}/{txn_date.year}"
        else:
            today = datetime.now()
            date_str = f"{today.month:02d}/{today.day:02d}/{today.year}"

        note = txn.note or ''

        if dry_run:
            print(f"  [DRY RUN] Would record: {full_name} - ${amount:.2f} ({date_str}) - @{payer_username}")
            payments_recorded += 1
        else:
            success = record_payment(
                sheets,
                player_name=full_name,
                amount=amount,
                method='venmo',
                transaction_id=txn_id,
                notes=note[:100],  # Truncate long notes
                recorded_by='venmo-sync',
                payment_date=date_str,
                venmo_username=payer_username,
                _cached_main_data=main_data,
                _cached_existing_ids=existing_ids,
                _skip_ensure_sheet=True
            )
            if success:
                payments_recorded += 1
                # Add to existing_ids to prevent duplicates within this batch
                existing_ids.add(txn_id)
                # Track for thank you message
                recorded_payment_details.append((full_name, first_name, mobile, amount))
            else:
                print(f"  [ERROR] Failed to record: {full_name} - ${amount:.2f}")

    # Summary
    print(f"\n=== Venmo Sync Summary ===")
    print(f"  Recorded: {payments_recorded}")
    print(f"  Skipped (already exists): {payments_skipped}")
    print(f"  Unmatched (no Venmo in sheet): {payments_unmatched}")

    if payments_unmatched > 0:
        print(f"\n[TIP] To match unmatched payments, add the payer's Venmo username")
        print(f"      (e.g., @john-doe) to their row in the Venmo column (Column E).")

    # Send WhatsApp thank you messages to newly recorded payments
    if not dry_run and send_thank_you and recorded_payment_details:
        wa_client = get_whatsapp_client()
        if wa_client:
            print(f"\n=== Sending Thank You Messages ===")
            thank_you_sent = 0
            for player_name, first_name, mobile, amount in recorded_payment_details:
                if send_whatsapp_thank_you(wa_client, player_name, first_name, mobile, amount):
                    thank_you_sent += 1
            print(f"[DONE] Sent {thank_you_sent}/{len(recorded_payment_details)} thank you messages")
        else:
            print(f"\n[INFO] WhatsApp not configured - skipping thank you messages")
            print(f"       Set GREENAPI_INSTANCE_ID and GREENAPI_API_TOKEN to enable")
    elif not dry_run and not send_thank_you and recorded_payment_details:
        print(f"\n[INFO] Skipping thank you messages (--no-thank-you flag used)")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='SMAD Pickleball Payment Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s record "John Doe" 50.00 --method venmo
  %(prog)s record "Jane Smith" 25.00 --date "1/15/26" --notes "Cash at game"
  %(prog)s sync-venmo
  %(prog)s sync-venmo --dry-run
  %(prog)s list
  %(prog)s list --player "John Doe" --days 30
  %(prog)s history "John Doe"
  %(prog)s setup-venmo

Environment variables:
  SMAD_SPREADSHEET_ID      Google Sheets ID
  SMAD_SHEET_NAME          Main sheet name (default: 2026 Pickleball)
  PAYMENT_LOG_SHEET_NAME   Payment log sheet name (default: Payment Log)
  GOOGLE_CREDENTIALS_FILE  Path to service account JSON
  VENMO_ACCESS_TOKEN       Venmo API access token (for sync-venmo)
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # record
    record_parser = subparsers.add_parser('record', help='Record a payment')
    record_parser.add_argument('player_name', help='Player name (e.g., "John Doe")')
    record_parser.add_argument('amount', type=float, help='Payment amount')
    record_parser.add_argument('--method', default='venmo',
                               choices=['venmo', 'zelle', 'cash', 'check'],
                               help='Payment method (default: venmo)')
    record_parser.add_argument('--date', help='Payment date (M/D/YY format)')
    record_parser.add_argument('--notes', default='', help='Optional notes')
    record_parser.add_argument('--transaction-id', default='', help='Transaction ID')

    # sync-venmo
    sync_parser = subparsers.add_parser('sync-venmo', help='Sync payments from Venmo')
    sync_parser.add_argument('--dry-run', action='store_true',
                             help='Show what would be synced without recording')
    sync_parser.add_argument('--limit', type=int, default=50,
                             help='Max transactions to fetch (default: 50)')
    sync_parser.add_argument('--no-thank-you', action='store_true',
                             help='Skip sending WhatsApp thank you messages')

    # list
    list_parser = subparsers.add_parser('list', help='List payments')
    list_parser.add_argument('--player', help='Filter by player name')
    list_parser.add_argument('--days', type=int, help='Filter to last N days')

    # history
    history_parser = subparsers.add_parser('history', help='Show payment history for a player')
    history_parser.add_argument('player_name', help='Player name')

    # setup-venmo
    subparsers.add_parser('setup-venmo', help='Set up Venmo access token')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Handle setup-venmo separately (doesn't need sheets)
    if args.command == 'setup-venmo':
        setup_venmo_token()
        sys.exit(0)

    # Initialize Google Sheets service
    sheets = get_sheets_service()

    # Execute command
    if args.command == 'record':
        record_payment(
            sheets,
            args.player_name,
            args.amount,
            method=args.method,
            transaction_id=args.transaction_id,
            notes=args.notes,
            payment_date=args.date
        )
    elif args.command == 'sync-venmo':
        sync_venmo_payments(sheets, dry_run=args.dry_run, limit=args.limit, send_thank_you=not args.no_thank_you)
    elif args.command == 'list':
        list_payments(sheets, player_name=args.player, days=args.days)
    elif args.command == 'history':
        show_payment_history(sheets, args.player_name)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
