# test_advanced_prompts.py

import sys
import os
import json
import logging

# --- Thêm đường dẫn gốc vào sys.path ---
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --------------------------------------

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("AdvancedPromptTest")

# Import các lớp/hàm cần thiết
try:
    from src.video_styles.base_style import BaseVideoStyle
    from src.video_styles.senior_conversational_style import SeniorConversationalStyle
    from src.script_generator import ScriptGenerator # Cần để gọi các hàm nội bộ
    from src.utils import safe_truncate
    # Import credentials nếu cần (ví dụ: để kiểm tra key khi chọn model)
    from config.credentials import OPENAI_API_KEY, DEEPSEEK_API_KEY
except ImportError as e:
    logger.error(f"Lỗi import: {e}. Đảm bảo file test được chạy từ thư mục gốc project.")
    sys.exit(1)

# --- Code Thực thi Test ---
if __name__ == "__main__":

    print("\n" + "="*10 + " Test Tạo Prompt Chế độ Advanced (Senior Style) " + "="*10)

    # 1. Khởi tạo Strategy và ScriptGenerator (chỉ để gọi hàm nội bộ)
    try:
        senior_strategy = SeniorConversationalStyle()
        # Khởi tạo ScriptGenerator với provider mặc định (hoặc provider bạn muốn test)
        # Không cần API key hoạt động vì chúng ta chỉ test tạo prompt, không gọi API thực sự
        script_gen = ScriptGenerator(selected_provider='openai') # Giả sử OpenAI là default
        logger.info("Đã tạo đối tượng SeniorConversationalStyle và ScriptGenerator.")
    except Exception as e:
        logger.error(f"Lỗi khi khởi tạo: {e}")
        sys.exit(1)

    # 2. Dữ liệu nguồn giả lập (ví dụ: keyword)
    test_source_data = {
        'type': 'keyword',
        'data': 'maintaining cognitive health after 70'
    }
    test_language = 'en'

    # ===========================================================
    # Test 1: Prompt Tạo Layout (Giai đoạn 1)
    # ===========================================================
    print("\n" + "-"*5 + " Test 1: Prompt Tạo Layout (Advanced - Stage 1) " + "-"*5)
    try:
        # Gọi hàm _generate_video_layout từ ScriptGenerator (vì nó chứa logic tạo prompt layout)
        # Lưu ý: Hàm này thực sự gọi LLM, nhưng ở đây ta chỉ quan tâm prompt nó tạo ra
        # Chúng ta sẽ không chạy phần gọi API thực sự trong test này.
        # -> Thay vào đó, tái tạo lại logic tạo prompt của _generate_video_layout ở đây để test
        logger.info("Tạo prompt layout (giả lập từ logic _generate_video_layout)...")

        # Lấy các tham số cần thiết từ strategy
        style_config_data = senior_strategy.get_style_config()
        use_override_layout = senior_strategy.should_override_layout()
        layout_params = senior_strategy.get_layout_generation_params() if use_override_layout else {}
        target_audience = style_config_data.get("target_audience")

        # Xác định tham số layout động (copy từ _generate_video_layout)
        if use_override_layout:
            ch_min, ch_max = layout_params.get("chapter_count_range", (3, 5))
            wt_min, wt_max = layout_params.get("chapter_word_target_range", (400, 700))
            ttw_min, ttw_max = layout_params.get("target_total_word_range", (1500, 3000))
            raw_structure_instruction = layout_params.get("structure_prompt", "")
            structure_instruction = raw_structure_instruction.format(chapter_count_min=ch_min, chapter_count_max=ch_max) if raw_structure_instruction else ""
        else: # Mặc định (dù senior luôn override)
            ch_min, ch_max = (3, 7); wt_min, wt_max = (150, 300); ttw_min, ttw_max = (0, 0); structure_instruction = ""

        # Xây dựng prompt layout (copy logic từ _generate_video_layout)
        prompt_layout = f"""
        You are an expert video script outliner...
        Video Style Context:
        - Tone: {style_config_data['tone']}
        - Goal: {style_config_data.get('goal', 'To inform and engage')}
        """
        if target_audience: prompt_layout += f"- Target Audience: {target_audience}\n"
        prompt_layout += "\nSource Material:\n"
        input_type = test_source_data.get('type'); content_data = test_source_data.get('data')
        if input_type == 'keyword':
             prompt_layout += f"- Type: Keyword/Topic\n- Topic: \"{content_data}\"\n"
             prompt_layout += f"\nTask: Develop a video outline in {test_language} about '{content_data}'. Define a main title and logical chapters."
        # Thêm elif cho 'article', 'text' nếu muốn test
        prompt_layout += "\n\n**Chapter Requirements:**\n"
        if use_override_layout:
             if target_audience: prompt_layout += f"- **Target Audience:** ... {target_audience}**.\n"
             if structure_instruction: prompt_layout += f"- **Structure Guidance:** {structure_instruction}\n"
             prompt_layout += f"- **Chapter Count:** Create between **{ch_min} and {ch_max}** chapters...\n"
             prompt_layout += "- **Chapter Titles:** ...\n- **Chapter Summaries:** ...\n"
             prompt_layout += f"- **Word Count & Detail Level:** ... target: {ttw_min}-{ttw_max} words approx... typically between **{wt_min} and {wt_max} words per chapter**...\n"
        else: prompt_layout += f"- Identify **{ch_min} to {ch_max}** sections...\n" # ... (yêu cầu mặc định) ...
        prompt_layout += "\nOutput Format:\nReturn ONLY a valid JSON object...\n" # ... (phần output format) ...

        print("\n--- PROMPT TẠO LAYOUT (Giai đoạn 1) ---")
        print(prompt_layout.strip())
        print("-" * 70)

        # Kiểm tra nhanh
        if f"between **{ch_min} and {ch_max}** distinct chapters" in prompt_layout:
            logger.info("Kiểm tra Layout: Yêu cầu số chương đúng.")
        if f"between **{wt_min} and {wt_max} words per chapter**" in prompt_layout:
             logger.info("Kiểm tra Layout: Yêu cầu word count/chapter đúng.")
        if structure_instruction and structure_instruction in prompt_layout:
             logger.info("Kiểm tra Layout: Chứa structure_prompt.")

    except Exception as e:
        logger.error(f"Lỗi khi tạo prompt layout: {e}", exc_info=True)

    # ===========================================================
    # Test 2: Prompt Tạo Content Chapter 1 (Giai đoạn 2)
    # ===========================================================
    print("\n" + "-"*5 + " Test 2: Prompt Tạo Content Chapter 1 (Advanced - Stage 2) " + "-"*5)
    # Giả lập layout đã được tạo từ Bước 1
    mock_layout_data = {
        "title": "Keeping Your Mind Sharp: Cognitive Health After 70",
        "layout": [
            {"chapter_number": 1, "chapter_title": "Understanding Cognitive Decline", "summary": "Explaining what normal age-related changes are versus more serious decline.", "word_count_target": 850},
            {"chapter_number": 2, "chapter_title": "Brain-Boosting Habits", "summary": "Discussing diet, exercise, and sleep.", "word_count_target": 900},
            {"chapter_number": 3, "chapter_title": "Staying Mentally Active", "summary": "Highlighting learning, puzzles, and social interaction.", "word_count_target": 950},
             {"chapter_number": 4, "chapter_title": "When to Seek Help", "summary": "Recognizing warning signs and consulting professionals.", "word_count_target": 800}
        ]
    }
    current_chapter_outline = mock_layout_data["layout"][0] # Lấy chapter 1

    try:
        # Gọi trực tiếp hàm _generate_chapter_content từ instance script_gen
        logger.info("Tạo prompt content cho Chapter 1...")
        # Tái tạo logic tạo prompt bên trong _generate_chapter_content để kiểm tra
        style_config_data = senior_strategy.get_style_config()
        style_tone = style_config_data.get('tone')
        style_instructions = style_config_data.get('instructions')
        target_audience = style_config_data.get('target_audience')
        chapter_num = current_chapter_outline['chapter_number']
        chapter_title = current_chapter_outline['chapter_title']
        chapter_summary = current_chapter_outline['summary']
        word_count_target = current_chapter_outline['word_count_target']
        next_chapter_title = mock_layout_data["layout"][1]['chapter_title'] if len(mock_layout_data["layout"]) > 1 else None

        # Lấy hướng dẫn content đặc biệt từ strategy
        chapter_content_instructions = senior_strategy.get_chapter_content_instructions(
            chapter_num, len(mock_layout_data["layout"]), chapter_summary, word_count_target, next_chapter_title
        )
        # Lấy hướng dẫn hook từ strategy
        hook_instr_str = senior_strategy.hook_instructions()

        # Xây dựng prompt (copy logic từ _generate_chapter_content)
        prompt_ch1 = f"You are a detailed... style: '{style_tone}'...\n"
        if target_audience: prompt_ch1 += f"\n**IMPORTANT: Tailor... audience: {target_audience}.**\n"
        prompt_ch1 += f"\n**Overall Video Context:**\n - Main Video Title: \"{mock_layout_data['title']}\"\n - Full Video Layout:\n```json\n{json.dumps(mock_layout_data['layout'], indent=2)}\n```\n - Target Style/Tone: {style_tone}\n"
        prompt_ch1 += f"\n**Current Chapter Focus:**\n - ONLY for: **Chapter {chapter_num}: \"{chapter_title}\"**\n - Goal: \"{chapter_summary}\"\n - Target Word Count: ~{word_count_target} words.\n"
        prompt_ch1 += "\n**Source Material:**\n" # Thêm source nếu cần test
        if test_source_data['type'] == 'keyword': prompt_ch1 += f"- Type: Keyword/Topic\n- Main Topic: \"{test_source_data['data']}\"\n"
        # Thêm elif cho article/text

        # Thêm hướng dẫn content và hook
        if chapter_content_instructions: prompt_ch1 += f"\n{chapter_content_instructions}\n"
        prompt_ch1 += "\n**Your Task & General Instructions:**\n"
        if chapter_num == 1 and hook_instr_str: prompt_ch1 += f"*   **Opening Hook Requirement:** {hook_instr_str.strip()}\n"
        prompt_ch1 += f"1.  Write detailed... explore key points... Target Word Count (~{word_count_target} words)...\n"
        prompt_ch1 += f"2.  Expand... strictly from Source Material...\n"
        prompt_ch1 += f"3.  Maintain the style ({style_tone}) and follow: {'; '.join(style_instructions)}\n"
        # ... (thêm các general instructions còn lại và output format) ...
        prompt_ch1 += "\nOutput Format:\nReturn ONLY a valid JSON object...\n{\n\"chapter_content\": [...]\n}\nREMEMBER: JSON ONLY..."


        print("\n--- PROMPT TẠO CONTENT CHAPTER 1 (Giai đoạn 2) ---")
        print(prompt_ch1.strip())
        print("-" * 70)

        # Kiểm tra nhanh
        if "**Specific Content Structure for Chapter 1:**" in prompt_ch1:
            logger.info("Kiểm tra Content Ch1: Chứa hướng dẫn cấu trúc riêng.")
        if "**Opening Hook Requirement:**" in prompt_ch1 and "tailored for a senior audience" in prompt_ch1:
            logger.info("Kiểm tra Content Ch1: Chứa hướng dẫn Hook riêng cho Senior.")

    except Exception as e:
        logger.error(f"Lỗi khi tạo prompt content chapter 1: {e}", exc_info=True)


    # ===========================================================
    # Test 3: Prompt Tạo Content Chapter Giữa (Giai đoạn 2)
    # ===========================================================
    print("\n" + "-"*5 + " Test 3: Prompt Tạo Content Chapter Giữa (Advanced - Stage 2) " + "-"*5)
    if len(mock_layout_data["layout"]) > 1: # Chỉ chạy nếu có chapter giữa
        current_chapter_outline = mock_layout_data["layout"][1] # Lấy chapter 2
        try:
            logger.info("Tạo prompt content cho Chapter 2...")

            # --- SAO CHÉP VÀ ĐIỀU CHỈNH LOGIC TẠO PROMPT TỪ TEST 2 ---
            style_config_data = senior_strategy.get_style_config()
            style_tone = style_config_data.get('tone')
            style_instructions = style_config_data.get('instructions')
            target_audience = style_config_data.get('target_audience')
            chapter_num = current_chapter_outline['chapter_number']
            chapter_title = current_chapter_outline['chapter_title']
            chapter_summary = current_chapter_outline['summary']
            word_count_target = current_chapter_outline['word_count_target']
            # Xác định next_chapter_title cho chapter hiện tại (chapter 2)
            next_chapter_title = mock_layout_data["layout"][2]['chapter_title'] if len(mock_layout_data["layout"]) > 2 else None

            # Lấy hướng dẫn content đặc biệt từ strategy cho chapter này
            chapter_content_instructions = senior_strategy.get_chapter_content_instructions(
                chapter_num, len(mock_layout_data["layout"]), chapter_summary, word_count_target, next_chapter_title
            )

            # --- KHỞI TẠO BIẾN prompt_ch_mid ---
            prompt_ch_mid = f"You are a detailed and engaging scriptwriter specializing in the style: '{style_tone}'...\n" # Bắt đầu prompt
            if target_audience: prompt_ch_mid += f"\n**IMPORTANT: Tailor... audience: {target_audience}.**\n"
            prompt_ch_mid += f"\n**Overall Video Context:**\n - Main Video Title: \"{mock_layout_data['title']}\"\n - Full Video Layout:\n```json\n{json.dumps(mock_layout_data['layout'], indent=2)}\n```\n - Target Style/Tone: {style_tone}\n"
            prompt_ch_mid += f"\n**Current Chapter Focus:**\n - ONLY for: **Chapter {chapter_num}: \"{chapter_title}\"**\n - Goal: \"{chapter_summary}\"\n - Target Word Count: ~{word_count_target} words.\n"
            prompt_ch_mid += "\n**Source Material:**\n"
            if test_source_data['type'] == 'keyword': prompt_ch_mid += f"- Type: Keyword/Topic\n- Main Topic: \"{test_source_data['data']}\"\n"
            # Thêm elif cho article/text nếu cần

            # Thêm hướng dẫn content (nếu có)
            if chapter_content_instructions: prompt_ch_mid += f"\n{chapter_content_instructions}\n"

            # Thêm General Instructions (KHÔNG CÓ HOOK)
            prompt_ch_mid += "\n**Your Task & General Instructions:**\n"
            prompt_ch_mid += f"1.  Write detailed, engaging narrative sentences in {test_language} that thoroughly explore...\n"
            prompt_ch_mid += f"2.  Expand... strictly from Source Material...\n"
            prompt_ch_mid += f"3.  Maintain the style ({style_tone}) and follow: {'; '.join(style_instructions)}\n"
            # ... (thêm các general instructions còn lại) ...
            prompt_ch_mid += f"6. Write ONLY natural-sounding sentences...\n" # ví dụ
            prompt_ch_mid += f"7. Focus on delivering value...\n"

            # Thêm Output Format
            prompt_ch_mid += "\nOutput Format:\nReturn ONLY a valid JSON object...\n{\n\"chapter_content\": [...]\n}\nREMEMBER: JSON ONLY..."
            # --- KẾT THÚC XÂY DỰNG prompt_ch_mid ---


            # --- BỎ COMMENT PHẦN IN VÀ KIỂM TRA ---
            print("\n--- PROMPT TẠO CONTENT CHAPTER GIỮA (Giai đoạn 2) ---")
            print(prompt_ch_mid.strip())
            print("-" * 70)

            # Kiểm tra nhanh
            if chapter_content_instructions and "**Specific Content Structure for Chapter 2:**" in prompt_ch_mid:
                 logger.info("Kiểm tra Content Ch giữa: Chứa hướng dẫn cấu trúc riêng.")
            if "**Opening Hook Requirement:**" not in prompt_ch_mid:
                 logger.info("Kiểm tra Content Ch giữa: KHÔNG chứa hướng dẫn Hook (Đúng).")
            # --- KẾT THÚC BỎ COMMENT ---

        except Exception as e:
            logger.error(f"Lỗi khi tạo prompt content chapter giữa: {e}", exc_info=True)
    else:
        logger.warning("Skipping Test 3 because mock layout has less than 2 chapters.")

    # ===========================================================
    # Test 4: Prompt Chia Nhỏ Câu (Bước cuối của Basic/Advanced)
    # ===========================================================
    print("\n" + "-"*5 + " Test 4: Prompt Chia Nhỏ Câu thành Shots " + "-"*5)
    test_sentence = "Staying connected with friends and family, joining clubs, or volunteering are great ways to remain socially engaged and mentally stimulated."
    style_tone_for_breakdown = senior_strategy.get_style_config().get('tone')
    try:
        # Gọi trực tiếp hàm _breakdown_sentence_into_shots
        logger.info("Tạo prompt chia nhỏ câu...")
        # Tái tạo prompt bên trong _breakdown_sentence_into_shots
        prompt_breakdown = f"""
        Your task is to break down the provided narrative sentence into shorter visual "shots"...
        ... BUT **only when truly necessary**... Your default preference should be to **KEEP the sentence as ONE single shot**.
        **Guiding Principles (Apply Strictly):**
        ... (các nguyên tắc chia nhỏ) ...
        5.  ... choppy ({style_tone_for_breakdown}).
        ... (các nguyên tắc còn lại) ...
        **OUTPUT FORMAT (JSON ONLY):** ... {{"shots": [...]}} ...
        **EXAMPLES:** ...
        **TEXT TO BREAK DOWN:**
        "{test_sentence}"
        """

        print("\n--- PROMPT CHIA NHỎ CÂU ---")
        print(prompt_breakdown.strip())
        print("-" * 70)

    except Exception as e:
        logger.error(f"Lỗi khi tạo prompt chia nhỏ câu: {e}", exc_info=True)


    print("\n" + "="*10 + " Kết thúc Test Prompt Advanced " + "="*10)