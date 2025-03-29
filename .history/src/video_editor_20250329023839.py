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
        
        # Cài đặt hiệu ứng Ken Burns cho ảnh tĩnh
        # self.enable_ken_burns = VIDEO_SETTINGS.get("enable_ken_burns", True)
        
        # Cài đặt nhạc nền
        self.enable_background_music = VIDEO_SETTINGS.get("enable_background_music", False)
        self.music_volume = VIDEO_SETTINGS.get("music_volume", 0.1)
        
        logger.info(f"VideoEditor đã khởi tạo. Kích thước video: {self.width}x{self.height}, FPS: {self.fps}")
    
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
        Xử lý media (ảnh hoặc video) cho một scene và kết hợp với audio.
        
        Args:
            media_item (dict): Thông tin media (type, path, etc.)
            audio_path (str): Đường dẫn đến file audio
            output_path (str): Đường dẫn lưu video đầu ra
            
        Returns:
            str: Đường dẫn đến file video đã tạo
        """
        media_type = media_item.get('type', 'image')  # 'image' hoặc 'video'
        media_path = media_item.get('path')
        scene_number = media_item.get('number', 'unknown')
        
        if not media_path or not os.path.exists(media_path):
            raise ValueError(f"Không tìm thấy media: {media_path}")
        
        if not os.path.exists(audio_path):
            raise ValueError(f"Không tìm thấy audio: {audio_path}")
        
        logger.info(f"Xử lý scene {scene_number} với {media_type} từ {os.path.basename(media_path)}")
        
        # Đọc audio để lấy thời lượng
        audio_clip = AudioFileClip(audio_path)
        audio_duration = audio_clip.duration
        logger.info(f"Thời lượng audio: {audio_duration:.2f}s")
        audio_clip.close()  # Đóng clip sau khi lấy thông tin
        
        # Xử lý theo loại media
        if media_type == 'video':
            # Xử lý video clip (giữ nguyên code xử lý video)
            try:
                video_clip = VideoFileClip(media_path)
                
                # Kiểm tra thời lượng video
                logger.info(f"Thời lượng video gốc: {video_clip.duration:.2f}s")
                
                # Nếu video ngắn hơn audio, lặp lại video
                if video_clip.duration < audio_duration:
                    logger.info(f"Video ngắn hơn audio. Lặp lại video để phù hợp.")
                    video_clip = video_clip.fx(vfx.loop, duration=audio_duration)
                
                # Nếu video dài hơn, cắt bớt
                elif video_clip.duration > audio_duration:
                    logger.info(f"Video dài hơn audio. Cắt bớt để phù hợp.")
                    video_clip = video_clip.subclip(0, audio_duration)
                
                # Đảm bảo kích thước video đúng
                if video_clip.size != (self.width, self.height):
                    logger.info(f"Điều chỉnh kích thước video từ {video_clip.size} thành {(self.width, self.height)}")
                    video_clip = video_clip.resize(width=self.width, height=self.height)
                
                # Thêm audio
                final_clip = video_clip.set_audio(AudioFileClip(audio_path))
                
                # Xuất video
                final_clip.write_videofile(
                    output_path,
                    codec='libx264',
                    audio_codec='aac',
                    fps=self.fps,
                    preset='medium',
                    threads=4,
                    ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"]
                )
                
                # Đóng clips
                video_clip.close()
                final_clip.close()
                
            except Exception as e:
                logger.error(f"Lỗi khi xử lý video: {str(e)}", exc_info=True)
                # Fallback: Nếu xử lý video thất bại, chuyển sang xử lý như ảnh tĩnh
                logger.info("Chuyển sang xử lý như ảnh tĩnh do lỗi video")
                media_type = 'image'
        
        if media_type == 'image':
            try:
                # Sử dụng ffmpeg trực tiếp để tạo video từ ảnh tĩnh với hiệu ứng zoom nhẹ
                logger.info(f"Xử lý ảnh tĩnh với ffmpeg và hiệu ứng zoom nhẹ nhàng")
                
                # Tạo video tạm chỉ từ ảnh (chưa có audio)
                temp_video_path = os.path.splitext(output_path)[0] + "_temp.mp4"
                
                # Đường dẫn đến ffmpeg (có thể thay đổi tùy hệ thống)
                ffmpeg_path = "ffmpeg"  # Hoặc đường dẫn tuyệt đối nếu ffmpeg không trong PATH
                
                # Tạo video từ ảnh với hiệu ứng zoom nhẹ nhàng
                command = [
                    ffmpeg_path,
                    "-y",  # Ghi đè file nếu đã tồn tại
                    "-loop", "1",  # Lặp ảnh
                    "-i", media_path,  # Ảnh đầu vào
                    "-t", str(audio_duration),  # Thời lượng video
                    "-filter_complex",
                    # Hiệu ứng zoom đơn giản sử dụng hàm sin để tạo chuyển động mượt mà
                    f"zoompan=z='1+(0.03*sin(PI*on/({self.fps*audio_duration}*2)))':d={int(self.fps*audio_duration)}:s={self.width}x{self.height}",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-r", str(self.fps),
                    "-preset", "medium",
                    "-crf", "23",
                    temp_video_path
                ]
                
                # Thực thi lệnh ffmpeg
                logger.info(f"Chạy lệnh ffmpeg: {' '.join(command)}")
                process = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                if not os.path.exists(temp_video_path) or os.path.getsize(temp_video_path) < 1000:
                    logger.error("Tạo video tạm từ ảnh thất bại")
                    raise Exception("Không thể tạo video từ ảnh với ffmpeg")
                    
                # Thêm audio vào video tạm
                command_audio = [
                    ffmpeg_path,
                    "-y",
                    "-i", temp_video_path,  # Video tạm (không có audio)
                    "-i", audio_path,       # File audio
                    "-c:v", "copy",         # Copy video stream không chuyển mã
                    "-c:a", "aac",          # Chuyển mã audio sang AAC
                    "-shortest",            # Kết thúc khi stream ngắn nhất kết thúc
                    output_path
                ]
                
                logger.info(f"Thêm audio: {' '.join(command_audio)}")
                process_audio = subprocess.run(command_audio, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                # Xóa file tạm
                if os.path.exists(temp_video_path):
                    os.remove(temp_video_path)
                    
                logger.info(f"Đã tạo video scene với ảnh và audio thành công: {output_path}")
                
            except subprocess.CalledProcessError as e:
                logger.error(f"Lỗi ffmpeg: {e.stderr.decode('utf-8', errors='ignore')}")
                logger.error(f"Lỗi khi tạo video từ ảnh với ffmpeg: {str(e)}")
                
                # Fallback: Sử dụng MoviePy nếu ffmpeg thất bại
                logger.info("Chuyển sang sử dụng MoviePy do ffmpeg thất bại")
                try:
                    # Phương pháp dự phòng sử dụng MoviePy
                    image_clip = ImageClip(media_path, duration=audio_duration)
                    
                    # Đảm bảo kích thước ảnh đúng
                    if image_clip.size != (self.width, self.height):
                        image_clip = image_clip.resize((self.width, self.height))
                    
                    # Thêm audio
                    final_clip = image_clip.set_audio(AudioFileClip(audio_path))
                    
                    # Xuất video
                    final_clip.write_videofile(
                        output_path,
                        codec='libx264',
                        audio_codec='aac',
                        fps=self.fps,
                        preset='medium',
                        threads=4,
                        ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"]
                    )
                    
                    # Đóng clips
                    image_clip.close()
                    final_clip.close()
                    
                except Exception as e2:
                    logger.error(f"Lỗi khi sử dụng phương pháp dự phòng: {str(e2)}", exc_info=True)
                    raise
            except Exception as e:
                logger.error(f"Lỗi khi xử lý ảnh: {str(e)}", exc_info=True)
                raise
        
        return output_path
    
    def concatenate_scene_videos(self, scene_videos, output_path):
        """
        Nối tất cả video của các scene thành một video liên tục sử dụng ffmpeg trực tiếp.
        
        Args:
            scene_videos (list): Danh sách các đường dẫn tới video scenes
            output_path (str): Đường dẫn để lưu video cuối cùng
            
        Returns:
            str: Đường dẫn tới video cuối cùng
        """
        if not scene_videos:
            raise ValueError("Không có scene videos để nối")
        
        logger.info(f"Nối {len(scene_videos)} video scenes thành video cuối cùng sử dụng ffmpeg trực tiếp")
        
        # Tạo file danh sách tạm thời
        temp_list_file = os.path.join(self.temp_dir, f"concat_list_{int(time.time())}.txt")
        
        try:
            # Tạo file danh sách cho ffmpeg
            with open(temp_list_file, 'w', encoding='utf-8') as f:
                for video_path in scene_videos:
                    if os.path.exists(video_path) and os.path.getsize(video_path) > 10000:
                        # Sử dụng đường dẫn tương đối để tránh vấn đề với đường dẫn có khoảng trắng
                        f.write(f"file '{video_path.replace(os.sep, '/')}'\n")
                    else:
                        logger.warning(f"Bỏ qua video không hợp lệ: {video_path}")
            
            # Đường dẫn ffmpeg
            ffmpeg_path = "ffmpeg"  # Hoặc đường dẫn đầy đủ nếu ffmpeg không trong PATH
            
            # Chuẩn bị tạo video tạm trước
            temp_output = output_path + ".temp.mp4"
            
            # Command để nối các video
            concat_command = [
                ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", temp_list_file,
                "-c", "copy",  # Chỉ copy không encode lại để tránh lỗi
                temp_output
            ]
            
            logger.info(f"Chạy ffmpeg để nối videos: {' '.join(concat_command)}")
            subprocess.run(concat_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Kiểm tra kết quả
            if not os.path.exists(temp_output) or os.path.getsize(temp_output) < 10000:
                raise Exception("Lỗi: Video đầu ra không hợp lệ sau khi nối")
            
            # Bước cuối: Encode lại video để đảm bảo tính tương thích
            final_command = [
                ffmpeg_path,
                "-y",
                "-i", temp_output,
                "-c:v", "libx264",
                "-crf", "23",
                "-preset", "medium",
                "-pix_fmt", "yuv420p",
                "-r", str(self.fps),
                "-c:a", "aac",
                "-b:a", "192k",
                output_path
            ]
            
            logger.info(f"Chạy ffmpeg để encode lại video cuối cùng: {' '.join(final_command)}")
            subprocess.run(final_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Xóa file tạm
            if os.path.exists(temp_output):
                os.remove(temp_output)
            
            if os.path.exists(temp_list_file):
                os.remove(temp_list_file)
            
            logger.info(f"Đã tạo video hoàn chỉnh thành công: {output_path}")
            return output_path
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            logger.error(f"Lỗi ffmpeg: {error_msg}")
            
            # Fallback: Sử dụng MoviePy nếu ffmpeg thất bại
            logger.info("Chuyển sang sử dụng MoviePy do ffmpeg thất bại")
            
            try:
                # Sử dụng MoviePy để nối
                video_clips = []
                for video_path in scene_videos:
                    if os.path.exists(video_path) and os.path.getsize(video_path) > 10000:
                        clip = VideoFileClip(video_path)
                        video_clips.append(clip)
                
                if not video_clips:
                    raise Exception("Không có clip hợp lệ để nối")
                    
                # Nối không có transition
                final_video = concatenate_videoclips(video_clips)
                
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
                
                # Đóng tất cả clips
                for clip in video_clips:
                    clip.close()
                final_video.close()
                
                return output_path
                
            except Exception as e2:
                logger.error(f"Cả hai phương pháp đều thất bại. Lỗi MoviePy: {str(e2)}")
                raise Exception(f"Không thể tạo video cuối cùng: {str(e)} -> {str(e2)}")
        
        except Exception as e:
            logger.error(f"Lỗi không xác định: {str(e)}")
            
            # Xóa files tạm nếu có
            if os.path.exists(temp_list_file):
                os.remove(temp_list_file)
                
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