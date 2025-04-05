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
            """Tạo file âm thanh cho từng speech_unit trong kịch bản."""
            # Tạo thư mục project dựa trên project_id hoặc timestamp
            project_id = script.get('project_id', f"project_{time.strftime('%Y%m%d%H%M%S')}")
            project_audio_dir = os.path.join(self.audio_dir, project_id)
            os.makedirs(project_audio_dir, exist_ok=True)

            logger.info(f"Bắt đầu tạo giọng nói cho script: '{script['title']}' (Project: {project_id}, theo speech units)")

            # Danh sách lưu thông tin các file audio đã tạo
            audio_files_info = []

            # Kiểm tra xem script có speech_units không
            if not script.get('speech_units'):
                logger.error(f"Script cho project {project_id} không chứa 'speech_units'. Không thể tạo audio.")
                return [] # Trả về list rỗng

            # --- Lặp qua từng Speech Unit để tạo Audio ---
            total_units = len(script['speech_units'])
            for i, unit in enumerate(script['speech_units']):
                unit_number = unit.get('unit_number')
                unit_text = unit.get('text', '').strip()
                scene_numbers_in_unit = unit.get('scene_numbers', [])

                if unit_number is None:
                    logger.warning(f"Bỏ qua speech unit không có 'unit_number': {unit}")
                    continue
                if not unit_text:
                    logger.warning(f"Speech Unit {unit_number} có nội dung rỗng, bỏ qua.")
                    continue

                logger.info(f"Processing Speech Unit {unit_number}/{total_units}...")

                try:
                    # Tạo tên file audio cho unit
                    unit_audio_filename = f"unit_{unit_number}.mp3"
                    unit_audio_path = os.path.join(project_audio_dir, unit_audio_filename)

                    # Gọi hàm tạo audio (hàm này không đổi)
                    self._generate_audio(unit_text, unit_audio_path)

                    # Lấy thời lượng thực tế của file audio vừa tạo
                    actual_unit_duration = 0.0
                    try:
                        if os.path.exists(unit_audio_path) and os.path.getsize(unit_audio_path) > 100: # Kiểm tra file hợp lệ
                            audio_info_mutagen = mutagen.mp3.MP3(unit_audio_path)
                            actual_unit_duration = audio_info_mutagen.info.length
                            logger.info(f"  Speech Unit {unit_number}: Audio duration = {actual_unit_duration:.3f}s")
                        else:
                            logger.warning(f"  Speech Unit {unit_number}: Audio file '{unit_audio_filename}' không hợp lệ sau khi tạo. Ước tính duration.")
                            actual_unit_duration = self._estimate_duration(unit_text)
                    except mutagen.MutagenError as me:
                        logger.warning(f"  Speech Unit {unit_number}: Lỗi Mutagen khi đọc duration file '{unit_audio_filename}': {me}. Ước tính duration.")
                        actual_unit_duration = self._estimate_duration(unit_text)
                    except Exception as e:
                        logger.warning(f"  Speech Unit {unit_number}: Lỗi không xác định khi đọc duration file '{unit_audio_filename}': {e}. Ước tính duration.")
                        actual_unit_duration = self._estimate_duration(unit_text)

                    # Thêm thông tin audio của unit vào danh sách kết quả
                    audio_files_info.append({
                        "type": "speech_unit", # Đánh dấu loại
                        "unit_number": unit_number,
                        "path": unit_audio_path, # Lưu đường dẫn đầy đủ để dùng ngay
                        "duration": actual_unit_duration, # Thời lượng thực tế (hoặc ước tính)
                        "content": unit_text, # Text gốc của unit
                        "scene_numbers": scene_numbers_in_unit # Danh sách các scene (shots) thuộc unit này
                    })

                except Exception as e:
                    logger.error(f"Lỗi khi tạo audio cho Speech Unit {unit_number}: {str(e)}", exc_info=True)
                    # Có thể thêm xử lý lỗi khác ở đây nếu cần

            # --- Kết thúc vòng lặp qua speech units ---

            # --- Lưu thông tin audio vào file JSON (sử dụng hàm đã sửa đổi) ---
            if audio_files_info:
                self._save_audio_info(audio_files_info, script['title'], project_audio_dir, project_id)
                logger.info(f"Hoàn thành tạo {len(audio_files_info)} file âm thanh (speech units) cho project {project_id}.")
            else:
                logger.error(f"Không tạo được file audio nào cho project {project_id}.")


            # Trả về danh sách thông tin các file audio đã tạo
            return audio_files_info
    
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
    
    def _estimate_duration(self, text):
        """Ước tính thời lượng của đoạn âm thanh dựa trên số từ (DÙNG LÀM FALLBACK)"""
        # Tiếng Anh: trung bình 3 từ/giây khi đọc
        words = text.split()
        return len(words) / 3.0 if len(words) > 0 else 0.0
    
    def _save_audio_info(self, audio_files_info, title, project_audio_dir, project_id):
            """Lưu thông tin âm thanh (speech units) vào file JSON."""
            if not audio_files_info:
                logger.warning(f"Project {project_id}: Không có thông tin audio để lưu.")
                return

            audio_metadata = []
            for audio_unit_info in audio_files_info:
                # Chỉ lưu các thông tin cần thiết cho metadata
                metadata_entry = {
                    "type": audio_unit_info.get("type", "speech_unit"),
                    "unit_number": audio_unit_info.get("unit_number"),
                    # Lưu tên file thay vì đường dẫn đầy đủ trong metadata
                    "filename": os.path.basename(audio_unit_info.get("path", "")),
                    "duration": audio_unit_info.get("duration"),
                    "scene_numbers": audio_unit_info.get("scene_numbers"),
                    # "content": audio_unit_info.get("content") # Có thể bỏ content nếu không cần trong file info
                }
                # Bỏ qua các giá trị None nếu có
                metadata_entry = {k: v for k, v in metadata_entry.items() if v is not None}
                audio_metadata.append(metadata_entry)

            # Tên file metadata
            output_file = os.path.join(project_audio_dir, f"audio_info_{project_id}.json")

            # Dữ liệu tổng hợp để lưu
            output_data = {
                'project_id': project_id,
                'project_title': title,
                'creation_timestamp': time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                'project_audio_folder': os.path.basename(project_audio_dir),
                'total_speech_units_generated': len(audio_metadata),
                'speech_unit_audio_files': audio_metadata # Đổi tên key cho rõ ràng
            }

            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, ensure_ascii=False, indent=2)
                logger.info(f"Project {project_id}: Đã lưu thông tin audio tại: {output_file}")
            except Exception as e:
                logger.error(f"Project {project_id}: Lỗi khi lưu audio_info.json: {e}", exc_info=True)
    
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