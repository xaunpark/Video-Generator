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
import itertools
from itertools import groupby

from src.logger_config import setup_logger
logger = setup_logger(__name__)

# Import MoviePy từ các phiên bản 2.x trở lên
from moviepy import *
from moviepy.video.fx.MultiplySpeed import MultiplySpeed
from moviepy import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips, TextClip, ColorClip
import moviepy.video.fx as vfx
from moviepy.audio.AudioClip import CompositeAudioClip, concatenate_audioclips
from moviepy.video import VideoClip
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

from src.image_generator import ImageGenerator # Để tạo Chapter Cards

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

        # Thêm thuộc tính mới để theo dõi các file clip tạm thời
        self.temp_unit_files = []

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
    def _calculate_precise_shot_durations(self, visual_items, word_timestamps, audio_duration=None):
        """
        Tính thời lượng chính xác cho mỗi visual item (shot) dựa trên word timestamps.

        Args:
            visual_items (list): List các dict media item (chứa 'content', 'number').
            word_timestamps (list): List word timestamps từ Whisper cho cả speech unit.
            audio_duration (float): Thời lượng audio tổng thể (nếu biết) để kiểm tra tính hợp lý.

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
                calculated_duration = max(0.5, calculated_duration) # Thời lượng tối thiểu 500ms

                # Cập nhật timestamp_idx chính thức cho shot tiếp theo
                # Dùng vị trí *sau* từ cuối cùng khớp được
                timestamp_idx = last_match_idx + 1
                total_duration_calculated += calculated_duration
                logger.debug(f"Scene {scene_num} duration calculated: {calculated_duration:.3f}s (from ts_idx {first_match_idx} to {last_match_idx})")

            elif not shot_words: # Trường hợp shot rỗng đã xử lý ở trên
                calculated_duration = 0.5
                logger.debug(f"Scene {scene_num} has no words, duration: {calculated_duration:.3f}s")
            else: # Trường hợp không khớp được từ nào
                logger.warning(f"Scene {scene_num}: Failed to calculate valid duration for shot '{shot_text}' (matched {words_matched_count}/{len(shot_words)} words). Assigning default 0.5s.")
                calculated_duration = 0.5 # Gán duration mặc định nếu lỗi (tăng lên 0.5s thay vì 0.2s)
                # Không cập nhật timestamp_idx nếu shot này lỗi hoàn toàn

            timed_items.append({
                **item,
                'calculated_duration': calculated_duration,
                'start_time': start_time, # Lưu lại để debug nếu cần
                'end_time': end_time,     # Lưu lại để debug nếu cần
                'matched_words': words_matched_count # Thêm thông tin để biết bao nhiêu từ khớp được
                })

        # KẾT THÚC: Thêm đoạn kiểm tra tính hợp lý của kết quả tính toán
        total_duration_calculated = sum(item['calculated_duration'] for item in timed_items)
        
        # Nếu có audio_duration, kiểm tra xem tổng thời lượng có hợp lý không
        if audio_duration is not None:
            match_count = sum(1 for item in timed_items if item.get('matched_words', 0) > 0)
            match_ratio = match_count / len(timed_items) if timed_items else 0
            logger.info(f"Word timestamp matching: {match_count}/{len(timed_items)} shots matched ({match_ratio:.2%}). Total duration: {total_duration_calculated:.3f}s vs audio {audio_duration:.3f}s")
            
            # Nếu <80% thời lượng audio hoặc <50% số cảnh khớp được -> coi như thất bại
            if match_ratio < 0.5 or total_duration_calculated < audio_duration * 0.8:
                logger.error("Word timestamp matching considered failed. Too few matches or duration too short compared to audio.")
                return None  # Báo hiệu thất bại để kích hoạt phương pháp fallback
        
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
            script_mode = script.get("script_mode", "basic") # Lấy chế độ từ script
            logger.info(f"Detected script mode: {script_mode}")
            image_gen = None # Khởi tạo là None
            if script_mode == "advanced":
                image_gen = ImageGenerator() # Chỉ khởi tạo nếu là chế độ nâng cao
                if not image_gen:
                    logger.error("Failed to initialize ImageGenerator, cannot create chapter cards.")
                    # Decide how to handle this: fallback to basic or exit? For now, log and continue without cards.

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
                        intro_image_clip = intro_image_clip.with_fps(self.fps).resized(width=self.width) # Đảm bảo FPS và size
                        # Cần crop nếu tỉ lệ không đúng (thường title card đã đúng size)
                        if abs(intro_image_clip.aspect_ratio - (self.width/self.height)) > 0.01:
                            intro_image_clip = intro_image_clip.cropped(width=self.width, height=self.height, x_center=intro_image_clip.w/2, y_center=intro_image_clip.h/2)

                        intro_clip = intro_image_clip.with_audio(intro_audio_clip)
                        intro_clip = intro_clip.with_duration(intro_duration) # Đảm bảo duration cuối
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
            self.temp_unit_files = []  # Reset danh sách khi bắt đầu project mới

            all_speech_units = sorted(script.get('speech_units', []), key=lambda u: u.get('unit_number', 0)) # Sắp xếp trước

            if script_mode == "basic":
                # --- BASIC MODE ---
                logger.info("Processing speech units sequentially (Basic Mode)...")
                for speech_unit in all_speech_units: # Lặp qua các unit đã sắp xếp
                    unit_number = speech_unit['unit_number']
                    scene_numbers_in_unit = speech_unit['scene_numbers']
                    logger.info(f"--- Processing Speech Unit {unit_number} (Basic) ---")

                    # --- COPY LOGIC XỬ LÝ 1 SPEECH UNIT TỪ CODE CŨ VÀO ĐÂY ---
                    # Bắt đầu từ: Lấy thông tin audio cho unit này
                    audio_info = audio_map.get(unit_number)
                    if not audio_info or not os.path.exists(audio_info['path']):
                        logger.warning(f"Audio not found for Speech Unit {unit_number}. Skipping.")
                        continue

                    # Lấy danh sách media items (visuals)
                    visual_items_for_unit = []
                    for scene_num in scene_numbers_in_unit:
                        media_item = media_map.get(scene_num)
                        if media_item and media_item.get('path') and os.path.exists(media_item['path']):
                            visual_items_for_unit.append(media_item)
                        else:
                            logger.warning(f"Media not found or invalid for Scene/Shot {scene_num} in Unit {unit_number}.")
                    if not visual_items_for_unit:
                        logger.warning(f"No valid media for Speech Unit {unit_number}. Skipping.")
                        continue

                    # Gọi hàm tạo sequence video cho unit
                    unit_clip = None
                    unit_temp_path = os.path.join(temp_project_dir, f"unit_{unit_number}_temp.mp4")
                    try:
                        # Gọi hàm _create_speech_unit_video_sequence_direct như cũ
                        unit_clip = self._create_speech_unit_video_sequence_direct(
                            speech_unit=speech_unit,
                            audio_info=audio_info,
                            visual_items=visual_items_for_unit,
                            temp_dir=temp_project_dir,
                            language=language
                        )
                        if unit_clip:
                            # Lưu clip thành file tạm (logic cũ)
                            logger.info(f"Saving Unit {unit_number} clip to temporary file...")
                            try:
                                unit_clip.write_videofile(
                                    unit_temp_path, codec='libx264', audio_codec='aac',
                                    temp_audiofile=os.path.join(temp_project_dir, f'temp-unit-{unit_number}-audio.m4a'),
                                    remove_temp=True, fps=self.fps, preset="ultrafast", logger=None,
                                    threads=os.cpu_count() or 4,
                                    ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"]
                                )
                                if os.path.exists(unit_temp_path) and os.path.getsize(unit_temp_path) > 10000:
                                    # Dùng SỐ unit làm key cho chế độ basic
                                    self.temp_unit_files.append((unit_number, unit_temp_path))
                                    logger.info(f"Unit {unit_number} saved to temporary file: {unit_temp_path}")
                                else:
                                    logger.warning(f"Failed to save Unit {unit_number} to temporary file.")
                                unit_clip.close() # Đóng clip sau khi lưu
                            except Exception as write_err:
                                logger.error(f"Error writing Unit {unit_number} to temp file: {write_err}", exc_info=True)
                                if unit_clip and hasattr(unit_clip, 'close'): unit_clip.close()
                        else:
                            logger.error(f"Failed to create video sequence for Speech Unit {unit_number}.")
                    except Exception as unit_err:
                        logger.error(f"Critical error processing Speech Unit {unit_number}: {unit_err}", exc_info=True)
                        if unit_clip and hasattr(unit_clip, 'close'): unit_clip.close()
                    # --- KẾT THÚC PHẦN COPY LOGIC BASIC ---
                # --- END BASIC MODE ---

            elif script_mode == "advanced":
                # --- ADVANCED MODE (CHAPTERS) ---
                logger.info("Processing content by chapters (Advanced Mode)...")
                chapter_title_duration = VIDEO_SETTINGS.get("chapter_title_duration", 2.5) # Lấy duration từ settings

                # Sắp xếp lại units theo chapter rồi đến unit number để groupby hoạt động đúng
                all_speech_units_sorted_for_grouping = sorted(
                    all_speech_units,
                    key=lambda u: (u.get('chapter_number', 0), u.get('unit_number', 0))
                )

                current_clip_index = 0 # Để tạo key duy nhất cho file tạm

                # Lặp qua các chapter đã nhóm
                for chapter_num, unit_group_iterator in groupby(all_speech_units_sorted_for_grouping, key=lambda u: u.get('chapter_number', 0)):
                    unit_group = list(unit_group_iterator) # Chuyển iterator thành list để dùng nhiều lần
                    if not unit_group: continue # Bỏ qua nếu nhóm rỗng

                    first_unit_in_chapter = unit_group[0]
                    chapter_title = first_unit_in_chapter.get('chapter_title', f'Chapter {chapter_num}') # Lấy title từ unit đầu tiên
                    logger.info(f"--- Processing Chapter {chapter_num}: '{chapter_title}' ---")

                    # 1. Tạo và thêm Chapter Title Card Clip
                    if image_gen: # Chỉ tạo nếu ImageGenerator đã khởi tạo thành công
                        chapter_card_img_path = os.path.join(temp_project_dir, f"chapter_{chapter_num}_card.png")
                        chapter_card_video_path = os.path.join(temp_project_dir, f"chapter_{chapter_num}_card_video.mp4")

                        # Gọi hàm tạo ảnh card chapter
                        created_card_img_path = image_gen._create_chapter_title_card(chapter_title, chapter_card_img_path, chapter_num)

                        if created_card_img_path and os.path.exists(created_card_img_path):
                            logger.info(f"Creating video clip for Chapter {chapter_num} title card...")
                            try:
                                # Sử dụng FFmpeg trực tiếp để tạo video từ ảnh (hiệu quả hơn)
                                ffmpeg_cmd = [
                                    self.ffmpeg_path, "-y",
                                    "-loop", "1",                  # Lặp ảnh đầu vào
                                    "-i", created_card_img_path,   # Ảnh card chapter
                                    "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo", # Nguồn audio im lặng
                                    "-t", str(chapter_title_duration), # Thời lượng mong muốn
                                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", # Encode video
                                    "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,format=pix_fmts=yuv420p", # Scale và pad, đảm bảo format
                                    "-c:a", "aac", "-b:a", "128k", # Encode audio im lặng
                                    "-r", str(self.fps),           # Đặt FPS
                                    chapter_card_video_path
                                ]
                                subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

                                if os.path.exists(chapter_card_video_path) and os.path.getsize(chapter_card_video_path) > 1000:
                                    # Dùng tuple (chapter_num, -1) để đảm bảo card đứng trước unit 0 của chapter đó
                                    self.temp_unit_files.append(((chapter_num, -1), chapter_card_video_path))
                                    logger.info(f"Chapter {chapter_num} title card video saved to temp file: {chapter_card_video_path}")
                                else:
                                    logger.warning(f"Failed to create Chapter {chapter_num} title card video using FFmpeg.")

                            except Exception as card_err:
                                logger.error(f"Error creating video clip for chapter {chapter_num} title card: {card_err}", exc_info=True)
                        else:
                            logger.warning(f"Could not create image for chapter {chapter_num} title card. Skipping card.")
                    else:
                        logger.warning("ImageGenerator not available. Skipping chapter title card.")


                    # 2. Xử lý các Speech Units trong Chapter này
                    logger.info(f"Processing {len(unit_group)} speech units for Chapter {chapter_num}...")
                    for speech_unit in unit_group:
                        unit_number = speech_unit['unit_number']
                        scene_numbers_in_unit = speech_unit['scene_numbers']
                        logger.info(f"--- Processing Speech Unit {unit_number} (Chapter {chapter_num}) ---")

                        # --- COPY LOGIC XỬ LÝ 1 SPEECH UNIT TỪ CODE CŨ (GIỐNG HET BASIC MODE) VÀO ĐÂY ---
                        audio_info = audio_map.get(unit_number)
                        # ... (lấy audio_info, visual_items_for_unit như trong basic mode) ...
                        if not audio_info or not os.path.exists(audio_info['path']): continue # Skip nếu thiếu
                        visual_items_for_unit = []
                        for scene_num in scene_numbers_in_unit:
                            media_item = media_map.get(scene_num)
                            if media_item and media_item.get('path') and os.path.exists(media_item['path']): visual_items_for_unit.append(media_item)
                            else: logger.warning(f"Media not found or invalid for Scene/Shot {scene_num} in Unit {unit_number}.")
                        if not visual_items_for_unit: continue # Skip nếu thiếu

                        # Gọi hàm tạo sequence video cho unit
                        unit_clip = None
                        unit_temp_path = os.path.join(temp_project_dir, f"unit_{unit_number}_temp.mp4") # Đặt tên file tạm
                        try:
                            unit_clip = self._create_speech_unit_video_sequence_direct(
                                speech_unit=speech_unit, audio_info=audio_info, visual_items=visual_items_for_unit,
                                temp_dir=temp_project_dir, language=language
                            )
                            if unit_clip:
                                # Lưu clip thành file tạm (logic cũ)
                                logger.info(f"Saving Unit {unit_number} (Ch {chapter_num}) clip to temp file...")
                                try:
                                    unit_clip.write_videofile(
                                        unit_temp_path, codec='libx264', audio_codec='aac',
                                        temp_audiofile=os.path.join(temp_project_dir, f'temp-unit-{unit_number}-audio.m4a'),
                                        remove_temp=True, fps=self.fps, preset="ultrafast", logger=None,
                                        threads=os.cpu_count() or 4,
                                        ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"]
                                    )
                                    if os.path.exists(unit_temp_path) and os.path.getsize(unit_temp_path) > 10000:
                                        # Dùng tuple (chapter_num, unit_number) làm key để sắp xếp đúng
                                        self.temp_unit_files.append(((chapter_num, unit_number), unit_temp_path))
                                        logger.info(f"Unit {unit_number} (Ch {chapter_num}) saved to temp file: {unit_temp_path}")
                                    else:
                                        logger.warning(f"Failed to save Unit {unit_number} (Ch {chapter_num}) to temp file.")
                                    unit_clip.close() # Đóng clip sau khi lưu
                                except Exception as write_err:
                                    logger.error(f"Error writing Unit {unit_number} (Ch {chapter_num}) to temp file: {write_err}", exc_info=True)
                                    if unit_clip and hasattr(unit_clip, 'close'): unit_clip.close()
                            else:
                                logger.error(f"Failed to create video sequence for Unit {unit_number} (Ch {chapter_num}).")
                        except Exception as unit_err:
                            logger.error(f"Critical error processing Unit {unit_number} (Ch {chapter_num}): {unit_err}", exc_info=True)
                            if unit_clip and hasattr(unit_clip, 'close'): unit_clip.close()
                        # --- KẾT THÚC PHẦN COPY LOGIC XỬ LÝ UNIT ---
                # --- END ADVANCED MODE ---
            else:
                logger.error(f"Unknown script mode: {script_mode}. Cannot process content.")
                # Handle error appropriately, maybe return None after cleanup

            # --- 3. Xử lý Outro (Giống Intro, tạo file tạm) ---
            if outro_media_item and outro_audio_info:
                logger.info("Processing Outro...")
                # Không cần tạo MoviePy clip nữa, sẽ tạo file tạm trực tiếp
                # outro_clip = None # Không cần biến này nữa

                # Đường dẫn file tạm cho video outro
                outro_temp_path = os.path.join(temp_project_dir, "outro_temp.mp4")

                try:
                    # Kiểm tra các file đầu vào
                    outro_image_path = outro_media_item.get('path')
                    outro_audio_path = outro_audio_info.get('path')
                    outro_duration = outro_audio_info.get('duration', VIDEO_SETTINGS.get("outro_duration", 5)) # Lấy duration từ audio info

                    if outro_media_item.get('type') == 'image' and \
                       outro_image_path and os.path.exists(outro_image_path) and \
                       outro_audio_path and os.path.exists(outro_audio_path) and \
                       outro_duration > 0.1:

                        logger.info(f"Creating temporary video file for Outro (Duration: {outro_duration:.2f}s)...")

                        # Lệnh FFmpeg để tạo video từ ảnh và audio
                        ffmpeg_cmd = [
                            self.ffmpeg_path, "-y",
                            "-loop", "1",                      # Lặp ảnh đầu vào
                            "-i", outro_image_path,           # Ảnh outro
                            "-i", outro_audio_path,           # Audio outro
                            "-t", str(outro_duration),        # Thời lượng mong muốn (theo audio)
                            "-map", "0:v:0",                   # Map video từ input 0 (ảnh)
                            "-map", "1:a:0",                   # Map audio từ input 1 (audio)
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", # Encode video nhanh cho file tạm
                            "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,format=pix_fmts=yuv420p", # Scale/pad và format
                            "-c:a", "aac", "-b:a", "128k",     # Encode audio
                            "-r", str(self.fps),               # Đặt FPS
                            "-shortest",                       # Dừng khi input ngắn nhất kết thúc (là audio do -t)
                            outro_temp_path                    # File output tạm
                        ]

                        # Chạy lệnh FFmpeg
                        process = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=False) # check=False để bắt lỗi stderr

                        # Kiểm tra kết quả
                        if process.returncode == 0 and os.path.exists(outro_temp_path) and os.path.getsize(outro_temp_path) > 1000:
                            # Thêm file tạm vào danh sách để ghép nối sau
                            # Sử dụng key đặc biệt để đảm bảo nó ở cuối cùng khi sắp xếp
                            outro_sort_key = (float('inf'), float('inf'))
                            self.temp_unit_files.append((outro_sort_key, outro_temp_path))
                            logger.info(f"Outro saved to temporary file for concatenation: {outro_temp_path}")
                        else:
                            logger.error(f"Failed to create Outro temporary video using FFmpeg.")
                            logger.error(f"FFmpeg stderr: {process.stderr}") # Log lỗi từ FFmpeg

                    else:
                        # Log lý do không xử lý được
                        if outro_media_item.get('type') != 'image':
                            logger.warning("Outro media is not an image, skipping temporary file creation.")
                        elif not (outro_image_path and os.path.exists(outro_image_path)):
                            logger.warning(f"Outro image path invalid or file missing: {outro_image_path}")
                        elif not (outro_audio_path and os.path.exists(outro_audio_path)):
                            logger.warning(f"Outro audio path invalid or file missing: {outro_audio_path}")
                        elif not outro_duration > 0.1:
                             logger.warning(f"Outro audio duration invalid: {outro_duration}")

                except Exception as e:
                    logger.error(f"Error processing outro and creating temporary file: {e}", exc_info=True)
                    # Không cần đóng `outro_clip` vì không tạo ra nó nữa

            # --- 4. Nối tất cả các Clips (Intro, Units, Outro) ---

            if not self.temp_unit_files:
                logger.error(f"Project {project_id}: No temporary video files were generated to concatenate. Cannot create final video.")
                # Dọn dẹp thư mục tạm
                if VIDEO_SETTINGS.get("cleanup_temp_files", False): shutil.rmtree(temp_project_dir, ignore_errors=True)
                # Đóng các clip đã mở (nếu có) - thường sẽ ít khi có ở bước này nếu chỉ dùng file tạm
                for clip in all_clips_to_close:
                    if clip and not isinstance(clip, str) and hasattr(clip, 'close'):
                        try: clip.close()
                        except: pass
                return None

            logger.info(f"Project {project_id}: Preparing to concatenate {len(self.temp_unit_files)} temporary video files...")

            # Khởi tạo biến cho đường dẫn file trung gian
            intermediate_output_path = os.path.join(temp_project_dir, f"intermediate_{project_id}.mp4")
            ffmpeg_concatenation_successful = False # Cờ để theo dõi thành công

            # ----- BẮT ĐẦU KHỐI TRY CHO CONCATENATE VÀ WRITE -----
            try:
                # --- SẮP XẾP FILE TẠM ĐỂ GHÉP NỐI ---
                # Key sort: Dùng tuple (chapter_num, sub_order)
                # Intro: (0, -2)
                # Chapter 1 Card: (1, -1)
                # Unit 1 (Chap 1): (1, 1)
                # Unit 2 (Chap 1): (1, 2)
                # Chapter 2 Card: (2, -1)
                # Unit 3 (Chap 2): (2, 3)
                # Basic Mode Units (Assume Chapter 0): (0, unit_number)
                # Outro: (float('inf'), float('inf'))
                def sort_key_logic(item):
                    key, path = item # key có thể là int (basic), tuple (advanced), hoặc string ("intro")
                    if key == "intro":
                        return (0, -2) # Intro luôn đứng đầu

                    # Handle outro key explicitly
                    if isinstance(key, tuple) and key == (float('inf'), float('inf')):
                        return key # Outro luôn đứng cuối

                    # Handle advanced mode tuple key (chapter_num, unit_or_card_marker)
                    if isinstance(key, tuple) and len(key) == 2:
                        chap_num, unit_or_card = key
                        # Đảm bảo chapter number là số hợp lệ
                        chap_num = int(chap_num) if isinstance(chap_num, (int, float)) else 0
                        # Đảm bảo unit/card marker là số hợp lệ
                        unit_or_card = int(unit_or_card) if isinstance(unit_or_card, (int, float)) else 0
                        return (chap_num, unit_or_card) # card marker là -1, unit number >= 1

                    # Handle basic mode key (integer unit number)
                    if isinstance(key, int):
                        return (0, key) # Gán vào chapter 0 cho chế độ basic

                    # Fallback cho các key không xác định (đặt trước outro)
                    logger.warning(f"Unknown sort key type encountered: {key}. Placing near end.")
                    return (float('inf') - 1, float('inf') - 1)

                # Thực hiện sắp xếp
                try:
                    sorted_temp_files_info = sorted(self.temp_unit_files, key=sort_key_logic)
                except TypeError as sort_err:
                     logger.error(f"Error sorting temporary files: {sort_err}. Keys: {[k for k, p in self.temp_unit_files]}", exc_info=True)
                     raise Exception("Sorting temporary files failed.") from sort_err

                temp_file_paths = [f[1] for f in sorted_temp_files_info] # Lấy đường dẫn đã sắp xếp

                # Log thứ tự file sẽ ghép
                logger.info(f"Concatenation order ({len(temp_file_paths)} files):")
                for i, file_path in enumerate(temp_file_paths):
                    logger.info(f"  {i+1}: {os.path.basename(file_path)}")

                # --- Sử dụng FFmpeg để ghép nối ---
                if temp_file_paths: # Kiểm tra lại xem có file nào không
                    logger.info(f"Attempting FFmpeg concatenation -> {intermediate_output_path}")
                    ffmpeg_output_path = self.concatenate_videos_with_ffmpeg(
                        temp_file_paths,
                        intermediate_output_path # Lưu vào file trung gian
                    )

                    if ffmpeg_output_path and os.path.exists(ffmpeg_output_path) and os.path.getsize(ffmpeg_output_path) > 10000:
                        logger.info(f"FFmpeg concatenation successful: {ffmpeg_output_path}")
                        ffmpeg_concatenation_successful = True
                        # Không cần mở lại bằng MoviePy ở đây nếu các bước sau cũng dùng FFmpeg
                    else:
                        logger.error("FFmpeg concatenation failed or output file invalid.")
                        # Có thể thử fallback MoviePy ở đây nếu muốn, nhưng sẽ phức tạp hơn
                        # Hiện tại, chúng ta sẽ raise lỗi nếu FFmpeg thất bại
                        raise Exception("FFmpeg concatenation failed.")
                else:
                    logger.error("No valid temporary files found for concatenation after sorting.")
                    raise Exception("No temporary files to concatenate.")

            except Exception as concat_err:
                logger.error(f"Error during video concatenation: {concat_err}", exc_info=True)
                # Dọn dẹp và thoát nếu ghép nối thất bại
                if VIDEO_SETTINGS.get("cleanup_temp_files", False): shutil.rmtree(temp_project_dir, ignore_errors=True)
                # Đóng các clip (nếu có)
                for clip in all_clips_to_close:
                    if clip and not isinstance(clip, str) and hasattr(clip, 'close'):
                        try: clip.close()
                        except: pass
                return None

            # --- Dọn dẹp các file tạm thời (Unit, Card, Intro, Outro temps) sau khi ghép nối thành công ---
            if ffmpeg_concatenation_successful:
                 logger.info("Cleaning up temporary individual clip files...")
                 cleaned_count = 0
                 failed_clean_count = 0
                 for key, temp_file in self.temp_unit_files: # Lặp qua danh sách gốc
                      if temp_file and os.path.exists(temp_file):
                          try:
                              os.remove(temp_file)
                              cleaned_count += 1
                              # logger.debug(f"Removed temporary file: {temp_file}")
                          except Exception as e:
                              failed_clean_count += 1
                              logger.warning(f"Error removing temporary file {temp_file}: {e}")
                 logger.info(f"Cleanup complete: Removed {cleaned_count} temp files, failed to remove {failed_clean_count}.")

                 # Xóa cả file card image gốc nếu là advanced mode
                 if script_mode == 'advanced':
                      logger.info("Cleaning up temporary chapter card images...")
                      img_cleaned_count = 0
                      # Tìm các key của chapter card (marker -1)
                      chapter_card_keys = [k for k, p in self.temp_unit_files if isinstance(k, tuple) and len(k) == 2 and k[1] == -1]
                      for chap_key in chapter_card_keys:
                          chap_num = chap_key[0]
                          card_img_path = os.path.join(temp_project_dir, f"chapter_{chap_num}_card.png")
                          if os.path.exists(card_img_path):
                              try:
                                  os.remove(card_img_path)
                                  img_cleaned_count +=1
                              except Exception as img_e:
                                   logger.warning(f"Could not remove chapter card image {card_img_path}: {img_e}")
                      logger.info(f"Removed {img_cleaned_count} chapter card images.")

            # Ở thời điểm này, intermediate_output_path chứa video đã ghép nối thành công

            # --- 5. Thêm nhạc nền (Áp dụng cho intermediate_output_path) ---

            final_output_with_fx = intermediate_output_path # Mặc định là file trung gian nếu không thêm nhạc/phụ đề

            # Kiểm tra xem file trung gian có tồn tại không trước khi tiếp tục
            if not (intermediate_output_path and os.path.exists(intermediate_output_path) and os.path.getsize(intermediate_output_path) > 1000):
                 logger.error(f"Project {project_id}: Intermediate video file is missing or invalid. Cannot add effects.")
                 # Dọn dẹp thư mục project và thoát
                 if VIDEO_SETTINGS.get("cleanup_temp_files", False): shutil.rmtree(temp_project_dir, ignore_errors=True)
                 return None # Không thể tiếp tục

            # Biến để lưu đường dẫn file cuối cùng thực sự (có thể là intermediate hoặc file có nhạc)
            video_input_for_next_step = intermediate_output_path # File đầu vào cho bước tiếp theo (phụ đề)

            if background_music_path and os.path.exists(background_music_path) and VIDEO_SETTINGS.get("enable_background_music", False):
                logger.info(f"Project {project_id}: Adding background music from: {os.path.basename(background_music_path)}")

                # Đường dẫn file output cuối cùng nếu thêm nhạc thành công
                # Sẽ ghi đè lên output_path gốc được truyền vào hàm create_video
                output_path_with_music = output_path
                music_temp_files_to_clean = [] # Theo dõi file tạm của nhạc

                try:
                    # 1. Tạo file nhạc đã điều chỉnh âm lượng
                    music_file_with_volume = os.path.join(temp_project_dir, f"music_adjusted_volume_{project_id}.mp3")
                    music_temp_files_to_clean.append(music_file_with_volume)
                    volume_cmd = [
                        self.ffmpeg_path, "-y",
                        "-i", background_music_path,
                        "-filter:a", f"volume={self.music_volume}",
                        "-c:a", "libmp3lame", # Sử dụng mp3 cho tương thích rộng
                        "-q:a", "5", # Chất lượng mp3 khá
                        music_file_with_volume
                    ]
                    logger.info(f"Adjusting music volume using FFmpeg...")
                    volume_process = subprocess.run(volume_cmd, capture_output=True, text=True, check=False)
                    if volume_process.returncode != 0 or not os.path.exists(music_file_with_volume) or os.path.getsize(music_file_with_volume) < 1000:
                        logger.error(f"Failed to create adjusted volume music file. FFmpeg stderr: {volume_process.stderr}")
                        raise Exception("Failed to adjust music volume")
                    logger.info(f"Adjusted music volume saved to: {music_file_with_volume}")


                    # 2. Lấy thông tin duration của video và nhạc
                    # Dùng ffprobe để lấy duration chính xác hơn
                    video_duration = self._get_video_duration_ffprobe(intermediate_output_path)
                    music_duration = self._get_video_duration_ffprobe(music_file_with_volume)

                    if video_duration is None or video_duration <= 0:
                        logger.warning("Could not get intermediate video duration via ffprobe, trying MoviePy...")
                        try:
                             with VideoFileClip(intermediate_output_path) as temp_clip: video_duration = temp_clip.duration
                        except Exception as e:
                             logger.error(f"Failed to get video duration with MoviePy too: {e}. Cannot proceed with music looping/mixing accurately.")
                             raise Exception("Failed to determine video duration")

                    if music_duration is None or music_duration <= 0:
                        logger.warning("Could not get adjusted music duration via ffprobe, trying mutagen...")
                        try:
                             audio_info_mutagen = mutagen.mp3.MP3(music_file_with_volume)
                             music_duration = audio_info_mutagen.info.length
                        except Exception as e:
                             logger.error(f"Failed to get music duration with mutagen too: {e}. Cannot proceed with music looping.")
                             raise Exception("Failed to determine music duration")

                    logger.info(f"Video Duration: {video_duration:.2f}s, Adjusted Music Duration: {music_duration:.2f}s")

                    # 3. Tạo file nhạc lặp nếu cần
                    music_file_to_use = music_file_with_volume # Mặc định dùng file đã chỉnh volume
                    looped_music_file = None
                    concat_list_path = None

                    if music_duration > 0 and music_duration < video_duration:
                        looped_music_file = os.path.join(temp_project_dir, f"looped_music_{project_id}.mp3")
                        music_temp_files_to_clean.append(looped_music_file)
                        loops_needed = math.ceil(video_duration / music_duration)
                        logger.info(f"Music duration shorter than video. Creating looped music with {loops_needed} repetitions.")

                        # Tạo file danh sách cho FFmpeg concat demuxer
                        concat_list_path = os.path.join(temp_project_dir, f"music_list_{project_id}.txt")
                        music_temp_files_to_clean.append(concat_list_path)
                        with open(concat_list_path, 'w', encoding='utf-8') as f:
                            abs_music_path = os.path.abspath(music_file_with_volume).replace('\\', '/') # Path tuyệt đối, dùng /
                            for _ in range(loops_needed):
                                # FFmpeg concat cần đường dẫn được escape đúng cách nếu có ký tự đặc biệt
                                # Dùng cách an toàn nhất là path tuyệt đối
                                f.write(f"file '{abs_music_path}'\n")

                        # Lệnh FFmpeg để ghép lặp bản nhạc
                        loop_cmd = [
                            self.ffmpeg_path, "-y",
                            "-f", "concat",
                            "-safe", "0", # Cho phép path tuyệt đối
                            "-i", concat_list_path,
                            "-c", "copy", # Chỉ copy stream nhạc, không re-encode
                            looped_music_file
                        ]
                        logger.info(f"Running FFmpeg concat command for music looping...")
                        loop_process = subprocess.run(loop_cmd, capture_output=True, text=True, check=False)

                        if loop_process.returncode == 0 and os.path.exists(looped_music_file) and os.path.getsize(looped_music_file) > 1000:
                            logger.info(f"Looped music created successfully: {looped_music_file}")
                            music_file_to_use = looped_music_file # Sử dụng file nhạc đã lặp
                        else:
                            logger.warning(f"Failed to create looped music file. Using original adjusted music. FFmpeg stderr: {loop_process.stderr}")
                            # music_file_to_use vẫn là music_file_with_volume

                    # 4. Thêm nhạc nền (đã chỉnh volume, có thể đã lặp) vào video bằng FFmpeg amix
                    logger.info(f"Adding background music ('{os.path.basename(music_file_to_use)}') to video using FFmpeg amix...")

                    # Sử dụng filter amix để trộn audio của video gốc và nhạc nền
                    # duration=first: Độ dài output bằng input đầu tiên (video)
                    # dropout_transition=2: Fade out nhẹ cho input thứ 2 (nhạc nền) nếu nó dài hơn
                    add_music_cmd = [
                        self.ffmpeg_path, "-y",
                        "-i", intermediate_output_path,      # Input 0: Video gốc (đã ghép nối)
                        "-i", music_file_to_use,             # Input 1: Nhạc nền (đã xử lý)
                        "-filter_complex", f"[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]", # Trộn audio
                        "-map", "0:v:0",                      # Map luồng video từ input 0
                        "-map", "[aout]",                     # Map luồng audio đã trộn
                        "-c:v", "copy",                       # Copy luồng video (nhanh)
                        "-c:a", "aac", "-b:a", "192k",        # Encode lại audio hỗn hợp sang AAC
                        "-shortest",                          # Đảm bảo output không dài hơn video gốc
                        output_path_with_music               # File output cuối cùng
                    ]

                    # Chạy lệnh thêm nhạc
                    logger.debug(f"FFmpeg add music command: {' '.join(add_music_cmd)}")
                    add_music_process = subprocess.run(add_music_cmd, capture_output=True, text=True, check=False)

                    # Kiểm tra kết quả
                    if add_music_process.returncode == 0 and os.path.exists(output_path_with_music) and os.path.getsize(output_path_with_music) > 10000:
                        logger.info(f"Successfully created video with background music: {output_path_with_music}")
                        video_input_for_next_step = output_path_with_music  # Cập nhật đường dẫn cho bước phụ đề

                        # Xóa file trung gian nếu tên khác file cuối cùng và việc thêm nhạc thành công
                        if intermediate_output_path != output_path_with_music and os.path.exists(intermediate_output_path):
                            try:
                                os.remove(intermediate_output_path)
                                logger.info(f"Removed intermediate video file (music added): {intermediate_output_path}")
                            except OSError as rm_err:
                                logger.warning(f"Could not remove intermediate video file {intermediate_output_path}: {rm_err}")
                    else:
                        logger.error(f"Failed to add background music using FFmpeg amix. Keeping video without music.")
                        logger.error(f"FFmpeg stderr: {add_music_process.stderr}")
                        # Nếu thất bại, file input cho bước sau vẫn là file trung gian
                        # Đổi tên/copy file trung gian thành file output cuối cùng (nếu tên khác)
                        if intermediate_output_path != output_path:
                             try:
                                 shutil.move(intermediate_output_path, output_path)
                                 logger.info(f"Moved intermediate file to final output path (music failed): {output_path}")
                                 video_input_for_next_step = output_path # Cập nhật input cho bước sau
                             except Exception as move_err:
                                 logger.error(f"Could not move intermediate file after music failure: {move_err}. Keeping intermediate file.")
                                 video_input_for_next_step = intermediate_output_path # Giữ nguyên intermediate
                        else:
                             # Nếu tên giống nhau thì không cần làm gì
                             video_input_for_next_step = intermediate_output_path


                except Exception as music_err:
                    logger.error(f"Error during background music processing: {str(music_err)}", exc_info=True)
                    logger.warning("Proceeding with video without background music.")
                    # Đổi tên/copy file trung gian nếu cần
                    if os.path.exists(intermediate_output_path):
                        if intermediate_output_path != output_path:
                             try:
                                 shutil.move(intermediate_output_path, output_path)
                                 logger.info(f"Moved intermediate file to final output path (music error): {output_path}")
                                 video_input_for_next_step = output_path
                             except Exception as move_err:
                                 logger.error(f"Could not move intermediate file after music error: {move_err}. Keeping intermediate file.")
                                 video_input_for_next_step = intermediate_output_path
                        else:
                             video_input_for_next_step = intermediate_output_path
                    else:
                         video_input_for_next_step = None # Lỗi nghiêm trọng hơn

                finally:
                    # Dọn dẹp các file nhạc tạm thời
                    logger.debug("Cleaning up temporary music files...")
                    for temp_file in music_temp_files_to_clean:
                        if temp_file and os.path.exists(temp_file):
                            try:
                                os.remove(temp_file)
                            except OSError as rm_music_err:
                                logger.warning(f"Could not remove temporary music file {temp_file}: {rm_music_err}")

            else:
                # Trường hợp không bật hoặc không có nhạc nền
                logger.info("Background music disabled or not provided. Using concatenated video directly.")
                # Đổi tên/di chuyển file trung gian thành file output cuối cùng (nếu tên khác)
                if os.path.exists(intermediate_output_path):
                    if intermediate_output_path != output_path:
                         try:
                             shutil.move(intermediate_output_path, output_path)
                             logger.info(f"Moved intermediate file to final output path: {output_path}")
                             video_input_for_next_step = output_path
                         except Exception as move_err:
                             logger.error(f"Could not move intermediate file: {move_err}. Keeping intermediate file.")
                             video_input_for_next_step = intermediate_output_path
                    else:
                         video_input_for_next_step = intermediate_output_path # Đã là đường dẫn cuối
                else:
                     video_input_for_next_step = None # Lỗi nếu file trung gian không tồn tại

            # Cập nhật final_output_with_fx để phản ánh đường dẫn hiện tại (có thể đã có nhạc hoặc chưa)
            final_output_with_fx = video_input_for_next_step

            # --- 6. Thêm phụ đề (Áp dụng cho final_output_with_fx) ---
            final_output_path_final = final_output_with_fx # Đường dẫn mặc định trả về là file từ bước trước

            # Chỉ thêm phụ đề nếu được bật và file video đầu vào hợp lệ
            if VIDEO_SETTINGS.get("enable_subtitles", False) and \
               final_output_with_fx and \
               os.path.exists(final_output_with_fx) and \
               os.path.getsize(final_output_with_fx) > 1000:

                logger.info(f"Project {project_id}: Adding subtitles...")

                # Xác định đường dẫn file audio gốc của các speech units
                # Cần tìm thư mục chứa các file audio của unit
                audio_unit_dir = None
                if audio_map: # audio_map là dict {unit_number: audio_info}
                    # Lấy thông tin của unit đầu tiên để xác định thư mục
                    first_unit_info = next(iter(audio_map.values()), None)
                    if first_unit_info and 'path' in first_unit_info:
                        audio_unit_dir = os.path.dirname(first_unit_info['path'])

                if not audio_unit_dir or not os.path.isdir(audio_unit_dir):
                     logger.error("Could not determine speech unit audio directory. Cannot generate combined audio for subtitles.")
                     # Không thể tiếp tục thêm phụ đề, giữ nguyên file từ bước trước
                     final_output_path_final = final_output_with_fx
                else:
                    # Ghép các file audio unit lại thành 1 file tạm để tạo SRT tổng thể
                    temp_full_audio_path = os.path.join(temp_project_dir, f"combined_audio_{project_id}.mp3")
                    srt_file_path = os.path.join(temp_project_dir, f"subtitles_{project_id}.srt")
                    subtitled_output_path_temp = os.path.join(temp_project_dir, f"output_with_subs_temp_{project_id}.mp4") # File output tạm thời

                    combined_audio_success = False
                    try:
                        logger.info("Combining speech unit audios for subtitle generation...")
                        # Sắp xếp các unit audio theo unit_number
                        sorted_units_info = sorted(audio_map.values(), key=lambda x: x['unit_number'])
                        unit_audio_paths_to_concat = [unit['path'] for unit in sorted_units_info if unit.get('path') and os.path.exists(unit['path'])]

                        if not unit_audio_paths_to_concat:
                            logger.error("No valid speech unit audio files found to combine for subtitles.")
                        else:
                            # Tạo file list cho FFmpeg concat
                            concat_audio_list_path = os.path.join(temp_project_dir, f"audio_list_{project_id}.txt")
                            with open(concat_audio_list_path, 'w', encoding='utf-8') as f:
                                for audio_file in unit_audio_paths_to_concat:
                                    f.write(f"file '{os.path.abspath(audio_file).replace('\\', '/')}'\n")

                            # Lệnh FFmpeg để ghép nối audio
                            concat_audio_cmd = [
                                self.ffmpeg_path, "-y",
                                "-f", "concat",
                                "-safe", "0",
                                "-i", concat_audio_list_path,
                                "-c", "copy", # Copy không cần re-encode
                                temp_full_audio_path
                            ]
                            concat_audio_process = subprocess.run(concat_audio_cmd, capture_output=True, text=True, check=False)

                            # Dọn dẹp file list ngay lập tức
                            if os.path.exists(concat_audio_list_path):
                                try: os.remove(concat_audio_list_path)
                                except OSError: pass

                            if concat_audio_process.returncode == 0 and os.path.exists(temp_full_audio_path) and os.path.getsize(temp_full_audio_path) > 100:
                                logger.info(f"Successfully combined audio for subtitles: {temp_full_audio_path}")
                                combined_audio_success = True
                            else:
                                logger.error(f"Failed to combine audio for subtitles. FFmpeg stderr: {concat_audio_process.stderr}")

                    except Exception as e:
                        logger.error(f"Error combining audio for subtitles: {e}", exc_info=True)

                    # Nếu tạo audio tổng hợp thành công, tiến hành tạo SRT và thêm vào video
                    if combined_audio_success:
                        subtitle_generation_success = False
                        try:
                            # Gọi hàm tạo SRT (hàm này đã bao gồm fallback faster-whisper -> whisper)
                            generated_srt = self.generate_subtitles_with_whisper(
                                temp_full_audio_path,
                                srt_file_path,
                                model=VIDEO_SETTINGS.get("subtitle_whisper_model", "base"),
                                language=language # Sử dụng ngôn ngữ từ script
                            )

                            if generated_srt and os.path.exists(generated_srt) and os.path.getsize(generated_srt) > 0:
                                logger.info(f"Successfully generated subtitles file: {srt_file_path}")
                                subtitle_generation_success = True
                            else:
                                logger.error("Failed to generate subtitles file (SRT).")

                        except Exception as srt_e:
                            logger.error(f"Error generating subtitles file (SRT): {srt_e}", exc_info=True)

                        # Nếu tạo SRT thành công, thêm vào video bằng FFmpeg
                        if subtitle_generation_success:
                            logger.info(f"Burning subtitles into video: {final_output_with_fx} -> {subtitled_output_path_temp}")
                            try:
                                # Chuẩn bị đường dẫn SRT cho FFmpeg (cần escape ký tự đặc biệt)
                                # Trên Windows, FFmpeg cần escape dấu hai chấm và backslash
                                if os.name == 'nt':
                                    srt_path_escaped = srt_file_path.replace('\\', '\\\\').replace(':', '\\:')
                                else: # Linux/macOS
                                    # Thường chỉ cần escape ký tự đặc biệt như ':', ',', '[', ']'
                                    # Cách an toàn là đặt trong dấu nháy đơn nếu shell không tự xử lý
                                    # Tuy nhiên, khi gọi từ subprocess, không cần quote shell, chỉ cần escape
                                    srt_path_escaped = srt_file_path.replace("'", "\\'") # Escape dấu nháy đơn nếu có

                                # Lấy subtitle style từ settings
                                subtitle_style_string = VIDEO_SETTINGS.get("subtitle_style", "Alignment=2,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=1")
                                font_size = VIDEO_SETTINGS.get("subtitle_font_size", 24)
                                subtitle_vf = f"subtitles='{srt_path_escaped}':force_style='FontSize={font_size},{subtitle_style_string}'"

                                add_subs_cmd = [
                                    self.ffmpeg_path, "-y",
                                    "-i", final_output_with_fx,   # Video đầu vào (có thể đã có nhạc)
                                    "-vf", subtitle_vf,           # Filter để burn subtitle
                                    "-c:a", "copy",               # Copy luồng audio gốc
                                    "-c:v", "libx264", "-crf", "23", "-preset", "medium", # Encode lại video với subs
                                    "-pix_fmt", "yuv420p",
                                    subtitled_output_path_temp    # File output tạm thời
                                ]

                                logger.debug(f"FFmpeg add subtitles command: {' '.join(add_subs_cmd)}")
                                subs_process = subprocess.run(add_subs_cmd, capture_output=True, text=True, check=False)

                                if subs_process.returncode == 0 and os.path.exists(subtitled_output_path_temp) and os.path.getsize(subtitled_output_path_temp) > 10000:
                                    logger.info(f"Successfully added subtitles to temporary video: {subtitled_output_path_temp}")

                                    # Xóa file gốc không có phụ đề
                                    original_file_to_delete = final_output_with_fx
                                    try:
                                        if os.path.exists(original_file_to_delete):
                                            time.sleep(1)
                                            os.remove(original_file_to_delete)
                                            logger.info(f"Removed original video without subtitles: {original_file_to_delete}")
                                    except OSError as rm_err:
                                        logger.warning(f"Could not remove original file before subtitle rename ({original_file_to_delete}): {rm_err}")

                                    # Đổi tên file tạm thành file output cuối cùng
                                    final_target_path = output_path # Đường dẫn cuối cùng mong muốn
                                    try:
                                        shutil.move(subtitled_output_path_temp, final_target_path)
                                        final_output_path_final = final_target_path # Cập nhật đường dẫn trả về
                                        logger.info(f"Renamed subtitled video to final path: {final_output_path_final}")
                                    except OSError as mv_err:
                                        logger.error(f"Could not rename subtitled video to {final_target_path}: {mv_err}. Keeping temp subtitled file: {subtitled_output_path_temp}")
                                        final_output_path_final = subtitled_output_path_temp # Trả về file tạm nếu không đổi tên được

                                else:
                                    logger.error("Failed to add subtitles using FFmpeg.")
                                    logger.error(f"FFmpeg stderr: {subs_process.stderr}")
                                    # Giữ nguyên file từ bước trước (có thể có nhạc hoặc không)
                                    final_output_path_final = final_output_with_fx

                            except Exception as burn_err:
                                logger.error(f"Error burning subtitles into video: {burn_err}", exc_info=True)
                                final_output_path_final = final_output_with_fx # Giữ nguyên file gốc
                        else:
                             # Giữ nguyên file từ bước trước nếu tạo SRT thất bại
                             final_output_path_final = final_output_with_fx
                    else:
                         # Giữ nguyên file từ bước trước nếu không tạo được audio tổng hợp
                         final_output_path_final = final_output_with_fx

                    # Dọn dẹp file audio tổng hợp và SRT tạm
                    for temp_sub_file in [temp_full_audio_path, srt_file_path]:
                        if temp_sub_file and os.path.exists(temp_sub_file):
                            try:
                                os.remove(temp_sub_file)
                                # logger.debug(f"Removed temporary subtitle file: {temp_sub_file}")
                            except OSError: pass

            else:
                logger.info("Subtitles disabled in settings or input video invalid. Skipping subtitle step.")
                # Đường dẫn trả về cuối cùng không đổi
                final_output_path_final = final_output_with_fx


            # --- 7. Dọn dẹp cuối cùng --- (Phần này nên đặt sau cả bước 5 và 6)
            logger.debug(f"Final cleanup stage for project {project_id}...")
            # ... (Giữ nguyên logic đóng clips và xóa temp_project_dir) ...
            # Đóng tất cả các clip đã được quản lý (ít clip MoviePy hơn trong luồng này)
            closed_count = 0
            for clip in all_clips_to_close:
                if clip and not isinstance(clip, str) and hasattr(clip, 'close') and callable(clip.close):
                    try:
                        # logger.debug(f"  Closing final tracked clip: {type(clip)}")
                        clip.close()
                        closed_count += 1
                    except Exception as close_err:
                        if "AttributeError: 'NoneType'" not in str(close_err):
                            logger.warning(f"Error closing a tracked clip during final cleanup: {close_err}")
            logger.debug(f"Closed {closed_count} tracked MoviePy clips during final cleanup.")

            # Xóa thư mục tạm của project
            if VIDEO_SETTINGS.get("cleanup_temp_files", True):
                try:
                    logger.info(f"Cleaning up temporary project directory: {temp_project_dir}")
                    # Đợi một chút trước khi xóa để đảm bảo file không còn bị khóa
                    time.sleep(1)
                    shutil.rmtree(temp_project_dir, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Error during final temp directory cleanup: {str(e)}")

            logger.info(f"=== Video Creation Finished for Project: {project_id} ===")

            # Kiểm tra file cuối cùng trước khi trả về
            if final_output_path_final and os.path.exists(final_output_path_final) and os.path.getsize(final_output_path_final) > 10000:
                logger.info(f"Final video saved to: {final_output_path_final}")
                return final_output_path_final
            else:
                logger.error(f"Final output file is missing or invalid: {final_output_path_final}")
                # Thử tìm file output khác có thể sử dụng được (ít khả năng xảy ra nếu logic đúng)
                potential_outputs = [
                    final_output_with_fx, # File trước khi thêm sub
                    intermediate_output_path, # File trước khi thêm nhạc/sub
                    output_path # Đường dẫn gốc mong muốn
                ]
                for potential_path in potential_outputs:
                    if potential_path and os.path.exists(potential_path) and os.path.getsize(potential_path) > 10000:
                        logger.warning(f"Returning best available output path: {potential_path}")
                        return potential_path

                logger.error("No valid output file found to return.")
                return None

    def concatenate_videos_with_ffmpeg(self, video_files, output_path):
        """Sử dụng FFmpeg để ghép nối các file video trực tiếp."""
        # Kiểm tra đầu vào
        if not video_files:
            logger.error("Không có file video nào để ghép nối")
            return None
        
        # Lọc các file tồn tại
        valid_video_files = [f for f in video_files if os.path.exists(f) and os.path.getsize(f) > 10000]
        if not valid_video_files:
            logger.error("Không có file video hợp lệ để ghép nối")
            return None
        
        logger.info(f"Ghép nối {len(valid_video_files)} file video với FFmpeg")
        
        # In thông tin chi tiết từng file để debug
        for idx, file_path in enumerate(valid_video_files):
            try:
                duration = self._get_video_duration_ffprobe(file_path) or "Unknown"
                file_size = os.path.getsize(file_path) / (1024*1024)  # Convert to MB
                logger.info(f"  File {idx+1}: {os.path.basename(file_path)}, Duration: {duration}s, Size: {file_size:.2f}MB")
            except Exception as e:
                logger.warning(f"  File {idx+1}: {os.path.basename(file_path)}, Error getting info: {e}")
        
        # Tạo file danh sách tạm thời
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            temp_list_path = f.name
            for video_file in valid_video_files:
                f.write(f"file '{os.path.abspath(video_file)}'\n")
            
            # Đảm bảo dữ liệu được ghi đĩa trước khi đóng file
            f.flush()
            os.fsync(f.fileno())
        
        # Log nội dung file danh sách để debug
        try:
            with open(temp_list_path, 'r') as f:
                list_content = f.read()
                logger.debug(f"Content of temp list file:\n{list_content}")
        except Exception as e:
            logger.warning(f"Error reading temp list file: {e}")
        
        # Lệnh FFmpeg để ghép nối
        cmd = [
            self.ffmpeg_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", temp_list_path,
            "-c", "copy",  # Copy không cần re-encode
            output_path
        ]
        
        logger.info(f"Câu lệnh FFmpeg: {' '.join(cmd)}")
        try:
            # Sử dụng subprocess.PIPE để lấy log đầy đủ
            process = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            stdout_output = process.stdout.decode('utf-8', errors='ignore')
            stderr_output = process.stderr.decode('utf-8', errors='ignore')
            
            if stdout_output:
                logger.debug(f"FFmpeg stdout: {stdout_output}")
            
            if stderr_output:
                if 'Error' in stderr_output:
                    logger.error(f"FFmpeg stderr: {stderr_output}")
                else:
                    logger.debug(f"FFmpeg stderr: {stderr_output}")
            
            os.remove(temp_list_path)  # Dọn dẹp file tạm
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                logger.info(f"Ghép nối video thành công với FFmpeg: {output_path}")
                return output_path
            else:
                logger.error(f"FFmpeg concat tạo ra file output không hợp lệ hoặc quá nhỏ: {os.path.getsize(output_path) if os.path.exists(output_path) else 'File không tồn tại'}")
                return None
        except Exception as e:
            logger.error(f"Lỗi khi ghép nối với FFmpeg: {e}")
            if os.path.exists(temp_list_path):
                try:
                    os.remove(temp_list_path)
                except:
                    pass
            return None

    def _create_speech_unit_video_sequence_direct(self, speech_unit, audio_info, visual_items, temp_dir, language='en'):
        """
        Tạo một VideoClip duy nhất cho một speech_unit sử dụng FFmpeg trực tiếp.
        """
        unit_number = speech_unit['unit_number']
        audio_path = audio_info['path']
        audio_duration = audio_info['duration']
        num_visuals = len(visual_items)

        if audio_duration <= 0 or num_visuals == 0:
            logger.warning(f"Speech Unit {unit_number}: Invalid audio duration ({audio_duration}s) or no visuals ({num_visuals}). Skipping.")
            return None

        logger.info(f"--- Creating sequence for Speech Unit {unit_number} using FFmpeg directly (Audio: {audio_duration:.2f}s) ---")

        # --- 1. Tính toán thời lượng chính xác cho từng Shot ---
        word_timestamps = self.get_word_timestamps(audio_path, model_name=VIDEO_SETTINGS.get("subtitle_whisper_model", "base"), language=language)

        timed_visual_items = None
        use_fallback_timing = True

        if word_timestamps:
            try:
                # Truyền thêm audio_duration để giúp kiểm tra tính hợp lý của kết quả
                timed_visual_items = self._calculate_precise_shot_durations(
                    visual_items, 
                    word_timestamps,
                    audio_duration=audio_duration
                )
                
                if timed_visual_items:
                    use_fallback_timing = False
                    total_calculated_vis_duration = sum(item['calculated_duration'] for item in timed_visual_items)
                    logger.info(f"Unit {unit_number}: Precise durations calculated. Total visual time: {total_calculated_vis_duration:.3f}s (Audio: {audio_duration:.3f}s)")
                    
                    # Thêm kiểm tra để đảm bảo tổng thời lượng hợp lý
                    if total_calculated_vis_duration < audio_duration * 0.8:
                        logger.warning(f"Unit {unit_number}: Calculated duration too short compared to audio ({total_calculated_vis_duration:.3f}s vs {audio_duration:.3f}s). Falling back.")
                        use_fallback_timing = True
                        timed_visual_items = None
                else:
                    logger.warning(f"Unit {unit_number}: Failed to calculate precise durations. Falling back.")
            except Exception as calc_e:
                logger.error(f"Unit {unit_number}: Error calculating precise durations: {calc_e}. Falling back.", exc_info=True)
        else:
            logger.warning(f"Unit {unit_number}: Word alignment failed. Falling back.")

        # --- 2. Tính toán thời gian Fallback (nếu cần) ---
# --- 2. Tính toán thời gian Fallback (nếu cần) ---
        if use_fallback_timing:
            logger.info(f"Using fallback timing for Unit {unit_number} (Audio: {audio_duration:.3f}s, Visuals: {num_visuals})")
            
            # Đảm bảo mỗi cảnh có thời lượng tối thiểu
            min_duration_per_shot = max(1.0, audio_duration * 0.1)  # Tối thiểu 1 giây hoặc 10% audio
            
            # Cách phân phối thời gian hợp lý hơn
            if num_visuals > 0:
                # Nếu có ít cảnh, phân phối đều
                if num_visuals <= 3:
                    avg_visual_duration = audio_duration / num_visuals
                # Nếu có nhiều cảnh, phân phối theo quy luật: càng về sau càng ngắn lại
                else:
                    # Tính tổng số phần cần chia theo dãy 1/n
                    total_parts = sum(1/(i+1) for i in range(num_visuals))
                    # Tạo list các duration theo tỉ lệ giảm dần
                    durations = [audio_duration * (1/(i+1)) / total_parts for i in range(num_visuals)]
                    # Đảm bảo tổng duration bằng đúng audio_duration
                    durations = [d * (audio_duration / sum(durations)) for d in durations]
                    
                    # Đưa kết quả vào timed_visual_items
                    timed_visual_items = []
                    for i, item in enumerate(visual_items):
                        timed_visual_items.append({
                            **item, 
                            'calculated_duration': max(min_duration_per_shot, durations[i]),
                            'start_time': -1, 
                            'end_time': -1
                        })
                    
                    # Kiểm tra và điều chỉnh để đảm bảo tổng duration chính xác
                    total_duration = sum(item['calculated_duration'] for item in timed_visual_items)
                    if abs(total_duration - audio_duration) > 0.1:
                        # Điều chỉnh duration cảnh cuối cùng nếu cần
                        last_item = timed_visual_items[-1]
                        last_item['calculated_duration'] += (audio_duration - total_duration)
                        last_item['calculated_duration'] = max(min_duration_per_shot, last_item['calculated_duration'])
                        
                    logger.info(f"Fallback: Progressive duration distribution. Total: {sum(item['calculated_duration'] for item in timed_visual_items):.3f}s")
                    
                    # Kết thúc sớm nếu đã xử lý phân phối theo quy luật
                    if timed_visual_items:
                        # Log thông tin để debug
                        for i, item in enumerate(timed_visual_items):
                            logger.debug(f"Scene {item.get('number')}: {item['calculated_duration']:.3f}s")
                            
                        if sum(item['calculated_duration'] for item in timed_visual_items) < audio_duration * 0.95:
                            logger.warning(f"Fallback duration sum ({sum(item['calculated_duration'] for item in timed_visual_items):.3f}s) less than audio ({audio_duration:.3f}s)")
                            
                        return timed_visual_items  # Trả về kết quả phân phối theo quy luật
            
            # Nếu chưa thoát sớm (khi number of visuals ≤ 3), tiếp tục với phân phối đều
            avg_visual_duration = audio_duration / num_visuals if num_visuals > 0 else 0
            logger.info(f"Unit {unit_number}: Using even fallback visual duration: {avg_visual_duration:.3f}s")
            timed_visual_items = [{**item, 'calculated_duration': avg_visual_duration, 'start_time': -1, 'end_time': -1} for item in visual_items]
            
            # Đảm bảo không có thời lượng âm hoặc quá ngắn
            if avg_visual_duration < min_duration_per_shot:
                logger.warning(f"Unit {unit_number}: Calculated duration too short. Setting minimum {min_duration_per_shot:.2f}s per scene.")
                # Lựa chọn ngẫu nhiên số cảnh cần hiển thị
                max_scenes_possible = int(audio_duration / min_duration_per_shot)
                if max_scenes_possible < num_visuals:
                    logger.warning(f"Not enough time to show all {num_visuals} scenes with min duration. Showing {max_scenes_possible} scenes.")
                    # Chọn ngẫu nhiên max_scenes_possible cảnh để hiển thị
                    import random
                    selected_indices = sorted(random.sample(range(num_visuals), max_scenes_possible))
                    selected_items = [visual_items[i] for i in selected_indices]
                    even_duration = audio_duration / max_scenes_possible
                    timed_visual_items = [{**item, 'calculated_duration': even_duration, 'start_time': -1, 'end_time': -1} for item in selected_items]
                else:
                    # Tất cả cảnh đều có thời lượng tối thiểu
                    for item in timed_visual_items:
                        item['calculated_duration'] = min_duration_per_shot

        # --- 3. Tạo các clip scene/shot và lưu vào file tạm ---
        scene_video_files = []
        
        for i, item_with_timing in enumerate(timed_visual_items):
            media_path = item_with_timing['path']
            media_type = item_with_timing.get('type', 'image')
            scene_num_for_media = item_with_timing.get('number', f'unit{unit_number}_item{i+1}')
            target_shot_duration = item_with_timing['calculated_duration']

            if target_shot_duration < 0.1:
                logger.warning(f"Unit {unit_number} Scene {scene_num_for_media}: Skipping shot with very short duration ({target_shot_duration:.3f}s).")
                continue

            scene_temp_path = os.path.join(temp_dir, f"unit{unit_number}_scene{scene_num_for_media}_direct.mp4")
            logger.debug(f"Processing Unit {unit_number} Scene {scene_num_for_media} ({media_type}), Target Duration: {target_shot_duration:.3f}s")

            try:
                if media_type == 'image':
                    # Tạo video từ ảnh sử dụng FFmpeg trực tiếp
                    animation_type = VIDEO_SETTINGS.get("image_animation", "none")
                    intensity = VIDEO_SETTINGS.get("animation_intensity", 0.02)
                    total_frames = int(self.fps * target_shot_duration)
                    vf_filter = ""
                    
                    if animation_type == "zoom" and total_frames > self.fps / 2:
                        # Sử dụng cách tạo zoom từ code tham khảo - cách này đơn giản nhưng hiệu quả
                        vf_filter = f"zoompan=z='1+({intensity}*on/{total_frames})':d={total_frames}:s={self.width}x{self.height}:fps={self.fps},setsar=1"
                        logger.info(f"Scene {scene_num_for_media}: Applying linear zoom effect to image.")
                    else:
                        vf_filter = f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
                        if animation_type != "none":
                            logger.warning(f"Scene {scene_num_for_media}: Invalid image duration or animation type '{animation_type}'. Using static image.")
                        else:
                            logger.info(f"Scene {scene_num_for_media}: Using static image (no animation).")

                    image_cmd = [
                        self.ffmpeg_path, "-y",
                        "-loop", "1", "-i", media_path,
                        "-t", str(target_shot_duration),
                        "-vf", vf_filter,
                        "-c:v", "libx264", "-crf", "23", "-preset", "medium",  # Changed preset from "veryfast" to "medium" for better quality
                        "-pix_fmt", "yuv420p", "-r", str(self.fps), "-an",
                        scene_temp_path
                    ]
                    logger.info(f"Creating video from image command: {' '.join(image_cmd)}")
                    subprocess.run(image_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

                elif media_type == 'video':
                    # Xử lý video - cắt hoặc lặp lại để đạt được target_shot_duration
                    source_duration = self._get_video_duration_ffprobe(media_path) or 0
                    
                    if source_duration <= 0:
                        # Thử dùng moviepy để lấy duration nếu ffprobe thất bại
                        try:
                            with VideoFileClip(media_path) as clip:
                                source_duration = clip.duration
                        except:
                            source_duration = 0
                    
                    if source_duration <= 0:
                        logger.warning(f"Cannot determine source video duration. Using fallback black clip.")
                        # Tạo video đen
                        black_cmd = [
                            self.ffmpeg_path, "-y",
                            "-f", "lavfi", "-i", f"color=c=black:s={self.width}x{self.height}:r={self.fps}",
                            "-t", str(target_shot_duration),
                            "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                            scene_temp_path
                        ]
                        subprocess.run(black_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    elif source_duration <= target_shot_duration:
                        # Video gốc ngắn hơn thời lượng cần thiết - dùng toàn bộ
                        # Có thể loop nếu cần
                        shutil.copy(media_path, scene_temp_path)
                    else:
                        # Video gốc dài hơn - cắt một đoạn ngẫu nhiên
                        import random
                        start_time = random.uniform(0, source_duration - target_shot_duration)
                        video_cmd = [
                            self.ffmpeg_path, "-y",
                            "-ss", str(start_time),
                            "-i", media_path,
                            "-t", str(target_shot_duration),
                            "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
                            "-pix_fmt", "yuv420p", "-r", str(self.fps), "-an",
                            scene_temp_path
                        ]
                        subprocess.run(video_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

                # Kiểm tra file kết quả
                if os.path.exists(scene_temp_path) and os.path.getsize(scene_temp_path) > 10000:
                    scene_video_files.append(scene_temp_path)
                    logger.debug(f"Created scene video: {scene_temp_path}")
                else:
                    logger.warning(f"Failed to create scene video or file too small: {scene_temp_path}")
                    
            except Exception as e:
                logger.error(f"Error processing media for Scene {scene_num_for_media}: {e}", exc_info=True)
                # Tạo video đen khi có lỗi
                try:
                    black_cmd = [
                        self.ffmpeg_path, "-y",
                        "-f", "lavfi", "-i", f"color=c=black:s={self.width}x{self.height}:r={self.fps}",
                        "-t", str(target_shot_duration),
                        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        scene_temp_path
                    ]
                    subprocess.run(black_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    if os.path.exists(scene_temp_path) and os.path.getsize(scene_temp_path) > 10000:
                        scene_video_files.append(scene_temp_path)
                except:
                    logger.error("Failed to create fallback black video.")

        # --- 4. Ghép nối các video scene bằng FFmpeg ---
        if not scene_video_files:
            logger.error(f"Unit {unit_number}: No scene videos were created. Cannot proceed.")
            return None
        
        # Đường dẫn file video unit (chưa có audio)
        unit_video_path = os.path.join(temp_dir, f"unit{unit_number}_video.mp4")
        
        # Ghép nối các scene video
        logger.info(f"Unit {unit_number}: Concatenating {len(scene_video_files)} scene videos...")
        concat_result = self.concatenate_videos_with_ffmpeg(scene_video_files, unit_video_path)
        
        if not concat_result or not os.path.exists(unit_video_path):
            logger.error(f"Unit {unit_number}: Failed to concatenate scene videos.")
            return None
        
        # --- 5. Thêm audio vào video unit, với điều chỉnh tốc độ nếu cần ---
        unit_with_audio_path = os.path.join(temp_dir, f"unit{unit_number}_final.mp4")
        adjusted_video_path = os.path.join(temp_dir, f"unit{unit_number}_speed_adjusted.mp4")
        
        try:
            # Lấy duration của video đã ghép nối
            video_duration = self._get_video_duration_ffprobe(unit_video_path) 
            if not video_duration:
                # Fallback nếu ffprobe thất bại
                with VideoFileClip(unit_video_path) as clip:
                    video_duration = clip.duration
            
            # Kiểm tra xem có cần điều chỉnh tốc độ không
            allowed_diff = max(0.05, audio_duration * 0.01)
            adjust_speed = False
            
            if abs(video_duration - audio_duration) > allowed_diff:
                speed_factor = video_duration / audio_duration
                ptsFactor = 1/speed_factor  # setpts = 1/speed
                
                # Chỉ điều chỉnh nếu hệ số nằm trong khoảng hợp lý
                if 0.5 <= speed_factor <= 2.0:
                    adjust_speed = True
                    logger.warning(f"Unit {unit_number}: Adjusting video speed by factor {speed_factor:.4f} (setpts={ptsFactor:.4f}) to match audio")
                    
                    # Điều chỉnh tốc độ bằng FFmpeg
                    speed_cmd = [
                        self.ffmpeg_path, "-y",
                        "-i", unit_video_path,
                        "-filter:v", f"setpts={ptsFactor}*PTS",
                        "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                        "-pix_fmt", "yuv420p",
                        adjusted_video_path
                    ]
                    
                    # Thực thi lệnh FFmpeg để điều chỉnh tốc độ
                    try:
                        subprocess.run(speed_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                        if os.path.exists(adjusted_video_path) and os.path.getsize(adjusted_video_path) > 10000:
                            logger.info(f"Unit {unit_number}: Successfully adjusted video speed")
                            # Sử dụng video đã điều chỉnh tốc độ cho bước tiếp theo
                            unit_video_path = adjusted_video_path
                        else:
                            logger.warning(f"Unit {unit_number}: Failed to adjust video speed, using original video")
                            adjust_speed = False
                    except Exception as e:
                        logger.error(f"Unit {unit_number}: Error adjusting video speed: {e}")
                        adjust_speed = False
                else:
                    logger.warning(f"Unit {unit_number}: Speed factor {speed_factor:.4f} out of reasonable range (0.5 to 2.0), skipping speed adjustment")
            
            # Thêm audio vào video (có hoặc không điều chỉnh tốc độ)
            add_audio_cmd = [
                self.ffmpeg_path, "-y",
                "-i", unit_video_path,
                "-i", audio_path,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                unit_with_audio_path
            ]
            
            logger.info(f"Unit {unit_number}: Adding audio to video...")
            process = subprocess.run(add_audio_cmd, capture_output=True, text=True)
            
            if process.returncode != 0:
                logger.error(f"FFmpeg error: {process.stderr}")
                # Thử phương pháp đơn giản hơn nếu cách trên thất bại
                simple_cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", unit_video_path,
                    "-i", audio_path,
                    "-c", "copy",
                    "-shortest",
                    unit_with_audio_path
                ]
                logger.info("Trying simplified FFmpeg command...")
                process = subprocess.run(simple_cmd, capture_output=True, text=True)
                
                if process.returncode != 0:
                    logger.error(f"Simplified FFmpeg command also failed: {process.stderr}")
                    raise Exception("Failed to add audio to video")
            
            if os.path.exists(unit_with_audio_path) and os.path.getsize(unit_with_audio_path) > 10000:
                logger.info(f"Unit {unit_number}: Successfully created unit video with audio: {unit_with_audio_path}")
                
                # Mở với MoviePy để tương thích với phần còn lại của code
                final_unit_clip = VideoFileClip(unit_with_audio_path)
                return final_unit_clip
            else:
                logger.error(f"Unit {unit_number}: Failed to create valid output file")
                return None
        
        except Exception as e:
            logger.error(f"Unit {unit_number}: Error processing video: {e}", exc_info=True)
            
            # Phương pháp dự phòng với MoviePy
            try:
                logger.info("Trying MoviePy as fallback for audio addition and speed adjustment...")
                video_clip = VideoFileClip(unit_video_path)
                audio_clip = AudioFileClip(audio_path)
                
                # Điều chỉnh tốc độ nếu cần
                if abs(video_clip.duration - audio_clip.duration) > allowed_diff:
                    speed_factor = video_clip.duration / audio_clip.duration
                    if 0.5 <= speed_factor <= 2.0:
                        logger.info(f"MoviePy fallback: adjusting speed by factor {speed_factor:.4f}")
                        video_clip = video_clip.with_fps(self.fps).fx(MultiplySpeed, speed_factor)
                
                # Cắt để khớp độ dài nếu cần
                min_duration = min(video_clip.duration, audio_clip.duration)
                video_clip = video_clip.subclipped(0, min_duration)
                audio_clip = audio_clip.subclipped(0, min_duration)
                
                # Thêm audio
                final_clip = video_clip.with_audio(audio_clip)
                final_clip.write_videofile(
                    unit_with_audio_path,
                    codec='libx264', audio_codec='aac',
                    temp_audiofile=os.path.join(temp_dir, f'temp-unit-{unit_number}-audio.m4a'),
                    remove_temp=True, fps=self.fps, preset="medium",
                    threads=os.cpu_count() or 4, logger=None,
                    ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"]
                )
                
                # Đóng clip
                video_clip.close()
                audio_clip.close()
                
                if os.path.exists(unit_with_audio_path) and os.path.getsize(unit_with_audio_path) > 10000:
                    logger.info(f"Unit {unit_number}: Successfully created unit video using MoviePy fallback")
                    return VideoFileClip(unit_with_audio_path)
                else:
                    logger.error("MoviePy fallback also failed")
                    return None
            except Exception as mp_err:
                logger.error(f"MoviePy fallback also failed: {mp_err}")
                return None
        
        finally:
            # Dọn dẹp các file tạm
            for scene_file in scene_video_files:
                try:
                    if os.path.exists(scene_file):
                        os.remove(scene_file)
                except:
                    pass
            
            if os.path.exists(unit_video_path) and unit_video_path != adjusted_video_path:
                try:
                    os.remove(unit_video_path)
                except:
                    pass
            
            if 'adjusted_video_path' in locals() and os.path.exists(adjusted_video_path) and adjusted_video_path != unit_with_audio_path:
                try:
                    os.remove(adjusted_video_path)
                except:
                    pass

    def add_subtitles_to_video_ffmpeg(self, video_path, audio_path_for_srt, output_path):
        """
        Sử dụng FFmpeg để thêm phụ đề vào video từ file audio.
        
        Args:
            video_path (str): Đường dẫn đến video đầu vào
            audio_path_for_srt (str): Đường dẫn đến file audio để tạo SRT
            output_path (str): Đường dẫn đến video đầu ra với phụ đề
            
        Returns:
            str: Đường dẫn đến video đã thêm phụ đề hoặc None nếu thất bại
        """
        if not os.path.exists(video_path):
            logger.error(f"Video file doesn't exist: {video_path}")
            return None
            
        if not os.path.exists(audio_path_for_srt):
            logger.error(f"Audio file for subtitles doesn't exist: {audio_path_for_srt}")
            return None
        
        # Lưu trữ đường dẫn tuyệt đối của ffmpeg
        ffmpeg_absolute_path = os.path.abspath(self.ffmpeg_path)
        
        # Tạo thư mục tạm
        temp_dir = os.path.join(self.temp_dir, f"subs_temp_{int(time.time())}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Tạo SRT từ audio
        srt_path = os.path.join(temp_dir, "subtitles.srt")
        try:
            srt_file = self.generate_subtitles_with_whisper(
                audio_path_for_srt,
                srt_path,
                model=VIDEO_SETTINGS.get("subtitle_whisper_model", "base"),
                language=VIDEO_SETTINGS.get("subtitle_language", "en")
            )
            
            if not srt_file or not os.path.exists(srt_file):
                logger.error("Failed to generate subtitles")
                return None
                
            # Sao chép video vào thư mục tạm 
            temp_video_path = os.path.join(temp_dir, "input_video.mp4")
            try:
                shutil.copy(video_path, temp_video_path)
                logger.info(f"Copied video to temp directory")
            except Exception as e:
                logger.error(f"Failed to copy video to temp directory: {e}")
                return None
            
            # Sử dụng phương pháp batch file
            try:
                # Đảm bảo chúng ta đang ở trong thư mục tạm
                current_dir = os.getcwd()
                
                # Tạo file batch để chạy FFmpeg
                batch_file = os.path.join(temp_dir, "add_subs.bat")
                
                with open(batch_file, 'w', encoding='utf-8') as f:
                    f.write('@echo off\n')
                    # Sử dụng đường dẫn tuyệt đối cho FFmpeg
                    f.write(f'"{ffmpeg_absolute_path}" -y -i input_video.mp4 -vf "subtitles=subtitles.srt:force_style=\'FontSize=24,Alignment=2\'" -c:a copy output_video.mp4\n')
                    f.write('exit /b %errorlevel%\n')
                
                # Chạy batch file từ thư mục tạm
                os.chdir(temp_dir)
                logger.info(f"Running batch file for subtitles")
                batch_process = subprocess.run("add_subs.bat", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                # Quay lại thư mục gốc
                os.chdir(current_dir)
                
                # Kiểm tra kết quả
                temp_output_path = os.path.join(temp_dir, "output_video.mp4")
                if os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 10000:
                    # Sao chép trở lại file đầu ra
                    shutil.copy(temp_output_path, output_path)
                    logger.info(f"Successfully added subtitles to video: {output_path}")
                    return output_path
                else:
                    stderr = batch_process.stderr.decode('utf-8', errors='ignore')
                    logger.error(f"Batch execution error: {stderr}")
                    logger.error("Failed to create output with subtitles")
                    return None
                    
            except Exception as e:
                logger.error(f"Error running batch file: {e}", exc_info=True)
                return None
                
        except Exception as e:
            logger.error(f"Error adding subtitles to video: {e}", exc_info=True)
            return None
        finally:
            # Dọn dẹp thư mục tạm
            try:
                if os.path.exists(temp_dir):
                    # Đợi một chút để đảm bảo tất cả các quá trình đều đã giải phóng các file
                    time.sleep(1)
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    logger.debug(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")
        
        return None

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
                # Escape quotes and add quotes around path with spaces
                f.write(f'"{ffmpeg_absolute_path}" -y -i "{video_filename}" -vf "subtitles=\\"{temp_dir_name}/subtitle.srt\\"" -c:a copy "{output_filename}"\n')
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