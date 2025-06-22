from flask import Flask, render_template, request, Blueprint, flash, redirect, url_for
from youtube_client import config
from youtube_client import youtube_api # This now has the full parsing logic
import os
import subprocess # For yt-dlp
import re # For sanitizing filenames and extracting video ID

# print(f"app.py (full) loaded, config.SECRET_KEY: {config.SECRET_KEY}") # Debug
# print(f"app.py (full) loaded, youtube_api: {youtube_api}") # Debug

# Using Blueprint for better organization
# Ensure template_folder is correctly specified if not in default location relative to blueprint
main_bp = Blueprint('main', __name__, template_folder='templates', static_folder='static')

# This will be used by downloader later, ensure it's defined
# Path is relative to this app.py file, then one up to project root, then into 'downloads'
# DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'downloads') # For old downloader

# New temporary directory for videos to be played
# Inside youtube_client/static/ so they are web-accessible
TEMP_VIDEOS_STATIC_PATH = 'temp_videos' # Relative to static folder
TEMP_VIDEOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', TEMP_VIDEOS_STATIC_PATH)

if not os.path.exists(TEMP_VIDEOS_DIR):
    try:
        os.makedirs(TEMP_VIDEOS_DIR)
        print(f"Created temporary videos directory: {TEMP_VIDEOS_DIR}")
    except Exception as e:
        print(f"Error creating temporary videos directory {TEMP_VIDEOS_DIR}: {e}")
        # This could be critical for the play_video functionality

@main_bp.route('/')
def index():
    # print("Attempting to fetch homepage videos for Flask app...") # Debug
    # Use the renamed functions from the restored youtube_api.py
    videos = youtube_api.get_homepage_videos_parsed()
    if not videos:
        # print("No videos returned from youtube_api.get_homepage_videos_parsed()") # Debug
        flash("Could not fetch homepage videos. Check cookies and console output.", "warning")
    # else:
        # print(f"Successfully fetched {len(videos)} video(s) for homepage.") # Debug
    return render_template('index.html', videos=videos)

@main_bp.route('/search')
def search():
    query = request.args.get('q', '')
    if not query:
        flash("Please enter a search query.", "info")
        return redirect(url_for('main.index'))

    # print(f"Attempting to search videos for query: '{query}' in Flask app...") # Debug
    videos = youtube_api.search_videos_parsed(query)
    if not videos:
        # print(f"No videos returned from youtube_api.search_videos_parsed() for query '{query}'.") # Debug
        flash(f"No results found for '{query}'.", "info")
    # else:
        # print(f"Successfully fetched {len(videos)} video(s) for search query '{query}'.") # Debug
    return render_template('search_results.html', videos=videos, query=query)

def sanitize_filename(name):
    """Remove characters that are problematic for filenames."""
    name = re.sub(r'[\\/*?:"<>|]',"", name) # Remove illegal characters
    name = name.replace(" ", "_") # Replace spaces with underscores
    return name[:100] # Limit length

def get_video_id(url):
    """Extracts YouTube video ID from URL."""
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/v\/([a-zA-Z0-9_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

@main_bp.route('/play_video')
def play_video_route():
    video_url = request.args.get('url')
    video_title_hint = request.args.get('title', 'video') # Optional title hint for filename

    if not video_url:
        flash("Error: No video URL provided for playback.", "error")
        return redirect(url_for('main.index'))

    video_id = get_video_id(video_url)
    if not video_id:
        flash(f"Error: Could not extract Video ID from URL: {video_url}", "error")
        return redirect(url_for('main.index'))

    # Use Video ID for a somewhat unique filename, sanitize title hint for more readability
    sanitized_title = sanitize_filename(video_title_hint)
    # Filename will be like: VideoID_SanitizedTitle.mp4
    # We'll let yt-dlp determine the extension, then rename if needed, or just use a fixed one.
    # For simplicity, let's aim for mp4 and name it VideoID.mp4

    # Using only video_id for filename to ensure uniqueness and avoid issues with long/special titles
    # The output template of yt-dlp will handle the actual extension.
    # We want the file to be named like 'VIDEOID.mp4' in our temp_videos folder.
    # yt-dlp's -o template can use %(id)s.

    # Define the output file path (e.g., static/temp_videos/VIDEOID.mp4)
    # yt-dlp will determine the actual extension, we want to control the name part.
    # Let's make the target filename fixed as VIDEO_ID.mp4 for simplicity in linking.
    # yt-dlp can transcode to mp4 if needed.

    # Output filename template for yt-dlp
    # This will save as VIDEO_ID.mp4 (or whatever extension yt-dlp chooses if mp4 merge fails)
    # We will then construct the link to this specific filename.
    output_filename_template = os.path.join(TEMP_VIDEOS_DIR, f"{video_id}.%(ext)s")
    # The actual file that will be created by yt-dlp (e.g. VIDEO_ID.mp4)
    # We need to know this to serve it. Forcing mp4 for HTML5 video player.
    expected_downloaded_file_path = os.path.join(TEMP_VIDEOS_DIR, f"{video_id}.mp4")
    video_static_path = f"{TEMP_VIDEOS_STATIC_PATH}/{video_id}.mp4" # Path for HTML src

    # Check if the MP4 file already exists
    if os.path.exists(expected_downloaded_file_path):
        print(f"Video {video_id}.mp4 already downloaded. Serving existing file.")
        return render_template('play_video.html', video_file_url=url_for('static', filename=video_static_path), title=video_title_hint)

    print(f"Attempting to download video: {video_url} for playback.")
    flash(f"Downloading '{video_title_hint}'... Please wait. This may take a moment.", "info")

    # Force redirect to show flash message before blocking download starts
    # This is a common pattern but a full solution often needs JS or async tasks.
    # For now, the user experience won't be ideal as the page will hang.
    # A better way is to have a separate "loading" page or JS polling.
    # Let's try to render a temporary "downloading" page.

    # This is a synchronous download. The page will appear to hang.
    try:
        # Construct path to ffmpeg assuming it's in the same directory as app.py (youtube_client/)
        # This path needs to point to the DIRECTORY containing ffmpeg.exe and ffprobe.exe
        ffmpeg_dir_path = os.path.dirname(os.path.abspath(__file__))
        # User provided: "C:\Users\artur\Desktop\Youtube\youtube_client\ffmpeg.exe"
        # So, ffmpeg_dir_path should indeed be the 'youtube_client' directory.

        command = [
            'yt-dlp',
            '--ffmpeg-location', ffmpeg_dir_path,
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', # Request MP4
            '--merge-output-format', 'mp4', # Ensure output is mp4
            '-o', output_filename_template, # Save as VIDEO_ID.ext (yt-dlp determines ext)
            '--no-playlist',
            video_url
        ]
        print(f"DEBUG: yt-dlp command: {' '.join(command)}") # Debugging the command

        TIMEOUT_SECONDS = 300 # 5 minutes
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', timeout=TIMEOUT_SECONDS)

        if result.returncode == 0:
            # yt-dlp might have chosen a different extension if mp4 wasn't possible directly.
            # We need to find the actual downloaded file.
            # The output_filename_template uses %(ext)s.
            # We need to find what file was actually created.
            actual_downloaded_file = None
            # A bit of a hack: list files in temp_dir that start with video_id
            for f_name in os.listdir(TEMP_VIDEOS_DIR):
                if f_name.startswith(video_id + "."):
                    # If we forced mp4, this should be video_id.mp4
                    if f_name == f"{video_id}.mp4":
                        actual_downloaded_file = os.path.join(TEMP_VIDEOS_DIR, f_name)
                        break
                    # Fallback if it's not mp4 for some reason (shouldn't happen with --merge-output-format mp4)
                    # In a more robust scenario, we'd handle this better.
                    # For now, we strictly expect video_id.mp4 due to the command.

            if os.path.exists(expected_downloaded_file_path):
                print(f"Download complete: {expected_downloaded_file_path}")
                flash(f"'{video_title_hint}' downloaded. Now playing.", "success")
                return render_template('play_video.html', video_file_url=url_for('static', filename=video_static_path), title=video_title_hint)
            else:
                flash(f"Download completed but expected file {video_id}.mp4 not found. Output: {result.stdout} Stderr: {result.stderr}", "error")
                return redirect(url_for('main.index'))

        else:
            flash(f"Download failed for '{video_title_hint}'. Error: {result.stderr or result.stdout}", "error")
            print(f"yt-dlp stdout: {result.stdout}")
            print(f"yt-dlp stderr: {result.stderr}")
            return redirect(url_for('main.index'))

    except FileNotFoundError:
        flash("Error: yt-dlp command not found. Is it installed and in PATH?", "error")
    except subprocess.TimeoutExpired:
        flash(f"Download for '{video_title_hint}' timed out.", "error")
    except Exception as e:
        flash(f"An unexpected error occurred during download: {str(e)}", "error")

    return redirect(url_for('main.index'))


def create_app():
    # The Flask app instance. Note: static_folder and template_folder here
    # are relative to the app's root_path (usually where app.py is).
    # Blueprints can have their own template/static folders.
    # If your templates/static are inside youtube_client/, this should be fine.
    current_app = Flask(__name__, static_folder='static', template_folder='templates')

    # Load configuration from config.py
    current_app.config.from_object(config) # This loads SECRET_KEY etc.

    current_app.register_blueprint(main_bp) # url_prefix='/' is default

    return current_app

# This is the global app object that `python -m youtube_client.app` will look for by default
# if it doesn't find a `create_app` factory. Or, Flask CLI can be told to use create_app.
# For simplicity with `python -m`, providing `app` directly can work.
# However, using a factory `create_app()` is generally better practice.
# Let's ensure Flask CLI can find it if `FLASK_APP=youtube_client.app` is used.
# The `python -m youtube_client.app` command might need the app object directly
# or might execute this file and then look for `app`.
# The `if __name__ == '__main__':` block handles direct execution.
app = create_app()

if __name__ == '__main__':
    # This allows running the app directly with `python youtube_client/app.py`
    # (though `python -m youtube_client.app` is preferred from project root).
    # The create_app() call above already creates the app instance.
    print(f"Starting Flask app. Ensure CWD is project root for cookie file if using relative path: {os.getcwd()}")
    print(f"Cookie file path configured as: {config.COOKIE_FILE_PATH}")
    app.run(debug=True, port=5001)
