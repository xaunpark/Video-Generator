# --- START OF FILE main.py ---

# main.py
import logging
import os
import re
import sys
import json
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import pprint
from src.telegram_notifier import TelegramNotifier
from newspaper import Article
from src.news_scraper import NewsScraper
from src.script_generator import ScriptGenerator
from src.image_generator import ImageGenerator
from src.voice_generator import VoiceGenerator
from src.video_editor import VideoEditor
from config.settings import VIDEO_SETTINGS
from src.youtube_uploader import YouTubeUploader

from config.credentials import (
    OPENAI_API_KEY,
    YOUTUBE_CLIENT_SECRETS_FILE_PATH,
    YOUTUBE_REFRESH_TOKEN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID
)

from config.settings import (
    OUTPUT_DIR, TEMP_DIR, ASSETS_DIR,
    YOUTUBE_SETTINGS,
    LLM_PROVIDERS, DEFAULT_LLM_PROVIDER
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# Force always using controversial style (Keep this if needed, but user choice will override if False)
FORCE_CONTROVERSIAL_STYLE = False

# --- Add youtube-transcript-api import ---
try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
except ImportError:
    YouTubeTranscriptApi = None
    logger.warning("youtube-transcript-api not installed. YouTube transcript feature disabled.")
# -----------------------------------------

# --- Helper function to prompt for Style ---
def prompt_for_style():
    """Prompts the user to select a video style and returns the chosen style key."""
    print("\nSelect a style for the video:")
    print("1. Informative - Professional, neutral tone")
    print("2. Conversational - Friendly, approachable tone")
    print("3. Dramatic - Emphasizes impact, strong emotions")
    print("4. Controversial - Highlights opposing views, provokes debate")
    print("5. Emotional - Focuses on feelings and empathy")
    print("6. Funny - Humorous or lighthearted approach")
    print("7. Motivational - Inspiring and encouraging")
    print("8. Senior Conversational - Warm, friendly, detailed for seniors (60+)")

    style_choice = ""
    valid_choices = ["1", "2", "3", "4", "5", "6", "7", "8"]
    while style_choice not in valid_choices:
        prompt_text = f"Enter style choice ({','.join(valid_choices)}, default is 1): "
        style_choice = input(prompt_text).strip()
        if not style_choice:
            style_choice = "1"  # Default to Informative

    style_map = {
        "1": "informative", "2": "conversational", "3": "dramatic",
        "4": "controversial", "5": "emotional", "6": "funny", "7": "motivational",
        "8": "senior_conversational" # Thêm mapping cho lựa chọn mới
    }
    chosen_style = style_map.get(style_choice, "informative")

    # Apply FORCE_CONTROVERSIAL_STYLE if set
    if FORCE_CONTROVERSIAL_STYLE:
        logger.warning("FORCE_CONTROVERSIAL_STYLE is enabled. Overriding user choice.")
        return "controversial"
    else:
        return chosen_style

# --- Helper function to prompt for Visual Source ---
def prompt_for_visual_source():
    """Prompts the user to select the source for visual elements."""
    print("\nSelect method for creating visuals (images/videos):")
    print("1. Search online (Serper, Pexels, Pixabay) - Default")
    print("2. Generate images with AI (Google Imagen 3)")

    vis_choice = ""
    while vis_choice not in ["1", "2"]:
        vis_choice = input("Enter visual source choice (1 or 2, default is 1): ").strip()
        if not vis_choice:
            vis_choice = "1"

    if vis_choice == "2":
        logger.info("Selected AI image generation (Google Imagen 3).")
        print("Note: AI image generation may take longer and incur costs.")
        return "ai"
    else:
        logger.info("Selected online search for images/videos.")
        return "search" # default

# --- Helper function to get article from URL ---
def get_article_from_url(url):
    """Fetches article information from a URL using newspaper3k."""
    try:
        logger.info(f"Downloading and parsing article from URL: {url}")
        article_obj = Article(url)
        article_obj.download()
        # Add a small delay after download before parsing
        time.sleep(1) # Consider making this configurable or removing if not needed
        article_obj.parse()

        if not article_obj.title or not article_obj.text:
            logger.error(f"Could not extract title or content from URL: {url}")
            return None

        # Create a structure similar to RSS articles
        article_data = {
            'title': article_obj.title,
            'content': article_obj.text,
            'summary': article_obj.summary, # newspaper3k generates summary
            'image_url': article_obj.top_image,
            'source': article_obj.source_url or urlparse(url).netloc, # Use domain as source fallback
            'url': url,
            'published_date': article_obj.publish_date.strftime("%Y-%m-%d") if article_obj.publish_date else datetime.now().strftime("%Y-%m-%d"),
            'language': article_obj.meta_lang or 'en' # Try getting language from meta tag
        }
        logger.info(f"Successfully extracted article: '{article_data['title']}'")
        return article_data

    except Exception as e:
        logger.error(f"Error processing article URL {url}: {str(e)}", exc_info=True)
        return None

# --- Function to get YouTube transcript ---
def get_youtube_transcript(video_url, languages=None):
    """Fetches the transcript for a given YouTube video URL."""
    if languages is None:
        languages = ['en', 'vi'] # Default preference

    if YouTubeTranscriptApi is None:
        logger.error("YouTubeTranscriptApi is not installed. Cannot fetch transcripts.")
        return None, None

    video_id = None
    try:
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/|v\/|youtu\.be\/)([0-9A-Za-z_-]{11}).*'
        ]
        for pattern in patterns:
            match = re.search(pattern, video_url)
            if match:
                video_id = match.group(1)
                break

        if not video_id:
            logger.error(f"Could not extract YouTube video ID from URL: {video_url}")
            return None, None

        logger.info(f"Extracted YouTube Video ID: {video_id}")
        logger.info(f"Attempting to fetch transcript for video ID {video_id} in languages: {languages}")

        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        detected_language = None

        # Try preferred languages (manual first)
        for lang_code in languages:
            try:
                transcript = transcript_list.find_transcript([lang_code])
                detected_language = lang_code
                logger.info(f"Found manually created transcript in '{lang_code}'.")
                break
            except NoTranscriptFound: continue

        # Try preferred languages (generated)
        if not transcript:
            for lang_code in languages:
                try:
                    transcript = transcript_list.find_generated_transcript([lang_code])
                    detected_language = lang_code
                    logger.info(f"Found automatically generated transcript in '{lang_code}'.")
                    break
                except NoTranscriptFound: continue

        # Try any available language if still not found
        if not transcript:
            logger.warning(f"No transcript found in preferred languages {languages}. Trying any available language.")
            try:
                available_transcripts_list = list(transcript_list) # Get available transcripts
                if available_transcripts_list:
                    first_available = available_transcripts_list[0]
                    transcript = first_available.translate('en') # Example: try translating to English
                    # Or simply fetch the first one: transcript = first_available
                    # transcript = transcript_list.find_transcript([first_available.language_code]) # Fetch using its code
                    detected_language = first_available.language # Get the actual language code
                    logger.info(f"Found transcript in language: '{detected_language}'. Will attempt fetch.")
                    # Ensure we get the right object to call fetch on
                    transcript = transcript_list.find_transcript([detected_language])
                else:
                    raise NoTranscriptFound("No transcripts available at all.")
            except NoTranscriptFound:
                logger.error(f"No transcript found for video {video_id} in any language.")
                return None, None
            except Exception as find_err:
                 logger.error(f"Error finding any transcript for video {video_id}: {find_err}", exc_info=True)
                 return None, None

        # Fetch the actual transcript data
        transcript_data = transcript.fetch()
        full_transcript = " ".join([segment.text for segment in transcript_data])

        logger.info(f"Successfully fetched transcript (Language: {detected_language}, Length: {len(full_transcript)} chars)")
        return full_transcript, detected_language

    except TranscriptsDisabled:
        logger.error(f"Transcripts are disabled for video: {video_id}")
        return None, None
    except NoTranscriptFound:
        logger.error(f"Could not find any transcript for video: {video_id}")
        return None, None
    except Exception as e:
        logger.error(f"Error fetching YouTube transcript for {video_url}: {str(e)}", exc_info=True)
        return None, None
# --- End of YouTube function ---

# --- Helper function to prompt for LLM Provider ---
def prompt_for_llm_provider():
    """Prompts the user to select an LLM provider."""
    print("\nSelect LLM Provider:")
    available_providers = list(LLM_PROVIDERS.keys())
    for i, provider_name in enumerate(available_providers):
        print(f"{i+1}. {provider_name.capitalize()}")

    default_index = -1
    try:
        default_index = available_providers.index(DEFAULT_LLM_PROVIDER)
    except ValueError:
        logger.warning(f"Default LLM Provider '{DEFAULT_LLM_PROVIDER}' not found in available list. Using first provider as default.")
        default_index = 0

    choice = ""
    valid_choices = [str(j+1) for j in range(len(available_providers))]
    while choice not in valid_choices:
        prompt_text = f"Enter LLM provider choice ({','.join(valid_choices)}, default is {default_index+1} '{available_providers[default_index].capitalize()}'): "
        choice = input(prompt_text).strip()
        if not choice:
            choice = str(default_index + 1) # Use default if empty input

    selected_index = int(choice) - 1
    chosen_provider = available_providers[selected_index]
    logger.info(f"Selected LLM Provider: {chosen_provider}")
    return chosen_provider
# --- End Helper function ---

# --- Helper function to prompt for Visual Timing Mode (SIMPLIFIED) ---
def prompt_for_visual_timing_mode():
    print("\n--- Step 3.5: Select Visual Presentation Mode ---")
    print("1. Sync visuals to audio segments (Default)")
    print("2. Overall theme visuals with fixed duration")

    timing_choice = ""
    valid_timing_choices = ["1", "2"]
    # Lấy default từ settings
    default_mode_from_settings = VIDEO_SETTINGS.get("visual_timing_mode", "sync_to_audio")
    # Map default setting to choice number
    default_choice_str = "1" if default_mode_from_settings == "sync_to_audio" else "2"

    while timing_choice not in valid_timing_choices:
        prompt_text = f"Enter visual mode choice ({','.join(valid_timing_choices)}, default is {default_choice_str}): "
        timing_choice = input(prompt_text).strip()
        if not timing_choice:
            timing_choice = default_choice_str

    # Map choice number back to mode name
    mode_map = {"1": "sync_to_audio", "2": "overall_theme_fixed_duration"}
    chosen_mode = mode_map.get(timing_choice, "sync_to_audio") # Fallback an toàn
    logger.info(f"Selected Visual Presentation Mode: {chosen_mode}")
    return chosen_mode
# --- End Helper function ---
def main():
    logger.info("="*20 + " Automated News Video Generation " + "="*20)

    # Ensure base directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

    # --- Prompt for LLM Provider FIRST ---
    print("\n--- Step 0: Select LLM Provider ---")
    selected_llm = prompt_for_llm_provider()

    # --- Gather ALL User Inputs First ---
    print("\n--- Step 1: Select Input Source ---")
    print("1. Latest news from configured RSS feeds.")
    print("2. Specific article URL.")
    print("3. Generate video from a keyword (AI content).")
    print("4. Generate video from a YouTube video transcript.")

    choice = ""
    valid_choices = ["1", "2", "3", "4"]
    while choice not in valid_choices:
        choice = input(f"Enter your choice ({','.join(valid_choices)}): ").strip()
        if choice == "4" and YouTubeTranscriptApi is None:
            print("Error: YouTube Transcript feature requires 'youtube-transcript-api'.")
            print("Please install it: pip install youtube-transcript-api")
            choice = "" # Ask again

    # --- Get Video Mode ---
    print("\n--- Step 1.5: Select Video Mode ---") # Numeration adjusted for clarity
    print("1. Basic Video (Standard news style) - Default")
    print("2. Advanced Video (Chapters for detailed topics)")

    video_mode_choice = ""
    video_mode = "basic" # Default mode
    valid_mode_choices = ["1", "2"]
    while video_mode_choice not in valid_mode_choices:
        video_mode_choice = input(f"Enter video mode choice ({','.join(valid_mode_choices)}, default is 1): ").strip()
        if not video_mode_choice:
            video_mode_choice = "1" # Default to Basic

    if video_mode_choice == "2":
        video_mode = "advanced"
        # --- Add Guidance ---
        logger.info("Selected Advanced (Chapters) mode.")
        print("INFO: Advanced mode works best with 'Keyword/Topic' input or longer 'Article URL'/'YouTube Transcript' inputs.")
        # Optional: Add warning if incompatible source was chosen earlier (e.g., RSS)
        if choice == "1":
            logger.warning("Advanced (Chapters) mode might not be ideal for short news items typically found in RSS feeds.")
    else:
        video_mode = "basic"
        logger.info("Selected Basic (Standard) mode.")
    # --- End Get Video Mode ---

    # --- Get specific details based on choice ---
    article_url = None
    keyword = None
    youtube_url = None
    preferred_langs_yt = ['en', 'vi']
    language = "en" # Default language, will be updated

    if choice == "2":
        while not article_url:
            article_url = input("Enter the article URL: ").strip()
            if not article_url.startswith('http'):
                logger.warning("Invalid URL. Please include http:// or https://.")
                article_url = ""
    elif choice == "3":
        while not keyword:
            keyword = input("Enter the keyword for AI video generation: ").strip()
            if len(keyword) < 3:
                logger.warning("Keyword is too short.")
                keyword = ""
        lang_choice = input("Select output language (vi/en, default vi): ").strip().lower()
        language = "en" if lang_choice == "en" else "vi"
    elif choice == "4":
        while not youtube_url:
            youtube_url = input("Enter the YouTube video URL: ").strip()
            if not ("youtube.com" in youtube_url or "youtu.be" in youtube_url):
                logger.warning("Invalid YouTube URL.")
                youtube_url = ""
        lang_pref_input = input(f"Enter preferred transcript languages (comma-separated, e.g., en,vi), leave blank for default ({','.join(preferred_langs_yt)}): ").strip().lower()
        if lang_pref_input:
            preferred_langs_yt = [lang.strip() for lang in lang_pref_input.split(',') if lang.strip()]

    # --- Get Style ---
    print("\n--- Step 2: Select Video Style ---")
    selected_style = prompt_for_style()

    # --- Get Visual Source ---
    print("\n--- Step 3: Select Visual Source ---")
    visual_source_choice = prompt_for_visual_source()

    # --- Get Visual Presentation Mode  ---
    final_timing_mode = prompt_for_visual_timing_mode()

    logger.info("--- User Input Gathering Complete ---")
    logger.info(f"Selected LLM: {selected_llm}")
    logger.info(f"Input Method: {choice}")
    if article_url: logger.info(f"Article URL: {article_url}")
    logger.info(f"Selected Mode: {video_mode}")
    if article_url: logger.info(f"Article URL: {article_url}")
    if keyword: logger.info(f"Keyword: {keyword}, Language: {language}")
    if youtube_url: logger.info(f"YouTube URL: {youtube_url}, Pref Langs: {preferred_langs_yt}")
    logger.info(f"Selected Style: {selected_style}")
    logger.info(f"Visual Source: {visual_source_choice}")
    logger.info(f"Visual Presentation Mode: {final_timing_mode}")
    print("-" * 50)

    # --- Start Processing Based on Inputs ---
    script_generator = ScriptGenerator(selected_provider=selected_llm)
    script = None
    selected_article = None
    transcript_text = None
    transcript_language = None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- Action based on choice ---
    if choice == "1": # RSS
        logger.info("Processing Choice 1: Fetching from RSS...")
        scraper = NewsScraper()
        articles = scraper.fetch_articles(limit=5)
        if not articles:
            logger.error("No articles found from RSS. Exiting.")
            return

        logger.info(f"Found {len(articles)} articles from RSS.")
        categorized = scraper.categorize_articles(articles)
        # Select article (same logic as before)
        priority_categories = ['politics', 'technology', 'business', 'entertainment', 'general']
        for category in priority_categories:
            category_articles = categorized.get(category, [])
            if category_articles:
                selected_article = category_articles[0]
                logger.info(f"Selected article from category {category}: {selected_article['title']}")
                break
        if not selected_article and articles:
            selected_article = articles[0]
            logger.info(f"No priority category match, selected first article: {selected_article['title']}")

        if not selected_article:
            logger.error("Could not select an article from RSS. Exiting.")
            return

        language = selected_article.get('language', 'en') # Detect language from selected article
        logger.info(f"Article language: {language}. Generating script...")
        script = script_generator.generate_script(selected_article, style=selected_style, language=language, video_mode=video_mode)

        # Save fetched articles (optional)
        try:
             with open(os.path.join(TEMP_DIR, f"articles_{timestamp}.json"), 'w', encoding='utf-8') as f:
                 json.dump(articles, f, ensure_ascii=False, indent=2)
        except Exception as e: logger.warning(f"Could not save fetched articles: {e}")


    elif choice == "2": # URL
        logger.info("Processing Choice 2: Fetching from URL...")
        selected_article = get_article_from_url(article_url)
        if not selected_article:
            logger.error(f"Failed to process article from URL: {article_url}. Exiting.")
            return

        language = selected_article.get('language', 'en')
        logger.info(f"Article language: {language}. Generating script...")
        script = script_generator.generate_script(
            selected_article,
            style=selected_style,
            language=language,
            video_mode=video_mode # Existing parameters
        )

        # Save article info (optional)
        try:
            sanitized_title = "".join(c for c in selected_article['title'][:50] if c.isalnum() or c in (' ', '_')).rstrip().replace(' ', '_')
            article_filename = f"article_url_{sanitized_title}_{timestamp}.json"
            with open(os.path.join(TEMP_DIR, article_filename), 'w', encoding='utf-8') as f:
                json.dump(selected_article, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved article info from URL to: {article_filename}")
        except Exception as save_err: logger.warning(f"Could not save article info from URL: {save_err}")


    elif choice == "3": # Keyword
        logger.info(f"Processing Choice 3: Generating script from keyword '{keyword}'...")
        # Language was already set during input gathering
        script = script_generator.generate_script_from_keyword(
            keyword,
            selected_style,
            language,
            video_mode=video_mode # Existing parameters
        )


    elif choice == "4": # YouTube Transcript
        logger.info(f"Processing Choice 4: Generating script from YouTube transcript...")
        print("Fetching transcript...")
        transcript_text, transcript_language = get_youtube_transcript(youtube_url, languages=preferred_langs_yt)

        if not transcript_text:
            logger.error(f"Could not get transcript for {youtube_url}. Exiting.")
            return # Exit if transcript fetching fails

        logger.info(f"Transcript fetched (Language: {transcript_language}).")

        # Save transcript (optional)
        try:
            transcript_filename = f"transcript_{timestamp}.txt"
            with open(os.path.join(TEMP_DIR, transcript_filename), 'w', encoding='utf-8') as f:
                f.write(f"Source URL: {youtube_url}\nDetected Language: {transcript_language}\n\n")
                f.write(transcript_text)
            logger.info(f"Saved transcript content to: {transcript_filename}")
        except Exception as save_err: logger.warning(f"Could not save transcript file: {save_err}")

        # Determine output language (Prompt user or use transcript language)
        # Example: Ask user again or just use the detected transcript language
        lang_out_choice = input(f"Select output language (vi/en, default '{transcript_language or 'vi'}'): ").strip().lower()
        language = transcript_language if not lang_out_choice else ("en" if lang_out_choice == "en" else "vi")

        logger.info(f"Generating script from transcript (Output Lang: {language})...")
        script = script_generator.generate_script_from_text(
             input_text=transcript_text,
             style=selected_style,
             language=language,
             context_hint=f"YouTube transcript ({youtube_url})",
             video_mode=video_mode # Existing parameters
        )

    # --- Validation and Script Saving ---
    if not script:
        logger.error("Script generation failed. Cannot proceed. Check previous logs.")
        return

    # Save the generated script
    script_path = os.path.join(TEMP_DIR, f"script_{timestamp}.json")
    try:
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        logger.info(f"Script saved to: {script_path}")
    except Exception as e:
        logger.error(f"Error saving script: {e}")
        return # Critical error, cannot proceed without script

    # --- Display Final Script Info ---
    print("\n" + "="*50)
    print(f"Script Generated: {script.get('title', 'N/A')}")
    print(f"Input Source Type: {choice}")
    print(f"Chosen Style: {selected_style}")
    print(f"Chosen Visual Source: {visual_source_choice}")
    print(f"Output Language: {language}")
    print(f"Number of Shots (Scenes): {len(script.get('scenes', []))}")
    print(f"Number of Speech Units: {len(script.get('speech_units', []))}")
    print("="*50 + "\n")
    print("Proceeding with Voice, Visuals, and Video Editing...")

    # --- Voice Generation ---
    logger.info("Generating voice...")
    voice_generator = VoiceGenerator()
    # Optionally set voice/model based on language/style here if needed
    # voice_generator.set_voice(...)
    audio_files = voice_generator.generate_audio_for_script(script)
    if not audio_files:
        logger.error("Audio generation failed. Cannot proceed.")
        return
    logger.info(f"Generated {len(audio_files)} audio files for speech units.")

    # --- Image/Video Generation ---
    logger.info("Generating visuals...")
    image_generator = ImageGenerator()
    logger.info(f"Requesting images (Source: {visual_source_choice}, Presentation: {final_timing_mode})...")

    images = image_generator.generate_images_for_script(
        script=script,
        audio_files_info=audio_files,
        visual_source=visual_source_choice,
        visual_timing_mode=final_timing_mode # Truyền mode timing
    )    

    if not images:
        logger.error("Visual generation failed.")
        return
    logger.info(f"Image Generator created {len(images)} visual items (intro/outro/scenes/theme).")

    if choice not in ["1", "2"]:
        if script: # Check if script object exists
             script['image_url'] = None
             
    # Save image info (optional)
    images_path = os.path.join(TEMP_DIR, f"images_{timestamp}.json")
    try:
        image_info = []
        for img in images:
            img_copy = {k: v for k, v in img.items() if k not in ['path']}
            img_copy['filename'] = os.path.basename(img.get('path', ''))
            image_info.append(img_copy)
        with open(images_path, 'w', encoding='utf-8') as f:
            json.dump(image_info, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved visual items info to: {images_path}")
    except Exception as e: logger.warning(f"Could not save visual items info: {e}")

    # --- Save Project Information ---
    article_info = {}
    creation_method = "unknown"
    if choice == "3": # Keyword
        article_info = {"title": script['title'], "url": f"keyword://{keyword}", "source": "AI Generated from Keyword"}
        creation_method = "ai_keyword"
    elif choice == "4": # YouTube Subtitles
         article_info = {"title": script['title'], "url": youtube_url, "source": f"YouTube Transcript ({youtube_url})"}
         creation_method = "youtube_subtitle"
    elif choice in ["1", "2"]: # RSS or Article URL
        article_info = {"title": selected_article['title'], "url": selected_article.get('url', ''), "source": selected_article.get('source', '')}
        creation_method = "url" if choice == "2" else "rss"

    project_info = {
        "title": script['title'],
        "timestamp": timestamp,
        "style": selected_style,
        "visual_source": visual_source_choice,
        "article": article_info,
        "script": {
            "path": script_path,
            "scenes_count": len(script['scenes']),
            "speech_units_count": len(script.get('speech_units', []))
        },
        "images": [{"type": img['type'], "filename": os.path.basename(img.get('path',''))} for img in images],
        "audio": [{"type": audio['type'], "filename": os.path.basename(audio.get('path',''))} for audio in audio_files],
        "creation_method": creation_method,
        "language": language
    }
    project_path = os.path.join(TEMP_DIR, f"project_{timestamp}.json")
    try:
        with open(project_path, 'w', encoding='utf-8') as f:
            json.dump(project_info, f, ensure_ascii=False, indent=2)
        logger.info(f"Project information saved to: {project_path}")
    except Exception as e: logger.error(f"Failed to save project information: {e}")

    # --- Video Editing ---
    try:
        logger.info("Starting final video editing process...")
        video_editor = VideoEditor()

        # Find background music
        background_music = None
        music_dir = os.path.join(ASSETS_DIR, "music")
        if os.path.exists(music_dir):
            music_files = [f for f in os.listdir(music_dir) if f.endswith(('.mp3', '.wav', '.m4a'))]
            if music_files:
                background_music = os.path.join(music_dir, music_files[0]) # Take the first one
                logger.info(f"Using background music: {music_files[0]}")

        # Sanitize title for filename
        def sanitize_filename(filename):
            import unicodedata
            filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
            filename = re.sub(r'[^\w\s-]', '', filename).strip()
            filename = re.sub(r'[-\s]+', '_', filename)
            return filename[:100] # Limit length

        safe_title = sanitize_filename(script.get('title', 'untitled_video'))
        video_filename = f"{timestamp}_{safe_title}.mp4"
        output_path_final = os.path.join(OUTPUT_DIR, video_filename)

        # Create the video
        logger.info(f"Creating video (Presentation Mode: {final_timing_mode})...")
        final_video_path = video_editor.create_video(
            script=script,
            media_items=images, # Danh sách visual items (scene-specific hoặc theme-based)
            audio_files_info=audio_files,
            output_path=output_path_final,
            background_music_path=background_music,
            visual_timing_mode=final_timing_mode # Truyền mode timing
        )

        # --- Final Output ---
        print("\n" + "="*50)
        if final_video_path and os.path.exists(final_video_path):
            print(f"Video successfully created!")
            print(f"Title: {script['title']}")
            print(f"Style: {selected_style}")
            if FORCE_CONTROVERSIAL_STYLE and choice in ["1", "2"]: # Chỉ áp dụng khi FORCE bật
                print("(FORCED CONTROVERSIAL MODE ENABLED)")
            print(f"Output: {final_video_path}")

            # --- NEW: Initialize Telegram Notifier ---
            telegram_notifier = None # Khởi tạo là None
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                logger.info("Attempting to initialize Telegram Notifier...")
                try:
                    # Khởi tạo Notifier với token và chat_id từ credentials
                    telegram_notifier = TelegramNotifier(
                        bot_token=TELEGRAM_BOT_TOKEN,
                        chat_id=TELEGRAM_CHAT_ID
                    )
                    # Log thành công nếu không có lỗi
                    logger.info("TelegramNotifier initialized successfully.")
                except ValueError as e: # Bắt lỗi cụ thể từ __init__
                    logger.error(f"Failed to initialize TelegramNotifier (ValueError): {e}")
                except ConnectionError as e: # Bắt lỗi cụ thể từ __init__
                    logger.error(f"Failed to initialize TelegramNotifier (ConnectionError): {e}")
                except Exception as tele_init_err: # Bắt lỗi chung khác
                    logger.error(f"Unexpected error initializing TelegramNotifier: {tele_init_err}", exc_info=True)
            else:
                logger.warning("Telegram BOT_TOKEN or CHAT_ID not configured in .env. Telegram notifications will be skipped.")
            # --- END NEW: Initialize Telegram Notifier ---

            # --- NEW: Ask for YouTube Upload ---
            # Chỉ hỏi upload nếu video thực sự được tạo thành công
            upload_choice = input("\nDo you want to upload this video to YouTube? (y/N): ").strip().lower()
            if upload_choice == 'y':
                logger.info("Attempting to upload video to YouTube...")
                # Kiểm tra các credentials cần thiết cho việc upload
                if not YOUTUBE_CLIENT_SECRETS_FILE_PATH or not os.path.exists(YOUTUBE_CLIENT_SECRETS_FILE_PATH):
                    logger.error(f"YouTube client secrets file not found or path not set ('{YOUTUBE_CLIENT_SECRETS_FILE_PATH}'). Cannot upload.")
                elif not YOUTUBE_REFRESH_TOKEN:
                    logger.error("YOUTUBE_REFRESH_TOKEN not found in environment variables. Cannot upload.")
                    logger.error("Please run the 'get_refresh_token.py' script once to obtain it.")
                else:
                    # Nếu có đủ thông tin, tiến hành upload
                    try:
                        # Chuẩn bị thông tin video cho YouTube
                        yt_title = script.get('title', 'AI Generated Video')
                        # Tạo description động hơn
                        yt_description = f"Video generated based on: {article_info.get('source', 'N/A')}\n"
                        if article_info.get('url'):
                            yt_description += f"Source URL: {article_info.get('url')}\n"
                        yt_description += f"Style: {selected_style}\nMode: {video_mode}"
                        # Thêm phần tóm tắt ngắn nếu có (ví dụ từ script hoặc article)
                        # yt_summary = script.get('summary', article_info.get('summary', ''))
                        # if yt_summary: yt_description += f"\n\nSummary:\n{yt_summary[:500]}" # Giới hạn độ dài summary

                        # Lấy tags và các cài đặt khác từ settings
                        yt_tags = YOUTUBE_SETTINGS.get("tags", [])
                        # Thêm style và keyword (nếu có) vào tags
                        if selected_style: yt_tags.append(selected_style)
                        if keyword: yt_tags.extend(keyword.split()) # Thêm từng từ của keyword
                        yt_tags = list(set(yt_tags)) # Loại bỏ trùng lặp

                        yt_category_id = YOUTUBE_SETTINGS.get("category_id", "28") # 28 = Science & Technology
                        yt_privacy_status = YOUTUBE_SETTINGS.get("privacy_status", "private")
                        yt_language = language # Ngôn ngữ đã xác định khi tạo script

                        logger.info("Initializing YouTube Uploader...")

                        # Đảm bảo secrets_path_str đã được định nghĩa từ YOUTUBE_CLIENT_SECRETS_FILE_PATH
                        secrets_path_str = str(YOUTUBE_CLIENT_SECRETS_FILE_PATH)
                        if not os.path.exists(secrets_path_str): # Kiểm tra lại đường dẫn
                            raise FileNotFoundError(f"Secrets file not found at final check: {secrets_path_str}")

                        uploader = YouTubeUploader(
                            client_secrets_file_path=secrets_path_str,
                            refresh_token=YOUTUBE_REFRESH_TOKEN
                        )

                        logger.info(f"Starting upload for video: '{yt_title}'")
                        youtube_video_id = uploader.upload_video(
                            video_path=final_video_path, # Đường dẫn file video đã tạo
                            title=yt_title,
                            description=yt_description,
                            tags=yt_tags,
                            category_id=yt_category_id,
                            privacy_status=yt_privacy_status,
                            language=yt_language
                        )

                        if youtube_video_id:
                            logger.info(f"--- YouTube Upload Successful! ---")
                            print(f"Video ID: {youtube_video_id}")
                            print(f"Watch Link: https://www.youtube.com/watch?v={youtube_video_id}")
                            print(f"Studio Link: https://studio.youtube.com/video/{youtube_video_id}/edit")

                            # --- NEW: Send Telegram Notification ---
                            # Kiểm tra xem notifier đã được khởi tạo thành công ở bước trước chưa
                            if telegram_notifier:
                                logger.info("Sending notification to Telegram...")
                                try:
                                    # --- SỬA ĐỔI CÁCH GỌI ---
                                    # Tạo coroutine bằng cách gọi hàm async
                                    coro = telegram_notifier.send_upload_notification_async(
                                        video_id=youtube_video_id,
                                        video_title=yt_title,
                                        video_url=f"https://www.youtube.com/watch?v={youtube_video_id}",
                                        studio_url=f"https://studio.youtube.com/video/{youtube_video_id}/edit"
                                    )
                                    # Chạy coroutine bằng asyncio.run()
                                    import asyncio # Đảm bảo asyncio đã được import ở đầu main.py
                                    sent_telegram_msg = asyncio.run(coro)
                                    # --- KẾT THÚC SỬA ĐỔI ---

                                    if sent_telegram_msg:
                                        logger.info("Telegram notification sent successfully.")
                                    else:
                                        logger.warning("Sending Telegram notification seems to have failed (check logs above).")
                                except Exception as notify_err:
                                    logger.error(f"Unexpected error sending Telegram notification: {notify_err}", exc_info=True)
                            else:
                                logger.info("Telegram notifier was not initialized, skipping notification.")
                            # --- END NEW: Send Telegram Notification ---
                            
                        else:
                            logger.error("--- YouTube Upload Failed ---")
                            print("Upload failed. Please check the application logs (app.log) for more details.")

                    except FileNotFoundError as fnf_err:
                        # Lỗi này thường xảy ra nếu client_secrets.json không tìm thấy khi khởi tạo Uploader
                        logger.error(f"Upload initialization failed: {fnf_err}")
                    except ValueError as val_err:
                        # Lỗi này thường xảy ra nếu refresh_token rỗng
                        logger.error(f"Upload initialization failed: {val_err}")
                    except Exception as upload_err:
                        logger.error(f"An unexpected error occurred during YouTube upload process: {upload_err}", exc_info=True)
                        print("An unexpected error occurred during upload. Check logs.")
            else:
                logger.info("Skipping YouTube upload as requested.")
            # --- END NEW ---


        else:
            print("Video creation failed. Check logs for details.")
            logger.error(f"Video creation process did not return a valid path or the file does not exist: {final_video_path}")
        print("="*50 + "\n")

    except Exception as e:
        # --- Sửa lỗi: Đảm bảo khối này bắt lỗi từ VideoEditor ---
        logger.error(f"An error occurred during the main video processing pipeline: {str(e)}", exc_info=True)
        print("An unexpected error stopped the process. Check app.log for details.")

if __name__ == "__main__":
    main()

# --- END OF FILE main.py ---