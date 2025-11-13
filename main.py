from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import re
import shutil

# ✅ Add FFmpeg to PATH
os.environ["PATH"] += os.pathsep + r"C:\Users\kalai kumar\Downloads\ffmpeg-8.0-essentials_build\ffmpeg-8.0-essentials_build\bin"

app = Flask(__name__)
CORS(app)

# Temporary download directory
TEMP_DOWNLOAD_PATH = tempfile.gettempdir()

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)

def check_ffmpeg_installed():
    """Check if FFmpeg is available in PATH"""
    return shutil.which("ffmpeg") is not None

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "message": "Backend server is running",
        "ffmpeg": check_ffmpeg_installed()
    }), 200

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    """Fetch video metadata without downloading"""
    try:
        data = request.get_json()
        url = data.get("url")

        if not url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Format duration
            duration_seconds = info.get('duration', 0)
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            duration_str = f"{minutes}:{seconds:02d}"

            # Format views
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
                "duration": duration_str,
                "views": views_str,
                "description": (info.get('description', '')[:200] + '...')
                if info.get('description') else ''
            }

            return jsonify({"success": True, "info": video_info}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    """Download video/audio and stream it to client"""
    temp_file = None
    try:
        # ✅ Ensure FFmpeg is installed
        if not check_ffmpeg_installed():
            return jsonify({"error": "FFmpeg not found in PATH"}), 500

        data = request.get_json()
        url = data.get("url")
        download_type = data.get("type", "video")  # 'video' or 'audio'
        quality = data.get("quality", "highest")

        if not url:
            return jsonify({"error": "URL is required"}), 400

        temp_filename = f"temp_{os.urandom(8).hex()}"

        ydl_opts = {
            'outtmpl': os.path.join(TEMP_DOWNLOAD_PATH, f'{temp_filename}.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }

        if download_type == "audio":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192' if quality == 'bestaudio' else '128',
                }],
            })
        else:
            if quality == "highest":
                ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            elif quality == "high":
                ydl_opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
            elif quality == "medium":
                ydl_opts['format'] = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best'
            elif quality == "lowest":
                ydl_opts['format'] = 'worstvideo[ext=mp4]+worstaudio[ext=m4a]/worst[ext=mp4]/worst'
            else:
                ydl_opts['format'] = 'best[ext=mp4]/best'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = sanitize_filename(info.get('title', 'video'))

            expected_ext = 'mp3' if download_type == 'audio' else 'mp4'
            temp_file = os.path.join(TEMP_DOWNLOAD_PATH, f'{temp_filename}.{expected_ext}')

            if not os.path.exists(temp_file):
                for f in os.listdir(TEMP_DOWNLOAD_PATH):
                    if f.startswith(temp_filename):
                        temp_file = os.path.join(TEMP_DOWNLOAD_PATH, f)
                        break

        if not os.path.exists(temp_file):
            return jsonify({"error": "Downloaded file not found"}), 500

        download_filename = f"{title}.{expected_ext}"

        def generate():
            with open(temp_file, 'rb') as f:
                while chunk := f.read(8192):
                    yield chunk
            try:
                os.remove(temp_file)
            except:
                pass

        response = Response(generate(), mimetype='application/octet-stream')
        response.headers['Content-Disposition'] = f'attachment; filename="{download_filename}"'
        try:
            response.headers['Content-Length'] = str(os.path.getsize(temp_file))
        except:
            pass

        return response

    except Exception as e:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("X_ZOHO_CATALYST_LISTEN_PORT", 5000))
    print(f"✅ YouTube Downloader Backend running on port {port}")
    print(f"FFmpeg Installed: {check_ffmpeg_installed()}")
    app.run(host='0.0.0.0', port=port, debug=False)
