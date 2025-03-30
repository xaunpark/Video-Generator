#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_transition.py - Kiểm tra hiệu ứng chuyển cảnh (transition) trong VideoEditor
Chạy lệnh: python test_transition.py
"""

import os
import sys
import logging
import shutil
import tempfile
import argparse
from pathlib import Path

# Thêm thư mục gốc vào sys.path
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import các module cần thiết
from src.video_editor import VideoEditor
from config.settings import TEMP_DIR, VIDEO_SETTINGS

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('transition_test.log')
    ]
)
logger = logging.getLogger("TransitionTest")

def create_test_videos(temp_dir, num_videos=3, duration=3, width=1280, height=720):
    """
    Tạo các video test đơn giản với các màu khác nhau để kiểm tra transition.
    
    Args:
        temp_dir (str): Thư mục tạm để lưu các video test
        num_videos (int): Số lượng video test cần tạo
        duration (int): Thời lượng mỗi video (giây)
        width (int): Chiều rộng video
        height (int): Chiều cao video
        
    Returns:
        list: Danh sách đường dẫn đến các video test
    """
    colors = ["red", "green", "blue", "yellow", "purple"]
    test_videos = []
    
    logger.info(f"Đang tạo {num_videos} video test trong {temp_dir}")
    
    # Tìm ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        logger.error("Không tìm thấy ffmpeg trong PATH. Vui lòng cài đặt ffmpeg.")
        sys.exit(1)
    
    for i in range(num_videos):
        color = colors[i % len(colors)]
        output_file = os.path.join(temp_dir, f"test_video_{i+1}.mp4")
        
        # Tạo video màu đơn sắc với ffmpeg
        cmd = [
            ffmpeg_path, "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:s={width}x{height}:d={duration}",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-t", str(duration),
            # Thêm số đếm vào video và một số pattern để tăng kích thước
            "-vf", f"drawtext=text='{i+1}':fontcolor=white:fontsize=120:x=(w-text_w)/2:y=(h-text_h)/2,noise=alls=20:allf=t",
            "-b:v", "1M",  # Tăng bitrate để tăng kích thước file
            "-an",
            output_file
        ]
        
        logger.info(f"Tạo video test {i+1} (màu {color}): {' '.join(cmd)}")
        
        try:
            import subprocess
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                test_videos.append(output_file)
                logger.info(f"Đã tạo video test {i+1}: {output_file}")
            else:
                logger.error(f"Không thể tạo video test {i+1}")
        except Exception as e:
            logger.error(f"Lỗi khi tạo video test {i+1}: {str(e)}")
    
    return test_videos

def test_simple_concatenation(video_editor, test_videos, output_dir):
    """Kiểm tra nối video đơn giản không có transition"""
    output_file = os.path.join(output_dir, "simple_concat.mp4")
    logger.info("Kiểm tra nối video đơn giản (không có transition)")
    
    try:
        result = video_editor.concatenate_scene_videos(test_videos, output_file)
        if os.path.exists(result) and os.path.getsize(result) > 0:
            logger.info(f"Nối video đơn giản thành công: {result}")
            return result
        else:
            logger.error("Nối video đơn giản thất bại: File không tồn tại hoặc kích thước = 0")
            return None
    except Exception as e:
        logger.error(f"Lỗi khi nối video đơn giản: {str(e)}")
        return None

def test_fade_transition(video_editor, test_videos, output_dir):
    """Kiểm tra nối video với hiệu ứng fade"""
    output_file = os.path.join(output_dir, "fade_transition.mp4")
    
    # Kiểm tra xem phương thức này có tồn tại không
    if not hasattr(video_editor, 'concatenate_scene_videos_with_fade'):
        logger.error("Phương thức 'concatenate_scene_videos_with_fade' không tồn tại trong VideoEditor")
        logger.info("Vui lòng thêm phương thức này vào class VideoEditor trước khi test")
        return None
    
    logger.info("Kiểm tra nối video với hiệu ứng fade")
    try:
        result = video_editor.concatenate_scene_videos_with_fade(test_videos, output_file, 0.8)
        if os.path.exists(result) and os.path.getsize(result) > 0:
            logger.info(f"Nối video với hiệu ứng fade thành công: {result}")
            return result
        else:
            logger.error("Nối video với hiệu ứng fade thất bại: File không tồn tại hoặc kích thước = 0")
            return None
    except Exception as e:
        logger.error(f"Lỗi khi nối video với hiệu ứng fade: {str(e)}")
        return None

def add_fade_to_individual_videos(video_editor, test_videos, output_dir):
    """Kiểm tra thêm hiệu ứng fade vào từng video riêng biệt"""
    processed_videos = []
    
    # Kiểm tra xem phương thức này có tồn tại không
    if not hasattr(video_editor, 'add_fade_to_scene'):
        logger.error("Phương thức 'add_fade_to_scene' không tồn tại trong VideoEditor")
        logger.info("Vui lòng thêm phương thức này vào class VideoEditor trước khi test")
        return None
    
    logger.info("Kiểm tra thêm hiệu ứng fade vào từng video riêng biệt")
    
    for i, video in enumerate(test_videos):
        output_file = os.path.join(output_dir, f"video_{i+1}_with_fade.mp4")
        try:
            result = video_editor.add_fade_to_scene(video, output_file, 0.8)
            if os.path.exists(result) and os.path.getsize(result) > 0:
                processed_videos.append(result)
                logger.info(f"Thêm fade vào video {i+1} thành công: {result}")
            else:
                logger.error(f"Thêm fade vào video {i+1} thất bại")
        except Exception as e:
            logger.error(f"Lỗi khi thêm fade vào video {i+1}: {str(e)}")
    
    # Nối các video đã xử lý
    if processed_videos:
        output_file = os.path.join(output_dir, "individual_fades_concat.mp4")
        try:
            result = video_editor.concatenate_scene_videos(processed_videos, output_file)
            if os.path.exists(result):
                logger.info(f"Nối các video đã thêm fade riêng lẻ thành công: {result}")
                return result
        except Exception as e:
            logger.error(f"Lỗi khi nối các video đã thêm fade: {str(e)}")
    
    return None

def main():
    # Xử lý tham số dòng lệnh
    parser = argparse.ArgumentParser(description="Kiểm tra hiệu ứng chuyển cảnh trong VideoEditor")
    parser.add_argument("--videos", type=int, default=4, help="Số lượng video test (mặc định: 4)")
    parser.add_argument("--duration", type=int, default=5, help="Thời lượng mỗi video (giây) (mặc định: 5)")
    parser.add_argument("--method", choices=["all", "simple", "fade", "individual"], default="all", 
                        help="Phương pháp test (mặc định: all)")
    parser.add_argument("--output", type=str, help="Thư mục đầu ra (mặc định: thư mục temp)")
    
    args = parser.parse_args()
    
    # Tạo thư mục đầu ra
    if args.output:
        output_dir = args.output
        os.makedirs(output_dir, exist_ok=True)
    else:
        output_dir = os.path.join(TEMP_DIR, "transition_test_output")
        os.makedirs(output_dir, exist_ok=True)
    
    logger.info("===== Bắt đầu kiểm tra hiệu ứng chuyển cảnh =====")
    logger.info(f"Thư mục đầu ra: {output_dir}")
    
    try:
        # Tạo thư mục tạm
        temp_dir = tempfile.mkdtemp(prefix="transition_test_")
        logger.info(f"Đã tạo thư mục tạm: {temp_dir}")
        
        # Tạo các video test
        test_videos = create_test_videos(
            temp_dir, 
            num_videos=args.videos, 
            duration=args.duration
        )
        
        if not test_videos or len(test_videos) < 2:
            logger.error("Không đủ video test để thực hiện kiểm tra")
            return
        
        # Khởi tạo VideoEditor
        video_editor = VideoEditor()
        
        # Lưu cài đặt hiện tại
        current_settings = {
            "enable_transitions": VIDEO_SETTINGS.get("enable_transitions", False),
            "transition_types": VIDEO_SETTINGS.get("transition_types", []),
            "transition_duration": VIDEO_SETTINGS.get("transition_duration", 0.5)
        }
        
        logger.info(f"Cài đặt hiện tại: {current_settings}")
        
        # Thực hiện các bài test theo tham số
        if args.method in ["all", "simple"]:
            simple_result = test_simple_concatenation(video_editor, test_videos, output_dir)
        
        if args.method in ["all", "fade"]:
            fade_result = test_fade_transition(video_editor, test_videos, output_dir)
        
        if args.method in ["all", "individual"]:
            individual_result = add_fade_to_individual_videos(video_editor, test_videos, output_dir)
        
        # Hiển thị kết quả
        logger.info("\n===== KẾT QUẢ KIỂM TRA =====")
        
        if args.method in ["all", "simple"]:
            status = "THÀNH CÔNG" if 'simple_result' in locals() and simple_result else "THẤT BẠI"
            logger.info(f"1. Nối video đơn giản: {status}")
        
        if args.method in ["all", "fade"]:
            status = "THÀNH CÔNG" if 'fade_result' in locals() and fade_result else "THẤT BẠI"
            logger.info(f"2. Nối video với hiệu ứng fade: {status}")
        
        if args.method in ["all", "individual"]:
            status = "THÀNH CÔNG" if 'individual_result' in locals() and individual_result else "THẤT BẠI"
            logger.info(f"3. Thêm fade vào từng video riêng lẻ: {status}")
        
        logger.info(f"\nCác video kết quả được lưu tại: {output_dir}")
        
    except Exception as e:
        logger.error(f"Lỗi không mong muốn: {str(e)}", exc_info=True)
    
    finally:
        # Dọn dẹp
        try:
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Đã xóa thư mục tạm: {temp_dir}")
        except:
            pass
        
        logger.info("===== Kết thúc kiểm tra hiệu ứng chuyển cảnh =====")

if __name__ == "__main__":
    main()