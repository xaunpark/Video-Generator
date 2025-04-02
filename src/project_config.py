# src/project_config.py

# -----------
# Cấu hình chung cho toàn bộ project
# -----------

from src.prompt_generator import style_configs

SCENE_RANGE = {style: cfg["scene_range"] for style, cfg in style_configs.items()}
AVAILABLE_STYLES = list(style_configs.keys())


# Tỷ lệ đề xuất ảnh/video dự phòng (nên >1.0)
RECOMMENDED_MEDIA_RATIO = 1.1

# Giới hạn chiều dài bài viết (token limit friendly) - Giới hạn độ dài nội dung bài báo để tiết kiệm token
MAX_ARTICLE_LENGTH = 10000

# Logger format
LOGGER_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"

# Enable video clip detector by default
ENABLE_VIDEO_CLIP_DETECTOR = True

# Threshold detect Vietnamese
VI_CHAR_RATIO_THRESHOLD = 0.3
