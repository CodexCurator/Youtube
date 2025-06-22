import sqlite3
import os
from datetime import datetime

# Define the path for the SQLite database file
# It will be created in the project root directory (one level up from youtube_client directory)
DATABASE_NAME = 'youtube_queue.db'
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), DATABASE_NAME)

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row # Access columns by name
    return conn

def init_db(force_recreate=False):
    """Initializes the database and creates tables if they don't exist."""
    if force_recreate and os.path.exists(DATABASE_PATH):
        os.remove(DATABASE_PATH)
        print(f"Removed existing database '{DATABASE_PATH}' due to force_recreate=True.")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Create video_queue table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS video_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT UNIQUE NOT NULL,
        youtube_url TEXT NOT NULL,
        title TEXT NOT NULL,
        thumbnail_url TEXT,
        status TEXT DEFAULT 'pending'
            CHECK(status IN ('pending', 'queued', 'downloading', 'completed', 'failed', 'watched', 'cached')),
        filepath TEXT, /* Full path to the downloaded file */
        added_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_status_update DATETIME DEFAULT CURRENT_TIMESTAMP, /* To track when status last changed */
        error_message TEXT,
        download_attempts INTEGER DEFAULT 0
        /* user_order might be added later if manual reordering is needed */
    )
    ''')
    print("Table 'video_queue' initialized.")

    # Create user_settings table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_settings (
        setting_name TEXT PRIMARY KEY,
        setting_value TEXT
    )
    ''')
    print("Table 'user_settings' initialized.")

    # Example: Initialize some default settings if they don't exist
    default_settings = {
        'cookie_source_path': 'new_cookies.txt', # Default path in project root
        'delete_source_cookie': 'false', # 'true' or 'false' as TEXT
        'max_cached_videos': '5',
        'max_concurrent_downloads': '2'
    }
    for name, value in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO user_settings (setting_name, setting_value) VALUES (?, ?)", (name, value))

    print("Default settings populated if not existing.")

    conn.commit()
    conn.close()
    print(f"Database '{DATABASE_PATH}' initialized successfully.")

# --- Utility functions for user_settings ---

def set_setting(name, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_settings (setting_name, setting_value) VALUES (?, ?)", (name, str(value)))
    conn.commit()
    conn.close()

def get_setting(name, default=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM user_settings WHERE setting_name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    if row:
        # Convert 'true'/'false' strings for boolean-like settings
        if name == 'delete_source_cookie':
            return row['setting_value'].lower() == 'true'
        # Convert numeric settings
        if name in ['max_cached_videos', 'max_concurrent_downloads']:
            try:
                return int(row['setting_value'])
            except ValueError:
                return default # Or handle error
        return row['setting_value']
    return default

# --- Utility functions for video_queue ---

def add_video_to_queue(video_id, youtube_url, title, thumbnail_url):
    """Adds a video to the queue if it doesn't already exist (based on video_id).
       If it exists and status is 'failed', it resets status to 'pending' and increments attempts.
       Returns True if added/updated, False if already present and not in a failed state.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT status, download_attempts FROM video_queue WHERE video_id = ?", (video_id,))
    existing_video = cursor.fetchone()

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if existing_video:
        current_status = existing_video['status']
        current_attempts = existing_video['download_attempts']
        if current_status == 'failed':
            # Reset status to 'pending' for retry, increment attempts
            cursor.execute('''
            UPDATE video_queue
            SET status = 'pending', title = ?, youtube_url = ?, thumbnail_url = ?,
                error_message = NULL, download_attempts = ?, last_status_update = ?
            WHERE video_id = ?
            ''', (title, youtube_url, thumbnail_url, current_attempts + 1, current_time, video_id))
            print(f"Video {video_id} status reset to 'pending' for retry (attempt {current_attempts + 1}).")
            conn.commit()
            conn.close()
            return True
        else:
            # Video exists and is not in a 'failed' state (e.g., pending, downloading, completed)
            print(f"Video {video_id} already in queue with status '{current_status}'. Not re-adding.")
            conn.close()
            return False # Or indicate it's already there
    else:
        # Add new video
        cursor.execute('''
        INSERT INTO video_queue
            (video_id, youtube_url, title, thumbnail_url, status, added_timestamp, last_status_update, download_attempts)
        VALUES (?, ?, ?, ?, 'pending', ?, ?, 0)
        ''', (video_id, youtube_url, title, thumbnail_url, current_time, current_time))
        print(f"Video {video_id} ('{title}') added to queue.")
        conn.commit()
        conn.close()
        return True

def get_queued_videos(status_filter=None, limit=None):
    """Fetches videos from the queue, optionally filtered by status, ordered by added_timestamp."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM video_queue"
    params = []
    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)

    query += " ORDER BY added_timestamp ASC" # Oldest first for pending/queued

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cursor.execute(query, tuple(params))
    videos = [dict(row) for row in cursor.fetchall()] # Convert rows to dicts
    conn.close()
    return videos

def update_video_status(video_id, status, filepath=None, error_message=None):
    """Updates the status, filepath, and/or error message of a video in the queue."""
    conn = get_db_connection()
    cursor = conn.cursor()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if status == 'downloading':
         cursor.execute("SELECT download_attempts FROM video_queue WHERE video_id = ?", (video_id,))
         row = cursor.fetchone()
         attempts = row['download_attempts'] + 1 if row else 1 # Should exist if downloading
         cursor.execute('''
         UPDATE video_queue
         SET status = ?, last_status_update = ?, download_attempts = ?
         WHERE video_id = ?
         ''', (status, current_time, attempts, video_id))
    elif status == 'completed':
        cursor.execute('''
        UPDATE video_queue
        SET status = ?, filepath = ?, error_message = NULL, last_status_update = ?
        WHERE video_id = ?
        ''', (status, filepath, current_time, video_id))
    elif status == 'failed':
        cursor.execute('''
        UPDATE video_queue
        SET status = ?, error_message = ?, last_status_update = ?
        WHERE video_id = ?
        ''', (status, error_message, current_time, video_id))
    else: # For 'pending', 'queued', 'watched', 'cached' or other statuses
        cursor.execute('''
        UPDATE video_queue
        SET status = ?, last_status_update = ?
        WHERE video_id = ?
        ''', (status, current_time, video_id))

    conn.commit()
    if conn.total_changes == 0:
        print(f"Warning: No rows updated for video_id {video_id} with status {status}.")
    conn.close()
    print(f"Status for video {video_id} updated to '{status}'.")

def get_video_by_id(video_id):
    """Fetches a single video from the queue by its YouTube video_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM video_queue WHERE video_id = ?", (video_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_videos_by_status(status_list):
    """Fetches videos matching any status in the provided list."""
    if not isinstance(status_list, list):
        status_list = [status_list]
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ','.join('?' for status in status_list)
    query = f"SELECT * FROM video_queue WHERE status IN ({placeholders}) ORDER BY added_timestamp ASC"
    cursor.execute(query, tuple(status_list))
    videos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return videos

def remove_video_from_queue(video_id):
    """Removes a video from the queue by its YouTube video_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM video_queue WHERE video_id = ?", (video_id,))
    conn.commit()
    deleted_count = conn.total_changes
    conn.close()
    if deleted_count > 0:
        print(f"Video {video_id} removed from queue.")
        return True
    print(f"Video {video_id} not found in queue for removal.")
    return False


if __name__ == '__main__':
    # This block can be used for direct testing of the database module
    print(f"Database will be created/checked at: {DATABASE_PATH}")
    init_db(force_recreate=False) # Set to True to wipe and recreate DB for testing

    print("\n--- Testing Settings ---")
    set_setting('test_setting', 'test_value_123')
    print(f"Retrieved 'test_setting': {get_setting('test_setting')}")
    set_setting('max_cached_videos', '10')
    print(f"Retrieved 'max_cached_videos': {get_setting('max_cached_videos', 5)} (type: {type(get_setting('max_cached_videos', 5))})")
    print(f"Retrieved 'delete_source_cookie': {get_setting('delete_source_cookie', False)} (type: {type(get_setting('delete_source_cookie', False))})")
    print(f"Retrieved non-existent setting: {get_setting('fake_setting', 'default_val')}")


    print("\n--- Testing Video Queue ---")
    # Test adding videos
    add_video_to_queue('vid001', 'url1', 'Title One', 'thumb1.jpg')
    add_video_to_queue('vid002', 'url2', 'Title Two', 'thumb2.jpg')
    add_video_to_queue('vid001', 'url1_updated', 'Title One Updated', 'thumb1_updated.jpg') # Test duplicate add (should not add new, or update if failed)

    # Test fetching
    print("\nAll queued videos:")
    for v in get_queued_videos(): print(v)

    # Test status update
    print("\nUpdating vid001 status...")
    update_video_status('vid001', 'downloading')
    vid1 = get_video_by_id('vid001')
    print(f"vid001 after 'downloading': {vid1}")

    update_video_status('vid001', 'completed', filepath='/path/to/vid001.mp4')
    vid1 = get_video_by_id('vid001')
    print(f"vid001 after 'completed': {vid1}")

    update_video_status('vid002', 'failed', error_message='Download timed out.')
    vid2 = get_video_by_id('vid002')
    print(f"vid002 after 'failed': {vid2}")

    # Test re-adding a failed video
    add_video_to_queue('vid002', 'url2_retry', 'Title Two Retry', 'thumb2_retry.jpg')
    vid2_retry = get_video_by_id('vid002')
    print(f"vid002 after re-queue attempt: {vid2_retry}")


    print("\nPending videos:")
    for v in get_videos_by_status(['pending']): print(v)

    print("\nDownloading or Completed videos:")
    for v in get_videos_by_status(['downloading', 'completed']): print(v)

    # Test removal
    # remove_video_from_queue('vid001')
    # print("\nAll queued videos after removing vid001:")
    # for v in get_queued_videos(): print(v)

    print("\nDB Test Complete.")
