# test_slow_motion.py
import os
import subprocess
import logging
import shutil
import sys
import time

# -- Thêm thư mục gốc vào sys.path để import các module src và config --
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# ---------------------------------------------------------------------

from src.video_editor import VideoEditor
from config.settings import TEMP_DIR, VIDEO_SETTINGS

# --- CẤU HÌNH ---
# Đặt logging level thành DEBUG để xem chi tiết các lệnh ffmpeg và thông báo
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SlowMotionTest")

# Thời lượng mong muốn (giả lập audio duration)
TARGET_DURATION_SECONDS = 10.0
# Thời lượng của video clip test (phải nằm trong khoảng slow_motion_min_ratio * TARGET_DURATION_SECONDS và TARGET_DURATION_SECONDS)
TEST_VIDEO_DURATION_SECONDS = 8.0 # 8 giây (là 80% của 10 giây, khớp với min_ratio mặc định 0.8)

# Đường dẫn thư mục test
TEST_ASSETS_DIR = os.path.join(TEMP_DIR, "slow_motion_test_assets")
TEST_OUTPUT_DIR = os.path.join(TEMP_DIR, "slow_motion_test_output")

# Đường dẫn file test
TEST_VIDEO_PATH = os.path.join(TEST_ASSETS_DIR, f"test_video_{int(TEST_VIDEO_DURATION_SECONDS)}s.mp4")
TEST_AUDIO_PATH = os.path.join(TEST_ASSETS_DIR, f"test_audio_{int(TARGET_DURATION_SECONDS)}s.mp3")
TEST_OUTPUT_VIDEO_PATH = os.path.join(TEST_OUTPUT_DIR, "processed_scene_slowmo.mp4")
# -----------------

def create_test_assets(ffmpeg_path):
    """Tạo file video và audio test bằng ffmpeg nếu chưa tồn tại."""
    os.makedirs(TEST_ASSETS_DIR, exist_ok=True)
    logger.info(f"Thư mục test assets: {TEST_ASSETS_DIR}")

    # 1. Tạo video test ngắn (8 giây, 720p, màu xanh)
    if not os.path.exists(TEST_VIDEO_PATH) or os.path.getsize(TEST_VIDEO_PATH) < 1000:
        logger.info(f"Đang tạo video test ({TEST_VIDEO_DURATION_SECONDS}s): {TEST_VIDEO_PATH}")
        try:
            video_cmd = [
                ffmpeg_path, "-y",
                "-f", "lavfi", "-i", f"color=c=blue:s={VIDEO_SETTINGS['width']}x{VIDEO_SETTINGS['height']}:d={TEST_VIDEO_DURATION_SECONDS}",
                "-vf", f"fps={VIDEO_SETTINGS['fps']}", # Đặt fps
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-an", # Không có audio
                TEST_VIDEO_PATH
            ]
            logger.debug(f"Executing: {' '.join(video_cmd)}")
            subprocess.run(video_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info("Tạo video test thành công.")
        except Exception as e:
            logger.error(f"Lỗi khi tạo video test: {e}", exc_info=True)
            return False
    else:
        logger.info(f"Video test đã tồn tại: {TEST_VIDEO_PATH}")

    # 2. Tạo audio test dài hơn (10 giây, im lặng)
    if not os.path.exists(TEST_AUDIO_PATH) or os.path.getsize(TEST_AUDIO_PATH) < 100:
        logger.info(f"Đang tạo audio test ({TARGET_DURATION_SECONDS}s): {TEST_AUDIO_PATH}")
        try:
            audio_cmd = [
                ffmpeg_path, "-y",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(TARGET_DURATION_SECONDS),
                "-c:a", "aac", "-b:a", "128k", # Sử dụng aac cho mp4 container
                TEST_AUDIO_PATH.replace(".mp3", ".m4a") # Tạm thời dùng m4a cho anullsrc
            ]
            logger.debug(f"Executing: {' '.join(audio_cmd)}")
            subprocess.run(audio_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Đổi tên lại thành mp3 nếu cần (mặc dù m4a cũng được ffmpeg đọc)
            if os.path.exists(TEST_AUDIO_PATH.replace(".mp3", ".m4a")):
                 shutil.move(TEST_AUDIO_PATH.replace(".mp3", ".m4a"), TEST_AUDIO_PATH)

            logger.info("Tạo audio test thành công.")
        except Exception as e:
            logger.error(f"Lỗi khi tạo audio test: {e}", exc_info=True)
            # Thử tạo file mp3 nếu m4a lỗi
            try:
                 audio_cmd_mp3 = [
                    ffmpeg_path, "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", str(TARGET_DURATION_SECONDS),
                    "-c:a", "libmp3lame", "-b:a", "128k", # codec mp3
                    TEST_AUDIO_PATH
                ]
                 logger.debug(f"Executing (MP3 fallback): {' '.join(audio_cmd_mp3)}")
                 subprocess.run(audio_cmd_mp3, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 logger.info("Tạo audio test thành công (MP3 fallback).")
            except Exception as e2:
                 logger.error(f"Lỗi khi tạo audio test (MP3 fallback): {e2}", exc_info=True)
                 return False

    else:
        logger.info(f"Audio test đã tồn tại: {TEST_AUDIO_PATH}")

    return True


def run_slow_motion_test():
    """Chạy kiểm tra tính năng slow motion."""
    logger.info("--- Bắt đầu Test Slow Motion ---")
    os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)

    try:
        # 1. Khởi tạo VideoEditor (sẽ tìm ffmpeg và ffprobe)
        logger.info("Khởi tạo VideoEditor...")
        video_editor = VideoEditor()
        logger.info("VideoEditor đã khởi tạo.")

        # 2. Tạo test assets
        logger.info("Kiểm tra/Tạo test assets...")
        if not create_test_assets(video_editor.ffmpeg_path):
            logger.error("Không thể tạo test assets. Dừng kiểm tra.")
            return
        logger.info("Test assets đã sẵn sàng.")

        # 3. Chuẩn bị media_item giả lập
        media_item = {
            "type": "video",
            "media_type": "scene", # Giả lập là một scene
            "number": 99,         # Số scene giả lập
            "path": TEST_VIDEO_PATH, # Đường dẫn đến video NGẮN
            "duration": TARGET_DURATION_SECONDS # Thời lượng MONG MUỐN (từ audio)
        }
        logger.info(f"Media item cho test: {media_item}")

        # 4. Gọi process_scene_media
        logger.info(f"Gọi process_scene_media cho video '{os.path.basename(TEST_VIDEO_PATH)}' với target duration {TARGET_DURATION_SECONDS}s...")
        start_time = time.time()
        processed_path = video_editor.process_scene_media(
            media_item,
            TEST_AUDIO_PATH,          # Đường dẫn đến audio DÀI
            TEST_OUTPUT_VIDEO_PATH
        )
        end_time = time.time()
        logger.info(f"process_scene_media thực thi trong {end_time - start_time:.2f} giây.")

        # 5. Kiểm tra kết quả
        if processed_path and os.path.exists(processed_path):
            logger.info(f"Xử lý thành công, file output: {processed_path}")

            # Kiểm tra thời lượng output bằng ffprobe
            output_duration = video_editor._get_video_duration_ffprobe(processed_path)

            if output_duration is not None:
                logger.info(f"Thời lượng video output đo được: {output_duration:.2f}s")
                # Kiểm tra xem có khớp với target duration không (cho phép sai số nhỏ)
                if abs(output_duration - TARGET_DURATION_SECONDS) < 0.1:
                    logger.info(">>> THÀNH CÔNG: Thời lượng video output khớp với target duration!")
                    logger.info(">>> Hãy kiểm tra log DEBUG ở trên để tìm dòng 'Applying slow motion'.")
                else:
                    logger.error(f">>> THẤT BẠI: Thời lượng video output ({output_duration:.2f}s) KHÔNG khớp với target duration ({TARGET_DURATION_SECONDS:.2f}s).")
            else:
                logger.warning("Không thể kiểm tra thời lượng video output bằng ffprobe.")

        else:
            logger.error(">>> THẤT BẠI: process_scene_media không trả về đường dẫn hợp lệ hoặc file output không tồn tại.")

    except FileNotFoundError as fnf_error:
         logger.error(f"Lỗi không tìm thấy file (ffmpeg/ffprobe?): {fnf_error}")
    except Exception as e:
        logger.error(f"Lỗi không mong muốn xảy ra: {e}", exc_info=True)

    finally:
        logger.info("--- Kết thúc Test Slow Motion ---")
        # Dọn dẹp (tùy chọn, comment nếu muốn giữ file để kiểm tra thủ công)
        # logger.info("Dọn dẹp file test...")
        # if os.path.exists(TEST_ASSETS_DIR):
        #     shutil.rmtree(TEST_ASSETS_DIR, ignore_errors=True)
        # if os.path.exists(TEST_OUTPUT_DIR):
        #      shutil.rmtree(TEST_OUTPUT_DIR, ignore_errors=True)
        # logger.info("Đã dọn dẹp.")


if __name__ == "__main__":
    run_slow_motion_test()