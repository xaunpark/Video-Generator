#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
video_generator.py - Module để tạo video từ ảnh, video clips và audio
"""

import os
import logging
import shutil
import random
import time
import json
import math
import subprocess
import tempfile

from moviepy.editor import (
    VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, 
    concatenate_videoclips, TextClip
)
import moviepy.video.fx.all as vfx
from moviepy.audio.AudioClip import CompositeAudioClip
from src.fix_pillow import *

# Import cấu hình từ project
from config.settings import TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
        
        # Tạo thư mục tạm để lưu các video scene
        self.temp_video_dir = os.path.join(self.temp_dir, "scene_videos")
        os.makedirs(self.temp_video_dir, exist_ok=True)
        
        # Cài đặt hiệu ứng cho video
        self.enable_transitions = VIDEO_SETTINGS.get("enable_transitions", True)
        self.transition_types = VIDEO_SETTINGS.get("transition_types", ["fade"])
        self.transition_duration = VIDEO_SETTINGS.get("transition_duration", 0.8)
        
        # Cài đặt hiệu ứng cho ảnh tĩnh
        self.image_animation = VIDEO_SETTINGS.get("image_animation", "zoom")
        self.animation_intensity = VIDEO_SETTINGS.get("animation_intensity", 0.02)
        self.animation_cycle_seconds = VIDEO_SETTINGS.get("animation_cycle_seconds", 5)
        
        # Cài đặt nhạc nền
        self.enable_background_music = VIDEO_SETTINGS.get("enable_background_music", False)
        self.music_volume = VIDEO_SETTINGS.get("music_volume", 0.1)
        
        logger.info(f"VideoEditor đã khởi tạo. Kích thước video: {self.width}x{self.height}, FPS: {self.fps}")
        logger.info(f"Hiệu ứng ảnh: {self.image_animation}, Cường độ: {self.animation_intensity}")
    
    def create_video(self, script, media_items, audio_dir, output_path):
        """
        Tạo video hoàn chỉnh từ script, media và audio.
        
        Args:
            script (dict): Script từ script_generator
            media_items (list): Danh sách thông tin media (ảnh/video) từ image_generator
            audio_dir (str): Thư mục chứa các file audio
            output_path (str): Đường dẫn file video cuối cùng
            
        Returns:
            str: Đường dẫn đến video đã tạo
        """
        logger.info(f"Bắt đầu tạo video cho: '{script['title']}'")
        
        # Tạo thư mục tạm cho các scene videos
        timestamp = int(time.time())
        project_id = f"{timestamp}_{hash(script['title']) % 10000:04d}"
        temp_scene_dir = os.path.join(self.temp_video_dir, f"project_{project_id}")
        os.makedirs(temp_scene_dir, exist_ok=True)
        
        # Danh sách các scene videos theo thứ tự
        scene_videos = []
        
        # Phân loại media items theo loại
        intro_items = [item for item in media_items if item.get('media_type') == 'intro']
        scene_items = [item for item in media_items if item.get('media_type') == 'scene']
        outro_items = [item for item in media_items if item.get('media_type') == 'outro']
        
        # Sắp xếp scene items theo số thứ tự
        scene_items.sort(key=lambda x: x.get('number', 0))
        
        # Danh sách tất cả items theo thứ tự
        ordered_items = intro_items + scene_items + outro_items
        
        # Đếm số lượng từng loại
        num_images = sum(1 for item in ordered_items if item.get('type') == 'image')
        num_videos = sum(1 for item in ordered_items if item.get('type') == 'video')
        logger.info(f"Tổng cộng {len(ordered_items)} media items ({num_images} ảnh, {num_videos} video)")
        
        # Xử lý từng item theo thứ tự
        for i, item in enumerate(ordered_items):
            media_type = item.get('media_type', '')  # 'intro', 'scene', 'outro', etc.
            media_format = item.get('type', 'image')   # 'image' hoặc 'video'
            scene_number = item.get('number', 0)
            
            # Xác định tên file audio tương ứng
            if media_type == 'intro':
                audio_file = os.path.join(audio_dir, "intro.mp3")
                output_video = os.path.join(temp_scene_dir, f"00_intro.mp4")
            elif media_type == 'outro':
                audio_file = os.path.join(audio_dir, "outro.mp3")
                output_video = os.path.join(temp_scene_dir, f"99_outro.mp4")
            elif media_type == 'scene':
                audio_file = os.path.join(audio_dir, f"scene_{scene_number}.mp3")
                output_video = os.path.join(temp_scene_dir, f"{scene_number:02d}_scene.mp4")
            else:
                # Bỏ qua các item không xác định
                logger.warning(f"Bỏ qua media không xác định loại: {media_type}")
                continue
            
            # Kiểm tra file audio tồn tại
            if not os.path.exists(audio_file):
                logger.warning(f"Không tìm thấy file audio: {audio_file}. Bỏ qua item này.")
                continue
                
            # Xử lý media item và kết hợp với audio
            try:
                logger.info(f"Đang xử lý {media_type} {scene_number} ({media_format})")
                scene_video = self.process_scene_media(item, audio_file, output_video)
                scene_videos.append(scene_video)
                logger.info(f"Đã xử lý xong {media_type} {scene_number}")
            except Exception as e:
                logger.error(f"Lỗi khi xử lý {media_type} {scene_number}: {str(e)}", exc_info=True)
                # Tiếp tục với item tiếp theo
        
        # Kiểm tra xem có video scene nào được tạo không
        if not scene_videos:
            raise Exception("Không có scene video nào được tạo thành công.")
        
        # Nối tất cả scene videos lại với nhau
        logger.info(f"Đang nối {len(scene_videos)} scene videos thành video cuối cùng")
        try:
            final_video = self.concatenate_scene_videos(scene_videos, output_path)
            logger.info(f"Đã tạo video hoàn thành: {output_path}")
        except Exception as e:
            logger.error(f"Lỗi khi nối các scene videos: {str(e)}", exc_info=True)
            raise
        
        # Ghi metadata về video (tùy chọn)
        try:
            metadata = {
                'title': script['title'],
                'source': script.get('source', 'Unknown'),
                'creation_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'dimensions': f"{self.width}x{self.height}",
                'duration': self._get_video_duration(output_path),
                'num_scenes': len(scene_items),
                'has_intro': len(intro_items) > 0,
                'has_outro': len(outro_items) > 0,
                'num_video_clips': num_videos,
                'num_images': num_images
            }
            
            metadata_file = os.path.splitext(output_path)[0] + ".json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
                
            logger.info(f"Đã lưu metadata video vào: {metadata_file}")
        except Exception as e:
            logger.warning(f"Không lưu được metadata: {str(e)}")
        
        # Dọn dẹp thư mục tạm (tùy chọn)
        if VIDEO_SETTINGS.get("cleanup_temp_files", False):
            try:
                # Xóa các files scene tạm ngay lập tức (vì đã có video cuối cùng)
                shutil.rmtree(temp_scene_dir, ignore_errors=True)
                logger.info(f"Đã xóa thư mục tạm: {temp_scene_dir}")
                
                # Thêm: Dọn dẹp các thư mục tạm cũ (quá 1 ngày)
                self._cleanup_old_temp_dirs(days=1)
            except Exception as e:
                logger.warning(f"Lỗi khi dọn dẹp thư mục tạm: {str(e)}")
        
        return output_path
    
    def process_scene_media(self, media_item, audio_path, output_path):
        """
        Xử lý media (ảnh hoặc video) cho một scene và kết hợp với audio,
        sử dụng thời lượng chính xác từ media_item.
        """
        media_type = media_item.get('type', 'image')
        media_path = media_item.get('path')
        scene_number = media_item.get('number', 'unknown')

        # --- BƯỚC 1: Lấy Thời lượng Đích ---
        target_duration = media_item.get('duration')
        if target_duration is None or not isinstance(target_duration, (int, float)) or target_duration <= 0:
            # Fallback nếu duration không hợp lệ (không nên xảy ra)
            logger.error(f"Scene {scene_number}: Invalid or missing duration in media_item: {target_duration}. Cannot process.")
            # Có thể raise lỗi hoặc trả về None/False tùy cách bạn muốn xử lý lỗi
            raise ValueError(f"Scene {scene_number}: Invalid duration provided in media_item.")
            # Hoặc dùng default nếu muốn cố gắng tiếp tục:
            # logger.warning(f"Scene {scene_number}: Invalid duration {target_duration}. Using default: {VIDEO_SETTINGS['image_duration']}s")
            # target_duration = VIDEO_SETTINGS['image_duration']
        # --- KẾT THÚC BƯỚC 1 ---

        # Kiểm tra file media và audio
        if not media_path or not os.path.exists(media_path):
            raise ValueError(f"Scene {scene_number}: Media path not found or invalid: {media_path}")
        if not os.path.exists(audio_path):
            raise ValueError(f"Scene {scene_number}: Audio path not found: {audio_path}")

        logger.info(f"Processing Scene {scene_number} ({media_type}) using media: {os.path.basename(media_path)}")
        logger.info(f"Target duration for scene {scene_number}: {target_duration:.2f}s (from media_item)") # Log thời lượng đích

        # --- BƯỚC 2: THAY THẾ audio_duration BẰNG target_duration ---

        # Xử lý video hoặc ảnh
        if media_type == 'video':
            try:
                temp_video = output_path + ".temp.mp4"
                # Sử dụng ffmpeg trực tiếp
                video_cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", media_path,
                    # Sử dụng target_duration để cắt video đầu vào nếu cần
                    "-t", str(target_duration),
                    "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1", # Thêm setsar=1
                    "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-r", str(self.fps),
                    "-an", # Bỏ audio gốc
                    temp_video
                ]
                logger.info(f"Processing video clip (duration: {target_duration:.2f}s): {' '.join(video_cmd)}")
                subprocess.run(video_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                # Kết hợp video và audio
                output_cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", temp_video,
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    # -shortest đảm bảo video cuối cùng không dài hơn audio hoặc video đã xử lý
                    "-shortest",
                    output_path
                ]
                logger.info(f"Combining processed video and audio: {' '.join(output_cmd)}")
                subprocess.run(output_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                if os.path.exists(temp_video): os.remove(temp_video)
                logger.info(f"Scene {scene_number}: Video clip processed successfully: {output_path}")

            except subprocess.CalledProcessError as e:
                logger.error(f"Scene {scene_number}: FFmpeg error processing video: {e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)}")
                logger.info(f"Scene {scene_number}: Attempting to process as static image due to video error.")
                media_type = 'image' # Chuyển sang xử lý như ảnh
            except Exception as e:
                logger.error(f"Scene {scene_number}: Error processing video: {str(e)}")
                logger.info(f"Scene {scene_number}: Attempting to process as static image due to error.")
                media_type = 'image' # Chuyển sang xử lý như ảnh

        # Lưu ý: Logic dưới đây chỉ chạy nếu media_type là 'image' ban đầu HOẶC nếu xử lý video thất bại
        if media_type == 'image':
            try:
                temp_video = output_path + ".temp.mp4"
                animation_type = VIDEO_SETTINGS.get("image_animation", "none") # Mặc định là none nếu không chắc
                intensity = VIDEO_SETTINGS.get("animation_intensity", 0.02)
                # Tính tổng số khung hình dựa trên target_duration
                total_frames = int(self.fps * target_duration) # Sử dụng target_duration

                vf_filter = ""
                if animation_type == "zoom" and total_frames > 0:
                    # Sử dụng zoom tuyến tính đã sửa
                    vf_filter = f"zoompan=z='1+({intensity}*on/{total_frames})':d={total_frames}:s={self.width}x{self.height}:fps={self.fps},setsar=1" # Thêm fps và setsar
                    logger.info(f"Scene {scene_number}: Applying linear zoom effect.")
                else:
                    # Mặc định không hiệu ứng hoặc nếu total_frames <= 0
                    if animation_type != "none":
                         logger.warning(f"Scene {scene_number}: Invalid duration or animation type '{animation_type}'. Using static image.")
                    vf_filter = f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1" # Thêm setsar
                    logger.info(f"Scene {scene_number}: Using static image (no animation).")

                image_cmd = [
                    self.ffmpeg_path, "-y",
                    "-loop", "1",
                    "-i", media_path,
                    # Sử dụng target_duration
                    "-t", str(target_duration),
                    "-vf", vf_filter,
                    "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-r", str(self.fps),
                    "-an", # Bỏ audio (sẽ ghép sau)
                    temp_video
                ]
                logger.info(f"Creating video from image (duration: {target_duration:.2f}s): {' '.join(image_cmd)}")
                subprocess.run(image_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                if not os.path.exists(temp_video) or os.path.getsize(temp_video) < 1000: # Kiểm tra size nhỏ hơn
                    raise Exception(f"Temporary video from image is invalid or too small: {temp_video}")

                # Kết hợp video và audio
                output_cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", temp_video,
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    output_path
                ]
                logger.info(f"Combining image-video and audio: {' '.join(output_cmd)}")
                subprocess.run(output_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                if os.path.exists(temp_video): os.remove(temp_video)
                logger.info(f"Scene {scene_number}: Image processed successfully: {output_path}")

            except subprocess.CalledProcessError as e:
                # Lỗi ngay cả khi tạo ảnh tĩnh -> đây là lỗi nghiêm trọng hơn
                logger.error(f"Scene {scene_number}: FFmpeg error processing image: {e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)}")
                # Cố gắng xóa file tạm nếu có
                temp_video = output_path + ".temp.mp4"
                if os.path.exists(temp_video): os.remove(temp_video)
                # Raise lỗi để báo hiệu xử lý scene thất bại
                raise Exception(f"Scene {scene_number}: Failed to process image even without effects.") from e
            except Exception as e:
                logger.error(f"Scene {scene_number}: Unexpected error processing image: {str(e)}")
                 # Cố gắng xóa file tạm nếu có
                temp_video = output_path + ".temp.mp4"
                if os.path.exists(temp_video): os.remove(temp_video)
                raise # Re-raise lỗi

        return output_path # Trả về đường dẫn video của scene đã xử lý
    
    def concatenate_scene_videos(self, scene_videos, output_path):
        """
        Nối tất cả video của các scene thành một video liên tục.
        Phiên bản đơn giản và ổn định nhất.
        """
        if not scene_videos:
            raise ValueError("Không có scene videos để nối")
        
        logger.info(f"Nối {len(scene_videos)} video scenes thành video cuối cùng")
        
        # Tạo file danh sách chứa các video hợp lệ
        valid_videos = []
        for video_path in scene_videos:
            if os.path.exists(video_path) and os.path.getsize(video_path) > 10000:
                valid_videos.append(video_path)
            else:
                logger.warning(f"Bỏ qua video không hợp lệ: {video_path}")
        
        if not valid_videos:
            raise ValueError("Không có video hợp lệ để nối")
        
        # Tạo file danh sách
        concat_list = os.path.join(self.temp_dir, f"concat_list_{int(time.time())}.txt")
        with open(concat_list, 'w', encoding='utf-8') as f:
            for video in valid_videos:
                # Escape path for ffmpeg
                escaped_path = video.replace('\\', '/')
                f.write(f"file '{escaped_path}'\n")
        
        try:
            # Sử dụng phương pháp concat để nối video
            # Cách này đơn giản nhất và ít lỗi nhất
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",  # Chỉ copy không encode lại
                output_path
            ]
            
            logger.info(f"Nối video với ffmpeg: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Xóa file danh sách tạm
            os.remove(concat_list)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                logger.info(f"Đã tạo video cuối cùng thành công: {output_path}")
                return output_path
            else:
                raise Exception("Video đầu ra không hợp lệ hoặc quá nhỏ")
        
        except subprocess.CalledProcessError as e:
            logger.error(f"Lỗi ffmpeg khi nối video: {e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)}")
            
            # Xóa file danh sách nếu có
            if os.path.exists(concat_list):
                os.remove(concat_list)
            
            # Fallback sử dụng MoviePy một cách đơn giản nhất
            logger.info("Thử nối video bằng MoviePy")
            try:
                clips = []
                for video in valid_videos:
                    clip = VideoFileClip(video)
                    clips.append(clip)
                
                final = concatenate_videoclips(clips)
                final.write_videofile(
                    output_path,
                    codec='libx264',
                    audio_codec='aac',
                    fps=self.fps,
                    preset='medium',
                    threads=4,
                    ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"]
                )
                
                # Đóng tất cả clips
                for clip in clips:
                    clip.close()
                final.close()
                
                return output_path
                
            except Exception as e2:
                logger.error(f"Lỗi MoviePy khi nối video: {str(e2)}")
                raise Exception(f"Không thể nối video bằng cả hai phương pháp: {str(e)} -> {str(e2)}")
        
        except Exception as e:
            logger.error(f"Lỗi không xác định: {str(e)}")
            
            # Xóa file danh sách nếu có
            if os.path.exists(concat_list):
                os.remove(concat_list)
                
            raise
    
    def add_subtitles_to_video(self, video_path, script, output_path=None):
        """
        Thêm phụ đề vào video dựa trên script.
        
        Args:
            video_path (str): Đường dẫn video gốc
            script (dict): Script với nội dung từng scene
            output_path (str, optional): Đường dẫn video đầu ra với phụ đề
        
        Returns:
            str: Đường dẫn đến video có phụ đề
        """
        if output_path is None:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_with_subs{ext}"
        
        logger.info(f"Thêm phụ đề vào video: {os.path.basename(video_path)}")
        
        # Đọc video gốc
        video = VideoFileClip(video_path)
        
        # Tạo phụ đề cho từng scene
        subtitle_clips = []
        
        for scene in script.get('scenes', []):
            scene_number = scene.get('number', 0)
            content = scene.get('content', '')
            
            # TODO: Cần tính toán thời điểm bắt đầu và kết thúc của scene trong video
            # Hiện tại chỉ là đơn giản hóa, cần thêm logic tính thời gian chính xác
            
            # Tạo TextClip cho phụ đề
            txt_clip = TextClip(
                content, 
                font='Arial', 
                fontsize=24,
                color='white',
                bg_color='black',
                method='caption',
                size=(video.w, None)
            )
            
            # Đặt vị trí phụ đề ở dưới cùng
            txt_clip = txt_clip.set_position(('center', 'bottom'))
            
            # Thêm vào danh sách
            subtitle_clips.append(txt_clip)
        
        # Tạo video mới với phụ đề
        final_video = CompositeVideoClip([video] + subtitle_clips)
        
        # Xuất video
        final_video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            fps=self.fps,
            preset='medium',
            threads=4,
            ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"]
        )
        
        # Đóng clips
        video.close()
        final_video.close()
        
        logger.info(f"Đã thêm phụ đề vào video: {output_path}")
        return output_path
    
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