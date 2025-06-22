from flask import Flask, render_template
# Explicitly import from the youtube_client package
from youtube_client import config
from youtube_client import youtube_api

# print(f"app.py overwritten, config.SECRET_KEY: {config.SECRET_KEY}") # Optional debug
# print(f"app.py overwritten, youtube_api: {youtube_api}") # Optional debug

app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = config.SECRET_KEY # Ensure config is usable

@app.route('/')
def minimal_index():
    # Test calling a function from youtube_api
    api_data = youtube_api.get_some_data() # Ensure youtube_api is usable
    # print(f"API Data in route: {api_data}") # Optional debug
    return render_template('index.html', message=api_data)

if __name__ == '__main__':
    # This __main__ block is typically for when you run the script directly
    # e.g., python youtube_client/app.py
    # For the `python -m youtube_client.app` execution style,
    # the `app` object at the module level is what's usually picked up by Flask's runner.
    print("Running app directly via __main__ (intended for 'python -m youtube_client.app')")
    app.run(debug=True, port=5001)

# Note: If `python -m youtube_client.app` were to look for a `create_app` factory,
# we would define it like this:
# def create_app():
#     # app initialization as above
#     return app
# However, for `python -m module.submodule_with_app_object`, Flask should find the global `app` object.
