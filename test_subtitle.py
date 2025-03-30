#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_subtitle.py - Kiểm tra chức năng thêm phụ đề vào video với Whisper
"""

import os
import sys
import logging
import argparse
from pathlib import Path

# Thêm thư mục gốc vào sys.path
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import các module cần thiết
from src.video_editor import VideoEditor
from config.settings import VIDEO_SETTINGS

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('subtitle_test.log')
    ]
)
logger = logging.getLogger("SubtitleTest")

def main():
    # Xử lý tham số dòng lệnh
    parser = argparse.ArgumentParser(description="Kiểm tra chức năng thêm phụ đề vào video")
    parser.add_argument("video_path", help="Đường dẫn đến video cần thêm phụ đề")
    parser.add_argument("--model", choices=["tiny", "base", "small", "medium", "large"], default="base",
                      help="Mô hình Whisper (mặc định: base)")
    parser.add_argument("--lang", default="en", help="Ngôn ngữ (mặc định: en, dùng auto để tự động phát hiện)")
    parser.add_argument("--output", help="Đường dẫn đầu ra (mặc định: thêm _with_subs vào tên file)")
    parser.add_argument("--audio", help="Đường dẫn đến file audio riêng (nếu có)")
    
    args = parser.parse_args()
    
    # Kiểm tra đường dẫn video
    if not os.path.exists(args.video_path):
        logger.error(f"Không tìm thấy video: {args.video_path}")
        return
    
    # Đường dẫn output mặc định
    if not args.output:
        args.output = os.path.splitext(args.video_path)[0] + "_with_subs" + os.path.splitext(args.video_path)[1]
    
    # Tạm thời đặt cài đặt subtitle
    VIDEO_SETTINGS["enable_subtitles"] = True
    VIDEO_SETTINGS["subtitle_whisper_model"] = args.model
    VIDEO_SETTINGS["subtitle_language"] = args.lang
    
    logger.info("===== Bắt đầu kiểm tra thêm phụ đề vào video =====")
    logger.info(f"Video: {args.video_path}")
    logger.info(f"Mô hình: {args.model}")
    logger.info(f"Ngôn ngữ: {args.lang}")
    logger.info(f"Đầu ra: {args.output}")
    
    try:
        # Khởi tạo VideoEditor
        video_editor = VideoEditor()
        
        # Thêm phụ đề vào video
        result = video_editor.add_subtitles_to_video(
            video_path=args.video_path,
            audio_dir=os.path.dirname(args.audio) if args.audio else None,
            output_path=args.output
        )
        
        if result and os.path.exists(result):
            logger.info(f"Thêm phụ đề thành công: {result}")
            logger.info(f"Kích thước file: {os.path.getsize(result) / (1024*1024):.2f} MB")
            
            # Tìm file SRT đã tạo
            srt_path = os.path.splitext(result)[0] + ".srt"
            if os.path.exists(srt_path):
                logger.info(f"Đã tạo file SRT: {srt_path}")
                logger.info(f"Kích thước SRT: {os.path.getsize(srt_path) / 1024:.2f} KB")
        else:
            logger.error("Không thể thêm phụ đề vào video.")
    
    except Exception as e:
        logger.error(f"Lỗi khi test chức năng subtitle: {str(e)}", exc_info=True)
    
    logger.info("===== Kết thúc kiểm tra thêm phụ đề vào video =====")

if __name__ == "__main__":
    main()