# src/image_generator.py
import os
import requests
import logging
import time
import json
import random
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from config.credentials import SERPER_API_KEY  # Thêm Serper API key vào file credentials
from config.settings import TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self):
        self.serper_api_key = SERPER_API_KEY
        self.temp_dir = TEMP_DIR
        self.assets_dir = ASSETS_DIR
        self.width = VIDEO_SETTINGS["width"]
        self.height = VIDEO_SETTINGS["height"]
        
        # URL cho Serper.dev API
        self.serper_url = "https://google.serper.dev/images"
        self.headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json"
        }
        
        # Tạo thư mục lưu trữ hình ảnh trong temp
        self.image_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(self.image_dir, exist_ok=True)
        
        # Tạo thư mục fonts nếu chưa có
        self.fonts_dir = os.path.join(self.assets_dir, "fonts")
        os.makedirs(self.fonts_dir, exist_ok=True)
        
        # Kiểm tra và tải font nếu chưa có
        self._check_and_download_fonts()
    
    def generate_images_for_script(self, script):
        """Tạo hình ảnh cho tất cả phân cảnh trong kịch bản với cơ chế dự phòng đa tầng
        
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
                
                # Sử dụng Serper để tìm hình ảnh
                keywords = self._extract_keywords(scene['content'])
                search_query = self._create_search_query(keywords, script['title'])
                
                # Tên file
                scene_image_filename = f"scene_{scene_number}.jpg"
                scene_image_path = os.path.join(project_dir, scene_image_filename)
                
                # Phương thức multi-stage để lấy hình ảnh
                try:
                    # Giai đoạn 1: Kiểm tra cache hoặc tải từ Serper API
                    logger.info(f"Giai đoạn 1: Kiểm tra cache hoặc tải từ Serper API")
                    scene_image = self._get_cached_or_download_image(search_query, scene_image_path)
                    
                except Exception as e1:
                    logger.warning(f"Giai đoạn 1 thất bại: {str(e1)}")
                    
                    try:
                        # Giai đoạn 2: Thử tìm kiếm với từ khóa đơn giản hơn
                        logger.info(f"Giai đoạn 2: Tìm kiếm với từ khóa đơn giản hơn")
                        simplified_query = self._extract_keywords(scene['content'], max_words=5) + " news image"
                        scene_image = self._search_and_download_image(simplified_query, scene_image_path)
                        
                    except Exception as e2:
                        logger.warning(f"Giai đoạn 2 thất bại: {str(e2)}")
                        
                        try:
                            # Giai đoạn 3: Sử dụng hình ảnh dự phòng cục bộ
                            logger.info(f"Giai đoạn 3: Sử dụng hình ảnh dự phòng cục bộ")
                            scene_image = self._use_local_fallback_image(search_query, scene_image_path)
                            
                        except Exception as e3:
                            logger.warning(f"Giai đoạn 3 thất bại: {str(e3)}")
                            
                            # Giai đoạn 4: Tạo hình ảnh text-only khi tất cả thất bại
                            logger.info(f"Giai đoạn 4: Tạo hình ảnh text-only")
                            scene_image = self._create_text_only_image(
                                scene['content'][:150], 
                                os.path.join(project_dir, f"text_scene_{scene_number}.png")
                            )
                
                image_info = {
                    "type": "scene",
                    "number": scene_number,
                    "path": scene_image,
                    "duration": VIDEO_SETTINGS["image_duration"],
                    "content": scene['content'],
                    "search_query": search_query
                }
                
                images.append(image_info)
                
                # Tránh gọi API quá nhanh
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Lỗi không xử lý được khi tạo hình ảnh cho phân cảnh {scene.get('number', 'unknown')}: {str(e)}")
                
                # Tạo hình ảnh khẩn cấp nếu mọi thứ đều thất bại
                fallback_image = self._create_fallback_image(
                    scene.get('number', 0), 
                    scene.get('content', 'Unknown content'), 
                    project_dir
                )
                
                images.append({
                    "type": "emergency_fallback",
                    "number": scene.get('number', 0),
                    "path": fallback_image,
                    "duration": VIDEO_SETTINGS["image_duration"],
                    "content": scene.get('content', 'Unknown content')
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
        """Tìm kiếm và tải hình ảnh từ Google qua Serper.dev API
        
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
            response = requests.post(self.serper_url, headers=self.headers, json=payload)
            
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
            
            # Thử tải từng hình ảnh cho đến khi thành công
            max_attempts = min(5, len(filtered_images))
            download_errors = 0
            
            for i in range(max_attempts):
                # Chọn một hình ảnh từ danh sách
                selected_image = filtered_images[i]
                
                # Lấy URL hình ảnh
                image_url = selected_image.get("imageUrl")
                
                if not image_url:
                    logger.warning(f"Không tìm thấy URL hình ảnh trong kết quả thứ {i+1}")
                    download_errors += 1
                    continue
                
                logger.info(f"Đang thử tải hình ảnh {i+1}/{max_attempts}: {image_url[:50]}...")
                
                try:
                    # Tải hình ảnh với headers giả lập trình duyệt
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': 'https://www.google.com/'
                    }
                    
                    image_response = requests.get(image_url, headers=headers, timeout=15)
                    
                    if image_response.status_code != 200:
                        logger.warning(f"Không thể tải hình ảnh từ URL: {image_url}. Mã trạng thái: {image_response.status_code}")
                        download_errors += 1
                        continue
                    
                    # Kiểm tra Content-Type
                    content_type = image_response.headers.get('Content-Type', '')
                    if not content_type.startswith('image/'):
                        logger.warning(f"URL trả về định dạng không phải hình ảnh: {content_type}")
                        download_errors += 1
                        continue
                    
                    # Kiểm tra xem dữ liệu có phải là hình ảnh hợp lệ không
                    if not self._validate_image(image_response.content):
                        logger.warning(f"Dữ liệu tải về không phải là hình ảnh hợp lệ")
                        download_errors += 1
                        continue
                    
                    # Xử lý hình ảnh
                    image = Image.open(BytesIO(image_response.content))
                    
                    # Điều chỉnh kích thước để phù hợp với video
                    image = self._resize_image(image)
                    
                    # Lưu hình ảnh
                    image.save(output_path)
                    logger.info(f"Đã lưu hình ảnh tại: {output_path}")
                    
                    # Thành công, trả về đường dẫn
                    return output_path
                    
                except requests.exceptions.Timeout:
                    logger.warning(f"Hết thời gian chờ khi tải hình ảnh từ: {image_url}")
                    download_errors += 1
                    continue
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Lỗi yêu cầu khi tải hình ảnh: {str(e)}")
                    download_errors += 1
                    continue
                except Exception as e:
                    logger.warning(f"Lỗi xử lý hình ảnh từ {image_url}: {str(e)}")
                    download_errors += 1
                    continue
            
            # Nếu tất cả các nỗ lực tải đều thất bại
            logger.error(f"Tất cả {download_errors} lần thử tải hình ảnh đều thất bại cho từ khóa: {query}")
            raise Exception(f"Không thể tải hình ảnh sau {max_attempts} lần thử")
                
        except Exception as e:
            logger.error(f"Lỗi khi tìm kiếm và tải hình ảnh: {str(e)}")
            raise

    def _validate_image(self, image_data):
        """Kiểm tra xem dữ liệu có phải là hình ảnh hợp lệ không
        
        Args:
            image_data (bytes): Dữ liệu hình ảnh nhị phân
            
        Returns:
            bool: True nếu là hình ảnh hợp lệ
        """
        try:
            # Thử mở dữ liệu dưới dạng hình ảnh
            img = Image.open(BytesIO(image_data))
            
            # Kiểm tra định dạng
            if img.format not in ['JPEG', 'PNG', 'GIF', 'BMP', 'WEBP']:
                return False
                
            # Kiểm tra kích thước tối thiểu
            if img.width < 100 or img.height < 100:
                return False
            
            # Thử đọc dữ liệu hình ảnh
            img.verify()
            
            # Mở lại hình ảnh để kiểm tra
            img = Image.open(BytesIO(image_data))
            img.load()
                
            # Hình ảnh hợp lệ
            return True
        except Exception as e:
            logger.warning(f"Dữ liệu không phải là hình ảnh hợp lệ: {str(e)}")
            return False

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
    
    def _get_cached_or_download_image(self, query, output_path):
        """Kiểm tra trong cache trước, chỉ tải nếu không có trong cache
        
        Args:
            query (str): Từ khóa tìm kiếm
            output_path (str): Đường dẫn lưu hình ảnh
            
        Returns:
            str: Đường dẫn đến hình ảnh
        """
        # Tạo thư mục cache nếu chưa tồn tại
        cache_dir = os.path.join(self.temp_dir, "image_cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        # Tạo hash từ query để đặt tên file trong cache
        import hashlib
        query_hash = hashlib.md5(query.encode()).hexdigest()
        cache_path = os.path.join(cache_dir, f"{query_hash}.jpg")
        
        # Kiểm tra nếu hình ảnh đã tồn tại trong cache
        if os.path.exists(cache_path):
            logger.info(f"Sử dụng hình ảnh từ cache cho từ khóa: {query}")
            
            # Sao chép từ cache sang đường dẫn output
            import shutil
            shutil.copy(cache_path, output_path)
            return output_path
        
        # Nếu không có trong cache, tải mới
        try:
            downloaded_path = self._search_and_download_image(query, output_path)
            
            # Lưu vào cache để sử dụng sau này
            import shutil
            shutil.copy(downloaded_path, cache_path)
            
            return downloaded_path
        except Exception as e:
            logger.error(f"Lỗi khi tải và cache hình ảnh: {str(e)}")
            raise    

    def _use_local_fallback_image(self, query, output_path):
        """Sử dụng hình ảnh cục bộ khi tất cả các cách tìm kiếm trực tuyến đều thất bại
        
        Args:
            query (str): Từ khóa tìm kiếm
            output_path (str): Đường dẫn lưu hình ảnh
            
        Returns:
            str: Đường dẫn đến hình ảnh
        """
        # Tạo thư mục chứa hình ảnh dự phòng nếu chưa có
        fallback_dir = os.path.join(self.assets_dir, "fallback_images")
        if not os.path.exists(fallback_dir):
            os.makedirs(fallback_dir, exist_ok=True)
            logger.warning(f"Đã tạo thư mục hình ảnh dự phòng tại: {fallback_dir}")
            logger.warning("Hãy thêm một số hình ảnh vào thư mục này để sử dụng khi cần")
            
        # Các chủ đề và từ khóa tương ứng
        themes = {
            "tin_tuc": ["tin", "báo", "báo chí", "thời sự", "news"],
            "cong_nghe": ["công nghệ", "máy tính", "điện thoại", "phần mềm", "technology"],
            "kinh_te": ["kinh tế", "tài chính", "thị trường", "chứng khoán", "economy"],
            "the_thao": ["thể thao", "bóng đá", "thể dục", "vận động viên", "sports"],
            "giai_tri": ["giải trí", "âm nhạc", "phim", "nghệ sĩ", "entertainment"],
            "general": []  # Mặc định
        }
        
        # Xác định chủ đề phù hợp nhất dựa trên từ khóa
        best_theme = "general"
        best_score = 0
        
        for theme, keywords in themes.items():
            score = sum(1 for keyword in keywords if keyword.lower() in query.lower())
            if score > best_score:
                best_score = score
                best_theme = theme
                
        # Thư mục chứa hình ảnh theo chủ đề
        theme_dir = os.path.join(fallback_dir, best_theme)
        
        # Nếu thư mục chủ đề không tồn tại, sử dụng thư mục general
        if not os.path.exists(theme_dir):
            theme_dir = os.path.join(fallback_dir, "general")
            
        # Nếu thư mục general cũng không tồn tại, tạo hình ảnh text
        if not os.path.exists(theme_dir):
            logger.warning(f"Không tìm thấy thư mục hình ảnh dự phòng: {theme_dir}")
            return self._create_text_only_image(query, output_path)
            
        # Lấy tất cả file hình ảnh trong thư mục
        import glob
        image_files = glob.glob(os.path.join(theme_dir, "*.jpg")) + \
                    glob.glob(os.path.join(theme_dir, "*.jpeg")) + \
                    glob.glob(os.path.join(theme_dir, "*.png"))
                    
        if not image_files:
            logger.warning(f"Không tìm thấy hình ảnh dự phòng trong thư mục: {theme_dir}")
            return self._create_text_only_image(query, output_path)
            
        # Chọn một hình ảnh ngẫu nhiên
        import random
        selected_image = random.choice(image_files)
        
        # Sao chép sang output path
        import shutil
        shutil.copy(selected_image, output_path)
        
        logger.info(f"Đã sử dụng hình ảnh dự phòng từ: {selected_image}")
        return output_path

    def _create_text_only_image(self, query, output_path):
        """Tạo hình ảnh chứa text khi không còn lựa chọn nào khác
        
        Args:
            query (str): Từ khóa tìm kiếm
            output_path (str): Đường dẫn lưu hình ảnh
            
        Returns:
            str: Đường dẫn đến hình ảnh
        """
        # Tạo hash từ query để tạo màu nền độc đáo
        import hashlib
        query_hash = hashlib.md5(query.encode()).hexdigest()
        r1 = int(query_hash[:2], 16)
        g1 = int(query_hash[2:4], 16)
        b1 = int(query_hash[4:6], 16)
        r2 = int(query_hash[6:8], 16)
        g2 = int(query_hash[8:10], 16)
        b2 = int(query_hash[10:12], 16)
        
        # Tạo hình ảnh với nền gradient
        img = Image.new('RGB', (self.width, self.height), color=(r1, g1, b1))
        draw = ImageDraw.Draw(img)
        
        # Vẽ hiệu ứng gradient
        for y in range(self.height):
            # Tính toán màu gradient cho vị trí y
            r = r1 + (r2 - r1) * y // self.height
            g = g1 + (g2 - g1) * y // self.height
            b = b1 + (b2 - b1) * y // self.height
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        
        # Lấy font và chuẩn bị text
        font = self._get_font(size=50)
        wrapped_text = self._wrap_text(query, font, self.width - 100)
        
        # Vẽ hình chữ nhật trắng ở giữa để dễ đọc
        text_height = len(wrapped_text) * 60
        rect_top = (self.height - text_height) // 2 - 30
        rect_bottom = rect_top + text_height + 60
        draw.rectangle(
            [(50, rect_top), (self.width - 50, rect_bottom)],
            fill=(255, 255, 255, 180)
        )
        
        # Vẽ text với màu tối trên nền trắng
        text_y = (self.height - text_height) // 2
        for i, line in enumerate(wrapped_text):
            try:
                text_width = font.getbbox(line)[2] if hasattr(font, 'getbbox') else len(line) * 30
            except:
                text_width = len(line) * 30
                
            position = ((self.width - text_width) // 2, text_y + i * 60)
            draw.text(position, line, font=font, fill=(20, 20, 20))
        
        # Lưu và trả về
        img.save(output_path)
        logger.info(f"Đã tạo hình ảnh text-only tại: {output_path}")
        return output_path

    def _create_title_card(self, title, source, project_dir):
        """Tạo hình ảnh tiêu đề cho phần mở đầu video"""
        # Tạo hình ảnh trắng với kích thước video
        img = Image.new('RGB', (self.width, self.height), color=(0, 51, 102))  # Màu xanh đậm
        draw = ImageDraw.Draw(img)
        
        # Tải font
        title_font = self._get_font(size=60)
        source_font = self._get_font(size=40)
        
        # Vẽ tiêu đề
        title_wrapped = self._wrap_text(title, title_font, self.width - 200)
        title_y = (self.height - (len(title_wrapped) * 70)) // 2  # Căn giữa dọc
        
        for i, line in enumerate(title_wrapped):
            # Tính toán chiều rộng văn bản để căn giữa
            try:
                text_width = title_font.getbbox(line)[2]
            except:
                # Nếu không lấy được kích thước, ước tính
                text_width = len(line) * 30
            
            position = ((self.width - text_width) // 2, title_y + i * 70)
            draw.text(position, line, font=title_font, fill=(255, 255, 255))  # Chữ trắng
        
        # Vẽ nguồn (nếu có)
        if source:
            source_text = f"Nguồn: {source}"
            try:
                source_width = source_font.getbbox(source_text)[2]
            except:
                source_width = len(source_text) * 20
            
            draw.text(
                ((self.width - source_width) // 2, self.height - 100),
                source_text,
                font=source_font,
                fill=(200, 200, 200)  # Màu xám nhạt
            )
        
        # Lưu hình ảnh
        output_path = os.path.join(project_dir, "intro_title.png")
        img.save(output_path)
        
        return output_path
    
    def _create_outro_card(self, title, source, project_dir):
        """Tạo hình ảnh kết thúc"""
        # Tạo hình ảnh với màu nền khác với intro
        img = Image.new('RGB', (self.width, self.height), color=(51, 0, 102))  # Màu tím đậm
        draw = ImageDraw.Draw(img)
        
        # Tải font
        title_font = self._get_font(size=60)
        subtitle_font = self._get_font(size=40)
        
        # Vẽ chữ "Cảm ơn đã xem"
        thank_you_text = "Cảm ơn đã xem"
        try:
            text_width = title_font.getbbox(thank_you_text)[2]
        except:
            text_width = len(thank_you_text) * 30
        
        draw.text(
            ((self.width - text_width) // 2, self.height // 3),
            thank_you_text,
            font=title_font,
            fill=(255, 255, 255)  # Chữ trắng
        )
        
        # Vẽ tiêu đề thu nhỏ
        title_wrapped = self._wrap_text(title, subtitle_font, self.width - 200)
        title_y = self.height // 2
        
        for i, line in enumerate(title_wrapped):
            try:
                text_width = subtitle_font.getbbox(line)[2]
            except:
                text_width = len(line) * 20
            
            position = ((self.width - text_width) // 2, title_y + i * 50)
            draw.text(position, line, font=subtitle_font, fill=(200, 200, 200))  # Chữ xám nhạt
        
        # Lưu hình ảnh
        output_path = os.path.join(project_dir, "outro.png")
        img.save(output_path)
        
        return output_path
    
    def _create_fallback_image(self, scene_number, content, project_dir):
        """Tạo hình ảnh thay thế khi không thể tìm được từ Serper"""
        try:
            # Thử tìm với từ khóa đơn giản hơn
            simplified_query = self._extract_keywords(content, max_words=5) + " news"
            
            output_path = os.path.join(project_dir, f"fallback_scene_{scene_number}.jpg")
            return self._search_and_download_image(simplified_query, output_path)
        except Exception as e:
            logger.error(f"Lỗi khi tạo fallback image: {str(e)}")
            
            # Tạo hình ảnh đơn giản màu trơn nếu không tìm được hình
            img = Image.new('RGB', (self.width, self.height), color=(45, 45, 45))
            draw = ImageDraw.Draw(img)
            
            # Tải font
            font = self._get_font(size=40)
            
            # Cắt ngắn nội dung nếu quá dài
            max_chars = 300
            short_content = content if len(content) <= max_chars else content[:max_chars] + "..."
            
            # Chia nội dung thành các dòng
            wrapped_text = self._wrap_text(short_content, font, self.width - 200)
            
            # Vẽ văn bản
            text_y = (self.height - (len(wrapped_text) * 50)) // 2  # Căn giữa dọc
            
            for i, line in enumerate(wrapped_text):
                try:
                    text_width = font.getbbox(line)[2]
                except:
                    text_width = len(line) * 20
                
                position = ((self.width - text_width) // 2, text_y + i * 50)
                draw.text(position, line, font=font, fill=(255, 255, 255))  # Chữ trắng
            
            output_path = os.path.join(project_dir, f"fallback_scene_{scene_number}.png")
            img.save(output_path)
            return output_path
    
    def _add_caption_to_image(self, image_path, caption, project_dir):
        """Thêm chú thích vào hình ảnh"""
        try:
            # Mở hình ảnh
            img = Image.open(image_path).convert('RGBA')
            
            # Tạo một lớp overlay trong suốt để đặt chú thích
            overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            
            # Tạo một dải đen mờ ở dưới cùng cho chú thích
            overlay_height = 100  # Giảm kích thước lớp overlay
            draw.rectangle(
                [(0, img.height - overlay_height), (img.width, img.height)],
                fill=(0, 0, 0, 180)  # Màu đen với độ mờ 70%
            )
            
            # Gộp hình ảnh gốc với overlay
            img = Image.alpha_composite(img, overlay).convert('RGB')
            draw = ImageDraw.Draw(img)
            
            # Tải font và điều chỉnh kích thước nếu không có font
            font = self._get_font(size=28)  # Giảm kích thước chữ
            
            # Cắt ngắn caption nếu quá dài
            if len(caption) > 100:
                caption = caption[:97] + "..."
            
            # Căn giữa và vẽ caption
            try:
                # Thử lấy kích thước văn bản
                if hasattr(font, 'getbbox'):
                    text_width = font.getbbox(caption)[2]
                elif hasattr(font, 'getsize'):
                    text_width, _ = font.getsize(caption)
                else:
                    text_width = len(caption) * 15
            except:
                # Nếu không lấy được kích thước, ước tính
                text_width = len(caption) * 15
            
            # Vẽ caption
            position = ((img.width - text_width) // 2, img.height - overlay_height + 30)
            draw.text(position, caption, font=font, fill=(255, 255, 255))
            
            # Tạo tên file mới
            filename = os.path.basename(image_path)
            base_name = os.path.splitext(filename)[0]
            output_path = os.path.join(project_dir, f"{base_name}_captioned.png")
            
            # Lưu hình ảnh
            img.save(output_path)
            
            return output_path
        except Exception as e:
            logger.error(f"Lỗi khi thêm caption vào hình ảnh: {str(e)}")
            # Nếu có lỗi, trả về hình ảnh gốc
            return image_path
    
    def _download_and_process_image(self, image_url, output_path):
        """Tải và xử lý hình ảnh từ URL với xử lý lỗi tốt hơn
        
        Args:
            image_url (str): URL của hình ảnh
            output_path (str): Đường dẫn để lưu hình ảnh
            
        Returns:
            str: Đường dẫn đến hình ảnh đã xử lý hoặc None nếu thất bại
        """
        max_retries = 3
        current_retry = 0
        
        while current_retry < max_retries:
            try:
                # Tạo headers giả lập trình duyệt
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.google.com/'
                }
                
                # Tải hình ảnh với timeout dài hơn
                response = requests.get(image_url, headers=headers, timeout=20)
                
                if response.status_code != 200:
                    logger.warning(f"Lần thử {current_retry+1}/{max_retries}: Không thể tải hình ảnh từ URL: {image_url}. Mã trạng thái: {response.status_code}")
                    current_retry += 1
                    time.sleep(1)  # Chờ 1 giây trước khi thử lại
                    continue
                
                # Kiểm tra Content-Type
                content_type = response.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    logger.warning(f"Lần thử {current_retry+1}/{max_retries}: URL trả về nội dung không phải hình ảnh: {content_type}")
                    current_retry += 1
                    time.sleep(1)
                    continue
                
                # Kiểm tra xem dữ liệu có phải là hình ảnh hợp lệ không
                if not self._validate_image(response.content):
                    logger.warning(f"Lần thử {current_retry+1}/{max_retries}: Dữ liệu tải về không phải là hình ảnh hợp lệ")
                    current_retry += 1
                    time.sleep(1)
                    continue
                
                # Mở hình ảnh từ dữ liệu nhận được
                image = Image.open(BytesIO(response.content))
                
                # Điều chỉnh kích thước hình ảnh
                processed_image = self._resize_image(image)
                
                # Lưu hình ảnh
                processed_image.save(output_path)
                logger.info(f"Đã tải và xử lý thành công hình ảnh từ URL: {image_url}")
                
                return output_path
                
            except requests.exceptions.Timeout:
                logger.warning(f"Lần thử {current_retry+1}/{max_retries}: Hết thời gian chờ khi tải hình ảnh từ URL: {image_url}")
                current_retry += 1
                time.sleep(1)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Lần thử {current_retry+1}/{max_retries}: Lỗi kết nối khi tải hình ảnh: {str(e)}")
                current_retry += 1
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Lần thử {current_retry+1}/{max_retries}: Lỗi khi tải và xử lý hình ảnh: {str(e)}")
                current_retry += 1
                time.sleep(1)
        
        logger.error(f"Đã thử {max_retries} lần nhưng không thể tải hình ảnh từ: {image_url}")
        return None
    
    def _resize_image(self, image):
        """Điều chỉnh kích thước hình ảnh để phù hợp với kích thước video"""
        # Tính tỷ lệ khung hình
        target_ratio = self.width / self.height
        img_ratio = image.width / image.height
        
        if img_ratio > target_ratio:
            # Hình ảnh quá rộng, cần cắt bớt hai bên
            new_width = int(image.height * target_ratio)
            left = (image.width - new_width) // 2
            image = image.crop((left, 0, left + new_width, image.height))
        else:
            # Hình ảnh quá cao, cần cắt bớt trên dưới
            new_height = int(image.width / target_ratio)
            top = (image.height - new_height) // 2
            image = image.crop((0, top, image.width, top + new_height))
        
        # Thay đổi kích thước thành kích thước video
        image = image.resize((self.width, self.height), Image.LANCZOS)
        
        return image
    
    def _extract_keywords(self, text, max_words=10):
        """Trích xuất từ khóa chính từ văn bản"""
        # Kiểm tra xem text có dữ liệu không
        if not text or len(text.strip()) == 0:
            return "news image"
        
        # Nếu văn bản đủ ngắn, dùng nguyên
        if len(text.split()) <= max_words:
            return text.strip()
        
        # Lấy câu đầu tiên hoàn chỉnh
        sentences = text.split('.')
        first_sentence = sentences[0].strip() if sentences else text
        
        # Nếu câu đầu tiên đủ ngắn, dùng luôn
        if len(first_sentence.split()) <= max_words:
            return first_sentence
            
        # Nếu quá dài, cắt bớt và thêm dấu "..." ở cuối
        words = first_sentence.split()
        return ' '.join(words[:max_words])
    
    def _create_search_query(self, keywords, title):
        """Tạo truy vấn tìm kiếm cho Serper API
        
        Args:
            keywords (str): Từ khóa trích xuất từ phân cảnh
            title (str): Tiêu đề bài viết
            
        Returns:
            str: Truy vấn tìm kiếm
        """
        # Loại bỏ các ký tự đặc biệt
        keywords = keywords.replace('"', '').replace("'", '')
        title_keywords = ' '.join(title.split()[:3])  # Lấy 3 từ đầu tiên của tiêu đề
        
        # Kết hợp từ khóa với tiêu đề và thêm từ khóa "news"
        search_query = f"{keywords} {title_keywords} news hd"
        
        return search_query
    
    def _create_caption(self, text):
        """Tạo chú thích ngắn từ văn bản"""
        # Lấy câu đầu tiên hoặc tối đa 100 ký tự
        max_length = 100
        
        if len(text) <= max_length:
            return text
        
        # Tìm vị trí của dấu chấm đầu tiên
        dot_pos = text.find('.')
        if dot_pos > 0 and dot_pos < max_length + 20:
            return text[:dot_pos+1]
        
        # Nếu không có dấu chấm hoặc câu quá dài, cắt ở từ cuối cùng trước khi đạt đến max_length
        cut_text = text[:max_length].rsplit(' ', 1)[0]
        return cut_text + "..."
    
    def _wrap_text(self, text, font, max_width):
        """Chia văn bản thành các dòng phù hợp với chiều rộng"""
        words = text.split()
        if not words:
            return []
            
        lines = []
        current_line = words[0]
        
        for word in words[1:]:
            # Kiểm tra nếu thêm từ mới vào dòng hiện tại có vượt quá chiều rộng không
            test_line = current_line + " " + word
            try:
                if hasattr(font, 'getbbox'):
                    text_width = font.getbbox(test_line)[2]
                elif hasattr(font, 'getsize'):
                    text_width, _ = font.getsize(test_line)
                else:
                    text_width = len(test_line) * 15  # Ước tính
            except:
                text_width = len(test_line) * 15  # Ước tính nếu không lấy được kích thước
            
            if text_width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        
        lines.append(current_line)  # Thêm dòng cuối cùng
        
        return lines
    
    def _check_and_download_fonts(self):
        """Kiểm tra font và thông báo nếu chưa có"""
        # Đường dẫn đến file font
        font_path = os.path.join(self.fonts_dir, "Roboto-Bold.ttf")
        
        # Nếu font chưa tồn tại, thông báo cho người dùng
        if not os.path.exists(font_path):
            logger.warning(f"Font không tồn tại: {font_path}")
            logger.warning("Vui lòng tải font Roboto-Bold.ttf từ fonts.google.com và đặt vào thư mục assets/fonts")
            # Không cần tự động tải nữa vì URL không hoạt động
    
    def _get_font(self, size=40):
        """Lấy font với kích thước cụ thể"""
        font_path = os.path.join(self.fonts_dir, "Roboto-Bold.ttf")
        
        # Kiểm tra xem font có tồn tại không
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception as e:
                logger.warning(f"Không thể tải font từ {font_path}: {str(e)}")
        
        # Thử dùng các font hệ thống thay thế
        system_font_names = ['Arial', 'Tahoma', 'Verdana', 'Times New Roman', 'Segoe UI']
        for font_name in system_font_names:
            try:
                return ImageFont.truetype(font_name, size)
            except Exception:
                continue
        
        # Nếu không tìm thấy font nào, sử dụng font mặc định
        logger.warning("Không tìm thấy font thay thế, sử dụng font mặc định")
        default_font = ImageFont.load_default()
        
        # Trong Pillow phiên bản mới, load_default() trả về font không đúng kích thước
        # Thử điều chỉnh kích thước
        try:
            return default_font.font_variant(size=size)
        except AttributeError:
            return default_font
    
    def _save_image_info(self, images, title, project_dir):
        """Lưu thông tin hình ảnh vào file JSON
        
        Args:
            images (list): Danh sách thông tin hình ảnh
            title (str): Tiêu đề dự án
            project_dir (str): Thư mục dự án
        """
        import json
        
        # Tạo bản sao để tránh thay đổi dữ liệu gốc
        image_info = []
        for img in images:
            # Chỉ lưu đường dẫn tương đối để dễ di chuyển
            img_copy = img.copy()
            img_copy['rel_path'] = os.path.basename(img['path'])
            image_info.append(img_copy)
        
        output_file = os.path.join(project_dir, "image_info.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'title': title,
                'creation_time': time.strftime("%Y-%m-%d %H:%M:%S"),
                'project_dir': os.path.basename(project_dir),
                'images': image_info
            }, f, ensure_ascii=False, indent=4)
        
        logger.info(f"Đã lưu thông tin hình ảnh tại: {output_file}")

# Test module nếu chạy trực tiếp
if __name__ == "__main__":
    # Script giả lập để test
    test_script = {
        'title': 'Economic Impact of Recent Market Fluctuations',
        'full_script': 'Content of the script...',
        'source': 'Financial Times',
        'scenes': [
            {
                'number': 1,
                'content': 'Global markets have shown significant volatility in the past week with major indices experiencing sharp declines.'
            },
            {
                'number': 2,
                'content': 'Technology stocks were particularly affected, with some companies losing over 10% of their value in just days.'
            }
        ]
    }
    
    generator = ImageGenerator()
    images = generator.generate_images_for_script(test_script)
    
    print(f"Đã tạo {len(images)} hình ảnh:")
    for img in images:
        print(f"- Loại: {img['type']}, Đường dẫn: {img['path']}")        