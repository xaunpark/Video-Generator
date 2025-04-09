# src/youtube_uploader.py

import os
import json # Cần lại json để đọc file secrets
import time
import logging
import google.oauth2.credentials
# import google_auth_oauthlib.flow # Vẫn không cần flow ở đây
from google.auth.transport.requests import Request
import googleapiclient
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# --- Import cấu hình credentials ---
# Import này sẽ thất bại nếu config/credentials.py chưa chạy hoặc có lỗi
# nên cần có xử lý lỗi cơ bản
try:
    from config.credentials import YOUTUBE_PROJECT_ID # Có thể dùng để log hoặc kiểm tra
except ImportError:
    logging.warning("Could not import YOUTUBE_PROJECT_ID from credentials.")
    YOUTUBE_PROJECT_ID = "Unknown" # Giá trị mặc định

# Setup logger for this module
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Define the scopes needed for uploading
YOUTUBE_UPLOAD_SCOPE = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# Chunk size for resumable uploads (e.g., 10MB) - Adjust as needed
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024

class YouTubeUploader:
    """Handles authentication and video uploads to YouTube using a secrets file path."""

    def __init__(self, client_secrets_file_path, refresh_token):
        """
        Initializes the YouTubeUploader.

        Args:
            client_secrets_file_path (str): Absolute or relative path to the client_secrets.json file.
                                            Will be resolved relative to the current working directory if relative.
            refresh_token (str): The refresh token obtained from the initial OAuth flow.

        Raises:
            FileNotFoundError: If the client_secrets_file_path does not exist.
            ValueError: If refresh_token is empty or loading client secrets fails.
        """
        # Resolve the path absolutely for robustness
        self.client_secrets_file_path = os.path.abspath(client_secrets_file_path)

        if not os.path.exists(self.client_secrets_file_path):
            logger.error(f"Client secrets file NOT FOUND at resolved path: {self.client_secrets_file_path}")
            raise FileNotFoundError(f"Client secrets file not found: {self.client_secrets_file_path}")
        if not refresh_token:
            logger.error("Refresh token is required.")
            raise ValueError("Refresh token cannot be empty.")

        self.refresh_token = refresh_token
        self.client_config = None # Will hold loaded secrets (dict)
        self.credentials = None # Will hold google.oauth2.credentials.Credentials object
        self.youtube_client = None # Will hold the API client service object

        logger.debug(f"YouTubeUploader initialized with secrets file: {self.client_secrets_file_path}")

        # Load client config immediately
        if not self._load_client_config():
             # Error logged within the function
             raise ValueError("Failed to load or parse client secrets file during initialization.")

        # Attempt to get credentials immediately (which might involve refresh)
        self._get_credentials()
        if self.credentials and self.credentials.valid:
             self._initialize_youtube_client()
        elif not self.credentials:
            logger.warning("Could not obtain initial valid credentials during init (refresh might have failed or token invalid).")


    def _load_client_config(self):
        """Loads client configuration from the secrets file path stored in self."""
        try:
            logger.debug(f"Loading client config from: {self.client_secrets_file_path}")
            with open(self.client_secrets_file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # Find the correct configuration key ('installed' or 'web')
            if "installed" in config:
                self.client_config = config["installed"]
                logger.debug("Loaded 'installed' client configuration.")
                # Basic validation of essential keys
                required_keys = ['client_id', 'project_id', 'token_uri', 'client_secret']
                if not all(key in self.client_config for key in required_keys):
                     logger.error(f"Client secrets file ({self.client_secrets_file_path}) is missing one or more required keys: {required_keys}")
                     self.client_config = None
                     return False
                return True
            elif "web" in config:
                self.client_config = config["web"]
                logger.warning("Loaded 'web' client configuration. 'installed' (Desktop app) type is strongly recommended for this script.")
                required_keys = ['client_id', 'project_id', 'token_uri', 'client_secret']
                if not all(key in self.client_config for key in required_keys):
                     logger.error(f"Client secrets file ({self.client_secrets_file_path}) is missing one or more required keys: {required_keys}")
                     self.client_config = None
                     return False
                return True
            else:
                logger.error("Invalid format: 'installed' or 'web' key not found in client secrets file.")
                self.client_config = None
                return False
        except json.JSONDecodeError as json_err:
            logger.error(f"Error decoding JSON from client secrets file {self.client_secrets_file_path}: {json_err}")
            self.client_config = None
            return False
        except FileNotFoundError: # Should be caught in __init__, but good to have here too
            logger.error(f"Client secrets file not found at {self.client_secrets_file_path} during config loading.")
            self.client_config = None
            return False
        except Exception as e:
            logger.error(f"Error reading client secrets file {self.client_secrets_file_path}: {e}", exc_info=True)
            self.client_config = None
            return False

    def _get_credentials(self):
        """
        Gets valid Google OAuth2 credentials using the refresh token and loaded client config.
        Refreshes the access token if necessary. Stores valid creds in self.credentials.

        Returns:
            google.oauth2.credentials.Credentials or None: Valid credentials object or None if failed.
        """
        # Return cached valid credentials if available
        if self.credentials and self.credentials.valid:
            # logger.debug("Using cached valid credentials.")
            return self.credentials

        # Ensure client_config is loaded
        if not self.client_config:
             logger.error("Client configuration not loaded. Cannot get credentials.")
             return None

        creds = None
        logger.debug("Attempting to create/refresh credentials using refresh token and loaded config...")
        try:
            # Create credentials object
            creds = google.oauth2.credentials.Credentials(
                None, # No initial access token needed
                refresh_token=self.refresh_token,
                token_uri=self.client_config.get('token_uri'), # Use .get for safety
                client_id=self.client_config.get('client_id'),
                client_secret=self.client_config.get('client_secret'),
                scopes=YOUTUBE_UPLOAD_SCOPE
            )

            # Check if all necessary components for refresh are present
            if not all([creds.refresh_token, creds.token_uri, creds.client_id, creds.client_secret]):
                 logger.error("Cannot refresh: Missing components (refresh_token, token_uri, client_id, or client_secret) in credentials object.")
                 self.credentials = None
                 return None

            # Attempt to refresh the token to validate it and get a fresh access token
            logger.info("Attempting to refresh credentials...")
            req = Request() # Create a transport request object
            creds.refresh(req)
            logger.info("Credentials refreshed successfully.")
            self.credentials = creds # Store the now valid and refreshed credentials
            return self.credentials

        except google.auth.exceptions.RefreshError as refresh_err:
            # Catch specific refresh errors
            error_details = getattr(refresh_err, 'args', [str(refresh_err)])[0] # Try to get details
            logger.error(f"Failed to refresh credentials using refresh token: {error_details}", exc_info=False) # exc_info=False for cleaner log usually
            logger.error("Possible reasons: Refresh token is invalid/revoked/expired, Client ID/Secret mismatch, API access disabled, or Test User not added in GCP Console (for 'Testing' apps).")
            self.credentials = None # Invalidate stored credentials
            return None
        except KeyError as key_err:
            logger.error(f"Missing key in loaded client configuration required for Credentials object: {key_err}")
            self.credentials = None
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while creating/getting credentials: {e}", exc_info=True)
            self.credentials = None
            return None

    def _initialize_youtube_client(self):
        """
        Initializes the YouTube API client using valid credentials.

        Returns:
            googleapiclient.discovery.Resource or None: The YouTube client object or None if failed.
        """
        if self.youtube_client and self.credentials and self.credentials.valid:
             # logger.debug("Returning existing valid YouTube client.") # Can be noisy
             return self.youtube_client

        # Ensure we have valid credentials before building
        if not self.credentials or not self.credentials.valid:
            logger.info("Credentials not available or invalid in _initialize_youtube_client, attempting get/refresh...")
            self._get_credentials() # Attempt to get/refresh credentials again

        # Check credentials status *after* attempting get/refresh
        if self.credentials and self.credentials.valid:
            try:
                logger.info("Building YouTube API client service...")
                # Use the validated/refreshed credentials
                self.youtube_client = build(
                    YOUTUBE_API_SERVICE_NAME,
                    YOUTUBE_API_VERSION,
                    credentials=self.credentials,
                    cache_discovery=False # Add this to potentially avoid cache issues
                )
                logger.info("YouTube API client initialized successfully.")
                return self.youtube_client
            except Exception as build_err:
                logger.error(f"Failed to build YouTube API client: {build_err}", exc_info=True)
                self.youtube_client = None
                self.credentials = None # Invalidate credentials if build fails
                return None
        else:
            # Error should have been logged in _get_credentials
            logger.error("Cannot initialize YouTube client: No valid credentials available.")
            self.youtube_client = None
            return None

    def upload_video(self, video_path, title, description, tags, category_id, privacy_status, language="en"):
        """
        Uploads a video file to YouTube.

        Args:
            video_path (str): Path to the video file.
            title (str): Title of the video.
            description (str): Description of the video.
            tags (list): List of tags (strings) for the video.
            category_id (str): YouTube category ID (e.g., "22" for People & Blogs, "25" for News).
            privacy_status (str): Privacy status ("public", "private", "unlisted").
            language (str, optional): Default language for the video (e.g., "en", "vi"). Defaults to "en".

        Returns:
            str or None: The YouTube video ID if successful, None otherwise.
        """
        # 1. Validate inputs
        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return None
        if not title:
            logger.error("Video title cannot be empty.")
            return None
        valid_privacy_statuses = ["public", "private", "unlisted"]
        if privacy_status not in valid_privacy_statuses:
            logger.error(f"Invalid privacy status '{privacy_status}'. Must be one of: {valid_privacy_statuses}")
            return None

        # 2. Initialize YouTube client (ensures valid credentials)
        youtube = self._initialize_youtube_client()
        if not youtube:
            # Error logged within _initialize_youtube_client
            logger.error("Cannot upload: Failed to initialize YouTube client.")
            return None

        try:
            # 3. Prepare Request Body (Metadata)
            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": tags if isinstance(tags, list) else [],
                    "categoryId": str(category_id),
                    "defaultLanguage": language,
                    "defaultAudioLanguage": language
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                    "embeddable": True
                }
            }
            logger.info("Prepared video metadata for upload.")
            logger.debug(f"Upload body (snippet/status): {json.dumps(body, indent=2)}")

            # 4. Prepare Media File Upload object
            logger.info(f"Preparing media file for upload: {video_path}")
            media_file_upload = MediaFileUpload(
                video_path,
                chunksize=DEFAULT_CHUNK_SIZE,
                resumable=True,
                mimetype='application/octet-stream' # More generic mimetype sometimes helps
            )

            # 5. Execute the upload request
            logger.info("Starting YouTube video insert request...")
            request = youtube.videos().insert(
                part="snippet,status", # Comma-separated string
                body=body,
                media_body=media_file_upload
            )

            # 6. Track Upload Progress
            response = None
            logger.info("Uploading video...")
            upload_start_time = time.time()
            last_log_time = upload_start_time
            retry_delay = 5 # Initial delay for retrying server errors
            max_retries = 3
            retries = 0

            while response is None:
                status = None # Reset status for each chunk attempt
                try:
                    status, response = request.next_chunk()
                    if status:
                        percent_complete = int(status.progress() * 100)
                        current_time = time.time()
                        # Log progress less frequently
                        if current_time - last_log_time >= 5 or percent_complete == 100:
                            logger.info(f"YouTube Upload Progress: {percent_complete}%")
                            last_log_time = current_time
                    # Reset retries on successful chunk
                    retries = 0
                    time.sleep(0.1) # Small delay even on success

                except HttpError as http_err:
                     if http_err.resp.status in [401]:
                          logger.error(f"Authorization error (401) during upload. Credentials may need refreshing.", exc_info=True)
                          logger.info("Attempting to re-initialize client...")
                          self.credentials = None # Force re-authentication
                          self.youtube_client = None
                          youtube = self._initialize_youtube_client() # Re-initialize
                          if not youtube:
                               logger.error("Failed to re-initialize client after 401 error. Upload aborted.")
                               return None
                          # Recreating the request might be necessary if state is lost.
                          # The googleapiclient library might handle some of this with resumable.
                          # For simplicity here, we'll log and let it potentially retry the chunk.
                          logger.warning("Re-initialized client. Library might retry the chunk or fail if state is lost.")
                          time.sleep(retry_delay) # Wait before potential retry

                     elif http_err.resp.status in [403]:
                          logger.error(f"Permission error (403) during upload: {http_err.content}", exc_info=True)
                          logger.error("Check user permissions (youtube.upload scope) or API quotas/restrictions.")
                          return None

                     elif http_err.resp.status in [500, 502, 503, 504]:
                          if retries < max_retries:
                               retries += 1
                               logger.warning(f"Resumable upload server error {http_err.resp.status}. Retry {retries}/{max_retries} in {retry_delay}s...")
                               time.sleep(retry_delay)
                               retry_delay *= 2 # Exponential backoff
                               # No need to manually call next_chunk again, loop will continue
                          else:
                               logger.error(f"Upload failed after {max_retries} retries due to server error {http_err.resp.status}.", exc_info=True)
                               return None
                     else:
                          logger.error(f"An unhandled HTTP error occurred during chunk upload: {http_err}", exc_info=True)
                          return None # Non-retriable HTTP error
                except Exception as chunk_err:
                     logger.error(f"A non-HTTP error occurred during chunk upload: {chunk_err}", exc_info=True)
                     return None # General error during upload

            upload_duration = time.time() - upload_start_time
            logger.info(f"Upload process finished in {upload_duration:.2f} seconds.")

            # 7. Process Final Response
            if response:
                video_id = response.get("id")
                if video_id:
                    logger.info(f"Video upload successful! YouTube Video ID: {video_id}")
                    logger.info(f"Watch URL: https://www.youtube.com/watch?v={video_id}")
                    return video_id
                else:
                    logger.error(f"Upload completed but response did not contain video ID. Response: {response}")
                    return None
            else:
                logger.error("Upload process finished but no final response received.")
                return None

        except HttpError as e:
            # Catch errors during the initial request creation
            logger.error(f"An HTTP error occurred before/during upload initiation: {e.resp.status} {e.content}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred during video upload: {e}", exc_info=True)
            return None

    def update_video_status(self, video_id, new_status="public"):
        valid_statuses = ["public", "private", "unlisted"]
        if new_status not in valid_statuses:
            logger.error(f"Invalid new status '{new_status}'.")
            return False

        youtube = self._initialize_youtube_client()
        if not youtube: return False

        logger.info(f"Attempting DIRECT status update for video '{video_id}' to '{new_status}' (skipping pre-check)...") # Log khác đi
        try:
            # --- BỎ QUA HOÀN TOÀN BƯỚC LIST ---

            update_body = {
                "id": video_id,
                "status": {
                    "privacyStatus": new_status
                    # Có thể thêm các thuộc tính status khác nếu API yêu cầu khi update
                    # Ví dụ: "embeddable": True, "license": "youtube" (ít khi cần)
                }
            }

            update_request = youtube.videos().update(
                part="status", # Chỉ định rõ chỉ cập nhật status
                body=update_body
            )
            update_response = update_request.execute()

            # Kiểm tra kết quả update trực tiếp
            updated_status = update_response.get("status", {}).get("privacyStatus")
            if updated_status == new_status:
                logger.info(f"Successfully updated video '{video_id}' status to '{new_status}'.")
                return True
            else:
                logger.error(f"Status update call succeeded but status did not change as expected for '{video_id}'. Response: {update_response}")
                return False

        except googleapiclient.errors.HttpError as e:
            error_content = e.content.decode('utf-8') if e.content else str(e)
            if e.resp.status == 404:
                logger.error(f"Video with ID '{video_id}' not found when attempting to update status.")
            elif e.resp.status == 403:
                # Lỗi vẫn là 403 ở đây thì vấn đề chắc chắn là scope 'upload'
                logger.error(f"Permission error (403) when attempting direct status UPDATE for '{video_id}': {error_content}")
                logger.error("This strongly indicates the refresh token lacks 'youtube.upload' scope.")
            else:
                logger.error(f"An HTTP error occurred while updating video status for '{video_id}': {e.resp.status} {error_content}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred updating video status for '{video_id}': {e}", exc_info=True)
            return False
        
# Example usage (Optional - for testing this module directly)
if __name__ == '__main__':
     print("--- Testing YouTubeUploader (reading secrets file path) ---")
     # Load .env variables relative to this script's location if needed
     from dotenv import load_dotenv
     from pathlib import Path
     # Assuming this script is in src/, load .env from parent
     env_path = Path(__file__).resolve().parent.parent / '.env'
     if os.path.exists(env_path):
          load_dotenv(dotenv_path=env_path)
          print(f"Loaded .env from: {env_path}")
     else:
          load_dotenv() # Try loading from CWD or default locations
          print("Attempted to load .env from default locations.")


     # Get credentials from env
     SECRETS_FILENAME_TEST = os.getenv('YOUTUBE_CLIENT_SECRETS_FILE', 'client_secrets.json')
     # Construct path relative to project root (assuming structure)
     try:
         PROJECT_ROOT_TEST = Path(__file__).resolve().parent.parent
     except NameError:
         PROJECT_ROOT_TEST = Path('.').resolve()

     CLIENT_SECRETS_PATH_TEST = str(PROJECT_ROOT_TEST / SECRETS_FILENAME_TEST) # Convert Path to string
     REFRESH_TOKEN_TEST = os.getenv('YOUTUBE_REFRESH_TOKEN')

     # --- Dummy Video File ---
     # You might need to adjust the path or ensure ffmpeg is available
     import shutil
     import subprocess
     DUMMY_VIDEO_PATH = str(PROJECT_ROOT_TEST / "output" / "dummy_upload_test.mp4")
     os.makedirs(PROJECT_ROOT_TEST / "output", exist_ok=True) # Ensure output dir exists

     def create_dummy_video(output_path):
        if os.path.exists(output_path): return True
        logger.info(f"Creating dummy video file: {output_path}")
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            logger.error("ffmpeg not found in PATH.")
            return False
        try:
            cmd = [ffmpeg_path, "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=640x360:rate=24",
                   "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "64k", "-shortest", output_path]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info("Dummy video created.")
            return True
        except Exception as e:
            logger.error(f"Failed to create dummy video: {e}")
            return False

     # --- Run Upload Test ---
     if not os.path.exists(CLIENT_SECRETS_PATH_TEST):
          print(f"ERROR: Client secrets file not found at: {CLIENT_SECRETS_PATH_TEST}")
     elif not REFRESH_TOKEN_TEST:
          print("ERROR: YOUTUBE_REFRESH_TOKEN not found in .env")
     elif not create_dummy_video(DUMMY_VIDEO_PATH):
          print(f"ERROR: Failed to create dummy video at {DUMMY_VIDEO_PATH}")
     else:
          print(f"Using Client Secrets File Path: {CLIENT_SECRETS_PATH_TEST}")
          print(f"Using Refresh Token: {REFRESH_TOKEN_TEST[:10]}...")
          print(f"Uploading test video: {DUMMY_VIDEO_PATH}")

          uploader = None
          try:
              # Khởi tạo với đường dẫn file secrets và refresh token
              uploader = YouTubeUploader(
                  client_secrets_file_path=CLIENT_SECRETS_PATH_TEST,
                  refresh_token=REFRESH_TOKEN_TEST
              )

              if not uploader.youtube_client:
                   print("ERROR: Failed to initialize YouTube client within Uploader.")
              else:
                    # Chuẩn bị metadata
                    test_title = f"API Path Test - {time.strftime('%Y%m%d_%H%M%S')}"
                    test_description = "Testing video upload using secrets file path."
                    test_tags = ["test", "path", "python"]
                    test_category = "28"
                    test_privacy = "private"

                    video_id = uploader.upload_video(
                        video_path=DUMMY_VIDEO_PATH,
                        title=test_title,
                        description=test_description,
                        tags=test_tags,
                        category_id=test_category,
                        privacy_status=test_privacy,
                        language="en"
                    )

                    if video_id:
                        print(f"\n--- TEST SUCCESS ---")
                        print(f"Video ID: {video_id}")
                        print(f"Watch Link: https://www.youtube.com/watch?v={video_id}")
                    else:
                        print("\n--- TEST FAILED ---")
                        print("Upload failed. Check logs.")

          except (FileNotFoundError, ValueError) as init_err:
               print(f"\nERROR during initialization: {init_err}")
          except Exception as e:
               print(f"\nAn unexpected error occurred: {e}")
               import traceback
               traceback.print_exc()
          finally:
               if os.path.exists(DUMMY_VIDEO_PATH):
                    try: os.remove(DUMMY_VIDEO_PATH); logger.info("Removed dummy video.")
                    except: pass

     print("\n--- YouTubeUploader Test Finished ---")