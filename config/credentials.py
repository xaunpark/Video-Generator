# config/credentials.py
import os
import logging # Thêm logging để báo lỗi
from dotenv import load_dotenv

# Nạp biến môi trường từ file .env (đảm bảo dòng này ở đầu)
load_dotenv()

logger = logging.getLogger(__name__) # Tạo logger cho file này

# --- Lấy API Keys CHỈ TỪ BIẾN MÔI TRƯỜNG ---

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
YOUTUBE_CLIENT_ID = os.getenv('YOUTUBE_CLIENT_ID')
YOUTUBE_CLIENT_SECRET = os.getenv('YOUTUBE_CLIENT_SECRET')
YOUTUBE_REFRESH_TOKEN = os.getenv('YOUTUBE_REFRESH_TOKEN')
SERPER_API_KEY = os.getenv('SERPER_API_KEY')
PEXELS_API_KEY = os.getenv('PEXELS_API_KEY')
PIXABAY_API_KEY = os.getenv('PIXABAY_API_KEY')

# --- KIỂM TRA CÁC KEY QUAN TRỌNG VÀ BÁO LỖI NẾU THIẾU ---
missing_keys = []
if not OPENAI_API_KEY:
    missing_keys.append('OPENAI_API_KEY')
# Bỏ comment nếu bạn dùng ElevenLabs thay vì OpenAI TTS
# if not ELEVENLABS_API_KEY:
#     missing_keys.append('ELEVENLABS_API_KEY')
if not SERPER_API_KEY:
    missing_keys.append('SERPER_API_KEY')
if not PEXELS_API_KEY:
    missing_keys.append('PEXELS_API_KEY')
if not PIXABAY_API_KEY:
    missing_keys.append('PIXABAY_API_KEY')

if missing_keys:
    error_message = (
        f"Lỗi: Các API key sau không được tìm thấy trong file .env hoặc biến môi trường: "
        f"{', '.join(missing_keys)}. Vui lòng tạo file .env ở thư mục gốc và thêm các key cần thiết."
    )
    logger.error(error_message)
    # Raise lỗi để dừng chương trình nếu thiếu key quan trọng
    # Hoặc bạn có thể chỉ cảnh báo nếu muốn chương trình cố gắng chạy tiếp với một số tính năng bị hạn chế
    raise ValueError(error_message)
else:
    logger.info("Tất cả các API keys cần thiết đã được load thành công từ môi trường.") 