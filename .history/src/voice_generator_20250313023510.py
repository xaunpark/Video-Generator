# src/voice_generator.py
import os
import sys
import logging
import time
import json
from dotenv import load_dotenv

# Thêm thư mục gốc vào sys.path để có thể import các module từ thư mục gốc
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
        """Khởi tạo VoiceGenerator chỉ sử dụng ElevenLabs"""
        self.temp_dir = TEMP_DIR
        
        # Tạo thư mục lưu trữ âm thanh
        self.audio_dir = os.path.join(self.temp_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        
        # Kiểm tra và khởi tạo ElevenLabs client
        try:
            # Import thư viện ElevenLabs
            from elevenlabs.client import ElevenLabs
            
            # Khởi tạo client
            self.client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
            logger.info("Đã khởi tạo ElevenLabs client thành công")
            
            # Kiểm tra kết nối với ElevenLabs API
            try:
                # Lấy danh sách models
                models = self.client.models.get_all()
                logger.info(f"Kết nối ElevenLabs thành công. Số lượng model khả dụng: {len(models)}")
                
                # Lấy danh sách voices
                voices = self.client.voices.get_all()
                logger.info(f"Số lượng voices khả dụng: {len(voices)}")
                
                # Tìm kiếm giọng tiếng Việt nếu có
                vietnamese_voice = None
                for voice in voices:
                    if hasattr(voice, 'name') and ('vietnamese' in voice.name.lower() or 'viet' in voice.name.lower()):
                        vietnamese_voice = voice.voice_id
                        logger.info(f"Đã tìm thấy giọng tiếng Việt: {voice.name}, ID: {voice.voice_id}")
                        break
                
                # Lưu ID giọng đã chọn
                self.voice_id = vietnamese_voice if vietnamese_voice else "c8Vkv3mdER2fkhJdEIPK"  # Mặc định giọng nam tiếng Việt
                
                # Lưu model ID
                self.model_id = "eleven_multilingual_v2"  # Multilingual model hỗ trợ tiếng Việt
                
            except Exception as e:
                logger.error(f"Lỗi khi kết nối đến ElevenLabs API: {str(e)}")
                raise
        except ImportError:
            logger.error("Không thể import thư viện ElevenLabs. Hãy cài đặt với lệnh 'pip install elevenlabs'")
            raise
        except Exception as e:
            logger.error(f"Lỗi khi khởi tạo ElevenLabs client: {str(e)}")
            raise
    
    def generate_audio_for_script(self, script):
        """Tạo file âm thanh cho kịch bản
        
        Args:
            script (dict): Kịch bản với các phân cảnh
            
        Returns:
            list: Danh sách thông tin các file âm thanh đã tạo
        """
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
        """Tạo file âm thanh từ văn bản sử dụng ElevenLabs API
        
        Args:
            text (str): Văn bản cần chuyển thành giọng nói
            output_path (str): Đường dẫn lưu file âm thanh
            
        Returns:
            str: Đường dẫn đến file âm thanh
        """
        try:
            # Kiểm tra xem văn bản có quá dài không
            if len(text) > 5000:
                logger.warning(f"Văn bản quá dài ({len(text)} ký tự), có thể gây lỗi API. Cắt xuống 5000 ký tự.")
                text = text[:5000]
            
            # Sử dụng ElevenLabs API
            audio = self.client.text_to_speech.convert(
                text=text,
                voice_id=self.voice_id,
                model_id=self.model_id,
                output_format="mp3_44100_128",
            )
            
            # Lưu audio vào file
            with open(output_path, 'wb') as f:
                f.write(audio)
            
            logger.info(f"Đã tạo file âm thanh tại: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Lỗi khi tạo âm thanh với ElevenLabs: {str(e)}")
            raise
    
    def _extract_full_script_content(self, script):
        """Trích xuất nội dung đầy đủ từ kịch bản
        
        Args:
            script (dict): Kịch bản
            
        Returns:
            str: Nội dung đầy đủ
        """
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
        """Ước tính thời lượng của đoạn âm thanh dựa trên số từ
        
        Args:
            text (str): Văn bản
            
        Returns:
            float: Thời lượng ước tính tính bằng giây
        """
        # Tiếng Việt: trung bình 2.5 từ/giây khi đọc
        words = text.split()
        return len(words) / 2.5
    
    def _save_audio_info(self, audio_files, title, project_dir):
        """Lưu thông tin âm thanh vào file JSON
        
        Args:
            audio_files (list): Danh sách thông tin âm thanh
            title (str): Tiêu đề dự án
            project_dir (str): Thư mục dự án
        """
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
        'title': 'Việt Nam phát triển công nghệ AI mới',
        'full_script': 'Các nhà nghiên cứu Việt Nam vừa công bố phát triển thành công công nghệ AI mới. Công nghệ này có khả năng giải quyết các bài toán phức tạp trong lĩnh vực y tế.',
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
    
    # Test
    try:
        generator = VoiceGenerator()
        audio_files = generator.generate_audio_for_script(test_script)
        
        print(f"Đã tạo {len(audio_files)} file âm thanh:")
        for audio in audio_files:
            print(f"- Loại: {audio['type']}, Đường dẫn: {audio['path']}, Thời lượng: {audio['duration']}s")
    except Exception as e:
        print(f"Lỗi khi test module: {str(e)}")