# src/script_generator.py
import logging
from openai import OpenAI
from config.credentials import OPENAI_API_KEY

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ScriptGenerator:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
    
    def generate_script(self, article, style="informative"):
        """Tạo kịch bản từ bài báo
        
        Args:
            article (dict): Bài báo với các khóa title, content, url, v.v.
            style (str): Phong cách kịch bản (informative, conversational, dramatic)
            
        Returns:
            dict: Kịch bản đã tạo bao gồm full_script và danh sách các scenes
        """
        styles = {
            "informative": "trang trọng, chuyên nghiệp như người dẫn bản tin chính thức",
            "conversational": "thân thiện, trò chuyện như trong một podcast thông tin",
            "dramatic": "kịch tính, gây ấn tượng mạnh nhưng vẫn giữ tính chính xác của tin tức"
        }
        
        style_prompt = styles.get(style, styles["informative"])
        
        try:
            # Chuẩn bị nội dung bài báo
            title = article.get('title', '')
            content = article.get('content', '')
            
            if not title or not content:
                logger.error("Bài báo không có tiêu đề hoặc nội dung")
                return None
            
            # Giới hạn độ dài nội dung để tiết kiệm token
            max_content_length = 4000
            if len(content) > max_content_length:
                content = content[:max_content_length] + "..."
            
            # Tạo prompt cho OpenAI
            prompt = f"""
            Hãy tạo một kịch bản tin tức với giọng điệu {style_prompt} dựa trên bài báo sau:
            
            TIÊU ĐỀ: {title}
            
            NỘI DUNG: {content}
            
            Yêu cầu kịch bản:
            1. Mở đầu ngắn gọn (15-20 từ)
            2. Nội dung chính (chi tiết và chính xác, khoảng 150-200 từ)
            3. Kết luận ngắn gọn (15-20 từ)
            4. Chia thành các phân cảnh riêng biệt, mỗi phân cảnh 1-2 câu
            5. Giữ nguyên các thông tin quan trọng: tên người, địa điểm, số liệu
            6. Sử dụng tiếng Việt chuẩn mực, dễ đọc cho người dẫn chương trình
            
            Format kịch bản theo cấu trúc sau (quan trọng: giữ đúng định dạng này):
            
            #SCENE 1#
            [Nội dung phân cảnh 1]
            
            #SCENE 2#
            [Nội dung phân cảnh 2]
            
            #SCENE 3#
            [Nội dung phân cảnh 3]
            
            ...và tiếp tục với các phân cảnh khác. Mỗi phân cảnh phải được đánh số rõ ràng và cách nhau bằng dòng trống.
            """
            
            # Gọi OpenAI API
            response = self.client.chat.completions.create(
                model="gpt-4o", # hoặc model khác phù hợp
                messages=[
                    {"role": "system", "content": "Bạn là một biên kịch chuyên nghiệp cho các video tin tức."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
            )
            
            # Lấy kịch bản từ phản hồi
            full_script = response.choices[0].message.content.strip()
            
            # Phân tích kịch bản thành các phân cảnh
            scenes = self._parse_scenes(full_script)
            
            logger.info(f"Đã tạo kịch bản với {len(scenes)} phân cảnh cho bài: {title}")
            
            return {
                "title": title,
                "full_script": full_script,
                "scenes": scenes,
                "source": article.get('source', 'Không rõ nguồn'),
                "url": article.get('url', '')
            }
            
        except Exception as e:
            logger.error(f"Lỗi khi tạo kịch bản: {str(e)}")
            return None
    
    def _parse_scenes(self, script):
        """Phân tích kịch bản thành các phân cảnh riêng biệt
        
        Args:
            script (str): Kịch bản đầy đủ
            
        Returns:
            list: Danh sách các phân cảnh, mỗi phân cảnh là một dict
        """
        scenes = []
        current_scene = ""
        scene_number = 0
        
        lines = script.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('#SCENE'):
                # Lưu phân cảnh trước đó (nếu có)
                if current_scene and scene_number > 0:
                    scenes.append({
                        "number": scene_number,
                        "content": current_scene.strip()
                    })
                # Bắt đầu phân cảnh mới
                try:
                    scene_number = int(line.replace('#SCENE', '').replace('#', '').strip())
                    current_scene = ""
                except ValueError:
                    logger.warning(f"Không thể phân tích số phân cảnh từ: {line}")
                    continue
            elif line and scene_number > 0:
                current_scene += line + "\n"
        
        # Thêm phân cảnh cuối cùng
        if current_scene and scene_number > 0:
            scenes.append({
                "number": scene_number,
                "content": current_scene.strip()
            })
        
        return scenes

# Test module nếu chạy trực tiếp
if __name__ == "__main__":
    # Tạo bài báo giả để test
    test_article = {
        'title': 'Tiêu đề bài báo test',
        'content': 'Nội dung bài báo test. Đây là một đoạn văn bản mẫu để kiểm tra chức năng tạo kịch bản.',
        'source': 'Nguồn Test'
    }
    
    generator = ScriptGenerator()
    script = generator.generate_script(test_article)
    
    if script:
        print(f"Tiêu đề: {script['title']}")
        print("\nKịch bản đầy đủ:")
        print(script['full_script'])
        
        print("\nCác phân cảnh:")
        for scene in script['scenes']:
            print(f"\nPhân cảnh {scene['number']}:")
            print(scene['content'])