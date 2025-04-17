# src/prompt_generator.py

from src import project_config as cfg
from src.utils import safe_truncate

# ----------------------------
# Style Definitions
# ----------------------------

# Sử dụng scene_range đã tăng lên ở bước trước (ví dụ)
# Bạn có thể điều chỉnh các giá trị này sau khi thử nghiệm
style_configs = {
    "controversial": {
        "tone": "highly controversial, fast-paced",
        "instructions": ["Use emotional, polarizing words.", "Start with shocking fact/question.", "Inject sharp questions.", "Build tension.", "Use punchy contrasts.", "End provocatively."],
        "title_hint": "A highly provocative and engaging title",
        "scene_range": (40, 80),
    },
    "informative": {
        "tone": "clear and informative",
        "instructions": ["Use clear, concise segments.", "Start with intro phrase.", "Break down info into tiny visual chunks.", "End with conclusion phrase."],
        "title_hint": "An informative and clear title",
        "scene_range": (80, 150),
    },
    # ... (Giữ nguyên các style khác với scene_range đã tăng) ...
     "emotional": {
        "tone": "deeply emotional and touching",
        "instructions": ["Use emotional, heartfelt snippets.", "Begin with touching fragment.", "Deepen impact via short phrases.", "End with reflective fragment."],
        "title_hint": "An emotionally powerful title",
        "scene_range": (40, 80),
    },
    "funny": {
        "tone": "funny and lighthearted",
        "instructions": ["Use humor in short bursts.", "Begin with funny phrase.", "Sprinkle witty fragments.", "End with punchline fragment."],
        "title_hint": "A witty and humorous title",
        "scene_range": (40, 80),
    },
    "motivational": {
        "tone": "highly motivational and inspiring",
        "instructions": ["Use powerful, uplifting snippets.", "Start with inspiring fragment.", "Increase intensity with impactful phrases.", "End with strong call to action fragment."],
        "title_hint": "A powerful and inspiring title",
        "scene_range": (40, 80),
    },
    "conversational": {
        "tone": "friendly and engaging",
        "instructions": ["Use conversational phrases.", "Use simple, clear snippets.", "Break down thoughts into small parts."],
        "title_hint": "A friendly and engaging title",
        "scene_range": (50, 100),
    },
    "dramatic": {
        "tone": "highly dramatic and impactful",
        "instructions": ["Use vivid, intense fragments.", "Begin with shocking phrase.", "Keep tension high with short snippets.", "Use contrasts.", "End with powerful fragment."],
        "title_hint": "A dramatic and impactful title",
        "scene_range": (40, 80),
    },
    "senior_conversational": {
    "tone": "warm, conversational, and motivational, targeted at seniors (60+)", # Lấy từ prompt
    "instructions": [
        "Speak directly to the viewer like a caring friend.",
        "Use simple, clear language, avoid jargon or overly complex sentences.",
        "Provide practical, actionable advice with relatable examples for seniors.",
        "Maintain a positive, reassuring, and uplifting mood.",
        "Ensure smooth, natural transitions between ideas and chapters.",
        "Write as a continuous narrative, avoiding bullet points or explicit section titles in the content."
    ],
    "title_hint": "A helpful, friendly, and encouraging title for seniors", # Điều chỉnh hint
    # Tăng scene_range đáng kể vì các chapter sẽ dài hơn.
    # Con số này chủ yếu ảnh hưởng đến bước breakdown, không phải word count tổng.
    "scene_range": (150, 350),
    "target_audience": "60+", # Thêm thông tin về đối tượng mục tiêu
    },
    "senior_conversational": {
    "tone": "warm, conversational, and motivational, targeted at seniors (60+)",
    "instructions": [
        "Speak directly to the viewer like a caring friend.",
        "Use simple, clear language, avoid jargon or overly complex sentences.",
        "Provide practical, actionable advice with relatable examples for seniors.",
        "Maintain a positive, reassuring, and uplifting mood.",
        "Ensure smooth, natural transitions between ideas and chapters.",
        "Write as a continuous narrative, avoiding bullet points or explicit section titles in the content."
    ],
    "title_hint": "A helpful, friendly, and encouraging title for seniors",
    "scene_range": (150, 350),
    "target_audience": "60+",
    # --- THÊM CẤU HÌNH LAYOUT ĐẶC BIỆT ---
    "layout_override": {
        "enabled": True, # Bật chế độ override layout prompt
        "target_total_word_range": (2800, 4000), # Mục tiêu tổng từ (để LLM tham khảo)
        "chapter_count_range": (3, 5),         # Số chapter mong muốn
        "chapter_word_target_range": (400, 700), # Mục tiêu từ/chapter
        "structure_prompt": "Structure the video logically into 3 main conceptual parts: 1) An engaging Introduction/Hook, 2) The main discussion points providing value and practical advice, 3) A concluding summary and call to action/uplifting message. Divide these 3 conceptual parts into {chapter_count_min} to {chapter_count_max} distinct chapters in the final layout." # Prompt mô tả cấu trúc
    }
    },
}

# ----------------------------
# Prompt Generator
# ----------------------------

def generate_prompt(style, article=None, keyword=None, language="en"):
    """
    Sinh prompt yêu cầu chia nhỏ thành shots (scenes) và nhóm thành speech_units.
    """
    if style not in cfg.AVAILABLE_STYLES:
        raise ValueError(f"Unknown style: {style}")

    config = style_configs[style]
    scene_min, scene_max = cfg.SCENE_RANGE[style]

    # --- Định nghĩa lại khái niệm "Scene" (Shot) và "Speech Unit" ---
    structure_definition = """
    **Critical Output Structure Requirements:**

    1.  **`scenes` (Visual Shots/Slides):**
        *   This array defines the *visual* flow. Each element is a VERY SHORT text segment (a "shot" or "slide").
        *   You MUST aggressively break down the original sentences into these tiny visual scenes/shots.
        *   Focus on splitting based on distinct visual concepts, keywords, actions, or natural pauses.
        *   Example: "They grow barley, wheat, dates, lotus, and apples." becomes multiple scenes: `{"number": 1, "content": "They grow"}, {"number": 2, "content": "barley, wheat"}, {"number": 3, "content": "dates"}, {"number": 4, "content": "lotus"}, {"number": 5, "content": "and apples."}`.
        *   Scene numbers MUST be sequential starting from 1.

    2.  **`speech_units` (Audio Segments):**
        *   This array defines the *audio* flow for natural-sounding voice generation.
        *   Each element groups one or more consecutive `scenes` into a logical, natural-sounding phrase or sentence.
        *   The `text` field in each `speech_unit` MUST be the exact concatenation of the `content` from the scenes listed in its `scene_numbers` array, forming a complete, speakable unit.
        *   The `scene_numbers` array lists the `number`s of the scenes belonging to this speech unit.
        *   All scenes MUST be included in exactly one speech unit, and the units must cover the scenes sequentially without gaps or overlaps.
        *   Example: If scenes 1-5 form a sentence, the speech unit would be `{"unit_number": 1, "text": "They grow barley, wheat, dates, lotus, and apples.", "scene_numbers": [1, 2, 3, 4, 5]}`.
    """

    # --------- CASE 1: Article ---------
    if article is not None:
        article_title = article.get('title', '').strip()
        article_content = safe_truncate(article.get('content', '').strip(), cfg.MAX_ARTICLE_LENGTH)
        if not article_title or not article_content:
            raise ValueError("Missing article title or content.")

        prompt = f"""
        Create a {config['tone']} news script based on the following article.
        The script must be meticulously structured into two parts as defined below:
        1) Extremely short visual `scenes` (shots/slides).
        2) Logical `speech_units` grouping these scenes for natural audio.

        ARTICLE TITLE: {article_title}
        ARTICLE CONTENT: {article_content}

        {structure_definition}

        **Script Content Rules:**
        *   Follow the {config['tone']} style.
        *   Ensure the concatenated `speech_units.text` accurately reflects the core information of the article.
        *   Generate between {scene_min} and {scene_max} SHORT visual scenes in total.
        """

    # --------- CASE 2: Keyword ---------
    elif keyword is not None:
        if language == "vi":
            lang_label = "bằng tiếng Việt"
        else:
            lang_label = "in English"

        prompt = f"""
        Create a {config['tone']} news script {lang_label} based on the topic: \"{keyword}\".
        The script must be meticulously structured into two parts as defined below:
        1) Extremely short visual `scenes` (shots/slides).
        2) Logical `speech_units` grouping these scenes for natural audio.

        TOPIC: "{keyword}"

        {structure_definition}

        **Script Content Rules:**
        *   Generate relevant content for the keyword in the specified {config['tone']} style.
        *   Immediately break down the generated content into the required `scenes` and `speech_units`.
        *   Generate between {scene_min} and {scene_max} SHORT visual scenes in total.
        """
    else:
        raise ValueError("Either article or keyword must be provided.")

    # --------- Common Style Instructions ---------
    # Add specific style instructions subtly
    prompt += "\n**Style Guidance:**\n"
    for instruction in config['instructions']:
         prompt += f"- {instruction}\n"

    # --------- Output Format Reminder ---------
    prompt += f"""
**Final Output Format (JSON ONLY - Adhere Strictly):**
{{
  "title": "{config['title_hint']}",
  "scenes": [
    {{"number": 1, "content": "Short shot 1"}},
    {{"number": 2, "content": "Next few words"}},
    // ... more scenes ...
  ],
  "speech_units": [
    {{
      "unit_number": 1,
      "text": "Concatenated text of scenes in this unit.",
      "scene_numbers": [/* list of scene numbers */]
    }},
    // ... more speech units ...
  ]
}}

**REMEMBER:** Provide ONLY the valid JSON object. No introductory text, explanations, or code fences. Both `scenes` and `speech_units` arrays are mandatory. Ensure perfect sequential coverage of scenes by speech units.
    """
    return prompt.strip()