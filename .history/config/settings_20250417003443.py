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
    #{
    #    "name": "TechCrunch",
    #    "url": "https://techcrunch.com/feed/",
    #    "type": "rss",
    #    "language": "en"
    #}
    #{
    #    "name": "VnExpress",
    #    "url": "https://vnexpress.net/rss/giai-tri.rss",
    #    "type": "rss",
    #    "language": "vi"
    #},
    #{
    #    "name": "TuoiTre",
    #    "url": "https://tuoitre.vn/rss/khoa-hoc.rss",
    #    "type": "rss",
    #    "language": "vi"
    #},
    {
        "name": "Theguardian Lifestyle",
        "url": "https://www.theguardian.com/uk/lifeandstyle/rss",
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
    "video_clip_duration": 10,            # Thời lượng mong muốn cho video clips (giây)
    "enable_sentence_to_shot_breakdown": True, # Bật/tắt tính năng chia nhỏ video thành các đoạn ngắn hơn
    "video_clip_frequency": 0.4,         # Tỷ lệ scene nên dùng video (0.0-1.0)
    "min_scenes_between_videos": 1,      # Số scene tối thiểu giữa 2 video clips
    "chapter_title_duration": 2.5,
    "openai_model_for_scene_analysis": "gpt-4o",  # Model để phân tích scene
    "enable_transitions": True,
    "transition_types": ["fade"],
    "transition_duration": 0.5,
    "enable_background_music": True,
    "music_volume": 0.1,
    # Cài đặt hiệu ứng cho ảnh tĩnh
    "enable_ken_burns": False,
    "debug_disable_effects": False,
    "image_animation": "random",     # để random rồi sau đó trong video editor chọn ngẫu nhiên các hiệu ứng 
    "animation_intensity": 0.05,     # Từ 0.01 (rất nhẹ) đến 0.1 (rõ ràng hơn)
    "animation_cycle_seconds": 5,    # Thời gian để hoàn thành một chu kỳ hiệu ứng (giây)
    # --- THÊM CẤU HÌNH CHO SLOW MOTION ---
    "enable_slow_motion_fallback": True, # Bật/tắt tính năng này
    # Tỷ lệ thời lượng tối thiểu của video so với audio để áp dụng slow motion
    # Ví dụ: 0.8 nghĩa là video phải dài ít nhất 80% audio duration
    "slow_motion_min_ratio": 0.8,
    # ------------------------------------
    "enable_subtitles": True,  # Bật/tắt phụ đề
    "subtitle_font_size": 24,    # Kích thước font chữ phụ đề
    "subtitle_whisper_model": "base",    # Mô hình whisper: tiny, base, small, medium, large
    "subtitle_language": "auto",           # Ngôn ngữ phụ đề (auto để tự động phát hiện)
    "subtitle_style": "Alignment=2,OutlineColour=&H80000000,BorderStyle=3,Outline=1", # Style cho FFmpeg
    # -------------CHẾ ĐỘ CHẠY ẢNH/VIDEO THEO AUDIO HAY THEO TIME CỐ ĐỊNH --------------------
    "visual_timing_mode": "sync_to_audio", # Chỉ 2 lựa chọn: 'sync_to_audio', 'overall_theme_fixed_duration'
    "fixed_visual_duration": 15.0,        # Dùng cho 'overall_theme_fixed_duration'
    "theme_visual_query_count": 7,       # Số query/prompt cho chế độ theme
    "theme_visual_generation_factor": 1.1, # Tạo dư visual cho chế độ theme
    # -------------TĂNG CƯỜNG CHẤT LƯỢNG VIDEO----------------------
    "enable_video_enhancement": True,  # Bật/tắt tính năng tăng cường
    "enhancement_saturation": 1.1,     # Giá trị saturation (1.0 là gốc, >1 tăng, <1 giảm)
    "enhancement_contrast": 1.05,      # Giá trị contrast (1.0 là gốc, >1 tăng, <1 giảm)
    "enhancement_brightness": 0.0,      # Giá trị brightness (-1.0 đến 1.0, 0 là gốc)    
}

# --- LLM Provider Settings ---
LLM_PROVIDERS = {
    "openai": {
        "api_key_name": "OPENAI_API_KEY", # Name of the key variable in credentials.py
        "base_url": "https://api.openai.com/v1",
        "chat_model": "gpt-4o", # Or your preferred OpenAI model
        "supports_json_mode": True,
    },
    "deepseek": {
        "api_key_name": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "chat_model": "deepseek-chat", #deepseek-reasoner không hỗ trợ json mode
        "supports_json_mode": True, # IMPORTANT: Verify if Deepseek supports a forced JSON output mode like OpenAI. Set to False if not.
    },
    # Add other providers here in the future
}

DEFAULT_LLM_PROVIDER = "openai"
if DEFAULT_LLM_PROVIDER not in LLM_PROVIDERS:
    raise ValueError(f"DEFAULT_LLM_PROVIDER ('{DEFAULT_LLM_PROVIDER}') in settings.py is not defined in LLM_PROVIDERS.")

# DALL-E Settings
DALLE_SETTINGS = {
    "model": "dall-e-3",
    "default_size": "1792x1024", # Landscape
    "default_quality": "standard",
    "default_style": "vivid"
}

# Cấu hình cho việc tạo ảnh bằng Google Imagen (qua Gemini API)
IMAGEN_SETTINGS = {
    "model": "imagen-3.0-generate-002", # Model Imagen muốn sử dụng
    "number_of_images": 1,              # Số lượng ảnh tạo mỗi lần gọi (thường chỉ cần 1)
    # Thêm các cấu hình khác của Imagen nếu cần (ví dụ: aspect_ratio, quality, style...)
    # Tham khảo: https://ai.google.dev/api/python/google/genai/types/GenerateImagesConfig
    "aspect_ratio": "16:9",          # Tỉ lệ khung hình mong muốn (ví dụ)
    "quality": "standard",            # Có thể thêm các tùy chọn khác
    "person_generation": "ALLOW_ADULT" # Hoặc "DONT_ALLOW"
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

# Đường dẫn đến ffprobe (tương tự ffmpeg)
FFPROBE_EXECUTABLE_PATH = "ffprobe" # Mặc định tìm trong PATH