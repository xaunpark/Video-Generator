import os
import shutil
import sys
import time
import logging
import json
from dotenv import load_dotenv
import mutagen.mp3 # Để kiểm tra duration file nếu cần

# ---- Đảm bảo import đúng module từ src ----
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# -----------------------------------------

# --- Import các thành phần cần thiết ---
from src.voice_generator import VoiceGenerator
from config.settings import TEMP_DIR, TTS_PROVIDERS # Cần TTS_PROVIDERS để lấy valid voices/models
from config.credentials import MINIMAX_API_KEY, MINIMAX_GROUP_ID # Kiểm tra key tồn tại
# -----------------------------------

# --- Cấu hình Logging ---
logging.basicConfig(
    level=logging.INFO, # Đặt INFO hoặc DEBUG để xem chi tiết
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("VoiceGeneratorMiniMaxTest")
# ------------------------

# --- Cấu hình Test ---
OUTPUT_DIR_VG_TEST = os.path.join(TEMP_DIR, "minimax_vg_test_output")
os.makedirs(OUTPUT_DIR_VG_TEST, exist_ok=True)
# --------------------

def run_minimax_vg_tests():
    """Chạy các bài kiểm tra cho VoiceGenerator với provider MiniMax."""
    logger.info("--- Starting VoiceGenerator MiniMax Integration Test ---")
    load_dotenv()

    # --- 1. Kiểm tra Credentials ---
    if not MINIMAX_API_KEY or not MINIMAX_GROUP_ID:
        logger.critical("❌ FATAL: MINIMAX_API_KEY or MINIMAX_GROUP_ID not found in environment variables. Please check your .env file.")
        return False
    logger.info("✅ MiniMax Credentials found.")
    # -----------------------------

    # --- 2. Khởi tạo VoiceGenerator với MiniMax ---
    generator = None
    try:
        logger.info("Initializing VoiceGenerator with selected_provider='minimax'...")
        generator = VoiceGenerator(selected_provider="minimax")
        logger.info("✅ VoiceGenerator initialized successfully for MiniMax.")
    except ValueError as ve:
        logger.critical(f"❌ FATAL: Failed to initialize VoiceGenerator for MiniMax: {ve}")
        return False
    except Exception as e:
        logger.critical(f"❌ FATAL: Unexpected error initializing VoiceGenerator: {e}", exc_info=True)
        return False
    # -------------------------------------------

    # --- 3. Lấy danh sách giọng và model hợp lệ từ config ---
    try:
        minimax_config = TTS_PROVIDERS.get("minimax", {})
        valid_voices = minimax_config.get("valid_voices", [])
        valid_models = minimax_config.get("valid_models", [])
        if not valid_voices:
             logger.warning("⚠️ WARNING: 'valid_voices' list for MiniMax is empty or missing in settings.py. Voice validation might not work correctly.")
             # Gán một list mặc định tối thiểu để tránh lỗi sau này nếu muốn test
             # valid_voices = ["male-qn-qingse"] # Ví dụ
        if not valid_models:
             logger.warning("⚠️ WARNING: 'valid_models' list for MiniMax is empty or missing in settings.py.")

    except Exception as e:
        logger.error(f"Error accessing provider config from settings: {e}")
        valid_voices = []
        valid_models = []
    # ---------------------------------------------------

    # --- 4. Định nghĩa các Test Cases ---
    test_cases = [
        {
            "name": "Default Voice and Model",
            "text": "Đây là một bài kiểm tra sử dụng giọng nói và mô hình mặc định của MiniMax.",
            "filename": "minimax_default.mp3",
            "expected_voice": generator.voice, # Giọng mặc định đã được load
            "expected_model": generator.model  # Model mặc định đã được load
        },
        # --- Thêm test case với giọng cụ thể (thay 'Wise_Woman' bằng voice_id hợp lệ khác nếu cần) ---
        {
            "name": "Specific Voice (Wise_Woman)",
            "text": "Testing with the Wise Woman voice.",
            "filename": "minimax_wise_woman.mp3",
            "set_voice": "Wise_Woman", # Giọng muốn test
            "expected_voice": "Wise_Woman",
            "expected_model": generator.model # Giữ model mặc định
        },
        # --- Thêm test case với model HD (chọn giọng phù hợp với HD nếu biết) ---
        {
            "name": "HD Model",
            "text": "This audio should be generated using the high-definition model.",
            "filename": "minimax_hd_model.mp3",
            "set_voice": "female-english-hidy", # Ví dụ giọng tiếng Anh
            "set_model": "speech-02-hd", # Model HD
            "expected_voice": "female-english-hidy",
            "expected_model": "speech-02-hd"
        },
         # --- Test case với khoảng dừng ---
        {
            "name": "Text with Pause Tag",
            "text": "Sentence one.<#1.5#>Sentence two after a pause.",
            "filename": "minimax_with_pause.mp3",
            "expected_voice": generator.voice, # Quay lại giọng default
            "expected_model": generator.model
        },
        # --- Test case tiếng Việt (chọn voice_id tiếng Việt phù hợp) ---
        {
            "name": "Vietnamese Voice",
            "text": "Xin chào, đây là giọng nói tiếng Việt tự động từ MiniMax.",
            "filename": "minimax_vietnamese.mp3",
            "set_voice": "female-qn-yujie", # CHỌN MỘT GIỌNG TIẾNG VIỆT HỢP LỆ TỪ valid_voices CỦA BẠN
            "expected_voice": "female-qn-yujie",
            "expected_model": generator.model
        },
    ]
    # ---------------------------------

    successful_tests_count = 0
    total_tests_to_run = len(test_cases)

    # --- 5. Chạy các Test Cases ---
    for i, case in enumerate(test_cases):
        logger.info(f"\n--- Running Test Case {i+1}/{total_tests_to_run}: {case['name']} ---")
        test_passed = False
        try:
            # --- 5a. Set Voice và Model (nếu được yêu cầu) ---
            if "set_voice" in case:
                # Kiểm tra trước xem giọng có hợp lệ không (nếu có list valid_voices)
                if valid_voices and case["set_voice"] not in valid_voices:
                     logger.warning(f"⚠️ Test Case '{case['name']}': Voice '{case['set_voice']}' is not in valid_voices list from settings. Skipping set_voice.")
                     # Có thể quyết định bỏ qua test case này hoặc dùng default
                     # continue # Bỏ qua test này
                     # Hoặc không set và dùng default:
                     generator.set_voice(generator.provider_config.get("default_voice")) # Reset về default
                else:
                     generator.set_voice(case["set_voice"])
                     # Kiểm tra xem voice có thực sự được set không
                     if generator.voice != case["expected_voice"]:
                          logger.error(f"❌ Failed to set voice correctly. Expected: {case['expected_voice']}, Got: {generator.voice}")
                          # continue # Có thể bỏ qua nếu set voice lỗi

            if "set_model" in case:
                 if valid_models and case["set_model"] not in valid_models:
                      logger.warning(f"⚠️ Test Case '{case['name']}': Model '{case['set_model']}' is not in valid_models list from settings. Skipping set_model.")
                      # continue
                      generator.set_model(generator.provider_config.get("default_model")) # Reset về default
                 else:
                      generator.set_model(case["set_model"])
                      if generator.model != case["expected_model"]:
                           logger.error(f"❌ Failed to set model correctly. Expected: {case['expected_model']}, Got: {generator.model}")
                           # continue

            logger.info(f"Using Voice: {generator.voice}, Model: {generator.model}")
            # ----------------------------------------------

            # --- 5b. Tạo Script giả lập chỉ với 1 unit ---
            dummy_script = {
                'project_id': f"minimax_test_{i+1}_{int(time.time())}",
                'title': f"Test Case {i+1}: {case['name']}",
                'language': 'en', # Hoặc 'vi' tùy test case
                'speech_units': [
                    {
                        'unit_number': 1,
                        'text': case['text'],
                        'scene_numbers': [1] # Số scene không quan trọng cho test này
                    }
                ]
            }
            # ----------------------------------------------

            # --- 5c. Gọi hàm chính cần test ---
            logger.info(f"Calling generate_audio_for_script for project: {dummy_script['project_id']}")
            start_gen_time = time.time()
            audio_files_info = generator.generate_audio_for_script(dummy_script)
            end_gen_time = time.time()
            logger.info(f"generate_audio_for_script finished in {end_gen_time - start_gen_time:.2f} seconds.")
            # ---------------------------------

            # --- 5d. Kiểm tra kết quả ---
            if audio_files_info and isinstance(audio_files_info, list) and len(audio_files_info) == 1:
                result_info = audio_files_info[0]
                output_path = result_info.get('path')
                duration = result_info.get('duration')

                logger.info(f"  Returned Path: {output_path}")
                logger.info(f"  Returned Duration: {duration}")

                # Kiểm tra path tồn tại và đúng tên file mong đợi
                expected_path_part = os.path.join(dummy_script['project_id'], case['filename'])
                if output_path and expected_path_part in output_path:
                    # Kiểm tra file tồn tại và kích thước > 0
                    full_output_path = os.path.join(OUTPUT_DIR_VG_TEST, os.path.basename(output_path)) # Tạo đường dẫn đầy đủ để kiểm tra
                    # Correct the path construction for the actual saved file
                    actual_saved_path = os.path.join(generator.audio_dir, dummy_script['project_id'], case['filename'])


                    if os.path.exists(actual_saved_path) and os.path.getsize(actual_saved_path) > 1000:
                        logger.info(f"  ✅ File '{case['filename']}' exists and has size > 1KB.")
                        # Kiểm tra duration hợp lệ
                        if duration is not None and isinstance(duration, (int, float)) and duration > 0.1:
                            logger.info(f"  ✅ Duration ({duration:.2f}s) seems valid.")
                            test_passed = True
                             # Optional: Copy to main test output dir for easier access
                            try:
                                shutil.copy2(actual_saved_path, os.path.join(OUTPUT_DIR_VG_TEST, case['filename']))
                                logger.info(f"  Copied final audio to: {os.path.join(OUTPUT_DIR_VG_TEST, case['filename'])}")
                            except Exception as copy_err:
                                logger.warning(f"  Could not copy final audio: {copy_err}")

                        else:
                            logger.error(f"  ❌ Invalid duration returned: {duration}")
                    else:
                        logger.error(f"  ❌ Output file missing or invalid: {actual_saved_path}")
                else:
                    logger.error(f"  ❌ Returned path '{output_path}' does not match expected pattern '{expected_path_part}'.")
            else:
                logger.error(f"  ❌ generate_audio_for_script did not return the expected list structure or is empty. Result: {audio_files_info}")
            # --------------------------

        except Exception as test_err:
            logger.error(f"❌ Unexpected error during test case '{case['name']}': {test_err}", exc_info=True)
            test_passed = False

        if test_passed:
            successful_tests_count += 1
            logger.info(f"--- Test Case {i+1} PASSED ---")
        else:
            logger.error(f"--- Test Case {i+1} FAILED ---")
    # --- Kết thúc vòng lặp Test Cases ---

    # --- 6. Test xử lý giọng/model không hợp lệ ---
    logger.info("\n--- Testing Invalid Inputs ---")
    try:
        logger.info("Setting invalid voice 'invalid_voice_test'...")
        generator.set_voice("invalid_voice_test")
        # Kiểm tra xem log có cảnh báo không (cần nhìn log output)
        if generator.voice == generator.provider_config.get("default_voice"):
             logger.info("  ✅ Generator correctly reverted to default voice after invalid input (as expected).")
        else:
             logger.warning("  ⚠️ Generator did not revert to default voice after invalid input.")

        logger.info("Setting invalid model 'invalid_model_test'...")
        generator.set_model("invalid_model_test")
        if generator.model == generator.provider_config.get("default_model"):
             logger.info("  ✅ Generator correctly reverted to default model after invalid input (as expected).")
        else:
              logger.warning("  ⚠️ Generator did not revert to default model after invalid input.")
    except Exception as invalid_err:
        logger.error(f"❌ Error during invalid input tests: {invalid_err}", exc_info=True)
    # -----------------------------------------

    # --- 7. In kết quả cuối cùng ---
    logger.info("\n===== MiniMax VoiceGenerator Test Summary =====")
    logger.info(f"Total tests run: {total_tests_to_run}")
    logger.info(f"Successful tests: {successful_tests_count}")
    logger.info(f"Failed tests: {total_tests_to_run - successful_tests_count}")
    if successful_tests_count > 0:
         logger.info(f"✅ Check the '{OUTPUT_DIR_VG_TEST}' directory for generated audio files.")
    else:
         logger.warning("⚠️ No audio files were generated successfully by VoiceGenerator.")
    logger.info("===============================================")

    return successful_tests_count == total_tests_to_run

# --- Chạy Script ---
if __name__ == "__main__":
    overall_start_time = time.time()
    all_passed = run_minimax_vg_tests()
    overall_end_time = time.time()
    logger.info(f"--- Test Script finished in {overall_end_time - overall_start_time:.2f} seconds. Overall Result: {'PASSED' if all_passed else 'FAILED'} ---")
# ------------------