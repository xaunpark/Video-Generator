#!/usr/bin/env python
"""
Serper API Image Search Test and Enhancement

This script tests Serper.dev API response structure, implements enhanced image scoring logic
that doesn't rely on API-provided dimensions, and improves the image filtering mechanism.

Usage:
    1. Set your SERPER_API_KEY as an environment variable or modify the script
    2. Run the script: python test_serper_image.py
"""

import os
import json
import logging
import requests
import tempfile
import time
from PIL import Image
from io import BytesIO
import pprint

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("serper-test")

# API Configuration
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")  # Set environment variable before running
if not SERPER_API_KEY:
    # Fallback to hardcoded value if needed for testing
    SERPER_API_KEY = "8f9c1cf90515e0b8bffe46642d627c28a5b24d84"  # Add your key here for testing if not using env var
    if not SERPER_API_KEY:
        logger.error("No SERPER_API_KEY found in environment variables or hardcoded")
        exit(1)

# Target video dimensions (for scoring)
TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080

# Create a temp directory for test images
TEMP_DIR = tempfile.mkdtemp()
logger.info(f"Created temporary directory for test images: {TEMP_DIR}")


def test_serper_api(query="artificial intelligence", num_results=5):
    """
    Test 1: Make a request to Serper API and analyze the full response structure
    """
    logger.info(f"Testing Serper API with query: '{query}'")
    
    serper_url = "https://google.serper.dev/images"
    serper_headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    
    # Payload for US/English search
    payload = json.dumps({
        "q": query,
        "gl": "us",  # Geo-location: United States
        "hl": "en",  # Host language: English
        "num": num_results  # Number of results to request
    })
    
    try:
        logger.info("Sending request to Serper API...")
        response = requests.post(serper_url, headers=serper_headers, data=payload, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Serper API error: {response.status_code}, {response.text}")
            return None
        
        data = response.json()
        
        # 1. Analyze and log the full response structure
        logger.info("Full Serper API response structure:")
        pretty_json = json.dumps(data, indent=2)
        print(pretty_json)
        
        # Check if 'images' key exists in response
        image_results = data.get("images", [])
        if not image_results:
            logger.warning("No images found in response")
            return None
        
        # Analyze structure of the first image result
        logger.info("\nAnalyzing first image result structure:")
        first_image = image_results[0]
        logger.info(f"Keys in image object: {list(first_image.keys())}")
        
        # Check for dimension information
        has_width = "width" in first_image
        has_height = "height" in first_image
        logger.info(f"Contains width information: {has_width}")
        logger.info(f"Contains height information: {has_height}")
        
        if has_width and has_height:
            logger.info(f"Width: {first_image.get('width')}, Height: {first_image.get('height')}")
        
        # Check other important fields
        logger.info(f"Image URL field: {'imageUrl' if 'imageUrl' in first_image else 'Not found'}")
        if 'imageUrl' in first_image:
            logger.info(f"Sample image URL: {first_image['imageUrl'][:100]}...")
        
        return image_results
    
    except Exception as e:
        logger.error(f"Error calling Serper API: {str(e)}")
        return None


def get_actual_image_dimensions(image_url):
    """
    Helper function to get actual dimensions by downloading the image
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(image_url, headers=headers, timeout=10, stream=True)
        response.raise_for_status()
        
        # Check Content-Type
        content_type = response.headers.get('Content-Type', '').lower()
        if not content_type.startswith('image/'):
            if not ('webp' in content_type or 'avif' in content_type or 'octet-stream' in content_type):
                logger.warning(f"Non-image content type: {content_type}")
                return None, None
        
        # Read image data
        image_data = response.content
        if not image_data:
            logger.warning("Empty image data")
            return None, None
        
        # Open image and get dimensions
        image = Image.open(BytesIO(image_data))
        return image.width, image.height
    
    except Exception as e:
        logger.warning(f"Error getting image dimensions: {str(e)}")
        return None, None


def score_images_with_enhanced_logic(image_results):
    """
    Test 2: Implement enhanced image scoring that doesn't rely on API dimensions
    
    This function:
    1. Assigns a base score to all images
    2. Attempts to download each image to get real dimensions
    3. Adjusts scores based on actual dimensions and other factors
    """
    logger.info("\n=== Testing Enhanced Image Scoring Logic ===")
    
    if not image_results:
        logger.error("No image results to score")
        return []
    
    enhanced_results = []
    
    for i, img_data in enumerate(image_results[:5]):  # Limit to first 5 to keep test quick
        img_url = img_data.get("imageUrl")
        if not img_url:
            logger.warning(f"Image {i+1} missing URL, skipping")
            continue
        
        # Initialize with base score - all images start with a decent chance
        base_score = 0.5
        source_score = 0.0
        dimension_score = 0.0
        
        logger.info(f"\nAnalyzing image {i+1}: {img_url[:100]}...")
        
        # Check for "source quality" heuristics in URL
        source_terms = ["stock", "shutterstock", "getty", "adobe", "unsplash", "pexels"]
        lower_url = img_url.lower()
        if any(term in lower_url for term in source_terms):
            source_score = 0.2  # Bonus for stock/quality image sites
            logger.info(f"Quality source detected (+0.2 score)")
            
        # Skip problematic URLs 
        if "lookaside." in lower_url or "fbcdn" in lower_url:
            logger.info(f"Potentially problematic URL, reducing score")
            source_score -= 0.2
        
        # Get actual dimensions by downloading a small sample of the image
        logger.info("Downloading image to check actual dimensions...")
        try:
            width, height = get_actual_image_dimensions(img_url)
            
            if width and height:
                logger.info(f"Actual dimensions: {width}x{height}")
                
                # Score based on actual dimensions
                # Higher score for images closer to target dimensions
                size_ratio = (width * height) / (TARGET_WIDTH * TARGET_HEIGHT) 
                
                # Cap the ratio between 0.1 and 1.5
                size_ratio = max(0.1, min(size_ratio, 1.5))
                
                # Convert to a 0-1 score, favoring images closer to target size
                if size_ratio <= 1.0:
                    # Smaller than target: linear score from 0.1 to 1.0
                    dimension_score = 0.3 + (size_ratio * 0.7)
                else:
                    # Larger than target: slight bonus
                    dimension_score = 1.0 + ((size_ratio - 1.0) * 0.2)
                    dimension_score = min(dimension_score, 1.2)  # Cap at 1.2
                
                logger.info(f"Dimension score: {dimension_score:.2f}")
                
                # Check aspect ratio
                target_ratio = TARGET_WIDTH / TARGET_HEIGHT
                img_ratio = width / height
                ratio_diff = abs(img_ratio - target_ratio)
                
                # Adjust score based on aspect ratio match
                aspect_ratio_score = max(0, 1.0 - (ratio_diff * 1.5))
                logger.info(f"Aspect ratio difference: {ratio_diff:.2f}, score: {aspect_ratio_score:.2f}")
                
                # Final score calculation
                final_score = (base_score * 0.3) + (dimension_score * 0.4) + (aspect_ratio_score * 0.2) + (source_score * 0.1)
                
                enhanced_results.append({
                    "url": img_url,
                    "width": width,
                    "height": height,
                    "score": final_score,
                    "original_data": img_data
                })
                
                logger.info(f"Final score: {final_score:.2f}")
            else:
                logger.warning("Could not determine image dimensions")
                # Still include but with lower score
                enhanced_results.append({
                    "url": img_url,
                    "width": 0,
                    "height": 0,
                    "score": base_score * 0.8,  # Penalty for unknown dimensions
                    "original_data": img_data
                })
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
    
    # Sort by score (highest first)
    enhanced_results.sort(key=lambda x: x["score"], reverse=True)
    
    # Display final ranking
    logger.info("\nFinal image ranking by enhanced scoring:")
    for i, result in enumerate(enhanced_results):
        logger.info(f"{i+1}. Score: {result['score']:.2f}, Size: {result['width']}x{result['height']}, URL: {result['url'][:80]}...")
    
    return enhanced_results


def test_improved_image_filtering(image_results):
    """
    Test 3: Implement improved image filtering logic
    
    This function:
    1. Includes all images with URLs (doesn't filter by size)
    2. Implements a more flexible filtering system
    3. Tests a two-pass approach: first quick filter, then detail check
    """
    logger.info("\n=== Testing Improved Image Filtering Logic ===")
    
    if not image_results:
        logger.error("No image results to filter")
        return []
    
    # First-pass quick filtering (lenient)
    quick_filtered = []
    for img in image_results:
        img_url = img.get("imageUrl")
        if not img_url:
            continue  # Skip images without URL
            
        # Skip obviously problematic URLs
        lower_url = img_url.lower()
        if ("lookaside.fbsbx" in lower_url or 
            "lookaside.instagram" in lower_url or
            "data:image" in lower_url):  # Skip data URLs
            logger.info(f"Skipping problematic URL: {img_url[:80]}...")
            continue
            
        # All other images pass the quick filter
        quick_filtered.append(img)
    
    logger.info(f"First-pass filtering: {len(quick_filtered)}/{len(image_results)} images passed")
    
    # Second-pass: Analyze a sample of images more carefully
    detailed_results = []
    tested_count = min(5, len(quick_filtered))  # Test up to 5 images
    
    for i, img in enumerate(quick_filtered[:tested_count]):
        img_url = img.get("imageUrl")
        logger.info(f"\nDetailed analysis of image {i+1}: {img_url[:80]}...")
        
        try:
            # Try to get actual dimensions (as we would in production)
            width, height = get_actual_image_dimensions(img_url)
            
            if width and height:
                logger.info(f"Image can be downloaded successfully. Dimensions: {width}x{height}")
                is_valid = True
                
                # Quality check: extremely small images
                if width < 200 or height < 200:
                    logger.warning(f"Image is very small ({width}x{height})")
                    is_valid = False
                    
                # Save test download to verify
                if is_valid:
                    logger.info(f"Image passed all checks")
                    detailed_results.append({
                        "url": img_url,
                        "width": width,
                        "height": height,
                        "original_data": img
                    })
            else:
                logger.warning(f"Could not determine dimensions, may be a problematic image")
        except Exception as e:
            logger.error(f"Error during detailed analysis: {str(e)}")
    
    logger.info(f"\nDetailed filtering results: {len(detailed_results)}/{tested_count} images passed the detail check")
    
    # Suggested approach for production
    logger.info("\nSuggested improvements for image filtering:")
    logger.info("1. Don't filter out images based on API-provided dimensions (which are unreliable)")
    logger.info("2. Use a two-pass approach: quick filtering by URL patterns, then test downloads")
    logger.info("3. Always try to download images to get actual dimensions")
    logger.info("4. Add fallback logic if first N images fail download")
    logger.info("5. Implement scoring based on successful downloads and actual dimensions")
    
    return detailed_results


def generate_improved_code_recommendations():
    """Generate recommendations for improving the image_generator.py code"""
    logger.info("\n=== Recommended Code Changes for image_generator.py ===")
    
    recommendations = [
        {"function": "_search_and_download_image", 
         "issue": "Relies on API-provided dimensions which may be missing/inaccurate",
         "suggestion": "Don't filter images by API-provided dimensions. Instead, use URL-based filtering, then check dimensions after downloading."},
        
        {"function": "_search_and_download_image", 
         "issue": "Scoring depends heavily on reported dimensions",
         "suggestion": "Implement a base score for all images and factor in other elements like URL quality, successful download, etc."},
        
        {"function": "_search_and_download_image", 
         "issue": "All filtered images scored 0.00 with Size: 0x0",
         "suggestion": "Create a more resilient scoring system. Assign partial scores to images before checking dimensions."},
        
        {"function": "_search_and_download_image", 
         "issue": "Some image sources consistently fail",
         "suggestion": "Implement a blacklist for problematic domains (lookaside.fbsbx.com, etc.) to avoid wasting download attempts."},
    ]
    
    for i, rec in enumerate(recommendations):
        logger.info(f"\nRecommendation {i+1}:")
        logger.info(f"Function: {rec['function']}")
        logger.info(f"Issue: {rec['issue']}")
        logger.info(f"Suggestion: {rec['suggestion']}")
    
    # Example code for improved _search_and_download_image function
    improved_function = """
def _search_and_download_image(self, query, output_path):
    \"\"\"Improved version that doesn't rely on API-provided dimensions\"\"\"
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

        # Problematic domains to avoid
        blacklisted_domains = ["lookaside.fbsbx.com", "lookaside.instagram.com", "fbcdn"]
        
        # First pass: Quick filter to skip only obviously bad URLs
        potential_images = []
        for img_data in image_results:
            url = img_data.get("imageUrl")
            if not url:
                continue
                
            # Skip blacklisted domains
            if any(domain in url.lower() for domain in blacklisted_domains):
                logger.debug(f"Skipping blacklisted domain: {url}")
                continue
                
            # Base score - start with 0.5 for all images that pass basic checks
            score = 0.5
            
            # Bonus for URLs from good sources
            good_sources = ["stock", "shutterstock", "getty", "unsplash", "pexels"]
            if any(source in url.lower() for source in good_sources):
                score += 0.2
                
            potential_images.append({"url": url, "score": score})
        
        if not potential_images:
            logger.warning(f"No suitable images found after filtering for query: '{query}'")
            raise Exception("No suitable images found")

        # Sort by initial score
        potential_images.sort(key=lambda x: x["score"], reverse=True)

        # Attempt to download the top-ranked images
        max_attempts = min(5, len(potential_images)) # Try the best 5 images
        for i in range(max_attempts):
            selected_image = potential_images[i]
            image_url = selected_image["url"]
            logger.info(f"Attempting download {i+1}/{max_attempts} (Initial Score: {selected_image['score']:.2f}): {image_url[:70]}...")

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
    """
    
    logger.info("\nSuggested improved implementation for _search_and_download_image function:")
    print(improved_function)
    
    return recommendations


if __name__ == "__main__":
    try:
        # Run the tests
        logger.info("Starting Serper API and image handling tests...")
        
        # Test 1: Check Serper API response structure
        search_query = "artificial intelligence visualization"
        image_results = test_serper_api(search_query)
        
        if image_results:
            # Test 2: Test enhanced image scoring
            enhanced_results = score_images_with_enhanced_logic(image_results)
            
            # Test 3: Test improved filtering
            filtered_results = test_improved_image_filtering(image_results)
            
            # Generate code improvement recommendations
            generate_improved_code_recommendations()
        
        logger.info("\nTests completed. Check the logs for results and recommendations.")
        
    except Exception as e:
        logger.error(f"Test failed with error: {str(e)}", exc_info=True)
    finally:
        # Clean up temp directory (commented out for debugging)
        # import shutil
        # shutil.rmtree(TEMP_DIR)
        # logger.info(f"Removed temporary directory: {TEMP_DIR}")
        pass