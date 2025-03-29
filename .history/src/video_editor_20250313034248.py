# src/video_editor.py
import os
os.environ["IMAGEIO_FFMPEG_EXE"] = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ffmpeg.exe")
# os.environ["IMAGEIO_FFMPEG_EXE"] = "I:/VS Project/Video-Generator/ffmpeg.exe"
import sys
import logging
import time
import json
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
        
        # Kiểm tra MoviePy
        self._check_moviepy()
    
    def _check_moviepy(self):
        """Kiểm tra thư viện MoviePy"""
        try:
            import moviepy.editor as mp
            logger.info("Đã nhập thư viện MoviePy thành công")
        except ImportError:
            logger.error("Không thể nhập thư viện MoviePy. Hãy cài đặt với lệnh 'pip install moviepy'")
            raise
    
    def create_video(self, images, audio_files, script, background_music=None):
        """
        Tạo video từ hình ảnh và âm thanh
        
        Args:
            images (list): Danh sách thông tin hình ảnh
            audio_files (list): Danh sách thông tin file âm thanh
            script (dict): Thông tin kịch bản
            background_music (str, optional): Đường dẫn đến file nhạc nền
            
        Returns:
            str: Đường dẫn đến file video đã tạo
        """
        import moviepy.editor as mp
        
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_filename = f"news_video_{timestamp}.{self.video_format}"
            output_path = os.path.join(self.output_dir, output_filename)
            
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
            
            # Tạo video từ danh sách hình ảnh và âm thanh
            clips = []
            
            # Sắp xếp hình ảnh theo thứ tự
            intro_images = [img for img in images if img["type"] == "intro"]
            scene_images = sorted([img for img in images if img["type"] == "scene"], key=lambda x: x["number"])
            outro_images = [img for img in images if img["type"] == "outro"]
            
            all_images = intro_images + scene_images + outro_images
            
            # Tạo clip cho mỗi hình ảnh
            audio_track = mp.AudioFileClip(full_audio["path"])
            total_audio_duration = audio_track.duration
            
            current_audio_position = 0
            for i, img in enumerate(all_images):
                # Xác định thời lượng cho clip
                if img["type"] == "intro":
                    duration = self.intro_duration
                elif img["type"] == "outro":
                    duration = self.outro_duration
                else:
                    duration = img.get("duration", self.img_duration)
                
                # Giới hạn thời lượng để không vượt quá audio
                if current_audio_position + duration > total_audio_duration:
                    duration = max(0, total_audio_duration - current_audio_position)
                
                if duration <= 0:
                    continue
                
                # Tạo clip hình ảnh
                img_clip = mp.ImageClip(img["path"]).set_duration(duration)
                
                # Điều chỉnh kích thước để phù hợp với video
                img_clip = img_clip.resize(height=self.height)
                if img_clip.w > self.width:
                    img_clip = img_clip.resize(width=self.width)
                
                # Căn giữa clip
                img_clip = img_clip.set_position(("center", "center"))
                
                # Tạo background màu đen
                bg_clip = mp.ColorClip(size=(self.width, self.height), color=(0, 0, 0)).set_duration(duration)
                
                # Gộp clip hình ảnh với background
                comp_clip = mp.CompositeVideoClip([bg_clip, img_clip])
                
                # Thêm vào danh sách clips
                clips.append(comp_clip)
                
                # Cập nhật vị trí audio hiện tại
                current_audio_position += duration
            
            # Ghép tất cả các clip thành video
            final_clip = mp.concatenate_videoclips(clips)
            
            # Thêm audio track
            final_clip = final_clip.set_audio(audio_track)
            
            # Thêm nhạc nền (nếu có)
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
            
            # Thêm nhạc nền nếu có
            if background_music and os.path.exists(background_music):
                logger.info(f"Thêm nhạc nền: {background_music}")
                bg_music = mp.AudioFileClip(background_music)
                
                # Lặp lại nhạc nếu cần
                if bg_music.duration < final_clip.duration:
                    bg_music = bg_music.fx(mp.vfx.loop, duration=final_clip.duration)
                
                # Cắt nhạc nền nếu dài hơn video
                bg_music = bg_music.subclip(0, final_clip.duration)
                
                # Điều chỉnh âm lượng
                bg_music = bg_music.volumex(self.background_music_volume)
                
                # Trộn nhạc nền với âm thanh chính
                final_audio = mp.CompositeAudioClip([final_clip.audio, bg_music])
                final_clip = final_clip.set_audio(final_audio)
            
            # Ghi video ra file
            logger.info(f"Đang xuất video ra file: {output_path}")
            final_clip.write_videofile(
                output_path,
                fps=self.fps,
                codec="libx264",
                audio_codec="aac",
                threads=4,
                preset="medium",
                ffmpeg_params=["-crf", "22"]
            )
            
            # Đóng clip để giải phóng tài nguyên
            final_clip.close()
            if 'audio_track' in locals() and audio_track:
                audio_track.close()
            
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