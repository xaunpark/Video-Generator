def _check_and_download_fonts(self):
        """Kiểm tra font và tải về nếu cần"""
        # Đường dẫn đến file font
        font_path = os.path.join(self.fonts_dir, "Roboto-Bold.ttf")
        
        # Nếu font chưa tồn tại, thử tải về
        if not os.path.exists(font_path):
            logger.warning(f"Font không tồn tại: {font_path}")
            try:
                # URL cho font Roboto Bold từ Google Fonts
                font_url = "https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Bold.ttf"
                logger.info(f"Đang tải font từ: {font_url}")
                
                response = requests.get(font_url, timeout=15)
                if response.status_code == 200:
                    with open(font_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"Đã tải font thành công: {font_path}")
                else:
                    logger.error(f"Không thể tải font. Mã trạng thái: {response.status_code}")
                    logger.warning("Vui lòng tải font Roboto-Bold.ttf từ fonts.google.com và đặt vào thư mục assets/fonts")
            except Exception as e:
                logger.error(f"Lỗi khi tải font: {str(e)}")
                logger.warning("Vui lòng tải font Roboto-Bold.ttf từ fonts.google.com và đặt vào thư mục assets/fonts")# src/image_generator.py
import os
import requests
import logging
import time
import json
import random
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import base64
import re
from urllib.parse import urlparse
from config.credentials import SERPER_API_KEY, OPENAI_API_KEY
from config.settings import TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self):
        self.serper_api_key = SERPER_API_KEY
        self.openai_api_key = OPENAI_API_KEY
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
        
        # URL cho OpenAI DALL-E API
        self.dalle_url = "https://api.openai.com/v1/images/generations"
        self.dalle_headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        
        # Tạo thư mục lưu trữ hình ảnh trong temp
        self.image_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(self.image_dir, exist_ok=True)
        
        # Tạo thư mục stock images để lưu trữ hình ảnh dự phòng
        self.stock_images_dir = os.path.join(self.assets_dir, "stock_images")
        os.makedirs(self.stock_images_dir, exist_ok=True)
        
        # Tạo thư mục fonts nếu chưa có
        self.fonts_dir = os.path.join(self.assets_dir, "fonts")
        os.makedirs(self.fonts_dir, exist_ok=True)
        
        # Kiểm tra và tải font nếu chưa có
        self._check_and_download_fonts()
        
        # Chuẩn bị hình ảnh dự phòng
        self._prepare_stock_images()
        
        # Cờ để kiểm soát việc sử dụng DALL-E khi Serper không thành công
        self.use_dalle_fallback = True  # Đặt thành False nếu bạn không muốn sử dụng DALL-E
    
    def generate_images_for_script(self, script):
        """Tạo hình ảnh cho tất cả phân cảnh trong kịch bản
        
        Args:
            script (dict): Kịch bản với các khóa title, scenes, source
            
        Returns:
            list: Danh sách thông tin các hình ảnh đã tạo
        """
        images = []
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        project_dir = os.path.join(self.image_dir, f"project_{timestamp}")
        os.makedirs(project_dir, exist_ok=True)
        
        logger.info(f"Bắt đầu tạo hình ảnh cho kịch bản: {script['title']}")
        
        # Tạo hình ảnh mở đầu với tiêu đề
        intro_image = self._create_title_card(script['title'], script.get('source', ''), project_dir)
        images.append({
            "type": "intro",
            "path": intro_image,
            "duration": VIDEO_SETTINGS["intro_duration"]
        })
        
        # Kiểm tra xem có hình ảnh từ bài báo gốc không
        source_image_url = script.get('image_url', None)
        if source_image_url:
            try:
                source_image_path = self._download_and_process_image(
                    source_image_url, 
                    os.path.join(project_dir, "source_image.jpg")
                )
                
                # Thêm hình ảnh nguồn (nếu tải thành công)
                if source_image_path:
                    images.append({
                        "type": "source",
                        "path": source_image_path,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "caption": "Hình ảnh từ bài báo gốc"
                    })
            except Exception as e:
                logger.error(f"Lỗi khi tải hình ảnh nguồn: {str(e)}")
        
        # Tạo hình ảnh cho từng phân cảnh
        for scene in script['scenes']:
            try:
                scene_number = scene['number']
                logger.info(f"Đang tạo hình ảnh cho phân cảnh {scene_number}")
                
                # Tên file
                scene_image_filename = f"scene_{scene_number}.jpg"
                scene_image_path = os.path.join(project_dir, scene_image_filename)
                
                # Trích xuất từ khóa
                keywords = self._extract_keywords(scene['content'])
                search_query = self._create_search_query(keywords, script['title'])
                
                # Cờ để theo dõi việc tạo hình ảnh thành công hay không
                image_created = False
                image_info = None
                
                # Phương pháp 1: Sử dụng Serper và thử tải trực tiếp
                try:
                    # Tìm hình ảnh qua Serper.dev API
                    scene_image = self._search_and_download_image(search_query, scene_image_path)
                    
                    # Kiểm tra xem file có tồn tại và có kích thước hợp lệ không
                    if os.path.exists(scene_image) and os.path.getsize(scene_image) > 1000:
                        # Thêm chú thích cho hình ảnh
                        caption = self._create_caption(scene['content'])
                        captioned_image = self._add_caption_to_image(scene_image, caption, project_dir)
                        
                        image_info = {
                            "type": "scene",
                            "number": scene_number,
                            "path": captioned_image,
                            "duration": VIDEO_SETTINGS["image_duration"],
                            "content": scene['content'],
                            "search_query": search_query,
                            "source": "serper"
                        }
                        image_created = True
                    else:
                        logger.warning(f"Hình ảnh tải về không hợp lệ hoặc quá nhỏ: {scene_image}")
                        raise Exception("Invalid image downloaded")
                        
                except Exception as e:
                    logger.warning(f"Lỗi khi tìm hình ảnh từ Serper cho phân cảnh {scene_number}: {str(e)}")
                
                # Phương pháp 2: Thử sử dụng DALL-E nếu Serper thất bại và DALL-E được bật
                if not image_created and self.use_dalle_fallback and self.openai_api_key:
                    try:
                        logger.info(f"Thử tạo hình ảnh bằng DALL-E cho phân cảnh {scene_number}")
                        dalle_prompt = self._create_dalle_prompt(scene['content'], script['title'])
                        dalle_image_path = os.path.join(project_dir, f"dalle_scene_{scene_number}.png")
                        
                        # Gọi DALL-E API để tạo hình ảnh
                        dalle_result = self._generate_image_with_dalle(dalle_prompt, dalle_image_path)
                        
                        if dalle_result:
                            # Thêm chú thích cho hình ảnh
                            caption = self._create_caption(scene['content'])
                            captioned_image = self._add_caption_to_image(dalle_result, caption, project_dir)
                            
                            image_info = {
                                "type": "scene",
                                "number": scene_number,
                                "path": captioned_image,
                                "duration": VIDEO_SETTINGS["image_duration"],
                                "content": scene['content'],
                                "dalle_prompt": dalle_prompt,
                                "source": "dalle"
                            }
                            image_created = True
                        else:
                            logger.warning(f"Không thể tạo hình ảnh với DALL-E cho phân cảnh {scene_number}")
                    except Exception as e:
                        logger.warning(f"Lỗi khi sử dụng DALL-E cho phân cảnh {scene_number}: {str(e)}")
                
                # Phương pháp 3: Sử dụng hình ảnh dự phòng nếu tất cả phương pháp trên đều thất bại
                if not image_created:
                    logger.warning(f"Tất cả phương pháp tạo hình ảnh thất bại cho phân cảnh {scene_number}. Sử dụng hình dự phòng.")
                    # Tạo hình ảnh thay thế
                    fallback_image = self._create_fallback_image(
                        scene_number, 
                        scene['content'], 
                        project_dir
                    )
                    
                    image_info = {
                        "type": "fallback",
                        "number": scene_number,
                        "path": fallback_image,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "content": scene['content'],
                        "source": "fallback"
                    }
                
                # Thêm thông tin hình ảnh vào danh sách
                images.append(image_info)
                
                # Tránh gọi API quá nhanh
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Lỗi khi xử lý phân cảnh {scene.get('number', 'unknown')}: {str(e)}")
                # Sử dụng hình ảnh dự phòng có sẵn
                fallback_path = self._get_random_stock_image()
                images.append({
                    "type": "stock",
                    "number": scene.get('number', 0),
                    "path": fallback_path,
                    "duration": VIDEO_SETTINGS["image_duration"],
                    "content": scene.get('content', ''),
                    "source": "stock"
                })
        
        # Tạo hình ảnh kết thúc
        outro_image = self._create_outro_card(script['title'], script.get('source', ''), project_dir)
        images.append({
            "type": "outro",
            "path": outro_image,
            "duration": VIDEO_SETTINGS["outro_duration"]
        })
        
        logger.info(f"Đã tạo {len(images)} hình ảnh cho kịch bản")
        
        # Lưu thông tin hình ảnh vào file JSON để tham khảo sau
        self._save_image_info(images, script['title'], project_dir)
        
        return images
    
    def _search_and_download_image(self, query, output_path):
        """Tìm kiếm và tải hình ảnh từ Google qua Serper.dev API với nhiều cải tiến cho độ tin cậy
        
        Args:
            query (str): Từ khóa tìm kiếm
            output_path (str): Đường dẫn lưu hình ảnh
            
        Returns:
            str: Đường dẫn đến hình ảnh đã tải
        """
        try:
            logger.info(f"Tìm kiếm hình ảnh với từ khóa: {query}")
            
            # Chuẩn bị payload
            payload = {
                "q": query,
                "gl": "us",  # Khu vực địa lý
                "hl": "en",  # Ngôn ngữ
            }
            
            # Gọi Serper API
            response = requests.post(self.serper_url, headers=self.serper_headers, json=payload)
            
            if response.status_code != 200:
                logger.error(f"Lỗi khi gọi Serper API: {response.status_code}, {response.text}")
                raise Exception(f"Serper API error: {response.status_code}")
            
            data = response.json()
            
            # Lấy danh sách kết quả hình ảnh
            images = data.get("images", [])
            
            if not images:
                logger.warning(f"Không tìm thấy hình ảnh nào cho từ khóa: {query}")
                raise Exception("No images found")
            
            # Lọc các hình ảnh có kích thước phù hợp (ưu tiên hình ảnh lớn)
            filtered_images = [img for img in images if self._is_good_image_size(img)]
            
            if not filtered_images:
                filtered_images = images  # Nếu không có hình nào phù hợp, dùng tất cả kết quả
            
            # Lọc bỏ các URL có khả năng không tải được
            safe_images = [img for img in filtered_images if self._is_safe_image_url(img.get("imageUrl", ""))]
            
            if not safe_images and filtered_images:
                safe_images = filtered_images  # Nếu không có hình an toàn, dùng tất cả
            
            # Thử tải nhiều hình ảnh theo thứ tự ưu tiên cho đến khi thành công
            successful_download = False
            image_path = None
            
            # Tối đa 5 lần thử với các hình ảnh khác nhau
            max_attempts = min(5, len(safe_images))
            for i in range(max_attempts):
                selected_image = safe_images[i]
                image_url = selected_image.get("imageUrl")
                
                if not image_url:
                    logger.warning(f"Không tìm thấy URL hình ảnh trong kết quả thứ {i+1}")
                    continue
                
                try:
                    logger.info(f"Thử tải hình ảnh {i+1}/{max_attempts}: {image_url[:50]}...")
                    
                    # Kiểm tra URL
                    if not self._is_valid_url(image_url):
                        logger.warning(f"URL không hợp lệ: {image_url[:50]}...")
                        continue
                    
                    # Thử với nhiều hình thức request khác nhau
                    # Cách 1: Yêu cầu trực tiếp
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                    }
                    image_response = requests.get(image_url, headers=headers, timeout=10, allow_redirects=True)
                    
                    # Kiểm tra xem phản hồi có phải là hình ảnh không
                    content_type = image_response.headers.get('Content-Type', '')
                    if 'image' not in content_type:
                        logger.warning(f"Phản hồi không phải là hình ảnh: {content_type}")
                        # Thử các cách khác hoặc tiếp tục với hình tiếp theo
                        continue
                    
                    if image_response.status_code != 200 or len(image_response.content) < 1000:
                        logger.warning(f"Không thể tải hình ảnh hoặc hình ảnh quá nhỏ: {image_url}. Mã trạng thái: {image_response.status_code}, Kích thước: {len(image_response.content)}")
                        continue
                    
                    # Mở hình ảnh để kiểm tra tính hợp lệ
                    try:
                        image = Image.open(BytesIO(image_response.content))
                        
                        # Kiểm tra kích thước hình ảnh
                        if image.width < 400 or image.height < 300:
                            logger.warning(f"Hình ảnh quá nhỏ: {image.width}x{image.height}")
                            continue
                        
                        # Điều chỉnh kích thước để phù hợp với video
                        image = self._resize_image(image)
                        
                        # Lưu hình ảnh
                        image.save(output_path)
                        logger.info(f"Đã lưu hình ảnh tại: {output_path}")
                        
                        successful_download = True
                        image_path = output_path
                        break
                    except Exception as e:
                        logger.warning(f"Không thể xử lý hình ảnh từ URL {image_url}: {str(e)}")
                        continue
                        
                except Exception as e:
                    logger.warning(f"Lỗi khi tải hình ảnh từ URL {image_url}: {str(e)}")
                    continue
            
            if successful_download:
                return image_path
            else:
                logger.error("Không thể tải bất kỳ hình ảnh nào sau nhiều lần thử")
                raise Exception("Failed to download any image after multiple attempts")
                
        except Exception as e:
            logger.error(f"Lỗi khi tìm kiếm và tải hình ảnh: {str(e)}")
            raise
    
    def _is_valid_url(self, url):
        """Kiểm tra xem URL có hợp lệ không"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
        except Exception:
            return False
    
    def _is_safe_image_url(self, url):
        """Kiểm tra xem URL có khả năng tải được không"""
        if not url:
            return False
            
        # Kiểm tra URL có hợp lệ không
        if not self._is_valid_url(url):
            return False
        
        # Loại bỏ các URL từ các trang thường gây vấn đề CORS
        problematic_domains = ['pinterest', 'facebook', 'instagram', 'tiktok']
        if any(domain in url.lower() for domain in problematic_domains):
            return False
        
        # Kiểm tra phần mở rộng file
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        if not any(url.lower().endswith(ext) for ext in image_extensions) and 'image' not in url.lower():
            # Nếu URL không có phần mở rộng rõ ràng là hình ảnh, vẫn giữ lại nhưng đánh dấu là ít an toàn hơn
            return True
        
        return True
    
    def _download_and_process_image(self, image_url, output_path):
        """Tải và xử lý hình ảnh từ URL với nhiều phương pháp dự phòng"""
        try:
            # Phương pháp 1: Tải trực tiếp với request thông thường
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            # Kiểm tra URL hợp lệ
            if not self._is_valid_url(image_url):
                logger.warning(f"URL không hợp lệ: {image_url}")
                return None
            
            # Tải hình ảnh
            response = requests.get(image_url, headers=headers, timeout=10, allow_redirects=True)
            
            if response.status_code != 200 or len(response.content) < 1000:
                logger.warning(f"Không thể tải hình ảnh từ URL: {image_url}. Mã trạng thái: {response.status_code}, Kích thước: {len(response.content)}")
                return None
            
            # Kiểm tra xem phản hồi có phải là hình ảnh không
            content_type = response.headers.get('Content-Type', '')
            if 'image' not in content_type:
                logger.warning(f"Phản hồi không phải là hình ảnh: {content_type}")
                return None
            
            try:
                # Mở hình ảnh từ dữ liệu nhận được
                image = Image.open(BytesIO(response.content))
                
                # Kiểm tra kích thước hình ảnh
                if image.width < 400 or image.height < 300:
                    logger.warning(f"Hình ảnh quá nhỏ: {image.width}x{image.height}")
                    return None
                
                # Điều chỉnh kích thước hình ảnh
                processed_image = self._resize_image(image)
                
                # Lưu hình ảnh
                processed_image.save(output_path)
                logger.info(f"Đã tải và xử lý hình ảnh thành công: {output_path}")
                
                return output_path
            except Exception as e:
                logger.warning(f"Lỗi khi xử lý hình ảnh: {str(e)}")
                return None
            
        except Exception as e:
            logger.error(f"Lỗi khi tải và xử lý hình ảnh: {str(e)}")
            return None
    
    def _generate_image_with_dalle(self, prompt, output_path):
        """Tạo hình ảnh sử dụng DALL-E của OpenAI
        
        Args:
            prompt (str): Mô tả hình ảnh cần tạo
            output_path (str): Đường dẫn lưu hình ảnh
            
        Returns:
            str: Đường dẫn đến hình ảnh đã tạo, hoặc None nếu có lỗi
        """
        try:
            # Chuẩn bị payload cho DALL-E
            payload = {
                "model": "dall-e-3",  # Có thể sử dụng "dall-e-2" nếu cần
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",  # Kích thước chuẩn cho DALL-E 3
                "response_format": "b64_json"  # Nhận base64 để tránh vấn đề với URL
            }
            
            # Gọi API
            response = requests.post(self.dalle_url, headers=self.dalle_headers, json=payload)
            
            if response.status_code != 200:
                logger.error(f"Lỗi khi gọi DALL-E API: {response.status_code}, {response.text}")
                return None
            
            # Xử lý phản hồi
            data = response.json()
            image_data = data.get("data", [{}])[0].get("b64_json")
            
            if not image_data:
                logger.error("Không tìm thấy dữ liệu hình ảnh trong phản hồi DALL-E")
                return None
            
            # Giải mã base64 và tạo hình ảnh
            image_bytes = base64.b64decode(image_data)
            image = Image.open(BytesIO(image_bytes))
            
            # Điều chỉnh kích thước
            image = self._resize_image(image)
            
            # Lưu hình ảnh
            image.save(output_path)
            logger.info(f"Đã tạo hình ảnh với DALL-E và lưu tại: {output_path}")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Lỗi khi tạo hình ảnh với DALL-E: {str(e)}")
            return None
    
    def _create_dalle_prompt(self, content, title):
        """Tạo prompt phù hợp cho DALL-E dựa trên nội dung phân cảnh"""
        # Trích xuất từ khóa chính
        keywords = self._extract_keywords(content, max_words=15)
        
        # Tạo prompt đầy đủ
        prompt = f"Create a high-quality, realistic image that represents the following news content: '{keywords}'. The image should be suitable for a news article about {title}. Make it clear, professional, and look like a journalistic photograph. Do not include any text in the image."
        
        return prompt
    
    def _prepare_stock_images(self):
        """Kiểm tra và tạo một số hình ảnh dự phòng nếu thư mục trống"""
        stock_images = [f for f in os.listdir(self.stock_images_dir) if f.endswith(('.jpg', '.png', '.jpeg'))]
        
        # Nếu không có hình ảnh dự phòng, tạo một số hình đơn giản
        if not stock_images:
            logger.info("Không tìm thấy hình ảnh dự phòng. Tạo hình đơn giản...")
            
            # Tạo một số hình ảnh đơn giản với màu nền và văn bản khác nhau
            colors = [
                (0, 51, 102),    # Xanh đậm
                (102, 0, 51),    # Đỏ đậm
                (51, 102, 0),    # Xanh lá đậm
                (51, 0, 102),    # Tím đậm
                (102, 51, 0)     # Nâu đậm
            ]
            
            titles = [
                "Breaking News",
                "Latest Update",
                "World News",
                "Business Review",
                "Technology Today"
            ]
            
            for i, (color, title) in enumerate(zip(colors, titles)):
                # Tạo hình ảnh
                img = Image.new('RGB', (self.width, self.height), color=color)
                draw = ImageDraw.Draw(img)
                
                # Vẽ tiêu đề
                font = self._get_font(size=60)
                try:
                    text_width = font.getbbox(title)[2]
                except:
                    text_width = len(title) * 30
                
                draw.text(
                    ((self.width - text_width) // 2, self.height // 2 - 30),
                    title,
                    font=font,
                    fill=(255, 255, 255)  # Chữ trắng
                )
                
                # Lưu hình ảnh
                output_path = os.path.join(self.stock_images_dir, f"stock_{i+1}.png")
                img.save(output_path)
                logger.info(f"Đã tạo hình ảnh dự phòng: {output_path}")
    
    def _get_random_stock_image(self):
        """Lấy một hình ảnh dự phòng ngẫu nhiên từ thư mục stock_images"""
        stock_images = [f for f in os.listdir(self.stock_images_dir) if f.endswith(('.jpg', '.png', '.jpeg'))]
        
        if not stock_images:
            # Nếu không có hình ảnh dự phòng, tạo một hình ảnh đơn giản
            img = Image.new('RGB', (self.width, self.height), color=(45, 45, 45))
            draw = ImageDraw.Draw(img)
            
            font = self._get_font(size=60)
            text = "No Image Available"
            try:
                text_width = font.getbbox(text)[2]
            except:
                text_width = len(text) * 30
            
            draw.text(
                ((self.width - text_width) // 2, self.height // 2 - 30),
                text,
                font=font,
                fill=(255, 255, 255)
            )
            
            # Lưu hình ảnh
            output_path = os.path.join(self.stock_images_dir, "no_image.png")
            img.save(output_path)
            return output_path
        
        # Chọn ngẫu nhiên một hình ảnh
        random_image = random.choice(stock_images)
        return os.path.join(self.stock_images_dir, random_image)
    
    def _is_good_image_size(self, image_data):
        """Kiểm tra xem hình ảnh có kích thước phù hợp không
        
        Args:
            image_data (dict): Thông tin hình ảnh từ Serper API
            
        Returns:
            bool: True nếu kích thước phù hợp
        """
        # Lấy thông tin kích thước hình ảnh nếu có
        width = image_data.get("width", 0)
        height = image_data.get("height", 0)
        
        # Ưu tiên hình ảnh lớn
        if width >= 800 and height >= 600:
            return True
        
        # Ưu tiên hình ảnh có tỷ lệ gần với 16:9
        if width > 0 and height > 0:
            ratio = width / height
            target_ratio = 16 / 9
            # Cho phép sai số 20%
            if 0.8 * target_ratio <= ratio <= 1.2 * target_ratio:
                return True
        
        return False