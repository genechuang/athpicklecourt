"""
Venmo Payment Email Trigger Cloud Function (Pub/Sub)

Triggered by Gmail API push notifications when Venmo payment emails arrive.
Uses Gmail API watch + Cloud Pub/Sub for true push notifications (no polling).

Deployment:
    gcloud functions deploy venmo-sync-trigger \
      --gen2 \
      --runtime=python311 \
      --region=us-west1 \
      --source=. \
      --entry-point=venmo_email_trigger \
      --trigger-topic=venmo-payment-emails \
      --set-env-vars SMAD_SPREADSHEET_ID=<spreadsheet_id> \
      --set-secrets VENMO_ACCESS_TOKEN=VENMO_ACCESS_TOKEN:latest,SMAD_GOOGLE_CREDENTIALS_JSON=SMAD_GOOGLE_CREDENTIALS_JSON:latest

Environment Variables:
    SMAD_SPREADSHEET_ID: Google Sheets spreadsheet ID
    VENMO_ACCESS_TOKEN: Venmo API access token (from Secret Manager)
    SMAD_GOOGLE_CREDENTIALS_JSON: Google service account JSON (from Secret Manager)
    SMAD_SHEET_NAME: (optional) Main sheet name (default: 2026 Pickleball)
    PAYMENT_LOG_SHEET_NAME: (optional) Payment log sheet name (default: Payment Log)
"""

import os
import sys
import json
import base64
import functions_framework
from cloudevents.http import CloudEvent

from shared.venmo_sync import sync_venmo_to_sheet


@functions_framework.cloud_event
def venmo_email_trigger(cloud_event: CloudEvent):
    """
    Pub/Sub Cloud Function triggered by Gmail API push notifications.

    When a Venmo payment email arrives, Gmail publishes a notification to
    Pub/Sub, which triggers this function. The function runs venmo-sync
    to fetch and match payments by @username.

    Note: Gmail notification only contains metadata (historyId, emailAddress),
    not the actual email content. We don't need the email content since
    venmo-sync uses the Venmo API directly for matching.

    Args:
        cloud_event: CloudEvent containing Pub/Sub message from Gmail

    Returns:
        None (Pub/Sub functions don't return values)
    """
    print("[INFO] Gmail notification received, triggering Venmo sync...")

    # Optional: Log Gmail notification metadata (for debugging)
    try:
        # Pub/Sub message data is base64-encoded JSON
        pubsub_message = cloud_event.data.get('message', {})
        if 'data' in pubsub_message:
            gmail_notification = json.loads(base64.b64decode(pubsub_message['data']).decode('utf-8'))
            email_address = gmail_notification.get('emailAddress', '')
            history_id = gmail_notification.get('historyId', '')
            print(f"[INFO] Gmail notification for: {email_address}, historyId: {history_id}")
    except Exception as e:
        print(f"[WARN] Could not parse Gmail notification: {e}")

    # Get configuration from environment
    venmo_token = os.environ.get('VENMO_ACCESS_TOKEN')
    spreadsheet_id = os.environ.get('SMAD_SPREADSHEET_ID')
    google_creds_json = os.environ.get('SMAD_GOOGLE_CREDENTIALS_JSON')
    main_sheet = os.environ.get('SMAD_SHEET_NAME', '2026 Pickleball')
    payment_log_sheet = os.environ.get('PAYMENT_LOG_SHEET_NAME', 'Payment Log')

    # Validate required configuration
    if not venmo_token:
        error_msg = "VENMO_ACCESS_TOKEN not configured"
        print(f"[ERROR] {error_msg}")
        raise ValueError(error_msg)

    if not spreadsheet_id:
        error_msg = "SMAD_SPREADSHEET_ID not configured"
        print(f"[ERROR] {error_msg}")
        raise ValueError(error_msg)

    if not google_creds_json:
        error_msg = "SMAD_GOOGLE_CREDENTIALS_JSON not configured"
        print(f"[ERROR] {error_msg}")
        raise ValueError(error_msg)

    # Run venmo-sync
    try:
        recorded, skipped, unmatched = sync_venmo_to_sheet(
            venmo_access_token=venmo_token,
            spreadsheet_id=spreadsheet_id,
            google_credentials=google_creds_json,
            main_sheet_name=main_sheet,
            payment_log_sheet_name=payment_log_sheet,
            limit=50,  # Check last 50 transactions
            dry_run=False
        )

        print(f"[SUCCESS] Sync completed: {recorded} recorded, {skipped} skipped, {unmatched} unmatched")
        print(f"[DONE] Venmo sync completed successfully")

    except Exception as e:
        error_msg = f"Sync failed: {str(e)}"
        print(f"[ERROR] {error_msg}")
        import traceback
        traceback.print_exc()
        raise  # Re-raise exception so Pub/Sub knows it failed
