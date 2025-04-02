# src/utils.py

import re

def detect_language(text):
    """
    Phát hiện ngôn ngữ đơn giản dựa trên bảng chữ cái.
    Nếu đa số là ký tự Latin => tiếng Anh, nếu đa số là Unicode tiếng Việt => tiếng Việt
    """
    # Đếm số ký tự có dấu (unicode Vietnamese)
    vietnamese_chars = len(re.findall(r'[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]', text, flags=re.IGNORECASE))

    # Đếm tổng chữ cái
    total_letters = len(re.findall(r'[a-zA-Z]', text)) + vietnamese_chars

    if total_letters == 0:
        return "en"  # Mặc định

    # Nếu >30% là ký tự tiếng Việt => nhận là tiếng Việt
    if vietnamese_chars / total_letters > 0.3:
        return "vi"
    return "en"


def safe_truncate(text, max_len=10000):
    """
    Cắt nội dung an toàn tránh vượt quá token
    """
    return text[:max_len].strip() + ("..." if len(text) > max_len else "")


def slugify(text):
    """
    Tạo slug đơn giản từ text
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text).strip('-')
    return text


def generate_project_id(keyword_or_title):
    """
    Tạo mã project ngắn từ keyword hoặc title
    """
    slug = slugify(keyword_or_title)
    return f"prj-{slug[:30]}"
