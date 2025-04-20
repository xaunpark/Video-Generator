import sys
import os
import json
import logging

# --- Đoạn sys.path này vẫn hữu ích để đảm bảo thư mục gốc được ưu tiên ---
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# src_path và config_path không cần thêm riêng vì project_root đã được thêm
# -------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("SeniorPromptTest")

# Import các lớp cần thiết
try:
    # --- SỬA IMPORT Ở ĐÂY ---
    from src.video_styles.base_style import BaseVideoStyle
    from src.video_styles.senior_conversational_style import SeniorConversationalStyle
    from src.utils import safe_truncate
    # Nếu cần import từ config:
    # from config.settings import MAX_ARTICLE_LENGTH
    # --- KẾT THÚC SỬA IMPORT ---
except ImportError as e:
    logger.error(f"Lỗi import: {e}. Đảm bảo file test được chạy từ thư mục gốc project.")
    sys.exit(1)

# --- Code Thực thi Test ---
if __name__ == "__main__":

    print("\n" + "="*10 + " Test Lấy Script Prompt từ SeniorConversationalStyle " + "="*10)

    # 1. Tạo đối tượng Strategy
    try:
        senior_strategy = SeniorConversationalStyle()
        logger.info("Đã tạo đối tượng SeniorConversationalStyle.")
    except Exception as e:
        logger.error(f"Lỗi khi tạo đối tượng SeniorConversationalStyle: {e}")
        sys.exit(1)

    # 2. Tạo dữ liệu nguồn giả lập (ví dụ: từ keyword)
    test_source_data = {
        'type': 'keyword',
        'data': 'staying active and social after retirement' # Keyword phù hợp với style
    }
    test_language = 'en'
    test_video_mode = 'basic' # CHÚ Ý: Mặc dù Senior thường ép Advanced, hàm generate_script_prompt
                              # hiện tại được thiết kế cho Basic step 1. Chúng ta test prompt này.

    logger.info(f"Dữ liệu nguồn giả lập: {test_source_data}")
    logger.info(f"Ngôn ngữ: {test_language}, Chế độ (cho prompt): {test_video_mode}")


    # 3. Gọi hàm generate_script_prompt của strategy
    try:
        logger.info("Gọi senior_strategy.generate_script_prompt()...")
        generated_prompt = senior_strategy.generate_script_prompt(
            source_data=test_source_data,
            language=test_language,
            video_mode=test_video_mode
        )

        if "Error:" in generated_prompt:
            logger.error(f"Hàm generate_script_prompt báo lỗi: {generated_prompt}")
        else:
            logger.info("Đã tạo prompt thành công.")
            print("\n--- PROMPT ĐƯỢC TẠO ---")
            print(generated_prompt)
            print("-" * 70)

            # Kiểm tra nhanh một số yếu tố đặc trưng của prompt Senior (tùy chọn)
            if "Target Audience: **Seniors (60+)**" in generated_prompt:
                logger.info("Kiểm tra: Prompt chứa thông tin Target Audience.")
            else:
                logger.warning("Kiểm tra: Prompt thiếu thông tin Target Audience.")

            if "like a caring friend" in generated_prompt:
                logger.info("Kiểm tra: Prompt chứa hướng dẫn style 'caring friend'.")
            else:
                logger.warning("Kiểm tra: Prompt thiếu hướng dẫn style 'caring friend'.")

            if '"initial_scenes":' in generated_prompt:
                 logger.info("Kiểm tra: Prompt yêu cầu output 'initial_scenes' (đúng cho Basic Step 1).")
            else:
                 logger.error("Kiểm tra: Prompt KHÔNG yêu cầu output 'initial_scenes'.")


    except Exception as e:
        logger.error(f"Lỗi không mong muốn khi gọi generate_script_prompt: {e}", exc_info=True)

    print("\n" + "="*10 + " Kết thúc Test " + "="*10)