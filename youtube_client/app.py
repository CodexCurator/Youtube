from flask import Flask, render_template, request, Blueprint
from . import youtube_api # Import the youtube_api module
from . import config # Import the config module
# Using Blueprint for better organization
main_bp = Blueprint('main', __name__, template_folder='templates', static_folder='static')

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
