# main.py
import logging
import os
import sys
import json
from datetime import datetime
from src.news_scraper import NewsScraper
from src.script_generator import ScriptGenerator
from src.image_generator import ImageGenerator
from src.voice_generator import VoiceGenerator
from src.video_editor import VideoEditor
from config.settings import OUTPUT_DIR, TEMP_DIR, ASSETS_DIR

from newspaper import Article
import time

from urllib.parse import urlparse, parse_qs
import re

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# Force always using controversial style
FORCE_CONTROVERSIAL_STYLE = False

# --- Add youtube-transcript-api import ---
try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
except ImportError:
    YouTubeTranscriptApi = None
# -----------------------------------------

# --- Hàm Helper để hỏi Style ---
def prompt_for_style():
    """Hàm hiển thị menu, hỏi và trả về style do người dùng chọn."""
    print("\nChọn phong cách cho video:")
    print("1. Thông tin (informative) - Giọng điệu chính thống, chuyên nghiệp")
    print("2. Hội thoại (conversational) - Giọng điệu thân thiện, gần gũi")
    print("3. Kịch tính (dramatic) - Gây ấn tượng mạnh, tập trung vào tác động")
    print("4. Gây tranh cãi (controversial) - Nêu bật các quan điểm đối lập, gây tranh luận")
    # Thêm các style khác nếu có trong prompt_generator.py
    print("5. Cảm xúc (emotional)")
    print("6. Hài hước (funny)")
    print("7. Truyền động lực (motivational)")


    style_choice = ""
    # Cập nhật số lượng lựa chọn hợp lệ
    valid_choices = ["1", "2", "3", "4", "5", "6", "7"]
    while style_choice not in valid_choices:
        style_choice = input(f"Nhập lựa chọn phong cách ({','.join(valid_choices)}, mặc định là 1): ").strip()
        if not style_choice:
            style_choice = "1"  # Mặc định là Informative

    # Ánh xạ lựa chọn sang phong cách
    style_map = {
        "1": "informative",
        "2": "conversational",
        "3": "dramatic",
        "4": "controversial",
        "5": "emotional",
        "6": "funny",
        "7": "motivational"
    }
    return style_map.get(style_choice, "informative") # Fallback về informative
# --- Kết thúc hàm Helper ---

def get_article_from_url(url):
    """
    Lấy thông tin bài báo từ một URL cụ thể sử dụng newspaper3k.

    Args:
        url (str): URL của bài báo.

    Returns:
        dict: Một dictionary chứa thông tin bài báo (title, content, image_url, source, url)
              hoặc None nếu có lỗi.
    """
    try:
        logger.info(f"Đang tải và phân tích bài báo từ URL: {url}")
        article_obj = Article(url)
        article_obj.download()
        time.sleep(1)
        article_obj.parse()

        if not article_obj.title or not article_obj.text:
            logger.error(f"Không thể trích xuất tiêu đề hoặc nội dung từ URL: {url}")
            return None

        # Tạo cấu trúc giống như bài báo lấy từ RSS
        article_data = {
            'title': article_obj.title,
            'content': article_obj.text,
            'summary': article_obj.summary, # newspaper3k tự tạo summary
            'image_url': article_obj.top_image,
            'source': article_obj.source_url or urlparse(url).netloc, # Lấy tên miền làm nguồn nếu có
            'url': url,
            'published_date': article_obj.publish_date.strftime("%Y-%m-%d") if article_obj.publish_date else datetime.now().strftime("%Y-%m-%d"),
            'language': article_obj.meta_lang or 'en' # Thử lấy ngôn ngữ từ meta tag
        }
        logger.info(f"Đã trích xuất thành công bài báo: '{article_data['title']}'")
        return article_data

    except Exception as e:
        logger.error(f"Lỗi khi xử lý URL bài báo {url}: {str(e)}", exc_info=True)
        return None

# --- Function to get YouTube transcript ---
def get_youtube_transcript(video_url, languages=None):
    """
    Fetches the transcript for a given YouTube video URL.

    Args:
        video_url (str): The URL of the YouTube video.
        languages (list, optional): List of preferred languages (e.g., ['vi', 'en']).
                                    Defaults to ['en', 'vi'].

    Returns:
        tuple: (transcript_text, detected_language) or (None, None) if failed.
    """
    if languages is None:
        languages = ['en', 'vi'] # Default preference

    if YouTubeTranscriptApi is None:
        logger.error("YouTubeTranscriptApi is not installed. Cannot fetch transcripts.")
        return None, None

    video_id = None
    try:
        # Try extracting video ID using regex for various URL formats
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', # Standard watch?v=... or /v/...
            r'(?:embed\/|v\/|youtu\.be\/)([0-9A-Za-z_-]{11}).*' # embed, v/, youtu.be/
        ]
        for pattern in patterns:
            match = re.search(pattern, video_url)
            if match:
                video_id = match.group(1)
                break

        if not video_id:
            logger.error(f"Could not extract YouTube video ID from URL: {video_url}")
            return None, None

        logger.info(f"Extracted YouTube Video ID: {video_id}")
        logger.info(f"Attempting to fetch transcript for video ID {video_id} in languages: {languages}")

        # Fetch the transcript
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Find a suitable transcript (manual or generated)
        transcript = None
        detected_language = None

        # Try preferred languages first
        for lang_code in languages:
            try:
                transcript = transcript_list.find_transcript([lang_code])
                detected_language = lang_code
                logger.info(f"Found manually created transcript in '{lang_code}'.")
                break
            except NoTranscriptFound:
                continue # Try next language

        # If no manual transcript in preferred languages, try generated ones
        if not transcript:
            for lang_code in languages:
                try:
                    transcript = transcript_list.find_generated_transcript([lang_code])
                    detected_language = lang_code
                    logger.info(f"Found automatically generated transcript in '{lang_code}'.")
                    break
                except NoTranscriptFound:
                    continue # Try next language

        # If still no transcript, try any available language
        if not transcript:
            logger.warning(f"No transcript found in preferred languages {languages}. Trying any available language.")
            try:
                 # Iterate through all available transcripts
                 available_transcripts = transcript_list._transcripts # Accessing internal dict might be fragile
                 if available_transcripts:
                    first_lang = list(available_transcripts.keys())[0]
                    transcript = transcript_list.find_transcript([first_lang])
                    detected_language = first_lang
                    logger.info(f"Found transcript in language: '{detected_language}'.")
                 else:
                    raise NoTranscriptFound("No transcripts available at all.")
            except NoTranscriptFound:
                logger.error(f"No transcript found for video {video_id} in any language.")
                return None, None

        # Fetch the actual transcript data
        transcript_data = transcript.fetch()

        # Combine the text segments
        full_transcript = " ".join([segment.text for segment in transcript_data])

        logger.info(f"Successfully fetched transcript (Language: {detected_language}, Length: {len(full_transcript)} chars)")
        return full_transcript, detected_language

    except TranscriptsDisabled:
        logger.error(f"Transcripts are disabled for video: {video_id}")
        return None, None
    except NoTranscriptFound: # Catch specific error if find_transcript fails broadly
        logger.error(f"Could not find any transcript for video: {video_id}")
        return None, None
    except Exception as e:
        logger.error(f"Error fetching YouTube transcript for {video_url}: {str(e)}", exc_info=True)
        return None, None
# --- End of new function ---

def main():
    logger.info("Starting automated news video generation program")
    
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

    # --- HỎI LỰA CHỌN CỦA NGƯỜI DÙNG ---
    print("\nChọn phương thức lấy tin tức:")
    print("1. Lấy tin mới nhất từ nguồn RSS đã cấu hình.")
    print("2. Nhập URL của một bài báo cụ thể.")
    print("3. Tạo video từ từ khóa (nội dung tạo bởi AI).")
    print("4. Tạo video từ phụ đề Video Youtube.")

    choice = ""

    while choice not in ["1", "2", "3", "4"]:
        choice = input("Nhập lựa chọn của bạn (1, 2, 3 hoặc 4): ").strip()
        if choice == "4" and YouTubeTranscriptApi is None:
            print("Lỗi: Tính năng này yêu cầu thư viện 'youtube-transcript-api'. Vui lòng cài đặt: pip install youtube-transcript-api")
            choice = "" # Reset choice to ask again

    # Khởi tạo các biến chung
    selected_article = None
    script = None
    articles = []
    categorized = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    selected_style = None
    keyword = None
    transcript_text = None
    youtube_url = None
    language = "en"
    script_generator = ScriptGenerator()

    # --- XỬ LÝ LỰA CHỌN 1: LẤY TỪ RSS ---
    if choice == "1":
        logger.info("Lựa chọn 1: Lấy tin từ RSS...")
        # Initialize scraper and fetch news
        scraper = NewsScraper()
        articles = scraper.fetch_articles(limit=5) # Giới hạn số lượng để không quá lâu

        if not articles:
            logger.error("Không tìm thấy bài báo nào từ RSS. Kết thúc chương trình.")
            return

        logger.info(f"Tìm thấy {len(articles)} bài báo từ RSS.")

        # Categorize articles
        categorized = scraper.categorize_articles(articles)
    
        # Save fetched news data to temp directory for future reference
        with open(os.path.join(TEMP_DIR, f"articles_{timestamp}.json"), 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
    
        # Select an article for video creation
        priority_categories = ['politics', 'technology', 'business', 'entertainment', 'general']
    
        for category in priority_categories:
            # Lấy danh sách bài báo cho category, xử lý trường hợp key không tồn tại
            category_articles = categorized.get(category, [])
            if category_articles: # Kiểm tra xem danh sách có rỗng không
                selected_article = category_articles[0]
                logger.info(f"Đã chọn bài báo từ danh mục {category}: {selected_article['title']}")
                break
    
        if not selected_article:
            # Fallback: Nếu không có bài nào trong các category ưu tiên, lấy bài đầu tiên
            if articles:
                selected_article = articles[0]
                logger.info(f"Không tìm thấy bài trong category ưu tiên, chọn bài báo đầu tiên: {selected_article['title']}")
            else:
                # Trường hợp này gần như không xảy ra vì đã kiểm tra articles ở trên
                logger.error("Không có bài báo nào phù hợp để tạo script.")
                return

        # *** Hỏi Style NGAY SAU KHI có selected_article ***
        selected_style = prompt_for_style()
        language = selected_article.get('language', 'vi') # Lấy ngôn ngữ từ bài báo
        logger.info(f"Ngôn ngữ bài báo: {language}. Phong cách đã chọn: {selected_style}")

        # Tạo script
        script = script_generator.generate_script(selected_article, style=selected_style)

    # --- XỬ LÝ LỰA CHỌN 2: NHẬP URL ---
    elif choice == "2":
        logger.info("Lựa chọn 2: Nhập URL bài báo...")
        article_url = ""
        while not article_url:
            article_url = input("Nhập URL bài báo bạn muốn tạo video: ").strip()
            if not article_url.startswith('http'):
                logger.warning("URL không hợp lệ. Vui lòng nhập URL đầy đủ (bắt đầu bằng http:// hoặc https://).")
                article_url = "" # Reset để hỏi lại

        # Lấy thông tin bài báo từ URL
        selected_article = get_article_from_url(article_url)

        if not selected_article:
            logger.error(f"Không thể xử lý bài báo từ URL đã nhập. Kết thúc chương trình.")
            return

        # *** Hỏi Style NGAY SAU KHI có selected_article ***
        selected_style = prompt_for_style()
        language = selected_article.get('language', 'vi') # Lấy ngôn ngữ từ bài báo
        logger.info(f"Ngôn ngữ bài báo: {language}. Phong cách đã chọn: {selected_style}")

        # Tạo script
        script = script_generator.generate_script(selected_article, style=selected_style)

        # Lưu bài báo đã nhập để tham khảo (tùy chọn)
        try:
            sanitized_title = "".join(c for c in selected_article['title'][:50] if c.isalnum() or c in (' ', '_')).rstrip()
            sanitized_title = sanitized_title.replace(' ', '_')
            article_filename = f"article_url_{sanitized_title}_{timestamp}.json"
            with open(os.path.join(TEMP_DIR, article_filename), 'w', encoding='utf-8') as f:
                json.dump(selected_article, f, ensure_ascii=False, indent=2)
            logger.info(f"Đã lưu thông tin bài báo từ URL vào: {article_filename}")
        except Exception as save_err:
            logger.warning(f"Không thể lưu thông tin bài báo từ URL: {save_err}")

    # --- XỬ LÝ LỰA CHỌN 3: TẠO VIDEO TỪ TỪ KHÓA BẰNG AI ---
    elif choice == "3":
        logger.info("Lựa chọn 3: Tạo video từ từ khóa bằng AI...")
        keyword = ""
        while not keyword:
            keyword = input("Nhập từ khóa bạn muốn tạo video: ").strip()
            if len(keyword) < 3:
                logger.warning("Từ khóa quá ngắn...")
                keyword = ""

        # Chọn ngôn ngữ output
        language_choice = input("Chọn ngôn ngữ output (vi/en, mặc định là vi): ").strip().lower()
        language = "en" if language_choice == "en" else "vi"

        # *** Hỏi Style bằng hàm helper ***
        selected_style = prompt_for_style()
        logger.info(f"Đang tạo kịch bản từ từ khóa '{keyword}' với phong cách '{selected_style}' và ngôn ngữ '{language}'...")
        print("\nĐang xử lý...")

        # Tạo kịch bản trực tiếp từ từ khóa
        script = script_generator.generate_script_from_keyword(keyword, selected_style, language)
        
    # --- NEW: XỬ LÝ LỰA CHỌN 4: TẠO TỪ PHỤ ĐỀ YOUTUBE ---
    elif choice == "4":
        logger.info("Lựa chọn 4: Tạo video từ phụ đề Youtube...")

        youtube_url = ""
        transcript_text = None
        transcript_language = None

        while not transcript_text:
            youtube_url = input("Nhập URL của video Youtube: ").strip()
            # Basic validation
            if not ("youtube.com" in youtube_url or "youtu.be" in youtube_url):
                logger.warning("URL không giống link Youtube hợp lệ. Vui lòng thử lại.")
                continue

            # Fetch transcript
            print("Đang tải phụ đề từ Youtube...")
            # Allow specifying preferred languages, default to English then Vietnamese
            preferred_langs = ['en', 'vi']
            lang_choice = input(f"Nhập mã ngôn ngữ ưu tiên (vd: en, vi), cách nhau bởi dấu phẩy, hoặc để trống (mặc định {','.join(preferred_langs)}): ").strip().lower()
            if lang_choice:
                preferred_langs = [lang.strip() for lang in lang_choice.split(',')]

            transcript_text, transcript_language = get_youtube_transcript(youtube_url, languages=preferred_langs)

            if not transcript_text:
                logger.error(f"Không thể lấy phụ đề cho URL: {youtube_url}. Vui lòng kiểm tra URL hoặc thử video khác.")
                # Ask user if they want to try another URL
                retry = input("Bạn có muốn thử URL khác không? (y/n): ").strip().lower()
                if retry != 'y':
                    logger.info("Hủy bỏ tạo video từ Youtube.")
                    return # Exit main function
                # Loop continues to ask for URL again
            else:
                logger.info(f"Đã lấy được phụ đề (ngôn ngữ: {transcript_language}).")
                # Save transcript for reference (optional)
                try:
                    transcript_filename = f"transcript_{timestamp}.txt"
                    with open(os.path.join(TEMP_DIR, transcript_filename), 'w', encoding='utf-8') as f:
                        f.write(f"Source URL: {youtube_url}\nDetected Language: {transcript_language}\n\n")
                        f.write(transcript_text)
                    logger.info(f"Đã lưu nội dung phụ đề vào: {transcript_filename}")
                except Exception as save_err:
                    logger.warning(f"Không thể lưu file phụ đề: {save_err}")


        # *** Hỏi Style bằng hàm helper ***
        selected_style = prompt_for_style()

        # Chọn ngôn ngữ output
        language_out_choice = input(f"Chọn ngôn ngữ output (vi/en, mặc định là '{transcript_language or 'vi'}'): ").strip().lower()
        language = transcript_language if language_out_choice == "" else ("en" if language_out_choice == "en" else "vi")

        logger.info(f"Đang tạo kịch bản từ phụ đề với phong cách '{selected_style}' và ngôn ngữ '{language}'...")
        print("\nĐang xử lý...")

        # Gọi hàm tạo script từ transcript
        script = script_generator.generate_script_from_text(
            input_text=transcript_text,
            style=selected_style,
            language=language,
            context_hint=f"YouTube transcript ({youtube_url})"
        )

        # --- Kiểm tra và Lưu Script (Thực hiện sau khi đã có script từ bất kỳ lựa chọn nào) ---
        if not script:
            logger.error(f"Không thể tạo kịch bản từ phụ đề. Kết thúc chương trình.")
            return

        # Lưu kịch bản
        script_path = os.path.join(TEMP_DIR, f"script_{timestamp}.json")
        try:
            with open(script_path, 'w', encoding='utf-8') as f:
                json.dump(script, f, ensure_ascii=False, indent=2)
            logger.info(f"Đã lưu script tại: {script_path}")
        except Exception as e:
            logger.error(f"Lỗi khi lưu script: {e}")
            return

        # Hiển thị thông tin script cuối cùng
        print("\n" + "="*50)
        print(f"Chuẩn bị tạo video cho: {script.get('title', 'N/A')}") # Dùng .get() để an toàn hơn
        print(f"Phong cách đã chọn: {selected_style}")
        print(f"Ngôn ngữ output: {language}")
        print(f"Số lượng shots (scenes): {len(script.get('scenes', []))}")
        print(f"Số lượng speech units: {len(script.get('speech_units', []))}")
        print("="*50 + "\n")

    ### --- KHỐI TẠO VOICE ---
    # Generate voice for script
    logger.info("Generating voice for the script...")
    voice_generator = VoiceGenerator()
    audio_files = voice_generator.generate_audio_for_script(script)
    logger.info(f"Generated {len(audio_files)} audio files for script's speech units.")
    
    if not audio_files:
        logger.error("Audio generation failed or returned empty list. Cannot proceed with image/video generation.")
        return # Thoát nếu không có audio

    ###--- KHỐI TẠO IMAGE/VIDEO ---
    logger.info("Generating images/videos for the script...")
    image_generator = ImageGenerator()

    # Add image from original article if available (only for choices 1 & 2)
    if choice in ["1", "2"] and selected_article and 'image_url' in selected_article:
        script['image_url'] = selected_article['image_url']
    elif choice == "4":
        # Optionally try to get YouTube thumbnail as a "source image"
        # This requires additional logic, e.g., using pytube or regex
        # For simplicity, we'll skip this for now.
        script['image_url'] = None
        logger.info("Source image not applicable for YouTube transcript generation.")
    else: # Choice 3 (keyword) also has no source image
        script['image_url'] = None

    # Generate images (Truyền audio_files vào generate_images_for_script)
    # audio_files_info argument in ImageGenerator is mainly used for intro/outro timing now
    images = image_generator.generate_images_for_script(script, audio_files_info=audio_files)

    logger.info(f"Generated {len(images)} images/videos for script")
    
    # Save image information
    images_path = os.path.join(TEMP_DIR, f"images_{timestamp}.json")
    with open(images_path, 'w', encoding='utf-8') as f:
        # Only save necessary information
        image_info = []
        for img in images:
            img_copy = {k: v for k, v in img.items() if k not in ['path']} # Exclude absolute path
            img_copy['filename'] = os.path.basename(img.get('path', '')) # Store only filename
            image_info.append(img_copy)

        json.dump(image_info, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved image information at: {images_path}")
    ###---KẾT THÚC KHỐI TẠO IMAGE/VIDEO---
    
    # --- SAVE PROJECT INFORMATION ---
    article_info = {}
    creation_method = "unknown"
    if choice == "3": # Keyword
        article_info = {
            "title": script['title'], # AI generated title
            "url": f"keyword://{keyword}",
            "source": "AI Generated from Keyword"
        }
        creation_method = "ai_keyword"
    elif choice == "4": # YouTube Subtitles
         article_info = {
             "title": script['title'], # AI generated title based on transcript
             "url": youtube_url,
             "source": f"YouTube Transcript ({youtube_url})"
         }
         creation_method = "youtube_subtitle"
    elif choice in ["1", "2"]: # RSS or Article URL
        article_info = {
            "title": selected_article['title'],
            "url": selected_article.get('url', ''),
            "source": selected_article.get('source', '')
        }
        creation_method = "url" if choice == "2" else "rss"

    project_info = {
        "title": script['title'],
        "timestamp": timestamp,
        "style": selected_style,
        "article": article_info, # Source info
        "script": {
            "path": script_path,
            "scenes_count": len(script['scenes']),
            "speech_units_count": len(script.get('speech_units', []))
        },
        # Store relative paths or just filenames for images/audio in project file
        "images": [{"type": img['type'], "filename": os.path.basename(img.get('path',''))} for img in images],
        "audio": [{"type": audio['type'], "filename": os.path.basename(audio.get('path',''))} for audio in audio_files],
        "creation_method": creation_method
    }

    project_path = os.path.join(TEMP_DIR, f"project_{timestamp}.json")
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(project_info, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved project information at: {project_path}")
    
    # --- CREATE VIDEO ---
    try:
        video_editor = VideoEditor()

        # Find default background music if available
        background_music = None
        music_dir = os.path.join(ASSETS_DIR, "music")
        if os.path.exists(music_dir):
            music_files = [f for f in os.listdir(music_dir) if f.endswith('.mp3')]
            if music_files:
                # Optionally, select music based on style? For now, just take the first.
                background_music = os.path.join(music_dir, music_files[0])
                logger.info(f"Using background music: {music_files[0]}")

        # Create output path
        def sanitize_filename(filename):
            """Remove invalid characters from filename"""
            import unicodedata
            # Normalize và loại bỏ dấu
            filename = unicodedata.normalize('NFKD', filename)
            filename = ''.join([c for c in filename if not unicodedata.combining(c)])

            # Xử lý các ký tự không hợp lệ
            invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*', "'"]
            for char in invalid_chars:
                filename = filename.replace(char, '_')

            # Loại bỏ khoảng trắng đầu/cuối
            filename = filename.strip()

            # Thay thế nhiều khoảng trắng liên tiếp bằng một dấu gạch dưới
            import re
            filename = re.sub(r'\s+', '_', filename)

            # Giới hạn độ dài tên file (adjust length as needed)
            max_len = 100
            if len(filename) > max_len:
                 # Find the last underscore before max_len to avoid cutting words awkwardly
                 last_underscore = filename.rfind('_', 0, max_len - 3)
                 if last_underscore != -1:
                     filename = filename[:last_underscore] + "..."
                 else:
                     filename = filename[:max_len - 3] + "..."


            return filename

        # Use the generated script title for the filename
        safe_title = sanitize_filename(script.get('title', 'untitled_video')[:50]) # Limit length
        video_filename = f"{timestamp}_{safe_title}.mp4"
        output_path = os.path.join(OUTPUT_DIR, video_filename)


        # Create video with correct parameter order
        logger.info("Starting final video editing process...")
        # *** CRITICAL CHANGE: Pass audio_files (list of speech unit audio info) ***
        output_path_final = video_editor.create_video(
            script=script,               # Script contains scenes (shots) and speech_units
            media_items=images,          # List of visual media items (images/videos)
            audio_files_info=audio_files,# <-- Pass the list of speech unit audio info
            output_path=output_path,     # Final output path
            background_music_path=background_music # Optional background music
        )

        # Added completion message
        print("\n" + "="*50)
        if output_path_final and os.path.exists(output_path_final):
             print(f"Video successfully created!")
             print(f"Title: {script['title']}")
             print(f"Style: {selected_style}")
             if FORCE_CONTROVERSIAL_STYLE and choice in ["1", "2"]: # Only show forced mode if applicable
                  print("(FORCED CONTROVERSIAL MODE ENABLED)")
             print(f"Output: {output_path_final}") # Use the path returned by create_video
        else:
             print("Video creation failed. Check logs for details.")
             logger.error(f"Video creation process did not return a valid path or the file does not exist: {output_path_final}")
        print("="*50 + "\n")

    except Exception as e:
        logger.error(f"Error creating video: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()