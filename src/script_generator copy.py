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

from src.prompt_generator import generate_prompt
# Đổi tên hàm validator được import
from src.scene_validator import validate_script_json_with_speech_units, recommend_media_count
from src import project_config as cfg
from src.utils import detect_language, safe_truncate, generate_project_id

try:
    from src.scene_video_detector import enhance_script_with_video_annotations
except ImportError:
    enhance_script_with_video_annotations = None
    logger.warning("Could not import scene_video_detector. Video annotation unavailable.")

from config.credentials import OPENAI_API_KEY
from config.settings import TEMP_DIR, VIDEO_SETTINGS

# Thêm thư mục gốc vào sys.path (Only needed if running this script directly)
# It's generally better practice to run via main.py which handles paths correctly.
# if __name__ == "__main__":
#     project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
#     if project_root not in sys.path:
#         sys.path.insert(0, project_root)

from config.credentials import OPENAI_API_KEY
from config.settings import TEMP_DIR, VIDEO_SETTINGS # Import VIDEO_SETTINGS here

class ScriptGenerator:
    def __init__(self):
        """Khởi tạo ScriptGenerator"""
        self.temp_dir = TEMP_DIR
        self.api_key = OPENAI_API_KEY

        if not self.api_key:
            logger.error("API key của OpenAI không được cung cấp")
            raise ValueError("API key không hợp lệ")

        # Cấu hình API
        self.base_url = "https://api.openai.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Tạo thư mục lưu trữ tạm thời
        os.makedirs(self.temp_dir, exist_ok=True)

    ###--- TẠO KỊCH BẢN TỪ NGUỒN LÀ BÁO CHÍ ---###
    def generate_script(self, article, style="informative", language=None):
        """
        Tạo kịch bản từ bài báo bằng cách yêu cầu và phân tích JSON từ OpenAI.

        Args:
            article (dict): Bài báo với các khóa title, content, url, v.v.
            style (str): Phong cách kịch bản (informative, conversational, dramatic, controversial)

        Returns:
            dict: Kịch bản đã tạo (hoặc None nếu lỗi) bao gồm title, scenes, source, url, style.
                  'full_script' key chứa phiên bản text tái tạo từ scenes (tùy chọn).
        """
        try:
            if not style:
                style = "informative"

            language = language or detect_language(article.get('content', ''))

            article_title = article.get('title', '').strip()

            project_id = generate_project_id(article_title)
            logger.info(f"Project ID: {project_id}")

            article_content = safe_truncate(article.get('content', '').strip())

            if not article_title or not article_content:
                logger.error("Bài báo thiếu tiêu đề hoặc nội dung")
                return None

            # Giới hạn độ dài nội dung để tiết kiệm token
            article_content = article.get('content', '')

            prompt = generate_prompt(style, article)

            # Gọi OpenAI API (hàm này đã được cấu hình để trả về chuỗi JSON)
            response_json_string = self._call_openai_api(prompt, style)

            if not response_json_string:
                logger.error("Không nhận được phản hồi JSON từ OpenAI API cho bài báo.")
                return None

            # --- KIỂM TRA JSON --- 
            # Sử dụng hàm validator mới
            is_valid, msg = validate_script_json_with_speech_units(response_json_string)
            if not is_valid:
                logger.error(f"Script JSON không hợp lệ: {msg}")
                logger.error(f"Nội dung nhận được: {response_json_string[:500]}...")
                return None

            # --- Parse JSON đã validate ---
            script_data = json.loads(response_json_string)
            extracted_title = script_data.get("title", article_title)
            scenes_data = script_data.get("scenes", [])
            speech_units_data = script_data.get("speech_units", [])

            if not scenes_data:
                 logger.warning(f"JSON hợp lệ nhưng không có 'scenes' hoặc mảng rỗng cho bài: {extracted_title}")
                 return None # Script không có scene là vô dụng

            # Tạo lại 'full_script' dạng text và xác thực scenes
            valid_scenes = []
            for scene_item in scenes_data:
                scene_num = scene_item.get("number")
                scene_content = scene_item.get("content", "") # Lấy content, có thể rỗng
                if isinstance(scene_num, int) and isinstance(scene_content, str):
                    valid_scenes.append({
                        "number": scene_num,
                        "content": scene_content.strip() # Strip khoảng trắng thừa
                    })
                else:
                    logger.warning(f"Bỏ qua mục scene không hợp lệ trong JSON: {scene_item}")
            valid_scenes.sort(key=lambda x: x["number"]) # Sắp xếp lại

            if not valid_scenes:
                 logger.error(f"Không trích xuất được scene hợp lệ nào từ JSON cho bài: {extracted_title}")
                 return None

            logger.info(f"Đã parse JSON và trích xuất {len(valid_scenes)} scenes cho bài: {extracted_title}")

            # --- Xử lý speech_units (lấy các unit hợp lệ) ---
            valid_speech_units = []
            for unit_item in speech_units_data:
                unit_num = unit_item.get("unit_number")
                unit_text = unit_item.get("text")
                unit_scene_nums = unit_item.get("scene_numbers")
                if (isinstance(unit_num, int) and
                    isinstance(unit_text, str) and unit_text.strip() and # Text unit phải có nội dung
                    isinstance(unit_scene_nums, list) and unit_scene_nums): # Phải có scene_numbers
                    valid_speech_units.append({
                        "unit_number": unit_num,
                        "text": unit_text.strip(),
                        "scene_numbers": unit_scene_nums
                    })
                else:
                    logger.warning(f"Bỏ qua speech_unit không hợp lệ: {unit_item}")
            valid_speech_units.sort(key=lambda x: x["unit_number"])

            if not valid_scenes or not valid_speech_units:
                 logger.error(f"Không trích xuất được scenes hoặc speech_units hợp lệ từ JSON.")
                 return None

            logger.info(f"Đã parse JSON: {len(valid_scenes)} scenes (shots), {len(valid_speech_units)} speech units.")

            # --- Tạo đối tượng script cuối cùng ---
            script_result = {
                "project_id": project_id, # Thêm project_id để tiện theo dõi
                "title": extracted_title,
                "scenes": valid_scenes,           # Danh sách scene (shots) ngắn
                "speech_units": valid_speech_units, # Danh sách speech units để tạo audio
                "source": article.get('source', 'Unknown'),
                "url": article.get('url', ''),
                "style": style,
                "language": language,
                "is_ai_generated": False,
                 "creation_timestamp": datetime.datetime.now().isoformat()
            }

            # --- Gọi phân tích video (Enhance Script) ---
            # Logic này vẫn hoạt động trên `scenes` (shots)
            enhanced_script = script_result # Mặc định
            if enhance_script_with_video_annotations and VIDEO_SETTINGS.get("enable_video_clips", False):
                try:
                    logger.info(f"Phân tích {len(script_result['scenes'])} scene (shots) để xác định video...")
                    # Truyền bản sao để tránh thay đổi không mong muốn nếu có lỗi
                    enhanced_script = enhance_script_with_video_annotations(script_result.copy())
                    video_scenes = sum(1 for scene in enhanced_script.get('scenes', []) if scene.get('prefer_video', False))
                    logger.info(f"Phân tích video: {video_scenes}/{len(script_result['scenes'])} shots nên dùng video.")
                except Exception as e:
                    logger.error(f"Lỗi khi phân tích scene cho video: {str(e)}", exc_info=True)
                    enhanced_script = script_result # Quay lại script gốc nếu lỗi
            elif not enhance_script_with_video_annotations:
                 logger.warning("Skipping video scene analysis (detector module missing).")
            else: # enable_video_clips is False
                 logger.info("Video clip analysis is disabled in settings.")
                 # Đảm bảo tất cả scene đều không prefer_video
                 for scene in enhanced_script.get('scenes', []):
                      scene['prefer_video'] = False

            return enhanced_script

        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng khi tạo kịch bản từ bài báo: {str(e)}", exc_info=True)
            return None

    ###--- TẠO KỊCH BẢN TỪ KEYWORD ---###
    def generate_script_from_keyword(self, keyword, style="informative", language=None):
        """
        Tạo kịch bản từ từ khóa, bao gồm scenes (shots) và speech_units.
        """
        logger.info(f"Đang tạo kịch bản từ từ khóa: '{keyword}'")
        try:
            # --- Phần chuẩn bị prompt (tương tự generate_script) ---
            if not style: style = "informative"
            language = language or detect_language(keyword)
            project_id = generate_project_id(keyword)
            logger.info(f"Project ID: {project_id}")
            prompt = generate_prompt(style=style, keyword=keyword, language=language) # Truyền keyword

            # --- Gọi API và Validate JSON ---
            response_json_string = self._call_openai_api(prompt, style)
            if not response_json_string: return None
            is_valid, msg = validate_script_json_with_speech_units(response_json_string)
            if not is_valid:
                logger.error(f"Script JSON không hợp lệ (keyword): {msg}")
                logger.error(f"Nội dung nhận được: {response_json_string[:500]}...")
                return None

            # --- Parse JSON ---
            script_data = json.loads(response_json_string)
            extracted_title = script_data.get("title", f"Video about {keyword}")
            scenes_data = script_data.get("scenes", [])
            speech_units_data = script_data.get("speech_units", [])

             # --- Xử lý scenes (lấy các scene hợp lệ) ---
            valid_scenes = []
            # ... (Copy logic xử lý scenes_data từ generate_script) ...
            for scene_item in scenes_data:
                 scene_num = scene_item.get("number")
                 scene_content = scene_item.get("content", "")
                 if isinstance(scene_num, int) and isinstance(scene_content, str):
                      valid_scenes.append({"number": scene_num, "content": scene_content.strip()})
                 else: logger.warning(f"Bỏ qua scene không hợp lệ (keyword): {scene_item}")
            valid_scenes.sort(key=lambda x: x["number"])

            # --- Xử lý speech_units (lấy các unit hợp lệ) ---
            valid_speech_units = []
            # ... (Copy logic xử lý speech_units_data từ generate_script) ...
            for unit_item in speech_units_data:
                 unit_num = unit_item.get("unit_number")
                 unit_text = unit_item.get("text")
                 unit_scene_nums = unit_item.get("scene_numbers")
                 if (isinstance(unit_num, int) and isinstance(unit_text, str) and unit_text.strip() and
                     isinstance(unit_scene_nums, list) and unit_scene_nums):
                      valid_speech_units.append({"unit_number": unit_num, "text": unit_text.strip(), "scene_numbers": unit_scene_nums})
                 else: logger.warning(f"Bỏ qua speech_unit không hợp lệ (keyword): {unit_item}")
            valid_speech_units.sort(key=lambda x: x["unit_number"])


            if not valid_scenes or not valid_speech_units:
                 logger.error(f"Không trích xuất được scenes hoặc speech_units hợp lệ (keyword).")
                 return None

            logger.info(f"Đã parse JSON (keyword): {len(valid_scenes)} scenes (shots), {len(valid_speech_units)} speech units.")

            # --- Tạo đối tượng script cuối cùng ---
            script_result = {
                "project_id": project_id,
                "title": extracted_title,
                "scenes": valid_scenes,
                "speech_units": valid_speech_units,
                "source": "AI Generated",
                "url": f"keyword://{keyword}",
                "style": style,
                "language": language,
                "keyword": keyword,
                "is_ai_generated": True,
                "creation_timestamp": datetime.datetime.now().isoformat()
            }

            # --- Gọi phân tích video (Enhance Script - logic giữ nguyên) ---
            enhanced_script = script_result # Mặc định
            # ... (Copy logic gọi enhance_script_with_video_annotations từ generate_script) ...
            if enhance_script_with_video_annotations and VIDEO_SETTINGS.get("enable_video_clips", False):
                 try:
                      logger.info(f"Phân tích {len(script_result['scenes'])} scene (shots) để xác định video (keyword)...")
                      enhanced_script = enhance_script_with_video_annotations(script_result.copy())
                      video_scenes = sum(1 for scene in enhanced_script.get('scenes', []) if scene.get('prefer_video', False))
                      logger.info(f"Phân tích video (keyword): {video_scenes}/{len(script_result['scenes'])} shots nên dùng video.")
                 except Exception as e:
                      logger.error(f"Lỗi khi phân tích scene cho video (keyword): {str(e)}", exc_info=True)
                      enhanced_script = script_result
            elif not enhance_script_with_video_annotations:
                  logger.warning("Skipping video scene analysis (detector module missing).")
            else: # enable_video_clips is False
                  logger.info("Video clip analysis is disabled in settings.")
                  for scene in enhanced_script.get('scenes', []):
                       scene['prefer_video'] = False

            return enhanced_script

        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng khi tạo kịch bản từ từ khóa: {str(e)}", exc_info=True)
            return None

    def _call_openai_api(self, prompt, style="informative"):
        """Gọi OpenAI API để tạo kịch bản JSON (Hàm này giữ nguyên)."""
        try:
            url = f"{self.base_url}/chat/completions"
            payload = {
                "model": "gpt-4o-mini", # Hoặc model khác bạn muốn
                "messages": [
                    {"role": "system", "content": "You are a professional script writer. Always return ONLY a valid JSON object matching the structure specified in the user prompt (including both 'scenes' and 'speech_units'). Ensure the JSON is perfectly parsable. Do not include any text, explanations, or markdown formatting outside the JSON object itself."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7, # Giữ nhiệt độ vừa phải
                "max_tokens": 4000,
                "response_format": {"type": "json_object"} # Bắt buộc JSON mode
            }
            response = requests.post(url, headers=self.headers, json=payload, timeout=90) # Tăng timeout nếu cần
            response.raise_for_status()
            data = response.json()
            if 'choices' not in data or not data['choices']:
                 logger.error("Phản hồi API OpenAI không hợp lệ: Thiếu 'choices'")
                 logger.debug(f"Full API Response Data: {data}")
                 return None
            json_string = data['choices'][0]['message']['content'].strip()
            # Kiểm tra cơ bản xem có giống JSON không
            if not (json_string.startswith('{') and json_string.endswith('}')):
                logger.warning(f"Phản hồi từ API không giống JSON: {json_string[:200]}...")
            return json_string
        except requests.exceptions.Timeout:
            logger.error("Lỗi: OpenAI API call timed out.")
            return None
        except requests.exceptions.RequestException as e:
             logger.error(f"Lỗi mạng hoặc API OpenAI: {e}")
             if hasattr(e, 'response') and e.response is not None:
                 logger.error(f"Response status: {e.response.status_code}, text: {e.response.text[:500]}...")
             return None
        except Exception as e:
            logger.error(f"Lỗi không xác định khi gọi OpenAI API: {str(e)}", exc_info=True)
            return None

# --- Phần Test Cuối File (Cập nhật để kiểm tra cấu trúc mới) ---
if __name__ == "__main__":
    print("--- Testing ScriptGenerator (JSON with Scenes & Speech Units) ---")
    test_article = {
        'title': 'Ancient Egyptian Agriculture',
        'content': 'The Nile River valley was incredibly fertile. Ancient Egyptians primarily grew crops like barley, wheat, dates, lotus, and apples. The Nile delta was also home to diverse wildlife important to Egyptian beliefs, such as falcons, cattle, crocodiles, leopards, and many other animals.',
        'source': 'History Today',
        'language': 'en' # Hoặc 'vi' nếu nội dung là tiếng Việt
    }

    try:
        generator = ScriptGenerator()

        print("\nTesting 'informative' style (expecting scenes and speech_units)...")
        script_info = generator.generate_script(test_article, "informative")

        if script_info and isinstance(script_info, dict) and 'scenes' in script_info and 'speech_units' in script_info:
            print(f"SUCCESS: Generated 'informative' script.")
            print(f"Title: {script_info.get('title')}")
            print(f"Number of scenes (shots): {len(script_info.get('scenes', []))}")
            print(f"Number of speech units: {len(script_info.get('speech_units', []))}")
            print("\nExample Scene (Shot):")
            if script_info['scenes']: print(f"  - Scene {script_info['scenes'][0].get('number')}: '{script_info['scenes'][0].get('content')}'")
            print("\nExample Speech Unit:")
            if script_info['speech_units']:
                 unit1 = script_info['speech_units'][0]
                 print(f"  - Unit {unit1.get('unit_number')}: Scenes {unit1.get('scene_numbers')}")
                 print(f"    Text: '{unit1.get('text')}'")
        else:
            print("FAILED to generate 'informative' script or result is not in expected dict format.")
            print(f"Result received: {script_info}")

        # Thêm test cho keyword nếu muốn
        # print("\nTesting generation from keyword...")
        # keyword_script = generator.generate_script_from_keyword("benefits of reading daily", "conversational", "en")
        # ... (kiểm tra tương tự) ...

    except ValueError as ve:
         print(f"Configuration Error (Missing API Key?): {ve}")
    except Exception as e:
        print(f"\n--- An error occurred during testing ---")
        logger.exception("Test failed")