# test_youtube_list.py
import os
import sys
import logging
from dotenv import load_dotenv
from pathlib import Path
import googleapiclient.discovery
import googleapiclient.errors
import google.oauth2.credentials
from google.auth.transport.requests import Request
import json # Cần nếu dùng phương pháp đọc file secrets

# --- Setup Đường dẫn và Logging ---
try:
    project_root = Path(__file__).resolve().parent
except NameError:
    project_root = Path('.').resolve()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('list_test.log', encoding='utf-8') # Log riêng
    ]
)
logger = logging.getLogger("YouTubeListTest")

# --- Tải Biến Môi trường ---
dotenv_path = project_root / '.env'
load_dotenv(dotenv_path=dotenv_path)
logger.info(f"Loaded .env from: {dotenv_path if os.path.exists(dotenv_path) else 'default locations'}")

# --- Import và Kiểm tra Credentials ---
# Chọn MỘT trong hai cách lấy credentials:

# --- Cách 1: Dùng file secrets (Giống cách bạn đang dùng trong Uploader) ---
try:
    from config.credentials import YOUTUBE_CLIENT_SECRETS_FILE_PATH, YOUTUBE_REFRESH_TOKEN
    SECRETS_PATH = str(YOUTUBE_CLIENT_SECRETS_FILE_PATH)
    REFRESH_TOKEN = YOUTUBE_REFRESH_TOKEN
    if not os.path.exists(SECRETS_PATH): raise FileNotFoundError("Secrets file not found")
    if not REFRESH_TOKEN: raise ValueError("Refresh token not found")
    USE_ENV_VARS_DIRECTLY = False
except (ImportError, FileNotFoundError, ValueError) as e:
    logger.warning(f"Could not load credentials using secrets file path: {e}. Trying direct env vars...")
    # Fallback sang Cách 2 nếu Cách 1 lỗi
    try:
        from config.credentials import (
            YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET,
            YOUTUBE_TOKEN_URI, YOUTUBE_REFRESH_TOKEN
        )
        if not all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_TOKEN_URI, YOUTUBE_REFRESH_TOKEN]):
            raise ValueError("One or more YouTube credential env vars missing")
        REFRESH_TOKEN = YOUTUBE_REFRESH_TOKEN # Gán lại để dùng ở dưới
        USE_ENV_VARS_DIRECTLY = True
    except (ImportError, ValueError) as e2:
        logger.critical(f"Failed to load YouTube credentials using either method: {e2}")
        sys.exit(1)
# --- Kết thúc chọn cách lấy credentials ---


API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
# Scope chỉ cần readonly cho test này
SCOPES = ['https://www.googleapis.com/auth/youtube.readonly']

def get_authenticated_service_for_list():
    """Lấy service YouTube đã xác thực chỉ với quyền readonly."""
    creds = None
    client_config = None

    # Load client config nếu dùng phương pháp file secrets
    if not USE_ENV_VARS_DIRECTLY:
        try:
            with open(SECRETS_PATH, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                client_config = config_data.get('installed') or config_data.get('web')
                if not client_config: raise ValueError("Invalid secrets file format")
        except Exception as e:
            logger.error(f"Failed to load/parse secrets file {SECRETS_PATH}: {e}")
            return None

    logger.info("Attempting to get/refresh credentials for listing...")
    try:
        if USE_ENV_VARS_DIRECTLY:
            creds = google.oauth2.credentials.Credentials(
                None, refresh_token=REFRESH_TOKEN, token_uri=YOUTUBE_TOKEN_URI,
                client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET,
                scopes=SCOPES
            )
        else: # Dùng file secrets đã load
            creds = google.oauth2.credentials.Credentials(
                None, refresh_token=REFRESH_TOKEN, token_uri=client_config['token_uri'],
                client_id=client_config['client_id'], client_secret=client_config['client_secret'],
                scopes=SCOPES
            )

        # Luôn thử refresh để kiểm tra token
        if creds and creds.refresh_token:
             req = Request()
             creds.refresh(req)
             logger.info("Credentials refreshed successfully for listing.")
        else:
             logger.error("Cannot refresh credentials, missing refresh token.")
             return None

        # Build service
        youtube_service = googleapiclient.discovery.build(
            API_SERVICE_NAME, API_VERSION, credentials=creds, cache_discovery=False)
        logger.info("YouTube service built successfully for listing.")
        return youtube_service

    except google.auth.exceptions.RefreshError as refresh_err:
        error_details = getattr(refresh_err, 'args', [str(refresh_err)])[0]
        logger.error(f"Failed to refresh credentials: {error_details}", exc_info=True)
        logger.error("Ensure the refresh token is valid and scopes granted include youtube.readonly.")
        return None
    except Exception as e:
        logger.error(f"Error getting authenticated service: {e}", exc_info=True)
        return None

def list_my_videos(youtube_service, max_results=5):
    """Liệt kê các video gần đây nhất trên kênh của người dùng đã xác thực."""
    if not youtube_service:
        return

    logger.info(f"Attempting to list recent videos (max {max_results})...")
    try:
        request = youtube_service.search().list(
            part="snippet",
            forMine=True, # Chỉ lấy video của kênh đã xác thực
            maxResults=max_results,
            order="date", # Sắp xếp theo ngày tải lên gần nhất
            type="video"  # Chỉ tìm video
        )
        response = request.execute()

        logger.info("Successfully received response from search.list API.")
        print("\n--- Recent Videos Found ---")
        if 'items' in response and response['items']:
            for item in response['items']:
                video_id = item['id']['videoId']
                video_title = item['snippet']['title']
                published_at = item['snippet']['publishedAt']
                print(f"- ID: {video_id}, Title: '{video_title}', Published: {published_at}")
            print(f"Listed {len(response['items'])} videos.")
        else:
            print("No videos found on the channel or API returned empty list.")

    except googleapiclient.errors.HttpError as e:
        error_content = e.content.decode('utf-8') if e.content else str(e)
        logger.error(f"HTTP Error occurred while listing videos: {e.resp.status} {error_content}", exc_info=True)
        print(f"ERROR listing videos: {e.resp.status} - Check logs for details (list_test.log).")
        if e.resp.status == 403:
             print(">>> This 403 error likely indicates the 'youtube.readonly' scope was NOT granted correctly during authentication. <<<")
    except Exception as e:
        logger.error(f"An unexpected error occurred listing videos: {e}", exc_info=True)
        print(f"ERROR listing videos: {e}")


if __name__ == "__main__":
    logger.info("--- Starting YouTube List Scope Test ---")
    youtube = get_authenticated_service_for_list()
    if youtube:
        list_my_videos(youtube)
        logger.info("--- YouTube List Scope Test Finished ---")
    else:
        logger.error("Failed to get authenticated YouTube service. Cannot perform list test.")
        print("\nERROR: Could not authenticate with YouTube. Check logs.")
    print("\nTest complete. Check list_test.log for detailed logs.")