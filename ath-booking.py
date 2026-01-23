r"""
Athenaeum Pickleball Court Booking Automation - Playwright Version

This script automates logging into the Athenaeum website and booking a pickleball court.
Playwright provides better JavaScript handling and more reliable automation.

Windows 11 Installation:
1. Open PowerShell or Command Prompt
2. python -m venv venv
3. venv\Scripts\activate
4. pip install playwright python-dotenv pytz
5. python -m playwright install chromium

Configuration:
1. Create a .env file in the same folder as this script
2. Add your credentials (see .env.example)
3. Never commit .env to git!
"""

import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json
import os
import sys
import pytz
from pathlib import Path

# Import common email service
from email_service import send_booking_notification

# Load environment variables from .env file
load_dotenv()


# ==================== TWELVE-FACTOR APP UTILITIES ====================

def log(message, level='INFO', **kwargs):
    """
    Structured logging following twelve-factor app principles.
    Outputs JSON-formatted logs to stdout/stderr for better parsing and monitoring.

    Args:
        message: Log message
        level: Log level (INFO, WARN, ERROR, DEBUG) - defaults to INFO
        **kwargs: Additional structured data to include in log
    """
    log_entry = {
        "timestamp": datetime.now(pytz.UTC).isoformat(),
        "level": level.upper(),
        "message": message,
        **kwargs
    }
    output = sys.stderr if level.upper() == "ERROR" else sys.stdout
    print(json.dumps(log_entry), file=output, flush=True)


# ==================== END TWELVE-FACTOR UTILITIES ====================


def prepare_booking_list_mode(booking_list_str, invoke_time, target_time_str):
    """
    Prepare booking list for automated daily scheduling.

    Args:
        booking_list_str: BOOKING_LIST environment variable
        invoke_time: Invoke timestamp string (MM-DD-YYYY HH:MM:SS) or None
        target_time_str: Target booking time (HH:MM:SS)

    Returns:
        tuple: (to_book_list, booking_date, target_hour, target_minute, target_second, should_wait)
        - to_book_list: List of (day_of_week, time_str) tuples to book
        - booking_date: Date to book (7 days from target time)
        - target_hour, target_minute, target_second: Parsed target time components
        - should_wait: Whether to wait for target time before booking
    """
    pst_tz = pytz.timezone('America/Los_Angeles')

    # Determine the reference datetime for day-of-week matching
    if invoke_time:
        log(f"Script invoked at: {invoke_time} PST/PDT", 'INFO')
        try:
            invoke_datetime_naive = datetime.strptime(invoke_time, "%m-%d-%Y %H:%M:%S")
            invoke_datetime_pst = pst_tz.localize(invoke_datetime_naive)
            log(f"Processing with PST/PDT time: {invoke_datetime_pst.strftime('%m/%d/%Y %H:%M:%S %Z')}", 'INFO')
        except Exception as e:
            log(f"ERROR: Failed to parse invoke_time '{invoke_time}': {e}", 'ERROR')
            return None
    else:
        log("No invoke_time provided, using current PST time", 'INFO')
        invoke_datetime_pst = datetime.now(pst_tz)
        log(f"Current PST time: {invoke_datetime_pst.strftime('%m/%d/%Y %H:%M:%S %Z')}", 'INFO')

    log(f"BOOKING_LIST: {booking_list_str}", 'INFO')

    # Parse target booking time FIRST (before day-of-week matching)
    try:
        time_parts = target_time_str.split(':')
        target_hour = int(time_parts[0])
        target_minute = int(time_parts[1])
        target_second = int(time_parts[2])
        log(f"\nTarget booking time: {target_hour:02d}:{target_minute:02d}:{target_second:02d} PST", 'INFO')
    except (ValueError, IndexError) as e:
        log(f"\n! Invalid BOOKING_TARGET_TIME format: '{target_time_str}', using default 00:01:00", 'ERROR')
        target_hour, target_minute, target_second = 0, 1, 0

    # Calculate target booking datetime (handles midnight boundary)
    # Use invoke_datetime if available, otherwise use current time
    reference_time = invoke_datetime_pst if invoke_time else datetime.now(pst_tz)
    target_booking_datetime = reference_time.replace(hour=target_hour, minute=target_minute, second=target_second, microsecond=0)

    # Handle midnight boundary: if target time is earlier than reference time by more than 12 hours,
    # it means target is tomorrow (e.g., 11:56 PM -> 12:00:15 AM next day)
    if target_booking_datetime < reference_time and (reference_time - target_booking_datetime).total_seconds() > 12 * 3600:
        target_booking_datetime = target_booking_datetime + timedelta(days=1)
    elif target_booking_datetime > reference_time:
        pass  # target_booking_datetime is already correct

    log(f"Reference time for day matching: {reference_time.strftime('%m/%d/%Y %I:%M:%S %p %Z')}", 'INFO')
    log(f"Target booking time: {target_booking_datetime.strftime('%m/%d/%Y %I:%M:%S %p %Z')}", 'INFO')

    # Calculate the actual booking datetime (7 days from target booking time)
    # Day-of-week matching should be against THIS date, not the current date
    # This ensures we book for the first occurrence of the desired day that is 7+ days away
    booking_datetime = target_booking_datetime + timedelta(days=7)
    booking_date = booking_datetime.strftime('%m/%d/%Y')

    log(f"Booking datetime (7 days from target): {booking_datetime.strftime('%A %m/%d/%Y %I:%M:%S %p %Z')}", 'INFO')
    log(f"Day-of-week matching against: {booking_datetime.strftime('%A')}", 'INFO')

    # Get list of bookings for the booking day's day-of-week (7 days from now)
    # This matches against the actual day we're trying to book, not today
    to_book_list = get_booking_list(booking_list_str, booking_datetime)

    if not to_book_list:
        log("\n[INFO] No bookings scheduled for this day. Exiting.", 'INFO')
        return None

    log(f"\n=== Bookings to make for {booking_datetime.strftime('%A')} ===", 'INFO')
    for idx, (_day_of_week, time_str, court_name) in enumerate(to_book_list, 1):
        if court_name:
            log(f"  {idx}. {time_str} -> Court: {court_name}", 'INFO')
        else:
            log(f"  {idx}. {time_str}", 'INFO')

    return (to_book_list, booking_date)


def prepare_manual_booking_mode(booking_date_time_str, booking_date_override=None, booking_time_override=None):
    """
    Prepare single booking for manual mode.

    Args:
        booking_date_time_str: BOOKING_DATE_TIME environment variable
        booking_date_override: Optional booking date from command-line
        booking_time_override: Optional booking time from command-line

    Returns:
        tuple: (to_book_list, booking_date) or None on error
        - to_book_list: List with single (None, time_str) tuple
        - booking_date: Date to book
    """
    try:
        parts = booking_date_time_str.rsplit(' ', 2)
        if len(parts) == 3:
            date_part = parts[0]  # MM/DD/YYYY
            time_part = f"{parts[1]} {parts[2]}"  # HH:MM AM/PM
            booking_date = booking_date_override or date_part
            booking_time = booking_time_override or time_part
            log(f"Using BOOKING_DATE_TIME: {booking_date_time_str}", 'INFO')
        else:
            raise ValueError("Invalid format - expected 'MM/DD/YYYY HH:MM AM/PM'")
    except Exception as e:
        log(f"[ERROR] Failed to parse BOOKING_DATE_TIME '{booking_date_time_str}': {e}", 'ERROR')
        log("[ERROR] Please set BOOKING_DATE_TIME in format: MM/DD/YYYY HH:MM AM/PM", 'ERROR')
        return None

    to_book_list = [(None, booking_time)]

    log(f"Booking: {booking_date} at {booking_time}", 'INFO')

    return (to_book_list, booking_date)


async def prepare_bookings(booking_date=None, booking_time=None, invoke_time=None, court_name=None, booking_duration=None):
    """
    Main wrapper function to prepare bookings for either list mode or manual mode.

    Determines which mode to use based on environment variables and command-line arguments,
    then prepares the booking list accordingly.

    Args:
        booking_date: Optional booking date from command-line
        booking_time: Optional booking time from command-line
        invoke_time: Optional invoke timestamp for scheduled runs
        court_name: Optional court name for display
        booking_duration: Optional duration for display

    Returns:
        tuple: (to_book_list, booking_date, target_time_str) or None on error
        - to_book_list: List of (day_of_week, time_str) tuples to book
        - booking_date: Date to book (MM/DD/YYYY format)
        - target_time_str: Target time string (HH:MM:SS) or None if no wait needed
    """
    BOOKING_LIST = os.getenv('BOOKING_LIST', '')
    BOOKING_TARGET_TIME = os.getenv('BOOKING_TARGET_TIME', '00:01:00')
    BOOKING_DATE_TIME = os.getenv('BOOKING_DATE_TIME', '01/20/2026 10:00 AM')

    # If --booking-date-time was passed via command-line, always use Manual Single Booking Mode
    # regardless of whether BOOKING_LIST exists
    if BOOKING_LIST and not (booking_date or booking_time):
        log("\n=== BOOKING LIST MODE ===", 'INFO')

        result = prepare_booking_list_mode(
            BOOKING_LIST,
            invoke_time,
            BOOKING_TARGET_TIME
        )

        if result is None:
            return None

        to_book_list, booking_date_final = result

        # Return target time string only for scheduled runs with invoke_time
        # Main function will decide whether to wait based on invoke_time
        return (to_book_list, booking_date_final, BOOKING_TARGET_TIME)

    else:
        log("\n=== MANUAL SINGLE BOOKING MODE ===", 'INFO')

        result = prepare_manual_booking_mode(
            BOOKING_DATE_TIME,
            booking_date,
            booking_time
        )

        if result is None:
            return None

        to_book_list, booking_date_final = result

        log(f"Court: {court_name}", 'INFO')
        log(f"Duration: {booking_duration} minutes", 'INFO')

        return (to_book_list, booking_date_final, None)  # No wait needed for manual mode


class AthenaeumBooking:
    def __init__(self, username, password, headless=False):
        self.username = username
        self.password = password
        self.base_url = "https://www.athenaeumcaltech.com"
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        
    async def setup(self):
        """Initialize Playwright browser"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            slow_mo=100  # Slow down by 100ms for better stability
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        self.page = await self.context.new_page()
        
        # Enable request/response logging for debugging
        self.page.on('console', lambda msg: print(f'Browser console: {msg.text}'))
        
    async def login(self):
        """Log into the Athenaeum member portal"""
        log("Navigating to login page...", 'INFO')
        await self.page.goto(f"{self.base_url}/member-login", wait_until='networkidle')
        
        # Wait for page to fully load
        
        try:
            # Save initial page state
#            await self.page.screenshot(path='01_initial_page.png')
            
            # Try to find login form - try multiple possible selectors
            log("Looking for login form...", 'INFO')
            
            username_selectors = [
                '#masterPageUC_MPCA378459_ctl00_ctl02_txtUsername',
                'input[placeholder="Username"]',
                'input.advLogUsername',
                'input[type="text"][placeholder*="Username"]'
            ]
            
            password_selectors = [
                '#masterPageUC_MPCA378459_ctl00_ctl02_txtPassword',
                'input[placeholder="Password"]',
                'input.advLogPassword',
                'input[type="password"]'
            ]
            
            username_field = None
            password_field = None
            
            # Try to find username field
            for selector in username_selectors:
                try:
                    username_field = await self.page.wait_for_selector(selector, timeout=3000)
                    if username_field:
                        log(f"! Found username field: {selector}", 'INFO')
                        break
                except:
                    continue
            
            # Try to find password field
            for selector in password_selectors:
                try:
                    password_field = await self.page.wait_for_selector(selector, timeout=3000)
                    if password_field:
                        log(f"! Found password field: {selector}", 'INFO')
                        break
                except:
                    continue
            
            if not username_field or not password_field:
                log("! Could not find login fields", 'ERROR')
                log("\nDebugging - All input fields on page:", 'INFO')
                inputs = await self.page.query_selector_all('input')
                for inp in inputs:
                    id_attr = await inp.get_attribute('id')
                    name_attr = await inp.get_attribute('name')
                    type_attr = await inp.get_attribute('type')
                    placeholder = await inp.get_attribute('placeholder')
                    log(f"  Input: id={id_attr}, name={name_attr}, type={type_attr}, placeholder={placeholder}", 'INFO')
                
                # Save page HTML for inspection
                content = await self.page.content()
                with open('login_page_source.html', 'w', encoding='utf-8') as f:
                    f.write(content)
                log("\n! Page HTML saved to login_page_source.html", 'INFO')
                return False
            
            log("Entering credentials...", 'INFO')
            await username_field.fill(self.username)
            await password_field.fill(self.password)
            
            # Take screenshot before login
#            await self.page.screenshot(path='02_before_login.png')
            
            # Find login button
            login_button = None
            login_selectors = [
                '#btnSecureLogin',
                'input#btnSecureLogin',
                'input.abut',
                'input[type="button"][id*="Login"]',
                '#masterPageUC_MPCA378459_ctl00_ctl02_persistLoginBtn',
                'button:has-text("Login")',
                'input[type="submit"]',
                'button[type="submit"]'
            ]
            
            for selector in login_selectors:
                try:
                    login_button = await self.page.query_selector(selector)
                    if login_button:
                        log(f"! Found login button: {selector}", 'INFO')
                        break
                except:
                    continue
            
            if not login_button:
                log("! Could not find login button", 'ERROR')
                return False
            
            # Click login and wait for navigation
            log("Clicking login button...", 'INFO')
            
            # The button might trigger JavaScript instead of form submission
            # Try clicking and waiting for navigation, but with fallback
            try:
                async with self.page.expect_navigation(timeout=15000, wait_until='networkidle'):
                    await login_button.click()
            except PlaywrightTimeout:
                # If navigation doesn't happen, wait a bit for JavaScript
                log("  No navigation detected, waiting for JavaScript...", 'INFO')
            
            # Wait a moment for any redirects
            
            # Check if login was successful
            current_url = self.page.url
            if "member-login" in current_url.lower():
                log("! Login failed - still on login page", 'ERROR')
#                await self.page.screenshot(path='03_login_failed.png')
                return False
                
            log(f"! Login successful! Current URL: {current_url}", 'INFO')
#            await self.page.screenshot(path='04_after_login.png')
            return True
            
        except PlaywrightTimeout as e:
            log(f"! Timeout during login: {str(e)}", 'INFO')
#            await self.page.screenshot(path='login_timeout.png')
            return False
        except Exception as e:
            log(f"! Error during login: {str(e)}", 'ERROR')
#            await self.page.screenshot(path='login_error.png')
            import traceback
            traceback.print_exc()
            return False
    
    async def find_booking_page(self):
        """Navigate directly to the court booking page"""
        log("\nNavigating directly to Court Reservations page...", 'INFO')

        try:
            # Direct URL to Court Reservations
            booking_url = "https://www.athenaeumcaltech.com/Default.aspx?p=dynamicmodule&pageid=378495&tt=booking&ssid=295150&vnf=1"

            await self.page.goto(booking_url, wait_until='networkidle')

            log(f"! Navigated to: {self.page.url}", 'INFO')
#            await self.page.screenshot(path='booking_page.png')
            return True

        except Exception as e:
            log(f"Error navigating to booking page: {str(e)}", 'INFO')
#            await self.page.screenshot(path='navigation_error.png')
            return False
    
    async def explore_page_structure(self):
        """Explore and document the current page structure"""
        log("\n=== PAGE STRUCTURE ANALYSIS ===", 'INFO')
        
        # Get page title
        title = await self.page.title()
        log(f"Page Title: {title}", 'INFO')
        log(f"Current URL: {self.page.url}", 'INFO')
        
        # Look for forms
        forms = await self.page.query_selector_all('form')
        log(f"\nForms found: {len(forms)}", 'INFO')
        
        # Look for date inputs
        date_inputs = await self.page.query_selector_all(
            'input[type="date"], input[type="text"][id*="date"], input[name*="date"]'
        )
        log(f"Date inputs found: {len(date_inputs)}", 'INFO')
        for inp in date_inputs:
            id_attr = await inp.get_attribute('id')
            name_attr = await inp.get_attribute('name')
            log(f"  - ID: {id_attr}, Name: {name_attr}", 'INFO')
        
        # Look for time selectors
        time_selects = await self.page.query_selector_all(
            'select[id*="time"], select[name*="time"], input[type="time"]'
        )
        log(f"Time selectors found: {len(time_selects)}", 'INFO')
        
        # Look for buttons
        buttons = await self.page.query_selector_all('button, input[type="submit"]')
        log(f"\nButtons found: {len(buttons)}", 'INFO')
        for btn in buttons[:10]:  # Show first 10
            text = await btn.inner_text()
            if text.strip():
                log(f"  - {text.strip()}", 'INFO')
        
        # Check for iframes (many booking systems use them)
        frames = self.page.frames
        log(f"\nIframes found: {len(frames) - 1}", 'INFO')  # -1 for main frame
        for frame in frames[1:]:  # Skip main frame
            log(f"  - {frame.url}", 'INFO')
        
        # Save page content
        content = await self.page.content()
        with open('page_structure.html', 'w', encoding='utf-8') as f:
            f.write(content)
        log("\nPage HTML saved to: page_structure.html", 'INFO')
        
    async def book_court(self, date_str, start_time, court_name="North Pickleball Court", duration_minutes="60"):
        """
        Book a court for specific date and time
        
        Args:
            date_str: Date in US format MM/DD/YYYY (e.g., '01/20/2026', '12/25/2026')
            start_time: Time in format 'H:MM AM/PM' (e.g., '10:00 AM', '2:30 PM')
            court_name: Full court name - options:
                - 'North Pickleball Court'
                - 'South Pickleball Court'
                - 'West Tennis Court'
                - 'East Tennis Court'
            duration_minutes: Duration in minutes - "60" or "120"
        """
        log(f"\n=== ATTEMPTING COURT BOOKING ===", 'INFO')
        log(f"Court: {court_name}", 'INFO')
        log(f"Date: {date_str}", 'INFO')
        log(f"Time: {start_time}", 'INFO')
        log(f"Duration: {duration_minutes} Minutes", 'INFO')
        
        try:
            # Take initial screenshot
#            await self.page.screenshot(path='booking_01_initial.png', full_page=True)
#            print("! Screenshot: booking_01_initial.png")
            
            # Look for the date input field
            log("\nLooking for date input field...", 'INFO')
            date_input = await self.page.query_selector('#txtDate')
            
            if not date_input:
                log("! Could not find #txtDate field", 'ERROR')
                return False
            
            # Check if it's visible
            is_visible = await date_input.is_visible()
            log(f"Date field visible: {is_visible}", 'INFO')
            
            if is_visible:
                log(f"Entering date: {date_str}", 'INFO')
                
                # Click on the date field
                await date_input.click()
                
                # Clear existing value
                await date_input.press('Control+A')
                await date_input.press('Backspace')
                
                # Type the date (MM/DD/YYYY format)
                await date_input.type(date_str, delay=1)
                
                # Press Enter to submit the date and reload calendar
                await date_input.press('Enter')
                
                # Wait for the calendar/schedule iframe to fully reload with new date
                log("Waiting for calendar to update...", 'INFO')
                await asyncio.sleep(2)
                
#                await self.page.screenshot(path='booking_02_date_entered.png', full_page=True)
#                print("! Date entered, calendar updated")
                
            else:
                log("! Date field is not visible", 'INFO')
                return False
            
            # Now find the booking link for the specific time and court
            log(f"\nSearching for available slot: {start_time} - {court_name}", 'INFO')
            
            # Find all clickable links that match the court name
            # Only GREEN available slots will be clickable links
            # White/gray text (already booked) = no link, will be skipped
            # Blue boxes (your reservations) = EDIT button, not court name link
            all_court_links = await self.page.query_selector_all(f'a:has-text("{court_name}")')
            
            log(f"Found {len(all_court_links)} clickable instances of '{court_name}'", 'INFO')
            
            booking_link = None
            checked_count = 0
            
            # Actually, looking at the HTML, we need to find DIVs with onclick, not links!
            # Available courts are in divs with class "rbm_TimeSlotPanelSlotAvailable" and onclick handlers
            log("\nSearching for clickable court divs...", 'INFO')
            
            # Find all table cells that might contain bookable courts
            all_cells = await self.page.query_selector_all('td[class*="rbm_"]')
            
            log(f"Found {len(all_cells)} table cells to check", 'INFO')
            
            for cell in all_cells:
                try:
                    # Get the div inside the cell
                    court_div = await cell.query_selector('div.rbm_TimeSlotPanelSlotAvailable, div.rbm_TimeSlotPanelNoSlots')
                    
                    if not court_div:
                        continue
                    
                    # Check if it has onclick (means it's bookable)
                    onclick = await court_div.get_attribute('onclick')
                    if not onclick or onclick == '':
                        continue  # Not bookable
                    
                    # Check if it contains our court name
                    div_text = await court_div.inner_text()
                    if court_name not in div_text:
                        continue
                    
                    # Get the row to check the time
                    parent_row = await cell.evaluate_handle('el => el.closest("tr")')
                    row_text = await parent_row.evaluate('el => el.innerText')
                    
                    checked_count += 1
                    
                    # Debug first few
                    if checked_count <= 3:
                        log(f"Debug #{checked_count}:", 'INFO')
                        log(f"  Court div text: '{div_text.strip()[:50]}'", 'INFO')
                        log(f"  Row text: '{row_text.strip()[:100]}'", 'INFO')
                        log(f"  Has onclick: {bool(onclick)}", 'INFO')
                        log(f"  Looking for: '{start_time}'", 'INFO')
                    
                    # Check if this row has our time
                    if start_time in row_text:
                        booking_link = court_div
                        log(f"\n! Found bookable court!", 'INFO')
                        log(f"  Court: {div_text.strip()[:50]}", 'INFO')
                        log(f"  Time: {start_time}", 'INFO')
                        break
                        
                except Exception as e:
                    continue
            
            log(f"\nTotal bookable courts checked for '{court_name}': {checked_count}", 'INFO')
            
            if booking_link:
                # Take screenshot of the specific slot
                try:
#                    await booking_link.screenshot(path='booking_03_target_slot.png')
                    log("! Screenshot of target slot: booking_03_target_slot.png", 'INFO')
                except:
                    pass
                
                # Get the link details
                link_text = await booking_link.inner_text()
                href = await booking_link.get_attribute('href')
                
                log(f"\n{'='*60}", 'INFO')
                log(f"READY TO BOOK", 'INFO')
                log(f"{'='*60}", 'INFO')
                log(f"Court: {link_text.strip()}", 'INFO')
                log(f"Time: {start_time}", 'INFO')
                log(f"Date: {date_str}", 'INFO')
                
                # Check safety mode
                safety_mode = os.getenv('SAFETY_MODE', 'True').lower() != 'false'
                
                if safety_mode:
                    log(f"\n{'='*60}", 'INFO')
                    log("SAFETY MODE ENABLED - BOOKING NOT SUBMITTED", 'INFO')
                    log(f"{'='*60}", 'INFO')
                    log("The script found the correct booking slot.", 'INFO')
                    log("\nReview the screenshots:", 'INFO')
                    log("  - booking_01_initial.png (initial calendar)", 'INFO')
                    log("  - booking_02_date_entered.png (after date entry)", 'INFO')
                    log("  - booking_03_target_slot.png (the slot to book)", 'INFO')
                    log("\nTo complete the booking, update your .env file:", 'INFO')
                    log("  SAFETY_MODE=false", 'INFO')
                    log("\nThen run the script again.", 'INFO')
                    
                else:
                    # Actually click to book
                    log(f"\n! SAFETY MODE OFF - PROCEEDING WITH BOOKING...", 'INFO')
                    await booking_link.click()
                    
                    # Wait for booking form to load IN IFRAME
                    log("Waiting for booking form modal with iframe...", 'INFO')

                    # Wait for iframe to appear
                    try:
                        await self.page.wait_for_selector('iframe', timeout=10000)
                        log("! Found iframe", 'INFO')
                    except:
                        log("! No iframe detected", 'INFO')


                    # Take screenshot of booking form
#                    await self.page.screenshot(path='booking_04_booking_form.png', full_page=True)
                    log("! Screenshot: booking_04_booking_form.png", 'INFO')

                    # Get the iframe that contains the booking form
                    log("\nSearching for iframe with booking form...", 'INFO')
                    frames = self.page.frames
                    booking_frame = None

                    for frame in frames:
                        frame_url = frame.url
                        if 'rbmPop' in frame_url or 'MakebookingTime' in frame_url or 'dialog.aspx' in frame_url:
                            booking_frame = frame
                            log(f"! Found booking iframe: {frame_url[:80]}", 'INFO')
                            break

                    if not booking_frame:
                        log("! Booking iframe not found, using main page", 'INFO')
                        booking_frame = self.page.main_frame

                    # Wait for iframe content to load by waiting for form elements
                    log("NOT Waiting for iframe content to load...", 'INFO')
#                    try:
#                        await booking_frame.wait_for_selector('select, input, button, a[onclick]', timeout=10000)
#                        print("! Iframe content loaded")
#                    except:
#                        print("! Timeout waiting for iframe content")


                    # Debug: Check what's in the iframe and get HTML
                    iframe_content = await booking_frame.evaluate('''() => {
                        return {
                            title: document.title,
                            bodyText: document.body ? document.body.innerText.substring(0, 200) : 'no body',
                            hasSelects: document.querySelectorAll('select').length,
                            hasButtons: document.querySelectorAll('button, input, a[onclick]').length,
                            bodyHTML: document.body ? document.body.innerHTML.substring(0, 2000) : 'no body'
                        };
                    }''')
                    log(f"Iframe content: title='{iframe_content['title']}', selects={iframe_content['hasSelects']}, buttons={iframe_content['hasButtons']}", 'INFO')
                    log(f"Body preview: {iframe_content['bodyText'][:100]}...", 'INFO')

                    # Save iframe HTML for debugging
                    with open('iframe_content.html', 'w', encoding='utf-8') as f:
                        f.write(iframe_content['bodyHTML'])
                    log("! Saved iframe HTML to iframe_content.html", 'INFO')

                    # Fill out the booking form IN THE IFRAME
                    log("\nSearching for form elements in iframe...", 'INFO')

                    # Use JavaScript to find ALL selects and their visibility status IN THE IFRAME
                    select_info = await booking_frame.evaluate('''() => {
                        const selects = document.querySelectorAll('select');
                        return Array.from(selects).map((select, idx) => {
                            const rect = select.getBoundingClientRect();
                            const isVisible = rect.width > 0 && rect.height > 0 &&
                                            window.getComputedStyle(select).display !== 'none' &&
                                            window.getComputedStyle(select).visibility !== 'hidden';
                            const currentText = select.options[select.selectedIndex]?.text || '';
                            const options = Array.from(select.options).map(opt => opt.text);
                            return {
                                index: idx,
                                visible: isVisible,
                                currentText: currentText,
                                hasMinutes: options.some(opt => opt.includes('Minutes') || opt.includes('minutes')),
                                id: select.id,
                                name: select.name,
                                options: options.slice(0, 5)
                            };
                        });
                    }''')

                    log(f"Found {len(select_info)} select elements:", 'INFO')
                    for info in select_info:
                        log(f"  [{info['index']}] visible={info['visible']}, current='{info['currentText']}', hasMinutes={info['hasMinutes']}, id={info['id']}", 'INFO')

                    # Find the duration select
                    duration_idx = None
                    for info in select_info:
                        if info['hasMinutes'] and info['visible']:
                            duration_idx = info['index']
                            log(f"! Found duration dropdown at index {duration_idx}", 'INFO')
                            break

                    # If not found visible, try any with minutes
                    if duration_idx is None:
                        for info in select_info:
                            if info['hasMinutes']:
                                duration_idx = info['index']
                                log(f"! Found duration dropdown at index {duration_idx} (not marked visible)", 'INFO')
                                break

                    # Change duration
                    if duration_idx is not None:
                        log(f"\nChanging duration to {duration_minutes} minutes...", 'INFO')

                        try:
                            # Use JavaScript to select the option directly IN THE IFRAME
                            success = await booking_frame.evaluate(f'''(idx) => {{
                                const select = document.querySelectorAll('select')[idx];
                                if (!select) return false;

                                // Find option with {duration_minutes} Minutes
                                for (let i = 0; i < select.options.length; i++) {{
                                    if (select.options[i].text.includes('{duration_minutes}')) {{
                                        select.selectedIndex = i;
                                        select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        return true;
                                    }}
                                }}
                                return false;
                            }}''', duration_idx)

                            if success:
                                log(f"! Duration set to {duration_minutes} minutes", 'INFO')
                            else:
                                log(f"! Could not find {duration_minutes} minutes option", 'ERROR')

                        except Exception as e:
                            log(f"! Could not change duration: {str(e)[:100]}", 'ERROR')
                    else:
                        # Try Telerik RadComboBox for duration
                        log("! Standard dropdown not found, trying Telerik RadComboBox...", 'INFO')
                        try:
                            # Use JavaScript to interact with Telerik RadComboBox
                            # Note: findItemByText can be unreliable, so we search items manually
                            success = await booking_frame.evaluate(f'''() => {{
                                // Find the RadComboBox by input ID
                                const input = document.getElementById('ctl00_ctrl_MakeBookingTime_drpDuration_tCombo_Input');
                                if (!input) return {{ success: false, reason: 'input not found' }};

                                // Get the Telerik combo object
                                const comboId = 'ctl00_ctrl_MakeBookingTime_drpDuration_tCombo';
                                const combo = window.$find(comboId);

                                if (combo && typeof combo.get_items === 'function') {{
                                    const items = combo.get_items();
                                    const targetText = '{duration_minutes} Minutes';
                                    const itemTexts = [];
                                    let foundIndex = -1;

                                    // Search items manually for more reliable matching
                                    for (let i = 0; i < items.get_count(); i++) {{
                                        const itemText = items.getItem(i).get_text();
                                        itemTexts.push(itemText);
                                        // Check if this item contains our duration
                                        if (itemText.includes('{duration_minutes}')) {{
                                            foundIndex = i;
                                        }}
                                    }}

                                    if (foundIndex >= 0) {{
                                        const item = items.getItem(foundIndex);
                                        combo.set_selectedIndex(foundIndex);
                                        combo.set_text(item.get_text());
                                        return {{ success: true, method: 'telerik API (manual search)', selectedText: item.get_text() }};
                                    }} else {{
                                        return {{ success: false, reason: 'item not found', available: itemTexts, searched: targetText }};
                                    }}
                                }} else {{
                                    return {{ success: false, reason: 'combo object not found or no API' }};
                                }}
                            }}''')

                            if success.get('success'):
                                log(f"! Set Telerik duration to '{success.get('selectedText', duration_minutes + ' Minutes')}' using {success.get('method')}", 'INFO')
                            else:
                                log(f"! Could not set Telerik duration: {success.get('reason')}", 'ERROR')
                                if 'available' in success:
                                    log(f"   Available options: {success['available']}", 'INFO')
                                if 'searched' in success:
                                    log(f"   Searched for: '{success['searched']}'", 'INFO')
                        except Exception as e:
                            log(f"! Could not set Telerik duration: {str(e)[:100]}", 'ERROR')

                    
                    # Take screenshot after filling form
#                    await self.page.screenshot(path='booking_05_form_filled.png', full_page=True)
                    log("! Screenshot: booking_05_form_filled.png", 'INFO')
                    
                    # Look for "Make Reservation" button IN THE IFRAME
                    log("\nSearching for buttons in iframe...", 'INFO')

                    # First, let's see ALL elements with __doPostBack
                    all_postback = await booking_frame.evaluate('''() => {
                        const allElements = document.querySelectorAll('*[onclick*="__doPostBack"]');
                        return Array.from(allElements).map(el => ({
                            tag: el.tagName,
                            text: (el.innerText || el.value || '').substring(0, 30),
                            onclick: el.getAttribute('onclick') || '',
                            id: el.id,
                            hasLbBook: (el.getAttribute('onclick') || '').includes('lbBook')
                        }));
                    }''')

                    log(f"Found {len(all_postback)} elements with __doPostBack:", 'INFO')
                    for item in all_postback[:10]:
                        log(f"  {item['tag']}: '{item['text']}' hasLbBook={item['hasLbBook']}", 'INFO')
                        log(f"     onclick={item['onclick']}", 'INFO')

                    # PRIORITY 0: Try finding button by ID pattern (MOST RELIABLE)
                    log("\nTrying to find button by ID containing 'lbBook'...", 'INFO')
                    button_by_id = await booking_frame.evaluate('''() => {
                        const byId = document.querySelector('[id*="lbBook"]');
                        if (byId) {
                            return {
                                found: true,
                                id: byId.id,
                                tag: byId.tagName,
                                text: byId.innerText || byId.value || '',
                                onclick: byId.getAttribute('onclick') || byId.onclick?.toString() || 'none'
                            };
                        }
                        return { found: false };
                    }''')

                    if button_by_id['found']:
                        log(f"! Found button by ID: {button_by_id['id']}", 'INFO')
                        log(f"  Tag: {button_by_id['tag']}, Text: '{button_by_id['text']}'", 'INFO')

                        log("\n! Clicking Make Reservation button by ID...", 'INFO')
#                        await self.page.screenshot(path='booking_05a_before_submit.png', full_page=True)

                        try:
                            await booking_frame.click(f"#{button_by_id['id']}")
                            log("! Clicked Booked!", 'INFO')

#                            await self.page.screenshot(path='booking_06_confirmation.png', full_page=True)

                            # Close the confirmation dialog
                            log("\nClosing confirmation dialog...", 'INFO')
                            try:
                                # Wait for dialog to appear
#                                await asyncio.sleep(1)

                                # Debug: Try to find what links/buttons exist
                                log("! Searching for close button...", 'INFO')

                                # Look for "Click here to close this window" or close button
                                # Try both the iframe and main page with more comprehensive selectors
                                close_selectors = [
                                    'a:has-text("Click here")',
                                    'a:has-text("close")',
                                    'a:has-text("Close")',
                                    'button:has-text("Close")',
                                    'button:has-text("close")',
                                    'a[onclick*="close"]',
                                    'a[onclick*="Close"]',
                                    '[onclick*="window.close"]',
                                    'a[href*="close"]',
                                    'a[href="javascript:window.close()"]',
                                    'a[href="javascript:void(0)"][onclick]',
                                    'text=Click here to close this window',
                                    'text=close this window'
                                ]

                                closed = False

                                # Try iframe first
                                log("! Checking iframe for close button...", 'INFO')
                                for selector in close_selectors:
                                    try:
                                        close_btn = await booking_frame.query_selector(selector)
                                        if close_btn:
                                            is_visible = await close_btn.is_visible()
                                            log(f"! Found element with '{selector}', visible: {is_visible}", 'INFO')
                                            if is_visible:
                                                await close_btn.click()
                                                log(f"! Closed confirmation dialog (iframe) with: {selector}", 'INFO')
                                                closed = True
                                                await asyncio.sleep(1)
                                                break
                                    except Exception as e:
                                        continue

                                # If not found in iframe, try main page
                                if not closed:
                                    log("! Checking main page for close button...", 'INFO')
                                    for selector in close_selectors:
                                        try:
                                            close_btn = await self.page.query_selector(selector)
                                            if close_btn:
                                                is_visible = await close_btn.is_visible()
                                                log(f"! Found element with '{selector}', visible: {is_visible}", 'INFO')
                                                if is_visible:
                                                    await close_btn.click()
                                                    log(f"! Closed confirmation dialog (main page) with: {selector}", 'INFO')
                                                    closed = True
                                                    await asyncio.sleep(1)
                                                    break
                                        except Exception as e:
                                            continue

                                # Last resort: Use JavaScript to find and click any link with "close" text
                                if not closed:
                                    log("! Trying JavaScript approach...", 'INFO')
                                    try:
                                        # Try in iframe first
                                        result = await booking_frame.evaluate('''() => {
                                            const links = Array.from(document.querySelectorAll('a'));
                                            const closeLink = links.find(a =>
                                                a.textContent.toLowerCase().includes('click here') ||
                                                a.textContent.toLowerCase().includes('close')
                                            );
                                            if (closeLink) {
                                                closeLink.click();
                                                return 'iframe: ' + closeLink.textContent;
                                            }
                                            return null;
                                        }''')
                                        if result:
                                            log(f"! Closed with JS (iframe): {result}", 'INFO')
                                            closed = True
                                    except:
                                        pass

                                # Try main page with JS
                                if not closed:
                                    try:
                                        result = await self.page.evaluate('''() => {
                                            const links = Array.from(document.querySelectorAll('a'));
                                            const closeLink = links.find(a =>
                                                a.textContent.toLowerCase().includes('click here') ||
                                                a.textContent.toLowerCase().includes('close')
                                            );
                                            if (closeLink) {
                                                closeLink.click();
                                                return 'main: ' + closeLink.textContent;
                                            }
                                            return null;
                                        }''')
                                        if result:
                                            log(f"! Closed with JS (main page): {result}", 'INFO')
                                            closed = True
                                    except:
                                        pass

                                if not closed:
                                    log("! Could not find close button, confirmation dialog may remain open", 'ERROR')

                            except Exception as e:
                                log(f"! Could not close dialog automatically: {str(e)[:80]}", 'ERROR')

                            log("\n" + "="*60, 'INFO')
                            log("! BOOKING SUBMITTED!", 'INFO')
                            log("="*60, 'INFO')

                            log("\n=== PROCESS COMPLETE ===", 'INFO')
                            return True
                        except Exception as e:
                            log(f"! Click error: {str(e)}", 'ERROR')
                    else:
                        log("! Button not found by ID", 'INFO')

                    # Search for ANY element with __doPostBack and lbBook IN THE IFRAME
                    button_analysis = await booking_frame.evaluate('''() => {
                        // Find ALL elements with onclick containing __doPostBack and lbBook
                        const allElements = document.querySelectorAll('*[onclick*="__doPostBack"]');

                        const bookButtons = Array.from(allElements).filter(el => {
                            const onclick = el.getAttribute('onclick') || '';
                            return onclick.includes('lbBook');
                        }).map((el, idx) => {
                            const rect = el.getBoundingClientRect();
                            const isVisible = rect.width > 0 && rect.height > 0 &&
                                            window.getComputedStyle(el).display !== 'none' &&
                                            window.getComputedStyle(el).visibility !== 'hidden' &&
                                            window.getComputedStyle(el).opacity !== '0';

                            const text = el.innerText || el.value || el.textContent || el.alt || '';
                            const title = el.getAttribute('title') || '';
                            const className = el.className || '';
                            const id = el.id || '';
                            const onclick = el.getAttribute('onclick') || '';

                            return {
                                index: idx,
                                visible: isVisible,
                                text: text.trim(),
                                title: title,
                                className: className,
                                id: id,
                                onclick: onclick,
                                tagName: el.tagName,
                                type: el.type || ''
                            };
                        });

                        return { buttons: bookButtons };
                    }''')

                    button_info = button_analysis['buttons']
                    log(f"Found {len(button_info)} elements with __doPostBack and lbBook in iframe", 'INFO')

                    # Show all found buttons
                    for info in button_info:
                        log(f"  [{info['index']}] {info['tagName']}: '{info['text']}', visible={info['visible']}", 'INFO')
                        log(f"     onclick: {info['onclick'][:80]}", 'INFO')

                    # Debug: Show ALL button texts to find the right one
                    log("\nAll visible buttons (first 30):", 'INFO')
                    for i, info in enumerate(button_info[:30]):
                        log(f"  [{info['index']}] {info['tagName']}: '{info['text']}'", 'INFO')

                    # Look for the reservation button
                    reservation_btn_idx = None

                    log("\nLooking for reservation button...", 'INFO')

                    # PRIORITY 1: Look for the button with __doPostBack and lbBook
                    for info in button_info:
                        onclick_lower = info['onclick'].lower()

                        if '__dopostback' in onclick_lower and 'lbbook' in onclick_lower:
                            reservation_btn_idx = info['index']
                            log(f"! Found reservation button (by onclick) at index {reservation_btn_idx}: '{info['text']}'", 'INFO')
                            log(f"  onclick: {info['onclick']}", 'INFO')
                            break

                    # PRIORITY 2: Look for text with "Make Reservation"
                    if reservation_btn_idx is None:
                        for info in button_info:
                            text_lower = info['text'].lower()

                            # Debug: print buttons that might be relevant
                            if any(keyword in text_lower for keyword in ['reserv', 'book', 'submit', 'save', 'confirm', 'ok']):
                                log(f"  Candidate [{info['index']}] {info['tagName']}: '{info['text']}', onclick='{info['onclick'][:40]}'", 'INFO')

                            # Look for explicit reservation text
                            if any(keyword in text_lower for keyword in ['make reservation', 'create reservation', 'reserve']):
                                # Exclude cancel/close buttons
                                if not any(neg in text_lower for neg in ['cancel', 'close', 'discard', 'delete', 'minimize']):
                                    reservation_btn_idx = info['index']
                                    log(f"! Found reservation button (by text) at index {reservation_btn_idx}: '{info['text']}'", 'INFO')
                                    break

                    # PRIORITY 3: Fallback - look for submit buttons
                    if reservation_btn_idx is None:
                        log("No explicit reservation button found, looking for submit buttons...", 'INFO')
                        for info in button_info:
                            text_lower = info['text'].lower()
                            onclick_lower = info['onclick'].lower()

                            # Look for submit-like buttons but exclude minimize/cancel/close
                            if info['tagName'] == 'INPUT' or 'submit' in text_lower or text_lower == 'ok':
                                if not any(neg in text_lower for neg in ['cancel', 'close', 'discard', 'minimize', 'delete']):
                                    if not any(neg in onclick_lower for neg in ['min', 'cancel', 'close']):
                                        reservation_btn_idx = info['index']
                                        log(f"! Found submit button at index {reservation_btn_idx}: '{info['text']}'", 'INFO')
                                        break

                    # Click the button
                    if reservation_btn_idx is not None:
                        log(f"\n! Clicking reservation button at index {reservation_btn_idx}...", 'INFO')
#                        await self.page.screenshot(path='booking_05a_before_submit.png', full_page=True)

                        try:
                            # Use JavaScript to click the button with __doPostBack IN THE IFRAME
                            success = await booking_frame.evaluate(f'''(idx) => {{
                                const allElements = document.querySelectorAll('*[onclick*="__doPostBack"]');
                                const bookButtons = Array.from(allElements).filter(el => {{
                                    const onclick = el.getAttribute('onclick') || '';
                                    return onclick.includes('lbBook');
                                }});

                                if (bookButtons[idx]) {{
                                    bookButtons[idx].click();
                                    return true;
                                }}
                                return false;
                            }}''', reservation_btn_idx)

                            if success:
                                log("! Clicked!", 'INFO')
#                                await asyncio.sleep(2)
                            else:
                                log("! Button click failed", 'ERROR')

                        except Exception as e:
                            log(f"! Click error: {str(e)[:80]}", 'ERROR')
                    else:
                        log("\n! 'Make Reservation' button not found in visible elements", 'INFO')
                    
                    # Final screenshot
#                    await self.page.screenshot(path='booking_06_confirmation.png', full_page=True)
                    log("\n" + "="*60, 'INFO')
                    log("! BOOKING PROCESS COMPLETED!", 'INFO')
                    log("="*60, 'INFO')
                    log("Check booking_06_confirmation.png for confirmation", 'INFO')
                    log("If successful, the court should now appear in blue on the calendar", 'INFO')
                
                return True
                
            else:
                log(f"\n! NO AVAILABLE SLOT FOUND", 'INFO')
                log(f"{'='*60}", 'INFO')
                log(f"Could not find an available (green) slot for:", 'ERROR')
                log(f"  Court: {court_name}", 'INFO')
                log(f"  Time: {start_time}", 'INFO')
                log(f"  Date: {date_str}", 'INFO')
                log(f"\nPossible reasons:", 'INFO')
                log(f"  1. Court is already booked (gray text, no link)", 'INFO')
                log(f"  2. You already have a reservation (blue box with EDIT)", 'INFO')
                log(f"  3. Time format doesn't match (use 'H:MM AM' format)", 'INFO')
                log(f"  4. Court name doesn't match exactly", 'INFO')
                log(f"\nCheck booking_02_date_entered.png to see available slots", 'INFO')
                log(f"(Green boxes = available, Gray text = booked by others)", 'INFO')
                
#                await self.page.screenshot(path='booking_no_slot_found.png', full_page=True)
                
                return False
            
        except Exception as e:
            log(f"\n! ERROR DURING BOOKING", 'ERROR')
            log(f"{'='*60}", 'INFO')
            log(f"{str(e)}", 'INFO')
#            await self.page.screenshot(path='booking_error.png', full_page=True)
            import traceback
            traceback.print_exc()
            return False
    
    async def interactive_mode(self):
        """Interactive mode for manual navigation and exploration"""
        log("\n=== INTERACTIVE MODE ===", 'INFO')
        log("Browser window opened. You can:", 'INFO')
        log("1. Manually navigate to the booking page", 'INFO')
        log("2. Inspect the page structure", 'INFO')
        log("3. Press Enter when ready to continue automation", 'INFO')
        
        input("\nPress Enter to continue...")
        
        await self.explore_page_structure()
    
    async def close(self):
        """Close the browser"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        log("Browser closed", 'INFO')


def get_booking_list(booking_list_str, booking_datetime):
    """
    Parse BOOKING_LIST and filter bookings for the target booking day's day of week.

    Args:
        booking_list_str: String like "Tuesday 7:00 PM|Both,Wednesday 7:00 PM,Friday 4:00 PM|North Pickleball Court"
                         Format: <DayName> <Time>|<CourtName>, comma-separated
                         Court specification is optional (defaults to None)
        booking_datetime: datetime object representing the actual booking date (7 days from target time)

    Returns:
        List of tuples: [(day_name, time_str, court_name), ...]
        court_name will be None if not specified

    Example:
        If booking_datetime is Tuesday and booking_list has "Tuesday 7:00 PM|Both,Wednesday 7:00 PM"
        Returns: [("Tuesday", "7:00 PM", "Both")]
    """
    if not booking_list_str:
        return []

    # Day name mapping (case-insensitive)
    day_names = {
        'monday': 0,
        'tuesday': 1,
        'wednesday': 2,
        'thursday': 3,
        'friday': 4,
        'saturday': 5,
        'sunday': 6
    }

    day_names_display = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    # Get the day of week from booking_datetime (7 days from target time)
    python_weekday = booking_datetime.weekday()  # 0=Mon, 6=Sun
    target_day_name = day_names_display[python_weekday]

    log(f"\nProcessing BOOKING_LIST for day of week: {target_day_name}", 'INFO')

    to_book_list = []

    # Parse the booking list
    entries = booking_list_str.split(',')
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        # Check for optional court specification: "Tuesday 7:00 PM|Both"
        court_name = None
        if '|' in entry:
            entry_parts = entry.split('|', 1)
            entry = entry_parts[0].strip()
            court_name = entry_parts[1].strip()

        # Parse "Tuesday 7:00 PM" format
        parts = entry.split(' ', 1)
        if len(parts) != 2:
            log(f"  ! Skipping invalid entry: '{entry}'", 'ERROR')
            continue

        try:
            day_str = parts[0].strip().lower()
            time_str = parts[1].strip()

            # Check if day name is valid
            if day_str not in day_names:
                log(f"  ! Invalid day name: '{parts[0]}' (expected: Monday, Tuesday, etc.)", 'ERROR')
                continue

            day_display = parts[0].strip().title()  # Preserve capitalization from input

            # Display parsed entry with optional court
            if court_name:
                log(f"  Parsed: {day_display} at {time_str} -> Court: {court_name}", 'INFO')
            else:
                log(f"  Parsed: {day_display} at {time_str}", 'INFO')

            # Check if this booking is for today
            if day_names[day_str] == python_weekday:
                to_book_list.append((day_display, time_str, court_name))
                log(f"    -> MATCH! Adding to booking queue", 'INFO')
            else:
                log(f"    -> Skip (not today)", 'INFO')

        except (ValueError, IndexError) as e:
            log(f"  ! Error parsing entry '{entry}': {e}", 'ERROR')
            continue

    log(f"\nTotal bookings to make today: {len(to_book_list)}", 'INFO')
    return to_book_list


async def wait_until_booking_time(target_time_str='00:01:00', timezone_name='America/Los_Angeles', grace_period_minutes=10):
    """
    Wait until the specified time in PST/PDT timezone.
    If already past target time but within grace period, book immediately.
    Otherwise, wait until target time tomorrow.

    Args:
        target_time_str: Target time in HH:MM:SS format (24-hour), default '00:01:00' for 12:01 AM
        timezone_name: Timezone string, default 'America/Los_Angeles' for PST/PDT
        grace_period_minutes: If past target time by this many minutes or less, book immediately. Default 10 minutes.
    """
    # Parse target time string
    try:
        time_parts = target_time_str.split(':')
        target_hour = int(time_parts[0])
        target_minute = int(time_parts[1])
        target_second = int(time_parts[2])
    except (ValueError, IndexError):
        log(f"\n! Invalid target_time_str format: '{target_time_str}', using default 00:01:00", 'ERROR')
        target_hour, target_minute, target_second = 0, 1, 0

    # Get the timezone
    target_tz = pytz.timezone(timezone_name)

    # Get current time in target timezone
    now_tz = datetime.now(target_tz)

    # Calculate target time today
    target_time = now_tz.replace(hour=target_hour, minute=target_minute, second=target_second, microsecond=0)

    # Calculate time difference
    time_diff_seconds = (now_tz - target_time).total_seconds()

    # If we've passed the target time
    if time_diff_seconds > 0:
        # Check if we're within the grace period
        if time_diff_seconds <= (grace_period_minutes * 60):
            log(f"\n=== Booking Time Grace Period ===", 'INFO')
            log(f"Current time ({timezone_name}): {now_tz.strftime('%Y-%m-%d %H:%M:%S %Z')}", 'INFO')
            log(f"Target time ({timezone_name}): {target_time.strftime('%Y-%m-%d %H:%M:%S %Z')}", 'INFO')
            log(f"We're {time_diff_seconds:.1f} seconds ({time_diff_seconds/60:.1f} minutes) past target time", 'INFO')
            log(f"Within {grace_period_minutes}-minute grace period - booking immediately!", 'INFO')
            return
        else:
            # Special case: If current time is late evening (e.g., 11:50 PM) and target is early morning (e.g., 12:00 AM),
            # this means we want to wait a few minutes until tonight becomes tomorrow, not wait 24 hours.
            # Check if the time difference is > 12 hours, which indicates we crossed midnight boundary
            if time_diff_seconds > 12 * 3600:  # More than 12 hours means target is "tonight" not "yesterday"
                # Target should be tomorrow, not today
                target_time = target_time + timedelta(days=1)
                log(f"\n=== Waiting for midnight transition ===", 'INFO')
                log(f"Current time is late evening, target is early morning - waiting a few minutes for midnight", 'INFO')
            else:
                # Genuinely too late, wait until tomorrow
                target_time = target_time + timedelta(days=1)
                log(f"\n! WARNING: More than {grace_period_minutes} minutes past target time. Waiting until tomorrow.", 'INFO')

    # Calculate seconds to wait
    wait_seconds = (target_time - now_tz).total_seconds()

    # SAFETY: Cap wait time at exactly grace period to prevent waiting 24 hours due to logic bugs
    max_wait_seconds = grace_period_minutes * 60
    if wait_seconds > max_wait_seconds:
        log(f"\n! WARNING: Calculated wait time ({wait_seconds/60:.1f} minutes) exceeds safety cap ({max_wait_seconds/60:.1f} minutes)", 'INFO')
        log(f"! This likely indicates a logic error. Capping wait time to {max_wait_seconds/60:.1f} minutes.", 'INFO')
        wait_seconds = max_wait_seconds

    log(f"\n=== Waiting for booking time ===", 'INFO')
    log(f"Current time ({timezone_name}): {now_tz.strftime('%Y-%m-%d %H:%M:%S %Z')}", 'INFO')
    log(f"Target time ({timezone_name}): {target_time.strftime('%Y-%m-%d %H:%M:%S %Z')}", 'INFO')
    log(f"Waiting {wait_seconds:.1f} seconds ({wait_seconds/60:.1f} minutes)...", 'INFO')

    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)
        log(f"[SUCCESS] Reached target time! Proceeding with booking...", 'INFO')
    else:
        log(f"[WARN] Target time already passed, proceeding immediately", 'INFO')


# Email notification is now handled by email_service.py
# Use send_booking_notification() imported at top of file


async def main(booking_date=None, booking_time=None, court_name=None, booking_duration=None, invoke_time=None):
    # ==================== CONFIGURATION ====================
    # Load credentials from environment variables
    ATHENAEUM_USERNAME = os.getenv('ATHENAEUM_USERNAME')
    ATHENAEUM_PASSWORD = os.getenv('ATHENAEUM_PASSWORD')

    if not ATHENAEUM_USERNAME or not ATHENAEUM_PASSWORD:
        log("ERROR: Missing credentials!", 'ERROR')
        log("Please set environment variables in your .env file", 'INFO')
        return

    # Safety mode - set to False to actually complete the booking
    SAFETY_MODE = os.getenv('SAFETY_MODE', 'True').lower() != 'false'

    # Run in headless mode (False = show browser window)
    HEADLESS = os.getenv('HEADLESS', 'False').lower() == 'true'

    # Court options:
    #   'North Pickleball Court'
    #   'South Pickleball Court'
    #   'West Tennis Court'
    #   'East Tennis Court'
    COURT_NAME = court_name or os.getenv('COURT_NAME', 'North Pickleball Court')

    # Duration in minutes: 60 or 120
    BOOKING_DURATION = booking_duration or os.getenv('BOOKING_DURATION', '120')

    # =======================================================
    # PREPARE BOOKINGS (List Mode or Manual Mode)
    # =======================================================

    result = await prepare_bookings(booking_date, booking_time, invoke_time, COURT_NAME, BOOKING_DURATION)
    if result is None:
        return

    to_book_list, BOOKING_DATE, target_time_str = result

    # =======================================================
    # START BOOKING PROCESS
    # =======================================================

    booking = AthenaeumBooking(ATHENAEUM_USERNAME, ATHENAEUM_PASSWORD, headless=HEADLESS)

    try:
        # Setup browser
        await booking.setup()
        log("\n[OK] Browser initialized", 'INFO')

        # Login
        if not await booking.login():
            log("\n[ERROR] Login failed. Please check your credentials.", 'ERROR')
            return

        log("\n[SUCCESS] Login successful!", 'INFO')

        # Try to find booking page automatically
        found_booking = await booking.find_booking_page()

        if not found_booking:
            log("[ERROR] Could not automatically locate booking page", 'ERROR')
            return

        # Wait until target booking time (if scheduled run with invoke_time) AFTER navigation
        # This ensures we're ready to click "Book" exactly when courts are released
        if invoke_time and target_time_str is not None:
            log(f"\n[OPTIMIZED TIMING] Waiting until {target_time_str} PST before booking...", 'INFO')
            await wait_until_booking_time(target_time_str=target_time_str)
            log("[SUCCESS] Target time reached! Reloading page to get fresh availability...", 'INFO')
            await booking.page.reload(wait_until='networkidle')
            log("[OK] Page reloaded with fresh schedule", 'INFO')
        elif not invoke_time:
            log("\n[INFO] No invoke_time - booking immediately without waiting", 'INFO')

        # Book all courts in the to_book_list
        log(f"\n=== Starting booking process ===", 'INFO')
        successful_bookings = 0
        failed_bookings = 0
        booking_details = []  # Track individual booking results for email

        for idx, booking_entry in enumerate(to_book_list, 1):
            # Handle both old format (day, time) and new format (day, time, court)
            if len(booking_entry) == 3:
                _, time_str, court_override = booking_entry
            else:
                _, time_str = booking_entry
                court_override = None

            log(f"\n--- Booking {idx}/{len(to_book_list)} ---", 'INFO')
            log(f"Time: {time_str}", 'INFO')
            log(f"Duration: {BOOKING_DURATION} minutes", 'INFO')

            # Determine which court(s) to book for this time slot
            # Priority: court_override from BOOKING_LIST > COURT_NAME environment variable
            if court_override:
                log(f"Using court specification from BOOKING_LIST: {court_override}", 'INFO')
                if court_override.lower() == "both":
                    courts_to_book = ["North Pickleball Court", "South Pickleball Court"]
                else:
                    courts_to_book = [court_override]
            else:
                # Fall back to COURT_NAME environment variable
                if COURT_NAME.lower() == "both":
                    courts_to_book = ["North Pickleball Court", "South Pickleball Court"]
                else:
                    courts_to_book = [COURT_NAME]

            if len(courts_to_book) > 1:
                log(f"Booking BOTH courts for this time slot", 'INFO')
            else:
                log(f"Booking court: {courts_to_book[0]}", 'INFO')

            # Book each court for this time slot
            for court_idx, court in enumerate(courts_to_book, 1):
                if len(courts_to_book) > 1:
                    log(f"\n  Court {court_idx}/{len(courts_to_book)}: {court}", 'INFO')
                else:
                    log(f"  Court: {court}", 'INFO')

                try:
                    success = await booking.book_court(BOOKING_DATE, time_str, court, BOOKING_DURATION)

                    if success:
                        successful_bookings += 1
                        log(f"  [SUCCESS] {court} booked!", 'INFO')
                        booking_details.append({
                            'status': 'success',
                            'court': court,
                            'date': BOOKING_DATE,
                            'time': time_str,
                            'duration': BOOKING_DURATION
                        })
                    else:
                        failed_bookings += 1
                        log(f"  [WARN] {court} booking may have failed", 'ERROR')
                        booking_details.append({
                            'status': 'failed',
                            'court': court,
                            'date': BOOKING_DATE,
                            'time': time_str,
                            'duration': BOOKING_DURATION,
                            'error': 'Booking may have failed'
                        })

                    # Small delay between court bookings
                    if court_idx < len(courts_to_book):
                        await asyncio.sleep(1)

                except Exception as e:
                    failed_bookings += 1
                    log(f"  [ERROR] {court} booking failed with exception: {e}", 'ERROR')
                    booking_details.append({
                        'status': 'error',
                        'court': court,
                        'date': BOOKING_DATE,
                        'time': time_str,
                        'duration': BOOKING_DURATION,
                        'error': str(e)
                    })

            # Delay between different time slots
            if idx < len(to_book_list):
                await asyncio.sleep(2)

        # Summary
        log(f"\n=== Booking Summary ===", 'INFO')
        total_attempts = len(to_book_list) * len(courts_to_book)
        log(f"Time slots: {len(to_book_list)}", 'INFO')
        log(f"Courts per slot: {len(courts_to_book)}", 'INFO')
        log(f"Total bookings attempted: {total_attempts}", 'INFO')
        log(f"Successful: {successful_bookings}", 'INFO')
        log(f"Failed: {failed_bookings}", 'ERROR')

        # Create booking summary dictionary
        booking_summary = {
            'time_slots': len(to_book_list),
            'courts_per_slot': len(courts_to_book),
            'total_attempts': total_attempts,
            'successful': successful_bookings,
            'failed': failed_bookings,
            'details': booking_details,
            'booking_date': BOOKING_DATE,
            'timestamp': datetime.now(pytz.timezone('America/Los_Angeles')).strftime('%Y-%m-%d %H:%M:%S %Z')
        }

        # Collect screenshot files
        import glob
        screenshot_files = glob.glob('*.png')

        # Send email notification using common email service
        log("\n=== Sending Email Notification ===", 'INFO')
        send_booking_notification(
            booking_summary=booking_summary,
            booking_details=booking_details,
            booking_date=BOOKING_DATE,
            screenshot_files=screenshot_files,
            log_func=log
        )

        # Keep browser open for manual verification
        log("\n=== PROCESS COMPLETE ===", 'INFO')

        if not HEADLESS:
            log("Review the browser window and screenshots.", 'INFO')
            input("\nPress Enter to close browser...")

    except Exception as e:
        log(f"\n[ERROR] Unexpected error: {str(e)}", 'ERROR')
        import traceback
        traceback.print_exc()
        if booking.page:
            await booking.page.screenshot(path='unexpected_error.png')

    finally:
        await booking.close()


if __name__ == "__main__":
    import argparse

    # Parse command-line arguments with named parameters
    parser = argparse.ArgumentParser(description='Book a court at The Athenaeum')
    parser.add_argument('--booking-date-time', help='Booking date and time in "MM/DD/YYYY HH:MM AM/PM" format (e.g., "01/20/2026 10:00 AM")')
    parser.add_argument('--court', help='Court name (e.g., "South Pickleball Court" or "both")')
    parser.add_argument('--duration', help='Duration in minutes (60 or 120)')
    parser.add_argument('--invoke-time', help='Invoke timestamp in PST (MM-DD-YYYY HH:MM:SS) for booking list mode')

    args = parser.parse_args()

    # Parse --booking-date-time into date and time if provided
    booking_date = None
    booking_time = None
    if args.booking_date_time:
        try:
            parts = args.booking_date_time.rsplit(' ', 2)
            if len(parts) == 3:
                booking_date = parts[0]  # MM/DD/YYYY
                booking_time = f"{parts[1]} {parts[2]}"  # HH:MM AM/PM
            else:
                log(f"[ERROR] Invalid --booking-date-time format: '{args.booking_date_time}'", 'ERROR')
                log("[ERROR] Expected format: MM/DD/YYYY HH:MM AM/PM", 'ERROR')
                exit(1)
        except Exception as e:
            log(f"[ERROR] Failed to parse --booking-date-time: {e}", 'ERROR')
            exit(1)

    # Example usage:
    #
    # Manual single booking mode (no BOOKING_LIST needed):
    #   python ath-booking.py --booking-date-time "01/20/2026 10:00 AM" --court "South Pickleball Court" --duration "120"
    #   python ath-booking.py --booking-date-time "01/20/2026 10:00 AM" --court "both" --duration "120"
    #
    # Booking list mode with invoke-time (waits until 12:00:15 AM PST):
    #   python ath-booking.py --invoke-time "01-15-2026 23:55:00"
    #
    # Booking list mode without invoke-time (books immediately, requires BOOKING_LIST in .env):
    #   python ath-booking.py

    asyncio.run(main(booking_date, booking_time, args.court, args.duration, getattr(args, 'invoke_time')))