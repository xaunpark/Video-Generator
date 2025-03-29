# test_scraper_content.py
import sys
import os
import logging
from datetime import datetime

# Thêm thư mục gốc vào sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import các module cần thiết
from src.news_scraper import NewsScraper

# Cấu hình logging cơ bản
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_content_extraction():
    """Test trích xuất nội dung từ NewsScraper"""
    logger.info("Bắt đầu kiểm tra trích xuất nội dung...")
    
    # Khởi tạo NewsScraper
    scraper = NewsScraper()
    
    # Chọn số lượng bài báo cần lấy
    num_articles = 2
    
    # Lấy bài báo
    logger.info(f"Đang lấy {num_articles} bài báo...")
    articles = scraper.fetch_articles(limit=num_articles)
    
    if not articles:
        logger.error("Không lấy được bài báo nào!")
        return
    
    logger.info(f"Đã lấy được {len(articles)} bài báo")
    
    # Tạo thư mục để lưu kết quả nếu cần
    output_dir = "content_test_results"
    os.makedirs(output_dir, exist_ok=True)
    
    # Tên file kết quả
    result_filename = os.path.join(output_dir, f"content_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    
    # Mở file để ghi kết quả
    with open(result_filename, "w", encoding="utf-8") as f:
        f.write(f"=== TEST TRÍCH XUẤT NỘI DUNG ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n\n")
        
        # Phân tích từng bài báo
        for idx, article in enumerate(articles, 1):
            f.write(f"--- BÀI BÁO #{idx} ---\n")
            f.write(f"Tiêu đề: {article.get('title', 'Không có tiêu đề')}\n")
            f.write(f"Nguồn: {article.get('source', 'Không rõ nguồn')}\n")
            f.write(f"URL: {article.get('url', 'Không có URL')}\n")
            
            # Thông tin về nội dung
            content = article.get('content', '')
            content_length = len(content)
            f.write(f"Độ dài nội dung: {content_length} ký tự\n")
            f.write(f"Số từ: {len(content.split())} từ\n")
            f.write(f"Số dòng: {len(content.splitlines())} dòng\n\n")
            
            # Hiển thị nội dung
            f.write("=== NỘI DUNG ĐẦY ĐỦ ===\n")
            f.write(content)
            f.write("\n\n")
            
            # Hiển thị tóm tắt nếu có
            if 'summary' in article:
                f.write("=== TÓM TẮT ===\n")
                f.write(article.get('summary', ''))
                f.write("\n\n")
            
            f.write("-" * 80 + "\n\n")
    
    # In ra thông tin kết quả
    logger.info(f"Đã lưu kết quả kiểm tra vào file: {result_filename}")
    
    # Hiển thị thông tin trên console
    print("\n=== THÔNG TIN TỔNG QUAN VỀ NỘI DUNG ===")
    for idx, article in enumerate(articles, 1):
        title = article.get('title', 'Không có tiêu đề')
        content = article.get('content', '')
        content_length = len(content)
        print(f"\nBài #{idx}: {title}")
        print(f"- Độ dài: {content_length} ký tự")
        print(f"- Số từ: {len(content.split())} từ")
        print(f"- URL: {article.get('url', 'N/A')}")
        
        # Hiển thị vài dòng đầu tiên
        first_lines = "\n".join(content.splitlines()[:5])
        print(f"\n--- Vài dòng đầu tiên ---\n{first_lines}...\n")

if __name__ == "__main__":
    test_content_extraction()