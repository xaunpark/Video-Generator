# src/voice_generator.py
import os
import logging
import time
import requests
import pyttsx3
from elevenlabs import generate, save, set_api_key
from config.credentials import ELEVENLABS_API_KEY
from config.settings import TEMP_DIR

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoiceGenerator:
    def __init__(self, use_elevenlabs=True):
        """Khởi tạo VoiceGenerator
        
        Args:
            use_elevenlabs (bool): Sử dụng ElevenLabs API thay vì pyttsx3 offline
        """
        self.use_elevenlabs = use_elevenlabs
        self.temp_dir = TEMP_DIR
        
        # Tạo thư mục lưu trữ âm thanh
        self.audio_dir = os.path.join(self.temp_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        
        if self.use_elevenlabs:
            # Kiểm tra API key của ElevenLabs
            if not ELEVENLABS_API_KEY:
                logger.warning("Không tìm thấy ElevenLabs API key. Chuyển sang sử dụng pyttsx3.")
                self.use_elevenlabs = False
            else:
                # Thiết lập API key
                set_api_key(ELEVENLABS_API_KEY)
                logger.info("Đã thiết lập ElevenLabs API key")
        
        if not self.use_elevenlabs:
            # Khởi tạo pyttsx3 cho giọng nói offline
            try:
                self.engine = pyttsx3.init()
                
                # Lấy danh sách giọng nói có sẵn
                voices = self.engine.getProperty('voices')
                
                # Thiết lập giọng nói (ưu tiên giọng tiếng Việt nếu có)
                vietnamese_voice = None
                for voice in voices:
                    if 'vietnam' in voice.name.lower() or 'viet' in voice.name.lower():
                        vietnamese_voice = voice.id
                        break
                
                if vietnamese_voice:
                    self.engine.setProperty('voice', vietnamese_voice)
                    logger.info(f"Đã thiết lập giọng nói tiếng Việt: {vietnamese_voice}")
                else:
                    # Nếu không có giọng tiếng Việt, sử dụng giọng mặc định
                    logger.warning("Không tìm thấy giọng tiếng Việt, sử dụng giọng mặc định")
                
                # Thiết lập tốc độ đọc (mặc định là 200 từ/phút)
                self.engine.setProperty('rate', 170)  # Chậm hơn một chút để rõ ràng hơn
                
                logger.info("Đã khởi tạo pyttsx3 thành công")
            except Exception as e:
                logger.error(f"Lỗi khi khởi tạo pyttsx3: {str(e)}")
                raise
    
    def generate_audio_for_script(self, script):
        """Tạo file âm thanh cho kịch bản
        
        Args:
            script (dict): Kịch bản với các phân cảnh
            
        Returns:
            dict: Thông tin về các file âm thanh đã tạo
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
            
            audio_files.append({
                "type": "full",
                "path": full_audio_path,
                "duration": self._get_audio_duration(full_audio_path),
                "content": full_script_content
            })
            
            logger.info(f"Đã tạo file âm thanh đầy đủ: {full_audio_path}")
        except Exception as e:
            logger.error(f"Lỗi khi tạo file âm thanh đầy đủ: {str(e)}")
        
        # Tạo file âm thanh cho từng phân cảnh (nếu cần)
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
                    
                    audio_files.append({
                        "type": "scene",
                        "number": scene_number,
                        "path": scene_audio_path,
                        "duration": self._get_audio_duration(scene_audio_path),
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
        """Tạo file âm thanh từ văn bản
        
        Args:
            text (str): Văn bản cần chuyển thành giọng nói
            output_path (str): Đường dẫn lưu file âm thanh
            
        Returns:
            str: Đường dẫn đến file âm thanh
        """
        if self.use_elevenlabs:
            try:
                # Sử dụng ElevenLabs API
                audio = generate(
                    text=text,
                    voice="Vietnamese Male",  # hoặc voice_id cụ thể
                    model="eleven_multilingual_v2"
                )
                save(audio, output_path)
                return output_path
            except Exception as e:
                logger.error(f"Lỗi khi tạo âm thanh với ElevenLabs: {str(e)}")
                logger.warning("Chuyển sang sử dụng pyttsx3")
                self.use_elevenlabs = False
                return self._generate_audio_pyttsx3(text, output_path)
        else:
            return self._generate_audio_pyttsx3(text, output_path)
    
    def _generate_audio_pyttsx3(self, text, output_path):
        """Tạo file âm thanh bằng pyttsx3 (offline)
        
        Args:
            text (str): Văn bản cần chuyển thành giọng nói
            output_path (str): Đường dẫn lưu file âm thanh
            
        Returns:
            str: Đường dẫn đến file âm thanh
        """
        try:
            # Thay đổi đuôi file thành .wav vì pyttsx3 chỉ hỗ trợ .wav
            wav_path = output_path.replace('.mp3', '.wav')
            
            # Tạo giọng nói
            self.engine.save_to_file(text, wav_path)
            self.engine.runAndWait()
            
            # Nếu cần file .mp3, chuyển đổi từ .wav sang .mp3
            if output_path.endswith('.mp3'):
                try:
                    # Import trong hàm để tránh lỗi khi không cần
                    import moviepy.editor as mp
                    wav_audio = mp.AudioFileClip(wav_path)
                    wav_audio.write_audiofile(output_path, logger=None)
                    wav_audio.close()
                    
                    # Xóa file .wav tạm thời
                    os.remove(wav_path)
                except Exception as e:
                    logger.warning(f"Không thể chuyển đổi wav sang mp3: {str(e)}")
                    # Sử dụng file wav thay thế
                    output_path = wav_path
            
            return output_path
        except Exception as e:
            logger.error(f"Lỗi khi tạo âm thanh với pyttsx3: {str(e)}")
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
    
    def _get_audio_duration(self, audio_path):
        """Lấy thời lượng của file âm thanh
        
        Args:
            audio_path (str): Đường dẫn đến file âm thanh
            
        Returns:
            float: Thời lượng tính bằng giây
        """
        try:
            from moviepy.editor import AudioFileClip
            audio = AudioFileClip(audio_path)
            duration = audio.duration
            audio.close()
            return duration
        except Exception as e:
            logger.warning(f"Không thể lấy thời lượng âm thanh: {str(e)}")
            return 0
    
    def _save_audio_info(self, audio_files, title, project_dir):
        """Lưu thông tin âm thanh vào file JSON
        
        Args:
            audio_files (list): Danh sách thông tin âm thanh
            title (str): Tiêu đề dự án
            project_dir (str): Thư mục dự án
        """
        import json
        
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
    
    # Test với pyttsx3 (offline)
    generator = VoiceGenerator(use_elevenlabs=False)
    audio_files = generator.generate_audio_for_script(test_script)
    
    print(f"Đã tạo {len(audio_files)} file âm thanh:")
    for audio in audio_files:
        print(f"- Loại: {audio['type']}, Đường dẫn: {audio['path']}, Thời lượng: {audio['duration']}s")