import os
import requests
import json
import logging
import random
import hashlib
import time
import shutil
from urllib.parse import urlparse
from moviepy.editor import VideoFileClip, concatenate_videoclips, vfx
from src.fix_pillow import *

# Import API keys and settings
from config.credentials import PEXELS_API_KEY, PIXABAY_API_KEY
from config.settings import TEMP_DIR, VIDEO_SETTINGS

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VideoClipFinder:
    """Class to find and download short video clips from free sources like Pexels and Pixabay."""
    
    def __init__(self):
        """Initialize VideoClipFinder with necessary API keys and settings."""
        self.pexels_api_key = PEXELS_API_KEY
        self.pixabay_api_key = PIXABAY_API_KEY
        
        if not self.pexels_api_key and not self.pixabay_api_key:
            logger.warning("No API keys for Pexels or Pixabay. Video clip search will be limited.")
            
        # Create directories
        self.temp_dir = TEMP_DIR
        self.video_cache_dir = os.path.join(self.temp_dir, "video_cache")
        os.makedirs(self.video_cache_dir, exist_ok=True)
        
        # Video parameters
        self.target_width = VIDEO_SETTINGS["width"]
        self.target_height = VIDEO_SETTINGS["height"]
        self.target_duration = 7  # Default target duration in seconds
        
        # API endpoints
        self.pexels_url = "https://api.pexels.com/videos/search"
        self.pexels_headers = {"Authorization": self.pexels_api_key}
        
        self.pixabay_url = "https://pixabay.com/api/videos/"
        
        # Blacklisted terms (to avoid inappropriate content)
        self.blacklisted_terms = ["nude", "nsfw", "explicit", "porn", "sex", "adult", "violence", "bloody"]
        
    def find_video_clip(self, query, scene_content, output_path, target_duration=None):
        """
        Find and download a short video clip matching the query and scene content.
        
        Args:
            query (str): The search query for video content
            scene_content (str): Content of the scene (for context)
            output_path (str): Path to save the processed video clip
            target_duration (float, optional): Target duration for the clip in seconds
            
        Returns:
            str: Path to the processed video clip, or None if no suitable clip found
        """
        if target_duration:
            self.target_duration = target_duration
            
        # Check for blacklisted terms
        if any(term in query.lower() for term in self.blacklisted_terms):
            logger.warning(f"Query '{query}' contains blacklisted terms. Sanitizing query.")
            # Extract main keywords and create safer query
            safer_terms = [word for word in query.split() 
                          if word.lower() not in self.blacklisted_terms]
            query = " ".join(safer_terms) + " safe"
            
        logger.info(f"Searching for video clip with query: '{query}'")
        
        # Check video cache first
        cached_video = self._check_video_cache(query)
        if cached_video:
            logger.info(f"Using cached video for query: '{query}'")
            # Convert cached video to required format
            return self._process_video_clip(cached_video, output_path)
            
        # Try different sources until a suitable video is found
        video_sources = [
            self._search_pexels_videos,
            self._search_pixabay_videos
        ]
        
        for source_func in video_sources:
            if not callable(source_func):
                continue
                
            try:
                video_results = source_func(query)
                
                if video_results and len(video_results) > 0:
                    # Filter and sort videos by relevance and quality
                    suitable_videos = self._filter_videos(video_results, query)
                    
                    if suitable_videos:
                        # Try to download top videos until success
                        for video_data in suitable_videos[:5]:  # Try top 5
                            try:
                                video_url = video_data.get("video_url")
                                if not video_url:
                                    continue
                                    
                                logger.info(f"Attempting to download video: {video_url[:80]}...")
                                
                                # Download and process video
                                downloaded_path = self._download_video(video_url, query)
                                if downloaded_path:
                                    # Process video to fit requirements
                                    processed_path = self._process_video_clip(downloaded_path, output_path)
                                    if processed_path:
                                        return processed_path
                            except Exception as e:
                                logger.warning(f"Failed to download/process video {video_url}: {str(e)}")
                                continue  # Try next video
            except Exception as e:
                logger.warning(f"Error searching videos from source {source_func.__name__}: {str(e)}")
                continue  # Try next source
                
        logger.warning(f"No suitable video clips found for query: '{query}'")
        return None
        
    def _search_pexels_videos(self, query):
        """Search videos from Pexels API."""
        if not self.pexels_api_key:
            logger.warning("No Pexels API key available.")
            return []
            
        try:
            params = {
                "query": query,
                "per_page": 15,
                "size": "medium",  # Prefer medium size videos
                "orientation": "landscape"
            }
            
            response = requests.get(
                self.pexels_url, 
                headers=self.pexels_headers, 
                params=params,
                timeout=15
            )
            
            if response.status_code != 200:
                logger.error(f"Pexels API error: {response.status_code}, {response.text}")
                return []
                
            data = response.json()
            videos = data.get("videos", [])
            
            # Transform Pexels response to standard format
            standardized_results = []
            for video in videos:
                # Get the HD or SD video file URL
                video_files = video.get("video_files", [])
                
                # Sort video files by quality (prefer HD)
                video_files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
                
                if video_files:
                    # Get best quality that's not too large
                    selected_file = None
                    for file in video_files:
                        if file.get("width", 0) >= 720:  # At least 720p
                            selected_file = file
                            break
                            
                    if not selected_file and video_files:
                        selected_file = video_files[0]  # Fallback to first file
                        
                    if selected_file:
                        standardized_results.append({
                            "video_url": selected_file.get("link"),
                            "width": selected_file.get("width", 0),
                            "height": selected_file.get("height", 0),
                            "duration": video.get("duration", 0),
                            "source": "pexels",
                            "preview_url": video.get("image"),  # Thumbnail
                            "title": video.get("alt", "Pexels Video")
                        })
            
            logger.info(f"Found {len(standardized_results)} videos from Pexels")
            return standardized_results
            
        except Exception as e:
            logger.error(f"Error searching Pexels videos: {str(e)}")
            return []
            
    def _search_pixabay_videos(self, query):
        """Search videos from Pixabay API."""
        if not self.pixabay_api_key:
            logger.warning("No Pixabay API key available.")
            return []
            
        try:
            params = {
                "key": self.pixabay_api_key,
                "q": query,
                "video_type": "film",  # Options: all, film, animation
                "per_page": 20
            }
            
            response = requests.get(
                self.pixabay_url,
                params=params,
                timeout=15
            )
            
            if response.status_code != 200:
                logger.error(f"Pixabay API error: {response.status_code}, {response.text}")
                return []
                
            data = response.json()
            hits = data.get("hits", [])
            
            # Transform Pixabay response to standard format
            standardized_results = []
            for video in hits:
                # Get the best video URL (prefer HD)
                videos = video.get("videos", {})
                video_url = None
                width = 0
                height = 0
                
                # Try to get best quality
                if videos.get("large"):
                    video_url = videos["large"]["url"]
                    width = videos["large"]["width"]
                    height = videos["large"]["height"]
                elif videos.get("medium"):
                    video_url = videos["medium"]["url"]
                    width = videos["medium"]["width"]
                    height = videos["medium"]["height"]
                elif videos.get("small"):
                    video_url = videos["small"]["url"]
                    width = videos["small"]["width"]
                    height = videos["small"]["height"]
                    
                if video_url:
                    standardized_results.append({
                        "video_url": video_url,
                        "width": width,
                        "height": height,
                        "duration": 0,  # Pixabay doesn't provide duration
                        "source": "pixabay",
                        "preview_url": video.get("userImageURL", ""),
                        "title": f"Pixabay Video {video.get('id', '')}"
                    })
            
            logger.info(f"Found {len(standardized_results)} videos from Pixabay")
            return standardized_results
            
        except Exception as e:
            logger.error(f"Error searching Pixabay videos: {str(e)}")
            return []
            
    def _filter_videos(self, video_results, query):
        """
        Filter and score videos based on quality, relevance, and DURATION MATCH. # <-- Cập nhật docstring

        Args:
            video_results (list): List of video data dictionaries
            query (str): The original search query

        Returns:
            list: Filtered and sorted list of videos
        """
        if not video_results:
            return []

        scored_videos = []

        # Convert query to lowercase for comparison
        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Lấy target_duration từ instance variable
        target_duration = self.target_duration
        logger.debug(f"Target duration for filtering: {target_duration:.2f}s") # Thêm log để debug

        for video in video_results:
            # Skip videos without URL
            if not video.get("video_url"):
                continue

            # Base score
            score = 0.5

            # Score based on title match with query (Giữ nguyên)
            title = video.get("title", "").lower()
            title_words = set(title.split())
            common_words = query_words.intersection(title_words)
            if common_words:
                title_score = len(common_words) / len(query_words) if len(query_words) > 0 else 0 # Tránh chia cho 0
                score += title_score * 0.3

            # Score based on resolution (Giữ nguyên)
            width = video.get("width", 0)
            height = video.get("height", 0)
            if width >= 1920 and height >= 1080:
                score += 0.3
            elif width >= 1280 and height >= 720:
                score += 0.2
            elif width >= 640 and height >= 480:
                score += 0.1

            # Score based on aspect ratio match (Giữ nguyên)
            if width > 0 and height > 0:
                video_ratio = width / height
                target_ratio = self.target_width / self.target_height
                ratio_diff = abs(video_ratio - target_ratio)
                if ratio_diff < 0.1:
                    score += 0.2
                elif ratio_diff < 0.3:
                    score += 0.1

            # --- BẮT ĐẦU LOGIC CHẤM ĐIỂM THỜI LƯỢNG MỚI ---
            duration = video.get("duration", 0)
            duration_score_bonus = 0.0 # Điểm thưởng dựa trên thời lượng

            if duration > 0 and target_duration > 0: # Chỉ chấm điểm nếu biết cả hai thời lượng
                # Định nghĩa các khoảng thời lượng lý tưởng và chấp nhận được
                ideal_lower_bound = target_duration
                ideal_upper_bound = target_duration + 5.0 # Cho phép dài hơn tối đa 5 giây
                acceptable_lower_bound = target_duration * 0.75 # Ngắn hơn tối đa 25% (để có thể làm chậm)

                # Tính điểm thưởng
                if ideal_lower_bound <= duration <= ideal_upper_bound:
                    # Rất tốt: Thời lượng đúng hoặc dài hơn một chút
                    duration_score_bonus = 0.35 # Điểm thưởng cao nhất
                    logger.debug(f"Video {video.get('source')}/{video.get('id', '')}: Duration {duration:.1f}s - IDEAL MATCH (+{duration_score_bonus})")
                elif acceptable_lower_bound <= duration < ideal_lower_bound:
                    # Chấp nhận được: Ngắn hơn một chút, có thể làm chậm
                    # Điểm thưởng giảm dần khi càng ngắn
                    proximity_factor = (duration - acceptable_lower_bound) / (ideal_lower_bound - acceptable_lower_bound)
                    duration_score_bonus = 0.1 + (0.15 * proximity_factor) # Từ 0.1 đến 0.25
                    logger.debug(f"Video {video.get('source')}/{video.get('id', '')}: Duration {duration:.1f}s - ACCEPTABLE SHORT (+{duration_score_bonus:.2f})")
                else:
                     # Quá ngắn hoặc quá dài, không có điểm thưởng
                     logger.debug(f"Video {video.get('source')}/{video.get('id', '')}: Duration {duration:.1f}s - POOR MATCH (+0.0)")
                     pass

            elif duration == 0:
                # Không biết thời lượng (thường là Pixabay), không cộng không trừ
                logger.debug(f"Video {video.get('source')}/{video.get('id', '')}: Duration UNKNOWN (+0.0)")
                pass

            # Cộng điểm thưởng thời lượng vào điểm tổng
            score += duration_score_bonus
            # --- KẾT THÚC LOGIC CHẤM ĐIỂM THỜI LƯỢNG MỚI ---

            # XÓA HOẶC COMMENT OUT LOGIC CHẤM ĐIỂM THỜI LƯỢNG CŨ NẾU CÓ
            # Ví dụ:
            # # Score based on duration (LOGIC CŨ - ĐÃ BÌNH LUẬN)
            # # duration = video.get("duration", 0)
            # # if 5 <= duration <= 15:
            # #     score += 0.2  # Ideal duration
            # # elif duration > 0:
            # #     score += 0.1  # At least we know the duration

            # Giới hạn điểm tối đa là 1.0
            score = min(1.0, score)

            # Add to list with score
            video["score"] = score
            scored_videos.append(video)
            logger.debug(f"Video {video.get('source')}/{video.get('id', '')} final score: {score:.2f}") # Log điểm cuối cùng

        # Sort by score, highest first (Giữ nguyên)
        scored_videos.sort(key=lambda x: x.get("score", 0), reverse=True)

        return scored_videos
            
    def _download_video(self, video_url, query):
        """
        Download video from URL.
        
        Args:
            video_url (str): URL of the video to download
            query (str): Original query (used for caching)
            
        Returns:
            str: Path to downloaded video file
        """
        # Generate hash for caching
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        # Create a filename based on URL
        parsed_url = urlparse(video_url)
        url_path = parsed_url.path
        file_extension = os.path.splitext(url_path)[1]
        if not file_extension or file_extension.lower() not in ['.mp4', '.webm', '.mov']:
            file_extension = '.mp4'  # Default to mp4
            
        # Full path for downloaded file
        cache_filename = f"{query_hash}{file_extension}"
        output_path = os.path.join(self.video_cache_dir, cache_filename)
        
        # Check if already cached
        if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:  # > 10KB
            logger.info(f"Using cached video: {output_path}")
            return output_path
            
        try:
            logger.info(f"Downloading video from: {video_url}")
            
            # Download with user agent header (some sites require this)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Stream download to file
            with requests.get(video_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        
            # Verify file was downloaded successfully
            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:  # > 10KB
                logger.info(f"Video downloaded successfully: {output_path}")
                return output_path
            else:
                logger.warning(f"Downloaded file is too small or invalid: {output_path}")
                if os.path.exists(output_path):
                    os.remove(output_path)
                return None
                
        except Exception as e:
            logger.error(f"Error downloading video from {video_url}: {str(e)}")
            
            # Clean up partial download if any
            if os.path.exists(output_path):
                os.remove(output_path)
                
            return None
            
    def _process_video_clip(self, input_path, output_path):
        """
        Process downloaded video to match required format and duration.
        
        Args:
            input_path (str): Path to the input video file
            output_path (str): Path to save the processed video
            
        Returns:
            str: Path to the processed video, or None if processing failed
        """
        try:
            # Load the video clip
            video = VideoFileClip(input_path)
            
            # Get clip duration
            original_duration = video.duration
            logger.info(f"Original video duration: {original_duration:.2f}s")
            
            # Cut to target duration if needed
            if original_duration > self.target_duration:
                # Calculate a good starting point (avoid starting at the very beginning)
                if original_duration > (self.target_duration * 2):
                    max_start = original_duration - self.target_duration - 1
                    start_time = random.uniform(1, max_start)
                else:
                    start_time = 0
                    
                logger.info(f"Cutting video from {start_time:.2f}s to {start_time + self.target_duration:.2f}s")
                video = video.subclip(start_time, start_time + self.target_duration)
            
            # Resize if needed
            if video.w != self.target_width or video.h != self.target_height:
                # Check if we need to crop or pad
                video_ratio = video.w / video.h
                target_ratio = self.target_width / self.target_height
                
                if abs(video_ratio - target_ratio) < 0.1:
                    # Similar ratio, just resize
                    video = video.resize((self.target_width, self.target_height))
                else:
                    # Different ratio, resize the correct dimension and crop the other
                    if video_ratio > target_ratio:
                        # Video is wider, resize height and crop width
                        new_height = self.target_height
                        new_width = int(video.w * (new_height / video.h))
                        video = video.resize((new_width, new_height))
                        
                        # Crop width
                        x_center = video.w / 2
                        video = video.crop(x1=x_center - self.target_width/2, 
                                          y1=0, 
                                          x2=x_center + self.target_width/2, 
                                          y2=self.target_height)
                    else:
                        # Video is taller, resize width and crop height
                        new_width = self.target_width
                        new_height = int(video.h * (new_width / video.w))
                        video = video.resize((new_width, new_height))
                        
                        # Crop height
                        y_center = video.h / 2
                        video = video.crop(x1=0, 
                                          y1=y_center - self.target_height/2, 
                                          x2=self.target_width, 
                                          y2=y_center + self.target_height/2)
            
            # Mute the video (optional, comment out if you want to keep original audio)
            video = video.without_audio()
            
            # Add a subtle effect (makes it look more professional)
            video = video.fx(vfx.colorx, 1.1)  # Slightly enhance colors
            
            # Write to output file
            video.write_videofile(
                output_path,
                codec='libx264',
                audio_codec='aac',
                fps=24,
                preset='medium',
                ffmpeg_params=['-crf', '23']  # Controls quality
            )
            
            # Close the video to free resources
            video.close()
            
            logger.info(f"Video processed successfully: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error processing video: {str(e)}")
            
            # Clean up any partial output
            if os.path.exists(output_path):
                os.remove(output_path)
                
            return None
            
    def _check_video_cache(self, query):
        """
        Check if a video for this query is already in the cache.
        
        Args:
            query (str): Search query
            
        Returns:
            str: Path to cached video if exists, None otherwise
        """
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        # Check for various extensions
        for ext in ['.mp4', '.webm', '.mov']:
            cache_path = os.path.join(self.video_cache_dir, f"{query_hash}{ext}")
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 10000:  # > 10KB
                return cache_path
                
        return None