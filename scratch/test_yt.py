import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from services.scraper_service import get_youtube_transcript

video_id = "ojCSZx0syLk"

try:
    print(f"Fetching transcript for video {video_id}...")
    transcript = get_youtube_transcript(video_id)
    print("Success! Transcript length:", len(transcript))
    print("First 300 chars of transcript:")
    print(transcript[:300])
    
    # Check if any temp files were left in scratch/
    temp_files = [f for f in os.listdir("scratch") if f.startswith(f"tmp_subs_{video_id}")]
    print("Temporary files left:", temp_files)
except Exception as e:
    print("Failed to fetch transcript:", e)
