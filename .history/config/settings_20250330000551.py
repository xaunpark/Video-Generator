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

# Cấu hình các nguồn tin tức tiếng Anh
NEWS_SOURCES = [
    #{
    #    "name": "CNN",
    #    "url": "http://rss.cnn.com/rss/edition_world.rss",
    #    "type": "rss",
    #    "language": "en"
    #},
    #{
    #    "name": "The New York Times",
    #    "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    #    "type": "rss",
    #    "language": "en"
    #},
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "type": "rss",
        "language": "en"
    }
]

# Danh mục tin tức tiếng Anh
NEWS_CATEGORIES = {
    "business": ["business", "finance", "economy", "stock", "market", "investment", "company", "corporate"],
    "technology": ["technology", "tech", "IT", "software", "AI", "science", "innovation", "digital"],
    "health": ["health", "medical", "disease", "pandemic", "vaccine", "healthcare", "medicine"],
    "entertainment": ["entertainment", "celebrity", "movie", "film", "music", "hollywood", "showbiz"],
    "sports": ["sports", "football", "soccer", "tennis", "olympics", "basketball", "nba"],
    "politics": ["politics", "government", "election", "president", "congress", "senate", "parliament"],
    "environment": ["environment", "climate", "global warming", "sustainability", "renewable", "green"]
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
    "format": "mp4",
    "enable_video_clips": True,          # Bật/tắt tính năng video clips
    "video_clip_duration": 7,            # Thời lượng mong muốn cho video clips (giây)
    "video_clip_frequency": 0.4,         # Tỷ lệ scene nên dùng video (0.0-1.0)
    "min_scenes_between_videos": 1,      # Số scene tối thiểu giữa 2 video clips
    "openai_model_for_scene_analysis": "gpt-4o-mini",  # Model để phân tích scene
    "enable_transitions": True,
    "transition_types": ["fade"],
    "transition_duration": 0.8,
    "enable_background_music": True,
    "music_volume": 0.1,
    # Cài đặt hiệu ứng cho ảnh tĩnh
    "enable_ken_burns": False,
    "debug_disable_effects": True,
    "image_animation": "zoom",      # Các tùy chọn: "none", "zoom"
    "animation_intensity": 0.1,     # Từ 0.01 (rất nhẹ) đến 0.1 (rõ ràng hơn)
    "animation_cycle_seconds": 5,    # Thời gian để hoàn thành một chu kỳ hiệu ứng (giây)
    # --- THÊM CẤU HÌNH CHO SLOW MOTION ---
    "enable_slow_motion_fallback": True, # Bật/tắt tính năng này
    # Tỷ lệ thời lượng tối thiểu của video so với audio để áp dụng slow motion
    # Ví dụ: 0.8 nghĩa là video phải dài ít nhất 80% audio duration
    "slow_motion_min_ratio": 0.8
    # ------------------------------------
}

# Cấu hình YouTube
YOUTUBE_SETTINGS = {
    "category_id": "25",  # News & Politics
    "privacy_status": "private",  # private, public, unlisted
    "tags": ["news", "daily news", "world news", "AI news", "English news"],
    "default_language": "en"  # Thay đổi ngôn ngữ mặc định thành tiếng Anh
}

# Cấu hình Voice Generator
VOICE_SETTINGS = {
    "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel - Giọng nữ tiếng Anh Mỹ
    "model_id": "eleven_monolingual_v1",  # Model cho tiếng Anh
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,  # Giọng đọc tin tức trung tính
    "use_speaker_boost": True
}