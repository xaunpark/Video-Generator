# simple_test.py
try:
    import moviepy
    print(f"MoviePy version: {moviepy.__version__}")
    print(f"MoviePy path: {moviepy.__path__}")
    
    import moviepy.editor
    print("Import moviepy.editor thành công!")
except Exception as e:
    print(f"Lỗi: {e}")