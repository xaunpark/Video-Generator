# test_youtube_upload.py
import datetime
import os
import sys
import logging
import time
import subprocess # Cần cho việc tạo dummy video
import shutil     # Cần cho việc tìm ffmpeg
from dotenv import load_dotenv
from pathlib import Path # Sử dụng Path cho đường dẫn

# --- Setup Đường dẫn và Logging ---
# Thêm thư mục gốc vào sys.path để import hoạt động đúng
try:
    # __file__ là đường dẫn đến test_youtube_upload.py hiện tại
    # .parent là thư mục gốc project
    project_root = Path(__file__).resolve().parent
except NameError:
    # Fallback nếu __file__ không tồn tại (ví dụ: chạy tương tác)
    project_root = Path('.').resolve()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('upload_test.log', encoding='utf-8') # Log riêng, dùng utf-8
    ]
)
logger = logging.getLogger("YouTubeUploadTest")

# --- Tải Biến Môi trường ---
# Đảm bảo tải file .env từ thư mục gốc project
dotenv_path = project_root / '.env'
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    logger.info(f"Loaded environment variables from: {dotenv_path}")
else:
    load_dotenv() # Thử tải từ vị trí mặc định
    logger.warning(f".env file not found at project root ({dotenv_path}). Attempting load from default locations.")


# --- Import Các Thành phần Cần thiết ---
try:
    from src.youtube_uploader import YouTubeUploader
    # Import đường dẫn tuyệt đối và refresh token từ credentials
    from config.credentials import YOUTUBE_CLIENT_SECRETS_FILE_PATH, YOUTUBE_REFRESH_TOKEN
    from config.settings import YOUTUBE_SETTINGS, OUTPUT_DIR # Import OUTPUT_DIR
except ImportError as e:
    logger.critical(f"Failed to import necessary modules: {e}")
    logger.critical("Please ensure the project structure is correct (e.g., you are running from the project root) and all dependencies are installed ('pip install -r requirements.txt').")
    sys.exit(1) # Thoát nếu không import được

# --- === THÔNG TIN VIDEO CẦN UPLOAD === ---
# Sử dụng OUTPUT_DIR để tạo đường dẫn động
# VIDEO_FILENAME_TO_UPLOAD = "test_video.mp4" # Tên file bạn muốn test
# VIDEO_TO_UPLOAD = OUTPUT_DIR / VIDEO_FILENAME_TO_UPLOAD
# HOẶC đặt đường dẫn cứng nếu bạn muốn test file cụ thể đó:
VIDEO_TO_UPLOAD = project_root / "output" / "test_video.mp4" # Đường dẫn ĐẦY ĐỦ tới video
# --- ================================== ---

# --- Hàm tạo dummy video (nếu cần) ---
def create_dummy_video(output_path: Path):
    """Tạo một file video MP4 nhỏ để test upload."""
    # Chuyển Path thành string để dùng với os.path và subprocess
    output_path_str = str(output_path)

    if os.path.exists(output_path_str):
        logger.info(f"Dummy video already exists: {output_path_str}")
        return True

    logger.info(f"Attempting to create dummy video file: {output_path_str}")
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        logger.error("ffmpeg command not found in system PATH. Cannot create dummy video.")
        print("ERROR: ffmpeg not found. Please install ffmpeg and add it to your system PATH.")
        return False
    try:
        ffmpeg_cmd = [
            ffmpeg_path, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=5:size=640x360:rate=24",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k",
            "-shortest",
            output_path_str # Truyền đường dẫn dạng string
        ]
        logger.debug(f"Running ffmpeg command: {' '.join(ffmpeg_cmd)}")
        result = subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        # Log stderr nếu có gì đó bất thường, ngay cả khi thành công
        if result.stderr:
            logger.debug(f"ffmpeg stderr (might contain warnings): {result.stderr}")

        if os.path.exists(output_path_str) and os.path.getsize(output_path_str) > 1000:
             logger.info(f"Dummy video created successfully at: {output_path_str}")
             return True
        else:
             logger.error("Failed to create dummy video file (file missing or too small after ffmpeg run).")
             print("ERROR: Failed to create dummy video.")
             return False
    except FileNotFoundError:
         logger.error("ffmpeg command failed (FileNotFound). Ensure ffmpeg is correctly installed and in PATH.")
         print("ERROR: ffmpeg command failed. Is it installed and in PATH?")
         return False
    except subprocess.CalledProcessError as e:
         logger.error(f"ffmpeg failed to create dummy video. Return code: {e.returncode}")
         logger.error(f"ffmpeg stderr: {e.stderr}")
         print(f"ERROR: ffmpeg failed. Check logs ({logger.root.handlers[-1].baseFilename if logger.root.handlers else 'console'}) for details.")
         return False
    except Exception as ffmpeg_err:
         logger.error(f"An unexpected error occurred creating dummy video: {ffmpeg_err}", exc_info=True)
         print(f"ERROR: Unexpected error creating dummy video: {ffmpeg_err}")
         return False

def run_upload_test():
    """Hàm chính để chạy test upload."""
    logger.info("--- Starting YouTube Upload Test ---")

    # 1. Kiểm tra/Tạo file video test
    video_path_to_use = VIDEO_TO_UPLOAD
    video_path_to_use_str = str(video_path_to_use) # Dùng dạng string cho các hàm os.path
    is_dummy_created = False # Cờ để biết có cần xóa dummy không

    if not os.path.exists(video_path_to_use_str):
        logger.warning(f"Specified video file does not exist: {video_path_to_use_str}")
        logger.info("Attempting to create a dummy video for testing instead.")
        # Tạo dummy trong thư mục output nếu có thể, nếu không thì tạo ở thư mục gốc
        dummy_output_dir = OUTPUT_DIR if OUTPUT_DIR and os.path.isdir(OUTPUT_DIR) else project_root
        dummy_path = dummy_output_dir / "dummy_youtube_upload_test.mp4"

        if create_dummy_video(dummy_path):
            video_path_to_use = dummy_path
            video_path_to_use_str = str(video_path_to_use)
            is_dummy_created = True
        else:
            print(f"ERROR: Could not find or create a video file for testing.")
            logger.critical("Aborting test: No video file available.")
            return # Thoát nếu không có video

    logger.info(f"Using video file for upload: {video_path_to_use_str}")

    # 2. Kiểm tra Credentials (đọc từ config.credentials)
    secrets_path_str = str(YOUTUBE_CLIENT_SECRETS_FILE_PATH) # Chuyển Path object thành string
    if not secrets_path_str or not os.path.exists(secrets_path_str):
        logger.error(f"YouTube client secrets file path is invalid or file not found: {secrets_path_str}")
        print(f"ERROR: Client secrets file missing or path invalid. Check config/credentials.py and .env.")
        return
    if not YOUTUBE_REFRESH_TOKEN:
        logger.error("YOUTUBE_REFRESH_TOKEN not found in environment variables.")
        print("ERROR: YOUTUBE_REFRESH_TOKEN is missing in your .env file.")
        print("Please run 'get_refresh_token.py' first and ensure it's in .env.")
        return

    logger.info(f"Using Client Secrets File Path: {secrets_path_str}")
    logger.info(f"Using Refresh Token: {YOUTUBE_REFRESH_TOKEN[:10]}...")

    # 3. Chuẩn bị Metadata cho YouTube
    try:
        video_filename = os.path.basename(video_path_to_use_str)
        yt_title = f"API Test (Secrets File): {video_filename} - {time.strftime('%Y%m%d_%H%M%S')}" # Đổi title để phân biệt

        yt_description = f"Automated test upload via Python script (using secrets file method).\n" \
                         f"File: {video_filename}\n" \
                         f"Timestamp: {datetime.datetime.now().isoformat()}"

        yt_tags = ["api test", "python", "secrets file", "automation"]
        default_tags = YOUTUBE_SETTINGS.get("tags", [])
        if isinstance(default_tags, list): yt_tags.extend(default_tags)
        yt_tags = list(set(yt_tags)) # Loại bỏ trùng lặp

        yt_category_id = YOUTUBE_SETTINGS.get("category_id", "28") # Science & Technology
        yt_privacy_status = "private" # !!! LUÔN DÙNG "private" KHI TEST !!!
        yt_language = YOUTUBE_SETTINGS.get("default_language", "en")

        logger.info(f"Video Title: {yt_title}")
        logger.info(f"Privacy Status: {yt_privacy_status}")
        logger.info(f"Category ID: {yt_category_id}")

    except Exception as e:
        logger.error(f"Error preparing video metadata: {e}", exc_info=True)
        print("ERROR: Could not prepare video metadata.")
        return

    # 4. Khởi tạo và Thực hiện Upload
    uploader = None
    try:
        logger.info("Initializing YouTubeUploader...")
        # Khởi tạo với đường dẫn file secrets và refresh token
        uploader = YouTubeUploader(
            client_secrets_file_path=secrets_path_str, # Truyền đường dẫn dạng string
            refresh_token=YOUTUBE_REFRESH_TOKEN
        )

        # Kiểm tra lại client sau khi khởi tạo
        if not uploader.youtube_client:
             logger.error("YouTube client could not be initialized within YouTubeUploader. Check credentials and logs in upload_test.log.")
             print("ERROR: Failed to initialize YouTube connection (Check logs).")
             return

        logger.info(f"Starting upload of: {video_path_to_use_str}")
        youtube_video_id = uploader.upload_video(
            video_path=video_path_to_use_str,
            title=yt_title,
            description=yt_description,
            tags=yt_tags,
            category_id=yt_category_id,
            privacy_status=yt_privacy_status,
            language=yt_language
        )

        if youtube_video_id:
            logger.info(f"--- YouTube Upload Successful! ---")
            print(f"\n--- TEST SUCCESS ---")
            print(f"Video ID: {youtube_video_id}")
            print(f"Watch Link: https://www.youtube.com/watch?v={youtube_video_id}")
            print(f"Studio Link: https://studio.youtube.com/video/{youtube_video_id}/edit")
        else:
            logger.error("--- YouTube Upload Failed ---")
            print("\n--- TEST FAILED ---")
            print("Upload failed. Please check the application logs (upload_test.log) for more details.")

    except (FileNotFoundError, ValueError) as init_err:
        # Bắt lỗi từ __init__ của Uploader
        logger.error(f"Upload initialization failed: {init_err}")
        print(f"ERROR: Initialization failed - {init_err}")
    except Exception as upload_err:
        logger.error(f"An unexpected error occurred during the upload test: {upload_err}", exc_info=True)
        print(f"ERROR: An unexpected error occurred: {upload_err}")

    finally:
        # Clean up dummy video nếu nó được tạo ra
        if is_dummy_created and os.path.exists(video_path_to_use_str):
             try:
                  os.remove(video_path_to_use_str)
                  logger.info(f"Removed dummy video file: {video_path_to_use_str}")
             except Exception as clean_err:
                  logger.warning(f"Could not remove dummy video file: {video_path_to_use_str} - Error: {clean_err}")

    logger.info("--- YouTube Upload Test Finished ---")


if __name__ == "__main__":
    run_upload_test()