# src/script_generator.py
import os
import sys
import logging
import time
import json
import requests
from dotenv import load_dotenv
from src.scene_video_detector import enhance_script_with_video_annotations

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
            style (str): Phong cách kịch bản (informative, conversational, dramatic, controversial)
            
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
            max_content_length = 10000
            if len(content) > max_content_length:
                content = content[:max_content_length] + "..."
            
            # Tạo prompt dựa vào phong cách được chọn
            if style == "controversial":
                prompt = f"""
                Create a highly controversial news script based on the following article. The script should generate debate, provoke strong reactions, and maximize viewer engagement:
                
                TITLE: {title}
                                
                CONTENT: {content}
                                
                Script requirements:
                1. Start with a shocking statement or question that challenges mainstream views
                2. Frame the topic as a heated debate between opposing sides
                3. Use emotionally charged language while maintaining factual accuracy
                4. Highlight the most divisive aspects of the story
                5. Emphasize how this topic affects different groups in conflicting ways
                6. Include multiple perspectives with escalating tension throughout
                7. End with a provocative question that encourages viewers to comment
                8. Keep each scene short and intense (1-2 sentences)
                9. Create as many scenes as needed to fully explore the controversy
                                
                Format the script with the following structure (important: maintain this exact format):
                                
                #SCENE 1#
                [First scene content - shocking opening]
                                
                #SCENE 2#
                [Next scene content]

                ... continue with additional scenes as needed to fully explore opposing viewpoints, escalating tensions, and conflicting expert opinions.

                End with a final scene that poses a provocative question to spark debate.

                Each scene must be clearly numbered and separated by empty lines.
                """
            else:
                # Prompt gốc cho các phong cách khác
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
            response = self._call_openai_api(prompt, style)
            
            if not response:
                logger.error("Không nhận được phản hồi từ OpenAI API")
                return None
            
            # Lấy kịch bản từ phản hồi
            full_script = response
            
            # Phân tích kịch bản thành các phân cảnh
            scenes = self._parse_scenes(full_script)
            
            logger.info(f"Đã tạo kịch bản với {len(scenes)} phân cảnh cho bài: {title}")
            
            # Tạo script object để trả về
            script = {
                "title": title,
                "full_script": full_script,
                "scenes": scenes,
                "source": article.get('source', 'Unknown'),
                "url": article.get('url', ''),
                "style": style
            }
            
            # Phân tích và đánh dấu các scene nên dùng video
            try:
                # Kiểm tra xem tính năng video clips có được bật không
                from config.settings import VIDEO_SETTINGS
                if VIDEO_SETTINGS.get("enable_video_clips", False):
                    logger.info(f"Phân tích {len(scenes)} scene để xác định nên dùng video...")
                    enhanced_script = enhance_script_with_video_annotations(script)
                    
                    # Log kết quả phân tích để debug
                    video_scenes = sum(1 for scene in enhanced_script.get('scenes', []) if scene.get('prefer_video', False))
                    logger.info(f"Kết quả phân tích: {video_scenes}/{len(scenes)} scene nên dùng video")
                    
                    return enhanced_script
                else:
                    logger.info("Tính năng video clips đang bị tắt trong cài đặt")
                    return script
            except ImportError as e:
                logger.warning(f"Không thể import module scene_video_detector: {str(e)}")
                return script
            except Exception as e:
                logger.error(f"Lỗi khi phân tích scene cho video: {str(e)}")
                return script
            
        except Exception as e:
            logger.error(f"Lỗi khi tạo kịch bản: {str(e)}")
            return None
    
    def _call_openai_api(self, prompt, style="informative"):
        """Gọi OpenAI API để tạo kịch bản
        
        Args:
            prompt (str): Prompt gửi đến OpenAI
            style (str): Phong cách kịch bản
            
        Returns:
            str: Phản hồi từ OpenAI, hoặc None nếu có lỗi
        """
        try:
            url = f"{self.base_url}/chat/completions"
            
            # Điều chỉnh system prompt dựa trên phong cách
            system_content = "You are a professional script writer for news videos."
            if style == "controversial":
                system_content = "You are a provocative script writer who creates engaging, debate-sparking news content that presents multiple perspectives in an emotionally charged manner while maintaining factual accuracy."
            
            payload = {
                "model": "gpt-4o",  # hoặc model khác phù hợp
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.8 if style == "controversial" else 0.7,  # Tăng nhiệt độ cho phong cách gây tranh cãi
                "max_tokens": 10000
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
        'content': 'Researchers have announced a breakthrough in AI technology for healthcare applications. The new AI system can efficiently diagnose complex medical conditions with high accuracy. However, some privacy advocates express concerns about patient data security and the potential for reduced human oversight in critical medical decisions. The technology has shown promising results in early trials, correctly identifying 95% of test cases compared to 89% accuracy from experienced doctors. Medical associations are debating guidelines for AI implementation while tech companies push for faster adoption.',
        'source': 'Tech News'
    }
    
    # Test
    try:
        generator = ScriptGenerator()
        
        # Test phong cách thông thường
        script_normal = generator.generate_script(test_article, "informative")
        
        # Test phong cách gây tranh cãi
        script_controversial = generator.generate_script(test_article, "controversial")
        
        # Hiển thị kết quả
        if script_normal:
            print(f"\n=== PHONG CÁCH THÔNG THƯỜNG ===")
            print(f"Tiêu đề: {script_normal['title']}")
            print("\nKịch bản đầy đủ:")
            print(script_normal['full_script'])
        
        if script_controversial:
            print(f"\n\n=== PHONG CÁCH GÂY TRANH CÃI ===")
            print(f"Tiêu đề: {script_controversial['title']}")
            print("\nKịch bản đầy đủ:")
            print(script_controversial['full_script'])
            
    except Exception as e:
        print(f"Lỗi khi test module: {str(e)}")