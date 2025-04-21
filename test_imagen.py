import os
# --- QUAY LẠI IMPORT NHƯ SAMPLE CODE ---
from google import genai
# Vẫn giữ import types từ đường dẫn đầy đủ này
from google.genai import types as genai_types
# ---------------------------------------
from google.api_core import exceptions as google_exceptions
from PIL import Image
from io import BytesIO
import time
from dotenv import load_dotenv
import traceback

# Tải biến môi trường từ file .env
load_dotenv()

# --- Cấu hình ---
API_KEY = os.getenv('GEMINI_API_KEY')
IMAGEN_MODEL_NAME = "imagen-3.0-generate-002"
OUTPUT_DIR = "imagen_test_output"

# --- Hàm chính để kiểm tra (SỬA ĐỔI ĐỂ NHẬN CLIENT) ---
def test_imagen_generation(client, prompt, output_filename): # Thêm tham số client
    """
    Tạo ảnh từ prompt sử dụng Imagen và lưu lại.

    Args:
        client (genai.Client): Đối tượng client đã khởi tạo.
        prompt (str): Mô tả cho ảnh cần tạo.
        output_filename (str): Tên file để lưu ảnh (ví dụ: "cat_on_moon.jpg").

    Returns:
        bool: True nếu thành công, False nếu thất bại.
    """
    print(f"\nAttempting to generate image for prompt: '{prompt}'")
    print(f"Using model: {IMAGEN_MODEL_NAME}")

    try:
        # Tạo config (Giữ nguyên)
        config = genai_types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="16:9"
        )

        # Gọi API qua client (Giữ nguyên)
        response = client.models.generate_images(
            model=IMAGEN_MODEL_NAME,
            prompt=prompt,
            config=config
        )

        # Kiểm tra và xử lý kết quả (Giữ nguyên)
        if hasattr(response, 'generated_images') and response.generated_images:
            print(f"Successfully received {len(response.generated_images)} image candidate(s).")
            generated_image_data = response.generated_images[0]

            if hasattr(generated_image_data, 'image') and hasattr(generated_image_data.image, 'image_bytes'):
                image_bytes = generated_image_data.image.image_bytes
                if image_bytes:
                    print("Image bytes received.")
                    img = Image.open(BytesIO(image_bytes))
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    output_path = os.path.join(OUTPUT_DIR, output_filename)
                    img_format = output_filename.split('.')[-1].upper()
                    if img_format == 'JPG' or img_format == 'JPEG':
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        img.save(output_path, format="JPEG", quality=90)
                    else:
                        img.save(output_path)

                    print(f"✅ Image successfully saved to: {output_path}")
                    return True
                else:
                    print("❌ Error: Imagen API response has empty image bytes.")
                    return False
            else:
                print("❌ Error: Generated image data structure is unexpected (missing image_bytes).")
                return False
        else:
            print(f"❌ Error: Imagen API response did not contain generated images.")
            if hasattr(response, 'safety_feedback') and response.safety_feedback:
                print(f"   Safety feedback received: {response.safety_feedback}")
            return False

    # Giữ nguyên phần xử lý lỗi
    except google_exceptions.PermissionDenied as e:
        print(f"❌ API Error: Permission Denied. Check your API key and ensure the Imagen API is enabled.")
        print(f"   Details: {e}")
        return False
    except google_exceptions.ResourceExhausted as e:
        print(f"❌ API Error: Quota exceeded.")
        print(f"   Details: {e}")
        return False
    except google_exceptions.InvalidArgument as e:
         print(f"❌ API Error: Invalid Argument. Prompt might be blocked or malformed.")
         print(f"   Details: {e}")
         return False
    except google_exceptions.GoogleAPICallError as e:
        print(f"❌ Google API Call Error: {e}")
        return False
    except AttributeError as ae:
         print(f"❌ AttributeError: Likely an issue with the library version or API call structure.")
         print(f"   Details: {ae}")
         traceback.print_exc()
         return False
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        traceback.print_exc()
        return False

# --- Khối thực thi chính (SỬA ĐỔI) ---
if __name__ == "__main__":
    print("--- Imagen Generation Test Script ---")
    if not API_KEY:
        print("❌ FATAL ERROR: GEMINI_API_KEY environment variable not found.")
        exit()
    else:
        print("✅ GEMINI_API_KEY found.")

    # --- KHỞI TẠO CLIENT THEO SAMPLE CODE ---
    try:
        # Sử dụng genai đã import từ 'google' để tạo Client
        client = genai.Client(api_key=API_KEY)
        print(f"✅ Google AI Client initialized successfully (using genai.Client).")
    except AttributeError as client_attr_err:
         # Nếu lỗi này xảy ra, có thể phiên bản thư viện đã thay đổi hoặc import vẫn sai
         print(f"❌ FATAL ERROR: Failed to initialize Google AI Client - AttributeError: {client_attr_err}")
         print(f"   Make sure 'google-generativeai' is installed and the import 'from google import genai' works.")
         exit()
    except Exception as client_err:
        print(f"❌ FATAL ERROR: Failed to initialize Google AI Client: {client_err}")
        exit()
    # ---------------------------------------

    test_prompts = {
        "realistic_cat": ("A photorealistic image of a tabby cat lounging in a sunbeam.", "realistic_cat.jpg"),
        "fantasy_landscape": ("A vibrant fantasy landscape with floating islands and waterfalls under a purple sky, digital painting style.", "fantasy_landscape.png"),
        "abstract_concept": ("An abstract representation of 'creativity' using flowing lines and bright colors.", "abstract_creativity.png"),
        "product_photo": ("A studio photograph of a sleek, modern wireless headphone on a white background.", "product_headphone.jpg"),
        "cyberpunk_city": ("A neon-lit cyberpunk city street at night with flying vehicles and rain.", "cyberpunk_city.jpg"),
    }

    success_count = 0
    total_tests = len(test_prompts)
    start_time = time.time()
    for key, (prompt, filename) in test_prompts.items():
        if test_imagen_generation(client, prompt, filename):
            success_count += 1
        # time.sleep(2)
    end_time = time.time()

    # Giữ nguyên phần tóm tắt kết quả
    print("\n--- Test Summary ---")
    print(f"Total prompts tested: {total_tests}")
    print(f"Successful generations: {success_count}")
    print(f"Failed generations: {total_tests - success_count}")
    print(f"Total time taken: {end_time - start_time:.2f} seconds")
    if total_tests > 0:
        print(f"Success rate: {(success_count / total_tests) * 100:.1f}%")
    if success_count > 0:
        print(f"\n✅ Test completed. Check the '{OUTPUT_DIR}' directory for generated images.")
    else:
        print("\n⚠️ Test completed, but no images were generated successfully. Please review the error messages above.")