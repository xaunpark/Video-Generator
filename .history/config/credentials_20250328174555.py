import os
from dotenv import load_dotenv

# Nạp biến môi trường từ file .env
load_dotenv()

# API Keys - cách 1: từ biến môi trường
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
YOUTUBE_CLIENT_ID = os.getenv('YOUTUBE_CLIENT_ID')
YOUTUBE_CLIENT_SECRET = os.getenv('YOUTUBE_CLIENT_SECRET')
YOUTUBE_REFRESH_TOKEN = os.getenv('YOUTUBE_REFRESH_TOKEN')
SERPER_API_KEY = os.getenv('SERPER_API_KEY', '8f9c1cf90515e0b8bffe46642d627c28a5b24d84')
PEXELS_API_KEY = "To8Cla26rOGn94KUV7mD30iHVVeLO27R9Xed36XuefIcWiAkuSq334my"
PIXABAY_API_KEY = "49574020-31c90e293b7479c966d33aaa6"

# Nếu không có trong biến môi trường, sử dụng giá trị cụ thể
if not ELEVENLABS_API_KEY:
    # ElevenLabs API key
    ELEVENLABS_API_KEY = "sk_0e8cd650f678d27d45ce5fa94b246b722684ebf8836ec94a"

if not OPENAI_API_KEY:
    # OpenAI API key
    OPENAI_API_KEY = "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"