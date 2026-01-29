"""
SMAD Picklebot - WhatsApp Chatbot Cloud Function

Receives commands from Admin Dinkers WhatsApp group via GREEN-API webhook.
Uses Claude Haiku for natural language intent parsing.

Commands:
    /pb help - Show available commands
    /pb deadbeats - Show players with outstanding balances
    /pb balance [name] - Show balances
    /pb book <date> <time> [duration] - Book court (requires confirmation)
    /pb poll create - Create weekly poll (requires confirmation)
    /pb reminders - Send vote reminders (requires confirmation)
    /pb status - Show system status

Deployment:
    gcloud functions deploy smad-picklebot \
        --runtime=python311 \
        --trigger-http \
        --allow-unauthenticated \
        --entry-point=picklebot_webhook
"""

import os
import json
import logging
import secrets
import re
from datetime import datetime, timedelta
from typing import Optional

import functions_framework
import pytz
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PST timezone
PST = pytz.timezone('America/Los_Angeles')

# Environment variables
GREENAPI_INSTANCE_ID = os.environ.get('GREENAPI_INSTANCE_ID', '')
GREENAPI_API_TOKEN = os.environ.get('GREENAPI_API_TOKEN', '')
ADMIN_DINKERS_GROUP_ID = os.environ.get('ADMIN_DINKERS_WHATSAPP_GROUP_ID', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'genechuang/SMADPickleBot')
PICKLEBOT_CONFIRM_URL = os.environ.get('PICKLEBOT_CONFIRM_URL', '')

# Google Sheets config (reuse from smad-whatsapp.py)
SPREADSHEET_ID = os.environ.get('SMAD_SPREADSHEET_ID', '1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY')
SHEET_NAME = os.environ.get('SMAD_SHEET_NAME', '2026 Pickleball')

# GCS bucket for pending actions
GCS_BUCKET_NAME = 'smad-pickleball-screenshots'
GCS_PROJECT_ID = 'smad-pickleball'

# Cloud Scheduler config
SCHEDULER_LOCATION = 'us-west1'
SCHEDULER_TIMEZONE = 'America/Los_Angeles'

# Booking advance days limit (Athenaeum only allows 7 days in advance)
BOOKING_ADVANCE_DAYS = 7

# Bot signature (matching court booking summary)
PICKLEBOT_SIGNATURE = "SMAD Picklebot🥒🏓🤖"

# Column indices for player data
COL_FIRST_NAME = 0
COL_LAST_NAME = 1
COL_BALANCE = 7

# Pickle Poll Log sheet columns
POLL_LOG_SHEET_NAME = 'Pickle Poll Log'
PPL_COL_POLL_ID = 0
PPL_COL_POLL_DATE = 1
PPL_COL_POLL_QUESTION = 2
PPL_COL_PLAYER_NAME = 3
PPL_COL_VOTE_TIMESTAMP = 4
PPL_COL_VOTE_OPTIONS = 5

# Command prefixes
COMMAND_PREFIXES = ['/pb ', '/picklebot ']

# Dry run flags that can appear in command text
DRY_RUN_FLAGS = ['--dry-run', '--dry', '-n', 'dry run', 'dryrun']


def extract_dry_run_flag(command_text: str) -> tuple[str, bool]:
    """
    Check if command contains a dry run flag and remove it from the command.

    Returns:
        tuple: (cleaned_command, is_dry_run)
    """
    text_lower = command_text.lower()

    for flag in DRY_RUN_FLAGS:
        if flag in text_lower:
            # Remove the flag from command (case-insensitive)
            import re
            pattern = re.compile(re.escape(flag), re.IGNORECASE)
            cleaned = pattern.sub('', command_text).strip()
            # Clean up any double spaces
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            return cleaned, True

    return command_text, False


def send_whatsapp_message(chat_id: str, message: str, dry_run: bool = False) -> bool:
    """Send a WhatsApp message via GREEN-API.

    Args:
        chat_id: The WhatsApp chat ID to send to
        message: The message content
        dry_run: If True, skip sending and just log

    Returns:
        True if sent (or would be sent in dry run), False on error
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would send to {chat_id}: {message[:100]}...")
        return True

    if not GREENAPI_INSTANCE_ID or not GREENAPI_API_TOKEN:
        logger.error("GREEN-API credentials not configured")
        return False

    url = f"https://api.green-api.com/waInstance{GREENAPI_INSTANCE_ID}/sendMessage/{GREENAPI_API_TOKEN}"

    try:
        response = requests.post(url, json={
            'chatId': chat_id,
            'message': message
        }, timeout=30)

        if response.status_code == 200:
            logger.info(f"Message sent to {chat_id}")
            return True
        else:
            logger.error(f"Failed to send message: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return False


def send_whatsapp_image(chat_id: str, image_url: str, caption: str = "", dry_run: bool = False) -> bool:
    """Send an image via GREEN-API using URL.

    Args:
        chat_id: The WhatsApp chat ID to send to
        image_url: URL of the image to send
        caption: Optional caption for the image
        dry_run: If True, skip sending and just log

    Returns:
        True if sent (or would be sent in dry run), False on error
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would send image to {chat_id}: {image_url[:100]}...")
        return True

    if not GREENAPI_INSTANCE_ID or not GREENAPI_API_TOKEN:
        logger.error("GREEN-API credentials not configured")
        return False

    url = f"https://api.green-api.com/waInstance{GREENAPI_INSTANCE_ID}/sendFileByUrl/{GREENAPI_API_TOKEN}"

    try:
        response = requests.post(url, json={
            'chatId': chat_id,
            'urlFile': image_url,
            'fileName': 'meme.jpg',
            'caption': caption
        }, timeout=30)

        if response.status_code == 200:
            logger.info(f"Image sent to {chat_id}")
            return True
        else:
            logger.error(f"Failed to send image: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending image: {e}")
        return False


def parse_intent_with_claude(command_text: str) -> dict:
    """Use Claude Haiku to parse natural language command."""
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, using fallback parsing")
        return parse_intent_fallback(command_text)

    prompt = f"""Parse this SMAD Picklebot command and extract the intent and parameters.

Command: {command_text}

Available intents:
- help: Show available commands (no params)
- show_deadbeats: Show players with outstanding balances (no params)
- show_balances: Show all balances or specific player (optional: player_name)
- show_games: Show all scheduled games this week from poll votes (no params)
- next_game: Show the next upcoming game from poll votes (no params)
- book_court: Book a court (params: date, time, duration_minutes, court - north/south/both)
- list_jobs: List scheduled court bookings (no params)
- cancel_job: Cancel a scheduled booking (params: job_id)
- create_poll: Create weekly availability poll (no params)
- send_reminders: Send reminders (params: type - vote/payment)
- show_status: Show system status (no params)
- tell_joke: Tell a pickleball joke (no params)
- post_meme: Post a pickleball meme (no params)

For book_court:
- Parse dates like "2/4", "Feb 4", "tomorrow", "next Tuesday"
- Parse times like "7pm", "7:00 PM", "19:00"
- Parse durations like "2 hours", "2hrs", "120 minutes" (default: 120 minutes)
- Parse courts like "north", "south", "both" (default: both)

Return ONLY valid JSON (no markdown, no explanation):
{{"intent": "...", "params": {{}}, "confirmation_required": true/false}}

Set confirmation_required=true for: book_court, create_poll, send_reminders, cancel_job
Set confirmation_required=false for: help, show_deadbeats, show_balances, show_games, next_game, show_status, list_jobs, tell_joke, post_meme"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            content = result.get('content', [{}])[0].get('text', '{}')
            # Clean up any markdown formatting
            content = content.strip()
            if content.startswith('```'):
                content = re.sub(r'^```\w*\n?', '', content)
                content = re.sub(r'\n?```$', '', content)
            return json.loads(content)
        else:
            logger.error(f"Claude API error: {response.status_code} - {response.text}")
            return parse_intent_fallback(command_text)

    except Exception as e:
        logger.error(f"Error parsing intent with Claude: {e}")
        return parse_intent_fallback(command_text)


def parse_intent_fallback(command_text: str) -> dict:
    """Simple regex-based intent parsing as fallback."""
    text = command_text.lower().strip()

    # Remove command prefix
    for prefix in COMMAND_PREFIXES:
        if text.startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break

    if text in ['help', '?', 'commands']:
        return {"intent": "help", "params": {}, "confirmation_required": False}

    if text in ['deadbeats', 'deadbeat', 'owes', 'outstanding']:
        return {"intent": "show_deadbeats", "params": {}, "confirmation_required": False}

    if text.startswith('balance'):
        name = text.replace('balance', '').strip()
        return {"intent": "show_balances", "params": {"player_name": name} if name else {}, "confirmation_required": False}

    if text.startswith('book'):
        # Basic parsing: book 2/4 7pm 2hrs
        return {"intent": "book_court", "params": {"raw": text}, "confirmation_required": True}

    # Jobs commands
    if text == 'jobs' or text == 'scheduled':
        return {"intent": "list_jobs", "params": {}, "confirmation_required": False}

    if text.startswith('jobs cancel ') or text.startswith('cancel job '):
        job_id = text.replace('jobs cancel ', '').replace('cancel job ', '').strip()
        return {"intent": "cancel_job", "params": {"job_id": job_id}, "confirmation_required": False}

    if 'poll' in text and 'create' in text:
        return {"intent": "create_poll", "params": {}, "confirmation_required": True}

    if 'reminder' in text:
        return {"intent": "send_reminders", "params": {"type": "vote"}, "confirmation_required": True}

    if text in ['status', 'health']:
        return {"intent": "show_status", "params": {}, "confirmation_required": False}

    # Games/schedule commands
    if text in ['games', 'schedule', 'scheduled games', 'games this week', 'who is playing']:
        return {"intent": "show_games", "params": {}, "confirmation_required": False}

    if text in ['next', 'next game', 'upcoming', 'upcoming game', 'when is the next game']:
        return {"intent": "next_game", "params": {}, "confirmation_required": False}

    # Fun commands
    if 'joke' in text:
        return {"intent": "tell_joke", "params": {}, "confirmation_required": False}

    if 'meme' in text or 'photo' in text or 'pic' in text:
        return {"intent": "post_meme", "params": {}, "confirmation_required": False}

    return {"intent": "unknown", "params": {"raw": text}, "confirmation_required": False}


def get_sheets_service():
    """Initialize Google Sheets API service."""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

        # Try SMAD-specific credentials first, then fall back to generic
        creds_env = os.environ.get('SMAD_GOOGLE_CREDENTIALS_JSON') or os.environ.get('GOOGLE_CREDENTIALS_JSON')
        if creds_env:
            creds_json = json.loads(creds_env)
            creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        else:
            from google.auth import default
            creds, _ = default(scopes=SCOPES)

        service = build('sheets', 'v4', credentials=creds)
        return service.spreadsheets()
    except Exception as e:
        logger.error(f"Failed to initialize Sheets service: {e}")
        return None


def get_player_balances() -> list:
    """Get all player balances from Google Sheets."""
    sheets = get_sheets_service()
    if not sheets:
        return []

    try:
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        players = []
        for row in data[1:]:  # Skip header
            if len(row) > COL_BALANCE:
                first_name = row[COL_FIRST_NAME] if len(row) > COL_FIRST_NAME else ""
                last_name = row[COL_LAST_NAME] if len(row) > COL_LAST_NAME else ""

                if not first_name:
                    continue

                # Skip the Totals row (sheet summary)
                if first_name.lower() in ('totals', 'total', 'sum'):
                    continue

                balance_str = row[COL_BALANCE] if len(row) > COL_BALANCE else "0"
                try:
                    balance = float(balance_str.replace('$', '').replace(',', '').strip() or '0')
                except ValueError:
                    balance = 0

                players.append({
                    'name': f"{first_name} {last_name}".strip(),
                    'balance': balance
                })

        return players

    except Exception as e:
        logger.error(f"Failed to get player balances: {e}")
        return []


def get_poll_votes() -> Optional[dict]:
    """Get current poll votes from Pickle Poll Log sheet.

    Returns:
        dict with poll info and votes organized by option, or None if failed
    """
    sheets = get_sheets_service()
    if not sheets:
        return None

    try:
        # Read poll log data
        result = sheets.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{POLL_LOG_SHEET_NAME}'"
        ).execute()
        data = result.get('values', [])

        if len(data) < 2:
            return None

        # Find the most recent poll date
        poll_dates = set()
        for row in data[1:]:
            if len(row) > PPL_COL_POLL_DATE:
                poll_dates.add(row[PPL_COL_POLL_DATE])

        if not poll_dates:
            return None

        # Get the most recent poll date (sort by timestamp format M/D/YY H:MM:SS)
        def parse_poll_date(d):
            try:
                return datetime.strptime(d, '%m/%d/%y %H:%M:%S')
            except:
                try:
                    return datetime.strptime(d, '%m/%d/%Y %H:%M:%S')
                except:
                    return datetime.min

        latest_poll_date = max(poll_dates, key=parse_poll_date)
        poll_question = ""

        # Collect votes for the latest poll
        votes_by_option = {}
        voters = set()

        for row in data[1:]:
            if len(row) > PPL_COL_VOTE_OPTIONS:
                row_poll_date = row[PPL_COL_POLL_DATE]
                if row_poll_date == latest_poll_date:
                    player_name = row[PPL_COL_PLAYER_NAME]
                    vote_options_str = row[PPL_COL_VOTE_OPTIONS]
                    if not poll_question and len(row) > PPL_COL_POLL_QUESTION:
                        poll_question = row[PPL_COL_POLL_QUESTION]

                    voters.add(player_name)

                    # Parse selected options
                    selected = [opt.strip() for opt in vote_options_str.split(',') if opt.strip()]

                    for option in selected:
                        if option not in votes_by_option:
                            votes_by_option[option] = []
                        votes_by_option[option].append(player_name)

        return {
            'poll_date': latest_poll_date,
            'question': poll_question,
            'votes_by_option': votes_by_option,
            'total_voters': len(voters)
        }

    except Exception as e:
        logger.error(f"Failed to get poll votes: {e}")
        return None


def parse_game_option_date(option: str) -> Optional[datetime]:
    """Parse a date from a poll option string like 'Mon 1/26/26 7pm' or 'Fri 1/30/26 4pm'.

    Returns:
        datetime object with PST timezone, or None if not parseable as a game date
    """
    # Skip non-game options
    skip_keywords = ['cannot', "can't", 'none', 'removed', 'other']
    option_lower = option.lower()
    if any(kw in option_lower for kw in skip_keywords):
        return None

    # Try to extract date and time from option
    # Common formats: "Mon 1/26/26 7pm", "Fri 1/30/26 4pm", "Sat 1/31/26 10am"
    # Also: "Wed 1/29/26 7pm", "Tues 1/27/26 7pm", "Sun 2/1/26 2:00PM"

    # Remove day name prefix if present
    import re
    # Match patterns like "Mon ", "Tues ", "Wed ", etc.
    option_clean = re.sub(r'^(Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)\s+', '', option, flags=re.IGNORECASE)

    # Try to parse date and time
    patterns = [
        r'(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))',  # 1/26/26 7pm or 1/26/26 7:00pm
        r'(\d{1,2}/\d{1,2})\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))',  # 1/26 7pm
    ]

    for pattern in patterns:
        match = re.search(pattern, option_clean, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            time_str = match.group(2).upper().replace(' ', '')

            # Parse date
            now = datetime.now(PST)
            current_year = now.year

            for date_fmt in ['%m/%d/%y', '%m/%d/%Y', '%m/%d']:
                try:
                    parsed_date = datetime.strptime(date_str, date_fmt)
                    if '%y' not in date_fmt.lower():
                        parsed_date = parsed_date.replace(year=current_year)
                    break
                except ValueError:
                    continue
            else:
                continue

            # Parse time
            for time_fmt in ['%I:%M%p', '%I%p', '%H:%M']:
                try:
                    parsed_time = datetime.strptime(time_str, time_fmt)
                    break
                except ValueError:
                    continue
            else:
                continue

            # Combine date and time
            result = parsed_date.replace(
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                second=0,
                microsecond=0
            )
            return PST.localize(result)

    return None


def get_games_from_votes(votes_by_option: dict) -> list:
    """Extract game dates and players from poll votes.

    Args:
        votes_by_option: dict mapping option strings to list of player names

    Returns:
        List of game dicts sorted by date, each with:
        - option: original option string
        - date: datetime object
        - players: list of player names
        - player_count: number of players
    """
    games = []

    for option, players in votes_by_option.items():
        game_date = parse_game_option_date(option)
        if game_date:
            games.append({
                'option': option,
                'date': game_date,
                'players': sorted(players),
                'player_count': len(players)
            })

    # Sort by date
    games.sort(key=lambda g: g['date'])
    return games


# Command handlers
def handle_help(is_admin_group: bool = True) -> str:
    """Return help message with available commands.

    Args:
        is_admin_group: If True, show all commands. If False, hide action commands.
    """
    if is_admin_group:
        return f"""*{PICKLEBOT_SIGNATURE} Commands*

*Read-only:*
/pb help - Show this message
/pb deadbeats - Show players with outstanding balances
/pb balance [name] - Show all balances or specific player
/pb games - Show games scheduled this week
/pb next - Show next upcoming game
/pb status - Show system status
/pb jobs - List scheduled court bookings

*Actions:*
/pb book <date> <time> [duration] - Book court
  Example: /pb book 2/4 7pm 2hrs both courts
  📅 If date is >7 days out, auto-schedules booking!
/pb jobs cancel <job_id> - Cancel a scheduled booking
/pb poll create - Create weekly availability poll
/pb reminders - Send vote reminders

*Fun:*
/pb joke - Tell a pickleball joke 🎭
/pb meme - Post a pickleball meme 📸

*Options:*
--dry-run - Test command without executing

Tip: You can use natural language!
  "/pb tell me a joke"
  "/pb book next Tuesday at 7pm"
"""
    else:
        # Restricted help for non-admin groups (SMAD Pickleball)
        return f"""*{PICKLEBOT_SIGNATURE} Commands*

*Read-only:*
/pb help - Show this message
/pb deadbeats - Show players with outstanding balances
/pb balance [name] - Show all balances or specific player
/pb games - Show games scheduled this week
/pb next - Show next upcoming game
/pb status - Show system status
/pb jobs - List scheduled court bookings

*Fun:*
/pb joke - Tell a pickleball joke 🎭
/pb meme - Post a pickleball meme 📸

_Action commands are only available in Admin Dinkers._
"""


def handle_deadbeats() -> str:
    """Return list of players with outstanding balances."""
    players = get_player_balances()
    deadbeats = [p for p in players if p['balance'] > 0]

    if not deadbeats:
        return f"*{PICKLEBOT_SIGNATURE}*\n\nNo outstanding balances! Everyone is paid up."

    # Sort by balance descending
    deadbeats.sort(key=lambda x: x['balance'], reverse=True)
    total = sum(p['balance'] for p in deadbeats)

    message = f"*{PICKLEBOT_SIGNATURE} - Outstanding Balances*\n\n"
    for p in deadbeats:
        message += f"- {p['name']}: ${p['balance']:.2f}\n"
    message += f"\n*Total: ${total:.2f}*"

    return message


def handle_balances(player_name: str = None) -> str:
    """Return all balances or specific player balance."""
    players = get_player_balances()

    if player_name:
        # Search for specific player
        player_name_lower = player_name.lower()
        matches = [p for p in players if player_name_lower in p['name'].lower()]

        if not matches:
            return f"*{PICKLEBOT_SIGNATURE}*\n\nPlayer '{player_name}' not found."

        if len(matches) == 1:
            p = matches[0]
            status = "owes" if p['balance'] > 0 else "has credit of" if p['balance'] < 0 else "is all paid up"
            if p['balance'] == 0:
                return f"*{PICKLEBOT_SIGNATURE}*\n\n{p['name']} {status}!"
            return f"*{PICKLEBOT_SIGNATURE}*\n\n{p['name']} {status} ${abs(p['balance']):.2f}"

        # Multiple matches
        message = f"*{PICKLEBOT_SIGNATURE}*\n\nMultiple matches for '{player_name}':\n"
        for p in matches:
            message += f"- {p['name']}: ${p['balance']:.2f}\n"
        return message

    # All players
    players.sort(key=lambda x: x['balance'], reverse=True)
    total = sum(p['balance'] for p in players if p['balance'] > 0)

    message = f"*{PICKLEBOT_SIGNATURE} - All Balances*\n\n"
    for p in players:
        if p['balance'] != 0:
            message += f"- {p['name']}: ${p['balance']:.2f}\n"
    message += f"\n*Total Outstanding: ${total:.2f}*"

    return message


def handle_status() -> str:
    """Return system status."""
    now = datetime.now(PST)
    timestamp = now.strftime('%m/%d/%y %I:%M %p PST')

    status = f"""*{PICKLEBOT_SIGNATURE} Status*

Time: {timestamp}
Webhook: Online
GREEN-API: {'Connected' if GREENAPI_INSTANCE_ID else 'Not configured'}
Claude API: {'Connected' if ANTHROPIC_API_KEY else 'Not configured'}
GitHub: {'Connected' if GITHUB_TOKEN else 'Not configured'}
Sheets: {'Connected' if SPREADSHEET_ID else 'Not configured'}
"""
    return status


def handle_show_games() -> str:
    """Show all scheduled games this week from poll votes."""
    poll_data = get_poll_votes()

    if not poll_data:
        return f"""*{PICKLEBOT_SIGNATURE} - Games This Week*

No poll data found. Create a poll first with /pb poll create."""

    votes_by_option = poll_data.get('votes_by_option', {})
    games = get_games_from_votes(votes_by_option)

    if not games:
        return f"""*{PICKLEBOT_SIGNATURE} - Games This Week*

No games scheduled from current poll.

Poll: {poll_data.get('question', 'Unknown')}
Voters: {poll_data.get('total_voters', 0)}"""

    now = datetime.now(PST)
    message = f"*{PICKLEBOT_SIGNATURE} - Games This Week* 🏓\n\n"

    for game in games:
        game_date = game['date']
        day_name = game_date.strftime('%A')
        date_str = game_date.strftime('%m/%d')
        time_str = game_date.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ')

        # Check if game is in the past
        is_past = game_date < now
        status = "✅ " if is_past else "📅 "

        message += f"{status}*{day_name} {date_str} @ {time_str}*\n"
        message += f"   Players ({game['player_count']}): "
        message += ", ".join(game['players'][:8])  # Show first 8 players
        if game['player_count'] > 8:
            message += f" +{game['player_count'] - 8} more"
        message += "\n\n"

    return message.strip()


def handle_next_game() -> str:
    """Show the next upcoming game from poll votes."""
    poll_data = get_poll_votes()

    if not poll_data:
        return f"""*{PICKLEBOT_SIGNATURE} - Next Game*

No poll data found. Create a poll first with /pb poll create."""

    votes_by_option = poll_data.get('votes_by_option', {})
    games = get_games_from_votes(votes_by_option)

    if not games:
        return f"""*{PICKLEBOT_SIGNATURE} - Next Game*

No games scheduled from current poll."""

    now = datetime.now(PST)

    # Find the next game that hasn't happened yet
    next_game = None
    for game in games:
        if game['date'] > now:
            next_game = game
            break

    if not next_game:
        # All games are in the past, show the last one
        next_game = games[-1]
        return f"""*{PICKLEBOT_SIGNATURE} - Next Game*

All games for this week have passed!

Last game was:
📅 {next_game['date'].strftime('%A, %B %d at %I:%M %p').replace(' 0', ' ')}
👥 Players ({next_game['player_count']}): {', '.join(next_game['players'])}"""

    # Calculate time until game
    time_diff = next_game['date'] - now
    days = time_diff.days
    hours = time_diff.seconds // 3600

    if days > 0:
        time_until = f"{days} day{'s' if days != 1 else ''}"
        if hours > 0:
            time_until += f", {hours} hour{'s' if hours != 1 else ''}"
    elif hours > 0:
        time_until = f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        minutes = time_diff.seconds // 60
        time_until = f"{minutes} minute{'s' if minutes != 1 else ''}"

    return f"""*{PICKLEBOT_SIGNATURE} - Next Game* 🏓

📅 *{next_game['date'].strftime('%A, %B %d at %I:%M %p').replace(' 0', ' ')}*
⏰ In {time_until}

👥 *Players ({next_game['player_count']}):*
{chr(10).join('  - ' + p for p in next_game['players'])}"""


def handle_unknown(raw_text: str) -> str:
    """Handle unknown commands."""
    return f"""*{PICKLEBOT_SIGNATURE}*

I didn't understand: "{raw_text}"

Type /pb help to see available commands."""


def handle_action_not_available(intent: str) -> str:
    """Return message when an action command is used in a non-admin group."""
    return f"""*{PICKLEBOT_SIGNATURE}*

This command is only available in Admin Dinkers.

Type /pb help to see available commands here."""


def generate_pickleball_joke() -> str:
    """Generate a pickleball joke using Claude."""
    if not ANTHROPIC_API_KEY:
        # Fallback jokes if Claude unavailable
        import random
        jokes = [
            "Why did the pickleball player bring a ladder? To get to the top of the rankings! 🏆",
            "What do you call a pickleball player who won't stop talking? A dink-talker! 🗣️",
            "Why do pickleball players make great friends? They always return your calls! 📞",
            "What's a pickleball player's favorite music? Heavy dink metal! 🎸",
            "Why did the pickle go to the court? It wanted to be in a real pickle! 🥒",
        ]
        return random.choice(jokes)

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 150,
                "messages": [{
                    "role": "user",
                    "content": "Tell me a funny, original pickleball joke. Keep it short and family-friendly. Just the joke, no explanation. Add a relevant emoji at the end."
                }]
            },
            timeout=15
        )

        if response.status_code == 200:
            result = response.json()
            return result.get('content', [{}])[0].get('text', '').strip()
        else:
            logger.error(f"Claude API error for joke: {response.status_code}")
            return "Why did the pickleball cross the court? To get to the kitchen! 🥒"

    except Exception as e:
        logger.error(f"Error generating joke: {e}")
        return "What do you call a dinosaur playing pickleball? A dink-osaur! 🦖"


def handle_tell_joke() -> str:
    """Return a pickleball joke."""
    joke = generate_pickleball_joke()
    return f"""*{PICKLEBOT_SIGNATURE}* 🎭

{joke}"""


def validate_image_url(url: str) -> bool:
    """Check if an image URL is accessible."""
    try:
        response = requests.head(url, timeout=5, allow_redirects=True)
        return response.status_code == 200
    except Exception:
        return False


def find_pickleball_meme() -> dict:
    """Find a pickleball meme image URL.

    Returns:
        dict with 'url' and 'caption' keys, or 'error' if failed
    """
    import random

    # Use reliable stock image URLs from Unsplash (pickleball/tennis themed)
    # These are stable CDN URLs that shouldn't break
    meme_sources = [
        {
            "url": "https://images.unsplash.com/photo-1554068865-24cecd4e34b8?w=600",
            "caption": "When you're ready to dominate the kitchen 🔥"
        },
        {
            "url": "https://images.unsplash.com/photo-1622279457486-62dcc4a431d6?w=600",
            "caption": "POV: Your opponent just hit it into the net again 😂"
        },
        {
            "url": "https://images.unsplash.com/photo-1551773188-0801da12ddda?w=600",
            "caption": "Me pretending I didn't just hit the ball out of bounds 🙈"
        },
        {
            "url": "https://images.unsplash.com/photo-1587280501635-68a0e82cd5ff?w=600",
            "caption": "When someone asks if pickleball is a 'real' sport 🤨"
        },
        {
            "url": "https://images.unsplash.com/photo-1599586120429-48281b6f0ece?w=600",
            "caption": "The face you make when you finally beat your nemesis 💪"
        }
    ]

    # Try to get a meme from Claude with a caption
    caption = None
    if ANTHROPIC_API_KEY:
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 100,
                    "messages": [{
                        "role": "user",
                        "content": "Write a short, funny pickleball meme caption (1-2 sentences max). Include an emoji. Just the caption, nothing else."
                    }]
                },
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                caption = result.get('content', [{}])[0].get('text', '').strip()

        except Exception as e:
            logger.error(f"Error getting meme caption: {e}")

    # Pick a random image, shuffle to try different ones if needed
    random.shuffle(meme_sources)

    for meme in meme_sources:
        if validate_image_url(meme["url"]):
            return {
                "url": meme["url"],
                "caption": caption or meme["caption"]
            }

    # All URLs failed - return error
    logger.error("All meme image URLs failed validation")
    return {"error": "No valid image URLs found", "caption": caption or "Pickleball life! 🥒"}


def handle_post_meme(chat_id: str, dry_run: bool = False) -> str:
    """Find and post a pickleball meme."""
    meme = find_pickleball_meme()

    if 'error' in meme:
        return f"""*{PICKLEBOT_SIGNATURE}*

Couldn't find a meme right now. Try again later! 😅"""

    # Send the image
    caption = f"*{PICKLEBOT_SIGNATURE}* 📸\n\n{meme['caption']}"

    if dry_run:
        return f"""*{PICKLEBOT_SIGNATURE}* (DRY RUN)

Would post meme:
URL: {meme['url']}
Caption: {meme['caption']}"""

    success = send_whatsapp_image(chat_id, meme['url'], caption)

    if success:
        # Return empty - the image was sent separately
        return ""
    else:
        return f"""*{PICKLEBOT_SIGNATURE}*

{meme['caption']}

(Couldn't load image, but here's the caption! 🥒)"""


def parse_booking_date(date_str: str) -> Optional[datetime]:
    """
    Parse a date string into a datetime object.
    Handles formats like: 2/4, Feb 4, February 4, 2/4/25, 2/4/2025
    """
    if not date_str or date_str == 'unknown':
        return None

    now = datetime.now(PST)
    current_year = now.year

    # Clean up the date string
    date_str = date_str.strip()

    # Try various date formats
    formats_to_try = [
        '%m/%d/%Y',      # 2/4/2025
        '%m/%d/%y',      # 2/4/25
        '%m/%d',         # 2/4
        '%m-%d-%Y',      # 2-4-2025
        '%m-%d-%y',      # 2-4-25
        '%m-%d',         # 2-4
        '%B %d',         # February 4
        '%B %d, %Y',     # February 4, 2025
        '%b %d',         # Feb 4
        '%b %d, %Y',     # Feb 4, 2025
    ]

    for fmt in formats_to_try:
        try:
            parsed = datetime.strptime(date_str, fmt)
            # If no year was in the format, use current year (or next year if date passed)
            if '%Y' not in fmt and '%y' not in fmt:
                parsed = parsed.replace(year=current_year)
                # If the date is in the past, assume next year
                if PST.localize(parsed) < now:
                    parsed = parsed.replace(year=current_year + 1)
            return PST.localize(parsed)
        except ValueError:
            continue

    return None


def parse_booking_time(time_str: str) -> Optional[str]:
    """
    Parse a time string and return in HH:MM AM/PM format.
    Handles formats like: 7pm, 7:00 PM, 19:00, 7 PM
    """
    if not time_str or time_str == 'unknown':
        return None

    time_str = time_str.strip().upper()

    # Try various time formats
    formats_to_try = [
        '%I:%M %p',      # 7:00 PM
        '%I:%M%p',       # 7:00PM
        '%I %p',         # 7 PM
        '%I%p',          # 7PM
        '%H:%M',         # 19:00
    ]

    for fmt in formats_to_try:
        try:
            parsed = datetime.strptime(time_str, fmt)
            return parsed.strftime('%I:%M %p').lstrip('0')
        except ValueError:
            continue

    return None


def get_scheduler_client():
    """Initialize Cloud Scheduler client."""
    try:
        from google.cloud import scheduler_v1
        return scheduler_v1.CloudSchedulerClient()
    except ImportError:
        logger.error("google-cloud-scheduler not installed")
        return None
    except Exception as e:
        logger.error(f"Failed to init scheduler client: {e}")
        return None


def create_scheduled_booking(booking_date: datetime, booking_time: str,
                            duration: int, court: str, dry_run: bool = False) -> dict:
    """
    Create a Cloud Scheduler job to book court 7 days before the booking date.

    Args:
        booking_date: The target booking date (datetime with PST timezone)
        booking_time: Time string like "7:00 PM"
        duration: Duration in minutes
        court: Court name (north/south/both)
        dry_run: If True, don't actually create the job

    Returns:
        dict with status and details
    """
    now = datetime.now(PST)

    # Calculate the scheduling date (7 days before booking)
    schedule_date = booking_date - timedelta(days=BOOKING_ADVANCE_DAYS)

    # If schedule date is in the past, we can't schedule it
    if schedule_date.date() < now.date():
        days_until = (booking_date.date() - now.date()).days
        return {
            'status': 'error',
            'message': f'Booking date is only {days_until} days away - schedule date has passed'
        }

    # Format booking date/time for the workflow
    booking_datetime_str = booking_date.strftime('%m/%d/%Y') + f' {booking_time}'

    # Create unique job name based on booking details
    job_id = f"book-court-{booking_date.strftime('%Y%m%d')}-{booking_time.replace(':', '').replace(' ', '').lower()}"
    job_id = re.sub(r'[^a-z0-9-]', '', job_id.lower())

    # Schedule for 12:01 AM PST on the schedule date
    cron_schedule = f"1 0 {schedule_date.day} {schedule_date.month} *"

    # Build the GitHub Actions workflow dispatch payload
    workflow_payload = {
        "ref": "main",
        "inputs": {
            "booking_date_time": booking_datetime_str,
            "court": court if court != 'both' else '',
            "duration": str(duration)
        }
    }

    if dry_run:
        return {
            'status': 'dry_run',
            'job_id': job_id,
            'schedule_date': schedule_date.strftime('%m/%d/%Y'),
            'cron': cron_schedule,
            'booking_datetime': booking_datetime_str,
            'court': court,
            'duration': duration,
            'message': f'Would schedule job "{job_id}" for {schedule_date.strftime("%m/%d/%Y")} at 12:01 AM'
        }

    try:
        scheduler = get_scheduler_client()
        if not scheduler:
            return {'status': 'error', 'message': 'Cloud Scheduler client not available'}

        from google.cloud import scheduler_v1
        from google.protobuf import duration_pb2

        parent = f"projects/{GCS_PROJECT_ID}/locations/{SCHEDULER_LOCATION}"
        job_name = f"{parent}/jobs/{job_id}"

        # GitHub API endpoint for workflow dispatch
        github_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/court-booking.yml/dispatches"

        job = scheduler_v1.Job(
            name=job_name,
            description=f"Auto-book court for {booking_datetime_str}",
            schedule=cron_schedule,
            time_zone=SCHEDULER_TIMEZONE,
            http_target=scheduler_v1.HttpTarget(
                uri=github_url,
                http_method=scheduler_v1.HttpMethod.POST,
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json"
                },
                body=json.dumps(workflow_payload).encode()
            ),
            retry_config=scheduler_v1.RetryConfig(
                retry_count=3,
                max_retry_duration=duration_pb2.Duration(seconds=300)
            )
        )

        # Try to delete existing job with same name (in case of re-scheduling)
        try:
            scheduler.delete_job(name=job_name)
            logger.info(f"Deleted existing job: {job_id}")
        except Exception:
            pass  # Job doesn't exist, that's fine

        # Create the job
        created_job = scheduler.create_job(parent=parent, job=job)
        logger.info(f"Created scheduler job: {created_job.name}")

        return {
            'status': 'scheduled',
            'job_id': job_id,
            'schedule_date': schedule_date.strftime('%m/%d/%Y'),
            'cron': cron_schedule,
            'booking_datetime': booking_datetime_str,
            'court': court,
            'duration': duration
        }

    except Exception as e:
        logger.error(f"Failed to create scheduler job: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


def list_scheduled_jobs() -> list:
    """
    List all scheduled court booking jobs.

    Returns:
        List of job dicts with id, description, schedule, next_run
    """
    try:
        scheduler = get_scheduler_client()
        if not scheduler:
            return []

        parent = f"projects/{GCS_PROJECT_ID}/locations/{SCHEDULER_LOCATION}"
        jobs = []

        for job in scheduler.list_jobs(parent=parent):
            # Only include court booking jobs
            if not job.name.split('/')[-1].startswith('book-court-'):
                continue

            # Parse next run time
            next_run = None
            if job.schedule_time:
                next_run = job.schedule_time.astimezone(PST).strftime('%m/%d/%Y %I:%M %p PST')

            jobs.append({
                'id': job.name.split('/')[-1],
                'name': job.name,
                'description': job.description,
                'schedule': job.schedule,
                'next_run': next_run,
                'state': job.state.name if job.state else 'UNKNOWN'
            })

        return jobs

    except Exception as e:
        logger.error(f"Failed to list scheduler jobs: {e}", exc_info=True)
        return []


def cancel_scheduled_job(job_id: str) -> dict:
    """
    Cancel/delete a scheduled court booking job.

    Args:
        job_id: The job ID (e.g., "book-court-20250215-700pm")

    Returns:
        dict with status and message
    """
    try:
        scheduler = get_scheduler_client()
        if not scheduler:
            return {'status': 'error', 'message': 'Cloud Scheduler client not available'}

        job_name = f"projects/{GCS_PROJECT_ID}/locations/{SCHEDULER_LOCATION}/jobs/{job_id}"

        # Verify it's a court booking job
        if not job_id.startswith('book-court-'):
            return {'status': 'error', 'message': 'Can only cancel court booking jobs'}

        scheduler.delete_job(name=job_name)
        logger.info(f"Deleted scheduler job: {job_id}")

        return {'status': 'deleted', 'job_id': job_id}

    except Exception as e:
        error_msg = str(e)
        if '404' in error_msg or 'not found' in error_msg.lower():
            return {'status': 'error', 'message': f'Job not found: {job_id}'}
        logger.error(f"Failed to delete scheduler job: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


# ============================================================================
# GCS Pending Action Storage (Phase 2 Confirmation Flow)
# ============================================================================

def get_storage_client():
    """Initialize GCS client."""
    try:
        from google.cloud import storage
        return storage.Client(project=GCS_PROJECT_ID)
    except ImportError:
        logger.error("google-cloud-storage not installed")
        return None
    except Exception as e:
        logger.error(f"Failed to init storage client: {e}")
        return None


def store_pending_action(action_data: dict) -> Optional[str]:
    """
    Store a pending action in GCS with a unique token.

    Args:
        action_data: Dict containing:
            - intent: The command intent (book_court, create_poll, etc.)
            - params: The command parameters
            - chat_id: WhatsApp chat ID to reply to
            - sender: Sender info

    Returns:
        The confirmation token, or None if storage failed
    """
    try:
        client = get_storage_client()
        if not client:
            return None

        # Generate unique token
        token = secrets.token_urlsafe(32)
        now = datetime.now(PST)
        expires_at = now + timedelta(hours=24)

        blob_name = f"pending_actions/{token}.json"
        data = {
            "token": token,
            "action": action_data,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "executed": False
        }

        bucket = client.get_bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(json.dumps(data), content_type='application/json')

        logger.info(f"Stored pending action with token: {token[:16]}...")
        return token

    except Exception as e:
        logger.error(f"Failed to store pending action: {e}", exc_info=True)
        return None


def get_pending_action(token: str) -> Optional[dict]:
    """
    Retrieve a pending action from GCS.

    Args:
        token: The confirmation token

    Returns:
        The action data dict, or None if not found/expired/invalid
    """
    try:
        client = get_storage_client()
        if not client:
            return None

        blob_name = f"pending_actions/{token}.json"
        bucket = client.get_bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_name)

        if not blob.exists():
            logger.warning(f"Pending action not found: {token[:16]}...")
            return None

        data = json.loads(blob.download_as_string())

        # Check if expired
        expires_at = datetime.fromisoformat(data.get('expires_at', ''))
        if datetime.now(PST) > PST.localize(expires_at.replace(tzinfo=None)) if expires_at.tzinfo is None else expires_at:
            logger.warning(f"Pending action expired: {token[:16]}...")
            # Clean up expired action
            blob.delete()
            return None

        return data

    except Exception as e:
        logger.error(f"Failed to get pending action: {e}", exc_info=True)
        return None


def mark_action_executed(token: str) -> bool:
    """
    Mark a pending action as executed.

    Args:
        token: The confirmation token

    Returns:
        True if marked successfully, False otherwise
    """
    try:
        client = get_storage_client()
        if not client:
            return False

        blob_name = f"pending_actions/{token}.json"
        bucket = client.get_bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_name)

        if not blob.exists():
            return False

        data = json.loads(blob.download_as_string())
        data['executed'] = True
        data['executed_at'] = datetime.now(PST).isoformat()

        blob.upload_from_string(json.dumps(data), content_type='application/json')
        logger.info(f"Marked action as executed: {token[:16]}...")
        return True

    except Exception as e:
        logger.error(f"Failed to mark action executed: {e}", exc_info=True)
        return False


def delete_pending_action(token: str) -> bool:
    """
    Delete a pending action from GCS.

    Args:
        token: The confirmation token

    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        client = get_storage_client()
        if not client:
            return False

        blob_name = f"pending_actions/{token}.json"
        bucket = client.get_bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_name)

        if blob.exists():
            blob.delete()
            logger.info(f"Deleted pending action: {token[:16]}...")
            return True
        return False

    except Exception as e:
        logger.error(f"Failed to delete pending action: {e}", exc_info=True)
        return False


def generate_confirmation_url(token: str) -> str:
    """Generate the confirmation URL for a pending action."""
    base_url = PICKLEBOT_CONFIRM_URL or f"https://us-west1-{GCS_PROJECT_ID}.cloudfunctions.net/smad-picklebot"
    return f"{base_url}?action=confirm&token={token}"


# ============================================================================
# Action Execution Functions (Phase 2)
# ============================================================================

def execute_book_court(params: dict) -> dict:
    """
    Execute court booking via GitHub Actions workflow dispatch.

    Args:
        params: Booking parameters (date, time, duration, court)

    Returns:
        dict with status and message
    """
    try:
        date_str = params.get('date', '')
        time_str = params.get('time', '')
        duration = params.get('duration_minutes', 120)
        court = params.get('court', 'both')

        booking_date = parse_booking_date(date_str)
        booking_time = parse_booking_time(time_str)

        if not booking_date or not booking_time:
            return {'status': 'error', 'message': 'Invalid booking date or time'}

        # Format for workflow
        booking_datetime_str = booking_date.strftime('%m/%d/%Y') + f' {booking_time}'

        # Trigger GitHub Actions workflow
        url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/court-booking.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
        payload = {
            "ref": "main",
            "inputs": {
                "booking_date_time": booking_datetime_str,
                "court": court if court != 'both' else '',
                "duration": str(duration)
            }
        }

        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 204:
            return {
                'status': 'success',
                'message': f'Court booking triggered for {booking_datetime_str}'
            }
        else:
            return {
                'status': 'error',
                'message': f'GitHub API error: {response.status_code} - {response.text}'
            }

    except Exception as e:
        logger.error(f"Failed to execute booking: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


def execute_create_poll(params: dict) -> dict:
    """
    Execute poll creation via GitHub Actions workflow dispatch.

    Returns:
        dict with status and message
    """
    try:
        # Trigger GitHub Actions workflow
        url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/poll-creation.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
        payload = {"ref": "main"}

        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 204:
            return {
                'status': 'success',
                'message': 'Poll creation workflow triggered'
            }
        else:
            return {
                'status': 'error',
                'message': f'GitHub API error: {response.status_code} - {response.text}'
            }

    except Exception as e:
        logger.error(f"Failed to create poll: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


def execute_send_reminders(params: dict) -> dict:
    """
    Execute sending reminders via GitHub Actions workflow dispatch.

    Args:
        params: Reminder parameters (type: vote/payment)

    Returns:
        dict with status and message
    """
    try:
        reminder_type = params.get('type', 'vote')

        # Trigger GitHub Actions workflow
        url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/vote-payment-reminders.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
        payload = {
            "ref": "main",
            "inputs": {
                "send_vote_reminders": "true" if reminder_type == 'vote' else "false"
            }
        }

        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 204:
            return {
                'status': 'success',
                'message': f'{reminder_type.capitalize()} reminders workflow triggered'
            }
        else:
            return {
                'status': 'error',
                'message': f'GitHub API error: {response.status_code} - {response.text}'
            }

    except Exception as e:
        logger.error(f"Failed to send reminders: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


def execute_pending_action(action_data: dict) -> dict:
    """
    Execute a pending action based on its intent.

    Args:
        action_data: The action data from stored pending action

    Returns:
        dict with status and message
    """
    intent = action_data.get('intent', '')
    params = action_data.get('params', {})

    if intent == 'book_court':
        return execute_book_court(params)
    elif intent == 'create_poll':
        return execute_create_poll(params)
    elif intent == 'send_reminders':
        return execute_send_reminders(params)
    else:
        return {'status': 'error', 'message': f'Unknown intent: {intent}'}


def handle_list_jobs() -> str:
    """Return list of scheduled court booking jobs."""
    jobs = list_scheduled_jobs()

    if not jobs:
        return f"""*{PICKLEBOT_SIGNATURE} - Scheduled Jobs*

No scheduled court bookings found.

Use `/pb book <date> <time>` to schedule a booking."""

    message = f"*{PICKLEBOT_SIGNATURE} - Scheduled Jobs*\n\n"

    for job in jobs:
        message += f"📋 *{job['id']}*\n"
        if job['description']:
            message += f"   {job['description']}\n"
        message += f"   Schedule: {job['schedule']}\n"
        if job['next_run']:
            message += f"   Next run: {job['next_run']}\n"
        message += f"   State: {job['state']}\n\n"

    message += "_To cancel: /pb jobs cancel <job_id>_"

    return message


def handle_cancel_job(job_id: str) -> str:
    """Cancel a scheduled court booking job."""
    if not job_id:
        return f"""*{PICKLEBOT_SIGNATURE} - Cancel Job*

Please specify a job ID to cancel.

Use `/pb jobs` to see scheduled jobs."""

    result = cancel_scheduled_job(job_id)

    if result['status'] == 'error':
        return f"""*{PICKLEBOT_SIGNATURE} - Cancel Job*

Failed to cancel job: {result.get('message', 'Unknown error')}"""

    return f"""*{PICKLEBOT_SIGNATURE} - Cancel Job*

✅ Job cancelled: {job_id}

The scheduled booking has been removed."""


def handle_book_court_preview(params: dict, dry_run: bool = False) -> str:
    """
    Generate preview message for court booking.

    If booking date is >7 days in the future, offers to schedule automatic booking.
    If ≤7 days, shows confirmation preview for immediate booking.
    """
    # Extract parameters
    date_str = params.get('date', 'unknown')
    time_str = params.get('time', 'unknown')
    duration = params.get('duration_minutes', 120)
    court = params.get('court', 'both')

    # Parse the booking date
    booking_date = parse_booking_date(date_str)
    booking_time = parse_booking_time(time_str)

    if not booking_date:
        return f"""*{PICKLEBOT_SIGNATURE} - Book Court*

Could not parse booking date: "{date_str}"

Please use a format like:
- /pb book 2/4 7pm
- /pb book Feb 4 7:00 PM"""

    if not booking_time:
        return f"""*{PICKLEBOT_SIGNATURE} - Book Court*

Could not parse booking time: "{time_str}"

Please use a format like:
- /pb book 2/4 7pm
- /pb book Feb 4 7:00 PM"""

    now = datetime.now(PST)
    days_until_booking = (booking_date.date() - now.date()).days

    # Check if booking date is in the past
    if days_until_booking < 0:
        return f"""*{PICKLEBOT_SIGNATURE} - Book Court*

Cannot book a date in the past: {booking_date.strftime('%m/%d/%Y')}"""

    # Format for display
    booking_datetime_display = f"{booking_date.strftime('%A, %B %d, %Y')} at {booking_time}"

    # If booking is more than 7 days out, schedule it
    if days_until_booking > BOOKING_ADVANCE_DAYS:
        schedule_date = booking_date - timedelta(days=BOOKING_ADVANCE_DAYS)

        result = create_scheduled_booking(
            booking_date=booking_date,
            booking_time=booking_time,
            duration=duration,
            court=court,
            dry_run=dry_run
        )

        if result['status'] == 'error':
            return f"""*{PICKLEBOT_SIGNATURE} - Book Court*

Failed to schedule booking: {result.get('message', 'Unknown error')}"""

        if result['status'] == 'dry_run':
            return f"""*{PICKLEBOT_SIGNATURE} - Book Court* (DRY RUN)

Booking date is {days_until_booking} days away (>{BOOKING_ADVANCE_DAYS} days).
Would schedule automatic booking.

*Booking Details:*
📅 Date: {booking_datetime_display}
⏱️ Duration: {duration} minutes
🏓 Court: {court}

*Scheduled Job:*
🕐 Will run: {schedule_date.strftime('%A, %B %d, %Y')} at 12:01 AM PST
📋 Job ID: {result['job_id']}"""

        return f"""*{PICKLEBOT_SIGNATURE} - Book Court*

✅ *Booking Scheduled!*

Booking date is {days_until_booking} days away. Courts can only be booked {BOOKING_ADVANCE_DAYS} days in advance, so I've scheduled an automatic booking.

*Booking Details:*
📅 Date: {booking_datetime_display}
⏱️ Duration: {duration} minutes
🏓 Court: {court}

*Scheduled Job:*
🕐 Will run: {schedule_date.strftime('%A, %B %d, %Y')} at 12:01 AM PST
📋 Job ID: {result['job_id']}

The booking will be attempted automatically on the scheduled date."""

    # Booking is within 7 days - can book now (requires confirmation)
    return f"""*{PICKLEBOT_SIGNATURE} - Book Court*

This action requires confirmation.

*Booking Details:*
📅 Date: {booking_datetime_display}
⏱️ Duration: {duration} minutes
🏓 Court: {court}
📆 Days until: {days_until_booking}

_Confirmation links coming in Phase 2_"""


def handle_create_poll_preview() -> str:
    """Generate preview message for poll creation (confirmation required)."""
    return f"""*{PICKLEBOT_SIGNATURE} - Create Poll*

This action requires confirmation.

Will create a weekly availability poll in the SMAD group.

_Confirmation links coming in Phase 2_"""


def handle_send_reminders_preview(reminder_type: str) -> str:
    """Generate preview message for sending reminders (confirmation required)."""
    return f"""*{PICKLEBOT_SIGNATURE} - Send Reminders*

This action requires confirmation.

Will send {reminder_type} reminders to players who haven't responded.

_Confirmation links coming in Phase 2_"""


def process_command(command_text: str, sender_data: dict, dry_run: bool = False, is_admin_group: bool = True) -> dict:
    """Process a picklebot command and return response.

    Args:
        command_text: The command text (with or without dry run flag)
        sender_data: Sender info from webhook
        dry_run: If True, don't execute actions (external override)
        is_admin_group: If True, allow all commands. If False, block action commands.

    Returns:
        dict with message, intent, and dry_run status
    """
    # Check for dry run flag in command text
    cleaned_command, text_has_dry_run = extract_dry_run_flag(command_text)
    is_dry_run = dry_run or text_has_dry_run

    if is_dry_run:
        logger.info(f"[DRY RUN] Processing command: {cleaned_command}")
    else:
        logger.info(f"Processing command: {cleaned_command} (admin_group={is_admin_group})")

    # Parse intent from cleaned command
    intent_data = parse_intent_with_claude(cleaned_command)
    intent = intent_data.get('intent', 'unknown')
    params = intent_data.get('params', {})
    needs_confirmation = intent_data.get('confirmation_required', False)

    logger.info(f"Parsed intent: {intent}, params: {params}, needs_confirmation: {needs_confirmation}")

    # Build base result with dry_run status
    def build_result(message: str, **kwargs) -> dict:
        result = {'message': message, 'dry_run': is_dry_run}
        if is_dry_run:
            result['message'] = f"[DRY RUN]\n\n{message}"
        result.update(kwargs)
        return result

    # Define action commands that are only available in admin group
    ACTION_INTENTS = {'book_court', 'cancel_job', 'create_poll', 'send_reminders'}

    # Block action commands in non-admin groups
    if not is_admin_group and intent in ACTION_INTENTS:
        return build_result(handle_action_not_available(intent), intent=intent)

    # Handle read-only commands directly
    if intent == 'help':
        return build_result(handle_help(is_admin_group=is_admin_group), intent=intent)

    if intent == 'show_deadbeats':
        return build_result(handle_deadbeats(), intent=intent)

    if intent == 'show_balances':
        return build_result(handle_balances(params.get('player_name')), intent=intent)

    if intent == 'show_status':
        return build_result(handle_status(), intent=intent)

    if intent == 'show_games':
        return build_result(handle_show_games(), intent=intent)

    if intent == 'next_game':
        return build_result(handle_next_game(), intent=intent)

    if intent == 'list_jobs':
        return build_result(handle_list_jobs(), intent=intent)

    if intent == 'cancel_job':
        # Cancel job directly (no confirmation needed for simplicity)
        return build_result(handle_cancel_job(params.get('job_id', '')), intent=intent)

    # Fun commands
    if intent == 'tell_joke':
        return build_result(handle_tell_joke(), intent=intent)

    if intent == 'post_meme':
        chat_id = sender_data.get('chatId', ADMIN_DINKERS_GROUP_ID)
        message = handle_post_meme(chat_id, dry_run=is_dry_run)
        # If message is empty, the image was sent successfully
        if not message:
            return {'message': '', 'dry_run': is_dry_run, 'intent': intent, 'skip_reply': True}
        return build_result(message, intent=intent)

    # Handle destructive commands (show preview, require confirmation)
    if intent == 'book_court':
        # Pass dry_run to handle_book_court_preview for scheduled bookings
        message = handle_book_court_preview(params, dry_run=is_dry_run)
        # Check if booking was scheduled (>7 days out) - no confirmation needed
        if "Booking Scheduled!" in message or "(DRY RUN)" in message:
            return {'message': message, 'dry_run': is_dry_run, 'intent': intent, 'needs_confirmation': False}
        return build_result(message, intent=intent, needs_confirmation=True)

    if intent == 'create_poll':
        return build_result(handle_create_poll_preview(), intent=intent, needs_confirmation=True)

    if intent == 'send_reminders':
        return build_result(handle_send_reminders_preview(params.get('type', 'vote')), intent=intent, needs_confirmation=True)

    # Unknown command
    return build_result(handle_unknown(params.get('raw', cleaned_command)), intent='unknown')


@functions_framework.http
def picklebot_webhook(request):
    """
    HTTP Cloud Function entry point for picklebot commands.

    This can be called directly or routed from the main smad-whatsapp-webhook.
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

    if request.method != 'POST':
        return {'error': 'Method not allowed'}, 405

    try:
        data = request.get_json(silent=True)
        if not data:
            return {'error': 'No JSON payload'}, 400

        # Check for dry_run and is_admin_group parameters in request
        dry_run = data.get('dry_run', False)
        is_admin_group = data.get('is_admin_group', True)  # Default to admin for backward compatibility

        # Check if this is a direct command (from routing) or a webhook payload
        if 'command' in data:
            # Direct routing from smad-whatsapp-webhook
            command_text = data['command']
            chat_id = data.get('chatId', ADMIN_DINKERS_GROUP_ID)
            sender_data = {
                'chatId': chat_id,
                'sender': data.get('sender', ''),
                'senderName': data.get('senderName', '')
            }
        else:
            # Full GREEN-API webhook payload (direct call to picklebot)
            sender_data = data.get('senderData', {})
            message_data = data.get('messageData', {})
            chat_id = sender_data.get('chatId', '')

            # For direct webhook calls, only allow from Admin Dinkers group
            if ADMIN_DINKERS_GROUP_ID and chat_id != ADMIN_DINKERS_GROUP_ID:
                return {'status': 'ignored', 'reason': 'not_admin_group'}, 200

            is_admin_group = True  # Direct webhook calls are from admin group

            # Extract text message
            type_message = message_data.get('typeMessage', '')
            if type_message != 'textMessage':
                return {'status': 'ignored', 'reason': 'not_text_message'}, 200

            text = message_data.get('textMessageData', {}).get('textMessage', '')

            # Check for command prefix
            is_command = False
            for prefix in COMMAND_PREFIXES:
                if text.lower().startswith(prefix.lower()):
                    is_command = True
                    break

            if not is_command:
                return {'status': 'ignored', 'reason': 'not_command'}, 200

            command_text = text

        # Process the command
        result = process_command(command_text, sender_data, dry_run=dry_run, is_admin_group=is_admin_group)

        # Get effective dry_run status (could be from param or command text)
        is_dry_run = result.get('dry_run', dry_run)

        # Send response to group (skipped in dry run mode or if skip_reply is set)
        if result.get('message') and not result.get('skip_reply'):
            send_whatsapp_message(chat_id or ADMIN_DINKERS_GROUP_ID, result['message'], dry_run=is_dry_run)

        return {
            'status': 'processed',
            'intent': result.get('intent'),
            'needs_confirmation': result.get('needs_confirmation', False),
            'dry_run': is_dry_run,
            'response_message': result.get('message') if is_dry_run else None
        }, 200

    except Exception as e:
        logger.error(f"Picklebot error: {e}", exc_info=True)
        return {'error': str(e)}, 500


# For local testing
if __name__ == '__main__':
    # Test intent parsing
    test_commands = [
        "/pb help",
        "/pb deadbeats",
        "/pb balance John",
        "/pb book 2/4 7pm 2hrs",
        "/pb poll create",
        "/pb status",
    ]

    for cmd in test_commands:
        print(f"\nCommand: {cmd}")
        result = parse_intent_fallback(cmd)
        print(f"Result: {json.dumps(result, indent=2)}")
