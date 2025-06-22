from flask import Flask, render_template, request, Blueprint, flash, redirect, url_for
from youtube_client import config
from youtube_client import youtube_api # This now has the full parsing logic
import os
import subprocess # For yt-dlp
import re # For sanitizing filenames and extracting video ID
import threading # For asynchronous downloads

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

# Global in-memory queue for download tasks
# Each item: {'video_id': 'xxx', 'url': 'full_url', 'title': 'yyy',
#             'status': 'pending/downloading/completed/failed',
#             'progress': 0, # Will be tricky to implement with subprocess.run
#             'filepath': None, 'error_message': None, 'thread': None (optional: store thread object)}
download_queue = []
queue_lock = threading.Lock() # To ensure thread-safe access to the download_queue

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

# This route will now handle adding to queue and starting download thread
# It will also handle playing if already downloaded.
@main_bp.route('/process_video_request')
def process_video_request_route():
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

    # Expected file path for the final MP4
    expected_downloaded_file_path = os.path.join(TEMP_VIDEOS_DIR, f"{video_id}.mp4")
    video_static_path = f"{TEMP_VIDEOS_STATIC_PATH}/{video_id}.mp4" # Path for HTML src

    # 1. Check if already downloaded
    if os.path.exists(expected_downloaded_file_path):
        print(f"Video {video_id}.mp4 already downloaded. Redirecting to player.")
        return redirect(url_for('main.player_route', video_id=video_id, title=video_title_hint))

    # 2. Check if in queue (and not failed)
    with queue_lock:
        for item in download_queue:
            if item['video_id'] == video_id:
                if item['status'] == 'pending' or item['status'] == 'downloading':
                    flash(f"'{item['title']}' is already in the download queue ({item['status']}).", "info")
                    return redirect(request.referrer or url_for('main.index')) # Or redirect to queue page
                elif item['status'] == 'completed': # Should have been caught by file exists check
                    flash(f"'{item['title']}' was in queue as completed, playing now.", "info")
                    return render_template('play_video.html',
                                           video_file_url=url_for('static', filename=video_static_path),
                                           title=item['title'])
                # If 'failed', we allow re-queueing by falling through

    # 3. Add to queue and start download thread
    new_queue_item = {
        'video_id': video_id,
        'url': video_url,
        'title': video_title_hint,
        'status': 'pending', # Initial status
        'progress': 0,
        'filepath': None, # Will be set upon completion
        'error_message': None,
        'thread': None # Will hold the thread object
    }

    with queue_lock:
        # Remove any previous failed entry for this video_id before adding new one
        download_queue[:] = [item for item in download_queue if item['video_id'] != video_id or item['status'] != 'failed']
        download_queue.append(new_queue_item)

    # Placeholder for the actual worker function (to be implemented next)
    # def _download_video_worker(item_video_id, item_url, item_title):
    #    print(f"WORKER_PLACEHOLDER: Starting download for {item_title} ({item_video_id})")
    #    # Actual yt-dlp subprocess call will go here
    #    # Update status in download_queue (using queue_lock)
    #    pass

    # For now, let's define a simple placeholder worker directly or call a function that will be fully defined later
    # The actual _download_video_worker function will be complex, let's just start the thread
    # with a target function that will be defined in the next step.

    # We need to ensure _download_video_worker exists before starting a thread for it.
    # I will define a placeholder for it in this file for now.

    thread = threading.Thread(target=_download_video_worker_placeholder, args=(new_queue_item,))
    new_queue_item['thread'] = thread # Store thread if needed for management
    thread.start()

    flash(f"'{video_title_hint}' has been added to the download queue.", "success")
    # Redirect to a new queue page (to be created) or back to index/referrer
    # For now, redirect to index. Later, redirect to a /queue page.
    # thread = threading.Thread(target=_download_video_worker_placeholder, args=(new_queue_item,)) # Old placeholder target
    thread = threading.Thread(target=_download_video_worker, args=(new_queue_item,))
    new_queue_item['thread'] = thread
    thread.start()

    flash(f"'{video_title_hint}' has been added to the download queue.", "success")
    return redirect(url_for('main.queue_page_route'))


@main_bp.route('/queue')
def queue_page_route():
    # Make a copy of the queue for rendering to avoid issues if modified during render
    # although direct iteration should be fine with the lock for status updates.
    # For simplicity, direct access with lock during iteration is also an option for templates.
    # However, passing a snapshot is safer.
    with queue_lock:
        current_queue_snapshot = list(download_queue) # Shallow copy
    return render_template('queue.html', download_queue=current_queue_snapshot)

@main_bp.route('/player/<video_id>')
def player_route(video_id):
    # This route assumes the video is already downloaded.
    video_title_hint = request.args.get('title', video_id) # Get title from query param or use ID
    expected_downloaded_file_path = os.path.join(TEMP_VIDEOS_DIR, f"{video_id}.mp4")
    video_static_path = f"{TEMP_VIDEOS_STATIC_PATH}/{video_id}.mp4"

    if os.path.exists(expected_downloaded_file_path):
        return render_template('play_video.html',
                               video_file_url=url_for('static', filename=video_static_path),
                               title=video_title_hint)
    else:
        flash(f"Cannot play '{video_title_hint}'. File not found. Please try adding to queue again.", "error")
        return redirect(url_for('main.queue_page_route'))


def _download_video_worker(queue_item):
    video_id = queue_item['video_id']
    video_url = queue_item['url']
    video_title = queue_item['title'] # Original title hint

    # Update status to 'downloading'
    with queue_lock:
        for item in download_queue:
            if item['video_id'] == video_id:
                item['status'] = 'downloading'
                # Potentially clear previous error message if retrying
                item['error_message'] = None
                break

    print(f"WORKER: Starting download for '{video_title}' ({video_id}). URL: {video_url}")

    output_filename_template = os.path.join(TEMP_VIDEOS_DIR, f"{video_id}.%(ext)s")
    expected_downloaded_file_path = os.path.join(TEMP_VIDEOS_DIR, f"{video_id}.mp4")

    final_status = 'failed' # Default to failed
    error_msg_details = "Download did not complete as expected." # Default error

    try:
        ffmpeg_dir_path = os.path.dirname(os.path.abspath(__file__))
        cookie_file_abs_path = os.path.abspath(config.COOKIE_FILE_PATH)

        if not os.path.exists(cookie_file_abs_path):
            print(f"WORKER: Cookie file not found at {cookie_file_abs_path} for video {video_id}. Download may fail for restricted content.")
            # Decide if you want to proceed without cookies or fail early
            # For now, proceed, yt-dlp will try without.

        command = [
            'yt-dlp',
            # Only add --cookies if the file exists, otherwise yt-dlp might error on missing file
            *(['--cookies', cookie_file_abs_path] if os.path.exists(cookie_file_abs_path) else []),
            '--ffmpeg-location', ffmpeg_dir_path,
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '-o', output_filename_template,
            '--no-playlist',
            '--force-overwrites', # Overwrite if previous partial download exists for this video_id
            # '--no-warnings', # Suppress yt-dlp warnings if too noisy, but usually helpful
            # Consider adding --write-info-json to get metadata like actual title if needed
            video_url
        ]

        print(f"WORKER: yt-dlp command for {video_id}: {' '.join(command)}")

        TIMEOUT_SECONDS = 600 # Increased timeout to 10 minutes for potentially larger files
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', timeout=TIMEOUT_SECONDS)

        if result.returncode == 0:
            if os.path.exists(expected_downloaded_file_path):
                print(f"WORKER: Download successful for {video_id}. File: {expected_downloaded_file_path}")
                final_status = 'completed'
                queue_item['filepath'] = expected_downloaded_file_path
                # Update title in queue if yt-dlp provides a better one (e.g. from --write-info-json)
                # For now, keep original title_hint.
            else:
                error_msg_details = f"yt-dlp exited successfully but expected file {video_id}.mp4 not found. stdout: {result.stdout}, stderr: {result.stderr}"
                print(f"WORKER ERROR for {video_id}: {error_msg_details}")
        else:
            error_msg_details = f"yt-dlp failed. stderr: {result.stderr or result.stdout}"
            print(f"WORKER ERROR for {video_id}: {error_msg_details}")
            # Log full output for debugging specific yt-dlp issues
            # print(f"WORKER {video_id} yt-dlp stdout: {result.stdout}")
            # print(f"WORKER {video_id} yt-dlp stderr: {result.stderr}")


    except FileNotFoundError: # yt-dlp or ffmpeg not found
        error_msg_details = "yt-dlp command or ffmpeg not found. Ensure they are installed and in PATH or configured correctly."
        print(f"WORKER ERROR for {video_id}: {error_msg_details}")
    except subprocess.TimeoutExpired:
        error_msg_details = "Download command timed out."
        print(f"WORKER ERROR for {video_id}: {error_msg_details}")
    except Exception as e:
        error_msg_details = f"An unexpected error occurred in worker: {str(e)}"
        print(f"WORKER ERROR for {video_id}: {error_msg_details}")

    # Final update to the queue item
    with queue_lock:
        for item in download_queue:
            if item['video_id'] == video_id:
                item['status'] = final_status
                if final_status == 'failed':
                    item['error_message'] = error_msg_details
                # 'filepath' is set directly in queue_item if successful
                break
    print(f"WORKER: Finished processing for '{video_title}' ({video_id}). Status: {final_status}")


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
