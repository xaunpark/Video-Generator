import logging
import os
import sys
from src.news_scraper import NewsScraper
from config.settings import OUTPUT_DIR

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

if __name__ == "__main__":
    main()