import os
from dotenv import load_dotenv

# Nạp biến môi trường từ file .env
load_dotenv()

# API Keys - cách 1: từ biến môi trường
OPENAI_API_KEY = os.getenv('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')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
YOUTUBE_CLIENT_ID = os.getenv('YOUTUBE_CLIENT_ID')
YOUTUBE_CLIENT_SECRET = os.getenv('YOUTUBE_CLIENT_SECRET')
YOUTUBE_REFRESH_TOKEN = os.getenv('YOUTUBE_REFRESH_TOKEN')
SERPER_API_KEY = os.getenv('SERPER_API_KEY', '8f9c1cf90515e0b8bffe46642d627c28a5b24d84')
PEXELS_API_KEY = "To8Cla26rOGn94KUV7mD30iHVVeLO27R9Xed36XuefIcWiAkuSq334my"
PIXABAY_API_KEY = "49574020-31c90e293b7479c966d33aaa6"

# Nếu không có trong biến môi trường, sử dụng giá trị cụ thể
if not ELEVENLABS_API_KEY:
    ELEVENLABS_API_KEY = "sk_0e8cd650f678d27d45ce5fa94b246b722684ebf8836ec94a"

if not OPENAI_API_KEY:
    OPENAI_API_KEY = "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"