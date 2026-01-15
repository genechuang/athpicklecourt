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
import pytz

# Load environment variables from .env file
load_dotenv()


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
        print("Navigating to login page...")
        await self.page.goto(f"{self.base_url}/member-login", wait_until='networkidle')
        
        # Wait for page to fully load
        
        try:
            # Save initial page state
#            await self.page.screenshot(path='01_initial_page.png')
            
            # Try to find login form - try multiple possible selectors
            print("Looking for login form...")
            
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
                        print(f"! Found username field: {selector}")
                        break
                except:
                    continue
            
            # Try to find password field
            for selector in password_selectors:
                try:
                    password_field = await self.page.wait_for_selector(selector, timeout=3000)
                    if password_field:
                        print(f"! Found password field: {selector}")
                        break
                except:
                    continue
            
            if not username_field or not password_field:
                print("! Could not find login fields")
                print("\nDebugging - All input fields on page:")
                inputs = await self.page.query_selector_all('input')
                for inp in inputs:
                    id_attr = await inp.get_attribute('id')
                    name_attr = await inp.get_attribute('name')
                    type_attr = await inp.get_attribute('type')
                    placeholder = await inp.get_attribute('placeholder')
                    print(f"  Input: id={id_attr}, name={name_attr}, type={type_attr}, placeholder={placeholder}")
                
                # Save page HTML for inspection
                content = await self.page.content()
                with open('login_page_source.html', 'w', encoding='utf-8') as f:
                    f.write(content)
                print("\n! Page HTML saved to login_page_source.html")
                return False
            
            print("Entering credentials...")
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
                        print(f"! Found login button: {selector}")
                        break
                except:
                    continue
            
            if not login_button:
                print("! Could not find login button")
                return False
            
            # Click login and wait for navigation
            print("Clicking login button...")
            
            # The button might trigger JavaScript instead of form submission
            # Try clicking and waiting for navigation, but with fallback
            try:
                async with self.page.expect_navigation(timeout=15000, wait_until='networkidle'):
                    await login_button.click()
            except PlaywrightTimeout:
                # If navigation doesn't happen, wait a bit for JavaScript
                print("  No navigation detected, waiting for JavaScript...")
            
            # Wait a moment for any redirects
            
            # Check if login was successful
            current_url = self.page.url
            if "member-login" in current_url.lower():
                print("! Login failed - still on login page")
#                await self.page.screenshot(path='03_login_failed.png')
                return False
                
            print(f"! Login successful! Current URL: {current_url}")
#            await self.page.screenshot(path='04_after_login.png')
            return True
            
        except PlaywrightTimeout as e:
            print(f"! Timeout during login: {str(e)}")
#            await self.page.screenshot(path='login_timeout.png')
            return False
        except Exception as e:
            print(f"! Error during login: {str(e)}")
#            await self.page.screenshot(path='login_error.png')
            import traceback
            traceback.print_exc()
            return False
    
    async def find_booking_page(self):
        """Navigate directly to the court booking page"""
        print("\nNavigating directly to Court Reservations page...")

        try:
            # Direct URL to Court Reservations
            booking_url = "https://www.athenaeumcaltech.com/Default.aspx?p=dynamicmodule&pageid=378495&tt=booking&ssid=295150&vnf=1"

            await self.page.goto(booking_url, wait_until='networkidle')

            print(f"! Navigated to: {self.page.url}")
#            await self.page.screenshot(path='booking_page.png')
            return True

        except Exception as e:
            print(f"Error navigating to booking page: {str(e)}")
#            await self.page.screenshot(path='navigation_error.png')
            return False
    
    async def explore_page_structure(self):
        """Explore and document the current page structure"""
        print("\n=== PAGE STRUCTURE ANALYSIS ===")
        
        # Get page title
        title = await self.page.title()
        print(f"Page Title: {title}")
        print(f"Current URL: {self.page.url}")
        
        # Look for forms
        forms = await self.page.query_selector_all('form')
        print(f"\nForms found: {len(forms)}")
        
        # Look for date inputs
        date_inputs = await self.page.query_selector_all(
            'input[type="date"], input[type="text"][id*="date"], input[name*="date"]'
        )
        print(f"Date inputs found: {len(date_inputs)}")
        for inp in date_inputs:
            id_attr = await inp.get_attribute('id')
            name_attr = await inp.get_attribute('name')
            print(f"  - ID: {id_attr}, Name: {name_attr}")
        
        # Look for time selectors
        time_selects = await self.page.query_selector_all(
            'select[id*="time"], select[name*="time"], input[type="time"]'
        )
        print(f"Time selectors found: {len(time_selects)}")
        
        # Look for buttons
        buttons = await self.page.query_selector_all('button, input[type="submit"]')
        print(f"\nButtons found: {len(buttons)}")
        for btn in buttons[:10]:  # Show first 10
            text = await btn.inner_text()
            if text.strip():
                print(f"  - {text.strip()}")
        
        # Check for iframes (many booking systems use them)
        frames = self.page.frames
        print(f"\nIframes found: {len(frames) - 1}")  # -1 for main frame
        for frame in frames[1:]:  # Skip main frame
            print(f"  - {frame.url}")
        
        # Save page content
        content = await self.page.content()
        with open('page_structure.html', 'w', encoding='utf-8') as f:
            f.write(content)
        print("\nPage HTML saved to: page_structure.html")
        
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
        print(f"\n=== ATTEMPTING COURT BOOKING ===")
        print(f"Court: {court_name}")
        print(f"Date: {date_str}")
        print(f"Time: {start_time}")
        print(f"Duration: {duration_minutes} Minutes")
        
        try:
            # Take initial screenshot
#            await self.page.screenshot(path='booking_01_initial.png', full_page=True)
#            print("! Screenshot: booking_01_initial.png")
            
            # Look for the date input field
            print("\nLooking for date input field...")
            date_input = await self.page.query_selector('#txtDate')
            
            if not date_input:
                print("! Could not find #txtDate field")
                return False
            
            # Check if it's visible
            is_visible = await date_input.is_visible()
            print(f"Date field visible: {is_visible}")
            
            if is_visible:
                print(f"Entering date: {date_str}")
                
                # Click on the date field
                await date_input.click()
                
                # Clear existing value
                await date_input.press('Control+A')
                await date_input.press('Backspace')
                
                # Type the date (MM/DD/YYYY format)
                await date_input.type(date_str, delay=1)
                
                # Press Enter to submit the date and reload calendar
                await date_input.press('Enter')
                
                # Wait for the calendar to reload with new date - this is important to wait
                print("Waiting for calendar to update...")
                await asyncio.sleep(1)
                
#                await self.page.screenshot(path='booking_02_date_entered.png', full_page=True)
#                print("! Date entered, calendar updated")
                
            else:
                print("! Date field is not visible")
                return False
            
            # Now find the booking link for the specific time and court
            print(f"\nSearching for available slot: {start_time} - {court_name}")
            
            # Find all clickable links that match the court name
            # Only GREEN available slots will be clickable links
            # White/gray text (already booked) = no link, will be skipped
            # Blue boxes (your reservations) = EDIT button, not court name link
            all_court_links = await self.page.query_selector_all(f'a:has-text("{court_name}")')
            
            print(f"Found {len(all_court_links)} clickable instances of '{court_name}'")
            
            booking_link = None
            checked_count = 0
            
            # Actually, looking at the HTML, we need to find DIVs with onclick, not links!
            # Available courts are in divs with class "rbm_TimeSlotPanelSlotAvailable" and onclick handlers
            print("\nSearching for clickable court divs...")
            
            # Find all table cells that might contain bookable courts
            all_cells = await self.page.query_selector_all('td[class*="rbm_"]')
            
            print(f"Found {len(all_cells)} table cells to check")
            
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
                        print(f"Debug #{checked_count}:")
                        print(f"  Court div text: '{div_text.strip()[:50]}'")
                        print(f"  Row text: '{row_text.strip()[:100]}'")
                        print(f"  Has onclick: {bool(onclick)}")
                        print(f"  Looking for: '{start_time}'")
                    
                    # Check if this row has our time
                    if start_time in row_text:
                        booking_link = court_div
                        print(f"\n! Found bookable court!")
                        print(f"  Court: {div_text.strip()[:50]}")
                        print(f"  Time: {start_time}")
                        break
                        
                except Exception as e:
                    continue
            
            print(f"\nTotal bookable courts checked for '{court_name}': {checked_count}")
            
            if booking_link:
                # Take screenshot of the specific slot
                try:
#                    await booking_link.screenshot(path='booking_03_target_slot.png')
                    print("! Screenshot of target slot: booking_03_target_slot.png")
                except:
                    pass
                
                # Get the link details
                link_text = await booking_link.inner_text()
                href = await booking_link.get_attribute('href')
                
                print(f"\n{'='*60}")
                print(f"READY TO BOOK")
                print(f"{'='*60}")
                print(f"Court: {link_text.strip()}")
                print(f"Time: {start_time}")
                print(f"Date: {date_str}")
                
                # Check safety mode
                safety_mode = os.getenv('SAFETY_MODE', 'True').lower() != 'false'
                
                if safety_mode:
                    print(f"\n{'='*60}")
                    print("SAFETY MODE ENABLED - BOOKING NOT SUBMITTED")
                    print(f"{'='*60}")
                    print("The script found the correct booking slot.")
                    print("\nReview the screenshots:")
                    print("  - booking_01_initial.png (initial calendar)")
                    print("  - booking_02_date_entered.png (after date entry)")
                    print("  - booking_03_target_slot.png (the slot to book)")
                    print("\nTo complete the booking, update your .env file:")
                    print("  SAFETY_MODE=false")
                    print("\nThen run the script again.")
                    
                else:
                    # Actually click to book
                    print(f"\n! SAFETY MODE OFF - PROCEEDING WITH BOOKING...")
                    await booking_link.click()
                    
                    # Wait for booking form to load IN IFRAME
                    print("Waiting for booking form modal with iframe...")

                    # Wait for iframe to appear
                    try:
                        await self.page.wait_for_selector('iframe', timeout=10000)
                        print("! Found iframe")
                    except:
                        print("! No iframe detected")


                    # Take screenshot of booking form
#                    await self.page.screenshot(path='booking_04_booking_form.png', full_page=True)
                    print("! Screenshot: booking_04_booking_form.png")

                    # Get the iframe that contains the booking form
                    print("\nSearching for iframe with booking form...")
                    frames = self.page.frames
                    booking_frame = None

                    for frame in frames:
                        frame_url = frame.url
                        if 'rbmPop' in frame_url or 'MakebookingTime' in frame_url or 'dialog.aspx' in frame_url:
                            booking_frame = frame
                            print(f"! Found booking iframe: {frame_url[:80]}")
                            break

                    if not booking_frame:
                        print("! Booking iframe not found, using main page")
                        booking_frame = self.page.main_frame

                    # Wait for iframe content to load by waiting for form elements
                    print("NOT Waiting for iframe content to load...")
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
                    print(f"Iframe content: title='{iframe_content['title']}', selects={iframe_content['hasSelects']}, buttons={iframe_content['hasButtons']}")
                    print(f"Body preview: {iframe_content['bodyText'][:100]}...")

                    # Save iframe HTML for debugging
                    with open('iframe_content.html', 'w', encoding='utf-8') as f:
                        f.write(iframe_content['bodyHTML'])
                    print("! Saved iframe HTML to iframe_content.html")

                    # Fill out the booking form IN THE IFRAME
                    print("\nSearching for form elements in iframe...")

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

                    print(f"Found {len(select_info)} select elements:")
                    for info in select_info:
                        print(f"  [{info['index']}] visible={info['visible']}, current='{info['currentText']}', hasMinutes={info['hasMinutes']}, id={info['id']}")

                    # Find the duration select
                    duration_idx = None
                    for info in select_info:
                        if info['hasMinutes'] and info['visible']:
                            duration_idx = info['index']
                            print(f"! Found duration dropdown at index {duration_idx}")
                            break

                    # If not found visible, try any with minutes
                    if duration_idx is None:
                        for info in select_info:
                            if info['hasMinutes']:
                                duration_idx = info['index']
                                print(f"! Found duration dropdown at index {duration_idx} (not marked visible)")
                                break

                    # Change duration
                    if duration_idx is not None:
                        print(f"\nChanging duration to {duration_minutes} minutes...")

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
                                print(f"! Duration set to {duration_minutes} minutes")
                            else:
                                print(f"! Could not find {duration_minutes} minutes option")

                        except Exception as e:
                            print(f"! Could not change duration: {str(e)[:100]}")
                    else:
                        # Try Telerik RadComboBox for duration
                        print("! Standard dropdown not found, trying Telerik RadComboBox...")
                        try:
                            # Use JavaScript to interact with Telerik RadComboBox
                            success = await booking_frame.evaluate(f'''() => {{
                                // Find the RadComboBox by input ID
                                const input = document.getElementById('ctl00_ctrl_MakeBookingTime_drpDuration_tCombo_Input');
                                if (!input) return {{ success: false, reason: 'input not found' }};

                                // Get the Telerik combo object
                                const comboId = 'ctl00_ctrl_MakeBookingTime_drpDuration_tCombo';
                                const combo = window.$find(comboId);

                                if (combo && typeof combo.findItemByText === 'function') {{
                                    // Try to find and select the item
                                    const item = combo.findItemByText('{duration_minutes} Minutes');
                                    if (item) {{
                                        combo.set_selectedIndex(item.get_index());
                                        combo.set_text(item.get_text());
                                        return {{ success: true, method: 'telerik API' }};
                                    }} else {{
                                        // List available items for debugging
                                        const items = combo.get_items();
                                        const itemTexts = [];
                                        for (let i = 0; i < items.get_count(); i++) {{
                                            itemTexts.push(items.getItem(i).get_text());
                                        }}
                                        return {{ success: false, reason: 'item not found', available: itemTexts }};
                                    }}
                                }} else {{
                                    return {{ success: false, reason: 'combo object not found or no API' }};
                                }}
                            }}''')

                            if success.get('success'):
                                print(f"! Set Telerik duration to {duration_minutes} minutes using {success.get('method')}")
                            else:
                                print(f"! Could not set Telerik duration: {success.get('reason')}")
                                if 'available' in success:
                                    print(f"   Available options: {success['available']}")
                        except Exception as e:
                            print(f"! Could not set Telerik duration: {str(e)[:100]}")

                    
                    # Take screenshot after filling form
#                    await self.page.screenshot(path='booking_05_form_filled.png', full_page=True)
                    print("! Screenshot: booking_05_form_filled.png")
                    
                    # Look for "Make Reservation" button IN THE IFRAME
                    print("\nSearching for buttons in iframe...")

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

                    print(f"Found {len(all_postback)} elements with __doPostBack:")
                    for item in all_postback[:10]:
                        print(f"  {item['tag']}: '{item['text']}' hasLbBook={item['hasLbBook']}")
                        print(f"     onclick={item['onclick']}")

                    # PRIORITY 0: Try finding button by ID pattern (MOST RELIABLE)
                    print("\nTrying to find button by ID containing 'lbBook'...")
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
                        print(f"! Found button by ID: {button_by_id['id']}")
                        print(f"  Tag: {button_by_id['tag']}, Text: '{button_by_id['text']}'")

                        print("\n! Clicking Make Reservation button by ID...")
#                        await self.page.screenshot(path='booking_05a_before_submit.png', full_page=True)

                        try:
                            await booking_frame.click(f"#{button_by_id['id']}")
                            print("! Clicked Booked!")

#                            await self.page.screenshot(path='booking_06_confirmation.png', full_page=True)

                            # Close the confirmation dialog
                            print("\nClosing confirmation dialog...")
                            try:
                                # Wait for dialog to appear
#                                await asyncio.sleep(1)

                                # Debug: Try to find what links/buttons exist
                                print("! Searching for close button...")

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
                                print("! Checking iframe for close button...")
                                for selector in close_selectors:
                                    try:
                                        close_btn = await booking_frame.query_selector(selector)
                                        if close_btn:
                                            is_visible = await close_btn.is_visible()
                                            print(f"! Found element with '{selector}', visible: {is_visible}")
                                            if is_visible:
                                                await close_btn.click()
                                                print(f"! Closed confirmation dialog (iframe) with: {selector}")
                                                closed = True
                                                await asyncio.sleep(1)
                                                break
                                    except Exception as e:
                                        continue

                                # If not found in iframe, try main page
                                if not closed:
                                    print("! Checking main page for close button...")
                                    for selector in close_selectors:
                                        try:
                                            close_btn = await self.page.query_selector(selector)
                                            if close_btn:
                                                is_visible = await close_btn.is_visible()
                                                print(f"! Found element with '{selector}', visible: {is_visible}")
                                                if is_visible:
                                                    await close_btn.click()
                                                    print(f"! Closed confirmation dialog (main page) with: {selector}")
                                                    closed = True
                                                    await asyncio.sleep(1)
                                                    break
                                        except Exception as e:
                                            continue

                                # Last resort: Use JavaScript to find and click any link with "close" text
                                if not closed:
                                    print("! Trying JavaScript approach...")
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
                                            print(f"! Closed with JS (iframe): {result}")
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
                                            print(f"! Closed with JS (main page): {result}")
                                            closed = True
                                    except:
                                        pass

                                if not closed:
                                    print("! Could not find close button, confirmation dialog may remain open")

                            except Exception as e:
                                print(f"! Could not close dialog automatically: {str(e)[:80]}")

                            print("\n" + "="*60)
                            print("! BOOKING SUBMITTED!")
                            print("="*60)

                            print("\n=== PROCESS COMPLETE ===")
                            return True
                        except Exception as e:
                            print(f"! Click error: {str(e)}")
                    else:
                        print("! Button not found by ID")

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
                    print(f"Found {len(button_info)} elements with __doPostBack and lbBook in iframe")

                    # Show all found buttons
                    for info in button_info:
                        print(f"  [{info['index']}] {info['tagName']}: '{info['text']}', visible={info['visible']}")
                        print(f"     onclick: {info['onclick'][:80]}")

                    # Debug: Show ALL button texts to find the right one
                    print("\nAll visible buttons (first 30):")
                    for i, info in enumerate(button_info[:30]):
                        print(f"  [{info['index']}] {info['tagName']}: '{info['text']}'")

                    # Look for the reservation button
                    reservation_btn_idx = None

                    print("\nLooking for reservation button...")

                    # PRIORITY 1: Look for the button with __doPostBack and lbBook
                    for info in button_info:
                        onclick_lower = info['onclick'].lower()

                        if '__dopostback' in onclick_lower and 'lbbook' in onclick_lower:
                            reservation_btn_idx = info['index']
                            print(f"! Found reservation button (by onclick) at index {reservation_btn_idx}: '{info['text']}'")
                            print(f"  onclick: {info['onclick']}")
                            break

                    # PRIORITY 2: Look for text with "Make Reservation"
                    if reservation_btn_idx is None:
                        for info in button_info:
                            text_lower = info['text'].lower()

                            # Debug: print buttons that might be relevant
                            if any(keyword in text_lower for keyword in ['reserv', 'book', 'submit', 'save', 'confirm', 'ok']):
                                print(f"  Candidate [{info['index']}] {info['tagName']}: '{info['text']}', onclick='{info['onclick'][:40]}'")

                            # Look for explicit reservation text
                            if any(keyword in text_lower for keyword in ['make reservation', 'create reservation', 'reserve']):
                                # Exclude cancel/close buttons
                                if not any(neg in text_lower for neg in ['cancel', 'close', 'discard', 'delete', 'minimize']):
                                    reservation_btn_idx = info['index']
                                    print(f"! Found reservation button (by text) at index {reservation_btn_idx}: '{info['text']}'")
                                    break

                    # PRIORITY 3: Fallback - look for submit buttons
                    if reservation_btn_idx is None:
                        print("No explicit reservation button found, looking for submit buttons...")
                        for info in button_info:
                            text_lower = info['text'].lower()
                            onclick_lower = info['onclick'].lower()

                            # Look for submit-like buttons but exclude minimize/cancel/close
                            if info['tagName'] == 'INPUT' or 'submit' in text_lower or text_lower == 'ok':
                                if not any(neg in text_lower for neg in ['cancel', 'close', 'discard', 'minimize', 'delete']):
                                    if not any(neg in onclick_lower for neg in ['min', 'cancel', 'close']):
                                        reservation_btn_idx = info['index']
                                        print(f"! Found submit button at index {reservation_btn_idx}: '{info['text']}'")
                                        break

                    # Click the button
                    if reservation_btn_idx is not None:
                        print(f"\n! Clicking reservation button at index {reservation_btn_idx}...")
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
                                print("! Clicked!")
#                                await asyncio.sleep(2)
                            else:
                                print("! Button click failed")

                        except Exception as e:
                            print(f"! Click error: {str(e)[:80]}")
                    else:
                        print("\n! 'Make Reservation' button not found in visible elements")
                    
                    # Final screenshot
#                    await self.page.screenshot(path='booking_06_confirmation.png', full_page=True)
                    print("\n" + "="*60)
                    print("! BOOKING PROCESS COMPLETED!")
                    print("="*60)
                    print("Check booking_06_confirmation.png for confirmation")
                    print("If successful, the court should now appear in blue on the calendar")
                
                return True
                
            else:
                print(f"\n! NO AVAILABLE SLOT FOUND")
                print(f"{'='*60}")
                print(f"Could not find an available (green) slot for:")
                print(f"  Court: {court_name}")
                print(f"  Time: {start_time}")
                print(f"  Date: {date_str}")
                print(f"\nPossible reasons:")
                print(f"  1. Court is already booked (gray text, no link)")
                print(f"  2. You already have a reservation (blue box with EDIT)")
                print(f"  3. Time format doesn't match (use 'H:MM AM' format)")
                print(f"  4. Court name doesn't match exactly")
                print(f"\nCheck booking_02_date_entered.png to see available slots")
                print(f"(Green boxes = available, Gray text = booked by others)")
                
#                await self.page.screenshot(path='booking_no_slot_found.png', full_page=True)
                
                return False
            
        except Exception as e:
            print(f"\n! ERROR DURING BOOKING")
            print(f"{'='*60}")
            print(f"{str(e)}")
#            await self.page.screenshot(path='booking_error.png', full_page=True)
            import traceback
            traceback.print_exc()
            return False
    
    async def interactive_mode(self):
        """Interactive mode for manual navigation and exploration"""
        print("\n=== INTERACTIVE MODE ===")
        print("Browser window opened. You can:")
        print("1. Manually navigate to the booking page")
        print("2. Inspect the page structure")
        print("3. Press Enter when ready to continue automation")
        
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
        print("Browser closed")


def get_booking_list(booking_list_str, invoke_datetime):
    """
    Parse BOOKING_LIST and filter bookings for today's day of week.

    Args:
        booking_list_str: String like "Tuesday 7:00 PM,Wednesday 7:00 PM,Friday 4:00 PM,Sunday 10:00 AM"
                         Format: <DayName> <Time>, comma-separated
        invoke_datetime: datetime object representing when the script was invoked

    Returns:
        List of tuples: [(day_name, time_str), ...]

    Example:
        If today is Tuesday and booking_list has "Tuesday 7:00 PM,Wednesday 7:00 PM"
        Returns: [("Tuesday", "7:00 PM")]
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

    # Get the day of week from invoke_datetime
    python_weekday = invoke_datetime.weekday()  # 0=Mon, 6=Sun
    today_name = day_names_display[python_weekday]

    print(f"\nProcessing BOOKING_LIST for day of week: {today_name}")

    to_book_list = []

    # Parse the booking list
    entries = booking_list_str.split(',')
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        # Parse "Tuesday 7:00 PM" format
        parts = entry.split(' ', 1)
        if len(parts) != 2:
            print(f"  ! Skipping invalid entry: '{entry}'")
            continue

        try:
            day_str = parts[0].strip().lower()
            time_str = parts[1].strip()

            # Check if day name is valid
            if day_str not in day_names:
                print(f"  ! Invalid day name: '{parts[0]}' (expected: Monday, Tuesday, etc.)")
                continue

            day_display = parts[0].strip().title()  # Preserve capitalization from input
            print(f"  Parsed: {day_display} at {time_str}")

            # Check if this booking is for today
            if day_names[day_str] == python_weekday:
                to_book_list.append((day_display, time_str))
                print(f"    -> MATCH! Adding to booking queue")
            else:
                print(f"    -> Skip (not today)")

        except (ValueError, IndexError) as e:
            print(f"  ! Error parsing entry '{entry}': {e}")
            continue

    print(f"\nTotal bookings to make today: {len(to_book_list)}")
    return to_book_list


async def wait_until_booking_time(target_hour=0, target_minute=0, target_second=15, timezone_name='America/Los_Angeles'):
    """
    Wait until the specified time in PST/PDT timezone.

    Args:
        target_hour: Hour to wait for (0-23), default 0 for midnight
        target_minute: Minute to wait for (0-59), default 0
        target_second: Second to wait for (0-59), default 15
        timezone_name: Timezone string, default 'America/Los_Angeles' for PST/PDT
    """
    # Get the timezone
    target_tz = pytz.timezone(timezone_name)

    # Get current time in target timezone
    now_tz = datetime.now(target_tz)

    # Calculate target time today
    target_time = now_tz.replace(hour=target_hour, minute=target_minute, second=target_second, microsecond=0)

    # If we've already passed the target time today, target tomorrow
    if now_tz >= target_time:
        target_time = target_time + timedelta(days=1)

    # Calculate seconds to wait
    wait_seconds = (target_time - now_tz).total_seconds()

    print(f"\n=== Waiting for booking time ===")
    print(f"Current time ({timezone_name}): {now_tz.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Target time ({timezone_name}): {target_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Waiting {wait_seconds:.1f} seconds ({wait_seconds/60:.1f} minutes)...")

    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)
        print(f"[SUCCESS] Reached target time! Proceeding with booking...")
    else:
        print(f"[WARN] Target time already passed, proceeding immediately")


async def main(booking_date=None, booking_time=None, court_name=None, booking_duration=None, invoke_time=None):
    # ==================== CONFIGURATION ====================
    # Load credentials from environment variables
    import os

    USERNAME = os.getenv('ATHENAEUM_USERNAME')
    PASSWORD = os.getenv('ATHENAEUM_PASSWORD')

    if not USERNAME or not PASSWORD:
        print("ERROR: Missing credentials!")
        print("Please set environment variables in your .env file")
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
    # TWO MODES: Booking List Mode vs. Manual Single Booking Mode
    # =======================================================

    # Check if BOOKING_LIST is set (Booking List Mode)
    BOOKING_LIST = os.getenv('BOOKING_LIST', '')

    if BOOKING_LIST:
        print("\n=== BOOKING LIST MODE ===")

        # Determine the reference datetime for day-of-week matching
        if invoke_time:
            print(f"Script invoked at: {invoke_time}")
            # Parse invoke_time (format: "MM-DD-YYYY HH:MM:SS" UTC)
            try:
                invoke_datetime_utc = datetime.strptime(invoke_time, "%m-%d-%Y %H:%M:%S")
                invoke_datetime_utc = pytz.utc.localize(invoke_datetime_utc)

                # Convert to PST/PDT for processing
                pst_tz = pytz.timezone('America/Los_Angeles')
                invoke_datetime_pst = invoke_datetime_utc.astimezone(pst_tz)

                print(f"Converted to PST/PDT: {invoke_datetime_pst.strftime('%m/%d/%Y %H:%M:%S %Z')}")
            except Exception as e:
                print(f"ERROR: Failed to parse invoke_time '{invoke_time}': {e}")
                return
        else:
            # No invoke_time provided - use current PST time
            print("No invoke_time provided, using current PST time")
            pst_tz = pytz.timezone('America/Los_Angeles')
            invoke_datetime_pst = datetime.now(pst_tz)
            print(f"Current PST time: {invoke_datetime_pst.strftime('%m/%d/%Y %H:%M:%S %Z')}")

        print(f"BOOKING_LIST: {BOOKING_LIST}")

        # Get list of bookings for today's day of week
        to_book_list = get_booking_list(BOOKING_LIST, invoke_datetime_pst)

        if not to_book_list:
            print("\n[INFO] No bookings scheduled for today. Exiting.")
            return

        print(f"\n=== Bookings to make today ===")
        for idx, (day_of_week, time_str) in enumerate(to_book_list, 1):
            print(f"  {idx}. {time_str}")

        # Only wait if invoke_time was provided (scheduled GitHub Actions run)
        if invoke_time:
            # Wait until 12:00:15 AM PST before proceeding
            await wait_until_booking_time(target_hour=0, target_minute=0, target_second=15)
        else:
            print("\n[INFO] No invoke_time provided - booking immediately without waiting")

        # Calculate booking date (7 days from now in PST)
        booking_date_obj = invoke_datetime_pst + timedelta(days=7)
        BOOKING_DATE = booking_date_obj.strftime('%m/%d/%Y')
        print(f"\nBooking date (7 days out): {BOOKING_DATE}")

    else:
        print("\n=== MANUAL SINGLE BOOKING MODE ===")
        # Manual booking mode with explicit parameters
        BOOKING_DATE = booking_date or os.getenv('BOOKING_DATE', '01/20/2026')
        BOOKING_TIME = booking_time or os.getenv('BOOKING_TIME', '10:00 AM')

        to_book_list = [(None, BOOKING_TIME)]  # Single booking

        print(f"Booking: {BOOKING_DATE} at {BOOKING_TIME}")
        print(f"Court: {COURT_NAME}")
        print(f"Duration: {BOOKING_DURATION} minutes")

    # =======================================================
    # START BOOKING PROCESS
    # =======================================================

    booking = AthenaeumBooking(USERNAME, PASSWORD, headless=HEADLESS)

    try:
        # Setup browser
        await booking.setup()
        print("\n[OK] Browser initialized")

        # Login
        if not await booking.login():
            print("\n[ERROR] Login failed. Please check your credentials.")
            return

        print("\n[SUCCESS] Login successful!")

        # Try to find booking page automatically
        found_booking = await booking.find_booking_page()

        if not found_booking:
            print("[ERROR] Could not automatically locate booking page")
            return

        # Book all courts in the to_book_list
        print(f"\n=== Starting booking process ===")
        successful_bookings = 0
        failed_bookings = 0

        # If COURT_NAME is "both", book both courts; otherwise use COURT_NAME
        if COURT_NAME.lower() == "both":
            courts_to_book = ["North Pickleball Court", "South Pickleball Court"]
            print(f"COURT_NAME is 'both' - will book BOTH courts for each time slot")
        else:
            courts_to_book = [COURT_NAME]
            print(f"Will book: {COURT_NAME}")

        for idx, (day_of_week, time_str) in enumerate(to_book_list, 1):
            print(f"\n--- Booking {idx}/{len(to_book_list)} ---")
            print(f"Time: {time_str}")
            print(f"Duration: {BOOKING_DURATION} minutes")

            # Book each court for this time slot
            for court_idx, court in enumerate(courts_to_book, 1):
                if len(courts_to_book) > 1:
                    print(f"\n  Court {court_idx}/{len(courts_to_book)}: {court}")
                else:
                    print(f"  Court: {court}")

                try:
                    success = await booking.book_court(BOOKING_DATE, time_str, court, BOOKING_DURATION)

                    if success:
                        successful_bookings += 1
                        print(f"  [SUCCESS] {court} booked!")
                    else:
                        failed_bookings += 1
                        print(f"  [WARN] {court} booking may have failed")

                    # Small delay between court bookings
                    if court_idx < len(courts_to_book):
                        await asyncio.sleep(1)

                except Exception as e:
                    failed_bookings += 1
                    print(f"  [ERROR] {court} booking failed with exception: {e}")

            # Delay between different time slots
            if idx < len(to_book_list):
                await asyncio.sleep(2)

        # Summary
        print(f"\n=== Booking Summary ===")
        total_attempts = len(to_book_list) * len(courts_to_book)
        print(f"Time slots: {len(to_book_list)}")
        print(f"Courts per slot: {len(courts_to_book)}")
        print(f"Total bookings attempted: {total_attempts}")
        print(f"Successful: {successful_bookings}")
        print(f"Failed: {failed_bookings}")

        # Keep browser open for manual verification
        print("\n=== PROCESS COMPLETE ===")

        if not HEADLESS:
            print("Review the browser window and screenshots.")
            input("\nPress Enter to close browser...")

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")
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
    parser.add_argument('--date', help='Booking date in MM/DD/YYYY format (e.g., "01/20/2026")')
    parser.add_argument('--time', help='Booking time (e.g., "10:00 AM")')
    parser.add_argument('--court', help='Court name (e.g., "South Pickleball Court" or "both")')
    parser.add_argument('--duration', help='Duration in minutes (60 or 120)')
    parser.add_argument('--invoke-time', help='Invoke timestamp in UTC (MM-DD-YYYY HH:MM:SS) for booking list mode')

    args = parser.parse_args()

    # Example usage:
    #
    # Manual single booking mode (no BOOKING_LIST needed):
    #   python ath-booking.py --date "01/20/2026" --time "10:00 AM" --court "South Pickleball Court" --duration "120"
    #   python ath-booking.py --date "01/20/2026" --time "10:00 AM" --court "both" --duration "120"
    #
    # Booking list mode with invoke-time (waits until 12:00:15 AM PST):
    #   python ath-booking.py --invoke-time "01-15-2026 07:59:30"
    #
    # Booking list mode without invoke-time (books immediately, requires BOOKING_LIST in .env):
    #   python ath-booking.py

    asyncio.run(main(args.date, args.time, args.court, args.duration, getattr(args, 'invoke_time')))