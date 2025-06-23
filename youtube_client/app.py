from flask import Flask, render_template, request, Blueprint, flash, redirect, url_for, make_response
from youtube_client import config
from youtube_client import youtube_api
from youtube_client import database
from youtube_client import cookie_processor
import os
import subprocess
import re
import threading
import time
import filecmp
import json # Added json import

# --- Global variables related to app state ---
_global_app_initialized = False
_operational_cookies_ready = False # True if operational cookies are present and considered valid
_cookie_polling_thread = None
_stop_cookie_polling = threading.Event() # Event to signal the poller to stop

# --- User Specific Hardcoded Paths (as requested for now) ---
USER_COOKIE_DOWNLOAD_PATH = "C:/Users/artur/Downloads/www.youtube.com_cookies.txt"

def are_files_identical(file1_path, file2_path):
    if not os.path.exists(file1_path) or not os.path.exists(file2_path):
        return False
    # For small cookie files, content comparison is fine.
    # For very large files, hashing might be better, but cookies are small.
    try:
        with open(file1_path, 'r', encoding='utf-8') as f1, open(file2_path, 'r', encoding='utf-8') as f2:
            return f1.read() == f2.read()
    except IOError:
        return False # If files can't be read, assume not identical for safety

def check_operational_cookie_file_validity(operational_cookie_file_abs_path):
    if not os.path.exists(operational_cookie_file_abs_path):
        return False
    try:
        with open(operational_cookie_file_abs_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content: return False
            lines = [line for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
            if not lines: return False
        return True
    except Exception:
        return False

def _cookie_polling_worker_func():
    global _operational_cookies_ready
    source_path_to_poll = os.path.normpath(USER_COOKIE_DOWNLOAD_PATH)
    operational_cookie_file_abs_path = os.path.abspath(config.COOKIE_FILE_PATH)

    print(f"COOKIE_POLLER_THREAD: Started. Polling '{source_path_to_poll}' every 1 second.")
    while not _stop_cookie_polling.is_set(): # Loop until stop event is set
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
                _stop_cookie_polling.set() # Signal thread to stop
                break # Exit loop
            else:
                print(f"COOKIE_POLLER_THREAD: Failed to process new cookie file from '{source_path_to_poll}'. Will delete source and retry polling.")
                try: # Attempt to delete potentially corrupt source to avoid reprocessing bad file
                    os.remove(source_path_to_poll)
                    print(f"COOKIE_POLLER_THREAD: (Potentially corrupt) Source cookie file '{source_path_to_poll}' deleted after failed processing.")
                except OSError as e:
                    print(f"COOKIE_POLLER_THREAD: Error deleting (potentially corrupt) source cookie file '{source_path_to_poll}': {e}")
        time.sleep(1)

    if _stop_cookie_polling.is_set():
        print("COOKIE_POLLER_THREAD: Stop event received, exiting.")
    else: # Should only happen if _operational_cookies_ready became true via another means
        print("COOKIE_POLLER_THREAD: Exiting (operational_cookies_ready became true).")


def handle_cookie_update_on_startup():
    global _operational_cookies_ready, _cookie_polling_thread, _stop_cookie_polling

    print("STARTUP_COOKIE_CHECK: Initiated. Strict 'always new' policy.")
    source_cookie_path_abs = os.path.normpath(USER_COOKIE_DOWNLOAD_PATH)
    operational_cookie_file_abs_path = os.path.abspath(config.COOKIE_FILE_PATH)

    _operational_cookies_ready = False # Assume not ready until successfully processed
    _stop_cookie_polling.clear() # Reset stop event for poller

    # 1. Always delete any existing operational cookie file from previous session.
    if os.path.exists(operational_cookie_file_abs_path):
        try:
            os.remove(operational_cookie_file_abs_path)
            print(f"STARTUP_COOKIE_CHECK: Deleted existing operational cookie file: '{operational_cookie_file_abs_path}'.")
        except OSError as e:
            print(f"STARTUP_COOKIE_CHECK: Error deleting existing operational cookie file '{operational_cookie_file_abs_path}': {e}")
            # If we can't delete it, we might have issues writing the new one.

    # 2. Check for the source cookie file.
    if os.path.exists(source_cookie_path_abs):
        print(f"STARTUP_COOKIE_CHECK: New cookie file found at '{source_cookie_path_abs}'. Processing...")
        if cookie_processor.process_new_cookie_file(source_cookie_path_abs, operational_cookie_file_abs_path):
            print(f"STARTUP_COOKIE_CHECK: Successfully processed. Operational cookies at '{operational_cookie_file_abs_path}' created/updated.")
            try:
                os.remove(source_cookie_path_abs) # Always delete source after successful processing
                print(f"STARTUP_COOKIE_CHECK: Source cookie file '{source_cookie_path_abs}' deleted.")
            except OSError as e:
                print(f"STARTUP_COOKIE_CHECK: Error deleting source cookie file '{source_cookie_path_abs}': {e}")
            _operational_cookies_ready = check_operational_cookie_file_validity(operational_cookie_file_abs_path)
        else:
            print(f"STARTUP_COOKIE_CHECK: Failed to process new cookie file from '{source_cookie_path_abs}'.")
            # Try to delete the problematic source file to avoid reprocessing it if it's malformed
            try:
                os.remove(source_cookie_path_abs)
                print(f"STARTUP_COOKIE_CHECK: (Potentially corrupt) Source cookie file '{source_cookie_path_abs}' deleted after failed processing.")
            except OSError as e:
                print(f"STARTUP_COOKIE_CHECK: Error deleting (potentially corrupt) source cookie file '{source_cookie_path_abs}': {e}")
            _operational_cookies_ready = False # Explicitly false due to processing failure
    else: # Source does not exist
        print(f"STARTUP_COOKIE_CHECK: No new cookie file found at '{source_cookie_path_abs}'.")
        _operational_cookies_ready = False

    if not _operational_cookies_ready:
        print("STARTUP_COOKIE_CHECK: Operational cookies are not ready. Starting background poller for new cookies.")
        print(f"STARTUP_COOKIE_CHECK: Please place your cookies.txt file at: {source_cookie_path_abs}")
        # Ensure only one poller thread runs
        if _cookie_polling_thread is None or not _cookie_polling_thread.is_alive():
            _cookie_polling_thread = threading.Thread(target=_cookie_polling_worker_func, daemon=True)
            _cookie_polling_thread.start()
        else:
            print("STARTUP_COOKIE_CHECK: Cookie poller thread already running (should not happen here).")
    else:
        print(f"STARTUP_COOKIE_CHECK: Operational cookies are ready. Using: '{operational_cookie_file_abs_path}'")
        _stop_cookie_polling.set() # Ensure any old poller (if somehow alive) is signalled to stop

# Blueprint and other app setup follows...
main_bp = Blueprint('main', __name__, template_folder='templates', static_folder='static')
TEMP_VIDEOS_STATIC_PATH = 'temp_videos'
TEMP_VIDEOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', TEMP_VIDEOS_STATIC_PATH)

@main_bp.route('/')
def index():
    videos = []
    continuation_token = None
    page_type = 'home' # For "Load More" button context in template
    if _operational_cookies_ready:
        data = youtube_api.get_homepage_videos_parsed(limit=30)
        if data and isinstance(data, dict):
            videos = data.get('videos', [])
            continuation_token = data.get('continuation_token')

        if not videos:
            flash("Cookies seem loaded, but could not fetch homepage videos. Possible YouTube structure change or no videos found.", "warning")
    else:
         flash(f"Cookies not loaded. Waiting for cookie file at {USER_COOKIE_DOWNLOAD_PATH}", "warning")
    return render_template('index.html',
                           videos=videos,
                           continuation_token=continuation_token,
                           current_page_type=page_type,
                           api_load_route='main.api_load_more_home_route') # Added api_load_route

@main_bp.route('/subscriptions')
def subscriptions_feed_route():
    videos = []
    continuation_token = None
    page_type = 'subscriptions'
    if _operational_cookies_ready:
        data = youtube_api.get_subscriptions_feed_parsed() # API has internal limit
        if data and isinstance(data, dict):
            videos = data.get('videos', [])
            continuation_token = data.get('continuation_token')

        if not videos:
            flash("Could not load subscriptions feed. Possible cookie issue, YouTube change, or no new subscription videos.", "warning")
    else:
        flash(f"Cookies not loaded. Cannot fetch subscriptions. Waiting for cookie file at {USER_COOKIE_DOWNLOAD_PATH}", "warning")

    return render_template('subscriptions_feed.html',
                           videos=videos,
                           page_title="My Subscriptions",
                           continuation_token=continuation_token,
                           current_page_type=page_type,
                           api_load_route='main.api_load_more_subscriptions_route') # Added api_load_route

@main_bp.route('/channel')
def channel_page_route():
    channel_url = request.args.get('url')
    videos = []
    continuation_token = None
    page_type = 'channel' # For "Load More"

    # Simple heuristic for page title from URL, can be refined
    channel_name_from_url = "Channel"
    if channel_url:
        try:
            if "/@" in channel_url: channel_name_from_url = channel_url.split("/@")[1].split("/")[0]
            elif "/channel/": channel_name_from_url = channel_url.split("/channel/")[1].split("/")[0]
            elif "/user/": channel_name_from_url = channel_url.split("/user/")[1].split("/")[0]
        except IndexError: pass

    if not channel_url:
        flash("No channel URL provided.", "error")
        return redirect(url_for('main.index'))

    data = youtube_api.get_channel_videos_parsed(channel_url, limit=30)
    if data and isinstance(data, dict):
        videos = data.get('videos', [])
        continuation_token = data.get('continuation_token')

    if not videos:
        flash(f"Could not load videos for channel: {channel_name_from_url}. Channel may be invalid or parsing failed.", "warning")

    return render_template('channel_page.html',
                           videos=videos,
                           page_title=f"{channel_name_from_url}",
                           channel_url=channel_url,
                           continuation_token=continuation_token,
                           current_page_type=page_type,
                           api_load_route='main.api_load_more_channel_route') # Added api_load_route


@main_bp.route('/load_more_home')
def load_more_home_route():
    # This was a placeholder UI route, now we implement the API version
    pass # Will be replaced by the actual API route below


# --- API Routes for HTMX "Load More" ---
@main_bp.route('/api/load_more/home')
def api_load_more_home_route():
    token = request.args.get('token')
    # print(f"API: /api/load_more/home called with token: {token}") # Debug
    data = youtube_api.get_more_home_videos_parsed(continuation_data=token)
    videos = data.get('videos', [])
    next_token = data.get('continuation_token')
    # This will render a partial template with new videos
    # and an OOB swap for the button itself with the new token.
    return render_template('_video_card_list.html', videos=videos,
                           continuation_token=next_token,
                           current_page_type='home',
                           api_load_route='main.api_load_more_home_route')


@main_bp.route('/api/load_more/subscriptions')
def api_load_more_subscriptions_route():
    token = request.args.get('token')
    # print(f"API: /api/load_more/subscriptions called with token: {token}") # Debug
    data = youtube_api.get_more_subscriptions_videos_parsed(continuation_data=token)
    videos = data.get('videos', [])
    next_token = data.get('continuation_token')
    return render_template('_video_card_list.html', videos=videos,
                           continuation_token=next_token,
                           current_page_type='subscriptions',
                           api_load_route='main.api_load_more_subscriptions_route')

@main_bp.route('/api/load_more/channel')
def api_load_more_channel_route():
    token = request.args.get('token')
    channel_url = request.args.get('channel_url') # Important for context
    # print(f"API: /api/load_more/channel for {channel_url} with token: {token}") # Debug
    data = youtube_api.get_more_channel_videos_parsed(channel_url=channel_url, continuation_data=token)
    videos = data.get('videos', [])
    next_token = data.get('continuation_token')
    return render_template('_video_card_list.html', videos=videos,
                           continuation_token=next_token,
                           current_page_type='channel',
                           channel_url=channel_url, # Pass back for next button
                           api_load_route='main.api_load_more_channel_route')

@main_bp.route('/api/load_more/recommendations')
def api_load_more_recommendations_route():
    token = request.args.get('token')
    video_id = request.args.get('video_id') # Context for recommendations
    # print(f"API: /api/load_more/recommendations for video {video_id} with token: {token}") # Debug
    data = youtube_api.get_more_recommended_videos_parsed(current_video_id=video_id, continuation_data=token)
    videos = data.get('videos', [])
    next_token = data.get('continuation_token')
    # Recommended videos might need a different partial if layout is different
    return render_template('_video_card_list.html', videos=videos,
                           continuation_token=next_token,
                           current_page_type='recommendations',
                           video_id=video_id, # Pass back for next button context
                           api_load_route='main.api_load_more_recommendations_route')


@main_bp.route('/api/queue/clear', methods=['POST'])
def clear_queue_api_route():
    """Clears all items from the video queue."""
    try:
        count = database.clear_all_video_queue_items()
        flash(f"Successfully cleared {count} items from the queue.", "success")
        # For HTMX, trigger a refresh of the queue display
        response = make_response("", 200) # Empty success response
        response.headers['HX-Trigger'] = 'queueUpdated' # Event for HTMX to listen to
        return response
    except Exception as e:
        print(f"Error clearing queue: {e}")
        flash("Error clearing the queue.", "error")
        # HTMX can also handle error responses if needed, e.g. return error code
        response = make_response("Error clearing queue", 500)
        return response

def _clear_temp_video_files():
    """Deletes all .mp4 files from TEMP_VIDEOS_DIR and updates DB."""
    cleared_files_count = 0
    updated_db_entries_count = 0
    if not os.path.exists(TEMP_VIDEOS_DIR):
        print("Video cache directory does not exist. Nothing to clear.")
        return cleared_files_count, updated_db_entries_count

    for filename in os.listdir(TEMP_VIDEOS_DIR):
        if filename.endswith(".mp4"): # Or other extensions if we support more
            file_path = os.path.join(TEMP_VIDEOS_DIR, filename)
            try:
                os.remove(file_path)
                cleared_files_count += 1
                print(f"Deleted cached file: {file_path}")

                # Update corresponding DB entry
                video_id = filename.replace(".mp4", "") # Assumes filename is VIDEO_ID.mp4
                db_item = database.get_video_by_id(video_id)
                if db_item and db_item['status'] in ['completed', 'cached']: # Only update if it was considered downloaded/cached
                    # Reset to 'pending' or a new 'archived_no_file' status.
                    # 'pending' allows re-download. 'archived' might hide it from active queue.
                    # Let's use 'pending' to allow easy re-download.
                    database.update_video_status(video_id, 'pending', filepath=None, error_message="Cache file deleted by user.")
                    updated_db_entries_count +=1
            except OSError as e:
                print(f"Error deleting file {file_path}: {e}")
    return cleared_files_count, updated_db_entries_count

@main_bp.route('/api/cache/clear', methods=['POST'])
def clear_cache_api_route():
    """Clears all .mp4 files from the temporary video cache."""
    try:
        cleared_count, db_updated_count = _clear_temp_video_files()
        flash(f"Successfully cleared {cleared_count} cached video files and updated {db_updated_count} DB entries.", "success")
        response = make_response("", 200)
        response.headers['HX-Trigger'] = 'queueUpdated' # Refresh queue to show changed statuses
        return response
    except Exception as e:
        print(f"Error clearing video cache: {e}")
        flash("Error clearing the video cache.", "error")
        response = make_response("Error clearing video cache", 500)
        return response

@main_bp.route('/api/queue/add', methods=['POST'])
def add_to_queue_api_route():
    try:
        # Data from HTMX POST request (hx-vals)
        video_id = request.form.get('video_id')
        youtube_url = request.form.get('youtube_url')
        title = request.form.get('title')
        thumbnail_url = request.form.get('thumbnail_url')

        if not all([video_id, youtube_url, title]): # thumbnail_url is optional for adding
            flash("Missing video data for adding to queue.", "error")
            return make_response("Missing data", 400)

        if database.add_video_to_queue(video_id, youtube_url, title, thumbnail_url):
            flash(f"'{title}' added to queue.", "success")
            response = make_response("", 200) # OK, no content needed
             # Trigger sidebar queue update and potentially other elements
            response.headers['HX-Trigger'] = json.dumps({"queueUpdated": None, "showMessage": f"{title} added to queue."})
            return response
        else:
            # add_video_to_queue returned False, likely meaning it's already in queue and not failed
            db_item = database.get_video_by_id(video_id)
            current_status = db_item['status'] if db_item else "unknown"
            flash(f"'{title}' already in queue (status: {current_status}).", "info")
            # Still send queueUpdated trigger as status might have been 'failed' and now 'pending'
            response = make_response("", 200)
            response.headers['HX-Trigger'] = json.dumps({"queueUpdated": None, "showMessage": f"{title} already in queue ({current_status})."})
            return response

    except Exception as e:
        print(f"Error in /api/queue/add: {e}")
        flash("Error adding video to queue.", "error")
        return make_response(f"Error adding to queue: {str(e)}", 500)


@main_bp.route('/render_queue_fragment')
def render_queue_fragment_route():
    # This route will eventually render a partial template for the queue
    # For now, let's get items from DB and pass to a new partial template
    # Or, for extreme simplicity in this step, just return a basic HTML string
    try:
        # In a real HTMX app, you'd often use a specific partial template here.
        # e.g., return render_template('_queue_list_partial.html', download_queue=database.get_queued_videos())

        # For now, let's keep it super simple to ensure the route is hit.
        # The actual queue display logic is in queue.html, this is for the sidebar.
        items = database.get_queued_videos() # Get latest queue items

        # This will be replaced by rendering a partial template in a later step.
        html_items = []
        if not items:
            html_items.append("<li>Queue is empty.</li>")
        else:
            for item in items[:5]: # Show top 5 for sidebar brevity
                status_class = f"status-{item['status'].lower()}"
                title_short = item['title'][:30] + '...' if len(item['title']) > 30 else item['title']
                html_items.append(f"<li><span class='queue-item-title'>{title_short}</span> <span class='queue-item-status {status_class}'>{item['status'].capitalize()}</span></li>")

        # The HTMX div in base.html expects innerHTML swap.
        # The styling for these items is in style.css under #queue-sidebar-content
        return f"<ul>{''.join(html_items)}</ul>"

    except Exception as e:
        print(f"Error in render_queue_fragment_route: {e}")
        return "<li>Error loading queue.</li>" # Fallback content for HTMX target


@main_bp.route('/search')
def search():
    query = request.args.get('q', '')
    if not query:
        flash("Please enter a search query.", "info")
        return redirect(url_for('main.index'))

    page_type = 'search'
    # youtube_api.search_videos_parsed returns a dict: {'videos': [], 'continuation_token': None}
    data = youtube_api.search_videos_parsed(query, limit=30)
    videos = data.get('videos', [])
    continuation_token = data.get('continuation_token') # Will be None if not implemented in API

    if not videos:
        flash(f"No results found for '{query}'.", "info")

    return render_template('search_results.html',
                           videos=videos,
                           query=query,
                           current_page_type=page_type,
                           continuation_token=continuation_token, # Pass for future "Load More"
                           api_load_route='main.api_load_more_search_route' # Define even if not used by template yet
                           )

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
        return redirect(url_for('main.player_route', video_id=video_id, title=db_video_item['title']))

    if os.path.exists(expected_downloaded_file_path): # File exists, but DB might be out of sync
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
        # Pass video_id to worker, it will fetch details from DB
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

        recommended_videos = youtube_api.get_recommended_videos_for_player(current_video_id=video_id)

        # If this route is targeted by HTMX for the main content area:
        # Render 'play_video.html' which should be structured as a content block,
        # not extending base.html if it's meant to be a fragment for hx-swap="innerHTML".
        # For now, assume play_video.html is a full page, but it can be adapted.
        return render_template('play_video.html',
                               video_file_url=url_for('static', filename=video_static_path_constructed),
                               title=video_item_db['title'],
                               current_video_id=video_id,
                               recommended_videos=recommended_videos)
    else:
        flash(f"Cannot play video {video_id}. File not found or not in database correctly.", "error")
        if video_item_db:
             database.update_video_status(video_id, 'failed', error_message="File missing or status incorrect for playback.")
        return redirect(url_for('main.queue_page_route'))

def _download_video_worker(item_video_id):
    global _operational_cookies_ready # Worker might update this if it's the poller, but primary worker shouldn't
    try:
        video_item = database.get_video_by_id(item_video_id)
        if not video_item:
            print(f"WORKER: Video {item_video_id} not found in DB. Aborting.")
            return

        if video_item['status'] not in ['pending', 'queued']:
            print(f"WORKER: Video {item_video_id} status is '{video_item['status']}', not 'pending'/'queued'. Aborting.")
            return

        video_url = video_item['youtube_url']
        video_title = video_item['title'] # Use title from DB for consistency

        print(f"WORKER: Fetched from DB for video_id '{item_video_id}': title='{video_title}', url='{video_url}', current_status='{video_item['status']}'")

        database.update_video_status(item_video_id, 'downloading')
    except Exception as e_db_initial:
        print(f"WORKER: DB error for {item_video_id} at start: {e_db_initial}")
        try:
            database.update_video_status(item_video_id, 'failed', error_message=f"DB error at worker start: {str(e_db_initial)}")
        except Exception: pass # Avoid error loops if DB is truly unavailable
        return

    print(f"WORKER: Starting download for '{video_title}' ({item_video_id}). URL: {video_url}")
    output_filename_template = os.path.join(TEMP_VIDEOS_DIR, f"{item_video_id}.%(ext)s")
    expected_downloaded_file_path = os.path.join(TEMP_VIDEOS_DIR, f"{item_video_id}.mp4")
    final_status = 'failed'
    error_msg_details = "Download did not complete as expected."
    actual_filepath = None

    try:
        cookie_file_abs_path = os.path.abspath(config.COOKIE_FILE_PATH)

        use_cookies_for_yt_dlp = _operational_cookies_ready and check_operational_cookie_file_validity(cookie_file_abs_path)
        if use_cookies_for_yt_dlp:
             print(f"WORKER: Using operational cookies for {item_video_id}: {cookie_file_abs_path}")
        else:
             print(f"WORKER: Not using cookies for {item_video_id} (operational_cookies_ready: {_operational_cookies_ready}, file valid: {check_operational_cookie_file_validity(cookie_file_abs_path)})")

        command = [
            config.YT_DLP_PATH, # Use configured path for yt-dlp
        ]

        # Add --ffmpeg-location if FFMPEG_PATH is configured to something other than 'ffmpeg' (i.e., not relying on system PATH)
        # yt-dlp can take either the path to the executable or the directory.
        if config.FFMPEG_PATH and config.FFMPEG_PATH.lower() != 'ffmpeg':
            command.extend(['--ffmpeg-location', config.FFMPEG_PATH])
            print(f"WORKER: Using specific ffmpeg location: {config.FFMPEG_PATH}")
        else:
            print(f"WORKER: Assuming ffmpeg is in system PATH or yt-dlp will find it.")

        # Conditionally add cookie arguments
        cookie_arguments = []
        if use_cookies_for_yt_dlp:
            cookie_arguments.extend(['--cookies', cookie_file_abs_path])

        command.extend(cookie_arguments + [
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', # Standard format selection
            '--merge-output-format', 'mp4', # Ensure output is mp4 after merge
            '-o', output_filename_template, # Output template
            '--no-playlist',
            '--force-overwrites',
            video_url
        ])

        print(f"WORKER: yt-dlp command for {item_video_id}: {' '.join(command)}")
        TIMEOUT_SECONDS = 600

        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_filename_template), exist_ok=True)

        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', timeout=TIMEOUT_SECONDS)

        if result.returncode == 0:
            if os.path.exists(expected_downloaded_file_path):
                final_status = 'completed'
                actual_filepath = expected_downloaded_file_path
                print(f"WORKER: Download successful for {item_video_id}. File: {actual_filepath}")
            else:
                error_msg_details = f"yt-dlp OK but expected file missing. stdout: {result.stdout}, stderr: {result.stderr}"
                print(f"WORKER ERROR for {item_video_id}: {error_msg_details}")
        else:
            error_msg_details = f"yt-dlp failed. stderr: {result.stderr or result.stdout}"
            print(f"WORKER ERROR for {item_video_id}: {error_msg_details}")

    except Exception as e:
        error_msg_details = f"Unexpected error in worker for {item_video_id}: {str(e)}"
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
        with current_app.app_context():
            print("STARTUP: Initializing DB and Startup Routines (within create_app)...")
            database.init_db()
            print(f"Database initialized at: {database.DATABASE_PATH}")

            if not os.path.exists(TEMP_VIDEOS_DIR):
                try:
                    os.makedirs(TEMP_VIDEOS_DIR)
                    print(f"Created temporary videos directory: {TEMP_VIDEOS_DIR}")
                except Exception as e:
                    print(f"Error creating temporary videos directory {TEMP_VIDEOS_DIR}: {e}")

            handle_cookie_update_on_startup() # This will manage _operational_cookies_ready

        _global_app_initialized = True
        print("STARTUP: Initialization complete.")

    return current_app

app = create_app()

if __name__ == '__main__':
    print(f"Starting Flask app directly via __main__. Ensure CWD is project root: {os.getcwd()}")
    app.run(debug=True, port=5001)
