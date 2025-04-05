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

def validate_script_json_with_speech_units(response_text):
    """Kiểm tra JSON script bao gồm cả cấu trúc 'scenes' và 'speech_units'."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        return False, f"JSON Decode Error: {e}"

    if not isinstance(data, dict):
        return False, "Script must be a JSON object."

    if "title" not in data or not isinstance(data["title"], str) or not data["title"].strip():
        return False, "Missing or invalid 'title' field."

    # Validate 'scenes'
    if "scenes" not in data or not isinstance(data["scenes"], list) or not data["scenes"]: # Chỉ cần scenes tồn tại và là list
        return False, "Missing or invalid 'scenes' field (must be a list, can be empty initially if keyword generation)."
        # Có thể nới lỏng kiểm tra số lượng tối thiểu ở đây nếu cần

    all_scene_numbers = set()
    max_scene_num = 0
    for i, scene in enumerate(data["scenes"], 1):
        if not isinstance(scene, dict):
            return False, f"Scene item #{i} is not a JSON object."
        if "number" not in scene or not isinstance(scene["number"], int) or scene["number"] <= 0:
            return False, f"Scene item #{i} missing or invalid 'number' field (must be positive integer)."
        if "content" not in scene or not isinstance(scene["content"], str):
             # Cho phép content rỗng vì shot có thể rất ngắn hoặc chỉ là hình ảnh
             # return False, f"Scene #{scene.get('number', i)} missing or invalid 'content' field."
             pass # Allow empty content for shots
        scene_num = scene["number"]
        if scene_num in all_scene_numbers:
            return False, f"Duplicate scene number found: {scene_num}"
        all_scene_numbers.add(scene_num)
        max_scene_num = max(max_scene_num, scene_num)

    # Check if scene numbers are sequential from 1 to max
    if all_scene_numbers and set(range(1, max_scene_num + 1)) != all_scene_numbers:
         return False, f"Scene numbers are not sequential from 1 to {max_scene_num}."


    # Validate 'speech_units'
    if "speech_units" not in data or not isinstance(data["speech_units"], list) or not data["speech_units"]:
        return False, "Missing or empty 'speech_units' field. This is required for audio generation."

    all_scenes_covered_by_units = set()
    last_scene_number_in_unit = 0
    max_unit_num = 0
    for i, unit in enumerate(data["speech_units"], 1):
        if not isinstance(unit, dict):
            return False, f"Speech Unit item #{i} is not a JSON object."
        if "unit_number" not in unit or not isinstance(unit["unit_number"], int) or unit["unit_number"] <= 0:
            return False, f"Speech Unit item #{i} missing or invalid 'unit_number' (must be positive integer)."
        if "text" not in unit or not isinstance(unit["text"], str) or not unit["text"].strip():
             # Text trong speech unit phải có nội dung
             return False, f"Speech Unit #{unit.get('unit_number', i)} missing or empty 'text'."
        if "scene_numbers" not in unit or not isinstance(unit["scene_numbers"], list) or not unit["scene_numbers"]:
             # Phải có ít nhất 1 scene trong unit
             return False, f"Speech Unit #{unit.get('unit_number', i)} missing or empty 'scene_numbers'."

        unit_num = unit["unit_number"]
        max_unit_num = max(max_unit_num, unit_num)

        current_unit_scenes = set()
        min_scene_in_unit = float('inf')
        max_scene_in_unit = 0
        for scene_num in unit["scene_numbers"]:
            if not isinstance(scene_num, int) or scene_num <= 0:
                return False, f"Invalid scene number '{scene_num}' in Speech Unit #{unit_num}."
            # Kiểm tra tính liên tục *so với unit trước*
            if scene_num <= last_scene_number_in_unit:
                return False, f"Scene numbers not sequential across units. Scene {scene_num} in Unit {unit_num} overlaps or is out of order with previous unit (last scene was {last_scene_number_in_unit})."
            # Kiểm tra trùng lặp *trong các unit khác nhau*
            if scene_num in all_scenes_covered_by_units:
                return False, f"Scene number {scene_num} appears in multiple Speech Units."
            # Kiểm tra xem scene có tồn tại trong danh sách 'scenes' không
            if scene_num not in all_scene_numbers:
                 return False, f"Speech Unit #{unit_num} refers to a non-existent scene number: {scene_num}."

            current_unit_scenes.add(scene_num)
            all_scenes_covered_by_units.add(scene_num)
            min_scene_in_unit = min(min_scene_in_unit, scene_num)
            max_scene_in_unit = max(max_scene_in_unit, scene_num)

        # Kiểm tra tính liên tục *bên trong* unit
        if set(range(min_scene_in_unit, max_scene_in_unit + 1)) != current_unit_scenes:
             return False, f"Scene numbers within Speech Unit #{unit_num} are not consecutive."

        # Cập nhật scene cuối cùng đã thấy để kiểm tra unit tiếp theo
        last_scene_number_in_unit = max_scene_in_unit

    # Check if all scenes are covered by units exactly once
    if all_scenes_covered_by_units != all_scene_numbers:
        missing_scenes = all_scene_numbers - all_scenes_covered_by_units
        extra_scenes = all_scenes_covered_by_units - all_scene_numbers
        msg = "Mismatch between scenes defined and scenes covered by speech units. "
        if missing_scenes: msg += f"Scenes missing from units: {sorted(list(missing_scenes))}. "
        if extra_scenes: msg += f"Units refer to non-existent scenes: {sorted(list(extra_scenes))}."
        return False, msg

    # Check if unit numbers are sequential from 1 to max
    if set(range(1, max_unit_num + 1)) != {u['unit_number'] for u in data['speech_units']}:
        return False, f"Speech Unit numbers are not sequential from 1 to {max_unit_num}."


    return True, "Valid script JSON with scenes and speech_units."

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
