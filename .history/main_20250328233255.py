# main.py
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

# Force always using controversial style
FORCE_CONTROVERSIAL_STYLE = True

def select_script_style(article, categories=None):
    """
    Select an appropriate script style based on the article content and category
    
    Args:
        article (dict): Article with title, content, category, etc.
        categories (dict): Article categories from NewsScraper if available
        
    Returns:
        str: Script style (informative, conversational, dramatic, controversial)
    """
    # Always return controversial style if forced
    if FORCE_CONTROVERSIAL_STYLE:
        logger.info(f"Forced controversial style enabled - using controversial style for all articles")
        return "controversial"
    
    # Rest of the existing implementation remains the same
    # ... (existing implementation)

def main():
    logger.info("Starting automated news video generation program")
    
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Initialize scraper and fetch news
    scraper = NewsScraper()
    articles = scraper.fetch_articles(limit=5)
    
    if not articles:
        logger.error("No articles found. Exiting program.")
        return
    
    logger.info(f"Found {len(articles)} articles")
    
    # Categorize articles
    categorized = scraper.categorize_articles(articles)
    
    # Print list of articles by category
    for category, category_articles in categorized.items():
        if category_articles:
            logger.info(f"Category {category}: {len(category_articles)} articles")
            for i, article in enumerate(category_articles, 1):
                logger.info(f"  {i}. {article['title']}")
    
    # Save fetched news data to temp directory for future reference
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(TEMP_DIR, f"articles_{timestamp}.json"), 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    
    # Select an article for video creation
    selected_article = None
    priority_categories = ['politics', 'technology', 'business', 'entertainment', 'general']
    
    for category in priority_categories:
        if categorized.get(category) and len(categorized[category]) > 0:
            selected_article = categorized[category][0]
            logger.info(f"Selected article from {category} category: {selected_article['title']}")
            break
    
    if not selected_article:
        logger.error("No suitable article found for script generation.")
        return
    
    # Generate script with forced controversial style
    script_generator = ScriptGenerator()
    selected_style = select_script_style(selected_article, categorized)
    logger.info(f"Selected '{selected_style}' style based on current settings")
    
    script = script_generator.generate_script(selected_article, style=selected_style)
    
    if not script:
        logger.error("Could not generate script. Exiting program.")
        return
    
    # Print script information
    logger.info(f"Generated script for: {script['title']}")
    logger.info(f"Number of scenes: {len(script['scenes'])}")
    logger.info(f"Style used: {selected_style}")
    
    # Save script
    script_path = os.path.join(TEMP_DIR, f"script_{timestamp}.json")
    with open(script_path, 'w', encoding='utf-8') as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved script at: {script_path}")
    
    # Generate images for script
    image_generator = ImageGenerator()
    
    # Add image from original article if available
    if 'image_url' in selected_article:
        script['image_url'] = selected_article['image_url']
    
    # Generate images
    images = image_generator.generate_images_for_script(script)
    
    logger.info(f"Generated {len(images)} images for script")
    
    # Prepare images with full path and required attributes
    prepared_images = []
    for img in images:
        # Ensure each image has required attributes
        prepared_img = {
            'path': img.get('path', ''),
            'type': img.get('type', 'scene'),
            'duration': img.get('duration', 5),  # default duration
            'number': img.get('number', 0)  # for scene images
        }
        prepared_images.append(prepared_img)
    
    # Save image information
    images_path = os.path.join(TEMP_DIR, f"images_{timestamp}.json")
    with open(images_path, 'w', encoding='utf-8') as f:
        json.dump(prepared_images, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved image information at: {images_path}")
    
    # Generate voice for script
    voice_generator = VoiceGenerator()
    audio_files = voice_generator.generate_audio_for_script(script)
    
    logger.info(f"Generated {len(audio_files)} audio files for script")
    
    # Prepare audio files with full path and required attributes
    prepared_audio_files = []
    for audio in audio_files:
        # Ensure each audio has required attributes
        prepared_audio = {
            'path': audio.get('path', ''),
            'type': audio.get('type', 'scene'),
            'number': audio.get('number', 0)  # for scene audio
        }
        prepared_audio_files.append(prepared_audio)
    
    # Create video from images and audio
    try:
        video_editor = VideoEditor()
        
        # Find default background music if available
        background_music = None
        music_dir = os.path.join(ASSETS_DIR, "music")
        if os.path.exists(music_dir):
            music_files = [f for f in os.listdir(music_dir) if f.endswith('.mp3')]
            if music_files:
                background_music = os.path.join(music_dir, music_files[0])
        
        # Create video
        output_path = video_editor.create_video(
            prepared_images, 
            prepared_audio_files, 
            script, 
            background_music
        )
        
        logger.info(f"Successfully created video: {output_path}")
        
        # Added completion message
        print("\n" + "="*50)
        print(f"Video successfully created!")
        print(f"Title: {script['title']}")
        print(f"Style: {selected_style} (CONTROVERSIAL MODE ENABLED)")
        print(f"Output: {output_path}")
        print("="*50 + "\n")
        
    except Exception as e:
        logger.error(f"Error creating video: {str(e)}")
        # Add more detailed error logging
        logger.error(f"Detailed error: {sys.exc_info()}")

if __name__ == "__main__":
    main()