# src/voice_generator.py
import os
import sys
import logging
import time
import json
import requests
import mutagen.mp3
from dotenv import load_dotenv

# Thêm thư mục gốc vào sys.path
if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from config.credentials import OPENAI_API_KEY
from config.settings import TEMP_DIR

# Tải các biến môi trường
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoiceGenerator:
    def __init__(self):
        """Khởi tạo VoiceGenerator sử dụng OpenAI TTS API"""
        self.temp_dir = TEMP_DIR
        self.api_key = OPENAI_API_KEY
        
        if not self.api_key:
            logger.error("API key của OpenAI không được cung cấp")
            raise ValueError("API key không hợp lệ")
        
        # Cấu hình API OpenAI
        self.base_url = "https://api.openai.com/v1/audio/speech"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Tạo thư mục lưu trữ âm thanh
        self.audio_dir = os.path.join(self.temp_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        
        # Thiết lập mặc định cho OpenAI TTS
        self.voice = "alloy"  # Các lựa chọn: alloy, echo, fable, onyx, nova, shimmer
        self.model = "tts-1"  # hoặc "tts-1-hd" cho chất lượng cao hơn
        
        # Kiểm tra kết nối
        self._test_connection()
    
    def _test_connection(self):
        """Kiểm tra kết nối với OpenAI API"""
        try:
            # Tạo một đoạn audio ngắn để kiểm tra kết nối
            test_text = "OpenAI TTS connection test."
            
            payload = {
                "model": self.model,
                "input": test_text,
                "voice": self.voice
            }
            
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload
            )
            
            if response.status_code == 200:
                logger.info("Kết nối OpenAI TTS API thành công.")
                logger.info(f"Đang sử dụng model: {self.model} với giọng: {self.voice}")
            else:
                logger.warning(f"Không thể kết nối đến OpenAI TTS API: {response.status_code}, {response.text}")
                
        except Exception as e:
            logger.error(f"Lỗi khi kết nối đến OpenAI TTS API: {str(e)}")
    
    def generate_audio_for_script(self, script):
        """Tạo file âm thanh cho kịch bản và lấy thời lượng chính xác."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        project_dir = os.path.join(self.audio_dir, f"project_{timestamp}")
        os.makedirs(project_dir, exist_ok=True)
        
        logger.info(f"Bắt đầu tạo giọng nói cho kịch bản: {script['title']}")
        
        audio_files = []
        
        # Tạo file âm thanh cho toàn bộ kịch bản
        try:
            full_script_content = self._extract_full_script_content(script)
            full_audio_path = os.path.join(project_dir, "full_audio.mp3")

            # Tạo file âm thanh
            self._generate_audio(full_script_content, full_audio_path)
            
            # --- LẤY THỜI LƯỢNG THỰC TẾ CHO FULL AUDIO ---
            actual_full_duration = 0.0
            try:
                # Kiểm tra file tồn tại trước khi đọc
                if os.path.exists(full_audio_path):
                    audio_info = mutagen.mp3.MP3(full_audio_path)
                    actual_full_duration = audio_info.info.length # Thời lượng tính bằng giây
                    logger.info(f"Thời lượng thực tế (mutagen) cho full audio: {actual_full_duration:.2f}s")
                else:
                    logger.warning(f"File {full_audio_path} không tồn tại sau khi tạo. Không thể lấy thời lượng.")
                    actual_full_duration = self._estimate_duration(full_script_content) # Fallback estimation

            except Exception as e:
                logger.warning(f"Lỗi khi đọc thời lượng file {full_audio_path} bằng mutagen: {e}. Sử dụng ước tính.")
                actual_full_duration = self._estimate_duration(full_script_content) # Fallback estimation
            # --- KẾT THÚC LẤY THỜI LƯỢNG ---

            # Ghi âm thành công, thêm thông tin vào danh sách với thời lượng thực tế
            audio_files.append({
                "type": "full",
                "path": full_audio_path,
                "duration": actual_full_duration, # <-- SỬ DỤNG THỜI LƯỢNG THỰC TẾ
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

                    # --- LẤY THỜI LƯỢNG THỰC TẾ CHO SCENE ---
                    actual_scene_duration = 0.0
                    try:
                         # Kiểm tra file tồn tại trước khi đọc
                        if os.path.exists(scene_audio_path):
                            audio_info = mutagen.mp3.MP3(scene_audio_path)
                            actual_scene_duration = audio_info.info.length # Thời lượng tính bằng giây
                            logger.info(f"Thời lượng thực tế (mutagen) cho scene {scene_number}: {actual_scene_duration:.2f}s")
                        else:
                            logger.warning(f"File {scene_audio_path} không tồn tại sau khi tạo. Không thể lấy thời lượng.")
                            actual_scene_duration = self._estimate_duration(content) # Fallback estimation

                    except Exception as e:
                        logger.warning(f"Lỗi khi đọc thời lượng file {scene_audio_path} bằng mutagen: {e}. Sử dụng ước tính.")
                        actual_scene_duration = self._estimate_duration(content) # Fallback estimation
                    # --- KẾT THÚC LẤY THỜI LƯỢNG ---

                    # Ghi âm thành công, thêm thông tin vào danh sách với thời lượng thực tế
                    audio_files.append({
                        "type": "scene",
                        "number": scene_number,
                        "path": scene_audio_path,
                        "duration": actual_scene_duration, # <-- SỬ DỤNG THỜI LƯỢNG THỰC TẾ
                        "content": content
                    })

                    # Bỏ log cũ nếu không cần thiết nữa
                    # logger.info(f"Đã tạo file âm thanh cho phân cảnh {scene_number}")
                except Exception as e:
                    logger.error(f"Lỗi khi tạo file âm thanh cho phân cảnh {scene.get('number', 'unknown')}: {str(e)}")

        # Lưu thông tin các file âm thanh (không cần sửa hàm này)
        self._save_audio_info(audio_files, script['title'], project_dir)

        logger.info(f"Đã tạo {len(audio_files)} file âm thanh cho kịch bản (với thời lượng thực tế)")

        return audio_files
    
    def _generate_audio(self, text, output_path):
        """Tạo file âm thanh từ văn bản sử dụng OpenAI TTS API"""
        try:
            # Kiểm tra xem văn bản có quá dài không
            # OpenAI TTS có giới hạn khoảng 4096 tokens (khoảng 3000 từ)
            if len(text) > 4000:
                logger.warning(f"Văn bản quá dài ({len(text)} ký tự), có thể gây lỗi API. Cắt xuống 4000 ký tự.")
                text = text[:4000]
            
            # Payload theo định dạng của API OpenAI
            payload = {
                "model": self.model,
                "input": text,
                "voice": self.voice,
                "response_format": "mp3"
            }
            
            # Gọi API
            response = requests.post(self.base_url, json=payload, headers=self.headers)
            
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
            logger.error(f"Lỗi khi tạo âm thanh với OpenAI TTS: {str(e)}")
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
        """Ước tính thời lượng của đoạn âm thanh dựa trên số từ (DÙNG LÀM FALLBACK)"""
        # Tiếng Anh: trung bình 3 từ/giây khi đọc
        words = text.split()
        return len(words) / 3.0 if len(words) > 0 else 0.0
    
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
    
    def set_voice(self, voice):
        """Thiết lập giọng đọc"""
        valid_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        if voice in valid_voices:
            self.voice = voice
            logger.info(f"Đã thiết lập giọng đọc: {voice}")
        else:
            logger.warning(f"Giọng không hợp lệ: {voice}. Sử dụng giọng mặc định: {self.voice}")
    
    def set_model(self, model):
        """Thiết lập model TTS"""
        valid_models = ["tts-1", "tts-1-hd"]
        if model in valid_models:
            self.model = model
            logger.info(f"Đã thiết lập model: {model}")
        else:
            logger.warning(f"Model không hợp lệ: {model}. Sử dụng model mặc định: {self.model}")

# Test module nếu chạy trực tiếp
# python -m src.voice_generator

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
        
        # Bạn có thể thử các giọng khác nhau
        # generator.set_voice("nova")
        # generator.set_model("tts-1-hd")  # Chất lượng cao hơn
        
        audio_files = generator.generate_audio_for_script(test_script)
        
        print(f"Đã tạo {len(audio_files)} file âm thanh:")
        for audio in audio_files:
            print(f"- Loại: {audio['type']}, Đường dẫn: {audio['path']}, Thời lượng: {audio['duration']}s")
    except Exception as e:
        print(f"Lỗi khi test module: {str(e)}")