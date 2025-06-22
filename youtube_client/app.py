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

# Global flag to ensure startup routines run only once
_global_app_initialized = False

def handle_cookie_update_on_startup():
    """Checks for a new cookie file as per settings and processes it."""
    print("STARTUP: Checking for new cookie file...")
    source_path_setting = database.get_setting('cookie_source_path', 'new_cookies.txt')
    delete_source = database.get_setting('delete_source_cookie', False)

    abs_source_path = os.path.abspath(source_path_setting)
    operational_cookie_file = os.path.abspath(config.COOKIE_FILE_PATH)

    if os.path.exists(abs_source_path):
        print(f"STARTUP: New cookie file found at '{abs_source_path}'. Processing...")
        if cookie_processor.process_new_cookie_file(abs_source_path, operational_cookie_file):
            print(f"STARTUP: Successfully processed new cookie file. Operational cookies at '{operational_cookie_file}' updated.")
            if delete_source:
                try:
                    os.remove(abs_source_path)
                    print(f"STARTUP: Source cookie file '{abs_source_path}' deleted as per setting.")
                except OSError as e:
                    print(f"STARTUP: Error deleting source cookie file '{abs_source_path}': {e}")
        else:
            print(f"STARTUP: Failed to process new cookie file from '{abs_source_path}'. Using existing operational cookies if available.")
    else:
        print(f"STARTUP: No new cookie file found at '{abs_source_path}'. Using existing operational cookies if available.")

    if not os.path.exists(operational_cookie_file):
        print(f"WARNING: Operational cookie file '{operational_cookie_file}' does not exist. Application may not have cookies for YouTube.")
    else:
        print(f"STARTUP: Using operational cookie file: '{operational_cookie_file}'")

main_bp = Blueprint('main', __name__, template_folder='templates', static_folder='static')

TEMP_VIDEOS_STATIC_PATH = 'temp_videos'
TEMP_VIDEOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', TEMP_VIDEOS_STATIC_PATH)

@main_bp.route('/')
def index():
    videos = youtube_api.get_homepage_videos_parsed()
    if not videos:
        flash("Could not fetch homepage videos. Check cookies and console output.", "warning")
    return render_template('index.html', videos=videos)

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
        # Ensure Flask app context for operations that might need it (e.g., config access)
        # This is more robust if worker uses app config or extensions.
        # For current direct config import and os calls, it might not be strictly necessary,
        # but good practice if the worker evolves.
        # However, creating a new app context in a thread requires care.
        # Simpler for now: assume worker has all info or can access config directly.
        # with app.app_context(): # If app object is accessible and needed

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
        # Attempt to mark as failed if we can identify the item
        try:
            database.update_video_status(item_video_id, 'failed', error_message=f"DB error at worker start: {str(e_db_initial)}")
        except Exception:
            pass # Avoid error loops if DB is truly unavailable
        return

    print(f"WORKER: Starting download for '{video_title}' ({item_video_id}). URL: {video_url}")

    output_filename_template = os.path.join(TEMP_VIDEOS_DIR, f"{item_video_id}.%(ext)s")
    expected_downloaded_file_path = os.path.join(TEMP_VIDEOS_DIR, f"{item_video_id}.mp4")

    final_status = 'failed'
    error_msg_details = "Download did not complete as expected."
    actual_filepath = None

    try:
        ffmpeg_dir_path = os.path.dirname(os.path.abspath(__file__))
        cookie_file_abs_path = os.path.abspath(config.COOKIE_FILE_PATH)

        if not os.path.exists(cookie_file_abs_path):
            print(f"WORKER: Cookie file not found at {cookie_file_abs_path} for video {item_video_id}. Download may fail.")

        command = [
            'yt-dlp',
            *(['--cookies', cookie_file_abs_path] if os.path.exists(cookie_file_abs_path) else []),
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
    global _global_app_initialized

    current_app = Flask(__name__, static_folder='static', template_folder='templates')
    current_app.config.from_object(config)
    current_app.register_blueprint(main_bp)

    if not _global_app_initialized:
        # It's better to do this within app_context if db operations need it,
        # but init_db and handle_cookie_update_on_startup are designed to be standalone for now.
        print("STARTUP: Initializing DB and Startup Routines (within create_app)...")
        database.init_db()
        print(f"Database initialized at: {database.DATABASE_PATH}")
        handle_cookie_update_on_startup()

        # Ensure TEMP_VIDEOS_DIR is created
        if not os.path.exists(TEMP_VIDEOS_DIR):
            try:
                os.makedirs(TEMP_VIDEOS_DIR)
                print(f"Created temporary videos directory: {TEMP_VIDEOS_DIR}")
            except Exception as e:
                print(f"Error creating temporary videos directory {TEMP_VIDEOS_DIR}: {e}")

        _global_app_initialized = True
        print("STARTUP: Initialization complete.")

    return current_app

app = create_app()

if __name__ == '__main__':
    # This block is less critical when `python -m youtube_client.app` is used,
    # as Flask's CLI invokes `create_app` or finds the `app` object.
    # The `create_app()` call above already handles initialization logic once.
    print(f"Starting Flask app directly via __main__ (Flask's reloader might run create_app again). Ensure CWD is project root: {os.getcwd()}")
    # The app object is already created by `app = create_app()` above.
    # The init routines are called within create_app ensuring they run once.
    app.run(debug=True, port=5001)
