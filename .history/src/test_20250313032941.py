# test_moviepy.py
import os
os.environ["IMAGEIO_FFMPEG_EXE"] = "C:\ProgramData\chocolatey\bin\ffmpeg.exe"
import sys

# Hiển thị đường dẫn tìm kiếm module
print(f"Python path: {sys.path}")

# Thử import MoviePy
try:
    import moviepy.editor as mp
    print("MoviePy đã được import thành công")
    
    # Tạo một video test đơn giản
    clip = mp.ColorClip(size=(640, 480), color=(0, 0, 255), duration=2)
    output_file = "test_output.mp4"
    clip.write_videofile(output_file, fps=24)
    print(f"Đã tạo file video test: {output_file}")
    
except Exception as e:
    print(f"Lỗi khi import hoặc sử dụng MoviePy: {e}")

# Hiển thị biến môi trường
import os
try:
    import imageio
    print(f"ImageIO path: {imageio.__path__}")
    
    import imageio_ffmpeg
    print(f"FFMPEG path: {imageio_ffmpeg.get_ffmpeg_exe()}")
    
except Exception as e:
    print(f"Lỗi khi kiểm tra imageio: {e}")