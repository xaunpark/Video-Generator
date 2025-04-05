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
from urllib.parse import urlparse

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
FORCE_CONTROVERSIAL_STYLE = True

def select_script_style(article, categories=None):
    """
    Select an appropriate script style based on the article content and category
    
    Args:
        article (dict): Article with title, content, category, etc.
        categories (dict): Article categories from NewsScraper if available
        
    Returns:
        str: Script style (informative, conversational, dramatic, controversial)
    """
    # Always return controversial style if forced
    if FORCE_CONTROVERSIAL_STYLE:
        logger.info(f"Forced controversial style enabled - using controversial style for all articles")
        return "controversial"
    
    # Rest of the function remains the same but will never be reached when FORCE_CONTROVERSIAL_STYLE is True
    # Determine the article's category
    article_category = None
    if categories:
        for category, articles in categories.items():
            if article in articles:
                article_category = category
                break
    
    # Keywords that may trigger controversial style
    controversial_keywords = [
        'debate', 'dispute', 'controversy', 'divided', 'conflict', 'argument', 'clash',
        'disputed', 'polarizing', 'scandal', 'protest', 'criticism', 'oppose', 'lawsuit',
        'allegations', 'backlash', 'outrage', 'contentious', 'dispute', 'heated'
    ]
    
    title = article.get('title', '').lower()
    content = article.get('content', '').lower()
    
    # Check for controversial keywords in title and content
    has_controversial_content = any(keyword in title or keyword in content 
                                   for keyword in controversial_keywords)
    
    # Style selection logic based on category and content
    if has_controversial_content:
        # Prioritize controversial style if content is already controversial
        logger.info(f"Detected controversial content, using controversial style")
        return "controversial"
    elif article_category in ['technology', 'science']:
        logger.info(f"Article in {article_category} category, using informative style")
        return "informative"
    elif article_category in ['entertainment', 'lifestyle', 'sports']:
        logger.info(f"Article in {article_category} category, using conversational style")
        return "conversational"
    elif article_category in ['politics', 'business', 'world']:
        logger.info(f"Article in {article_category} category, using dramatic style")
        return "dramatic"
    else:
        logger.info(f"Using default informative style")
        return "informative"

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
        # Thêm sleep nhỏ để tránh bị chặn (tùy chọn)
        # time.sleep(1)
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

    choice = ""
    while choice not in ["1", "2", "3"]:
        choice = input("Nhập lựa chọn của bạn (1, 2 hoặc 3): ").strip()

    # Khởi tạo các biến chung
    selected_article = None
    script = None
    articles = []
    categorized = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    selected_style = None

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
        
        # Nhập từ khóa
        keyword = ""
        while not keyword:
            keyword = input("Nhập từ khóa bạn muốn tạo video: ").strip()
            if len(keyword) < 3:
                logger.warning("Từ khóa quá ngắn. Vui lòng nhập ít nhất 3 ký tự.")
                keyword = ""  # Reset để hỏi lại
        
        # Chọn ngôn ngữ (tùy chọn)
        language_choice = input("Chọn ngôn ngữ (vi/en, mặc định là vi): ").strip().lower()
        language = "en" if language_choice == "en" else "vi"
        
        # Chọn phong cách
        print("\nChọn phong cách cho video:")
        print("1. Thông tin (informative) - Giọng điệu chính thống, chuyên nghiệp")
        print("2. Hội thoại (conversational) - Giọng điệu thân thiện, gần gũi")
        print("3. Kịch tính (dramatic) - Gây ấn tượng mạnh, tập trung vào tác động")
        print("4. Gây tranh cãi (controversial) - Nêu bật các quan điểm đối lập, gây tranh luận")
        
        style_choice = ""
        while style_choice not in ["1", "2", "3", "4"]:
            style_choice = input("Nhập lựa chọn phong cách (1-4, mặc định là 1): ").strip()
            if not style_choice:
                style_choice = "1"  # Mặc định
        
        # Ánh xạ lựa chọn sang phong cách
        style_map = {
            "1": "informative",
            "2": "conversational",
            "3": "dramatic",
            "4": "controversial"
        }
        selected_style = style_map.get(style_choice, "informative")
        
        logger.info(f"Đang tạo kịch bản từ từ khóa '{keyword}' với phong cách '{selected_style}' và ngôn ngữ '{language}'...")
        
        # Hiển thị thông báo đang xử lý
        print("\nĐang xử lý... (có thể mất vài phút)")
        
        # Khởi tạo ScriptGenerator
        script_generator = ScriptGenerator()
        
        # Tạo kịch bản trực tiếp từ từ khóa
        script = script_generator.generate_script_from_keyword(keyword, selected_style, language)
        
        if not script:
            logger.error(f"Không thể tạo kịch bản từ từ khóa '{keyword}'. Kết thúc chương trình.")
            return
        
        # Lưu kịch bản
        script_path = os.path.join(TEMP_DIR, f"script_{timestamp}.json")
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        logger.info(f"Đã lưu script tại: {script_path}")
        
        # Hiển thị thông tin kịch bản đã tạo
        print("\n" + "="*50)
        print(f"Đã tạo kịch bản AI từ từ khóa: {keyword}")
        print(f"Tiêu đề: {script['title']}")
        print(f"Phong cách: {selected_style}")
        print("="*50 + "\n")

    # --- KIỂM TRA TRẠNG THÁI DỮ LIỆU ---
    if choice in ["1", "2"] and not selected_article:
        logger.error("Không có bài báo nào được chọn hoặc xử lý. Kết thúc chương trình.")
        return
        
    if choice in ["1", "2"]:
        logger.info(f"Bài báo được chọn để tạo video: '{selected_article['title']}'")
        logger.info(f"Nguồn: {selected_article.get('source', 'N/A')}")             

        # Generate script with selected style
        script_generator = ScriptGenerator()
        selected_style = select_script_style(selected_article, categorized if choice == "1" else None)
        logger.info(f"Đang tạo script với phong cách '{selected_style}'...")
        
        script = script_generator.generate_script(selected_article, style=selected_style)
        
        if not script:
            logger.error("Could not generate script. Exiting program.")
            return
        
        # Print script information
        logger.info(f"Generated script for: {script['title']}")
        logger.info(f"Number of scenes: {len(script['scenes'])}")
        logger.info(f"Style used: {selected_style}")
        
        # Save script
        script_path = os.path.join(TEMP_DIR, f"script_{timestamp}.json")
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved script at: {script_path}")

    # Kiểm tra script sau khi đã xử lý từng lựa chọn
    if not script:
        logger.error("Không có script nào được tạo. Kết thúc chương trình.")
        return

    ### --- KHỐI TẠO VOICE ---
    # Generate voice for script
    voice_generator = VoiceGenerator()
    audio_files = voice_generator.generate_audio_for_script(script)
    
    logger.info(f"Generated {len(audio_files)} audio files for script")
    
    # --- THÊM KIỂM TRA audio_files ---
    if not audio_files:
        logger.error("Audio generation failed or returned empty list. Cannot proceed with image/video generation.")
        return # Thoát nếu không có audio
    ### --- KẾT THÚC KHỐI TẠO VOICE ---

    ###--- KHỐI TẠO IMAGE---
    # Generate images for script
    image_generator = ImageGenerator()
    
    # Add image from original article if available
    if selected_article and 'image_url' in selected_article:
        script['image_url'] = selected_article['image_url']
    
    # Generate images (Truyền thêm audio_files vào generate_images_for_script)
    images = image_generator.generate_images_for_script(script, audio_files_info=audio_files)
    
    logger.info(f"Generated {len(images)} images/videos for script")
    
    # Save image information
    images_path = os.path.join(TEMP_DIR, f"images_{timestamp}.json")
    with open(images_path, 'w', encoding='utf-8') as f:
        # Only save necessary information
        image_info = []
        for img in images:
            img_copy = {k: v for k, v in img.items() if k != 'path'}
            img_copy['filename'] = os.path.basename(img['path'])
            image_info.append(img_copy)
        
        json.dump(image_info, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved image information at: {images_path}")
    ###---KẾT THÚC KHỐI TẠO IMAGE---
    
    # Save project information
    if choice == "3":
        article_info = {
            "title": script['title'],
            "url": f"keyword://{keyword}",
            "source": "AI Generated"
        }
    else:
        article_info = {
            "title": selected_article['title'],
            "url": selected_article.get('url', ''),
            "source": selected_article.get('source', '')
        }

    project_info = {
        "title": script['title'],
        "timestamp": timestamp,
        "style": selected_style,
        "article": article_info,
        "script": {
            "path": script_path,
            "scenes_count": len(script['scenes'])
        },
        "images": [{"type": img['type'], "path": img['path']} for img in images],
        "audio": [{"type": audio['type'], "path": audio['path']} for audio in audio_files],
        "creation_method": "ai_keyword" if choice == "3" else ("url" if choice == "2" else "rss")
    }
    
    project_path = os.path.join(TEMP_DIR, f"project_{timestamp}.json")
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(project_info, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved project information at: {project_path}")
    
    # Create video from images and audio
    try:
        video_editor = VideoEditor()
        
        # Find default background music if available
        background_music = None
        music_dir = os.path.join(ASSETS_DIR, "music")
        if os.path.exists(music_dir):
            music_files = [f for f in os.listdir(music_dir) if f.endswith('.mp3')]
            if music_files:
                background_music = os.path.join(music_dir, music_files[0])
        
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
            
            # Giới hạn độ dài tên file
            if len(filename) > 100:
                filename = filename[:97] + "..."
            
            return filename

        video_filename = sanitize_filename(f"{timestamp}_{script['title'][:30].replace(' ', '_')}.mp4")

        output_path = os.path.join(OUTPUT_DIR, video_filename)

        # Cần lấy audio_dir từ audio_files (ví dụ: từ file đầu tiên)
        audio_dir = None
        if audio_files and audio_files[0].get('path'):
            audio_dir = os.path.dirname(audio_files[0]['path'])

        if not audio_dir:
            logger.error("Could not determine audio directory. Cannot create video.")
            return

        # Create video with correct parameter order
        logger.info("Bắt đầu quá trình chỉnh sửa và tạo video cuối cùng...")
        output_path_final = video_editor.create_video(
            script=script,               # Script chứa scenes và speech_units
            media_items=images,          # List media items cho từng scene/shot
            audio_files_info=audio_files,# <--- TRUYỀN DANH SÁCH AUDIO INFO CỦA SPEECH UNITS
            output_path=output_path,     # Đường dẫn output cuối cùng
            background_music_path=background_music # Nhạc nền (tùy chọn)
            # project_id=script.get('project_id') # Tùy chọn: truyền project_id nếu muốn dùng tên thư mục tạm khớp nhau
        )

        # Added completion message
        print("\n" + "="*50)
        print(f"Video successfully created!")
        print(f"Title: {script['title']}")

        if choice == "3":
            print(f"Style: {selected_style}")
            if FORCE_CONTROVERSIAL_STYLE:
                print("(CONTROVERSIAL MODE ENABLED)")
        else:
            print(f"Style: {selected_style} (CONTROVERSIAL MODE ENABLED)")
            
        print(f"Output: {output_path}")
        print("="*50 + "\n")
        
    except Exception as e:
        logger.error(f"Error creating video: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()