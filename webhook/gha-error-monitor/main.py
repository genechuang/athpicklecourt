"""
GitHub Actions Error Monitor Cloud Function

Monitors GitHub Actions workflow failures and sends diagnostic reports via WhatsApp.
Uses Claude API for intelligent error diagnosis with fallback to simple parsing.

Trigger: GitHub webhook (workflow_run.completed event)
Notifications: WhatsApp DM to admin + Admin Dinkers group

Environment Variables:
    GITHUB_TOKEN: GitHub personal access token (repo scope)
    ANTHROPIC_API_KEY: Anthropic API key for Claude diagnosis
    GREENAPI_INSTANCE_ID: GREEN-API instance ID
    GREENAPI_API_TOKEN: GREEN-API API token
    ADMIN_DINKERS_WHATSAPP_GROUP_ID: Admin group for notifications
    ADMIN_PHONE_ID: Admin phone ID for personal DM (format: 1234567890@c.us)
    GITHUB_REPO: Repository name (e.g., genechuang/SMADPickleBot)
"""

import os
import json
import logging
import hmac
import hashlib
import requests
from datetime import datetime
import pytz
from google.cloud import storage

import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PST timezone
PST = pytz.timezone('America/Los_Angeles')

# Configuration from environment
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_WEBHOOK_SECRET = os.environ.get('GITHUB_WEBHOOK_SECRET', '')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'genechuang/SMADPickleBot')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
GREENAPI_INSTANCE_ID = os.environ.get('GREENAPI_INSTANCE_ID', '')
GREENAPI_API_TOKEN = os.environ.get('GREENAPI_API_TOKEN', '')
ADMIN_DINKERS_GROUP_ID = os.environ.get('ADMIN_DINKERS_WHATSAPP_GROUP_ID', '')
ADMIN_PHONE_ID = os.environ.get('ADMIN_PHONE_ID', '')  # Personal DM recipient

# Maximum log size to send to Claude (to control costs)
MAX_LOG_SIZE = 15000  # ~15KB, roughly 3-4K tokens

# Workflows to check for booking failures even when successful
BOOKING_WORKFLOWS = ['Court Booking']

# Screenshot filename to look for in booking failures
BOOKING_FAILURE_SCREENSHOT = 'booking_no_slot_found.png'

# GCS bucket for screenshot storage
GCS_BUCKET_NAME = 'smad-pickleball-screenshots'
GCS_PROJECT_ID = 'smad-pickleball'

# Patterns indicating booking failures in logs
BOOKING_FAILURE_PATTERNS = [
    'NO AVAILABLE SLOT FOUND',
    'booking may have failed',
    'Could not find an available',
    'Failed: ',  # e.g., "Failed: 1"
]


def fetch_screenshot_artifact(run_id: int, filename: str = BOOKING_FAILURE_SCREENSHOT) -> bytes | None:
    """Fetch a screenshot from workflow artifacts.

    Args:
        run_id: The workflow run ID
        filename: The screenshot filename to look for

    Returns:
        Image bytes if found, None otherwise
    """
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN not configured")
        return None

    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }

    # List artifacts for this run
    artifacts_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/artifacts"

    try:
        response = requests.get(artifacts_url, headers=headers, timeout=30)

        if response.status_code != 200:
            logger.warning(f"Failed to list artifacts: {response.status_code}")
            return None

        artifacts = response.json().get('artifacts', [])

        # Find the booking-screenshots artifact
        screenshot_artifact = None
        for artifact in artifacts:
            if 'booking-screenshots' in artifact.get('name', ''):
                screenshot_artifact = artifact
                break

        if not screenshot_artifact:
            logger.info("No booking-screenshots artifact found")
            return None

        # Download the artifact
        download_url = screenshot_artifact.get('archive_download_url')
        if not download_url:
            return None

        logger.info(f"Downloading artifact: {screenshot_artifact.get('name')}")
        download_response = requests.get(download_url, headers=headers, allow_redirects=True, timeout=60)

        if download_response.status_code != 200:
            logger.warning(f"Failed to download artifact: {download_response.status_code}")
            return None

        # Extract the specific file from the zip
        import zipfile
        import io

        with zipfile.ZipFile(io.BytesIO(download_response.content)) as z:
            for name in z.namelist():
                if name.endswith(filename) or name == filename:
                    logger.info(f"Found screenshot: {name}")
                    return z.read(name)

        logger.info(f"Screenshot {filename} not found in artifact")
        return None

    except Exception as e:
        logger.error(f"Error fetching screenshot artifact: {e}")
        return None


def upload_screenshot_to_gcs(image_bytes: bytes, run_id: int) -> str | None:
    """Upload screenshot to Google Cloud Storage and return public URL.

    Args:
        image_bytes: The image data
        run_id: Workflow run ID (used for unique filename)

    Returns:
        Public URL to the uploaded image, or None if failed
    """
    try:
        # Create storage client
        client = storage.Client(project=GCS_PROJECT_ID)

        # Get bucket (should already exist with public access via IAM)
        bucket = client.get_bucket(GCS_BUCKET_NAME)

        # Generate unique filename with timestamp
        timestamp = datetime.now(PST).strftime('%Y%m%d_%H%M%S')
        blob_name = f"booking_failures/{timestamp}_run{run_id}.png"

        # Upload the image
        blob = bucket.blob(blob_name)
        blob.upload_from_string(image_bytes, content_type='image/png')

        # Get public URL (bucket has uniform bucket-level access with allUsers read)
        public_url = blob.public_url
        logger.info(f"Screenshot uploaded to GCS: {public_url}")
        return public_url

    except Exception as e:
        logger.error(f"Error uploading screenshot to GCS: {e}")
        return None


def verify_github_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature."""
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET not set, skipping signature verification")
        return True

    if not signature:
        return False

    expected = 'sha256=' + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def fetch_workflow_logs(run_id: int, filter_errors: bool = True, for_booking: bool = False) -> str:
    """Fetch workflow run logs from GitHub API.

    Args:
        run_id: The workflow run ID
        filter_errors: If True, only return logs containing error/failed keywords.
                      If False, return all logs (useful for checking booking status).
        for_booking: If True, prioritize booking script logs to avoid truncation issues.
    """
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN not configured")
        return ""

    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }

    # Get the logs URL
    logs_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/logs"

    try:
        response = requests.get(logs_url, headers=headers, allow_redirects=True, timeout=30)

        if response.status_code == 200:
            # Logs are returned as a zip file, we need to extract them
            import zipfile
            import io

            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                all_logs = []

                # For booking checks, prioritize the booking script log file
                if for_booking:
                    # Look for the specific step log with booking script output
                    # Prefer individual step logs over combined logs (0_*.txt) which are too large
                    script_log = None
                    step_logs = []
                    combined_logs = []
                    other_logs = []

                    for name in z.namelist():
                        if name.endswith('.txt'):
                            with z.open(name) as f:
                                log_content = f.read().decode('utf-8', errors='ignore')

                                # Identify log type
                                if 'Run booking script' in name or 'booking script' in name.lower():
                                    # This is the specific step log we want most
                                    script_log = f"=== {name} ===\n{log_content}"
                                elif name.startswith('0_'):
                                    # Combined log file - use as fallback only
                                    combined_logs.append(f"=== {name} ===\n{log_content}")
                                elif 'book' in name.lower():
                                    # Other booking-related step logs
                                    step_logs.append(f"=== {name} ===\n{log_content}")
                                elif not filter_errors or 'error' in log_content.lower() or 'failed' in log_content.lower():
                                    other_logs.append(f"=== {name} ===\n{log_content}")

                    # Build log list: specific script log first, then other steps, then combined
                    if script_log:
                        all_logs = [script_log] + step_logs + other_logs
                    else:
                        all_logs = step_logs + combined_logs + other_logs
                else:
                    for name in z.namelist():
                        if name.endswith('.txt'):
                            with z.open(name) as f:
                                log_content = f.read().decode('utf-8', errors='ignore')
                                if filter_errors:
                                    # Look for error indicators
                                    if 'error' in log_content.lower() or 'failed' in log_content.lower():
                                        all_logs.append(f"=== {name} ===\n{log_content}")
                                else:
                                    # Include all logs
                                    all_logs.append(f"=== {name} ===\n{log_content}")

                if all_logs:
                    combined = '\n\n'.join(all_logs)
                    # Truncate if too long
                    if len(combined) > MAX_LOG_SIZE:
                        combined = combined[:MAX_LOG_SIZE] + "\n\n[... truncated ...]"
                    return combined

        logger.warning(f"Failed to fetch logs: {response.status_code}")
        return ""

    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        return ""


def fetch_failed_jobs(run_id: int) -> list:
    """Fetch failed job details from GitHub API."""
    if not GITHUB_TOKEN:
        return []

    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }

    jobs_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/jobs"

    try:
        response = requests.get(jobs_url, headers=headers, timeout=30)

        if response.status_code == 200:
            jobs_data = response.json()
            failed_jobs = []

            for job in jobs_data.get('jobs', []):
                if job.get('conclusion') == 'failure':
                    failed_steps = []
                    for step in job.get('steps', []):
                        if step.get('conclusion') == 'failure':
                            failed_steps.append({
                                'name': step.get('name', 'Unknown'),
                                'number': step.get('number', 0)
                            })

                    failed_jobs.append({
                        'name': job.get('name', 'Unknown'),
                        'id': job.get('id'),
                        'failed_steps': failed_steps
                    })

            return failed_jobs

        return []

    except Exception as e:
        logger.error(f"Error fetching jobs: {e}")
        return []


def detect_booking_failures(logs: str) -> dict:
    """Detect booking failures from workflow logs.

    Returns:
        dict with 'has_failures', 'failed_bookings' list, 'successful_bookings' count,
        and 'failure_reason' if detected from logs
    """
    result = {
        'has_failures': False,
        'failed_bookings': [],
        'successful_count': 0,
        'failed_count': 0,
        'failure_reason': None  # Extracted from logs if available
    }

    if not logs:
        return result

    import re

    # Check for booking failure patterns
    for pattern in BOOKING_FAILURE_PATTERNS:
        if pattern in logs:
            result['has_failures'] = True
            break

    if not result['has_failures']:
        return result

    # Try to extract specific failure reason from logs
    # Priority 1: Check for countdown (court not released yet)
    # Try multiple patterns - court-booking.py logs in different formats
    countdown_match = re.search(r'Countdown:\s*(.+?until\s+reservations\s+open)', logs, re.IGNORECASE)
    if countdown_match:
        countdown_text = countdown_match.group(1).strip()
        result['failure_reason'] = f"Court not yet released - {countdown_text}"
        logger.info(f"Extracted failure reason from logs: {result['failure_reason']}")

    # Also check for COURT_NOT_RELEASED prefix
    if not result['failure_reason']:
        not_released_match = re.search(r'COURT_NOT_RELEASED:\s*(.+)', logs)
        if not_released_match:
            result['failure_reason'] = f"Court not yet released - {not_released_match.group(1).strip()}"
            logger.info(f"Extracted failure reason from logs: {result['failure_reason']}")

    # Also check for the fallback "reservations not open" message
    if not result['failure_reason']:
        if 'Court not yet released (reservations not open)' in logs or 'reservations not yet open' in logs.lower():
            result['failure_reason'] = "Court not yet released - reservations not open for this date"
            logger.info(f"Extracted failure reason from logs: {result['failure_reason']}")

    # Priority 2: Check for "already reserved by you" (blue box with Edit)
    if not result['failure_reason']:
        already_reserved_match = re.search(r'ALREADY_RESERVED:\s*(.+)', logs)
        if already_reserved_match:
            result['failure_reason'] = already_reserved_match.group(1).strip()
            logger.info(f"Extracted failure reason from logs: {result['failure_reason']}")

    # Priority 3: Check for "booked by others" (gray/white text, no link)
    if not result['failure_reason']:
        booked_match = re.search(r'BOOKED_BY_OTHERS:\s*(.+)', logs)
        if booked_match:
            result['failure_reason'] = f"Already booked by someone else - {booked_match.group(1).strip()}"
            logger.info(f"Extracted failure reason from logs: {result['failure_reason']}")

    # Extract failed booking details
    # Look for patterns like:
    #   Court: North Pickleball Court
    #   Time: 9:00 AM
    #   Date: 02/06/2026

    # Find the "NO AVAILABLE SLOT FOUND" sections and extract details
    lines = logs.split('\n')
    current_booking = {}

    for i, line in enumerate(lines):
        # Look for court name
        if 'Booking court:' in line:
            match = re.search(r'Booking court:\s*(.+)', line)
            if match:
                current_booking['court'] = match.group(1).strip()

        # Look for date in booking attempt
        if 'Date:' in line and 'Date:' in line:
            match = re.search(r'Date:\s*(\d{2}/\d{2}/\d{4})', line)
            if match:
                current_booking['date'] = match.group(1)

        # Look for time
        if 'Time:' in line:
            match = re.search(r'Time:\s*(\d{1,2}:\d{2}\s*[AP]M)', line)
            if match:
                current_booking['time'] = match.group(1)

        # When we hit "NO AVAILABLE SLOT FOUND", capture the booking as failed
        if 'NO AVAILABLE SLOT FOUND' in line:
            if current_booking:
                result['failed_bookings'].append(current_booking.copy())
            current_booking = {}

    # Extract success/fail counts from summary
    # Look for "Successful: 0" and "Failed: 1" patterns
    success_match = re.search(r'Successful:\s*(\d+)', logs)
    if success_match:
        result['successful_count'] = int(success_match.group(1))

    fail_match = re.search(r'Failed:\s*(\d+)', logs)
    if fail_match:
        result['failed_count'] = int(fail_match.group(1))

    return result


def diagnose_booking_failure(logs: str, booking_info: dict) -> str:
    """Generate diagnosis for booking failure using Claude or simple parsing."""
    if not ANTHROPIC_API_KEY:
        return simple_booking_diagnosis(logs, booking_info)

    prompt = f"""Analyze this court booking failure and provide a brief explanation.

Failed bookings: {len(booking_info.get('failed_bookings', []))}
Successful bookings: {booking_info.get('successful_count', 0)}

Logs:
{logs[-5000:]}  # Last 5KB of logs

Provide a 1-2 sentence explanation of why the booking(s) failed.
Common reasons: court not yet released (>7 days out), already booked, time slot unavailable.
Keep response under 200 characters."""

    try:
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': 'claude-3-haiku-20240307',
                'max_tokens': 150,
                'messages': [
                    {'role': 'user', 'content': prompt}
                ]
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            return result.get('content', [{}])[0].get('text', '')

    except Exception as e:
        logger.error(f"Claude booking diagnosis failed: {e}")

    return simple_booking_diagnosis(logs, booking_info)


def simple_booking_diagnosis(logs: str, booking_info: dict) -> str:
    """Simple diagnosis for booking failures."""
    logs_lower = logs.lower()

    if 'already booked' in logs_lower or 'gray text' in logs_lower:
        return "Court already booked by someone else"
    elif '>7 days' in logs_lower or 'not yet released' in logs_lower:
        return "Court not yet released (>7 days out)"
    elif 'no link' in logs_lower or 'not clickable' in logs_lower:
        return "Time slot not available for booking"
    else:
        return "Court/time slot unavailable"


def diagnose_with_claude(workflow_name: str, logs: str, failed_jobs: list) -> str:
    """Use Claude API to diagnose the error."""
    if not ANTHROPIC_API_KEY:
        logger.info("ANTHROPIC_API_KEY not configured, using simple diagnosis")
        return None

    # Build context about what failed
    job_context = ""
    if failed_jobs:
        job_context = "Failed jobs:\n"
        for job in failed_jobs:
            job_context += f"- {job['name']}\n"
            for step in job.get('failed_steps', []):
                job_context += f"  - Step {step['number']}: {step['name']}\n"

    prompt = f"""Analyze this GitHub Actions workflow failure and provide a concise diagnosis.

Workflow: {workflow_name}
{job_context}

Logs:
{logs}

Provide a brief diagnosis (2-3 sentences max) explaining:
1. What failed
2. The likely root cause
3. Suggested fix (if obvious)

Keep the response under 500 characters for WhatsApp."""

    try:
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': 'claude-3-haiku-20240307',  # Fast and cheap
                'max_tokens': 300,
                'messages': [
                    {'role': 'user', 'content': prompt}
                ]
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            diagnosis = result.get('content', [{}])[0].get('text', '')
            logger.info("Claude diagnosis successful")
            return diagnosis
        elif response.status_code == 429 or response.status_code == 402:
            # Rate limited or out of credits
            logger.warning(f"Claude API returned {response.status_code}, falling back to simple diagnosis")
            return None
        else:
            logger.warning(f"Claude API error: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logger.error(f"Claude API request failed: {e}")
        return None


def simple_diagnosis(logs: str, failed_jobs: list) -> str:
    """Simple error parsing when Claude is unavailable."""
    diagnosis_parts = []

    # Extract job/step failures
    if failed_jobs:
        job_names = [job['name'] for job in failed_jobs]
        diagnosis_parts.append(f"Failed jobs: {', '.join(job_names)}")

    # Look for common error patterns
    error_patterns = [
        ('Element is not attached to the DOM', 'DOM element detached - page likely changed during interaction'),
        ('TimeoutError', 'Operation timed out - possible network or page load issue'),
        ('ECONNREFUSED', 'Connection refused - service might be down'),
        ('Authentication failed', 'Authentication error - check credentials'),
        ('rate limit', 'Rate limited - too many requests'),
        ('permission denied', 'Permission denied - check access rights'),
        ('not found', 'Resource not found - check paths/URLs'),
        ('ModuleNotFoundError', 'Missing Python module - check requirements.txt'),
        ('SyntaxError', 'Python syntax error in code'),
    ]

    logs_lower = logs.lower()
    for pattern, description in error_patterns:
        if pattern.lower() in logs_lower:
            diagnosis_parts.append(description)
            break

    if not diagnosis_parts:
        diagnosis_parts.append("Unknown error - check logs for details")

    return '. '.join(diagnosis_parts)


def send_whatsapp_message(recipient_id: str, message: str) -> bool:
    """Send WhatsApp message via GREEN-API."""
    if not GREENAPI_INSTANCE_ID or not GREENAPI_API_TOKEN:
        logger.error("GREEN-API credentials not configured")
        return False

    if not recipient_id:
        logger.warning("No recipient ID provided")
        return False

    url = f"https://api.green-api.com/waInstance{GREENAPI_INSTANCE_ID}/sendMessage/{GREENAPI_API_TOKEN}"

    try:
        response = requests.post(
            url,
            json={
                'chatId': recipient_id,
                'message': message
            },
            timeout=30
        )

        if response.status_code == 200:
            logger.info(f"Message sent to {recipient_id}")
            return True
        else:
            logger.error(f"Failed to send message: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"WhatsApp send failed: {e}")
        return False


def build_alert_message(workflow_name: str, run_id: int, run_url: str,
                        diagnosis: str, failed_jobs: list) -> str:
    """Build the WhatsApp alert message."""
    now = datetime.now(PST)
    timestamp = now.strftime('%m/%d/%y %I:%M %p PST')

    # Build failed steps list
    steps_text = ""
    if failed_jobs:
        for job in failed_jobs:
            for step in job.get('failed_steps', []):
                steps_text += f"  - {step['name']}\n"

    message = f"""[GHA ALERT] Workflow Failed

Workflow: {workflow_name}
Time: {timestamp}
"""

    if steps_text:
        message += f"\nFailed Steps:\n{steps_text}"

    message += f"\nDiagnosis:\n{diagnosis}"

    message += f"\n\nRun: {run_url}"

    return message


def build_booking_failure_message(workflow_name: str, run_url: str,
                                   booking_info: dict, diagnosis: str,
                                   screenshot_url: str = None) -> str:
    """Build WhatsApp alert message for booking failures."""
    now = datetime.now(PST)
    timestamp = now.strftime('%m/%d/%y %I:%M %p PST')

    failed_bookings = booking_info.get('failed_bookings', [])
    successful_count = booking_info.get('successful_count', 0)
    failed_count = booking_info.get('failed_count', 0)

    message = f"""[BOOKING ALERT] Court Booking Failed

Time: {timestamp}
"""

    # Summary
    if successful_count > 0 or failed_count > 0:
        message += f"Results: {successful_count} successful, {failed_count} failed\n"

    # List failed bookings
    if failed_bookings:
        message += "\nFailed:\n"
        for booking in failed_bookings[:5]:  # Limit to 5
            court = booking.get('court', 'Unknown')
            date = booking.get('date', '')
            time = booking.get('time', '')
            message += f"  - {court}"
            if date:
                message += f" on {date}"
            if time:
                message += f" at {time}"
            message += "\n"

    message += f"\nReason: {diagnosis}"

    # Add screenshot link if available
    if screenshot_url:
        message += f"\n\nScreenshot: {screenshot_url}"

    message += f"\n\nRun: {run_url}"

    return message


@functions_framework.http
def gha_error_monitor(request):
    """
    HTTP Cloud Function entry point.
    Receives webhooks from GitHub.
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type, X-Hub-Signature-256',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    # Only accept POST
    if request.method != 'POST':
        return {'error': 'Method not allowed'}, 405

    # Verify GitHub signature
    raw_payload = request.get_data()
    signature = request.headers.get('X-Hub-Signature-256', '')

    if not verify_github_signature(raw_payload, signature):
        logger.warning("Invalid GitHub signature")
        return {'error': 'Invalid signature'}, 403

    # Check event type
    event_type = request.headers.get('X-GitHub-Event', '')
    if event_type != 'workflow_run':
        logger.info(f"Ignoring event type: {event_type}")
        return {'status': 'ignored', 'event': event_type}, 200

    try:
        data = request.get_json(silent=True)
        if not data:
            return {'error': 'No JSON payload'}, 400

        # Check if this is a completed workflow
        action = data.get('action', '')
        if action != 'completed':
            logger.info(f"Ignoring action: {action}")
            return {'status': 'ignored', 'action': action}, 200

        workflow_run = data.get('workflow_run', {})
        conclusion = workflow_run.get('conclusion', '')
        workflow_name = workflow_run.get('name', 'Unknown')
        run_id = workflow_run.get('id', 0)
        run_url = workflow_run.get('html_url', '')

        # Handle workflow failures (actual crashes/errors)
        if conclusion == 'failure':
            logger.info(f"Processing failed workflow: {workflow_name} (run {run_id})")

            # Fetch failed job details
            failed_jobs = fetch_failed_jobs(run_id)

            # Fetch logs (filter for error-related content)
            logs = fetch_workflow_logs(run_id, filter_errors=True)

            # Get diagnosis (try Claude first, fall back to simple)
            diagnosis = diagnose_with_claude(workflow_name, logs, failed_jobs)
            if not diagnosis:
                diagnosis = simple_diagnosis(logs, failed_jobs)

            # Build alert message
            alert_message = build_alert_message(
                workflow_name=workflow_name,
                run_id=run_id,
                run_url=run_url,
                diagnosis=diagnosis,
                failed_jobs=failed_jobs
            )

            # Send notifications
            sent_group = send_whatsapp_message(ADMIN_DINKERS_GROUP_ID, alert_message) if ADMIN_DINKERS_GROUP_ID else False
            sent_dm = send_whatsapp_message(ADMIN_PHONE_ID, alert_message) if ADMIN_PHONE_ID else False

            logger.info(f"Workflow failure alert sent: group={sent_group}, dm={sent_dm}")
            return {
                'status': 'processed',
                'type': 'workflow_failure',
                'workflow': workflow_name,
                'run_id': run_id,
                'diagnosis': diagnosis,
                'notifications': {'group': sent_group, 'dm': sent_dm}
            }, 200

        # Handle successful workflows - check for booking failures
        if conclusion == 'success' and workflow_name in BOOKING_WORKFLOWS:
            logger.info(f"Checking successful {workflow_name} for booking failures (run {run_id})")

            # Fetch logs with booking-script priority to avoid truncation issues
            logs = fetch_workflow_logs(run_id, filter_errors=False, for_booking=True)

            # Detect booking failures
            booking_info = detect_booking_failures(logs)

            if booking_info['has_failures']:
                logger.info(f"Booking failures detected: {booking_info['failed_count']} failed")

                # Try to fetch screenshot artifact
                screenshot_bytes = fetch_screenshot_artifact(run_id, BOOKING_FAILURE_SCREENSHOT)
                screenshot_url = None

                # Upload screenshot to GCS if available
                if screenshot_bytes:
                    logger.info(f"Screenshot found: {len(screenshot_bytes)} bytes")
                    screenshot_url = upload_screenshot_to_gcs(screenshot_bytes, run_id)

                # Determine diagnosis - prefer log-extracted reason (free & fast)
                if booking_info.get('failure_reason'):
                    # Use the reason extracted from logs (no API call needed)
                    diagnosis = booking_info['failure_reason']
                    logger.info(f"Using log-extracted diagnosis: {diagnosis}")
                else:
                    # Fall back to text-only Claude or simple diagnosis
                    logger.info("No specific reason in logs, using text-only diagnosis")
                    diagnosis = diagnose_booking_failure(logs, booking_info)

                # Build booking failure alert (includes screenshot URL if available)
                alert_message = build_booking_failure_message(
                    workflow_name=workflow_name,
                    run_url=run_url,
                    booking_info=booking_info,
                    diagnosis=diagnosis,
                    screenshot_url=screenshot_url
                )

                # Send notifications
                sent_group = False
                sent_dm = False

                if ADMIN_DINKERS_GROUP_ID:
                    sent_group = send_whatsapp_message(ADMIN_DINKERS_GROUP_ID, alert_message)

                if ADMIN_PHONE_ID:
                    sent_dm = send_whatsapp_message(ADMIN_PHONE_ID, alert_message)

                logger.info(f"Booking failure alert sent: group={sent_group}, dm={sent_dm}, screenshot_url={screenshot_url is not None}")
                return {
                    'status': 'processed',
                    'type': 'booking_failure',
                    'workflow': workflow_name,
                    'run_id': run_id,
                    'booking_info': booking_info,
                    'diagnosis': diagnosis,
                    'screenshot_url': screenshot_url,
                    'notifications': {
                        'group': sent_group,
                        'dm': sent_dm
                    }
                }, 200
            else:
                logger.info(f"No booking failures detected in {workflow_name}")
                return {'status': 'ignored', 'reason': 'all_bookings_successful'}, 200

        # Ignore other successful workflows
        logger.info(f"Workflow conclusion: {conclusion} (not monitored)")
        return {'status': 'ignored', 'conclusion': conclusion}, 200

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return {'error': str(e)}, 500


# For local testing
if __name__ == '__main__':
    # Test with sample data
    test_payload = {
        'action': 'completed',
        'workflow_run': {
            'id': 12345,
            'name': 'Court Booking',
            'conclusion': 'failure',
            'html_url': 'https://github.com/genechuang/SMADPickleBot/actions/runs/12345'
        }
    }

    # Mock request
    class MockRequest:
        method = 'POST'
        headers = {'X-GitHub-Event': 'workflow_run'}
        def get_data(self):
            return json.dumps(test_payload).encode()
        def get_json(self, silent=False):
            return test_payload

    result, status = gha_error_monitor(MockRequest())
    print(f"Status: {status}")
    print(f"Result: {json.dumps(result, indent=2)}")
