#!/usr/bin/env python3
"""
Test script for Google's Imagen API using the code sample pattern
"""

import os
import sys
import logging
from io import BytesIO
from PIL import Image
from google import genai  # Using this import pattern specifically
from google.genai import types  # For GenerateImagesConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_imagen():
    """Test image generation using Imagen API with the provided code sample pattern."""
    # Get API key from environment
    api_key = "AIzaSyBh00gnIL3NAm3ipt5URKOmySHIIWOefpc"
    if not api_key:
        logger.error("GOOGLE_API_KEY environment variable not set")
        sys.exit(1)
    
    try:
        # Initialize client as in the code sample
        client = genai.Client(api_key=api_key)
        logger.info("Google AI client initialized successfully")
        
        # Test prompts
        test_prompts = [
            "A red apple sitting on a wooden table, photorealistic style with soft natural lighting",
            "A serene mountain landscape at sunset with vibrant colors, cinematic wide shot"
        ]
        
        for i, prompt in enumerate(test_prompts, 1):
            logger.info(f"\n--- TEST PROMPT {i}/{len(test_prompts)} ---")
            logger.info(f"Requesting Imagen image with prompt: {prompt[:80]}...")
            
            # Generate image using the exact pattern from the code sample
            try:
                response = client.models.generate_images(
                    model='imagen-3.0-generate-002',  # Use exact model name from sample
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                    )
                )
                
                # Process response
                if hasattr(response, 'generated_images') and response.generated_images:
                    logger.info("Image generated successfully!")
                    
                    # Save the image
                    output_path = f"test_imagen_{i}.png"
                    image_bytes = response.generated_images[0].image.image_bytes
                    image = Image.open(BytesIO(image_bytes))
                    image.save(output_path)
                    logger.info(f"Image saved to {output_path}")
                else:
                    logger.error("No images were generated in the response")
                    logger.error(f"Response structure: {dir(response)}")
            
            except Exception as e:
                logger.error(f"Error generating image: {e}", exc_info=True)
        
    except Exception as e:
        logger.error(f"Error initializing client: {e}", exc_info=True)

if __name__ == "__main__":
    test_imagen()