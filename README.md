# Athenaeum Court Booking Automation

Automated court booking script for The Athenaeum at Caltech. Books pickleball and tennis courts with customizable date, time, court selection, and duration.

## Features

- ✅ Automated login to Athenaeum member portal
- ✅ Direct navigation to Court Reservations page
- ✅ Automatic court slot selection by date, time, and court name
- ✅ Configurable booking duration (60 or 120 minutes)
- ✅ Handles Telerik RadComboBox controls
- ✅ Automatic confirmation dialog closure
- ✅ Screenshot capture at each step for debugging
- ✅ Command-line arguments or environment variable configuration

## Prerequisites

- Python 3.7+
- Playwright browser automation library

## Installation

1. Clone or download this repository

2. Install required dependencies:
```bash
pip install playwright python-dotenv
```

3. Install Playwright browsers:
```bash
playwright install chromium
```

## Configuration

### Environment Variables

Create a `.env` file in the project directory with your credentials:

```env
# Required: Your Athenaeum login credentials
ATHENAEUM_USERNAME=your_username
ATHENAEUM_PASSWORD=your_password

# Optional: Default booking parameters (can be overridden by command-line args)
BOOKING_DATE=01/20/2026
BOOKING_TIME=10:00 AM
COURT_NAME=South Pickleball Court
BOOKING_DURATION=120

# Optional: Safety mode (set to False to actually complete bookings)
SAFETY_MODE=False

# Optional: Run in headless mode
HEADLESS=False
```

**⚠️ Security Note:** Never commit your `.env` file to version control. Add it to `.gitignore`.

## Usage

### Command-Line Arguments (Recommended)

Run with named parameters to specify booking details:

```bash
# Full booking specification
python ath-booking-v2.py --date "01/20/2026" --time "10:00 AM" --court "South Pickleball Court" --duration "120"

# Partial arguments (rest use .env defaults)
python ath-booking-v2.py --date "01/21/2026" --time "2:00 PM"

# Just change duration
python ath-booking-v2.py --duration "120"

# Use all .env defaults
python ath-booking-v2.py
```

### Command-Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--date` | Booking date in MM/DD/YYYY format | `"01/20/2026"` |
| `--time` | Booking time in 12-hour format | `"10:00 AM"` |
| `--court` | Court name (see available courts below) | `"South Pickleball Court"` |
| `--duration` | Duration in minutes (60 or 120) | `"120"` |

### Available Courts

- `North Pickleball Court`
- `South Pickleball Court`
- `West Tennis Court`
- `East Tennis Court`

## How It Works

1. **Login**: Authenticates with your Athenaeum credentials
2. **Navigate**: Goes directly to Court Reservations page
3. **Find Slot**: Searches for available court slot matching your criteria
4. **Book**: Opens booking form modal (iframe)
5. **Set Duration**: Uses Telerik RadComboBox API to select duration
6. **Submit**: Clicks "Make Reservation" button
7. **Confirm**: Automatically closes confirmation dialog
8. **Screenshot**: Saves screenshots at each step for verification

## Screenshots

The script saves screenshots during execution:

- `before_login.png` - Login page
- `after_login.png` - After successful login
- `booking_page.png` - Court reservations page
- `booking_01_initial.png` - Calendar view
- `booking_03_target_slot.png` - Selected time slot
- `booking_04_booking_form.png` - Booking form modal
- `booking_05a_before_submit.png` - Before clicking submit
- `booking_06_confirmation.png` - Confirmation page

## Troubleshooting

### Issue: Login fails
**Solution:** Verify your credentials in `.env` file are correct

### Issue: Court slot not found
**Solution:**
- Check the date format is MM/DD/YYYY
- Verify the time format includes AM/PM
- Ensure the court name matches exactly (case-sensitive)
- The slot may already be booked - try a different time

### Issue: Duration not changing from 60 to 120 minutes
**Solution:** This script uses Telerik RadComboBox API. If it fails, check the console output for error messages.

### Issue: Modal/iframe not loading
**Solution:** The script waits for the iframe to load. If network is slow, you may need to increase wait times in the code.

### Issue: Unicode emoji errors on Windows
**Solution:** The script has been updated to use ASCII markers `[OK]`, `[ERROR]`, `[WARN]` instead of Unicode emojis for Windows compatibility.

## Safety Mode

Safety mode is controlled by the `SAFETY_MODE` environment variable in `.env`:

- `SAFETY_MODE=True` (default): Stops before clicking "Make Reservation" button
- `SAFETY_MODE=False`: Completes the full booking process

## Technical Details

### Key Technologies
- **Playwright**: Browser automation
- **Async/Await**: Asynchronous Python execution
- **Telerik RadComboBox**: Custom dropdown handling via JavaScript API

### Browser Configuration
- Uses Chromium browser
- Viewport: 1920x1080
- Configurable headless mode
- Network idle wait strategy

### Form Handling
The booking form uses Telerik RadComboBox controls, not standard HTML `<select>` elements. The script:
1. Detects Telerik controls by ID pattern
2. Uses `window.$find()` to get the combo object
3. Calls `findItemByText()` to locate the duration option
4. Uses `set_selectedIndex()` and `set_text()` to select it

## Known Limitations

- Only supports single court bookings (not multiple simultaneous bookings)
- Requires valid Athenaeum member credentials
- Court availability depends on club rules and reservation windows
- May need updates if website structure changes

## Contributing

This is a personal automation tool. If you find bugs or have improvements:
1. Test thoroughly before committing changes
2. Update documentation for any new features
3. Maintain screenshot captures for debugging

## License

Personal use only. Respect The Athenaeum's terms of service.

## Disclaimer

This tool is for personal convenience and should be used responsibly:
- ⚠️ Do not abuse the booking system
- ⚠️ Follow all club rules and reservation policies
- ⚠️ Do not share your credentials
- ⚠️ The Athenaeum may modify their website at any time, breaking this script

## Version History

### v2.0 (Current)
- ✅ Command-line arguments with argparse
- ✅ Telerik RadComboBox support for duration selection
- ✅ Automatic confirmation dialog closure
- ✅ Direct URL navigation to Court Reservations
- ✅ Improved iframe detection and handling
- ✅ Better error handling and debugging output
- ✅ Windows compatibility (ASCII markers)

### v1.0
- Initial implementation with basic booking functionality
