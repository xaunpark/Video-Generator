# src/voice_generator.py
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

from config.credentials import ELEVENLABS_API_KEY
from config.settings import TEMP_DIR

# Tải các biến môi trường
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoiceGenerator:
    def __init__(self):
        """Khởi tạo VoiceGenerator sử dụng ElevenLabs REST API trực tiếp"""
        self.temp_dir = TEMP_DIR
        self.api_key = ELEVENLABS_API_KEY
        
        if not self.api_key:
            logger.error("API key của ElevenLabs không được cung cấp")
            raise ValueError("API key không hợp lệ")
        
        # Cấu hình API 
        self.base_url = "https://api.elevenlabs.io/v1"
        self.headers = {
            "Accept": "application/json",
            "xi-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        # Tạo thư mục lưu trữ âm thanh
        self.audio_dir = os.path.join(self.temp_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        
        # Thiết lập mặc định
        self.voice_id = "21m00Tcm4TlvDq8ikWAM"  # Rachel - Giọng nữ tiếng Anh
        self.model_id = "eleven_monolingual_v1"  # Model cho tiếng Anh
        
        # Kiểm tra kết nối (thay đổi để sử dụng REST API đúng cách)
        self._test_connection()
    
    def _test_connection(self):
        """Kiểm tra kết nối với ElevenLabs API"""
        try:
            # Thử lấy danh sách voices thay vì models
            response = requests.get(
                f"{self.base_url}/voices",
                headers=self.headers
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Kết nối ElevenLabs thành công. Số lượng giọng khả dụng: {len(data.get('voices', []))}")
                
                # Kiểm tra và hiển thị một số giọng đọc
                voices = data.get('voices', [])
                if voices:
                    logger.info("Danh sách giọng có sẵn:")
                    for idx, voice in enumerate(voices[:5]):  # Chỉ hiển thị 5 giọng đầu tiên
                        logger.info(f"  {idx+1}. {voice.get('name')} - ID: {voice.get('voice_id')}")
            else:
                logger.warning(f"Không thể lấy danh sách voices: {response.status_code}, {response.text}")
                
        except Exception as e:
            logger.error(f"Lỗi khi kết nối đến ElevenLabs API: {str(e)}")
    
    def generate_audio_for_script(self, script):
        """Tạo file âm thanh cho kịch bản"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        project_dir = os.path.join(self.audio_dir, f"project_{timestamp}")
        os.makedirs(project_dir, exist_ok=True)
        
        logger.info(f"Bắt đầu tạo giọng nói cho kịch bản: {script['title']}")
        
        audio_files = []
        
        # Tạo file âm thanh cho toàn bộ kịch bản
        try:
            full_script_content = self._extract_full_script_content(script)
            
            full_audio_path = os.path.join(project_dir, "full_audio.mp3")
            self._generate_audio(full_script_content, full_audio_path)
            
            # Ghi âm thành công, thêm thông tin vào danh sách
            duration = self._estimate_duration(full_script_content)
            
            audio_files.append({
                "type": "full",
                "path": full_audio_path,
                "duration": duration,
                "content": full_script_content
            })
            
            logger.info(f"Đã tạo file âm thanh đầy đủ: {full_audio_path}")
        except Exception as e:
            logger.error(f"Lỗi khi tạo file âm thanh đầy đủ: {str(e)}")
        
        # Tạo file âm thanh cho từng phân cảnh
        if script.get('scenes'):
            for scene in script['scenes']:
                try:
                    scene_number = scene['number']
                    content = scene['content']
                    
                    # Tên file
                    scene_audio_filename = f"scene_{scene_number}.mp3"
                    scene_audio_path = os.path.join(project_dir, scene_audio_filename)
                    
                    # Tạo file âm thanh
                    self._generate_audio(content, scene_audio_path)
                    
                    # Ghi âm thành công, thêm thông tin vào danh sách
                    duration = self._estimate_duration(content)
                    
                    audio_files.append({
                        "type": "scene",
                        "number": scene_number,
                        "path": scene_audio_path,
                        "duration": duration,
                        "content": content
                    })
                    
                    logger.info(f"Đã tạo file âm thanh cho phân cảnh {scene_number}")
                except Exception as e:
                    logger.error(f"Lỗi khi tạo file âm thanh cho phân cảnh {scene.get('number', 'unknown')}: {str(e)}")
        
        # Lưu thông tin các file âm thanh
        self._save_audio_info(audio_files, script['title'], project_dir)
        
        logger.info(f"Đã tạo {len(audio_files)} file âm thanh cho kịch bản")
        
        return audio_files
    
    def _generate_audio(self, text, output_path):
        """Tạo file âm thanh từ văn bản sử dụng ElevenLabs REST API trực tiếp"""
        try:
            # Kiểm tra xem văn bản có quá dài không
            if len(text) > 5000:
                logger.warning(f"Văn bản quá dài ({len(text)} ký tự), có thể gây lỗi API. Cắt xuống 5000 ký tự.")
                text = text[:5000]
            
            # URL endpoint text-to-speech
            url = f"{self.base_url}/text-to-speech/{self.voice_id}"
            
            # Payload theo định dạng của API
            payload = {
                "text": text,
                "model_id": self.model_id,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
            
            # Gọi API
            response = requests.post(url, json=payload, headers=self.headers)
            
            # Kiểm tra kết quả
            if response.status_code == 200:
                # Lưu audio vào file
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"Đã tạo file âm thanh tại: {output_path}")
                return output_path
            else:
                error_msg = f"Lỗi API ({response.status_code}): {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)
                
        except Exception as e:
            logger.error(f"Lỗi khi tạo âm thanh với ElevenLabs: {str(e)}")
            raise
    
    def _extract_full_script_content(self, script):
        """Trích xuất nội dung đầy đủ từ kịch bản"""
        if 'full_script' in script and script['full_script']:
            # Xóa các tag #SCENE X# nếu có
            content = script['full_script']
            import re
            content = re.sub(r'#SCENE \d+#', '', content)
            return content.strip()
        
        # Nếu không có full_script, ghép nội dung từ các phân cảnh
        if 'scenes' in script and script['scenes']:
            scene_contents = [scene['content'] for scene in sorted(script['scenes'], key=lambda x: x['number'])]
            return ' '.join(scene_contents)
        
        # Nếu không có cả hai, trả về tiêu đề
        return script.get('title', '')
    
    def _estimate_duration(self, text):
        """Ước tính thời lượng của đoạn âm thanh dựa trên số từ"""
        # Tiếng Anh: trung bình 3 từ/giây khi đọc
        words = text.split()
        return len(words) / 3
    
    def _save_audio_info(self, audio_files, title, project_dir):
        """Lưu thông tin âm thanh vào file JSON"""
        # Tạo bản sao để tránh thay đổi dữ liệu gốc
        audio_info = []
        for audio in audio_files:
            # Chỉ lưu đường dẫn tương đối để dễ di chuyển
            audio_copy = audio.copy()
            audio_copy['rel_path'] = os.path.basename(audio['path'])
            audio_info.append(audio_copy)
        
        output_file = os.path.join(project_dir, "audio_info.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'title': title,
                'creation_time': time.strftime("%Y-%m-%d %H:%M:%S"),
                'project_dir': os.path.basename(project_dir),
                'audio_files': audio_info
            }, f, ensure_ascii=False, indent=4)
        
        logger.info(f"Đã lưu thông tin âm thanh tại: {output_file}")

# Test module nếu chạy trực tiếp
if __name__ == "__main__":
    # Script giả lập để test
    test_script = {
        'title': 'AI Innovation in Healthcare',
        'full_script': 'Researchers have announced a breakthrough in AI technology for healthcare applications. The new AI system can efficiently diagnose complex medical conditions with high accuracy.',
        'scenes': [
            {
                'number': 1,
                'content': 'Researchers have announced a breakthrough in AI technology for healthcare applications.'
            },
            {
                'number': 2,
                'content': 'The new AI system can efficiently diagnose complex medical conditions with high accuracy.'
            }
        ]
    }
    
    # Test
    try:
        generator = VoiceGenerator()
        audio_files = generator.generate_audio_for_script(test_script)
        
        print(f"Đã tạo {len(audio_files)} file âm thanh:")
        for audio in audio_files:
            print(f"- Loại: {audio['type']}, Đường dẫn: {audio['path']}, Thời lượng: {audio['duration']}s")
    except Exception as e:
        print(f"Lỗi khi test module: {str(e)}")