# test_video_editor.py
import os
import json
import logging
import sys
from config.settings import TEMP_DIR, OUTPUT_DIR, ASSETS_DIR
from src.video_editor import VideoEditor # Import class cần test

# --- Cấu hình Logging (Copy từ main.py hoặc đơn giản hơn) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VideoEditorTest")
# Để xem log DEBUG của VideoEditor, bạn cần đặt level DEBUG cho logger của nó
# logging.getLogger('src.video_editor').setLevel(logging.DEBUG)

# --- THÔNG TIN TỪ LẦN CHẠY TRƯỚC ---
# Thay thế bằng timestamp và project_id thực tế từ lần chạy trước
TIMESTAMP_PREVIOUS_RUN = "20250404_013711" # Ví dụ timestamp
PROJECT_ID_PREVIOUS_RUN = "prj-markets-digest-bank-earnings-a" # Ví dụ project_id

# --- Đường dẫn đến các tài nguyên đã lưu ---
script_path = os.path.join(TEMP_DIR, f"script_{TIMESTAMP_PREVIOUS_RUN}.json")
# Lưu ý: Cần file audio_info_{project_id}.json để lấy thông tin audio unit
audio_info_path = os.path.join(TEMP_DIR, "audio", PROJECT_ID_PREVIOUS_RUN, f"audio_info_{PROJECT_ID_PREVIOUS_RUN}.json")
# Lưu ý: Cần file media_info.json để lấy thông tin media
media_info_path = os.path.join(TEMP_DIR, "images", PROJECT_ID_PREVIOUS_RUN, "media_info.json")

# Đường dẫn tới thư mục chứa audio và media thực tế
audio_files_dir = os.path.join(TEMP_DIR, "audio", PROJECT_ID_PREVIOUS_RUN)
media_files_dir = os.path.join(TEMP_DIR, "images", PROJECT_ID_PREVIOUS_RUN)

# Đường dẫn output cho video test
output_video_path = os.path.join(OUTPUT_DIR, f"test_video_{PROJECT_ID_PREVIOUS_RUN}.mp4")

# Đường dẫn nhạc nền (nếu có)
background_music = None
music_dir = os.path.join(ASSETS_DIR, "music")
if os.path.exists(music_dir):
    music_files = [f for f in os.listdir(music_dir) if f.endswith('.mp3')]
    if music_files:
        background_music = os.path.join(music_dir, music_files[0])
        logger.info(f"Using background music: {background_music}")

def load_json_data(file_path):
    """Hàm helper để tải dữ liệu JSON."""
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading JSON from {file_path}: {e}")
        return None

def main_test():
    logger.info("--- Starting VideoEditor Test ---")

    # 1. Load Script
    script_data = load_json_data(script_path)
    if not script_data: return

    # 2. Load Audio Info và tạo lại list audio_files_info với path đầy đủ
    audio_info_data = load_json_data(audio_info_path)
    if not audio_info_data or 'speech_unit_audio_files' not in audio_info_data:
        logger.error("Invalid or missing audio info data.")
        return
    audio_files_info_list = []
    for unit_info in audio_info_data['speech_unit_audio_files']:
        unit_file_path = os.path.join(audio_files_dir, unit_info['filename'])
        if os.path.exists(unit_file_path):
            audio_files_info_list.append({
                "type": unit_info['type'],
                "unit_number": unit_info['unit_number'],
                "path": unit_file_path, # Đường dẫn đầy đủ
                "duration": unit_info['duration'],
                # "content": unit_info.get('content'), # Không cần content ở đây
                "scene_numbers": unit_info['scene_numbers']
            })
        else:
            logger.warning(f"Audio file not found: {unit_file_path}")
    if not audio_files_info_list:
         logger.error("No valid audio unit files found.")
         return
    logger.info(f"Loaded info for {len(audio_files_info_list)} audio units.")


    # 3. Load Media Info và tạo lại list media_items với path đầy đủ
    media_info_data = load_json_data(media_info_path)
    if not media_info_data or 'items' not in media_info_data:
         logger.error("Invalid or missing media info data.")
         return
    media_items_list = []
    for item_info in media_info_data['items']:
         media_file_path = os.path.join(media_files_dir, item_info['relative_path'])
         if os.path.exists(media_file_path):
              media_items_list.append({
                   "type": item_info['type'],
                   "media_type": item_info['media_type'],
                   "number": item_info.get('number'), # Có thể None cho intro/outro/source
                   "path": media_file_path, # Đường dẫn đầy đủ
                   "duration": item_info.get('duration', 0), # Duration placeholder/gốc
                   "content": item_info.get('content', ''),
                   "search_query": item_info.get('search_query')
              })
         else:
              # Xử lý media cho intro/outro nếu tên file khác
              is_special = False
              for special_name in ["intro_title.png", "outro.png", "source_image.jpg"]:
                   special_path = os.path.join(media_files_dir, special_name)
                   if item_info['relative_path'] == special_name and os.path.exists(special_path):
                       media_items_list.append({
                           "type": item_info['type'],
                           "media_type": item_info['media_type'],
                           "number": item_info.get('number'),
                           "path": special_path,
                           "duration": item_info.get('duration', 0),
                           "content": item_info.get('content', ''),
                           "search_query": item_info.get('search_query')
                       })
                       is_special = True
                       break
              if not is_special:
                   logger.warning(f"Media file not found: {media_file_path} (Relative: {item_info['relative_path']})")

    if not media_items_list:
          logger.error("No valid media items found.")
          return
    logger.info(f"Loaded info for {len(media_items_list)} media items.")


    # 4. Khởi tạo VideoEditor
    try:
        video_editor = VideoEditor()
    except Exception as e:
        logger.error(f"Failed to initialize VideoEditor: {e}")
        return

    # 5. Gọi hàm create_video với dữ liệu đã load
    logger.info(f"Calling video_editor.create_video for project {PROJECT_ID_PREVIOUS_RUN}...")
    try:
        output_final = video_editor.create_video(
            script=script_data,
            media_items=media_items_list,
            audio_files_info=audio_files_info_list, # Truyền list đã tạo
            output_path=output_video_path,
            background_music_path=background_music
            # project_id=PROJECT_ID_PREVIOUS_RUN # Truyền project_id vào đây
        )

        if output_final and os.path.exists(output_final):
            logger.info(f"--- VideoEditor Test SUCCESS ---")
            logger.info(f"Final video created at: {output_final}")
        else:
            logger.error(f"--- VideoEditor Test FAILED ---")
            logger.error(f"create_video did not return a valid path or the file doesn't exist.")

    except Exception as e:
        logger.error(f"--- VideoEditor Test FAILED with exception ---")
        logger.error(f"Error during create_video call: {e}", exc_info=True)

    logger.info("--- VideoEditor Test Finished ---")

if __name__ == "__main__":
    main_test()