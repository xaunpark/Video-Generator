# test_chapter_card.py
import os
import sys
import time
import shutil
import logging

# --- Thêm đường dẫn gốc vào sys.path để import các module khác ---
# Giả định test_chapter_card.py nằm ở thư mục gốc project
project_root = os.path.abspath(os.path.dirname(__file__))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)
# --------------------------------------------------------------

# --- Import các thành phần cần thiết ---
from src.video_editor import VideoEditor
from config.settings import TEMP_DIR, VIDEO_SETTINGS, OUTPUT_DIR
from config.credentials import OPENAI_API_KEY # Cần cho việc lấy query nền (nếu dùng LLM)
# Đảm bảo các thư mục tồn tại
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
# ------------------------------------

# --- Cấu hình Logging ---
logging.basicConfig(level=logging.DEBUG, # Đặt DEBUG để xem log chi tiết
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ChapterCardTest")
# ------------------------

def run_chapter_card_test():
    logger.info("===== Starting Chapter Card Generation Test =====")

    # --- Dữ liệu giả lập cho việc test ---
    test_chapter_num = 1
    test_chapter_title = "Exploring the Depths: A New Beginning"
    test_card_duration = VIDEO_SETTINGS.get("chapter_title_duration", 2.5)
    # Query nền có thể lấy cứng hoặc gọi LLM nếu muốn test cả bước đó
    # test_background_query = "abstract flowing particles blue gold" # Query cứng
    test_project_id = f"test_card_{int(time.time())}"
    # Tạo thư mục tạm riêng cho lần test này
    test_temp_dir = os.path.join(TEMP_DIR, test_project_id)
    os.makedirs(test_temp_dir, exist_ok=True)
    # Đường dẫn file output cuối cùng cho card
    test_output_card_path = os.path.join(OUTPUT_DIR, f"chapter_{test_chapter_num}_card_test.mp4")
    # --------------------------------------

    try:
        # --- Khởi tạo VideoEditor ---
        logger.info("Initializing VideoEditor...")
        editor = VideoEditor()
        logger.info("VideoEditor Initialized.")

        # --- (Tùy chọn) Test việc lấy query nền bằng LLM ---
        # Bạn cần có script giả lập hoặc truyền thông tin cần thiết
        mock_script = {"title": "Test Video Title"}
        logger.info("Getting background query using LLM (if implemented)...")
        # Lưu ý: _get_all_card_background_queries trả về map, cần lấy query cụ thể
        # Hoặc gọi một hàm test riêng nếu _get_all_card_background_queries phức tạp
        # Tạm thời dùng query cứng để đơn giản hóa test card creation
        test_background_query = "abstract technology background"
        logger.info(f"Using background query: '{test_background_query}'")
        # ---------------------------------------------

        # --- Gọi trực tiếp hàm tạo card động ---
        logger.info(f"Attempting to create dynamic chapter card for Chapter {test_chapter_num}...")
        created_card_path = editor._create_dynamic_chapter_card(
            chapter_num=test_chapter_num,
            chapter_title=test_chapter_title,
            card_duration=test_card_duration,
            background_query=test_background_query,
            temp_project_dir=test_temp_dir, # Dùng thư mục tạm riêng của test
            output_video_path=test_output_card_path # Lưu trực tiếp vào output
        )
        # --------------------------------------

        # --- Kiểm tra kết quả ---
        if created_card_path and os.path.exists(created_card_path):
            logger.info(f"SUCCESS! Dynamic chapter card created at: {created_card_path}")
            duration = editor._get_video_duration_ffprobe(created_card_path)
            logger.info(f"  -> Final Card Duration: {duration:.3f}s (Target: {test_card_duration:.2f}s)")
            logger.info("Please manually check the video file for visual correctness (background, title, fade).")
        else:
            logger.error("FAILED to create the dynamic chapter card.")
            logger.error("Check the logs above for specific FFmpeg or other errors.")
        # -------------------------

    except FileNotFoundError as fnf_err:
         logger.error(f"ERROR: Required tool (like FFmpeg/ffprobe) not found: {fnf_err}")
    except ImportError as imp_err:
         logger.error(f"ERROR: Missing required library: {imp_err}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during the test: {e}", exc_info=True)
    finally:
        # --- Dọn dẹp thư mục tạm của test ---
        if os.path.exists(test_temp_dir):
             logger.info(f"Cleaning up test temporary directory: {test_temp_dir}")
             try:
                 # Đợi chút trước khi xóa
                 time.sleep(1)
                 shutil.rmtree(test_temp_dir, ignore_errors=True)
             except Exception as clean_err:
                 logger.warning(f"Could not completely cleanup test temp directory: {clean_err}")
        logger.info("===== Chapter Card Generation Test Finished =====")

# --- Chạy test khi file này được thực thi trực tiếp ---
if __name__ == "__main__":
    # Kiểm tra API Key trước khi chạy
    if not OPENAI_API_KEY: # Hoặc key LLM bạn dùng để lấy query
        print("\nERROR: OpenAI API Key (or relevant LLM key) is not set.")
        print("Please configure it in your .env file or environment variables.")
        # sys.exit(1) # Thoát nếu muốn bắt buộc có key

    run_chapter_card_test()
# ----------------------------------------------------