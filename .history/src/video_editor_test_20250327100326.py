#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import logging
import time
import json
import subprocess
import shutil
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

class VideoEditorTest:
    def __init__(self):
        """Khởi tạo VideoEditorTest sử dụng cấu hình từ settings"""
        self.temp_dir = TEMP_DIR
        self.output_dir = OUTPUT_DIR
        self.assets_dir = ASSETS_DIR
        
        # Thư mục âm nhạc
        self.music_dir = os.path.join(self.assets_dir, "music")
        
        # Cấu hình video
        self.width = VIDEO_SETTINGS["width"]
        self.height = VIDEO_SETTINGS["height"]
        self.fps = VIDEO_SETTINGS["fps"]
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
    
    def create_silent_video(self, images, project_dir):
        """Tạo video không có âm thanh từ danh sách hình ảnh
        
        Args:
            images (list): Danh sách thông tin hình ảnh
            project_dir (str): Thư mục dự án
            
        Returns:
            str: Đường dẫn đến video đã tạo hoặc None nếu thất bại
        """
        try:
            # Đường dẫn output
            silent_video_path = os.path.join(project_dir, "silent_video.mp4")
            
            # Tạo file danh sách hình ảnh và thời lượng
            input_file_path = os.path.join(project_dir, "image_list.txt")
            with open(input_file_path, 'w', encoding='utf-8') as f:
                for img in images:
                    # Lấy đường dẫn hình ảnh
                    image_path = img.get('path')
                    
                    # Kiểm tra đường dẫn
                    if not image_path:
                        logger.warning(f"Không có đường dẫn cho hình ảnh: {img}")
                        continue
                    
                    # Kiểm tra xem đường dẫn tuyệt đối hay tương đối
                    if not os.path.isabs(image_path):
                        # Thử các vị trí khác nhau
                        possible_paths = [
                            os.path.join(project_dir, image_path),
                            os.path.join(project_dir, os.path.basename(image_path)),
                            os.path.join(self.temp_dir, image_path)
                        ]
                        
                        # Nếu có rel_path, thử thêm
                        if img.get('rel_path'):
                            possible_paths.append(os.path.join(project_dir, img['rel_path']))
                        
                        # Tìm đường dẫn đầu tiên tồn tại
                        for path in possible_paths:
                            if os.path.exists(path):
                                image_path = path
                                break
                    
                    # Kiểm tra lại xem file có tồn tại không
                    if not os.path.exists(image_path):
                        logger.warning(f"Không tìm thấy file hình ảnh: {image_path}")
                        continue
                    
                    # Xác định thời lượng dựa vào loại hình ảnh
                    if img.get('type') == 'intro':
                        duration = self.intro_duration
                    elif img.get('type') == 'outro':
                        duration = self.outro_duration
                    else:
                        duration = img.get('duration', self.img_duration)
                    
                    # Ghi vào file
                    f.write(f"file '{image_path}'\n")
                    f.write(f"duration {duration}\n")
                
                # Hình ảnh cuối cùng cần lặp lại để tránh lỗi
                if images:
                    last_image = images[-1].get('path')
                    if os.path.exists(last_image):
                        f.write(f"file '{last_image}'\n")
            
            logger.info(f"Đã tạo file danh sách hình ảnh: {input_file_path}")
            
            # Tạo video im lặng với ffmpeg
            command = [
                self.ffmpeg_path,
                "-y",  # Ghi đè nếu file đã tồn tại
                "-f", "concat",
                "-safe", "0",
                "-i", input_file_path,
                "-vsync", "vfr",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264",
                "-r", str(self.fps),
                "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2",
                silent_video_path
            ]
            
            logger.info("Đang tạo video không âm thanh...")
            if self._run_ffmpeg_command(command):
                logger.info(f"Đã tạo video không âm thanh: {silent_video_path}")
                return silent_video_path
            else:
                logger.error("Tạo video không âm thanh thất bại.")
                
                # Thử phương án B với ít tham số hơn
                logger.info("Đang thử phương án B với ít tham số hơn...")
                command_b = [
                    self.ffmpeg_path,
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", input_file_path,
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    silent_video_path
                ]
                
                if self._run_ffmpeg_command(command_b):
                    logger.info(f"Phương án B thành công. Đã tạo video không âm thanh: {silent_video_path}")
                    return silent_video_path
                else:
                    return None
        except Exception as e:
            logger.error(f"Lỗi khi tạo video không âm thanh: {str(e)}")
            return None
    
    def create_final_video(self, silent_video_path, audio_files, output_filename=None, background_music=None):
        """Tạo video cuối cùng bằng cách kết hợp video không âm thanh và âm thanh
        
        Args:
            silent_video_path (str): Đường dẫn đến video không âm thanh
            audio_files (list): Danh sách thông tin file âm thanh
            output_filename (str, optional): Tên file đầu ra
            background_music (str, optional): Đường dẫn đến file nhạc nền
            
        Returns:
            str: Đường dẫn đến video cuối cùng nếu thành công, None nếu thất bại
        """
        try:
            if not os.path.exists(silent_video_path):
                logger.error(f"Không tìm thấy video không âm thanh: {silent_video_path}")
                return None
            
            # Tìm file âm thanh toàn bộ
            full_audio = None
            for audio in audio_files:
                if audio.get('type') == 'full':
                    full_audio = audio
                    break
            
            if not full_audio or not full_audio.get('path') or not os.path.exists(full_audio.get('path')):
                logger.error("Không tìm thấy file âm thanh toàn bộ hợp lệ")
                return None
            
            # Đường dẫn output
            project_dir = os.path.dirname(silent_video_path)
            if not output_filename:
                output_filename = f"final_video_{time.strftime('%Y%m%d_%H%M%S')}.{self.video_format}"
            
            output_path = os.path.join(self.output_dir, output_filename)
            
            # Thêm âm thanh vào video
            video_with_audio = os.path.join(project_dir, "video_with_audio.mp4")
            
            # Lệnh thêm âm thanh
            command = [
                self.ffmpeg_path,
                "-y",
                "-i", silent_video_path,
                "-i", full_audio['path'],
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                video_with_audio
            ]
            
            logger.info("Đang thêm âm thanh vào video...")
            if not self._run_ffmpeg_command(command):
                # Thử phương án khác
                logger.info("Thử phương án B cho việc thêm âm thanh...")
                command_b = [
                    self.ffmpeg_path,
                    "-y",
                    "-i", silent_video_path,
                    "-i", full_audio['path'],
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    video_with_audio
                ]
                
                if not self._run_ffmpeg_command(command_b):
                    logger.error("Không thể thêm âm thanh vào video.")
                    return None
            
            # Kiểm tra nếu có nhạc nền
            if background_music and os.path.exists(background_music):
                logger.info(f"Thêm nhạc nền: {background_music}")
                
                final_video = os.path.join(project_dir, "final_with_bgm.mp4")
                
                # Lệnh trộn nhạc nền
                bgm_command = [
                    self.ffmpeg_path,
                    "-y",
                    "-i", video_with_audio,
                    "-i", background_music,
                    "-filter_complex", f"[1:a]volume={self.background_music_volume}[bg]; [0:a][bg]amix=inputs=2:duration=shortest",
                    "-c:v", "copy",
                    final_video
                ]
                
                if self._run_ffmpeg_command(bgm_command):
                    # Sao chép vào thư mục đầu ra
                    shutil.copy2(final_video, output_path)
                else:
                    # Nếu thất bại, sử dụng video chỉ có âm thanh chính
                    logger.warning("Không thể thêm nhạc nền, sử dụng video chỉ có âm thanh chính")
                    shutil.copy2(video_with_audio, output_path)
            else:
                # Sao chép video chỉ có âm thanh chính
                shutil.copy2(video_with_audio, output_path)
            
            logger.info(f"Đã tạo video cuối cùng: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Lỗi khi tạo video cuối cùng: {str(e)}")
            return None
    
    def process_latest_project(self):
        """Xử lý dự án mới nhất tìm thấy trong thư mục temp
        
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
            
            logger.info(f"Xử lý dự án: {project_data.get('title', 'Unknown')}")
            
            # Lấy thông tin hình ảnh
            if 'images' in project_data:
                images = project_data['images']
                logger.info(f"Tìm thấy {len(images)} hình ảnh trong dự án")
            else:
                # Tìm trong thư mục images
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
                logger.info(f"Tìm thấy {len(images)} hình ảnh trong {image_project_dir}")
            
            # Lấy thông tin âm thanh
            if 'audio_files' in project_data:
                audio_files = project_data['audio_files']
                logger.info(f"Tìm thấy {len(audio_files)} file âm thanh trong dự án")
            else:
                # Tìm trong thư mục audio
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
                
                # Chuyển đổi thông tin âm thanh
                audio_files = []
                for audio in audio_data.get('audio_files', []):
                    # Điều chỉnh đường dẫn
                    if 'rel_path' in audio:
                        audio['path'] = os.path.join(audio_project_dir, audio['rel_path'])
                    elif 'path' in audio and not os.path.isabs(audio['path']):
                        audio['path'] = os.path.join(audio_project_dir, audio['path'])
                    
                    audio_files.append(audio)
                
                logger.info(f"Tìm thấy {len(audio_files)} file âm thanh trong {audio_project_dir}")
            
            # Tạo video
            if not images:
                logger.error("Không tìm thấy thông tin hình ảnh hợp lệ")
                return None
            
            if not audio_files:
                logger.error("Không tìm thấy thông tin âm thanh hợp lệ")
                return None
            
            # Tạo video không âm thanh
            silent_video = self.create_silent_video(images, project_dir)
            if not silent_video:
                return None
            
            # Tạo video cuối cùng
            title = project_data.get('title', 'video')
            output_filename = f"{title.replace(' ', '_')}_{time.strftime('%Y%m%d_%H%M%S')}.{self.video_format}"
            
            # Tìm nhạc nền (nếu có)
            background_music = None
            if os.path.exists(self.music_dir):
                music_files = [f for f in os.listdir(self.music_dir) if f.endswith('.mp3') or f.endswith('.wav')]
                if music_files:
                    background_music = os.path.join(self.music_dir, music_files[0])
            
            return self.create_final_video(silent_video, audio_files, output_filename, background_music)
            
        except Exception as e:
            logger.error(f"Lỗi khi xử lý dự án: {str(e)}")
            return None

def main():
    """Hàm chính chạy khi thực thi script"""
    logger.info("Bắt đầu chương trình VideoEditorTest")
    
    try:
        # Khởi tạo editor
        editor = VideoEditorTest()
        
        # Xử lý dự án mới nhất
        output_path = editor.process_latest_project()
        
        if output_path:
            logger.info(f"Chương trình hoàn thành. Video đã được tạo: {output_path}")
        else:
            logger.error("Chương trình không thể tạo video. Vui lòng xem log để biết chi tiết.")
    except Exception as e:
        logger.error(f"Lỗi không xử lý được: {str(e)}")

if __name__ == "__main__":
    main()