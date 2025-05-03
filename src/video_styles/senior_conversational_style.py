# src/video_styles/senior_conversational_style.py
from .base_style import BaseVideoStyle
from typing import Dict, Optional, List

class SeniorConversationalStyle(BaseVideoStyle):
    """
    Generates detailed, conversational scripts suitable for explaining complex topics
    to seniors or those preferring a slower, more narrative pace.
    FORCES usage of local fallback videos and fixed duration timing.
    """

    def get_style_config(self) -> Dict:
        """Returns configuration for the senior conversational style."""
        return {
            "tone": "Warm, Patient, Detailed, Conversational",
            "instructions": [
                "Speak directly to the viewer in a warm, respectful, and engaging manner.",
                "Explain concepts thoroughly, assuming no prior knowledge.",
                "Use clear, simple language but don't oversimplify complex ideas.",
                "Break down information into logical, easy-to-follow steps or chapters.",
                "Incorporate relatable analogies or simple examples.",
                "Maintain a patient and encouraging tone.",
                "Ensure a good narrative flow, like telling a story.",
                "Aim for comprehensive coverage of the topic within each chapter.",
            ],
            "goal": "To educate and engage seniors or beginners on a topic in a detailed, understandable, and conversational way.",
            "target_audience": "Seniors or individuals new to the topic seeking detailed explanations."
        }

    def should_override_layout(self) -> bool:
        """This style strongly benefits from a specific chapter layout."""
        return True

    def get_layout_generation_params(self) -> Dict:
        """Define the structure needed for the Senior Conversational style."""
        return {
            "chapter_count_range": (2, 3), #4-7 chapters total
            "chapter_word_target_range": (50, 100), # 350-600 words per chapter
            "target_total_word_range": (200, 300), # 1600-3500 words total
            "structure_prompt": (
                "Start with a welcoming introduction and clear problem/topic statement (Chapter 1). "
                "Dedicate subsequent chapters to exploring different facets, background, explanations, or steps in detail ({chapter_count_min}-{chapter_count_max} chapters total). "
                "Conclude with a summary, key takeaways, and encouraging closing remarks (Final Chapter)."
            )
        }

    def get_chapter_content_instructions(self, chapter_num, total_chapters, chapter_summary, word_count_target, next_chapter_title=None) -> str:
        """Specific instructions for generating chapter content."""
        instructions = f"""
        **Chapter-Specific Instructions (Chapter {chapter_num}/{total_chapters}):**
        - **Tone:** Maintain the warm, patient, and conversational tone throughout. Address the audience directly (using 'you' is often appropriate).
        - **Depth & Detail:** Remember the target word count (~{word_count_target} words). Fully elaborate on the points in the chapter summary ('{chapter_summary}'). Use examples, analogies, and clear explanations suitable for the target audience (seniors/beginners). Avoid jargon where possible or explain it clearly.
        - **Pacing:** Write slightly longer, more descriptive sentences than a typical news report. Ensure a relaxed, unhurried pace.
        """
        if chapter_num == 1:
            instructions += "- **Opening:** Start with a warm welcome and directly address the topic or question this video answers. Set a friendly, reassuring tone.\n"
        elif chapter_num > 1:
            instructions += "- **Transition In:** Begin by smoothly linking back to the previous chapter's main idea before introducing this chapter's focus. Use phrases like 'Now that we understand [previous topic], let's explore...', 'Building on that, we can now look at...'\n"

        if chapter_num < total_chapters and next_chapter_title:
            instructions += f"- **Transition Out:** Conclude this chapter by naturally setting the stage for the next topic ('{next_chapter_title}'). Hint at what's coming next without explicitly stating 'Next chapter...'. For example: 'This leads us nicely into thinking about...' or 'With this foundation, we're ready to explore how [next topic] plays a role...'\n"
        elif chapter_num == total_chapters:
            instructions += "- **Conclusion:** As this is the final chapter, summarize the key takeaways from the *entire video*. Offer final encouraging thoughts or practical advice. End on a positive and reassuring note.\n"

        return instructions.strip()

    def generate_script_prompt(self, source_data, language, mode="basic") -> str:
        """
        Generates the LLM prompt. This style typically uses Advanced Mode (layout override).
        """
        # This prompt generation is primarily for the 'basic' mode fallback,
        # which might not be ideal for this style. Advanced mode is preferred.
        config = self.get_style_config()
        lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"
        input_type = source_data.get('type', 'unknown')
        content_data = source_data.get('data', '')
        context_hint = source_data.get('context', None)

        prompt = f"""
        **Task:** Create a video script based on the provided source material.
        **Style:** {config['tone']} (Target Audience: {config.get('target_audience', 'Seniors/Beginners')})
        **Language:** Generate the script {lang_instruction}.
        **Goal:** {config['goal']}

        **Follow these instructions strictly:**
        """
        for instruction in config['instructions']:
            prompt += f"- {instruction}\n"
        prompt += "- Prioritize detailed explanations and a conversational flow.\n"

        prompt += f"""
        **Source Material:**
        """
        if input_type == 'article':
            prompt += f"- Type: News Article\n"
            prompt += f"- Title: {content_data.get('title', '')}\n"
            prompt += f"- Content to Elaborate On:\n{content_data.get('content', '')}\n"
            prompt += "- Task: Elaborate on this article in a detailed, conversational manner suitable for seniors.\n"
        elif input_type == 'keyword':
            prompt += f"- Type: Keyword/Topic\n"
            prompt += f"- Topic: \"{content_data}\"\n"
            prompt += "- Task: Generate a detailed, conversational script explaining this topic to seniors/beginners.\n"
        elif input_type == 'text':
            prompt += f"- Type: Input Text {f'({context_hint})' if context_hint else ''}\n"
            prompt += f"- Text Content:\n{content_data}\n"
            prompt += "- Task: Rewrite and expand on this text in a detailed, conversational style suitable for seniors.\n"
        else:
            return "Error: Invalid source data type."

        prompt += f"""
        **Output Format (Basic Mode):**
        Return ONLY a valid JSON object following this structure:
        {{
        "title": "Warm and Clear Video Title {lang_instruction}",
        "initial_scenes": [
            "First sentence, starting the conversation warmly.",
            "Second sentence, explaining a concept simply but thoroughly.",
            "Third sentence, perhaps using an analogy or simple example.",
            // ... continue generating detailed, conversational sentences. Aim for more sentences than a purely informative style.
        ]
        }}

        **REMEMBER:** JSON ONLY. No introductory text. Focus on detailed explanation and a patient, warm tone.
        """
        return prompt

    # --- Overrides for Visuals and Timing ---

    def should_override_visual_source(self) -> bool:
        """Forces the use of local fallback videos only."""
        return True

    def get_visual_source_preference(self) -> str:
        """Specifies the forced visual source type."""
        # Define a NEW identifier specifically for this purpose
        return "local_fallback_video_only"

    def should_override_timing_mode(self) -> bool:
        """Forces the use of overall theme fixed duration timing."""
        return True

    def get_preferred_timing_mode(self) -> str:
        """Specifies the forced timing mode."""
        return "overall_theme_fixed_duration"

    # --- Voice and Editing Settings (Keep as before or adjust) ---
    def get_voice_settings(self) -> dict:
        """Suggests voice settings."""
        return {
            "voice": "moss_audio_27e22420-2381-11f0-b934-42db1b8d9b3b",
            # "speed": 0.95 # Optionally slow down slightly
        }

    def get_video_editing_settings(self) -> dict:
        """Suggests video editing settings."""
        return {
            "transition_types": ["fade"], # Use 'fade' as smoother default
            "animation_intensity": 0.02,
            "image_animation": "zoom_in"
        }

    def get_description(self) -> str:
        """Returns a user-friendly description of the style."""
        return "Senior Conversational (FORCED LOCAL VIDEOS - Fixed Duration)" # Update desc