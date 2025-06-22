from flask import Flask, render_template, request, Blueprint, flash, redirect, url_for
from youtube_client import config
from youtube_client import youtube_api # This now has the full parsing logic
import os # Will be used for downloader later

# print(f"app.py (full) loaded, config.SECRET_KEY: {config.SECRET_KEY}") # Debug
# print(f"app.py (full) loaded, youtube_api: {youtube_api}") # Debug

# Using Blueprint for better organization
# Ensure template_folder is correctly specified if not in default location relative to blueprint
main_bp = Blueprint('main', __name__, template_folder='templates', static_folder='static')

# This will be used by downloader later, ensure it's defined
# Path is relative to this app.py file, then one up to project root, then into 'downloads'
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'downloads')

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

# Downloader route will be re-added in a later step

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
