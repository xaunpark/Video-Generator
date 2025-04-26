# src/video_styles/senior_conversational_style.py

import json
from typing import List, Optional, Union

from .base_style import BaseVideoStyle
from config.settings import MAX_ARTICLE_LENGTH
from src.utils import safe_truncate # Import hàm tiện ích nếu cần

import logging
logger = logging.getLogger(f"{__name__}.SeniorConversationalStyle")

# Import style_configs cũ để lấy cấu trúc prompt gốc (TẠM THỜI)
# SAU KHI HOÀN THÀNH VIỆC DI CHUYỂN, BẠN CÓ THỂ XÓA IMPORT NÀY
# from src.prompt_generator import style_configs as old_style_configs

class SeniorConversationalStyle(BaseVideoStyle):
    """
    Chiến lược cho style video 'Senior Conversational'.
    Ghi đè nhiều phương thức để cung cấp hành vi và cấu hình đặc biệt.
    """

    def get_style_config(self) -> dict:
        """
        Trả về cấu hình cụ thể cho style 'Senior Conversational'.
        """
        return {
            "tone": "warm, conversational, and motivational, targeted at seniors (60+)",
            "instructions": [
                "Speak directly to the viewer like a caring friend.",
                "Use simple, clear language, avoid jargon or overly complex sentences.",
                "Provide practical, actionable advice with relatable examples for seniors.",
                "Maintain a positive, reassuring, and uplifting mood.",
                "Ensure smooth, natural transitions between ideas and chapters.",
                "Write as a continuous narrative, avoiding bullet points or explicit section titles in the content."
            ],
            "title_hint": "A helpful, friendly, and encouraging title for seniors",
            "scene_range": (150, 350),
            "target_audience": "60+",
            "layout_override": {
                "enabled": True,
                "target_total_word_range": (1500, 2500),
                "chapter_count_range": (3, 4),
                "chapter_word_target_range": (400, 700),
                "structure_prompt": "Structure the video logically into 3 main conceptual parts: 1) An engaging Introduction/Hook, 2) The main discussion points providing value and practical advice, 3) A concluding summary and call to action/uplifting message. Divide these 3 conceptual parts into {chapter_count_min} to {chapter_count_max} distinct chapters in the final layout."
            }
        }

    # --- GHI ĐÈ CÁC PHƯƠNG THỨC CẦN THIẾT ---

    def should_override_layout(self) -> bool:
        """Senior Conversational yêu cầu cấu trúc layout chương đặc biệt."""
        return True # Lấy từ config["layout_override"]["enabled"]

    def get_layout_generation_params(self) -> dict:
        """Trả về các tham số để tạo layout cho Senior Conversational."""
        config = self.get_style_config()
        layout_override = config.get("layout_override", {})
        # Trả về các tham số cần thiết, ví dụ:
        return {
            "chapter_count_range": layout_override.get("chapter_count_range", (3, 4)),
            "chapter_word_target_range": layout_override.get("chapter_word_target_range", (400, 700)),
            "target_total_word_range": layout_override.get("target_total_word_range", (1500, 2500)),
            "structure_prompt": layout_override.get("structure_prompt", "")
            # Thêm các tham số khác nếu cần
        }

    # --- EP BUỘC TIMING MODE LÀ FIXED ---
    def should_override_timing_mode(self) -> bool:
        """Senior Conversational nên dùng timing mode cố định."""
        return True

    def get_preferred_timing_mode(self) -> str:
        """Timing mode ưu tiên cho Senior Conversational."""
        return "overall_theme_fixed_duration"
    # --- KẾT THÚC ÉP BUỘC TIMING MODE ---

    # --- ÉP BUỘC VISUAL SOURCE LÀ VIDEO_ONLY ---
    def should_override_visual_source(self) -> bool:
        """
        Style này bắt buộc sử dụng nguồn visual cụ thể (chỉ video).
        """
        return True

    def get_visual_source_preference(self) -> str:
        """
        Trả về nguồn visual bắt buộc cho style này.
        """
        return "video_only"
    # --- KẾT THÚC ÉP BUỘC VISUAL SOURCE ---

    def hook_instructions(self) -> str:
        """
        Trả về hướng dẫn tạo hook đặc biệt cho Senior Conversational.
        """
        logger.info("Đang thực  thi SeniorConversationalStyle: Generating hook instructions.")
        return """
        Start with one of the following proven hook styles tailored for a senior audience (60+). The goal is to instantly grab attention by speaking directly to their current concerns or goals:
        • Highlight a common struggle or pain point 
            (e.g., “Do you feel like your family no longer listens to you? This video will help you change that…”).
        • Ask a thought-provoking question 
            (e.g., “Do you still need friends after 70? What you’ll hear may surprise you…”).
        • Lead with a striking statistic or health warning 
            (e.g., “99% of deaths after age 75 are caused by these 5 things – here's how to avoid them.”).
        • Present a powerful personal transformation 
            (e.g., “At 74, I stay sharp and active every day thanks to these 4 simple habits…”).
        • Make a clear and motivating promise 
            (e.g., “If you eat these 5 foods, your constipation could disappear after age 60.”).

        Use language that feels empathetic, inspiring, and easy to follow – avoid overly complex or fast-paced delivery.
        """
    ### --- Nhận thông tin về chapter hiện tại và trả về chuỗi hướng dẫn cụ thể (hoặc chuỗi rỗng nếu dùng mặc định) --- ###
    def get_chapter_content_instructions(self, chapter_num: int, total_chapters: int, chapter_summary: str, word_count_target: int, next_chapter_title: str | None = None) -> str:
        """
        Cung cấp hướng dẫn cấu trúc nội dung chi tiết cho từng chapter
        theo yêu cầu của style Senior Conversational (3 phần).
        """
        logger.info(f"SeniorConversationalStyle: Generating specific content instructions for Chapter {chapter_num}/{total_chapters}.")
        instructions = f"\n**Specific Content Structure for Chapter {chapter_num}:**\n"

        if chapter_num == 1:
            instructions += """
        - Start with the required hook (as per separate instructions).
        - Briefly introduce the main topic '[SELECTED TOPIC]' and its importance for seniors.
        - Mention the key takeaways the video will cover (e.g., 'In this video, we’ll go over X simple habits...').
        - Transition smoothly into the first point(s) relevant to this chapter's summary ('{chapter_summary}').
        - Cover the first set of points thoroughly.
        - End naturally, preparing the viewer for the next logical step (next chapter topic: '{next_chapter_title}').
        """
        elif chapter_num == total_chapters: # Chapter cuối cùng
            instructions += f"""
        - Cover the final points relevant to this chapter's summary ('{chapter_summary}').
        - Provide a natural-feeling summary of the main takeaways from the *entire* video.
        - Include a positive and reassuring motivational message suitable for seniors.
        - Encourage viewers to share their thoughts or experiences in the comments.
        - Include a call to action: ask them to like the video and subscribe.
        - End with an uplifting closing statement (e.g., 'Here’s to living your best life at any age!').
        """
        else: # Các chapter ở giữa
            instructions += f"""
        - Continue discussing the points relevant to this chapter's summary ('{chapter_summary}').
        - Provide clear explanations, actionable steps, and relatable examples for each point covered in this chapter.
        - Ensure smooth, conversational transitions between points within the chapter.
        - End naturally, preparing the viewer for the next logical step (next chapter topic: '{next_chapter_title}').
        """
        # Thay thế các placeholder nếu cần
        instructions = instructions.replace("{chapter_summary}", chapter_summary)
        instructions = instructions.replace("{next_chapter_title}", next_chapter_title if next_chapter_title else "[End of Video]")
        # Bạn có thể cần truyền [SELECTED TOPIC] vào hàm này nếu muốn dùng nó ở đây

        return instructions.strip()

    def generate_ai_image_prompt(self, scene_content: str, video_title: str) -> str:
        """
        Tạo prompt *cụ thể và an toàn* cho Imagen cho style Senior Conversational.
        Logic này được chuyển từ ImageGenerator._create_imagen_prompt.
        """
        logger.debug(f"Creating specific Imagen prompt for Senior Conversational.")

        # (Sao chép toàn bộ phần tạo gpt_prompt cho "senior_conversational"
        # từ hàm _create_imagen_prompt trong image_generator.py cũ vào đây)
        # ... (Phần này khá dài, hãy copy từ code cũ của bạn) ...
        gpt_prompt = f"""
            You are an expert prompt engineer for text-to-image AI like Google Imagen 3.
            Your task is to convert the following scene content into a detailed, effective, and **appropriate** prompt for a video targeting **seniors (60+)**.

            Consider these factors:
            - Overall video title: "{video_title}"
            - **Target Audience:** Seniors (60+)
            - **Desired Video Style/Tone:** Warm, conversational, motivational, relatable, positive, gentle (warm, conversational, and motivational, targeted at seniors (60+)).
            - Specific content of this scene: "{scene_content}"

            **IMPORTANT SAFETY GUIDELINES (Apply Strictly):**
            - NEVER generate prompts depicting children, minors, or family scenes with minors. Replace with adults (18+) or symbolic objects.
            - Avoid depicting vulnerable populations or overly sensitive scenarios (e.g., severe illness depiction).
            - Avoid depicting realistic human faces in close detail. Focus on general appearance, emotion, and setting.
            - Ensure generated images are positive, respectful, and avoid ageist stereotypes.

            **Instructions for the Imagen Prompt (Senior Conversational Style):**
            1.  **Visual Style:** Aim for **photorealistic** but with **warm, soft lighting** and **calm, pleasing compositions**. Avoid harsh contrasts or overly busy scenes.
            2.  **Subject Focus:** If depicting people, show **older adults (appearing 60+)** engaged in relatable activities (e.g., gentle exercise like walking/yoga, gardening, reading, talking with friends/family (adults only), enjoying nature, hobbies). Depict them with **positive expressions** (smiles, contentment, thoughtfulness). Show diversity in older adults respectfully.
            3.  **Emotion:** Emphasize feelings of **warmth, comfort, connection, peace, gentle motivation, or contentment**.
            4.  **Setting:** Prefer **cozy, comfortable, or serene settings** (e.g., comfortable homes, sunny gardens, parks, cafes, libraries).
            5.  **Clarity & Simplicity:** Keep the visual concept clear and easy to understand. Avoid overly abstract or complex metaphors unless the scene content specifically calls for it.
            6.  **Incorporate Tone:** Use descriptive words reflecting the warm, motivational, and conversational tone (e.g., "gentle sunlight," "cozy armchair," "warm smile," "peaceful garden," "supportive friend").
            7.  **Length & Detail:** Be descriptive but concise (under 150 words). Mention key subjects, actions, setting, mood.
            8.  **Safety First:** Strictly adhere to the safety guidelines above. Rewrite scene concepts if needed (e.g., instead of "grandchildren playing," use "photo albums on a table" or "knitting supplies").

            Output ONLY the generated Imagen prompt, with no extra explanations or quotation marks.
            """

        # (Phần gọi OpenAI API để tạo prompt thực tế nên nằm trong ImageGenerator,
        # hàm này chỉ trả về CÁI PROMPT để ImageGenerator sử dụng)
        # Hàm này chỉ cần trả về string prompt cho OpenAI/LLM khác xử lý sau.
        # Logic gọi API để tạo prompt này nên nằm trong ImageGenerator._create_imagen_prompt
        # hoặc một helper chung, và hàm này chỉ cần trả về text prompt.
        # Tạm thời, hàm này sẽ trả về chính `gpt_prompt` này.

        # TODO: Xem xét lại việc gọi API tạo prompt AI. Có thể hàm này nên
        # trả về *hướng dẫn* cho LLM tạo prompt, thay vì tự gọi API.
        # Hiện tại, trả về prompt hướng dẫn LLM tạo prompt Imagen.
        # ImageGenerator sẽ cần gọi LLM một lần nữa với prompt này.

        # Ví dụ trả về prompt cho LLM (để LLM tạo ra prompt Imagen cuối)
        # Tuy nhiên, code hiện tại của bạn là _create_imagen_prompt gọi API,
        # nên chúng ta sẽ tạm giữ logic đó ở đây cho nhất quán, dù không lý tưởng lắm.

        return gpt_prompt.strip()

#    def get_video_search_query_override(self) -> Union[str, List[str], None]:
        """
        Cung cấp truy vấn tìm kiếm video cố định cho style này.
        Trả về một chuỗi, một danh sách chuỗi, hoặc None.
        """
        logger.info("SeniorConversationalStyle: Providing fixed 'natural/calm' video search queries.")
        # --- LỰA CHỌN 1: Trả về một danh sách các query ---
        # Ưu điểm: Tăng khả năng tìm thấy video đa dạng hơn một chút.
        # ImageGenerator sẽ cần chọn ngẫu nhiên từ list này.
        return [
            "peaceful nature landscape",
            "calm serene outdoors",
            "gentle flowing water relaxing",
            "quiet garden pathway",
            "warm sunlight park bench",
            "slow motion nature close up",
            "tranquil forest scene",
            "relaxing countryside view"
        ]

        # --- LỰA CHỌN 2: Trả về một chuỗi query duy nhất ---
        # Ưu điểm: Đơn giản hơn cho ImageGenerator xử lý.
        # Nhược điểm: Kết quả tìm kiếm có thể ít đa dạng hơn.
        # return "peaceful nature calm landscape serene relaxing"

        # --- LỰA CHỌN 3: Trả về None (Không dùng cho yêu cầu này) ---
        # return None # Nếu không muốn override query
    # --- KẾT THÚC THÊM PHƯƠNG THỨC MỚI ---

    # Các phương thức khác như get_voice_settings, get_video_editing_settings
    # có thể được ghi đè ở đây nếu Senior Conversational cần cấu hình đặc biệt.
    # Ví dụ:
    # def get_voice_settings(self) -> dict:
    #     return {"voice": "onyx", "stability": 0.6} # Chọn giọng nam trầm ấm chẳng hạn

    # def get_video_editing_settings(self) -> dict:
    #     return {"transition_type": "dissolve", "animation_intensity": 0.02} # Hiệu ứng nhẹ nhàng hơn