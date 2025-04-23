# src/image_generator.py

import math
import os
import requests
import time
import json
import random
import hashlib
import shutil
import glob
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import subprocess
from moviepy import VideoFileClip
from typing import Dict, List, Optional, Tuple

from src.video_styles.base_style import BaseVideoStyle

from src.logger_config import setup_logger
logger = setup_logger(__name__)

# Import API keys and settings
from config.credentials import SERPER_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY
from config.settings import TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS, DALLE_SETTINGS, IMAGEN_SETTINGS
from src.video_clip_finder import VideoClipFinder

# --- IMPORTS CHO GEMINI ---
try:
    from google import genai
    from google.genai import types as genai_types
    from google.api_core import exceptions as google_exceptions # Để bắt lỗi API Google
    GOOGLE_AI_AVAILABLE = True
except ImportError:
    logger.warning("google-generativeai library not found. AI image generation with Imagen will be disabled. Install with: pip install google-generativeai")
    GOOGLE_AI_AVAILABLE = False

class ImageGenerator:
    def __init__(self, script_generator=None):
        """Initializes ImageGenerator with Serper and OpenAI configurations."""
        self.serper_api_key = SERPER_API_KEY
        if not self.serper_api_key:
            logger.error("Serper API key not found in credentials. Image search will likely fail.")
            # Consider raising an error if Serper is mandatory
            # raise ValueError("Serper API key is required.")

        # --- OpenAI Configuration (giữ lại key làm fallback) ---
        self.openai_api_key = OPENAI_API_KEY
        if not self.openai_api_key:
            # Chỉ cảnh báo, vì ưu tiên dùng script_generator
            logger.warning("OpenAI API key not found. Fallback LLM calls within ImageGenerator might fail if ScriptGenerator is not provided.")
        # Giữ lại base_url và headers phòng trường hợp cần gọi trực tiếp làm fallback cuối cùng
        self.openai_base_url = "https://api.openai.com/v1"
        self.openai_headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        # --- End OpenAI Configuration ---

        # --- LƯU LẠI INSTANCE SCRIPT GENERATOR ---
        self.script_generator = script_generator
        if not self.script_generator:
            logger.warning("ImageGenerator initialized without a ScriptGenerator instance. LLM calls for prompts/queries will use fallback methods (potentially direct OpenAI calls).")
        else:
             logger.info("ImageGenerator initialized with a ScriptGenerator instance for centralized LLM calls.")
        # --- KẾT THÚC LƯU INSTANCE ---

        # --- KHỞI TẠO GEMINI CLIENT VÀ ĐỌC CẤU HÌNH IMAGEN ---
        self.gemini_client = None # Vẫn khởi tạo là None
        self.genai_types = None   # Thêm để lưu types nếu cần
        if GOOGLE_AI_AVAILABLE and GEMINI_API_KEY:
            try:
                # --- THAY ĐỔI CHÍNH ---
                # Bỏ genai.configure(...)
                # Tạo client instance như sample code
                self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
                self.genai_types = genai_types # Lưu lại types để dùng sau
                # --- KẾT THÚC THAY ĐỔI ---
                logger.info("Google AI Client (for Imagen) initialized successfully using genai.Client.")
                # Đọc cấu hình Imagen (giữ nguyên)
                self.imagen_model = IMAGEN_SETTINGS.get("model", "models/imagen-3.0-generate-002")
                self.imagen_num_images = IMAGEN_SETTINGS.get("number_of_images", 1)
                self.imagen_aspect_ratio = IMAGEN_SETTINGS.get("aspect_ratio", "16:9")
                self.imagen_negative_prompt = IMAGEN_SETTINGS.get("negative_prompt", None)
                self.imagen_style_raw = IMAGEN_SETTINGS.get("style_raw", False)
                logger.info(f"Imagen settings loaded: Model={self.imagen_model}, Num={self.imagen_num_images}, AspectRatio={self.imagen_aspect_ratio}, StyleRaw={self.imagen_style_raw}")

            except AttributeError as client_attr_err: # Bắt lỗi nếu genai không có Client
                logger.error(f"Failed to initialize Google AI Client - AttributeError: {client_attr_err}")
                logger.error("It seems 'from google import genai' does not provide 'genai.Client'. Check library version or installation.")
                self.gemini_client = None
                self.genai_types = None
            except Exception as e:
                logger.error(f"Failed to initialize Google AI Client: {e}", exc_info=True)
                self.gemini_client = None
                self.genai_types = None
        elif not GOOGLE_AI_AVAILABLE:
            logger.warning("Google AI library not installed, Imagen generation disabled.")
        else:
            logger.warning("GEMINI_API_KEY not found in environment variables. Imagen generation disabled.")
        # --- KẾT THÚC KHỞI TẠO GEMINI ---

        # --- Các cài đặt thư mục và video dimensions ---
        self.temp_dir = TEMP_DIR
        self.assets_dir = ASSETS_DIR
        self.width = VIDEO_SETTINGS["width"]
        self.height = VIDEO_SETTINGS["height"]

        # Serper.dev API URL
        self.serper_url = "https://google.serper.dev/images"
        self.serper_headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json"
        }

        # Tạo thư mục tạm và cache
        self.image_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(self.image_dir, exist_ok=True)
        self.cache_dir = os.path.join(self.temp_dir, "image_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Tạo thư mục assets và fonts
        os.makedirs(self.assets_dir, exist_ok=True)
        self.fonts_dir = os.path.join(self.assets_dir, "fonts")
        os.makedirs(self.fonts_dir, exist_ok=True)

        # Kiểm tra fonts
        self._check_fonts()

        # Khởi tạo video finder (sẽ được gọi khi cần)
        self.video_finder = None

        # Đường dẫn cache cho video
        self.video_cache_dir = os.path.join(self.temp_dir, "video_cache")
        os.makedirs(self.video_cache_dir, exist_ok=True)

        # Tạo thư mục fallback video và load danh sách
        self.fallback_video_dir = os.path.join(self.assets_dir, "fallback_videos")
        os.makedirs(self.fallback_video_dir, exist_ok=True)
        self.fallback_video_files = []
        try:
             self.fallback_video_files = [os.path.join(self.fallback_video_dir, f) for f in os.listdir(self.fallback_video_dir) if f.lower().endswith(('.mp4', '.mov', '.webm'))]
             if self.fallback_video_files:
                 logger.info(f"Loaded {len(self.fallback_video_files)} fallback video files.")
        except Exception as e:
            logger.warning(f"Could not list fallback video files: {e}")

    # --- Tạo Theme Queries/Prompts PHỤC VỤ overall_theme_fixed_duration ---
    def _generate_theme_queries(self, main_title, count, language):
        """
        Sử dụng LLM để tạo các truy vấn tìm kiếm/prompt AI đa dạng dựa trên tiêu đề chính.

        Args:
            main_title (str): Tiêu đề chính của video.
            count (int): Số lượng ý tưởng cần tạo.
            language (str): Ngôn ngữ ('en', 'vi', ...).

        Returns:
            list: Danh sách các chuỗi query/prompt hoặc list fallback nếu lỗi.
        """
        logger.info(f"Generating {count} theme-based visual ideas for title: '{main_title}'")

        # Ngôn ngữ hướng dẫn cho prompt
        lang_instruction = f"in {language}" if language != "vi" else "bằng tiếng Việt"

        # --- Xây dựng Prompt ---
        prompt = f"""
        Analyze the main video title: "{main_title}"

        Your task is to brainstorm and generate exactly {count} diverse visual ideas related to this central theme. These ideas should be suitable either as concise image search queries (for stock photos/videos) or as descriptive prompts for an AI image generator (like DALL-E or Imagen).

        **Requirements for each visual idea:**
        - **Relevance:** Directly relate to the main title's theme or potential sub-topics.
        - **Diversity:** Each idea should represent a *different facet*, angle, metaphor, or visual style associated with the theme. Avoid simple variations of the same core idea. Think broadly: concepts, actions, objects, settings, emotions, styles (photorealistic, illustration, abstract if relevant).
        - **Conciseness:** Keep each idea relatively short (ideally 5-15 words).
        - **Visual Focus:** Emphasize visual elements and descriptions.
        - **Language:** Generate the ideas {lang_instruction}.

        **Example (Title: "The Rise of Remote Work"):**
        1. Diverse team collaborating online video call screen. (Action/Setting)
        2. Person working comfortably laptop home office cozy setting. (Setting/Mood)
        3. World map connected glowing lines symbolizing global teams. (Concept/Metaphor)
        4. Empty traditional office space sunlight streaming window. (Contrast/Setting)
        5. Graph showing upward trend remote work statistics. (Data/Concept)
        6. Close up hands typing laptop coffee mug nearby. (Detail/Action)
        7. Futuristic virtual reality workspace illustration. (Style/Concept)

        **Output Format:**
        Return ONLY a valid JSON object with a single key "theme_visual_ideas". The value should be a list of exactly {count} strings, each being a distinct visual idea.
        {{
          "theme_visual_ideas": [
            "Visual Idea 1 {lang_instruction}",
            "Visual Idea 2 {lang_instruction}",
            // ... up to {count} items
          ]
        }}
        """

        # --- Gọi LLM API ---
        # Giả sử ImageGenerator cũng được khởi tạo với LLM provider hoặc có cách truy cập
        # Nếu không, cần truyền đối tượng ScriptGenerator hoặc tạo instance mới ở đây.
        # TẠM THỜI: Giả sử có một phương thức _call_llm_api tương tự ScriptGenerator
        # Hoặc đơn giản là gọi trực tiếp OpenAI/Deepseek ở đây nếu không cần chuyển đổi LLM cho việc này.
        # Ví dụ gọi trực tiếp OpenAI (cần điều chỉnh nếu dùng Deepseek hoặc wrapper):
        if self.script_generator: # Chỉ gọi nếu có instance
            try:
                response_json_str = self.script_generator._call_llm_api(
                    user_prompt=prompt,
                    system_prompt="You are an assistant brainstorming diverse visual ideas based on a theme.", # Prompt hệ thống đơn giản
                    require_json=True,
                    is_core_content_task=False, # Đây là task phụ trợ
                    request_timeout=60
                )
                if response_json_str:
                    parsed_data = json.loads(response_json_str)
                    queries = parsed_data.get("theme_visual_ideas")
                    if queries and isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                        logger.info(f"LLM generated {len(queries)} theme visual ideas via ScriptGenerator.")
                        return [q for q in queries if q][:count]
                    else:
                        logger.warning("LLM response (via SG) for theme queries had invalid format.")
                else:
                    logger.warning("LLM call (via SG) for theme queries returned no response.")
            except Exception as e:
                logger.error(f"Error calling LLM (via SG) for theme queries: {e}", exc_info=True)
        else:
            logger.warning("ScriptGenerator instance not available for theme query generation.")

        # --- Fallback Logic ---
        logger.warning("LLM failed or unavailable for theme queries. Using simple fallback based on title.")
        base_queries = [main_title]
        keywords = [word for word in main_title.lower().split() if len(word) > 3] # Lấy từ khóa đơn giản
        if len(keywords) >= 2:
            base_queries.append(f"{keywords[0]} {keywords[1]}")
            if len(keywords) >= 3:
                 base_queries.append(f"{keywords[0]} {keywords[2]}")
        if keywords:
            base_queries.append(f"{keywords[0]} concept art")
            base_queries.append(f"{keywords[-1]} background")
        base_queries.append(f"Abstract visual theme {main_title[:30]}")
        base_queries.append(f"Technology related to {main_title[:30]}")
        base_queries.append(f"People working on {main_title[:30]}")

        # Lấy đủ số lượng yêu cầu, loại bỏ trùng lặp
        unique_queries = list(dict.fromkeys(base_queries)) # Giữ thứ tự và loại trùng
        return unique_queries[:count]
    

    def _select_media_with_ai(self, media_type: str, query: str, target_duration: Optional[float], candidates: List[Dict], scene_content: Optional[str] = None) -> Optional[str]:
        """
        Sử dụng LLM để chọn media (ảnh hoặc video) tốt nhất từ danh sách ứng viên
        dựa trên các tiêu chí hoặc quyết định từ chối tất cả.

        Args:
            media_type (str): Loại media cần chọn ("video" hoặc "image").
            query (str): Từ khóa tìm kiếm gốc đã được sử dụng.
            target_duration (Optional[float]): Thời lượng mục tiêu bằng giây (chỉ áp dụng cho video).
                                              Truyền None nếu là image.
            candidates (List[Dict]): Danh sách các dictionary chứa thông tin ứng viên media.
                                     Mỗi dict cần có ít nhất URL (key khác nhau cho ảnh/video),
                                     và nên có title/description, width, height, duration (cho video).
            scene_content (Optional[str]): Nội dung của scene/shot hiện tại để cung cấp thêm
                                           ngữ cảnh cho AI (nếu có).

        Returns:
            Optional[str]: URL của media được AI chọn. Trả về None nếu AI quyết định
                           không có ứng viên nào phù hợp, hoặc nếu có lỗi xảy ra.
        """
        # --- 1. Kiểm tra đầu vào ---
        if not candidates:
            logger.debug("AI Selection: No candidates provided to select from.")
            return None # Không có gì để chọn

        if not self.script_generator:
            logger.error("AI Selection: ScriptGenerator instance is required but not available.")
            return None # Không thể gọi AI nếu thiếu script_generator

        logger.info(f"Asking AI to select the best {media_type} from {len(candidates)} candidates for query: '{query}'...")

        # --- 2. Chuẩn bị dữ liệu ứng viên cho Prompt LLM ---
        # Giới hạn số lượng ứng viên gửi cho LLM để tránh quá tải token và chi phí
        max_candidates_to_send = 15 # Có thể điều chỉnh
        candidates_to_send = candidates[:max_candidates_to_send]
        logger.debug(f"Sending top {len(candidates_to_send)} candidates to LLM for evaluation.")

        candidates_info_for_prompt = []
        for idx, cand in enumerate(candidates_to_send):
            # Trích xuất thông tin cần thiết và chuẩn hóa
            info = {"id": idx + 1} # ID đơn giản để AI tham chiếu (1-based)
            info["source"] = cand.get("source", "Unknown Source")

            if media_type == "video":
                # Ưu tiên 'title', sau đó 'alt', rồi đến mô tả mặc định
                description = cand.get("title") or cand.get("alt", "No description provided")
                info["description"] = description[:120] # Giới hạn độ dài mô tả
                # Làm tròn duration và xử lý trường hợp 0 hoặc None
                duration_raw = cand.get("duration")
                info["duration_seconds"] = round(duration_raw, 1) if isinstance(duration_raw, (int, float)) and duration_raw > 0 else 0.0
                info["resolution"] = f"{cand.get('width', 'N/A')}x{cand.get('height', 'N/A')}"
                info["url_preview"] = cand.get("video_url", "")[:80] # Lấy phần đầu URL
            elif media_type == "image":
                # Ưu tiên 'title', 'alt', rồi đến mô tả mặc định
                description = cand.get("title") or cand.get("alt", "No description provided")
                info["description"] = description[:120]
                info["resolution"] = f"{cand.get('width', 'N/A')}x{cand.get('height', 'N/A')}"
                # Key URL cho ảnh thường là 'imageUrl' (Serper) hoặc 'src' (Pexels/Pixabay ảnh - cần chuẩn hóa trước)
                # Giả sử đã chuẩn hóa key thành 'imageUrl'
                info["url_preview"] = cand.get("imageUrl", cand.get("src", {}).get("original", ""))[:80]
            else:
                logger.error(f"AI Selection: Unsupported media_type '{media_type}'")
                return None

            candidates_info_for_prompt.append(info)

        # Chuyển danh sách thông tin ứng viên thành chuỗi JSON để đưa vào prompt
        try:
            candidates_json_str = json.dumps(candidates_info_for_prompt, indent=2, ensure_ascii=False)
        except Exception as json_err:
            logger.error(f"AI Selection: Error formatting candidate data to JSON: {json_err}")
            return None # Không thể tạo prompt nếu lỗi JSON

        # --- 3. Xây dựng Prompt chi tiết cho LLM ---
        prompt = f"""
        You are an expert Visual Content Selector AI. Your critical task is to analyze the following list of candidate {media_type}s and select the **single best** option that matches the requirements, OR explicitly decide that **none** of the candidates are suitable.

        **Requirements & Context:**
        - Media Type Needed: {media_type.capitalize()}
        - Original Search Query: "{query}"
        """
        # Thêm ngữ cảnh scene nếu có
        if scene_content:
            prompt += f"- Scene Context/Description: \"{scene_content[:150]}...\" (Use this to judge relevance)\n"

        # Thêm yêu cầu thời lượng cho video nếu có
        if media_type == "video" and target_duration is not None and target_duration > 0:
            min_acceptable_duration = target_duration * 0.75 # Ví dụ: Chấp nhận ngắn hơn tối đa 25%
            max_acceptable_duration = target_duration + 5.0   # Ví dụ: Chấp nhận dài hơn tối đa 5 giây
            prompt += f"- **Target Video Duration:** Approximately **{target_duration:.1f} seconds**. The ideal duration is between **{min_acceptable_duration:.1f}s and {max_acceptable_duration:.1f}s**. While duration is important, **relevance is the primary factor.** A highly relevant video slightly outside this range might still be acceptable.\n" # Nhấn mạnh sự linh hoạt nếu liên quan
        elif media_type == "video":
            prompt += "- Target Video Duration: Not specified or invalid. Focus on relevance and quality.\n"

        # Thêm yêu cầu chung về chất lượng và tỷ lệ khung hình
        prompt += f"""- Desired Aspect Ratio: Primarily **landscape** (approximately 16:9).
        - **Selection Goal (PRIORITY ON RELEVANCE):** Your **primary objective** is to choose the candidate with the **highest relevance** to the Search Query and Scene Context, based *mainly on its description*.
            - **Relevance (Most Important):** How well does the candidate's description match the query/context? This is the critical deciding factor.
            - **Secondary Factors (Consider AFTER Relevance):**
                - Visual Quality: Is it clear and professional? Higher resolution preferred.
                - Aspect Ratio: Does it match landscape 16:9?
                {' - Duration Match (Video Only): Does it fall near the target range? Remember, high relevance can outweigh minor duration mismatches.' if media_type == 'video' and target_duration is not None and target_duration > 0 else ''}

        **Candidate {media_type.capitalize()}s (Review these options):**
        ```json
        {candidates_json_str}
        ```

        **Your Decision Task:**
        Carefully evaluate each candidate, placing the **highest priority on relevance** (description match to query/context). Select the single candidate ID that is **most relevant**, while also being acceptable in terms of quality, aspect ratio, and (for video) duration. If NO candidate is sufficiently relevant OR if the most relevant candidate fails badly on secondary factors (e.g., extremely low quality, completely wrong aspect ratio, drastically wrong duration), you MUST decide to reject all.

        Respond ONLY with a valid JSON object following this exact structure:
        {{
          "decision": "select" | "reject_all",
          "selected_id": <integer: The 'id' number of the BEST candidate if decision is "select". Output null if "reject_all".>,
          "reasoning": "<string: Provide a concise explanation for your decision. Emphasize the relevance factor in your reasoning. If rejecting, explain why relevance or other critical factors were not met.>"
        }}

        **Example Reasoning:**
        - If selecting: "Candidate #2 (Pexels) has the strongest relevance, clearly describing '{query}'. Quality and aspect ratio are good. Duration (11.5s vs target 10.0s) is acceptable given the high relevance."
        - If rejecting (due to relevance): "None of the candidates' descriptions strongly match the required context of '{query} / {scene_content[:30]}...'. Rejecting all."
        - If rejecting (despite relevance): "Candidate #1 is relevant but its duration (3s) is far too short for the target (10s) and cannot be used. Rejecting all."

        **Output ONLY the JSON object.** No introductory text, no apologies, just the JSON.
        """

        # --- 4. Gọi API LLM thông qua ScriptGenerator ---
        try:
            # Sử dụng model được cấu hình riêng cho việc chọn media nếu có, nếu không dùng model chat mặc định
            selection_model = VIDEO_SETTINGS.get("llm_model_for_media_selection") or self.script_generator.chat_model

            # Ghi đè model trong payload nếu cần
            # (Lưu ý: Cách tốt hơn có thể là sửa đổi _call_llm_api để nhận tham số model)
            # Tạm thời, nếu model khác, có thể cần gọi API trực tiếp hoặc sửa đổi _call_llm_api
            # Giả sử _call_llm_api dùng model mặc định của script_generator
            if selection_model != self.script_generator.chat_model:
                 logger.warning(f"Media selection model ({selection_model}) differs from default chat model. Using default for now. Consider modifying _call_llm_api.")
                 # Hoặc bạn có thể tạo một instance ScriptGenerator mới với model này

            response_json_str = self.script_generator._call_llm_api(
                user_prompt=prompt,
                system_prompt=f"You are an AI assistant. Your sole task is to analyze candidate {media_type}s based on provided metadata and context, and select the best one or reject all, responding ONLY in the specified JSON format.",
                require_json=True,          # API phải trả về JSON
                is_core_content_task=False, # Đây là task phụ trợ, có thể dùng model rẻ/nhanh hơn
                request_timeout=60          # Timeout đủ cho AI phân tích và trả lời
            )

            if not response_json_str:
                logger.error("AI Selection: No response received from LLM.")
                return None # Lỗi giao tiếp API

        except Exception as api_err:
            logger.error(f"AI Selection: Error calling LLM API: {api_err}", exc_info=True)
            return None # Lỗi trong quá trình gọi API

        # --- 5. Phân tích phản hồi JSON từ LLM ---
        try:
            result = json.loads(response_json_str)

            decision = result.get("decision")
            reasoning = result.get("reasoning", "No reasoning provided by AI.")

            logger.info(f"AI Selection Decision: '{decision}'. Reasoning: {reasoning}")

            if decision == "select":
                selected_id = result.get("selected_id")

                # Kiểm tra selected_id hợp lệ
                if not isinstance(selected_id, int):
                    logger.error(f"AI Selection Error: 'selected_id' is not an integer ({selected_id}).")
                    return None

                # Chuyển đổi ID (1-based) thành index (0-based)
                selected_index = selected_id - 1

                # Kiểm tra xem index có nằm trong phạm vi của danh sách gốc không
                if 0 <= selected_index < len(candidates):
                    # Lấy thông tin ứng viên gốc từ danh sách ban đầu
                    selected_candidate = candidates[selected_index]

                    # Trích xuất URL chính xác dựa trên loại media
                    selected_url = None
                    if media_type == "video":
                        selected_url = selected_candidate.get("video_url")
                        if not selected_url: # Fallback key nếu cần
                            selected_url = selected_candidate.get("url")
                    elif media_type == "image":
                        # Ưu tiên các key phổ biến
                        selected_url = selected_candidate.get("imageUrl") # Serper
                        if not selected_url:
                             selected_url = selected_candidate.get("url") # Chung
                        if not selected_url:
                              # Thử cấu trúc src từ Pexels/Pixabay ảnh
                              src_dict = selected_candidate.get("src")
                              if isinstance(src_dict, dict):
                                   selected_url = src_dict.get("original") or src_dict.get("large2x") or src_dict.get("large")
                    # Thêm logic lấy URL cho các loại khác nếu cần

                    if selected_url:
                        logger.info(f"AI selected Candidate ID: {selected_id} (Index: {selected_index}). URL: {selected_url[:80]}...")
                        return selected_url # Trả về URL đã chọn
                    else:
                        logger.error(f"AI Selection Error: AI selected valid ID {selected_id}, but the corresponding candidate data is missing the required URL field.")
                        logger.debug(f"Candidate data: {selected_candidate}")
                        return None
                else:
                    logger.error(f"AI Selection Error: AI selected ID {selected_id}, which is out of range for the original candidate list (size: {len(candidates)}).")
                    return None # ID không hợp lệ

            elif decision == "reject_all":
                logger.info("AI decided to reject all candidates based on the criteria.")
                return None # Tín hiệu rõ ràng để kích hoạt fallback
            else:
                logger.warning(f"AI Selection Warning: Received an unexpected decision value '{decision}'. Treating as rejection.")
                return None # Coi như từ chối nếu decision không rõ ràng

        except json.JSONDecodeError as json_err:
            logger.error(f"AI Selection Error: Failed to parse JSON response from LLM: {json_err}")
            logger.debug(f"LLM Raw Response: {response_json_str}")
            return None # Lỗi parse JSON
        except Exception as parse_err:
            logger.error(f"AI Selection Error: Unexpected error processing LLM response: {parse_err}", exc_info=True)
            return None # Lỗi không xác định khác

    # --- Tìm/Tạo 1 Visual (KHÔNG có text fallback) PHỤC VỤ overall_theme_fixed_duration ---
    def _find_or_generate_single_visual(self, query, visual_source, project_media_dir, base_filename, style_strategy: BaseVideoStyle = None):
        """
        Thực hiện một lượt tìm kiếm (online -> local) hoặc tạo AI cho một query.
        Không bao gồm fallback tạo ảnh text.

        Args:
            query (str): Truy vấn tìm kiếm hoặc ý tưởng cho prompt AI.
            visual_source (str): 'search' hoặc 'ai'.
            project_media_dir (str): Thư mục để lưu file tạm.
            base_filename (str): Tên file cơ sở (không có phần mở rộng).

        Returns:
            tuple: (path_to_visual, visual_type) hoặc (None, None) nếu thất bại.
                   visual_type là 'image' hoặc 'video'.
        """
        # Định nghĩa đường dẫn file tạm
        temp_image_online_path = os.path.join(project_media_dir, f"{base_filename}_online.jpg")
        temp_image_local_path = os.path.join(project_media_dir, f"{base_filename}_local.jpg")
        temp_image_ai_path = os.path.join(project_media_dir, f"{base_filename}_ai.jpg")
        # Lưu ý: Không cần temp_video_search_path ở đây vì hàm này không tìm video

        visual_path = None
        visual_type = "unknown"

        logger.debug(f"Attempting to find/generate visual for query: '{query}' using method: {visual_source}")

        if visual_source == 'search':
            # --- Luồng Tìm kiếm ---
            # 1. Thử Online Search
            try:
                logger.debug(f"  Trying online search for '{query}'...")
                visual_path = self._get_cached_or_download_image(query, temp_image_online_path)
                if visual_path:
                    logger.debug(f"  Online search successful: {visual_path}")
                    visual_type = "image"
                    return visual_path, visual_type
                else:
                     logger.debug(f"  Online search returned no result for '{query}'.")
            except Exception as online_err:
                logger.warning(f"  Online search failed for '{query}': {online_err}")
                # Không return, tiếp tục thử local

            # 2. Thử Local Fallback (chỉ khi online thất bại)
            if not visual_path:
                try:
                    logger.debug(f"  Trying local fallback for '{query}'...")
                    visual_path = self._use_local_fallback_image(query, temp_image_local_path)
                    if visual_path:
                        logger.debug(f"  Local fallback successful: {visual_path}")
                        visual_type = "image"
                        return visual_path, visual_type
                    else:
                        logger.debug(f"  Local fallback returned no result for '{query}'.")
                except Exception as local_err:
                    logger.warning(f"  Local fallback failed for '{query}': {local_err}")

        elif visual_source == 'ai':
            # --- Luồng Tạo AI ---
            if not self.gemini_client:
                logger.warning(f"  Cannot generate AI image for '{query}': Gemini client not available.")
            elif not style_strategy: # THÊM KIỂM TRA
                logger.warning(f"  Cannot generate AI image for '{query}': Style Strategy not provided.")                
            else:
                try:
                    logger.debug(f"  Trying AI generation for '{query}'...")
                    # Tạo prompt AI từ query (có thể cần hàm helper riêng nếu muốn phức tạp hơn)
                    # Tạm thời coi query là content để tạo prompt đơn giản
                    imagen_prompt = self._create_imagen_prompt(
                        scene_content=query, # Dùng query làm content cho theme
                        video_title=query,   # Dùng query làm title cho theme
                        style_strategy=style_strategy # TRUYỀN STRATEGY
                    )
                    if imagen_prompt:
                        img_bytes = self._generate_image_with_imagen(imagen_prompt)
                        if img_bytes:
                            img = Image.open(BytesIO(img_bytes)).convert('RGB')
                            processed = self._resize_image(img)
                            processed.save(temp_image_ai_path, format="JPEG", quality=90)
                            visual_path = temp_image_ai_path
                            visual_type = "image"
                            logger.debug(f"  AI generation successful: {visual_path}")
                            return visual_path, visual_type
                        else:
                            logger.warning(f"  AI generation (Imagen API) returned no bytes for prompt based on '{query}'.")
                    else:
                        logger.warning(f"  Could not generate Imagen prompt for query '{query}'.")
                except Exception as ai_err:
                    logger.warning(f"  AI generation failed for '{query}': {ai_err}")

        elif visual_source == 'video_only':
            logger.debug(f"  Trying VIDEO ONLY sources for '{query}'...")
            # 1. Thử Online Video Finder
            # Đảm bảo finder được init nếu cần
            if self.video_finder is None and VIDEO_SETTINGS.get("enable_video_clips", False):
                try:
                    self.video_finder = VideoClipFinder()
                except Exception as vf_err:
                    logger.error(f"Error initializing VideoClipFinder in helper: {vf_err}")
                    self.video_finder = None

            if VIDEO_SETTINGS.get("enable_video_clips", False) and self.video_finder:
                try:
                    # Đường dẫn tạm cho video tìm được
                    temp_video_theme_online_path = os.path.join(project_media_dir, f"{base_filename}_vid_online.mp4")
                    # Gọi finder, dùng target duration mặc định cho theme mode (hoặc lấy từ settings)
                    theme_target_duration = VIDEO_SETTINGS.get("fixed_visual_duration", 7) # Lấy từ settings
                    visual_path = self.video_finder.find_video_clip(
                        query=query,
                        scene_content=query, # Dùng query làm context
                        output_path=temp_video_theme_online_path,
                        target_duration=theme_target_duration
                    )
                    if visual_path:
                        logger.debug(f"  Online video search successful: {visual_path}")
                        visual_type = "video"
                        # Trả về ngay khi tìm thấy online
                        return visual_path, visual_type
                    else:
                        logger.debug(f"  Online video search returned no result for '{query}'.")
                except Exception as online_vid_err:
                    logger.warning(f"  Online video search failed for '{query}': {online_vid_err}")
                    # Không return, tiếp tục thử fallback local

            # 2. Thử Local Video Fallback (chỉ khi online thất bại)
            if not visual_path:
                try:
                    logger.debug(f"  Trying local fallback video for '{query}'...")
                    local_fallback_path = self._use_local_fallback_video(query) # Chỉ lấy path
                    if local_fallback_path:
                        # Copy file fallback vào thư mục project để xử lý sau
                        temp_video_theme_local_path = os.path.join(project_media_dir, f"{base_filename}_vid_local_fallback.mp4")
                        shutil.copy2(local_fallback_path, temp_video_theme_local_path)
                        visual_path = temp_video_theme_local_path
                        visual_type = "video"
                        logger.debug(f"  Local video fallback successful: {visual_path}")
                        # Trả về ngay khi tìm thấy local fallback
                        return visual_path, visual_type
                    else:
                        logger.debug(f"  Local video fallback returned no result for '{query}'.")
                except Exception as local_vid_err:
                    logger.warning(f"  Local video fallback failed for '{query}': {local_vid_err}")
            # Nếu cả online và local video đều thất bại, visual_path sẽ là None

        # --- Nếu tất cả các phương pháp trong luồng đã chọn đều thất bại ---
        if visual_path:
            logger.debug(f"  Successfully obtained visual: {visual_path} (Type: {visual_type})")
        else:
            logger.debug(f"  No visual found/generated for query '{query}' using method '{visual_source}'.")

        # Trả về kết quả (có thể là None, None nếu thất bại)
        return visual_path, visual_type

    def generate_images_for_script(self, script, audio_files_info=None, visual_source="search", visual_timing_mode="sync_to_audio", style_strategy: BaseVideoStyle = None):
            """Tạo ảnh hoặc video cho tất cả các scenes (shots) trong script.
            Không còn dựa vào audio_files_info để xác định target duration cho từng shot ở bước này.

            Args:
                script (dict): Script được tạo bởi script_generator (chứa scenes/shots).
                audio_files_info (list, optional): Không còn được sử dụng để lấy duration scene.
                                                    Vẫn có thể dùng để lấy duration intro/outro.

            Returns:
                list: Danh sách thông tin về media (ảnh hoặc video) được tạo.
                    Trường 'duration' trong kết quả chỉ là placeholder hoặc duration gốc,
                    sẽ bị ghi đè bởi video_editor.
            """

            # Lấy các cài đặt cần thiết
            default_clip_target_duration = VIDEO_SETTINGS.get("video_clip_duration", 7) # Thời lượng mục tiêu cho video finder
            default_image_duration = VIDEO_SETTINGS.get("image_duration", 5) # Duration mặc định cho ảnh (placeholder)

            self.script = script
            media_items = []

            # Tạo thư mục project
            project_id = script.get('project_id', f"project_{time.strftime('%Y%m%d_%H%M%S')}")
            project_media_dir = os.path.join(self.image_dir, project_id)
            os.makedirs(project_media_dir, exist_ok=True)

            logger.info(f"Bắt đầu tạo media cho script: '{script['title']}' (Project: {project_id}) trong thư mục: {project_media_dir}")
            logger.info(f"Visual Source Method: '{visual_source}', Visual Timing Mode: '{visual_timing_mode}'")

            # Lấy tên style từ strategy để log nếu cần
            style_tone = "Unknown"
            if style_strategy:
                try:
                    style_tone = style_strategy.get_style_config().get('tone', 'Unknown')
                except Exception: pass
            logger.info(f"Style Tone: '{style_tone}', Visual Source: '{visual_source}', Timing Mode: '{visual_timing_mode}'")
            
            # --- 1. Xử lý intro card ---
            try:
                intro_image_path = self._create_title_card(script['title'], script.get('source', ''), project_media_dir)
                # Vẫn dùng audio_files_info để lấy duration intro nếu có
                intro_audio = next((a for a in audio_files_info if a.get('type') == 'intro'), None) if audio_files_info else None
                intro_duration_final = intro_audio['duration'] if intro_audio and intro_audio.get('duration', 0) > 0 else VIDEO_SETTINGS.get("intro_duration", 3)
                media_items.append({
                    "type": "image",
                    "media_type": "intro",
                    "path": intro_image_path,
                    "duration": intro_duration_final # Duration này là chính xác cho intro
                })
                logger.info(f" Intro Card created (Duration: {intro_duration_final:.2f}s)")
            except Exception as e:
                logger.error(f"Lỗi khi tạo intro card: {e}", exc_info=True)

            # --- 2. Source Image (nếu có) ---
            source_image_url = script.get('image_url')
            if source_image_url:
                logger.info(f"Attempting to download source image: {source_image_url}")
                try:
                    source_image_path = self._download_and_process_image(
                        source_image_url,
                        os.path.join(project_media_dir, "source_image.jpg")
                    )
                    if source_image_path:
                        media_items.append({
                            "type": "image", # Luôn là image
                            "media_type": "source", # Đánh dấu loại
                            "path": source_image_path,
                            "duration": default_image_duration, # Duration này chỉ là placeholder
                            "caption": "Source image from article"
                        })
                        logger.info(f" Successfully added source image: {os.path.basename(source_image_path)}")
                    else:
                        logger.warning(f"Failed to download or process source image from {source_image_url}")
                except Exception as e:
                    logger.error(f"Error downloading or processing source image {source_image_url}: {e}", exc_info=True)
            else:
                logger.info("No source image URL provided in the script.")

            # --- 3. Images/Videos for Each Scene (Shot) ---

            #------------------------------------------------------------#
            #==== PHÂN NHÁNH LOGIC CHÍNH DỰA TRÊN visual_timing_mode ====#
            #------------------------------------------------------------#
            
            if visual_timing_mode == 'overall_theme_fixed_duration':
                # --- LOGIC MỚI CHO CHẾ ĐỘ THEME (TỐI ƯU HÓA) ---
                logger.info("Generating visuals based on overall theme (Optimized Collection)...")
                fixed_duration_per_visual = VIDEO_SETTINGS.get("fixed_visual_duration", 5.0)
                query_count = VIDEO_SETTINGS.get("theme_visual_query_count", 7) # Số ý tưởng gốc

                # --- 1. Tính toán số lượng cần thiết ---
                total_estimated_audio_duration = sum(a.get('duration', 0) for a in audio_files_info if a.get('type') == 'speech_unit')
                if total_estimated_audio_duration <= 0:
                    logger.error("Cannot estimate audio duration for theme visuals.")
                    return media_items
                if fixed_duration_per_visual <= 0:
                    logger.error("Invalid fixed_visual_duration (<=0). Cannot proceed.")
                    return media_items

                # Số visual tối thiểu cần cho VideoEditor
                estimated_visual_slots = math.ceil(total_estimated_audio_duration / fixed_duration_per_visual)
                logger.info(f"Estimated audio: {total_estimated_audio_duration:.2f}s => Estimated visual slots needed: {estimated_visual_slots}")

                # --- 2. Đặt mục tiêu thu thập visual DUY NHẤT (Realistic Target) ---
                # Ví dụ: Gấp 3 lần số query gốc, hoặc 50% số slot cần, lấy giá trị lớn hơn
                # Hoặc đặt một con số cứng tối đa, ví dụ 30-40
                unique_visual_target_factor = 3.0 # Gấp mấy lần query gốc
                min_unique_ratio = 0.5 # Tối thiểu % so với slot cần
                max_api_calls = 40 # Giới hạn cứng số lần gọi API tối đa

                realistic_unique_target = max(
                    int(query_count * unique_visual_target_factor),
                    int(estimated_visual_slots * min_unique_ratio)
                )
                # Giới hạn số lượt gọi API tối đa
                num_api_calls_to_make = min(realistic_unique_target, max_api_calls)

                logger.info(f"Targeting collection of ~{realistic_unique_target} unique visuals, performing max {num_api_calls_to_make} API calls.")

                # --- 3. Tạo ý tưởng gốc từ LLM ---
                theme_queries = self._generate_theme_queries(
                    script.get('title', ''), query_count, script.get('language', 'en')
                )
                if not theme_queries:
                    logger.warning("Failed to generate theme queries. Using title as fallback query.")
                    # Fallback: dùng title làm query duy nhất
                    theme_queries = [script.get('title', 'natural')]
                    # Nếu fallback, chỉ nên gọi API 1 vài lần
                    num_api_calls_to_make = min(num_api_calls_to_make, 3)

                    # --- THÊM LOGIC KIỂM TRA VÀ OVERRIDE SEARCH QUERY Ở ĐÂY ---
                final_theme_queries = theme_queries # Mặc định dùng query đã tạo
                if visual_source == "video_only" and style_strategy:
                    try:
                        query_override = style_strategy.get_video_search_query_override()
                        if query_override:
                            if isinstance(query_override, list) and query_override:
                                    final_theme_queries = query_override # Thay thế hoàn toàn bằng list từ strategy
                                    logger.info(f"Theme Mode: Overriding theme queries with fixed list from strategy ({len(final_theme_queries)} queries).")
                            elif isinstance(query_override, str) and query_override.strip():
                                    final_theme_queries = [query_override.strip()] # Dùng string cố định làm query duy nhất
                                    logger.info(f"Theme Mode: Overriding theme queries with fixed string from strategy: '{final_theme_queries[0]}'")
                            # Nếu override không hợp lệ thì vẫn dùng theme_queries gốc
                    except AttributeError:
                        logger.debug("Theme Mode: Strategy does not support query override.")
                    except Exception as e:
                        logger.error(f"Theme Mode: Error getting query override: {e}. Using generated queries.")
                    # --- KẾT THÚC LOGIC OVERRIDE ---

                # --- 4. Mở rộng danh sách query để thực hiện API calls ---
                queries_to_process = []
                if final_theme_queries:
                    # Lặp lại các query (cố định hoặc gốc) để đạt đủ num_api_calls_to_make
                    query_source_list = final_theme_queries # Danh sách nguồn để lặp lại
                    # Nếu chỉ có 1 query cố định, số lần lặp là num_api_calls_to_make
                    repeat_factor = math.ceil(num_api_calls_to_make / len(query_source_list)) if len(query_source_list) > 0 else 1
                    queries_to_process = (query_source_list * repeat_factor)[:num_api_calls_to_make]
                    random.shuffle(queries_to_process) # Xáo trộn

                logger.info(f"Prepared {len(queries_to_process)} queries for limited API calls (using {'overridden' if final_theme_queries != theme_queries else 'generated/fallback'} theme queries).")

                # --- 5. Thực hiện API calls giới hạn và thu thập visual duy nhất ---
                unique_visuals_collected = []
                collected_paths = set()

                for idx, current_query in enumerate(queries_to_process):
                    logger.info(f"Processing API Call {idx + 1}/{len(queries_to_process)} for theme query: '{current_query[:80]}...' (Source: {visual_source})")

                    visual_path = None
                    visual_type = "unknown"
                    temp_base_filename = f"theme_limited_{idx + 1}" # Base filename cho file tạm

                    # --- Phân nhánh logic dựa trên visual_source ---
                    if visual_source == 'video_only':
                        visual_type = "video" # Luôn là video
                        # --- Tìm video cho theme (Logic tương tự sync_to_audio/video_only) ---
                        video_candidates = []
                        #if self.video_finder is None: # Khởi tạo nếu cần
                           # ... (logic khởi tạo video finder) ...
                        if VIDEO_SETTINGS.get("enable_video_clips", False) and self.video_finder:
                            video_candidates = self.video_finder.find_video_clip_candidates(current_query)

                        selected_video_url = None
                        if video_candidates:
                            if ai_selection_enabled:
                                logger.debug(f"Theme Call {idx+1}: Calling AI for video selection.")
                                selected_video_url = self._select_media_with_ai(
                                    media_type="video", query=current_query,
                                    target_duration=fixed_duration_per_visual, # Duration cố định cho theme
                                    candidates=video_candidates, scene_content=f"Overall theme: {script.get('title','')}" # Context là title
                                )
                            else:
                                logger.debug(f"Theme Call {idx+1}: AI disabled, picking first video.")
                                selected_video_url = video_candidates[0].get("video_url")

                        if selected_video_url:
                            try:
                                temp_video_theme_path = os.path.join(project_media_dir, f"{temp_base_filename}_vid_selected.mp4")
                                downloaded_path = self.video_finder._download_video(selected_video_url, current_query)
                                if downloaded_path:
                                    processed_path = self.video_finder._process_video_clip(downloaded_path, temp_video_theme_path)
                                    if processed_path: visual_path = processed_path
                            except Exception as e: logger.warning(f"Theme Call {idx+1}: Error processing selected video: {e}")

                        if not visual_path: # Fallback nếu AI không chọn hoặc lỗi
                            logger.debug(f"Theme Call {idx+1}: Trying local video fallback.")
                            local_fallback = self._use_local_fallback_video(current_query)
                            if local_fallback:
                                temp_local_vid_path = os.path.join(project_media_dir, f"{temp_base_filename}_vid_local.mp4")
                                try: # Copy và xử lý đơn giản (cắt)
                                    shutil.copy2(local_fallback, temp_local_vid_path)
                                    # Có thể thêm bước cắt local video về fixed_duration ở đây nếu muốn
                                    visual_path = temp_local_vid_path
                                except Exception as copy_err: logger.warning(f"Failed copying local fallback video: {copy_err}")

                        if not visual_path: # Fallback cuối: clip đen
                             logger.warning(f"Theme Call {idx+1}: Creating black clip fallback.")
                             black_path = os.path.join(project_media_dir, f"{temp_base_filename}_vid_black.mp4")
                             visual_path = self._create_black_clip(fixed_duration_per_visual, black_path)

                    elif visual_source == 'search':
                         visual_type = "image" # Trong theme mode, 'search' mặc định tìm ảnh
                         # --- Tìm ảnh cho theme sử dụng logic AI Selection ---
                         image_candidates = [] # Khởi tạo list ứng viên
                         try:
                             logger.debug(f"Theme Call {idx+1}: Searching online image candidates with _search_image_candidates_serper...")
                             # *** GỌI HÀM MỚI ĐỂ LẤY LIST ỨNG VIÊN ***
                             image_candidates = self._search_image_candidates_serper(current_query)
                         except Exception as search_err:
                             logger.warning(f"Theme Call {idx+1}: Error searching online image candidates via Serper: {search_err}")
                             image_candidates = [] # Đảm bảo list rỗng nếu lỗi

                         # --- Chọn ảnh bằng AI (nếu bật và có ứng viên) ---
                         selected_image_url = None
                         if image_candidates: # Chỉ chọn nếu có ứng viên tìm được
                             if ai_selection_enabled: # ai_selection_enabled đã được lấy ở đầu hàm generate_images_for_script
                                 # Gọi AI để chọn ảnh
                                 logger.debug(f"Theme Call {idx+1}: Calling AI to select from {len(image_candidates)} image candidate(s).")
                                 selected_image_url = self._select_media_with_ai(
                                     media_type="image",
                                     query=current_query, # Query hiện tại của theme
                                     target_duration=None,
                                     candidates=image_candidates, # List ứng viên ảnh
                                     scene_content=f"Overall theme: {script.get('title','')}" # Context là title video
                                 )
                             else:
                                 # Logic cũ nếu không dùng AI: Chọn ứng viên đầu
                                 logger.debug(f"Theme Call {idx+1}: AI selection disabled. Picking first image candidate.")
                                 first_img_url = image_candidates[0].get("imageUrl")
                                 if first_img_url:
                                      selected_image_url = first_img_url
                                 else:
                                      logger.warning(f"Theme Call {idx+1}: First image candidate missing 'imageUrl'.")
                         else:
                             logger.info(f"Theme Call {idx+1}: No online image candidates found for query '{current_query}'.")

                         # --- Tải và xử lý ảnh được chọn ---
                         if selected_image_url:
                             logger.info(f"Theme Call {idx+1}: Attempting download & process for selected image: {selected_image_url[:80]}...")
                             try:
                                 # Tạo path tạm cho ảnh theme này
                                 temp_image_theme_path = os.path.join(project_media_dir, f"{temp_base_filename}_img_selected.jpg")
                                 processed_path = self._download_and_process_image(selected_image_url, temp_image_theme_path)
                                 if processed_path:
                                     logger.info(f"Theme Call {idx+1}: Successfully processed selected online image.")
                                     visual_path = processed_path # Gán kết quả thành công
                                     # visual_type đã là "image"
                                 else:
                                     logger.warning(f"Theme Call {idx+1}: Failed processing selected image URL: {selected_image_url}")
                             except Exception as img_proc_err:
                                  logger.warning(f"Theme Call {idx+1}: Error processing selected image {selected_image_url}: {img_proc_err}")
                         # Nếu selected_image_url là None HOẶC xử lý lỗi -> Fallback tiếp theo

                         # --- Fallback ảnh local (nếu chưa tìm được online) ---
                         if not visual_path:
                             logger.debug(f"Theme Call {idx+1}: Trying local image fallback.")
                             try:
                                temp_local_img_path = os.path.join(project_media_dir, f"{temp_base_filename}_img_local.jpg")
                                local_path = self._use_local_fallback_image(current_query, temp_local_img_path)
                                if local_path:
                                     logger.info(f"Theme Call {idx+1}: Used local fallback image.")
                                     visual_path = local_path
                                else:
                                     logger.warning(f"Theme Call {idx+1}: Local image fallback returned no result.")
                             except Exception as e:
                                 logger.warning(f"Theme Call {idx+1}: Local image fallback failed: {e}")

                         if not visual_path: # Fallback ảnh local
                             logger.debug(f"Theme Call {idx+1}: Trying local image fallback.")
                             try:
                                temp_local_img_path = os.path.join(project_media_dir, f"{temp_base_filename}_img_local.jpg")
                                visual_path = self._use_local_fallback_image(current_query, temp_local_img_path)
                             except Exception as e: logger.warning(f"Local image fallback failed: {e}")

                         if not visual_path: # Fallback cuối: ảnh text (hoặc bỏ qua visual này?)
                              logger.warning(f"Theme Call {idx+1}: All image fallbacks failed. Consider text image or skipping.")
                              # visual_path = self._create_text_only_image(...) # Nếu muốn ảnh text

                    elif visual_source == 'ai':
                         visual_type = "image"
                         # --- Logic tạo ảnh AI (giữ nguyên, không cần AI selection) ---
                         if not self.gemini_client or not style_strategy:
                             logger.warning(f"Theme Call {idx+1}: Cannot generate AI image (Client or Strategy missing).")
                         else:
                            try:
                                temp_image_ai_path = os.path.join(project_media_dir, f"{temp_base_filename}_img_ai.jpg")
                                imagen_prompt = self._create_imagen_prompt(current_query, script.get('title',''), style_strategy)
                                if imagen_prompt:
                                    img_bytes = self._generate_image_with_imagen(imagen_prompt)
                                    if img_bytes:
                                        img = Image.open(BytesIO(img_bytes)).convert('RGB')
                                        processed = self._resize_image(img)
                                        processed.save(temp_image_ai_path, "JPEG", quality=90)
                                        visual_path = temp_image_ai_path
                            except Exception as ai_err: logger.warning(f"Theme Call {idx+1}: AI generation failed: {ai_err}")


                    # --- Thêm visual tìm được vào danh sách duy nhất ---
                    if visual_path:
                        if visual_path not in collected_paths:
                            unique_visuals_collected.append({
                                "type": visual_type, # visual_type đã được set ở trên
                                "media_type": "theme_visual",
                                "path": visual_path,
                                "duration": fixed_duration_per_visual,
                                "query_source": current_query # Lưu query gốc
                            })
                            collected_paths.add(visual_path)
                            logger.info(f"  Theme Call {idx+1}: Success. Collected unique visual #{len(unique_visuals_collected)}: {os.path.basename(visual_path)}")
                        else:
                            logger.debug(f"  Theme Call {idx+1}: Skipped duplicate visual: {os.path.basename(visual_path)}")
                    else:
                        logger.warning(f"  Theme Call {idx+1}: FAILED to obtain any visual for query '{current_query[:80]}...'.")

                # --- 6. Kiểm tra kết quả thu thập ---
                num_unique_collected = len(unique_visuals_collected)
                logger.info(f"Finished limited API calls. Collected {num_unique_collected} unique visuals.")

                final_visual_list_for_editor = [] # Danh sách cuối cùng gửi cho VideoEditor

                if num_unique_collected == 0:
                    logger.error("Failed to collect ANY unique theme visuals (Online or Local Fallback).")
                    # --- THÊM LOGIC FALLBACK TẠO CLIP ĐEN Ở ĐÂY ---
                    logger.warning(f"Creating {estimated_visual_slots} black video clips as fallback for theme mode.")
                    for slot_idx in range(estimated_visual_slots):
                         black_clip_filename = f"theme_black_fallback_{slot_idx + 1}.mp4"
                         black_clip_path = os.path.join(project_media_dir, black_clip_filename)
                         try:
                             created_black_path = self._create_black_clip(fixed_duration_per_visual, black_clip_path)
                             if created_black_path:
                                 # Thêm clip đen vào danh sách cuối cùng
                                 final_visual_list_for_editor.append({
                                     "type": "video", # Vẫn là video
                                     "media_type": "theme_visual_fallback", # Đánh dấu là fallback
                                     "path": created_black_path,
                                     "duration": fixed_duration_per_visual, # Duration cố định
                                     "query_source": "Black Clip Fallback"
                                 })
                                 # Không cần thêm vào collected_paths vì đây là fallback cuối
                             else:
                                 logger.error(f"Failed to create black clip fallback #{slot_idx + 1}.")
                         except Exception as black_gen_err:
                             logger.error(f"Error generating black clip fallback #{slot_idx + 1}: {black_gen_err}", exc_info=True)
                    # Kiểm tra lại xem có tạo được clip đen nào không
                    if not final_visual_list_for_editor:
                         logger.critical("CRITICAL: Failed to create even black clip fallbacks. Cannot proceed.")
                         # Có thể return media_items rỗng ở đây hoặc raise Exception
                         return media_items # Trả về list rỗng hiện tại (sẽ gây lỗi sau)
                    # --- KẾT THÚC LOGIC FALLBACK TẠO CLIP ĐEN ---
                    
                elif num_unique_collected >= estimated_visual_slots:
                    # Đủ visual duy nhất, chỉ cần lấy đủ số lượng cần
                    final_visual_list_for_editor = unique_visuals_collected[:estimated_visual_slots]
                    logger.info(f"Sufficient unique visuals collected ({num_unique_collected}). Using first {estimated_visual_slots}.")
                else:
                    # Không đủ visual duy nhất, cần lặp lại
                    logger.warning(f"Collected only {num_unique_collected} unique visuals, need {estimated_visual_slots}. Repeating collected visuals.")
                    final_visual_list_for_editor = list(unique_visuals_collected) # Bắt đầu với các visual đã có

                    # Lặp lại các visual đã có cho đến khi đủ số lượng
                    num_needed_more = estimated_visual_slots - num_unique_collected
                    # Sử dụng itertools.cycle để lặp lại danh sách một cách hiệu quả
                    from itertools import cycle
                    visual_cycle = cycle(unique_visuals_collected)

                    for _ in range(num_needed_more):
                        item_to_repeat = next(visual_cycle)
                        # Quan trọng: Tạo một bản sao nông (shallow copy) để tránh các vấn đề tham chiếu
                        # nếu có sửa đổi gì sau này (mặc dù ở đây chỉ đọc)
                        final_visual_list_for_editor.append(item_to_repeat.copy())

                    # Xáo trộn nhẹ danh sách cuối cùng để việc lặp lại ít lộ liễu hơn
                    # random.shuffle(final_visual_list_for_editor) # Bỏ comment nếu muốn xáo trộn cuối
                    logger.info(f"Filled visual list to {len(final_visual_list_for_editor)} items by repeating collected ones.")

                # Thêm danh sách cuối cùng vào media_items
                media_items.extend(final_visual_list_for_editor)
                # --- KẾT THÚC LOGIC MỚI CHO CHẾ ĐỘ THEME ---

            elif visual_timing_mode == 'sync_to_audio':
            # --- CHẾ ĐỘ SYNC TO AUDIO ---
                logger.info("Generating visuals synced to audio segments (per scene/shot)...")
                scenes_in_script = script.get('scenes', [])
                total_scenes = len(script.get('scenes', []))

                if total_scenes == 0:
                    logger.warning("No scenes found in script for sync_to_audio mode.")
                    return
                else:
                    # --- XÁC ĐỊNH DANH SÁCH QUERY CHO TẤT CẢ SCENES (ĐẶT RA NGOÀI VÒNG LẶP) ---
                    queries_for_scenes = [""] * total_scenes # Khởi tạo list rỗng với đúng kích thước
                    query_source_type = "openai_generated" # Mặc định

                    fixed_query_override = None
                    if visual_source == "video_only" and style_strategy: # Chỉ override nếu là video_only và có strategy
                        try:
                            query_override_value = style_strategy.get_video_search_query_override()
                            if query_override_value:
                                if isinstance(query_override_value, list) and query_override_value:
                                    fixed_query_override = query_override_value # Lưu lại list
                                    query_source_type = "strategy_list_override"
                                    logger.info(f"Sync Mode: Using overridden video query list ({len(fixed_query_override)} queries) from strategy.")
                                elif isinstance(query_override_value, str) and query_override_value.strip():
                                    fixed_query_override = [query_override_value.strip()] # Chuyển string thành list 1 phần tử
                                    query_source_type = "strategy_string_override"
                                    logger.info(f"Sync Mode: Using overridden fixed video query string from strategy: '{fixed_query_override[0]}'")
                                else:
                                    logger.warning("Sync Mode: Strategy query override is invalid. Falling back to OpenAI query generation.")
                                    query_source_type = "openai_generated" # Reset về default
                        except AttributeError:
                            logger.debug("Sync Mode: Strategy does not support query override. Will generate queries.")
                            query_source_type = "openai_generated" # Reset về default
                        except Exception as e:
                            logger.error(f"Sync Mode: Error getting query override: {e}. Will generate queries.", exc_info=True)
                            query_source_type = "openai_generated" # Reset về default

                # Tạo danh sách query cuối cùng
                if query_source_type.startswith("strategy"):
                    from itertools import cycle
                    query_cycler = cycle(fixed_query_override) # Tạo bộ lặp vòng
                    queries_for_scenes = [next(query_cycler) for _ in range(total_scenes)]
                    logger.info(f"Applied overridden queries cyclically to all {total_scenes} scenes.")
                else: # Tạo query bằng OpenAI cho từng scene
                     logger.info(f"Generating individual OpenAI queries for {total_scenes} scenes...")
                     for i, scene in enumerate(scenes_in_script):
                          scene_content = scene.get('content', '').strip()
                          if scene_content:
                               queries_for_scenes[i] = self._create_search_query(scene_content, script['title'])
                          else:
                               queries_for_scenes[i] = "natural" # Fallback cho scene rỗng
                     logger.info("Finished generating OpenAI queries.")
                # --- KẾT THÚC XÁC ĐỊNH DANH SÁCH QUERY ---

                for i, scene in enumerate(script.get('scenes', [])):
                    scene_number = scene.get('number', 'unknown')
                    scene_content = scene.get('content', '').strip()

                    # Lấy query đã chuẩn bị cho scene này
                    search_query = queries_for_scenes[i]
                    search_query_used = search_query # Lưu lại để log và thêm vào media_item

                    media_path_for_scene = None
                    media_type_for_scene = "unknown"
                    target_duration_for_finder = default_clip_target_duration # Dùng duration mặc định

                    logger.info(f"--- Processing Scene (Shot) {scene_number}/{total_scenes} (Query: '{search_query}') ---")

                    if not scene_content and not search_query: # Bỏ qua nếu cả content và query đều rỗng
                        logger.warning(f"Scene {scene_number}: Empty content and query. Skipping media generation.")
                        continue

                    # --- Tên file cơ sở (Đổi tên để rõ ràng hơn) ---
                    scene_base_filename = f"scene_{scene_number}"
                    temp_video_search_path = os.path.join(project_media_dir, f"{scene_base_filename}_vid_search.mp4")
                    temp_image_online_path = os.path.join(project_media_dir, f"{scene_base_filename}_img_online.jpg")
                    temp_image_local_path = os.path.join(project_media_dir, f"{scene_base_filename}_img_local.jpg") # File riêng cho local fallback
                    temp_image_ai_path = os.path.join(project_media_dir, f"{scene_base_filename}_img_ai.jpg") # File riêng cho AI
                    temp_image_text_path = os.path.join(project_media_dir, f"{scene_base_filename}_img_text.png") # File riêng cho text

                    # ==============================================================
                    # === PHÂN NHÁNH DỰA TRÊN visual_source ===
                    # ==============================================================

                    use_image_fallback_chain = False # Biến điều khiển chuỗi fallback ảnh

                    # --- OPTION 1: Primary Source is SEARCH ---
                    if visual_source == "search":
                        logger.debug(f"Scene {scene_number}: Using SEARCH as primary source (Image/Video).")
                        # Biến lưu kết quả cuối cùng cho scene này
                        media_path_for_scene = None
                        media_type_for_scene = "unknown" # Bắt đầu là unknown

                        # Kiểm tra cài đặt: có dùng AI không, có thử video không
                        ai_selection_enabled = VIDEO_SETTINGS.get("use_ai_for_media_selection", False)
                        attempt_video = scene.get('prefer_video', False) and VIDEO_SETTINGS.get("enable_video_clips", False)

                        # --- 1. ƯU TIÊN THỬ VIDEO (NẾU ĐƯỢC YÊU CẦU) ---
                        if attempt_video:
                            logger.info(f"Scene {scene_number}: Attempting VIDEO acquisition (AI Selection: {ai_selection_enabled})...")
                            try:
                                # --- a. Khởi tạo VideoClipFinder (nếu chưa có) ---
                                if self.video_finder is None:
                                    try:
                                        self.video_finder = VideoClipFinder()
                                        logger.debug("VideoClipFinder initialized.")
                                    except ImportError as ie:
                                        logger.error(f"Cannot import VideoClipFinder: {ie}. Video clips disabled for this run.")
                                        VIDEO_SETTINGS["enable_video_clips"] = False # Tắt tạm thời
                                        self.video_finder = None
                                    except Exception as vf_err:
                                        logger.error(f"Error initializing VideoClipFinder: {vf_err}. Cannot find videos.")
                                        self.video_finder = None

                                # --- b. Tìm ứng viên và chọn bằng AI (nếu có finder) ---
                                if self.video_finder:
                                    # Lấy danh sách ứng viên video thô
                                    video_candidates = self.video_finder.find_video_clip_candidates(search_query)
                                    selected_video_url = None

                                    if video_candidates:
                                        if ai_selection_enabled:
                                            # Gọi AI để chọn
                                            logger.debug(f"Scene {scene_number}: Calling AI to select from {len(video_candidates)} video candidates.")
                                            selected_video_url = self._select_media_with_ai(
                                                media_type="video",
                                                query=search_query_used, # Dùng query đã chuẩn bị
                                                target_duration=target_duration_for_finder,
                                                candidates=video_candidates,
                                                scene_content=scene_content
                                            )
                                        else:
                                            # Logic cũ nếu không dùng AI: Chọn ứng viên đầu tiên
                                            logger.debug(f"Scene {scene_number}: AI selection disabled. Picking first video candidate.")
                                            first_cand_url = video_candidates[0].get("video_url")
                                            if first_cand_url:
                                                selected_video_url = first_cand_url
                                            else:
                                                logger.warning(f"Scene {scene_number}: First video candidate missing URL.")
                                    else:
                                         logger.info(f"Scene {scene_number}: No online video candidates found for query '{search_query_used}'.")

                                    # --- c. Tải và xử lý video được chọn ---
                                    if selected_video_url:
                                        logger.info(f"Scene {scene_number}: Attempting download & process for selected video: {selected_video_url[:80]}...")
                                        try:
                                            # Download video (cần query gốc để caching hoạt động đúng)
                                            downloaded_path = self.video_finder._download_video(selected_video_url, search_query)
                                            if downloaded_path:
                                                # Process video (cắt, resize,...)
                                                processed_clip_path = self.video_finder._process_video_clip(downloaded_path, temp_video_search_path)
                                                if processed_clip_path:
                                                    logger.info(f"Scene {scene_number}: Successfully processed selected video: {os.path.basename(processed_clip_path)}")
                                                    media_path_for_scene = processed_clip_path
                                                    media_type_for_scene = "video" # Đặt loại media
                                                else:
                                                    logger.warning(f"Scene {scene_number}: Failed processing selected video file: {downloaded_path}")
                                            else:
                                                logger.warning(f"Scene {scene_number}: Failed downloading selected video URL: {selected_video_url}")
                                        except Exception as video_proc_err:
                                            logger.warning(f"Scene {scene_number}: Error downloading/processing selected video {selected_video_url}: {video_proc_err}")
                                    # Nếu không có selected_video_url hoặc xử lý lỗi, media_path_for_scene vẫn là None -> fallback ảnh

                                else: # self.video_finder is None
                                    logger.warning(f"Scene {scene_number}: Video finder not available, cannot search for video clips.")
                                # Kết thúc phần xử lý video finder

                            except Exception as video_acq_err:
                                logger.warning(f"Scene {scene_number}: Unexpected error during video acquisition: {video_acq_err}. Proceeding to image fallback.")
                        # --- Kết thúc Khối thử Video ---

                        # --- 2. FALLBACK SANG ẢNH (NẾU KHÔNG CÓ VIDEO HOẶC KHÔNG THỬ VIDEO) ---
                        if not media_path_for_scene:
                            # Log lý do chuyển sang ảnh
                            if attempt_video: # attempt_video đã được xác định ở phần xử lý video trước đó
                                logger.info(f"Scene {scene_number}: Video acquisition failed or no suitable video selected. Falling back to Image Acquisition.")
                            else:
                                logger.info(f"Scene {scene_number}: Video not preferred/enabled for this scene. Proceeding with Image Acquisition (AI Selection: {ai_selection_enabled}).") # ai_selection_enabled cũng đã xác định trước đó

                            # --- a. Tìm ứng viên ảnh online (Serper) ---
                            image_candidates = [] # Khởi tạo list ứng viên
                            try:
                                logger.debug(f"Scene {scene_number}: Searching online image candidates with _search_image_candidates_serper...")
                                # *** GỌI HÀM MỚI ĐỂ LẤY LIST ỨNG VIÊN ***
                                image_candidates = self._search_image_candidates_serper(search_query_used) # Dùng query đã chuẩn bị cho scene
                            except Exception as search_err:
                                logger.warning(f"Scene {scene_number}: Error searching online image candidates via Serper: {search_err}")
                                image_candidates = [] # Đảm bảo là list rỗng nếu lỗi

                            # --- b. Chọn ảnh bằng AI (nếu bật và có ứng viên) ---
                            selected_image_url = None
                            if image_candidates: # Chỉ chọn nếu có ứng viên tìm được
                                if ai_selection_enabled:
                                    # Gọi AI để chọn ảnh
                                    logger.debug(f"Scene {scene_number}: Calling AI to select from {len(image_candidates)} image candidate(s).")
                                    selected_image_url = self._select_media_with_ai(
                                        media_type="image",
                                        query=search_query_used,
                                        target_duration=None, # Ảnh không có target duration
                                        candidates=image_candidates, # Truyền list ứng viên
                                        scene_content=scene_content # Truyền context scene
                                    )
                                else:
                                    # Logic cũ nếu không dùng AI: Chọn ứng viên đầu tiên
                                    logger.debug(f"Scene {scene_number}: AI selection disabled. Picking first image candidate.")
                                    first_img_url = image_candidates[0].get("imageUrl") # Key URL của Serper
                                    if first_img_url:
                                         selected_image_url = first_img_url
                                    else:
                                         logger.warning(f"Scene {scene_number}: First image candidate missing 'imageUrl'.")
                            else:
                                logger.info(f"Scene {scene_number}: No online image candidates found for query '{search_query_used}'.")

                            # --- c. Tải và xử lý ảnh được chọn (bởi AI hoặc mặc định) ---
                            if selected_image_url:
                                logger.info(f"Scene {scene_number}: Attempting download & process for selected image: {selected_image_url[:80]}...")
                                try:
                                    # Hàm _download_and_process_image đã có sẵn và hoạt động tốt
                                    image_path_online = self._download_and_process_image(selected_image_url, temp_image_online_path) # Dùng path tạm của scene
                                    if image_path_online:
                                        logger.info(f"Scene {scene_number}: Successfully processed selected online image.")
                                        media_path_for_scene = image_path_online
                                        media_type_for_scene = "image" # Đặt loại media là ảnh
                                    else:
                                        # Hàm _download_and_process_image tự log lỗi bên trong
                                        logger.warning(f"Scene {scene_number}: Failed processing selected image URL: {selected_image_url}")
                                except Exception as img_proc_err:
                                     logger.warning(f"Scene {scene_number}: Error downloading/processing selected image {selected_image_url}: {img_proc_err}")
                            # Nếu selected_image_url là None HOẶC xử lý lỗi ở trên -> Fallback tiếp theo sẽ tự động chạy

                            # --- 3. CÁC BƯỚC FALLBACK ẢNH CÒN LẠI (NẾU CHƯA TÌM ĐƯỢC) ---
                            # Logic này giữ nguyên như code gốc của bạn, chỉ chạy nếu media_path_for_scene vẫn là None

                            # --- Fallback 3a: Local Image Fallback ---
                            if not media_path_for_scene:
                                try:
                                    logger.debug(f"Scene {scene_number}: Trying Local Fallback Image...")
                                    local_fallback_path = self._use_local_fallback_image(search_query, temp_image_local_path)
                                    if local_fallback_path:
                                        logger.info(f"Scene {scene_number}: Used Local Fallback Image.")
                                        media_path_for_scene = local_fallback_path
                                        media_type_for_scene = "image"
                                    else: logger.warning(f"Scene {scene_number}: Local Fallback Image returned no result.")
                                except Exception as local_err:
                                    logger.warning(f"Scene {scene_number}: Local Image Fallback failed: {local_err}. Proceeding.")

                            # --- Fallback 3b: AI Image Generation (NEW - Nếu được cấu hình) ---
                            if not media_path_for_scene and visual_source != 'ai': # Chỉ dùng làm fallback nếu nguồn chính không phải AI
                                if self.gemini_client and style_strategy: # Thêm kiểm tra style_strategy
                                    logger.info(f"Scene {scene_number}: Trying AI Image Generation Fallback (Imagen)...")
                                    try:
                                        # Tạo prompt và gọi Imagen (logic như cũ)
                                        imagen_prompt = self._create_imagen_prompt(scene_content, script['title'], style_strategy)
                                        if imagen_prompt:
                                            generated_image_bytes = self._generate_image_with_imagen(prompt=imagen_prompt)
                                            if generated_image_bytes:
                                                img = Image.open(BytesIO(generated_image_bytes)).convert('RGB')
                                                processed_image = self._resize_image(img)
                                                processed_image.save(temp_image_ai_path, "JPEG", quality=90)
                                                logger.info(f"Scene {scene_number}: AI Image Generation Fallback Successful.")
                                                media_path_for_scene = temp_image_ai_path
                                                media_type_for_scene = "image"
                                            else: logger.warning(f"Scene {scene_number}: AI Gen Fallback: Imagen API returned no image bytes.")
                                        else: logger.warning(f"Scene {scene_number}: AI Gen Fallback: Could not create Imagen prompt.")
                                    except Exception as ai_fallback_err:
                                        logger.warning(f"Scene {scene_number}: AI Image Generation Fallback failed: {ai_fallback_err}.")
                                else:
                                    logger.debug(f"Scene {scene_number}: Skipping AI Image Fallback (Gemini client/Strategy missing or AI is primary source).")

                            # --- Fallback 3c: Text-Only Image ---
                            if not media_path_for_scene:
                                try:
                                    logger.warning(f"Scene {scene_number}: All visual fallbacks failed. Creating Text-Only Image.")
                                    text_fallback_path = self._create_text_only_image(scene_content, temp_image_text_path)
                                    if text_fallback_path:
                                        logger.info(f"Scene {scene_number}: Created Text-Only Fallback Image.")
                                        media_path_for_scene = text_fallback_path
                                        media_type_for_scene = "image"
                                    else: logger.error(f"Scene {scene_number}: CRITICAL - Failed to create Text-Only fallback.")
                                except Exception as text_err:
                                    logger.error(f"Scene {scene_number}: CRITICAL - Error creating Text-Only fallback: {text_err}", exc_info=True)
                        # --- Kết thúc khối fallback ảnh ---
                    # --- Kết thúc Khối if visual_source == "search": ---

                    # --- OPTION 2: Primary Source is AI ---
                    elif visual_source == "ai":
                        logger.debug(f"Scene {scene_number}: Using AI Generation (Imagen) as primary source.")
                        media_type_for_scene = "image" # AI luôn tạo ảnh

                        if not self.gemini_client:
                            logger.error(f"Scene {scene_number}: Cannot use AI primary source - Gemini client not initialized.")
                            # ---> NHẢY XUỐNG PHẦN FALLBACK NGAY LẬP TỨC
                        elif not style_strategy: # THÊM KIỂM TRA NÀY
                            logger.error(f"Scene {scene_number}: Cannot generate AI image - Style Strategy not provided.")                            
                        else:
                            try:
                                # 1. Tạo Imagen prompt
                                imagen_prompt = self._create_imagen_prompt(
                                    scene_content=scene_content,
                                    video_title=script['title'],
                                    style_strategy=style_strategy # TRUYỀN STRATEGY
                                )
                                search_query_used = f"Imagen Prompt: {imagen_prompt[:100]}..." if imagen_prompt else "N/A"

                                if imagen_prompt:
                                    # 2. Gọi API Imagen
                                    generated_image_bytes = self._generate_image_with_imagen(prompt=imagen_prompt)
                                    if generated_image_bytes:
                                        # 3. Xử lý và lưu ảnh AI
                                        img = Image.open(BytesIO(generated_image_bytes))
                                        if img.mode != 'RGB': img = img.convert('RGB')
                                        processed_image = self._resize_image(img)
                                        processed_image.save(temp_image_ai_path, "JPEG", quality=90)
                                        logger.info(f"Scene {scene_number}: Primary AI Image Generation Successful.")
                                        media_path_for_scene = temp_image_ai_path
                                    else:
                                        logger.warning(f"Scene {scene_number}: Primary AI: Imagen API returned no image bytes.")
                                else:
                                    logger.warning(f"Scene {scene_number}: Primary AI: Could not generate Imagen prompt.")
                            except Exception as ai_err:
                                logger.error(f"Scene {scene_number}: Error during primary AI image generation: {ai_err}", exc_info=True)

                        # --- Fallback cho AI Primary (THỬ SEARCH TRƯỚC KHI TEXT) ---
                        if not media_path_for_scene:
                            logger.warning(f"Scene {scene_number}: Primary AI failed. Attempting Search/Local fallbacks...")

                            # --- Fallback 1 (cho AI): Online Image Search ---
                            try:
                                logger.debug(f"Scene {scene_number}: (AI Path Fallback) Trying Online Image Search...")
                                image_path_online = self._get_cached_or_download_image(search_query, temp_image_online_path) # Dùng search_query đã tạo
                                if image_path_online:
                                    logger.info(f"Scene {scene_number}: (AI Path Fallback) Found Online Image.")
                                    media_path_for_scene = image_path_online
                                    media_type_for_scene = "image"
                                else: logger.warning(f"Scene {scene_number}: (AI Path Fallback) Online Image Search returned no result.")
                            except Exception as online_err_f:
                                logger.warning(f"Scene {scene_number}: (AI Path Fallback) Online Image Search failed: {online_err_f}. Proceeding to next fallback.")

                            # --- Fallback 2 (cho AI): Local Image Fallback ---
                            if not media_path_for_scene:
                                try:
                                    logger.debug(f"Scene {scene_number}: (AI Path Fallback) Trying Local Fallback Image...")
                                    local_fallback_path = self._use_local_fallback_image(search_query, temp_image_local_path)
                                    if local_fallback_path:
                                        logger.info(f"Scene {scene_number}: (AI Path Fallback) Used Local Fallback Image.")
                                        media_path_for_scene = local_fallback_path
                                        media_type_for_scene = "image"
                                    else: logger.warning(f"Scene {scene_number}: (AI Path Fallback) Local Fallback Image returned no result.")
                                except Exception as local_err_f:
                                    logger.warning(f"Scene {scene_number}: (AI Path Fallback) Local Image Fallback failed: {local_err_f}. Proceeding to text fallback.")

                            # --- Fallback 3 (cho AI): Text-Only Image ---
                            if not media_path_for_scene:
                                try:
                                    logger.warning(f"Scene {scene_number}: Primary AI and Search/Local fallbacks failed. Creating Text-Only Image.")
                                    text_fallback_path = self._create_text_only_image(scene_content, temp_image_text_path)
                                    if text_fallback_path:
                                        logger.info(f"Scene {scene_number}: (AI Path Fallback) Created Text-Only Fallback Image.")
                                        media_path_for_scene = text_fallback_path
                                        media_type_for_scene = "image"
                                    else: logger.error(f"Scene {scene_number}: CRITICAL - Failed to create Text-Only fallback after AI failure.")
                                except Exception as text_err_f:
                                    logger.error(f"Scene {scene_number}: CRITICAL - Error creating Text-Only fallback after AI failure: {text_err_f}", exc_info=True)


                    # --- OPTION 3: Primary Source is VIDEO ONLY ---
                    elif visual_source == "video_only":
                        logger.debug(f"Scene {scene_number}: Using VIDEO ONLY as source.")
                        # Biến lưu kết quả cuối cùng
                        media_path_for_scene = None
                        media_type_for_scene = "video" # Luôn là video trong mode này

                        # Kiểm tra cài đặt AI
                        ai_selection_enabled = VIDEO_SETTINGS.get("use_ai_for_media_selection", False)

                        # --- Đảm bảo VideoClipFinder được khởi tạo (chỉ một lần nếu cần) ---
                        # Chỉ khởi tạo nếu chưa có và setting cho phép
                        if self.video_finder is None and VIDEO_SETTINGS.get("enable_video_clips", False):
                            try:
                                self.video_finder = VideoClipFinder()
                                logger.debug("VideoClipFinder initialized.")
                            except ImportError as ie:
                                logger.error(f"Cannot import VideoClipFinder: {ie}. Video clips disabled for this run.")
                                VIDEO_SETTINGS["enable_video_clips"] = False # Tắt tạm thời
                                self.video_finder = None
                            except Exception as vf_err:
                                logger.error(f"Error initializing VideoClipFinder: {vf_err}. Cannot find videos.")
                                self.video_finder = None
                        # ---------------------------------------------------------

                        # 1. Lấy danh sách ứng viên video từ các nguồn online
                        video_candidates = [] # Khởi tạo list rỗng
                        # <<< LỖI CỦA BẠN CÓ THỂ LÀ DO KHỐI LỆNH NGAY SAU ĐÂY BỊ THIẾU HOẶC SAI INDENT >>>
                        if VIDEO_SETTINGS.get("enable_video_clips", False) and self.video_finder:
                            try:
                                # Gọi hàm mới để lấy ứng viên thô
                                video_candidates = self.video_finder.find_video_clip_candidates(search_query_used) # Dùng query đã chuẩn bị
                            except Exception as cand_err:
                                logger.warning(f"Scene {scene_number}: Error getting video candidates: {cand_err}")
                                video_candidates = [] # Đảm bảo là list rỗng nếu có lỗi
                        else:
                            # Log lý do không tìm online
                            if not VIDEO_SETTINGS.get("enable_video_clips", False):
                                logger.info(f"Scene {scene_number}: Skipping online video search (Video clips disabled in settings).")
                            elif not self.video_finder:
                                logger.info(f"Scene {scene_number}: Skipping online video search (VideoClipFinder not available).")

                        # 2. Sử dụng AI để chọn video (nếu bật và có ứng viên)
                        selected_video_url = None
                        if video_candidates: # Chỉ chọn nếu có ứng viên
                            if ai_selection_enabled:
                                logger.debug(f"Scene {scene_number}: Calling AI to select from {len(video_candidates)} video candidates.")
                                selected_video_url = self._select_media_with_ai(
                                    media_type="video",
                                    query=search_query_used,
                                    target_duration=target_duration_for_finder, # Duration từ vòng lặp scene
                                    candidates=video_candidates,
                                    scene_content=scene_content
                                )
                            else:
                                # Logic cũ nếu không dùng AI: Chọn ứng viên đầu tiên
                                logger.debug(f"Scene {scene_number}: AI selection disabled. Picking first video candidate.")
                                first_cand_url = video_candidates[0].get("video_url")
                                if first_cand_url:
                                    selected_video_url = first_cand_url
                                else:
                                    logger.warning(f"Scene {scene_number}: First video candidate missing URL.")
                        else:
                            logger.info(f"Scene {scene_number}: No online video candidates found for query '{search_query_used}'. Proceeding to fallbacks.")

                        # 3. Thử tải và xử lý video được chọn (bởi AI hoặc mặc định)
                        if selected_video_url:
                            logger.info(f"Scene {scene_number}: Attempting download & process for selected video: {selected_video_url[:80]}...")
                            try:
                                if self.video_finder: # Kiểm tra lại finder còn tồn tại không
                                    # Download video (dùng query gốc để cache)
                                    downloaded_path = self.video_finder._download_video(selected_video_url, search_query)
                                    if downloaded_path:
                                        # Process video
                                        processed_clip_path = self.video_finder._process_video_clip(downloaded_path, temp_video_search_path) # Dùng path tạm cho scene
                                        if processed_clip_path:
                                            logger.info(f"Scene {scene_number}: Successfully processed selected online video: {os.path.basename(processed_clip_path)}")
                                            media_path_for_scene = processed_clip_path
                                            # media_type_for_scene đã là "video"
                                        else:
                                            logger.warning(f"Scene {scene_number}: Failed processing selected video file: {downloaded_path}")
                                    else:
                                        logger.warning(f"Scene {scene_number}: Failed downloading selected video URL: {selected_video_url}")
                                else:
                                     logger.error(f"Scene {scene_number}: VideoFinder became unavailable before processing selection.")
                            except Exception as video_proc_err:
                                logger.warning(f"Scene {scene_number}: Error processing selected video {selected_video_url}: {video_proc_err}")
                        # Nếu selected_video_url là None hoặc xử lý lỗi -> fallback

                        # 4. Fallback sang Local Video (nếu chưa tìm được online)
                        if not media_path_for_scene:
                            logger.info(f"Scene {scene_number}: Online video acquisition failed or skipped. Attempting Local Video Fallback...")
                            try:
                                # Logic gọi _use_local_fallback_video
                                local_fallback_path_orig = self._use_local_fallback_video(search_query) # Lấy path gốc
                                if local_fallback_path_orig:
                                    # Copy vào thư mục tạm của project và xử lý nếu cần
                                    fallback_dest_path = os.path.join(project_media_dir, f"{scene_base_filename}_vid_local_fallback.mp4")
                                    # TODO: Cân nhắc xử lý (vd: cắt theo target_duration_for_finder) video fallback ở đây nếu cần
                                    # Ví dụ đơn giản chỉ copy:
                                    shutil.copy2(local_fallback_path_orig, fallback_dest_path) # copy2 giữ metadata
                                    media_path_for_scene = fallback_dest_path # Sử dụng file đã copy
                                    logger.info(f"Scene {scene_number}: Used Local Fallback Video: {os.path.basename(media_path_for_scene)}")
                                else:
                                    logger.warning(f"Scene {scene_number}: Local Fallback Video directory empty or video not found for query '{search_query}'.")
                            except Exception as local_vid_err:
                                logger.warning(f"Scene {scene_number}: Error during Local Video Fallback: {local_vid_err}. Proceeding to final fallback.")

                        # 5. Fallback cuối cùng: Clip đen (nếu cả Online và Local đều thất bại)
                        if not media_path_for_scene:
                            logger.warning(f"Scene {scene_number}: All video sources failed (Online AI/Default, Local). Creating Black Video Clip as fallback.")
                            # Đường dẫn cho clip đen
                            black_clip_path = os.path.join(project_media_dir, f"{scene_base_filename}_vid_black_fallback.mp4")
                            try:
                                # Tạo clip đen với thời lượng mục tiêu của scene
                                created_black_path = self._create_black_clip(target_duration_for_finder, black_clip_path)
                                if created_black_path:
                                    media_path_for_scene = created_black_path
                                    # media_type_for_scene đã là "video"
                                    logger.info(f"Scene {scene_number}: Created Black Video fallback.")
                                else:
                                    logger.error(f"Scene {scene_number}: CRITICAL - Failed to create Black Video fallback.")
                                    # Scene này sẽ không có media
                            except Exception as black_err:
                                logger.error(f"Scene {scene_number}: CRITICAL - Error creating Black Video fallback: {black_err}", exc_info=True)
                                # Scene này sẽ không có media
                    # --- Kết thúc Khối elif visual_source == "video_only": ---

                    # === KHỐI CODE ĐỂ APPEND MEDIA ITEM CỦA SCENE HIỆN TẠI ===
                    if media_path_for_scene and media_type_for_scene != "unknown":
                        # Lấy duration gốc/placeholder (di chuyển logic tính duration vào đây)
                        media_final_duration_placeholder = 0
                        if media_type_for_scene == 'video':
                            try:
                                # Ưu tiên ffprobe
                                duration = self._get_video_duration_ffprobe(media_path_for_scene)
                                if duration:
                                     media_final_duration_placeholder = duration
                                else: # Fallback nếu ffprobe lỗi
                                     logger.warning(f"ffprobe failed for {os.path.basename(media_path_for_scene)}, trying VideoFileClip...")
                                     # Đặt timeout khi mở VideoFileClip để tránh treo
                                     # Lưu ý: Cần import VideoFileClip ở đầu file
                                     # from moviepy import VideoFileClip
                                     with VideoFileClip(media_path_for_scene, audio=False, target_resolution=(None, 480)) as clip: # Mở với độ phân giải thấp, không audio để nhanh hơn
                                        media_final_duration_placeholder = clip.duration
                            except Exception as e:
                                logger.warning(f"Could not get duration for video {os.path.basename(media_path_for_scene)}: {e}. Using default: {default_clip_target_duration}s")
                                media_final_duration_placeholder = default_clip_target_duration
                        elif media_type_for_scene == 'image':
                            media_final_duration_placeholder = default_image_duration

                        # Thực hiện append vào list media_items
                        media_items.append({
                            "type": media_type_for_scene,
                            "media_type": "scene",                # Quan trọng: Đánh dấu là scene
                            "number": scene_number,               # Quan trọng: Số thứ tự scene
                            "path": media_path_for_scene,
                            "duration": media_final_duration_placeholder,
                            "content": scene_content,
                            "search_query": search_query_used
                        })
                        # Log xác nhận
                        logger.info(f"Scene {scene_number}: Added {media_type_for_scene} media. Path: {os.path.basename(media_path_for_scene)}")
                        logger.debug(f"===> media_items now contains {len(media_items)} items after adding scene {scene_number}.")

                    else:
                        # Log lỗi nếu không tìm được gì cho scene này
                        logger.error(f"Scene {scene_number}: FAILED TO ADD ANY MEDIA after trying primary source and all fallback methods for content: '{scene_content[:50]}...'")
                    # ====================================================================
                    # === KẾT THÚC KHỐI CODE APPEND MEDIA ITEM SCENE ===
                    # ====================================================================                    

            # --- 4. Outro Card ---
            try:
                outro_image_path = self._create_outro_card(script['title'], script.get('source', ''), project_media_dir)
                # Vẫn dùng audio_files_info để lấy duration outro nếu có
                outro_audio = next((a for a in audio_files_info if a.get('type') == 'outro'), None) if audio_files_info else None
                outro_duration_final = outro_audio['duration'] if outro_audio and outro_audio.get('duration', 0) > 0 else VIDEO_SETTINGS.get("outro_duration", 5)
                if outro_image_path: # Chỉ thêm nếu tạo thành công
                    media_items.append({
                        "type": "image",
                        "media_type": "outro",
                        "path": outro_image_path,
                        "duration": outro_duration_final # Duration này là chính xác cho outro
                    })
                    logger.info(f" Outro Card created (Duration: {outro_duration_final:.2f}s)")
                else:
                    logger.warning("Failed to create outro card image path.")
            except Exception as e:
                logger.error(f"Lỗi khi tạo outro card (nhưng vẫn tiếp tục): {e}", exc_info=True) # Log lỗi nhưng không dừng lại

            # --- 5. Save Metadata ---
            try:
                # Hàm _save_media_info cần được cập nhật để xử lý duration placeholder
                self._save_media_info(media_items, script['title'], project_media_dir)
            except Exception as e:
                logger.error(f"Lỗi khi lưu metadata: {e}", exc_info=True)

                # *** THÊM LOG DEBUG Ở ĐÂY ***
                logger.debug("---------------------------------------------")
                logger.debug(f"Final check before returning from generate_images_for_script")
                logger.debug(f"Visual Timing Mode was: {visual_timing_mode}")
                logger.debug(f"Total media items generated: {len(media_items)}")
                media_types_summary = {}
                for item in media_items:
                    m_type = item.get("media_type", "unknown")
                    media_types_summary[m_type] = media_types_summary.get(m_type, 0) + 1
                logger.debug(f"Media types breakdown: {media_types_summary}")
                if not media_items:
                    logger.error("!!! media_items list IS EMPTY before final return !!!")
                else:
                    logger.debug(f"First item type: {media_items[0].get('media_type', 'N/A')}") # Log thử item đầu tiên
                logger.debug("---------------------------------------------")
                # *** KẾT THÚC LOG DEBUG ***

                image_count = sum(1 for item in media_items if item.get('type') == 'image')
                video_count = sum(1 for item in media_items if item.get('type') == 'video')
                logger.info(f"Hoàn thành tạo media: {len(media_items)} items ({image_count} ảnh, {video_count} video)")

                # *** LOG DEBUG Ở ĐÂY ***
                logger.debug("---------------------------------------------")
                logger.debug(f"Final check before returning from generate_images_for_script")
                logger.debug(f"Visual Timing Mode was: {visual_timing_mode}")
                logger.debug(f"Total media items generated: {len(media_items)}")
                # Log loại media để xem có theme visuals không
                media_types_summary = {}
                for item in media_items:
                    m_type = item.get("media_type", "unknown")
                    media_types_summary[m_type] = media_types_summary.get(m_type, 0) + 1
                logger.debug(f"Media types breakdown: {media_types_summary}")
                if not media_items:
                    logger.error("!!! media_items list IS EMPTY before final return !!!")
                logger.debug("---------------------------------------------")
                # *** KẾT THÚC LOG DEBUG ***

            return media_items

    def _create_imagen_prompt(self, scene_content, video_title, style_strategy: BaseVideoStyle):
        """
        Uses the configured LLM (via ScriptGenerator) to generate a descriptive Imagen prompt
        based on scene content, video title, and guidance from the style strategy.

        Args:
            scene_content (str): The narrative content of the current scene/shot.
            video_title (str): The main title of the video for context.
            style_strategy (BaseVideoStyle): The selected video style strategy object.

        Returns:
            str: A generated text prompt suitable for the Imagen API, or a basic fallback prompt.
        """
        # --- KIỂM TRA ĐẦU VÀO ---
        if not style_strategy:
            logger.error("Cannot create Imagen prompt: Style Strategy is missing.")
            # Trả về fallback đơn giản nhất
            return f"Simple image representing: {scene_content[:80]}"
        # --------------------

        # --- LẤY PROMPT HƯỚNG DẪN TỪ STRATEGY ---
        gpt_prompt_instructions = "" # Khởi tạo rỗng
        try:
            # Gọi phương thức của strategy để lấy hướng dẫn tạo prompt Imagen
            # Phương thức này nên trả về một chuỗi hướng dẫn chi tiết cho LLM khác
            gpt_prompt_instructions = style_strategy.generate_ai_image_prompt(scene_content, video_title)
            if not gpt_prompt_instructions:
                 logger.warning(f"Style strategy '{type(style_strategy).__name__}' returned empty instructions for Imagen prompt generation. Using basic fallback.")
                 return f"Image depicting: {scene_content[:100]}" # Fallback nếu strategy trả về rỗng

            logger.debug(f"Received AI image prompt instructions from strategy.")

        except AttributeError: # Nếu strategy không implement phương thức này
            logger.warning(f"Style strategy '{type(style_strategy).__name__}' does not implement 'generate_ai_image_prompt'. Using basic fallback.")
            return f"Image depicting: {scene_content[:100]}" # Fallback
        except Exception as strat_err:
            logger.error(f"Error getting AI image prompt instructions from strategy: {strat_err}. Using basic fallback.")
            return f"Image depicting: {scene_content[:100]}" # Fallback
        # ---------------------------------------

        # --- Fallback cơ bản nếu không có ScriptGenerator để gọi LLM ---
        if not self.script_generator:
            logger.warning("ScriptGenerator not available for Imagen prompt generation refinement. Using basic fallback based on strategy instructions (if any) or scene content.")
            # Cố gắng dùng instruction từ strategy làm prompt Imagen trực tiếp nếu có
            if gpt_prompt_instructions:
                 # Lấy phần cốt lõi của instruction (có thể cần tinh chỉnh dựa trên format của generate_ai_image_prompt)
                 # Giả sử instruction là một đoạn văn mô tả
                 return f"{gpt_prompt_instructions[:250]}" # Giới hạn độ dài
            else:
                 return f"Image depicting: {scene_content[:100]}" # Fallback cuối
        # ----------------------------------------------------

        # --- Gọi LLM (qua ScriptGenerator) để tạo prompt Imagen cuối cùng ---
        try:
            logger.debug(f"Refining final Imagen prompt via LLM (SG) based on strategy instructions for scene: '{scene_content[:80]}...'")

            # Gọi _call_llm_api thông qua instance đã lưu
            # Yêu cầu LLM tạo ra prompt cuối cùng dựa trên hướng dẫn từ strategy
            final_imagen_prompt_raw = self.script_generator._call_llm_api(
                user_prompt=gpt_prompt_instructions, # Dùng hướng dẫn từ strategy làm input chính
                system_prompt="You are an AI assistant specializing in crafting high-quality, descriptive text prompts for advanced image generation models like Google Imagen. Focus on visual details, style, composition, and lighting based on the user's instructions.",
                require_json=False, # Chỉ cần output là text prompt
                is_core_content_task=False, # Đây là task phụ trợ
                request_timeout=35 # Timeout vừa đủ
            )

            if final_imagen_prompt_raw:
                # Xử lý prompt nhận được: bỏ dấu ngoặc kép, khoảng trắng thừa
                final_imagen_prompt = final_imagen_prompt_raw.strip().replace('"', '')
                # Kiểm tra lại xem prompt có rỗng không sau khi xử lý
                if not final_imagen_prompt:
                    logger.error("LLM (via SG) returned an empty Imagen prompt after processing.")
                    return f"Image depicting: {scene_content[:100]}" # Fallback

                logger.info(f"Generated final Imagen prompt via LLM (SG): '{final_imagen_prompt[:100]}...'")
                return final_imagen_prompt # Trả về prompt cuối cùng cho Imagen
            else:
                logger.error(f"LLM call (via SG) for final Imagen prompt generation returned empty.")
                # Nếu LLM không trả về gì, thử dùng instruction gốc từ strategy làm fallback
                if gpt_prompt_instructions:
                    logger.warning("Falling back to using instructions from strategy as Imagen prompt.")
                    return f"{gpt_prompt_instructions[:250]}"
                else:
                    return f"Image depicting: {scene_content[:100]}" # Fallback cuối cùng

        except Exception as e:
            logger.error(f"Error calling LLM (via SG) for final Imagen prompt generation: {e}", exc_info=True)
            # Fallback nếu gọi LLM lỗi
            if gpt_prompt_instructions:
                 logger.warning("Falling back to using instructions from strategy as Imagen prompt due to LLM error.")
                 return f"{gpt_prompt_instructions[:250]}"
            else:
                 return f"Image depicting: {scene_content[:100]}" # Fallback cuối cùng

    def _generate_image_with_imagen(self, prompt):
        """Generates an image using the Google Imagen API via Google AI Client."""
        if not self.gemini_client:
            logger.error("Google AI Client not initialized. Cannot generate Imagen images.")
            return None

        if not self.genai_types:
            logger.error("Google AI types not available. Cannot create config.")
            # Hoặc thử import lại: from google.genai import types as genai_types
            # Nếu import lại không được thì return None
            return None
        
        logger.info(f"Requesting Imagen image (Model: {self.imagen_model}) with prompt: {prompt[:80]}...")

        try:
            # Tạo config sử dụng self.genai_types
            config = self.genai_types.GenerateImagesConfig(
                number_of_images=self.imagen_num_images,
                aspect_ratio=self.imagen_aspect_ratio
                # Thêm các tham số config khác nếu cần
            )

            # Gọi qua client instance đã lưu trong self.gemini_client
            response = self.gemini_client.models.generate_images( # DÙNG self.gemini_client
                model=self.imagen_model,
                prompt=prompt,
                config=config
            )

            if hasattr(response, 'generated_images') and response.generated_images and len(response.generated_images) > 0:
                # Get the first image from the response
                generated_image_data = response.generated_images[0]
                
                # Extract image bytes
                if hasattr(generated_image_data, 'image') and hasattr(generated_image_data.image, 'image_bytes'):
                    image_bytes = generated_image_data.image.image_bytes
                    if image_bytes:
                        logger.info("Imagen image bytes received successfully.")
                        return image_bytes
                    else:
                        logger.error("Imagen API response has empty image bytes.")
                        return None
                else:
                    logger.error("Generated image data does not contain expected image bytes attribute.")
                    return None
            else:
                logger.error(f"Imagen API response did not contain generated images: generated_images={getattr(response, 'generated_images', None)}")
                
                # Log additional information if available
                if hasattr(response, 'safety_feedback') and response.safety_feedback:
                    logger.warning(f"Safety feedback received: {response.safety_feedback}")
                    
                return None

        except Exception as e:
            logger.error(f"Unexpected error generating Imagen image: {e}", exc_info=True)
            return None

    def _save_media_info(self, media_items, title, project_dir):
            """Lưu metadata về các media được tạo.
            Ghi chú: Duration cho 'scene' items chỉ là placeholder/gốc.
            """
            media_metadata = []
            for item in media_items:
                item_copy = item.copy()
                try:
                    rel_path = os.path.relpath(item['path'], project_dir)
                    item_copy['relative_path'] = rel_path.replace('\\', '/')
                except ValueError:
                    item_copy['relative_path'] = os.path.basename(item['path'])

                # Giữ lại các trường quan trọng
                # Thêm ghi chú vào duration nếu là scene item
                keys_to_keep = ['type', 'media_type', 'number', 'relative_path', 'duration', 'search_query', 'content']
                metadata_entry = {k: item_copy.get(k) for k in keys_to_keep if k in item_copy}

                # Ghi chú về duration (tùy chọn)
                if metadata_entry.get('media_type') == 'scene':
                    metadata_entry['duration_note'] = "Placeholder or original clip duration; overridden by video editor"

                # Bỏ đường dẫn tuyệt đối khỏi metadata
                if 'path' in metadata_entry: del metadata_entry['path']

                media_metadata.append(metadata_entry)

            output_data = {
                'project_title': title,
                'creation_timestamp': time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                'project_folder': os.path.basename(project_dir),
                'total_items': len(media_metadata),
                'video_dimensions': f"{self.width}x{self.height}",
                'items': media_metadata
            }

            output_file = os.path.join(project_dir, "media_info.json")
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, ensure_ascii=False, indent=4)
                logger.info(f"Saved media metadata to: {output_file}")
            except Exception as e:
                logger.error(f"Failed to save media metadata to {output_file}: {e}", exc_info=True)

    def _search_image_candidates_serper(self, query: str, num_results: int = 20) -> List[Dict]:
        """
        Tìm kiếm ứng viên ảnh từ Serper.dev Image Search API và trả về danh sách thô.
        Hàm này KHÔNG tải ảnh, chỉ lấy metadata.

        Args:
            query (str): Từ khóa tìm kiếm ảnh.
            num_results (int): Số lượng kết quả tối đa yêu cầu từ API.

        Returns:
            List[Dict]: Danh sách các dictionary chứa thông tin metadata của
                        các ảnh ứng viên tìm được. Trả về list rỗng nếu lỗi.
        """
        if not self.serper_api_key:
            logger.error("Serper API key is missing. Cannot search for image candidates.")
            return [] # Không thể tìm kiếm nếu thiếu key

        logger.info(f"Searching Serper for IMAGE candidates with query: '{query}' (Requesting {num_results} results)")

        try:
            # Payload cho tìm kiếm ảnh (có thể thêm các tham số khác nếu cần)
            payload = json.dumps({
                "q": query,
                "gl": "us",  # Có thể điều chỉnh theo khu vực
                "hl": "en",  # Ngôn ngữ tìm kiếm
                "num": num_results
            })

            # Gọi API Serper Image Search
            response = requests.post(
                self.serper_url, # self.serper_url đã định nghĩa trong __init__
                headers=self.serper_headers, # self.serper_headers đã định nghĩa trong __init__
                data=payload,
                timeout=15 # Timeout hợp lý
            )

            # Kiểm tra lỗi HTTP
            if response.status_code != 200:
                logger.error(f"Serper Image API error: {response.status_code}, {response.text}")
                return [] # Trả về rỗng nếu lỗi API

            # Parse JSON response
            data = response.json()
            image_results = data.get("images", [])

            if not image_results:
                logger.info(f"No image candidates found by Serper for query: '{query}'")
                return []

            # --- Chuẩn hóa kết quả thành định dạng chung ---
            # Mục đích là để hàm _select_media_with_ai có thể xử lý đồng nhất
            standardized_candidates = []
            for img_data in image_results:
                # Lọc bỏ các domain không mong muốn (có thể giữ lại logic này)
                img_url = img_data.get("imageUrl")
                if not img_url: continue # Bỏ qua nếu không có URL

                blacklisted_domains = ["lookaside.fbsbx.com", "lookaside.instagram.com", "fbcdn"]
                if any(domain in img_url.lower() for domain in blacklisted_domains):
                    continue

                # Tạo dict ứng viên chuẩn hóa
                candidate = {
                    "imageUrl": img_url, # Key URL chính cho ảnh từ Serper
                    "url": img_url,      # Thêm key 'url' chung cho nhất quán (tùy chọn)
                    "title": img_data.get("title", "No Title"), # Lấy tiêu đề
                    "alt": img_data.get("title"), # Dùng title làm alt text luôn
                    "width": img_data.get("imageWidth", 0),
                    "height": img_data.get("imageHeight", 0),
                    "source": img_data.get("source", "serper") # Nguồn gốc
                    # Thêm các trường khác nếu cần thiết cho AI đánh giá
                }
                standardized_candidates.append(candidate)

            logger.info(f"Found {len(standardized_candidates)} potential image candidates from Serper (after basic filtering).")
            return standardized_candidates

        except requests.exceptions.RequestException as req_err:
            logger.error(f"Network error during Serper image search for '{query}': {req_err}")
            return []
        except json.JSONDecodeError as json_err:
            logger.error(f"Error decoding JSON response from Serper Image API: {json_err}")
            # Log thêm raw response để debug nếu cần
            # logger.debug(f"Raw Serper Response: {response.text[:500]}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during Serper image candidate search for '{query}': {e}", exc_info=True)
            return []

    def _search_and_download_image(self, query, output_path):
        """Searches for and downloads an image using the Serper.dev API for US/English results.

        Args:
            query (str): The search query.
            output_path (str): The path to save the processed image.

        Returns:
            str: The path to the successfully downloaded and processed image.

        Raises:
            Exception: If no suitable image can be found or downloaded.
        """
        if not self.serper_api_key:
            raise Exception("Serper API key is missing. Cannot search for images.")

        try:
            logger.info(f"Searching images with Serper (US/EN): '{query}'")

            # Payload for US/English search
            payload = json.dumps({
                "q": query,
                "gl": "us",  # Geo-location: United States
                "hl": "en",  # Host language: English
                "num": 20    # Request more results to increase chances of finding a good image
            })

            response = requests.post(self.serper_url, headers=self.serper_headers, data=payload, timeout=15)

            if response.status_code != 200:
                logger.error(f"Serper API error: {response.status_code}, {response.text}")
                raise Exception(f"Serper API error: {response.status_code}")

            data = response.json()
            image_results = data.get("images", [])

            if not image_results:
                logger.warning(f"No images found by Serper for query: '{query}'")
                raise Exception("No images found")

            # Define problematic domains to avoid
            blacklisted_domains = ["lookaside.fbsbx.com", "lookaside.instagram.com", "fbcdn"]
            
            # Add log to show the total number of images found before filtering
            logger.info(f"Found {len(image_results)} images from Serper API. Starting scoring process...")
                
            # Filter and score potential images based on size and aspect ratio
            potential_images = []
            #logger.info("=== Scoring all images from search results ===")
            
            for i, img_data in enumerate(image_results):
                width = img_data.get("imageWidth", 0)
                height = img_data.get("imageHeight", 0)
                url = img_data.get("imageUrl")
                
                # Skip images without URLs
                if not url:
                    #logger.debug(f"Image {i+1} skipped - No URL provided")
                    continue
                    
                # Skip known problematic domains
                if any(domain in url.lower() for domain in blacklisted_domains):
                    #logger.debug(f"Image {i+1} skipped - Blacklisted domain: {url[:80]}...")
                    continue
                
                # Filter out very small images if dimensions are provided
                if width != 0 and height != 0 and (width < 900 or height < 800):
                    #logger.debug(f"Image {i+1} skipped - Too small: {width}x{height}")
                    continue

                # Calculate score even if dimensions are not provided
                score = 0.5  # Base score for all images
                score_components = ["Base: 0.5"]
                
                if width > 0 and height > 0:
                    # Only calculate dimension-based score if dimensions are provided
                    ratio = width / height if height > 0 else 0
                    target_ratio = self.width / self.height
                    ratio_diff = abs(ratio - target_ratio)

                    # Calculate a score based on size and aspect ratio match
                    # Normalize size score relative to target video size (e.g., 1920x1080)
                    size_score = min((width * height) / (self.width * self.height * 1.5), 1.0)  # Favor larger images, cap at 1.0
                    score_components.append(f"Size: {size_score:.2f}")
                    
                    # Score higher for aspect ratios closer to the target
                    ratio_score = max(0, 1.0 - ratio_diff * 2)  # Penalize deviation from target ratio
                    score_components.append(f"Ratio: {ratio_score:.2f}")
                    
                    # Combine scores (adjust weights as needed)
                    score = (size_score * 0.6) + (ratio_score * 0.4)  # 60% size, 40% ratio
                
                # Give bonus for high-quality sources
                quality_domains = ["shutterstock", "getty", "unsplash", "pexels", "stock", "adobe"]
                domain_bonus = 0
                for domain in quality_domains:
                    if domain in url.lower():
                        domain_bonus = 0.2
                        score_components.append(f"Quality domain bonus: +0.2")
                        break
                        
                score += domain_bonus
                score = min(score, 1.0)  # Cap at 1.0

                # Log detailed scoring information
                #logger.info(f"Image {i+1}: Score={score:.2f} [{', '.join(score_components)}], Size={width}x{height}, URL={url[:80]}...")

                potential_images.append({"url": url, "score": score, "width": width, "height": height})

            if not potential_images:
                logger.warning(f"No suitable images found after filtering for query: '{query}'")
                # Fallback: use raw results if filtering removed everything
                logger.info("Using fallback method: accepting all images with valid URLs")
                potential_images = [{"url": img.get("imageUrl"), "score": 0.5, "width": img.get("imageWidth", 0), "height": img.get("imageHeight", 0)}
                                    for img in image_results if img.get("imageUrl")]
                if not potential_images:
                    raise Exception("No images with URLs found even in raw results")

            # Sort images by score, highest first
            potential_images.sort(key=lambda x: x["score"], reverse=True)
            
            # Log the sorted results
            #logger.info("=== Sorted images by score (highest first) ===")
            #for i, img in enumerate(potential_images[:5]):  # Log top 5 for brevity
            #    logger.info(f"Rank {i+1}: Score={img['score']:.2f}, Size={img['width']}x{img['height']}, URL={img['url'][:80]}...")
            
            logger.info(f"Starting download attempts from highest scored images...")

            # Attempt to download the top-ranked images
            max_attempts = min(5, len(potential_images)) # Try the best 5 images
            for i in range(max_attempts):
                selected_image = potential_images[i]
                image_url = selected_image["url"]
                logger.info(f"Attempting download {i+1}/{max_attempts} (Score: {selected_image['score']:.2f}, Size: {selected_image['width']}x{selected_image['height']}): {image_url[:70]}...")

                try:
                    # Use the dedicated download/process function
                    downloaded_path = self._download_and_process_image(image_url, output_path)
                    if downloaded_path:
                        logger.info(f"Successfully downloaded and processed image {i+1}.")
                        return downloaded_path # Return immediately on success
                except Exception as download_err:
                    logger.warning(f"Failed attempt {i+1} for {image_url}: {str(download_err)}")
                    # Don't raise here; the loop will try the next image

            # If all download attempts fail
            logger.error(f"All {max_attempts} download attempts failed for query: '{query}'")
            raise Exception(f"Failed to download a suitable image after {max_attempts} attempts")

        except Exception as e:
            logger.error(f"Error during image search/download for query '{query}': {str(e)}", exc_info=True)
            raise # Re-raise the exception for fallback mechanisms to handle

    def _download_and_process_image(self, image_url, output_path):
        """Downloads, validates, and processes (resize/crop) an image from a URL.

        Args:
            image_url (str): The URL of the image.
            output_path (str): The path to save the processed image.

        Returns:
            str: The path to the successfully processed image.

        Raises:
            Exception: If downloading, validation, or processing fails.
        """
        try:
            # Use headers to mimic a browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9', # Prioritize US English
                'Referer': 'https://www.google.com/' # Common referer
            }
            # Use stream=True to check headers before downloading full content
            response = requests.get(image_url, headers=headers, timeout=20, stream=True)
            response.raise_for_status() # Raise HTTPError for bad status codes (4xx or 5xx)

            # Check Content-Type header
            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                 # Allow common image types sometimes served with different content types
                if 'webp' in content_type or 'avif' in content_type or 'octet-stream' in content_type:
                     logger.debug(f"Content-Type is '{content_type}', proceeding as image.")
                else:
                    raise Exception(f"Invalid Content-Type: {content_type}")

            # Read the image data from the response
            image_data = response.content
            if not image_data:
                 raise Exception("Downloaded image data is empty")

            # Validate and open the image using Pillow
            try:
                image = Image.open(BytesIO(image_data))
                # Verify integrity (detects some truncated files)
                # Note: verify() can be problematic with some formats, use cautiously or remove if issues arise
                # image.verify()
                # Re-open after verify/or if verify is skipped
                image = Image.open(BytesIO(image_data))
                # Convert to RGB to ensure consistency (handles transparency, palettes)
                if image.mode != 'RGB':
                     logger.debug(f"Converting image from mode {image.mode} to RGB.")
                     image = image.convert('RGB')
            except Exception as img_err:
                raise Exception(f"Invalid or corrupted image data: {str(img_err)}")

            # Check minimum dimensions after opening
            if image.width < 300 or image.height < 200:
                raise Exception(f"Image dimensions too small: {image.width}x{image.height}")

            # Resize and crop the image to fit video dimensions
            processed_image = self._resize_image(image)

            # Save the processed image as JPEG with good quality
            processed_image.save(output_path, format="JPEG", quality=90)
            logger.debug(f"Image saved to: {output_path}")
            return output_path

        except requests.exceptions.RequestException as req_err:
             # Catch network-related errors
             raise Exception(f"Network error downloading {image_url}: {str(req_err)}")
        except Exception as e:
             # Catch any other error during the process
             # logger.error(f"Error processing image {image_url}: {str(e)}", exc_info=True) # Log details if needed
             raise Exception(f"Failed to download/process image {image_url}: {str(e)}")


    # These validation helpers are less critical now as validation is integrated into download/process
    # def _validate_image(self, image_data): ...
    # def _is_good_image_size(self, image_data): ...

    def _get_cached_or_download_image(self, query, output_path):
        """Checks cache first; if not found or invalid, searches/downloads and caches."""
        query_hash = hashlib.md5(query.encode()).hexdigest()
        cache_filename = f"{query_hash}.jpg"
        cache_path = os.path.join(self.cache_dir, cache_filename)

        if os.path.exists(cache_path):
            # Basic check for validity (e.g., file size > 0 bytes or a threshold)
            try:
                if os.path.getsize(cache_path) > 1024: # Check if file size is > 1KB
                    logger.info(f"Using cached image for query: '{query}'")
                    shutil.copy(cache_path, output_path)
                    return output_path
                else:
                    logger.warning(f"Invalid cache file found (size too small): {cache_path}. Will re-download.")
                    os.remove(cache_path) # Remove the invalid cache file
            except OSError as e:
                 logger.warning(f"Error accessing or removing cache file {cache_path}: {e}. Will re-download.")
            except Exception as e:
                 logger.warning(f"Error copying from cache {cache_path}: {e}. Will re-download.")

        # If not in cache or cache was invalid, proceed to download
        logger.info(f"Image not in cache or cache invalid for query: '{query}'. Searching and downloading.")
        try:
            downloaded_path = self._search_and_download_image(query, output_path)

            # Save the successfully downloaded image to cache
            try:
                shutil.copy(downloaded_path, cache_path)
                logger.info(f"Saved downloaded image to cache: {cache_path}")
            except Exception as e:
                logger.warning(f"Failed to save image to cache {cache_path}: {e}")

            return downloaded_path
        except Exception as e:
            # Log the error but re-raise it so the calling function knows the download failed
            logger.error(f"Failed to download image for caching (query: '{query}'): {str(e)}")
            raise # Re-raise exception for further fallback handling

    def _use_local_fallback_image(self, query, output_path):
        """Uses a fallback image from the assets/fallback_images directory based on themes."""
        fallback_base_dir = os.path.join(self.assets_dir, "fallback_images")
        if not os.path.exists(fallback_base_dir) or not os.listdir(fallback_base_dir):
            os.makedirs(fallback_base_dir, exist_ok=True)
            logger.warning(f"Fallback image directory is empty or missing: {fallback_base_dir}")
            logger.warning("Please add themed subdirectories with images (e.g., 'general_news', 'technology') to use this feature.")
            raise Exception("Local fallback directory is empty.")

        # Define English themes and associated keywords
        themes = {
            "general_news": ["news", "report", "update", "breaking", "story"],
            "technology": ["tech", "technology", "computer", "phone", "ai", "software", "internet"],
            "business": ["business", "economy", "finance", "market", "stock", "company", "money"],
            "politics": ["politics", "government", "election", "senate", "congress", "white house", "law"],
            "sports": ["sports", "game", "team", "player", "football", "basketball", "baseball"],
            "entertainment": ["entertainment", "movie", "music", "celebrity", "show", "award"],
            "health": ["health", "medical", "hospital", "doctor", "disease", "virus", "medicine"],
            "disaster": ["disaster", "weather", "storm", "fire", "flood", "earthquake", "emergency", "accident"],
            "science": ["science", "research", "space", "nature", "discovery"],
            "world_news": ["world", "international", "global", "country", "war", "diplomacy"]
        }
        best_theme = "general_news" # Default theme
        best_score = 0
        query_lower = query.lower()

        # Simple keyword matching to determine the best theme
        for theme, keywords in themes.items():
            score = sum(1 for keyword in keywords if keyword in query_lower)
            if score > best_score:
                best_score = score
                best_theme = theme
            # Prioritize if the theme name itself is in the query
            if theme.replace("_", " ") in query_lower and score == 0:
                 best_theme = theme
                 break

        theme_dir = os.path.join(fallback_base_dir, best_theme)
        logger.info(f"Selected fallback theme: {best_theme}")

        # If the specific theme directory doesn't exist or is empty, use the base fallback directory
        if not os.path.exists(theme_dir) or not os.listdir(theme_dir):
            logger.warning(f"Theme directory '{theme_dir}' not found or empty. Using base fallback directory: {fallback_base_dir}")
            theme_dir = fallback_base_dir

        # Get a list of image files from the selected directory
        image_files = glob.glob(os.path.join(theme_dir, "*.jpg")) + \
                      glob.glob(os.path.join(theme_dir, "*.jpeg")) + \
                      glob.glob(os.path.join(theme_dir, "*.png"))

        if not image_files:
            logger.error(f"No fallback images found in '{theme_dir}'. Cannot use local fallback.")
            raise Exception(f"No images in fallback directory: {theme_dir}")

        # Select a random image from the list
        selected_image_path = random.choice(image_files)
        logger.info(f"Using local fallback image: {selected_image_path}")

        # Copy and process the selected fallback image
        try:
            img = Image.open(selected_image_path)
            if img.mode != 'RGB':
                 img = img.convert('RGB') # Ensure RGB format
            processed_img = self._resize_image(img) # Resize/crop to fit video dimensions
            processed_img.save(output_path, format="JPEG", quality=85)
            return output_path
        except Exception as e:
            logger.error(f"Error processing local fallback image {selected_image_path}: {e}", exc_info=True)
            raise Exception(f"Failed to process fallback image {selected_image_path}")

    def _use_local_fallback_video(self, query):
        """
        Selects a random fallback video from the assets/fallback_videos directory.
        Does NOT process the video (trim/loop), just returns the path.

        Args:
            query (str): The original search query (currently unused, but kept for potential future thematic matching).

        Returns:
            str: Path to a randomly selected fallback video file, or None if directory is empty.
        """
        if not os.path.exists(self.fallback_video_dir) or not os.listdir(self.fallback_video_dir):
            logger.warning(f"Fallback video directory is empty or missing: {self.fallback_video_dir}")
            logger.warning("Please add video files (e.g., MP4) to this directory to use the video fallback feature.")
            return None # Không thể cung cấp fallback

        # Lấy danh sách các file video được hỗ trợ
        # Thêm các định dạng khác nếu cần (.mov, .avi, .webm)
        supported_extensions = ["*.mp4", "*.mov", "*.webm"]
        video_files = []
        for ext in supported_extensions:
            video_files.extend(glob.glob(os.path.join(self.fallback_video_dir, ext)))

        if not video_files:
            logger.error(f"No supported video files found in fallback directory: {self.fallback_video_dir}")
            return None

        # Chọn ngẫu nhiên một video
        selected_video_path = random.choice(video_files)
        logger.info(f"Using local fallback video: {os.path.basename(selected_video_path)}")

        # Chỉ trả về đường dẫn, không xử lý gì thêm ở đây
        return selected_video_path

    def _create_text_only_image(self, text_content, output_path):
        """Creates an image containing only the provided text."""
        try:
            # Generate a gradient background based on a hash of the text content
            text_hash = hashlib.md5(text_content.encode()).hexdigest()
            r1, g1, b1 = int(text_hash[0:2], 16), int(text_hash[2:4], 16), int(text_hash[4:6], 16)
            r2, g2, b2 = int(text_hash[6:8], 16), int(text_hash[8:10], 16), int(text_hash[10:12], 16)

            # Ensure colors are not too light or too dark for readability
            r1, g1, b1 = max(30, r1), max(30, g1), max(30, b1)
            r2, g2, b2 = min(220, r2), min(220, g2), min(220, b2)

            img = Image.new('RGB', (self.width, self.height))
            draw = ImageDraw.Draw(img)

            # Draw the gradient background
            for y in range(self.height):
                ratio = y / self.height
                r = int(r1 + (r2 - r1) * ratio)
                g = int(g1 + (g2 - g1) * ratio)
                b = int(b1 + (b2 - b1) * ratio)
                draw.line([(0, y), (self.width, y)], fill=(r, g, b))

            # Select font and size (adjust size based on text length)
            font_size = 45 if len(text_content) < 100 else 40
            font = self._get_font(size=font_size)
            if not font:
                 raise Exception("Cannot load any font for text image generation")

            # Wrap the text to fit within margins
            margin = 80
            wrapped_text = self._wrap_text(text_content, font, self.width - 2 * margin)

            # Calculate total text height and starting position for vertical centering
            line_height = font_size * 1.3 # Estimate line height based on font size
            total_text_height = len(wrapped_text) * line_height
            start_y = (self.height - total_text_height) / 2

            # Define text and outline colors
            text_color = (255, 255, 255) # White text
            outline_color = (0, 0, 0)    # Black outline

            # Draw each line of text with a slight outline for better readability
            for i, line in enumerate(wrapped_text):
                # Calculate x position for horizontal centering
                try:
                    # Use textbbox for more accurate width calculation (Pillow >= 8.0.0)
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_width = bbox[2] - bbox[0]
                except AttributeError:
                     # Fallback for older Pillow versions or fonts without bbox support
                    try:
                         text_width, _ = font.getsize(line)
                    except AttributeError:
                         # Rough estimation if getsize also fails
                         text_width = len(line) * (font_size * 0.6)

                x = (self.width - text_width) / 2
                y = start_y + i * line_height

                # Draw outline (draw text multiple times with slight offset)
                outline_strength = 1 # Adjust for thicker/thinner outline
                for dx in range(-outline_strength, outline_strength + 1):
                    for dy in range(-outline_strength, outline_strength + 1):
                        if dx != 0 or dy != 0: # Don't draw center for outline
                            draw.text((x + dx, y + dy), line, font=font, fill=outline_color)
                # Draw the main text on top
                draw.text((x, y), line, font=font, fill=text_color)

            img.save(output_path)
            logger.info(f"Created text-only image: {output_path}")
            return output_path
        except Exception as e:
             logger.error(f"Failed to create text-only image: {e}", exc_info=True)
             raise # Re-raise the exception

    def _create_title_card(self, title, source, project_dir):
        """Creates the introductory title card image."""
        output_path = os.path.join(project_dir, "intro_title.png")
        try:
            img = Image.new('RGB', (self.width, self.height), color=(20, 40, 80)) # Dark blue background
            draw = ImageDraw.Draw(img)
            title_font = self._get_font(size=65) # Larger font for title
            source_font = self._get_font(size=35) # Smaller font for source
            if not title_font or not source_font:
                raise Exception("Cannot load fonts required for title card")

            margin = 100
            # Wrap and draw the title, centered vertically and horizontally
            title_wrapped = self._wrap_text(title, title_font, self.width - 2 * margin)
            title_line_height = 75 # Adjust line spacing for title font
            total_title_height = len(title_wrapped) * title_line_height
            # Adjust starting y-position to center the block of text
            title_y_start = (self.height - total_title_height) / 2 - (title_line_height / 4) # Slightly higher than pure center

            for i, line in enumerate(title_wrapped):
                bbox = draw.textbbox((0, 0), line, font=title_font)
                text_width = bbox[2] - bbox[0]
                x = (self.width - text_width) / 2
                y = title_y_start + i * title_line_height
                # Draw slight shadow/outline
                draw.text((x+1, y+1), line, font=title_font, fill=(0,0,0, 128)) # Semi-transparent black
                # Draw main text
                draw.text((x, y), line, font=title_font, fill=(255, 255, 255)) # White text

            # Draw the source information at the bottom, if available
            if source:
                source_text = f"Source: {source}"
                bbox = draw.textbbox((0,0), source_text, font=source_font)
                source_width = bbox[2] - bbox[0]
                source_x = (self.width - source_width) / 2
                source_y = self.height - 80 # Position near the bottom
                # Draw slight shadow/outline
                draw.text((source_x+1, source_y+1), source_text, font=source_font, fill=(0,0,0,100))
                # Draw main source text
                draw.text((source_x, source_y), source_text, font=source_font, fill=(200, 200, 200)) # Light gray text

            img.save(output_path)
            logger.info(f"Created intro title card: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to create intro card: {e}", exc_info=True)
            # Fallback: Create a simple text image if card generation fails
            return self._create_text_only_image(f"Intro:\n{title[:100]}...", output_path)


    def _create_outro_card(self, title, source, project_dir):
        """Creates the concluding outro card image."""
        output_path = os.path.join(project_dir, "outro.png")
        try:
            img = Image.new('RGB', (self.width, self.height), color=(60, 20, 80)) # Dark purple background
            draw = ImageDraw.Draw(img)
            main_font = self._get_font(size=60) # Font for main message
            sub_font = self._get_font(size=40)  # Font for title recap
            if not main_font or not sub_font:
                raise Exception("Cannot load fonts required for outro card")

            # Draw "Thanks for watching" message, centered
            thank_you_text = "Thanks for watching"
            bbox = draw.textbbox((0,0), thank_you_text, font=main_font)
            text_width = bbox[2] - bbox[0]
            x = (self.width - text_width) / 2
            y = self.height / 2 - 100 # Position slightly above center
             # Draw slight shadow/outline
            draw.text((x+1, y+1), thank_you_text, font=main_font, fill=(0,0,0, 128))
            # Draw main text
            draw.text((x, y), thank_you_text, font=main_font, fill=(255, 255, 255)) # White text

            # Draw a shortened version of the title below the main message
            short_title = title[:80] + ('...' if len(title) > 80 else '') # Truncate if too long
            title_wrapped = self._wrap_text(short_title, sub_font, self.width - 200) # Wrap shortened title
            line_height = 50 # Line spacing for title recap
            start_y = self.height / 2 + 20 # Position below "Thanks for watching"

            for i, line in enumerate(title_wrapped):
                bbox = draw.textbbox((0,0), line, font=sub_font)
                text_width = bbox[2] - bbox[0]
                x = (self.width - text_width) / 2
                y = start_y + i * line_height
                # Draw slight shadow/outline
                draw.text((x+1, y+1), line, font=sub_font, fill=(0,0,0, 100))
                 # Draw main title recap text
                draw.text((x, y), line, font=sub_font, fill=(200, 200, 200)) # Light gray text

            img.save(output_path)
            logger.info(f"Created outro card: {output_path}")
            return output_path
        except Exception as e:
             logger.error(f"Failed to create outro card: {e}", exc_info=True)
             # Fallback: Create a simple text image
             return self._create_text_only_image("Thanks for watching!", output_path)

    def _create_chapter_title_card(self, chapter_title, output_path, chapter_number=None):
        """Creates the title card image for a specific chapter."""
        try:
            # 1. Create canvas with a distinct background color
            # Example: A medium teal color - adjust as desired
            img = Image.new('RGB', (self.width, self.height), color=(20, 80, 80))
            draw = ImageDraw.Draw(img)

            # 2. Get fonts (adjust size as needed, maybe slightly smaller than main intro)
            title_font_size = 60
            title_font = self._get_font(size=title_font_size)
            if not title_font:
                raise Exception("Cannot load font for chapter title card")

            # 3. Prepare the text to display
            display_text = chapter_title
            if chapter_number is not None:
                # Format with chapter number if provided
                display_text = f"Chapter {chapter_number}: {chapter_title}"

            # 4. Wrap text to fit within margins
            margin = 100
            wrapped_text = self._wrap_text(display_text, title_font, self.width - 2 * margin)

            # 5. Calculate vertical centering
            # Estimate line height based on font size (adjust multiplier if needed)
            line_height = title_font_size * 1.2
            total_text_height = len(wrapped_text) * line_height
            y_start = (self.height - total_text_height) / 2

            # 6. Draw text with outline/shadow for readability
            text_color = (255, 255, 255) # White text
            outline_color = (0, 0, 0)    # Black outline

            for i, line in enumerate(wrapped_text):
                # Calculate horizontal centering for each line
                try:
                    bbox = draw.textbbox((0, 0), line, font=title_font)
                    text_width = bbox[2] - bbox[0]
                except AttributeError: # Fallback for older Pillow
                    try: text_width, _ = title_font.getsize(line)
                    except AttributeError: text_width = len(line) * (title_font_size * 0.6) # Estimate
                except Exception: # General fallback
                    text_width = len(line) * (title_font_size * 0.6) # Estimate

                x = (self.width - text_width) / 2
                y = y_start + i * line_height

                # Draw outline (multiple offset draws)
                outline_strength = 1
                for dx in range(-outline_strength, outline_strength + 1):
                    for dy in range(-outline_strength, outline_strength + 1):
                        if dx != 0 or dy != 0:
                            draw.text((x + dx, y + dy), line, font=title_font, fill=outline_color)
                # Draw main text
                draw.text((x, y), line, font=title_font, fill=text_color)

            # 7. Save the image
            img.save(output_path, "PNG") # Use PNG to avoid compression artifacts on text
            chapter_info = f" (Chapter {chapter_number})" if chapter_number else ""
            logger.info(f"Created chapter title card{chapter_info}: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to create chapter card for '{chapter_title}': {e}", exc_info=True)
            # Fallback to a simple text image if card generation fails
            fallback_text = f"Chapter: {chapter_title[:100]}"
            if chapter_number:
                fallback_text = f"Chapter {chapter_number}:\n{chapter_title[:100]}"
            try:
                # Reuse existing text-only image fallback
                return self._create_text_only_image(fallback_text, output_path)
            except Exception as fallback_e:
                logger.error(f"Fallback text image generation also failed: {fallback_e}")
                return None # Return None if absolutely cannot create an image

    def _resize_image(self, image):
        """
        Resizes and crops an image to fit the target video dimensions.
        For images significantly smaller than the target size, preserves original size
        and places it on a background canvas.
        """
        try:
            target_ratio = self.width / self.height
            img_ratio = image.width / image.height
            
            # Define thresholds
            # Only resize if image dimensions are at least this percentage of target dimensions
            RESIZE_THRESHOLD = 0.5  # 50% of target dimensions
            # Minimum width/height to consider for resize operation
            MIN_WIDTH_FOR_RESIZE = int(self.width * RESIZE_THRESHOLD)
            MIN_HEIGHT_FOR_RESIZE = int(self.height * RESIZE_THRESHOLD)
            
            # Check if image is too small to resize without significant quality loss
            is_too_small = image.width < MIN_WIDTH_FOR_RESIZE or image.height < MIN_HEIGHT_FOR_RESIZE
            
            # If image is too small, place it on a background without resizing
            if is_too_small:
                logger.debug(f"Image too small ({image.width}x{image.height}) - preserving original size")
                
                # Create a blank canvas with target dimensions
                # Use a dark gray background for better visual integration
                background = Image.new('RGB', (self.width, self.height), color=(30, 30, 30))
                
                # Calculate position to center the image on the background
                x_pos = (self.width - image.width) // 2
                y_pos = (self.height - image.height) // 2
                
                # Paste the original image onto the background
                background.paste(image, (x_pos, y_pos))
                return background
                
            # For images close enough in size to the target, proceed with regular resize logic
            logger.debug(f"Image size suitable for resize ({image.width}x{image.height}) to target ({self.width}x{self.height})")
            
            # If aspect ratio is already close enough, just resize
            if abs(img_ratio - target_ratio) < 0.01:
                logger.debug(f"Resizing image with matching aspect ratio")
                return image.resize((self.width, self.height), Image.Resampling.LANCZOS)

            logger.debug(f"Cropping and resizing image to fit target ratio {target_ratio:.2f}")
            if img_ratio > target_ratio:
                # Image is wider than target (landscapeish) -> crop sides
                new_width = int(image.height * target_ratio)
                left = (image.width - new_width) // 2
                right = left + new_width
                crop_box = (left, 0, right, image.height)
                logger.debug(f"Cropping box (sides): {crop_box}")
            else:
                # Image is taller than target (portraitish) -> crop top/bottom
                new_height = int(image.width / target_ratio)
                top = (image.height - new_height) // 2
                # Simple center crop for top/bottom
                bottom = top + new_height
                crop_box = (0, top, image.width, bottom)
                logger.debug(f"Cropping box (top/bottom): {crop_box}")

            cropped_image = image.crop(crop_box)
            # Resize the cropped image to the final target dimensions
            return cropped_image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        except Exception as e:
            logger.error(f"Error resizing image: {e}", exc_info=True)
            # Re-raise the exception to signal failure in resizing
            raise

    def _create_search_query(self, scene_content, title):
        """Uses the configured LLM (via ScriptGenerator) to create an optimized search query."""

        # --- Fallback cơ bản nếu không có ScriptGenerator ---
        if not self.script_generator:
            logger.warning("ScriptGenerator not available for search query generation. Using basic fallback.")
            words = scene_content.split()[:5]
            simple_query = ' '.join(words) + " news photo"
            return simple_query[:150]
        # ----------------------------------------------------

        try:
            # Prepare prompt (giữ nguyên prompt cũ)
            prompt = f"""
            **Task:** Generate an extremely concise English image search query (target: 5-7 words, absolute max 10 words) based *only* on the visual elements described in the Scene Content below. Ignore the Video Title context unless essential for visual understanding.

            **Scene Content:** "{scene_content}"

            **CRITICAL INSTRUCTIONS:**
            1.  **Output ONLY the query text.** NO introductory phrases ("Here is the query:"), NO explanations, NO formatting (like quotes or hashtags).
            2.  **Focus on Visuals:** Extract the main nouns, actions, or descriptive adjectives that define the *look* of the scene.
            3.  **Be Concise:** Use the fewest words possible while still being descriptive. Aim for 5-7 words.
            4.  **English Only.**

            **Example Input:** "The sleek, silver electric car charged silently at the futuristic station under a twilight sky."
            **Example CORRECT Output:** silver electric car charging station twilight

            **Your turn. Input Scene:** "{scene_content}"
            **Output (Query Only):**
            """

            logger.debug(f"Calling LLM (via SG) for search query generation: {scene_content[:100]}...")
            # Gọi _call_llm_api thông qua instance đã lưu
            query_content = self.script_generator._call_llm_api(
                user_prompt=prompt,
                system_prompt="You are an expert at creating optimal image search queries for news content.",
                require_json=False, # Query chỉ là text, không cần JSON
                is_core_content_task=False, # Task phụ trợ
                request_timeout=20 # Timeout ngắn hơn cho query
            )

            if query_content:
                query = query_content.strip().replace('"', '').replace("'", '').replace('#', '').strip()
                if query and len(query) > 3 and len(query) < 100:
                    logger.info(f"LLM (via SG) generated search query: '{query}'")
                    # Bỏ phần thêm suffix "photo", để LLM tự quyết định
                    return query[:150]
                else:
                    logger.warning(f"LLM (via SG) returned invalid query: '{query}'. Falling back.")
            else:
                logger.error(f"LLM call (via SG) for query generation returned empty.")

        except Exception as e:
            logger.error(f"Error calling LLM (via SG) for query generation: {str(e)}", exc_info=True)

        # Fallback cuối cùng
        logger.warning("Falling back to basic query generation method.")
        words = scene_content.split()[:5]
        return ' '.join(words) + " news photo hd"

    def _wrap_text(self, text, font, max_width):
        """Wraps text into multiple lines to fit within a maximum width."""
        if not text: return []
        if not font: return [text] # Return original if font is missing

        lines = []
        words = text.split()
        if not words: return []

        current_line = words[0]
        for word in words[1:]:
            test_line = f"{current_line} {word}"
            try:
                # Use textbbox for accurate width calculation (Pillow >= 8.0.0)
                # Need a dummy draw object to use textbbox
                # This is slightly inefficient but required by the API
                if hasattr(ImageDraw.Draw(Image.new('RGB', (1,1))), 'textbbox'):
                    bbox = ImageDraw.Draw(Image.new('RGB', (1,1))).textbbox((0,0), test_line, font=font)
                    line_width = bbox[2] - bbox[0]
                # Fallback to getsize (older Pillow)
                elif hasattr(font, 'getsize'):
                    line_width, _ = font.getsize(test_line)
                else:
                    # Very rough estimate if font object lacks size methods
                    font_size_approx = 20 # Guess a size if font.size is unavailable
                    if hasattr(font, 'size'): font_size_approx = font.size
                    line_width = len(test_line) * (font_size_approx * 0.6)
            except Exception as e:
                 # Fallback estimation on error
                 logger.warning(f"Could not determine text width accurately for wrapping: {e}")
                 line_width = len(test_line) * 10 # Simple character count based estimation

            if line_width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word

        lines.append(current_line) # Add the last line
        return lines

    def _check_fonts(self):
        """Checks for the presence of a preferred font."""
        # Only checks and warns, does not download
        preferred_font = "Roboto-Bold.ttf" # Or your preferred font file name
        font_path = os.path.join(self.fonts_dir, preferred_font)

        if not os.path.exists(font_path):
            logger.warning(f"Preferred font '{preferred_font}' not found in '{self.fonts_dir}'.")
            logger.warning(f"Please download '{preferred_font}' (or another TTF/OTF font) and place it in the '{self.fonts_dir}' directory for best results.")
            logger.warning("The script will attempt to use system fonts or a default font, which might affect text appearance.")
        else:
             logger.info(f"Preferred font '{preferred_font}' found in '{self.fonts_dir}'.")


    def _get_font(self, size=40):
        """Gets a font object, prioritizing preferred, then system, then default."""
        preferred_font_name = "Roboto-Bold.ttf" # Your most preferred font
        preferred_font_path = os.path.join(self.fonts_dir, preferred_font_name)

        # 1. Try the preferred font from the assets directory
        if os.path.exists(preferred_font_path):
            try:
                logger.debug(f"Loading preferred font: {preferred_font_path} with size {size}")
                return ImageFont.truetype(preferred_font_path, size)
            except Exception as e:
                logger.warning(f"Could not load preferred font {preferred_font_path}: {e}")

        # 2. Try common system fonts (names or file names)
        system_fonts = [
            # Windows common
            'arial.ttf', 'arialbd.ttf', 'tahoma.ttf', 'tahomabd.ttf', 'verdana.ttf', 'verdanab.ttf', 'segoeui.ttf', 'seguisb.ttf', 'times.ttf', 'timesbd.ttf',
            # MacOS common
            'Arial.ttf', 'Helvetica.ttc', 'HelveticaNeue.ttc', 'Times New Roman',
            # Linux common (often available)
            'DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Regular.ttf', 'LiberationSans-Bold.ttf',
            'NotoSans-Regular.ttf', 'NotoSans-Bold.ttf' # Google Noto fonts are often available
        ]
        logger.debug(f"Preferred font not found or failed to load. Trying system fonts...")
        for font_attempt in system_fonts:
            try:
                # ImageFont.truetype can often find system fonts by name/filename
                logger.debug(f"Attempting to load system font '{font_attempt}' with size {size}")
                return ImageFont.truetype(font_attempt, size)
            except IOError: # Common error if font file is not found
                logger.debug(f"System font '{font_attempt}' not found.")
                continue
            except Exception as e: # Other errors (e.g., corrupted font file)
                logger.debug(f"Error trying to load system font '{font_attempt}': {e}")
                continue

        # 3. Fallback to Pillow's built-in default font
        logger.warning(f"No suitable preferred or system font found. Using Pillow's default font. Text appearance might be basic or lack support for some characters.")
        try:
            # Try loading with size argument (Pillow >= 9.0.0)
            return ImageFont.load_default(size=size)
        except TypeError:
             # Fallback for older Pillow versions
            return ImageFont.load_default()
        except Exception as e:
            # If even the default font fails (very unlikely)
            logger.error(f"CRITICAL: Failed to load even the default Pillow font: {e}")
            return None # Worst case scenario

    def _save_image_info(self, images, title, project_dir):
        """Saves detailed metadata about the generated images to a JSON file."""
        if not images:
             logger.warning("No images were generated, skipping image_info.json creation.")
             return

        image_metadata = []
        for img in images:
            img_copy = img.copy()
            # Create a relative path from the project directory base
            try:
                 # Example: project_dir = /path/to/temp/images/project_xyz
                 # img['path'] = /path/to/temp/images/project_xyz/scene_1.jpg
                 # We want to store 'scene_1.jpg'
                 rel_path = os.path.relpath(img['path'], project_dir)
                 img_copy['relative_path'] = rel_path.replace('\\', '/') # Ensure forward slashes
            except ValueError: # Handles cases like different drives on Windows
                 img_copy['relative_path'] = os.path.basename(img['path']) # Fallback to just filename

            # Optionally remove fields not needed in the JSON file
            if 'path' in img_copy: del img_copy['path'] # Remove absolute path if not needed

            image_metadata.append(img_copy)

        # Structure for the JSON output
        output_data = {
            'project_title': title,
            'creation_timestamp': time.strftime("%Y-%m-%d %H:%M:%S %Z"), # Add timezone info
            'project_folder': os.path.basename(project_dir),
            'total_items': len(image_metadata), # Renamed from total_images
            'video_dimensions': f"{self.width}x{self.height}",
            'items': image_metadata # Renamed from images for clarity (includes cards)
        }

        output_file = os.path.join(project_dir, "image_info.json")

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                # Use ensure_ascii=False for potential non-ASCII chars in content/title
                json.dump(output_data, f, ensure_ascii=False, indent=4)
            logger.info(f"Saved image metadata to: {output_file}")
        except Exception as e:
            logger.error(f"Failed to save image metadata to {output_file}: {e}", exc_info=True)


# --- Test Block ---
if __name__ == "__main__":
    print("--- Running ImageGenerator Test (English/US) ---")

    # Example English script relevant to a US audience
    test_script = {
        'title': 'Federal Reserve Announces Interest Rate Hike Amid Inflation Concerns',
        'full_script': """#SCENE 1#
        The U.S. Federal Reserve has announced another significant interest rate hike today as it continues its battle against persistent inflation.
        #SCENE 2#
        The central bank raised its benchmark federal funds rate by 75 basis points, marking the fourth consecutive increase of this magnitude.
        #SCENE 3#
        Fed Chair Jerome Powell stated that restoring price stability is essential, even if it means a period of slower economic growth and potential job losses. Stock markets reacted negatively to the news.
        #SCENE 4#
        Higher borrowing costs resulting from the rate hikes are expected to impact mortgages, car loans, and credit card interest rates for consumers across the country.
        #SCENE 5#
        Analysts predict further rate increases may be necessary in the coming months if inflation does not show clear signs of receding towards the Fed's 2% target.
        """,
        'source': 'Associated Press (AP)',
        'image_url': None, # Set to a valid URL to test source image download, or None/invalid to test without it
        'scenes': [
            {
                'number': 1,
                'content': 'The U.S. Federal Reserve has announced another significant interest rate hike today as it continues its battle against persistent inflation.'
            },
            {
                'number': 2,
                'content': 'The central bank raised its benchmark federal funds rate by 75 basis points, marking the fourth consecutive increase of this magnitude.'
            },
             {
                'number': 3,
                'content': 'Fed Chair Jerome Powell stated that restoring price stability is essential, even if it means slower economic growth. Stock markets reacted negatively.'
            },
            {
                'number': 4,
                'content': 'Higher borrowing costs will impact mortgages, car loans, and credit card interest rates for consumers.'
            },
            { # Scene for testing fallback
                 'number': 5,
                 'content': 'This is an ongoing economic situation.'
            }
        ]
    }

    # --- CHECK API KEYS ---
    if not OPENAI_API_KEY:
        print("\n*** WARNING: OPENAI_API_KEY is not configured. OpenAI keyword extraction will be skipped. ***\n")
    if not SERPER_API_KEY:
         print("\n*** WARNING: SERPER_API_KEY is not configured. Image search via Serper will fail. Ensure fallback images exist or expect text-only images. ***\n")
    # ---

    start_time = time.time()
    try:
        print("Initializing ImageGenerator...")
        generator = ImageGenerator()
        print("Generating images for the test script...")
        images_list = generator.generate_images_for_script(test_script)

        print("\n--- Image Generation Results ---")
        if images_list:
            print(f"Successfully generated {len(images_list)} images/cards.")
            project_dir = None
            for img_info in images_list:
                # Determine the base directory from the first valid path
                if not project_dir and 'path' in img_info and img_info['path']:
                     project_dir = os.path.dirname(img_info['path'])

                type_info = f"Scene {img_info['number']}" if img_info['type'] == 'scene' else img_info['type'].upper()
                query_info = f" (Query/Info: '{img_info.get('search_query', 'N/A')}')" if 'search_query' in img_info else ""
                path_info = img_info.get('path', 'Path missing')
                # Display relative path if project_dir is known
                display_path = os.path.relpath(path_info, os.path.dirname(project_dir)) if project_dir and path_info else path_info
                print(f"- {type_info}: {display_path}{query_info}")

            if project_dir:
                 print(f"\nProject files saved in directory: {project_dir}")
                 info_file = os.path.join(project_dir, "image_info.json")
                 if os.path.exists(info_file):
                      print(f"Metadata saved in: {os.path.basename(project_dir)}/image_info.json")
                 else:
                      print("Metadata file (image_info.json) was not created.")
            else:
                 print("\nCould not determine project directory (no valid image paths found).")


        else:
            print("Image generation process returned an empty list or failed.")

    except Exception as e:
        print(f"\n--- An error occurred during the test ---")
        # Log the full traceback for debugging
        logger.exception("Test execution failed")
        print(f"Error details: {str(e)}")

    end_time = time.time()
    print(f"\n--- Test finished in {end_time - start_time:.2f} seconds ---")


###  CODE TEST IMAGEN 3 ###

#!/usr/bin/env python3
"""
Test script for specifically testing the Imagen functionality in the ImageGenerator class.
Run with: python -m src.image_generator
"""

import os
import time
import logging
from io import BytesIO
from PIL import Image

# Configure logging to see detailed output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import the ImageGenerator class from your module
from src.image_generator import ImageGenerator
from config.settings import TEMP_DIR

def test_imagen_generation():
    """Test the Imagen image generation functionality specifically."""
    print("\n=== IMAGEN GENERATION TEST ===")
    
    # Initialize the ImageGenerator (this will set up the Gemini client)
    generator = ImageGenerator()
    
    # Check if Imagen is available
    if not generator.gemini_client:
        print("❌ ERROR: Gemini client not initialized. Check your API key and dependencies.")
        return False
    
    # Create a test directory for output
    test_output_dir = os.path.join(TEMP_DIR, "imagen_test")
    os.makedirs(test_output_dir, exist_ok=True)
    print(f"📁 Test images will be saved to: {test_output_dir}")
    
    # Test prompts that should be safer for Imagen (avoiding topics that trigger filters)
    test_prompts = [
        # Nature/Landscapes
        "A serene mountain landscape at sunset with vibrant colors, photorealistic style",
        
        # Abstract/Conceptual
        "An abstract digital illustration representing artificial intelligence technology with blue circuits",
        
        # Architecture
        "A modern office building with glass facade in downtown business district, professional photography style",
        
        # Food
        "A colorful arrangement of fresh fruits and vegetables on a rustic wooden table, top view photography",
        
        # Technology
        "A closeup of computer circuit board with glowing components, macro photography"
    ]
    
    success_count = 0
    
    # Test the prompt generation first
    print("\n--- Testing Imagen Prompt Generation ---")
    for i, base_prompt in enumerate(test_prompts, 1):
        print(f"\n🔍 Test {i}/{len(test_prompts)}: Generating Imagen prompt")
        
        # Generate an enhanced prompt using the _create_imagen_prompt method
        try:
            enhanced_prompt = generator._create_imagen_prompt(
                scene_content=base_prompt,
                video_title="Test Video for Imagen",
                script_style="informative"
            )
            
            if enhanced_prompt:
                print(f"✅ Successfully generated enhanced prompt:")
                print(f"   Base: \"{base_prompt}\"")
                print(f"   Enhanced: \"{enhanced_prompt[:100]}...\"")
                
                # Now test the actual image generation
                print(f"\n🖼️ Testing image generation with this prompt...")
                output_path = os.path.join(test_output_dir, f"imagen_test_{i}.jpg")
                
                # Generate the image
                image_bytes = generator._generate_image_with_imagen(prompt=enhanced_prompt)
                
                if image_bytes:
                    print(f"✅ Successfully received image bytes from Imagen API")
                    
                    # Process and save the image
                    try:
                        img = Image.open(BytesIO(image_bytes))
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        
                        # Resize/crop image to match video dimensions
                        processed_image = generator._resize_image(img)
                        
                        # Save the processed image
                        processed_image.save(output_path, format="JPEG", quality=90)
                        print(f"✅ Successfully saved image to: {output_path}")
                        success_count += 1
                    except Exception as proc_err:
                        print(f"❌ Error processing image bytes: {proc_err}")
                else:
                    print(f"❌ Failed to generate image with Imagen. Check logs for details.")
            else:
                print(f"❌ Failed to generate enhanced prompt")
        
        except Exception as e:
            print(f"❌ Error during imagen prompt/image generation: {e}")
    
    # Display final summary
    print(f"\n=== TEST RESULTS ===")
    print(f"Total test cases: {len(test_prompts)}")
    print(f"Successful generations: {success_count}")
    print(f"Success rate: {success_count/len(test_prompts)*100:.1f}%")
    
    return success_count > 0

if __name__ == "__main__":
    start_time = time.time()
    
    try:
        success = test_imagen_generation()
        if success:
            print("\n✅ IMAGEN TEST COMPLETED SUCCESSFULLY")
        else:
            print("\n⚠️ IMAGEN TEST FAILED OR PARTIALLY FAILED")
    except Exception as e:
        print(f"\n❌ TEST EXECUTION ERROR: {e}")
    
    end_time = time.time()
    print(f"\nTest completed in {end_time - start_time:.2f} seconds")