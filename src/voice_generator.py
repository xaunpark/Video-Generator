# src/voice_generator.py
import os
import shutil
import subprocess
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

from config.credentials import OPENAI_API_KEY, MINIMAX_API_KEY, MINIMAX_GROUP_ID
from config.settings import TEMP_DIR, TTS_PROVIDERS, DEFAULT_TTS_PROVIDER, VIDEO_SETTINGS

# Tải các biến môi trường
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoiceGenerator:
    def __init__(self, selected_provider=None): # Thêm selected_provider
        """Khởi tạo VoiceGenerator hỗ trợ nhiều provider (OpenAI, MiniMax)."""
        self.temp_dir = TEMP_DIR

        # --- Xác định Provider ---
        self.selected_tts_provider = selected_provider or DEFAULT_TTS_PROVIDER
        if self.selected_tts_provider not in TTS_PROVIDERS:
            logger.warning(
                f"Selected TTS Provider '{self.selected_tts_provider}' not found in settings. "
                f"Falling back to default '{DEFAULT_TTS_PROVIDER}'."
            )
            self.selected_tts_provider = DEFAULT_TTS_PROVIDER

        logger.info(f"Initializing VoiceGenerator with provider: {self.selected_tts_provider}")

        try:
            self.provider_config = TTS_PROVIDERS[self.selected_tts_provider]
        except KeyError:
            logger.critical(f"Configuration for TTS provider '{self.selected_tts_provider}' is missing in settings.py!")
            raise ValueError(f"Missing configuration for TTS provider: {self.selected_tts_provider}")

        # --- Load API Key và Group ID (nếu cần) ---
        self.api_key = None
        self.group_id = None
        api_key_name = self.provider_config.get("api_key_name")
        group_id_name = self.provider_config.get("group_id_name") # Thêm dòng này

        if api_key_name == "OPENAI_API_KEY":
            self.api_key = OPENAI_API_KEY
        elif api_key_name == "MINIMAX_API_KEY":
            self.api_key = MINIMAX_API_KEY
            if group_id_name == "MINIMAX_GROUP_ID": # Thêm kiểm tra group_id
                self.group_id = MINIMAX_GROUP_ID
        # Thêm elif cho các provider khác

        if not self.api_key:
            logger.critical(f"API key ('{api_key_name}') for TTS provider '{self.selected_tts_provider}' is missing or empty.")
            raise ValueError(f"API key for {self.selected_tts_provider} not found.")
        if self.selected_tts_provider == "minimax" and not self.group_id: # Kiểm tra group_id cho minimax
             logger.critical(f"Group ID ('{group_id_name}') for MiniMax TTS provider is missing or empty.")
             raise ValueError(f"Group ID for MiniMax not found.")


        # --- Cấu hình Chung và Mặc định ---
        self.base_url = self.provider_config.get("base_url")
        self.model = self.provider_config.get("default_model")
        self.voice = self.provider_config.get("default_voice")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Lưu cài đặt mặc định cụ thể của provider (nếu có)
        self.audio_settings = self.provider_config.get("default_audio_settings", {})
        self.voice_settings = self.provider_config.get("default_voice_settings", {})

        # Tạo thư mục lưu trữ âm thanh
        self.audio_dir = os.path.join(self.temp_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)

        # Bỏ qua _test_connection() vì phức tạp khi có nhiều provider
        # self._test_connection()
        logger.info(f"VoiceGenerator for '{self.selected_tts_provider}' initialized.")
        logger.info(f"  Default Model: {self.model}")
        logger.info(f"  Default Voice: {self.voice}")
    
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

    # --- HÀM HELPER TẠO SILENCE, KHOẢNG LẶNG KHI CÓ CHAPTER CARDS ---
    def _create_silence_audio(self, duration, output_path, sample_rate=32000):
        """Tạo file MP3 chứa khoảng lặng bằng FFmpeg."""
        logger.info(f"Creating silence audio (Duration: {duration:.2f}s, SR: {sample_rate}) -> {os.path.basename(output_path)}")
        try:
            # Lấy đường dẫn FFmpeg (cần có sẵn hoặc tìm)
            ffmpeg_path = shutil.which("ffmpeg") # Tìm trong PATH
            if not ffmpeg_path:
                # Thử lấy từ biến môi trường nếu không có trong PATH (tùy chọn)
                # ffmpeg_path = os.getenv("FFMPEG_PATH")
                if not ffmpeg_path:
                     logger.error("FFmpeg path not found. Cannot create silence.")
                     return None

            safe_duration = max(0.1, duration)
            # Lệnh tạo silence và encode sang MP3
            cmd = [
                ffmpeg_path, "-y",
                "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate={sample_rate}",
                "-t", str(safe_duration),
                "-c:a", "libmp3lame", "-q:a", "5", # Chất lượng MP3 vừa phải
                output_path
            ]
            process = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding='utf-8')
            if process.returncode != 0:
                logger.error(f"Failed to create silence audio. FFmpeg stderr: {process.stderr.strip()}")
                return None
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return output_path
            else:
                logger.error(f"Silence audio creation seemed successful but file is invalid: {output_path}")
                return None
        except Exception as e:
            logger.error(f"Error creating silence audio: {e}", exc_info=True)
            return None

    def generate_audio_for_script(self, script, visual_timing_mode="sync_to_audio"): # Thêm tham số timing mode
        """Tạo file âm thanh cho từng speech_unit, tùy chọn thêm silence cho chapter cards dựa trên timing mode."""
        project_id = script.get('project_id', f"project_{time.strftime('%Y%m%d%H%M%S')}")
        project_audio_dir = os.path.join(self.audio_dir, project_id)
        os.makedirs(project_audio_dir, exist_ok=True)

        # Log cả timing mode
        logger.info(f"Generating voice for script: '{script['title']}' (Project: {project_id}, Timing Mode: {visual_timing_mode})")
        audio_files_info = [] # List cuối cùng chứa thông tin tất cả file (speech & silence)
        # Không cần generated_audio_paths nữa, audio_files_info đủ

        if not script.get('speech_units'):
            logger.error(f"Script {project_id} missing 'speech_units'. Cannot generate audio.")
            return []

        # Lấy cài đặt từ VIDEO_SETTINGS
        card_duration = VIDEO_SETTINGS.get("chapter_title_duration", 2.5)
        # Chuyển is_advanced_mode vào trong vòng lặp để kiểm tra từng unit nếu cần
        is_advanced_mode_script = script.get("script_mode") == "advanced"

        processed_chapters_for_silence = set() # Theo dõi chapter đã thêm silence

        # Sắp xếp speech units để đảm bảo xử lý đúng thứ tự chapter
        speech_units_sorted = sorted(script.get('speech_units', []), key=lambda x: x.get('unit_number', float('inf')))
        total_units = len(speech_units_sorted)

        for i, unit in enumerate(speech_units_sorted):
            unit_number = unit.get('unit_number')
            unit_text = unit.get('text', '').strip()
            unit_chapter_num = unit.get('chapter_number') # Lấy chapter number
            unit_chapter_title = unit.get('chapter_title') # Lấy chapter title

            if unit_number is None:
                logger.warning(f"Skipping speech unit with missing number: {unit}")
                continue

            # === KIỂM TRA VÀ CHÈN SILENCE CHO CHAPTER MỚI ===
            # Điều kiện: Script là advanced, KHÔNG phải theme mode, có chapter > 1, và chưa xử lý chapter đó
            should_add_silence = (
                is_advanced_mode_script and
                visual_timing_mode != 'overall_theme_fixed_duration' and # << KIỂM TRA TIMING MODE
                unit_chapter_num is not None and
                unit_chapter_num > 1 and
                unit_chapter_num not in processed_chapters_for_silence
            )

            if should_add_silence:
                logger.info(f"Detected start of Chapter {unit_chapter_num} (>1) in non-theme mode. Inserting silence for card...")
                silence_filename = f"chapter_{unit_chapter_num}_silence.mp3"
                silence_output_path = os.path.join(project_audio_dir, silence_filename)
                tts_sample_rate = self.provider_config.get("default_audio_settings", {}).get("sample_rate", 32000)

                created_silence_path = self._create_silence_audio(card_duration, silence_output_path, sample_rate=tts_sample_rate)

                if created_silence_path:
                    # Thêm thông tin silence vào danh sách kết quả chính
                    audio_files_info.append({
                        "type": "silence", # Đổi type cho rõ ràng
                        "path": created_silence_path,
                        "duration": card_duration,
                        "unit_number": None, # Không phải speech unit
                        "scene_numbers": [],
                        "content": f"[Silence for Chapter {unit_chapter_num}]",
                        "chapter_number": unit_chapter_num,
                        "chapter_title": unit_chapter_title # Lưu lại title để tham khảo
                    })
                    processed_chapters_for_silence.add(unit_chapter_num) # Đánh dấu đã xử lý
                    logger.info(f"  Added silence file: {silence_filename}")
                else:
                    logger.error(f"  Failed to create silence for Chapter {unit_chapter_num} card.")
            # Ghi log nếu bỏ qua silence do timing mode hoặc các lý do khác
            elif is_advanced_mode_script and unit_chapter_num is not None and unit_chapter_num > 1 and unit_chapter_num not in processed_chapters_for_silence:
                 log_reason = "timing mode is 'overall_theme_fixed_duration'" if visual_timing_mode == 'overall_theme_fixed_duration' else f"chapter {unit_chapter_num} already processed or other condition unmet"
                 logger.debug(f"Skipping silence for Chapter {unit_chapter_num} because {log_reason}.")
                 # Vẫn đánh dấu đã xử lý để tránh log lặp
                 processed_chapters_for_silence.add(unit_chapter_num)
            # === KẾT THÚC CHÈN SILENCE ===

            # --- Tạo Audio cho Speech Unit (chỉ khi text không rỗng) ---
            if unit_text:
                logger.info(f"Processing Speech Unit {unit_number}/{total_units}...")
                try:
                    unit_audio_filename = f"unit_{unit_number}.mp3"
                    unit_audio_path = os.path.join(project_audio_dir, unit_audio_filename)
                    generated_path, api_duration = self._generate_audio(unit_text, unit_audio_path)

                    if not generated_path:
                        logger.error(f"  Speech Unit {unit_number}: Audio generation failed.")
                        continue # Bỏ qua unit này

                    # --- Lấy Duration (logic như cũ) ---
                    actual_unit_duration = 0.0
                    if api_duration is not None and api_duration > 0:
                        actual_unit_duration = api_duration
                        logger.debug(f"  Using duration from API: {actual_unit_duration:.3f}s")
                    else:
                        logger.debug(f"  Getting duration using mutagen/estimate...")
                        try:
                            if os.path.exists(generated_path) and os.path.getsize(generated_path) > 100:
                                audio_info_mutagen = mutagen.mp3.MP3(generated_path)
                                actual_unit_duration = audio_info_mutagen.info.length
                            else: actual_unit_duration = self._estimate_duration(unit_text)
                        except Exception as e_mut:
                            logger.warning(f"    Mutagen/Estimate failed: {e_mut}. Using fallback estimate.")
                            actual_unit_duration = self._estimate_duration(unit_text)
                        logger.debug(f"    Calculated duration: {actual_unit_duration:.3f}s")
                    # --- Kết thúc lấy Duration ---

                    # --- Thêm thông tin audio unit vào danh sách chính ---
                    audio_files_info.append({
                        "type": "speech_unit",
                        "unit_number": unit_number,
                        "path": generated_path,
                        "duration": actual_unit_duration,
                        "content": unit_text,
                        "scene_numbers": unit.get('scene_numbers', []),
                        "chapter_number": unit_chapter_num, # Giữ lại chapter info
                        "chapter_title": unit_chapter_title
                    })
                except Exception as e:
                    logger.error(f"Error creating audio for Speech Unit {unit_number}: {str(e)}", exc_info=True)
            else:
                 # Chỉ log nếu unit rỗng nhưng không phải là unit đầu tiên của chapter > 1 (vì đã log ở trên)
                 if not (is_advanced_mode_script and unit_chapter_num is not None and unit_chapter_num > 1 and i > 0 and speech_units_sorted[i-1].get('chapter_number') != unit_chapter_num):
                     logger.info(f"Skipping audio generation for empty Speech Unit {unit_number}.")
        # --- Kết thúc vòng lặp ---

        # --- Lưu thông tin audio (bao gồm cả silence nếu có) ---
        if audio_files_info:
            self._save_audio_info(audio_files_info, script['title'], project_audio_dir, project_id)
            total_files_gen = len([f for f in audio_files_info if f.get('path')])
            logger.info(f"Finished generating {total_files_gen} audio files (speech & silence if applicable) for {project_id}.")
        else:
            logger.error(f"No audio files generated for project {project_id}.")

        return audio_files_info # Trả về list cuối cùng
    
    def _generate_audio(self, text, output_path):
        """
        Tạo file âm thanh từ văn bản sử dụng provider đã chọn (OpenAI hoặc MiniMax).

        Returns:
            tuple: (str path_to_audio, float duration_in_seconds | None)
                Trả về (None, None) nếu thất bại.
        """
        logger.debug(f"[{self.selected_tts_provider}] Generating audio for text: '{text[:50]}...' -> {os.path.basename(output_path)}")
        max_chars = 4000 if self.selected_tts_provider == "openai" else 5000 # Giới hạn ký tự khác nhau

        if len(text) > max_chars:
            logger.warning(f"[{self.selected_tts_provider}] Văn bản quá dài ({len(text)} chars). Cắt xuống {max_chars} chars.")
            text = text[:max_chars]

        # --- Phân nhánh theo Provider ---
        if self.selected_tts_provider == "openai":
            try:
                payload = {
                    "model": self.model,
                    "input": text,
                    "voice": self.voice,
                    "response_format": "mp3"
                }
                response = requests.post(self.base_url, json=payload, headers=self.headers, timeout=60) # Timeout hợp lý
                response.raise_for_status() # Kiểm tra lỗi HTTP

                with open(output_path, 'wb') as f:
                    f.write(response.content)
                logger.info(f"[openai] Đã tạo file âm thanh: {os.path.basename(output_path)}")
                # OpenAI không trả về duration, sẽ lấy bằng mutagen sau
                return output_path, None
            except requests.exceptions.RequestException as e:
                logger.error(f"[openai] Lỗi API request: {e}")
                return None, None
            except Exception as e:
                logger.error(f"[openai] Lỗi không xác định khi tạo audio: {e}", exc_info=True)
                return None, None

        elif self.selected_tts_provider == "minimax":
            try:
                # --- Xây dựng URL và Payload cho MiniMax ---
                if not self.group_id: # Kiểm tra lại group_id
                    raise ValueError("MiniMax Group ID is required but missing.")
                url = f"{self.base_url}?GroupId={self.group_id}"

                # Lấy cài đặt voice từ self.voice_settings và cập nhật voice_id
                current_voice_settings = self.provider_config.get('default_voice_settings', {}).copy()
                current_voice_settings['voice_id'] = self.voice # Gán voice_id hiện tại

                payload = {
                    "model": self.model,
                    "text": text,
                    "stream": False, # Luôn là False cho non-streaming
                    "output_format": "hex", # Luôn yêu cầu hex để lấy data
                    "voice_setting": current_voice_settings,
                    "audio_setting": self.provider_config.get('default_audio_settings', {})
                    # Thêm các tham số khác nếu cần, ví dụ:
                    # "language_boost": "English",
                    # "subtitle_enable": False,
                }
                logger.debug(f"[minimax] Payload: {json.dumps(payload, indent=2)}") # Log payload để debug

                # --- Gọi API MiniMax ---
                response = requests.post(url, headers=self.headers, json=payload, timeout=90) # Timeout dài hơn chút
                response.raise_for_status() # Kiểm tra lỗi HTTP

                # --- Xử lý Response MiniMax ---
                data = response.json()
                base_resp = data.get('base_resp', {})
                status_code = base_resp.get('status_code', -1)
                status_msg = base_resp.get('status_msg', 'Unknown Error')

                if status_code != 0:
                    logger.error(f"[minimax] Lỗi API ({status_code}): {status_msg}")
                    logger.error(f"  Trace ID: {data.get('trace_id')}")
                    return None, None # Báo lỗi

                # Lấy audio hex và decode
                hex_audio = data.get('data', {}).get('audio')
                if not hex_audio:
                    logger.error("[minimax] API trả về thành công nhưng không có dữ liệu audio ('data.audio').")
                    return None, None

                try:
                    audio_bytes = bytes.fromhex(hex_audio)
                except ValueError as hex_err:
                    logger.error(f"[minimax] Lỗi giải mã chuỗi hex audio: {hex_err}")
                    return None, None

                # Ghi file audio
                with open(output_path, 'wb') as f:
                    f.write(audio_bytes)
                logger.info(f"[minimax] Đã tạo file âm thanh: {os.path.basename(output_path)}")

                # Lấy duration từ extra_info
                duration_sec = None
                extra_info = data.get('extra_info', {})
                duration_ms = extra_info.get('audio_length')
                if isinstance(duration_ms, (int, float)) and duration_ms > 0:
                    duration_sec = duration_ms / 1000.0
                    logger.info(f"[minimax] Duration từ API: {duration_sec:.3f}s")
                else:
                    logger.warning(f"[minimax] Không tìm thấy hoặc duration không hợp lệ trong extra_info: {extra_info}. Sẽ dùng mutagen.")

                return output_path, duration_sec

            except requests.exceptions.RequestException as e:
                logger.error(f"[minimax] Lỗi API request: {e}")
                return None, None
            except json.JSONDecodeError as e:
                logger.error(f"[minimax] Lỗi giải mã JSON response: {e}")
                logger.debug(f"Raw response text: {response.text[:500]}") # Log phần đầu response nếu lỗi JSON
                return None, None
            except Exception as e:
                logger.error(f"[minimax] Lỗi không xác định khi tạo audio: {e}", exc_info=True)
                return None, None

        else:
            logger.error(f"TTS Provider '{self.selected_tts_provider}' không được hỗ trợ.")
            return None, None
    
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
        """Thiết lập giọng đọc, kiểm tra tính hợp lệ theo provider đã chọn."""
        valid_voices = self.provider_config.get("valid_voices", [])
        if voice in valid_voices:
            self.voice = voice
            logger.info(f"[{self.selected_tts_provider}] Đã thiết lập giọng đọc: {voice}")
        else:
            logger.warning(
                f"[{self.selected_tts_provider}] Giọng không hợp lệ: {voice}. "
                f"Các giọng hợp lệ: {valid_voices}. Sử dụng giọng mặc định: {self.voice}"
            )
    
    def set_model(self, model):
        """Thiết lập model TTS, kiểm tra tính hợp lệ theo provider đã chọn."""
        valid_models = self.provider_config.get("valid_models", [])
        if model in valid_models:
            self.model = model
            logger.info(f"[{self.selected_tts_provider}] Đã thiết lập model: {model}")
        else:
            logger.warning(
                f"[{self.selected_tts_provider}] Model không hợp lệ: {model}. "
                f"Các model hợp lệ: {valid_models}. Sử dụng model mặc định: {self.model}"
            )

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