# src/telegram_bot_listener.py

import html
import logging
import os
import sys
import time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton # Import thêm các lớp cần thiết
import telegram
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext, filters

# --- Setup đường dẫn và Logging ---
try:
    # Giả định listener.py nằm trong src/, cần tìm thư mục gốc (parent)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
except NameError:
     # Fallback nếu __file__ không tồn tại
     project_root = '.'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] - %(message)s', # Thêm tên hàm vào format
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('telegram_listener.log', encoding='utf-8') # Log riêng cho listener
    ]
)
logger = logging.getLogger("TelegramBotListener")

# --- Tải Biến Môi trường ---
dotenv_path = os.path.join(project_root, '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    logger.info(f"Loaded environment variables from: {dotenv_path}")
else:
    load_dotenv()
    logger.warning(".env file not found at project root. Attempting load from default locations.")

# --- Import Credentials và Uploader ---
try:
    from config.credentials import (
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID, # Có thể cần để xác thực người dùng nếu muốn
        YOUTUBE_CLIENT_SECRETS_FILE_PATH, # Đường dẫn tuyệt đối đã tạo
        YOUTUBE_REFRESH_TOKEN
    )
    from src.youtube_uploader import YouTubeUploader
except ImportError as e:
    logger.critical(f"Failed to import necessary modules: {e}")
    logger.critical("Ensure config/credentials.py and src/youtube_uploader.py exist and are correct.")
    sys.exit(1)

# --- Kiểm tra Credentials ---
if not TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN not found in environment variables. Listener cannot start.")
    sys.exit(1)
# Kiểm tra các credentials YouTube cũng quan trọng vì sẽ dùng đến chúng
if not YOUTUBE_CLIENT_SECRETS_FILE_PATH or not YOUTUBE_REFRESH_TOKEN:
     logger.critical("YouTube credentials (Secrets Path or Refresh Token) missing. Listener cannot publish videos.")
     sys.exit(1)
if not os.path.exists(YOUTUBE_CLIENT_SECRETS_FILE_PATH):
     logger.critical(f"YouTube Client Secrets file not found at: {YOUTUBE_CLIENT_SECRETS_FILE_PATH}")
     sys.exit(1)


# --- Hàm Callback Xử lý Nút Bấm ---
async def button_callback(update: Update, context: CallbackContext) -> None:
    """Handles button presses from inline keyboards."""
    query = update.callback_query
    user = query.from_user # Người dùng đã nhấn nút

    # Rất nên kiểm tra xem người nhấn nút có phải là bạn không (dựa vào chat_id hoặc user_id)
    # Để tránh người lạ publish video của bạn
    authorized_chat_id = TELEGRAM_CHAT_ID
    if authorized_chat_id and str(query.message.chat_id) != str(authorized_chat_id):
         logger.warning(f"Unauthorized button press attempt from chat_id {query.message.chat_id} (expected {authorized_chat_id}). User: {user.username or user.first_name}")
         try:
              query.answer(text="Sorry, you are not authorized to perform this action.", show_alert=True)
         except Exception as ans_err:
              logger.error(f"Error sending unauthorized answer: {ans_err}")
         return # Không xử lý gì thêm

    # Bắt buộc phải gọi query.answer() để tắt trạng thái loading trên nút bấm
    try:
        await query.answer() # Gửi tín hiệu đã nhận
    except Exception as e:
         logger.warning(f"Could not answer callback query: {e}") # Log lỗi nếu không answer được

    callback_data = query.data
    logger.info(f"Received callback data: '{callback_data}' from user {user.id} ({user.username or user.first_name})")

    # Phân tích callback_data
    if callback_data and callback_data.startswith("publish_"):
        video_id = callback_data.split("publish_", 1)[1]
        if not video_id:
             logger.error("Callback data 'publish_' received without video ID.")
             try: # Cố gắng thông báo lỗi cho người dùng
                  await query.edit_message_text(text=f"{query.message.text}\n\n⚠️ Error: Could not extract video ID.", parse_mode='HTML')
             except Exception: pass
             return

        logger.info(f"Attempting to publish video ID: {video_id}")

        # Gửi tin nhắn tạm thời báo đang xử lý
        try:
            await query.edit_message_text(
                text=f"{query.message.text}\n\n⏳ Processing publish request for <code>{video_id}</code>...",
                reply_markup=None, # Xóa nút bấm cũ
                parse_mode='HTML'
            )
        except Exception as edit_err:
            logger.warning(f"Could not edit message to 'Processing': {edit_err}")
            # Gửi tin nhắn mới nếu edit lỗi
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"⏳ Processing publish request for {video_id}...")


        # Gọi Logic Publish YouTube
        publish_success = False
        error_message = "An unknown error occurred."
        try:
            logger.info("Initializing YouTubeUploader for publishing...")
            # Khởi tạo uploader với credentials đã load
            uploader = YouTubeUploader(
                client_secrets_file_path=YOUTUBE_CLIENT_SECRETS_FILE_PATH,
                refresh_token=YOUTUBE_REFRESH_TOKEN
            )

            # Kiểm tra client trước khi gọi update
            if not uploader.youtube_client:
                 logger.error("Failed to initialize YouTube client within callback.")
                 error_message = "Failed to connect to YouTube."
            else:
                 # Gọi hàm cập nhật trạng thái video thành 'public'
                 publish_success = uploader.update_video_status(video_id, new_status="public")
                 if not publish_success:
                      error_message = "YouTube API failed to update status. Check listener logs."


        except FileNotFoundError as fnf_err:
             logger.error(f"Error initializing uploader in callback (FileNotFound): {fnf_err}")
             error_message = "Configuration error (secrets file)."
        except ValueError as val_err:
             logger.error(f"Error initializing uploader in callback (ValueError): {val_err}")
             error_message = "Configuration error (refresh token)."
        except Exception as e:
            logger.error(f"Unexpected error during YouTube publish process for {video_id}: {e}", exc_info=True)
            error_message = f"An unexpected error occurred: {e}"

        # Phản hồi kết quả cuối cùng cho người dùng
        final_message_text = query.message.text # Lấy text gốc của tin nhắn (không có chữ Processing)

        if publish_success:
            logger.info(f"Successfully published video ID: {video_id}")
            # Tạo link mới
            published_video_url = f"https://www.youtube.com/watch?v={video_id}"
            # Cập nhật tin nhắn thành công và xóa nút bấm cũ
            try:
                await query.edit_message_text(
                    text=f"{final_message_text}\n\n✅ <b>Successfully published!</b>\nWatch: <a href='{published_video_url}'>{published_video_url}</a>",
                    reply_markup=None, # Xóa bàn phím
                    parse_mode='HTML',
                    disable_web_page_preview=False
                )
            except Exception as final_edit_err:
                 logger.error(f"Could not edit final success message: {final_edit_err}")
                 await context.bot.send_message(chat_id=query.message.chat_id, text=f"✅ Video {video_id} published: {published_video_url}")

        else:
            logger.error(f"Failed to publish video ID: {video_id}. Reason: {error_message}")
            # Giữ lại nút bấm để người dùng có thể thử lại? Hoặc thông báo lỗi
            try:
                 # Thêm thông báo lỗi vào tin nhắn, giữ lại nút bấm để thử lại nếu muốn
                 # Hoặc xóa nút bấm: reply_markup=None
                await query.edit_message_text( # Nhớ thêm await
                    text=f"{final_message_text}\n\n❌ <b>Publish failed:</b> {html.escape(error_message)}\nPlease check logs.", # <-- Sửa thành html.escape
                    reply_markup=query.message.reply_markup, # Giữ lại nút để thử lại? Hoặc None để xóa
                    parse_mode='HTML'
                )
            except Exception as final_edit_err:
                 logger.error(f"Could not edit final error message: {final_edit_err}")
                 await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Failed to publish video {video_id}. Error: {error_message}")

    # Xử lý các callback data khác nếu có (ví dụ: delete)
    elif callback_data and callback_data.startswith("delete_"):
         video_id = callback_data.split("delete_", 1)[1]
         logger.warning(f"Received 'delete' request for video {video_id} (Not implemented yet).")
         try:
             await query.edit_message_text(text=f"{query.message.text}\n\nℹ️ Delete action for {video_id} is not implemented yet.", reply_markup=None, parse_mode='HTML')
         except: pass # Ignore edit errors for unimplemented action
    else:
         logger.warning(f"Received unknown callback data: {callback_data}")
         try:
             query.answer(text="Unknown action.")
         except: pass


# --- Hàm Main để Chạy Bot Listener ---
def main() -> None:
    """Starts the Telegram bot listener."""
    logger.info("Initializing Telegram Bot Updater...")

     # Tạo ApplicationBuilder và truyền token
    try:
         application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    except Exception as build_err:
         logger.critical(f"Failed to build Telegram Application: {build_err}", exc_info=True)
         sys.exit(1)
    # -----------------------------

    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"^(publish_|delete_).+"))
    logger.info("CallbackQueryHandler registered for 'publish_' and 'delete_' patterns.")

    # Bắt đầu chạy bot bằng polling
    logger.info("Starting bot polling...")
    # Sử dụng application.run_polling() thay vì updater.start_polling()/idle()
    # allowed_updates có thể giúp lọc bớt các update không cần thiết
    application.run_polling(allowed_updates=Update.CALLBACK_QUERY)
    # -----------------------------

    # Code sau run_polling sẽ chỉ chạy khi bot dừng (ví dụ: Ctrl+C)
    logger.info("Telegram bot listener stopped.")

if __name__ == '__main__':
    main()