# src/image_generator.py

import os
import requests
import logging
import time
import json
import random
import hashlib
import shutil
import glob
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# Import API keys and settings
from config.credentials import SERPER_API_KEY, OPENAI_API_KEY
from config.settings import TEMP_DIR, ASSETS_DIR, VIDEO_SETTINGS

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self):
        """Initializes ImageGenerator with Serper and OpenAI configurations."""
        self.serper_api_key = SERPER_API_KEY
        if not self.serper_api_key:
            logger.error("Serper API key not found in credentials. Image search will likely fail.")
            # Consider raising an error if Serper is mandatory
            # raise ValueError("Serper API key is required.")

        # --- OpenAI Configuration ---
        self.openai_api_key = OPENAI_API_KEY
        if not self.openai_api_key:
            # Warn if OpenAI key is missing, since it's required for query generation
            logger.warning("OpenAI API key not found. Search queries will use a simple fallback method.")
        self.openai_base_url = "https://api.openai.com/v1"
        self.openai_headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        # --- End OpenAI Configuration ---

        self.temp_dir = TEMP_DIR
        self.assets_dir = ASSETS_DIR
        self.width = VIDEO_SETTINGS["width"]
        self.height = VIDEO_SETTINGS["height"]

        # Serper.dev API URL
        self.serper_url = "https://google.serper.dev/images"
        self.serper_headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json"
        }

        # Create temporary image storage directory
        self.image_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(self.image_dir, exist_ok=True)

        # Create image cache directory
        self.cache_dir = os.path.join(self.temp_dir, "image_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Create assets and fonts directories if they don't exist
        os.makedirs(self.assets_dir, exist_ok=True)
        self.fonts_dir = os.path.join(self.assets_dir, "fonts")
        os.makedirs(self.fonts_dir, exist_ok=True)

        # Check for required fonts
        self._check_fonts() # Renamed from _check_and_download_fonts

    def generate_images_for_script(self, script):
        """Generates images for all scenes in a script using a multi-stage fallback mechanism.

        Args:
            script (dict): Script dictionary with keys 'title', 'scenes', 'source', 'image_url' (optional).

        Returns:
            list: A list of dictionaries containing information about the generated images.
        """
        images = []
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        # Create a more identifiable folder name based on the title
        safe_title = "".join(c if c.isalnum() else "_" for c in script['title'][:30]).rstrip('_')
        project_folder_name = f"project_{safe_title}_{timestamp}"
        project_dir = os.path.join(self.image_dir, project_folder_name)
        os.makedirs(project_dir, exist_ok=True)

        logger.info(f"Starting image generation for script: '{script['title']}' in folder: {project_folder_name}")

        # --- 1. Intro Title Card ---
        try:
            intro_image = self._create_title_card(script['title'], script.get('source', ''), project_dir)
            images.append({
                "type": "intro",
                "path": intro_image,
                "duration": VIDEO_SETTINGS["intro_duration"]
            })
        except Exception as e:
             logger.error(f"Error creating intro card: {e}", exc_info=True)
             # Optionally add a simple text fallback for intro

        # --- 2. Source Image (if available) ---
        source_image_url = script.get('image_url')
        if source_image_url:
            logger.info(f"Attempting to download source image: {source_image_url}")
            try:
                source_image_path = self._download_and_process_image(
                    source_image_url,
                    os.path.join(project_dir, "source_image.jpg")
                )
                if source_image_path:
                    images.append({
                        "type": "source",
                        "path": source_image_path,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "caption": "Source image from article" # Caption in English
                    })
                    logger.info(f"Successfully added source image: {source_image_path}")
                else:
                    logger.warning(f"Failed to download or process source image from {source_image_url}")
            except Exception as e:
                logger.error(f"Error downloading or processing source image {source_image_url}: {e}", exc_info=True)
        else:
             logger.info("No source image URL provided in the script.")

        # --- 3. Images for Each Scene ---
        for scene in script.get('scenes', []):
            scene_number = scene.get('number', 'unknown')
            scene_content = scene.get('content', '')
            scene_image_path = None
            search_query_used = "N/A" # Default value

            try:
                logger.info(f"--- Processing Scene {scene_number} ---")
                if not scene_content:
                     logger.warning(f"Scene {scene_number} has empty content. Skipping image generation for this scene.")
                     continue # Skip if no content

                # --- Step 3.1: Generate Search Query with OpenAI ---
                search_query = self._create_search_query_with_openai(scene_content, script['title'])
                search_query_used = search_query # Store the query intended for use

                # File name for the scene image
                scene_image_filename = f"scene_{scene_number}.jpg"
                target_image_path = os.path.join(project_dir, scene_image_filename)

                # --- Step 3.2: Find Image (Multi-stage fallback) ---
                try:
                    # Stage 1: Check cache or search Serper API (using OpenAI/basic query)
                    logger.info(f"Stage 1: Cache check / Serper API search (Query: '{search_query}')")
                    scene_image_path = self._get_cached_or_download_image(search_query, target_image_path)

                except Exception as e1:
                    logger.warning(f"Stage 1 failed for scene {scene_number}: {str(e1)}")

                    try:
                        # Stage 2: Try simpler search
                        logger.info(f"Stage 2: Trying simplified search with a different approach")
                        try:
                            # Create a more simplified prompt for OpenAI
                            simplified_content = ' '.join(scene_content.split()[:20])  # First 20 words only
                            simplified_query = self._create_search_query_with_openai(simplified_content, "News Story")
                            search_query_used = simplified_query  # Update the query that was actually used
                            logger.info(f"Simplified Query: '{simplified_query}'")
                        except Exception as e2:
                            # Final fallback if even the simplified OpenAI call fails
                            logger.warning(f"Simplified search also failed: {str(e2)}")
                            words = scene_content.split()[:5]  # Take first 5 words
                            simplified_query = ' '.join(words) + " news photo"
                            search_query_used = simplified_query
                            logger.info(f"Emergency fallback query: '{simplified_query}'")
                        # Don't necessarily cache this simplified query, download directly
                        scene_image_path = self._search_and_download_image(simplified_query, target_image_path)

                    except Exception as e2:
                        logger.warning(f"Stage 2 failed for scene {scene_number}: {str(e2)}")

                        try:
                            # Stage 3: Use local fallback image (assets/fallback_images)
                            logger.info(f"Stage 3: Using local fallback image")
                            scene_image_path = self._use_local_fallback_image(search_query, target_image_path) # Use original query to determine theme

                        except Exception as e3:
                            logger.warning(f"Stage 3 failed for scene {scene_number}: {str(e3)}")

                            # Stage 4: Create text-only image as last resort
                            logger.info(f"Stage 4: Creating text-only image for scene {scene_number}")
                            text_image_path = os.path.join(project_dir, f"text_scene_{scene_number}.png")
                            scene_image_path = self._create_text_only_image(
                                f"Scene {scene_number}:\n{scene_content[:150]}...", # Add scene number to text image
                                text_image_path
                            )
                            search_query_used = "Text-only fallback" # Record that this was a text fallback

                # --- Step 3.3: Add Image Info to List ---
                if scene_image_path:
                    image_info = {
                        "type": "scene",
                        "number": scene_number,
                        "path": scene_image_path,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "content": scene_content,
                        "search_query": search_query_used # Store the query that actually led to the image (or fallback type)
                    }
                    images.append(image_info)
                    logger.info(f"Added image for scene {scene_number}: {scene_image_path}")
                else:
                    # Very rare case: even text image creation failed
                    logger.error(f"Failed to create ANY image for scene {scene_number}. Skipping.")
                    continue # Skip this scene

                # Slight delay between scenes to avoid potential rate limits
                time.sleep(random.uniform(0.5, 1.5)) # Randomize delay

            except Exception as e:
                # Unexpected error during the scene processing loop
                logger.error(f"Unhandled error processing scene {scene_number}: {str(e)}", exc_info=True)
                # Create an emergency fallback image
                try:
                    emergency_path = os.path.join(project_dir, f"emergency_fallback_{scene_number}.png")
                    fallback_image = self._create_text_only_image(
                        f"Error processing scene {scene_number}:\nPlease check logs.",
                        emergency_path
                    )
                    images.append({
                        "type": "emergency_fallback",
                        "number": scene_number,
                        "path": fallback_image,
                        "duration": VIDEO_SETTINGS["image_duration"],
                        "content": scene_content,
                        "search_query": "Emergency Fallback"
                    })
                    logger.warning(f"Created emergency fallback image for scene {scene_number}")
                except Exception as fallback_err:
                     logger.critical(f"CRITICAL: Failed even to create emergency fallback image for scene {scene_number}: {fallback_err}", exc_info=True)

        # --- 4. Outro Card ---
        try:
            outro_image = self._create_outro_card(script['title'], script.get('source', ''), project_dir)
            images.append({
                "type": "outro",
                "path": outro_image,
                "duration": VIDEO_SETTINGS["outro_duration"]
            })
        except Exception as e:
            logger.error(f"Error creating outro card: {e}", exc_info=True)
            # Optionally add a simple text fallback for outro

        logger.info(f"Finished generating images. Total images/cards created: {len(images)}")

        # --- 5. Save Metadata ---
        self._save_image_info(images, script['title'], project_dir)

        return images

    def _search_and_download_image(self, query, output_path):
        """Searches for and downloads an image using the Serper.dev API for US/English results.

        Args:
            query (str): The search query.
            output_path (str): The path to save the processed image.

        Returns:
            str: The path to the successfully downloaded and processed image.

        Raises:
            Exception: If no suitable image can be found or downloaded.
        """
        if not self.serper_api_key:
            raise Exception("Serper API key is missing. Cannot search for images.")

        try:
            logger.info(f"Searching images with Serper (US/EN): '{query}'")

            # Payload for US/English search
            payload = json.dumps({
                "q": query,
                "gl": "us",  # Geo-location: United States
                "hl": "en",  # Host language: English
                "num": 20    # Request more results to increase chances of finding a good image
            })

            response = requests.post(self.serper_url, headers=self.serper_headers, data=payload, timeout=15)

            if response.status_code != 200:
                logger.error(f"Serper API error: {response.status_code}, {response.text}")
                raise Exception(f"Serper API error: {response.status_code}")

            data = response.json()
            image_results = data.get("images", [])

            if not image_results:
                logger.warning(f"No images found by Serper for query: '{query}'")
                raise Exception("No images found")

            # Define problematic domains to avoid
            blacklisted_domains = ["lookaside.fbsbx.com", "lookaside.instagram.com", "fbcdn"]
                
            # Filter and score potential images based on size and aspect ratio
            potential_images = []
            for img_data in image_results:
                # CORRECTION: Use proper Serper API property names (imageWidth/imageHeight instead of width/height)
                width = img_data.get("imageWidth", 0)
                height = img_data.get("imageHeight", 0)
                url = img_data.get("imageUrl")
                
                # Skip images without URLs
                if not url:
                    continue
                    
                # Skip known problematic domains
                if any(domain in url.lower() for domain in blacklisted_domains):
                    logger.debug(f"Skipping blacklisted domain: {url}")
                    continue
                
                # Filter out very small images if dimensions are provided
                if width != 0 and height != 0 and (width < 400 or height < 300):
                    continue

                # Calculate score even if dimensions are not provided
                score = 0.5  # Base score for all images
                
                if width > 0 and height > 0:
                    # Only calculate dimension-based score if dimensions are provided
                    ratio = width / height if height > 0 else 0
                    target_ratio = self.width / self.height
                    ratio_diff = abs(ratio - target_ratio)

                    # Calculate a score based on size and aspect ratio match
                    # Normalize size score relative to target video size (e.g., 1920x1080)
                    size_score = min((width * height) / (self.width * self.height * 1.5), 1.0)  # Favor larger images, cap at 1.0
                    # Score higher for aspect ratios closer to the target
                    ratio_score = max(0, 1.0 - ratio_diff * 2)  # Penalize deviation from target ratio
                    # Combine scores (adjust weights as needed)
                    score = (size_score * 0.6) + (ratio_score * 0.4)  # 60% size, 40% ratio
                
                # Give bonus for high-quality sources
                quality_domains = ["shutterstock", "getty", "unsplash", "pexels", "stock", "adobe"]
                if any(domain in url.lower() for domain in quality_domains):
                    score += 0.2
                    score = min(score, 1.0)  # Cap at 1.0

                potential_images.append({"url": url, "score": score, "width": width, "height": height})

            if not potential_images:
                logger.warning(f"No suitable images found after filtering for query: '{query}'")
                # Fallback: use raw results if filtering removed everything
                potential_images = [{"url": img.get("imageUrl"), "score": 0.5, "width": img.get("imageWidth", 0), "height": img.get("imageHeight", 0)}
                                    for img in image_results if img.get("imageUrl")]
                if not potential_images:
                    raise Exception("No images with URLs found even in raw results")

            # Sort images by score, highest first
            potential_images.sort(key=lambda x: x["score"], reverse=True)

            # Attempt to download the top-ranked images
            max_attempts = min(5, len(potential_images)) # Try the best 5 images
            for i in range(max_attempts):
                selected_image = potential_images[i]
                image_url = selected_image["url"]
                logger.info(f"Attempting download {i+1}/{max_attempts} (Score: {selected_image['score']:.2f}, Size: {selected_image['width']}x{selected_image['height']}): {image_url[:70]}...")

                try:
                    # Use the dedicated download/process function
                    downloaded_path = self._download_and_process_image(image_url, output_path)
                    if downloaded_path:
                        logger.info(f"Successfully downloaded and processed image {i+1}.")
                        return downloaded_path # Return immediately on success
                except Exception as download_err:
                    logger.warning(f"Failed attempt {i+1} for {image_url}: {str(download_err)}")
                    # Don't raise here; the loop will try the next image

            # If all download attempts fail
            logger.error(f"All {max_attempts} download attempts failed for query: '{query}'")
            raise Exception(f"Failed to download a suitable image after {max_attempts} attempts")

        except Exception as e:
            logger.error(f"Error during image search/download for query '{query}': {str(e)}", exc_info=True)
            raise # Re-raise the exception for fallback mechanisms to handle

    def _download_and_process_image(self, image_url, output_path):
        """Downloads, validates, and processes (resize/crop) an image from a URL.

        Args:
            image_url (str): The URL of the image.
            output_path (str): The path to save the processed image.

        Returns:
            str: The path to the successfully processed image.

        Raises:
            Exception: If downloading, validation, or processing fails.
        """
        try:
            # Use headers to mimic a browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9', # Prioritize US English
                'Referer': 'https://www.google.com/' # Common referer
            }
            # Use stream=True to check headers before downloading full content
            response = requests.get(image_url, headers=headers, timeout=20, stream=True)
            response.raise_for_status() # Raise HTTPError for bad status codes (4xx or 5xx)

            # Check Content-Type header
            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                 # Allow common image types sometimes served with different content types
                if 'webp' in content_type or 'avif' in content_type or 'octet-stream' in content_type:
                     logger.debug(f"Content-Type is '{content_type}', proceeding as image.")
                else:
                    raise Exception(f"Invalid Content-Type: {content_type}")

            # Read the image data from the response
            image_data = response.content
            if not image_data:
                 raise Exception("Downloaded image data is empty")

            # Validate and open the image using Pillow
            try:
                image = Image.open(BytesIO(image_data))
                # Verify integrity (detects some truncated files)
                # Note: verify() can be problematic with some formats, use cautiously or remove if issues arise
                # image.verify()
                # Re-open after verify/or if verify is skipped
                image = Image.open(BytesIO(image_data))
                # Convert to RGB to ensure consistency (handles transparency, palettes)
                if image.mode != 'RGB':
                     logger.debug(f"Converting image from mode {image.mode} to RGB.")
                     image = image.convert('RGB')
            except Exception as img_err:
                raise Exception(f"Invalid or corrupted image data: {str(img_err)}")

            # Check minimum dimensions after opening
            if image.width < 300 or image.height < 200:
                raise Exception(f"Image dimensions too small: {image.width}x{image.height}")

            # Resize and crop the image to fit video dimensions
            processed_image = self._resize_image(image)

            # Save the processed image as JPEG with good quality
            processed_image.save(output_path, "JPEG", quality=90)
            logger.debug(f"Image saved to: {output_path}")
            return output_path

        except requests.exceptions.RequestException as req_err:
             # Catch network-related errors
             raise Exception(f"Network error downloading {image_url}: {str(req_err)}")
        except Exception as e:
             # Catch any other error during the process
             # logger.error(f"Error processing image {image_url}: {str(e)}", exc_info=True) # Log details if needed
             raise Exception(f"Failed to download/process image {image_url}: {str(e)}")


    # These validation helpers are less critical now as validation is integrated into download/process
    # def _validate_image(self, image_data): ...
    # def _is_good_image_size(self, image_data): ...

    def _get_cached_or_download_image(self, query, output_path):
        """Checks cache first; if not found or invalid, searches/downloads and caches."""
        query_hash = hashlib.md5(query.encode()).hexdigest()
        cache_filename = f"{query_hash}.jpg"
        cache_path = os.path.join(self.cache_dir, cache_filename)

        if os.path.exists(cache_path):
            # Basic check for validity (e.g., file size > 0 bytes or a threshold)
            try:
                if os.path.getsize(cache_path) > 1024: # Check if file size is > 1KB
                    logger.info(f"Using cached image for query: '{query}'")
                    shutil.copy(cache_path, output_path)
                    return output_path
                else:
                    logger.warning(f"Invalid cache file found (size too small): {cache_path}. Will re-download.")
                    os.remove(cache_path) # Remove the invalid cache file
            except OSError as e:
                 logger.warning(f"Error accessing or removing cache file {cache_path}: {e}. Will re-download.")
            except Exception as e:
                 logger.warning(f"Error copying from cache {cache_path}: {e}. Will re-download.")

        # If not in cache or cache was invalid, proceed to download
        logger.info(f"Image not in cache or cache invalid for query: '{query}'. Searching and downloading.")
        try:
            downloaded_path = self._search_and_download_image(query, output_path)

            # Save the successfully downloaded image to cache
            try:
                shutil.copy(downloaded_path, cache_path)
                logger.info(f"Saved downloaded image to cache: {cache_path}")
            except Exception as e:
                logger.warning(f"Failed to save image to cache {cache_path}: {e}")

            return downloaded_path
        except Exception as e:
            # Log the error but re-raise it so the calling function knows the download failed
            logger.error(f"Failed to download image for caching (query: '{query}'): {str(e)}")
            raise # Re-raise exception for further fallback handling

    def _use_local_fallback_image(self, query, output_path):
        """Uses a fallback image from the assets/fallback_images directory based on themes."""
        fallback_base_dir = os.path.join(self.assets_dir, "fallback_images")
        if not os.path.exists(fallback_base_dir) or not os.listdir(fallback_base_dir):
            os.makedirs(fallback_base_dir, exist_ok=True)
            logger.warning(f"Fallback image directory is empty or missing: {fallback_base_dir}")
            logger.warning("Please add themed subdirectories with images (e.g., 'general_news', 'technology') to use this feature.")
            raise Exception("Local fallback directory is empty.")

        # Define English themes and associated keywords
        themes = {
            "general_news": ["news", "report", "update", "breaking", "story"],
            "technology": ["tech", "technology", "computer", "phone", "ai", "software", "internet"],
            "business": ["business", "economy", "finance", "market", "stock", "company", "money"],
            "politics": ["politics", "government", "election", "senate", "congress", "white house", "law"],
            "sports": ["sports", "game", "team", "player", "football", "basketball", "baseball"],
            "entertainment": ["entertainment", "movie", "music", "celebrity", "show", "award"],
            "health": ["health", "medical", "hospital", "doctor", "disease", "virus", "medicine"],
            "disaster": ["disaster", "weather", "storm", "fire", "flood", "earthquake", "emergency", "accident"],
            "science": ["science", "research", "space", "nature", "discovery"],
            "world_news": ["world", "international", "global", "country", "war", "diplomacy"]
        }
        best_theme = "general_news" # Default theme
        best_score = 0
        query_lower = query.lower()

        # Simple keyword matching to determine the best theme
        for theme, keywords in themes.items():
            score = sum(1 for keyword in keywords if keyword in query_lower)
            if score > best_score:
                best_score = score
                best_theme = theme
            # Prioritize if the theme name itself is in the query
            if theme.replace("_", " ") in query_lower and score == 0:
                 best_theme = theme
                 break

        theme_dir = os.path.join(fallback_base_dir, best_theme)
        logger.info(f"Selected fallback theme: {best_theme}")

        # If the specific theme directory doesn't exist or is empty, use the base fallback directory
        if not os.path.exists(theme_dir) or not os.listdir(theme_dir):
            logger.warning(f"Theme directory '{theme_dir}' not found or empty. Using base fallback directory: {fallback_base_dir}")
            theme_dir = fallback_base_dir

        # Get a list of image files from the selected directory
        image_files = glob.glob(os.path.join(theme_dir, "*.jpg")) + \
                      glob.glob(os.path.join(theme_dir, "*.jpeg")) + \
                      glob.glob(os.path.join(theme_dir, "*.png"))

        if not image_files:
            logger.error(f"No fallback images found in '{theme_dir}'. Cannot use local fallback.")
            raise Exception(f"No images in fallback directory: {theme_dir}")

        # Select a random image from the list
        selected_image_path = random.choice(image_files)
        logger.info(f"Using local fallback image: {selected_image_path}")

        # Copy and process the selected fallback image
        try:
            img = Image.open(selected_image_path)
            if img.mode != 'RGB':
                 img = img.convert('RGB') # Ensure RGB format
            processed_img = self._resize_image(img) # Resize/crop to fit video dimensions
            processed_img.save(output_path, "JPEG", quality=85) # Save as JPEG
            return output_path
        except Exception as e:
            logger.error(f"Error processing local fallback image {selected_image_path}: {e}", exc_info=True)
            raise Exception(f"Failed to process fallback image {selected_image_path}")


    def _create_text_only_image(self, text_content, output_path):
        """Creates an image containing only the provided text."""
        try:
            # Generate a gradient background based on a hash of the text content
            text_hash = hashlib.md5(text_content.encode()).hexdigest()
            r1, g1, b1 = int(text_hash[0:2], 16), int(text_hash[2:4], 16), int(text_hash[4:6], 16)
            r2, g2, b2 = int(text_hash[6:8], 16), int(text_hash[8:10], 16), int(text_hash[10:12], 16)

            # Ensure colors are not too light or too dark for readability
            r1, g1, b1 = max(30, r1), max(30, g1), max(30, b1)
            r2, g2, b2 = min(220, r2), min(220, g2), min(220, b2)

            img = Image.new('RGB', (self.width, self.height))
            draw = ImageDraw.Draw(img)

            # Draw the gradient background
            for y in range(self.height):
                ratio = y / self.height
                r = int(r1 + (r2 - r1) * ratio)
                g = int(g1 + (g2 - g1) * ratio)
                b = int(b1 + (b2 - b1) * ratio)
                draw.line([(0, y), (self.width, y)], fill=(r, g, b))

            # Select font and size (adjust size based on text length)
            font_size = 45 if len(text_content) < 100 else 40
            font = self._get_font(size=font_size)
            if not font:
                 raise Exception("Cannot load any font for text image generation")

            # Wrap the text to fit within margins
            margin = 80
            wrapped_text = self._wrap_text(text_content, font, self.width - 2 * margin)

            # Calculate total text height and starting position for vertical centering
            line_height = font_size * 1.3 # Estimate line height based on font size
            total_text_height = len(wrapped_text) * line_height
            start_y = (self.height - total_text_height) / 2

            # Define text and outline colors
            text_color = (255, 255, 255) # White text
            outline_color = (0, 0, 0)    # Black outline

            # Draw each line of text with a slight outline for better readability
            for i, line in enumerate(wrapped_text):
                # Calculate x position for horizontal centering
                try:
                    # Use textbbox for more accurate width calculation (Pillow >= 8.0.0)
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_width = bbox[2] - bbox[0]
                except AttributeError:
                     # Fallback for older Pillow versions or fonts without bbox support
                    try:
                         text_width, _ = font.getsize(line)
                    except AttributeError:
                         # Rough estimation if getsize also fails
                         text_width = len(line) * (font_size * 0.6)

                x = (self.width - text_width) / 2
                y = start_y + i * line_height

                # Draw outline (draw text multiple times with slight offset)
                outline_strength = 1 # Adjust for thicker/thinner outline
                for dx in range(-outline_strength, outline_strength + 1):
                    for dy in range(-outline_strength, outline_strength + 1):
                        if dx != 0 or dy != 0: # Don't draw center for outline
                            draw.text((x + dx, y + dy), line, font=font, fill=outline_color)
                # Draw the main text on top
                draw.text((x, y), line, font=font, fill=text_color)

            img.save(output_path)
            logger.info(f"Created text-only image: {output_path}")
            return output_path
        except Exception as e:
             logger.error(f"Failed to create text-only image: {e}", exc_info=True)
             raise # Re-raise the exception

    def _create_title_card(self, title, source, project_dir):
        """Creates the introductory title card image."""
        output_path = os.path.join(project_dir, "intro_title.png")
        try:
            img = Image.new('RGB', (self.width, self.height), color=(20, 40, 80)) # Dark blue background
            draw = ImageDraw.Draw(img)
            title_font = self._get_font(size=65) # Larger font for title
            source_font = self._get_font(size=35) # Smaller font for source
            if not title_font or not source_font:
                raise Exception("Cannot load fonts required for title card")

            margin = 100
            # Wrap and draw the title, centered vertically and horizontally
            title_wrapped = self._wrap_text(title, title_font, self.width - 2 * margin)
            title_line_height = 75 # Adjust line spacing for title font
            total_title_height = len(title_wrapped) * title_line_height
            # Adjust starting y-position to center the block of text
            title_y_start = (self.height - total_title_height) / 2 - (title_line_height / 4) # Slightly higher than pure center

            for i, line in enumerate(title_wrapped):
                bbox = draw.textbbox((0, 0), line, font=title_font)
                text_width = bbox[2] - bbox[0]
                x = (self.width - text_width) / 2
                y = title_y_start + i * title_line_height
                # Draw slight shadow/outline
                draw.text((x+1, y+1), line, font=title_font, fill=(0,0,0, 128)) # Semi-transparent black
                # Draw main text
                draw.text((x, y), line, font=title_font, fill=(255, 255, 255)) # White text

            # Draw the source information at the bottom, if available
            if source:
                source_text = f"Source: {source}"
                bbox = draw.textbbox((0,0), source_text, font=source_font)
                source_width = bbox[2] - bbox[0]
                source_x = (self.width - source_width) / 2
                source_y = self.height - 80 # Position near the bottom
                # Draw slight shadow/outline
                draw.text((source_x+1, source_y+1), source_text, font=source_font, fill=(0,0,0,100))
                # Draw main source text
                draw.text((source_x, source_y), source_text, font=source_font, fill=(200, 200, 200)) # Light gray text

            img.save(output_path)
            logger.info(f"Created intro title card: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to create intro card: {e}", exc_info=True)
            # Fallback: Create a simple text image if card generation fails
            return self._create_text_only_image(f"Intro:\n{title[:100]}...", output_path)


    def _create_outro_card(self, title, source, project_dir):
        """Creates the concluding outro card image."""
        output_path = os.path.join(project_dir, "outro.png")
        try:
            img = Image.new('RGB', (self.width, self.height), color=(60, 20, 80)) # Dark purple background
            draw = ImageDraw.Draw(img)
            main_font = self._get_font(size=60) # Font for main message
            sub_font = self._get_font(size=40)  # Font for title recap
            if not main_font or not sub_font:
                raise Exception("Cannot load fonts required for outro card")

            # Draw "Thanks for watching" message, centered
            thank_you_text = "Thanks for watching"
            bbox = draw.textbbox((0,0), thank_you_text, font=main_font)
            text_width = bbox[2] - bbox[0]
            x = (self.width - text_width) / 2
            y = self.height / 2 - 100 # Position slightly above center
             # Draw slight shadow/outline
            draw.text((x+1, y+1), thank_you_text, font=main_font, fill=(0,0,0, 128))
            # Draw main text
            draw.text((x, y), thank_you_text, font=main_font, fill=(255, 255, 255)) # White text

            # Draw a shortened version of the title below the main message
            short_title = title[:80] + ('...' if len(title) > 80 else '') # Truncate if too long
            title_wrapped = self._wrap_text(short_title, sub_font, self.width - 200) # Wrap shortened title
            line_height = 50 # Line spacing for title recap
            start_y = self.height / 2 + 20 # Position below "Thanks for watching"

            for i, line in enumerate(title_wrapped):
                bbox = draw.textbbox((0,0), line, font=sub_font)
                text_width = bbox[2] - bbox[0]
                x = (self.width - text_width) / 2
                y = start_y + i * line_height
                # Draw slight shadow/outline
                draw.text((x+1, y+1), line, font=sub_font, fill=(0,0,0, 100))
                 # Draw main title recap text
                draw.text((x, y), line, font=sub_font, fill=(200, 200, 200)) # Light gray text

            img.save(output_path)
            logger.info(f"Created outro card: {output_path}")
            return output_path
        except Exception as e:
             logger.error(f"Failed to create outro card: {e}", exc_info=True)
             # Fallback: Create a simple text image
             return self._create_text_only_image("Thanks for watching!", output_path)

    def _resize_image(self, image):
        """
        Resizes and crops an image to fit the target video dimensions.
        For images significantly smaller than the target size, preserves original size
        and places it on a background canvas.
        """
        try:
            target_ratio = self.width / self.height
            img_ratio = image.width / image.height
            
            # Define thresholds
            # Only resize if image dimensions are at least this percentage of target dimensions
            RESIZE_THRESHOLD = 0.5  # 50% of target dimensions
            # Minimum width/height to consider for resize operation
            MIN_WIDTH_FOR_RESIZE = int(self.width * RESIZE_THRESHOLD)
            MIN_HEIGHT_FOR_RESIZE = int(self.height * RESIZE_THRESHOLD)
            
            # Check if image is too small to resize without significant quality loss
            is_too_small = image.width < MIN_WIDTH_FOR_RESIZE or image.height < MIN_HEIGHT_FOR_RESIZE
            
            # If image is too small, place it on a background without resizing
            if is_too_small:
                logger.debug(f"Image too small ({image.width}x{image.height}) - preserving original size")
                
                # Create a blank canvas with target dimensions
                # Use a dark gray background for better visual integration
                background = Image.new('RGB', (self.width, self.height), color=(30, 30, 30))
                
                # Calculate position to center the image on the background
                x_pos = (self.width - image.width) // 2
                y_pos = (self.height - image.height) // 2
                
                # Paste the original image onto the background
                background.paste(image, (x_pos, y_pos))
                return background
                
            # For images close enough in size to the target, proceed with regular resize logic
            logger.debug(f"Image size suitable for resize ({image.width}x{image.height}) to target ({self.width}x{self.height})")
            
            # If aspect ratio is already close enough, just resize
            if abs(img_ratio - target_ratio) < 0.01:
                logger.debug(f"Resizing image with matching aspect ratio")
                return image.resize((self.width, self.height), Image.Resampling.LANCZOS)

            logger.debug(f"Cropping and resizing image to fit target ratio {target_ratio:.2f}")
            if img_ratio > target_ratio:
                # Image is wider than target (landscapeish) -> crop sides
                new_width = int(image.height * target_ratio)
                left = (image.width - new_width) // 2
                right = left + new_width
                crop_box = (left, 0, right, image.height)
                logger.debug(f"Cropping box (sides): {crop_box}")
            else:
                # Image is taller than target (portraitish) -> crop top/bottom
                new_height = int(image.width / target_ratio)
                top = (image.height - new_height) // 2
                # Simple center crop for top/bottom
                bottom = top + new_height
                crop_box = (0, top, image.width, bottom)
                logger.debug(f"Cropping box (top/bottom): {crop_box}")

            cropped_image = image.crop(crop_box)
            # Resize the cropped image to the final target dimensions
            return cropped_image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        except Exception as e:
            logger.error(f"Error resizing image: {e}", exc_info=True)
            # Re-raise the exception to signal failure in resizing
            raise

    def _create_search_query_with_openai(self, scene_content, title):
        """Uses OpenAI to create an optimized search query based on scene content and title.
        
        Args:
            scene_content (str): The content of the current scene.
            title (str): The title of the video.
            
        Returns:
            str: The generated search query, or a fallback query if OpenAI fails.
        """
        if not self.openai_api_key:
            logger.warning("OpenAI API key is required but missing. Using default query.")
            # Simple fallback when API key is missing
            words = scene_content.split()[:5]  # Take first 5 words
            simple_query = ' '.join(words) + " news photo"
            return simple_query[:150]  # Enforce max length

        try:
            # Prepare prompt for OpenAI
            prompt = f"""
            Create a specific, detailed image search query for the scene from a news video described below.
            The query should be optimized to find high-quality, relevant stock photos or news images.
            The query should be in English, 5-7 words, and focus on the visual elements of the scene.
            Do NOT include quotes or hashtags in your response.
            
            Video Title: "{title}"
            Scene Content: "{scene_content}"
            
            Output ONLY the search query text with no additional explanations, prefixes or formatting.
            """

            url = f"{self.openai_base_url}/chat/completions"
            payload = {
                "model": "gpt-4o-mini", # Or "gpt-3.5-turbo" for cost savings
                "messages": [
                    {"role": "system", "content": "You are an expert at creating optimal image search queries for news content."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3, # Lower temperature for more consistent results
                "max_tokens": 30    # Limit tokens for concise query
            }

            logger.debug(f"Calling OpenAI for search query generation: {scene_content[:100]}...")
            response = requests.post(url, headers=self.openai_headers, json=payload, timeout=15)

            if response.status_code == 200:
                data = response.json()
                if 'choices' in data and data['choices']:
                    query = data['choices'][0]['message']['content'].strip()
                    # Clean up the result
                    query = query.replace('"', '').replace("'", '').replace('#', '').strip()
                    
                    # Validate the query
                    if query and len(query) > 3 and len(query) < 100:
                        logger.info(f"OpenAI generated search query: '{query}'")
                        
                        # Add a suffix for image search if needed
                        if not any(word in query.lower() for word in ["photo", "image", "picture"]):
                            suffix = random.choice(["photo", "image"])
                            #query = f"{query} {suffix}"
                            query = f"{query}"
                        
                        return query[:150]  # Enforce max length
                    else:
                        logger.warning(f"OpenAI returned invalid query: '{query}'. Falling back to basic method.")
                else:
                    logger.error(f"OpenAI API response missing choices: {data}")
            else:
                logger.error(f"OpenAI API error for query generation: {response.status_code}, {response.text}")

        except requests.exceptions.Timeout:
            logger.error("OpenAI API call for query generation timed out.")
        except Exception as e:
            logger.error(f"Error calling OpenAI API for query generation: {str(e)}", exc_info=True)

        # Super simple fallback if OpenAI completely fails
        words = scene_content.split()[:5]  # Take first 5 words
        return ' '.join(words) + " news photo hd"

    def _wrap_text(self, text, font, max_width):
        """Wraps text into multiple lines to fit within a maximum width."""
        if not text: return []
        if not font: return [text] # Return original if font is missing

        lines = []
        words = text.split()
        if not words: return []

        current_line = words[0]
        for word in words[1:]:
            test_line = f"{current_line} {word}"
            try:
                # Use textbbox for accurate width calculation (Pillow >= 8.0.0)
                # Need a dummy draw object to use textbbox
                # This is slightly inefficient but required by the API
                if hasattr(ImageDraw.Draw(Image.new('RGB', (1,1))), 'textbbox'):
                    bbox = ImageDraw.Draw(Image.new('RGB', (1,1))).textbbox((0,0), test_line, font=font)
                    line_width = bbox[2] - bbox[0]
                # Fallback to getsize (older Pillow)
                elif hasattr(font, 'getsize'):
                    line_width, _ = font.getsize(test_line)
                else:
                    # Very rough estimate if font object lacks size methods
                    font_size_approx = 20 # Guess a size if font.size is unavailable
                    if hasattr(font, 'size'): font_size_approx = font.size
                    line_width = len(test_line) * (font_size_approx * 0.6)
            except Exception as e:
                 # Fallback estimation on error
                 logger.warning(f"Could not determine text width accurately for wrapping: {e}")
                 line_width = len(test_line) * 10 # Simple character count based estimation

            if line_width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word

        lines.append(current_line) # Add the last line
        return lines

    def _check_fonts(self):
        """Checks for the presence of a preferred font."""
        # Only checks and warns, does not download
        preferred_font = "Roboto-Bold.ttf" # Or your preferred font file name
        font_path = os.path.join(self.fonts_dir, preferred_font)

        if not os.path.exists(font_path):
            logger.warning(f"Preferred font '{preferred_font}' not found in '{self.fonts_dir}'.")
            logger.warning(f"Please download '{preferred_font}' (or another TTF/OTF font) and place it in the '{self.fonts_dir}' directory for best results.")
            logger.warning("The script will attempt to use system fonts or a default font, which might affect text appearance.")
        else:
             logger.info(f"Preferred font '{preferred_font}' found in '{self.fonts_dir}'.")


    def _get_font(self, size=40):
        """Gets a font object, prioritizing preferred, then system, then default."""
        preferred_font_name = "Roboto-Bold.ttf" # Your most preferred font
        preferred_font_path = os.path.join(self.fonts_dir, preferred_font_name)

        # 1. Try the preferred font from the assets directory
        if os.path.exists(preferred_font_path):
            try:
                logger.debug(f"Loading preferred font: {preferred_font_path} with size {size}")
                return ImageFont.truetype(preferred_font_path, size)
            except Exception as e:
                logger.warning(f"Could not load preferred font {preferred_font_path}: {e}")

        # 2. Try common system fonts (names or file names)
        system_fonts = [
            # Windows common
            'arial.ttf', 'arialbd.ttf', 'tahoma.ttf', 'tahomabd.ttf', 'verdana.ttf', 'verdanab.ttf', 'segoeui.ttf', 'seguisb.ttf', 'times.ttf', 'timesbd.ttf',
            # MacOS common
            'Arial.ttf', 'Helvetica.ttc', 'HelveticaNeue.ttc', 'Times New Roman',
            # Linux common (often available)
            'DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Regular.ttf', 'LiberationSans-Bold.ttf',
            'NotoSans-Regular.ttf', 'NotoSans-Bold.ttf' # Google Noto fonts are often available
        ]
        logger.debug(f"Preferred font not found or failed to load. Trying system fonts...")
        for font_attempt in system_fonts:
            try:
                # ImageFont.truetype can often find system fonts by name/filename
                logger.debug(f"Attempting to load system font '{font_attempt}' with size {size}")
                return ImageFont.truetype(font_attempt, size)
            except IOError: # Common error if font file is not found
                logger.debug(f"System font '{font_attempt}' not found.")
                continue
            except Exception as e: # Other errors (e.g., corrupted font file)
                logger.debug(f"Error trying to load system font '{font_attempt}': {e}")
                continue

        # 3. Fallback to Pillow's built-in default font
        logger.warning(f"No suitable preferred or system font found. Using Pillow's default font. Text appearance might be basic or lack support for some characters.")
        try:
            # Try loading with size argument (Pillow >= 9.0.0)
            return ImageFont.load_default(size=size)
        except TypeError:
             # Fallback for older Pillow versions
            return ImageFont.load_default()
        except Exception as e:
            # If even the default font fails (very unlikely)
            logger.error(f"CRITICAL: Failed to load even the default Pillow font: {e}")
            return None # Worst case scenario

    def _save_image_info(self, images, title, project_dir):
        """Saves detailed metadata about the generated images to a JSON file."""
        if not images:
             logger.warning("No images were generated, skipping image_info.json creation.")
             return

        image_metadata = []
        for img in images:
            img_copy = img.copy()
            # Create a relative path from the project directory base
            try:
                 # Example: project_dir = /path/to/temp/images/project_xyz
                 # img['path'] = /path/to/temp/images/project_xyz/scene_1.jpg
                 # We want to store 'scene_1.jpg'
                 rel_path = os.path.relpath(img['path'], project_dir)
                 img_copy['relative_path'] = rel_path.replace('\\', '/') # Ensure forward slashes
            except ValueError: # Handles cases like different drives on Windows
                 img_copy['relative_path'] = os.path.basename(img['path']) # Fallback to just filename

            # Optionally remove fields not needed in the JSON file
            if 'path' in img_copy: del img_copy['path'] # Remove absolute path if not needed

            image_metadata.append(img_copy)

        # Structure for the JSON output
        output_data = {
            'project_title': title,
            'creation_timestamp': time.strftime("%Y-%m-%d %H:%M:%S %Z"), # Add timezone info
            'project_folder': os.path.basename(project_dir),
            'total_items': len(image_metadata), # Renamed from total_images
            'video_dimensions': f"{self.width}x{self.height}",
            'items': image_metadata # Renamed from images for clarity (includes cards)
        }

        output_file = os.path.join(project_dir, "image_info.json")

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                # Use ensure_ascii=False for potential non-ASCII chars in content/title
                json.dump(output_data, f, ensure_ascii=False, indent=4)
            logger.info(f"Saved image metadata to: {output_file}")
        except Exception as e:
            logger.error(f"Failed to save image metadata to {output_file}: {e}", exc_info=True)


# --- Test Block ---
if __name__ == "__main__":
    print("--- Running ImageGenerator Test (English/US) ---")

    # Example English script relevant to a US audience
    test_script = {
        'title': 'Federal Reserve Announces Interest Rate Hike Amid Inflation Concerns',
        'full_script': """#SCENE 1#
        The U.S. Federal Reserve has announced another significant interest rate hike today as it continues its battle against persistent inflation.
        #SCENE 2#
        The central bank raised its benchmark federal funds rate by 75 basis points, marking the fourth consecutive increase of this magnitude.
        #SCENE 3#
        Fed Chair Jerome Powell stated that restoring price stability is essential, even if it means a period of slower economic growth and potential job losses. Stock markets reacted negatively to the news.
        #SCENE 4#
        Higher borrowing costs resulting from the rate hikes are expected to impact mortgages, car loans, and credit card interest rates for consumers across the country.
        #SCENE 5#
        Analysts predict further rate increases may be necessary in the coming months if inflation does not show clear signs of receding towards the Fed's 2% target.
        """,
        'source': 'Associated Press (AP)',
        'image_url': None, # Set to a valid URL to test source image download, or None/invalid to test without it
        'scenes': [
            {
                'number': 1,
                'content': 'The U.S. Federal Reserve has announced another significant interest rate hike today as it continues its battle against persistent inflation.'
            },
            {
                'number': 2,
                'content': 'The central bank raised its benchmark federal funds rate by 75 basis points, marking the fourth consecutive increase of this magnitude.'
            },
             {
                'number': 3,
                'content': 'Fed Chair Jerome Powell stated that restoring price stability is essential, even if it means slower economic growth. Stock markets reacted negatively.'
            },
            {
                'number': 4,
                'content': 'Higher borrowing costs will impact mortgages, car loans, and credit card interest rates for consumers.'
            },
            { # Scene for testing fallback
                 'number': 5,
                 'content': 'This is an ongoing economic situation.'
            }
        ]
    }

    # --- CHECK API KEYS ---
    if not OPENAI_API_KEY:
        print("\n*** WARNING: OPENAI_API_KEY is not configured. OpenAI keyword extraction will be skipped. ***\n")
    if not SERPER_API_KEY:
         print("\n*** WARNING: SERPER_API_KEY is not configured. Image search via Serper will fail. Ensure fallback images exist or expect text-only images. ***\n")
    # ---

    start_time = time.time()
    try:
        print("Initializing ImageGenerator...")
        generator = ImageGenerator()
        print("Generating images for the test script...")
        images_list = generator.generate_images_for_script(test_script)

        print("\n--- Image Generation Results ---")
        if images_list:
            print(f"Successfully generated {len(images_list)} images/cards.")
            project_dir = None
            for img_info in images_list:
                # Determine the base directory from the first valid path
                if not project_dir and 'path' in img_info and img_info['path']:
                     project_dir = os.path.dirname(img_info['path'])

                type_info = f"Scene {img_info['number']}" if img_info['type'] == 'scene' else img_info['type'].upper()
                query_info = f" (Query/Info: '{img_info.get('search_query', 'N/A')}')" if 'search_query' in img_info else ""
                path_info = img_info.get('path', 'Path missing')
                # Display relative path if project_dir is known
                display_path = os.path.relpath(path_info, os.path.dirname(project_dir)) if project_dir and path_info else path_info
                print(f"- {type_info}: {display_path}{query_info}")

            if project_dir:
                 print(f"\nProject files saved in directory: {project_dir}")
                 info_file = os.path.join(project_dir, "image_info.json")
                 if os.path.exists(info_file):
                      print(f"Metadata saved in: {os.path.basename(project_dir)}/image_info.json")
                 else:
                      print("Metadata file (image_info.json) was not created.")
            else:
                 print("\nCould not determine project directory (no valid image paths found).")


        else:
            print("Image generation process returned an empty list or failed.")

    except Exception as e:
        print(f"\n--- An error occurred during the test ---")
        # Log the full traceback for debugging
        logging.exception("Test execution failed")
        print(f"Error details: {str(e)}")

    end_time = time.time()
    print(f"\n--- Test finished in {end_time - start_time:.2f} seconds ---")