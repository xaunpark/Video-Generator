#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import logging
import time
import json
import subprocess
import shutil
import tempfile
import random
from pathlib import Path

# Thêm thư mục gốc vào sys.path nếu cần
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import các cài đặt từ config
try:
    from config.settings import TEMP_DIR, OUTPUT_DIR, ASSETS_DIR, VIDEO_SETTINGS
except ImportError:
    # Fallback nếu không thể import
    TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    VIDEO_SETTINGS = {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "image_duration": 5,
        "intro_duration": 5,
        "outro_duration": 5,
        "background_music_volume": 0.1,
        "format": "mp4"
    }

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VideoEditorTestEffects:
    def __init__(self):
        """Khởi tạo VideoEditorTest để tạo video với hiệu ứng"""
        self.temp_dir = TEMP_DIR
        self.output_dir = OUTPUT_DIR
        self.assets_dir = ASSETS_DIR
        
        # Thư mục âm nhạc
        self.music_dir = os.path.join(self.assets_dir, "music")
        
        # Cấu hình video
        self.width = VIDEO_SETTINGS["width"]
        self.height = VIDEO_SETTINGS["height"]
        self.fps = 60  # Tăng fps để có chuyển động mượt mà hơn
        self.img_duration = VIDEO_SETTINGS["image_duration"]
        self.intro_duration = VIDEO_SETTINGS["intro_duration"]
        self.outro_duration = VIDEO_SETTINGS["outro_duration"]
        self.background_music_volume = VIDEO_SETTINGS["background_music_volume"]
        self.video_format = VIDEO_SETTINGS["format"]
        
        # Đảm bảo thư mục đầu ra tồn tại
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Kiểm tra FFmpeg
        self.ffmpeg_path = self._check_ffmpeg()
    
    def _check_ffmpeg(self):
        """Kiểm tra FFmpeg đã được cài đặt và trả về đường dẫn"""
        try:
            ffmpeg_path = "ffmpeg"
            # Nếu ffmpeg.exe tồn tại trong thư mục dự án, ưu tiên sử dụng
            local_ffmpeg = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ffmpeg.exe")
            if os.path.exists(local_ffmpeg):
                ffmpeg_path = local_ffmpeg
                logger.info(f"Tìm thấy FFmpeg tại: {local_ffmpeg}")
            
            # Kiểm tra FFmpeg hoạt động
            result = subprocess.run([ffmpeg_path, "-version"], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE, 
                                   text=True)
            if result.returncode == 0:
                logger.info(f"FFmpeg hoạt động: {result.stdout.splitlines()[0]}")
                return ffmpeg_path
            else:
                logger.error(f"FFmpeg không hoạt động: {result.stderr}")
                raise Exception("FFmpeg không hoạt động")
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra FFmpeg: {str(e)}")
            logger.error("Đảm bảo FFmpeg đã được cài đặt và có thể truy cập từ dòng lệnh hoặc tồn tại trong thư mục dự án")
            raise
    
    def _run_ffmpeg_command(self, command):
        """Thực thi lệnh FFmpeg và ghi log chi tiết
        
        Args:
            command (list): Danh sách các tham số lệnh
            
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        try:
            # In lệnh để debug
            cmd_str = ' '.join(command)
            logger.info(f"Đang chạy lệnh: {cmd_str}")
            
            # Chạy lệnh và hiển thị output real-time
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            # Đọc stderr để xem tiến trình và lỗi
            for line in process.stderr:
                line = line.strip()
                if line:
                    # Chỉ hiện log thông báo quan trọng, không hiện từng frame
                    if not line.startswith('frame=') and not line.startswith('size='):
                        logger.info(line)
            
            # Đợi quá trình hoàn thành
            process.wait()
            
            if process.returncode != 0:
                logger.error(f"FFmpeg trả về mã lỗi: {process.returncode}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Lỗi khi thực thi lệnh FFmpeg: {str(e)}")
            return False
    
    def find_latest_project(self):
        """Tìm file project JSON mới nhất trong thư mục temp
        
        Returns:
            dict: Dữ liệu project hoặc None nếu không tìm thấy
        """
        try:
            # Tìm tất cả file .json trong thư mục temp
            json_files = []
            for root, _, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith('.json') and not file.startswith('audio_') and not file.startswith('image_'):
                        json_files.append(os.path.join(root, file))
            
            if not json_files:
                logger.error(f"Không tìm thấy file project JSON nào trong {self.temp_dir}")
                return None
            
            # Sắp xếp theo thời gian sửa đổi, mới nhất đầu tiên
            json_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            latest_file = json_files[0]
            
            logger.info(f"Tìm thấy file project mới nhất: {latest_file}")
            
            # Đọc dữ liệu
            with open(latest_file, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            return {
                'file_path': latest_file,
                'data': project_data
            }
        except Exception as e:
            logger.error(f"Lỗi khi tìm file project: {str(e)}")
            return None
    
    def _prepare_image_with_effects(self, image_path, output_dir, index, img_type=None, duration=None):
        """Chuẩn bị hình ảnh với hiệu ứng Ken Burns đơn giản và nền mờ cho hình ảnh nhỏ
        
        Args:
            image_path (str): Đường dẫn đến hình ảnh gốc
            output_dir (str): Thư mục đầu ra
            index (int): Chỉ số của hình ảnh
            img_type (str, optional): Loại hình ảnh (intro, scene, outro)
            duration (float, optional): Thời lượng tùy chỉnh
            
        Returns:
            str: Đường dẫn đến hình ảnh đã được xử lý với hiệu ứng
        """
        try:
            # Tên file đầu ra
            output_filename = f"effect_image_{index}.mp4"
            output_path = os.path.join(output_dir, output_filename)
            
            # Xác định thời lượng dựa vào loại hình ảnh
            if duration is not None:
                pass
            elif img_type == "intro":
                duration = self.intro_duration
            elif img_type == "outro":
                duration = self.outro_duration
            else:
                # Thử đoán loại từ tên file
                basename = os.path.basename(image_path).lower()
                if "intro" in basename:
                    duration = self.intro_duration
                elif "outro" in basename:
                    duration = self.outro_duration
                else:
                    duration = self.img_duration
            
            # Tạo hiệu ứng Ken Burns đơn giản
            # Chọn tham số zoom nhẹ nhàng
            zoom_value = 0.05  # Giá trị zoom tối đa 5%
            
            # Sử dụng phiên bản đơn giản nhưng vẫn đảm bảo có nền mờ cho hình ảnh nhỏ
            command = [
                self.ffmpeg_path,
                "-y",
                "-loop", "1",
                "-i", image_path,
                "-t", str(duration),
                "-filter_complex",
                # Hiệu ứng đơn giản với nền mờ
                # 1. Tạo hai bản sao của hình ảnh đầu vào
                # 2. Một bản sao được phóng to và làm mờ làm nền
                # 3. Bản còn lại được áp dụng hiệu ứng zoom đơn giản
                f"[0:v]split=2[bg][fg]; "
                f"[bg]scale={self.width*2}:-1,boxblur=10:5,crop={self.width}:{self.height}:(iw-{self.width})/2:(ih-{self.height})/2[blurred]; "
                f"[fg]scale='min({self.width}*0.9,iw)':'min({self.height}*0.9,ih)':force_original_aspect_ratio=decrease,"
                f"zoompan=z='1+({zoom_value}*sin(PI*on/({self.fps*duration}*2)))':d={self.fps*duration}:s=-1:-1[main]; "
                f"[blurred][main]overlay=(W-w)/2:(H-h)/2",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", str(self.fps),
                "-preset", "medium",
                "-crf", "22",
                output_path
            ]
            
            # Thực thi lệnh
            if self._run_ffmpeg_command(command):
                logger.info(f"Đã tạo hiệu ứng đơn giản với nền mờ cho hình ảnh: {output_path}")
                return output_path
            else:
                # Nếu không thành công, thử cực kỳ đơn giản không có nền mờ
                logger.warning(f"Không thể tạo hiệu ứng với nền mờ cho {image_path}, thử với hiệu ứng siêu đơn giản")
                
                # Phương án cuối cùng, cực kỳ đơn giản
                command_basic = [
                    self.ffmpeg_path,
                    "-y",
                    "-loop", "1",
                    "-i", image_path,
                    "-t", str(duration),
                    "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", 
                    "-r", "30",
                    output_path
                ]
                
                if self._run_ffmpeg_command(command_basic):
                    logger.info(f"Đã tạo hình ảnh tĩnh đơn giản: {output_path}")
                    return output_path
                else:
                    # Nếu vẫn không thành công, trả về False
                    logger.error(f"Không thể tạo hiệu ứng cho hình ảnh: {image_path}")
                    return False
        except Exception as e:
            logger.error(f"Lỗi khi chuẩn bị hình ảnh với hiệu ứng: {str(e)}")
            return False
    
    def create_video_from_enhanced_images(self, enhanced_image_paths, temp_dir):
        """Tạo video từ các hình ảnh đã được xử lý với hiệu ứng
        
        Args:
            enhanced_image_paths (list): Danh sách đường dẫn đến các hình ảnh đã xử lý
            temp_dir (str): Thư mục tạm
            
        Returns:
            str: Đường dẫn đến video đã tạo nếu thành công, False nếu thất bại
        """
        try:
            # Đường dẫn output
            silent_video_path = os.path.join(temp_dir, "silent_video.mp4")
            
            # Tạo file danh sách video
            input_file_path = os.path.join(temp_dir, "video_list.txt")
            with open(input_file_path, 'w', encoding='utf-8') as f:
                for video_path in enhanced_image_paths:
                    if os.path.exists(video_path):
                        f.write(f"file '{video_path}'\n")
            
            # Ghép các video lại với nhau
            command = [
                self.ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", input_file_path,
                "-c", "copy",
                silent_video_path
            ]
            
            logger.info("Đang ghép các video lại...")
            if self._run_ffmpeg_command(command):
                logger.info(f"Đã tạo video không âm thanh: {silent_video_path}")
                return silent_video_path
            else:
                logger.error("Không thể ghép các video lại")
                return False
        except Exception as e:
            logger.error(f"Lỗi khi tạo video từ các hình ảnh đã xử lý: {str(e)}")
            return False
    
    def add_audio_to_video(self, silent_video_path, audio_path, output_path):
        """Thêm âm thanh vào video không có âm thanh
        
        Args:
            silent_video_path (str): Đường dẫn đến video không âm thanh
            audio_path (str): Đường dẫn đến file âm thanh
            output_path (str): Đường dẫn đầu ra
            
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        try:
            # Kiểm tra file đầu vào
            if not os.path.exists(silent_video_path):
                logger.error(f"Không tìm thấy file video: {silent_video_path}")
                return False
                
            if not os.path.exists(audio_path):
                logger.error(f"Không tìm thấy file âm thanh: {audio_path}")
                return False
            
            # Lệnh thêm âm thanh
            command = [
                self.ffmpeg_path,
                "-y",
                "-i", silent_video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                output_path
            ]
            
            logger.info("Đang thêm âm thanh vào video...")
            if self._run_ffmpeg_command(command):
                logger.info(f"Đã thêm âm thanh vào video: {output_path}")
                return True
            else:
                # Thử phương án B
                logger.warning("Lệnh FFmpeg thất bại, thử với cấu hình khác")
                command_b = [
                    self.ffmpeg_path,
                    "-y",
                    "-i", silent_video_path,
                    "-i", audio_path,
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    output_path
                ]
                
                if self._run_ffmpeg_command(command_b):
                    logger.info(f"Phương án B thành công! Đã thêm âm thanh vào video: {output_path}")
                    return True
                else:
                    logger.error("Không thể thêm âm thanh vào video.")
                    return False
        except Exception as e:
            logger.error(f"Lỗi khi thêm âm thanh vào video: {str(e)}")
            return False
    
    def process_latest_project(self):
        """Xử lý dự án mới nhất và tạo video với hiệu ứng chuyển động mượt mà
        
        Returns:
            str: Đường dẫn đến video cuối cùng hoặc None nếu thất bại
        """
        try:
            # Tìm project mới nhất
            project = self.find_latest_project()
            if not project:
                return None
            
            project_file_path = project['file_path']
            project_data = project['data']
            project_dir = os.path.dirname(project_file_path)
            
            # Tạo thư mục tạm thời cho việc xử lý
            with tempfile.TemporaryDirectory() as temp_dir:
                logger.info(f"Xử lý dự án: {project_data.get('title', 'Unknown')}")
                
                # Lấy thông tin hình ảnh
                images = self._get_images_from_project(project_data)
                if not images:
                    logger.error("Không tìm thấy thông tin hình ảnh hợp lệ")
                    return None
                
                # Lấy thông tin âm thanh
                audio_files = self._get_audio_from_project(project_data)
                if not audio_files:
                    logger.error("Không tìm thấy thông tin âm thanh hợp lệ")
                    return None
                
                # Tìm file âm thanh toàn bộ
                full_audio = None
                for audio in audio_files:
                    if audio.get('type') == 'full':
                        full_audio = audio
                        break
                
                if not full_audio:
                    logger.warning("Không tìm thấy file âm thanh toàn bộ. Sẽ ghép từ các file âm thanh phân cảnh")
                    
                    # Ghép file âm thanh từ các phân cảnh
                    scene_audios = [audio for audio in audio_files if audio.get("type") == "scene"]
                    
                    if not scene_audios:
                        logger.error("Không có file âm thanh phân cảnh nào")
                        return None
                    
                    # Tạo file danh sách âm thanh
                    audio_list_file = os.path.join(temp_dir, "audio_list.txt")
                    with open(audio_list_file, "w", encoding="utf-8") as f:
                        for audio in sorted(scene_audios, key=lambda x: x.get("number", 0)):
                            audio_path = audio.get("path")
                            if os.path.exists(audio_path):
                                f.write(f"file '{audio_path}'\n")
                    
                    # Ghép các file âm thanh
                    merged_audio_path = os.path.join(temp_dir, "merged_audio.mp3")
                    merge_command = [
                        self.ffmpeg_path,
                        "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", audio_list_file,
                        "-c", "copy",
                        merged_audio_path
                    ]
                    
                    logger.info("Đang ghép các file âm thanh phân cảnh...")
                    if not self._run_ffmpeg_command(merge_command):
                        logger.error("Không thể ghép các file âm thanh phân cảnh")
                        return None
                    
                    # Tạo thông tin âm thanh ghép
                    full_audio = {
                        "type": "full",
                        "path": merged_audio_path
                    }
                
                # Kiểm tra file âm thanh tồn tại
                audio_path = full_audio.get("path")
                if not audio_path or not os.path.exists(audio_path):
                    logger.error(f"File âm thanh không tồn tại: {audio_path}")
                    return None
                
                # Chuẩn bị danh sách hình ảnh
                intro_images = [img for img in images if img.get("type") == "intro"]
                scene_images = sorted([img for img in images if img.get("type") == "scene"], key=lambda x: x.get("number", 0))
                outro_images = [img for img in images if img.get("type") == "outro"]
                
                all_images = intro_images + scene_images + outro_images
                
                # Tạo thư mục cho các hình ảnh đã xử lý
                enhanced_dir = os.path.join(temp_dir, "enhanced")
                os.makedirs(enhanced_dir, exist_ok=True)
                
                # Xử lý từng hình ảnh với hiệu ứng
                enhanced_image_paths = []
                for i, img in enumerate(all_images):
                    img_path = img.get("path")
                    if not img_path or not os.path.exists(img_path):
                        logger.warning(f"Bỏ qua hình ảnh không tồn tại: {img_path}")
                        continue
                    
                    # Xử lý hình ảnh với hiệu ứng mượt mà
                    enhanced_path = self._prepare_image_with_effects(
                        img_path, 
                        enhanced_dir, 
                        i, 
                        img.get('type'),
                        img.get('duration')
                    )
                    
                    if enhanced_path:
                        enhanced_image_paths.append(enhanced_path)
                
                if not enhanced_image_paths:
                    logger.error("Không có hình ảnh nào được xử lý thành công")
                    return None
                
                # Tạo video từ các hình ảnh đã xử lý
                silent_video_path = self.create_video_from_enhanced_images(enhanced_image_paths, temp_dir)
                if not silent_video_path:
                    logger.error("Không thể tạo video từ các hình ảnh đã xử lý")
                    return None
                
                # Thêm âm thanh vào video
                video_with_audio_path = os.path.join(temp_dir, "video_with_audio.mp4")
                if not self.add_audio_to_video(silent_video_path, audio_path, video_with_audio_path):
                    logger.error("Không thể thêm âm thanh vào video")
                    return None
                
                # Nếu có file nhạc nền, thêm vào
                final_video_path = video_with_audio_path
                
                # Tìm nhạc nền (nếu có)
                background_music = None
                if os.path.exists(self.music_dir):
                    music_files = [f for f in os.listdir(self.music_dir) if f.endswith('.mp3') or f.endswith('.wav')]
                    if music_files:
                        background_music = os.path.join(self.music_dir, music_files[0])
                        logger.info(f"Tìm thấy nhạc nền: {background_music}")
                
                # Nếu có nhạc nền, trộn với âm thanh chính
                if background_music and os.path.exists(background_music):
                    logger.info(f"Thêm nhạc nền: {background_music}")
                    
                    final_video_with_bg = os.path.join(temp_dir, "final_video.mp4")
                    
                    # Lệnh trộn nhạc nền
                    bgm_command = [
                        self.ffmpeg_path,
                        "-y",
                        "-i", video_with_audio_path,
                        "-i", background_music,
                        "-filter_complex", f"[1:a]volume={self.background_music_volume}[bg]; [0:a][bg]amix=inputs=2:duration=shortest",
                        "-c:v", "copy",
                        final_video_with_bg
                    ]
                    
                    # Thực thi lệnh trộn nhạc nền
                    logger.info("Đang thêm nhạc nền...")
                    if self._run_ffmpeg_command(bgm_command):
                        final_video_path = final_video_with_bg
                    else:
                        logger.warning("Không thể thêm nhạc nền, sử dụng video không có nhạc nền")
                
                # Tạo thư mục đầu ra nếu chưa tồn tại
                os.makedirs(self.output_dir, exist_ok=True)
                
                # Tạo tên file đầu ra
                title = project_data.get('title', 'video')
                title_safe = title.replace(' ', '_').replace('/', '_').replace('\\', '_')
                output_filename = f"{title_safe}_effects_{time.strftime('%Y%m%d_%H%M%S')}.{self.video_format}"
                output_path = os.path.join(self.output_dir, output_filename)
                
                # Sao chép video cuối cùng vào thư mục đầu ra
                try:
                    shutil.copy2(final_video_path, output_path)
                    logger.info(f"Đã tạo video thành công: {output_path}")
                    return output_path
                except Exception as e:
                    logger.error(f"Lỗi khi sao chép video cuối cùng: {str(e)}")
                    return None
        except Exception as e:
            logger.error(f"Lỗi khi xử lý dự án: {str(e)}")
            return None
    
    def _get_images_from_project(self, project_data):
        """Lấy thông tin hình ảnh từ dữ liệu dự án hoặc tìm trong thư mục images
        
        Args:
            project_data (dict): Dữ liệu dự án
            
        Returns:
            list: Danh sách thông tin hình ảnh
        """
        # Lấy thông tin hình ảnh trực tiếp từ project data nếu có
        if 'images' in project_data:
            images = project_data['images']
            logger.info(f"Tìm thấy {len(images)} hình ảnh trong dữ liệu dự án")
            return images
        
        # Nếu không có, tìm trong thư mục images
        images_dir = os.path.join(self.temp_dir, "images")
        if not os.path.exists(images_dir):
            logger.error(f"Không tìm thấy thư mục images: {images_dir}")
            return None
        
        # Tìm project mới nhất trong thư mục images
        image_projects = [d for d in os.listdir(images_dir) if d.startswith("project_") and os.path.isdir(os.path.join(images_dir, d))]
        if not image_projects:
            logger.error(f"Không tìm thấy project hình ảnh nào trong {images_dir}")
            return None
        
        # Lấy project mới nhất
        latest_image_project = sorted(image_projects)[-1]
        image_project_dir = os.path.join(images_dir, latest_image_project)
        
        # Tìm file image_info.json
        image_info_path = os.path.join(image_project_dir, "image_info.json")
        if not os.path.exists(image_info_path):
            logger.error(f"Không tìm thấy file image_info.json trong {image_project_dir}")
            return None
        
        # Đọc thông tin hình ảnh
        with open(image_info_path, 'r', encoding='utf-8') as f:
            image_data = json.load(f)
        
        images = image_data.get('images', [])
        
        # Chuyển đổi đường dẫn tương đối thành tuyệt đối
        for img in images:
            if 'rel_path' in img:
                img['path'] = os.path.join(image_project_dir, img['rel_path'])
            elif 'path' in img and not os.path.isabs(img['path']):
                img['path'] = os.path.join(image_project_dir, img['path'])
        
        logger.info(f"Tìm thấy {len(images)} hình ảnh trong {image_project_dir}")
        return images
    
    def _get_audio_from_project(self, project_data):
        """Lấy thông tin âm thanh từ dữ liệu dự án hoặc tìm trong thư mục audio
        
        Args:
            project_data (dict): Dữ liệu dự án
            
        Returns:
            list: Danh sách thông tin âm thanh
        """
        # Lấy thông tin âm thanh trực tiếp từ project data nếu có
        if 'audio_files' in project_data:
            audio_files = project_data['audio_files']
            logger.info(f"Tìm thấy {len(audio_files)} file âm thanh trong dữ liệu dự án")
            return audio_files
        
        # Nếu không có, tìm trong thư mục audio
        audio_dir = os.path.join(self.temp_dir, "audio")
        if not os.path.exists(audio_dir):
            logger.error(f"Không tìm thấy thư mục audio: {audio_dir}")
            return None
        
        # Tìm project mới nhất trong thư mục audio
        audio_projects = [d for d in os.listdir(audio_dir) if d.startswith("project_") and os.path.isdir(os.path.join(audio_dir, d))]
        if not audio_projects:
            logger.error(f"Không tìm thấy project âm thanh nào trong {audio_dir}")
            return None
        
        # Lấy project mới nhất
        latest_audio_project = sorted(audio_projects)[-1]
        audio_project_dir = os.path.join(audio_dir, latest_audio_project)
        
        # Tìm file audio_info.json
        audio_info_path = os.path.join(audio_project_dir, "audio_info.json")
        if not os.path.exists(audio_info_path):
            logger.error(f"Không tìm thấy file audio_info.json trong {audio_project_dir}")
            return None
        
        # Đọc thông tin âm thanh
        with open(audio_info_path, 'r', encoding='utf-8') as f:
            audio_data = json.load(f)
        
        audio_files = audio_data.get('audio_files', [])
        
        # Chuyển đổi đường dẫn tương đối thành tuyệt đối
        for audio in audio_files:
            if 'rel_path' in audio:
                audio['path'] = os.path.join(audio_project_dir, audio['rel_path'])
            elif 'path' in audio and not os.path.isabs(audio['path']):
                audio['path'] = os.path.join(audio_project_dir, audio['path'])
        
        logger.info(f"Tìm thấy {len(audio_files)} file âm thanh trong {audio_project_dir}")
        return audio_files

def main():
    """Hàm chính chạy khi thực thi script"""
    logger.info("Bắt đầu chương trình VideoEditorTestEffects")
    
    try:
        # Khởi tạo editor
        editor = VideoEditorTestEffects()
        
        # Xử lý dự án mới nhất
        output_path = editor.process_latest_project()
        
        if output_path:
            logger.info(f"Chương trình hoàn thành. Video với hiệu ứng mượt mà đã được tạo: {output_path}")
        else:
            logger.error("Chương trình không thể tạo video. Vui lòng xem log để biết chi tiết.")
    except Exception as e:
        logger.error(f"Lỗi không xử lý được: {str(e)}")

if __name__ == "__main__":
    main()