import os
import requests
import logging
import time
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from openai import OpenAI
from config.credentials import OPENAI_API_KEY
from config.settings import TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.temp_dir = TEMP_DIR
        self.assets_dir = ASSETS_DIR
        self.width = VIDEO_SETTINGS["width"]
        self.height = VIDEO_SETTINGS["height"]
        
        # Tạo thư mục lưu trữ hình ảnh trong temp
        self.image_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(self.image_dir, exist_ok=True)
        
        # Tạo thư mục fonts nếu chưa có
        self.fonts_dir = os.path.join(self.assets_dir, "fonts")
        os.makedirs(self.fonts_dir, exist_ok=True)
        
        # Kiểm tra và tải font nếu chưa có
        self._check_and_download_fonts()
    
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
                
                # Sử dụng DALL-E để tạo hình ảnh
                keywords = self._extract_keywords(scene['content'])
                prompt = self._create_image_prompt(keywords, script['title'])
                
                # Tên file
                scene_image_filename = f"scene_{scene_number}.png"
                scene_image_path = os.path.join(project_dir, scene_image_filename)
                
                try:
                    # Tạo hình ảnh bằng DALL-E
                    scene_image = self._generate_image_dalle(prompt, scene_image_path)
                    
                    # Thêm chú thích cho hình ảnh
                    caption = self._create_caption(scene['content'])
                    captioned_image = self._add_caption_to_image(scene_image, caption, project_dir)
                    
                    image_info = {
                        "type": "scene",
                        "number": scene_number,
                        "path": captioned_image,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "content": scene['content'],
                        "prompt_used": prompt
                    }
                    
                except Exception as e:
                    logger.warning(f"Lỗi khi tạo hình ảnh DALL-E cho phân cảnh {scene_number}: {str(e)}")
                    logger.warning("Tạo hình ảnh thay thế")
                    
                    # Tạo hình ảnh thay thế với văn bản
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
                        "content": scene['content']
                    }
                
                images.append(image_info)
                
                # Tránh gọi API quá nhanh
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Lỗi khi xử lý phân cảnh {scene.get('number', 'unknown')}: {str(e)}")
        
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
    
    def _generate_image_dalle(self, prompt, output_path):
        """Tạo hình ảnh bằng DALL-E API
        
        Args:
            prompt (str): Mô tả hình ảnh cần tạo
            output_path (str): Đường dẫn lưu hình ảnh
            
        Returns:
            str: Đường dẫn đến hình ảnh đã tạo
        """
        try:
            logger.info(f"Gọi DALL-E API với prompt: {prompt[:50]}...")
            
            response = self.client.images.generate(
                model="dall-e-3",  # hoặc "dall-e-2" nếu bạn muốn chi phí thấp hơn
                prompt=prompt,
                size="1024x1024",  # Kích thước hình ảnh
                quality="standard",  # hoặc "hd" cho chất lượng cao hơn
                n=1  # Số lượng hình ảnh
            )
            
            image_url = response.data[0].url
            logger.info(f"Đã nhận URL hình ảnh từ DALL-E: {image_url[:50]}...")
            
            # Tải hình ảnh về
            image_response = requests.get(image_url)
            image = Image.open(BytesIO(image_response.content))
            
            # Điều chỉnh kích thước để phù hợp với video
            image = self._resize_image(image)
            
            # Lưu hình ảnh
            image.save(output_path)
            logger.info(f"Đã lưu hình ảnh tại: {output_path}")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Lỗi khi tạo hình ảnh với DALL-E: {str(e)}")
            raise
    
    def _create_title_card(self, title, source, project_dir):
        """Tạo hình ảnh tiêu đề cho phần mở đầu video
        
        Args:
            title (str): Tiêu đề bài viết
            source (str): Nguồn bài viết
            project_dir (str): Thư mục dự án
            
        Returns:
            str: Đường dẫn đến hình ảnh tiêu đề
        """
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
            text_width = title_font.getbbox(line)[2]
            position = ((self.width - text_width) // 2, title_y + i * 70)
            draw.text(position, line, font=title_font, fill=(255, 255, 255))  # Chữ trắng
        
        # Vẽ nguồn (nếu có)
        if source:
            source_text = f"Nguồn: {source}"
            source_width = source_font.getbbox(source_text)[2]
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
        """Tạo hình ảnh kết thúc
        
        Args:
            title (str): Tiêu đề bài viết
            source (str): Nguồn bài viết
            project_dir (str): Thư mục dự án
            
        Returns:
            str: Đường dẫn đến hình ảnh kết thúc
        """
        # Tạo hình ảnh với màu nền khác với intro
        img = Image.new('RGB', (self.width, self.height), color=(51, 0, 102))  # Màu tím đậm
        draw = ImageDraw.Draw(img)
        
        # Tải font
        title_font = self._get_font(size=60)
        subtitle_font = self._get_font(size=40)
        
        # Vẽ chữ "Cảm ơn đã xem"
        thank_you_text = "Cảm ơn đã xem"
        text_width = title_font.getbbox(thank_you_text)[2]
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
            text_width = subtitle_font.getbbox(line)[2]
            position = ((self.width - text_width) // 2, title_y + i * 50)
            draw.text(position, line, font=subtitle_font, fill=(200, 200, 200))  # Chữ xám nhạt
        
        # Lưu hình ảnh
        output_path = os.path.join(project_dir, "outro.png")
        img.save(output_path)
        
        return output_path
    
    def _create_fallback_image(self, scene_number, content, project_dir):
        """Tạo hình ảnh thay thế khi không thể tạo bằng DALL-E
        
        Args:
            scene_number (int): Số thứ tự phân cảnh
            content (str): Nội dung phân cảnh
            project_dir (str): Thư mục dự án
            
        Returns:
            str: Đường dẫn đến hình ảnh thay thế
        """
        # Tạo hình ảnh với một màu nền trung tính
        img = Image.new('RGB', (self.width, self.height), color=(40, 40, 40))  # Màu xám đậm
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
                text_width = len(line) * size * 0.6  # Ước lượng chiều rộng theo số ký tự
            position = ((self.width - text_width) // 2, text_y + i * 50)
            draw.text(position, line, font=font, fill=(255, 255, 255))  # Chữ trắng
        
        # Lưu hình ảnh
        output_path = os.path.join(project_dir, f"fallback_scene_{scene_number}.png")
        img.save(output_path)
        
        return output_path
    
    def _add_caption_to_image(self, image_path, caption, project_dir):
        """Thêm chú thích vào hình ảnh
        
        Args:
            image_path (str): Đường dẫn đến hình ảnh gốc
            caption (str): Chú thích cần thêm
            project_dir (str): Thư mục dự án
            
        Returns:
            str: Đường dẫn đến hình ảnh đã thêm chú thích
        """
        # Mở hình ảnh
        img = Image.open(image_path).convert('RGBA')
        
        # Tạo một lớp overlay trong suốt để đặt chú thích
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Tạo một dải đen mờ ở dưới cùng cho chú thích
        overlay_height = 150
        draw.rectangle(
            [(0, img.height - overlay_height), (img.width, img.height)],
            fill=(0, 0, 0, 180)  # Màu đen với độ mờ 70%
        )
        
        # Gộp hình ảnh gốc với overlay
        img = Image.alpha_composite(img, overlay).convert('RGB')
        draw = ImageDraw.Draw(img)
        
        # Tải font cho chú thích
        font = self._get_font(size=36)
        
        # Chia chú thích thành các dòng
        wrapped_caption = self._wrap_text(caption, font, img.width - 100)
        
        # Chỉ hiển thị tối đa 2 dòng
        if len(wrapped_caption) > 2:
            wrapped_caption = wrapped_caption[:2]
            if len(wrapped_caption[1]) > 3:
                wrapped_caption[1] = wrapped_caption[1][:-3] + "..."
        
        # Vẽ chú thích
        caption_y = img.height - overlay_height + 30  # Căn trên của overlay + padding
        
        for i, line in enumerate(wrapped_caption):
            text_width = font.getbbox(line)[2]
            position = ((img.width - text_width) // 2, caption_y + i * 50)
            draw.text(position, line, font=font, fill=(255, 255, 255))  # Chữ trắng
        
        # Tạo tên file mới
        filename = os.path.basename(image_path)
        base_name = os.path.splitext(filename)[0]
        output_path = os.path.join(project_dir, f"{base_name}_captioned.png")
        
        # Lưu hình ảnh
        img.save(output_path)
        
        return output_path
    
    def _download_and_process_image(self, image_url, output_path):
        """Tải và xử lý hình ảnh từ URL
        
        Args:
            image_url (str): URL của hình ảnh cần tải
            output_path (str): Đường dẫn lưu hình ảnh
            
        Returns:
            str: Đường dẫn đến hình ảnh đã xử lý
        """
        try:
            response = requests.get(image_url, timeout=10)
            if response.status_code != 200:
                logger.warning(f"Không thể tải hình ảnh từ URL: {image_url}. Mã trạng thái: {response.status_code}")
                return None
            
            # Mở hình ảnh từ dữ liệu nhận được
            image = Image.open(BytesIO(response.content))
            
            # Điều chỉnh kích thước hình ảnh
            processed_image = self._resize_image(image)
            
            # Lưu hình ảnh
            processed_image.save(output_path)
            
            return output_path
            
        except Exception as e:
            logger.error(f"Lỗi khi tải và xử lý hình ảnh: {str(e)}")
            return None
    
    def _resize_image(self, image):
        """Điều chỉnh kích thước hình ảnh để phù hợp với kích thước video
        
        Args:
            image (PIL.Image): Hình ảnh cần điều chỉnh
            
        Returns:
            PIL.Image: Hình ảnh đã điều chỉnh
        """
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
        """Trích xuất từ khóa chính từ văn bản
        
        Args:
            text (str): Văn bản cần trích xuất từ khóa
            max_words (int): Số từ tối đa
            
        Returns:
            str: Chuỗi từ khóa
        """
        # Cách đơn giản: lấy câu đầu tiên
        first_sentence = text.split('.')[0].strip()
        
        # Giới hạn số từ
        words = first_sentence.split()
        if len(words) > max_words:
            return ' '.join(words[:max_words])
        return first_sentence
    
    def _create_image_prompt(self, keywords, title):
        """Tạo prompt cho việc tạo hình ảnh
        
        Args:
            keywords (str): Từ khóa trích xuất từ phân cảnh
            title (str): Tiêu đề bài viết
            
        Returns:
            str: Prompt hoàn chỉnh
        """
        return f"""
        Tạo một hình ảnh minh họa chuyên nghiệp cho tin tức với nội dung: {keywords}
        
        Tiêu đề bài viết: {title}
        
        Yêu cầu:
        - Phong cách chuyên nghiệp, phù hợp cho tin tức
        - Rõ ràng, dễ hiểu
        - Không có chữ hoặc chữ ký trong hình
        - Không có biểu tượng nước
        - Tỷ lệ 16:9, không bị cắt xén
        - Chú ý đến ánh sáng và màu sắc để tạo sự thu hút
        """
    
    def _create_caption(self, text):
        """Tạo chú thích ngắn từ văn bản
        
        Args:
            text (str): Văn bản cần tạo chú thích
            
        Returns:
            str: Chú thích
        """
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
        """Chia văn bản thành các dòng phù hợp với chiều rộng
        
        Args:
            text (str): Văn bản cần chia
            font (PIL.ImageFont): Font chữ
            max_width (int): Chiều rộng tối đa
            
        Returns:
            list: Danh sách các dòng văn bản
        """
        words = text.split()
        lines = []
        current_line = words[0] if words else ""
        
        for word in words[1:]:
            # Kiểm tra nếu thêm từ mới vào dòng hiện tại có vượt quá chiều rộng không
            test_line = current_line + " " + word
            text_width = font.getbbox(test_line)[2]
            
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
        # Thử điều chỉnh kích thước nếu có phương thức font_variant
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
        'title': 'Việt Nam phát triển công nghệ AI mới',
        'full_script': 'Nội dung kịch bản...',
        'source': 'VnExpress',
        'scenes': [
            {
                'number': 1,
                'content': 'Các nhà nghiên cứu Việt Nam vừa công bố phát triển thành công công nghệ AI mới.'
            },
            {
                'number': 2,
                'content': 'Công nghệ này có khả năng giải quyết các bài toán phức tạp trong lĩnh vực y tế.'
            }
        ]
    }
    
    generator = ImageGenerator()
    images = generator.generate_images_for_script(test_script)
    
    print(f"Đã tạo {len(images)} hình ảnh:")
    for img in images:
        print(f"- Loại: {img['type']}, Đường dẫn: {img['path']}")