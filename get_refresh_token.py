import os
import pickle
import google.oauth2.credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# --- Cấu hình ---
# Đường dẫn tới file client secrets JSON bạn đã tải về
CLIENT_SECRETS_FILE = "client_secrets.json"

# Phạm vi quyền cần thiết để quản lý video YouTube
# Đảm bảo bạn đã bật YouTube Data API v3 trong Google Cloud Console
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"] # Thêm readonly nếu cần đọc thông tin

# Tên file để lưu trữ tạm thời credentials (bao gồm refresh token) sau khi xác thực
# File này không cần thiết sau khi bạn đã lấy và lưu refresh token vào .env
CREDENTIALS_PICKLE_FILE = 'token.pickle'
# ----------------

def get_credentials():
    """Thực hiện quy trình OAuth 2.0 để lấy credentials."""
    creds = None
    # File token.pickle lưu trữ token truy cập và làm mới của người dùng,
    # và được tạo tự động khi quy trình ủy quyền hoàn tất lần đầu.
    if os.path.exists(CREDENTIALS_PICKLE_FILE):
        try:
            with open(CREDENTIALS_PICKLE_FILE, 'rb') as token:
                creds = pickle.load(token)
                print("Credentials loaded from token.pickle")
        except Exception as e:
             print(f"Error loading token.pickle: {e}. Will re-authenticate.")
             creds = None # Đảm bảo creds là None nếu load lỗi

    # Nếu không có credentials hợp lệ, yêu cầu người dùng đăng nhập.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Credentials expired, attempting to refresh...")
            try:
                creds.refresh(Request())
                print("Credentials refreshed successfully.")
            except Exception as e:
                print(f"Failed to refresh credentials: {e}")
                print("Proceeding with full authentication flow.")
                creds = None # Reset creds để chạy flow mới
        else:
            print("No valid credentials found, starting authentication flow...")
            # Kiểm tra client_secrets.json tồn tại
            if not os.path.exists(CLIENT_SECRETS_FILE):
                 print(f"ERROR: Client secrets file not found at '{CLIENT_SECRETS_FILE}'")
                 print("Please download the OAuth 2.0 Client ID JSON for a 'Desktop app' from Google Cloud Console and save it here.")
                 return None

            try:
                # Tạo luồng OAuth 2.0 từ file client secrets
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRETS_FILE, SCOPES)

                # Chạy luồng xác thực cục bộ, mở trình duyệt để người dùng đăng nhập và cấp quyền
                # port=0 sẽ tìm một cổng trống ngẫu nhiên
                creds = flow.run_local_server(port=0)
                print("Authentication successful!")
            except Exception as e:
                 print(f"Error during authentication flow: {e}")
                 return None

        # Lưu credentials cho lần chạy tiếp theo (nếu muốn, nhưng không cần thiết sau khi lấy refresh token)
        try:
            with open(CREDENTIALS_PICKLE_FILE, 'wb') as token:
                pickle.dump(creds, token)
            print(f"Credentials saved to {CREDENTIALS_PICKLE_FILE}")
        except Exception as e:
            print(f"Error saving credentials to pickle file: {e}")

    return creds

if __name__ == '__main__':
    print("Attempting to obtain YouTube API credentials...")
    credentials = get_credentials()

    if credentials:
        print("\n--- Credentials Obtained Successfully ---")
        if credentials.refresh_token:
            print("\n!!! IMPORTANT: Copy the Refresh Token below and save it securely !!!")
            print("-----------------------------------------------------------------------")
            print(f"YOUR REFRESH TOKEN: {credentials.refresh_token}")
            print("-----------------------------------------------------------------------")
            print(f"\nAdd this line to your .env file:")
            print(f"YOUTUBE_REFRESH_TOKEN={credentials.refresh_token}")
            print("\nYou can now delete the 'token.pickle' file if you wish.")
        else:
            print("\nWARNING: Successfully authenticated, but NO refresh token was found in the credentials.")
            print("This might happen if you've revoked access previously or due to specific Google account settings.")
            print("Try removing 'token.pickle' and running the script again.")
            print("If the issue persists, you may need to re-check your Google Cloud Project settings or account permissions.")

        # Tùy chọn: In Access Token (chỉ có giá trị trong 1 giờ)
        # if credentials.token:
        #     print(f"\nAccess Token (expires soon): {credentials.token[:30]}...")

    else:
        print("\n--- Failed to obtain credentials ---")
        print("Please check the error messages above and ensure:")
        print(f"1. '{CLIENT_SECRETS_FILE}' exists and is valid (downloaded for 'Desktop app').")
        print("2. You completed the browser authentication and granted permissions.")
        print("3. YouTube Data API v3 is enabled in your Google Cloud project.")