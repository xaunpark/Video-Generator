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
        styles = {
            "informative": "formal and professional, like a news anchor",
            "conversational": "friendly and engaging, like in a podcast",
            "dramatic": "impactful and attention-grabbing, while maintaining accuracy"
        }
        
        style_prompt = styles.get(style, styles["informative"])
        
        try:
            # Chuẩn bị nội dung bài báo
            title = article.get('title', '')
            content = article.get('content', '')
            
            if not title or not content:
                logger.error("Article doesn't have title or content")
                return None
            
            # Giới hạn độ dài nội dung để tiết kiệm token
            max_content_length = 4000
            if len(content) > max_content_length:
                content = content[:max_content_length] + "..."
            
            # Tạo prompt cho OpenAI
            prompt = f"""
            Create a news script with a {style_prompt} tone based on the following article:
            
            TITLE: {title}
            
            CONTENT: {content}
            
            Script requirements:
            1. Short introduction (15-20 words)
            2. Main content (detailed and accurate, about 150-200 words)
            3. Brief conclusion (15-20 words)
            4. Divide into separate scenes, each scene 1-2 sentences
            5. Keep important information: names, locations, numbers
            6. Use standard English, suitable for a news presenter
            
            Format the script with the following structure (important: maintain this exact format):
            
            #SCENE 1#
            [Scene 1 content]
            
            #SCENE 2#
            [Scene 2 content]
            
            #SCENE 3#
            [Scene 3 content]
            
            ...and continue with additional scenes. Each scene must be clearly numbered and separated by empty lines.
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