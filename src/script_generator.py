# src/script_generator.py
import os
import sys
import time
import json
import requests
import datetime # Đảm bảo import datetime
from dotenv import load_dotenv

from src.logger_config import setup_logger
logger = setup_logger(__name__)

from src import project_config as cfg
from src.utils import detect_language, safe_truncate, generate_project_id

try:
    from src.scene_video_detector import enhance_script_with_video_annotations
except ImportError:
    enhance_script_with_video_annotations = None
    logger.warning("Could not import scene_video_detector. Video annotation unavailable.")

from config.credentials import OPENAI_API_KEY
from config.settings import TEMP_DIR, VIDEO_SETTINGS # Import VIDEO_SETTINGS here

class ScriptGenerator:
    def __init__(self):
        self.temp_dir = TEMP_DIR
        self.api_key = OPENAI_API_KEY
        if not self.api_key:
            logger.error("API key của OpenAI không được cung cấp")
            raise ValueError("API key không hợp lệ")
        self.base_url = "https://api.openai.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        os.makedirs(self.temp_dir, exist_ok=True)

    # --- HÀM GỌI API ---
    def _call_openai_api(self, prompt, max_retries=3, request_timeout=90): # <- THÊM request_timeout vào đây
        """Gọi OpenAI API, yêu cầu JSON, có retry đơn giản."""
        payload = {
            "model": "gpt-4o-mini", # Hoặc model khác
            "messages": [
                {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"}
        }
        url = f"{self.base_url}/chat/completions"
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            try:
                # Sử dụng biến request_timeout đã truyền vào
                response = requests.post(url, headers=self.headers, json=payload, timeout=request_timeout)
                response.raise_for_status()
                data = response.json()
                if 'choices' in data and data['choices']:
                    json_string = data['choices'][0]['message']['content'].strip()
                    # Kiểm tra cơ bản
                    if json_string.startswith('{') and json_string.endswith('}'):
                        return json_string
                    else:
                        logger.warning(f"API response doesn't look like JSON (Attempt {attempt}/{max_retries}): {json_string[:100]}...")
                else:
                    logger.warning(f"Invalid API response structure (Attempt {attempt}/{max_retries}): {data}")

            # Bắt lỗi Timeout riêng biệt để log rõ ràng hơn
            except requests.exceptions.Timeout:
                logger.warning(f"OpenAI API call timed out after {request_timeout}s (Attempt {attempt}/{max_retries}). Retrying...")
            except requests.exceptions.RequestException as e:
                 logger.error(f"OpenAI API request error (Attempt {attempt}/{max_retries}): {e}")
                 if hasattr(e, 'response') and e.response is not None:
                      logger.error(f"Response status: {e.response.status_code}, text: {e.response.text[:200]}...")
                 # Không retry nếu lỗi client (4xx) trừ 429 (rate limit)
                 if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                      break
            except Exception as e:
                logger.error(f"Unexpected error calling OpenAI API (Attempt {attempt}/{max_retries}): {e}", exc_info=True)

            if attempt < max_retries:
                time.sleep(2 ** attempt) # Exponential backoff

        logger.error("Failed to get valid JSON response from OpenAI API after multiple retries.")
        return None

    # --- Bước 1 - Tạo Script với Câu Hoàn Chỉnh ---
    def _generate_initial_script_sentences(self, style_config, article=None, keyword=None, language="en"):
        """Tạo script ban đầu với các scene là các câu hoàn chỉnh."""
        logger.info("Step 1: Generating initial script with full sentences...")
        # --- Xây dựng Prompt cho Bước 1 ---
        prompt_step1 = "Create a script based on the provided context.\n"
        prompt_step1 += f"Style Requirements: Tone should be {style_config['tone']}. Follow these instructions:\n"
        for instr in style_config['instructions']:
             prompt_step1 += f"- {instr}\n"

        if article:
            prompt_step1 += f"\nARTICLE TITLE: {article.get('title', '')}\n"
            prompt_step1 += f"ARTICLE CONTENT:\n{safe_truncate(article.get('content', ''))}\n"
            prompt_step1 += "\nInstructions: Generate a script summarizing the article."
        elif keyword:
            lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"
            prompt_step1 += f"\nTOPIC: \"{keyword}\"\n"
            prompt_step1 += f"\nInstructions: Generate a script {lang_instruction} about the topic."
        else:
            return None # Không có context

        prompt_step1 += "\n\nOutput Requirements:\n"
        prompt_step1 += "- Return ONLY a valid JSON object.\n"
        prompt_step1 += "- The JSON object must have a 'title' (string) and 'initial_scenes' (list of strings).\n"
        prompt_step1 += "- Each string in 'initial_scenes' should be one or more complete, natural-sounding sentences covering a part of the topic/article.\n"
        prompt_step1 += "- Example Format:\n"
        prompt_step1 += '{\n'
        prompt_step1 += f'  "title": "{style_config["title_hint"]}",\n'
        prompt_step1 += '  "initial_scenes": [\n'
        prompt_step1 += '    "First complete sentence or two.",\n'
        prompt_step1 += '    "Next logical sentence or paragraph fragment.",\n'
        prompt_step1 += '    ...\n'
        prompt_step1 += '  ]\n'
        prompt_step1 += '}'

        # --- Gọi API cho Bước 1 ---
        response_json_str = self._call_openai_api(prompt_step1)
        if not response_json_str:
            logger.error("Step 1 Failed: No response from API for initial script generation.")
            return None

        # --- Parse và Validate kết quả Bước 1 ---
        try:
            data_step1 = json.loads(response_json_str)
            if not isinstance(data_step1, dict) or \
               "title" not in data_step1 or not isinstance(data_step1["title"], str) or \
               "initial_scenes" not in data_step1 or not isinstance(data_step1["initial_scenes"], list):
                logger.error(f"Step 1 Failed: Invalid JSON structure received: {data_step1}")
                return None
            if not data_step1["initial_scenes"]:
                 logger.error("Step 1 Failed: 'initial_scenes' list is empty.")
                 return None

            logger.info(f"Step 1 Success: Generated {len(data_step1['initial_scenes'])} initial sentence-based scenes.")
            return data_step1
        except json.JSONDecodeError as e:
            logger.error(f"Step 1 Failed: Could not decode JSON response: {e}")
            logger.debug(f"Received content: {response_json_str}")
            return None
        except Exception as e:
             logger.error(f"Step 1 Failed: Unexpected error parsing result: {e}", exc_info=True)
             return None

    # --- Bước 2 - Chia Câu thành Shots ---
    def _breakdown_sentence_into_shots(self, sentence_text, target_style_tone):
        """Yêu cầu OpenAI chia một câu/đoạn văn thành các shots ngắn."""
        logger.debug(f"Step 2: Breaking down sentence: '{sentence_text[:100]}...'")
        # --- Xây dựng Prompt cho Bước 2 ---
        prompt_step2 = f"""
        Break down the following text into short visual "shots" for an engaging video.

        🧠 GOAL:
        - Create a dynamic and visual video experience, but do not over-fragment the content.
        - Only split a scene into multiple shots **if it contains multiple visual elements, ideas, or clauses**.
        - If the text is already short (under 12 words), expresses one clear idea, and is easily representable by one image or video → **DO NOT split it**.

        🔍 WHEN TO SPLIT:
        - The sentence contains multiple distinct objects, actions, or concepts.
        - There are natural pauses (commas, conjunctions).
        - Multiple visual elements are mentioned that would be hard to capture in a single illustration.

        ⛔ WHEN NOT TO SPLIT:
        - The sentence is already short (under ~12 words).
        - It conveys a single, clear, visualizable idea.
        - It has no major punctuation or clause boundaries.

        💡 OUTPUT FORMAT:
        Return a JSON object like:
        {{
        "shots": [
            "Shot 1 text",
            "Shot 2 text",
            ...
        ]
        }}

        📘 EXAMPLES:

        Example 1:
        Input: "The sun rises over the quiet hills."
        Output:
        {{ "shots": ["The sun rises over the quiet hills."] }}

        Example 2:
        Input: "They grow barley, wheat, dates, lotus, and apples."
        Output:
        {{ "shots": ["They grow barley and wheat,", "dates and lotus,", "and apples."] }}

        Now break down this scene:
        "{sentence_text}"
        """

        # --- Gọi API cho Bước 2 ---
        response_json_str = self._call_openai_api(prompt_step2, request_timeout=30) # Timeout ngắn hơn cho task này
        if not response_json_str:
            logger.warning(f"Step 2 Failed: No response from API for breaking down sentence.")
            return None # Trả về None nếu không breakdown được

        # --- Parse và Validate kết quả Bước 2 ---
        try:
            data_step2 = json.loads(response_json_str)
            if not isinstance(data_step2, dict) or \
               "shots" not in data_step2 or not isinstance(data_step2["shots"], list) or \
               not data_step2["shots"]: # Phải có ít nhất 1 shot
                logger.warning(f"Step 2 Failed: Invalid JSON structure or empty shots list received: {data_step2}")
                return None
            # Kiểm tra xem các phần tử có phải string không
            if not all(isinstance(s, str) for s in data_step2["shots"]):
                 logger.warning(f"Step 2 Failed: Not all items in 'shots' are strings: {data_step2['shots']}")
                 return None

            logger.debug(f"Step 2 Success: Broke sentence into {len(data_step2['shots'])} shots.")
            return data_step2["shots"] # Chỉ trả về list các strings
        except json.JSONDecodeError as e:
            logger.warning(f"Step 2 Failed: Could not decode JSON response: {e}")
            logger.debug(f"Received content: {response_json_str}")
            return None
        except Exception as e:
            logger.warning(f"Step 2 Failed: Unexpected error parsing result: {e}", exc_info=True)
            return None

    # --- HÀM CHÍNH: generate_script (Sử dụng 2 bước) ---
    def generate_script(self, article, style="informative", language=None):
        """
        Tạo kịch bản sử dụng quy trình 2 bước: câu -> shots.
        """
        project_id = generate_project_id(article.get('title', ''))
        logger.info(f"Generating script for article '{article.get('title', '')[:50]}...' (Style: {style})")

        # Lấy cấu hình style
        if style not in cfg.style_configs:
            logger.warning(f"Unknown style '{style}', defaulting to 'informative'.")
            style = "informative"
        style_config = cfg.style_configs[style]
        language = language or detect_language(article.get('content', ''))

        # --- Bước 1: Tạo script với câu hoàn chỉnh ---
        initial_script_data = self._generate_initial_script_sentences(
            style_config=style_config,
            article=article,
            language=language
        )
        if not initial_script_data:
            return None # Lỗi đã được log bên trong hàm con

        final_title = initial_script_data["title"]
        initial_sentences = initial_script_data["initial_scenes"]

        # --- Bước 2: Chia từng câu thành shots và xây dựng cấu trúc cuối cùng ---
        final_scenes = [] # Danh sách các shots cuối cùng
        final_speech_units = [] # Danh sách các speech units (tương ứng câu gốc)
        global_shot_number = 1
        speech_unit_number = 1

        logger.info("Step 2: Breaking down sentences into visual shots...")
        for sentence in initial_sentences:
            if not sentence.strip(): continue # Bỏ qua câu rỗng

            # Gọi API để chia câu này thành shots
            shots_for_sentence = self._breakdown_sentence_into_shots(sentence, style_config['tone'])

            if shots_for_sentence:
                shot_numbers_for_unit = []
                # Thêm các shots vào danh sách cuối cùng với số thứ tự toàn cục
                for shot_content in shots_for_sentence:
                    final_scenes.append({
                        "number": global_shot_number,
                        "content": shot_content.strip() # Đảm bảo strip
                    })
                    shot_numbers_for_unit.append(global_shot_number)
                    global_shot_number += 1

                # Tạo speech unit tương ứng với câu gốc
                final_speech_units.append({
                    "unit_number": speech_unit_number,
                    "text": sentence.strip(), # Giữ nguyên text của câu gốc
                    "scene_numbers": shot_numbers_for_unit
                })
                speech_unit_number += 1
            else:
                # Nếu không chia được câu -> xem câu đó như 1 shot duy nhất (Fallback)
                logger.warning(f"Could not break down sentence, using the full sentence as a single shot: '{sentence[:50]}...'")
                final_scenes.append({
                    "number": global_shot_number,
                    "content": sentence.strip()
                })
                final_speech_units.append({
                    "unit_number": speech_unit_number,
                    "text": sentence.strip(),
                    "scene_numbers": [global_shot_number]
                })
                global_shot_number += 1
                speech_unit_number += 1


        # --- Kiểm tra kết quả cuối cùng ---
        if not final_scenes or not final_speech_units:
            logger.error("Script generation failed: No valid scenes or speech units were created after breakdown.")
            return None

        logger.info(f"Script generation complete: {len(final_scenes)} shots, {len(final_speech_units)} speech units.")

        # --- Tạo đối tượng script cuối cùng ---
        script_result = {
            "project_id": project_id,
            "title": final_title,
            "scenes": final_scenes,           # Danh sách shots ngắn
            "speech_units": final_speech_units, # Speech units là các câu gốc
            "source": article.get('source', 'Unknown'),
            "url": article.get('url', ''),
            "style": style,
            "language": language,
            "is_ai_generated": False,
             "creation_timestamp": datetime.datetime.now().isoformat()
        }

        # --- Gọi phân tích video (Enhance Script - logic giữ nguyên) ---
        # Logic này hoạt động trên `scenes` (shots)
        enhanced_script = script_result
        if enhance_script_with_video_annotations and VIDEO_SETTINGS.get("enable_video_clips", False):
             try:
                 logger.info(f"Analyzing {len(script_result['scenes'])} shots for video suitability...")
                 enhanced_script = enhance_script_with_video_annotations(script_result.copy())
                 video_shots = sum(1 for shot in enhanced_script.get('scenes', []) if shot.get('prefer_video', False))
                 logger.info(f"Video analysis result: {video_shots}/{len(script_result['scenes'])} shots marked for video.")
             except Exception as e:
                 logger.error(f"Error during video analysis: {str(e)}", exc_info=True)
                 enhanced_script = script_result # Fallback to original if analysis fails
        elif not enhance_script_with_video_annotations:
            logger.warning("Skipping video shot analysis (detector module missing).")
        else:
            logger.info("Video clip analysis is disabled in settings.")
            for scene in enhanced_script.get('scenes', []):
                scene['prefer_video'] = False

        return enhanced_script

    # --- Hàm generate_script_from_keyword (cần được sửa tương tự) ---
    def generate_script_from_keyword(self, keyword, style="informative", language=None):
        """
        Tạo kịch bản từ từ khóa sử dụng quy trình 2 bước.
        """
        project_id = generate_project_id(keyword)
        logger.info(f"Generating script for keyword '{keyword}' (Style: {style})")

        if style not in cfg.style_configs:
            logger.warning(f"Unknown style '{style}', defaulting to 'informative'.")
            style = "informative"
        style_config = cfg.style_configs[style]
        language = language or detect_language(keyword)

        # --- Bước 1: Tạo script với câu hoàn chỉnh ---
        initial_script_data = self._generate_initial_script_sentences(
            style_config=style_config,
            keyword=keyword, # Truyền keyword thay vì article
            language=language
        )
        if not initial_script_data:
            return None

        final_title = initial_script_data["title"]
        initial_sentences = initial_script_data["initial_scenes"]

        # --- Bước 2: Chia từng câu thành shots ---
        final_scenes = []
        final_speech_units = []
        global_shot_number = 1
        speech_unit_number = 1

        logger.info("Step 2: Breaking down generated sentences into visual shots...")
        for sentence in initial_sentences:
            # ... (Copy logic chia câu từ hàm generate_script) ...
            if not sentence.strip(): continue
            shots_for_sentence = self._breakdown_sentence_into_shots(sentence, style_config['tone'])
            if shots_for_sentence:
                 shot_numbers_for_unit = []
                 for shot_content in shots_for_sentence:
                      final_scenes.append({"number": global_shot_number, "content": shot_content.strip()})
                      shot_numbers_for_unit.append(global_shot_number)
                      global_shot_number += 1
                 final_speech_units.append({"unit_number": speech_unit_number, "text": sentence.strip(), "scene_numbers": shot_numbers_for_unit})
                 speech_unit_number += 1
            else:
                 logger.warning(f"Could not break down sentence (keyword), using full sentence as shot: '{sentence[:50]}...'")
                 final_scenes.append({"number": global_shot_number, "content": sentence.strip()})
                 final_speech_units.append({"unit_number": speech_unit_number, "text": sentence.strip(), "scene_numbers": [global_shot_number]})
                 global_shot_number += 1
                 speech_unit_number += 1

        if not final_scenes or not final_speech_units:
            logger.error("Script generation failed (keyword): No valid scenes or speech units created.")
            return None

        logger.info(f"Script generation complete (keyword): {len(final_scenes)} shots, {len(final_speech_units)} speech units.")

        # --- Tạo đối tượng script cuối cùng ---
        script_result = {
            "project_id": project_id,
            "title": final_title,
            "scenes": final_scenes,
            "speech_units": final_speech_units,
            "source": "AI Generated",
            "url": f"keyword://{keyword}",
            "style": style,
            "language": language,
            "keyword": keyword,
            "is_ai_generated": True,
            "creation_timestamp": datetime.datetime.now().isoformat()
        }

        # --- Gọi phân tích video (Enhance Script - logic giữ nguyên) ---
        enhanced_script = script_result
        # ... (Copy logic gọi enhance_script_with_video_annotations từ generate_script) ...
        if enhance_script_with_video_annotations and VIDEO_SETTINGS.get("enable_video_clips", False):
             try:
                 logger.info(f"Analyzing {len(script_result['scenes'])} shots for video suitability (keyword)...")
                 enhanced_script = enhance_script_with_video_annotations(script_result.copy())
                 video_shots = sum(1 for shot in enhanced_script.get('scenes', []) if shot.get('prefer_video', False))
                 logger.info(f"Video analysis result (keyword): {video_shots}/{len(script_result['scenes'])} shots marked for video.")
             except Exception as e:
                 logger.error(f"Error during video analysis (keyword): {str(e)}", exc_info=True)
                 enhanced_script = script_result
        elif not enhance_script_with_video_annotations:
             logger.warning("Skipping video shot analysis (detector module missing).")
        else:
            logger.info("Video clip analysis is disabled in settings.")
            for scene in enhanced_script.get('scenes', []):
                 scene['prefer_video'] = False

        return enhanced_script

    def _call_openai_api(self, prompt, max_retries=3, request_timeout=90):
        """Gọi OpenAI API, yêu cầu JSON, có retry đơn giản."""
        payload = {
            "model": "gpt-4o-mini", # Hoặc model khác
            "messages": [
                # Sửa system prompt để phù hợp hơn với việc chỉ trả JSON
                {"role": "system", "content": "You are a helpful assistant designed to output JSON. Respond ONLY with the valid JSON object requested, without any introductory text, explanations, or markdown formatting."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"}
        }
        url = f"{self.base_url}/chat/completions"
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            try:
                logger.debug(f"Calling OpenAI API (Attempt {attempt}/{max_retries}, Timeout: {request_timeout}s)...")
                # Sử dụng biến request_timeout đã truyền vào thay vì giá trị cứng
                response = requests.post(url, headers=self.headers, json=payload, timeout=request_timeout)
                response.raise_for_status()
                data = response.json()
                if 'choices' in data and data['choices']:
                    json_string = data['choices'][0]['message']['content'].strip()
                    # Kiểm tra cơ bản (có thể thêm kiểm tra JSON hợp lệ ở đây nếu muốn)
                    if json_string.startswith('{') and json_string.endswith('}'):
                        logger.debug(f"API call successful (Attempt {attempt}).")
                        return json_string
                    else:
                        logger.warning(f"API response doesn't look like JSON (Attempt {attempt}/{max_retries}): {json_string[:100]}...")
                else:
                    logger.warning(f"Invalid API response structure (Attempt {attempt}/{max_retries}): {data}")

            except requests.exceptions.Timeout:
                logger.warning(f"OpenAI API call timed out after {request_timeout}s (Attempt {attempt}/{max_retries}). Retrying...")
            except requests.exceptions.RequestException as e:
                 logger.error(f"OpenAI API request error (Attempt {attempt}/{max_retries}): {e}")
                 if hasattr(e, 'response') and e.response is not None:
                      logger.error(f"Response status: {e.response.status_code}, text: {e.response.text[:200]}...")
                 # Không retry nếu lỗi client (4xx) trừ 429 (rate limit) và 401/403 (key lỗi)
                 if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code not in [429, 401, 403]:
                      logger.error("Client error detected, stopping retries.")
                      break
            except Exception as e:
                logger.error(f"Unexpected error calling OpenAI API (Attempt {attempt}/{max_retries}): {e}", exc_info=True)

            if attempt < max_retries:
                wait_time = 2 ** attempt # Exponential backoff
                logger.info(f"Waiting {wait_time}s before retrying...")
                time.sleep(wait_time)

        logger.error("Failed to get valid JSON response from OpenAI API after multiple retries.")
        return None

# --- Phần Test Cuối File (Cập nhật để kiểm tra quy trình 2 bước) ---
# --- Phần Test Cuối File (Tắt phân tích video và hiển thị kết quả) ---
if __name__ == "__main__":
    print("--- Testing ScriptGenerator (2-Step Process: Sentences -> Shots) ---")
    # --- Cấu hình Logger (Tùy chọn) ---
    # import logging
    # import sys
    # ... (giữ nguyên cấu hình logger nếu cần) ...

    # --- TẠM THỜI TẮT PHÂN TÍCH VIDEO CHO TEST ---
    # Import settings ở đây để có thể sửa đổi tạm thời
    from config.settings import VIDEO_SETTINGS
    original_enable_video_clips = VIDEO_SETTINGS.get("enable_video_clips", False)
    VIDEO_SETTINGS["enable_video_clips"] = False
    logger.info("--- Video analysis explicitly disabled for this test run ---")
    # ----------------------------------------------

    # --- Dữ liệu Test ---
    test_article_vi = {
        'title': 'Nông nghiệp Ai Cập Cổ đại',
        'content': 'Họ chủ yếu trồng các loại cây như là đại mạch, tiểu mạch, chà là, sen hay là táo. Đồng thời đồng bằng sông Nile cũng là nơi sinh sống của những sinh vật đa dạng và quan trọng đến tín ngưỡng Ai Cập như là chim ưng, trâu bò, cá sấu, hổ báo và nhiều loại động vật khác.',
        'source': 'Wikipedia (vi)',
        'language': 'vi'
    }
    test_article_en = {
        'title': 'Electric Vehicle Market Growth',
        'content': 'The global electric vehicle market continues to experience rapid growth, driven by government incentives, improving battery technology, and increasing consumer awareness about environmental issues. Major automakers are heavily investing in new EV models to compete.',
        'source': 'Reuters',
        'language': 'en'
    }
    test_keyword_vi = "lợi ích của việc đọc sách"
    test_keyword_en = "impact of social media on teenagers"

    # --- Khởi tạo Generator và Thực hiện Test ---
    generator = None # Khởi tạo là None để đảm bảo nó nằm trong scope của finally
    try:
        # Đảm bảo API key đã được load
        if not OPENAI_API_KEY:
             raise ValueError("OPENAI_API_KEY is not set. Please check config/credentials.py or your .env file.")

        generator = ScriptGenerator()

        # --- Test 1: Tạo script từ Bài báo Tiếng Việt ---
        print("\n" + "="*10 + " Test 1: Article (Vietnamese) - Informative " + "="*10)
        # Giờ đây khi gọi generate_script, bước phân tích video sẽ bị bỏ qua do cài đặt đã tắt
        script_vi = generator.generate_script(test_article_vi, "informative")

        if script_vi:
            print(f"\nSUCCESS: Generated script for '{script_vi.get('title')}'")
            # Output sẽ không còn các log "Analyzing..." nữa
            print(f"Total Shots (items in 'scenes' list): {len(script_vi.get('scenes', []))}")
            print(f"Total Speech Units (original sentences): {len(script_vi.get('speech_units', []))}")

            print("\n--- Example Shots (First 5): ---")
            for i, scene in enumerate(script_vi.get('scenes', [])[:5]):
                print(f"  Shot {scene.get('number')}: '{scene.get('content')}'")
            if len(script_vi.get('scenes', [])) > 5: print("  ...")

            print("\n--- Speech Units (First 2): ---")
            for i, unit in enumerate(script_vi.get('speech_units', [])[:2]):
                print(f"  Unit {unit.get('unit_number')}:")
                print(f"    Original Text: '{unit.get('text')}'")
                print(f"    Covers Shot Numbers: {unit.get('scene_numbers')}")
            if len(script_vi.get('speech_units', [])) > 2: print("  ...")
            print("-" * 30)
        else:
            print("\nFAILED to generate script from Vietnamese article.")
            print("-" * 30)

        # --- Test 2: Tạo script từ Từ khóa Tiếng Anh ---
        print("\n" + "="*10 + " Test 2: Keyword (English) - Conversational " + "="*10)
        script_en_kw = generator.generate_script_from_keyword(test_keyword_en, "conversational", "en")

        if script_en_kw:
            print(f"\nSUCCESS: Generated script for keyword '{test_keyword_en}'")
            print(f"Title: {script_en_kw.get('title')}")
            print(f"Total Shots (items in 'scenes' list): {len(script_en_kw.get('scenes', []))}")
            print(f"Total Speech Units (original sentences): {len(script_en_kw.get('speech_units', []))}")

            print("\n--- Example Shots (First 5): ---")
            for i, scene in enumerate(script_en_kw.get('scenes', [])[:5]):
                print(f"  Shot {scene.get('number')}: '{scene.get('content')}'")
            if len(script_en_kw.get('scenes', [])) > 5: print("  ...")

            print("\n--- Speech Units (First 2): ---")
            for i, unit in enumerate(script_en_kw.get('speech_units', [])[:2]):
                print(f"  Unit {unit.get('unit_number')}:")
                print(f"    Original Text: '{unit.get('text')}'")
                print(f"    Covers Shot Numbers: {unit.get('scene_numbers')}")
            if len(script_en_kw.get('speech_units', [])) > 2: print("  ...")
            print("-" * 30)
        else:
            print("\nFAILED to generate script from English keyword.")
            print("-" * 30)

    except ValueError as ve:
         print(f"\nERROR: Configuration Error: {ve}")
    except Exception as e:
        print(f"\n--- An unexpected error occurred during testing ---")
        import traceback
        print(traceback.format_exc())
    finally:
        # --- KHÔI PHỤC LẠI CÀI ĐẶT GỐC ---
        # Quan trọng nếu script còn làm việc khác sau block test này
        VIDEO_SETTINGS["enable_video_clips"] = original_enable_video_clips
        logger.info(f"--- Video analysis setting restored to: {original_enable_video_clips} ---")
        # ---------------------------------

    print("\n--- Testing Finished ---")