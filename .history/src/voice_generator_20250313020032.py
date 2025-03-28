# src/voice_generator.py
import os
import logging
import time
import pyttsx3
from config.settings import TEMP_DIR

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoiceGenerator:
    def __init__(self, use_elevenlabs=False):
        """Khởi tạo VoiceGenerator
        
        Args:
            use_elevenlabs (bool): Khởi tạo với elevenlabs (hiện đã bị tắt do API thay đổi)
        """
        self.temp_dir = TEMP_DIR
        
        # Tạo thư mục lưu trữ âm thanh
        self.audio_dir = os.path.join(self.temp_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        
        # Chỉ sử dụng pyttsx3 vì elevenlabs API đã thay đổi
        try:
            self.engine = pyttsx3.init()
            
            # Lấy danh sách giọng nói có sẵn
            voices = self.engine.getProperty('voices')
            
            # In ra danh sách giọng để dễ dàng chọn lựa
            logger.info(f"Đã tìm thấy {len(voices)} giọng nói:")
            for i, voice in enumerate(voices):
                logger.info(f"{i}: ID={voice.id}, Tên={voice.name}")
            
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
            
            full_audio_path = os.path.join(project_dir, "full_audio.wav")
            self._generate_audio(full_script_content, full_audio_path)
            
            audio_files.append({
                "type": "full",
                "path": full_audio_path,
                "duration": 0,  # Không tính thời lượng
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
                    scene_audio_filename = f"scene_{scene_number}.wav"
                    scene_audio_path = os.path.join(project_dir, scene_audio_filename)
                    
                    # Tạo file âm thanh
                    self._generate_audio(content, scene_audio_path)
                    
                    audio_files.append({
                        "type": "scene",
                        "number": scene_number,
                        "path": scene_audio_path,
                        "duration": 0,  # Không tính thời lượng
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
        try:
            # Tạo giọng nói và lưu thành file
            self.engine.save_to_file(text, output_path)
            self.engine.runAndWait()
            return output_path
        except Exception as e:
            logger.error(f"Lỗi khi tạo âm thanh: {str(e)}")
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