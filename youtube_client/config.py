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
