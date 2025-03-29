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
    
    # Rest of the function remains the same but will never be reached when FORCE_CONTROVERSIAL_STYLE is True
    # Determine the article's category
    article_category = None
    if categories:
        for category, articles in categories.items():
            if article in articles:
                article_category = category
                break
    
    # Keywords that may trigger controversial style
    controversial_keywords = [
        'debate', 'dispute', 'controversy', 'divided', 'conflict', 'argument', 'clash',
        'disputed', 'polarizing', 'scandal', 'protest', 'criticism', 'oppose', 'lawsuit',
        'allegations', 'backlash', 'outrage', 'contentious', 'dispute', 'heated'
    ]
    
    title = article.get('title', '').lower()
    content = article.get('content', '').lower()
    
    # Check for controversial keywords in title and content
    has_controversial_content = any(keyword in title or keyword in content 
                                   for keyword in controversial_keywords)
    
    # Style selection logic based on category and content
    if has_controversial_content:
        # Prioritize controversial style if content is already controversial
        logger.info(f"Detected controversial content, using controversial style")
        return "controversial"
    elif article_category in ['technology', 'science']:
        logger.info(f"Article in {article_category} category, using informative style")
        return "informative"
    elif article_category in ['entertainment', 'lifestyle', 'sports']:
        logger.info(f"Article in {article_category} category, using conversational style")
        return "conversational"
    elif article_category in ['politics', 'business', 'world']:
        logger.info(f"Article in {article_category} category, using dramatic style")
        return "dramatic"
    else:
        logger.info(f"Using default informative style")
        return "informative"

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
    
    # Save image information
    images_path = os.path.join(TEMP_DIR, f"images_{timestamp}.json")
    with open(images_path, 'w', encoding='utf-8') as f:
        # Only save necessary information
        image_info = []
        for img in images:
            img_copy = {k: v for k, v in img.items() if k != 'path'}
            img_copy['filename'] = os.path.basename(img['path'])
            image_info.append(img_copy)
        
        json.dump(image_info, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved image information at: {images_path}")
    
    # Generate voice for script
    voice_generator = VoiceGenerator()
    audio_files = voice_generator.generate_audio_for_script(script)
    
    logger.info(f"Generated {len(audio_files)} audio files for script")
    
    # Save project information
    project_info = {
        "title": script['title'],
        "timestamp": timestamp,
        "style": selected_style,
        "article": {
            "title": selected_article['title'],
            "url": selected_article.get('url', ''),
            "source": selected_article.get('source', '')
        },
        "script": {
            "path": script_path,
            "scenes_count": len(script['scenes'])
        },
        "images": [{"type": img['type'], "path": img['path']} for img in images],
        "audio": [{"type": audio['type'], "path": audio['path']} for audio in audio_files]
    }
    
    project_path = os.path.join(TEMP_DIR, f"project_{timestamp}.json")
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(project_info, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved project information at: {project_path}")
    
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
        #output_path = video_editor.create_video(images, audio_files, script, background_music)
        #logger.info(f"Successfully created video: {output_path}")
        
        # Create output path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_filename = f"{timestamp}_{script['title'][:30].replace(' ', '_')}.mp4"
        output_path = os.path.join(OUTPUT_DIR, video_filename)

        # Get the directory where audio files are stored
        audio_dir = os.path.dirname(audio_files[0]['path']) if audio_files else None

        # Create video with correct parameter order
        output_path = video_editor.create_video(
            script=script,                 # First parameter should be the script
            media_items=images,            # Second parameter should be the media items (images)
            audio_dir=audio_dir,           # Third parameter should be the audio directory
            output_path=output_path        # Fourth parameter should be the output path
        )

        # Added completion message
        print("\n" + "="*50)
        print(f"Video successfully created!")
        print(f"Title: {script['title']}")
        print(f"Style: {selected_style} (CONTROVERSIAL MODE ENABLED)")
        print(f"Output: {output_path}")
        print("="*50 + "\n")
        
    except Exception as e:
        logger.error(f"Error creating video: {str(e)}")

if __name__ == "__main__":
    main()