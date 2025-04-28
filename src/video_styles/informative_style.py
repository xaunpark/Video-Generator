# src/video_styles/informative_style.py

from .base_style import BaseVideoStyle
# Bạn cũng có thể cần import các thư viện khác nếu ghi đè các phương thức phức tạp hơn

class InformativeStyle(BaseVideoStyle):
    """
    Chiến lược cho style video 'Informative'.
    Kế thừa hầu hết hành vi mặc định từ BaseVideoStyle.
    """

    def get_style_config(self) -> dict:
        """
        Trả về cấu hình cụ thể cho style 'Informative'.
        Dữ liệu này được chuyển từ style_configs cũ.
        """
        # --- SAO CHÉP CONFIG TỪ prompt_generator.style_configs CHO KEY 'informative' ---
        return {
            "tone": "clear and informative",
            "instructions": [
                "Use clear, concise segments.",
                "Start with intro phrase.",
                "Break down info into tiny visual chunks.",
                "End with conclusion phrase."
            ],
            "title_hint": "An informative and clear title",
            # Đảm bảo scene_range được lấy từ project_config hoặc định nghĩa ở đây
            # Ví dụ lấy từ cfg (cần import cfg):
            # "scene_range": cfg.SCENE_RANGE.get("informative", (80, 150)),
            # Hoặc định nghĩa cứng ở đây nếu muốn tách biệt hoàn toàn:
             "scene_range": (20, 30), # Cần khớp với giá trị cũ
             # Có thể thêm các key khác nếu BaseVideoStyle yêu cầu sau này
        }

    def get_voice_settings(self) -> dict:
        """
        Suggests voice settings for the Informative style.
        Prefers a potentially warmer or deeper voice and slightly slower speed.
        Example: OpenAI's 'onyx' or 'shimmer', MiniMax's emotional/audiobook voices.
        """
        return {
            "voice": "moss_audio_27e22420-2381-11f0-b934-42db1b8d9b3b",
        }

    def get_video_editing_settings(self) -> dict:
        """
        Suggests video editing settings for the informative style.
        Prefers clean 'fade' transitions and simple 'zoom_in' animation.
        """
        return {
            "transition_types": ["fade"], # Force simple fade if transitions are enabled
            "image_animation": "zoom_in", # Use a subtle zoom in instead of random
            "animation_intensity": 0.02   # Keep intensity low for informative style
        }