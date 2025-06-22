from flask import Flask, render_template, request, Blueprint, flash, redirect, url_for
from youtube_client import config
from youtube_client import youtube_api
from youtube_client import database
from youtube_client import cookie_processor
import os
import subprocess
import re
import threading
import time
import filecmp # For comparing file content

# --- Global variables related to app state ---
_global_app_initialized = False
# Flag to indicate if operational cookies are present and considered valid after startup checks
# This will be used to decide if the cookie polling thread needs to run.
_operational_cookies_ready = False
_cookie_polling_thread = None # To hold the reference to the polling thread

# --- User Specific Hardcoded Paths (as requested for now) ---
# This should eventually be moved to a user-editable config file or DB setting
USER_COOKIE_DOWNLOAD_PATH = "C:/Users/artur/Downloads/www.youtube.com_cookies.txt" # Use forward slashes for better cross-platform Python string handling, os.path will normalize.

def are_files_identical(file1_path, file2_path):
    """Compares two files by content. Returns True if identical, False otherwise."""
    if not os.path.exists(file1_path) or not os.path.exists(file2_path):
        return False
    return filecmp.cmp(file1_path, file2_path, shallow=False)

def check_operational_cookie_file_validity(operational_cookie_file_abs_path):
    """Checks if the operational cookie file exists and is not empty or just comments."""
    if not os.path.exists(operational_cookie_file_abs_path):
        return False
    try:
        with open(operational_cookie_file_abs_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content: # Empty
                return False
            # Check if it's only comments (very basic check)
            lines = [line for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
            if not lines: # Only comments or blank lines
                return False
        return True # Has some non-comment content
    except Exception:
        return False # Error reading or other issues

def _cookie_polling_worker_func():
    """Polls the source cookie path until a file appears, then processes it."""
    global _operational_cookies_ready
    source_path_to_poll = os.path.normpath(USER_COOKIE_DOWNLOAD_PATH) # Normalize path
    operational_cookie_file_abs_path = os.path.abspath(config.COOKIE_FILE_PATH)

    print(f"COOKIE_POLLER_THREAD: Started. Polling '{source_path_to_poll}' every 1 second for new cookies.")
    while not _operational_cookies_ready: # Loop until operational cookies are ready
        if os.path.exists(source_path_to_poll):
            print(f"COOKIE_POLLER_THREAD: New cookie file detected at '{source_path_to_poll}'. Processing...")
            if cookie_processor.process_new_cookie_file(source_path_to_poll, operational_cookie_file_abs_path):
                print(f"COOKIE_POLLER_THREAD: Successfully processed new cookie file. Operational cookies updated.")
                try:
                    os.remove(source_path_to_poll)
                    print(f"COOKIE_POLLER_THREAD: Source cookie file '{source_path_to_poll}' deleted.")
                except OSError as e:
                    print(f"COOKIE_POLLER_THREAD: Error deleting source cookie file '{source_path_to_poll}': {e}")
                _operational_cookies_ready = True # Signal that cookies are now ready
                print("COOKIE_POLLER_THREAD: Operational cookies now ready. Polling will stop.")
                # Thread will exit as _operational_cookies_ready is True
            else:
                print(f"COOKIE_POLLER_THREAD: Failed to process new cookie file from '{source_path_to_poll}'. Will retry.")
                # Optional: delete corrupt source file if processing fails consistently? For now, it will just keep trying.
        time.sleep(1)
    print("COOKIE_POLLER_THREAD: Exiting.")


def handle_cookie_update_on_startup():
    """Checks for a new cookie file at a user-defined path and processes it."""
    global _operational_cookies_ready, _cookie_polling_thread

    print("STARTUP_COOKIE_CHECK: Initiated.")
    source_cookie_path_abs = os.path.normpath(USER_COOKIE_DOWNLOAD_PATH) # Normalize path
    operational_cookie_file_abs_path = os.path.abspath(config.COOKIE_FILE_PATH)

    source_exists = os.path.exists(source_cookie_path_abs)
    operational_exists_and_valid = check_operational_cookie_file_validity(operational_cookie_file_abs_path)

    if source_exists:
        if operational_exists_and_valid and are_files_identical(source_cookie_path_abs, operational_cookie_file_abs_path):
            print(f"STARTUP_COOKIE_CHECK: New cookie file at '{source_cookie_path_abs}' is identical to the operational one.")
            print("STARTUP_COOKIE_CHECK: Deleting both identical cookie files as per requirement.")
            try:
                os.remove(source_cookie_path_abs)
                print(f"STARTUP_COOKIE_CHECK: Deleted source cookie file: '{source_cookie_path_abs}'.")
            except OSError as e:
                print(f"STARTUP_COOKIE_CHECK: Error deleting source cookie file '{source_cookie_path_abs}': {e}")
            try:
                os.remove(operational_cookie_file_abs_path)
                print(f"STARTUP_COOKIE_CHECK: Deleted operational cookie file: '{operational_cookie_file_abs_path}'.")
            except OSError as e:
                print(f"STARTUP_COOKIE_CHECK: Error deleting operational cookie file '{operational_cookie_file_abs_path}': {e}")

            _operational_cookies_ready = False
            print(f"STARTUP_COOKIE_CHECK: Action required: Please provide a new cookie file at '{source_cookie_path_abs}'.")

        else: # Source exists and is different, or operational doesn't exist/is invalid
            print(f"STARTUP_COOKIE_CHECK: New/different cookie file found at '{source_cookie_path_abs}'. Processing...")
            if cookie_processor.process_new_cookie_file(source_cookie_path_abs, operational_cookie_file_abs_path):
                print(f"STARTUP_COOKIE_CHECK: Successfully processed. Operational cookies at '{operational_cookie_file_abs_path}' updated.")
                try:
                    os.remove(source_cookie_path_abs) # Always delete source after successful processing
                    print(f"STARTUP_COOKIE_CHECK: Source cookie file '{source_cookie_path_abs}' deleted.")
                except OSError as e:
                    print(f"STARTUP_COOKIE_CHECK: Error deleting source cookie file '{source_cookie_path_abs}': {e}")
                _operational_cookies_ready = check_operational_cookie_file_validity(operational_cookie_file_abs_path)
            else:
                print(f"STARTUP_COOKIE_CHECK: Failed to process new cookie file from '{source_cookie_path_abs}'.")
                _operational_cookies_ready = check_operational_cookie_file_validity(operational_cookie_file_abs_path) # Check current operational

    else: # Source does not exist
        print(f"STARTUP_COOKIE_CHECK: No new cookie file found at '{source_cookie_path_abs}'.")
        _operational_cookies_ready = check_operational_cookie_file_validity(operational_cookie_file_abs_path)
        if not _operational_cookies_ready:
            print(f"STARTUP_COOKIE_CHECK: Action required: Operational cookies not ready. Please provide a cookie file at '{source_cookie_path_abs}'.")

    if not _operational_cookies_ready:
        print("STARTUP_COOKIE_CHECK: Operational cookies are not ready. Starting background poller for new cookies.")
        if _cookie_polling_thread is None or not _cookie_polling_thread.is_alive():
            _cookie_polling_thread = threading.Thread(target=_cookie_polling_worker_func, daemon=True)
            _cookie_polling_thread.start()
        else:
            print("STARTUP_COOKIE_CHECK: Cookie poller thread already running.")
    else:
        print(f"STARTUP_COOKIE_CHECK: Operational cookies are ready. Using: '{operational_cookie_file_abs_path}'")


main_bp = Blueprint('main', __name__, template_folder='templates', static_folder='static')
TEMP_VIDEOS_STATIC_PATH = 'temp_videos'
TEMP_VIDEOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', TEMP_VIDEOS_STATIC_PATH)

@main_bp.route('/')
def index():
    videos = youtube_api.get_homepage_videos_parsed()
    if not videos and not _operational_cookies_ready:
         flash("Cookies not loaded. Please place your cookies.txt file at " + USER_COOKIE_DOWNLOAD_PATH, "warning")
    elif not videos and _operational_cookies_ready: # Cookies loaded but no videos
        flash("Could not fetch homepage videos. Cookies might be invalid or YouTube structure changed.", "warning")
    return render_template('index.html', videos=videos)

# ... (rest of the app.py code from previous correct version: search, sanitize_filename, get_video_id, process_video_request_route, queue_page_route, player_route, _download_video_worker)
# For brevity, I'm not repeating the routes that don't change in this step,
# but they should be assumed to be present from the previous correct state of app.py.
# The create_app and app = create_app() and if __name__ == '__main__' blocks also remain.
# The key is the new functions and the modified startup sequence within create_app().

@main_bp.route('/search')
def search():
    query = request.args.get('q', '')
    if not query:
        flash("Please enter a search query.", "info")
        return redirect(url_for('main.index'))
    videos = youtube_api.search_videos_parsed(query)
    if not videos:
        flash(f"No results found for '{query}'.", "info")
    return render_template('search_results.html', videos=videos, query=query)

def sanitize_filename(name):
    name = re.sub(r'[\\/*?:"<>|]',"", name)
    name = name.replace(" ", "_")
    return name[:100]

def get_video_id(url):
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

@main_bp.route('/process_video_request')
def process_video_request_route():
    video_url = request.args.get('url')
    video_title_hint = request.args.get('title', 'video')
    thumbnail_url_hint = request.args.get('thumbnail')

    if not video_url:
        flash("Error: No video URL provided.", "error")
        return redirect(url_for('main.index'))

    video_id = get_video_id(video_url)
    if not video_id:
        flash(f"Error: Could not extract Video ID from URL: {video_url}", "error")
        return redirect(url_for('main.index'))

    expected_downloaded_file_path = os.path.join(TEMP_VIDEOS_DIR, f"{video_id}.mp4")
    db_video_item = database.get_video_by_id(video_id)

    if db_video_item and db_video_item['status'] == 'completed' and \
       db_video_item['filepath'] and os.path.exists(db_video_item['filepath']):
        print(f"Video {video_id} already downloaded and in DB. Redirecting to player.")
        return redirect(url_for('main.player_route', video_id=video_id, title=db_video_item['title']))

    if os.path.exists(expected_downloaded_file_path):
        print(f"Video {video_id}.mp4 found on disk. Ensuring DB consistency and redirecting to player.")
        if not db_video_item:
            database.add_video_to_queue(video_id, video_url, video_title_hint, thumbnail_url_hint)
        database.update_video_status(video_id, 'completed', filepath=expected_downloaded_file_path)
        updated_db_item = database.get_video_by_id(video_id)
        display_title = updated_db_item['title'] if updated_db_item else video_title_hint
        return redirect(url_for('main.player_route', video_id=video_id, title=display_title))

    if db_video_item and db_video_item['status'] in ['pending', 'queued', 'downloading']:
        flash(f"'{db_video_item['title']}' is already in the download queue ({db_video_item['status']}).", "info")
        return redirect(url_for('main.queue_page_route'))

    added_or_updated = database.add_video_to_queue(video_id, video_url, video_title_hint, thumbnail_url_hint)

    if added_or_updated:
        thread = threading.Thread(target=_download_video_worker, args=(video_id,))
        thread.start()
        flash(f"'{video_title_hint}' has been added/updated in the download queue.", "success")
    else:
        flash(f"'{video_title_hint}' is already processed or in queue with a non-failed status.", "info")

    return redirect(url_for('main.queue_page_route'))

@main_bp.route('/queue')
def queue_page_route():
    current_queue = database.get_queued_videos()
    return render_template('queue.html', download_queue=current_queue)

@main_bp.route('/player/<video_id>')
def player_route(video_id):
    video_item_db = database.get_video_by_id(video_id)

    if video_item_db and video_item_db['filepath'] and os.path.exists(video_item_db['filepath']):
        video_file_for_static_url = os.path.basename(video_item_db['filepath'])
        video_static_path_constructed = f"{TEMP_VIDEOS_STATIC_PATH}/{video_file_for_static_url}"

        return render_template('play_video.html',
                               video_file_url=url_for('static', filename=video_static_path_constructed),
                               title=video_item_db['title'])
    else:
        flash(f"Cannot play video {video_id}. File not found or not in database correctly.", "error")
        if video_item_db:
             database.update_video_status(video_id, 'failed', error_message="File missing or status incorrect for playback.")
        return redirect(url_for('main.queue_page_route'))

def _download_video_worker(item_video_id):
    try:
        video_item = database.get_video_by_id(item_video_id)
        if not video_item:
            print(f"WORKER: Video {item_video_id} not found in DB when worker started. Aborting.")
            return

        if video_item['status'] not in ['pending', 'queued']:
            print(f"WORKER: Video {item_video_id} status is '{video_item['status']}', not 'pending'/'queued'. Aborting.")
            return

        video_url = video_item['youtube_url']
        video_title = video_item['title']
        database.update_video_status(item_video_id, 'downloading')
    except Exception as e_db_initial:
        print(f"WORKER: DB error fetching/updating item {item_video_id} at start: {e_db_initial}")
        try:
            database.update_video_status(item_video_id, 'failed', error_message=f"DB error at worker start: {str(e_db_initial)}")
        except Exception: pass
        return

    print(f"WORKER: Starting download for '{video_title}' ({item_video_id}). URL: {video_url}")

    output_filename_template = os.path.join(TEMP_VIDEOS_DIR, f"{item_video_id}.%(ext)s")
    expected_downloaded_file_path = os.path.join(TEMP_VIDEOS_DIR, f"{item_video_id}.mp4")

    final_status = 'failed'
    error_msg_details = "Download did not complete as expected."
    actual_filepath = None

    try:
        ffmpeg_dir_path = os.path.dirname(os.path.abspath(__file__))
        cookie_file_abs_path = os.path.abspath(config.COOKIE_FILE_PATH) # This is the operational cookie file

        if not check_operational_cookie_file_validity(cookie_file_abs_path): # Check if operational cookies are valid before use
            print(f"WORKER: Operational cookie file '{cookie_file_abs_path}' is missing or invalid for video {item_video_id}. Download may fail or use no cookies.")
            # yt-dlp will proceed without --cookies if the file isn't passed or is empty.
            # No explicit 'else' needed for command construction, it handles empty list for cookies arg.

        command = [
            'yt-dlp',
            *(['--cookies', cookie_file_abs_path] if check_operational_cookie_file_validity(cookie_file_abs_path) else []),
            '--ffmpeg-location', ffmpeg_dir_path,
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '-o', output_filename_template,
            '--no-playlist',
            '--force-overwrites',
            video_url
        ]

        print(f"WORKER: yt-dlp command for {item_video_id}: {' '.join(command)}")

        TIMEOUT_SECONDS = 600
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', timeout=TIMEOUT_SECONDS)

        if result.returncode == 0:
            if os.path.exists(expected_downloaded_file_path):
                print(f"WORKER: Download successful for {item_video_id}. File: {expected_downloaded_file_path}")
                final_status = 'completed'
                actual_filepath = expected_downloaded_file_path
            else:
                error_msg_details = f"yt-dlp exited successfully but expected file {item_video_id}.mp4 not found. stdout: {result.stdout}, stderr: {result.stderr}"
                print(f"WORKER ERROR for {item_video_id}: {error_msg_details}")
        else:
            error_msg_details = f"yt-dlp failed. stderr: {result.stderr or result.stdout}"
            print(f"WORKER ERROR for {item_video_id}: {error_msg_details}")

    except FileNotFoundError:
        error_msg_details = "yt-dlp command or ffmpeg not found."
        print(f"WORKER ERROR for {item_video_id}: {error_msg_details}")
    except subprocess.TimeoutExpired:
        error_msg_details = "Download command timed out."
        print(f"WORKER ERROR for {item_video_id}: {error_msg_details}")
    except Exception as e:
        error_msg_details = f"An unexpected error occurred in worker's download part: {str(e)}"
        print(f"WORKER ERROR for {item_video_id}: {error_msg_details}")

    try:
        database.update_video_status(item_video_id, final_status, filepath=actual_filepath, error_message=error_msg_details if final_status == 'failed' else None)
    except Exception as e_db_final:
        print(f"WORKER: DB error updating item {item_video_id} at end: {e_db_final}")

    print(f"WORKER: Finished processing for '{video_title}' ({item_video_id}). Status: {final_status}")

def create_app():
    global _global_app_initialized, _operational_cookies_ready, _cookie_polling_thread

    current_app = Flask(__name__, static_folder='static', template_folder='templates')
    current_app.config.from_object(config)
    current_app.register_blueprint(main_bp)

    if not _global_app_initialized:
        with current_app.app_context():
            print("STARTUP: Initializing DB and Startup Routines (within create_app)...")
            database.init_db()
            print(f"Database initialized at: {database.DATABASE_PATH}")

            # Create TEMP_VIDEOS_DIR before cookie handler might try to use it (though it doesn't)
            if not os.path.exists(TEMP_VIDEOS_DIR):
                try:
                    os.makedirs(TEMP_VIDEOS_DIR)
                    print(f"Created temporary videos directory: {TEMP_VIDEOS_DIR}")
                except Exception as e:
                    print(f"Error creating temporary videos directory {TEMP_VIDEOS_DIR}: {e}")

            handle_cookie_update_on_startup() # This function now updates _operational_cookies_ready

        _global_app_initialized = True
        print("STARTUP: Initialization complete.")

    return current_app

app = create_app()

if __name__ == '__main__':
    print(f"Starting Flask app directly via __main__. Ensure CWD is project root: {os.getcwd()}")
    app.run(debug=True, port=5001)
