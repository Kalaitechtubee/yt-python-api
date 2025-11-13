from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import re
import shutil
import requests

app = Flask(__name__)
CORS(app)

# YouTube Data API v3 Key
YOUTUBE_API_KEY = "AIzaSyADQYVvnEU3zqxnR7GvxXmUexO-EGL2KhI"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Temporary download directory
TEMP_DOWNLOAD_PATH = tempfile.gettempdir()

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)

def check_ffmpeg_installed():
    """Check if FFmpeg is available in PATH"""
    return shutil.which("ffmpeg") is not None

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([^&\n?#]+)',
        r'(?:youtu\.be\/)([^&\n?#]+)',
        r'(?:youtube\.com\/embed\/)([^&\n?#]+)',
        r'(?:youtube\.com\/v\/)([^&\n?#]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_video_info_from_api(video_id):
    """Fetch video info using official YouTube Data API v3"""
    try:
        url = f"{YOUTUBE_API_BASE}/videos"
        params = {
            'part': 'snippet,contentDetails,statistics',
            'id': video_id,
            'key': YOUTUBE_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'items' in data and len(data['items']) > 0:
                item = data['items'][0]
                snippet = item.get('snippet', {})
                statistics = item.get('statistics', {})
                content_details = item.get('contentDetails', {})
                
                # Parse duration (ISO 8601 format: PT15M33S)
                duration_iso = content_details.get('duration', 'PT0S')
                duration_str = parse_iso_duration(duration_iso)
                
                # Format view count
                views = int(statistics.get('viewCount', 0))
                if views >= 1_000_000:
                    views_str = f"{views/1_000_000:.1f}M"
                elif views >= 1_000:
                    views_str = f"{views/1_000:.1f}K"
                else:
                    views_str = str(views)
                
                return {
                    'title': snippet.get('title', 'Unknown'),
                    'channel': snippet.get('channelTitle', 'Unknown'),
                    'thumbnail': snippet.get('thumbnails', {}).get('maxres', {}).get('url', 
                                snippet.get('thumbnails', {}).get('high', {}).get('url', '')),
                    'duration': duration_str,
                    'views': views_str,
                    'description': snippet.get('description', '')[:200] + '...' if snippet.get('description') else ''
                }
        
        return None
    except Exception as e:
        print(f"❌ API Error: {str(e)}")
        return None

def parse_iso_duration(duration):
    """Convert ISO 8601 duration to MM:SS format"""
    import re
    
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return "0:00"
    
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    
    total_minutes = hours * 60 + minutes
    return f"{total_minutes}:{seconds:02d}"

def get_ydl_opts_base():
    """Enhanced yt-dlp options"""
    return {
        'quiet': True,
        'no_warnings': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['dash', 'hls']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
        },
    }

@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({
        "message": "YouTube Downloader API - Official API Integration",
        "version": "4.0",
        "status": "online",
        "features": ["YouTube Data API v3", "yt-dlp downloader", "FFmpeg processing"],
        "endpoints": {
            "/health": "Health check (GET)",
            "/api/video-info": "Get video information (POST)",
            "/api/download": "Download video/audio (POST)"
        }
    }), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "message": "Backend server is running",
        "ffmpeg": check_ffmpeg_installed(),
        "yt_dlp_version": yt_dlp.version.__version__,
        "api_configured": bool(YOUTUBE_API_KEY)
    }), 200

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    """Fetch video metadata using YouTube Data API v3"""
    try:
        data = request.get_json()
        url = data.get("url")

        if not url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        url = url.strip()
        
        # Extract video ID
        video_id = extract_video_id(url)
        
        if not video_id:
            return jsonify({"success": False, "error": "Invalid YouTube URL"}), 400
        
        print(f"🔍 Fetching info for video ID: {video_id}")
        
        # Try YouTube Data API first (100% reliable, no restrictions)
        video_info = get_video_info_from_api(video_id)
        
        if video_info:
            print(f"✅ Successfully fetched via API: {video_info['title']}")
            return jsonify({"success": True, "info": video_info, "method": "youtube_api"}), 200
        
        # Fallback to yt-dlp if API fails
        print("🔄 API failed, trying yt-dlp...")
        ydl_opts = get_ydl_opts_base()
        ydl_opts.update({
            'extract_flat': False,
            'skip_download': True,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            duration_seconds = info.get('duration', 0)
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            
            views = info.get('view_count', 0)
            if views >= 1_000_000:
                views_str = f"{views/1_000_000:.1f}M"
            elif views >= 1_000:
                views_str = f"{views/1_000:.1f}K"
            else:
                views_str = str(views)

            video_info = {
                "title": info.get('title', 'Unknown'),
                "channel": info.get('uploader', 'Unknown'),
                "thumbnail": info.get('thumbnail', ''),
                "duration": f"{minutes}:{seconds:02d}",
                "views": views_str,
                "description": (info.get('description', '')[:200] + '...')
                if info.get('description') else ''
            }
            
            print(f"✅ Successfully fetched via yt-dlp: {video_info['title']}")
            return jsonify({"success": True, "info": video_info, "method": "yt_dlp"}), 200

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({"success": False, "error": f"Failed to fetch video info: {str(e)}"}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    """Download video/audio and stream it to client"""
    temp_file = None
    try:
        if not check_ffmpeg_installed():
            return jsonify({"error": "FFmpeg not found. Cannot process downloads."}), 500

        data = request.get_json()
        url = data.get("url")
        download_type = data.get("type", "video")  # 'video' or 'audio'
        quality = data.get("quality", "highest")

        if not url:
            return jsonify({"error": "URL is required"}), 400

        url = url.strip()
        temp_filename = f"temp_{os.urandom(8).hex()}"

        print(f"📥 Starting download: {url}")
        print(f"   Type: {download_type}, Quality: {quality}")

        ydl_opts = get_ydl_opts_base()
        ydl_opts.update({
            'outtmpl': os.path.join(TEMP_DOWNLOAD_PATH, f'{temp_filename}.%(ext)s'),
            'noplaylist': True,
            'no_color': True,
            'age_limit': None,  # Bypass age restrictions
        })

        if download_type == "audio":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192' if quality == 'highest' else '128',
                }],
            })
            expected_ext = 'mp3'
        else:
            # Simplified video format selection for better compatibility
            if quality == "highest":
                ydl_opts['format'] = 'best'
            elif quality == "high":
                ydl_opts['format'] = 'best[height<=720]'
            elif quality == "medium":
                ydl_opts['format'] = 'best[height<=480]'
            elif quality == "lowest":
                ydl_opts['format'] = 'worst'
            else:
                ydl_opts['format'] = 'best'
            
            expected_ext = 'mp4'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = sanitize_filename(info.get('title', 'video'))

        # Find the downloaded file
        temp_file = os.path.join(TEMP_DOWNLOAD_PATH, f'{temp_filename}.{expected_ext}')
        
        if not os.path.exists(temp_file):
            # Search for file with any extension
            for f in os.listdir(TEMP_DOWNLOAD_PATH):
                if f.startswith(temp_filename):
                    temp_file = os.path.join(TEMP_DOWNLOAD_PATH, f)
                    # Update extension based on actual file
                    expected_ext = f.split('.')[-1]
                    break

        if not os.path.exists(temp_file):
            return jsonify({"error": "Downloaded file not found"}), 500

        file_size = os.path.getsize(temp_file)
        download_filename = f"{title}.{expected_ext}"
        
        print(f"✅ Download complete: {download_filename} ({file_size} bytes)")

        def generate():
            try:
                with open(temp_file, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        print(f"🗑️ Cleaned up: {temp_file}")
                except Exception as e:
                    print(f"⚠️ Cleanup failed: {e}")

        response = Response(generate(), mimetype='application/octet-stream')
        response.headers['Content-Disposition'] = f'attachment; filename="{download_filename}"'
        response.headers['Content-Length'] = str(file_size)
        response.headers['Content-Type'] = 'application/octet-stream'

        return response

    except yt_dlp.utils.DownloadError as e:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        
        error_msg = str(e)
        print(f"❌ Download Error: {error_msg}")
        
        # More specific error messages
        if "Sign in" in error_msg:
            return jsonify({"error": "This video requires authentication. Please try a different video."}), 403
        elif "age" in error_msg.lower() or "restricted" in error_msg.lower():
            return jsonify({"error": "This video is age-restricted and cannot be downloaded."}), 403
        elif "available" in error_msg.lower():
            return jsonify({"error": "Video is not available. It may be private or deleted."}), 404
        elif "copyright" in error_msg.lower():
            return jsonify({"error": "This video has copyright restrictions."}), 403
        else:
            return jsonify({"error": f"Download failed. Try a different video or quality setting."}), 500
        
    except Exception as e:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        
        print(f"❌ Unexpected Error: {str(e)}")
        return jsonify({"error": f"Download failed: {str(e)}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", os.environ.get("X_ZOHO_CATALYST_LISTEN_PORT", 5000)))
    print("=" * 60)
    print("🎬 YouTube Downloader Backend v4.0")
    print("=" * 60)
    print(f"🚀 Server running on: http://0.0.0.0:{port}")
    print(f"🔑 YouTube API: {'✅ Configured' if YOUTUBE_API_KEY else '❌ Not configured'}")
    print(f"🎬 FFmpeg: {'✅ Available' if check_ffmpeg_installed() else '❌ Not found'}")
    print(f"📦 yt-dlp: v{yt_dlp.version.__version__}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)