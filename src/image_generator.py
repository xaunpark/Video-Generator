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
from src.utils import safe_truncate

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
    def _generate_theme_queries(self, script: Dict, count: int, language: str): # <<< Nhận script object
        """
        Sử dụng LLM (ưu tiên gpt-4o-mini qua override) để tạo các truy vấn
        tìm kiếm/prompt AI đa dạng dựa trên nội dung script.

        Args:
            script (dict): Toàn bộ đối tượng script chứa title, scenes, full_script (nếu có).
            count (int): Số lượng ý tưởng cần tạo.
            language (str): Ngôn ngữ ('en', 'vi', ...).

        Returns:
            list: Danh sách các chuỗi query/prompt hoặc list fallback nếu lỗi.
        """
        main_title = script.get('title', 'Untitled Video')
        logger.info(f"Generating {count} theme-based visual ideas for video: '{main_title}'")

        # --- Lấy nội dung nguồn để đưa vào prompt ---
        source_material = ""
        if script.get('full_script'):
            source_material = safe_truncate(script['full_script'], 8000) # Ưu tiên full_script
            logger.debug("Using full_script (truncated) as source material for theme queries.")
        elif script.get('scenes'):
            # Ghép nối content của vài scene đầu tiên (ví dụ: 5 scenes)
            num_scenes_to_concat = 5
            concatenated_scenes = " ".join([
                scene.get('content', '') for scene in script['scenes'][:num_scenes_to_concat] if scene.get('content')
            ])
            source_material = safe_truncate(concatenated_scenes, 8000)
            logger.debug(f"Using concatenated content from first {num_scenes_to_concat} scenes (truncated) as source material.")
        else:
            # Fallback cuối cùng về title nếu không có script/scene content
            source_material = main_title
            logger.warning("No script content found, using only title for theme query generation.")
        # ---------------------------------------------

        # Ngôn ngữ hướng dẫn cho prompt
        lang_instruction = f"in {language}" if language != "vi" else "bằng tiếng Việt"

        # --- Xây dựng Prompt để yêu cầu theme queries ---
        prompt = f"""
        Analyze the provided Source Material for a video titled "{main_title}".

        Your task is to brainstorm and generate exactly {count} diverse visual ideas that represent the central themes and key concepts found in the Source Material. These ideas should be suitable either as concise image/video search queries or as descriptive prompts for an AI image generator.

        **Source Material:**
        \"\"\"
        {source_material}
        \"\"\"

        **Requirements for each visual idea:**
        - **Relevance:** Directly relate to the main themes or specific details in the Source Material.
        - **Diversity:** Each idea should represent a *different facet*, angle, metaphor, or visual style associated with the content. Avoid simple variations.
        - **Conciseness:** Keep each idea relatively short (ideally 5-15 words).
        - **Visual Focus:** Emphasize visual elements and descriptions.
        - **Language:** Generate the ideas {lang_instruction}.

        **Example (Source Material about Remote Work):**
        1. Diverse team collaborating online video call screen. (Action/Setting)
        2. Person working comfortably laptop home office cozy setting. (Setting/Mood)
        3. World map connected glowing lines symbolizing global teams. (Concept/Metaphor)
        # ... (các ví dụ khác) ...

        **Output Format:**
        Return ONLY a valid JSON object with a single key "theme_visual_ideas". The value should be a list of exactly {count} strings, each being a distinct visual idea based on the Source Material.
        {{
          "theme_visual_ideas": [
            "Visual Idea 1 based on Source Material {lang_instruction}",
            "Visual Idea 2 based on Source Material {lang_instruction}",
            // ... up to {count} items
          ]
        }}
        """
        # --- Kết thúc xây dựng Prompt ---

        # --- Gọi LLM API với override_model ---
        if self.script_generator:
            try:
                # Log rõ ràng việc sử dụng model override
                logger.info(f"Calling LLM (via ScriptGenerator) to generate {count} theme queries using specific model: gpt-4o-mini...")
                
                response_json_str = self.script_generator._call_llm_api(
                    user_prompt=prompt,
                    system_prompt="You are an assistant brainstorming diverse visual ideas based on provided text content.",
                    require_json=True,
                    is_core_content_task=False, # Task phụ trợ
                    request_timeout=90,
                    override_model="gpt-4o-mini" # <<< CHỈ ĐỊNH MODEL Ở ĐÂY
                )
                
                # Xử lý kết quả trả về
                if response_json_str:
                    parsed_data = json.loads(response_json_str)
                    queries = parsed_data.get("theme_visual_ideas")
                    # Kiểm tra cấu trúc và loại dữ liệu chặt chẽ hơn
                    if queries and isinstance(queries, list) and all(isinstance(q, str) and q.strip() for q in queries):
                        # Chỉ lấy các query hợp lệ và giới hạn số lượng bằng 'count'
                        valid_queries = [q.strip() for q in queries if q.strip()][:count]
                        logger.info(f"LLM generated {len(valid_queries)} valid theme visual ideas via ScriptGenerator (using override model).")
                        # Đảm bảo trả về đúng số lượng 'count' nếu LLM trả về nhiều hơn hoặc ít hơn (do lọc)
                        # Nếu ít hơn 'count', các bước sau sẽ xử lý việc lặp lại
                        return valid_queries
                    else:
                        logger.warning("LLM response (override model) for theme queries had invalid format or contained empty strings.")
                else:
                    logger.warning("LLM call (override model) for theme queries returned no response.")
            except Exception as e:
                # Log lỗi cụ thể khi gọi API với override model
                logger.error(f"Error calling LLM (override model 'gpt-4o-mini') for theme queries: {e}", exc_info=True)
        else:
            logger.warning("ScriptGenerator instance not available for theme query generation.")

        # --- Fallback Logic (Nếu gọi LLM thất bại hoặc không có ScriptGenerator) ---
        logger.warning("LLM failed or unavailable for theme queries. Using simple fallback based on title.")
        base_queries = [main_title]
        keywords = [word for word in main_title.lower().split() if len(word) > 3]
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

        # Đảm bảo không có query rỗng và giới hạn số lượng bằng 'count'
        unique_queries = [q for q in dict.fromkeys(base_queries) if q][:count]
        logger.info(f"Using {len(unique_queries)} fallback theme queries based on title.")
        return unique_queries

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
        You are an expert Visual Content Selector AI. Your critical task is to analyze the following list of candidate {media_type}s and select the **single best** option that matches the requirements, OR explicitly decide that **none** of the candidates are suitable enough. Your goal is to find the *most fitting* visual, even if it's not perfect.

        **Requirements & Context:**
        - Media Type Needed: {media_type.capitalize()}
        - Original Search Query: "{query}"
        """
        # Thêm ngữ cảnh scene nếu có
        if scene_content:
            prompt += f"- Scene Context/Description: \"{scene_content[:150]}...\" (Use this to judge relevance and fit)\n"

        # --- Sửa đổi cách trình bày yêu cầu thời lượng ---
        if media_type == "video" and target_duration is not None and target_duration > 0:
            # Giữ lại min/max để AI tham khảo, nhưng giảm độ "cứng" trong hướng dẫn
            min_acceptable_duration = target_duration * 0.75
            max_acceptable_duration = target_duration + 5.0
            prompt += f"- **Target Video Duration:** Aim for approximately **{target_duration:.1f} seconds**. (Reference range: {min_acceptable_duration:.1f}s - {max_acceptable_duration:.1f}s).\n"
            prompt += f"- **Duration Flexibility:** **Relevance is MOST important.** A **highly relevant** video slightly outside the reference duration range is STRONGLY preferred over a less relevant video that fits perfectly within the range. Use your judgment.\n"
        elif media_type == "video":
            prompt += "- Target Video Duration: Not specified. Focus primarily on relevance and visual quality.\n"
        # --- Kết thúc sửa đổi thời lượng ---

        # Thêm yêu cầu chung về chất lượng và tỷ lệ khung hình
        prompt += f"""- Desired Aspect Ratio: Primarily **landscape** (approx 16:9). Minor deviations acceptable if relevance is high.
        - **Selection Goal (RELEVANCE FIRST, then Secondary Factors):**
            1.  **Find the MOST RELEVANT candidate:** Assess how well the candidate's description matches the Search Query AND Scene Context. This is the **absolute top priority**.
            2.  **Partial Relevance is OK:** If no candidate is a perfect match, select the one that is *most* relevant, even if only partially, **provided** other critical factors (quality, aspect ratio) are acceptable.
            3.  **Evaluate Secondary Factors (AFTER checking relevance):**
                - Visual Quality: Must be clear and professional (avoid very low resolution like 360p unless no other option).
                - Aspect Ratio: Should be close to landscape (16:9 is ideal). Avoid clearly portrait videos.
                {' - Duration (Video Only): Check if it\'s reasonably close to the target, remembering the flexibility rule based on relevance.' if media_type == 'video' and target_duration is not None and target_duration > 0 else ''}

        **Candidate {media_type.capitalize()}s (Review these options):**
        ```json
        {candidates_json_str}
        ```

        **Your Decision Task:**
        Evaluate candidates based on the priorities above (Relevance > Quality/Ratio > Duration).
        - **SELECT:** Choose the ID of the candidate offering the best balance, strongly prioritizing relevance.
        - **REJECT ALL:** Only reject if *ALL* candidates have *very low relevance* to the query/context, OR if the *most relevant* candidate has a critical flaw (e.g., extremely poor quality, completely wrong aspect ratio, unusable duration like 1 second when 10s is needed).

        Respond ONLY with a valid JSON object following this exact structure:
        {{
          "decision": "select" | "reject_all",
          "selected_id": <integer: The 'id' number of the BEST candidate if decision is "select". Output null if "reject_all".>,
          "reasoning": "<string: Provide a **detailed** explanation.
                        - If selecting: Explain WHY it's the most relevant (mention keywords/context) AND briefly confirm secondary factors are acceptable (even if duration is slightly off).
                        - If rejecting: **Clearly state the primary reason for rejection** (e.g., 'Low Relevance for all', 'Relevant #X has critical quality issue', 'Relevant #Y has unusable duration'). Be specific (e.g., 'No candidates mentioned hiking trails', 'Candidate #2 is blurry', 'Candidate #4 duration 2s far too short for target 12s').>"
        }}

        **Output ONLY the JSON object.** No introductory text, no apologies, just the JSON.
        """

        # --- 4. Gọi API LLM thông qua ScriptGenerator ---
        try:
            logger.debug("Calling ScriptGenerator._call_openai_api_internal for media selection...")
            # Tạo headers riêng cho OpenAI từ thông tin lưu trong ImageGenerator
            openai_headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            # Tạo system prompt
            openai_system_prompt = f"You are an AI assistant. Your sole task is to analyze candidate {media_type}s based on provided metadata and context, and select the best one or reject all, responding ONLY in the specified JSON format."

            # Gọi hàm nội bộ của ScriptGenerator, truyền các tham số cụ thể cho OpenAI
            response_json_str = self.script_generator._call_openai_api_internal(
                system_prompt=openai_system_prompt,
                user_prompt=prompt,
                model_name="gpt-4o-mini",
                base_url=self.openai_base_url,
                headers=openai_headers,
                supports_json=True,
                force_json_output=True,
                max_retries=2,
                request_timeout=60
            )

            if not response_json_str:
                # Lỗi đã được log bên trong _call_openai_api_internal
                logger.error("AI Selection: Failed to get response from OpenAI API call via ScriptGenerator method.")
                return None

        except AttributeError as ae:
             # Xử lý trường hợp self.script_generator không có hàm _call_openai_api_internal (ít khả năng nhưng để phòng ngừa)
             logger.error(f"AI Selection Error: ScriptGenerator instance seems to lack the '_call_openai_api_internal' method: {ae}")
             return None
        except Exception as api_err:
            logger.error(f"AI Selection: Unexpected error calling OpenAI API via ScriptGenerator method: {api_err}", exc_info=True)
            return None

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
            
            ##################################
            ###--- CHẾ ĐỘ OVERALL_THEME_FIXED_DURATION ---###
            ##################################

            if visual_timing_mode == 'overall_theme_fixed_duration':
                # --- LOGIC CHO CHẾ ĐỘ THEME ---
                logger.info("Generating visuals based on overall theme (Optimized Collection)...")

                # --- 1. Tính toán số lượng cần thiết ---
                total_estimated_audio_duration = sum(a.get('duration', 0) for a in audio_files_info if a.get('type') == 'speech_unit')

                # ==========>>> CODE TÍNH TOÁN THỜI GIAN MỖI VISUAL fixed_visual_duration <<<==========

                DEFAULT_THEME_DURATION = 10.0 # Giá trị mặc định cơ sở
                MIN_THEME_DURATION = 5.0   # Thời lượng tối thiểu
                MAX_THEME_DURATION = 20.0  # Thời lượng tối đa

                calculated_duration = DEFAULT_THEME_DURATION # Bắt đầu với default

                if total_estimated_audio_duration > 0:
                    # Công thức tỷ lệ dựa trên căn bậc hai của audio duration
                    base_duration = math.sqrt(total_estimated_audio_duration) * 1.5 
                    calculated_duration = max(MIN_THEME_DURATION, min(MAX_THEME_DURATION, base_duration))
                    logger.debug(f"Theme Duration - Initial calculation based on audio ({total_estimated_audio_duration:.1f}s): {calculated_duration:.1f}s")

                    # (Tùy chọn) Điều chỉnh dựa trên số lượng scene gốc
                    num_scenes = len(script.get('scenes', []))
                    if num_scenes > 0:
                        avg_audio_per_scene = total_estimated_audio_duration / num_scenes
                        logger.debug(f"Theme Duration - Average audio per scene: {avg_audio_per_scene:.1f}s")
                        if avg_audio_per_scene < 8.0 and calculated_duration > 8.0:
                            adjusted_based_on_scenes = max(MIN_THEME_DURATION, calculated_duration * 0.8)
                            logger.debug(f"Theme Duration - Adjusting due to many short scenes: {calculated_duration:.1f}s -> {adjusted_based_on_scenes:.1f}s")
                            calculated_duration = adjusted_based_on_scenes

                # Sử dụng giá trị đã tính toán cuối cùng
                fixed_duration_per_visual = round(calculated_duration, 1)
                logger.info(f"Dynamically calculated fixed_visual_duration for theme mode: {fixed_duration_per_visual:.1f}s")

                # Kiểm tra lại giá trị cuối cùng trước khi tính slot
                if fixed_duration_per_visual <= 0:
                    logger.error(f"Calculated fixed_duration_per_visual ({fixed_duration_per_visual}) is invalid. Using default {DEFAULT_THEME_DURATION}s.")
                    fixed_duration_per_visual = DEFAULT_THEME_DURATION
                # --- END DYNAMIC fixed_visual_duration CALCULATION ---

                # --- Tính estimated_visual_slots dựa trên giá trị MỚI ---
                if total_estimated_audio_duration <= 0:
                    logger.warning("Audio duration is zero or negative. Using default slot count (e.g., 10).")
                    estimated_visual_slots = 10
                else:
                    # Tính lại số slot dựa trên duration đã tính toán động
                    estimated_visual_slots = math.ceil(total_estimated_audio_duration / fixed_duration_per_visual)

                logger.info(f"Estimated audio: {total_estimated_audio_duration:.2f}s => Estimated visual slots needed: {estimated_visual_slots}")
                if estimated_visual_slots <= 0:
                    logger.warning("Estimated visual slots needed is zero or less. Skipping theme visual generation.")
                    estimated_visual_slots = 0

                # ==========>>> LOGIC LẤY QUERY_COUNT Ở ĐÂY <<<==========
                # --- BEGIN DYNAMIC theme_visual_query_count CALCULATION ---
                
                # Giá trị mặc định và giới hạn
                DEFAULT_BASE_QUERY_COUNT = 7 # Số lượng tối thiểu yêu cầu LLM tạo (ngay cả khi cần ít slot)
                QUERY_COUNT_BUFFER = 3      # Yêu cầu LLM tạo dư ra bao nhiêu so với số slot cần
                MAX_ALLOWED_QUERY_COUNT = 50 # Giới hạn trên để tránh prompt quá lớn cho LLM

                # Tính toán số lượng query cần yêu cầu LLM tạo
                if estimated_visual_slots <= 0:
                    # Nếu không cần slot nào, cũng không cần tạo query
                    final_query_count = 0
                    logger.info("No visual slots needed, skipping theme query generation.")
                else:
                    # Số lượng cần = số slot + buffer, nhưng không ít hơn DEFAULT_BASE_QUERY_COUNT
                    calculated_query_count = max(DEFAULT_BASE_QUERY_COUNT, estimated_visual_slots + QUERY_COUNT_BUFFER)
                    # Giới hạn bởi MAX_ALLOWED_QUERY_COUNT
                    final_query_count = min(calculated_query_count, MAX_ALLOWED_QUERY_COUNT)
                    logger.info(f"Dynamically requesting {final_query_count} theme visual ideas from LLM (estimated slots: {estimated_visual_slots}).")

                # --- END DYNAMIC theme_visual_query_count CALCULATION ---

                # --- 2. Đặt mục tiêu thu thập và số API calls ---
                max_api_calls = 60 # Giới hạn cứng tổng thể

                # === BEGIN REVISED LOGIC (Simplified) ===
                # Mục tiêu chỉ là thu thập đủ estimated_visual_slots
                logger.info(f"Targeting collection of {estimated_visual_slots} unique visuals.")

                # Tính số API call tối đa: đủ để thử các query gốc và có một chút dự phòng
                # Ví dụ: Số lớn hơn giữa (số slot cần + 3) và số query gốc, nhưng không quá max_api_calls
                num_api_calls_to_make = min(
                    max(estimated_visual_slots + 3, final_query_count), 
                    max_api_calls
                ) 
                # Đảm bảo không gọi API nếu không cần slot
                if estimated_visual_slots <= 0:
                    num_api_calls_to_make = 0

                logger.info(f"Performing a maximum of {num_api_calls_to_make} API calls to achieve target.")

                # --- 3. Tạo/Override Theme Queries ---
                theme_queries = self._generate_theme_queries(
                    script,
                    final_query_count,
                    script.get('language', 'en')
                )
                if not theme_queries:
                    logger.warning("Failed to generate theme queries. Using title as fallback query.")
                    theme_queries = [script.get('title', 'abstract background')]
                    num_api_calls_to_make = min(num_api_calls_to_make, 3) # Giảm số call nếu fallback

                final_theme_queries = list(theme_queries) # Tạo bản sao để không ảnh hưởng list gốc
                query_source_info = "Generated by LLM" # Ghi chú nguồn query

                # --- Logic Override Query (Đầy đủ) ---
                if visual_source == "video_only" and style_strategy:
                    logger.debug("Theme Mode (Video Only): Checking for strategy query override...")
                    try:
                        query_override = style_strategy.get_video_search_query_override()
                        if query_override:
                            if isinstance(query_override, list) and query_override:
                                # Lọc bỏ các query rỗng trong list override
                                valid_override_queries = [q.strip() for q in query_override if isinstance(q, str) and q.strip()]
                                if valid_override_queries:
                                    final_theme_queries = valid_override_queries # Thay thế hoàn toàn
                                    query_source_info = f"Overridden by Strategy List ({len(final_theme_queries)} queries)"
                                    logger.info(f"Theme Mode: {query_source_info}")
                                    # Không cần điều chỉnh num_api_calls_to_make ở đây,
                                    # vòng lặp dưới sẽ tự giới hạn theo len(queries_to_process)
                                else:
                                     logger.warning("Theme Mode: Strategy query override list was empty or contained only empty strings. Using generated queries.")
                            elif isinstance(query_override, str) and query_override.strip():
                                final_theme_queries = [query_override.strip()] # Dùng string cố định
                                query_source_info = f"Overridden by Strategy String: '{final_theme_queries[0]}'"
                                logger.info(f"Theme Mode: {query_source_info}")
                                # Nếu chỉ có 1 query cố định, giới hạn số lần gọi API để tránh lặp quá nhiều
                                num_api_calls_to_make = min(num_api_calls_to_make, estimated_visual_slots + 2) # Gọi dư 2 lần phòng lỗi
                            else:
                                 logger.warning("Theme Mode: Strategy query override was invalid type or empty string. Using generated queries.")
                        else:
                             logger.debug("Theme Mode: Strategy get_video_search_query_override returned None. Using generated queries.")
                    except AttributeError:
                        logger.debug("Theme Mode: Strategy does not support get_video_search_query_override. Using generated queries.")
                    except Exception as e:
                        logger.error(f"Theme Mode: Error getting query override from strategy: {e}. Using generated queries.")
                logger.info(f"Final query source for theme mode: {query_source_info}")
                # --- Kết thúc Override Query ---

                # --- 4. Chuẩn bị Queries để xử lý ---
                queries_to_process = []
                if final_theme_queries and num_api_calls_to_make > 0 and estimated_visual_slots > 0: # Thêm check estimated_visual_slots
                    query_source_list = final_theme_queries
                    # Tính số lần lặp cần thiết để có ít nhất đủ API call
                    repeat_factor = math.ceil(num_api_calls_to_make / len(query_source_list)) if len(query_source_list) > 0 else 1
                    # Tạo list đủ dài và cắt theo num_api_calls_to_make
                    queries_to_process = (query_source_list * repeat_factor)[:num_api_calls_to_make]
                    # Xáo trộn để tránh lặp lại ngay lập tức nếu số query gốc ít
                    if len(query_source_list) < num_api_calls_to_make:
                         random.shuffle(queries_to_process)
                logger.info(f"Prepared {len(queries_to_process)} queries for API calls.")

                # --- 5. Thực hiện API calls giới hạn và thu thập visual duy nhất ---
                unique_visuals_collected = []
                collected_paths = set()
                ai_selection_enabled = VIDEO_SETTINGS.get("use_ai_for_media_selection", False)

                # --- Vòng lặp xử lý từng Query ---
                for idx, current_query in enumerate(queries_to_process):
                    # --- KIỂM TRA DỪNG SỚM NGAY ĐẦU VÒNG LẶP ---
                    if len(unique_visuals_collected) >= estimated_visual_slots:
                        logger.info(f"Collected enough unique visuals ({len(unique_visuals_collected)} >= {estimated_visual_slots}). Stopping API calls.")
                        break # Thoát khỏi vòng lặp for

                    logger.info(f"--- Processing Theme API Call {idx + 1}/{len(queries_to_process)} (VSrc: {visual_source}, Query: '{current_query[:80]}...') ---")

                    visual_path = None
                    visual_type = "unknown"
                    temp_base_filename = f"theme_call_{idx + 1}" # Base filename cho file tạm

                    # =====================================================================
                    # === LOGIC IF/ELIF/ELSE DỰA TRÊN visual_source (GỌI HÀM HELPER) ===
                    # =====================================================================

                    # --- Option 1: visual_source == "search" (Theme Mode) ---
                    if visual_source == "search":
                        logger.debug(f"Theme Call {idx+1}: Source is 'search'. Trying image acquisition chain...")

                        # a. Ảnh online
                        visual_path, visual_type = self._attempt_online_image_acquisition(
                            query=current_query, project_media_dir=project_media_dir,
                            base_filename=temp_base_filename,
                            scene_content=f"Overall theme visual for query: {current_query}" # Context cho AI
                        )

                        # b. Ảnh AI fallback
                        if visual_path is None:
                            visual_path, visual_type = self._attempt_ai_image_generation(
                                prompt_text=current_query, style_strategy=style_strategy,
                                project_media_dir=project_media_dir, base_filename=temp_base_filename
                            )

                        # c. Ảnh local fallback
                        if visual_path is None:
                            visual_path, visual_type = self._attempt_local_image_fallback(
                                query=current_query, project_media_dir=project_media_dir,
                                base_filename=temp_base_filename
                            )

                        # d. Ảnh text fallback (Bỏ qua cho theme mode để tránh làm xấu video)
                        if visual_path is None:
                            logger.warning(f"Theme Call {idx+1}: All image fallbacks (online, ai, local) failed for query '{current_query}'.")

                    # --- Option 2: visual_source == "ai" (Theme Mode) ---
                    elif visual_source == "ai":
                        logger.debug(f"Theme Call {idx+1}: Source is 'ai'. Trying AI generation first...")
                        # 1. Thử tạo ảnh AI
                        visual_path, visual_type = self._attempt_ai_image_generation(
                            prompt_text=current_query, style_strategy=style_strategy,
                            project_media_dir=project_media_dir, base_filename=temp_base_filename
                        )

                        # 2. Fallback ảnh online
                        if visual_path is None:
                            visual_path, visual_type = self._attempt_online_image_acquisition(
                                query=current_query, project_media_dir=project_media_dir,
                                base_filename=temp_base_filename,
                                scene_content=f"Overall theme visual for query: {current_query}"
                            )

                        # 3. Fallback ảnh local
                        if visual_path is None:
                            visual_path, visual_type = self._attempt_local_image_fallback(
                                query=current_query, project_media_dir=project_media_dir,
                                base_filename=temp_base_filename
                            )

                        # 4. Fallback ảnh text (Bỏ qua cho theme mode)
                        if visual_path is None:
                             logger.warning(f"Theme Call {idx+1}: Primary AI and all image fallbacks failed for query '{current_query}'.")

                    # --- Option 3: visual_source == "video_only" (Theme Mode) ---
                    elif visual_source == "video_only":
                        logger.debug(f"Theme Call {idx+1}: Source is 'video_only'.")
                        video_retry_attempted = False

                        # 1. Thử video online lần đầu
                        visual_path, visual_type = self._attempt_online_video_acquisition(
                            query=current_query,
                            scene_content=f"Overall theme visual for query: {current_query}",
                            target_duration=fixed_duration_per_visual, # Duration cố định
                            project_media_dir=project_media_dir,
                            base_filename=temp_base_filename
                        )

                        # 2. Thử retry video nếu lần đầu thất bại
                        if visual_path is None:
                            video_retry_attempted = True
                            logger.info(f"Theme Call {idx+1}: Initial online video failed. Attempting video query retry...")
                            # ----- Retry Logic -----
                            simplified_query_retry = self._simplify_video_query(current_query)
                            generic_query_retry = self._generate_generic_video_query_ai(current_query, [current_query, simplified_query_retry or ""])

                            for retry_q in [simplified_query_retry, generic_query_retry]:
                                if retry_q and retry_q.strip():
                                    logger.info(f"Theme Call {idx+1}: Retrying video with query: '{retry_q}'")
                                    path_retry, type_retry = self._attempt_online_video_acquisition(
                                        query=retry_q,
                                        scene_content=f"Overall theme visual for query: {retry_q}",
                                        target_duration=fixed_duration_per_visual,
                                        project_media_dir=project_media_dir,
                                        base_filename=f"{temp_base_filename}_retry"
                                    )
                                    if path_retry:
                                        visual_path = path_retry
                                        visual_type = type_retry
                                        current_query = retry_q # Cập nhật query thành công để lưu vào metadata
                                        logger.info(f"Theme Call {idx+1}: Video retry successful with query '{retry_q}'.")
                                        break # Thoát retry loop
                                    else:
                                        logger.info(f"Theme Call {idx+1}: Video retry failed with query '{retry_q}'.")
                            # ----- End Retry Logic -----

                        # 3. Fallback video local (CHỈ video)
                        if visual_path is None:
                            visual_path, visual_type = self._attempt_local_video_fallback(
                                query=current_query, # Dùng query gốc hoặc query retry thành công cuối cùng
                                project_media_dir=project_media_dir,
                                base_filename=temp_base_filename
                            )

                        # 4. Fallback sang IMAGE (NẾU TẤT CẢ VIDEO THẤT BẠI)
                        if visual_path is None:
                            logger.warning(f"Theme Call {idx+1}: ALL VIDEO attempts failed for query '{current_query}'. Switching to IMAGE fallback chain...")

                            # a. Ảnh AI fallback
                            logger.info(f"Theme Call {idx+1}: Trying AI Image Fallback...")
                            visual_path, visual_type = self._attempt_ai_image_generation(
                                prompt_text=current_query, # Dùng theme query làm prompt
                                style_strategy=style_strategy,
                                project_media_dir=project_media_dir,
                                base_filename=temp_base_filename # Tên file có hậu tố _ai_generated
                            )

                            # b. Ảnh online fallback
                            if visual_path is None:
                                logger.info(f"Theme Call {idx+1}: AI image failed. Trying Online Image Fallback...")
                                visual_path, visual_type = self._attempt_online_image_acquisition(
                                    query=current_query, # Dùng theme query để tìm ảnh
                                    project_media_dir=project_media_dir,
                                    base_filename=temp_base_filename, # Tên file có hậu tố _online_processed
                                    scene_content=f"Overall theme visual for query: {current_query}" # Context cho AI selection (nếu bật)
                                )

                            # c. Ảnh local fallback
                            if visual_path is None:
                                logger.info(f"Theme Call {idx+1}: Online image failed. Trying Local Image Fallback...")
                                visual_path, visual_type = self._attempt_local_image_fallback(
                                    query=current_query, # Dùng theme query để tìm theme ảnh local
                                    project_media_dir=project_media_dir,
                                    base_filename=temp_base_filename # Tên file có hậu tố _local_fallback
                                )

                            # d. Ảnh text fallback (Tùy chọn, có thể bỏ nếu không muốn text trong theme)
                            if visual_path is None:
                                logger.warning(f"Theme Call {idx+1}: All image fallbacks also failed. Trying Text Image...")
                                visual_path, visual_type = self._create_text_image_fallback(
                                    scene_content=current_query, # Hiển thị query làm text
                                    project_media_dir=project_media_dir,
                                    base_filename=temp_base_filename # Tên file có hậu tố _text_fallback
                                )

                        # 4. Fallback cuối cùng (Placeholder hoặc không có)
                        if visual_path is None:
                            logger.error(f"Theme Call {idx+1}: VIDEO ONLY FAILED for query '{current_query}'. No online/local video found.")

                    # --- Invalid visual_source ---
                    else:
                         logger.error(f"Theme Call {idx+1}: Invalid visual_source '{visual_source}'. Skipping.")
                         continue # Bỏ qua lần lặp này

                    # =========================================================
                    # === KẾT THÚC LOGIC IF/ELIF/ELSE DỰA TRÊN VISUAL SOURCE ===
                    # =========================================================

                    # --- Thêm visual tìm được vào danh sách duy nhất ---
                    if visual_path and visual_type != "unknown":
                        if visual_path not in collected_paths:
                            unique_visuals_collected.append({
                                "type": visual_type,
                                "media_type": "theme_visual", # Đánh dấu là theme visual
                                "path": visual_path,
                                "duration": fixed_duration_per_visual, # Gán duration cố định
                                "query_source": current_query # Lưu query (gốc hoặc retry thành công)
                            })
                            collected_paths.add(visual_path)
                            logger.info(f"  Collected unique theme visual #{len(unique_visuals_collected)}: {os.path.basename(visual_path)} (Type: {visual_type})")
                            
                            # --- KIỂM TRA DỪNG SỚM SAU KHI APPEND ---
                            if len(unique_visuals_collected) >= estimated_visual_slots:
                                logger.info(f"Reached required number of visuals ({estimated_visual_slots}). Stopping API calls after this successful one.")
                                break # Thoát khỏi vòng lặp for sớm                            
                        else:
                            logger.debug(f"  Skipped duplicate theme visual: {os.path.basename(visual_path)}")
                    else:
                        logger.warning(f"  FAILED to obtain any visual for theme query '{current_query[:80]}...'.")
                # --- Kết thúc vòng lặp for idx, current_query ---

                # --- 6. Kiểm tra và Xử lý Kết quả Thu thập ---
                num_unique_collected = len(unique_visuals_collected)
                logger.info(f"Finished API calls. Collected {num_unique_collected} unique visuals (Needed {estimated_visual_slots}).")

                final_visual_list_for_editor = [] # Khởi tạo danh sách cuối cùng

                if estimated_visual_slots <= 0:
                    # Trường hợp không cần visual nào (ví dụ audio quá ngắn)
                    logger.info("No theme visual slots were needed.")
                    # Không làm gì thêm, final_visual_list_for_editor sẽ rỗng

                elif num_unique_collected == 0:
                    # Trường hợp không thu thập được BẤT KỲ visual nào (kể cả fallback nếu có)
                    logger.error("CRITICAL: Failed to collect ANY unique theme visuals. VideoEditor must handle fallback.")
                    # Không thêm gì vào final_visual_list_for_editor

                elif num_unique_collected < estimated_visual_slots:
                    # Trường hợp không thu thập đủ số lượng unique cần thiết
                    logger.warning(f"Collected only {num_unique_collected} unique visuals, need {estimated_visual_slots}. Repeating collected visuals.")
                    # Bắt đầu với những gì đã có
                    final_visual_list_for_editor = list(unique_visuals_collected)
                    # Tính số lượng cần thêm
                    num_needed_more = estimated_visual_slots - num_unique_collected
                    # Sử dụng itertools.cycle để lặp lại danh sách một cách hiệu quả
                    from itertools import cycle
                    visual_cycle = cycle(unique_visuals_collected) # Lặp lại từ đầu danh sách đã có
                    for _ in range(num_needed_more):
                        item_to_repeat = next(visual_cycle)
                        # Tạo bản sao để tránh tham chiếu đến cùng một dict nhiều lần
                        final_visual_list_for_editor.append(item_to_repeat.copy())

                    # Xáo trộn nhẹ nếu muốn (tùy chọn)
                    # random.shuffle(final_visual_list_for_editor)
                    logger.info(f"Filled theme visual list to {len(final_visual_list_for_editor)} items by repeating collected ones.")

                else: # num_unique_collected >= estimated_visual_slots
                    # Đã thu thập đủ hoặc thừa (do vòng lặp dừng sớm khi >=)
                    # Chỉ lấy đúng số lượng cần thiết từ đầu danh sách unique đã thu thập
                    final_visual_list_for_editor = unique_visuals_collected[:estimated_visual_slots]
                    logger.info(f"Using the first {len(final_visual_list_for_editor)} collected unique visuals.")

                # Thêm danh sách cuối cùng (có thể rỗng nếu lỗi nghiêm trọng) vào media_items tổng
                if final_visual_list_for_editor:
                    media_items.extend(final_visual_list_for_editor)

            ##################################
            ###--- CHẾ ĐỘ SYNS_TO_AUDIO ---###
            ##################################
            elif visual_timing_mode == 'sync_to_audio':
                # --- CHẾ ĐỘ SYNC TO AUDIO ---
                logger.info("Generating visuals synced to audio segments (per scene/shot)...")
                scenes_in_script = script.get('scenes', [])
                total_scenes = len(script.get('scenes', []))

                if total_scenes == 0:
                    logger.warning("No scenes found in script for sync_to_audio mode.")
                    # Không return ở đây, để outro card vẫn được tạo
                else:
                    # --- XÁC ĐỊNH QUERIES ---
                    queries_for_scenes = [""] * total_scenes
                    query_source_type = "openai_generated"
                    fixed_query_override = None
                    if visual_source == "video_only" and style_strategy:
                        try:
                            query_override_value = style_strategy.get_video_search_query_override()
                            if query_override_value:
                                if isinstance(query_override_value, list) and query_override_value:
                                    fixed_query_override = query_override_value
                                    query_source_type = "strategy_list_override"
                                    logger.info(f"Sync Mode: Using overridden video query list ({len(fixed_query_override)} queries) from strategy.")
                                elif isinstance(query_override_value, str) and query_override_value.strip():
                                    fixed_query_override = [query_override_value.strip()]
                                    query_source_type = "strategy_string_override"
                                    logger.info(f"Sync Mode: Using overridden fixed video query string from strategy: '{fixed_query_override[0]}'")
                                else:
                                    logger.warning("Sync Mode: Strategy query override is invalid. Falling back to OpenAI query generation.")
                                    query_source_type = "openai_generated"
                        except AttributeError:
                            logger.debug("Sync Mode: Strategy does not support query override.")
                            query_source_type = "openai_generated"
                        except Exception as e:
                            logger.error(f"Sync Mode: Error getting query override: {e}.", exc_info=True)
                            query_source_type = "openai_generated"

                    if query_source_type.startswith("strategy"):
                        from itertools import cycle
                        query_cycler = cycle(fixed_query_override)
                        queries_for_scenes = [next(query_cycler) for _ in range(total_scenes)]
                        logger.info(f"Applied overridden queries cyclically.")
                    else:
                        logger.info(f"Generating individual OpenAI queries for {total_scenes} scenes...")
                        for idx_q, scene_q in enumerate(scenes_in_script):
                            content_q = scene_q.get('content', '').strip()
                            if content_q: queries_for_scenes[idx_q] = self._create_search_query(content_q, script['title'])
                            else: queries_for_scenes[idx_q] = "natural background" # Query fallback tốt hơn
                        logger.info("Finished generating OpenAI queries.")
                    # --- KẾT THÚC XÁC ĐỊNH QUERIES ---

                    # --- Vòng lặp xử lý từng scene ---
                    for i, scene in enumerate(scenes_in_script):
                        scene_number = scene.get('number', i + 1) # Đảm bảo có số thứ tự
                        scene_content = scene.get('content', '').strip()
                        search_query = queries_for_scenes[i]
                        search_query_used = search_query # Query sẽ được dùng thực tế

                        # Tên file cơ sở cho scene này
                        scene_base_filename = f"scene_{scene_number}"

                        # Khởi tạo kết quả cho scene này
                        media_path_for_scene = None
                        media_type_for_scene = "unknown"

                        # Log bắt đầu xử lý scene
                        logger.info(f"--- Processing Scene {scene_number}/{total_scenes} (VSrc: {visual_source}, Query: '{search_query}') ---")

                        # ==============================================================
                        # === LUỒNG LOGIC DỰA TRÊN VISUAL SOURCE VÀ HÀM HELPER ===
                        # ==============================================================

                        # --- OPTION 1: visual_source == "search" ---
                        if visual_source == "search":
                            logger.debug(f"Scene {scene_number}: Source is 'search'. Trying video first if preferred...")
                            attempt_video = scene.get('prefer_video', False) and VIDEO_SETTINGS.get("enable_video_clips", False)
                            video_retry_attempted = False # Cờ để tránh retry lặp lại

                            if attempt_video:
                                # 1. Thử video online lần đầu
                                media_path_for_scene, media_type_for_scene = self._attempt_online_video_acquisition(
                                    query=search_query_used, scene_content=scene_content, target_duration=default_clip_target_duration,
                                    project_media_dir=project_media_dir, base_filename=scene_base_filename )

                                # 2. Thử retry video nếu lần đầu thất bại
                                if media_path_for_scene is None:
                                    video_retry_attempted = True
                                    logger.info(f"Scene {scene_number}: Initial video failed. Attempting video query retry...")
                                    # (Logic retry query video - gọi hàm helper nếu có hoặc logic trực tiếp)
                                    # ----- Retry Logic -----
                                    simplified_query_retry = self._simplify_video_query(search_query_used) # Hoặc _basic
                                    generic_query_retry = self._generate_generic_video_query_ai(scene_content, [search_query_used, simplified_query_retry or ""])
                                    
                                    for retry_q in [simplified_query_retry, generic_query_retry]:
                                        if retry_q and retry_q.strip():
                                            logger.info(f"Scene {scene_number}: Retrying video with query: '{retry_q}'")
                                            path_retry, type_retry = self._attempt_online_video_acquisition(
                                                query=retry_q, scene_content=scene_content, target_duration=default_clip_target_duration,
                                                project_media_dir=project_media_dir, base_filename=f"{scene_base_filename}_retry" )
                                            if path_retry:
                                                media_path_for_scene = path_retry
                                                media_type_for_scene = type_retry
                                                search_query_used = retry_q # Cập nhật query thành công
                                                logger.info(f"Scene {scene_number}: Video retry successful with query '{retry_q}'.")
                                                break # Thoát vòng lặp retry
                                            else:
                                                logger.info(f"Scene {scene_number}: Video retry failed with query '{retry_q}'.")
                                    # ----- End Retry Logic -----
                            
                            # 3. Fallback sang ảnh nếu video vẫn thất bại (hoặc không thử video)
                            if media_path_for_scene is None:
                                if attempt_video: logger.info(f"Scene {scene_number}: Video attempts (initial/retry) failed. Falling back to image chain.")
                                else: logger.info(f"Scene {scene_number}: Video not preferred/enabled. Starting image chain.")
                                
                                # a. Ảnh online
                                media_path_for_scene, media_type_for_scene = self._attempt_online_image_acquisition(
                                    query=search_query_used, project_media_dir=project_media_dir,
                                    base_filename=scene_base_filename, scene_content=scene_content )

                                # b. Ảnh AI fallback
                                if media_path_for_scene is None:
                                    media_path_for_scene, media_type_for_scene = self._attempt_ai_image_generation(
                                        prompt_text=scene_content or search_query_used, style_strategy=style_strategy,
                                        project_media_dir=project_media_dir, base_filename=scene_base_filename )

                                # c. Ảnh local fallback
                                if media_path_for_scene is None:
                                    media_path_for_scene, media_type_for_scene = self._attempt_local_image_fallback(
                                        query=search_query, project_media_dir=project_media_dir,
                                        base_filename=scene_base_filename )
                                
                                # d. Ảnh text fallback
                                if media_path_for_scene is None:
                                    media_path_for_scene, media_type_for_scene = self._create_text_image_fallback(
                                        scene_content=scene_content, project_media_dir=project_media_dir,
                                        base_filename=scene_base_filename )

                        # --- OPTION 2: visual_source == "ai" ---
                        elif visual_source == "ai":
                            logger.debug(f"Scene {scene_number}: Source is 'ai'. Trying AI generation first...")
                            # 1. Thử tạo ảnh AI
                            media_path_for_scene, media_type_for_scene = self._attempt_ai_image_generation(
                                prompt_text=scene_content or search_query_used, style_strategy=style_strategy,
                                project_media_dir=project_media_dir, base_filename=scene_base_filename )

                            # 2. Fallback ảnh online
                            if media_path_for_scene is None:
                                media_path_for_scene, media_type_for_scene = self._attempt_online_image_acquisition(
                                    query=search_query, project_media_dir=project_media_dir,
                                    base_filename=scene_base_filename, scene_content=scene_content )

                            # 3. Fallback ảnh local
                            if media_path_for_scene is None:
                                media_path_for_scene, media_type_for_scene = self._attempt_local_image_fallback(
                                    query=search_query, project_media_dir=project_media_dir,
                                    base_filename=scene_base_filename )

                            # 4. Fallback ảnh text
                            if media_path_for_scene is None:
                                media_path_for_scene, media_type_for_scene = self._create_text_image_fallback(
                                    scene_content=scene_content, project_media_dir=project_media_dir,
                                    base_filename=scene_base_filename )

                        # --- OPTION 3: visual_source == "video_only" ---
                        elif visual_source == "video_only":
                            logger.debug(f"Scene {scene_number}: Source is 'video_only'.")
                            video_retry_attempted = False # Cờ

                            # 1. Thử video online lần đầu
                            media_path_for_scene, media_type_for_scene = self._attempt_online_video_acquisition(
                                query=search_query_used, scene_content=scene_content, target_duration=default_clip_target_duration,
                                project_media_dir=project_media_dir, base_filename=scene_base_filename )

                            # 2. Thử retry video nếu lần đầu thất bại
                            if media_path_for_scene is None:
                                video_retry_attempted = True
                                logger.info(f"Scene {scene_number}: Initial video failed. Attempting video query retry...")
                                # ----- Retry Logic (Giống như trong search mode) -----
                                simplified_query_retry = self._simplify_video_query(search_query_used) # Hoặc _basic
                                generic_query_retry = self._generate_generic_video_query_ai(scene_content, [search_query, simplified_query_retry or ""])
                                
                                for retry_q in [simplified_query_retry, generic_query_retry]:
                                    if retry_q and retry_q.strip():
                                        logger.info(f"Scene {scene_number}: Retrying video with query: '{retry_q}'")
                                        path_retry, type_retry = self._attempt_online_video_acquisition(
                                            query=retry_q, scene_content=scene_content, target_duration=default_clip_target_duration,
                                            project_media_dir=project_media_dir, base_filename=f"{scene_base_filename}_retry" )
                                        if path_retry:
                                            media_path_for_scene = path_retry
                                            media_type_for_scene = type_retry
                                            search_query_used = retry_q
                                            logger.info(f"Scene {scene_number}: Video retry successful with query '{retry_q}'.")
                                            break
                                        else:
                                            logger.info(f"Scene {scene_number}: Video retry failed with query '{retry_q}'.")
                                # ----- End Retry Logic -----

                            # 3. Fallback video local (CHỈ video)
                            if media_path_for_scene is None:
                                media_path_for_scene, media_type_for_scene = self._attempt_local_video_fallback(
                                    query=search_query, project_media_dir=project_media_dir,
                                    base_filename=scene_base_filename )

                            # 4. Fallback cuối cùng (Placeholder Video hoặc Không có gì)
                            if media_path_for_scene is None:
                                logger.error(f"Scene {scene_number}: VIDEO ONLY FAILED - All online (incl. retry) and local video attempts failed.")
                                # ---> TÙY CHỌN: Thêm logic gọi placeholder video ở đây <---
                                # placeholder_path = VIDEO_SETTINGS.get('placeholder_video_path')
                                # if placeholder_path and os.path.exists(placeholder_path):
                                #     dest_placeholder = os.path.join(project_media_dir, f"{scene_base_filename}_placeholder.mp4")
                                #     try:
                                #         shutil.copy2(placeholder_path, dest_placeholder)
                                #         media_path_for_scene = dest_placeholder
                                #         media_type_for_scene = "video"
                                #         logger.warning(f"Scene {scene_number}: Using generic placeholder video.")
                                #     except Exception as ph_err:
                                #         logger.error(f"Scene {scene_number}: Failed to copy placeholder video: {ph_err}")
                                # else:
                                #     logger.error(f"Scene {scene_number}: Placeholder video path not set or file missing. Scene will have no visual.")
                                # ---> Kết thúc tùy chọn placeholder <---
                                # Nếu không dùng placeholder, media_path_for_scene vẫn là None

                        # --- Invalid visual_source ---
                        else:
                            logger.error(f"Scene {scene_number}: Invalid visual_source '{visual_source}'. Skipping media generation for this scene.")
                            continue # Bỏ qua scene này

                        # === KHỐI APPEND MEDIA ITEM (Giữ nguyên logic cũ) ===
                        if media_path_for_scene and media_type_for_scene != "unknown":
                             # Lấy duration gốc/placeholder
                             media_final_duration_placeholder = 0
                             if media_type_for_scene == 'video':
                                 try:
                                     # Ưu tiên ffprobe nếu có trong VideoEditor (cần sửa lại đây nếu hàm ở chỗ khác)
                                     # Hoặc dùng moviepy như cũ
                                     with VideoFileClip(media_path_for_scene) as clip:
                                         media_final_duration_placeholder = clip.duration
                                 except Exception as e:
                                     logger.warning(f"Could not get duration for {os.path.basename(media_path_for_scene)}: {e}. Using default.")
                                     media_final_duration_placeholder = default_clip_target_duration
                             elif media_type_for_scene == 'image':
                                 media_final_duration_placeholder = default_image_duration

                             media_items.append({
                                 "type": media_type_for_scene,
                                 "media_type": "scene",
                                 "number": scene_number,
                                 "path": media_path_for_scene,
                                 "duration": media_final_duration_placeholder,
                                 "content": scene_content,
                                 "search_query": search_query_used # Lưu query đã dùng thành công
                             })
                             logger.info(f"Scene {scene_number}: Added {media_type_for_scene} media. Path: {os.path.basename(media_path_for_scene)}")
                        else:
                             logger.error(f"Scene {scene_number}: FAILED TO ADD ANY MEDIA after trying primary source and all fallback methods for content: '{scene_content[:50]}...'")
                        # ==================================================
                    # Kết thúc vòng lặp for scene
            # Kết thúc nhánh sync_to_audio                            

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

### --- KHỐI CÁC HÀM HELPER XỬ LÍ CỦA generate_images_for_script --- ###

    def _attempt_online_video_acquisition(
        self,
        query: str,
        scene_content: str,
        target_duration: float,
        project_media_dir: str, # <<< THÊM THAM SỐ NÀY
        base_filename: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Cố gắng tìm, chọn, tải và xử lý một video clip online.

        Args:
            query (str): Truy vấn tìm kiếm video.
            scene_content (str): Nội dung scene để làm ngữ cảnh cho AI.
            target_duration (float): Thời lượng mục tiêu cho clip video (giây).
            project_media_dir (str): Thư mục để lưu trữ các file media tạm thời và cuối cùng của project.
            base_filename (str): Tên file cơ sở để tạo các file tạm (ví dụ: "scene_1").

        Returns:
            Tuple[Optional[str], Optional[str]]: Trả về (đường_dẫn_file_đã_xử_lý, "video")
                                                nếu thành công, ngược lại (None, None).
        """
        logger.info(f"Attempting ONLINE VIDEO ACQUISITION for query: '{query}'")
        media_path = None
        media_type = None

        # --- 1. Kiểm tra cài đặt và Khởi tạo VideoFinder ---
        if not VIDEO_SETTINGS.get("enable_video_clips", False):
            logger.warning("Online video acquisition skipped: 'enable_video_clips' is False in settings.")
            return None, None

        if self.video_finder is None:
            logger.info("Initializing VideoClipFinder for online video search...")
            try:
                self.video_finder = VideoClipFinder()
                logger.info("VideoClipFinder initialized successfully.")
            except ImportError as ie:
                logger.error(f"Cannot import VideoClipFinder: {ie}. Disabling video clips for this run.")
                # Tạm thời tắt setting để không thử lại ở các scene sau
                VIDEO_SETTINGS["enable_video_clips"] = False
                self.video_finder = None
                return None, None
            except Exception as vf_err:
                logger.error(f"Error initializing VideoClipFinder: {vf_err}. Cannot search for online videos.")
                self.video_finder = None
                return None, None
        # --- Kết thúc kiểm tra ---

        # --- 2. Tìm ứng viên video online ---
        video_candidates = []
        try:
            logger.info(f"--> Finding online video candidates for query: '{query}'")
            video_candidates = self.video_finder.find_video_clip_candidates(query)
            logger.info(f"<-- Found {len(video_candidates)} online video candidates.")
        except Exception as cand_err:
            logger.error(f"!!! Exception during find_video_clip_candidates: {cand_err}", exc_info=True)
            video_candidates = [] # Đảm bảo list rỗng nếu lỗi

        if not video_candidates:
            logger.warning(f"No online video candidates found for query: '{query}'.")
            return None, None # Thất bại nếu không có ứng viên
        # --- Kết thúc tìm ứng viên ---

        # --- 3. Chọn URL (AI hoặc Default) ---
        selected_video_url = None
        ai_selection_enabled = VIDEO_SETTINGS.get("use_ai_for_media_selection", False)

        if ai_selection_enabled:
            logger.info("--> Attempting AI selection for video...")
            try:
                selected_video_url = self._select_media_with_ai(
                    media_type="video",
                    query=query,
                    target_duration=target_duration,
                    candidates=video_candidates,
                    scene_content=scene_content
                )
                if selected_video_url:
                    logger.info(f"<-- AI selected video URL: {selected_video_url[:80]}...")
                else:
                    logger.info("<-- AI rejected all video candidates.")
            except Exception as ai_select_err:
                logger.error(f"!!! Error during AI video selection: {ai_select_err}", exc_info=True)
                selected_video_url = None # Reset về None nếu AI lỗi
        else:
            logger.info("AI selection disabled. Picking first video candidate.")
            # Chọn ứng viên đầu tiên làm mặc định
            if video_candidates[0].get("video_url"): # Kiểm tra key tồn tại
                selected_video_url = video_candidates[0].get("video_url")
                logger.info(f"Selected first video candidate URL: {selected_video_url[:80]}...")
            else:
                logger.warning("First video candidate is missing 'video_url'. Cannot select.")
                selected_video_url = None

        if not selected_video_url:
            logger.warning("No video URL was selected (either AI rejected or default selection failed).")
            return None, None # Thất bại nếu không chọn được URL
        # --- Kết thúc chọn URL ---

        # --- 4. Tải Video ---
        downloaded_path = None
        try:
            logger.info(f"--> Attempting to download selected video: {selected_video_url[:80]}...")
            # Sử dụng query gốc để tận dụng cache của video_finder nếu có
            downloaded_path = self.video_finder._download_video(selected_video_url, query)
            if downloaded_path:
                logger.info(f"<-- Video downloaded successfully to: {downloaded_path}")
            else:
                logger.error(f"!!! Failed to download video from URL: {selected_video_url}")
                return None, None # Thất bại nếu không tải được
        except Exception as download_err:
            logger.error(f"!!! Exception during video download: {download_err}", exc_info=True)
            return None, None
        # --- Kết thúc tải video ---

        # --- 5. Xử lý Video (Resize, Crop, Duration) ---
        processed_path = None
        # Tạo đường dẫn file output cuối cùng cho clip đã xử lý
        final_processed_path = os.path.join(project_media_dir, f"{base_filename}_online_processed.mp4")
        try:
            logger.info(f"--> Processing downloaded video: {downloaded_path} -> {final_processed_path}")
            processed_path = self.video_finder._process_video_clip(
                input_path=downloaded_path,
                output_path=final_processed_path,
                process_target_duration=target_duration # <<< TRUYỀN THAM SỐ target_duration TỪ HÀM NÀY
            )
            if processed_path:
                logger.info(f"<-- Video processed successfully: {processed_path}")
                media_path = processed_path
                media_type = "video"
                # --- THÀNH CÔNG ---
                logger.info(f"ONLINE VIDEO ACQUISITION SUCCEEDED for query '{query}'. Path: {media_path}")
                return media_path, media_type
            else:
                logger.error(f"!!! Failed to process video file: {downloaded_path}")
                return None, None # Thất bại nếu xử lý lỗi
        except Exception as process_err:
            logger.error(f"!!! Exception during video processing: {process_err}", exc_info=True)
            return None, None
        # --- Kết thúc xử lý video ---

    def _attempt_local_video_fallback(
        self,
        query: str,
        project_media_dir: str, # <<< THÊM THAM SỐ NÀY
        base_filename: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Cố gắng tìm và sao chép một video fallback từ thư mục cục bộ.

        Args:
            query (str): Truy vấn tìm kiếm gốc (dùng để log hoặc tiềm năng cho thematic matching).
            project_media_dir (str): Thư mục tạm của project hiện tại để sao chép file vào.
            base_filename (str): Tên file cơ sở để tạo tên file đích duy nhất.

        Returns:
            Tuple[Optional[str], Optional[str]]: Trả về (đường_dẫn_file_đã_copy, "video")
                                                nếu thành công, ngược lại (None, None).
        """
        logger.info(f"Attempting LOCAL VIDEO FALLBACK for query: '{query}'")

        # --- 1. Tìm đường dẫn file video fallback gốc ---
        # Hàm _use_local_fallback_video đã có logic tìm file ngẫu nhiên
        # Chúng ta sẽ gọi nó để lấy đường dẫn gốc
        original_fallback_path = None
        try:
            original_fallback_path = self._use_local_fallback_video(query) # Hàm này chỉ trả về path hoặc None
            if not original_fallback_path:
                # Hàm _use_local_fallback_video đã log cảnh báo nếu thư mục rỗng hoặc không tìm thấy
                return None, None # Thất bại nếu không tìm thấy file gốc
        except Exception as find_err:
            # Bắt lỗi nếu _use_local_fallback_video có thể raise exception (ví dụ: thư mục không tồn tại)
            logger.error(f"Error trying to find local fallback video: {find_err}", exc_info=True)
            return None, None
        # --- Kết thúc tìm đường dẫn gốc ---

        # --- 2. Sao chép file vào thư mục project hiện tại ---
        # Tạo tên file đích duy nhất trong thư mục project
        # Lấy phần mở rộng từ file gốc để giữ nguyên định dạng
        _, ext = os.path.splitext(original_fallback_path)
        destination_filename = f"{base_filename}_local_fallback{ext}"
        destination_path = os.path.join(project_media_dir, destination_filename)

        try:
            logger.info(f"Copying local fallback video '{os.path.basename(original_fallback_path)}' to '{destination_path}'")
            shutil.copy2(original_fallback_path, destination_path) # copy2 giữ metadata nếu có thể

            # Kiểm tra xem file đã được copy thành công chưa
            if os.path.exists(destination_path) and os.path.getsize(destination_path) > 1000: # Kiểm tra kích thước cơ bản
                logger.info(f"LOCAL VIDEO FALLBACK SUCCEEDED. Path: {destination_path}")
                # --- THÀNH CÔNG ---
                return destination_path, "video"
            else:
                logger.error(f"Failed to copy local fallback video or resulting file is invalid: {destination_path}")
                return None, None
        except Exception as copy_err:
            logger.error(f"Error copying local fallback video from '{original_fallback_path}' to '{destination_path}': {copy_err}", exc_info=True)
            # Dọn dẹp file đích nếu việc copy bị lỗi giữa chừng
            if os.path.exists(destination_path):
                try: os.remove(destination_path)
                except: pass
            return None, None
        # --- Kết thúc sao chép ---

    def _attempt_online_image_acquisition(
            self,
            query: str,
            project_media_dir: str,
            base_filename: str,
            scene_content: Optional[str] = None
        ) -> Tuple[Optional[str], Optional[str]]:
            """
            Cố gắng tìm, chọn, tải và xử lý một ảnh online (ưu tiên Serper).
            BAO GỒM LỌC KÍCH THƯỚC TRƯỚC KHI CHỌN.
            """
            logger.info(f"Attempting ONLINE IMAGE ACQUISITION for query: '{query}'")
            media_path = None
            media_type = None
            MIN_WIDTH = 900  # Ngưỡng tối thiểu
            MIN_HEIGHT = 800 # Ngưỡng tối thiểu

            # --- 1. Tìm ứng viên ảnh online (Serper) ---
            raw_candidates = []
            try:
                logger.info(f"--> Finding online image candidates (Serper) for query: '{query}'")
                raw_candidates = self._search_image_candidates_serper(query)
                logger.info(f"<-- Found {len(raw_candidates)} raw image candidates (Serper).")
            except Exception as search_err:
                logger.error(f"!!! Exception during Serper image candidate search: {search_err}", exc_info=True)
                raw_candidates = []

            if not raw_candidates:
                logger.warning(f"No online image candidates found (Serper) for query: '{query}'.")
                return None, None

            # --- 1.5. LỌC ỨNG VIÊN THEO KÍCH THƯỚC ---
            filtered_candidates = []
            candidates_unknown_size = []
            for cand in raw_candidates:
                width = cand.get('width', 0)
                height = cand.get('height', 0)
                img_url = cand.get("imageUrl")

                if not img_url: # Bỏ qua nếu không có url
                    continue

                if width >= MIN_WIDTH and height >= MIN_HEIGHT:
                    filtered_candidates.append(cand) # Đạt chuẩn kích thước
                elif width == 0 or height == 0:
                    candidates_unknown_size.append(cand) # Kích thước không xác định
                # else: (width > 0 and height > 0 but < threshold) -> Bỏ qua

            logger.info(f"Filtered candidates: {len(filtered_candidates)} meet size criteria ({MIN_WIDTH}x{MIN_HEIGHT}). {len(candidates_unknown_size)} have unknown size.")

            # Ưu tiên các ứng viên đã lọc kích thước, nếu không có thì dùng các ứng viên không rõ kích thước
            candidates_to_consider = filtered_candidates
            if not candidates_to_consider:
                logger.warning("No candidates met minimum size criteria. Considering candidates with unknown size.")
                candidates_to_consider = candidates_unknown_size

            if not candidates_to_consider:
                logger.warning(f"No suitable image candidates (known size or unknown size) left after filtering for query: '{query}'.")
                return None, None
            # --- Kết thúc lọc ---

            # --- 2. Chọn URL (AI hoặc Default) TỪ DANH SÁCH ĐÃ LỌC/ƯU TIÊN ---
            selected_image_url = None
            ai_selection_enabled = VIDEO_SETTINGS.get("use_ai_for_media_selection", False)

            if ai_selection_enabled:
                logger.info(f"--> Attempting AI selection from {len(candidates_to_consider)} considered candidates...")
                try:
                    # *** CẢI TIẾN PROMPT AI ***
                    # Gọi hàm _select_media_with_ai với prompt đã được cải tiến (xem Bước 2B)
                    # và truyền candidates_to_consider
                    selected_image_url = self._select_media_with_ai(
                        media_type="image",
                        query=query,
                        target_duration=None,
                        candidates=candidates_to_consider, # Dùng list đã lọc/ưu tiên
                        scene_content=scene_content
                    )
                    if selected_image_url:
                        logger.info(f"<-- AI selected image URL: {selected_image_url[:80]}...")
                    else:
                        logger.info("<-- AI rejected considered candidates.")
                except Exception as ai_select_err:
                    logger.error(f"!!! Error during AI image selection: {ai_select_err}", exc_info=True)
                    selected_image_url = None
            else:
                # Chọn ứng viên đầu tiên từ danh sách đã lọc/ưu tiên
                logger.info(f"AI selection disabled. Picking first from {len(candidates_to_consider)} considered candidates.")
                if candidates_to_consider:
                    first_candidate = candidates_to_consider[0]
                    selected_image_url = first_candidate.get("imageUrl")
                    if selected_image_url:
                        img_w = first_candidate.get('width', 'N/A')
                        img_h = first_candidate.get('height', 'N/A')
                        logger.info(f"Selected first image candidate URL ({img_w}x{img_h}): {selected_image_url[:80]}...")
                    else:
                        logger.warning("First considered candidate is missing 'imageUrl'. Cannot select.")
                        selected_image_url = None
                else: # Trường hợp không còn ứng viên nào sau khi lọc (dù đã check ở trên)
                    logger.warning("No image candidates left to select from (non-AI path).")
                    selected_image_url = None


            if not selected_image_url:
                logger.warning("No image URL was selected.")
                return None, None
            # --- Kết thúc chọn URL ---

            # --- 3. Tải và Xử lý Ảnh (Không đổi) ---
            # ... (Phần này giữ nguyên) ...
            processed_path = None
            final_processed_path = os.path.join(project_media_dir, f"{base_filename}_online_processed.jpg")
            try:
                logger.info(f"--> Attempting to download and process selected image: {selected_image_url[:80]}...")
                processed_path = self._download_and_process_image(
                    image_url=selected_image_url,
                    output_path=final_processed_path
                )
                if processed_path:
                    logger.info(f"<-- Image downloaded and processed successfully: {processed_path}")
                    media_path = processed_path
                    media_type = "image"
                    logger.info(f"ONLINE IMAGE ACQUISITION SUCCEEDED for query '{query}'. Path: {media_path}")
                    return media_path, media_type
                else:
                    logger.error(f"!!! Failed to download or process image from URL: {selected_image_url}")
                    return None, None
            except Exception as proc_err:
                logger.error(f"!!! Exception during image download/processing: {proc_err}", exc_info=True)
                return None, None

    def _attempt_local_image_fallback(
        self,
        query: str,
        project_media_dir: str, # <<< THÊM THAM SỐ NÀY
        base_filename: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Cố gắng tìm và sao chép một ảnh fallback từ thư mục cục bộ assets.

        Args:
            query (str): Truy vấn tìm kiếm gốc (dùng để xác định theme).
            project_media_dir (str): Thư mục tạm của project hiện tại để sao chép ảnh vào.
            base_filename (str): Tên file cơ sở để tạo tên file đích duy nhất.

        Returns:
            Tuple[Optional[str], Optional[str]]: Trả về (đường_dẫn_file_đã_copy_và_xử_lý, "image")
                                                nếu thành công, ngược lại (None, None).
        """
        logger.info(f"Attempting LOCAL IMAGE FALLBACK for query: '{query}'")

        # Tạo đường dẫn file đích cuối cùng (sau khi xử lý)
        # Dùng .jpg vì hàm _use_local_fallback_image đã lưu ảnh thành JPEG
        destination_path = os.path.join(project_media_dir, f"{base_filename}_local_fallback.jpg")

        try:
            # --- Gọi hàm _use_local_fallback_image ---
            # Hàm này đã bao gồm logic:
            # 1. Xác định theme từ query.
            # 2. Tìm thư mục theme hoặc thư mục gốc fallback.
            # 3. Chọn ảnh ngẫu nhiên từ thư mục đó.
            # 4. Mở ảnh, convert sang RGB, resize/crop, và LƯU vào output_path (destination_path).
            # 5. Trả về output_path nếu thành công, raise Exception nếu lỗi.
            processed_fallback_path = self._use_local_fallback_image(query, destination_path)

            # Hàm _use_local_fallback_image sẽ raise Exception nếu thất bại,
            # nên nếu code chạy đến đây nghĩa là đã thành công.
            if processed_fallback_path and os.path.exists(processed_fallback_path):
                logger.info(f"LOCAL IMAGE FALLBACK SUCCEEDED. Path: {processed_fallback_path}")
                # --- THÀNH CÔNG ---
                return processed_fallback_path, "image"
            else:
                # Trường hợp hiếm hoi hàm trả về path nhưng file không tồn tại
                logger.error(f"Local fallback image processing returned path '{processed_fallback_path}' but file not found.")
                return None, None

        except FileNotFoundError as fnf_err:
            # Bắt lỗi cụ thể nếu thư mục fallback hoặc file không tìm thấy
            logger.warning(f"Local image fallback failed: {fnf_err}")
            return None, None
        except Exception as e:
            # Bắt các lỗi khác từ _use_local_fallback_image (ví dụ: không load được font, lỗi xử lý ảnh)
            logger.error(f"Error during local image fallback processing: {e}", exc_info=True)
            return None, None
        # --- Kết thúc xử lý fallback local ---

    def _attempt_ai_image_generation(
        self,
        prompt_text: str, # Dùng prompt_text thay vì scene_content để rõ ràng hơn
        style_strategy: BaseVideoStyle,
        project_media_dir: str, # <<< THÊM THAM SỐ NÀY
        base_filename: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Cố gắng tạo ảnh bằng AI (Imagen) dựa trên prompt và style.

        Args:
            prompt_text (str): Nội dung hoặc ý tưởng để tạo prompt cho AI.
            style_strategy (BaseVideoStyle): Strategy hiện tại để lấy hướng dẫn tạo prompt.
            project_media_dir (str): Thư mục tạm của project để lưu ảnh.
            base_filename (str): Tên file cơ sở (ví dụ: "scene_1").

        Returns:
            Tuple[Optional[str], Optional[str]]: Trả về (đường_dẫn_file_đã_tạo, "image")
                                                nếu thành công, ngược lại (None, None).
        """
        logger.info(f"Attempting AI IMAGE GENERATION for text: '{prompt_text[:80]}...'")
        media_path = None
        media_type = None

        # --- 1. Kiểm tra điều kiện cần thiết ---
        if not self.gemini_client:
            logger.warning("AI Image Generation skipped: Gemini client not initialized.")
            return None, None
        if not style_strategy:
            logger.error("AI Image Generation skipped: Style Strategy is missing.")
            return None, None
        # --- Kết thúc kiểm tra ---

        # --- 2. Tạo Prompt cho Imagen ---
        imagen_prompt = None
        try:
            logger.debug("--> Creating Imagen prompt...")
            # Sử dụng video title từ script (nếu có) làm context bổ sung
            video_title = self.script.get('title', '') if hasattr(self, 'script') else prompt_text[:30]
            imagen_prompt = self._create_imagen_prompt(
                scene_content=prompt_text, # Dùng prompt_text làm nội dung scene
                video_title=video_title,
                style_strategy=style_strategy
            )
            if imagen_prompt:
                logger.debug(f"<-- Imagen prompt created: '{imagen_prompt[:100]}...'")
            else:
                logger.error("!!! Failed to create Imagen prompt.")
                return None, None # Không thể tạo ảnh nếu thiếu prompt
        except Exception as prompt_err:
            logger.error(f"!!! Exception during Imagen prompt creation: {prompt_err}", exc_info=True)
            return None, None
        # --- Kết thúc tạo Prompt ---

        # --- 3. Gọi API Imagen để tạo ảnh ---
        generated_image_bytes = None
        try:
            logger.info("--> Requesting image from Imagen API...")
            generated_image_bytes = self._generate_image_with_imagen(prompt=imagen_prompt)
            if generated_image_bytes:
                logger.info("<-- Imagen API returned image bytes.")
            else:
                logger.error("!!! Imagen API returned no image bytes.")
                return None, None # Thất bại nếu API không trả về ảnh
        except Exception as api_err:
            logger.error(f"!!! Exception during Imagen API call: {api_err}", exc_info=True)
            return None, None
        # --- Kết thúc gọi API ---

        # --- 4. Xử lý và Lưu ảnh ---
        processed_path = None
        # Tạo đường dẫn file output cuối cùng cho ảnh AI
        final_ai_image_path = os.path.join(project_media_dir, f"{base_filename}_ai_generated.jpg")
        try:
            logger.debug(f"--> Processing and saving generated AI image to: {final_ai_image_path}")
            img = Image.open(BytesIO(generated_image_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB') # Đảm bảo định dạng RGB
            processed_image = self._resize_image(img) # Resize/crop
            processed_image.save(final_ai_image_path, "JPEG", quality=90) # Lưu ảnh JPEG

            # Kiểm tra file đã lưu
            if os.path.exists(final_ai_image_path) and os.path.getsize(final_ai_image_path) > 1000:
                processed_path = final_ai_image_path
                logger.info(f"<-- AI Image processed and saved successfully: {processed_path}")
                media_path = processed_path
                media_type = "image"
                # --- THÀNH CÔNG ---
                logger.info(f"AI IMAGE GENERATION SUCCEEDED for prompt text '{prompt_text[:50]}...'. Path: {media_path}")
                return media_path, media_type
            else:
                logger.error(f"!!! Failed to save processed AI image or file is invalid: {final_ai_image_path}")
                return None, None
        except Exception as proc_err:
            logger.error(f"!!! Exception during AI image processing/saving: {proc_err}", exc_info=True)
            # Dọn dẹp file nếu lỗi giữa chừng
            if os.path.exists(final_ai_image_path):
                try: os.remove(final_ai_image_path)
                except: pass
            return None, None
        # --- Kết thúc xử lý và lưu ---

    def _create_text_image_fallback(
        self,
        scene_content: str,
        project_media_dir: str, # <<< THÊM THAM SỐ NÀY
        base_filename: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Tạo ảnh chỉ chứa text làm fallback cuối cùng.

        Args:
            scene_content (str): Nội dung text để hiển thị trên ảnh.
            project_media_dir (str): Thư mục tạm của project để lưu ảnh.
            base_filename (str): Tên file cơ sở (ví dụ: "scene_1").

        Returns:
            Tuple[Optional[str], Optional[str]]: Trả về (đường_dẫn_file_đã_tạo, "image")
                                                nếu thành công, ngược lại (None, None).
        """
        logger.warning(f"Creating TEXT-ONLY IMAGE FALLBACK for content: '{scene_content[:80]}...'")
        media_path = None
        media_type = None

        # Tạo đường dẫn file output cuối cùng cho ảnh text
        # Dùng .png vì text card thường dùng PNG để tránh artifact
        final_text_image_path = os.path.join(project_media_dir, f"{base_filename}_text_fallback.png")

        try:
            # --- Gọi hàm _create_text_only_image ---
            # Hàm này đã bao gồm logic tạo nền gradient, lấy font, wrap text,
            # vẽ text với outline, và lưu file vào output_path.
            # Nó trả về output_path nếu thành công, hoặc raise Exception nếu lỗi.
            created_path = self._create_text_only_image(scene_content, final_text_image_path)

            # Kiểm tra kết quả trả về và sự tồn tại của file
            if created_path and os.path.exists(created_path) and os.path.getsize(created_path) > 500: # Kiểm tra size cơ bản
                media_path = created_path
                media_type = "image"
                # --- THÀNH CÔNG ---
                logger.info(f"TEXT-ONLY IMAGE FALLBACK SUCCEEDED. Path: {media_path}")
                return media_path, media_type
            else:
                # Trường hợp _create_text_only_image trả về None hoặc file không hợp lệ
                logger.error(f"!!! Failed to create a valid text-only image at: {final_text_image_path}")
                return None, None

        except Exception as text_err:
            # Bắt các lỗi từ _create_text_only_image (ví dụ: không load được font)
            logger.error(f"!!! CRITICAL - Error creating text-only fallback image: {text_err}", exc_info=True)
            return None, None
        # --- Kết thúc tạo ảnh text ---

### --- KẾT THÚC KHỐI CÁC HÀM HELPER XỬ LÍ CỦA generate_images_for_script --- ###

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

                blacklisted_domains = ["lookaside.fbsbx.com", "lookaside.instagram.com", "fbcdn", "medium.com", "reddit.com"]
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

    def _generate_ai_image_fallback(
        self,
        prompt_text: str,
        save_path: str,
        style_strategy: Optional[BaseVideoStyle] = None
    ) -> Optional[str]:
        """
        Tạo ảnh bằng Imagen (hoặc DALL-E) dùng `prompt_text`.
        Trả về `save_path` nếu thành công, `None` nếu lỗi.
        """
        if not self.gemini_client or not style_strategy:
            return None

        try:
            imagen_prompt = self._create_imagen_prompt(
                scene_content=prompt_text,
                video_title=self.script.get('title', prompt_text),
                style_strategy=style_strategy
            )
            if not imagen_prompt:
                return None

            img_bytes = self._generate_image_with_imagen(prompt=imagen_prompt)
            if not img_bytes:
                return None

            img = Image.open(BytesIO(img_bytes)).convert('RGB')
            processed = self._resize_image(img)
            processed.save(save_path, "JPEG", quality=90)
            return save_path
        except Exception as e:
            logger.warning(f"AI image generation failed: {e}")
            return None

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

    # === AI helper: rút gọn truy vấn video bằng GPT-4.1-nano ============
    def _simplify_video_query(self, original_query: str) -> str:
        """
        Gọi LLM GPT-4.1-nano để rút gọn query xuống ≤ 3 từ khoá chính.
        Nếu LLM trả về chuỗi rỗng hoặc giống hệt input → fallback stop-word.
        """
        if not original_query:
            return original_query

        # 1. Nếu có ScriptGenerator (khuyến khích) → dùng chung kênh gọi
        if self.script_generator:
            try:
                prompt = (
                    "You are an expert at creating concise stock-video search queries.\n"
                    "Rule: Return ONLY the 1-3 most visually important English keywords, "
                    "separated by spaces; no punctuation, no explanations.\n"
                    f"Original: {original_query}\n"
                    "Simplified:"
                )
                # Gọi hàm nội bộ do ScriptGenerator bọc sẵn
                simplified = self.script_generator._call_openai_api_internal(
                    system_prompt="You are a helpful assistant.",
                    user_prompt=prompt,
                    model_name="gpt-4.1-nano",
                    base_url=self.openai_base_url,
                    headers=self.openai_headers,
                    supports_json=False,
                    force_json_output=False,
                    max_retries=1,
                    request_timeout=10
                )
                if simplified:
                    simplified = simplified.strip().replace('"', '').replace("'", '')
                    # Đảm bảo không dài quá & khác input
                    if simplified and simplified.lower() != original_query.lower():
                        return simplified[:60]
            except Exception as e:
                logger.warning(f"AI simplify failed, fallback heuristic. Err: {e}")

        # 2. Fallback: thuật toán stop-word cũ
        return self._simplify_video_query_basic(original_query)

    ## === Tạo truy vấn CHUNG CHUNG/TỔNG QUÁT mới hoàn toàn so với query ban đầu ======
    def _generate_generic_video_query_ai(
        self,
        scene_content: str,
        tried_queries: list[str]
    ) -> str:
        """
        - scene_content  : nội dung gốc của scene (tiếng Anh / Việt tuỳ script).
        - tried_queries  : list các query đã thử (gốc + simplified) để AI loại trừ.
        Trả về tối đa 5 từ tiếng Anh mô tả bối cảnh / hành động chung.
        """
        if not scene_content:
            return ""

        # --- Tạo danh sách từ khóa cần loại trừ ---
        # Gộp tất cả query cũ lại, tách token đơn giản
        excluded_tokens = {
            tok.lower()
            for q in tried_queries
            for tok in q.split()
            if tok.isalpha() and len(tok) > 2
        }
        # Giới hạn 20 từ để prompt gọn
        excluded_list = ", ".join(list(excluded_tokens)[:20]) or "NONE"

        if self.script_generator:
            try:
                prompt = (
                    "Rewrite a stock-video search query that captures the MAIN visual action or setting of the "
                    "sentence below, without using people’s names, years or numbers.\n"
                    f"Do NOT reuse any of these words: {excluded_list}\n"
                    "• Maximum 5 English words\n"
                    "• Return ONLY the query.\n\n"
                    f"Sentence: {scene_content}\nQuery:"
                )

                generic = self.script_generator._call_openai_api_internal(
                    system_prompt="You are a helpful assistant.",
                    user_prompt=prompt,
                    model_name="gpt-4.1-nano",
                    base_url=self.openai_base_url,
                    headers=self.openai_headers,
                    supports_json=False,
                    force_json_output=False,
                    max_retries=1,
                    request_timeout=10
                )
                if generic:
                    q = generic.strip().replace('"', '').replace("'", "")
                    # Xoá bất kỳ token bị cấm còn sót
                    filtered = " ".join(
                        [t for t in q.split() if t.lower() not in excluded_tokens]
                    )
                    return filtered[:60]
            except Exception as e:
                logger.warning(f"Generic-query AI failed: {e}")

        return ""

    # === SIMPLE UTIL: Biến truy vấn dài thành ngắn hơn để tìm video ===
    def _simplify_video_query_basic(self, query: str) -> str:
        """
        Loại bỏ bớt từ chung chung/tính từ, chỉ giữ 1-3 keyword chính.
        Nếu rút gọn xong rỗng thì trả về 2 từ đầu của query gốc.
        """
        if not query:
            return query

        # 1. Bộ stop-words tuỳ chỉnh (có thể bổ sung sau)
        stop_words = {
            "daily", "weekly", "monthly", "positive", "support",
            "cheerful", "focus", "people", "person", "atmosphere",
            "great", "good", "beautiful", "nice", "very", "really"
        }

        tokens = [w for w in query.split() if w.lower() not in stop_words]
        # Giữ tối đa 3 token đầu
        simplified = " ".join(tokens[:3]).strip()

        # 2. Fallback: nếu xoá hết thì lấy 2 từ đầu query gốc
        return simplified if simplified else " ".join(query.split()[:2]).strip()

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