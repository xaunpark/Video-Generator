# src/script_generator.py
import os
import sys
import time
import json
import requests
import datetime
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
            "model": "gpt-4o", # Hoặc model khác
            "messages": [
                {"role": "system", "content": "You are a helpful assistant designed to output JSON. Respond ONLY with the valid JSON object requested, without any introductory text, explanations, or markdown formatting."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 200000,
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

    # --- Bước 1 - Tạo Script với Câu Hoàn Chỉnh ---
    def _generate_initial_script_sentences(self, style_config, article=None, keyword=None, transcript_text=None, language="en", context_hint=None):
        """Tạo script ban đầu với các scene là các câu hoàn chỉnh, bám sát context."""
        logger.info("Step 1: Generating initial script with full sentences...")

        prompt_step1 = "Create a script based on the provided context.\n"
        prompt_step1 += f"Style Requirements: Tone should be {style_config['tone']}. Follow these instructions:\n"
        for instr in style_config['instructions']:
            prompt_step1 += f"- {instr}\n"

        input_type = "Unknown"
        if article:
            input_type = "Article"
            prompt_step1 += f"\nCONTEXT TYPE: News Article\n"
            prompt_step1 += f"ARTICLE TITLE: {article.get('title', '')}\n"
            prompt_step1 += f"ARTICLE CONTENT:\n{safe_truncate(article.get('content', ''))}\n"
            # --- PROMPT ĐÃ ĐƯỢC TỐI ƯU CHO ARTICLE ---
            prompt_step1 += """
            Rewrite the provided news article into an engaging, emotionally compelling, and potentially viral video narration script (voice-over/subtitle).

            CRITICAL REQUIREMENTS:

            1. Write ONLY narrative sentences suitable for voice-over or subtitles. Do NOT include visual direction phrases (like "scene opens," "camera zooms," "hình ảnh," "cảnh quay," etc.).

            2. Clearly structure the script into 3 distinct parts:
            - **Hook (Opening)**: Start immediately with the MOST intriguing, surprising, or shocking detail from the article to instantly captivate viewers. Consider using a provocative question or a cliffhanger to trigger curiosity.
            - **Story (Middle)**: Clearly narrate the key events, dramatic developments, or interesting facts from the article, organized logically and vividly to build suspense and maintain engagement.
            - **Conclusion (Ending)**: End with a powerful, memorable statement or an open-ended question that encourages viewers to reflect, comment, or share the video.

            3. Use vivid, emotional language:
            - Incorporate emotionally-charged words (e.g., shocking, unbelievable, devastating, astonishing, heartbreaking, incredible) to amplify viewer reactions.
            - Use conversational, natural-sounding narration to deeply engage the audience.

            4. Highly visual-friendly narration:
            - Although you must NOT explicitly describe visuals (e.g., avoid "zoom in," "show," "image of"), choose wording that naturally evokes clear and dramatic mental imagery, facilitating the search for stock visuals later.

            5. Encourage viewer interaction:
            - End the script with a brief, provocative question inviting viewer opinions or encouraging sharing.

            6. Strict accuracy:
            - Only use facts and information directly from the provided article. Do NOT invent or speculate beyond provided content.

            OUTPUT FORMAT:
            Return ONLY a valid JSON object:
            {
            "title": "Emotionally engaging and click-worthy title",
            "initial_scenes": [
                "Captivating opening sentence or two (hook).",
                "Engaging narrative sentence clearly describing dramatic developments.",
                "...",
                "Powerful concluding sentence ending with a reflective question or strong emotional statement."
            ]
            }
            """
        elif keyword:
            input_type = "Keyword"
            lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"
            prompt_step1 += f"\nCONTEXT TYPE: Keyword/Topic\n"
            prompt_step1 += f"TOPIC: \"{keyword}\"\n"

            prompt_step1 += f"""
        Instructions:
        Generate an engaging, informative, and potentially viral video narration script {lang_instruction} about the topic '{keyword}'.

        CRITICAL REQUIREMENTS:

        1. Clear and structured storytelling:
        - **Hook (opening)**: Start with an intriguing question, surprising fact, or provocative statement related directly to the topic to immediately capture viewers' attention.
        - **Body (main content)**: Clearly explain or narrate key ideas, interesting facts, or insightful details about '{keyword}'. Structure the narrative logically, each scene clearly leading to the next.
        - **Conclusion (ending)**: End with a powerful statement, summary, or thought-provoking question that invites viewer interaction or encourages sharing.

        2. Vivid and visual-friendly language:
        - Use emotionally engaging and vivid descriptions to help the audience easily visualize each idea or concept.
        - While maintaining visual imagery, do NOT explicitly describe visual actions (e.g., avoid phrases like "scene shows", "camera zooms", "image of", "cảnh quay", etc.). Keep sentences purely narrative, suitable for voice-over or subtitle.

        3. Engaging, conversational tone:
        - Maintain a natural, conversational style that captivates and holds viewers' interest throughout the video.

        OUTPUT FORMAT:
        Return ONLY a valid JSON object:
        {{
        "title": "Engaging, attention-grabbing title related directly to '{keyword}'",
        "initial_scenes": [
            "Intriguing opening sentence or two (hook).",
            "Next logically connected narrative sentence(s) clearly describing key points.",
            "...",
            "Strong concluding sentence or question encouraging viewer reflection or interaction."
        ]
        }}
            """

        elif transcript_text:
            input_type = "YouTube Transcript"
            lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"
            prompt_step1 += f"\nCONTEXT TYPE: YouTube Video Transcript {f'({context_hint})' if context_hint else ''}\n"
            prompt_step1 += f"TRANSCRIPT CONTENT:\n{safe_truncate(transcript_text, 12000)}\n"

            prompt_step1 += f"""
        Instructions:
        Convert the provided YouTube transcript into a concise, highly engaging, and structured video narration script {lang_instruction} suitable for creating a shorter, viral summary video.

        CRITICAL REQUIREMENTS:

        1. Thorough but concise restructuring:
        - Remove ALL unnecessary filler words or phrases (e.g., "um", "you know", "actually", repeated sentences, etc.).
        - Clearly summarize the main ideas and key highlights from the transcript. 
        - Significantly condense the content into concise, easy-to-follow narrative sentences without losing important meaning.

        2. Clear storytelling structure:
        - **Hook (Opening)**: Start with the most intriguing, impactful, or surprising point from the transcript to immediately grab attention.
        - **Main points (Middle)**: Logically narrate the key points, highlights, or insights extracted from the transcript, structured clearly and sequentially for ease of understanding.
        - **Conclusion (Ending)**: Provide a compelling summary, impactful statement, or thought-provoking question encouraging viewers to reflect, interact, or share.

        3. Natural and conversational narration:
        - Rewrite sentences to ensure clarity, smoothness, and ease of narration.
        - Maintain a conversational, engaging tone appropriate for voice-over or subtitles.

        4. Visual-friendly language:
        - Choose wording that naturally evokes clear mental images, facilitating easy selection of relevant visuals later.
        - However, strictly avoid explicit visual direction phrases like "scene opens", "camera zooms", "hình ảnh", "cảnh quay", etc.

        5. Accuracy and faithfulness:
        - Do NOT add any external information. ONLY use content found directly in the provided transcript. Avoid deviating significantly from original topics or ideas.

        OUTPUT FORMAT:
        Return ONLY a valid JSON object:
        {{
        "title": "Engaging, click-worthy title summarizing video's main point",
        "initial_scenes": [
            "Intriguing opening sentence or two (hook).",
            "Next concise, logically narrated sentence(s) clearly summarizing key ideas.",
            "...",
            "Compelling conclusion or question designed to engage viewers and invite interaction."
        ]
        }}
        """
        else:
            logger.error("Step 1 Failed: No valid input provided.")
            return None

        logger.info(f"Generating initial script based on: {input_type}")

        # --- Gọi API cho Bước 1 ---
        response_json_str = self._call_openai_api(prompt_step1, request_timeout=120) # Increase timeout for potentially longer processing
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
        Break down the provided text into short visual "shots" for an engaging video narration.

        IMPORTANT – Follow these STRICT rules to avoid too many quick scene changes:

        1. Length-based splitting rules:
        - If the text has fewer than 15 words → DO NOT SPLIT. Keep as one shot.
        - If the text has 15-30 words → SPLIT INTO MAXIMUM 2 SHOTS.
        - If the text has over 30 words → SPLIT INTO MAXIMUM 3 SHOTS.

        2. Intelligent distribution:
        - If the previous sentence (scene) was already split into multiple shots (≥2 shots), strongly consider NOT splitting this current sentence unless absolutely necessary (extremely long or complex).

        3. Shot length guidelines:
        - Each shot ideally contains between 7 to 15 words.
        - Shots shorter than 5 words should only appear if extremely necessary for dramatic emphasis.

        4. Splitting logic:
        - Split at natural grammatical pauses or logical concept boundaries (commas, conjunctions, punctuation).
        - Do NOT break tightly connected phrases or compound nouns.

        OUTPUT FORMAT:
        Return ONLY a JSON object:
        {{
        "shots": ["Shot 1 text", "Shot 2 text", ...]
        }}

        EXAMPLES:

        Example 1 (short text - no split):
        Input: "The sun quietly sets over the mountain peaks."
        Output: {{
        "shots": ["The sun quietly sets over the mountain peaks."]
        }}

        Example 2 (medium-length text - 2 shots max):
        Input: "Local farmers rely on barley, wheat, dates, and apples as their main crops."
        Output: {{
        "shots": [
            "Local farmers rely on barley and wheat,",
            "dates and apples as their main crops."
        ]
        }}

        Example 3 (long text - 3 shots max):
        Input: "The ancient city was discovered in 1902, revealing countless artifacts, temples, and an impressive irrigation system that amazed archaeologists."
        Output: {{
        "shots": [
            "The ancient city was discovered in 1902,",
            "revealing countless artifacts and temples,",
            "and an impressive irrigation system that amazed archaeologists."
        ]
        }}

        TEXT TO BREAK DOWN:
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
    def generate_script(self, article, style="informative", language=None, video_mode="basic"):
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

        script_result = None
        enhanced_script = None

        if video_mode == "basic":
            logger.info("Generating script in Basic mode...")
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
        elif video_mode == "advanced":
            logger.info("Generating script in Advanced (Chapters) mode...")
            # Gọi hàm mới để tạo script nâng cao
            script_result = self._generate_advanced_script(
                source_data={'type': 'article', 'data': article},
                style_config=style_config,
                language=language,
                style=style, # Pass style for metadata
                project_id=project_id # Pass project_id
            )
            if not script_result:
                logger.error("Failed to generate advanced script.")
                return None

        else:
            logger.error(f"Invalid video_mode: '{video_mode}'. Cannot generate script.")
            return None

        # --- Gọi phân tích video (Enhance Script) ---
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

    # --- Hàm generate_script_from_keyword ---
    def generate_script_from_keyword(self, keyword, style="informative", language=None, video_mode="basic"):
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

        script_result = None
        enhanced_script = None

        if video_mode == "basic":
            logger.info("Generating keyword script in Basic mode...")
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

        elif video_mode == "advanced":
            logger.info("Generating keyword script in Advanced (Chapters) mode...")
            script_result = self._generate_advanced_script(
                source_data={'type': 'keyword', 'data': keyword},
                style_config=style_config,
                language=language,
                style=style,
                project_id=project_id
            )
            if not script_result:
                logger.error("Failed to generate advanced keyword script.")
                return None
            # Ensure AI generation flag is set correctly for advanced keyword script
            script_result["is_ai_generated"] = True
            script_result["source"] = "AI Generated (Chapters)"
            script_result["url"] = f"keyword_chapters://{keyword}"
            script_result["keyword"] = keyword


        else:
            logger.error(f"Invalid video_mode: '{video_mode}'. Cannot generate script.")
            return None

        # --- Gọi phân tích video (Enhance Script) ---
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

    # --- NEW Main function for TRANSCRIPT/TEXT input ---
    def generate_script_from_text(self, input_text, style="informative", language="en", context_hint=None, video_mode="basic"):
        """
        Generates a script from raw text (like a transcript) using the 2-step process.
        """
        # Generate a project ID based on the text's beginning
        project_id_hint = context_hint if context_hint else input_text[:50]
        project_id = generate_project_id(project_id_hint)
        logger.info(f"Generating script from text (Style: {style}, Lang: {language}, Hint: {context_hint or 'N/A'})")

        if style not in cfg.style_configs:
            logger.warning(f"Unknown style '{style}', defaulting to 'informative'.")
            style = "informative"
        style_config = cfg.style_configs[style]
        # Language is passed directly

        script_result = None
        enhanced_script = None

        if video_mode == "basic":
            logger.info("Generating text script in Basic mode...")

            # --- Step 1: Generate initial script with full sentences ---
            initial_script_data = self._generate_initial_script_sentences(
                style_config=style_config,
                transcript_text=input_text, # Pass transcript text
                language=language,
                context_hint=context_hint
            )
            if not initial_script_data:
                return None

            final_title = initial_script_data["title"]
            initial_sentences = initial_script_data["initial_scenes"]

            # --- Step 2: Breakdown sentences and build final structure ---
            # (Identical logic to other generate functions)
            final_scenes = []
            final_speech_units = []
            global_shot_number = 1
            speech_unit_number = 1

            logger.info("Step 2: Breaking down generated sentences into visual shots...")
            for sentence in initial_sentences:
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
                else: # Fallback
                    logger.warning(f"Could not break down sentence (text input), using full sentence as shot: '{sentence[:50]}...'")
                    final_scenes.append({"number": global_shot_number, "content": sentence.strip()})
                    final_speech_units.append({"unit_number": speech_unit_number, "text": sentence.strip(), "scene_numbers": [global_shot_number]})
                    global_shot_number += 1
                    speech_unit_number += 1

            if not final_scenes or not final_speech_units:
                logger.error("Script generation failed (text input): No valid scenes or speech units created.")
                return None

            logger.info(f"Script generation complete (text input): {len(final_scenes)} shots, {len(final_speech_units)} speech units.")

            # --- Final script object ---
            script_result = {
                "project_id": project_id,
                "title": final_title,
                "scenes": final_scenes,
                "speech_units": final_speech_units,
                "source": f"AI Generated from Text ({context_hint or 'Input Text'})",
                "url": f"text://{project_id}", # Placeholder URL
                "style": style,
                "language": language,
                "is_ai_generated": True,
                "creation_timestamp": datetime.datetime.now().isoformat()
            }

        elif video_mode == "advanced":
            logger.info("Generating text script in Advanced (Chapters) mode...")
            script_result = self._generate_advanced_script(
                source_data={'type': 'text', 'data': input_text, 'context': context_hint},
                style_config=style_config,
                language=language,
                style=style,
                project_id=project_id
            )
            if not script_result:
                logger.error("Failed to generate advanced text script.")
                return None
            # Ensure AI generation flag is set correctly for advanced text script
            script_result["is_ai_generated"] = True
            script_result["source"] = f"AI Generated from Text (Chapters - {context_hint or 'Input Text'})"
            script_result["url"] = f"text_chapters://{project_id}"


        else:
            logger.error(f"Invalid video_mode: '{video_mode}'. Cannot generate script.")
            return None

        # --- Enhance with video annotations ---
        enhanced_script = script_result
        if enhance_script_with_video_annotations and VIDEO_SETTINGS.get("enable_video_clips", False):
             try:
                 logger.info(f"Analyzing {len(script_result['scenes'])} shots for video suitability (text input)...")
                 enhanced_script = enhance_script_with_video_annotations(script_result.copy())
                 video_shots = sum(1 for shot in enhanced_script.get('scenes', []) if shot.get('prefer_video', False))
                 logger.info(f"Video analysis result (text input): {video_shots}/{len(script_result['scenes'])} shots marked for video.")
             except Exception as e:
                 logger.error(f"Error during video analysis (text input): {str(e)}", exc_info=True)
                 enhanced_script = script_result
        elif not enhance_script_with_video_annotations:
             logger.warning("Skipping video shot analysis (detector module missing).")
        else:
            logger.info("Video clip analysis is disabled in settings.")
            for scene in enhanced_script.get('scenes', []):
                 scene['prefer_video'] = False

        return enhanced_script

    def _generate_advanced_script(self, source_data, style_config, language, style, project_id):
        """Generates a chapter-based script using OpenAI."""
        logger.info("Step 1 (Advanced): Generating chapter structure...")

        # --- Bước 1: Tạo Prompt cho Chapters ---

        prompt_step1_advanced = f"""
        You are an expert video scriptwriter and storyteller known for creating highly engaging, insightful, emotionally resonant, and comprehensive video scripts.

        Your goal is to produce the highest quality, deeply thoughtful, and truly comprehensive video script possible, carefully avoiding superficial summaries or brief overviews.

        Video Style Requirements:
        - Tone: {style_config['tone']}
        - Instructions: {'; '.join(style_config['instructions'])}

        Input Content Details:
        """
        input_type = source_data.get('type', 'unknown')
        content_data = source_data.get('data', '')
        context_hint = source_data.get('context', None)

        if input_type == 'article':
            prompt_step1_advanced += f"- Type: News Article\n"
            prompt_step1_advanced += f"- Title: {content_data.get('title', '')}\n"
            prompt_step1_advanced += f"- Content to Analyze & Structure:\n{safe_truncate(content_data.get('content', ''))}\n"
            prompt_step1_advanced += "\nTask: Thoroughly analyze the article. Provide a deep, comprehensive, detailed narrative across clearly defined chapters. Include substantial background context, critical insights, emotional depth, illustrative examples, multiple perspectives, and implications to deliver a fully-rounded narrative."
        elif input_type == 'keyword':
            lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"
            prompt_step1_advanced += f"- Type: Keyword/Topic\n"
            prompt_step1_advanced += f"- Topic: \"{content_data}\"\n"
            prompt_step1_advanced += f"""
        Task: Extensively research and develop a truly comprehensive, detailed, and highly informative script {lang_instruction} about '{content_data}'.

        Explicitly adhere to these guidelines:
        - Aim for depth, providing extensive analysis, detailed explanations, historical context, practical examples, critical viewpoints, emotional resonance, and storytelling techniques to significantly enhance viewer engagement.
        - Avoid superficial or overly brief chapters; each chapter must comprehensively explore its respective facet of the topic.
        - Provide rich context and clear narrative progression from foundational concepts to advanced insights, ensuring clarity and complete understanding for the audience.
        - Clearly define your intended audience and tailor language, tone, and examples accordingly to maximize viewer resonance and impact.
        - Conclude each chapter with thoughtful reflections, actionable insights, or intriguing points that encourage further thinking or action by the viewers.
        """
        elif input_type == 'text':
            lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"
            prompt_step1_advanced += f"- Type: Input Text {f'({context_hint})' if context_hint else ''}\n"
            prompt_step1_advanced += f"- Text Content to Structure:\n{safe_truncate(content_data, 12000)}\n"
            prompt_step1_advanced += f"\nTask: Provide a deeply analytical, well-organized, and genuinely comprehensive narrative based on the text {lang_instruction}. Structure into detailed chapters, fully exploring each aspect with emotional depth, compelling storytelling, and rich explanations, avoiding superficial summaries at all costs."
        else:
            logger.error("Invalid source data type for advanced script generation.")
            return None

        prompt_step1_advanced += f"""

        Chapter Requirements:
        - Create between 3 and 7 chapters, focusing exclusively on achieving comprehensive depth and clarity. Never sacrifice content quality or detail for brevity.
        - Clearly identify the emotional goals (e.g., curiosity, empathy, inspiration, excitement, nostalgia) and deliberately structure the narrative to consistently achieve these emotional impacts throughout.
        - Each chapter must explore its topic comprehensively, providing rich context, detailed examples, extensive explanations, critical analysis, emotional resonance, and engaging storytelling.
        - Chapters must logically build upon each other, presenting information clearly, progressively, and cohesively from foundational to advanced levels.
        - Actively employ storytelling techniques—including anecdotes, metaphors, rhetorical questions, suspenseful narratives, historical examples—to enhance emotional and intellectual engagement.
        - Explicitly tailor your narrative style (language complexity, tone, and choice of examples) to your defined target audience, ensuring maximum resonance and viewer satisfaction.
        - Include actionable insights or reflective conclusions at the end of each chapter, enabling viewers to derive personal or practical value from the video.
        - Begin Chapter 1 with an intriguing opening that strongly captures viewer attention and clearly communicates the importance of the topic.
        - End the final chapter with a memorable and thoughtful conclusion, reinforcing key ideas and inspiring viewer reflection or further exploration.
        - Generate insightful, concise, and engaging `chapter_title` for each chapter (max 5-7 words).
        - For each chapter, provide extensive narrative content as a list of natural-sounding, detailed sentences (`chapter_content`) designed specifically for professional-quality voice-over narration.
        - Absolutely DO NOT include visual directions, editing instructions, or formatting cues.

        Output Format:
        Return ONLY a valid JSON object following this exact structure, without explanations or markdown formatting:
        {{
        "title": "Highly Engaging and Insightful Video Title About the Topic",
        "chapters": [
            {{
            "chapter_number": 1,
            "chapter_title": "Concise Chapter 1 Title",
            "chapter_content": [
                "Detailed opening sentence(s), strongly engaging viewers with context and emotional resonance.",
                "Further extensive and insightful sentences, continuing with comprehensive explanations and vivid storytelling."
            ]
            }},
            {{
            "chapter_number": 2,
            "chapter_title": "Insightful Chapter 2 Title",
            "chapter_content": [
                "Comprehensive and detailed exploration of chapter 2's main points, enriched by critical perspectives and compelling storytelling.",
                "Additional sentences providing thorough analysis, context-rich examples, emotional resonance, and actionable takeaways."
            ]
            }}
            // ... additional detailed and comprehensive chapters
        ]
        }}
        """
        
        # Call OpenAI API (potentially longer timeout needed)
        response_json_str = self._call_openai_api(prompt_step1_advanced, request_timeout=180) # Increased timeout
        if not response_json_str:
            logger.error("Step 1 (Advanced) Failed: No response from API for chapter structure.")
            return None

        # --- Bước 2: Parse và Flatten ---
        try:
            chapter_data = json.loads(response_json_str)

            # Validate structure
            if not isinstance(chapter_data, dict) or \
            "title" not in chapter_data or not isinstance(chapter_data["title"], str) or \
            "chapters" not in chapter_data or not isinstance(chapter_data["chapters"], list) or \
            not chapter_data["chapters"]:
                logger.error(f"Step 1 (Advanced) Failed: Invalid JSON structure received: {chapter_data}")
                return None

            final_title = chapter_data["title"]
            final_scenes = []
            final_speech_units = []
            global_shot_number = 1
            speech_unit_number = 1

            logger.info("Step 2 (Advanced): Flattening chapters and breaking sentences into shots...")

            for chapter in chapter_data["chapters"]:
                # Validate chapter structure
                if not isinstance(chapter, dict) or \
                "chapter_number" not in chapter or not isinstance(chapter["chapter_number"], int) or \
                "chapter_title" not in chapter or not isinstance(chapter["chapter_title"], str) or \
                "chapter_content" not in chapter or not isinstance(chapter["chapter_content"], list):
                    logger.warning(f"Skipping invalid chapter structure: {chapter}")
                    continue

                chapter_num = chapter["chapter_number"]
                chapter_title = chapter["chapter_title"].strip()
                chapter_content_sentences = chapter["chapter_content"]

                logger.info(f"  Processing Chapter {chapter_num}: '{chapter_title}' ({len(chapter_content_sentences)} sentences)")

                if not chapter_content_sentences:
                    logger.warning(f"Chapter {chapter_num} has empty content. Skipping.")
                    continue

                for sentence in chapter_content_sentences:
                    sentence = sentence.strip()
                    if not sentence: continue

                    # Breakdown sentence into shots (reuse existing function)
                    shots_for_sentence = self._breakdown_sentence_into_shots(sentence, style_config['tone'])

                    if not shots_for_sentence: # Fallback if breakdown fails
                        logger.warning(f"(Advanced) Could not break down sentence in Chapter {chapter_num}, using full sentence as shot: '{sentence[:50]}...'")
                        shots_for_sentence = [sentence] # Treat full sentence as one shot

                    shot_numbers_for_unit = []
                    for shot_content in shots_for_sentence:
                        shot_content = shot_content.strip()
                        if not shot_content: continue

                        scene = {
                            "number": global_shot_number,
                            "content": shot_content,
                            "chapter_number": chapter_num,
                            "chapter_title": chapter_title
                        }
                        final_scenes.append(scene)
                        shot_numbers_for_unit.append(global_shot_number)
                        global_shot_number += 1

                    if shot_numbers_for_unit: # Only create speech unit if scenes were generated
                        speech_unit = {
                            "unit_number": speech_unit_number,
                            "text": sentence, # Original sentence for TTS
                            "scene_numbers": shot_numbers_for_unit,
                            "chapter_number": chapter_num,
                            "chapter_title": chapter_title
                        }
                        final_speech_units.append(speech_unit)
                        speech_unit_number += 1

            if not final_scenes or not final_speech_units:
                logger.error("Script generation failed (Advanced): No valid scenes or speech units were created after flattening.")
                return None

            logger.info(f"Script generation complete (Advanced): {len(final_scenes)} shots, {len(final_speech_units)} speech units across {len(chapter_data['chapters'])} chapters.")

            # --- Bước 3: Return final script object ---
            # Basic metadata - specific source/url will be added in the calling function
            advanced_script_result = {
                "project_id": project_id,
                "title": final_title,
                "scenes": final_scenes,
                "speech_units": final_speech_units,
                "source": "AI Generated (Chapters)", # Placeholder, specific source added later
                "url": "",                          # Placeholder, specific URL added later
                "style": style,
                "language": language,
                "script_mode": "advanced", # Indicate mode
                "is_chapter_based": True, # Explicit flag
                "is_ai_generated": True, # Always true for advanced mode currently
                "creation_timestamp": datetime.datetime.now().isoformat()
            }
            return advanced_script_result

        except json.JSONDecodeError as e:
            logger.error(f"Step 1 (Advanced) Failed: Could not decode JSON response for chapters: {e}")
            logger.debug(f"Received content: {response_json_str}")
            return None
        except Exception as e:
            logger.error(f"Step 2 (Advanced) Failed: Unexpected error parsing or flattening chapters: {e}", exc_info=True)
            return None
    # --- End of _generate_advanced_script ---

    def _call_openai_api(self, prompt, max_retries=3, request_timeout=90):
        """Gọi OpenAI API, yêu cầu JSON, có retry đơn giản."""
        payload = {
            "model": "gpt-4o", # Hoặc model khác
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
    test_transcript = """
    Hello everyone, and welcome back to the channel. Today, we're diving deep into the world of sustainable gardening.
    First, let's talk about composting. It's a fantastic way to reduce waste and enrich your soil naturally.
    You can compost kitchen scraps like vegetable peelings and coffee grounds. Avoid meat and dairy products.
    Another key aspect is water conservation. Using rain barrels and drip irrigation systems can save a lot of water compared to traditional sprinklers.
    Choosing native plants is also crucial. They are adapted to the local climate and require less maintenance. That's all for today! Happy gardening!
    """
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

        # --- NEW Test 3: Transcript (En) ---
        print("\n" + "="*10 + " Test 3: Transcript (English) - Informative " + "="*10)
        script_transcript = generator.generate_script_from_text(test_transcript, "informative", "en", context_hint="Sustainable Gardening Tips")

        if script_transcript:
            print(f"\nSUCCESS: Generated script from transcript")
            print(f"Title: {script_transcript.get('title')}")
            print(f"Total Shots: {len(script_transcript.get('scenes', []))}")
            print(f"Total Speech Units: {len(script_transcript.get('speech_units', []))}")
            # ... (print more details as needed) ...
            print("-" * 30)
        else:
            print("\nFAILED to generate script from transcript.")
            print("-" * 30)

    except ValueError as ve:
         print(f"\nERROR: Configuration Error: {ve}")
    except Exception as e:
        print(f"\n--- An unexpected error occurred during testing ---")
        import traceback
        print(traceback.format_exc())
    finally:
        VIDEO_SETTINGS["enable_video_clips"] = original_enable_video_clips
        logger.info(f"--- Video analysis setting restored to: {original_enable_video_clips} ---")

    print("\n--- Testing Finished ---")