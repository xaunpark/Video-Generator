import os
import sys
import time
import logging
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv

# ---- Đảm bảo import đúng module từ src ----
# Chạy script này từ thư mục gốc của project
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# -----------------------------------------

from src.image_generator import ImageGenerator
from src.video_styles.base_style import BaseVideoStyle # Cần cho Mock Strategy
from config.settings import TEMP_DIR, VIDEO_SETTINGS
from config.credentials import GEMINI_API_KEY, OPENAI_API_KEY # Kiểm tra key tồn tại

# --- Cấu hình Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ImagenTest")
# ------------------------

# --- Tạo Style Strategy giả lập ---
class MockVideoStyle(BaseVideoStyle):
    def get_style_config(self):
        # Trả về config tối thiểu nếu cần
        return {"tone": "Test Style", "goal": "Testing"}

    def generate_ai_image_prompt(self, scene_content, video_title):
        # Tạo hướng dẫn prompt đơn giản để kiểm tra
        return f"""
        Generate an Imagen prompt based on the following, in a {self.get_style_config()['tone']} tone:
        Scene: {scene_content}
        Video Title: {video_title}
        Focus on a clear, simple visual. For example: 'A photorealistic image of {scene_content[:30]}'
        """
    # Implement các phương thức abstract khác nếu BaseVideoStyle yêu cầu (có thể trả về None hoặc giá trị mặc định)
    def generate_script_prompt(self, source_data, language, video_mode): return None
    def get_video_editing_settings(self): return {}
    def get_voice_settings(self): return {}
    def should_override_layout(self): return False
    def should_override_visual_source(self): return False
    def should_override_timing_mode(self): return False
# ---------------------------------

def run_imagen_tests():
    """Chạy các bài kiểm tra cho chức năng Imagen trong ImageGenerator."""
    logger.info("--- Starting ImageGenerator Imagen Test ---")
    load_dotenv()

    # --- Kiểm tra API Keys ---
    keys_ok = True
    if not GEMINI_API_KEY:
        logger.error("❌ FATAL: GEMINI_API_KEY not found in environment variables.")
        keys_ok = False
    # ImageGenerator có thể dùng OpenAI để tạo prompt Imagen, nên cũng cần check
    if not OPENAI_API_KEY:
        logger.warning("⚠️ WARNING: OPENAI_API_KEY not found. Imagen prompt generation might use basic fallback.")
        # Không đặt keys_ok = False ở đây vì có thể vẫn test API call Imagen

    if not keys_ok:
        return False
    # -------------------------

    # --- Khởi tạo ImageGenerator ---
    try:
        # Khởi tạo không có script_generator để test fallback tạo prompt (nếu có)
        # hoặc truyền script_generator nếu muốn test luồng đó
        logger.info("Initializing ImageGenerator...")
        # Sửa đổi: KHÔNG truyền script_generator=None nếu hàm __init__ không nhận tham số này
        # generator = ImageGenerator(script_generator=None)
        generator = ImageGenerator() # Giả sử __init__ không cần tham số

        if not generator.gemini_client:
            logger.error("❌ ERROR: ImageGenerator initialized, but Gemini client (for Imagen) is not available. Check API key and library installation.")
            return False
        logger.info("✅ ImageGenerator initialized successfully with Gemini client.")
    except Exception as init_err:
        logger.error(f"❌ ERROR: Failed to initialize ImageGenerator: {init_err}", exc_info=True)
        return False
    # -------------------------------

    # --- Tạo thư mục Output ---
    test_output_dir = os.path.join(TEMP_DIR, "imagen_generator_test_output")
    os.makedirs(test_output_dir, exist_ok=True)
    logger.info(f"Test images will be saved to: {test_output_dir}")
    # -------------------------

    # --- Dữ liệu Test ---
    test_prompt_content = "a friendly robot waving hello"
    test_video_title = "Robots of the Future"
    mock_strategy = MockVideoStyle()
    test_script = {
        'project_id': f"test_imagen_{int(time.time())}",
        'title': test_video_title,
        'language': 'en',
        'scenes': [
            {'number': 1, 'content': test_prompt_content},
            {'number': 2, 'content': "another scene description"},
        ]
        # Không cần speech_units cho test này
    }
    test_filename_direct = f"imagen_direct_test_{int(time.time())}.jpg"
    test_path_direct = os.path.join(test_output_dir, test_filename_direct)
    # ------------------

    test_results = {"direct_call": False, "prompt_gen": False, "integrated_call": False}
    all_tests_passed = True

    # === Test 1: Gọi trực tiếp _generate_image_with_imagen ===
    logger.info("\n--- Test 1: Direct call to _generate_image_with_imagen ---")
    try:
        # Tạo prompt đơn giản cho lần gọi trực tiếp
        direct_prompt = f"Generate image: {test_prompt_content}, style: photorealistic"
        logger.info(f"Using direct prompt: '{direct_prompt}'")
        image_bytes = generator._generate_image_with_imagen(direct_prompt)
        if image_bytes:
            logger.info("✅ Received image bytes from API.")
            img = Image.open(BytesIO(image_bytes))
            if img.mode != 'RGB': img = img.convert('RGB')
            img.save(test_path_direct, format="JPEG", quality=90)
            logger.info(f"✅ Image saved successfully to: {test_path_direct}")
            test_results["direct_call"] = True
        else:
            logger.error("❌ Direct API call did not return image bytes.")
            all_tests_passed = False
    except Exception as e:
        logger.error(f"❌ Error during direct API call test: {e}", exc_info=True)
        all_tests_passed = False
    # ========================================================

    # === Test 2: Gọi _create_imagen_prompt ===
    logger.info("\n--- Test 2: Call to _create_imagen_prompt (using Mock Strategy) ---")
    try:
        logger.info(f"Generating Imagen prompt for scene: '{test_prompt_content}'")
        generated_prompt = generator._create_imagen_prompt(
            scene_content=test_prompt_content,
            video_title=test_video_title,
            style_strategy=mock_strategy
        )
        if generated_prompt and isinstance(generated_prompt, str) and len(generated_prompt) > 10:
            logger.info(f"✅ Successfully generated Imagen prompt:")
            logger.info(f"   Prompt: '{generated_prompt[:150]}...'")
            test_results["prompt_gen"] = True

            # --- Bonus: Thử tạo ảnh với prompt vừa tạo ra ---
            logger.info("   (Bonus: Attempting image generation with this generated prompt)")
            bonus_filename = f"imagen_prompt_test_{int(time.time())}.jpg"
            bonus_output_path = os.path.join(test_output_dir, bonus_filename)
            bonus_image_bytes = generator._generate_image_with_imagen(generated_prompt)
            if bonus_image_bytes:
                img_bonus = Image.open(BytesIO(bonus_image_bytes))
                if img_bonus.mode != 'RGB': img_bonus = img_bonus.convert('RGB')
                img_bonus.save(bonus_output_path, format="JPEG", quality=90)
                logger.info(f"   ✅ Bonus image saved to: {bonus_output_path}")
            else:
                logger.warning("   ⚠️ Bonus image generation with generated prompt failed.")
            # ---------------------------------------------

        else:
            logger.error(f"❌ Failed to generate a valid Imagen prompt. Received: {generated_prompt}")
            all_tests_passed = False
    except Exception as e:
        logger.error(f"❌ Error during prompt generation test: {e}", exc_info=True)
        all_tests_passed = False
    # ============================================

    # === Test 3: Gọi generate_images_for_script với visual_source='ai' ===
    logger.info("\n--- Test 3: Integrated call via generate_images_for_script (visual_source='ai') ---")
    try:
        logger.info("Calling generate_images_for_script...")
        media_items = generator.generate_images_for_script(
            script=test_script,
            visual_source='ai', # QUAN TRỌNG: Chỉ định nguồn là AI
            style_strategy=mock_strategy
            # audio_files_info và visual_timing_mode không quá quan trọng cho test AI này
        )

        if media_items:
            logger.info(f"generate_images_for_script returned {len(media_items)} media items.")
            ai_image_found = False
            for item in media_items:
                # Tìm item tương ứng với scene 1 và kiểm tra xem nó có phải ảnh AI không
                if item.get("media_type") == "scene" and item.get("number") == 1:
                    item_path = item.get("path")
                    if item.get("type") == "image" and item_path and item_path.endswith("_ai.jpg"):
                        logger.info(f"✅ Found generated AI image for scene 1: {item_path}")
                        # Kiểm tra file tồn tại
                        if os.path.exists(item_path) and os.path.getsize(item_path) > 1000:
                            logger.info("   File exists and seems valid.")
                            ai_image_found = True
                        else:
                            logger.error(f"   ❌ File path exists in list but file is missing or invalid on disk: {item_path}")
                        break # Đã tìm thấy item cho scene 1
            if ai_image_found:
                test_results["integrated_call"] = True
            else:
                logger.error("❌ Did not find a valid generated AI image for scene 1 in the results.")
                all_tests_passed = False
        else:
            logger.error("❌ generate_images_for_script returned None or an empty list.")
            all_tests_passed = False

    except Exception as e:
        logger.error(f"❌ Error during integrated generation test: {e}", exc_info=True)
        all_tests_passed = False
    # =====================================================================

    logger.info("\n--- Test Summary ---")
    logger.info(f"Direct API Call (_generate_image_with_imagen): {'PASS' if test_results['direct_call'] else 'FAIL'}")
    logger.info(f"Prompt Generation (_create_imagen_prompt):       {'PASS' if test_results['prompt_gen'] else 'FAIL'}")
    logger.info(f"Integrated Call (generate_images_for_script):  {'PASS' if test_results['integrated_call'] else 'FAIL'}")

    if all_tests_passed:
        logger.info("\n✅ All Imagen generation tests passed!")
        return True
    else:
        logger.error("\n❌ Some Imagen generation tests failed. Please review the logs.")
        return False

# --- Chạy Script ---
if __name__ == "__main__":
    start = time.time()
    passed = run_imagen_tests()
    end = time.time()
    logger.info(f"--- Test finished in {end - start:.2f} seconds. Result: {'PASSED' if passed else 'FAILED'} ---")
# ------------------