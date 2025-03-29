import os
from dotenv import load_dotenv

# Nạp biến môi trường từ file .env
load_dotenv()

# API Keys
OPENAI_API_KEY = os.getenv('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')
ELEVENLABS_API_KEY = os.getenv('sk_0e8cd650f678d27d45ce5fa94b246b722684ebf8836ec94a')
YOUTUBE_CLIENT_ID = os.getenv('YOUTUBE_CLIENT_ID')
YOUTUBE_CLIENT_SECRET = os.getenv('YOUTUBE_CLIENT_SECRET')
YOUTUBE_REFRESH_TOKEN = os.getenv('YOUTUBE_REFRESH_TOKEN')