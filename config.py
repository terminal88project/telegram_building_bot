import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Directory Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Database Path
DB_NAME = "building_management.db"
DB_PATH = f"sqlite:///{os.path.join(BASE_DIR, DB_NAME)}"

# Media Paths
MEDIA_DIR = os.path.join(BASE_DIR, 'media')
RECEIPTS_DIR = os.path.join(MEDIA_DIR, 'receipts')

# Create necessary directories automatically
os.makedirs(RECEIPTS_DIR, exist_ok=True)

# Constants
CURRENCY = "تومان"
