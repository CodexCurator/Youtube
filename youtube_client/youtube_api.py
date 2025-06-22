import json
import requests
from bs4 import BeautifulSoup
from http.cookiejar import MozillaCookieJar # Can parse Netscape cookie files
import os # For path joining if needed, though config handles path now

from youtube_client import config # Explicit package-relative import

# print(f"youtube_api.py loaded, config.COOKIE_FILE_PATH: {config.COOKIE_FILE_PATH}") # Optional debug

BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'DNT': '1',
    'Upgrade-Insecure-Requests': '1'
}

def load_cookies():
    """
    Loads cookies from the Netscape-formatted cookie file specified in config.COOKIE_FILE_PATH.
    Returns a requests.cookies.RequestsCookieJar object.
    """
    cookie_jar = requests.cookies.RequestsCookieJar()
    # The config.COOKIE_FILE_PATH is relative to the project root.
    # We need to ensure it's an absolute path or correctly relative to current working dir.
    # If running `python -m ...` from project root, `config.COOKIE_FILE_PATH` should be found directly.
    # Let's assume current working directory is project root.

    file_path = config.COOKIE_FILE_PATH

    if not os.path.exists(file_path):
        print(f"Warning: Cookie file '{file_path}' not found. Requests will be made without authentication.")
        return cookie_jar # Return empty jar

    # Use MozillaCookieJar to parse the Netscape format file
    # then transfer cookies to a RequestsCookieJar
    mozilla_jar = MozillaCookieJar(file_path)
    try:
        mozilla_jar.load(ignore_discard=True, ignore_expires=True)
        # print(f"Successfully loaded {len(mozilla_jar)} cookies from Netscape file: {file_path}")
    except Exception as e:
        print(f"Error loading cookies from Netscape file '{file_path}': {e}")
        return cookie_jar # Return empty jar

    # Convert to RequestsCookieJar
    for cookie in mozilla_jar:
        # print(f"Adding cookie: name={cookie.name}, value={cookie.value}, domain={cookie.domain}, path={cookie.path}")
        cookie_jar.set_cookie(requests.cookies.create_cookie(
            name=cookie.name,
            value=cookie.value,
            domain=cookie.domain,
            path=cookie.path,
            secure=cookie.secure,
            expires=cookie.expires,
            rest={'HttpOnly': cookie.has_nonstandard_attr('HttpOnly') or cookie.has_nonstandard_attr('httponly')} # Requests uses 'rest' for HttpOnly
        ))

    # print(f"Returning RequestsCookieJar with {len(cookie_jar)} cookies.")
    if len(cookie_jar) == 0 and os.path.exists(file_path) :
        print(f"WARNING: Cookie file {file_path} was found but no cookies were loaded into the jar. Check file format/content.")
    # else:
        # for cookie in cookie_jar:
            # print(f"DEBUG_COOKIE_IN_JAR: name={cookie.name}, value={cookie.value}, domain={cookie.domain}, path={cookie.path}, secure={cookie.secure}, expires={cookie.expires}, httponly={cookie.get_nonstandard_attr('HttpOnly')}")
    return cookie_jar


def get_youtube_homepage_html(cookies_jar=None):
    url = "https://www.youtube.com/"
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    if cookies_jar and len(cookies_jar) > 0:
        session.cookies.update(cookies_jar)
        # print("DEBUG: Cookies sent with homepage request:")
        # for cookie in session.cookies:
            # print(f"  {cookie.name}={cookie.value}; domain={cookie.domain}; path={cookie.path}; secure={cookie.secure}; httponly={cookie.get_nonstandard_attr('HttpOnly')}")
    else:
        print("DEBUG: No cookies provided or jar is empty for homepage request.")

    try:
        # print(f"DEBUG: Requesting homepage URL: {url} with headers: {session.headers}")
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching YouTube homepage: {e}")
        return None

def search_youtube_html(query, cookies_jar=None):
    url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    if cookies_jar:
        session.cookies.update(cookies_jar)

    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching YouTube search results for '{query}': {e}")
        return None

def get_nested(data, keys, default=None):
    """Helper function to safely navigate deeply nested JSON-like structures."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list):
            try:
                if isinstance(key, int):
                    data = data[key]
                else: # Should not happen if keys are well-defined
                    return default
            except IndexError:
                return default
        else:
            return default
        if data is None:
            return default
    return data

def parse_video_data_from_script(html_content):
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, 'html.parser')
    scripts = soup.find_all('script')
    video_data = []
    yt_initial_data = None

    for script in scripts:
        script_text = script.string
        if script_text and ('var ytInitialData = ' in script_text or 'window["ytInitialData"] = ' in script_text):
            try:
                # Attempt to extract the JSON object string
                if 'var ytInitialData = ' in script_text:
                    json_str = script_text.split('var ytInitialData = ', 1)[1].rstrip(';')
                elif 'window["ytInitialData"] = ' in script_text:
                    json_str = script_text.split('window["ytInitialData"] = ', 1)[1].rstrip(';')
                else:
                    continue # Should not happen due to outer if

                # Clean up potential trailing characters like </script>
                if json_str.endswith("</script>"):
                    json_str = json_str[:-len("</script>")]

                yt_initial_data = json.loads(json_str)
                # print("Successfully extracted and parsed ytInitialData.") # Debug
                break
            except Exception as e:
                # print(f"Error processing script tag for ytInitialData: {e}") # Debug
                yt_initial_data = None
                continue

    if not yt_initial_data:
        print("Failed to find or parse ytInitialData from any script tag.")
        return []

    # Paths to video lists can vary. Try common ones.
    paths_to_try = [
        ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'richGridRenderer', 'contents'], # Homepage grid
        ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents', 'sectionListRenderer', 'contents', 0, 'itemSectionRenderer', 'contents'], # Search results
        ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'sectionListRenderer', 'contents', 0, 'itemSectionRenderer', 'contents'] # Another homepage/feed variant
    ]

    raw_video_items = None
    for path in paths_to_try:
        raw_video_items = get_nested(yt_initial_data, path)
        if raw_video_items:
            # print(f"Found video items at path: {path}") # Debug
            break

    # If the direct paths fail, sometimes items are nested further within sectionListRenderer
    if not raw_video_items:
        section_list_contents = get_nested(yt_initial_data, ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents', 'sectionListRenderer', 'contents']) or \
                                get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'sectionListRenderer', 'contents'])
        if section_list_contents and isinstance(section_list_contents, list):
            for section_content_item in section_list_contents:
                item_section = get_nested(section_content_item, ['itemSectionRenderer', 'contents'])
                if item_section:
                    raw_video_items = item_section
                    # print("Found video items in nested itemSectionRenderer.") # Debug
                    break

    if not raw_video_items or not isinstance(raw_video_items, list):
        print("Could not find video items list in ytInitialData using known paths.")
        return []

    for item in raw_video_items:
        video_renderer = get_nested(item, ['richItemRenderer', 'content', 'videoRenderer']) or \
                         item.get('videoRenderer') # Direct videoRenderer

        if video_renderer:
            try:
                video_id = video_renderer.get('videoId')
                title = get_nested(video_renderer, ['title', 'runs', 0, 'text']) or \
                        get_nested(video_renderer, ['title', 'simpleText'])

                thumbnails = get_nested(video_renderer, ['thumbnail', 'thumbnails'])
                thumbnail_url = thumbnails[-1]['url'] if thumbnails and isinstance(thumbnails, list) and thumbnails[-1] and 'url' in thumbnails[-1] else None

                channel_name_runs = get_nested(video_renderer, ['longBylineText', 'runs'])
                channel_name = None
                channel_url_suffix = None

                if channel_name_runs and isinstance(channel_name_runs, list) and len(channel_name_runs) > 0 and 'text' in channel_name_runs[0]:
                    channel_name = channel_name_runs[0].get('text')
                    channel_url_suffix = get_nested(channel_name_runs[0], ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                         get_nested(channel_name_runs[0], ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])


                if not channel_name: # Fallback for channel name
                    short_byline_runs = get_nested(video_renderer, ['shortBylineText', 'runs'])
                    if short_byline_runs and isinstance(short_byline_runs, list) and len(short_byline_runs) > 0 and 'text' in short_byline_runs[0]:
                        channel_name = short_byline_runs[0].get('text')
                        if not channel_url_suffix:
                             channel_url_suffix = get_nested(short_byline_runs[0], ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                                  get_nested(short_byline_runs[0], ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])

                if video_id and title and thumbnail_url:
                    video_data.append({
                        'title': title,
                        'url': f'https://www.youtube.com/watch?v={video_id}',
                        'thumbnail': thumbnail_url,
                        'channel_name': channel_name or "N/A",
                        'channel_url': f'https://www.youtube.com{channel_url_suffix}' if channel_url_suffix else '#'
                    })
            except Exception as e:
                # print(f"Error parsing a videoRenderer item: {e}. Item: {video_renderer}") # Debug
                continue

    if not video_data:
        print("Found ytInitialData, but failed to extract any video details using current parsing logic.")
    # else:
        # print(f"Successfully parsed {len(video_data)} videos from ytInitialData.") # Debug

    return video_data


def get_homepage_videos_parsed(): # Renamed to avoid clash with minimal version if any old state exists
    """Fetches and parses videos from the YouTube homepage."""
    cookies = load_cookies()
    html_content = get_youtube_homepage_html(cookies)
    if html_content:
        return parse_video_data_from_script(html_content)
    return []

def search_videos_parsed(query): # Renamed
    """Fetches and parses videos from YouTube search results."""
    cookies = load_cookies()
    html_content = search_youtube_html(query, cookies)
    if html_content:
        return parse_video_data_from_script(html_content)
    return []

# For the minimal app.py test, it uses get_some_data.
# We'll switch app.py to use the parsed functions once it's restored.
def get_some_data():
    """Minimal function for testing that was used by minimal app.py."""
    # Ensure config is actually usable here
    if hasattr(config, 'COOKIE_FILE_PATH'):
        return f"Data from youtube_api, using cookie path: {config.COOKIE_FILE_PATH}"
    else:
        return "Data from youtube_api, but config.COOKIE_FILE_PATH not found!"
