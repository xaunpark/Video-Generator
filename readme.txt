.\venv\Scripts\activate

Nếu bạn chia sẻ project này với người khác, hãy thêm một file README.md hoặc phần hướng dẫn chỉ rõ:

1. Cần tạo một file .env ở thư mục gốc.

2. Nội dung cần có trong file .env (có thể tạo một file .env.example với các key trống để họ copy và điền vào). Ví dụ file .env.example:

# .env.example - Copy this file to .env and fill in your actual keys
OPENAI_API_KEY=""
ELEVENLABS_API_KEY=""
SERPER_API_KEY=""
PEXELS_API_KEY=""
PIXABAY_API_KEY=""
# YOUTUBE_CLIENT_ID=""
# YOUTUBE_CLIENT_SECRET=""
# YOUTUBE_REFRESH_TOKEN=""

3. Thêm .env.example vào Git, nhưng .env thì không.

-------------------

Lần sau mỗi project, bạn nên có sẵn file:

requirements.txt

Hoặc mỗi khi thêm thư viện mới:

pip freeze > requirements.txt

Để sau này chỉ cần:

pip install -r requirements.txt

là đầy đủ lại y như cũ.

-------------------

MOVIEPY CÀI BẢN 1.0.3 \\ VẪN CẦN CÀI BẢN 2.1.2 NHƯNG SỬ DỤNG CÁC CHUẨN MỚI

pip uninstall moviepy
pip install moviepy==1.0.3

--------------------
TELEGRAM

Done! Congratulations on your new bot. You will find it at t.me/MyVideoUploadNotifyBot. You can now add a description, about section and profile picture for your bot, see /help for a list of commands. By the way, when you've finished creating your cool bot, ping our Bot Support if you want a better username for it. Just make sure the bot is fully operational before you do this.

Use this token to access the HTTP API:
7217562669:AAGdsMljsULjLqoGKG4TOvfuS2MIaevbhyo
Keep your token secure and store it safely, it can be used by anyone to control your bot.

For a description of the Bot API, see this page: https://core.telegram.org/bots/api

---
Telegram bot id của MyVideoUploadNotifyBot: 6452766273