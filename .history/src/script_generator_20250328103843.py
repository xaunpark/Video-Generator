# src/script_generator.py
import os
import sys
import logging
import time
import json
import requests
from dotenv import load_dotenv

# Thêm thư mục gốc vào sys.path
if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from config.credentials import OPENAI_API_KEY
from config.settings import TEMP_DIR

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
    
    def generate_script(self, article, style="informative"):
        """Tạo kịch bản từ bài báo
        
        Args:
            article (dict): Bài báo với các khóa title, content, url, v.v.
            style (str): Phong cách kịch bản (informative, conversational, dramatic)
            
        Returns:
            dict: Kịch bản đã tạo bao gồm full_script và danh sách các scenes
        """
        styles = {
            "informative": "formal and professional, like a news anchor",
            "conversational": "friendly and engaging, like in a podcast",
            "dramatic": "impactful and attention-grabbing, while maintaining accuracy",
            "controversial": "provocative and debate-sparking, highlighting conflicting viewpoints and tensions"

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
            response = self._call_openai_api(prompt)
            
            if not response:
                logger.error("Không nhận được phản hồi từ OpenAI API")
                return None
            
            # Lấy kịch bản từ phản hồi
            full_script = response
            
            # Phân tích kịch bản thành các phân cảnh
            scenes = self._parse_scenes(full_script)
            
            logger.info(f"Đã tạo kịch bản với {len(scenes)} phân cảnh cho bài: {title}")
            
            return {
                "title": title,
                "full_script": full_script,
                "scenes": scenes,
                "source": article.get('source', 'Unknown'),
                "url": article.get('url', '')
            }
            
        except Exception as e:
            logger.error(f"Lỗi khi tạo kịch bản: {str(e)}")
            return None
    
    def _call_openai_api(self, prompt):
        """Gọi OpenAI API để tạo kịch bản
        
        Args:
            prompt (str): Prompt gửi đến OpenAI
            
        Returns:
            str: Phản hồi từ OpenAI, hoặc None nếu có lỗi
        """
        try:
            url = f"{self.base_url}/chat/completions"
            
            payload = {
                "model": "gpt-4o-mini",  # hoặc model khác phù hợp
                "messages": [
                    {"role": "system", "content": "You are a professional script writer for news videos."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }
            
            response = requests.post(url, headers=self.headers, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content'].strip()
            else:
                logger.error(f"Lỗi API OpenAI: {response.status_code}, {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Lỗi khi gọi OpenAI API: {str(e)}")
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
        'title': 'AI Innovation in Healthcare',
        'content': 'Researchers have announced a breakthrough in AI technology for healthcare applications. The new AI system can efficiently diagnose complex medical conditions with high accuracy.',
        'source': 'Tech News'
    }
    
    # Test
    try:
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
        else:
            print("Không thể tạo kịch bản")
    except Exception as e:
        print(f"Lỗi khi test module: {str(e)}")