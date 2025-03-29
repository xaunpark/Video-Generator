# src/video_editor.py
import os
import sys
import logging
import time
import json
import subprocess
import shutil
import tempfile
from pathlib import Path

# Thêm thư mục gốc vào sys.path
if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from config.settings import TEMP_DIR, OUTPUT_DIR, ASSETS_DIR, VIDEO_SETTINGS

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VideoEditor:
    def __init__(self):
        """Khởi tạo VideoEditor"""
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
            logger.debug(f"Đang chạy lệnh: {cmd_str}")
            
            # Chạy lệnh và hiển thị output real-time
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            # Đọc và ghi log output từ ffmpeg
            for line in process.stderr:
                line = line.strip()
                if line:
                    # Lọc các dòng không cần thiết để giảm spam log
                    if not (line.startswith('frame=') or line.startswith('size=')):
                        logger.debug(line)
            
            # Đợi quá trình hoàn thành
            process.wait()
            
            if process.returncode != 0:
                logger.error(f"FFmpeg trả về mã lỗi: {process.returncode}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Lỗi khi thực thi lệnh FFmpeg: {str(e)}")
            return False
    
    def create_silent_video_from_images(self, images, output_dir):
        """Tạo video không có âm thanh từ danh sách hình ảnh
        
        Args:
            images (list): Danh sách thông tin hình ảnh
            output_dir (str): Thư mục đầu ra
            
        Returns:
            str: Đường dẫn đến video đã tạo nếu thành công, False nếu thất bại
        """
        try:
            # Đường dẫn output
            silent_video_path = os.path.join(output_dir, "silent_video.mp4")
            
            # Tạo file danh sách hình ảnh và thời lượng
            input_file_path = os.path.join(output_dir, "image_list.txt")
            with open(input_file_path, 'w', encoding='utf-8') as f:
                for img in images:
                    # Lấy đường dẫn hình ảnh
                    image_path = img.get('path')
                    
                    # Kiểm tra đường dẫn
                    if not image_path:
                        logger.warning(f"Không có đường dẫn cho hình ảnh: {img}")
                        continue
                    
                    # Kiểm tra xem file có tồn tại không
                    if not os.path.exists(image_path):
                        logger.warning(f"Không tìm thấy file hình ảnh: {image_path}")
                        
                        # Thử với đường dẫn tương đối nếu có
                        if img.get('rel_path'):
                            alternative_path = os.path.join(output_dir, img.get('rel_path'))
                            if os.path.exists(alternative_path):
                                image_path = alternative_path
                                logger.info(f"Tìm thấy đường dẫn thay thế: {image_path}")
                            else:
                                logger.warning(f"Không tìm thấy đường dẫn thay thế: {alternative_path}")
                                continue
                        else:
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
                silent_video_path
            ]
            
            logger.info("Đang tạo video không âm thanh...")
            if self._run_ffmpeg_command(command):
                logger.info(f"Đã tạo video không âm thanh: {silent_video_path}")
                return silent_video_path
            else:
                # Thử phương án B với tham số đơn giản hơn
                logger.warning("Lệnh FFmpeg thất bại, thử với cấu hình đơn giản hơn")
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
                    logger.info(f"Phương án B thành công! Đã tạo video không âm thanh: {silent_video_path}")
                    return silent_video_path
                else:
                    logger.error("Không thể tạo video không âm thanh.")
                    return False
        except Exception as e:
            logger.error(f"Lỗi khi tạo video không âm thanh: {str(e)}")
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
    
    def create_video(self, images, audio_files, script, background_music=None):
        """
        Tạo video từ hình ảnh và âm thanh sử dụng FFmpeg (cải tiến)
        
        Args:
            images (list): Danh sách thông tin hình ảnh
            audio_files (list): Danh sách thông tin file âm thanh
            script (dict): Thông tin kịch bản
            background_music (str, optional): Đường dẫn đến file nhạc nền
            
        Returns:
            str: Đường dẫn đến file video đã tạo hoặc None nếu thất bại
        """
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            title_safe = script['title'].replace(' ', '_').replace('/', '_').replace('\\', '_')
            output_filename = f"{title_safe}_{timestamp}.{self.video_format}"
            output_path = os.path.join(self.output_dir, output_filename)
            
            # Tạo thư mục tạm thời cho quá trình xử lý
            with tempfile.TemporaryDirectory() as temp_dir:
                logger.info(f"Bắt đầu tạo video cho kịch bản: {script['title']}")
                
                # Kiểm tra dữ liệu đầu vào
                if not images:
                    logger.error("Danh sách hình ảnh trống")
                    return None
                
                if not audio_files:
                    logger.error("Danh sách âm thanh trống")
                    return None
                
                # Tìm audio file cho toàn bộ kịch bản
                full_audio = None
                for audio in audio_files:
                    if audio.get("type") == "full":
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
                
                # Tạo video không âm thanh
                silent_video_path = self.create_silent_video_from_images(all_images, temp_dir)
                if not silent_video_path:
                    logger.error("Không thể tạo video không âm thanh")
                    return None
                
                # Thêm âm thanh vào video
                video_with_audio_path = os.path.join(temp_dir, "video_with_audio.mp4")
                if not self.add_audio_to_video(silent_video_path, audio_path, video_with_audio_path):
                    logger.error("Không thể thêm âm thanh vào video")
                    return None
                
                # Nếu có file nhạc nền, thêm vào
                final_video_path = video_with_audio_path
                
                if background_music:
                    # Đảm bảo file nhạc nền tồn tại
                    if not os.path.exists(background_music):
                        # Thử tìm trong thư mục music
                        bg_music_path = os.path.join(self.music_dir, os.path.basename(background_music))
                        if os.path.exists(bg_music_path):
                            background_music = bg_music_path
                        else:
                            logger.warning(f"Không tìm thấy file nhạc nền: {background_music}")
                            background_music = None
                
                # Nếu không có nhạc nền cụ thể, thử tìm file mặc định
                if not background_music:
                    default_music_path = os.path.join(self.music_dir, "background.mp3")
                    if os.path.exists(default_music_path):
                        background_music = default_music_path
                
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
                
                # Sao chép video cuối cùng vào thư mục đầu ra
                try:
                    shutil.copy2(final_video_path, output_path)
                    logger.info(f"Đã tạo video thành công: {output_path}")
                except Exception as e:
                    logger.error(f"Lỗi khi sao chép video cuối cùng: {str(e)}")
                    # Thử đổi tên file nếu sao chép thất bại
                    output_path = os.path.join(self.output_dir, f"video_{timestamp}.{self.video_format}")
                    shutil.copy2(final_video_path, output_path)
                    logger.info(f"Đã tạo video với tên thay thế: {output_path}")
                
                # Lưu thông tin video
                self._save_video_info(
                    output_path=output_path,
                    title=script["title"],
                    images=images,
                    audio_files=audio_files,
                    script=script
                )
                
                return output_path
                
        except Exception as e:
            logger.error(f"Lỗi khi tạo video: {str(e)}")
            return None
    
    def _save_video_info(self, output_path, title, images, audio_files, script):
        """Lưu thông tin video vào file JSON"""
        try:
            video_info = {
                "title": title,
                "creation_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "video_path": output_path,
                "script": {
                    "title": script.get("title", "Unknown"),
                    "scenes_count": len(script.get("scenes", []))
                },
                "stats": {
                    "images_count": len(images),
                    "audio_files_count": len(audio_files),
                    "duration": self._calculate_total_duration(images)
                }
            }
            
            # Lưu thông tin
            info_filename = f"video_info_{os.path.basename(output_path).split('.')[0]}.json"
            info_path = os.path.join(self.output_dir, info_filename)
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(video_info, f, indent=4, ensure_ascii=False)
            
            logger.info(f"Đã lưu thông tin video tại: {info_path}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi lưu thông tin video: {str(e)}")
            return False
    
    def _calculate_total_duration(self, images):
        """Tính tổng thời lượng dựa trên hình ảnh"""
        try:
            total_duration = 0
            
            for img in images:
                if img.get("type") == "intro":
                    total_duration += self.intro_duration
                elif img.get("type") == "outro":
                    total_duration += self.outro_duration
                else:
                    total_duration += img.get("duration", self.img_duration)
            
            return total_duration
        except Exception as e:
            logger.error(f"Lỗi khi tính tổng thời lượng: {str(e)}")
            return 0

# Test module nếu chạy trực tiếp
if __name__ == "__main__":
    try:
        # Import các module khác để test
        from src.news_scraper import NewsScraper
        from src.script_generator import ScriptGenerator
        from src.image_generator import ImageGenerator
        from src.voice_generator import VoiceGenerator
        
        # Tìm dữ liệu test trong thư mục temp
        temp_files = os.listdir(TEMP_DIR)
        project_files = [f for f in temp_files if f.endswith('.json') and not f.startswith('audio_') and not f.startswith('image_')]
        
        if project_files:
            # Lấy file mới nhất
            latest_project = sorted(project_files, key=lambda f: os.path.getmtime(os.path.join(TEMP_DIR, f)))[-1]
            project_path = os.path.join(TEMP_DIR, latest_project)
            
            logger.info(f"Tìm thấy project mới nhất: {project_path}")
            
            # Đọc dữ liệu project
            with open(project_path, "r", encoding="utf-8") as f:
                project_data = json.load(f)
            
            # Lấy thông tin script
            script = project_data.get('script', {})
            
            # Lấy thông tin images
            images = project_data.get('images', [])
            
            # Lấy thông tin audio
            audio_files = project_data.get('audio_files', [])
            
            # Nếu không có trong project, tìm trong thư mục
            if not images:
                # Tìm trong thư mục images
                images_dir = os.path.join(TEMP_DIR, "images")
                if os.path.exists(images_dir):
                    image_projects = [d for d in os.listdir(images_dir) 
                                     if d.startswith("project_") and os.path.isdir(os.path.join(images_dir, d))]
                    
                    if image_projects:
                        # Sắp xếp theo thời gian, lấy mới nhất
                        latest_image_project = sorted(image_projects)[-1]
                        image_project_dir = os.path.join(images_dir, latest_image_project)
                        
                        # Tìm file image_info.json
                        image_info_path = os.path.join(image_project_dir, "image_info.json")
                        if os.path.exists(image_info_path):
                            with open(image_info_path, "r", encoding="utf-8") as f:
                                image_data = json.load(f)
                            
                            images = image_data.get('images', [])
                            
                            # Chuyển đổi đường dẫn tương đối thành tuyệt đối
                            for img in images:
                                if 'rel_path' in img:
                                    img['path'] = os.path.join(image_project_dir, img['rel_path'])
            
            # Nếu không có trong project, tìm thông tin audio
            if not audio_files:
                # Tìm trong thư mục audio
                audio_dir = os.path.join(TEMP_DIR, "audio")
                if os.path.exists(audio_dir):
                    audio_projects = [d for d in os.listdir(audio_dir) 
                                     if d.startswith("project_") and os.path.isdir(os.path.join(audio_dir, d))]
                    
                    if audio_projects:
                        # Sắp xếp theo thời gian, lấy mới nhất
                        latest_audio_project = sorted(audio_projects)[-1]
                        audio_project_dir = os.path.join(audio_dir, latest_audio_project)
                        
                        # Tìm file audio_info.json
                        audio_info_path = os.path.join(audio_project_dir, "audio_info.json")
                        if os.path.exists(audio_info_path):
                            with open(audio_info_path, "r", encoding="utf-8") as f:
                                audio_data = json.load(f)
                            
                            audio_files = audio_data.get('audio_files', [])
                            
                            # Chuyển đổi đường dẫn tương đối thành tuyệt đối
                            for audio in audio_files:
                                if 'rel_path' in audio:
                                    audio['path'] = os.path.join(audio_project_dir, audio['rel_path'])
            
            # Kiểm tra dữ liệu
            if not script:
                logger.error("Không tìm thấy thông tin script")
            elif not images:
                logger.error("Không tìm thấy thông tin images")
            elif not audio_files:
                logger.error("Không tìm thấy thông tin audio")
            else:
                # Tạo video
                editor = VideoEditor()
                output_path = editor.create_video(images, audio_files, script)
                
                if output_path:
                    logger.info(f"Đã tạo video thành công: {output_path}")
                else:
                    logger.error("Không thể tạo video")
        else:
            logger.error(f"Không tìm thấy file project nào trong {TEMP_DIR}")
    except Exception as e:
        logger.error(f"Lỗi khi chạy test: {str(e)}")