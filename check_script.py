# check_script.py
import logging
import os
import sys
import json
from datetime import datetime
from src.news_scraper import NewsScraper
from src.script_generator import ScriptGenerator
from src.image_generator import ImageGenerator
from src.voice_generator import VoiceGenerator
from src.video_editor import VideoEditor
from config.settings import OUTPUT_DIR, TEMP_DIR, ASSETS_DIR
from config.settings import VIDEO_SETTINGS
import pprint

from newspaper import Article
import time

from urllib.parse import urlparse, parse_qs
import re

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

    style_choice = ""
    valid_choices = ["1", "2", "3", "4", "5", "6", "7"]
    while style_choice not in valid_choices:
        style_choice = input(f"Enter style choice ({','.join(valid_choices)}, default is 1): ").strip()
        if not style_choice:
            style_choice = "1"  # Default to Informative

    style_map = {
        "1": "informative", "2": "conversational", "3": "dramatic",
        "4": "controversial", "5": "emotional", "6": "funny", "7": "motivational"
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

def main():
    logger.info("="*20 + " Automated News Video Generation " + "="*20)

    # Ensure base directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

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

    logger.info("--- User Input Gathering Complete ---")
    logger.info(f"Input Method: {choice}")
    if article_url: logger.info(f"Article URL: {article_url}")
    logger.info(f"Selected Mode: {video_mode}")
    if article_url: logger.info(f"Article URL: {article_url}")
    if keyword: logger.info(f"Keyword: {keyword}, Language: {language}")
    if youtube_url: logger.info(f"YouTube URL: {youtube_url}, Pref Langs: {preferred_langs_yt}")
    logger.info(f"Selected Style: {selected_style}")
    logger.info(f"Visual Source: {visual_source_choice}")
    print("-" * 50)

    # --- Start Processing Based on Inputs ---
    script_generator = ScriptGenerator()
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
        script = script_generator.generate_script(selected_article, style=selected_style, language=language, video_mode=video_mode)

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
        script = script_generator.generate_script_from_keyword(keyword, selected_style, language, video_mode=video_mode)


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
            video_mode=video_mode # <-- THÊM VÀO ĐÂY
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

    # --- NEW: Display Script and Exit for Testing ---
    print("\n" + "="*20 + " SCRIPT GENERATION TEST RESULT " + "="*20)
    print(f"Input Method Choice: {choice}")
    print(f"Selected Video Mode: {video_mode}")
    print(f"Selected Style: {selected_style}")
    print(f"Breakdown Enabled Setting: {VIDEO_SETTINGS.get('enable_sentence_to_shot_breakdown', True)}") # Hiển thị cài đặt
    print("-" * 50)
    if script:
        print(f"Generated Title: {script.get('title', 'N/A')}")
        print(f"Script Mode Detected: {script.get('script_mode', 'N/A')}")
        is_chapter_based = script.get('is_chapter_based', False)
        print(f"Is Chapter Based: {is_chapter_based}")

        scenes = script.get('scenes', [])
        speech_units = script.get('speech_units', [])
        print(f"Total Scenes (Shots): {len(scenes)}")
        print(f"Total Speech Units: {len(speech_units)}")

        if is_chapter_based and scenes:
            # Đếm số chapter duy nhất từ thông tin trong scenes
            chapters = set(s.get('chapter_number') for s in scenes if s.get('chapter_number') is not None)
            print(f"Total Chapters Generated: {len(chapters)}")

        print("\n--- Full Generated Script Structure: ---")
        pprint.pprint(script) # In cấu trúc dict ra console
        # Hoặc dùng json.dumps:
        # print(json.dumps(script, ensure_ascii=False, indent=2))

        print(f"\nScript also saved to (if saving succeeded): {script_path}")
    else:
        # Trường hợp này không nên xảy ra nếu kiểm tra `if not script:` ở trên hoạt động
        print("ERROR: Script object is None after generation attempt.")

    logger.info("Exiting after script generation test.")
    return # Hoặc dùng sys.exit(0) - Thoát khỏi hàm main
    # --- END NEW ---

if __name__ == "__main__":
    main()