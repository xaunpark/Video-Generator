#!/usr/bin/env python3
"""
Test script to analyze and fix issues with Serper API image search.
This script will:
1. Examine the raw Serper API response structure
2. Test alternative image scoring methods
3. Improve image filtering logic
"""

import os
import sys
import json
import requests
import logging
import time
import random
from PIL import Image
from io import BytesIO

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("serper_test")

# You need to set your actual API key here or as environment variable
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "your_api_key_here")

class SerperImageSearchTester:
    def __init__(self):
        """Initialize the tester with Serper API configuration."""
        self.serper_api_key = SERPER_API_KEY
        self.serper_url = "https://google.serper.dev/images"
        self.serper_headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json"
        }
        
        # Create temp directory for downloaded images
        self.temp_dir = os.path.join(os.getcwd(), "temp_test_images")
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Target video dimensions for scoring
        self.width = 1920
        self.height = 1080

    def test_serper_api_response(self, query="technology news"):
        """Test the Serper API response and print its structure."""
        logger.info(f"Testing Serper API with query: '{query}'")
        
        try:
            # Payload for US/English search
            payload = json.dumps({
                "q": query,
                "gl": "us",  # Geo-location: United States
                "hl": "en",  # Host language: English
                "num": 10    # Number of results
            })
            
            response = requests.post(self.serper_url, headers=self.serper_headers, data=payload, timeout=15)
            
            if response.status_code != 200:
                logger.error(f"Serper API error: {response.status_code}, {response.text}")
                return None
                
            data = response.json()
            
            # Print the full response structure
            logger.info("=== FULL API RESPONSE STRUCTURE ===")
            print(json.dumps(data, indent=2))
            
            # Analyze the images array
            image_results = data.get("images", [])
            logger.info(f"Number of image results: {len(image_results)}")
            
            if not image_results:
                logger.warning("No images found in response.")
                return None
                
            # Check if width/height info exists in the results
            has_dimensions = False
            sample_image = None
            
            for i, img in enumerate(image_results[:5]):  # Check first 5 images
                logger.info(f"Image {i+1} data:")
                print(json.dumps(img, indent=2))
                
                width = img.get("width")
                height = img.get("height")
                
                if width is not None and height is not None and width > 0 and height > 0:
                    has_dimensions = True
                    sample_image = img
                    logger.info(f"Found dimensions in image {i+1}: {width}x{height}")
                    break
            
            if not has_dimensions:
                logger.warning("No valid dimension information found in any image result!")
                logger.info("Will need to implement alternative scoring methods.")
            else:
                logger.info("Dimension information is available in at least some results.")
                logger.info(f"Sample image with dimensions: {sample_image.get('width')}x{sample_image.get('height')}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error testing Serper API: {str(e)}", exc_info=True)
            return None

    def test_improved_scoring(self, data):
        """Test improved scoring methods that don't rely on API-provided dimensions."""
        if not data or "images" not in data:
            logger.error("No valid data to test improved scoring.")
            return
        
        image_results = data.get("images", [])
        logger.info(f"Testing improved scoring on {len(image_results)} images")
        
        potential_images = []
        
        # Original scoring method for comparison (if dimensions exist)
        for i, img in enumerate(image_results):
            width = img.get("width", 0)
            height = img.get("height", 0)
            url = img.get("imageUrl")
            
            if not url:
                continue
                
            if width > 0 and height > 0:
                ratio = width / height
                target_ratio = self.width / self.height
                ratio_diff = abs(ratio - target_ratio)
                
                # Original scoring
                size_score = min((width * height) / (self.width * self.height * 1.5), 1.0)
                ratio_score = max(0, 1.0 - ratio_diff * 2)
                original_score = (size_score * 0.6) + (ratio_score * 0.4)
                
                logger.info(f"Image {i+1} - Original scoring: {original_score:.2f} ({width}x{height})")
            else:
                logger.info(f"Image {i+1} - Missing dimensions, original scoring not possible")
            
            # New scoring method 1: Position-based priority
            # Assumption: Serper returns most relevant images first
            position_score = max(0.3, 1.0 - (i * 0.05))  # Linearly decreasing score based on position
            
            # New scoring method 2: Link quality heuristics
            link_score = 0.5  # Default score
            if "stock" in url.lower():
                link_score += 0.2  # Stock photos likely to be higher quality
            if any(domain in url.lower() for domain in ["unsplash", "pexels", "pixabay", "shutterstock"]):
                link_score += 0.3  # Known image sites with good quality
            if any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png"]):
                link_score += 0.2  # Direct image links often better
            link_score = min(link_score, 1.0)  # Cap at 1.0
            
            # Combined alternative score
            alternative_score = (position_score * 0.6) + (link_score * 0.4)
            
            logger.info(f"Image {i+1} - Alternative scoring: {alternative_score:.2f} (Position: {position_score:.2f}, Link: {link_score:.2f})")
            
            potential_images.append({
                "index": i,
                "url": url,
                "alternative_score": alternative_score,
                "width": width,
                "height": height
            })
        
        # Sort by alternative score
        potential_images.sort(key=lambda x: x["alternative_score"], reverse=True)
        
        # Test downloading and checking actual dimensions for top 3 images
        for i, img_data in enumerate(potential_images[:3]):
            logger.info(f"Testing download of image {i+1}/{3} (Score: {img_data['alternative_score']:.2f})")
            test_path = os.path.join(self.temp_dir, f"test_image_{i+1}.jpg")
            
            try:
                actual_width, actual_height = self._test_download_image(img_data["url"], test_path)
                
                if actual_width and actual_height:
                    logger.info(f"Actual dimensions: {actual_width}x{actual_height} (API reported: {img_data['width']}x{img_data['height']})")
                    
                    # Final score incorporating actual dimensions
                    actual_ratio = actual_width / actual_height if actual_height > 0 else 0
                    target_ratio = self.width / self.height
                    ratio_diff = abs(actual_ratio - target_ratio)
                    
                    actual_size_score = min((actual_width * actual_height) / (self.width * self.height * 1.5), 1.0)
                    actual_ratio_score = max(0, 1.0 - ratio_diff * 2)
                    position_score = img_data["alternative_score"]
                    
                    # Combined final score with actual dimensions
                    final_score = (actual_size_score * 0.4) + (actual_ratio_score * 0.3) + (position_score * 0.3)
                    
                    logger.info(f"Final score with actual dimensions: {final_score:.2f}")
            except Exception as e:
                logger.warning(f"Failed to download or process image: {str(e)}")

    def _test_download_image(self, image_url, output_path):
        """Test downloading an image and return its actual dimensions."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.google.com/'
            }
            
            response = requests.get(image_url, headers=headers, timeout=20)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/') and not any(format in content_type for format in ['webp', 'avif', 'octet-stream']):
                logger.warning(f"Invalid Content-Type: {content_type}")
                return None, None
            
            image_data = response.content
            if not image_data:
                logger.warning("Downloaded image data is empty")
                return None, None
            
            image = Image.open(BytesIO(image_data))
            
            # Convert to RGB to ensure consistency
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Get actual dimensions
            actual_width, actual_height = image.size
            
            # Save the image for verification
            image.save(output_path, "JPEG", quality=90)
            logger.info(f"Image saved to: {output_path}")
            
            return actual_width, actual_height
            
        except Exception as e:
            logger.warning(f"Error downloading/processing image: {str(e)}")
            return None, None

    def propose_fixes(self):
        """Propose code fixes based on test results."""
        logger.info("\n=== PROPOSED MODIFICATIONS TO ImageGenerator CLASS ===\n")
        
        # 1. Modification for _search_and_download_image method
        logger.info("1. Modified _search_and_download_image method:")
        print("""
def _search_and_download_image(self, query, output_path):
    """Searches for and downloads an image using the Serper.dev API for US/English results."""
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

        # Score and rank images using an improved approach
        potential_images = []
        for i, img_data in enumerate(image_results):
            url = img_data.get("imageUrl")
            if not url:
                continue

            # Get dimensions if available, but don't rely on them
            width = img_data.get("width", 0)
            height = img_data.get("height", 0)
            
            # Score based on position (earlier = better) - Serper typically returns better images first
            position_score = max(0.3, 1.0 - (i * 0.05))
            
            # Score based on URL quality heuristics
            link_score = 0.5  # Default score
            if "stock" in url.lower():
                link_score += 0.2  # Stock photos likely to be higher quality
            if any(domain in url.lower() for domain in ["unsplash", "pexels", "pixabay", "shutterstock"]):
                link_score += 0.3  # Known image sites with good quality
            if any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png"]):
                link_score += 0.2  # Direct image links often better
            link_score = min(link_score, 1.0)  # Cap at 1.0
            
            # Add dimensions-based scoring only if available and seems valid
            score = (position_score * 0.6) + (link_score * 0.4)
            if width > 300 and height > 200:
                # Include dimension-based scoring since data seems valid
                ratio = width / height if height > 0 else 0
                target_ratio = self.width / self.height
                ratio_diff = abs(ratio - target_ratio)
                
                size_score = min((width * height) / (self.width * self.height * 1.5), 1.0)
                ratio_score = max(0, 1.0 - ratio_diff * 2)
                
                # Adjust final score to include dimension data
                score = (size_score * 0.3) + (ratio_score * 0.2) + (position_score * 0.3) + (link_score * 0.2)

            potential_images.append({
                "url": url, 
                "score": score, 
                "width": width, 
                "height": height,
                "position": i
            })

        if not potential_images:
            logger.warning(f"No suitable images found after analysis for query: '{query}'")
            raise Exception("No suitable images found in results")

        # Sort images by score, highest first
        potential_images.sort(key=lambda x: x["score"], reverse=True)

        # Attempt to download the top-ranked images
        max_attempts = min(5, len(potential_images))
        for i in range(max_attempts):
            selected_image = potential_images[i]
            image_url = selected_image["url"]
            logger.info(f"Attempting download {i+1}/{max_attempts} (Score: {selected_image['score']:.2f}, " +
                        f"Position: {selected_image['position']}, " +
                        f"API Size: {selected_image['width']}x{selected_image['height']}): {image_url[:70]}...")

            try:
                downloaded_path = self._download_and_process_image(image_url, output_path)
                if downloaded_path:
                    logger.info(f"Successfully downloaded and processed image {i+1}.")
                    return downloaded_path
            except Exception as download_err:
                logger.warning(f"Failed attempt {i+1} for {image_url}: {str(download_err)}")

        logger.error(f"All {max_attempts} download attempts failed for query: '{query}'")
        raise Exception(f"Failed to download a suitable image after {max_attempts} attempts")

    except Exception as e:
        logger.error(f"Error during image search/download for query '{query}': {str(e)}", exc_info=True)
        raise
        """)
        
        # 2. Modification for _download_and_process_image to analyze actual dimensions
        logger.info("\n2. Add image analysis after download in _download_and_process_image:")
        print("""
# Add this to _download_and_process_image after loading the image but before processing it
# This validates actual image dimensions rather than relying on API-provided dimensions

# Get actual dimensions
actual_width, actual_height = image.size
logger.debug(f"Actual image dimensions: {actual_width}x{actual_height}")

# Verify minimum size
if actual_width < 200 or actual_height < 150:
    raise Exception(f"Image dimensions too small: {actual_width}x{actual_height}")
        """)
        
        logger.info("\n=== END OF PROPOSED MODIFICATIONS ===\n")

def main():
    """Main test function."""
    tester = SerperImageSearchTester()
    
    # Test with a general query
    logger.info("==== TESTING WITH GENERAL QUERY ====")
    data1 = tester.test_serper_api_response("technology news")
    
    # Test with a more specific query
    logger.info("\n==== TESTING WITH SPECIFIC QUERY ====")
    data2 = tester.test_serper_api_response("open source developers digital traps AI crawlers")
    
    # Test improved scoring
    if data1:
        logger.info("\n==== TESTING IMPROVED SCORING WITH GENERAL QUERY RESULTS ====")
        tester.test_improved_scoring(data1)
    
    if data2:
        logger.info("\n==== TESTING IMPROVED SCORING WITH SPECIFIC QUERY RESULTS ====")
        tester.test_improved_scoring(data2)
    
    # Propose fixes
    logger.info("\n==== PROPOSED CODE FIXES ====")
    tester.propose_fixes()
    
    logger.info("\nTest completed. Check the temp_test_images directory for downloaded test images.")

if __name__ == "__main__":
    main()