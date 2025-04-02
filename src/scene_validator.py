# src/scene_validator.py

import json

def validate_script_json(response_text):
    """Kiểm tra JSON từ OpenAI có hợp lệ và đúng định dạng không."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        return False, f"JSON Decode Error: {e}"

    if not isinstance(data, dict):
        return False, "Script must be a JSON object."

    if "title" not in data or not isinstance(data["title"], str) or not data["title"].strip():
        return False, "Missing or invalid 'title' field."

    if "scenes" not in data or not isinstance(data["scenes"], list) or len(data["scenes"]) < 3:
        return False, "Missing or too few 'scenes' (min 3 required)."

    for i, scene in enumerate(data["scenes"], 1):
        if not isinstance(scene, dict):
            return False, f"Scene #{i} is not a JSON object."
        if "number" not in scene or not isinstance(scene["number"], int):
            return False, f"Scene #{i} missing or invalid 'number' field."
        if "content" not in scene or not isinstance(scene["content"], str) or not scene["content"].strip():
            return False, f"Scene #{i} missing or empty 'content'."

    return True, "Valid script JSON."


def recommend_media_count(scene_count, ratio=1.0):
    """
    Gợi ý số lượng ảnh hoặc video cần thiết cho project dựa trên số scene.

    ratio: float >= 1.0 (đề phòng thiếu ảnh, clip)
    """
    recommended = int(scene_count * ratio)
    return recommended

# Ví dụ sử dụng
if __name__ == "__main__":
    with open("example_script.json", "r", encoding="utf-8") as f:
        script_text = f.read()
    
    valid, message = validate_script_json(script_text)
    print("Validation result:", valid)
    print("Message:", message)

    if valid:
        script = json.loads(script_text)
        print("Recommended media count:", recommend_media_count(len(script['scenes']), ratio=1.2))
