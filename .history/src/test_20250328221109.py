# Tạo file test.py
article = {
    "title": "Climate Protests Sweep Through European Capitals",
    "content": "Thousands of climate activists gathered in major European capitals this weekend to demand stronger environmental policies. In Paris, protesters marched from the Arc de Triomphe to the Eiffel Tower, waving banners and chanting slogans. The London demonstration saw participants floating a large model of a burning Earth down the Thames River. Meanwhile, in Berlin, activists blocked traffic at Brandenburg Gate, creating a human chain that stretched for nearly a kilometer. Organizers claimed over 50,000 participants across all events, though official estimates were lower. Several celebrities joined the protests, adding visibility to the cause. Government officials from several countries promised to review current climate policies in response to the growing pressure.",
    "source": "Environmental News Network"
}

# Import và gọi quy trình tạo video
from src.script_generator import ScriptGenerator
from src.image_generator import ImageGenerator
from src.audio_generator import AudioGenerator
from src.video_generator import VideoGenerator

# Tạo script
script_gen = ScriptGenerator()
script = script_gen.generate_script(article)

# Kiểm tra các scene đã được đánh dấu chưa
video_scenes = sum(1 for scene in script.get('scenes', []) if scene.get('prefer_video', False))
print(f"Script có {len(script.get('scenes', []))} scene, {video_scenes} scene được đánh dấu nên dùng video")

# Tiếp tục quy trình tạo video...