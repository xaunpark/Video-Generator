# src/telegram_notifier.py
import logging
import telegram # Vẫn cần để bắt lỗi và dùng type hint nếu muốn
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
import html # Dùng thư viện chuẩn để escape HTML
import asyncio # Cần thiết cho async/await

# --- Import credentials một cách an toàn ---
# Giả định các biến này được đọc từ .env trong config/credentials.py
try:
    from config.credentials import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    logging.error("Could not import Telegram credentials from config.credentials. Ensure variables are set.")
    TELEGRAM_BOT_TOKEN = None
    TELEGRAM_CHAT_ID = None

logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s')

class TelegramNotifier:
    """Handles sending notifications and interactive messages via Telegram Bot asynchronously."""

    def __init__(self, bot_token=None, chat_id=None):
        """
        Initializes the TelegramNotifier. Stores token and chat_id, creates Bot instance.

        Args:
            bot_token (str, optional): Telegram Bot API Token. Defaults to env var.
            chat_id (str | int, optional): Target Chat ID. Defaults to env var.

        Raises:
            ValueError: If bot_token or chat_id is missing or invalid.
            ConnectionError: If the bot object cannot be initialized (e.g., invalid token format).
        """
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID

        if not self.bot_token:
            logger.critical("Telegram Bot Token is missing.") # Dùng critical vì đây là lỗi nghiêm trọng
            raise ValueError("Telegram Bot Token is required.")
        if not self.chat_id:
            logger.critical("Telegram Chat ID is missing.")
            raise ValueError("Telegram Chat ID is required.")

        try:
            # Khởi tạo đối tượng Bot (đồng bộ)
            self.bot = telegram.Bot(token=self.bot_token)
            # Không cần gọi get_me() ở đây nữa để tránh vấn đề async trong init
            logger.info(f"Telegram Bot object initialized successfully for token ending in ...{self.bot_token[-6:]}")
            logger.info(f"Notifications will be sent to Chat ID: {self.chat_id}")
        except Exception as e:
            # Lỗi này thường ít xảy ra nếu token có định dạng đúng, lỗi thực sự hay ở lời gọi API sau đó
            logger.critical(f"Failed to initialize Telegram Bot object: {e}", exc_info=True)
            raise ConnectionError(f"Failed to initialize Telegram Bot object: {e}")

    async def send_message_async(self, message_text, parse_mode=None, reply_markup=None, disable_web_page_preview=True):
        """
        Sends a text message asynchronously to the configured chat_id.

        Args:
            message_text (str): The text of the message to send.
            parse_mode (str, optional): Mode for parsing entities (e.g., ParseMode.HTML).
            reply_markup (InlineKeyboardMarkup | ReplyKeyboardMarkup, optional): Keyboard markup.
            disable_web_page_preview (bool): Disable link previews.

        Returns:
            telegram.Message or None: The sent message object or None if failed.
        """
        if not self.bot:
            logger.error("Telegram Bot is not initialized. Cannot send message.")
            return None

        try:
            logger.debug(f"Sending message async to chat_id {self.chat_id}: {message_text[:100]}...")
            # Sử dụng await để gọi hàm bất đồng bộ của thư viện
            message = await self.bot.send_message(
                chat_id=self.chat_id,
                text=message_text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
            # Log message_id nếu thành công
            logger.info(f"Async message sent successfully (Message ID: {message.message_id}).")
            return message # Trả về đối tượng Message
        except telegram.error.BadRequest as e:
            logger.error(f"Telegram API Bad Request error sending message: {e}", exc_info=True)
        except telegram.error.NetworkError as e:
             logger.error(f"Telegram API Network error sending message: {e}", exc_info=True)
        except telegram.error.TelegramError as e:
            logger.error(f"Generic Telegram API error sending message: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error sending async Telegram message: {e}", exc_info=True)

        return None # Trả về None nếu có lỗi


    async def send_upload_notification_async(self, video_id, video_title, video_url, studio_url=None):
        """
        Sends a notification after a successful YouTube upload asynchronously,
        including a "Publish" button.

        Args:
            video_id (str): The YouTube video ID.
            video_title (str): The title of the uploaded video.
            video_url (str): The public watch URL for the video.
            studio_url (str, optional): The YouTube Studio URL for the video.

        Returns:
            telegram.Message or None: The sent message object or None if failed.
        """
        logger.info(f"Preparing async Telegram notification for video: {video_id} - '{video_title}'")

        # 1. Format Message Text (using HTML)
        message = (
            f"✅ <b>Video Uploaded Successfully!</b>\n\n"
            f"<b>Title:</b> {html.escape(video_title)}\n"
            f"<b>Video ID:</b> <code>{html.escape(video_id)}</code>\n\n"
            f"<a href='{video_url}'>Watch Video (Private)</a>"
        )
        if studio_url:
            message += f" | <a href='{studio_url}'>Edit in Studio</a>"
        message += "\n\nPlease review the video. Click below to publish."

        # 2. Create Inline Keyboard Button
        callback_data = f"publish_{video_id}"
        keyboard = [
            [InlineKeyboardButton("🚀 Publish Video", callback_data=callback_data)],
            # Optional: Add more buttons like delete
            # [InlineKeyboardButton("🗑️ Delete Video", callback_data=f"delete_{video_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 3. Send the message using the async helper method
        return await self.send_message_async(
            message_text=message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=False # Allow YouTube preview
        )