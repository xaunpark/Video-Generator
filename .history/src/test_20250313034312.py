# test_ffmpeg.py
import os
import sys

# Đặt đường dẫn đến ffmpeg
os.environ["IMAGEIO_FFMPEG_EXE"] = os.path.join(os.path.dirname(__file__), "ffmpeg.exe")

try:
    import imageio
    import imageio_ffmpeg
    print(f"FFmpeg được tìm thấy tại: {imageio_ffmpeg.get_ffmpeg_exe()}")
    
    # Thử tạo một video đơn giản
    import numpy as np
    from moviepy.editor import ColorClip
    
    # Tạo clip màu đơn giản
    clip = ColorClip(size=(640, 480), color=(0, 0, 255), duration=1)
    
    # Xuất ra file mp4
    clip.write_videofile("test_output.mp4", fps=24, logger=None)
    print("Đã tạo video test thành công!")
    
except Exception as e:
    print(f"Lỗi: {e}")