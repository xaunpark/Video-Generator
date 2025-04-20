# src/video_styles/senior_conversational_style.py

import json # Cần json để format layout trong prompt
from .base_style import BaseVideoStyle
from src import project_config as cfg # Import cấu hình nếu cần scene_range
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
        # --- SAO CHÉP CONFIG TỪ prompt_generator.style_configs CHO KEY 'senior_conversational' ---
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
            "scene_range": (150, 350), # Cần khớp giá trị cũ
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

    def generate_script_prompt(self, source_data: dict, language: str, video_mode: str) -> str:
        """
        Tạo prompt *đầy đủ và cụ thể* cho ScriptGenerator cho style này.
        LƯU Ý: Logic này được di chuyển và điều chỉnh từ hàm generate_prompt cũ.
               Sau Bước 3, phần chung có thể được chuyển vào BaseVideoStyle.
        """
        style_config = self.get_style_config() # Lấy config của chính style này
        tone = style_config['tone']
        instructions = style_config['instructions']
        title_hint = style_config['title_hint']
        scene_min, scene_max = style_config['scene_range']

        # Định nghĩa cấu trúc (giống như trong prompt_generator cũ)
        structure_definition = """
        **Critical Output Structure Requirements:**

        1.  **`scenes` (Visual Shots/Slides):**
            *   This array defines the *visual* flow. Each element is a VERY SHORT text segment (a "shot" or "slide").
            *   You MUST aggressively break down the original sentences into these tiny visual scenes/shots.
            *   Focus on splitting based on distinct visual concepts, keywords, actions, or natural pauses.
            *   Scene numbers MUST be sequential starting from 1.

        2.  **`speech_units` (Audio Segments):**
            *   This array defines the *audio* flow for natural-sounding voice generation.
            *   Each element groups one or more consecutive `scenes` into a logical, natural-sounding phrase or sentence.
            *   The `text` field MUST be the exact concatenation of the `content` from the scenes listed in its `scene_numbers` array.
            *   The `scene_numbers` array lists the `number`s of the scenes belonging to this unit.
            *   All scenes MUST be included in exactly one speech unit, sequentially without gaps or overlaps.
        """

        # --- Xác định loại input và xây dựng phần context của prompt ---
        prompt_start = f"Create a {tone} video script based on the following source material.\nThe script must be meticulously structured into `scenes` (visual shots) and `speech_units` (audio segments) as defined below.\n\n"

        input_type = source_data.get('type', 'unknown')
        content_data = source_data.get('data', '')
        context_hint = source_data.get('context', None)
        lang_instruction = f"in {language}" if language == "en" else f"bằng tiếng Việt" # Điều chỉnh cho phù hợp

        if input_type == 'article':
            prompt_start += f"SOURCE MATERIAL TYPE: News Article\n"
            prompt_start += f"ARTICLE TITLE: {content_data.get('title', '')}\n"
            prompt_start += f"ARTICLE CONTENT:\n{safe_truncate(content_data.get('content', ''), cfg.MAX_ARTICLE_LENGTH)}\n"
        elif input_type == 'keyword':
             prompt_start += f"SOURCE MATERIAL TYPE: Keyword/Topic\n"
             prompt_start += f"TOPIC: \"{content_data}\"\n"
             prompt_start += f"LANGUAGE: Generate content {lang_instruction}.\n"
        elif input_type == 'text':
             prompt_start += f"SOURCE MATERIAL TYPE: Input Text {f'({context_hint})' if context_hint else ''}\n"
             prompt_start += f"TEXT CONTENT:\n{safe_truncate(content_data, 12000)}\n" # Giữ limit lớn hơn cho text
             prompt_start += f"LANGUAGE: Process and generate script {lang_instruction}.\n"
        else:
             # Xử lý lỗi hoặc trả về prompt mặc định/thông báo lỗi
             logger.error(f"Invalid source data type '{input_type}' for SeniorConversationalStyle script prompt.")
             return "Error: Invalid source data type provided for script generation."

        # --- Ghép nối các phần của prompt ---
        full_prompt = prompt_start + "\n" + structure_definition

        # Thêm Script Content Rules
        full_prompt += f"""

        **Script Content Rules:**
        *   Follow the specific '{tone}' style. Adhere strictly to these instructions: {'; '.join(instructions)}
        *   Ensure the concatenated `speech_units.text` accurately reflects the core information or generated content.
        *   Target Audience: **Seniors (60+)**. Use appropriate language, examples, and pacing.
        *   Generate between {scene_min} and {scene_max} SHORT visual scenes in total.
        *   Prioritize clarity, warmth, and practical value.
        """

        # Nếu là Advanced mode (được xác định bởi logic gọi trong ScriptGenerator),
        # prompt này có thể cần điều chỉnh thêm để yêu cầu layout trước,
        # nhưng hiện tại, chúng ta giả định generate_script_prompt tạo prompt cuối cùng.
        # Việc tách layout sẽ được xử lý bởi should_override_layout và get_layout_generation_params.

        # Thêm Output Format Reminder
        full_prompt += f"""

        **Final Output Format (JSON ONLY - Adhere Strictly):**
        {{
          "title": "{title_hint}",
          "scenes": [
            {{"number": 1, "content": "Short shot 1"}},
            // ... more scenes ...
          ],
          "speech_units": [
            {{
              "unit_number": 1,
              "text": "Concatenated text of scenes.",
              "scene_numbers": [/* list of scene numbers */]
            }},
            // ... more speech units ...
          ]
        }}

        **REMEMBER:** Provide ONLY the valid JSON object. No introductory text, explanations, or code fences.
        """
        return full_prompt.strip()


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

    def should_override_timing_mode(self) -> bool:
        """Senior Conversational nên dùng timing mode cố định."""
        return True

    def get_preferred_timing_mode(self) -> str:
        """Timing mode ưu tiên cho Senior Conversational."""
        return "overall_theme_fixed_duration"

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

    # Các phương thức khác như get_voice_settings, get_video_editing_settings
    # có thể được ghi đè ở đây nếu Senior Conversational cần cấu hình đặc biệt.
    # Ví dụ:
    # def get_voice_settings(self) -> dict:
    #     return {"voice": "onyx", "stability": 0.6} # Chọn giọng nam trầm ấm chẳng hạn

    # def get_video_editing_settings(self) -> dict:
    #     return {"transition_type": "dissolve", "animation_intensity": 0.02} # Hiệu ứng nhẹ nhàng hơn