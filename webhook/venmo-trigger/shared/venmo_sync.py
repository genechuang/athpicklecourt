"""
Shared Venmo sync logic for SMAD Pickleball Payment Management.

This module can be used by:
- payments-management.py CLI tool
- Cloud Function triggered by email forwarding
- GitHub Actions workflows

Usage:
    from webhook.shared.venmo_sync import sync_venmo_to_sheet

    recorded, skipped, unmatched = sync_venmo_to_sheet(
        venmo_access_token="...",
        spreadsheet_id="...",
        google_credentials=creds_json_or_file
    )
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

# Timezone support
try:
    import pytz
    PACIFIC_TZ = pytz.timezone('America/Los_Angeles')
except ImportError:
    PACIFIC_TZ = None

# Google Sheets API
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Venmo API
from venmo_api import Client

# Configuration constants
DEFAULT_MAIN_SHEET_NAME = '2026 Pickleball'
DEFAULT_PAYMENT_LOG_SHEET_NAME = 'Payment Log'

# Column indices for main sheet (match smad-sheets.py)
COL_FIRST_NAME = 0  # A
COL_LAST_NAME = 1   # B
COL_VACATION = 2    # C
COL_EMAIL = 3       # D
COL_MOBILE = 4      # E
COL_VENMO = 5       # F
COL_ZELLE = 6       # G
COL_BALANCE = 7     # H
COL_PAID = 8        # I
COL_INVOICED = 9    # J
COL_2026_HOURS = 10 # K
COL_LAST_VOTED = 11 # L

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

PICKLEBOT_SIGNATURE = "Picklebot🥒🏓🤖"


def format_phone_for_whatsapp(phone: str) -> str:
    """Convert phone number to WhatsApp format (digits only + @c.us)."""
    if not phone:
        return ''
    digits = ''.join(c for c in phone if c.isdigit())
    if not digits:
        return ''
    return f"{digits}@c.us"


def get_whatsapp_client(instance_id: str, api_token: str):
    """Initialize and return WhatsApp GREEN-API client."""
    if not instance_id or not api_token:
        return None
    try:
        from whatsapp_api_client_python import API
        return API.GreenAPI(instance_id, api_token)
    except (ImportError, Exception):
        return None


def send_whatsapp_thank_you(wa_client, player_name: str, first_name: str, mobile: str, amount: float, balance: float) -> bool:
    """Send a WhatsApp thank you DM to a player for their payment."""
    if not wa_client:
        return False

    phone_id = format_phone_for_whatsapp(mobile)
    if not phone_id:
        print(f"  [SKIP WhatsApp] {player_name} - no valid phone number")
        return False

    message = f"""Hi {first_name}!

Thank you for your payment of *${amount:.2f}*!

Your balance is now: *${balance:.2f}*

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


def get_sheets_service(google_credentials):
    """
    Initialize and return Google Sheets API service.

    Args:
        google_credentials: Either:
            - Path to service account JSON file (str)
            - Service account JSON as dict
            - Service account JSON as string
    """
    if isinstance(google_credentials, str):
        if os.path.exists(google_credentials):
            # File path
            creds = Credentials.from_service_account_file(google_credentials, scopes=SCOPES)
        else:
            # JSON string
            import json
            creds_dict = json.loads(google_credentials)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    elif isinstance(google_credentials, dict):
        # JSON dict
        creds = Credentials.from_service_account_info(google_credentials, scopes=SCOPES)
    else:
        raise ValueError("google_credentials must be file path, JSON string, or dict")

    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()


def get_sheet_data(sheets, spreadsheet_id: str, sheet_name: str, range_name: str = None) -> List[List]:
    """Fetch data from a specific sheet."""
    if range_name:
        full_range = f"'{sheet_name}'!{range_name}"
    else:
        full_range = f"'{sheet_name}'"

    try:
        result = sheets.values().get(
            spreadsheetId=spreadsheet_id,
            range=full_range
        ).execute()
        return result.get('values', [])
    except HttpError as e:
        if 'Unable to parse range' in str(e) or 'not found' in str(e).lower():
            return []  # Sheet doesn't exist
        raise


def append_to_sheet(sheets, spreadsheet_id: str, sheet_name: str, values: List[List]):
    """Append rows to a sheet."""
    range_name = f"'{sheet_name}'!A:H"

    try:
        body = {'values': values}
        result = sheets.values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        return result
    except HttpError as e:
        print(f"ERROR: Failed to append to sheet: {e}")
        return None


def ensure_payment_log_sheet(sheets, spreadsheet_id: str, sheet_name: str):
    """Ensure Payment Log sheet exists with proper headers."""
    data = get_sheet_data(sheets, spreadsheet_id, sheet_name)

    if not data:
        # Sheet might not exist or is empty, try to create headers
        print(f"[INFO] Initializing '{sheet_name}' sheet with headers...")
        result = append_to_sheet(sheets, spreadsheet_id, sheet_name, [PAYMENT_LOG_HEADERS])
        if result:
            print(f"[OK] Created headers in '{sheet_name}'")
        else:
            print(f"[WARN] Could not create headers. Please create '{sheet_name}' sheet manually.")
        return True

    # Check if first row is headers
    if data[0] != PAYMENT_LOG_HEADERS:
        print(f"[WARN] Payment Log headers don't match expected format.")
        print(f"  Expected: {PAYMENT_LOG_HEADERS}")
        print(f"  Found: {data[0]}")

    return True


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


def get_existing_transaction_ids(sheets, spreadsheet_id: str, sheet_name: str) -> set:
    """Get set of existing transaction IDs from Payment Log to avoid duplicates."""
    data = get_sheet_data(sheets, spreadsheet_id, sheet_name)
    if not data or len(data) < 2:
        return set()

    transaction_ids = set()
    for row in data[1:]:
        if len(row) > PL_COL_TRANSACTION_ID and row[PL_COL_TRANSACTION_ID]:
            transaction_ids.add(row[PL_COL_TRANSACTION_ID].strip())

    return transaction_ids


def record_payment(sheets, spreadsheet_id: str, payment_log_sheet: str, main_data: List[List],
                   player_name: str, amount: float, venmo_username: str,
                   transaction_id: str, payment_date: str, note: str,
                   existing_ids: set) -> bool:
    """
    Record a single payment to Payment Log.

    Returns True if successful, False if duplicate or error.
    """
    # Check for duplicate
    if transaction_id in existing_ids:
        return False

    # Find player by Venmo username
    player_info = find_player_by_venmo(main_data, venmo_username)
    if not player_info:
        return False

    _, first_name, last_name = player_info
    full_name = f"{first_name} {last_name}"

    # Prepare recorded timestamp
    now = datetime.now()
    recorded_at = now.strftime("%Y-%m-%d %H:%M:%S")

    # Append to Payment Log
    payment_row = [
        payment_date,           # Date
        full_name,              # Player Name
        venmo_username,         # Venmo Username
        f"${amount:.2f}",       # Amount
        'venmo',                # Method
        transaction_id,         # Transaction ID
        note[:100],             # Notes (truncated)
        'venmo-sync',           # Recorded By
        recorded_at             # Recorded At
    ]

    result = append_to_sheet(sheets, spreadsheet_id, payment_log_sheet, [payment_row])
    if not result:
        return False

    print(f"[OK] Recorded payment: {full_name} - ${amount:.2f} (venmo)")
    return True


def sync_venmo_to_sheet(
    venmo_access_token: str,
    spreadsheet_id: str,
    google_credentials,
    main_sheet_name: str = DEFAULT_MAIN_SHEET_NAME,
    payment_log_sheet_name: str = DEFAULT_PAYMENT_LOG_SHEET_NAME,
    limit: int = 50,
    dry_run: bool = False,
    greenapi_instance_id: str = '',
    greenapi_api_token: str = ''
) -> Tuple[int, int, int]:
    """
    Sync Venmo payments to Google Sheets Payment Log.

    Args:
        venmo_access_token: Venmo API access token
        spreadsheet_id: Google Sheets ID
        google_credentials: Google service account credentials (file path, JSON string, or dict)
        main_sheet_name: Name of main sheet with player data
        payment_log_sheet_name: Name of payment log sheet
        limit: Max number of transactions to fetch
        dry_run: If True, don't actually record payments

    Returns:
        Tuple of (recorded_count, skipped_count, unmatched_count)
    """
    # Connect to Venmo
    print("[INFO] Connecting to Venmo API...")
    try:
        client = Client(access_token=venmo_access_token)
        my_profile = client.my_profile()
        print(f"[OK] Connected as: {my_profile.username}")
    except Exception as e:
        print(f"ERROR: Failed to connect to Venmo: {e}")
        raise

    # Connect to Google Sheets
    sheets = get_sheets_service(google_credentials)

    # Get main sheet data for matching
    main_data = get_sheet_data(sheets, spreadsheet_id, main_sheet_name)
    if not main_data:
        raise ValueError(f"Could not fetch main sheet data from '{main_sheet_name}'")

    # Get existing transaction IDs and ensure Payment Log sheet exists
    ensure_payment_log_sheet(sheets, spreadsheet_id, payment_log_sheet_name)
    existing_ids = get_existing_transaction_ids(sheets, spreadsheet_id, payment_log_sheet_name)
    print(f"[INFO] Found {len(existing_ids)} existing transactions in Payment Log")

    # Fetch transactions
    print(f"[INFO] Fetching up to {limit} recent transactions...")
    try:
        transactions = client.user.get_user_transactions(user_id=my_profile.id, limit=limit)
    except Exception as e:
        print(f"ERROR: Failed to fetch transactions: {e}")
        raise

    if not transactions:
        print("No transactions found.")
        return (0, 0, 0)

    print(f"[INFO] Found {len(transactions)} transactions")

    # Process transactions
    payments_recorded = 0
    payments_skipped = 0
    payments_unmatched = 0
    recorded_payment_details = []  # (full_name, first_name, mobile, amount, balance)

    for txn in transactions:
        # Skip if already recorded
        txn_id = str(txn.id)
        if txn_id in existing_ids:
            payments_skipped += 1
            continue

        # Get actor and target info
        actor = txn.actor if hasattr(txn, 'actor') else None
        target = txn.target if hasattr(txn, 'target') else None

        if not actor or not target:
            continue

        # Get amount
        amount = getattr(txn, 'amount', 0)
        if not amount:
            continue

        # Determine if we received this payment
        target_id = getattr(target, 'id', None)
        actor_id = getattr(actor, 'id', None)

        if target_id == my_profile.id:
            # We are the target - someone paid us
            payer = actor
        elif actor_id == my_profile.id and amount < 0:
            # We paid someone (skip outgoing payments)
            continue
        else:
            # Other transaction type
            continue

        # Make amount positive
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

        # Parse transaction date (MM/DD/YYYY format)
        txn_timestamp = txn.date_completed or txn.date_created
        if txn_timestamp:
            # Interpret timestamp directly as local time (Venmo quirk)
            txn_date = datetime.fromtimestamp(txn_timestamp)
            # Subtract the UTC offset to get actual Pacific Time
            if PACIFIC_TZ:
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
                spreadsheet_id,
                payment_log_sheet_name,
                main_data,
                full_name,
                amount,
                payer_username,
                txn_id,
                date_str,
                note,
                existing_ids
            )
            if success:
                payments_recorded += 1
                # Add to existing_ids to prevent duplicates within this batch
                existing_ids.add(txn_id)
                # Collect details for WhatsApp thank you (balance fetched later after sheet recalculates)
                player_row = main_data[row_index] if row_index < len(main_data) else []
                mobile = player_row[COL_MOBILE] if len(player_row) > COL_MOBILE else ''
                recorded_payment_details.append((full_name, first_name, mobile, amount, row_index))
            else:
                print(f"  [SKIP] {full_name} - ${amount:.2f} (duplicate)")
                payments_skipped += 1

    # Summary
    print(f"\n=== Venmo Sync Summary ===")
    print(f"  Recorded: {payments_recorded}")
    print(f"  Skipped (already exists): {payments_skipped}")
    print(f"  Unmatched (no Venmo in sheet): {payments_unmatched}")

    if payments_unmatched > 0:
        print(f"\n[TIP] To match unmatched payments, add the payer's Venmo username")
        print(f"      (e.g., @john-doe) to their row in the Venmo column (Column F).")

    # Send WhatsApp thank you messages
    if not dry_run and recorded_payment_details and (greenapi_instance_id and greenapi_api_token):
        wa_client = get_whatsapp_client(greenapi_instance_id, greenapi_api_token)
        if wa_client:
            # Re-read main sheet to get updated balances (formulas recalculate after payment recorded)
            updated_data = get_sheet_data(sheets, spreadsheet_id, main_sheet_name)
            print(f"\n=== Sending Thank You Messages ===")
            thank_you_sent = 0
            for player_name, fname, mobile, amt, row_idx in recorded_payment_details:
                balance = 0.0
                if updated_data and row_idx < len(updated_data):
                    row = updated_data[row_idx]
                    if len(row) > COL_BALANCE and row[COL_BALANCE]:
                        try:
                            balance = float(str(row[COL_BALANCE]).replace('$', '').replace(',', '').strip())
                        except (ValueError, AttributeError):
                            balance = 0.0
                if send_whatsapp_thank_you(wa_client, player_name, fname, mobile, amt, balance):
                    thank_you_sent += 1
            print(f"[DONE] Sent {thank_you_sent}/{len(recorded_payment_details)} thank you messages")

    return (payments_recorded, payments_skipped, payments_unmatched)
