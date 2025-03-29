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
    Hỗ trợ hiệu ứng Ken Burns cho ảnh, transitions giữa các cảnh, và nhạc nền.
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
        
        # Đọc audio
        audio_clip = AudioFileClip(audio_path)
        audio_duration = audio_clip.duration
        logger.info(f"Thời lượng audio: {audio_duration:.2f}s")
        
        # Xử lý theo loại media
        if media_type == 'video':
            # Xử lý video clip
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
                final_clip = video_clip.set_audio(audio_clip)
                
                # Tùy chọn: Thêm hiệu ứng video để tăng chất lượng
                if VIDEO_SETTINGS.get("enhance_video", False):
                    logger.info("Áp dụng hiệu ứng tăng cường chất lượng video")
                    final_clip = final_clip.fx(vfx.colorx, 1.1)  # Tăng cường màu sắc nhẹ
                
            except Exception as e:
                logger.error(f"Lỗi khi xử lý video: {str(e)}", exc_info=True)
                # Fallback: Nếu xử lý video thất bại, chuyển sang xử lý như ảnh tĩnh
                logger.info("Chuyển sang xử lý như ảnh tĩnh do lỗi video")
                media_type = 'image'
        
        if media_type == 'image':
            # Xử lý ảnh tĩnh
            try:
                # Đọc ảnh và tạo clip với thời lượng bằng audio
                image_clip = ImageClip(media_path, duration=audio_duration)
                
                # Đảm bảo kích thước ảnh đúng
                if image_clip.size != (self.width, self.height):
                    logger.debug(f"Điều chỉnh kích thước ảnh từ {image_clip.size} thành {(self.width, self.height)}")
                    image_clip = image_clip.resize((self.width, self.height))
                
                # REMOVED: All Ken Burns and animation code is removed from here
                
                # Thêm audio
                final_clip = image_clip.set_audio(audio_clip)
                
            except Exception as e:
                logger.error(f"Lỗi khi xử lý ảnh: {str(e)}", exc_info=True)
                raise
        
        # Xuất video scene
        try:
            final_clip.write_videofile(
                output_path,
                codec='libx264',
                audio_codec='aac',
                fps=self.fps,
                preset='medium',
                threads=4,
                ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"]
            )
            logger.info(f"Đã tạo video scene thành công: {output_path}")
        except Exception as e:
            logger.error(f"Lỗi khi xuất video scene: {str(e)}", exc_info=True)
            raise
        
        # Đóng các clips để giải phóng bộ nhớ
        try:
            if 'audio_clip' in locals() and audio_clip is not None:
                audio_clip.close()
            if 'final_clip' in locals() and final_clip is not None:
                final_clip.close()
        except Exception as e:
            logger.warning(f"Lỗi khi đóng clips: {str(e)}")
        
        return output_path
    
    def concatenate_scene_videos(self, scene_videos, output_path):
        """
        Nối tất cả video của các scene thành một video liên tục với transitions.
        
        Args:
            scene_videos (list): Danh sách các đường dẫn tới video scenes
            output_path (str): Đường dẫn để lưu video cuối cùng
            
        Returns:
            str: Đường dẫn tới video cuối cùng
        """
        if not scene_videos:
            raise ValueError("Không có scene videos để nối")
        
        logger.info(f"Nối {len(scene_videos)} video scenes thành video cuối cùng")
        
        # Đọc tất cả clip
        video_clips = []
        total_duration = 0
        
        for i, video_path in enumerate(scene_videos):
            try:
                if not os.path.exists(video_path):
                    logger.warning(f"Không tìm thấy video {i+1}: {video_path}. Bỏ qua.")
                    continue
                    
                clip = VideoFileClip(video_path)
                video_clips.append(clip)
                total_duration += clip.duration
                logger.info(f"Đọc video {i+1}: {os.path.basename(video_path)}, thời lượng: {clip.duration:.2f}s")
            except Exception as e:
                logger.error(f"Lỗi khi đọc video {i+1} ({video_path}): {str(e)}")
                # Tiếp tục với clip khác
        
        if not video_clips:
            raise Exception("Không có clip hợp lệ để nối")
        
        logger.info(f"Tổng thời lượng: {total_duration:.2f}s")
        
        # Tùy chọn: Thêm nhạc nền nếu được cấu hình
        background_music = None
        if self.enable_background_music:
            try:
                music_dir = os.path.join(self.assets_dir, "background_music")
                
                if os.path.exists(music_dir):
                    music_files = [f for f in os.listdir(music_dir) 
                                 if f.lower().endswith(('.mp3', '.wav', '.m4a'))]
                    
                    if music_files:
                        # Chọn file nhạc ngẫu nhiên
                        music_file = random.choice(music_files)
                        music_path = os.path.join(music_dir, music_file)
                        logger.info(f"Sử dụng nhạc nền: {music_file}")
                        
                        # Đọc file nhạc
                        background_music = AudioFileClip(music_path)
                        
                        # Điều chỉnh thời lượng nhạc
                        if background_music.duration < total_duration:
                            # Lặp lại nhạc nếu nhạc ngắn hơn video
                            logger.info(f"Lặp lại nhạc ({background_music.duration:.2f}s) để đủ thời lượng video ({total_duration:.2f}s)")
                            background_music = background_music.fx(vfx.audio_loop, duration=total_duration)
                        else:
                            # Cắt nhạc nếu nhạc dài hơn video
                            logger.info(f"Cắt nhạc ({background_music.duration:.2f}s) về thời lượng video ({total_duration:.2f}s)")
                            background_music = background_music.subclip(0, total_duration)
                        
                        # Điều chỉnh âm lượng nhạc nền
                        logger.info(f"Điều chỉnh âm lượng nhạc nền xuống {self.music_volume * 100:.0f}%")
                        background_music = background_music.volumex(self.music_volume)
            except Exception as e:
                logger.warning(f"Lỗi khi xử lý nhạc nền: {str(e)}")
                background_music = None
        
        # Thêm transitions giữa các clip nếu được bật
        final_video = None
        
        if self.enable_transitions and len(video_clips) > 1:
            logger.info(f"Thêm transitions giữa các scenes (loại: {', '.join(self.transition_types)})")
            
            # Chuẩn bị video với transitions
            clips_with_transitions = []
            
            for i, clip in enumerate(video_clips):
                # Đối với clip đầu tiên
                if i == 0:
                    # Thêm fade in cho clip đầu tiên
                    clip = clip.fx(vfx.fadein, self.transition_duration / 2)
                
                # Đối với clip cuối cùng
                if i == len(video_clips) - 1:
                    # Thêm fade out cho clip cuối cùng
                    clip = clip.fx(vfx.fadeout, self.transition_duration / 2)
                
                # Thêm clip vào danh sách
                clips_with_transitions.append(clip)
                
                # Nếu clip thứ i có transition tiếp theo
                if i < len(video_clips) - 1:
                    # Chọn một kiểu transition ngẫu nhiên
                    transition_type = random.choice(self.transition_types)
                    
                    if transition_type == "fade" and i < len(video_clips) - 1:
                        # Thêm crossfadeout cho clip hiện tại
                        video_clips[i] = video_clips[i].fx(vfx.fadeout, self.transition_duration / 2)
                        
                        # Thêm crossfadein cho clip tiếp theo
                        video_clips[i+1] = video_clips[i+1].fx(vfx.fadein, self.transition_duration / 2)
            
            # Nối các clip với transitions
            try:
                logger.info("Nối các clips với hiệu ứng transitions")
                final_video = concatenate_videoclips(video_clips, method="compose")
                logger.info(f"Đã nối {len(video_clips)} clips với transitions")
            except Exception as e:
                logger.error(f"Lỗi khi nối clips với transitions: {str(e)}")
                # Fallback: Nối đơn giản không có transition
                logger.info("Chuyển sang nối clips không có transition do lỗi")
                final_video = concatenate_videoclips(video_clips)
        else:
            # Nối đơn giản nếu không dùng transition
            logger.info("Nối các clips không có transition")
            final_video = concatenate_videoclips(video_clips)
        
        # Thêm nhạc nền nếu có
        if background_music is not None:
            try:
                # Lấy audio gốc từ video
                original_audio = final_video.audio
                
                if original_audio is not None:
                    # Trộn audio gốc với nhạc nền
                    logger.info("Trộn audio gốc với nhạc nền")
                    final_audio = CompositeAudioClip([original_audio, background_music])
                    final_video = final_video.set_audio(final_audio)
                    logger.info("Đã thêm nhạc nền vào video")
            except Exception as e:
                logger.error(f"Lỗi khi thêm nhạc nền: {str(e)}")
        
        # Xuất video cuối cùng
        try:
            logger.info(f"Đang xuất video cuối cùng vào: {output_path}")
            final_video.write_videofile(
                output_path,
                codec='libx264',
                audio_codec='aac',
                fps=self.fps,
                preset='medium',
                threads=4
            )
            logger.info(f"Đã xuất video cuối cùng thành công: {output_path}")
        except Exception as e:
            logger.error(f"Lỗi khi xuất video cuối cùng: {str(e)}", exc_info=True)
            raise
        
        # Đóng tất cả clips để giải phóng tài nguyên
        try:
            for clip in video_clips:
                clip.close()
            
            if background_music:
                background_music.close()
            
            final_video.close()
        except Exception as e:
            logger.warning(f"Lỗi khi đóng clips: {str(e)}")
        
        return output_path
    
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
            fps=self.fps
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
    print(f"Enable Ken Burns: {VIDEO_SETTINGS.get('enable_ken_burns', True)}")
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