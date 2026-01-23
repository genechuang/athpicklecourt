#!/usr/bin/env python3
"""
Setup Gmail API Watch for Venmo Payment Emails

This script sets up a Gmail watch that publishes notifications to Cloud Pub/Sub
when Venmo payment emails arrive. The watch expires after 7 days and must be renewed.

Prerequisites:
- Gmail API enabled in Google Cloud Console
- OAuth 2.0 credentials downloaded (credentials.json)
- Cloud Pub/Sub topic created (venmo-payment-emails)
- Gmail API permission granted to topic

Usage:
    python setup-gmail-watch.py                 # Initial setup (requires OAuth)
    python setup-gmail-watch.py --renew         # Renew existing watch

Environment Variables:
    GMAIL_WATCH_LABEL_IDS: (optional) Comma-separated Gmail label IDs to watch
                           Default: INBOX (watches entire inbox)
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("ERROR: Google API libraries not installed.")
    print("Run: pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Configuration
PROJECT_ID = 'smad-pickleball'
PUBSUB_TOPIC = f'projects/{PROJECT_ID}/topics/venmo-payment-emails'
TOKEN_FILE = 'gmail-token.json'  # Stores OAuth credentials
CREDENTIALS_FILE = 'gmail-credentials.json'  # OAuth client credentials


def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = None

    # Load existing token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # If no valid credentials, do OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[INFO] Refreshing expired credentials...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print(f"ERROR: {CREDENTIALS_FILE} not found.")
                print("\nTo get this file:")
                print("1. Go to https://console.cloud.google.com/apis/credentials")
                print("2. Create OAuth 2.0 Client ID (Desktop app)")
                print("3. Download JSON and save as gmail-credentials.json")
                sys.exit(1)

            print("[INFO] Starting OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        print(f"[OK] Credentials saved to {TOKEN_FILE}")

    return build('gmail', 'v1', credentials=creds)


def setup_watch(gmail_service, label_ids=None):
    """
    Set up Gmail watch to publish notifications to Pub/Sub.

    Args:
        gmail_service: Gmail API service instance
        label_ids: List of label IDs to watch (default: ['INBOX'])

    Returns:
        Watch response dict with historyId and expiration
    """
    if label_ids is None:
        label_ids = ['INBOX']

    request_body = {
        'labelIds': label_ids,
        'topicName': PUBSUB_TOPIC,
        'labelFilterBehavior': 'INCLUDE'  # Only send notifications for these labels
    }

    try:
        print(f"[INFO] Setting up Gmail watch...")
        print(f"  Topic: {PUBSUB_TOPIC}")
        print(f"  Labels: {', '.join(label_ids)}")

        response = gmail_service.users().watch(
            userId='me',
            body=request_body
        ).execute()

        history_id = response.get('historyId')
        expiration = int(response.get('expiration', 0)) / 1000  # Convert ms to seconds
        expiration_dt = datetime.fromtimestamp(expiration)

        print(f"\n[OK] Gmail watch configured successfully!")
        print(f"  History ID: {history_id}")
        print(f"  Expires: {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')} ({expiration_dt - datetime.now()})")
        print(f"\n[NOTE] Watch will expire in ~7 days. Run this script again to renew.")

        return response

    except HttpError as e:
        error_details = json.loads(e.content.decode('utf-8'))
        error_message = error_details.get('error', {}).get('message', str(e))

        print(f"\n[ERROR] Failed to set up Gmail watch:")
        print(f"  {error_message}")

        if 'Service account' in error_message:
            print("\n[TIP] If using service account:")
            print("  1. Enable domain-wide delegation")
            print("  2. Use user impersonation")
        elif 'has not been used' in error_message or 'disabled' in error_message:
            print("\n[TIP] Gmail API may not be enabled:")
            print("  1. Go to https://console.cloud.google.com/apis/library/gmail.googleapis.com")
            print("  2. Enable Gmail API")
            print("  3. Wait a few minutes and try again")
        elif 'Pub/Sub' in error_message:
            print("\n[TIP] Pub/Sub topic permissions issue:")
            print("  1. Ensure topic exists: gcloud pubsub topics list")
            print("  2. Grant Gmail permission:")
            print(f"     gcloud pubsub topics add-iam-policy-binding venmo-payment-emails \\")
            print(f"       --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \\")
            print(f"       --role=roles/pubsub.publisher")

        sys.exit(1)


def stop_watch(gmail_service):
    """Stop the current Gmail watch."""
    try:
        print("[INFO] Stopping Gmail watch...")
        gmail_service.users().stop(userId='me').execute()
        print("[OK] Gmail watch stopped successfully")
    except HttpError as e:
        if 'No valid push subscription' in str(e):
            print("[INFO] No active watch to stop")
        else:
            print(f"[WARN] Failed to stop watch: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Setup Gmail API watch for Venmo payment email notifications',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                  # Initial setup
  %(prog)s --renew          # Renew existing watch
  %(prog)s --stop           # Stop watch
  %(prog)s --status         # Check watch status

Setup Steps:
  1. Enable Gmail API in Cloud Console
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Download credentials.json → gmail-credentials.json
  4. Run this script
  5. Authorize in browser when prompted

Watch expires after 7 days. Re-run this script to renew.
        """
    )

    parser.add_argument('--renew', action='store_true',
                        help='Renew existing watch')
    parser.add_argument('--stop', action='store_true',
                        help='Stop Gmail watch')
    parser.add_argument('--status', action='store_true',
                        help='Check current watch status')
    parser.add_argument('--labels', type=str,
                        help='Comma-separated Gmail label IDs (default: INBOX)')

    args = parser.parse_args()

    # Get Gmail service
    gmail_service = get_gmail_service()

    # Parse label IDs
    label_ids = None
    if args.labels:
        label_ids = [l.strip() for l in args.labels.split(',')]

    if args.stop:
        stop_watch(gmail_service)
    elif args.status:
        print("[INFO] Checking Gmail watch status...")
        print("[NOTE] Gmail API doesn't provide a status endpoint.")
        print("       Watch is active until it expires (~7 days after setup).")
        print(f"       Check {TOKEN_FILE} modification time to estimate expiration.")
        if os.path.exists(TOKEN_FILE):
            mtime = os.path.getmtime(TOKEN_FILE)
            setup_time = datetime.fromtimestamp(mtime)
            estimated_expiry = setup_time + timedelta(days=7)
            print(f"\nLast setup: {setup_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Estimated expiry: {estimated_expiry.strftime('%Y-%m-%d %H:%M:%S')}")
            if estimated_expiry < datetime.now():
                print("[WARN] Watch likely expired. Run with --renew to reactivate.")
    elif args.renew:
        print("[INFO] Renewing Gmail watch (stopping old, starting new)...")
        stop_watch(gmail_service)
        setup_watch(gmail_service, label_ids)
    else:
        # Initial setup
        setup_watch(gmail_service, label_ids)

    print(f"\n[INFO] Gmail will now publish notifications to: {PUBSUB_TOPIC}")
    print(f"[INFO] Cloud Function will trigger on Venmo payment emails")


if __name__ == '__main__':
    main()
