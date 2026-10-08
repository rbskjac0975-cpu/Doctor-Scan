import os
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
PROVIDER = os.getenv("DATA_PROVIDER", "YFINANCE").upper()
DB_PATH = os.getenv("DB_PATH", "doctorscan.db")
TG_TOKEN, TG_CHAT = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
DISCLAIMER = ("Market signals are informational and are not financial advice. "
              "Trading involves risk. Verify all signals independently.")
