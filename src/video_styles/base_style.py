# src/video_styles/base_style.py

from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

class BaseVideoStyle(ABC):
    """
    Lớp cơ sở trừu tượng cho các chiến lược tạo kiểu video khác nhau.
    Định nghĩa các phương thức mà mỗi style cụ thể cần cung cấp.
    """

    @abstractmethod
    def get_style_config(self) -> dict:
        """
        Trả về cấu hình cơ bản cho style này.
        Tương đương với một mục trong `style_configs` cũ.
        Phải chứa ít nhất 'tone', 'instructions', 'scene_range', 'title_hint'.
        """
        pass

    def get_description(self) -> str:
        """
        Trả về mô tả ngắn gọn cho style này (để hiển thị trong menu chọn).
        Mặc định lấy từ 'tone'.
        """
        try:
            config = self.get_style_config()
            # Lấy 'tone' và viết hoa chữ cái đầu mỗi từ
            tone = config.get('tone', 'Unknown Style')
            return ' '.join(word.capitalize() for word in tone.split())
        except Exception:
            return "Unknown Style"

    # --- Phương thức liên quan đến Script Generation ---

    def hook_instructions(self) -> str:
        """Trả về hướng dẫn tạo hook mặc định cho Chapter 1."""
        logger.info(">>> Đang thực thi: BaseVideoStyle.hook_instructions (Default Hook)")
        return """
        Begin with one of the following styles to instantly grab attention:
        • A shocking statistic or surprising truth (e.g., “95% of YouTubers fail because of THIS!”).
        • A thought-provoking question (e.g., “If you only had 3 days to rank your video, what would you do first?”).
        • A specific result or transformation (e.g., “I gained 100,000 views in 2 weeks using this simple trick…”).
        • A direct call-out to the viewer’s pain point (e.g., “Still stuck at 50 views? This video is your breakthrough.”).
        • A bold promise or outcome-driven tease (e.g., “After watching this, you’ll know how to rank on YouTube in 48h.”).
        Use language that evokes curiosity, emotion, or urgency—designed to retain viewer interest in the first 15 seconds.
        """

    ### --- Nhận thông tin về chapter hiện tại và trả về chuỗi hướng dẫn cụ thể (hoặc chuỗi rỗng nếu dùng mặc định) --- ###
    def get_chapter_content_instructions(self, chapter_num: int, total_chapters: int, chapter_summary: str, word_count_target: int, next_chapter_title: str | None = None) -> str:
        """
        Trả về chuỗi hướng dẫn bổ sung về cấu trúc nội dung mong muốn
        cho một chapter cụ thể trong chế độ Advanced.
        Mặc định không có hướng dẫn đặc biệt nào. Lớp con có thể ghi đè.

        Args:
            chapter_num: Số thứ tự của chapter hiện tại (bắt đầu từ 1).
            total_chapters: Tổng số chapter trong layout.
            chapter_summary: Tóm tắt của chapter hiện tại.
            word_count_target: Mục tiêu từ cho chapter hiện tại.
            next_chapter_title: Tiêu đề chapter tiếp theo (nếu có).

        Returns:
            Chuỗi hướng dẫn bổ sung hoặc chuỗi rỗng.
        """
        logger.debug(f"BaseVideoStyle: Using default (no specific) content instructions for Chapter {chapter_num}.")
        # Mặc định không yêu cầu cấu trúc nội dung đặc biệt bên trong chapter
        # Chỉ yêu cầu LLM viết dựa trên summary và các hướng dẫn chung.
        return ""

    def generate_script_prompt(self, source_data: dict, language: str, video_mode: str) -> str:
        """
        Tạo prompt cho Bước 1 (Basic Mode) hoặc Bước Tạo Layout (Advanced Mode).
        Output yêu cầu từ LLM sẽ khác nhau tùy theo video_mode.

        - Basic Mode: Yêu cầu JSON { "title": "...", "initial_scenes": [...] } (list of full sentences).
        - Advanced Mode (Layout Stage): Sẽ được xử lý bởi _generate_video_layout.
                        Hàm này không nên được gọi trực tiếp cho Advanced Layout.
                        Tuy nhiên, để tránh lỗi, ta có thể thêm xử lý hoặc dựa vào logic gọi.
                        -> TỐT NHẤT: Hàm này CHỈ dùng cho BASIC MODE - Bước 1.
        """
        # Lấy cấu hình từ lớp con
        style_config = self.get_style_config()
        tone = style_config.get('tone', 'neutral')
        instructions = style_config.get('instructions', [])
        title_hint = style_config.get('title_hint', 'Engaging Video Title')
        target_audience = style_config.get('target_audience')

        logger.debug(f"BaseVideoStyle: Generating prompt for Step 1 (Initial Sentences) - Style: '{tone}'")

        # Xác định ngôn ngữ
        lang_instruction = f"in {language}" if language == "en" else f"bằng tiếng Việt"

        # --- Bắt đầu xây dựng prompt cho Bước 1 ---
        prompt = f"Create a video narration script {lang_instruction} in a **{tone}** style, focusing on generating complete, engaging sentences.\n\n"

        # --- Thêm Source Material ---
        prompt += "**Source Material:**\n"
        input_type = source_data.get('type', 'unknown')
        content_data = source_data.get('data', '')
        context_hint = source_data.get('context', None)

        from config.settings import MAX_ARTICLE_LENGTH
        from src.utils import safe_truncate

        if input_type == 'article':
            if not isinstance(content_data, dict):
                 logger.error("BaseVideoStyle: Invalid source_data['data'] for type 'article'. Expected dict.")
                 return "Error: Invalid article data format."
            prompt += f"- TYPE: News Article\n"
            prompt += f"- ARTICLE TITLE: {content_data.get('title', '[Title Missing]')}\n"
            prompt += f"- ARTICLE CONTENT (Analyze This):\n{safe_truncate(content_data.get('content', '[Content Missing]'), MAX_ARTICLE_LENGTH)}\n"
            prompt += "- TASK: Rewrite the article into engaging narrative sentences.\n"
        elif input_type == 'keyword':
            prompt += f"- TYPE: Keyword/Topic\n"
            prompt += f"- TOPIC: \"{content_data}\"\n"
            prompt += f"- TASK: Generate relevant and engaging narrative sentences about the topic.\n"
        elif input_type == 'text':
            prompt += f"- TYPE: Input Text {f'({context_hint})' if context_hint else ''}\n"
            prompt += f"- TEXT CONTENT (Analyze This):\n{safe_truncate(content_data, 12000)}\n"
            prompt += f"- TASK: Summarize and rewrite the text into engaging narrative sentences.\n"
        else:
            logger.error(f"BaseVideoStyle: Invalid source data type '{input_type}'.")
            return "Error: Invalid source data type for script generation."

        # --- Thêm Quy tắc và Hướng dẫn Style ---
        prompt += f"""

        **Script Content Rules & Style Guidance:**
        *   Strictly adhere to the **{tone}** style.
        *   Follow these specific instructions: {'; '.join(instructions)}
        *   Write ONLY complete, natural-sounding sentences suitable for voice-over.
        *   Structure the content logically (e.g., hook, body, conclusion).
        *   Focus on clarity, engagement, and conveying the core message effectively.
        *   ABSOLUTELY NO visual cues, scene markers, or formatting like bullet points.
        """

        # --- THÊM HƯỚNG DẪN HOOK VÀO ĐÂY ---
        try:
            hook_instructions_for_prompt = self.hook_instructions() # Gọi hook từ chính instance này
            if hook_instructions_for_prompt:
                 prompt += f"""
                 
                **Opening Hook Requirement:**
                {hook_instructions_for_prompt.replace('**CRITICAL - HOOK GENERATION (First Sentences):**','').strip()}\n"""
            else:
                 prompt += "*   Start with an engaging hook.\n" # Fallback nếu hook rỗng
        except Exception as e:
             logger.error(f"Error getting hook instructions for basic prompt: {e}")
             prompt += "*   Start with an engaging hook.\n" # Fallback nếu lỗi
        # --- KẾT THÚC THÊM HOOK ---

        prompt += f"""
        *   Structure the content logically (e.g., hook, body, conclusion).
        *   Focus on clarity, engagement, and conveying the core message effectively.
        *   ABSOLUTELY NO visual cues, scene markers, or formatting like bullet points.
        """
        if target_audience:
            prompt += f"*   Tailor language and examples for the target audience: **{target_audience}**.\n"

        # --- Định dạng Output Yêu cầu (CHỈ title và initial_scenes) ---
        prompt += f"""

        **Final Output Format (JSON ONLY - Adhere Strictly):**
        Return ONLY a valid JSON object containing the video title and a list of the generated narrative sentences.
        {{
          "title": "{title_hint}",
          "initial_scenes": [
            "Engaging opening sentence or two (hook).",
            "Next logical narrative sentence.",
            "...",
            "Concluding sentence."
          ]
        }}

        **REMEMBER:** Provide ONLY the valid JSON object. The `initial_scenes` array should contain complete sentences, not short shots.
        """
        return prompt.strip()

    def should_override_layout(self) -> bool:
        """
        Trả về True nếu style này yêu cầu cấu trúc layout chương đặc biệt (Advanced mode).
        Mặc định là False.
        """
        return False

    def get_layout_generation_params(self) -> dict:
        """
        Trả về các tham số để tạo layout (nếu should_override_layout là True).
        Ví dụ: {'chapter_count_range': (3, 5), 'word_target_range': (300, 600), ...}
        Mặc định trả về dict rỗng.
        """
        return {}
    
    # --- Phương thức liên quan đến Visuals ---

    def should_override_visual_source(self) -> bool:
        """
        Trả về True nếu style này bắt buộc một visual source cụ thể.
        Mặc định là False.
        """
        return False

    def get_visual_source_preference(self) -> str:
        """
        Trả về lựa chọn visual source mặc định/ưu tiên ('search', 'ai', 'video_only').
        Mặc định là 'search'.
        """
        return "search"

    def generate_ai_image_prompt(self, scene_content: str, video_title: str) -> str:
        """
        Tạo prompt *chuẩn* cho LLM để LLM đó tạo ra prompt cho AI image generator (ví dụ: Imagen).
        Lớp con CÓ THỂ ghi đè nếu cần prompt đặc thù (như SeniorConversational).
        Hàm này chỉ TRẢ VỀ STRING PROMPT cho LLM, không gọi API.
        """
        # Lấy tone từ config của style hiện tại
        style_config = self.get_style_config()
        style_tone_desc = style_config.get('tone', 'neutral') # Lấy mô tả tone

        logger.debug(f"BaseVideoStyle: Generating standard AI image prompt instructions for tone '{style_tone_desc}'.")

        gpt_prompt_instructions = f"""
        You are an expert prompt engineer for text-to-image AI like Google Imagen 3.
        Your task is to convert the following news video scene content into a detailed and effective prompt for Imagen.

        Consider these factors:
        - The overall video title: "{video_title}"
        - The desired video style/tone: "{style_tone_desc}"
        - The specific content of this scene: "{scene_content}"

        IMPORTANT SAFETY GUIDELINES (Apply Strictly):
        - NEVER generate prompts depicting children, minors, or family scenes with minors unless explicitly required AND appropriate for the context (use caution). If possible, replace with adults (18+) or symbolic objects/animals.
        - Avoid depicting vulnerable populations or overly sensitive scenarios unless essential and handled respectfully.
        - Avoid generating prompts asking for highly realistic human faces in close-up detail, especially identifiable individuals. Focus on general appearance, emotion, setting, and action.

        Instructions for the Imagen Prompt You Generate:
        1. Be descriptive and specific about visual elements. Mention subjects, actions, setting, mood, and composition (e.g., wide shot, close-up, bird's eye view).
        2. Incorporate the video's style/tone (e.g., if 'dramatic', use words like 'intense lighting', 'dynamic angle'; if 'funny', suggest a humorous composition or expression).
        3. Aim for a prompt length suitable for Imagen (typically under 150 words is effective).
        4. Primarily aim for **photorealistic** style unless the scene content or video tone strongly suggests illustration, graphic, or abstract styles.
        5. AVOID explicitly asking for text, logos, or readable words in the image unless the scene is specifically about text/code/signage.
        6. If the original scene implies children inappropriately, REWRITE the visual concept using adults or symbolic representations (e.g., "children playing" might become "colorful toys scattered on a playground" or "adults supervising children from a distance").

        Output ONLY the generated Imagen prompt text, with no extra explanations, introductory phrases, or quotation marks surrounding the entire prompt.
        """
        return gpt_prompt_instructions.strip()

    def should_override_timing_mode(self) -> bool:
        """
        Trả về True nếu style này bắt buộc một visual timing mode cụ thể.
        Mặc định là False.
        """
        return False

    def get_preferred_timing_mode(self) -> str:
        """
        Trả về visual timing mode ưu tiên ('sync_to_audio', 'overall_theme_fixed_duration').
        Chỉ có ý nghĩa nếu should_override_timing_mode là True.
        Mặc định là 'sync_to_audio'.
        """
        return "sync_to_audio"

    # --- Phương thức liên quan đến Voice ---

    def get_voice_settings(self) -> dict:
        """
        Returns preferred voice settings for this style.
        Can include keys like 'voice' (e.g., 'alloy', 'onyx'), 'model' (e.g., 'tts-1-hd'),
        'speed' (e.g., 0.95), specific provider settings etc.
        VoiceGenerator will try to apply these if compatible with the selected TTS provider.

        Returns:
            dict: A dictionary of voice settings to override, or empty if using defaults.
        """
        return {
            "voice": "moss_audio_27e22420-2381-11f0-b934-42db1b8d9b3b",            
        }

    def get_video_editing_settings(self) -> dict:
        """
        Returns preferred video editing parameters for this style.
        Can include keys like 'transition_types' (list or string, e.g., ['dissolve']),
        'transition_duration' (float), 'image_animation' (string, e.g., 'zoom_in'),
        'animation_intensity' (float), 'music_volume' (float), etc.
        VideoEditor will try to apply these overrides.

        Returns:
            dict: A dictionary of video editing settings to override, or empty if using defaults.
        """
        return {} # Default: Use VideoEditor's default settings