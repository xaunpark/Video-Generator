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
             "scene_range": (80, 150), # Cần khớp với giá trị cũ
             # Có thể thêm các key khác nếu BaseVideoStyle yêu cầu sau này
        }

    # --- CÁC PHƯƠNG THỨC KHÁC ---
    # Vì style 'informative' không có yêu cầu đặc biệt về prompt script,
    # prompt ảnh AI, layout, timing, voice, hoặc video editing so với mặc định,
    # chúng ta KHÔNG cần ghi đè các phương thức khác. Chúng sẽ sử dụng
    # triển khai mặc định từ BaseVideoStyle (mà chúng ta sẽ hoàn thiện ở Bước 3).

    # Ví dụ, các phương thức sau sẽ dùng mặc định từ BaseVideoStyle:
    # def generate_script_prompt(self, source_data: dict, language: str, video_mode: str) -> str:
    #     return super().generate_script_prompt(source_data, language, video_mode) # Hoặc không cần dòng này

    # def generate_ai_image_prompt(self, scene_content: str, video_title: str) -> str:
    #     return super().generate_ai_image_prompt(scene_content, video_title) # Hoặc không cần dòng này

    # ... và tương tự cho các phương thức should_override..., get_preferred..., get_voice_settings, v.v.