import os
from pathlib import Path

# Đường dẫn cơ sở
BASE_DIR = Path(__file__).resolve().parent.parent

# Thư mục
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
TEMPLATES_DIR = ASSETS_DIR / "templates"
FONTS_DIR = ASSETS_DIR / "fonts"

# Tạo thư mục nếu chưa tồn tại
for dir_path in [TEMP_DIR, OUTPUT_DIR, ASSETS_DIR, MUSIC_DIR, TEMPLATES_DIR, FONTS_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# Cấu hình các nguồn tin tức
NEWS_SOURCES = [
    {
        "name": "VnExpress",
        "url": "https://vnexpress.net/rss/tin-moi-nhat.rss",
        "type": "rss",
        "language": "vi"
    },
    {
        "name": "Tuổi Trẻ",
        "url": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
        "type": "rss",
        "language": "vi"
    }
]

# Danh mục tin tức
NEWS_CATEGORIES = {
    "business": ["kinh tế", "tài chính", "doanh nghiệp", "chứng khoán", "đầu tư"],
    "technology": ["công nghệ", "tech", "IT", "phần mềm", "AI", "khoa học"],
    "health": ["sức khỏe", "y tế", "bệnh", "dịch", "vaccine"],
    "entertainment": ["giải trí", "sao", "nghệ sĩ", "phim", "nhạc", "showbiz"],
    "sports": ["thể thao", "bóng đá", "tennis", "Olympic"]
}

# Cấu hình video
VIDEO_SETTINGS = {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "intro_duration": 3,  # seconds
    "outro_duration": 5,  # seconds
    "image_duration": 5,  # seconds per image
    "background_music_volume": 0.1,
    "format": "mp4"
}

# Cấu hình YouTube
YOUTUBE_SETTINGS = {
    "category_id": "25",  # News & Politics
    "privacy_status": "private",  # private, public, unlisted
    "tags": ["tin tức", "AI", "news", "daily update"],
    "default_language": "vi"
}