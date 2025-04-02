# src/prompt_generator.py

from src import project_config as cfg
from src.utils import safe_truncate

# ----------------------------
# Style Definitions
# ----------------------------

style_configs = {
    "controversial": {
        "tone": "highly controversial, fast-paced",
        "instructions": [
            "Use emotional, polarizing, provocative, and impactful words.",
            "Start with the most shocking or controversial fact or question.",
            "Inject direct, sharp rhetorical questions.",
            "Build tension progressively.",
            "Use punchy contrasts and opposing viewpoints.",
            "End with a provocative or open-ended question."
        ],
        "title_hint": "A highly provocative and engaging title",
        "scene_range": (15, 25),
    },
    "informative": {
        "tone": "clear and informative",
        "instructions": [
            "Use clear, concise, and fact-based sentences.",
            "Start with a clear introduction.",
            "Divide into short, easy-to-follow key points.",
            "End with a clear conclusion."
        ],
        "title_hint": "An informative and clear title",
        "scene_range": (15, 25),
    },
    "emotional": {
        "tone": "deeply emotional and touching",
        "instructions": [
            "Use emotional, heartfelt, and vivid language.",
            "Begin with a touching or emotionally strong statement.",
            "Gradually deepen the emotional impact.",
            "End with an uplifting, heartbreaking, or reflective closing."
        ],
        "title_hint": "An emotionally powerful and engaging title",
        "scene_range": (15, 25),
    },
    "funny": {
        "tone": "funny and lighthearted",
        "instructions": [
            "Use humor, exaggeration, or satire.",
            "Begin with a funny or unexpected statement.",
            "Sprinkle in funny rhetorical questions.",
            "End with a punchline or witty remark."
        ],
        "title_hint": "A witty and humorous title",
        "scene_range": (15, 25),
    },
    "motivational": {
        "tone": "highly motivational and inspiring",
        "instructions": [
            "Use powerful, inspiring, and uplifting language.",
            "Start with an attention-grabbing and inspiring statement.",
            "Increase the intensity of inspiration as you progress.",
            "End with a strong call to action or impactful quote."
        ],
        "title_hint": "A powerful and inspiring title",
        "scene_range": (15, 25),
    },
    "conversational": {
        "tone": "friendly and engaging",
        "instructions": [
            "Use a conversational and easy-to-understand style.",
            "Ask rhetorical or direct questions.",
            "Use simple and clear language.",
            "Make the audience feel like you are talking directly to them."
        ],
        "title_hint": "A friendly and engaging title",
        "scene_range": (15, 25),
    },
    "dramatic": {
        "tone": "highly dramatic and impactful",
        "instructions": [
            "Use vivid, intense, and emotionally charged language.",
            "Begin with a shocking or unexpected fact.",
            "Keep tension high and build suspense throughout.",
            "Use contrasts, cliffhangers, and rhetorical questions to engage the audience.",
            "End with a powerful or thought-provoking statement."
        ],
        "title_hint": "A dramatic and impactful title",
        "scene_range": (15, 25),
    }
}

# ----------------------------
# Prompt Generator
# ----------------------------

def generate_prompt(style, article=None, keyword=None, language="en"):
    """
    Sinh prompt dùng chung cho cả bài báo hoặc từ khóa
    """
    if style not in cfg.AVAILABLE_STYLES:
        raise ValueError(f"Unknown style: {style}")

    config = style_configs[style]
    scene_min, scene_max = cfg.SCENE_RANGE[style]

    # --------- CASE 1: Article ---------
    if article is not None:
        article_title = article.get('title', '').strip()
        article_content = safe_truncate(article.get('content', '').strip(), cfg.MAX_ARTICLE_LENGTH)
        if not article_title or not article_content:
            raise ValueError("Missing article title or content.")

        prompt = f"""
        Create a {config['tone']} news script based on the following article.
        The script must be continuous and divided into short sentences (called scenes) for fast-paced video editing.

        ARTICLE TITLE: {article_title}
        ARTICLE CONTENT: {article_content}

        **SCRIPT RULES:**
        1. Each "scene" = short sentence/snippet (NOT a standalone scene).
        2. The script must flow smoothly as one continuous story.
        """

    # --------- CASE 2: Keyword ---------
    elif keyword is not None:
        if language == "vi":
            lang_label = "bằng tiếng Việt"
        else:
            lang_label = "in English"

        prompt = f"""
        Create a {config['tone']} news script {lang_label} based on the topic: \"{keyword}\".
        The script must be continuous and divided into short sentences (called scenes) for fast-paced video editing.

        **SCRIPT RULES:**
        1. Each "scene" = short sentence/snippet (NOT a standalone scene).
        2. The script must flow smoothly as one continuous story.
        """

    else:
        raise ValueError("Either article or keyword must be provided.")

    # --------- Common rules ---------
    for i, instruction in enumerate(config['instructions'], start=3):
        prompt += f"\n{i}. {instruction}"

    prompt += f"""
{len(config['instructions']) + 3}. Total: {scene_min} to {scene_max} scenes depending on topic complexity.
{len(config['instructions']) + 4}. Each scene is typically 1 impactful sentence (max 2 very short).

**Output Format (MANDATORY):**
{{
  "title": "{config['title_hint']}",
  "scenes": [
    {{"number": 1, "content": "Scene 1"}},
    {{"number": 2, "content": "Scene 2"}},
    ...
  ]
}}

- Valid JSON only.
- Write between {scene_min} and {scene_max} scenes.
    """

    return prompt.strip()
