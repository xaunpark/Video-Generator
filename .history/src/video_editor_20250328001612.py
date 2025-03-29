# src/video_editor.py
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
        self.fps = 60  # Tăng fps lên 60 để có chuyển động mượt mà hơn
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
    
    def _prepare_image_with_effects(self, image_path, output_dir, index, img_type=None, duration=None):
        """Chuẩn bị hình ảnh với hiệu ứng Ken Burns và Blur Background với chuyển động mượt mà
        
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
            
            # Tạo hiệu ứng Ken Burns và Blur Background
            # Chọn ngẫu nhiên các tham số cho hiệu ứng Ken Burns
            # Nhưng giữ trong phạm vi hợp lý và giảm biên độ chuyển động
            zoom_start = 1.0
            zoom_end = random.uniform(1.05, 1.08)  # Giảm mức zoom để ít giật hơn
            
            # Chọn hướng di chuyển ngẫu nhiên 
            # Giảm biên độ di chuyển x, y để chuyển động tinh tế hơn
            x_start = 0
            y_start = 0
            x_end = random.uniform(-0.03, 0.03)  # Giảm biên độ di chuyển
            y_end = random.uniform(-0.03, 0.03)  # Giảm biên độ di chuyển
            
            # Thêm tính trơn tru cho chuyển động bằng nội suy sin
            # Sử dụng biểu thức sin để có hiệu ứng chuyển động bắt đầu và kết thúc mượt mà
            easing_expression = f"'if(gte(on,{self.fps*duration}),{zoom_end},{zoom_start}+(({zoom_end}-{zoom_start})*sin(PI*on/({self.fps*duration}*2)))'"
            pos_easing_x = f"'iw/2+iw*{x_start}+iw*({x_end}-{x_start})*sin(PI*on/({self.fps*duration}*2))'"
            pos_easing_y = f"'ih/2+ih*{y_start}+ih*({y_end}-{y_start})*sin(PI*on/({self.fps*duration}*2))'"
            
            # Lệnh FFmpeg để tạo hiệu ứng
            # Sử dụng cấu trúc đơn giản nhất (phương án B) nhưng thêm các tham số để cải thiện mượt mà
            command = [
                self.ffmpeg_path,
                "-y",
                "-loop", "1",
                "-i", image_path,
                "-t", str(duration),
                "-filter_complex",
                # Phần filter với các thay đổi để chuyển động mượt mà hơn:
                # 1. Tạo nền blur từ hình ảnh gốc (nhưng giảm mức độ blur)
                # 2. Áp dụng hiệu ứng Ken Burns với easing function
                # 3. Tăng fps và thêm frame interpolation
                f"[0:v]split=2[bg][fg]; "
                f"[bg]scale={self.width*2}:{self.height*2},boxblur=7:2,crop={self.width}:{self.height}:((in_w-{self.width})/2):((in_h-{self.height})/2)[blurred]; "
                f"[fg]scale='min({self.width}*0.9,iw)':'min({self.height}*0.9,ih)':force_original_aspect_ratio=decrease,"
                f"zoompan=z={easing_expression}:x={pos_easing_x}:y={pos_easing_y}:d={self.fps*duration}:s={self.width}x{self.height}[ken]; "
                f"[blurred][ken]overlay=(W-w)/2:(H-h)/2:format=auto,minterpolate='mi_mode=mci:mc_mode=aobmc:me_mode=bidir:mb_size=16:vsbmc=1:fps={self.fps}'",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", str(self.fps),
                "-preset", "medium",  # Dùng preset medium để tốc độ xử lý nhanh hơn
                "-crf", "22",  # Chất lượng khá tốt với kích thước file hợp lý
                "-tune", "film",  # Tối ưu hóa cho nội dung phim
                output_path
            ]
            
            # Thực thi lệnh
            if self._run_ffmpeg_command(command):
                logger.info(f"Đã tạo hiệu ứng cho hình ảnh: {output_path}")
                return output_path
            else:
                # Nếu không thành công, thử với cấu hình đơn giản hơn nhưng vẫn mượt
                logger.warning(f"Không thể tạo hiệu ứng phức tạp cho {image_path}, thử với hiệu ứng đơn giản hơn")
                
                # Phương án B với hiệu ứng đơn giản hơn nhưng vẫn mượt
                # Loại bỏ minterpolate và đơn giản hóa các bộ lọc
                command_simple = [
                    self.ffmpeg_path,
                    "-y",
                    "-loop", "1",
                    "-i", image_path,
                    "-t", str(duration),
                    "-filter_complex",
                    # Chỉ áp dụng hiệu ứng zoom đơn giản với easing
                    f"zoompan=z='1+(0.05*sin(PI*on/({self.fps*duration}*2)))':d={self.fps*duration}:s={self.width}x{self.height}",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-r", str(self.fps),
                    "-preset", "medium",
                    "-crf", "22",
                    output_path
                ]
                
                if self._run_ffmpeg_command(command_simple):
                    logger.info(f"Đã tạo hiệu ứng đơn giản cho hình ảnh: {output_path}")
                    return output_path
                else:
                    # Thử phương án cực kỳ đơn giản
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
    
    def create_video(self, images, audio_files, script, background_music=None):
        """
        Tạo video từ hình ảnh và âm thanh sử dụng FFmpeg (cải tiến với hiệu ứng Ken Burns và Blur Background)
        
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
                    
                    # Xử lý hình ảnh với hiệu ứng
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