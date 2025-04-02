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

from src.prompt_generator import generate_prompt
from src.scene_validator import validate_script_json, recommend_media_count
from src import project_config as cfg
from src.utils import detect_language, safe_truncate, generate_project_id

from src.logger_config import setup_logger
logger = setup_logger(__name__)

try:
    from src.scene_video_detector import enhance_script_with_video_annotations
except ImportError:
    enhance_script_with_video_annotations = None
    logger.warning("Could not import scene_video_detector. Video annotation unavailable.")

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
            is_valid, msg = validate_script_json(response_json_string)
            if not is_valid:
                logger.error(f"Script JSON không hợp lệ: {msg}")
                logger.error(f"Nội dung nhận được từ OpenAI: {response_json_string[:500]}...")
                return None

            # --- PHÂN TÍCH JSON SAU KHI ĐÃ VALIDATE --- 
            script_data = json.loads(response_json_string)

            # Trích xuất dữ liệu từ JSON đã parse
            # Sử dụng tiêu đề từ JSON, fallback về tiêu đề bài báo gốc
            extracted_title = script_data.get("title", article_title)
            scenes_data = script_data.get("scenes", [])

            if not scenes_data:
                 logger.warning(f"JSON hợp lệ nhưng không có 'scenes' hoặc mảng rỗng cho bài: {extracted_title}")
                 return None # Script không có scene là vô dụng

            # Tạo lại 'full_script' dạng text và xác thực scenes
            full_script_parts = []
            valid_scenes = []
            for i, scene_item in enumerate(scenes_data):
                scene_num = scene_item.get("number")
                scene_content = scene_item.get("content")

                if isinstance(scene_num, int) and isinstance(scene_content, str) and scene_content.strip():
                    full_script_parts.append(f"#SCENE {scene_num}#")
                    full_script_parts.append(scene_content.strip())
                    full_script_parts.append("")

                    valid_scenes.append({
                        "number": scene_num,
                        "content": scene_content.strip()
                    })
                else:
                    logger.warning(f"Bỏ qua mục scene không hợp lệ trong JSON: {scene_item}")

            valid_scenes.sort(key=lambda x: x["number"]) # Sắp xếp lại cho chắc chắn
            full_script_text = "\n".join(full_script_parts).strip()

            if not valid_scenes:
                 logger.error(f"Không trích xuất được scene hợp lệ nào từ JSON cho bài: {extracted_title}")
                 return None

            logger.info(f"Đã parse JSON và trích xuất {len(valid_scenes)} scenes cho bài: {extracted_title}")

            # Tạo đối tượng script cuối cùng
            script_result = {
                "title": extracted_title,        # Tiêu đề từ JSON
                "full_script": full_script_text, # Phiên bản text (tùy chọn)
                "scenes": valid_scenes,          # Danh sách scene từ JSON
                "source": article.get('source', 'Unknown'),
                "url": article.get('url', ''),
                "style": style
            }
            # --- KẾT THÚC PHÂN TÍCH JSON ---

            # --- Gọi phân tích video (Enhance Script) ---
            if enhance_script_with_video_annotations: # Check if import worked
                try:
                    # Kiểm tra xem tính năng video clips có được bật không
                    if VIDEO_SETTINGS.get("enable_video_clips", False):
                        logger.info(f"Phân tích {len(script_result['scenes'])} scene để xác định nên dùng video...")
                        enhanced_script = enhance_script_with_video_annotations(script_result)

                        video_scenes = sum(1 for scene in enhanced_script.get('scenes', []) if scene.get('prefer_video', False))
                        logger.info(f"Kết quả phân tích video: {video_scenes}/{len(script_result['scenes'])} scene nên dùng video")

                        return enhanced_script
                    else:
                        logger.info("Tính năng video clips đang bị tắt trong cài đặt")
                        # Mark all scenes as not preferring video if disabled
                        for scene in script_result.get('scenes', []):
                            scene['prefer_video'] = False
                        return script_result
                except Exception as e:
                    logger.error(f"Lỗi khi phân tích scene cho video: {str(e)}")
                    # Return script without analysis if enhancer fails
                    return script_result
            else:
                 logger.warning("Skipping video scene analysis because detector module couldn't be imported.")
                 return script_result # Return script without analysis

        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng khi tạo kịch bản từ bài báo: {str(e)}", exc_info=True)
            return None

    ###--- TẠO KỊCH BẢN TỪ KEYWORD ---###
    def generate_script_from_keyword(self, keyword, style="informative", language=None):
        """
        Tạo kịch bản trực tiếp từ từ khóa bằng cách yêu cầu và phân tích JSON.

        Args:
            keyword (str): Từ khóa để tạo kịch bản
            style (str): Phong cách kịch bản
            language (str): Ngôn ngữ kịch bản ("vi" hoặc "en")

        Returns:
            dict: Kịch bản được tạo hoặc None nếu lỗi
        """
        logger.info(f"Đang tạo kịch bản trực tiếp từ từ khóa: '{keyword}'")

        try:
            # --- TẠO PROMPT ---
            if not style:
                style = "informative"

            language = language or detect_language(keyword)
       
            project_id = generate_project_id(keyword)
            logger.info(f"Project ID: {project_id}")

            prompt = generate_prompt(style=style, keyword=keyword, language=language)

            # Gọi OpenAI API (hàm này trả về chuỗi JSON)
            response_json_string = self._call_openai_api(prompt, style)

            if not response_json_string:
                logger.error("Không nhận được phản hồi JSON từ OpenAI API cho từ khóa.")
                return None

            # === Validate JSON ===
            is_valid, msg = validate_script_json(response_json_string)
            if not is_valid:
                logger.error(f"Script JSON không hợp lệ (keyword): {msg}")
                logger.error(f"Nội dung nhận được từ OpenAI: {response_json_string[:500]}...")
                return None

            # === Phân tích JSON ===
            script_data = json.loads(response_json_string)
            extracted_title = script_data.get("title", f"Video about {keyword}")
            scenes_data = script_data.get("scenes", [])

            if not scenes_data:
                logger.warning(f"JSON hợp lệ nhưng không có 'scenes' hoặc mảng rỗng cho từ khóa: {keyword}")
                return None

            # Tạo lại 'full_script' dạng text và xác thực scenes
            full_script_parts = []
            valid_scenes = []
            for i, scene_item in enumerate(scenes_data):
                scene_num = scene_item.get("number")
                scene_content = scene_item.get("content")

                if isinstance(scene_num, int) and isinstance(scene_content, str) and scene_content.strip():
                    full_script_parts.append(f"#SCENE {scene_num}#")
                    full_script_parts.append(scene_content.strip())
                    full_script_parts.append("")

                    valid_scenes.append({
                        "number": scene_num,
                        "content": scene_content.strip()
                    })
                else:
                     logger.warning(f"Bỏ qua mục scene không hợp lệ trong JSON (keyword): {scene_item}")

            valid_scenes.sort(key=lambda x: x["number"])
            full_script_text = "\n".join(full_script_parts).strip()

            if not valid_scenes:
                 logger.error(f"Không trích xuất được scene hợp lệ nào từ JSON cho từ khóa: {keyword}")
                 return None

            logger.info(f"Đã parse JSON và trích xuất {len(valid_scenes)} scenes cho từ khóa: {keyword}")

            # Tạo đối tượng script cuối cùng
            current_date = datetime.datetime.now().strftime("%Y-%m-%d")
            script_result = { # Đổi tên thành script_result cho nhất quán
                "title": extracted_title,
                "full_script": full_script_text,
                "scenes": valid_scenes,
                "source": "AI Generated",
                "url": f"keyword://{keyword}",
                "style": style,
                "keyword": keyword,
                "is_ai_generated": True,
                "created_date": current_date
            }
            # --- KẾT THÚC PHÂN TÍCH JSON ---

            # --- Gọi phân tích video (Enhance Script) ---
            if enhance_script_with_video_annotations:
                try:
                    if VIDEO_SETTINGS.get("enable_video_clips", False):
                        logger.info(f"Phân tích {len(script_result['scenes'])} scene để xác định nên dùng video...")
                        enhanced_script = enhance_script_with_video_annotations(script_result)

                        video_scenes = sum(1 for scene in enhanced_script.get('scenes', []) if scene.get('prefer_video', False))
                        logger.info(f"Kết quả phân tích video: {video_scenes}/{len(script_result['scenes'])} scene nên dùng video")

                        return enhanced_script
                    else:
                        logger.info("Tính năng video clips đang bị tắt trong cài đặt")
                        for scene in script_result.get('scenes', []):
                            scene['prefer_video'] = False
                        return script_result
                except Exception as e:
                    logger.error(f"Lỗi khi phân tích scene cho video: {str(e)}")
                    return script_result
            else:
                logger.warning("Skipping video scene analysis because detector module couldn't be imported.")
                return script_result

        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng khi tạo kịch bản từ từ khóa: {str(e)}", exc_info=True)
            return None

    def _call_openai_api(self, prompt, style="informative"):
        """Gọi OpenAI API để tạo kịch bản, LUÔN yêu cầu JSON"""
        # --- GIỮ NGUYÊN NHƯ PHIÊN BẢN TRƯỚC ĐÃ SỬA ---
        # Đảm bảo có "response_format": {"type": "json_object"}
        try:
            url = f"{self.base_url}/chat/completions"

            payload = {
                "model": "gpt-4o-mini", # Consider using gpt-4o for complex prompts if needed
                "messages": [
                    {"role": "system", "content": "You are a professional script writer. Always return a valid JSON object matching the structure specified in the user prompt. Ensure the JSON can be parsed without errors. Do not include any text outside the JSON object itself."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.8 if style == "controversial" else 0.7,
                "max_tokens": 4000, # Adjusted max_tokens slightly
                "response_format": {"type": "json_object"}  # ESSENTIAL for this approach
            }

            response = requests.post(url, headers=self.headers, json=payload, timeout=60) # Increased timeout

            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            data = response.json()
            if 'choices' not in data or not data['choices']:
                 logger.error("Phản hồi API OpenAI không hợp lệ: Thiếu 'choices'")
                 logger.debug(f"Full API Response Data: {data}")
                 return None

            json_string = data['choices'][0]['message']['content'].strip()

            # Basic check if the response looks like JSON
            if not (json_string.startswith('{') and json_string.endswith('}')) and \
               not (json_string.startswith('[') and json_string.endswith(']')):
                logger.warning(f"Phản hồi từ API không giống JSON hợp lệ: {json_string[:200]}...")
                # Optionally try cleaning again, but likely indicates an API issue or prompt problem
                # return None # Or try to proceed cautiously

            return json_string

        except requests.exceptions.Timeout:
            logger.error("Lỗi: OpenAI API call timed out.")
            return None
        except requests.exceptions.RequestException as e:
             logger.error(f"Lỗi mạng hoặc API OpenAI: {e}")
             # Log response text if available for debugging
             if hasattr(e, 'response') and e.response is not None:
                 logger.error(f"Response status: {e.response.status_code}, text: {e.response.text[:500]}...")
             return None
        except Exception as e:
            logger.error(f"Lỗi không xác định khi gọi OpenAI API: {str(e)}", exc_info=True)
            return None

# --- PHẦN TEST CUỐI FILE (CẦN ĐIỀU CHỈNH ĐỂ KIỂM TRA JSON) ---
if __name__ == "__main__":
    print("--- Testing ScriptGenerator (JSON Output) ---")
    # Tạo bài báo giả để test
    test_article = {
        'title': 'AI Innovation in Healthcare',
        'content': 'Researchers have announced a breakthrough in AI technology for healthcare applications. The new AI system can efficiently diagnose complex medical conditions with high accuracy. Privacy concerns exist regarding patient data security and reduced human oversight. Early trials show 95% accuracy compared to 89% for doctors. Medical associations debate guidelines.',
        'source': 'Tech News',
        'language': 'en'
    }

    # Test
    try:
        generator = ScriptGenerator()

        # Test phong cách informative (sẽ yêu cầu JSON)
        print("\nTesting 'informative' style (expecting JSON)...")
        script_normal = generator.generate_script(test_article, "informative")

        if script_normal and isinstance(script_normal, dict) and 'scenes' in script_normal:
            print(f"SUCCESS: Generated 'informative' script.")
            print(f"Title: {script_normal.get('title')}")
            print(f"Number of scenes: {len(script_normal.get('scenes', []))}")
            # print("\nScenes:")
            # for scene in script_normal.get('scenes', [])[:3]: # Print first 3 scenes
            #     print(f"  - Scene {scene.get('number')}: {scene.get('content')}")
            # if len(script_normal.get('scenes', [])) > 3: print("  ...")
            # print("\nReconstructed Full Script (Optional):")
            # print(script_normal.get('full_script', 'N/A'))
        else:
            print("FAILED to generate 'informative' script or result is not in expected dict format.")
            # print(f"Result received: {script_normal}") # Print result for debugging

        # Test phong cách controversial (sẽ yêu cầu JSON)
        print("\nTesting 'controversial' style (expecting JSON)...")
        script_controversial = generator.generate_script(test_article, "controversial")

        if script_controversial and isinstance(script_controversial, dict) and 'scenes' in script_controversial:
             print(f"SUCCESS: Generated 'controversial' script.")
             print(f"Title: {script_controversial.get('title')}")
             print(f"Number of scenes: {len(script_controversial.get('scenes', []))}")
        else:
            print("FAILED to generate 'controversial' script or result is not in expected dict format.")
            # print(f"Result received: {script_controversial}")

        # Test tạo từ keyword (luôn yêu cầu JSON)
        print("\nTesting generation from keyword (expecting JSON)...")
        keyword_script = generator.generate_script_from_keyword("impact of social media on teenagers", "conversational", "en")

        if keyword_script and isinstance(keyword_script, dict) and 'scenes' in keyword_script:
            print(f"SUCCESS: Generated script from keyword.")
            print(f"Title: {keyword_script.get('title')}")
            print(f"Number of scenes: {len(keyword_script.get('scenes', []))}")
        else:
            print("FAILED to generate script from keyword or result is not in expected dict format.")
            # print(f"Result received: {keyword_script}")


    except ValueError as ve:
         print(f"Configuration Error (Missing API Key?): {ve}")
    except Exception as e:
        print(f"\n--- An error occurred during testing ---")
        logger.exception("Test failed") # Log traceback