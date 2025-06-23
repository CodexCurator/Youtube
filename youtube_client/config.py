import os

# Flask App Configuration
# Load from environment variable or use a default.
# Generate a good one using: python -c 'import secrets; print(secrets.token_hex(16))'
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'default_dev_secret_key_replace_me_123!')

# Path to the cookies file (Netscape format)
# Assumes 'www.youtube.com_cookies.txt' is in the project root directory (where you run `python -m ...`)
COOKIE_FILE_PATH = 'www.youtube.com_cookies.txt'
# Previous was: COOKIE_FILE_PATH = "cookies.json"

# Optional: You could add a variable to specify the format if you plan to support multiple
# COOKIE_FORMAT = 'netscape' # 'json' or 'netscape'

# print(f"config.py loaded. COOKIE_FILE_PATH set to: {COOKIE_FILE_PATH}")

# Paths for yt-dlp and ffmpeg
# Default to assuming they are in the system PATH.
# Users can override these by setting environment variables or modifying directly.
YT_DLP_PATH = os.environ.get('YT_DLP_PATH', 'yt-dlp')

# --- FFMPEG Path Configuration ---
# IMPORTANT:
# If ffmpeg.exe and ffprobe.exe are placed directly inside the 'youtube_client' directory
# (i.e., alongside app.py, config.py, etc.), this path should correctly point to ffmpeg.exe.
# This assumes config.py is in the 'youtube_client' directory.
_ffmpeg_executable_name = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
FFMPEG_PATH_CANDIDATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), _ffmpeg_executable_name)

if os.path.exists(FFMPEG_PATH_CANDIDATE):
    FFMPEG_PATH = FFMPEG_PATH_CANDIDATE
    print(f"CONFIG: Found bundled ffmpeg at: {FFMPEG_PATH}")
else:
    # Fallback to environment variable or assuming it's in PATH
    FFMPEG_PATH = os.environ.get('FFMPEG_PATH', 'ffmpeg')
    print(f"CONFIG: Bundled ffmpeg not found at '{FFMPEG_PATH_CANDIDATE}'. Using FFMPEG_PATH: '{FFMPEG_PATH}' (relies on PATH or explicit env var).")

# Example of setting FFMPEG_PATH if it's bundled elsewhere (adjust as needed):
# Example: if in project_root/bin/ffmpeg/ffmpeg.exe and config.py is in youtube_client/
# _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# FFMPEG_PATH = os.path.join(_project_root, 'bin', 'ffmpeg', 'ffmpeg.exe')
