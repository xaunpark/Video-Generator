#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test.py - Script kiểm tra quy trình tạo video từ bài viết

Script này thực hiện toàn bộ quy trình từ bài viết đến video tin tức,
bao gồm tạo script, phân tích scene, tìm ảnh/video, tạo audio và tạo video cuối cùng.
"""

import os
import sys
import time
import logging
import json
from datetime import datetime

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"test_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    ]
)
logger = logging.getLogger("video-test")

# Tìm config directory
base_dir = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(base_dir, "config")):
    # Thử đi lên một cấp
    base_dir = os.path.dirname(base_dir)

# Đảm bảo src và config được import
sys.path.append(base_dir)

try:
    # Kiểm tra các directory cần thiết
    for directory in ["src", "config", "temp", "assets"]:
        dir_path = os.path.join(base_dir, directory)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            logger.info(f"Đã tạo thư mục: {dir_path}")
    
    # Kiểm tra file cấu hình
    settings_path = os.path.join(base_dir, "config", "settings.py")
    if not os.path.exists(settings_path):
        logger.warning("Không tìm thấy file settings.py. Tạo file cấu hình mặc định...")
        with open(settings_path, 'w', encoding='utf-8') as f:
            f.write("""
# settings.py - Cấu hình mặc định

import os

# Thư mục dự án
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Thư mục temp
TEMP_DIR = os.path.join(BASE_DIR, "temp")

# Thư mục assets
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Cấu hình video
VIDEO_SETTINGS = {
    "width": 1920,
    "height": 1080,
    "fps": 24,
    "intro_duration": 5,
    "outro_duration": 5,
    "image_duration": 7,
    "enable_video_clips": True,
    "video_clip_duration": 7,
    "enable_transitions": True,
    "transition_types": ["fade"],
    "transition_duration": 0.8,
    "enable_ken_burns": True,
    "enable_background_music": False,
    "music_volume": 0.1,
    "cleanup_temp_files": False
}
""")
    
    # Kiểm tra file credentials
    credentials_path = os.path.join(base_dir, "config", "credentials.py")
    if not os.path.exists(credentials_path):
        logger.warning("Không tìm thấy file credentials.py. Tạo file credentials mẫu...")
        with open(credentials_path, 'w', encoding='utf-8') as f:
            f.write("""
# credentials.py - API Keys và thông tin đăng nhập

# OpenAI API Key
OPENAI_API_KEY = ""

# Serper.dev API Key
SERPER_API_KEY = ""

# Pexels API Key
PEXELS_API_KEY = ""

# Pixabay API Key
PIXABAY_API_KEY = ""
""")
        logger.warning("Hãy cập nhật API keys trong file config/credentials.py")
    
    # Import cấu hình
    from config.settings import TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS
    from config.credentials import OPENAI_API_KEY, SERPER_API_KEY, PEXELS_API_KEY, PIXABAY_API_KEY

    # Kiểm tra API keys
    missing_keys = []
    if not OPENAI_API_KEY:
        missing_keys.append("OPENAI_API_KEY")
    if not SERPER_API_KEY:
        missing_keys.append("SERPER_API_KEY")
    if VIDEO_SETTINGS.get("enable_video_clips", False) and not (PEXELS_API_KEY or PIXABAY_API_KEY):
        missing_keys.append("PEXELS_API_KEY hoặc PIXABAY_API_KEY")
    
    if missing_keys:
        logger.warning(f"Các API key sau đang thiếu: {', '.join(missing_keys)}")
        logger.warning("Một số tính năng có thể không hoạt động đúng. Hãy cập nhật trong config/credentials.py")
    
    # Kiểm tra xem các module cần thiết đã được cài đặt chưa
    try:
        import requests
        import moviepy.editor
        from PIL import Image
    except ImportError as e:
        logger.error(f"Thiếu module: {e}")
        logger.error("Chạy lệnh: pip install requests moviepy pillow để cài đặt các module cần thiết")
        sys.exit(1)
    
    # Tạo thư mục fonts nếu chưa có
    fonts_dir = os.path.join(ASSETS_DIR, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    
    # Tạo thư mục background_music nếu chưa có
    music_dir = os.path.join(ASSETS_DIR, "background_music")
    os.makedirs(music_dir, exist_ok=True)
    
    # Tạo thư mục fallback_images nếu chưa có
    fallback_dir = os.path.join(ASSETS_DIR, "fallback_images")
    os.makedirs(fallback_dir, exist_ok=True)
    
    # Bài viết mẫu để test
    test_article = {
        "title": "Climate Protests Sweep Through European Capitals",
        "content": """
        Thousands of climate activists gathered in major European capitals this weekend to demand stronger environmental policies. In Paris, protesters marched from the Arc de Triomphe to the Eiffel Tower, waving banners and chanting slogans. The London demonstration saw participants floating a large model of a burning Earth down the Thames River.
        
        Meanwhile, in Berlin, activists blocked traffic at Brandenburg Gate, creating a human chain that stretched for nearly a kilometer. Organizers claimed over 50,000 participants across all events, though official estimates were lower.
        
        Several celebrities joined the protests, adding visibility to the cause. Government officials from several countries promised to review current climate policies in response to the growing pressure.
        
        Scientists have warned that immediate action is necessary to prevent catastrophic climate change. Recent studies show that global temperatures continue to rise at an alarming rate, with 2024 on track to be the hottest year on record.
        
        Environmental groups are calling for more ambitious targets for reducing carbon emissions. They argue that current commitments under international agreements are insufficient to address the scale of the climate crisis.
        
        These protests come ahead of a major international climate conference scheduled for next month, where world leaders will discuss new environmental protection measures.
        """,
        "source": "Environmental News Network",
        "url": "https://example.com/climate-protests",
        "image_url": None  # Không có ảnh nguồn
    }
    
    # Thời gian bắt đầu
    start_time = time.time()
    logger.info("=== BẮT ĐẦU KIỂM TRA QUY TRÌNH TẠO VIDEO TIN TỨC ===")
    
    # 1. Khởi tạo các module
    try:
        logger.info("Khởi tạo các module...")
        
        # Script Generator
        from src.script_generator import ScriptGenerator
        script_generator = ScriptGenerator()
        logger.info("✓ Đã khởi tạo ScriptGenerator")
        
        # Image Generator
        from src.image_generator import ImageGenerator
        image_generator = ImageGenerator()
        logger.info("✓ Đã khởi tạo ImageGenerator")
        
        # Audio Generator
        try:
            from src.audio_generator import AudioGenerator
            audio_generator = AudioGenerator()
            logger.info("✓ Đã khởi tạo AudioGenerator")
        except Exception as e:
            logger.error(f"❌ Lỗi khởi tạo AudioGenerator: {str(e)}")
            logger.info("Tạo AudioGenerator đơn giản để test...")
            
            # Tạo class AudioGenerator giả lập
            class SimpleAudioGenerator:
                def generate_audio_for_script(self, script):
                    audio_dir = os.path.join(TEMP_DIR, f"audio_{int(time.time())}")
                    os.makedirs(audio_dir, exist_ok=True)
                    
                    # Tạo file audio trống
                    for scene in script.get('scenes', []):
                        scene_number = scene.get('number', 0)
                        audio_path = os.path.join(audio_dir, f"scene_{scene_number}.mp3")
                        with open(audio_path, 'wb') as f:
                            # Tạo file MP3 trống 5 giây
                            f.write(b'\x00' * 5000)
                    
                    # Tạo intro và outro audio
                    for name in ["intro", "outro"]:
                        audio_path = os.path.join(audio_dir, f"{name}.mp3")
                        with open(audio_path, 'wb') as f:
                            f.write(b'\x00' * 5000)
                    
                    return audio_dir
            
            audio_generator = SimpleAudioGenerator()
            logger.info("✓ Đã tạo SimpleAudioGenerator để test")
        
        # Video Generator
        from src.video_generator import VideoGenerator
        video_generator = VideoGenerator()
        logger.info("✓ Đã khởi tạo VideoGenerator")
        
    except Exception as e:
        logger.error(f"❌ Lỗi khởi tạo các module: {str(e)}", exc_info=True)
        sys.exit(1)
    
    # 2. Tạo script từ bài viết
    try:
        logger.info("\n=== BƯỚC 1: TẠO SCRIPT ===")
        script = script_generator.generate_script(test_article)
        
        if not script:
            logger.error("❌ Tạo script thất bại")
            sys.exit(1)
        
        num_scenes = len(script.get('scenes', []))
        logger.info(f"✓ Đã tạo script với {num_scenes} scenes")
        
        # Lưu script để kiểm tra
        script_path = os.path.join(TEMP_DIR, "test_script.json")
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        logger.info(f"✓ Đã lưu script vào: {script_path}")
        
        # Hiển thị một số scene mẫu
        for i, scene in enumerate(script.get('scenes', [])[:3]):
            logger.info(f"Scene {scene.get('number')}: {scene.get('content')[:100]}...")
            if i >= 2 and len(script.get('scenes', [])) > 3:
                logger.info(f"... và {len(script.get('scenes', [])) - 3} scene khác")
                break
    except Exception as e:
        logger.error(f"❌ Lỗi khi tạo script: {str(e)}", exc_info=True)
        sys.exit(1)
    
    # 3. Tìm media (ảnh/video) cho script
    try:
        logger.info("\n=== BƯỚC 2: TÌM MEDIA (ẢNH/VIDEO) ===")
        media_items = image_generator.generate_images_for_script(script)
        
        if not media_items:
            logger.error("❌ Tìm media thất bại")
            sys.exit(1)
        
        # Đếm số lượng ảnh và video
        num_images = sum(1 for item in media_items if item.get('type') == 'image')
        num_videos = sum(1 for item in media_items if item.get('type') == 'video')
        logger.info(f"✓ Đã tìm {len(media_items)} media items ({num_images} ảnh, {num_videos} video)")
        
        # Hiển thị thông tin một số media đầu tiên
        for i, item in enumerate(media_items[:5]):
            media_type = item.get('type', 'unknown')
            media_path = item.get('path', 'unknown')
            if os.path.exists(media_path):
                size_kb = os.path.getsize(media_path) / 1024
                logger.info(f"Media {i+1}: {media_type.upper()} - {os.path.basename(media_path)} ({size_kb:.1f} KB)")
            else:
                logger.warning(f"Media {i+1}: {media_type.upper()} - {os.path.basename(media_path)} (File không tồn tại)")
            
            if i >= 4 and len(media_items) > 5:
                logger.info(f"... và {len(media_items) - 5} media khác")
                break
    except Exception as e:
        logger.error(f"❌ Lỗi khi tìm media: {str(e)}", exc_info=True)
        sys.exit(1)
    
    # 4. Tạo audio cho script
    try:
        logger.info("\n=== BƯỚC 3: TẠO AUDIO ===")
        audio_dir = audio_generator.generate_audio_for_script(script)
        
        if not audio_dir or not os.path.exists(audio_dir):
            logger.error("❌ Tạo audio thất bại")
            sys.exit(1)
        
        # Đếm số file audio
        audio_files = [f for f in os.listdir(audio_dir) if f.endswith('.mp3')]
        logger.info(f"✓ Đã tạo {len(audio_files)} file audio trong thư mục: {audio_dir}")
        
        # Hiển thị thông tin các file audio
        for audio_file in audio_files[:5]:
            audio_path = os.path.join(audio_dir, audio_file)
            if os.path.exists(audio_path):
                size_kb = os.path.getsize(audio_path) / 1024
                logger.info(f"Audio: {audio_file} ({size_kb:.1f} KB)")
            else:
                logger.warning(f"Audio: {audio_file} (File không tồn tại)")
        
        if len(audio_files) > 5:
            logger.info(f"... và {len(audio_files) - 5} file audio khác")
    except Exception as e:
        logger.error(f"❌ Lỗi khi tạo audio: {str(e)}", exc_info=True)
        sys.exit(1)
    
    # 5. Tạo video cuối cùng
    try:
        logger.info("\n=== BƯỚC 4: TẠO VIDEO CUỐI CÙNG ===")
        output_dir = os.path.join(TEMP_DIR, "output")
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_video = os.path.join(output_dir, f"test_video_{timestamp}.mp4")
        
        logger.info(f"Đang tạo video: {output_video}")
        logger.info(f"Kích thước video: {VIDEO_SETTINGS['width']}x{VIDEO_SETTINGS['height']}")
        logger.info(f"FPS: {VIDEO_SETTINGS.get('fps', 24)}")
        
        result_video = video_generator.generate_video(script, media_items, audio_dir, output_video)
        
        if not result_video or not os.path.exists(result_video):
            logger.error("❌ Tạo video thất bại")
            sys.exit(1)
        
        video_size_mb = os.path.getsize(result_video) / (1024 * 1024)
        logger.info(f"✓ Đã tạo video thành công: {result_video} ({video_size_mb:.2f} MB)")
        
        # Trích xuất thumbnail
        thumbnail_path = video_generator.extract_thumbnail(result_video)
        if thumbnail_path and os.path.exists(thumbnail_path):
            logger.info(f"✓ Đã trích xuất thumbnail: {thumbnail_path}")
        
    except Exception as e:
        logger.error(f"❌ Lỗi khi tạo video: {str(e)}", exc_info=True)
        sys.exit(1)
    
    # Tính thời gian thực hiện
    end_time = time.time()
    duration = end_time - start_time
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    
    logger.info("\n=== KẾT QUẢ KIỂM TRA ===")
    logger.info(f"Tổng thời gian: {minutes} phút {seconds} giây")
    logger.info(f"Script: {script_path}")
    logger.info(f"Media: {len(media_items)} items ({num_images} ảnh, {num_videos} video)")
    logger.info(f"Audio: {len(audio_files)} files")
    logger.info(f"Video: {result_video} ({video_size_mb:.2f} MB)")
    logger.info(f"Kích thước: {VIDEO_SETTINGS['width']}x{VIDEO_SETTINGS['height']}, {VIDEO_SETTINGS.get('fps', 24)} FPS")
    
    logger.info("\n=== KIỂM TRA HOÀN TẤT ===")
    logger.info(f"Video được lưu tại: {result_video}")
    logger.info("Nếu video mở được và phát bình thường, quy trình đã hoạt động đúng!")

except Exception as e:
    logger.error(f"❌ Lỗi không mong muốn: {str(e)}", exc_info=True)
    sys.exit(1)