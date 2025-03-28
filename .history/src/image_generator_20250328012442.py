# src/image_generator.py

import os
import requests
import logging
import time
import json
import random
import hashlib
import shutil
import glob
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# Thêm import cho OpenAI API key và các cấu hình khác
from config.credentials import SERPER_API_KEY, OPENAI_API_KEY
from config.settings import TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self):
        """Khởi tạo ImageGenerator với cấu hình Serper và OpenAI"""
        self.serper_api_key = SERPER_API_KEY
        if not self.serper_api_key:
            logger.error("Serper API key not found in credentials. Image search will likely fail.")
            # Cân nhắc raise lỗi nếu Serper là bắt buộc
            # raise ValueError("Serper API key is required.")

        # --- Cấu hình OpenAI ---
        self.openai_api_key = OPENAI_API_KEY
        if not self.openai_api_key:
            # Nếu không có key OpenAI, chỉ cảnh báo và vẫn chạy được với fallback
            logger.warning("OpenAI API key not found. Keyword extraction will use the basic method only.")
        self.openai_base_url = "https://api.openai.com/v1"
        self.openai_headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        # --- Kết thúc cấu hình OpenAI ---

        self.temp_dir = TEMP_DIR
        self.assets_dir = ASSETS_DIR
        self.width = VIDEO_SETTINGS["width"]
        self.height = VIDEO_SETTINGS["height"]

        # URL cho Serper.dev API
        self.serper_url = "https://google.serper.dev/images"
        self.serper_headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json"
        }

        # Tạo thư mục lưu trữ hình ảnh trong temp
        self.image_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(self.image_dir, exist_ok=True)

        # Tạo thư mục cache hình ảnh
        self.cache_dir = os.path.join(self.temp_dir, "image_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Tạo thư mục assets và fonts nếu chưa có
        os.makedirs(self.assets_dir, exist_ok=True)
        self.fonts_dir = os.path.join(self.assets_dir, "fonts")
        os.makedirs(self.fonts_dir, exist_ok=True)

        # Kiểm tra font
        self._check_and_download_fonts()

    # --- Hàm mới để gọi OpenAI API cho keywords ---
    def _call_openai_for_keywords(self, prompt):
        """Gọi OpenAI API để lấy từ khóa hình ảnh.

        Args:
            prompt (str): Prompt gửi đến OpenAI.

        Returns:
            str: Các từ khóa được đề xuất bởi OpenAI, hoặc None nếu có lỗi.
        """
        # Chỉ gọi API nếu có key
        if not self.openai_api_key:
            logger.warning("Skipping OpenAI call for keywords as API key is missing.")
            return None

        try:
            url = f"{self.openai_base_url}/chat/completions"

            payload = {
                "model": "gpt-4o", # Hoặc "gpt-3.5-turbo" nếu muốn tiết kiệm chi phí
                "messages": [
                    {"role": "system", "content": "You are an expert at identifying the most visually descriptive keywords from a text snippet for the purpose of finding relevant images. Output only the keywords, separated by spaces, max 5 words. Do not include explanations or introductory phrases."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5, # Giảm nhiệt độ để kết quả nhất quán hơn
                "max_tokens": 25   # Giới hạn token cho từ khóa ngắn gọn (tăng nhẹ để phòng trường hợp trả về dài hơn chút)
            }

            logger.debug(f"Calling OpenAI for keywords with prompt: {prompt[:100]}...")
            response = requests.post(url, headers=self.openai_headers, json=payload, timeout=20) # Thêm timeout

            if response.status_code == 200:
                data = response.json()
                if 'choices' in data and data['choices']:
                    keywords = data['choices'][0]['message']['content'].strip()
                    # Làm sạch kết quả: bỏ dấu ngoặc kép, dấu chấm, dấu hai chấm, #
                    keywords = keywords.replace('"', '').replace("'", '').replace(':', '').replace('#', '').rstrip('.').strip()
                    # Loại bỏ các câu giới thiệu nếu AI vẫn trả về
                    if keywords.lower().startswith("keywords:") or keywords.lower().startswith("here are the keywords:"):
                        keywords = keywords.split(':', 1)[-1].strip()

                    logger.info(f"OpenAI suggested keywords: '{keywords}'")
                    # Kiểm tra lại độ dài sau khi làm sạch
                    if len(keywords.split()) > 7:
                        logger.warning(f"OpenAI keywords too long, taking first 5: '{keywords}'")
                        keywords = ' '.join(keywords.split()[:5])
                    return keywords
                else:
                    logger.error(f"OpenAI API response missing choices: {data}")
                    return None
            else:
                logger.error(f"OpenAI API error for keywords: {response.status_code}, {response.text}")
                return None

        except requests.exceptions.Timeout:
            logger.error("OpenAI API call for keywords timed out.")
            return None
        except Exception as e:
            logger.error(f"Error calling OpenAI API for keywords: {str(e)}", exc_info=True) # Log traceback
            return None

    # --- Hàm trích xuất từ khóa cũ, đổi tên thành _basic ---
    def _extract_keywords_basic(self, text, max_words=10):
        """Trích xuất từ khóa chính từ văn bản (phương pháp cơ bản - fallback)."""
        if not text or not text.strip():
            return "news image" # Mặc định nếu text trống

        text = text.strip()
        words = text.split()

        if len(words) <= max_words:
            return text.rstrip('.').strip() # Bỏ dấu chấm cuối nếu có

        # Lấy câu đầu tiên hoàn chỉnh
        sentences = text.split('.')
        # Lọc bỏ các chuỗi rỗng có thể xuất hiện nếu text bắt đầu hoặc có nhiều dấu chấm liền nhau
        valid_sentences = [s.strip() for s in sentences if s.strip()]
        first_sentence = valid_sentences[0] if valid_sentences else text # Nếu không có câu hợp lệ, dùng cả text

        words_in_sentence = first_sentence.split()

        if len(words_in_sentence) <= max_words:
            return first_sentence.rstrip('.').strip()

        # Nếu câu đầu quá dài, cắt bớt
        return ' '.join(words_in_sentence[:max_words]).rstrip('.').strip()

    # --- Hàm trích xuất từ khóa mới, sử dụng OpenAI với fallback ---
    def _extract_keywords(self, text):
        """Trích xuất từ khóa tìm kiếm hình ảnh từ nội dung phân cảnh, ưu tiên dùng OpenAI.

        Args:
            text (str): Nội dung của phân cảnh.

        Returns:
            str: Các từ khóa để tìm kiếm hình ảnh.
        """
        if not text or not text.strip():
            logger.info("Empty scene content, using default keywords 'news image'.")
            return "news image"

        text_to_process = text.strip()

        # Chuẩn bị prompt cho OpenAI
        prompt = f"""
        Extract the best 3-5 visually descriptive keywords for searching images related to the following Vietnamese news scene content.
        Focus on the main subject, action, and specific location/entities if mentioned. Be concise.
        Output only the keywords in Vietnamese, separated by spaces.

        Content: "{text_to_process}"

        Keywords:
        """

        # Thử gọi OpenAI
        openai_keywords = self._call_openai_for_keywords(prompt)

        if openai_keywords:
            # Kiểm tra xem kết quả có vẻ hợp lệ không (không quá dài, không chứa hướng dẫn)
            if 1 < len(openai_keywords) < 100 and \
               "keyword" not in openai_keywords.lower() and \
               "content" not in openai_keywords.lower() and \
               "extract" not in openai_keywords.lower() and \
               len(openai_keywords.split()) <= 7:
                 logger.info(f"Using OpenAI generated keywords for scene: '{openai_keywords}'")
                 return openai_keywords
            else:
                 logger.warning(f"OpenAI returned potentially invalid keywords: '{openai_keywords}'. Falling back to basic method.")
                 # Log chi tiết hơn nếu cần debug
                 # logger.debug(f"Invalid OpenAI keywords details: Length={len(openai_keywords)}, Content='{openai_keywords}'")


        # Nếu gọi OpenAI thất bại hoặc kết quả không hợp lệ, sử dụng phương pháp cơ bản
        logger.info("Falling back to basic keyword extraction method.")
        basic_keywords = self._extract_keywords_basic(text_to_process) # Dùng max_words mặc định (10)
        logger.info(f"Using basic extracted keywords: '{basic_keywords}'")
        return basic_keywords

    def generate_images_for_script(self, script):
        """Tạo hình ảnh cho tất cả phân cảnh trong kịch bản với cơ chế dự phòng đa tầng

        Args:
            script (dict): Kịch bản với các khóa title, scenes, source, image_url (optional)

        Returns:
            list: Danh sách thông tin các hình ảnh đã tạo
        """
        images = []
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        # Tạo tên thư mục dựa trên tiêu đề (làm sạch) thay vì chỉ timestamp cho dễ nhận biết
        safe_title = "".join(c if c.isalnum() else "_" for c in script['title'][:30]).rstrip('_')
        project_folder_name = f"project_{safe_title}_{timestamp}"
        project_dir = os.path.join(self.image_dir, project_folder_name)
        os.makedirs(project_dir, exist_ok=True)

        logger.info(f"Bắt đầu tạo hình ảnh cho kịch bản: '{script['title']}' in folder: {project_folder_name}")

        # --- 1. Hình ảnh mở đầu ---
        try:
            intro_image = self._create_title_card(script['title'], script.get('source', ''), project_dir)
            images.append({
                "type": "intro",
                "path": intro_image,
                "duration": VIDEO_SETTINGS["intro_duration"]
            })
        except Exception as e:
             logger.error(f"Lỗi tạo ảnh intro: {e}", exc_info=True)
             # Có thể thêm ảnh fallback text đơn giản cho intro nếu cần

        # --- 2. Hình ảnh từ bài báo gốc (nếu có) ---
        source_image_url = script.get('image_url')
        if source_image_url:
            logger.info(f"Attempting to download source image: {source_image_url}")
            try:
                source_image_path = self._download_and_process_image(
                    source_image_url,
                    os.path.join(project_dir, "source_image.jpg")
                )
                if source_image_path:
                    images.append({
                        "type": "source",
                        "path": source_image_path,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "caption": "Hình ảnh từ bài báo gốc" # Có thể thêm chú thích nếu muốn
                    })
                    logger.info(f"Successfully added source image: {source_image_path}")
                else:
                    logger.warning(f"Failed to download or process source image from {source_image_url}")
            except Exception as e:
                logger.error(f"Lỗi khi tải hoặc xử lý hình ảnh nguồn {source_image_url}: {e}", exc_info=True)
        else:
             logger.info("No source image URL provided in the script.")


        # --- 3. Hình ảnh cho từng phân cảnh ---
        for scene in script.get('scenes', []):
            scene_number = scene.get('number', 'unknown')
            scene_content = scene.get('content', '')
            scene_image_path = None
            search_query_used = "N/A" # Khởi tạo giá trị mặc định

            try:
                logger.info(f"--- Processing Scene {scene_number} ---")
                if not scene_content:
                     logger.warning(f"Scene {scene_number} has empty content. Skipping image generation for this scene.")
                     continue # Bỏ qua nếu không có nội dung

                # --- Bước 3.1: Trích xuất từ khóa ---
                keywords = self._extract_keywords(scene_content)
                search_query = self._create_search_query(keywords, script['title'])
                search_query_used = search_query # Lưu lại query sẽ dùng

                # Tên file cho ảnh của scene
                scene_image_filename = f"scene_{scene_number}.jpg"
                target_image_path = os.path.join(project_dir, scene_image_filename)

                # --- Bước 3.2: Tìm ảnh (Multi-stage fallback) ---
                try:
                    # Giai đoạn 1: Kiểm tra cache hoặc tải từ Serper API (dùng query từ OpenAI/basic)
                    logger.info(f"Stage 1: Cache check / Serper API search (Query: '{search_query}')")
                    scene_image_path = self._get_cached_or_download_image(search_query, target_image_path)

                except Exception as e1:
                    logger.warning(f"Stage 1 failed for scene {scene_number}: {str(e1)}")

                    try:
                        # Giai đoạn 2: Thử tìm kiếm với từ khóa đơn giản hơn (luôn dùng basic extract)
                        logger.info(f"Stage 2: Trying simplified search")
                        simplified_keywords = self._extract_keywords_basic(scene_content, max_words=5) # Lấy 5 từ đầu
                        simplified_query = f"{simplified_keywords} news photo" # Query đơn giản
                        search_query_used = simplified_query # Cập nhật query đã dùng
                        logger.info(f"Simplified Query: '{simplified_query}'")
                        # Không cần cache cho query đơn giản này, tải trực tiếp
                        scene_image_path = self._search_and_download_image(simplified_query, target_image_path)

                    except Exception as e2:
                        logger.warning(f"Stage 2 failed for scene {scene_number}: {str(e2)}")

                        try:
                            # Giai đoạn 3: Sử dụng hình ảnh dự phòng cục bộ (assets/fallback_images)
                            logger.info(f"Stage 3: Using local fallback image")
                            scene_image_path = self._use_local_fallback_image(search_query, target_image_path) # Dùng query gốc để xác định theme

                        except Exception as e3:
                            logger.warning(f"Stage 3 failed for scene {scene_number}: {str(e3)}")

                            # Giai đoạn 4: Tạo hình ảnh text-only khi tất cả thất bại
                            logger.info(f"Stage 4: Creating text-only image for scene {scene_number}")
                            text_image_path = os.path.join(project_dir, f"text_scene_{scene_number}.png")
                            scene_image_path = self._create_text_only_image(
                                f"Scene {scene_number}:\n{scene_content[:150]}...", # Thêm số scene vào ảnh
                                text_image_path
                            )
                            search_query_used = "Text-only fallback" # Ghi nhận là ảnh text

                # --- Bước 3.3: Thêm thông tin ảnh vào danh sách ---
                if scene_image_path:
                    image_info = {
                        "type": "scene",
                        "number": scene_number,
                        "path": scene_image_path,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "content": scene_content,
                        "search_query": search_query_used # Lưu query thực sự đã dẫn đến ảnh (hoặc fallback)
                    }
                    images.append(image_info)
                    logger.info(f"Added image for scene {scene_number}: {scene_image_path}")
                else:
                    # Trường hợp cực hiếm: ngay cả tạo ảnh text cũng lỗi
                    logger.error(f"Failed to create ANY image for scene {scene_number}. Skipping.")
                    continue # Bỏ qua scene này

                # Delay nhẹ giữa các scene để tránh rate limit (nếu có)
                time.sleep(random.uniform(0.5, 1.5)) # Randomize delay

            except Exception as e:
                # Lỗi không mong muốn trong vòng lặp xử lý scene
                logger.error(f"Unhandled error processing scene {scene_number}: {str(e)}", exc_info=True)
                # Tạo ảnh fallback khẩn cấp
                try:
                    emergency_path = os.path.join(project_dir, f"emergency_fallback_{scene_number}.png")
                    fallback_image = self._create_text_only_image(
                        f"Error processing scene {scene_number}:\nPlease check logs.",
                        emergency_path
                    )
                    images.append({
                        "type": "emergency_fallback",
                        "number": scene_number,
                        "path": fallback_image,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "content": scene_content,
                        "search_query": "Emergency Fallback"
                    })
                    logger.warning(f"Created emergency fallback image for scene {scene_number}")
                except Exception as fallback_err:
                     logger.critical(f"CRITICAL: Failed even to create emergency fallback image for scene {scene_number}: {fallback_err}", exc_info=True)


        # --- 4. Hình ảnh kết thúc ---
        try:
            outro_image = self._create_outro_card(script['title'], script.get('source', ''), project_dir)
            images.append({
                "type": "outro",
                "path": outro_image,
                "duration": VIDEO_SETTINGS["outro_duration"]
            })
        except Exception as e:
            logger.error(f"Lỗi tạo ảnh outro: {e}", exc_info=True)
            # Có thể thêm ảnh fallback text đơn giản cho outro nếu cần

        logger.info(f"Finished generating images. Total images created: {len(images)}")

        # --- 5. Lưu thông tin metadata ---
        self._save_image_info(images, script['title'], project_dir)

        return images

    def _search_and_download_image(self, query, output_path):
        """Tìm kiếm và tải hình ảnh từ Google qua Serper.dev API.

        Args:
            query (str): Từ khóa tìm kiếm.
            output_path (str): Đường dẫn lưu hình ảnh.

        Returns:
            str: Đường dẫn đến hình ảnh đã tải và xử lý.

        Raises:
            Exception: Nếu không tìm thấy hoặc không tải được hình ảnh phù hợp.
        """
        if not self.serper_api_key:
             raise Exception("Serper API key is missing. Cannot search for images.")

        try:
            logger.info(f"Searching images with Serper: '{query}'")

            payload = json.dumps({
                "q": query,
                "gl": "vn",  # Thử khu vực Việt Nam
                "hl": "vi",  # Thử ngôn ngữ Việt
                "num": 20 # Lấy nhiều kết quả hơn để tăng cơ hội tìm được ảnh tốt
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

            # Lọc và sắp xếp ưu tiên ảnh phù hợp
            # Ưu tiên ảnh có kích thước lớn và tỷ lệ gần 16:9
            potential_images = []
            for img_data in image_results:
                width = img_data.get("width", 0)
                height = img_data.get("height", 0)
                url = img_data.get("imageUrl")
                if not url or width < 400 or height < 300: # Lọc bỏ ảnh quá nhỏ hoặc không có URL
                    continue

                ratio = width / height if height > 0 else 0
                target_ratio = self.width / self.height
                ratio_diff = abs(ratio - target_ratio)

                # Tính điểm dựa trên kích thước và tỷ lệ
                size_score = min(width * height / (1920*1080), 1.0) # Điểm kích thước (max 1.0)
                ratio_score = max(0, 1.0 - ratio_diff * 2) # Điểm tỷ lệ (càng gần target càng cao)
                score = (size_score * 0.6) + (ratio_score * 0.4) # Trọng số 60% size, 40% ratio

                potential_images.append({"url": url, "score": score, "width": width, "height": height})

            if not potential_images:
                 logger.warning(f"No suitable images found after filtering for query: '{query}'")
                 # Thử dùng lại kết quả gốc nếu đã lọc hết
                 potential_images = [{"url": img.get("imageUrl"), "score": 0, "width": img.get("width",0), "height": img.get("height",0)} for img in image_results if img.get("imageUrl")]
                 if not potential_images:
                      raise Exception("No images with URLs found even in raw results")


            # Sắp xếp theo điểm số giảm dần
            potential_images.sort(key=lambda x: x["score"], reverse=True)

            # Thử tải các ảnh tốt nhất trước
            max_attempts = min(5, len(potential_images)) # Thử tối đa 5 ảnh đầu tiên
            for i in range(max_attempts):
                selected_image = potential_images[i]
                image_url = selected_image["url"]
                logger.info(f"Attempting to download image {i+1}/{max_attempts} (Score: {selected_image['score']:.2f}, Size: {selected_image['width']}x{selected_image['height']}): {image_url[:70]}...")

                try:
                    downloaded_path = self._download_and_process_image(image_url, output_path)
                    if downloaded_path:
                        logger.info(f"Successfully downloaded and processed image {i+1}.")
                        return downloaded_path # Trả về ngay khi thành công
                except Exception as download_err:
                    logger.warning(f"Failed attempt {i+1} for {image_url}: {str(download_err)}")
                    # Không cần raise ở đây, vòng lặp sẽ thử ảnh tiếp theo

            # Nếu tất cả các nỗ lực tải đều thất bại
            logger.error(f"All {max_attempts} download attempts failed for query: '{query}'")
            raise Exception(f"Failed to download a suitable image after {max_attempts} attempts")

        except Exception as e:
            logger.error(f"Error during image search/download for query '{query}': {str(e)}", exc_info=True)
            raise # Re-raise lỗi để các tầng fallback xử lý

    def _download_and_process_image(self, image_url, output_path):
        """Tải, xác thực và xử lý (resize/crop) hình ảnh từ URL.

        Args:
            image_url (str): URL của hình ảnh.
            output_path (str): Đường dẫn để lưu hình ảnh đã xử lý.

        Returns:
            str: Đường dẫn đến hình ảnh đã xử lý thành công.

        Raises:
            Exception: Nếu tải, xác thực hoặc xử lý thất bại.
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8', # Thêm tiếng Việt
                'Referer': 'https://www.google.com/' # Giả lập referer
            }
            response = requests.get(image_url, headers=headers, timeout=20, stream=True) # stream=True để kiểm tra header trước
            response.raise_for_status() # Raise HTTPError cho bad status codes (4xx or 5xx)

            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                # Kiểm tra một số kiểu dữ liệu đặc biệt có thể chứa ảnh (như webp)
                if 'webp' in content_type or 'avif' in content_type:
                     logger.debug(f"Content-Type is '{content_type}', proceeding as image.")
                else:
                    raise Exception(f"Invalid Content-Type: {content_type}")

            # Đọc nội dung (có thể giới hạn kích thước nếu cần)
            # content_length = response.headers.get('Content-Length')
            # if content_length and int(content_length) > 10 * 1024 * 1024: # Giới hạn 10MB
            #      raise Exception(f"Image size exceeds limit: {content_length} bytes")

            image_data = response.content # Đọc toàn bộ nội dung vào bộ nhớ
            if not image_data:
                 raise Exception("Downloaded image data is empty")

            # Xác thực và mở ảnh
            try:
                image = Image.open(BytesIO(image_data))
                image.verify() # Xác thực cấu trúc file ảnh
                # Mở lại sau khi verify
                image = Image.open(BytesIO(image_data))
                # Chuyển đổi sang RGB để đảm bảo tính tương thích (loại bỏ alpha, palette)
                if image.mode != 'RGB':
                     image = image.convert('RGB')
            except Exception as img_err:
                raise Exception(f"Invalid or corrupted image data: {str(img_err)}")

            # Kiểm tra kích thước tối thiểu sau khi mở
            if image.width < 300 or image.height < 200:
                raise Exception(f"Image dimensions too small: {image.width}x{image.height}")

            # Điều chỉnh kích thước (resize và crop)
            processed_image = self._resize_image(image)

            # Lưu hình ảnh với chất lượng tốt
            processed_image.save(output_path, "JPEG", quality=90) # Lưu dưới dạng JPEG chất lượng cao
            logger.debug(f"Image saved to: {output_path}")
            return output_path

        except requests.exceptions.RequestException as req_err:
             raise Exception(f"Network error downloading {image_url}: {str(req_err)}")
        except Exception as e:
             # Log lỗi chi tiết hơn
             # logger.error(f"Error processing image {image_url}: {str(e)}", exc_info=True)
             # Ném lại lỗi để báo hiệu thất bại
             raise Exception(f"Failed to download/process image {image_url}: {str(e)}")


    def _validate_image(self, image_data):
        """Kiểm tra xem dữ liệu có phải là hình ảnh hợp lệ không (ít dùng hơn khi đã tích hợp vào _download_and_process_image)"""
        try:
            img = Image.open(BytesIO(image_data))
            img.verify()
            # Mở lại để kiểm tra load
            img = Image.open(BytesIO(image_data))
            img.load()
            # Kiểm tra định dạng thông dụng và kích thước tối thiểu
            if img.format not in ['JPEG', 'PNG', 'GIF', 'BMP', 'WEBP'] or img.width < 100 or img.height < 100:
                return False
            return True
        except Exception:
            # logger.warning(f"Validation failed: {e}") # Giảm log thừa
            return False

    def _is_good_image_size(self, image_data):
        """Kiểm tra xem kích thước có phù hợp không (ít dùng hơn khi đã tích hợp vào _search_and_download)"""
        width = image_data.get("width", 0)
        height = image_data.get("height", 0)
        if width >= 800 and height >= 600: return True
        if width > 0 and height > 0:
            ratio = width / height
            target_ratio = 16 / 9
            if 0.8 * target_ratio <= ratio <= 1.2 * target_ratio: return True
        return False

    def _get_cached_or_download_image(self, query, output_path):
        """Kiểm tra cache trước, nếu không có thì tìm và tải, sau đó lưu vào cache."""
        query_hash = hashlib.md5(query.encode()).hexdigest()
        cache_filename = f"{query_hash}.jpg"
        cache_path = os.path.join(self.cache_dir, cache_filename)

        if os.path.exists(cache_path):
            # Kiểm tra xem file cache có hợp lệ không (kích thước > 0)
            if os.path.getsize(cache_path) > 1024: # Hơn 1KB là có vẻ ổn
                logger.info(f"Using cached image for query: '{query}'")
                try:
                    shutil.copy(cache_path, output_path)
                    return output_path
                except Exception as e:
                    logger.warning(f"Error copying from cache {cache_path}: {e}. Will re-download.")
            else:
                logger.warning(f"Invalid cache file found (size 0): {cache_path}. Will re-download.")
                try:
                     os.remove(cache_path) # Xóa file cache lỗi
                except OSError:
                     pass


        # Nếu không có trong cache hoặc cache lỗi, tải mới
        logger.info(f"Image not in cache or cache invalid for query: '{query}'. Searching and downloading.")
        try:
            downloaded_path = self._search_and_download_image(query, output_path)

            # Lưu vào cache nếu tải thành công
            try:
                shutil.copy(downloaded_path, cache_path)
                logger.info(f"Saved downloaded image to cache: {cache_path}")
            except Exception as e:
                logger.warning(f"Failed to save image to cache {cache_path}: {e}")

            return downloaded_path
        except Exception as e:
            logger.error(f"Failed to download image for caching (query: '{query}'): {str(e)}")
            raise # Ném lại lỗi để fallback tiếp tục

    def _use_local_fallback_image(self, query, output_path):
        """Sử dụng hình ảnh dự phòng từ thư mục assets/fallback_images."""
        fallback_base_dir = os.path.join(self.assets_dir, "fallback_images")
        if not os.path.exists(fallback_base_dir) or not os.listdir(fallback_base_dir):
            os.makedirs(fallback_base_dir, exist_ok=True)
            logger.warning(f"Fallback image directory is empty or missing: {fallback_base_dir}")
            raise Exception("Local fallback directory is empty.")

        # Logic xác định chủ đề (có thể cải thiện bằng NLP đơn giản nếu cần)
        themes = {
            "tin_tuc_chung": ["tin", "báo", "thời sự", "news", "chung"],
            "cong_nghe": ["công nghệ", "máy tính", "điện thoại", "ai", "robot", "tech"],
            "kinh_te": ["kinh tế", "tài chính", "thị trường", "cổ phiếu", "dollar", "economy"],
            "xa_hoi": ["xã hội", "người dân", "cuộc sống", "văn hóa", "society"],
            "the_thao": ["thể thao", "bóng đá", "cầu thủ", "sports"],
            "giao_thong": ["giao thông", "tai nạn", "xe cộ", "đường", "traffic"],
            "thien_tai": ["thiên tai", "bão", "lũ", "động đất", "disaster", "cháy"], # Thêm cháy
            "y_te": ["y tế", "bệnh viện", "bác sĩ", "dịch bệnh", "health"],
        }
        best_theme = "tin_tuc_chung" # Mặc định
        best_score = 0
        query_lower = query.lower()

        for theme, keywords in themes.items():
            score = sum(1 for keyword in keywords if keyword in query_lower)
            if score > best_score:
                best_score = score
                best_theme = theme
            # Nếu query chứa chính tên theme
            if theme.replace("_", " ") in query_lower and score == 0:
                 best_theme = theme
                 break # Ưu tiên tên theme

        theme_dir = os.path.join(fallback_base_dir, best_theme)
        logger.info(f"Selected fallback theme: {best_theme}")

        # Nếu thư mục theme không có, dùng thư mục gốc fallback
        if not os.path.exists(theme_dir) or not os.listdir(theme_dir):
            logger.warning(f"Theme directory '{theme_dir}' not found or empty. Using base fallback directory.")
            theme_dir = fallback_base_dir

        # Lấy ảnh ngẫu nhiên từ thư mục đã chọn
        image_files = glob.glob(os.path.join(theme_dir, "*.jpg")) + \
                      glob.glob(os.path.join(theme_dir, "*.jpeg")) + \
                      glob.glob(os.path.join(theme_dir, "*.png"))

        if not image_files:
            logger.error(f"No fallback images found in '{theme_dir}'. Cannot use local fallback.")
            raise Exception(f"No images in fallback directory: {theme_dir}")

        selected_image_path = random.choice(image_files)
        logger.info(f"Using local fallback image: {selected_image_path}")

        # Sao chép và xử lý kích thước ảnh fallback
        try:
            img = Image.open(selected_image_path)
            if img.mode != 'RGB':
                 img = img.convert('RGB')
            processed_img = self._resize_image(img)
            processed_img.save(output_path, "JPEG", quality=85)
            return output_path
        except Exception as e:
            logger.error(f"Error processing local fallback image {selected_image_path}: {e}", exc_info=True)
            raise Exception(f"Failed to process fallback image {selected_image_path}")


    def _create_text_only_image(self, text_content, output_path):
        """Tạo hình ảnh chỉ chứa văn bản."""
        try:
            # Tạo màu nền gradient dựa trên hash của nội dung
            text_hash = hashlib.md5(text_content.encode()).hexdigest()
            r1, g1, b1 = int(text_hash[0:2], 16), int(text_hash[2:4], 16), int(text_hash[4:6], 16)
            r2, g2, b2 = int(text_hash[6:8], 16), int(text_hash[8:10], 16), int(text_hash[10:12], 16)

            # Đảm bảo màu không quá sáng hoặc quá tối
            r1, g1, b1 = max(30, r1), max(30, g1), max(30, b1)
            r2, g2, b2 = min(220, r2), min(220, g2), min(220, b2)

            img = Image.new('RGB', (self.width, self.height))
            draw = ImageDraw.Draw(img)

            # Vẽ gradient nền
            for y in range(self.height):
                ratio = y / self.height
                r = int(r1 + (r2 - r1) * ratio)
                g = int(g1 + (g2 - g1) * ratio)
                b = int(b1 + (b2 - b1) * ratio)
                draw.line([(0, y), (self.width, y)], fill=(r, g, b))

            # Chọn font và kích thước
            font_size = 45 if len(text_content) < 100 else 40
            font = self._get_font(size=font_size)
            if not font: # Xử lý trường hợp không load được font nào
                 raise Exception("Cannot load any font for text image")


            # Wrap text
            margin = 80
            wrapped_text = self._wrap_text(text_content, font, self.width - 2 * margin)

            # Tính chiều cao tổng cộng của text
            line_height = font_size * 1.3 # Ước lượng chiều cao dòng
            total_text_height = len(wrapped_text) * line_height

            # Tính vị trí bắt đầu vẽ (căn giữa)
            start_y = (self.height - total_text_height) / 2

            # Vẽ từng dòng text với viền nhẹ để dễ đọc
            text_color = (255, 255, 255) # Chữ trắng
            outline_color = (0, 0, 0) # Viền đen

            for i, line in enumerate(wrapped_text):
                 # Tính toán vị trí x để căn giữa dòng
                try:
                    # Sử dụng textbbox để lấy kích thước chính xác hơn
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_width = bbox[2] - bbox[0]
                    # text_height = bbox[3] - bbox[1] # Ít dùng hơn khi đã có line_height
                except AttributeError:
                     # Fallback cho Pillow cũ hoặc font không hỗ trợ bbox
                    text_width = len(line) * (font_size * 0.6) # Ước tính

                x = (self.width - text_width) / 2
                y = start_y + i * line_height

                # Vẽ viền (vẽ text 4 lần với offset nhỏ)
                for dx, dy in [( -1, -1), ( -1, 1), ( 1, -1), ( 1, 1)]:
                     draw.text((x + dx, y + dy), line, font=font, fill=outline_color)
                # Vẽ text chính
                draw.text((x, y), line, font=font, fill=text_color)

            img.save(output_path)
            logger.info(f"Created text-only image: {output_path}")
            return output_path
        except Exception as e:
             logger.error(f"Failed to create text-only image: {e}", exc_info=True)
             raise # Ném lại lỗi

    def _create_title_card(self, title, source, project_dir):
        """Tạo hình ảnh tiêu đề (intro)."""
        output_path = os.path.join(project_dir, "intro_title.png")
        try:
            img = Image.new('RGB', (self.width, self.height), color=(20, 40, 80)) # Màu nền xanh đậm
            draw = ImageDraw.Draw(img)
            title_font = self._get_font(size=65)
            source_font = self._get_font(size=35)
            if not title_font or not source_font: raise Exception("Cannot load fonts for title card")


            margin = 100
            # Vẽ tiêu đề (wrap text)
            title_wrapped = self._wrap_text(title, title_font, self.width - 2 * margin)
            title_line_height = 75
            total_title_height = len(title_wrapped) * title_line_height
            title_y_start = (self.height - total_title_height) / 2 - 50 # Nâng lên một chút

            for i, line in enumerate(title_wrapped):
                bbox = draw.textbbox((0, 0), line, font=title_font)
                text_width = bbox[2] - bbox[0]
                x = (self.width - text_width) / 2
                y = title_y_start + i * title_line_height
                 # Viền nhẹ
                draw.text((x+1, y+1), line, font=title_font, fill=(0,0,0, 128))
                draw.text((x, y), line, font=title_font, fill=(255, 255, 255)) # Chữ trắng

            # Vẽ nguồn (nếu có)
            if source:
                source_text = f"Nguồn: {source}"
                bbox = draw.textbbox((0,0), source_text, font=source_font)
                source_width = bbox[2] - bbox[0]
                source_x = (self.width - source_width) / 2
                source_y = self.height - 80 # Gần đáy
                draw.text((source_x+1, source_y+1), source_text, font=source_font, fill=(0,0,0,100))
                draw.text((source_x, source_y), source_text, font=source_font, fill=(200, 200, 200)) # Xám nhạt

            img.save(output_path)
            logger.info(f"Created intro title card: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to create intro card: {e}", exc_info=True)
            # Fallback: Tạo ảnh text đơn giản nếu lỗi
            return self._create_text_only_image(f"Intro:\n{title[:100]}...", output_path)


    def _create_outro_card(self, title, source, project_dir):
        """Tạo hình ảnh kết thúc (outro)."""
        output_path = os.path.join(project_dir, "outro.png")
        try:
            img = Image.new('RGB', (self.width, self.height), color=(60, 20, 80)) # Màu nền tím đậm
            draw = ImageDraw.Draw(img)
            main_font = self._get_font(size=60)
            sub_font = self._get_font(size=40)
            if not main_font or not sub_font: raise Exception("Cannot load fonts for outro card")


            # Vẽ "Cảm ơn đã theo dõi"
            thank_you_text = "Cảm ơn đã theo dõi"
            bbox = draw.textbbox((0,0), thank_you_text, font=main_font)
            text_width = bbox[2] - bbox[0]
            x = (self.width - text_width) / 2
            y = self.height / 2 - 100 # Phần trên của trung tâm
            draw.text((x+1, y+1), thank_you_text, font=main_font, fill=(0,0,0, 128))
            draw.text((x, y), thank_you_text, font=main_font, fill=(255, 255, 255))

            # Vẽ lại tiêu đề (ngắn gọn)
            short_title = title[:80] + ('...' if len(title) > 80 else '')
            title_wrapped = self._wrap_text(short_title, sub_font, self.width - 200)
            line_height = 50
            start_y = self.height / 2 + 20 # Ngay dưới dòng cảm ơn

            for i, line in enumerate(title_wrapped):
                bbox = draw.textbbox((0,0), line, font=sub_font)
                text_width = bbox[2] - bbox[0]
                x = (self.width - text_width) / 2
                y = start_y + i * line_height
                draw.text((x+1, y+1), line, font=sub_font, fill=(0,0,0, 100))
                draw.text((x, y), line, font=sub_font, fill=(200, 200, 200))

            img.save(output_path)
            logger.info(f"Created outro card: {output_path}")
            return output_path
        except Exception as e:
             logger.error(f"Failed to create outro card: {e}", exc_info=True)
             return self._create_text_only_image("Cảm ơn đã theo dõi!", output_path)

    # Hàm này có thể không cần nữa vì đã tích hợp vào các stage fallback
    # def _create_fallback_image(self, scene_number, content, project_dir): ...

    def _resize_image(self, image):
        """Điều chỉnh kích thước và crop ảnh để phù hợp với khung hình video."""
        try:
            target_ratio = self.width / self.height
            img_ratio = image.width / image.height

            if abs(img_ratio - target_ratio) < 0.01:
                # Nếu tỷ lệ đã gần đúng, chỉ cần resize
                return image.resize((self.width, self.height), Image.Resampling.LANCZOS)

            if img_ratio > target_ratio:
                # Hình ảnh rộng hơn target (landscapeish) -> crop hai bên
                new_width = int(image.height * target_ratio)
                left = (image.width - new_width) // 2
                right = left + new_width
                crop_box = (left, 0, right, image.height)
            else:
                # Hình ảnh cao hơn target (portraitish) -> crop trên dưới
                new_height = int(image.width / target_ratio)
                top = (image.height - new_height) // 2
                # Cố gắng giữ phần giữa hoặc phần trên của ảnh (quan trọng hơn)
                # Có thể làm phức tạp hơn để phát hiện khuôn mặt/chủ thể chính
                # top = max(0, (image.height - new_height) // 3) # Ưu tiên giữ 1/3 trên
                bottom = top + new_height
                crop_box = (0, top, image.width, bottom)

            cropped_image = image.crop(crop_box)
            return cropped_image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        except Exception as e:
             logger.error(f"Error resizing image: {e}", exc_info=True)
             # Trả về ảnh gốc nếu resize lỗi? Hoặc ném lỗi
             # return image # Hoặc raise
             raise # Ném lỗi để báo hiệu xử lý resize thất bại

    def _create_search_query(self, keywords, title):
        """Tạo truy vấn tìm kiếm tối ưu cho Serper API."""
        # Làm sạch keywords đầu vào
        keywords = keywords.replace('"', '').replace("'", '').replace(':', '').replace('#', '').strip()
        keywords = ' '.join(keywords.split()[:7]) # Giới hạn lại 7 từ

        # Lấy một vài từ khóa chính từ tiêu đề (nếu có)
        title_keywords = ""
        if title:
             # Đơn giản hóa: lấy 2-3 từ đầu tiên của title
             title_words = title.split()[:3]
             # Loại bỏ các từ nối phổ biến nếu chúng ở đầu
             common_words = {"là", "của", "và", "ở", "tại", "một", "the", "a", "in", "on", "at"}
             title_keywords = ' '.join(w for w in title_words if w.lower() not in common_words)


        # Kết hợp và thêm hậu tố
        # Ưu tiên keywords từ AI/basic trước
        if len(keywords.split()) >= 3: # Nếu keywords đủ dài
             query = f"{keywords} {title_keywords}"
        elif title_keywords: # Nếu keywords ngắn nhưng có title
             query = f"{title_keywords} {keywords}"
        else: # Nếu cả hai đều ngắn/trống
             query = keywords if keywords else "tin tức hình ảnh" # Fallback cuối

        # Thêm hậu tố tìm kiếm
        # suffix = random.choice(["photo", "image", "illustration", "news photo", "hình ảnh", "ảnh"])
        suffix = "news photo hd" # Hoặc "hình ảnh tin tức"
        final_query = f"{query.strip()} {suffix}".strip()

        # Giới hạn độ dài query cuối cùng (Serper có thể có giới hạn)
        return final_query[:150]


    def _wrap_text(self, text, font, max_width):
        """Chia văn bản thành các dòng phù hợp với chiều rộng tối đa."""
        if not text: return []
        if not font: return [text] # Trả về nguyên bản nếu không có font

        lines = []
        words = text.split()
        if not words: return []

        current_line = words[0]
        for word in words[1:]:
            test_line = f"{current_line} {word}"
            try:
                # Ưu tiên textbbox nếu có
                if hasattr(draw := ImageDraw.Draw(Image.new('RGB', (1,1))), 'textbbox'):
                    bbox = draw.textbbox((0,0), test_line, font=font)
                    line_width = bbox[2] - bbox[0]
                # Fallback cho getsize (Pillow cũ)
                elif hasattr(font, 'getsize'):
                    line_width, _ = font.getsize(test_line)
                else:
                    # Ước tính rất thô nếu không có cả hai
                    line_width = len(test_line) * (font.size * 0.6 if hasattr(font, 'size') else 10)
            except Exception:
                 # Ước tính nếu có lỗi khi lấy kích thước
                 line_width = len(test_line) * 10

            if line_width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word

        lines.append(current_line) # Thêm dòng cuối cùng
        return lines

    def _check_and_download_fonts(self):
        """Kiểm tra sự tồn tại của font mong muốn."""
        # Chỉ kiểm tra và cảnh báo, không tự động tải
        preferred_font = "Roboto-Bold.ttf" # Hoặc font bạn muốn dùng
        font_path = os.path.join(self.fonts_dir, preferred_font)

        if not os.path.exists(font_path):
            logger.warning(f"Preferred font '{preferred_font}' not found in '{self.fonts_dir}'.")
            logger.warning(f"Please download '{preferred_font}' (or another TTF font) and place it in the assets/fonts directory for best results.")
            logger.warning("The script will attempt to use system fonts or a default font.")
        else:
             logger.info(f"Preferred font '{preferred_font}' found.")


    def _get_font(self, size=40):
        """Lấy đối tượng font, ưu tiên font trong assets, rồi đến hệ thống, cuối cùng là mặc định."""
        preferred_font_name = "Roboto-Bold.ttf" # Font bạn muốn dùng nhất
        preferred_font_path = os.path.join(self.fonts_dir, preferred_font_name)

        # 1. Thử font ưu tiên
        if os.path.exists(preferred_font_path):
            try:
                return ImageFont.truetype(preferred_font_path, size)
            except Exception as e:
                logger.warning(f"Could not load preferred font {preferred_font_path}: {e}")

        # 2. Thử các font hệ thống phổ biến (tên file hoặc tên font)
        system_fonts = [
            # Windows
            'arial.ttf', 'arialbd.ttf', 'tahoma.ttf', 'tahomabd.ttf', 'verdana.ttf', 'verdanab.ttf', 'segoeui.ttf', 'seguisb.ttf',
            # MacOS
            'Arial.ttf', 'Helvetica.ttc', 'HelveticaNeue.ttc',
            # Linux (common names)
            'DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Regular.ttf', 'LiberationSans-Bold.ttf',
            'NotoSans-Regular.ttf', 'NotoSans-Bold.ttf' # Google Noto
        ]
        for font_attempt in system_fonts:
            try:
                # truetype có thể tìm theo tên file hoặc tên font family
                return ImageFont.truetype(font_attempt, size)
            except IOError: # Lỗi phổ biến nhất là không tìm thấy font
                continue
            except Exception as e: # Lỗi khác (font hỏng?)
                logger.debug(f"Error trying system font '{font_attempt}': {e}")
                continue

        # 3. Nếu không tìm thấy gì, dùng font mặc định của Pillow
        logger.warning(f"No suitable preferred or system font found. Using Pillow's default font (may have limited character support or fixed size).")
        try:
            # Thử load với size (Pillow >= 9.0.0)
            return ImageFont.load_default(size=size)
        except TypeError:
             # Fallback cho Pillow cũ
            return ImageFont.load_default()
        except Exception as e:
            logger.error(f"CRITICAL: Failed to load even the default Pillow font: {e}")
            return None # Trường hợp tệ nhất

    def _save_image_info(self, images, title, project_dir):
        """Lưu thông tin chi tiết về các hình ảnh đã tạo vào file JSON."""
        if not images:
             logger.warning("No images were generated, skipping image_info.json creation.")
             return

        image_metadata = []
        for img in images:
            img_copy = img.copy()
            # Tạo đường dẫn tương đối từ thư mục gốc của project_dir
            try:
                 # Giả sử project_dir là /path/to/temp/images/project_xyz
                 # và img['path'] là /path/to/temp/images/project_xyz/scene_1.jpg
                 # Chúng ta muốn lưu 'scene_1.jpg'
                 rel_path = os.path.relpath(img['path'], project_dir)
                 img_copy['relative_path'] = rel_path
            except ValueError: # Nếu đường dẫn không cùng ổ đĩa (hiếm khi xảy ra ở đây)
                 img_copy['relative_path'] = os.path.basename(img['path']) # Fallback lấy tên file

            # Có thể xóa bớt các trường không cần thiết trong JSON
            # del img_copy['path'] # Xóa path tuyệt đối nếu không cần

            image_metadata.append(img_copy)

        output_data = {
            'project_title': title,
            'creation_timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'project_folder': os.path.basename(project_dir),
            'total_images': len(image_metadata),
            'video_dimensions': f"{self.width}x{self.height}",
            'images': image_metadata
        }

        output_file = os.path.join(project_dir, "image_info.json")

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=4)
            logger.info(f"Saved image metadata to: {output_file}")
        except Exception as e:
            logger.error(f"Failed to save image metadata: {e}", exc_info=True)


# --- Test block ---
if __name__ == "__main__":
    print("--- Running ImageGenerator Test ---")

    # Script giả lập tiếng Việt để test
    test_script = {
        'title': 'Bão số 5 đổ bộ gây mưa lớn và gió giật mạnh ở miền Trung',
        'full_script': """#SCENE 1#
        Bão số 5 (tên quốc tế là Noru) đã chính thức đổ bộ vào đất liền các tỉnh miền Trung Việt Nam vào sáng sớm nay.
        #SCENE 2#
        Tại Đà Nẵng và Quảng Nam, ghi nhận có mưa rất lớn và gió giật cấp 10-12, gây tốc mái nhiều nhà dân và làm cây cối gãy đổ.
        #SCENE 3#
        Hiện tại, nhiều khu vực đang bị mất điện trên diện rộng. Chính quyền địa phương đang nỗ lực khắc phục hậu quả.
        #SCENE 4#
        Người dân được khuyến cáo không ra khỏi nhà trong thời điểm này để đảm bảo an toàn. Các chuyến bay đến và đi từ khu vực bị ảnh hưởng tạm thời bị hủy.
        """,
        'source': 'Báo Tuổi Trẻ',
        'image_url': 'https://example.com/invalid_or_no_image.jpg', # URL ảnh nguồn (có thể không tồn tại để test fallback)
        'scenes': [
            {
                'number': 1,
                'content': 'Bão số 5 (tên quốc tế là Noru) đã chính thức đổ bộ vào đất liền các tỉnh miền Trung Việt Nam vào sáng sớm nay.'
            },
            {
                'number': 2,
                'content': 'Tại Đà Nẵng và Quảng Nam, ghi nhận có mưa rất lớn và gió giật cấp 10-12, gây tốc mái nhiều nhà dân và làm cây cối gãy đổ.'
            },
             {
                'number': 3,
                'content': 'Hiện tại, nhiều khu vực đang bị mất điện trên diện rộng. Chính quyền địa phương đang nỗ lực khắc phục hậu quả.'
            },
            { # Thêm scene với nội dung hơi khác
                'number': 4,
                'content': 'Người dân nên ở trong nhà. Nhiều chuyến bay bị hủy bỏ do thời tiết xấu.'
            },
            { # Scene với nội dung rất chung chung để test fallback
                 'number': 5,
                 'content': 'Đây là một bản tin cập nhật.'
            }
        ]
    }

    # --- KIỂM TRA API KEYS ---
    if not OPENAI_API_KEY:
        print("\n*** WARNING: OPENAI_API_KEY is not configured. OpenAI keyword extraction will be skipped. ***\n")
    if not SERPER_API_KEY:
         print("\n*** WARNING: SERPER_API_KEY is not configured. Image search via Serper will fail. Ensure fallback images exist. ***\n")
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
            for img_info in images_list:
                type_info = f"Scene {img_info['number']}" if img_info['type'] == 'scene' else img_info['type'].upper()
                query_info = f" (Query: '{img_info.get('search_query', 'N/A')}')" if 'search_query' in img_info else ""
                path_info = img_info.get('path', 'Path missing')
                print(f"- {type_info}: {path_info}{query_info}")

            # Tìm thư mục project vừa tạo
            if images_list:
                 project_dir = os.path.dirname(images_list[0]['path'])
                 print(f"\nProject files saved in: {project_dir}")
                 info_file = os.path.join(project_dir, "image_info.json")
                 if os.path.exists(info_file):
                      print(f"Metadata saved in: {info_file}")
                 else:
                      print("Metadata file (image_info.json) was not created.")

        else:
            print("Image generation process returned an empty list.")

    except Exception as e:
        print(f"\n--- An error occurred during the test ---")
        logging.exception("Test execution failed") # Log lỗi đầy đủ với traceback
        print(f"Error details: {str(e)}")

    end_time = time.time()
    print(f"\n--- Test finished in {end_time - start_time:.2f} seconds ---")