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
        self._check_ffmpeg()
    
    def _check_ffmpeg(self):
        """Kiểm tra FFmpeg đã được cài đặt"""
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
                self.ffmpeg_path = ffmpeg_path
            else:
                logger.error(f"FFmpeg không hoạt động: {result.stderr}")
                raise Exception("FFmpeg không hoạt động")
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra FFmpeg: {str(e)}")
            logger.error("Đảm bảo FFmpeg đã được cài đặt và có thể truy cập từ dòng lệnh hoặc tồn tại trong thư mục dự án")
            raise
    
    def create_video(self, images, audio_files, script, background_music=None):
        """
        Tạo video từ hình ảnh và âm thanh sử dụng FFmpeg
        
        Args:
            images (list): Danh sách thông tin hình ảnh
            audio_files (list): Danh sách thông tin file âm thanh
            script (dict): Thông tin kịch bản
            background_music (str, optional): Đường dẫn đến file nhạc nền
            
        Returns:
            str: Đường dẫn đến file video đã tạo
        """
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_filename = f"news_video_{timestamp}.{self.video_format}"
            output_path = os.path.join(self.output_dir, output_filename)
            
            # Tạo thư mục tạm thời cho quá trình xử lý
            with tempfile.TemporaryDirectory() as temp_dir:
                logger.info(f"Bắt đầu tạo video cho kịch bản: {script['title']}")
                
                # Tìm audio file cho toàn bộ kịch bản
                full_audio = None
                for audio in audio_files:
                    if audio["type"] == "full":
                        full_audio = audio
                        break
                
                if not full_audio:
                    logger.warning("Không tìm thấy file âm thanh toàn bộ. Sẽ ghép từ các file âm thanh phân cảnh")
                    # Ghép file âm thanh từ các phân cảnh (không triển khai trong code này)
                    return None
                
                # Chuẩn bị danh sách hình ảnh
                intro_images = [img for img in images if img["type"] == "intro"]
                scene_images = sorted([img for img in images if img["type"] == "scene"], key=lambda x: x["number"])
                outro_images = [img for img in images if img["type"] == "outro"]
                
                all_images = intro_images + scene_images + outro_images
                
                # Tạo file danh sách hình ảnh (input.txt) cho FFmpeg
                input_file = os.path.join(temp_dir, "input.txt")
                with open(input_file, "w", encoding="utf-8") as f:
                    for img in all_images:
                        # Xác định thời lượng cho mỗi hình ảnh
                        if img["type"] == "intro":
                            duration = self.intro_duration
                        elif img["type"] == "outro":
                            duration = self.outro_duration
                        else:
                            duration = img.get("duration", self.img_duration)
                        
                        # Ghi thông tin hình ảnh và thời lượng
                        f.write(f"file '{img['path']}'\n")
                        f.write(f"duration {duration}\n")
                    
                    # Hình ảnh cuối cùng cần lặp lại để tránh lỗi
                    if all_images:
                        f.write(f"file '{all_images[-1]['path']}'\n")
                
                # Tạo video không có âm thanh trước
                silent_video = os.path.join(temp_dir, "silent_video.mp4")
                
                # Lệnh tạo video không âm thanh
                cmd_create_video = [
                    self.ffmpeg_path,
                    "-y",  # Ghi đè file nếu tồn tại
                    "-f", "concat",  # Format concat
                    "-safe", "0",  # Cho phép đường dẫn tương đối
                    "-i", input_file,  # File danh sách hình ảnh
                    "-vsync", "vfr",  # Variable frame rate
                    "-pix_fmt", "yuv420p",  # Pixel format
                    "-c:v", "libx264",  # Video codec
                    "-r", str(self.fps),  # Frame rate
                    "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2",  # Giữ tỷ lệ và căn giữa
                    silent_video
                ]
                
                # Thực thi lệnh tạo video không âm thanh
                logger.info("Đang tạo video không âm thanh...")
                self._run_ffmpeg_command(cmd_create_video)
                
                # Thêm âm thanh vào video
                video_with_audio = os.path.join(temp_dir, "video_with_audio.mp4")
                
                # Lệnh thêm âm thanh
                cmd_add_audio = [
                    self.ffmpeg_path,
                    "-y",
                    "-i", silent_video,  # Video không âm thanh
                    "-i", full_audio["path"],  # File âm thanh
                    "-c:v", "copy",  # Giữ nguyên video
                    "-c:a", "aac",  # Audio codec
                    "-b:a", "192k",  # Audio bitrate
                    "-shortest",  # Cắt theo file ngắn nhất
                    video_with_audio
                ]
                
                # Thực thi lệnh thêm âm thanh
                logger.info("Đang thêm âm thanh vào video...")
                self._run_ffmpeg_command(cmd_add_audio)
                
                # Nếu có file nhạc nền, thêm vào
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
                final_video = video_with_audio
                if background_music and os.path.exists(background_music):
                    logger.info(f"Thêm nhạc nền: {background_music}")
                    
                    final_video_with_bg = os.path.join(temp_dir, "final_video.mp4")
                    
                    # Lệnh trộn nhạc nền
                    cmd_add_bg_music = [
                        self.ffmpeg_path,
                        "-y",
                        "-i", video_with_audio,  # Video với âm thanh chính
                        "-i", background_music,  # File nhạc nền
                        "-filter_complex", f"[1:a]volume={self.background_music_volume}[bg]; [0:a][bg]amix=inputs=2:duration=shortest",  # Trộn âm thanh
                        "-c:v", "copy",  # Giữ nguyên video
                        final_video_with_bg
                    ]
                    
                    # Thực thi lệnh trộn nhạc nền
                    logger.info("Đang thêm nhạc nền...")
                    self._run_ffmpeg_command(cmd_add_bg_music)
                    
                    final_video = final_video_with_bg
                
                # Sao chép video cuối cùng vào thư mục đầu ra
                shutil.copy2(final_video, output_path)
                
                logger.info(f"Đã tạo video thành công: {output_path}")
                
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
            raise
    
    def _run_ffmpeg_command(self, command):
        """Thực thi lệnh FFmpeg và ghi log
        
        Args:
            command (list): Danh sách các tham số lệnh
            
        Raises:
            Exception: Nếu lệnh không thành công
        """
        try:
            logger.debug(f"Executing: {' '.join(command)}")
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # Đọc và ghi log output từ ffmpeg
            for line in process.stderr:
                if "time=" in line:  # Chỉ hiển thị dòng có thông tin tiến độ
                    logger.debug(line.strip())
            
            # Đợi quá trình hoàn thành
            process.wait()
            
            if process.returncode != 0:
                raise Exception(f"FFmpeg command failed with code {process.returncode}")
            
        except Exception as e:
            logger.error(f"Lỗi khi thực thi lệnh FFmpeg: {str(e)}")
            raise
    
    def _save_video_info(self, output_path, title, images, audio_files, script):
        """Lưu thông tin video vào file JSON"""
        video_info = {
            "title": title,
            "creation_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "video_path": output_path,
            "script": {
                "title": script["title"],
                "scenes_count": len(script.get("scenes", []))
            },
            "stats": {
                "images_count": len(images),
                "audio_files_count": len(audio_files),
                "duration": self._calculate_total_duration(images)
            }
        }
        
        # Lưu thông tin
        info_path = os.path.join(self.output_dir, f"video_info_{os.path.basename(output_path).split('.')[0]}.json")
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(video_info, f, indent=4, ensure_ascii=False)
        
        logger.info(f"Đã lưu thông tin video tại: {info_path}")
    
    def _calculate_total_duration(self, images):
        """Tính tổng thời lượng dựa trên hình ảnh"""
        total_duration = 0
        
        for img in images:
            if img["type"] == "intro":
                total_duration += self.intro_duration
            elif img["type"] == "outro":
                total_duration += self.outro_duration
            else:
                total_duration += img.get("duration", self.img_duration)
        
        return total_duration

# Test module nếu chạy trực tiếp
if __name__ == "__main__":
    try:
        # Import các module khác để test
        sys.path.insert(0, project_root)
        
        from src.news_scraper import NewsScraper
        from src.script_generator import ScriptGenerator
        from src.image_generator import ImageGenerator
        from src.voice_generator import VoiceGenerator
        
        # Tìm dữ liệu test trong thư mục temp
        temp_files = os.listdir(TEMP_DIR)
        script_files = [f for f in temp_files if f.startswith("script_") and f.endswith(".json")]
        image_files = [f for f in temp_files if f.startswith("images_") and f.endswith(".json")]
        
        if script_files and image_files:
            # Lấy file mới nhất
            script_file = sorted(script_files)[-1]
            image_file = sorted(image_files)[-1]
            
            # Đọc dữ liệu
            script_path = os.path.join(TEMP_DIR, script_file)
            image_path = os.path.join(TEMP_DIR, image_file)
            
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            
            with open(image_path, "r", encoding="utf-8") as f:
                image_data = json.load(f)
            
            # Tìm file audio nếu có
            audio_dir = os.path.join(TEMP_DIR, "audio")
            if os.path.exists(audio_dir):
                audio_projects = [d for d in os.listdir(audio_dir) if d.startswith("project_")]
                if audio_projects:
                    # Lấy project mới nhất
                    audio_project = sorted(audio_projects)[-1]
                    audio_project_dir = os.path.join(audio_dir, audio_project)
                    
                    # Tìm file audio_info.json
                    audio_info_path = os.path.join(audio_project_dir, "audio_info.json")
                    if os.path.exists(audio_info_path):
                        with open(audio_info_path, "r", encoding="utf-8") as f:
                            audio_info = json.load(f)
                        
                        # Lấy danh sách file audio
                        audio_files = []
                        for audio in audio_info.get("audio_files", []):
                            audio["path"] = os.path.join(audio_project_dir, audio["rel_path"])
                            audio_files.append(audio)
                        
                        # Nếu có dữ liệu, tạo video
                        if audio_files:
                            # Chuyển đổi image_data thành định dạng phù hợp
                            images = []
                            for img in image_data:
                                # Tìm thư mục chứa ảnh
                                image_dirs = [d for d in os.listdir(os.path.join(TEMP_DIR, "images")) if d.startswith("project_")]
                                if image_dirs:
                                    image_dir = sorted(image_dirs)[-1]
                                    img["path"] = os.path.join(TEMP_DIR, "images", image_dir, img["filename"])
                                    images.append(img)
                            
                            # Tạo video
                            if images:
                                editor = VideoEditor()
                                output_path = editor.create_video(images, audio_files, script)
                                print(f"Đã tạo video thành công: {output_path}")
                            else:
                                print("Không tìm thấy đường dẫn hình ảnh phù hợp")
                        else:
                            print("Không tìm thấy file audio phù hợp")
                    else:
                        print(f"Không tìm thấy file audio_info.json trong {audio_project_dir}")
                else:
                    print("Không tìm thấy project audio nào")
            else:
                print(f"Không tìm thấy thư mục audio: {audio_dir}")
        else:
            print("Không tìm thấy dữ liệu test trong thư mục temp")
    except Exception as e:
        print(f"Lỗi khi chạy test: {str(e)}")