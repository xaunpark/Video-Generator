# test_telegram.py
import html
import logging
import os
import sys
import time
from dotenv import load_dotenv
import asyncio # Import asyncio
import threading

from telegram import InlineKeyboardButton, InlineKeyboardMarkup # Vẫn cần cho listener
from telegram.constants import ParseMode

# --- Setup đường dẫn và Logging ---
try:
    project_root = os.path.dirname(os.path.abspath(__file__))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except NameError:
    project_root = '.'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('telegram_test_async.log', encoding='utf-8') # Log riêng
    ]
)
logger = logging.getLogger("TelegramTestAsync")

# --- Tải Biến Môi trường ---
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)
logger.info(f"Loaded .env from: {dotenv_path if os.path.exists(dotenv_path) else 'default locations'}")

# --- Import Modules ---
try:
    from src.telegram_notifier import TelegramNotifier
    from src import telegram_bot_listener # Import module listener
    from config.credentials import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError as e:
    logger.critical(f"Failed to import necessary modules: {e}")
    sys.exit(1)

# --- Biến Test ---
TEST_VIDEO_ID = "HpMI2Q0pNOE"
TEST_VIDEO_TITLE = "API Test (Secrets File): test_video.mp4 - 20250409_173111"
TEST_VIDEO_URL = f"https://youtube.com/watch?v={TEST_VIDEO_ID}"
TEST_STUDIO_URL = f"https://youtube.com/studio/{TEST_VIDEO_ID}"

# --- Hàm chạy listener trong thread riêng (VẪN CẦN THREAD RIÊNG) ---
# Listener dùng Application.run_polling, nó tự quản lý loop của nó,
# nhưng vẫn cần chạy trong thread riêng để không chặn hàm test chính.
listener_stop_event = threading.Event() # Dùng event để báo dừng

def run_listener_in_thread():
    """Chạy hàm main của listener trong một thread với event loop asyncio riêng."""
    current_thread = threading.current_thread().name
    logger.info(f"[{current_thread}] Starting Telegram listener thread...")

    # 1. Tạo event loop mới cho thread này
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info(f"[{current_thread}] Created and set new asyncio event loop.")

    try:
        # 2. Chạy hàm main của listener, hàm này sẽ sử dụng loop hiện tại
        logger.info(f"[{current_thread}] Calling telegram_bot_listener.main()...")
        telegram_bot_listener.main() # Hàm này chứa application.run_polling()

        # 3. Nếu main() thoát bình thường (ví dụ do updater.stop()),
        #    cần đảm bảo loop chạy các tác vụ cleanup cuối cùng nếu có.
        #    Tuy nhiên, run_polling thường chặn nên đoạn này ít khi chạy.
        # logger.info(f"[{current_thread}] Listener main function finished. Running loop until complete...")
        # loop.run_forever() # Hoặc loop.run_until_complete(...) nếu có task cụ thể

    except Exception as e:
        logger.error(f"[{current_thread}] Error encountered within listener's main execution: {e}", exc_info=True)
    finally:
        # 4. Dọn dẹp và đóng loop khi thread kết thúc
        logger.info(f"[{current_thread}] Cleaning up listener thread...")
        if loop.is_running():
            logger.info(f"[{current_thread}] Stopping event loop...")
            loop.call_soon_threadsafe(loop.stop) # Yêu cầu loop dừng một cách an toàn từ thread khác nếu cần
            # Hoặc đơn giản là chờ loop tự dừng nếu run_polling kết thúc
            # time.sleep(1) # Chờ một chút

        # Hủy các task còn lại
        try:
            tasks = asyncio.all_tasks(loop)
            if tasks:
                 logger.info(f"[{current_thread}] Cancelling {len(tasks)} outstanding tasks...")
                 for task in tasks:
                     task.cancel()
                 # Chạy loop để xử lý việc hủy
                 loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                 logger.info(f"[{current_thread}] Finished cancelling tasks.")
            else:
                 logger.info(f"[{current_thread}] No outstanding tasks to cancel.")
        except RuntimeError as e:
             # Có thể lỗi "cannot cancel tasks" nếu loop đã đóng hoàn toàn
             logger.warning(f"[{current_thread}] Error during task cancellation (loop might be closed): {e}")
        except Exception as cancel_err:
             logger.warning(f"[{current_thread}] Unexpected error during task cancellation: {cancel_err}")

        # Đóng loop
        if not loop.is_closed():
             logger.info(f"[{current_thread}] Closing event loop.")
             loop.close()
             logger.info(f"[{current_thread}] Event loop closed.")
        else:
            logger.info(f"[{current_thread}] Event loop was already closed.")

    logger.info(f"[{current_thread}] Listener thread finished execution.")

# --- Hàm Test Chính (Async) ---
async def run_telegram_test_async():
    logger.info("--- Starting Async Telegram Integration Test ---")

    # 1. Kiểm tra Credentials
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials missing in .env. Aborting test.")
        print("ERROR: Telegram credentials missing in .env")
        return

    # 2. Khởi chạy Listener trong Thread
    # Sử dụng daemon=True để thread tự thoát khi chương trình chính kết thúc
    listener_thread = threading.Thread(target=run_listener_in_thread, daemon=True, name="TelegramListenerThread")
    listener_thread.start()
    logger.info("Waiting for listener thread to initialize (give it ~5 seconds)...")
    await asyncio.sleep(5) # Đợi listener khởi động

    # Kiểm tra nhanh xem thread còn sống không
    if not listener_thread.is_alive():
        logger.error("Listener thread seems to have failed immediately. Check listener logs (telegram_listener.log).")
        print("ERROR: Listener failed to start.")
        return
    logger.info("Listener thread should be running in the background.")

    # 3. Khởi tạo Notifier
    notifier = None
    try:
        logger.info("Initializing TelegramNotifier...")
        # Khởi tạo notifier vẫn là đồng bộ
        notifier = TelegramNotifier(bot_token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)
        logger.info("TelegramNotifier initialized.")
    except (ValueError, ConnectionError) as e:
        logger.error(f"Failed to initialize TelegramNotifier: {e}")
        print(f"ERROR: Failed to initialize notifier: {e}")
        return
    except Exception as e:
         logger.error(f"Unexpected error initializing notifier: {e}", exc_info=True)
         print(f"ERROR: Unexpected error initializing notifier.")
         return

    # --- Quan trọng: Sửa đổi lại hàm send_message trong TelegramNotifier ---
    # --- để nó là async def và gọi await self.bot.send_message ---
    # --- Bỏ qua bước asyncio.run() bên trong send_message ---
    # --- Xem hàm send_message_async mẫu bên dưới ---

    # 4. Gửi Tin nhắn Test Đơn giản (Dùng await)
    try:
        logger.info("Sending simple test message (async)...")
        # Gọi hàm async mới
        msg1 = await notifier.send_message_async("Async Telegram Test: Simple message.")
        if msg1:
            logger.info(f"Simple async message sent successfully. ID: {msg1.message_id}")
            print("STEP 1: Check your Telegram for a simple test message.")
        else:
            logger.error("Failed to send simple async test message.")
            print("ERROR: Failed to send simple message.")
    except Exception as e:
        logger.error(f"Error sending simple async message: {e}", exc_info=True)
        print("ERROR: Exception during simple message send.")

    logger.info("\nWaiting 5 seconds before sending notification with button...")
    await asyncio.sleep(5)

    # 5. Gửi Thông báo Upload với Nút Bấm (Dùng await)
    try:
        logger.info("Sending upload notification with 'Publish' button (async)...")
        # Gọi hàm async mới
        msg2 = await notifier.send_upload_notification_async(
            video_id=TEST_VIDEO_ID,
            video_title=TEST_VIDEO_TITLE,
            video_url=TEST_VIDEO_URL,
            studio_url=TEST_STUDIO_URL
        )
        if msg2:
            logger.info(f"Upload notification async message sent successfully. ID: {msg2.message_id}")
            print("\nSTEP 2: Check your Telegram for a message with a 'Publish Video' button.")
            print("          >>> PRESS the 'Publish Video' button on Telegram now! <<<")
        else:
            logger.error("Failed to send async upload notification message.")
            print("ERROR: Failed to send message with button.")
            return

    except Exception as e:
        logger.error(f"Error sending async upload notification: {e}", exc_info=True)
        print("ERROR: Exception during upload notification send.")
        return

    # 6. Đợi người dùng nhấn nút và listener xử lý
    print("\nWaiting for you to press the button and for the listener to respond...")
    print("(Listener running in background. Check listener logs)")
    print("\nPress Ctrl+C here in the terminal to stop the test when done observing.")
    try:
        while listener_thread.is_alive():
            await asyncio.sleep(0.5) # Kiểm tra định kỳ
        logger.info("Listener thread has exited.")
    except asyncio.CancelledError:
         logger.info("Main async task cancelled.")
    except KeyboardInterrupt:
        logger.info("Ctrl+C detected. Stopping test.")
        # Cố gắng dừng listener một cách nhẹ nhàng (nếu có cơ chế)
        # Hiện tại dựa vào daemon thread
    finally:
        logger.info("--- Async Telegram Integration Test Finished ---")
        print("\nTest finished. Check logs.")

if __name__ == "__main__":
    # Chạy hàm async chính bằng asyncio.run()
    try:
        asyncio.run(run_telegram_test_async())
    except KeyboardInterrupt:
        logger.info("Test stopped by user.")
    except Exception as main_err:
         logger.critical(f"Critical error running async test: {main_err}", exc_info=True)