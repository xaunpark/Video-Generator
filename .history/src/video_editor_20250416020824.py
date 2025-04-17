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
    Class để tạo video từ script, media và audio, hỗ trợ nhiều chế độ timing.
    Ưu tiên sử dụng FFmpeg cho hiệu suất và ổn định.
    """
    def __init__(self):
        """Khởi tạo VideoEditor với cấu hình cần thiết."""
        self.temp_dir = TEMP_DIR
        self.assets_dir = ASSETS_DIR

        self.width = VIDEO_SETTINGS.get("width", 1920)
        self.height = VIDEO_SETTINGS.get("height", 1080)
        self.fps = VIDEO_SETTINGS.get("fps", 30)

        self.ffmpeg_path = shutil.which("ffmpeg")
        if not self.ffmpeg_path:
            logger.critical("FFmpeg không tìm thấy trong PATH hệ thống!")
            raise FileNotFoundError("FFmpeg is required but not found in PATH.")
        logger.info(f"Using FFmpeg found at: {self.ffmpeg_path}")

        self.ffprobe_path = shutil.which(FFPROBE_EXECUTABLE_PATH) \
                            if FFPROBE_EXECUTABLE_PATH == "ffprobe" else FFPROBE_EXECUTABLE_PATH
        if not self.ffprobe_path or not os.path.exists(self.ffprobe_path):
            logger.warning(f"ffprobe not found at '{self.ffprobe_path}'. Duration checks might be less accurate.")
            self.ffprobe_path = None
        else:
            logger.info(f"Using ffprobe found at: {self.ffprobe_path}")

        # Thư mục tạm cho tất cả project của video editor
        self.temp_video_dir = os.path.join(self.temp_dir, "video_editor_projects")
        os.makedirs(self.temp_video_dir, exist_ok=True)

        # Cài đặt hiệu ứng
        self.image_animation = VIDEO_SETTINGS.get("image_animation", "zoom")
        self.animation_intensity = VIDEO_SETTINGS.get("animation_intensity", 0.02)
        self.transition_duration = VIDEO_SETTINGS.get("transition_duration", 0.5)
        self.enable_transitions = VIDEO_SETTINGS.get("enable_transitions", True) and self.transition_duration > 0

    # --- Các hàm Helper ---

    def _get_video_duration_ffprobe(self, media_path):
        """Lấy thời lượng media (video/audio) bằng ffprobe."""
        if not self.ffprobe_path or not os.path.exists(media_path):
            logger.debug(f"ffprobe not available or file not found: {media_path}. Cannot get duration.")
            return None
        try:
            cmd = [
                self.ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", media_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
            return float(result.stdout.strip())
        except subprocess.CalledProcessError as e:
            logger.warning(f"ffprobe error getting duration for {os.path.basename(media_path)}: {e.stderr.strip()}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error getting duration via ffprobe for {os.path.basename(media_path)}: {e}")
            return None

    def concatenate_videos_with_ffmpeg(self, video_files, output_path, add_transitions=False):
        """Sử dụng FFmpeg concat demuxer hoặc filter để ghép nối video, có thể thêm hiệu ứng chuyển cảnh."""
        valid_video_files = [f for f in video_files if f and os.path.exists(f) and os.path.getsize(f) > 1000]
        if not valid_video_files:
            logger.error("No valid video files provided for concatenation.")
            return None
        num_files = len(valid_video_files)
        logger.info(f"Concatenating {num_files} video files using FFmpeg -> {os.path.basename(output_path)}")

        # --- Lựa chọn phương pháp ghép nối ---
        # Concat demuxer (nhanh, copy codec) hoạt động tốt nhất khi các file có cùng codec, độ phân giải, fps.
        # Filter complex (xfade) linh hoạt hơn, cho phép transition, nhưng yêu cầu re-encode.

        use_complex_filter = add_transitions and self.enable_transitions and num_files > 1

        if use_complex_filter:
            logger.info("Using FFmpeg complex filter (xfade) for concatenation with transitions.")
            # --- Xây dựng lệnh FFmpeg với filter xfade ---
            input_args = []
            filter_complex_parts = []
            last_video_stream = ""

            for i, video_file in enumerate(valid_video_files):
                input_args.extend(["-i", video_file])
                # Giả sử mỗi video có 1 stream video (v:0) và có thể có 1 stream audio (a:0)
                # Xử lý luồng video
                filter_complex_parts.append(f"[{i}:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=pix_fmts=yuv420p[v{i}];")

                if i > 0: # Áp dụng xfade từ clip thứ 2 trở đi
                    offset = sum(self._get_video_duration_ffprobe(f) or 0 for f in valid_video_files[:i]) - self.transition_duration
                    offset = max(0, offset) # Đảm bảo offset không âm
                    # Ví dụ dùng fade, có thể đổi thành loại transition khác được xfade hỗ trợ
                    transition_type = random.choice(VIDEO_SETTINGS.get("transition_types", ["fade"])) # Chọn ngẫu nhiên nếu có nhiều loại
                    filter_complex_parts.append(f"[{last_video_stream}][v{i}]xfade=transition={transition_type}:duration={self.transition_duration}:offset={offset:.4f}[cv{i}];")
                    last_video_stream = f"cv{i}"
                else:
                    last_video_stream = f"v{i}" # Stream đầu tiên

            filter_complex_str = "".join(filter_complex_parts)

            # Lệnh FFmpeg cuối cùng
            cmd = [
                self.ffmpeg_path, "-y",
                *input_args, # Thêm tất cả các input "-i file"
                "-filter_complex", filter_complex_str.rstrip(';'), # Chuỗi filter
                "-map", f"[{last_video_stream}]", # Map video output cuối cùng
                "-c:v", "libx264", "-preset", "medium", "-crf", "22", # Re-encode video
                "-pix_fmt", "yuv420p", "-r", str(self.fps),
                "-an", # Tạm thời không xử lý audio ở đây, sẽ thêm sau
                output_path
            ]

        else: # Dùng concat demuxer (nhanh hơn, không transition)
            logger.info("Using FFmpeg concat demuxer for concatenation (no transitions).")
            list_file_path = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                    list_file_path = f.name
                    for video_file in valid_video_files:
                        abs_path = os.path.abspath(video_file).replace('\\', '/')
                        f.write(f"file '{abs_path}'\n")

                cmd = [
                    self.ffmpeg_path, "-y",
                    "-f", "concat", "-safe", "0", "-i", list_file_path,
                    "-c", "copy", # Copy codec nếu có thể
                    output_path
                ]
            except Exception as list_err:
                 logger.error(f"Error creating concat list file: {list_err}")
                 if list_file_path and os.path.exists(list_file_path): os.remove(list_file_path)
                 return None
            finally:
                 # Đảm bảo file list được xóa ngay cả khi FFmpeg lỗi sau đó
                 # Việc xóa ở finally của hàm concatenate đảm bảo nó được xóa
                 pass # Sẽ xóa ở finally của hàm gọi


        # --- Thực thi lệnh FFmpeg ---
        try:
            logger.debug(f"Running FFmpeg command: {' '.join(cmd)}")
            process = subprocess.run(cmd, capture_output=True, text=True, check=False, encoding='utf-8')

            if process.returncode != 0:
                logger.error(f"FFmpeg concatenation failed! Return code: {process.returncode}")
                logger.error(f"FFmpeg stderr: {process.stderr.strip()}")
                # Nếu dùng demuxer và lỗi, thử lại với re-encoding (chỉ khi không phải filter)
                if not use_complex_filter:
                    logger.info("Concat demuxer failed (maybe different codecs). Retrying with re-encoding...")
                    cmd_reencode = [
                        self.ffmpeg_path, "-y",
                        "-f", "concat", "-safe", "0", "-i", list_file_path,
                        "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", # Cần encode cả audio nếu có
                        "-r", str(self.fps),
                        output_path
                    ]
                    process = subprocess.run(cmd_reencode, capture_output=True, text=True, check=False, encoding='utf-8')
                    if process.returncode != 0:
                        logger.error(f"FFmpeg concatenation re-encoding also failed! Stderr: {process.stderr.strip()}")
                        return None # Thất bại hoàn toàn
                else: # Lỗi với complex filter
                     return None

            # Kiểm tra file output
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"FFmpeg concatenation successful: {os.path.basename(output_path)}")
                return output_path
            else:
                logger.error("Concatenated file is missing or invalid after FFmpeg.")
                return None

        except Exception as e:
            logger.error(f"Error during FFmpeg concatenation process: {e}", exc_info=True)
            return None
        finally:
            # Dọn dẹp file list tạm nếu dùng demuxer
            if not use_complex_filter and list_file_path and os.path.exists(list_file_path):
                try:
                    os.remove(list_file_path)
                    logger.debug(f"Removed temporary concat list file: {list_file_path}")
                except OSError as e:
                    logger.warning(f"Could not remove concat list file {list_file_path}: {e}")


    def generate_subtitles_with_whisper(self, audio_path, output_srt_path, model="base", language="en"):
        """Sử dụng Whisper (ưu tiên faster-whisper) để tạo SRT."""
        if not audio_path or not os.path.exists(audio_path):
            logger.error(f"Audio file not found for SRT generation: {audio_path}")
            return None
        if not output_srt_path: output_srt_path = os.path.splitext(audio_path)[0] + ".srt"

        logger.info(f"Generating subtitles from: {os.path.basename(audio_path)} (Model: {model}, Lang: {language}) -> {os.path.basename(output_srt_path)}")
        start_time = time.time()

        try: # Thử faster-whisper trước
            from faster_whisper import WhisperModel
            logger.debug("Attempting subtitle generation with faster-whisper...")
            # Nên tải model bên ngoài nếu dùng nhiều lần, nhưng tạm thời để đây cho đơn giản
            # Cân nhắc compute_type="int8" nếu CPU không mạnh
            fw_model = WhisperModel(model, device="cpu", compute_type="int8") # Hoặc "float32"
            segments, info = fw_model.transcribe(audio_path, language=(language if language != "auto" else None), task="transcribe")
            with open(output_srt_path, "w", encoding="utf-8") as f:
                i = 1
                for segment in segments:
                    start = self._format_srt_time(segment.start)
                    end = self._format_srt_time(segment.end)
                    f.write(f"{i}\n{start} --> {end}\n{segment.text.strip()}\n\n")
                    i += 1
            logger.info(f"Subtitles generated with faster-whisper in {time.time() - start_time:.2f}s")
            return output_srt_path
        except ImportError:
            logger.warning("faster-whisper not found. Falling back to standard whisper.")
        except Exception as e:
            logger.error(f"Error during faster-whisper SRT generation: {e}. Trying standard whisper.")

        try: # Fallback sang standard whisper
            import whisper
            logger.debug("Attempting subtitle generation with standard whisper...")
            std_model = whisper.load_model(model)
            options = {"language": (language if language != "auto" else None), "task": "transcribe"}
            result = std_model.transcribe(audio_path, **options)
            with open(output_srt_path, "w", encoding="utf-8") as f:
                for i, segment in enumerate(result["segments"], 1):
                    start = self._format_srt_time(segment["start"])
                    end = self._format_srt_time(segment["end"])
                    f.write(f"{i}\n{start} --> {end}\n{segment['text'].strip()}\n\n")
            logger.info(f"Subtitles generated with standard whisper in {time.time() - start_time:.2f}s")
            return output_srt_path
        except ImportError:
            logger.error("Standard whisper library not found. Cannot generate subtitles.")
            return None
        except Exception as e:
            logger.error(f"Error during standard whisper SRT generation: {e}", exc_info=True)
            return None

    def _format_srt_time(self, seconds):
        """Chuyển đổi thời gian từ giây sang định dạng SRT (HH:MM:SS,mmm)."""
        delta = timedelta(seconds=seconds)
        hours, remainder = divmod(delta.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d},{milliseconds:03d}"

    def _cleanup_temp_files(self, file_list, temp_dir_path):
        """Dọn dẹp các file tạm và thư mục tạm."""
        logger.debug(f"Cleaning up {len(file_list)} tracked temp files...")
        cleaned_files = 0
        for f_path in file_list:
            if f_path and os.path.exists(f_path):
                try:
                    os.remove(f_path)
                    cleaned_files += 1
                except OSError as e:
                    logger.warning(f"Could not remove temp file {f_path}: {e}")
        logger.debug(f"Removed {cleaned_files} individual temp files.")

        if VIDEO_SETTINGS.get("cleanup_temp_files", True) and temp_dir_path and os.path.exists(temp_dir_path):
            try:
                logger.info(f"Cleaning up temporary project directory: {temp_dir_path}")
                time.sleep(0.5) # Ngắn hơn
                shutil.rmtree(temp_dir_path, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Error during final temp directory cleanup: {str(e)}")

    def _create_black_clip(self, duration, output_path):
        """Tạo một clip video đen với thời lượng chỉ định."""
        logger.warning(f"Creating black clip (Duration: {duration:.2f}s) -> {os.path.basename(output_path)}")
        try:
            # Đảm bảo duration hợp lệ
            safe_duration = max(0.1, duration) # Tối thiểu 0.1s
            cmd = [
                self.ffmpeg_path, "-y",
                "-f", "lavfi", "-i", f"color=c=black:s={self.width}x{self.height}:r={self.fps}:d={safe_duration}",
                "-t", str(safe_duration),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-pix_fmt", "yuv420p",
                "-an", # Không có audio
                output_path
            ]
            # Sử dụng capture_output=True để bắt stderr khi check=False
            process = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding='utf-8')
            if process.returncode != 0:
                logger.error(f"Failed to create black clip. FFmpeg stderr: {process.stderr.strip()}")
                return None
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100: # Kích thước tối thiểu
                return output_path
            else:
                logger.error(f"Black clip creation seemed successful but file is invalid: {output_path}")
                return None
        except Exception as e:
            logger.error(f"Error creating black clip: {e}")
            return None

    def _create_temp_visual_clip(self, media_item, target_duration, output_path):
        """Tạo clip video TẠM THỜI (không audio) từ ảnh/video với thời lượng mục tiêu."""
        media_path = media_item['path']
        media_type = media_item.get('type', 'image') # Mặc định là image nếu thiếu
        scene_num = media_item.get('number', 'theme') # Lấy số scene hoặc đánh dấu là theme

        logger.debug(f"Creating temp visual clip for Scene/Item '{scene_num}' ({media_type}, Target: {target_duration:.2f}s) -> {os.path.basename(output_path)}")

        try:
            if not os.path.exists(media_path):
                raise FileNotFoundError(f"Media file not found: {media_path}")
            if target_duration <= 0.05: # Ngưỡng tối thiểu
                 logger.warning(f"Target duration {target_duration:.2f}s too short for {os.path.basename(media_path)}. Using 0.1s.")
                 target_duration = 0.1

            cmd = []
            if media_type == 'image':
                vf_filter_parts = []
                # --- Phần Animation (nếu bật) ---
                apply_animation = self.image_animation != "none" and target_duration > 0.5 # Chỉ áp dụng nếu đủ thời gian và animation khác none
                animation_type = "none" # Mặc định

                if apply_animation:
                    intensity = self.animation_intensity
                    total_frames = max(1, int(self.fps * target_duration)) # Đảm bảo > 0

                    # Chọn ngẫu nhiên kiểu animation (zoom, pan_left, pan_right)
                    # Giống cách làm file cũ hơn là chỉ dựa vào setting cứng
                    animation_choices = ["zoom"]
                    # Chỉ thêm pan nếu intensity đủ lớn để thấy rõ
                    if intensity > 0.01:
                        animation_choices.extend(["pan_left", "pan_right"])
                    animation_type = random.choice(animation_choices)
                    logger.debug(f"  Applying random animation: {animation_type} (intensity: {intensity})")

                    # Xây dựng filter zoompan dựa trên lựa chọn
                    if animation_type == "zoom":
                        # Zoom dần từ 1.0 đến 1.0 + intensity
                        zoom_expr = f"'1+({intensity}*(on/{total_frames}))'"
                        # Giữ cố định ở giữa
                        x_expr = "'(iw-iw/zoom)/2'"
                        y_expr = "'(ih-ih/zoom)/2'"
                        vf_filter_parts.append(f"zoompan=z={zoom_expr}:x={x_expr}:y={y_expr}:d={total_frames}:s={self.width}x{self.height}:fps={self.fps}")

                    elif animation_type in ["pan_left", "pan_right"]:
                        # Giữ zoom cố định nhẹ để có không gian pan
                        zoom_level = f"'1+{intensity}'"
                        # Tính toán khoảng cách pan tối đa theo chiều ngang
                        # iw=input width, ow=output width (self.width), z=zoom_level
                        max_x_offset = f"(iw*{zoom_level}-{self.width})"

                        if animation_type == "pan_left": # Nội dung ảnh dịch sang phải (view nhìn sang trái)
                            x_expr = f"'{max_x_offset}*(1-on/{total_frames})'" # Đi từ max offset về 0
                        else: # pan_right - Nội dung ảnh dịch sang trái (view nhìn sang phải)
                            x_expr = f"'{max_x_offset}*(on/{total_frames})'" # Đi từ 0 đến max offset

                        # Giữ y ở giữa
                        y_expr = f"'(ih*{zoom_level}-{self.height})/2'"
                        vf_filter_parts.append(f"zoompan=z={zoom_level}:x={x_expr}:y={y_expr}:d={total_frames}:s={self.width}x{self.height}:fps={self.fps}")

                    # Thêm format sau zoompan nếu có animation
                    vf_filter_parts.append(f"format=pix_fmts=yuv420p")

                else: # Không animation hoặc không đủ điều kiện
                    logger.debug(f"  No animation applied (Setting: {self.image_animation}, Duration: {target_duration:.2f}s)")
                    # Chỉ scale và pad nếu không có animation
                    vf_filter_parts.append(f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease")
                    vf_filter_parts.append(f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2")
                    vf_filter_parts.append(f"setsar=1")
                    vf_filter_parts.append(f"format=pix_fmts=yuv420p")

                # Kết hợp các phần filter
                final_vf_filter = ",".join(vf_filter_parts)

                cmd = [
                    self.ffmpeg_path, "-y",
                    "-loop", "1", "-i", media_path, "-t", str(target_duration),
                    "-vf", final_vf_filter,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-r", str(self.fps), "-an", output_path
                ]
            # --- Phần Video (nếu là video) ---
            elif media_type == 'video':
                source_duration = self._get_video_duration_ffprobe(media_path)
                start_time = 0
                duration_to_use = target_duration
                input_options = []

                if source_duration is None: # Không lấy được duration
                    logger.warning(f"Cannot get duration for video {media_path}. Using full clip up to {target_duration}s.")
                    duration_to_use = target_duration
                elif source_duration <= target_duration:
                    logger.debug(f"Source video ({source_duration:.2f}s) <= target ({target_duration:.2f}s). Using full source.")
                    duration_to_use = source_duration
                    # Có thể cần loop nếu muốn kéo dài đúng target_duration
                else: # Video gốc dài hơn
                    start_time = max(0, (source_duration - target_duration) / 2)
                    duration_to_use = target_duration
                    logger.debug(f"Source video ({source_duration:.2f}s) > target ({target_duration:.2f}s). Taking middle segment.")
                    input_options = ["-ss", str(start_time)] # Chỉ định thời gian bắt đầu

                cmd = [
                    self.ffmpeg_path, "-y",
                    *input_options, "-i", media_path,
                    "-t", str(duration_to_use),
                    "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=pix_fmts=yuv420p",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-r", str(self.fps), "-an", output_path
                ]
            else:
                raise ValueError(f"Unsupported media type: {media_type}")

            # Thực thi lệnh
            process = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding='utf-8')
            if process.returncode != 0:
                logger.error(f"FFmpeg failed creating temp visual. Stderr: {process.stderr.strip()}")
                raise ValueError("FFmpeg temp visual creation failed.")

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return output_path
            else:
                raise ValueError(f"FFmpeg created invalid temp visual: {output_path}")

        except Exception as e:
            logger.error(f"Error creating temp visual clip for {os.path.basename(media_path)}: {e}", exc_info=False)
            # Tạo clip đen làm fallback
            return self._create_black_clip(target_duration, output_path)


    # === HÀM CREATE_VIDEO CHÍNH (ĐÃ TỔNG HỢP) ===
    def create_video(self, script, media_items, audio_files_info, output_path, background_music_path=None, visual_timing_mode="sync_to_audio"):
        project_id = script.get('project_id', f"temp_{time.strftime('%Y%m%d_%H%M%S')}")
        logger.info(f"=== Starting Video Creation for Project: {project_id} (Timing: {visual_timing_mode}) ===")
        temp_project_dir = os.path.join(self.temp_video_dir, project_id)
        os.makedirs(temp_project_dir, exist_ok=True)
        final_output_video_path = output_path # Lưu đường dẫn cuối cùng mong muốn
        temp_files_to_clean = [] # Quản lý tất cả file tạm

        try:
            # --- 0. Chuẩn bị & Validation ---
            if not script or not media_items or not audio_files_info:
                raise ValueError("Missing required input: script, media_items, or audio_files_info.")
            language = script.get('language', 'en')
            script_mode = script.get("script_mode", "basic") # Dùng cho chapter card
            is_advanced_mode = (script_mode == "advanced") # Chế độ nâng cao cho chapter cards
            logger.info(f"Script Mode: {script_mode}")

            # *** Khởi tạo ImageGenerator nếu là advanced mode ***
            image_gen = None
            if is_advanced_mode:
                try:
                    image_gen = ImageGenerator() # Khởi tạo để tạo card
                    logger.info("ImageGenerator initialized for chapter cards.")
                except Exception as ig_err:
                    logger.error(f"Failed to initialize ImageGenerator for chapter cards: {ig_err}. Chapter cards will be skipped.")
                    image_gen = None # Đảm bảo là None nếu lỗi

            # --- 1. Tạo file tạm cho Intro & Outro (Video+Audio) ---
            intro_video_path = None
            outro_video_path = None
            intro_audio_path = None
            outro_audio_path = None
            try:
                # Intro
                intro_media = next((m for m in media_items if m.get('media_type') == 'intro'), None)
                intro_audio = next((a for a in audio_files_info if a.get('type') == 'intro'), None)
                if intro_media and intro_audio and intro_media['type'] == 'image' and os.path.exists(intro_media['path']) and os.path.exists(intro_audio['path']):
                    intro_video_path = os.path.join(temp_project_dir, "intro_final.mp4")
                    intro_audio_path = intro_audio['path']
                    temp_files_to_clean.append(intro_video_path)
                    intro_duration = intro_audio.get('duration', VIDEO_SETTINGS.get("intro_duration", 3))
                    cmd = [ self.ffmpeg_path, "-y", "-loop", "1", "-i", intro_media['path'], "-i", intro_audio_path, "-t", str(intro_duration), "-map", "0:v:0", "-map", "1:a:0", "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,format=pix_fmts=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-r", str(self.fps), "-shortest", intro_video_path ]
                    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                    if not os.path.exists(intro_video_path): raise ValueError("Failed creating intro video")
                    logger.info(f"Created intro video: {os.path.basename(intro_video_path)}")
                # Outro
                outro_media = next((m for m in media_items if m.get('media_type') == 'outro'), None)
                outro_audio = next((a for a in audio_files_info if a.get('type') == 'outro'), None)
                if outro_media and outro_audio and outro_media['type'] == 'image' and os.path.exists(outro_media['path']) and os.path.exists(outro_audio['path']):
                    outro_video_path = os.path.join(temp_project_dir, "outro_final.mp4")
                    outro_audio_path = outro_audio['path']
                    temp_files_to_clean.append(outro_video_path)
                    outro_duration = outro_audio.get('duration', VIDEO_SETTINGS.get("outro_duration", 5))
                    cmd = [ self.ffmpeg_path, "-y", "-loop", "1", "-i", outro_media['path'], "-i", outro_audio_path, "-t", str(outro_duration), "-map", "0:v:0", "-map", "1:a:0", "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,format=pix_fmts=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-r", str(self.fps), "-shortest", outro_video_path ]
                    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                    if not os.path.exists(outro_video_path): raise ValueError("Failed creating outro video")
                    logger.info(f"Created outro video: {os.path.basename(outro_video_path)}")
            except Exception as e:
                logger.error(f"Error creating intro/outro videos: {e}", exc_info=True) # Thoát nếu lỗi nghiêm trọng?

            # --- 2. Chuẩn bị Audio Track Chính (Ghép nối Speech Units) ---
            main_audio_track_path = None
            total_main_audio_duration = 0
            speech_units_audio = sorted([a for a in audio_files_info if a.get('type') == 'speech_unit'], key=lambda x: x['unit_number'])
            speech_audio_paths = [u['path'] for u in speech_units_audio if u.get('path') and os.path.exists(u['path'])]

            if not speech_audio_paths:
                logger.error("No valid speech unit audio files found.")
                self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                return None
            else:
                main_audio_track_path = os.path.join(temp_project_dir, f"main_audio_{project_id}.mp3")
                temp_files_to_clean.append(main_audio_track_path)
                audio_list_path = os.path.join(temp_project_dir, f"main_audio_list.txt")
                temp_files_to_clean.append(audio_list_path)
                try:
                    with open(audio_list_path, 'w', encoding='utf-8') as f:
                        for afp in speech_audio_paths: f.write(f"file '{os.path.abspath(afp).replace('\\', '/')}'\n")
                    concat_audio_cmd = [ self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", audio_list_path, "-c", "copy", main_audio_track_path ]
                    subprocess.run(concat_audio_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                    if not os.path.exists(main_audio_track_path): raise ValueError("Failed to concat main audio")
                    logger.info(f"Created main audio track ({len(speech_audio_paths)} files)")
                    total_main_audio_duration = self._get_video_duration_ffprobe(main_audio_track_path)
                    if total_main_audio_duration is None: total_main_audio_duration = sum(a.get('duration',0) for a in speech_units_audio)
                    logger.info(f"Total main audio duration: {total_main_audio_duration:.2f}s")
                except Exception as e:
                    logger.error(f"Error creating main audio track: {e}")
                    self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                    return None
                if total_main_audio_duration <= 0:
                    logger.error("Main audio track zero duration.")
                    self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                    return None

                if not main_audio_track_path or total_main_audio_duration <= 0:
                    raise ValueError("Failed to create or get duration for main audio track.")

                # --- 3. Chuẩn bị Visual Track Chính (Tùy theo Mode) ---
                main_visual_track_path = None
                temp_files_to_clean.append(main_visual_track_path) # Thêm vào cleanup ngay cả khi None ban đầu
                temp_visual_segments = []
                current_chapter_processed = 0 # Biến theo dõi chapter hiện tại - Dùng để biết khi nào cần chèn card
                
                if visual_timing_mode == 'sync_to_audio':
                    logger.info("Creating visual track synced to audio units...")
                    media_map = {item.get('number'): item for item in media_items if item.get('media_type') == 'scene'}
                    speech_units_audio = sorted([a for a in audio_files_info if a.get('type') == 'speech_unit'], key=lambda x: x.get('unit_number', 0))

                    for unit_info in speech_units_audio:
                        unit_number = unit_info['unit_number']
                        unit_audio_dur = unit_info.get('duration', 0)
                        segment_output_path = os.path.join(temp_project_dir, f"unit{unit_number}_vis_segment.mp4")
                        unit_chapter_num = unit_info.get('chapter_number') # Lấy chapter của unit (nếu có)
                        unit_chapter_title = unit_info.get('chapter_title')

                        # *** CHÈN CHAPTER CARD (NẾU CẦN) ***
                        if is_advanced_mode and image_gen and unit_chapter_num is not None and unit_chapter_num > current_chapter_processed:
                            logger.info(f"--- Inserting Chapter Card for Chapter {unit_chapter_num}: '{unit_chapter_title}' ---")
                            card_img_path = os.path.join(temp_project_dir, f"chapter_{unit_chapter_num}_card.png")
                            card_video_path = os.path.join(temp_project_dir, f"chapter_{unit_chapter_num}_card_video.mp4")
                            temp_files_to_clean.extend([card_img_path, card_video_path])

                            created_card_img = image_gen._create_chapter_title_card(unit_chapter_title, card_img_path, unit_chapter_num)
                            if created_card_img:
                                card_duration = VIDEO_SETTINGS.get("chapter_title_duration", 2.5)
                                # Tạo video từ ảnh card (không tiếng)
                                created_card_video = self._create_temp_visual_clip(
                                    {"path": created_card_img, "type": "image"}, # Giả lập media item
                                    card_duration,
                                    card_video_path
                                )
                                if created_card_video:
                                    temp_visual_segments.append(created_card_video)
                                    logger.info(f"Chapter {unit_chapter_num} card video created.")
                                else:
                                    logger.warning(f"Failed to create video for chapter {unit_chapter_num} card.")
                            else:
                                logger.warning(f"Failed to create image for chapter {unit_chapter_num} card.")
                            current_chapter_processed = unit_chapter_num # Đánh dấu đã xử lý card cho chapter này
                        # *** KẾT THÚC CHÈN CARD ***

                        if unit_audio_dur <= 0.1:
                            logger.warning(f"Unit {unit_number} duration too short ({unit_audio_dur:.2f}s). Creating black clip.")
                            created_segment = self._create_black_clip(0.1, segment_output_path)
                            if created_segment: temp_visual_segments.append(created_segment); temp_files_to_clean.append(created_segment)
                            continue

                        scenes_in_unit = [s for s in script.get('scenes', []) if s.get('number') in unit_info.get('scene_numbers', [])]
                        visual_items_for_unit = [media_map[s['number']] for s in scenes_in_unit if s['number'] in media_map and media_map[s['number']].get('path') and os.path.exists(media_map[s['number']]['path'])]

                        if not visual_items_for_unit:
                            logger.warning(f"Unit {unit_number}: No visuals found. Creating black segment.")
                            created_segment = self._create_black_clip(unit_audio_dur, segment_output_path)
                            if created_segment: temp_visual_segments.append(created_segment); temp_files_to_clean.append(created_segment)
                            continue
                        # Tạo visual segment cho unit này (không audio)
                        try:
                            # 1. Tính duration cho từng visual (word alignment hoặc fallback)
                            word_timestamps = self.get_word_timestamps(unit_info['path'], model_name=VIDEO_SETTINGS.get("subtitle_whisper_model", "base"), language=language)
                            timed_visual_items = None
                            use_fallback = not word_timestamps
                            if word_timestamps:
                                timed_visual_items = self._calculate_precise_shot_durations(visual_items_for_unit, word_timestamps, audio_duration=unit_audio_dur)
                                if not timed_visual_items: use_fallback = True
                            if use_fallback:
                                num_vis = len(visual_items_for_unit)
                                avg_dur = unit_audio_dur / num_vis if num_vis > 0 else unit_audio_dur
                                timed_visual_items = [{**item, 'calculated_duration': max(0.1, avg_dur)} for item in visual_items_for_unit]

                            # 2. Tạo clip tạm cho từng visual (không audio)
                            unit_scene_clips = []
                            for idx, item_timed in enumerate(timed_visual_items):
                                scene_clip_path = os.path.join(temp_project_dir, f"unit{unit_number}_vis{item_timed.get('number', idx)}_temp.mp4")
                                temp_files_to_clean.append(scene_clip_path) # Dọn dẹp clip nhỏ này
                                created_clip = self._create_temp_visual_clip(item_timed, item_timed['calculated_duration'], scene_clip_path)
                                if created_clip: unit_scene_clips.append(created_clip)

                            # 3. Ghép nối các clip visual của unit
                            if not unit_scene_clips: raise ValueError(f"No visual clips created for unit {unit_number}")
                            unit_vis_concat_path = os.path.join(temp_project_dir, f"unit{unit_number}_vis_concat.mp4")
                            temp_files_to_clean.append(unit_vis_concat_path)
                            unit_vis_concat_path = self.concatenate_videos_with_ffmpeg(unit_scene_clips, unit_vis_concat_path, add_transitions=False) # Ghép không transition ở đây
                            if not unit_vis_concat_path: raise ValueError("Failed unit visual concatenation")

                            # 4. Điều chỉnh tốc độ để khớp audio duration
                            vis_seg_duration = self._get_video_duration_ffprobe(unit_vis_concat_path)
                            final_unit_segment_path = unit_vis_concat_path # Mặc định
                            if vis_seg_duration and unit_audio_dur > 0 and abs(vis_seg_duration - unit_audio_dur) > 0.15:
                                speed_factor = vis_seg_duration / unit_audio_dur
                                pts_factor = 1.0 / speed_factor
                                if 0.7 <= speed_factor <= 1.5: # Chỉ chỉnh trong khoảng hợp lý
                                    logger.warning(f"Unit {unit_number}: Adjusting visual speed by {speed_factor:.3f}")
                                    adjusted_path = os.path.join(temp_project_dir, f"unit{unit_number}_vis_adjusted.mp4")
                                    temp_files_to_clean.append(adjusted_path)
                                    cmd_speed = [ self.ffmpeg_path, "-y", "-i", unit_vis_concat_path, "-vf", f"setpts={pts_factor:.4f}*PTS", "-c:v", "libx264", "-crf", "23", "-preset", "medium", "-an", adjusted_path ]
                                    subprocess.run(cmd_speed, check=True, capture_output=True)
                                    if os.path.exists(adjusted_path): final_unit_segment_path = adjusted_path
                                    else: logger.error(f"Unit {unit_number}: Speed adjustment failed.")
                                else: logger.warning(f"Unit {unit_number}: Speed factor {speed_factor:.3f} out of range.")

                            # Đổi tên/move file cuối cùng thành tên segment chuẩn
                            if final_unit_segment_path != segment_output_path and os.path.exists(final_unit_segment_path):
                                shutil.move(final_unit_segment_path, segment_output_path)
                            elif not os.path.exists(segment_output_path):
                                raise ValueError("Final unit segment missing after processing.")
                            # Thêm đường dẫn cuối cùng vào danh sách chính
                            temp_visual_segments.append(segment_output_path)

                        except Exception as e:
                            logger.error(f"Error processing visual segment unit {unit_number}: {e}. Creating black segment.", exc_info=True)
                            created_segment = self._create_black_clip(unit_audio_dur, segment_output_path)
                            if created_segment: temp_visual_segments.append(created_segment)

                elif visual_timing_mode == 'overall_theme_fixed_duration':
                    logger.info("Creating visual track from overall theme visuals...")
                    fixed_duration = VIDEO_SETTINGS.get("fixed_visual_duration", 5.0)
                    theme_visuals_available = [item for item in media_items if item.get("media_type") == "theme_visual"]
                    num_visual_slots_needed = math.ceil(total_main_audio_duration / fixed_duration) if total_main_audio_duration > 0 else 0

                    if num_visual_slots_needed <= 0:
                        logger.error("Cannot create theme visual track: Need 0 visual slots.")
                        self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                        return None

                    theme_visuals_available = [item for item in media_items if item.get("media_type") == "theme_visual"]
                    if not theme_visuals_available:
                        logger.warning("No theme visuals provided. Creating black visual track.")
                        main_visual_track_path = os.path.join(temp_project_dir, f"black_track_{project_id}.mp4")
                        temp_files_to_clean.append(main_visual_track_path)
                        if not self._create_black_clip(total_main_audio_duration, main_visual_track_path):
                            logger.error("Failed fallback black track.")
                            self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                            return None
                    else:
                        # Chọn visual (lặp lại visual cuối nếu thiếu)
                        selected_theme_visuals = theme_visuals_available[:num_visual_slots_needed] if len(theme_visuals_available) >= num_visual_slots_needed else \
                                                theme_visuals_available + [theme_visuals_available[-1]] * (num_visual_slots_needed - len(theme_visuals_available))
                        logger.info(f"Selected {len(selected_theme_visuals)} theme visuals.")

                        # Tạo clip tạm cho từng visual đã chọn
                        for idx, visual_item in enumerate(selected_theme_visuals):
                            clip_temp_path = os.path.join(temp_project_dir, f"theme_vis_{idx+1}.mp4")
                            temp_files_to_clean.append(clip_temp_path)
                            created_clip = self._create_temp_visual_clip(visual_item, fixed_duration, clip_temp_path)
                            if created_clip: temp_visual_segments.append(created_clip)

                        # Nếu không tạo được clip theme nào -> Lỗi
                        if not temp_visual_segments:
                            logger.error("Failed to create any theme visual clips.")
                            self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                            return None

                else: # Mode không hợp lệ
                    logger.error(f"Invalid visual_timing_mode: {visual_timing_mode}")
                    self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                    return None

                # --- Ghép nối các Visual Segments thành Track Chính ---
                if not temp_visual_segments:
                    logger.error("No visual segments were created. Cannot proceed.")
                    self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                    return None

                main_visual_track_path = os.path.join(temp_project_dir, f"main_visual_track_{project_id}.mp4")
                temp_files_to_clean.append(main_visual_track_path)
                # Quyết định có thêm transition khi ghép main visual track hay không
                # Chỉ thêm nếu là theme mode VÀ được bật
                add_main_vis_transitions = (visual_timing_mode == 'overall_theme_fixed_duration')
                main_visual_track_path = self.concatenate_videos_with_ffmpeg(temp_visual_segments, main_visual_track_path, add_transitions=add_main_vis_transitions)

                if not main_visual_track_path:
                    logger.error("Failed to concatenate main visual track.")
                    self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                    return None                            

            # --- 4. Ghép nối Video Cuối Cùng (Intro + Visual Track + Outro - Chỉ hình ảnh) ---
            final_video_segments_no_audio = []
            if intro_video_path and os.path.exists(intro_video_path): final_video_segments_no_audio.append(intro_video_path)
            if main_visual_track_path and os.path.exists(main_visual_track_path): final_video_segments_no_audio.append(main_visual_track_path)
            if outro_video_path and os.path.exists(outro_video_path): final_video_segments_no_audio.append(outro_video_path)

            if not final_video_segments_no_audio:
                logger.error("No video segments (intro/main/outro) available for final concatenation.")
                self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                return None

            intermediate_video_path = os.path.join(temp_project_dir, f"intermediate_visuals_{project_id}.mp4")
            temp_files_to_clean.append(intermediate_video_path)
            # Ghép nối cuối cùng KHÔNG cần transition (vì các segment đã có audio/transition riêng nếu cần)
            intermediate_video_path = self.concatenate_videos_with_ffmpeg(final_video_segments_no_audio, intermediate_video_path, add_transitions=False)

            if not intermediate_video_path:
                 logger.error("Failed to concatenate final video segments.")
                 self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)
                 return None

            # --- 5. Chuẩn bị Audio Track Cuối Cùng (Intro + Main + Outro) ---
            full_audio_path_final = None
            final_audio_files_to_concat = []
            if intro_audio_path and os.path.exists(intro_audio_path): final_audio_files_to_concat.append(intro_audio_path)
            if main_audio_track_path and os.path.exists(main_audio_track_path): final_audio_files_to_concat.append(main_audio_track_path)
            if outro_audio_path and os.path.exists(outro_audio_path): final_audio_files_to_concat.append(outro_audio_path)

            if final_audio_files_to_concat:
                full_audio_path_final = os.path.join(temp_project_dir, f"full_audio_final_{project_id}.mp3")
                temp_files_to_clean.append(full_audio_path_final)
                final_audio_list_path = os.path.join(temp_project_dir, f"final_audio_list.txt")
                temp_files_to_clean.append(final_audio_list_path)
                try:
                    with open(final_audio_list_path, 'w', encoding='utf-8') as f:
                        for afp in final_audio_files_to_concat: f.write(f"file '{os.path.abspath(afp).replace('\\', '/')}'\n")
                    concat_audio_cmd = [ self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", final_audio_list_path, "-c", "copy", full_audio_path_final ]
                    subprocess.run(concat_audio_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                    if not os.path.exists(full_audio_path_final): raise ValueError("Failed to concat final audio")
                    logger.info(f"Created final full audio track: {os.path.basename(full_audio_path_final)}")
                except Exception as e:
                    logger.error(f"Error creating final audio track: {e}")
                    full_audio_path_final = None
            else:
                logger.warning("No intro/main/outro audio found for final concatenation.")


            # --- 6. Thêm Audio Track Cuối Cùng vào Video Đã Ghép ---
            video_with_audio_path = os.path.join(temp_project_dir, f"intermediate_with_audio_{project_id}.mp4")
            temp_files_to_clean.append(video_with_audio_path)
            current_video_input = intermediate_video_path # Video hiện tại để thêm hiệu ứng

            if full_audio_path_final and os.path.exists(full_audio_path_final):
                logger.info("Adding final combined audio track to video...")
                add_final_audio_cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", intermediate_video_path,       # Input 0: Video đã ghép
                    "-i", full_audio_path_final,         # Input 1: Audio cuối cùng
                    "-map", "0:v:0", "-map", "1:a:0",     # Map video 0, audio 1
                    "-c:v", "copy",                       # Copy video stream
                    "-c:a", "aac", "-b:a", "192k",        # Encode audio
                    "-shortest",                          # Dừng theo stream ngắn hơn
                    video_with_audio_path
                ]
                try:
                    process = subprocess.run(add_final_audio_cmd, check=False, capture_output=True, text=True, encoding='utf-8')
                    if process.returncode != 0:
                        logger.error(f"FFmpeg add final audio failed. Stderr: {process.stderr.strip()}")
                        raise ValueError("Failed to add final audio.")
                    if not os.path.exists(video_with_audio_path): raise ValueError("Output file missing after adding audio.")
                    logger.info(f"Added final audio track: {os.path.basename(video_with_audio_path)}")
                    current_video_input = video_with_audio_path # Input cho bước sau
                except Exception as e:
                    logger.error(f"Error adding final audio track: {e}. Video might be silent.", exc_info=True)
                    # Giữ lại video không audio làm input
                    current_video_input = intermediate_video_path
            else:
                logger.warning("Proceeding without final combined audio track (video might be silent).")
                # Input cho bước sau vẫn là video không audio
                current_video_input = intermediate_video_path

            # --- 7. Thêm Nhạc Nền (Input là current_video_input) ---
            video_input_for_subs = current_video_input # File input cho bước phụ đề
            output_path_music_step = os.path.join(temp_project_dir, f"with_music_{project_id}.mp4")
            temp_files_to_clean.append(output_path_music_step)

            if background_music_path and os.path.exists(background_music_path) and VIDEO_SETTINGS.get("enable_background_music", False):
                logger.info("Adding background music...")
                music_temp_files = [] # Quản lý file nhạc tạm
                try:
                    # Điều chỉnh volume nhạc
                    music_vol_adj_path = os.path.join(temp_project_dir, f"music_vol_{project_id}.mp3")
                    music_temp_files.append(music_vol_adj_path)
                    vol_cmd = [ self.ffmpeg_path, "-y", "-i", background_music_path, "-filter:a", f"volume={VIDEO_SETTINGS.get('music_volume', 0.1)}", "-c:a", "libmp3lame", "-q:a", "5", music_vol_adj_path ]
                    subprocess.run(vol_cmd, check=True, capture_output=True)
                    if not os.path.exists(music_vol_adj_path): raise ValueError("Volume adjust failed")

                    # Lấy duration và loop nếu cần
                    video_dur = self._get_video_duration_ffprobe(current_video_input)
                    music_dur = self._get_video_duration_ffprobe(music_vol_adj_path)
                    music_to_use = music_vol_adj_path
                    if video_dur and music_dur and music_dur < video_dur:
                        looped_music_path = os.path.join(temp_project_dir, f"music_looped_{project_id}.mp3")
                        music_temp_files.append(looped_music_path)
                        loops = math.ceil(video_dur / music_dur)
                        music_list_path = os.path.join(temp_project_dir, f"music_loop_list.txt")
                        music_temp_files.append(music_list_path)
                        with open(music_list_path, 'w', encoding='utf-8') as f:
                            for _ in range(loops): f.write(f"file '{os.path.abspath(music_vol_adj_path).replace('\\', '/')}'\n")
                        loop_cmd = [ self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", music_list_path, "-c", "copy", looped_music_path ]
                        subprocess.run(loop_cmd, check=True, capture_output=True)
                        if os.path.exists(looped_music_path): music_to_use = looped_music_path
                        else: logger.warning("Music looping failed, using original.")

                    # Trộn audio bằng amix
                    add_music_cmd = [
                        self.ffmpeg_path, "-y",
                        "-i", current_video_input,    # Input 0: Video (có thể có audio chính)
                        "-i", music_to_use,           # Input 1: Nhạc nền
                        # Input 0 có thể không có audio, cần filter phức tạp hơn hoặc map audio nếu có
                        "-filter_complex",
                        # Nếu current_video_input có audio chính: "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]"
                        # Nếu current_video_input không có audio chính: "[1:a]apad[aout]", # Chỉ pad nhạc nền nếu video câm
                        # Cần kiểm tra xem current_video_input có audio không
                        f"[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]" if full_audio_path_final else "[1:a]apad[aout]",
                        "-map", "0:v:0", "-map", "[aout]",
                        "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k",
                        "-shortest",
                        output_path_music_step # Output tạm có nhạc
                    ]
                    subprocess.run(add_music_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                    if os.path.exists(output_path_music_step):
                        logger.info(f"Added background music: {os.path.basename(output_path_music_step)}")
                        video_input_for_subs = output_path_music_step # Input cho bước sub là file có nhạc
                    else:
                        logger.error("Adding background music failed.")
                        # video_input_for_subs giữ nguyên là current_video_input

                except Exception as music_err:
                    logger.error(f"Error adding background music: {music_err}")
                    # video_input_for_subs giữ nguyên là current_video_input
                finally:
                                    # Dọn dẹp file nhạc tạm
                                    logger.debug("Cleaning up temporary music files...")
                                    for f in music_temp_files:
                                        # Thêm kiểm tra xem f có giá trị không trước khi kiểm tra tồn tại
                                        if f and os.path.exists(f):
                                            try:
                                                os.remove(f)
                                                # Có thể thêm log debug nếu muốn:
                                                # logger.debug(f"Removed temp music file: {os.path.basename(f)}")
                                            except OSError as e: # Bắt lỗi cụ thể và log
                                                logger.warning(f"Could not remove temporary music file {os.path.basename(f)}: {e}")
                                            # Không cần 'pass' ở đây nữa
            else:
                logger.info("Skipping background music.")
                # Input cho sub là file không có nhạc
                video_input_for_subs = current_video_input

            # --- 7.5. Tăng cường chất lượng Video (Tùy chọn) ---
            enhanced_video_path = None # Biến tạm để lưu đường dẫn video đã tăng cường
            if VIDEO_SETTINGS.get("enable_video_enhancement", False) and video_input_for_subs and os.path.exists(video_input_for_subs):
                logger.info("Applying video enhancement filters...")
                enhanced_video_path = os.path.join(temp_project_dir, f"enhanced_{project_id}.mp4")
                temp_files_to_clean.append(enhanced_video_path) # Thêm vào danh sách dọn dẹp

                sat = VIDEO_SETTINGS.get("enhancement_saturation", 1.0)
                con = VIDEO_SETTINGS.get("enhancement_contrast", 1.0)
                bri = VIDEO_SETTINGS.get("enhancement_brightness", 0.0)

                # Xây dựng chuỗi filter eq
                # Chỉ thêm nếu khác giá trị gốc để tối ưu
                eq_filters = []
                if abs(sat - 1.0) > 0.01: eq_filters.append(f"saturation={sat:.2f}")
                if abs(con - 1.0) > 0.01: eq_filters.append(f"contrast={con:.2f}")
                if abs(bri - 0.0) > 0.01: eq_filters.append(f"brightness={bri:.2f}")

                if eq_filters:
                    vf_enhance_str = f"eq={' : '.join(eq_filters)}"
                    enhance_cmd = [
                        self.ffmpeg_path, "-y",
                        "-i", video_input_for_subs, # Input là video đã có audio/nhạc
                        "-vf", vf_enhance_str,
                        "-c:v", "libx264", "-crf", "22", "-preset", "medium", # Re-encode video
                        "-c:a", "copy", # SAO CHÉP audio, không re-encode lại
                        enhanced_video_path
                    ]
                    try:
                        logger.debug(f"Running enhancement command: {' '.join(enhance_cmd)}")
                        process = subprocess.run(enhance_cmd, check=False, capture_output=True, text=True, encoding='utf-8')
                        if process.returncode == 0 and os.path.exists(enhanced_video_path) and os.path.getsize(enhanced_video_path) > 1000:
                            logger.info(f"Video enhancement successful: {os.path.basename(enhanced_video_path)}")
                            video_input_for_subs = enhanced_video_path # Cập nhật input cho bước tiếp theo (subtitles)
                        else:
                            logger.error(f"Video enhancement failed. FFmpeg stderr: {process.stderr.strip()}")
                            # Không cập nhật video_input_for_subs, tiếp tục với video gốc
                            enhanced_video_path = None # Đặt lại để không bị xóa nhầm file gốc
                    except Exception as enhance_err:
                        logger.error(f"Error during video enhancement: {enhance_err}", exc_info=True)
                        enhanced_video_path = None
                else:
                    logger.info("Skipping enhancement as all values are default.")
                    enhanced_video_path = None # Không có gì để làm

            # --- 8. Thêm Phụ Đề (Input là video_input_for_subs) ---
            #    Nguồn audio cho SRT LÀ main_audio_track_path (chỉ lời thoại chính)
            final_video_generated_path = video_input_for_subs # Đường dẫn file hiện tại trước khi move/copy cuối cùng
            subtitled_temp_path = os.path.join(temp_project_dir, f"with_subs_{project_id}.mp4")
            temp_files_to_clean.append(subtitled_temp_path) # Thêm vào dọn dẹp

            if VIDEO_SETTINGS.get("enable_subtitles", False) and \
               video_input_for_subs and os.path.exists(video_input_for_subs) and \
               main_audio_track_path and os.path.exists(main_audio_track_path):
                logger.info("Adding subtitles...")
                srt_path = os.path.join(temp_project_dir, f"subtitles_{project_id}.srt")
                temp_files_to_clean.append(srt_path)
                generated_srt = self.generate_subtitles_with_whisper(
                    main_audio_track_path, srt_path, # Dùng audio chính
                    model=VIDEO_SETTINGS.get("subtitle_whisper_model", "base"),
                    language=language
                )
                if generated_srt:
                    try:
                        # Chuẩn bị path và style
                        if os.name == 'nt': srt_path_escaped = srt_path.replace('\\', '\\\\').replace(':', '\\:')
                        else: srt_path_escaped = srt_path.replace("'", "\\'")
                        style_str = VIDEO_SETTINGS.get("subtitle_style", "...")
                        font_size = VIDEO_SETTINGS.get("subtitle_font_size", 24)
                        vf_subs = f"subtitles='{srt_path_escaped}':force_style='FontSize={font_size},{style_str}'"

                        add_subs_cmd = [
                            self.ffmpeg_path, "-y",
                            "-i", video_input_for_subs,
                            "-vf", vf_subs,
                            "-c:a", "copy",
                            "-c:v", "libx264", "-crf", "22", "-preset", "medium", # Chất lượng cuối cùng
                            "-pix_fmt", "yuv420p",
                            subtitled_temp_path # Output tạm có sub
                        ]
                        process = subprocess.run(add_subs_cmd, check=False, capture_output=True, text=True, encoding='utf-8')
                        if process.returncode != 0 or not os.path.exists(subtitled_temp_path) or os.path.getsize(subtitled_temp_path) < 1000:
                             logger.error(f"Adding subtitles failed. FFmpeg stderr: {process.stderr.strip()}")
                             # final_video_generated_path giữ nguyên là video_input_for_subs
                        else:
                             logger.info(f"Subtitles added successfully to temp file: {os.path.basename(subtitled_temp_path)}")
                             final_video_generated_path = subtitled_temp_path # Cập nhật đường dẫn hiện tại

                    except Exception as sub_err:
                        logger.error(f"Error during subtitle burning process: {sub_err}", exc_info=True)
                        # final_video_generated_path giữ nguyên là video_input_for_subs
                else:
                     logger.error("Failed to generate SRT file. Skipping subtitles.")
                     # final_video_generated_path giữ nguyên là video_input_for_subs
            else:
                logger.info("Skipping subtitles (disabled or missing required files).")
                # final_video_generated_path giữ nguyên là video_input_for_subs


            # --- 9. Di chuyển/Copy file kết quả cuối cùng đến output_path ---
            if final_video_generated_path and os.path.exists(final_video_generated_path):
                 if final_video_generated_path != final_output_video_path:
                      logger.info(f"Moving final processed video to output path: {final_output_video_path}")
                      try:
                          shutil.move(final_video_generated_path, final_output_video_path)
                          logger.info("Final video move successful.")
                      except Exception as move_err:
                          logger.error(f"Could not move final video: {move_err}. Trying copy instead.")
                          try:
                              shutil.copy(final_video_generated_path, final_output_video_path)
                              logger.info("Final video copy successful.")
                          except Exception as copy_err:
                               logger.error(f"Could not copy final video either: {copy_err}. Output might be left in temp: {final_video_generated_path}")
                               final_output_video_path = final_video_generated_path # Trả về file tạm nếu không di chuyển/copy được
                 else:
                      logger.info("Final generated video is already at the output path.")
                      # final_output_video_path đã đúng
            else:
                 logger.error("The expected final video file path is invalid or does not exist before final move/copy.")
                 final_output_video_path = None # Đánh dấu lỗi

            # --- 9.5. Lưu Metadata ---
            if final_output_video_path and os.path.exists(final_output_video_path):
                try:
                    metadata_path = os.path.splitext(final_output_video_path)[0] + ".json"
                    logger.info(f"Saving video metadata to: {metadata_path}")

                    # Lấy duration của video cuối cùng
                    final_duration = self._get_video_duration_ffprobe(final_output_video_path)

                    # Thu thập thông tin metadata
                    metadata = {
                        'project_id': project_id,
                        'title': script.get('title', 'N/A'),
                        'output_path': final_output_video_path,
                        'creation_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'language': language,
                        'script_mode': script_mode,
                        'dimensions': f"{self.width}x{self.height}",
                        'fps': self.fps,
                        'estimated_main_audio_duration_sec': total_main_audio_duration,
                        'final_video_duration_sec': final_duration if final_duration else 'N/A',
                        'visual_timing_mode': visual_timing_mode,
                        'num_speech_units': len(speech_units_audio),
                        'num_total_media_items': len(media_items),
                        'num_scene_media_items': len([m for m in media_items if m.get('media_type') == 'scene']),
                        'num_theme_media_items': len([m for m in media_items if m.get('media_type') == 'theme_visual']),
                        'has_intro': intro_video_path is not None and os.path.exists(intro_video_path),
                        'has_outro': outro_video_path is not None and os.path.exists(outro_video_path),
                        'background_music_used': background_music_path is not None and os.path.exists(background_music_path) and video_input_for_subs != current_video_input,
                        'subtitles_added': 'generated_srt' in locals() and generated_srt is not None and final_video_generated_path == subtitled_temp_path,
                        'image_animation_setting': self.image_animation, # Lưu setting gốc
                        'transitions_enabled': self.enable_transitions,
                        'transition_duration': self.transition_duration,
                        'ffmpeg_path': self.ffmpeg_path,
                        'ffprobe_path': self.ffprobe_path
                    }

                    # Ghi file JSON
                    with open(metadata_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=4, ensure_ascii=False)
                    logger.info(f"Metadata successfully saved.")

                except Exception as meta_err:
                    logger.warning(f"Could not save metadata file: {meta_err}", exc_info=False) # Chỉ cảnh báo, không dừng hẳn

            # --- 10. Dọn dẹp cuối cùng ---
            self._cleanup_temp_files(temp_files_to_clean, temp_project_dir)

            # --- Return ---
            if final_output_video_path and os.path.exists(final_output_video_path) and os.path.getsize(final_output_video_path) > 10000:
                logger.info(f"=== Video Creation Successful: {final_output_video_path} ===")
                return final_output_video_path
            else:
                logger.error(f"Final video file is missing or invalid after all steps: {final_output_video_path}")
                return None # Lỗi cuối cùng

        except Exception as final_err:
             logger.error(f"CRITICAL ERROR during video creation pipeline: {final_err}", exc_info=True)
             self._cleanup_temp_files(temp_files_to_clean, temp_project_dir) # Cố gắng dọn dẹp
             return None

    def get_word_timestamps(self, audio_path, model_name="base", language=None):
        """
        Sử dụng Whisper để transcribe và trích xuất word-level timestamps.
        Ưu tiên faster-whisper nếu có.

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

        logger.info(f"Attempting word alignment for: {os.path.basename(audio_path)} (Model: {model_name})")
        start_time_align = time.time()
        word_timestamps = []

        # --- Thử Faster-Whisper trước ---
        try:
            from faster_whisper import WhisperModel
            logger.debug("Using faster-whisper for alignment.")
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            segments, info = model.transcribe(
                audio_path,
                language=(language if language and language != "auto" else None),
                task="transcribe",
                word_timestamps=True
            )
            # Xử lý segments từ faster-whisper
            for segment in segments:
                for word_info in segment.words:
                    word_text = word_info.word.strip()
                    if word_text:
                        word_timestamps.append({
                            "word": word_text,
                            "start": float(word_info.start),
                            "end": float(word_info.end)
                        })
            if word_timestamps: logger.info(f"Alignment with faster-whisper successful.")
            else: logger.warning("Faster-whisper completed but yielded no word timestamps.") # Cảnh báo nếu không có word

        except ImportError:
            logger.warning("faster-whisper not found. Falling back to standard whisper.")
            # --- Fallback sang Standard Whisper ---
            try:
                import whisper
                logger.debug("Using standard whisper for alignment.")
                model = whisper.load_model(model_name)
                # Sử dụng transcribe trực tiếp với word_timestamps=True cho đơn giản
                result = model.transcribe(
                    audio_path,
                    language=(language if language and language != "auto" else None),
                    fp16=False, # An toàn cho CPU
                    word_timestamps=True
                )

                # Trích xuất từ kết quả standard whisper
                if 'segments' in result:
                    for segment in result['segments']:
                        if 'words' in segment:
                            for word_info in segment['words']:
                                word_text = word_info.get('word', '').strip() # Dùng get an toàn
                                if word_text:
                                    # Đảm bảo start/end tồn tại và là số
                                    if 'start' in word_info and 'end' in word_info:
                                         try:
                                             start_t = float(word_info['start'])
                                             end_t = float(word_info['end'])
                                             word_timestamps.append({"word": word_text, "start": start_t, "end": end_t})
                                         except (TypeError, ValueError):
                                             logger.warning(f"Skipping word with invalid timestamp: {word_info}")
                                    else:
                                         logger.warning(f"Skipping word missing start/end timestamp: {word_info}")

                if word_timestamps: logger.info(f"Alignment with standard whisper successful.")
                else: logger.warning("Standard whisper processing did not yield valid word timestamps.")

            except ImportError:
                 logger.error("Standard whisper library not found either! Cannot perform alignment.")
                 return None # Lỗi nghiêm trọng
            except Exception as std_whisper_err:
                 logger.error(f"Error during standard whisper alignment fallback: {std_whisper_err}", exc_info=True)
                 return None # Lỗi trong quá trình fallback


        except Exception as fw_err:
            # Bắt lỗi chung từ quá trình thử faster-whisper (ngoài ImportError)
            logger.error(f"Error during faster-whisper processing: {fw_err}", exc_info=True)
            # Không cần fallback lại standard whisper ở đây vì đã có logic fallback cho ImportError
            return None # Lỗi trong quá trình transcribe ban đầu

        # --- Kết thúc xử lý ---
        end_time_align = time.time()
        if not word_timestamps:
            logger.error("Error: No word timestamps were extracted from the audio after trying available methods.")
            return None

        logger.info(f"Extracted {len(word_timestamps)} word timestamps in {end_time_align - start_time_align:.2f} seconds.")
        return word_timestamps

    # --- hàm helper chuẩn hóa text ---
    def _normalize_text_for_matching(self, text):
        """Chuẩn hóa text để so khớp (lowercase, bỏ dấu câu, bỏ dấu tiếng Việt)."""
        if not isinstance(text, str): return ""
        text = text.lower().strip('.,!?;:"\'()[]{}')
        # Bỏ các dấu nối câu không cần thiết khi so khớp từ đơn lẻ
        text = text.replace('-', ' ').replace('–', ' ')
        # Sử dụng unidecode để loại bỏ dấu nếu có
        if unidecode:
            try:
                text = unidecode(text)
            except Exception: pass # Bỏ qua lỗi unidecode
        # Loại bỏ khoảng trắng thừa
        text = ' '.join(text.split())
        return text

    # --- Triển khai hàm _calculate_precise_shot_durations ---
    def _calculate_precise_shot_durations(self, visual_items, word_timestamps, audio_duration=None):
        """
        Tính thời lượng chính xác cho mỗi visual item (shot) dựa trên word timestamps.

        Args:
            visual_items (list): List các dict media item (chứa 'content', 'number').
            word_timestamps (list): List word timestamps từ Whisper cho cả speech unit.
            audio_duration (float): Thời lượng audio tổng thể của speech unit (để kiểm tra).

        Returns:
            list: List các dict visual_item được thêm key 'calculated_duration',
                  hoặc None nếu không thể tính toán đáng tin cậy.
        """
        if not word_timestamps:
            logger.error("Cannot calculate precise durations: No word timestamps provided.")
            return None # Không có timestamp -> không thể tính

        logger.info("Calculating precise shot durations based on word timestamps...")
        timed_items = []
        timestamp_idx = 0 # Index hiện tại trong danh sách word_timestamps
        total_words_in_script = 0
        total_words_matched = 0

        # Chuẩn hóa word_timestamps một lần
        normalized_timestamps = [(wt['start'], wt['end'], self._normalize_text_for_matching(wt['word'])) for wt in word_timestamps]
        # Tạo list chỉ chứa các từ đã chuẩn hóa để tìm kiếm nhanh hơn
        normalized_whisper_words = [nt[2] for nt in normalized_timestamps]

        # Lặp qua từng visual item (shot)
        for item_index, item in enumerate(visual_items):
            shot_text = item.get('content', '').strip()
            scene_num = item.get('number', f'item_{item_index+1}')

            # Chuẩn hóa và tách từ của shot hiện tại
            shot_words_normalized = [w for w in map(self._normalize_text_for_matching, shot_text.split()) if w]
            total_words_in_script += len(shot_words_normalized)

            logger.debug(f"  Processing Shot {scene_num}, Text: '{shot_text[:50]}...', Norm Words: {shot_words_normalized}")

            if not shot_words_normalized:
                logger.warning(f"  Shot {scene_num}: No processable words found. Assigning minimal duration (0.1s).")
                timed_items.append({**item, 'calculated_duration': 0.1, 'start_time': -1, 'end_time': -1, 'matched_words': 0})
                continue

            start_time = -1.0
            end_time = -1.0
            words_matched_count_in_shot = 0
            first_match_ts_idx = -1 # Index trong normalized_timestamps
            last_match_ts_idx = -1

            # --- Logic khớp từ ---
            current_shot_word_idx = 0
            # Bắt đầu tìm kiếm từ vị trí timestamp_idx của shot trước
            search_start_ts_idx = timestamp_idx

            while current_shot_word_idx < len(shot_words_normalized) and search_start_ts_idx < len(normalized_whisper_words):
                word_to_find = shot_words_normalized[current_shot_word_idx]
                found_match_in_loop = False

                # Tìm word_to_find trong phần còn lại của timestamps
                try:
                    # Tìm vị trí đầu tiên khớp KỂ TỪ search_start_ts_idx
                    match_ts_idx = normalized_whisper_words.index(word_to_find, search_start_ts_idx)
                    found_match_in_loop = True

                    # Lấy thông tin thời gian từ tuple đã chuẩn hóa
                    match_start, match_end, _ = normalized_timestamps[match_ts_idx]

                    if words_matched_count_in_shot == 0: # Từ đầu tiên của shot khớp
                        start_time = match_start
                        first_match_ts_idx = match_ts_idx
                    # Luôn cập nhật end_time và index cuối cùng
                    end_time = match_end
                    last_match_ts_idx = match_ts_idx

                    words_matched_count_in_shot += 1
                    # Cập nhật vị trí bắt đầu tìm cho từ tiếp theo
                    search_start_ts_idx = match_ts_idx + 1
                    # logger.debug(f"    Matched '{word_to_find}' at ts_idx {match_ts_idx} ({match_start:.3f}-{match_end:.3f})")

                except ValueError: # .index() không tìm thấy
                    logger.warning(f"  Shot {scene_num}: Could not find timestamp match for word '{word_to_find}' (normalized) starting from ts_idx {search_start_ts_idx}.")
                    # Nếu không tìm thấy, bỏ qua từ này và thử từ tiếp theo trong shot
                    pass # current_shot_word_idx sẽ tăng ở cuối vòng lặp ngoài

                # Chuyển sang từ tiếp theo trong shot
                current_shot_word_idx += 1
            # --- Kết thúc khớp từ cho shot ---

            total_words_matched += words_matched_count_in_shot
            calculated_duration = 0.0

            if words_matched_count_in_shot > 0 and last_match_ts_idx >= first_match_ts_idx:
                # Tính duration dựa trên từ đầu và cuối khớp được
                start_time = normalized_timestamps[first_match_ts_idx][0]
                end_time = normalized_timestamps[last_match_ts_idx][1]
                calculated_duration = max(0.0, end_time - start_time) # Đảm bảo không âm
                # Áp dụng duration tối thiểu, ví dụ 100ms hoặc 200ms
                calculated_duration = max(0.15, calculated_duration)
                # Cập nhật timestamp_idx cho shot tiếp theo
                timestamp_idx = last_match_ts_idx + 1
                logger.debug(f"  Shot {scene_num}: Duration = {calculated_duration:.3f}s ({words_matched_count_in_shot}/{len(shot_words_normalized)} words matched, ts indices {first_match_ts_idx}-{last_match_ts_idx}). Next search starts at {timestamp_idx}.")

            else: # Không khớp được từ nào cho shot này
                # Chia đều phần thời gian còn lại của audio cho các shot còn lại? -> Phức tạp
                # Hoặc gán duration mặc định nhỏ. Ưu tiên mặc định nhỏ.
                calculated_duration = 0.5 # Duration fallback nếu không khớp
                logger.warning(f"  Shot {scene_num}: Failed to match any words. Assigning default duration: {calculated_duration:.3f}s.")
                # Không cập nhật timestamp_idx vì không từ nào được "tiêu thụ"

            timed_items.append({
                **item,
                'calculated_duration': calculated_duration,
                'start_time': start_time, # Giữ lại để debug
                'end_time': end_time,     # Giữ lại để debug
                'matched_words': words_matched_count_in_shot
            })
        # Kết thúc lặp qua visual_items

        # --- Kiểm tra tính hợp lý cuối cùng ---
        total_calculated_vis_duration = sum(item['calculated_duration'] for item in timed_items)
        match_ratio = total_words_matched / total_words_in_script if total_words_in_script > 0 else 0

        logger.info(f"Precise duration calculation finished. Matched {total_words_matched}/{total_words_in_script} words ({match_ratio:.1%}). Total visual duration: {total_calculated_vis_duration:.3f}s.")

        # Kiểm tra nếu audio_duration được cung cấp
        if audio_duration and audio_duration > 0:
             duration_diff_ratio = abs(total_calculated_vis_duration - audio_duration) / audio_duration
             logger.info(f"  Compared to audio duration {audio_duration:.3f}s (Difference: {abs(total_calculated_vis_duration - audio_duration):.3f}s, Ratio: {duration_diff_ratio:.1%})")
             # Điều kiện để coi là thất bại: ví dụ khớp dưới 60% từ HOẶC chênh lệch duration quá 25%
             if match_ratio < 0.6 or duration_diff_ratio > 0.25:
                  logger.error("Word timestamp matching results deemed unreliable (low match rate or significant duration mismatch). Falling back to simpler timing.")
                  return None # Báo hiệu thất bại -> dùng fallback

        return timed_items # Trả về danh sách item với duration đã tính

    def concatenate_videos_with_ffmpeg(self, video_files, output_path, add_transitions=False):
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