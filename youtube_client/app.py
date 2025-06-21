from flask import Flask, render_template, request, Blueprint, flash, redirect, url_for
from . import youtube_api # Import the youtube_api module
from . import config # Import the config module
import subprocess
import os

# Using Blueprint for better organization
main_bp = Blueprint('main', __name__, template_folder='templates', static_folder='static')

# Ensure a downloads directory exists
# Note: In a server environment, this might be better handled at app startup or deployment.
# For a local tool, doing it here is generally fine.
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'downloads')
if not os.path.exists(DOWNLOADS_DIR):
    try:
        os.makedirs(DOWNLOADS_DIR)
        print(f"Created downloads directory: {DOWNLOADS_DIR}")
    except Exception as e:
        print(f"Error creating downloads directory {DOWNLOADS_DIR}: {e}")
        # If the app can't create it, downloads will likely fail.
        # Consider how to handle this - for now, it will just print an error.

@main_bp.route('/')
def index():
    print("Attempting to fetch homepage videos for Flask app...")
    videos = youtube_api.get_homepage_videos()
    # The `videos` variable will be an empty list if parsing fails or cookies are missing,
    # or if the placeholder parsing logic in youtube_api.py isn't finding anything.
    if not videos:
        print("No videos returned from youtube_api.get_homepage_videos()")
    else:
        print(f"Successfully fetched {len(videos)} video(s) for homepage.")
    return render_template('index.html', videos=videos)

@main_bp.route('/search')
def search():
    query = request.args.get('q', '')
    if not query:
        # Redirect to homepage or show an error/empty search page
        return render_template('search_results.html', videos=[], query=query)

    print(f"Attempting to search videos for query: '{query}' in Flask app...")
    videos = youtube_api.search_videos(query)
    if not videos:
        print(f"No videos returned from youtube_api.search_videos() for query '{query}'.")
    else:
        print(f"Successfully fetched {len(videos)} video(s) for search query '{query}'.")
    return render_template('search_results.html', videos=videos, query=query)

@main_bp.route('/download')
def download_video():
    video_url = request.args.get('url')
    if not video_url:
        flash("Error: No video URL provided.", "error")
        return redirect(request.referrer or url_for('main.index'))

    if not ("youtube.com/watch?v=" in video_url or "youtu.be/" in video_url) :
        flash(f"Error: Invalid YouTube URL provided: {video_url}", "error")
        return redirect(request.referrer or url_for('main.index'))

    # Ensure downloads directory exists (it might fail above if permissions are an issue at startup)
    if not os.path.exists(DOWNLOADS_DIR):
        try:
            os.makedirs(DOWNLOADS_DIR)
            print(f"Ensured downloads directory exists: {DOWNLOADS_DIR}")
        except Exception as e:
            flash(f"Could not create downloads directory: {e}", "error")
            return redirect(request.referrer or url_for('main.index'))

    print(f"Attempting to download video: {video_url} into {DOWNLOADS_DIR}")

    try:
        # Using a simple format for filename. %(title)s and %(id)s are yt-dlp fields.
        # Prefer mp4, fallback to best.
        command = [
            'yt-dlp',
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '-o', os.path.join(DOWNLOADS_DIR, '%(title)s [%(id)s].%(ext)s'),
            '--no-playlist', # Ensure only single video is downloaded if URL is part of a playlist
            video_url
        ]

        # Run the command. This is a blocking call.
        # For a better UX in a web app, this should be an async task.
        # But for a basic local tool, synchronous might be acceptable initially.
        # Adding a timeout (e.g., 5 minutes = 300 seconds)
        TIMEOUT_SECONDS = 300
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', timeout=TIMEOUT_SECONDS)

        if result.returncode == 0:
            # Try to find the filename yt-dlp actually used
            # yt-dlp usually prints "Destination: <filename>" or "[download] Destination: <filename>"
            # or "Merging formats into "<filename>""
            output_lines = result.stdout.splitlines()
            downloaded_file_name = None
            for line in output_lines:
                if "[download] Destination: " in line:
                    downloaded_file_name = line.split("[download] Destination: ")[1].strip()
                    break
                if "Merging formats into \"" in line: # yt-dlp 2023.03.04 and later
                    downloaded_file_name = line.split("Merging formats into \"")[1].rstrip("\"").strip()
                    break

            if downloaded_file_name and os.path.exists(downloaded_file_name): # yt-dlp might output full path
                 flash(f"Download complete: {os.path.basename(downloaded_file_name)}", "success")
            elif downloaded_file_name: # yt-dlp might output relative path from where it ran
                potential_path = os.path.join(DOWNLOADS_DIR, os.path.basename(downloaded_file_name))
                if os.path.exists(potential_path):
                    flash(f"Download complete: {os.path.basename(potential_path)}", "success")
                else:
                    flash(f"Download likely complete (yt-dlp exit code 0). Check console/downloads folder. Output: {result.stdout}", "success")
            else:
                 flash(f"Download likely complete (yt-dlp exit code 0). Check console/downloads folder. Output: {result.stdout}", "success")

        else:
            flash(f"Download failed. Error: {result.stderr or result.stdout}", "error")
            print(f"yt-dlp stdout: {result.stdout}")
            print(f"yt-dlp stderr: {result.stderr}")

    except FileNotFoundError:
        flash("Error: yt-dlp command not found. Is it installed and in your system's PATH?", "error")
        print("Error: yt-dlp command not found.")
    except subprocess.TimeoutExpired:
        flash("Error: Download command timed out.", "error")
        print("Error: yt-dlp command timed out.")
    except Exception as e:
        flash(f"An unexpected error occurred during download: {str(e)}", "error")
        print(f"An unexpected error occurred: {e}")

    return redirect(request.referrer or url_for('main.index'))


def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    # It's good practice to define static_folder and template_folder for the app itself,
    # even if blueprints also define them, especially if you have app-level static/templates.
    # However, for blueprints, they are relative to the blueprint's location.
    # Let's adjust blueprint registration to ensure Flask finds templates correctly.
    # The Blueprint 'main_bp' will look for templates in a 'templates' subfolder
    # relative to where the blueprint is defined (i.e., youtube_client/templates).
    # Flask's app.register_blueprint will handle this.

    # Load configuration from config.py
    app.config.from_object(config)
    # Example: app.config['SECRET_KEY'] will now be set from config.SECRET_KEY

    # Register blueprint. The paths in the blueprint for templates/static
    # are relative to the blueprint's Python file location.
    # If app.py is in youtube_client/ and templates are in youtube_client/templates/,
    # Flask should find them.
    app.register_blueprint(main_bp, url_prefix='/') # Registering at root

    return app

if __name__ == '__main__':
    # This allows running the app directly with `python youtube_client/app.py`
    # Ensure your FLASK_APP environment variable is set correctly if using `flask run`
    # e.g., FLASK_APP=youtube_client.app:create_app
    # or FLASK_APP=youtube_client (if create_app is called from __init__.py)
    app = create_app()
    app.run(debug=True, port=5001)
