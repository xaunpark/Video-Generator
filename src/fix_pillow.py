"""
Fix cho lỗi 'module 'PIL.Image' has no attribute 'ANTIALIAS'
"""

import PIL
from PIL import Image

# Kiểm tra và thêm các hằng số đã bị loại bỏ trong Pillow mới
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

if not hasattr(PIL.Image, 'NEAREST'):
    PIL.Image.NEAREST = PIL.Image.NEAREST

if not hasattr(PIL.Image, 'BICUBIC'):
    PIL.Image.BICUBIC = PIL.Image.BICUBIC

if not hasattr(PIL.Image, 'BILINEAR'):
    PIL.Image.BILINEAR = PIL.Image.BILINEAR