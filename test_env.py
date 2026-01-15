from dotenv import load_dotenv
import os

load_dotenv()

print("Username:", os.getenv('ATHENAEUM_USERNAME'))
print("Password:", "***" if os.getenv('ATHENAEUM_PASSWORD') else "NOT SET")
print("Date:", os.getenv('BOOKING_DATE'))