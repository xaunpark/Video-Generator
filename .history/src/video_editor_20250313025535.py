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

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Bắt đầu chương trình tạo video tin tức tự động")
    
    # Đảm bảo các thư mục tồn tại
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Khởi tạo scraper và lấy tin tức
    scraper = NewsScraper()
    articles = scraper.fetch_articles(limit=5)
    
    if not articles:
        logger.error("Không tìm thấy bài viết nào. Kết thúc chương trình.")
        return
    
    logger.info(f"Đã tìm thấy {len(articles)} bài viết")
    
    # Phân loại tin tức
    categorized = scraper.categorize_articles(articles)
    
    # In ra danh sách các bài viết theo danh mục
    for category, articles in categorized.items():
        if articles:
            logger.info(f"Danh mục {category}: {len(articles)} bài viết")
            for i, article in enumerate(articles, 1):
                logger.info(f"  {i}. {article['title']}")
    
    # Lưu dữ liệu tin tức đã lấy được vào thư mục temp để tham khảo sau này
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(TEMP_DIR, f"articles_{timestamp}.json"), 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    
    # Chọn một bài viết để tạo video
    selected_article = None
    for category in ['technology', 'business', 'general']:
        if categorized.get(category) and len(categorized[category]) > 0:
            selected_article = categorized[category][0]
            logger.info(f"Đã chọn bài viết từ danh mục {category}: {selected_article['title']}")
            break
    
    if not selected_article:
        logger.error("Không tìm thấy bài viết phù hợp để tạo kịch bản.")
        return
    
    # Tạo kịch bản
    script_generator = ScriptGenerator()
    script = script_generator.generate_script(selected_article, style="informative")
    
    if not script:
        logger.error("Không thể tạo kịch bản. Kết thúc chương trình.")
        return
    
    # In thông tin kịch bản
    logger.info(f"Đã tạo kịch bản cho: {script['title']}")
    logger.info(f"Số phân cảnh: {len(script['scenes'])}")
    
    # Lưu kịch bản
    script_path = os.path.join(TEMP_DIR, f"script_{timestamp}.json")
    with open(script_path, 'w', encoding='utf-8') as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Đã lưu kịch bản tại: {script_path}")
    
    # Tạo hình ảnh cho kịch bản
    image_generator = ImageGenerator()
    
    # Thêm hình ảnh từ bài báo gốc vào kịch bản nếu có
    if 'image_url' in selected_article:
        script['image_url'] = selected_article['image_url']
    
    # Tạo hình ảnh
    images = image_generator.generate_images_for_script(script)
    
    logger.info(f"Đã tạo {len(images)} hình ảnh cho kịch bản")
    
    # Lưu thông tin hình ảnh
    images_path = os.path.join(TEMP_DIR, f"images_{timestamp}.json")
    with open(images_path, 'w', encoding='utf-8') as f:
        # Chỉ lưu thông tin cần thiết, không lưu đường dẫn đầy đủ
        image_info = []
        for img in images:
            img_copy = {k: v for k, v in img.items() if k != 'path'}
            img_copy['filename'] = os.path.basename(img['path'])
            image_info.append(img_copy)
        
        json.dump(image_info, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Đã lưu thông tin hình ảnh tại: {images_path}")
    
    # Tạo giọng nói cho kịch bản
    voice_generator = VoiceGenerator()
    audio_files = voice_generator.generate_audio_for_script(script)
    
    logger.info(f"Đã tạo {len(audio_files)} file âm thanh cho kịch bản")
    
    # Tạo video từ hình ảnh và âm thanh
    video_editor = VideoEditor()
    
    # Tìm file nhạc nền mặc định
    background_music = None
    music_dir = os.path.join(ASSETS_DIR, "music")
    default_music_file = os.path.join(music_dir, "background.mp3")
    if os.path.exists(default_music_file):
        background_music = default_music_file
    
    # Tạo video
    try:
        output_path = video_editor.create_video(images, audio_files, script, background_music)
        logger.info(f"Đã tạo video thành công: {output_path}")
    except Exception as e:
        logger.error(f"Lỗi khi tạo video: {str(e)}")

if __name__ == "__main__":
    main()