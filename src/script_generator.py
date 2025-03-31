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
                Create a highly controversial, fast-paced news script in VIETNAMESE based on the following article. The script must generate debate, provoke strong reactions, and maximize viewer engagement with a dynamic rhythm:

                TITLE: {title}

                CONTENT: {content}

                **CRITICAL Script Requirements (Follow Strictly):**
                1.  **Ultra-short Scenes:** Each scene MUST contain **only ONE impactful sentence**, maximum two extremely short ones if absolutely necessary. Aim for a rapid-fire feel.
                2.  **Shocking Opener:** Start immediately with the single most shocking or challenging statement/question from the article. No slow introduction.
                3.  **Intensify Debate:** Immediately frame the topic as a fierce conflict or dilemma. Use strong, emotionally charged words (but factually grounded).
                4.  **Highlight Division:** Focus exclusively on the most polarizing aspects and conflicting viewpoints.
                5.  **Rapid-Fire Questions:** **Frequently inject short, sharp rhetorical or direct questions** aimed at the viewer or challenging the stated facts/opinions.
                6.  **Contrasting Snippets:** **Extract or paraphrase very short, punchy quotes/statements** representing opposing sides. Place them in consecutive or nearby scenes for maximum contrast and whiplash effect.
                7.  **Escalate Tension:** Ensure the sequence of scenes builds tension or highlights the irresolvable nature of the conflict.
                8.  **More Scenes, Shorter Content:** **Generate MANY short scenes.** Break down complex arguments or information into multiple quick, distinct scenes rather than packing info into one. Prioritize rhythm over detail in each scene.
                9.  **Provocative Closer:** End with a single, extremely provocative question that forces viewers to take a side or question everything.

                **Formatting (Mandatory):**
                - Use `#SCENE X#` markers for each scene number (X).
                - Each scene marker must be on its own line.
                - The single sentence (or max two short ones) for the scene follows the marker on the next line(s).
                - Leave one empty line between the content of one scene and the marker for the next scene.

                **Example Snippet Structure:**
                #SCENE 1#
                [Single shocking sentence here.]

                #SCENE 2#
                [Short sentence presenting one extreme view.]

                #SCENE 3#
                [Short sentence presenting the opposing extreme view.]

                #SCENE 4#
                [Sharp question challenging the situation?]

                #SCENE 5#
                [...]

                **Language:** VIETNAMESE

                **Goal:** Create a script that feels fast, intense, argumentative, and leaves the viewer feeling agitated and needing to comment. Maximize the number of scenes by keeping each one minimal.
                """
            else:
                # Prompt gốc cho các phong cách khác (ĐÃ SỬA ĐỔI)
                prompt = f"""
                Create a news script with a {style_prompt} tone based on the following article. The script should be concise and have a good pace.

                TITLE: {title}

                CONTENT: {content}

                **Script Requirements (Follow Strictly):**
                1.  **Concise Scenes:** Divide the content into multiple distinct scenes. Each scene should ideally contain **only ONE main idea or sentence**, maximum two short sentences.
                2.  **Brisk Pace:** Aim for a steady, informative but not sluggish pace. More scenes with shorter content is preferred over fewer scenes with long content.
                3.  **Clear Structure:** Short introduction (1 scene), main points (multiple scenes), brief conclusion (1 scene).
                4.  **Accuracy:** Keep important information: names, locations, numbers, key facts.
                5.  **Language:** Use clear {article.get('language', 'en')} suitable for the chosen style ({style_prompt}).

                **Formatting (Mandatory):**
                - Use `#SCENE X#` markers for each scene number (X).
                - Each scene marker must be on its own line.
                - The single sentence (or max two short ones) for the scene follows the marker on the next line(s).
                - Leave one empty line between the content of one scene and the marker for the next scene.

                **Example Snippet Structure:**
                #SCENE 1#
                [Short introductory sentence.]

                #SCENE 2#
                [Sentence for the first key point.]

                #SCENE 3#
                [Sentence for the second key point.]

                #SCENE 4#
                [...]

                #SCENE N#
                [Short concluding sentence.]

                **Goal:** A clear, well-paced script divided into minimal, single-idea scenes.
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