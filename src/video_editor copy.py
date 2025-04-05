#!/usr/bin/env python
# -*- coding: utf-8 -*-
#delete later
"""
video_generator.py - Module để tạo video từ ảnh, video clips và audio
"""

import os
import shutil
import random
import time
import json
import math
import subprocess
import tempfile
import mutagen
from datetime import timedelta
import whisper

from src.logger_config import setup_logger
logger = setup_logger(__name__)

# from moviepy.editor import (
#     VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, 
#     concatenate_videoclips, TextClip, ColorClip 
# )
# import moviepy.video.fx.all as vfx
# from moviepy.audio.AudioClip import (CompositeAudioClip, concatenate_audioclips)

# Import MoviePy từ các phiên bản 2.x trở lên
from moviepy import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips, TextClip, ColorClip
import moviepy.video.fx as vfx
from moviepy.audio.AudioClip import CompositeAudioClip, concatenate_audioclips

from src.fix_pillow import *

# Import cấu hình từ project
from config.settings import (
    TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS, FFPROBE_EXECUTABLE_PATH, OUTPUT_DIR
)

# Import unidecode để chuẩn hóa text tốt hơn
try:
    from unidecode import unidecode
    logger.info("Imported unidecode for text normalization.")
except ImportError:
    unidecode = None
    logger.warning("unidecode not found. Text normalization for alignment might be less robust. Install with: pip install unidecode")

class VideoEditor:
    """
    Class để tạo video tin tức từ ảnh, video clips và audio.
    Hỗ trợ hiệu ứng cho ảnh, transitions giữa các cảnh, và nhạc nền.
    """
    
    def __init__(self):
        """Khởi tạo VideoEditor với cấu hình cần thiết."""
        self.temp_dir = TEMP_DIR
        self.assets_dir = ASSETS_DIR
        
        # Lấy cài đặt video từ config
        self.width = VIDEO_SETTINGS.get("width", 1920)
        self.height = VIDEO_SETTINGS.get("height", 1080)
        self.fps = VIDEO_SETTINGS.get("fps", 24)

        # === THÊM DÒNG NÀY ĐỂ TÌM FFMPEG ===
        self.ffmpeg_path = shutil.which("ffmpeg") # Tìm đường dẫn ffmpeg trong PATH
        if not self.ffmpeg_path:
            logger.error("Không tìm thấy FFmpeg trong PATH hệ thống!")
            raise FileNotFoundError("FFmpeg không được tìm thấy. Hãy cài đặt và thêm vào PATH.")
        else:
            logger.info(f"Đã tìm thấy FFmpeg tại: {self.ffmpeg_path}")
        # ===================================
        
        # === TÌM FFPROBE ===
        self.ffprobe_path = shutil.which(FFPROBE_EXECUTABLE_PATH) \
                            if FFPROBE_EXECUTABLE_PATH == "ffprobe" else FFPROBE_EXECUTABLE_PATH
        if not os.path.exists(self.ffprobe_path):
            logger.error(f"ffprobe không tìm thấy tại: {self.ffprobe_path}")
            # Có thể không cần raise lỗi nghiêm trọng nếu không bắt buộc, nhưng nên cảnh báo
            logger.warning("ffprobe không tìm thấy, không thể lấy duration chính xác trước khi xử lý video.")
            self.ffprobe_path = None # Đặt là None nếu không tìm thấy
        else:
            logger.info(f"Sử dụng ffprobe tại: {self.ffprobe_path}")

        # Tạo thư mục tạm để lưu các video scene
        self.temp_video_dir = os.path.join(self.temp_dir, "scene_videos")
        os.makedirs(self.temp_video_dir, exist_ok=True)
        
        # Cài đặt hiệu ứng cho video
        self.enable_transitions = VIDEO_SETTINGS.get("enable_transitions", True)
        self.transition_types = VIDEO_SETTINGS.get("transition_types", ["fade"])
        self.transition_duration = VIDEO_SETTINGS.get("transition_duration", 0.5)
        
        # Cài đặt hiệu ứng cho ảnh tĩnh
        self.image_animation = VIDEO_SETTINGS.get("image_animation", "zoom")
        self.animation_intensity = VIDEO_SETTINGS.get("animation_intensity", 0.02)
        self.animation_cycle_seconds = VIDEO_SETTINGS.get("animation_cycle_seconds", 5)
        
        # Cài đặt nhạc nền
        self.enable_background_music = VIDEO_SETTINGS.get("enable_background_music", False)
        self.music_volume = VIDEO_SETTINGS.get("music_volume", 0.1)
        
        logger.info(f"VideoEditor đã khởi tạo. Kích thước video: {self.width}x{self.height}, FPS: {self.fps}")
        logger.info(f"Hiệu ứng ảnh: {self.image_animation}, Cường độ: {self.animation_intensity}")

    # Đặt tên file đơn giản
    def sanitize_filename(self, filename):
        """
        Tạo tên file an toàn không chứa ký tự đặc biệt.
        
        Args:
            filename (str): Tên file gốc
            
        Returns:
            str: Tên file đã được xử lý
        """
        # Loại bỏ các ký tự không hợp lệ
        invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|', "'"]
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Xử lý dấu và ký tự đặc biệt
        import unicodedata
        # Chuyển về dạng không dấu
        filename = unicodedata.normalize('NFKD', filename)
        filename = ''.join([c for c in filename if not unicodedata.combining(c)])
        
        # Loại bỏ khoảng trắng đầu/cuối
        filename = filename.strip()
        
        # Thay thế nhiều khoảng trắng liên tiếp bằng một dấu gạch dưới
        import re
        filename = re.sub(r'\s+', '_', filename)
        
        # Giới hạn độ dài tên file
        if len(filename) > 100:
            filename = filename[:97] + "..."
        
        return filename

    # --- THÊM HÀM HELPER ĐỂ LẤY VIDEO DURATION BẰNG FFPROBE ---
    def _get_video_duration_ffprobe(self, video_path):
        """Lấy thời lượng video bằng ffprobe."""
        if not self.ffprobe_path:
            logger.warning("ffprobe không khả dụng, không thể lấy duration.")
            return None
        try:
            cmd = [
                self.ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
            return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"Lỗi khi lấy duration bằng ffprobe cho {os.path.basename(video_path)}: {e}")
            return None
    # --- KẾT THÚC HÀM HELPER ---

    # --- HÀM MỚI: LẤY WORD TIMESTAMPS ---
    def get_word_timestamps(self, audio_path, model_name="base", language=None):
        """
        Sử dụng Whisper để transcribe và trích xuất word-level timestamps.

        Args:
            audio_path (str): Đường dẫn đến file audio.
            model_name (str): Tên model Whisper (tiny, base, small, medium, large).
            language (str): Ngôn ngữ (ví dụ: 'vi', 'en'). None để tự động phát hiện.

        Returns:
            list: Danh sách các dictionary {'word', 'start', 'end'} hoặc None nếu lỗi.
        """
        if not os.path.exists(audio_path):
             logger.error(f"Audio file not found for alignment: {audio_path}")
             return None

        # Cân nhắc: Load model một lần trong __init__ để tiết kiệm thời gian nếu gọi nhiều lần
        # Tuy nhiên, load mỗi lần đơn giản hơn và tránh vấn đề bộ nhớ nếu xử lý nhiều video lớn
        logger.info(f"Loading Whisper model '{model_name}' for alignment...")
        try:
            # Kiểm tra xem model có tồn tại không trước khi load (tùy chọn)
            # whisper.available_models()
            model = whisper.load_model(model_name)
            logger.info(f"Whisper model '{model_name}' loaded.")
        except Exception as e:
            logger.error(f"Error loading Whisper model '{model_name}': {e}", exc_info=True)
            logger.error(f"Available models: {whisper.available_models()}")
            return None

        logger.info(f"Transcribing and aligning audio: {os.path.basename(audio_path)}...")
        start_time_align = time.time()
        try:
            # Sử dụng tùy chọn word_timestamps=True
            # verbose=False để tránh log quá nhiều từ whisper
            # fp16=False nếu chạy trên CPU (Whisper tự cảnh báo và chuyển đổi)
            result = model.transcribe(
                audio_path,
                language=language,
                word_timestamps=True,
                verbose=False,
                fp16=False # An toàn hơn cho CPU
            )
            end_time_align = time.time()
            logger.info(f"Alignment completed in {end_time_align - start_time_align:.2f} seconds.")

            # Trích xuất word timestamps
            word_timestamps = []
            if 'segments' in result:
                for segment in result['segments']:
                    if 'words' in segment:
                        for word_info in segment['words']:
                            # API có thể trả về key 'word' hoặc 'text' tùy phiên bản/cấu hình
                            word_text = word_info.get('word', word_info.get('text', '')).strip()
                            if word_text: # Chỉ xử lý nếu có từ
                                word_timestamps.append({
                                    "word": word_text,
                                    # Đảm bảo start/end là float
                                    "start": float(word_info['start']),
                                    "end": float(word_info['end'])
                                })
                    # else: logger.debug("Segment found without 'words' key.") # Log debug nếu cần
            # else: logger.warning("Transcription result does not contain 'segments' key.")

            if not word_timestamps:
                 logger.error("Error: No word timestamps were extracted from the audio.")
                 return None

            logger.info(f"Extracted {len(word_timestamps)} word timestamps.")
            return word_timestamps

        except FileNotFoundError:
            logger.error(f"Error: Audio file not found during alignment: {audio_path}")
            logger.error("Ensure ffmpeg is installed and accessible in your system's PATH.")
            return None
        except Exception as e:
            logger.error(f"Error during Whisper transcription/alignment: {e}", exc_info=True)
            return None

    # --- HÀM MỚI: Chuẩn hóa Text để so khớp ---
    def _normalize_text_for_matching(self, text):
        """Chuẩn hóa text để so khớp tốt hơn giữa script và kết quả whisper."""
        text = text.lower().strip('.,!?;:')
        # Sử dụng unidecode để loại bỏ dấu nếu đã import thành công
        if unidecode:
            try:
                text = unidecode(text)
            except Exception as e:
                logger.warning(f"unidecode error processing text '{text}': {e}")
        # Thêm các bước chuẩn hóa khác nếu cần (ví dụ: thay thế số thành chữ?)
        return text

    # --- HÀM MỚI: Tính Duration Chính xác ---
    def _calculate_precise_shot_durations(self, visual_items, word_timestamps):
        """
        Tính thời lượng chính xác cho mỗi visual item (shot) dựa trên word timestamps.

        Args:
            visual_items (list): List các dict media item (chứa 'content', 'number').
            word_timestamps (list): List word timestamps từ Whisper cho cả speech unit.

        Returns:
            list: List các dict visual_item được thêm key 'calculated_duration',
                  hoặc None nếu không thể tính toán.
        """
        if not word_timestamps:
            logger.error("Cannot calculate precise durations without word timestamps.")
            return None

        timed_items = []
        timestamp_idx = 0 # Index hiện tại trong danh sách word_timestamps
        total_duration_calculated = 0
        words_in_timestamps = [self._normalize_text_for_matching(wt['word']) for wt in word_timestamps]

        logger.debug(f"Starting precise duration calculation for {len(visual_items)} items.")

        for item_index, item in enumerate(visual_items):
            shot_text = item.get('content', '').strip()
            scene_num = item.get('number', f'item_{item_index+1}')
            # Chuẩn hóa và tách từ của shot hiện tại
            shot_words = [self._normalize_text_for_matching(w) for w in shot_text.split() if self._normalize_text_for_matching(w)]

            logger.debug(f"Processing Scene {scene_num}, Text: '{shot_text}', Normalized words: {shot_words}")

            if not shot_words:
                 logger.debug(f"Scene {scene_num}: Shot has no processable words. Assigning minimal duration.")
                 timed_items.append({**item, 'calculated_duration': 0.1, 'start_time': -1, 'end_time': -1})
                 continue

            start_time = -1.0
            end_time = -1.0
            words_matched_count = 0
            first_match_idx = -1
            last_match_idx = -1

            # --- Logic khớp từ được cải thiện ---
            current_shot_word_idx = 0
            search_start_ts_idx = timestamp_idx # Bắt đầu tìm từ vị trí của shot trước đó

            while current_shot_word_idx < len(shot_words) and search_start_ts_idx < len(words_in_timestamps):
                word_to_find = shot_words[current_shot_word_idx]
                found_match = False
                # Tìm từ word_to_find trong phần còn lại của timestamps
                for k in range(search_start_ts_idx, len(words_in_timestamps)):
                    if words_in_timestamps[k] == word_to_find:
                        # Tìm thấy khớp
                        if words_matched_count == 0: # Từ đầu tiên của shot
                            start_time = word_timestamps[k]['start']
                            first_match_idx = k
                        # Luôn cập nhật end_time và index cuối cùng
                        end_time = word_timestamps[k]['end']
                        last_match_idx = k
                        # Cập nhật vị trí bắt đầu tìm cho từ *tiếp theo* trong timestamps
                        search_start_ts_idx = k + 1
                        words_matched_count += 1
                        found_match = True
                        # logger.debug(f"  Matched '{word_to_find}' at ts_idx {k} ({start_time:.3f}-{end_time:.3f})")
                        break # Tìm thấy từ này, chuyển sang từ tiếp theo trong shot

                if not found_match:
                    logger.warning(f"Scene {scene_num}: Could not find timestamp match for word '{word_to_find}' starting from ts_idx {search_start_ts_idx}.")
                    # Nếu không tìm thấy 1 từ, có thể bỏ qua hoặc dừng tìm cho shot này
                    # Hiện tại: Bỏ qua từ này và tiếp tục tìm từ tiếp theo trong shot
                    pass

                current_shot_word_idx += 1 # Chuyển sang từ tiếp theo trong shot
            # --- Kết thúc logic khớp từ ---

            calculated_duration = 0.0
            if words_matched_count > 0 and start_time >= 0 and end_time >= start_time:
                # Tính duration dựa trên từ đầu tiên và cuối cùng khớp được
                calculated_duration = end_time - start_time
                # Đảm bảo duration không âm và có giá trị tối thiểu nhỏ
                calculated_duration = max(0.05, calculated_duration) # Thời lượng tối thiểu 50ms

                # Cập nhật timestamp_idx chính thức cho shot tiếp theo
                # Dùng vị trí *sau* từ cuối cùng khớp được
                timestamp_idx = last_match_idx + 1
                total_duration_calculated += calculated_duration
                logger.debug(f"Scene {scene_num} duration calculated: {calculated_duration:.3f}s (from ts_idx {first_match_idx} to {last_match_idx})")

            elif not shot_words: # Trường hợp shot rỗng đã xử lý ở trên
                 calculated_duration = 0.1
                 logger.debug(f"Scene {scene_num} has no words, duration: {calculated_duration:.3f}s")
            else: # Trường hợp không khớp được từ nào
                logger.warning(f"Scene {scene_num}: Failed to calculate valid duration for shot '{shot_text}' (matched {words_matched_count}/{len(shot_words)} words). Assigning default 0.2s.")
                calculated_duration = 0.2 # Gán duration mặc định nhỏ nếu lỗi
                # Không cập nhật timestamp_idx nếu shot này lỗi hoàn toàn

            timed_items.append({
                **item,
                'calculated_duration': calculated_duration,
                'start_time': start_time, # Lưu lại để debug nếu cần
                'end_time': end_time      # Lưu lại để debug nếu cần
                })

        logger.info(f"Precise duration calculation finished. Total calculated duration: {total_duration_calculated:.3f}s")
        return timed_items

    def create_video(self, script, media_items, audio_files_info, output_path, background_music_path=None):
            """
            Tạo video hoàn chỉnh từ script (với speech_units), media (cho scenes/shots)
            và audio (cho speech_units), sử dụng word-level alignment.

            Args:
                script (dict): Script với 'scenes' (shots) và 'speech_units'.
                media_items (list): Danh sách media items (ảnh/video) cho từng 'scene' (shot).
                                    Trường 'duration' trong đây chỉ là placeholder/gốc.
                audio_files_info (list): Danh sách thông tin audio cho từng 'speech_unit'.
                                        Phải chứa 'unit_number', 'path', 'duration', 'scene_numbers'.
                output_path (str): Đường dẫn file video cuối cùng.
                background_music_path (str, optional): Đường dẫn nhạc nền.

            Returns:
                str: Đường dẫn đến video đã tạo hoặc None nếu lỗi.
            """
            project_id = script.get('project_id', f"temp_{time.strftime('%Y%m%d%H%M%S')}")
            logger.info(f"=== Starting Video Creation for Project: {project_id} ===")
            logger.info(f"Output Path: {output_path}")

            # --- 0. Chuẩn bị và Kiểm tra đầu vào ---
            if not script or not script.get('scenes') or not script.get('speech_units'):
                logger.error("Invalid script structure: Missing scenes or speech_units.")
                return None
            if not media_items:
                logger.error("Missing media items.")
                return None
            if not audio_files_info:
                logger.error("Missing audio files information.")
                return None

            language = script.get('language', 'en') # Lấy ngôn ngữ từ script

            # Tạo thư mục tạm cho project này
            temp_project_dir = os.path.join(self.temp_video_dir, project_id)
            os.makedirs(temp_project_dir, exist_ok=True)
            logger.info(f"Using temporary directory: {temp_project_dir}")

            # Tạo mapping để truy cập nhanh media và audio
            # Media map: key là scene number (shot number)
            media_map = {item.get('number'): item for item in media_items if item.get('media_type') == 'scene'}
            # Audio map: key là unit number
            audio_map = {info.get('unit_number'): info for info in audio_files_info if info.get('type') == 'speech_unit'}
            # Lấy thông tin audio intro/outro (nếu có)
            intro_audio_info = next((a for a in audio_files_info if a.get('type') == 'intro'), None)
            outro_audio_info = next((a for a in audio_files_info if a.get('type') == 'outro'), None)
            # Lấy media intro/outro
            intro_media_item = next((m for m in media_items if m.get('media_type') == 'intro'), None)
            outro_media_item = next((m for m in media_items if m.get('media_type') == 'outro'), None)

            # --- Danh sách các VideoClip hoàn chỉnh (từ intro, units, outro) ---
            final_clips_sequence = []
            all_clips_to_close = [] # Quản lý tất cả clip cần đóng

            # --- 1. Xử lý Intro (nếu có) ---
            if intro_media_item and intro_audio_info:
                logger.info("Processing Intro...")
                intro_clip = None
                try:
                    # Intro thường là ảnh tĩnh, tạo video từ ảnh với duration của audio intro
                    if intro_media_item['type'] == 'image' and os.path.exists(intro_media_item['path']) and os.path.exists(intro_audio_info['path']):
                        intro_duration = intro_audio_info['duration']
                        intro_audio_clip = AudioFileClip(intro_audio_info['path'])
                        all_clips_to_close.append(intro_audio_clip)

                        # Tạo video từ ảnh intro
                        intro_image_clip = ImageClip(intro_media_item['path'], duration=intro_duration)
                        intro_image_clip = intro_image_clip.with_fps(self.fps).resize(width=self.width) # Đảm bảo FPS và size
                        # Cần crop nếu tỉ lệ không đúng (thường title card đã đúng size)
                        if abs(intro_image_clip.aspect_ratio - (self.width/self.height)) > 0.01:
                            intro_image_clip = intro_image_clip.crop(width=self.width, height=self.height, x_center=intro_image_clip.w/2, y_center=intro_image_clip.h/2)

                        intro_clip = intro_image_clip.set_audio(intro_audio_clip)
                        intro_clip = intro_clip.set_duration(intro_duration) # Đảm bảo duration cuối
                        all_clips_to_close.append(intro_image_clip) # Thêm clip ảnh vào ds đóng
                        final_clips_sequence.append(intro_clip)
                        logger.info(f"Intro clip created (Duration: {intro_duration:.2f}s)")
                    else:
                        logger.warning("Intro media or audio missing or invalid type.")
                except Exception as e:
                    logger.error(f"Error processing intro: {e}", exc_info=True)
                    if intro_clip and hasattr(intro_clip, 'close'): intro_clip.close() # Đóng nếu lỗi


            # --- 2. Xử lý từng Speech Unit ---
            logger.info(f"Processing {len(script['speech_units'])} speech units...")
            for speech_unit in sorted(script['speech_units'], key=lambda x: x['unit_number']):
                unit_number = speech_unit['unit_number']
                scene_numbers_in_unit = speech_unit['scene_numbers']
                logger.info(f"--- Processing Speech Unit {unit_number} (Scenes/Shots: {scene_numbers_in_unit}) ---")

                # Lấy thông tin audio cho unit này
                audio_info = audio_map.get(unit_number)
                if not audio_info or not os.path.exists(audio_info['path']):
                    logger.warning(f"Audio not found for Speech Unit {unit_number}. Skipping this unit.")
                    continue

                # Lấy danh sách media items (visuals) cho các scenes (shots) trong unit này
                visual_items_for_unit = []
                for scene_num in scene_numbers_in_unit:
                    media_item = media_map.get(scene_num)
                    # Kiểm tra xem media có tồn tại và hợp lệ không
                    if media_item and media_item.get('path') and os.path.exists(media_item['path']):
                        visual_items_for_unit.append(media_item)
                    else:
                        logger.warning(f"Media not found or invalid for Scene/Shot {scene_num} in Unit {unit_number}. It will be skipped.")
                        # Cân nhắc thêm fallback (clip đen) nếu muốn giữ số lượng visual
                        # black_item = {"type": "color", "number": scene_num, "duration": 0.1} # Duration sẽ được tính lại
                        # visual_items_for_unit.append(black_item)

                if not visual_items_for_unit:
                    logger.warning(f"No valid media found for Speech Unit {unit_number}. Skipping this unit.")
                    continue

                # Gọi hàm tạo sequence video cho unit (hàm này đã được chuẩn bị ở bước trước)
                unit_clip = None # Khởi tạo để đóng nếu lỗi
                try:
                    unit_clip = self._create_speech_unit_video_sequence(
                        speech_unit=speech_unit,
                        audio_info=audio_info,
                        visual_items=visual_items_for_unit,
                        temp_dir=temp_project_dir, # Thư mục tạm cho unit này
                        language=language
                    )

                    if unit_clip:
                        final_clips_sequence.append(unit_clip)
                        # Quan trọng: Không đóng unit_clip ở đây vì nó sẽ được dùng để nối
                        # all_clips_to_close.append(unit_clip) # Không thêm clip cuối của unit vào đây
                        logger.info(f"Successfully created video sequence for Speech Unit {unit_number} (Duration: {unit_clip.duration:.3f}s)")
                    else:
                        logger.error(f"Failed to create video sequence for Speech Unit {unit_number}.")

                except Exception as e:
                    logger.error(f"Critical error processing Speech Unit {unit_number}: {e}", exc_info=True)
                    if unit_clip and hasattr(unit_clip, 'close'): unit_clip.close() # Đóng nếu lỗi

            # --- 3. Xử lý Outro (tương tự Intro) ---
            if outro_media_item and outro_audio_info:
                logger.info("Processing Outro...")
                outro_clip = None
                try:
                    if outro_media_item['type'] == 'image' and os.path.exists(outro_media_item['path']) and os.path.exists(outro_audio_info['path']):
                        outro_duration = outro_audio_info['duration']
                        outro_audio_clip = AudioFileClip(outro_audio_info['path'])
                        all_clips_to_close.append(outro_audio_clip)

                        outro_image_clip = ImageClip(outro_media_item['path'], duration=outro_duration)
                        outro_image_clip = outro_image_clip.with_fps(self.fps).resize(width=self.width)
                        if abs(outro_image_clip.aspect_ratio - (self.width/self.height)) > 0.01:
                            outro_image_clip = outro_image_clip.crop(width=self.width, height=self.height, x_center=outro_image_clip.w/2, y_center=outro_image_clip.h/2)

                        outro_clip = outro_image_clip.set_audio(outro_audio_clip)
                        outro_clip = outro_clip.set_duration(outro_duration)
                        all_clips_to_close.append(outro_image_clip)
                        final_clips_sequence.append(outro_clip)
                        logger.info(f"Outro clip created (Duration: {outro_duration:.2f}s)")
                    else:
                        logger.warning("Outro media or audio missing or invalid type.")
                except Exception as e:
                    logger.error(f"Error processing outro: {e}", exc_info=True)
                    if outro_clip and hasattr(outro_clip, 'close'): outro_clip.close()

            # --- 4. Nối tất cả các Clips (Intro, Units, Outro) ---
            if not final_clips_sequence:
                logger.error("No video clips were generated to concatenate. Cannot create final video.")
                # Dọn dẹp thư mục tạm
                if VIDEO_SETTINGS.get("cleanup_temp_files", False): shutil.rmtree(temp_project_dir, ignore_errors=True)
                # Đóng các clip đã mở (nếu có)
                for clip in all_clips_to_close:
                    if clip and hasattr(clip, 'close'): clip.close()
                return None

            logger.info(f"Concatenating {len(final_clips_sequence)} final video clips...")
            final_video_no_music = None
            intermediate_output_path = os.path.join(temp_project_dir, f"intermediate_{project_id}.mp4")
            
            # ----- BẮT ĐẦU KHỐI TRY CHO CONCATENATE VÀ WRITE -----
            try:
                # Tạo clip tổng hợp
                # final_video_no_music = concatenate_videoclips(final_clips_sequence, method="compose")
                final_video_no_music = concatenate_videoclips(final_clips_sequence) # Mặc định là method="chain"
                # QUAN TRỌNG: KHÔNG đóng final_clips_sequence ở đây nữa.
                # Thêm clip tổng hợp vào danh sách sẽ được đóng ở cuối hàm create_video
                all_clips_to_close.append(final_video_no_music)

                logger.info(f"Writing intermediate video (without background music) to: {intermediate_output_path}")
                # Ghi file trung gian
                final_video_no_music.write_videofile(
                    intermediate_output_path,
                    codec='libx264',
                    audio_codec='aac',
                    temp_audiofile=os.path.join(temp_project_dir,'temp-concat-audio.m4a'),
                    remove_temp=True,
                    fps=self.fps,
                    preset=VIDEO_SETTINGS.get("ffmpeg_preset", "medium"),
                    threads=os.cpu_count() or 4,
                    logger='bar',
                    ffmpeg_params=["-crf", str(VIDEO_SETTINGS.get("ffmpeg_crf", "23")), "-pix_fmt", "yuv420p"]
                )
                logger.info(f"Intermediate video written successfully.")

            except Exception as e:
                logger.error(f"Error during final concatenation or writing intermediate video: {e}", exc_info=True)
                # Dọn dẹp và thoát
                # Khối finally ở cuối hàm create_video sẽ xử lý việc đóng all_clips_to_close
                if VIDEO_SETTINGS.get("cleanup_temp_files", False): shutil.rmtree(temp_project_dir, ignore_errors=True)
                return None
            # ----- KẾT THÚC KHỐI TRY -----

            # --- 5. Thêm nhạc nền (Logic giữ nguyên, áp dụng cho intermediate_output_path) ---
            final_output_with_fx = intermediate_output_path # Đường dẫn mặc định là file trung gian

            if background_music_path and os.path.exists(background_music_path) and VIDEO_SETTINGS.get("enable_background_music", False):
                logger.info(f"Adding background music from: {os.path.basename(background_music_path)}")
                video_clip_for_music = None
                music_clip_original = None
                adjusted_music = None
                final_audio_composite = None
                video_clip_with_music = None
                music_clips_list_to_close = [] # List riêng cho nhạc lặp
                try:
                    # Đường dẫn file output cuối cùng (sẽ ghi đè output_path ban đầu)
                    output_path_with_music = output_path

                    # Mở lại file trung gian để thêm nhạc
                    video_clip_for_music = VideoFileClip(intermediate_output_path)
                    all_clips_to_close.append(video_clip_for_music)
                    video_duration = video_clip_for_music.duration

                    music_clip_original = AudioFileClip(background_music_path)
                    all_clips_to_close.append(music_clip_original)
                    music_duration = music_clip_original.duration
                    music_volumed = music_clip_original.volumex(self.music_volume)
                    all_clips_to_close.append(music_volumed) # Kết quả volumex cũng cần đóng

                    # Lặp hoặc cắt nhạc nền
                    if music_duration < video_duration:
                        num_loops = math.ceil(video_duration / music_duration)
                        logger.info(f"Looping background music {num_loops} times.")
                        # Tạo list copy để nối, đảm bảo đóng sau
                        music_clips_list = [music_volumed.copy() for _ in range(num_loops)]
                        music_clips_list_to_close.extend(music_clips_list) # Thêm vào list cần đóng
                        adjusted_music = concatenate_audioclips(music_clips_list).subclip(0, video_duration)
                    else:
                        adjusted_music = music_volumed.subclip(0, video_duration)
                    all_clips_to_close.append(adjusted_music) # Kết quả nối/cắt cũng cần đóng

                    original_audio = video_clip_for_music.audio
                    if original_audio: all_clips_to_close.append(original_audio)

                    if original_audio is None:
                        final_audio_composite = adjusted_music
                    else:
                        final_audio_composite = CompositeAudioClip([original_audio, adjusted_music])
                        all_clips_to_close.append(final_audio_composite)

                    video_clip_with_music = video_clip_for_music.set_audio(final_audio_composite)
                    # Không thêm video_clip_with_music vào all_clips_to_close vì sẽ đóng sau khi ghi

                    logger.info(f"Writing final video with background music to: {output_path_with_music}")
                    video_clip_with_music.write_videofile(
                        output_path_with_music,
                        codec='libx264', audio_codec='aac',
                        temp_audiofile=os.path.join(temp_project_dir,'temp-music-audio.m4a'), remove_temp=True,
                        fps=self.fps, preset=VIDEO_SETTINGS.get("ffmpeg_preset", "medium"), threads=os.cpu_count() or 4, logger='bar',
                        ffmpeg_params=["-crf", str(VIDEO_SETTINGS.get("ffmpeg_crf", "23")), "-pix_fmt", "yuv420p"]
                    )

                    if os.path.exists(output_path_with_music):
                        logger.info(f"Successfully created video with background music: {output_path_with_music}")
                        final_output_with_fx = output_path_with_music # Cập nhật đường dẫn trả về
                        # Xóa file trung gian không có nhạc
                        # Việc đóng clip video_clip_for_music trước khi xóa là quan trọng
                        if video_clip_for_music: video_clip_for_music.close()
                        try:
                            if intermediate_output_path != output_path_with_music: # Chỉ xóa nếu khác tên
                                os.remove(intermediate_output_path)
                                logger.info(f"Removed intermediate video file: {intermediate_output_path}")
                        except OSError as rm_err:
                            logger.warning(f"Could not remove intermediate video file {intermediate_output_path}: {rm_err}")
                    else:
                        logger.error("Failed to write video with background music. Returning video without music.")

                except Exception as e:
                    logger.error(f"Error adding background music: {str(e)}", exc_info=True)
                    logger.warning("Proceeding with video without background music.")
                finally:
                    # Đóng clip nhạc lặp
                    for clip in music_clips_list_to_close:
                        if clip and hasattr(clip, 'close'): clip.close()
                    # Đóng clip cuối cùng có nhạc
                    if video_clip_with_music and hasattr(video_clip_with_music, 'close'):
                        video_clip_with_music.close()


            else:
                # Log các trường hợp không thêm nhạc nền
                logger.info("Background music disabled or not provided.")

            # --- 6. Thêm phụ đề (Logic giữ nguyên, áp dụng cho final_output_with_fx) ---
            final_output_path_final = final_output_with_fx # Đường dẫn trả về cuối cùng

            if VIDEO_SETTINGS.get("enable_subtitles", False):
                logger.info("Adding subtitles...")
                subtitled_output_path = os.path.splitext(final_output_with_fx)[0] + "_subs" + os.path.splitext(final_output_with_fx)[1]
                # Cần đường dẫn audio gốc của các speech units để tạo SRT chính xác
                # Tìm một file audio unit bất kỳ để xác định thư mục audio
                first_audio_unit = audio_map.get(1) if 1 in audio_map else (list(audio_map.values())[0] if audio_map else None)
                audio_unit_dir = os.path.dirname(first_audio_unit['path']) if first_audio_unit else None

                if audio_unit_dir:
                    # Ghép các file audio unit lại thành 1 file tạm để tạo SRT tổng thể
                    temp_full_audio_path = os.path.join(temp_project_dir, f"combined_audio_{project_id}.mp3")
                    unit_audio_clips_for_srt = []
                    all_clips_to_close.append(temp_full_audio_path) # Đánh dấu để xóa sau
                    try:
                        logger.info("Combining speech unit audios for subtitle generation...")
                        sorted_units = sorted(audio_map.values(), key=lambda x: x['unit_number'])
                        clips_to_concat = [AudioFileClip(unit['path']) for unit in sorted_units if os.path.exists(unit['path'])]
                        if clips_to_concat:
                                combined_audio = concatenate_audioclips(clips_to_concat)
                                combined_audio.write_audiofile(temp_full_audio_path, codec='mp3')
                                combined_audio.close() # Đóng clip tổng
                                for clip in clips_to_concat: clip.close() # Đóng clip con

                                if os.path.exists(temp_full_audio_path):
                                    # Gọi hàm thêm phụ đề bằng ffmpeg
                                    subtitled_video_path = self.add_subtitles_to_video_ffmpeg(
                                        video_path=final_output_with_fx, # Video đã có hoặc không có nhạc nền
                                        audio_path_for_srt=temp_full_audio_path, # Audio tổng để tạo SRT
                                        output_path=subtitled_output_path
                                    )
                                    if subtitled_video_path and os.path.exists(subtitled_video_path):
                                        logger.info(f"Successfully added subtitles: {subtitled_video_path}")
                                        # Xóa file video không có phụ đề nếu tên khác nhau
                                        if final_output_with_fx != subtitled_video_path and os.path.exists(final_output_with_fx):
                                            try:
                                                # Đóng file trước khi xóa (quan trọng)
                                                # Cần kiểm tra xem clip nào đang giữ file này
                                                # Cách đơn giản là không đóng clip final_video_no_music sớm hơn
                                                if 'final_video_no_music' in locals() and final_video_no_music and final_output_with_fx == intermediate_output_path:
                                                    final_video_no_music.close()
                                                    del final_video_no_music # Xóa tham chiếu

                                                os.remove(final_output_with_fx)
                                                logger.info(f"Removed original video without subtitles: {final_output_with_fx}")
                                            except Exception as rm_err:
                                                logger.warning(f"Could not remove video file before subtitle ({final_output_with_fx}): {rm_err}")
                                        final_output_path_final = subtitled_video_path # Cập nhật đường dẫn cuối cùng
                                    else:
                                        logger.warning("Failed to add subtitles. Returning video without subtitles.")
                                else:
                                    logger.error("Failed to combine audio for subtitles.")
                        else:
                                logger.error("No valid audio unit clips found to combine for subtitles.")

                    except Exception as e:
                        logger.error(f"Error processing audio for subtitles: {e}", exc_info=True)
                    finally:
                        # Xóa file audio tạm
                        if os.path.exists(temp_full_audio_path):
                            try:
                                    os.remove(temp_full_audio_path)
                                    # logger.debug(f"Removed temporary combined audio: {temp_full_audio_path}")
                            except OSError: pass
                else:
                    logger.error("Could not determine audio directory for subtitle generation.")


            # --- 7. Dọn dẹp cuối cùng ---
            logger.debug(f"Final cleanup stage for project {project_id}...")
            # Đóng tất cả các clip đã được quản lý
            closed_count = 0
            for clip in all_clips_to_close:
                if clip and not isinstance(clip, str) and hasattr(clip, 'close') and callable(clip.close):
                    try:
                        # logger.debug(f"  Closing final tracked clip: {type(clip)}")
                        clip.close()
                        closed_count += 1
                    except Exception as close_err:
                        # Tránh lỗi nếu clip đã được đóng bởi một phần khác (dù không nên)
                        if "AttributeError: 'NoneType'" not in str(close_err):
                            logger.warning(f"Error closing a tracked clip during final cleanup: {close_err}")
            logger.debug(f"Closed {closed_count} tracked clips during final cleanup.")

            # Xóa thư mục tạm của project
            if VIDEO_SETTINGS.get("cleanup_temp_files", True):
                try:
                    logger.info(f"Cleaning up temporary project directory: {temp_project_dir}")
                    shutil.rmtree(temp_project_dir, ignore_errors=True)
                    self._cleanup_old_temp_dirs(days=1) # Dọn dẹp các project cũ khác
                except Exception as e:
                    logger.warning(f"Error during final temp directory cleanup: {str(e)}")

            logger.info(f"=== Video Creation Finished for Project: {project_id} ===")
            logger.info(f"Final video saved to: {final_output_path_final}")
            return final_output_path_final

    def _create_speech_unit_video_sequence(self, speech_unit, audio_info, visual_items, temp_dir, language='en'):
        """
        Tạo một VideoClip duy nhất cho một speech_unit, sử dụng thời lượng shot chính xác.
        (Phiên bản sửa lỗi tên phương thức subclip và set_fps cho MoviePy 2.x)
        """
        unit_number = speech_unit['unit_number']
        audio_path = audio_info['path']
        audio_duration = audio_info['duration']
        num_visuals = len(visual_items)

        if audio_duration <= 0 or num_visuals == 0:
            logger.warning(f"Speech Unit {unit_number}: Invalid audio duration ({audio_duration}s) or no visuals ({num_visuals}). Skipping.")
            return None

        logger.info(f"--- Creating sequence for Speech Unit {unit_number} (Audio: {audio_duration:.2f}s) ---")

        # --- 1. Lấy Word Timestamps ---
        word_timestamps = self.get_word_timestamps(
            audio_path,
            model_name=VIDEO_SETTINGS.get("subtitle_whisper_model", "base"),
            language=language
        )

        # --- 2. Tính toán thời lượng Shot ---
        timed_visual_items = None
        use_fallback_timing = True
        if word_timestamps:
            try:
                timed_visual_items = self._calculate_precise_shot_durations(visual_items, word_timestamps)
                if timed_visual_items:
                    use_fallback_timing = False
                    total_calculated_vis_duration = sum(item['calculated_duration'] for item in timed_visual_items)
                    logger.info(f"Unit {unit_number}: Precise durations calculated. Total visual time: {total_calculated_vis_duration:.3f}s (Audio: {audio_duration:.3f}s)")
                else:
                    logger.warning(f"Unit {unit_number}: Failed to calculate precise durations. Falling back.")
            except Exception as calc_e:
                 logger.error(f"Unit {unit_number}: Error calculating precise durations: {calc_e}. Falling back.", exc_info=True)
        else:
            logger.warning(f"Unit {unit_number}: Word alignment failed. Falling back.")

        # --- 3. Tính toán thời gian Fallback (nếu cần) ---
        if use_fallback_timing:
            avg_visual_duration = audio_duration / num_visuals if num_visuals > 0 else 0
            logger.info(f"Unit {unit_number}: Using fallback average visual duration: {avg_visual_duration:.3f}s")
            timed_visual_items = [{**item, 'calculated_duration': avg_visual_duration, 'start_time': -1, 'end_time': -1} for item in visual_items]
            if avg_visual_duration <= 0:
                 logger.error(f"Unit {unit_number}: Cannot proceed with zero or negative average duration.")
                 return None

        # --- 4. Tạo các Clip Visual đã định thời lượng ---
        processed_visual_clips = []
        clips_to_close = []

        for i, item_with_timing in enumerate(timed_visual_items):
            media_path = item_with_timing['path']
            media_type = item_with_timing.get('type', 'image')
            scene_num_for_media = item_with_timing.get('number', f'unit{unit_number}_item{i+1}')
            target_shot_duration = item_with_timing['calculated_duration']

            if target_shot_duration < 0.1:
                 logger.warning(f"Unit {unit_number} Scene {scene_num_for_media}: Skipping shot with very short duration ({target_shot_duration:.3f}s).")
                 continue

            clip_for_item = None
            logger.debug(f"Processing Unit {unit_number} Scene {scene_num_for_media} ({media_type}), Target Duration: {target_shot_duration:.3f}s")

            try:
                if media_type == 'image':
                    temp_img_video_path = os.path.join(temp_dir, f"unit{unit_number}_scene{scene_num_for_media}_img.mp4")
                    animation_type = VIDEO_SETTINGS.get("image_animation", "none")
                    intensity = VIDEO_SETTINGS.get("animation_intensity", 0.02)
                    total_frames = int(self.fps * target_shot_duration)
                    vf_filter = ""
                    if animation_type == "zoom" and total_frames > self.fps / 2:
                        adjusted_intensity = intensity * min(1.0, 5.0 / max(0.5, target_shot_duration))
                        vf_filter = f"zoompan=z='min(zoom+({adjusted_intensity}/{self.fps}), 1.5)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={self.width}x{self.height}:fps={self.fps},setsar=1"
                    else:
                        vf_filter = f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1"

                    image_cmd = [
                        self.ffmpeg_path, "-y",
                        "-loop", "1", "-i", media_path,
                        "-t", str(target_shot_duration),
                        "-vf", vf_filter,
                        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", "-r", str(self.fps), "-an",
                        temp_img_video_path
                    ]
                    subprocess.run(image_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

                    if os.path.exists(temp_img_video_path) and os.path.getsize(temp_img_video_path) > 100:
                        clip_for_item = VideoFileClip(temp_img_video_path)
                        clip_for_item = clip_for_item.with_duration(target_shot_duration)
                    else:
                        logger.error(f"FFmpeg failed to create valid video from image {os.path.basename(media_path)}")
                        black_clip = ColorClip(size=(self.width, self.height), color=(0,0,0), duration=target_shot_duration)
                        # SỬA LỖI: Dùng with_fps
                        clip_for_item = black_clip.with_fps(self.fps)


                elif media_type == 'video':
                    original_clip = VideoFileClip(media_path)
                    clips_to_close.append(original_clip)
                    original_duration = original_clip.duration

                    if original_duration <= target_shot_duration:
                         clip_for_item = original_clip
                         if original_duration < target_shot_duration:
                              logger.warning(f"Unit {unit_number} Scene {scene_num_for_media}: Original video ({original_duration:.2f}s) shorter than target slot ({target_shot_duration:.2f}s).")
                         clip_for_item = clip_for_item.with_duration(target_shot_duration)
                    else:
                        start_time = random.uniform(0, original_duration - target_shot_duration)
                        # SỬA LỖI: Dùng subclip
                        clip_for_item = original_clip.subclipped(start_time, start_time + target_shot_duration)

                    clip_for_item = vfx.Resize(clip_for_item, height=self.height)
                    if abs(clip_for_item.w - self.width) > 1:
                        clip_for_item = vfx.crop(clip_for_item, x_center=clip_for_item.w/2, width=self.width)
                    clip_for_item = vfx.Resize(clip_for_item, newsize=(self.width, self.height))

                # Thêm clip đã xử lý vào danh sách
                if clip_for_item:
                    clip_for_item = clip_for_item.with_duration(target_shot_duration)
                    if clip_for_item.audio:
                        clip_for_item = clip_for_item.without_audio()
                    processed_visual_clips.append(clip_for_item)
                    clips_to_close.append(clip_for_item)
                else:
                     logger.warning(f"Failed to process media for Scene {scene_num_for_media}, using black clip.")
                     black_clip = ColorClip(size=(self.width, self.height), color=(0,0,0), duration=target_shot_duration)
                     # SỬA LỖI: Dùng with_fps
                     black_clip = black_clip.with_fps(self.fps)
                     processed_visual_clips.append(black_clip)
                     clips_to_close.append(black_clip)


            except Exception as e:
                logger.error(f"Error processing media for Scene {scene_num_for_media}: {e}", exc_info=True)
                black_clip = ColorClip(size=(self.width, self.height), color=(0,0,0), duration=target_shot_duration)
                # SỬA LỖI: Dùng with_fps
                black_clip = black_clip.with_fps(self.fps)
                processed_visual_clips.append(black_clip)
                clips_to_close.append(black_clip)

        # --- 5. Nối các Clip Visual ---
        if not processed_visual_clips:
             logger.error(f"Unit {unit_number}: No visual clips were successfully processed.")
             for clip in clips_to_close:
                 if clip and hasattr(clip, 'close'): clip.close()
             return None

        final_visual_sequence = None
        try:
            logger.info(f"Unit {unit_number}: Concatenating {len(processed_visual_clips)} visual clips...")
            final_visual_sequence = concatenate_videoclips(processed_visual_clips, method="compose")
            clips_to_close.append(final_visual_sequence)
            vis_duration = final_visual_sequence.duration
            logger.info(f"Unit {unit_number}: Concatenated visual sequence duration: {vis_duration:.3f}s")

            # --- 6. Điều chỉnh tốc độ để khớp Audio ---
            allowed_diff = max(0.05, audio_duration * 0.01)
            if abs(vis_duration - audio_duration) > allowed_diff:
                speed_factor = vis_duration / audio_duration
                logger.warning(f"Unit {unit_number}: Visual duration ({vis_duration:.3f}s) vs audio ({audio_duration:.3f}s). Adjusting speed by {speed_factor:.4f}x.")
                if 0.1 < speed_factor < 10.0 and audio_duration > 0.1:
                     try:
                          final_visual_sequence = final_visual_sequence.fx(vfx.speedx, factor=speed_factor)
                          final_visual_sequence = final_visual_sequence.with_duration(audio_duration)
                          logger.info(f"Unit {unit_number}: Speed adjusted. Final duration: {final_visual_sequence.duration:.3f}s")
                     except Exception as speed_err:
                          logger.error(f"Unit {unit_number}: Error applying speedx: {speed_err}. Setting duration directly.")
                          final_visual_sequence = final_visual_sequence.with_duration(audio_duration)
                else:
                     logger.error(f"Unit {unit_number}: Extreme speed factor ({speed_factor:.4f}). Setting duration directly.")
                     final_visual_sequence = final_visual_sequence.with_duration(audio_duration)
            else:
                 final_visual_sequence = final_visual_sequence.with_duration(audio_duration)


            # --- 7. Gán Audio ---
            logger.debug(f"Unit {unit_number}: Loading audio clip from {audio_path}")
            audio_clip = AudioFileClip(audio_path)
            clips_to_close.append(audio_clip)

            logger.debug(f"Unit {unit_number}: Setting audio. Visual dur: {final_visual_sequence.duration:.3f}s, Audio dur: {audio_clip.duration:.3f}s")
            try:
                 final_unit_clip = final_visual_sequence.with_audio(audio_clip)
            except AttributeError:
                 logger.warning("'.with_audio()' not found, trying '.set_audio()'.")
                 final_unit_clip = final_visual_sequence.set_audio(audio_clip) # Fallback

            final_unit_clip = final_unit_clip.with_duration(audio_duration)

            logger.info(f"Unit {unit_number}: Successfully created final clip (Duration: {final_unit_clip.duration:.3f}s).")
            return final_unit_clip

        except Exception as e:
            logger.error(f"Unit {unit_number}: Error during final concatenation/audio setting: {e}", exc_info=True)
            return None
        finally:
            # ... (Khối finally để đóng clip giữ nguyên như lần sửa trước) ...
            logger.debug(f"Unit {unit_number}: Cleaning up {len(clips_to_close)} tracked clips (excluding final components)...")
            components_to_keep_open = set()
            if 'audio_clip' in locals() and audio_clip: components_to_keep_open.add(audio_clip)
            if 'final_visual_sequence' in locals() and final_visual_sequence: components_to_keep_open.add(final_visual_sequence)
            if 'final_unit_clip' in locals() and final_unit_clip: components_to_keep_open.add(final_unit_clip)
            for clip in clips_to_close:
                if clip and clip not in components_to_keep_open and hasattr(clip, 'close') and callable(clip.close):
                    try: clip.close()
                    except Exception as close_err: logger.warning(f"Unit {unit_number}: Error closing intermediate clip: {close_err}")
            logger.debug(f"Unit {unit_number}: Intermediate clips cleanup finished.")

    def add_fade_to_scene(self, input_video, output_video, fade_duration=0.5):
        """
        Thêm fade in/out cho một scene video.
        
        Args:
            input_video (str): Đường dẫn video đầu vào
            output_video (str): Đường dẫn video đầu ra với hiệu ứng fade
            fade_duration (float): Thời lượng fade (giây)
            
        Returns:
            str: Đường dẫn video đã xử lý
        """
        try:
            video_duration = self._get_video_duration(input_video)
            
            # Nếu video quá ngắn cho fade in/out
            if video_duration <= fade_duration * 2:
                fade_duration = video_duration / 4  # Giảm thời lượng fade nếu video quá ngắn
                logger.warning(f"Video quá ngắn ({video_duration}s), giảm thời lượng fade xuống {fade_duration}s")
            
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", input_video,
                "-vf", f"fade=t=in:st=0:d={fade_duration},fade=t=out:st={video_duration - fade_duration}:d={fade_duration}",
                "-c:a", "copy",
                output_video
            ]
            
            logger.info(f"Thêm fade in/out cho video: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if os.path.exists(output_video) and os.path.getsize(output_video) > 10000:
                logger.info(f"Đã thêm fade in/out cho video thành công: {output_video}")
                return output_video
            else:
                logger.warning(f"File đầu ra không hợp lệ. Sử dụng video gốc.")
                shutil.copy(input_video, output_video)
                return output_video
                
        except Exception as e:
            logger.error(f"Lỗi khi thêm fade in/out cho video: {str(e)}")
            # Nếu lỗi, copy file gốc
            if not os.path.exists(output_video) or os.path.getsize(output_video) < 10000:
                shutil.copy(input_video, output_video)
            return output_video

    def create_simple_video(self, title, media_paths, audio_paths, output_path):
        """
        Tạo một video đơn giản từ danh sách media và audio.
        
        Args:
            title (str): Tiêu đề video
            media_paths (list): Danh sách các đường dẫn đến các media (ảnh, video)
            audio_paths (list): Danh sách các đường dẫn đến các file audio tương ứng
            output_path (str): Đường dẫn file video đầu ra
            
        Returns:
            str: Đường dẫn đến video đã tạo
        """
        if len(media_paths) != len(audio_paths):
            raise ValueError("Số lượng media và audio phải bằng nhau")
        
        logger.info(f"Tạo video đơn giản cho: '{title}'")
        
        # Tạo thư mục tạm
        temp_dir = os.path.join(self.temp_video_dir, f"simple_{int(time.time())}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Tạo video cho từng cặp media-audio
        scene_videos = []
        
        for i, (media_path, audio_path) in enumerate(zip(media_paths, audio_paths)):
            if not os.path.exists(media_path) or not os.path.exists(audio_path):
                logger.warning(f"Bỏ qua cặp {i+1}: file không tồn tại.")
                continue
            
            # Xác định loại media (ảnh hay video)
            media_type = "video" if media_path.lower().endswith(('.mp4', '.mov', '.avi')) else "image"
            
            # Tạo media item
            media_item = {
                "type": media_type,
                "media_type": "scene",
                "number": i+1,
                "path": media_path,
                "duration": 5  # Default duration
            }
            
            # Tạo output path cho scene này
            output_video = os.path.join(temp_dir, f"scene_{i+1}.mp4")
            
            try:
                # Xử lý media và audio
                scene_video = self.process_scene_media(media_item, audio_path, output_video)
                scene_videos.append(scene_video)
                logger.info(f"Đã xử lý cặp {i+1}: {os.path.basename(media_path)} + {os.path.basename(audio_path)}")
            except Exception as e:
                logger.error(f"Lỗi khi xử lý cặp {i+1}: {str(e)}")
        
        if not scene_videos:
            raise Exception("Không có scene video nào được tạo thành công")
        
        # Nối các scene videos
        logger.info(f"Nối {len(scene_videos)} scene videos thành video cuối cùng")
        logger.info(f"Điều kiện transition: enable={self.enable_transitions}, types={self.transition_types}, 'fade' in types={('fade' in self.transition_types) if self.transition_types else False}")
        if self.enable_transitions and self.transition_types and "fade" in self.transition_types:
            logger.info(f"Áp dụng hiệu ứng chuyển cảnh fade với thời lượng {self.transition_duration}s")
            final_video = self.concatenate_scene_videos_with_fade(scene_videos, output_path, self.transition_duration)
        else:
            logger.info(f"Nối video không có hiệu ứng chuyển cảnh")
            final_video = self.concatenate_scene_videos(scene_videos, output_path)
        
        # Dọn dẹp
        if VIDEO_SETTINGS.get("cleanup_temp_files", True):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
        
        logger.info(f"Đã tạo video đơn giản thành công: {output_path}")
        return final_video
    
    def _get_video_duration(self, video_path):
        """Lấy thời lượng của video."""
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            clip.close()
            return duration
        except Exception as e:
            logger.warning(f"Không xác định được thời lượng video: {str(e)}")
            return 0
    
    def _cleanup_old_temp_dirs(self, days=1):
        """Dọn dẹp các thư mục tạm cũ."""
        try:
            cutoff_time = time.time() - (days * 86400)  # days * 24 hours * 3600 seconds
            for dirname in os.listdir(self.temp_video_dir):
                dir_path = os.path.join(self.temp_video_dir, dirname)
                if os.path.isdir(dir_path) and os.path.getmtime(dir_path) < cutoff_time:
                    shutil.rmtree(dir_path, ignore_errors=True)
                    logger.info(f"Đã xóa thư mục tạm cũ: {dir_path}")
        except Exception as e:
            logger.warning(f"Lỗi khi dọn dẹp thư mục tạm cũ: {str(e)}")
    
    def extract_thumbnail(self, video_path, output_path=None, time_pos=1):
        """
        Trích xuất một khung hình từ video để làm thumbnail.
        
        Args:
            video_path (str): Đường dẫn đến video
            output_path (str, optional): Đường dẫn lưu thumbnail
            time_pos (float, optional): Vị trí thời gian để lấy khung hình (giây)
            
        Returns:
            str: Đường dẫn đến thumbnail đã tạo
        """
        if output_path is None:
            base, _ = os.path.splitext(video_path)
            output_path = f"{base}_thumb.jpg"
        
        try:
            logger.info(f"Trích xuất thumbnail từ video: {os.path.basename(video_path)}")
            video = VideoFileClip(video_path)
            
            # Lấy khung hình tại thời điểm cụ thể
            if time_pos >= video.duration:
                time_pos = video.duration / 2  # Lấy giữa video nếu time_pos quá lớn
                
            frame = video.get_frame(time_pos)
            
            # Lưu khung hình
            from PIL import Image
            import numpy as np
            Image.fromarray(np.uint8(frame)).save(output_path)
            
            video.close()
            logger.info(f"Đã trích xuất thumbnail: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Lỗi khi trích xuất thumbnail: {str(e)}")
            return None

    ###---- SUBTITLE  ----###
    def add_subtitles_to_video(self, video_path, script=None, audio_dir=None, output_path=None):
        """
        Thêm phụ đề cứng (hard subtitles) vào video bằng cách sử dụng Whisper và FFmpeg.
        """
        if output_path is None:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_with_subs{ext}"
        
        logger.info(f"Thêm phụ đề vào video: {os.path.basename(video_path)}")
        
        try:
            # Lấy thư mục output
            output_dir = os.path.dirname(output_path)
            video_filename = os.path.basename(video_path)
            output_filename = os.path.basename(output_path)
            
            # Tạo thư mục tạm riêng nhưng ở bên trong thư mục output để dễ truy cập
            temp_subtitle_dir = os.path.join(output_dir, f"sub_temp_{int(time.time())}")
            os.makedirs(temp_subtitle_dir, exist_ok=True)
            
            # Tìm file audio tổng của video
            full_audio_path = self._find_audio_file(video_path, audio_dir)
            if not full_audio_path:
                logger.error("Không thể tìm thấy hoặc trích xuất audio từ video")
                # Dọn dẹp thư mục tạm
                shutil.rmtree(temp_subtitle_dir, ignore_errors=True)
                return video_path
            
            # Tạo file SRT trong thư mục tạm
            srt_path = os.path.join(temp_subtitle_dir, "subtitle.srt")
            generated_srt = self.generate_subtitles_with_whisper(
                full_audio_path, 
                srt_path, 
                model=VIDEO_SETTINGS.get("subtitle_whisper_model", "base"), 
                language=VIDEO_SETTINGS.get("subtitle_language", "en")
            )
            
            if not generated_srt or not os.path.exists(generated_srt):
                logger.error("Không thể tạo phụ đề với Whisper")
                # Dọn dẹp thư mục tạm
                shutil.rmtree(temp_subtitle_dir, ignore_errors=True)
                return video_path
            
            # Lấy đường dẫn tuyệt đối của ffmpeg.exe
            ffmpeg_absolute_path = os.path.abspath(self.ffmpeg_path)
            logger.info(f"Đường dẫn tuyệt đối ffmpeg: {ffmpeg_absolute_path}")
            
            # Tạo batch file đơn giản để chạy từ thư mục output
            batch_file = os.path.join(temp_subtitle_dir, "add_subs.bat")
            
            temp_dir_name = os.path.basename(temp_subtitle_dir)
            
            with open(batch_file, 'w', encoding='utf-8') as f:
                f.write('@echo off\n')
                f.write(f'cd "{output_dir}"\n')
                f.write(f'"{ffmpeg_absolute_path}" -y -i "{video_filename}" -vf "subtitles={temp_dir_name}/subtitle.srt" -c:a copy "{output_filename}"\n')
                f.write('echo Completed successfully!\n')
            
            # Chạy batch file
            logger.info(f"Chạy batch file: {batch_file}")
            try:
                result = subprocess.run(batch_file, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout_output = result.stdout.decode('utf-8', errors='ignore')
                stderr_output = result.stderr.decode('utf-8', errors='ignore')
                
                logger.info(f"Batch execution stdout: {stdout_output}")
                logger.info(f"Batch execution stderr: {stderr_output}")
                
                if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                    logger.info(f"Thêm phụ đề thành công: {output_path}")
                    # Dọn dẹp thư mục tạm sau khi thành công
                    shutil.rmtree(temp_subtitle_dir, ignore_errors=True)
                    logger.info(f"Đã dọn dẹp thư mục tạm: {temp_subtitle_dir}")
                    return output_path
                else:
                    logger.error(f"Không thể thêm phụ đề. Mã lỗi: {result.returncode}")
                    # Giữ lại thư mục tạm trong trường hợp lỗi để debug (tuỳ chọn)
                    # Nếu muốn luôn dọn dẹp, hãy bỏ comment dòng dưới đây
                    # shutil.rmtree(temp_subtitle_dir, ignore_errors=True)
                    return video_path
            except Exception as e:
                logger.error(f"Lỗi khi chạy batch file: {str(e)}")
                # Giữ lại thư mục tạm trong trường hợp lỗi để debug (tuỳ chọn)
                # Nếu muốn luôn dọn dẹp, hãy bỏ comment dòng dưới đây
                # shutil.rmtree(temp_subtitle_dir, ignore_errors=True)
                return video_path
        except Exception as e:
            logger.error(f"Lỗi khi thêm phụ đề: {str(e)}")
            # Dọn dẹp thư mục tạm nếu có
            if 'temp_subtitle_dir' in locals():
                shutil.rmtree(temp_subtitle_dir, ignore_errors=True)
                logger.info(f"Đã dọn dẹp thư mục tạm: {temp_subtitle_dir}")
            return video_path

    def _find_audio_file(self, video_path, audio_dir=None):
        """
        Tìm file audio phù hợp hoặc trích xuất audio từ video nếu cần.
        """
        # Tìm file audio tổng trong audio_dir
        full_audio_path = None
        if audio_dir and os.path.exists(audio_dir):
            # Tìm file audio tổng
            for filename in ["full_audio.mp3", "all_audio.mp3", "complete_audio.mp3"]:
                potential_path = os.path.join(audio_dir, filename)
                if os.path.exists(potential_path):
                    full_audio_path = potential_path
                    logger.info(f"Tìm thấy file audio tổng: {full_audio_path}")
                    break
            
            if not full_audio_path:
                # Tìm theo tên khác nếu có
                import glob
                potential_paths = glob.glob(os.path.join(audio_dir, "*.mp3"))
                if potential_paths:
                    # Lấy file có kích thước lớn nhất
                    largest_file = max(potential_paths, key=os.path.getsize)
                    full_audio_path = largest_file
                    logger.info(f"Tìm thấy file audio lớn nhất: {full_audio_path}")
        
        # Trích xuất audio từ video nếu không tìm thấy
        if not full_audio_path:
            logger.info("Không tìm thấy file audio đầy đủ. Trích xuất audio từ video...")
            temp_audio_path = os.path.join(self.temp_dir, f"extracted_audio_{int(time.time())}.mp3")
            try:
                cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", video_path,
                    "-q:a", "0",
                    "-map", "a",
                    temp_audio_path
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                full_audio_path = temp_audio_path
                logger.info(f"Đã trích xuất audio từ video: {full_audio_path}")
            except Exception as e:
                logger.error(f"Lỗi khi trích xuất audio: {str(e)}")
                return None
        
        # Sửa lỗi: Nếu full_audio_path là một đối tượng Path, chuyển đổi thành str
        if full_audio_path:
            # Đảm bảo full_audio_path là chuỗi
            full_audio_path = str(full_audio_path)
            
            # Kiểm tra đúng khi dọn dẹp file tạm
            temp_dir_str = str(self.temp_dir)
            if full_audio_path.startswith(temp_dir_str) and os.path.exists(full_audio_path):
                logger.debug(f"Audio path {full_audio_path} nằm trong thư mục tạm {temp_dir_str}")
        
        return full_audio_path

    def generate_subtitles_with_whisper(self, audio_path, output_srt_path=None, model="base", language="en"):
        """
        Sử dụng Whisper để tạo file phụ đề SRT từ audio, với fallback từ faster-whisper sang whisper tiêu chuẩn.
        
        Args:
            audio_path (str): Đường dẫn đến file audio
            output_srt_path (str, optional): Đường dẫn đầu ra cho file SRT
            model (str): Tên mô hình Whisper (tiny, base, small, medium, large)
            language (str): Ngôn ngữ của audio (auto để tự động phát hiện)
            
        Returns:
            str: Đường dẫn đến file SRT đã tạo
        """
        if not audio_path or not os.path.exists(audio_path):
            logger.error(f"Không tìm thấy file audio: {audio_path}")
            return None
            
        if output_srt_path is None:
            output_srt_path = os.path.splitext(audio_path)[0] + ".srt"
        
        logger.info(f"Tạo phụ đề từ file audio: {audio_path} với mô hình: {model}")
        
        # Thử sử dụng faster-whisper trước
        try:
            logger.info("Thử sử dụng faster-whisper...")
            from faster_whisper import WhisperModel
            
            # Tải mô hình
            logger.info(f"Đang tải mô hình faster-whisper: {model}")
            whisper_model = WhisperModel(model, device="cpu", compute_type="float32")
            
            # Transcribe audio
            logger.info("Đang xử lý audio với faster-whisper...")
            transcribe_options = {
                "language": language if language != "auto" else None,
                "task": "transcribe"
            }
            segments, info = whisper_model.transcribe(audio_path, **transcribe_options)
            
            # Tạo file SRT
            with open(output_srt_path, "w", encoding="utf-8") as f:
                i = 1
                for segment in segments:
                    # Chuyển đổi thời gian
                    start = self._format_srt_time(segment.start)
                    end = self._format_srt_time(segment.end)
                    
                    # Ghi định dạng SRT
                    f.write(f"{i}\n{start} --> {end}\n{segment.text.strip()}\n\n")
                    i += 1
            
            logger.info(f"Đã tạo file phụ đề SRT với faster-whisper: {output_srt_path}")
            return output_srt_path
                
        except ImportError as e:
            logger.warning(f"Không thể import faster-whisper: {str(e)}. Thử fallback sang whisper tiêu chuẩn...")
            # Fallback sang whisper tiêu chuẩn
            try:
                import whisper
                
                # Tải mô hình
                logger.info(f"Đang tải mô hình whisper tiêu chuẩn: {model}")
                whisper_model = whisper.load_model(model)
                
                # Transcribe audio
                logger.info("Đang xử lý audio với whisper tiêu chuẩn...")
                transcribe_options = {"language": language if language != "auto" else None}
                result = whisper_model.transcribe(audio_path, **transcribe_options)
                
                # Tạo file SRT
                with open(output_srt_path, "w", encoding="utf-8") as f:
                    for i, segment in enumerate(result["segments"], 1):
                        # Chuyển đổi thời gian
                        start = self._format_srt_time(segment["start"])
                        end = self._format_srt_time(segment["end"])
                        
                        # Ghi định dạng SRT
                        f.write(f"{i}\n{start} --> {end}\n{segment['text'].strip()}\n\n")
                
                logger.info(f"Đã tạo file phụ đề SRT với whisper tiêu chuẩn: {output_srt_path}")
                return output_srt_path
                
            except ImportError as e2:
                logger.error(f"Không thể import whisper tiêu chuẩn: {str(e2)}")
                logger.error("Cả hai thư viện faster-whisper và whisper đều không khả dụng.")
                logger.error("Hãy cài đặt ít nhất một trong hai: pip install faster-whisper HOẶC pip install openai-whisper")
                return None
        
        except Exception as e:
            logger.error(f"Lỗi khi tạo phụ đề với faster-whisper: {str(e)}")
            
            # Thử fallback sang whisper tiêu chuẩn nếu lỗi không phải ImportError
            try:
                logger.info("Thử fallback sang whisper tiêu chuẩn...")
                import whisper
                
                # Tải mô hình
                logger.info(f"Đang tải mô hình whisper tiêu chuẩn: {model}")
                whisper_model = whisper.load_model(model)
                
                # Transcribe audio
                logger.info("Đang xử lý audio với whisper tiêu chuẩn...")
                transcribe_options = {"language": language if language != "auto" else None}
                result = whisper_model.transcribe(audio_path, **transcribe_options)
                
                # Tạo file SRT
                with open(output_srt_path, "w", encoding="utf-8") as f:
                    for i, segment in enumerate(result["segments"], 1):
                        # Chuyển đổi thời gian
                        start = self._format_srt_time(segment["start"])
                        end = self._format_srt_time(segment["end"])
                        
                        # Ghi định dạng SRT
                        f.write(f"{i}\n{start} --> {end}\n{segment['text'].strip()}\n\n")
                
                logger.info(f"Đã tạo file phụ đề SRT với whisper tiêu chuẩn: {output_srt_path}")
                return output_srt_path
                
            except Exception as e2:
                logger.error(f"Cả faster-whisper và whisper tiêu chuẩn đều lỗi: {str(e)} / {str(e2)}")
                return None

    def _generate_subtitles_with_standard_whisper(self, audio_path, output_srt_path, model="base", language="en"):
        """
        Sử dụng OpenAI Whisper tiêu chuẩn để tạo SRT.
        """
        import whisper
        
        # Tải mô hình (lần đầu sẽ tải về, lần sau sẽ dùng cache)
        logger.info(f"Đang tải mô hình Whisper: {model}")
        whisper_model = whisper.load_model(model)
        
        # Transcribe audio
        logger.info("Đang xử lý audio với Whisper...")
        transcribe_options = {"language": language if language != "auto" else None}
        result = whisper_model.transcribe(audio_path, **transcribe_options)
        
        # Tạo file SRT
        with open(output_srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(result["segments"], 1):
                # Chuyển đổi thời gian
                start = self._format_srt_time(segment["start"])
                end = self._format_srt_time(segment["end"])
                
                # Ghi định dạng SRT
                f.write(f"{i}\n{start} --> {end}\n{segment['text'].strip()}\n\n")
        
        logger.info(f"Đã tạo file phụ đề SRT: {output_srt_path}")
        return output_srt_path

    def _generate_subtitles_with_faster_whisper(self, audio_path, output_srt_path, model="base", language="en"):
        """
        Sử dụng faster-whisper để tạo SRT (nhanh hơn, hỗ trợ GPU tốt hơn).
        """
        from faster_whisper import WhisperModel
        
        # Tải mô hình
        logger.info(f"Đang tải mô hình faster-whisper: {model}")
        whisper_model = WhisperModel(model, device="auto", compute_type="auto")
        
        # Transcribe audio
        logger.info("Đang xử lý audio với faster-whisper...")
        transcribe_options = {
            "language": language if language != "auto" else None,
            "task": "transcribe"
        }
        segments, info = whisper_model.transcribe(audio_path, **transcribe_options)
        
        # Tạo file SRT
        with open(output_srt_path, "w", encoding="utf-8") as f:
            i = 1
            for segment in segments:
                # Chuyển đổi thời gian
                start = self._format_srt_time(segment.start)
                end = self._format_srt_time(segment.end)
                
                # Ghi định dạng SRT
                f.write(f"{i}\n{start} --> {end}\n{segment.text.strip()}\n\n")
                i += 1
        
        logger.info(f"Đã tạo file phụ đề SRT với faster-whisper: {output_srt_path}")
        return output_srt_path

    def _format_srt_time(self, seconds):
        """
        Chuyển đổi thời gian từ giây sang định dạng SRT (HH:MM:SS,mmm)
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        millisecs = int((secs - int(secs)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(secs):02d},{millisecs:03d}"

# Kiểm tra module khi chạy trực tiếp
if __name__ == "__main__":
    print("===== Kiểm tra VideoEditor =====")
    
    # Kiểm tra các thư mục cấu hình
    if not os.path.exists(TEMP_DIR):
        print(f"Tạo thư mục tạm: {TEMP_DIR}")
        os.makedirs(TEMP_DIR, exist_ok=True)
    
    if not os.path.exists(ASSETS_DIR):
        print(f"Tạo thư mục assets: {ASSETS_DIR}")
        os.makedirs(ASSETS_DIR, exist_ok=True)
    
    # Thông tin cấu hình
    print(f"Kích thước video: {VIDEO_SETTINGS.get('width', 1920)}x{VIDEO_SETTINGS.get('height', 1080)}")
    print(f"FPS: {VIDEO_SETTINGS.get('fps', 24)}")
    print(f"Enable transitions: {VIDEO_SETTINGS.get('enable_transitions', True)}")
    print(f"Enable background music: {VIDEO_SETTINGS.get('enable_background_music', False)}")
    
    # Kiểm tra test files nếu tồn tại
    test_image = os.path.join(ASSETS_DIR, "test_image.jpg")
    test_audio = os.path.join(ASSETS_DIR, "test_audio.mp3")
    
    if os.path.exists(test_image) and os.path.exists(test_audio):
        print(f"\nTạo video test từ {test_image} và {test_audio}...")
        
        generator = VideoEditor()
        
        # Tạo media_item giả lập
        media_item = {
            "type": "image",
            "media_type": "scene",
            "number": 1,
            "path": test_image,
            "content": "Đây là nội dung test.",
            "duration": 5
        }
        
        # Tạo video test
        test_output = os.path.join(TEMP_DIR, "test_video.mp4")
        
        try:
            result = generator.process_scene_media(media_item, test_audio, test_output)
            print(f"Đã tạo video test: {result}")
            print(f"Video test duration: {generator._get_video_duration(result):.2f}s")
        except Exception as e:
            print(f"Lỗi khi tạo video test: {str(e)}")
    else:
        print("\nKhông tìm thấy file test. Để kiểm tra đầy đủ, cần thêm:")
        print(f"- Ảnh test: {test_image}")
        print(f"- Audio test: {test_audio}")
    
    print("\n===== Kiểm tra kết thúc =====")