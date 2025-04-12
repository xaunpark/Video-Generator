# config/credentials.py
import os
import logging
from dotenv import load_dotenv
from pathlib import Path # Sử dụng pathlib

load_dotenv()
logger = logging.getLogger(__name__)

# --- Xác định Thư mục Gốc Project ---
# credentials.py nằm trong thư mục con 'config' của thư mục gốc
# Nếu cấu trúc khác, hãy điều chỉnh đường dẫn này
try:
    # __file__ là đường dẫn đến credentials.py
    # .parent là thư mục 'config'
    # .parent nữa là thư mục gốc project
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    logger.debug(f"Project root determined as: {PROJECT_ROOT}")
except NameError:
    # Fallback nếu __file__ không tồn tại (ví dụ: chạy tương tác)
    PROJECT_ROOT = Path('.').resolve()
    logger.warning(f"Could not determine project root reliably using __file__, assuming current directory: {PROJECT_ROOT}")

# --- Lấy API Keys CHỈ TỪ BIẾN MÔI TRƯỜNG ---

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
YOUTUBE_CLIENT_ID = os.getenv('YOUTUBE_CLIENT_ID')
YOUTUBE_CLIENT_SECRET = os.getenv('YOUTUBE_CLIENT_SECRET')
YOUTUBE_REFRESH_TOKEN = os.getenv('YOUTUBE_REFRESH_TOKEN')
SERPER_API_KEY = os.getenv('SERPER_API_KEY')
PEXELS_API_KEY = os.getenv('PEXELS_API_KEY')
PIXABAY_API_KEY = os.getenv('PIXABAY_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

# --- Đọc và Xử lý YouTube Credentials ---
SECRETS_FILENAME = os.getenv('YOUTUBE_CLIENT_SECRETS_FILE', 'client_secrets.json') # Lấy tên file từ .env
YOUTUBE_CLIENT_SECRETS_FILE_PATH = PROJECT_ROOT / SECRETS_FILENAME # Tạo đường dẫn tuyệt đối
YOUTUBE_REFRESH_TOKEN = os.getenv('YOUTUBE_REFRESH_TOKEN')

logger.debug(f"Expected client secrets file path: {YOUTUBE_CLIENT_SECRETS_FILE_PATH}")

###--- Telegram Bot ---### 
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- KIỂM TRA CÁC KEY QUAN TRỌNG VÀ BÁO LỖI NẾU THIẾU ---
missing_keys_files = []
if not OPENAI_API_KEY:
    missing_keys_files.append('OPENAI_API_KEY')
# Bỏ comment nếu bạn dùng ElevenLabs thay vì OpenAI TTS
# if not ELEVENLABS_API_KEY:
#     missing_keys.append('ELEVENLABS_API_KEY')
if not SERPER_API_KEY:
    missing_keys_files.append('SERPER_API_KEY')
if not PEXELS_API_KEY:
    missing_keys_files.append('PEXELS_API_KEY')
if not PIXABAY_API_KEY:
    missing_keys_files.append('PIXABAY_API_KEY')
if not DEEPSEEK_API_KEY:
    missing_keys_files.append('DEEPSEEK_API_KEY')

# Kiểm tra sự tồn tại của file secrets bằng đường dẫn tuyệt đối
if not os.path.exists(YOUTUBE_CLIENT_SECRETS_FILE_PATH):
    logger.error(f"YouTube client secrets file ('{SECRETS_FILENAME}') NOT FOUND at calculated path: {YOUTUBE_CLIENT_SECRETS_FILE_PATH}")
    missing_keys_files.append(f'Client Secrets File ({SECRETS_FILENAME}) at project root')
else:
     logger.debug("YouTube client secrets file found.")

if not YOUTUBE_REFRESH_TOKEN:
    missing_keys_files.append('YOUTUBE_REFRESH_TOKEN (env)')

if missing_keys_files:
    error_message = (
        f"ERROR: The following required items are missing or not found: "
        f"{', '.join(missing_keys_files)}. "
        f"Please check your .env file and project structure."
    )
    logger.critical(error_message) # Dùng critical cho lỗi khởi tạo
    raise ValueError(error_message)
else:
    logger.info("All necessary API keys and credential files loaded/located successfully.")
  