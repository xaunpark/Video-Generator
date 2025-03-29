#scr/news_scraper.py
import requests
import feedparser
from bs4 import BeautifulSoup
from newspaper import Article
import logging
import time
from datetime import datetime
from config.settings import NEWS_SOURCES, NEWS_CATEGORIES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NewsScraper:
    def __init__(self):
        self.sources = NEWS_SOURCES
        self.categories = NEWS_CATEGORIES
    
    def fetch_articles(self, limit=10):
        """Lấy tin tức từ các nguồn đã cấu hình"""
        all_articles = []
        
        for source in self.sources:
            try:
                logger.info(f"Đang lấy tin từ {source['name']}")
                if source['type'] == 'rss':
                    articles = self._fetch_from_rss(source['url'], limit)
                else:
                    articles = self._fetch_from_website(source['url'], limit)
                
                # Thêm thông tin nguồn
                for article in articles:
                    article['source'] = source['name']
                    article['language'] = source.get('language', 'en')
                
                all_articles.extend(articles)
                logger.info(f"Đã tìm thấy {len(articles)} bài viết từ {source['name']}")
            except Exception as e:
                logger.error(f"Lỗi khi lấy tin từ {source['name']}: {str(e)}")
        
        return all_articles[:limit]
    
    def _fetch_from_rss(self, rss_url, limit=10):
        """Lấy tin từ RSS feed"""
        feed = feedparser.parse(rss_url)
        articles = []
        
        for entry in feed.entries[:limit]:
            try:
                # Trích xuất thông tin cơ bản từ RSS
                article = {
                    'title': entry.title,
                    'url': entry.link,
                    'published_date': datetime.now().strftime("%Y-%m-%d")
                }
                
                if hasattr(entry, 'summary'):
                    article['summary'] = entry.summary
                
                if hasattr(entry, 'published'):
                    try:
                        article['published_date'] = datetime.strptime(
                            entry.published, "%a, %d %b %Y %H:%M:%S %z"
                        ).strftime("%Y-%m-%d")
                    except:
                        pass
                
                # Lấy nội dung chi tiết từ URL
                article_obj = Article(entry.link)
                article_obj.download()
                time.sleep(0.5)  # Tránh quá tải máy chủ
                article_obj.parse()
                
                article['content'] = article_obj.text
                if not article.get('summary'):
                    article['summary'] = article_obj.summary
                
                article['image_url'] = article_obj.top_image
                
                articles.append(article)
                logger.info(f"Đã lấy bài viết: {article['title']}")
            except Exception as e:
                logger.error(f"Lỗi xử lý bài viết {entry.title}: {str(e)}")
        
        return articles
    
    def _fetch_from_website(self, website_url, limit=10):
        """Lấy tin từ website thông thường (không phải RSS)"""
        response = requests.get(website_url)
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        
        # Logic tùy thuộc vào cấu trúc website
        # Đây là ví dụ chung, cần điều chỉnh cho từng website cụ thể
        news_links = soup.select('a.news-item') or soup.select('a.article-title') or soup.find_all('a', href=True)
        news_links = [link for link in news_links if '/tin-tuc/' in link.get('href', '') or '/news/' in link.get('href', '')][:limit]
        
        for link in news_links:
            try:
                article_url = link['href']
                if not article_url.startswith('http'):
                    if article_url.startswith('/'):
                        base_url = website_url.split('//')[-1].split('/')[0]
                        article_url = f"https://{base_url}{article_url}"
                    else:
                        article_url = f"{website_url}/{article_url}"
                
                article_obj = Article(article_url)
                article_obj.download()
                time.sleep(0.5)  # Tránh quá tải máy chủ
                article_obj.parse()
                
                articles.append({
                    'title': article_obj.title,
                    'url': article_url,
                    'content': article_obj.text,
                    'summary': article_obj.summary,
                    'image_url': article_obj.top_image,
                    'published_date': article_obj.publish_date.strftime("%Y-%m-%d") if article_obj.publish_date else datetime.now().strftime("%Y-%m-%d")
                })
                logger.info(f"Đã lấy bài viết: {article_obj.title}")
            except Exception as e:
                logger.error(f"Lỗi xử lý bài viết từ URL {article_url}: {str(e)}")
        
        return articles
    
    def categorize_articles(self, articles):
        """Phân loại tin tức theo danh mục"""
        categorized = {category: [] for category in self.categories}
        categorized['general'] = []  # Danh mục mặc định
        
        for article in articles:
            title = article.get('title', '').lower()
            content = article.get('content', '').lower()
            
            categorized_flag = False
            for category, keywords in self.categories.items():
                for keyword in keywords:
                    if keyword in title or keyword in content:
                        categorized[category].append(article)
                        categorized_flag = True
                        break
                if categorized_flag:
                    break
            
            # Nếu không thuộc danh mục nào
            if not categorized_flag:
                categorized['general'].append(article)
        
        return categorized

# Test module
if __name__ == "__main__":
    scraper = NewsScraper()
    articles = scraper.fetch_articles(3)
    categorized = scraper.categorize_articles(articles)
    
    for category, articles in categorized.items():
        if articles:
            print(f"\n=== {category.upper()} ({len(articles)}) ===")
            for article in articles:
                print(f"- {article['title']}")