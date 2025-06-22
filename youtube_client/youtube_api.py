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

def parse_video_data_from_script(html_content, context=None): # Added context
    if not html_content:
        return {'videos': [], 'continuation_token': None} # Return dict

    soup = BeautifulSoup(html_content, 'html.parser')
    scripts = soup.find_all('script')
    video_data_list = [] # Renamed to avoid confusion with video_data dict
    yt_initial_data = None
    continuation_token = None # Initialize continuation token

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

    if context == "subscriptions":
        # Subscriptions page structure often uses sectionListRenderer directly under a tab's content.
        # Path: contents.twoColumnBrowseResultsRenderer.tabs[0].tabRenderer.content.sectionListRenderer.contents
        # Each item in 'contents' can be an itemSectionRenderer or sometimes directly videoShelfRenderer etc.
        # We are looking for itemSectionRenderer -> contents -> gridVideoRenderer or videoRenderer

        # Try a common path for subscriptions (often the "Latest" or default view)
        # This usually involves finding the "shelf" renderers or item section renderers
        # within the main content area of the subscriptions tab.

        # Path 1: Direct sectionListRenderer under the primary tab content
        sections = get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'sectionListRenderer', 'contents'])
        if sections and isinstance(sections, list):
            for section in sections:
                # Each section could be an itemSectionRenderer or a richShelfRenderer, etc.
                # Look for itemSectionRenderer which usually holds a list of videos
                item_section_contents = get_nested(section, ['itemSectionRenderer', 'contents'])
                if item_section_contents and isinstance(item_section_contents, list):
                    raw_video_items = item_section_contents # This list should contain video renderers
                    print(f"API_PARSE(Subs): Found video items via itemSectionRenderer in subscriptions tab (Path 1). Count: {len(raw_video_items)}")
                    break

                # Sometimes videos are in a "gridRenderer" within a "shelfRenderer" or "richShelfRenderer"
                shelf_contents = get_nested(section, ['richShelfRenderer', 'contents']) \
                                 or get_nested(section, ['shelfRenderer', 'content', 'gridRenderer', 'items']) \
                                 or get_nested(section, ['shelfRenderer', 'content', 'expandedShelfContentsRenderer', 'items']) \
                                 or get_nested(section, ['shelfRenderer', 'content', 'verticalListRenderer', 'items']) # Less common for main vids

                if shelf_contents and isinstance(shelf_contents, list) and not raw_video_items: # Check if not already found
                    # These items might be gridVideoRenderer or videoRenderer directly
                    # Or they could be richItemRenderer containing them.
                    # The main parsing loop below handles richItemRenderer vs videoRenderer.
                    raw_video_items = shelf_contents
                    print(f"API_PARSE(Subs): Found video items via shelf/gridRenderer in subscriptions tab (Path 1 variant). Count: {len(raw_video_items)}")
                    break
            if raw_video_items: # Found in the first tab's sectionListRenderer
                 pass # Proceed to parsing loop
            else:
                print(f"API_PARSE(Subs): No video items found in the first tab's sectionListRenderer using common sub-paths.")
        else:
            print(f"API_PARSE(Subs): Could not find sectionListRenderer for subscriptions tab (Path 1 base).")

    if not raw_video_items: # Fallback to general paths if subscriptions context didn't yield results or context is not 'subscriptions'
        print(f"API_PARSE: Context '{context}' did not yield specific results or no context. Trying general paths...")
        for path in paths_to_try: # paths_to_try was defined before for homepage/search
            raw_video_items = get_nested(yt_initial_data, path)
            if raw_video_items:
                print(f"API_PARSE: Found video items at general path: {path}. Count: {len(raw_video_items)}")
                break

        if not raw_video_items: # Further fallback for general lists
            section_list_contents = get_nested(yt_initial_data, ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents', 'sectionListRenderer', 'contents']) or \
                                    get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'sectionListRenderer', 'contents'])
            if section_list_contents and isinstance(section_list_contents, list):
                for section_content_item in section_list_contents:
                    item_section = get_nested(section_content_item, ['itemSectionRenderer', 'contents'])
                    if item_section:
                        raw_video_items = item_section
                        print(f"API_PARSE: Found video items in nested itemSectionRenderer (general fallback). Count: {len(raw_video_items)}")
                        break

    if not raw_video_items or not isinstance(raw_video_items, list):
        print(f"API_PARSE: Could not find video items list in ytInitialData for context '{context}' using any known paths.")
        return {'videos': [], 'continuation_token': None}

    item_count = 0
    for item in raw_video_items:
        # Try to find continuation token first (usually at the end of item list)
        continuation_item_renderer = get_nested(item, ['continuationItemRenderer'])
        if continuation_item_renderer:
            token = get_nested(continuation_item_renderer, ['continuationEndpoint', 'continuationCommand', 'token'])
            if token:
                continuation_token = token
                print(f"API_PARSE: Found continuation token: {token[:20]}...") # Print first 20 chars
                # Typically, we stop processing items once a continuation token is found in that list.
                # Or, it might be the very last item.
                # For now, we'll assume if we find it, we store it and continue processing other items in *this* batch.
                # In many YT structures, the continuationItemRenderer is the *last* item in a batch.

        video_renderer = get_nested(item, ['gridVideoRenderer']) or \
                         get_nested(item, ['videoRenderer']) or \
                         get_nested(item, ['richItemRenderer', 'content', 'videoRenderer']) # Common pattern

        if video_renderer:
            try:
                video_id = video_renderer.get('videoId')
                title_obj = video_renderer.get('title', {})
                title = get_nested(title_obj, ['runs', 0, 'text']) or title_obj.get('simpleText')

                thumbnails = get_nested(video_renderer, ['thumbnail', 'thumbnails'])
                thumbnail_url = thumbnails[-1]['url'] if thumbnails and isinstance(thumbnails, list) and thumbnails[-1] and 'url' in thumbnails[-1] else None

                # Channel Info
                long_byline = get_nested(video_renderer, ['longBylineText', 'runs', 0])
                short_byline = get_nested(video_renderer, ['shortBylineText', 'runs', 0])
                owner_text_runs = get_nested(video_renderer, ['ownerText', 'runs', 0])

                channel_name = None
                channel_url_suffix = None

                if long_byline and 'text' in long_byline:
                    channel_name = long_byline.get('text')
                    channel_url_suffix = get_nested(long_byline, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                         get_nested(long_byline, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])
                elif short_byline and 'text' in short_byline:
                    channel_name = short_byline.get('text')
                    channel_url_suffix = get_nested(short_byline, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                         get_nested(short_byline, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])
                elif owner_text_runs and 'text' in owner_text_runs: # Common in search results
                     channel_name = owner_text_runs.get('text')
                     channel_url_suffix = get_nested(owner_text_runs, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                          get_nested(owner_text_runs, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])


                # Duration and Published Time
                duration_text = get_nested(video_renderer, ['lengthText', 'simpleText']) or \
                                "".join(run.get('text', '') for run in get_nested(video_renderer, ['lengthText', 'runs'], default=[]))
                published_time_text = get_nested(video_renderer, ['publishedTimeText', 'simpleText'])

                if video_id and title and thumbnail_url:
                    video_data_list.append({
                        'video_id': video_id, # Corrected: was 'title'
                        'url': f'https://www.youtube.com/watch?v={video_id}',
                        'title': title,
                        'thumbnail': thumbnail_url,
                        'channel_name': channel_name or "N/A",
                        'channel_url': f'https://www.youtube.com{channel_url_suffix}' if channel_url_suffix and channel_url_suffix.startswith('/') else (channel_url_suffix or '#'),
                        'duration_text': duration_text or "N/A",
                        'published_time_text': published_time_text or "N/A"
                    })
                    item_count += 1
                    if limit and item_count >= limit:
                        print(f"API_PARSE: Reached item limit of {limit}. Parsed {item_count} videos.")
                        break # Stop if limit is reached
            except Exception as e:
                print(f"API_PARSE: Error parsing a videoRenderer/gridVideoRenderer item: {e}. Item snippet: {str(video_renderer)[:200]}")
                continue

    if not video_data_list:
        print(f"API_PARSE: Found ytInitialData for context '{context}', but failed to extract any video details using current parsing logic.")
    else:
        print(f"API_PARSE: Successfully parsed {len(video_data_list)} videos for context '{context}'.")

    return {'videos': video_data_list, 'continuation_token': continuation_token}


def get_homepage_videos_parsed(limit=30): # Added limit
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
# def get_some_data(): # This was for initial import testing, no longer primary.
#    """Minimal function for testing that was used by minimal app.py."""
#    if hasattr(config, 'COOKIE_FILE_PATH'):
#        return f"Data from youtube_api, using cookie path: {config.COOKIE_FILE_PATH}"
#    else:
#        return "Data from youtube_api, but config.COOKIE_FILE_PATH not found!"

def get_subscriptions_feed_parsed():
    """
    Placeholder for fetching and parsing the YouTube subscriptions feed.
    This will require new logic to find the correct ytInitialData structure
    or specific API calls if any are made by the subscriptions page.
    """
    This will require new logic to find the correct ytInitialData structure
    or specific API calls if any are made by the subscriptions page.
    """
    print("API: Attempting to fetch and parse actual subscriptions feed...")
    cookies = load_cookies()
    if not cookies or len(cookies) == 0:
        print("API: No cookies loaded, cannot fetch subscriptions feed.")
        return {'videos': [], 'continuation_token': None} # Return dict

    url = "https://www.youtube.com/feed/subscriptions"
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    session.cookies.update(cookies)

    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        # parse_video_data_from_script will now also try to find a continuation token
        parsed_data = parse_video_data_from_script(response.text, context="subscriptions", limit=30)
        return parsed_data # Expecting {'videos': [...], 'continuation_token': ...}
    except requests.exceptions.RequestException as e:
        print(f"API Error: Could not fetch subscriptions page: {e}")
        return {'videos': [], 'continuation_token': None}
    except Exception as e:
        print(f"API Error: Unexpected error fetching subscriptions: {e}")
        return {'videos': [], 'continuation_token': None}

def get_more_home_videos_parsed(next_page_token=None, continuation_data=None):
    """
    Placeholder for fetching more homepage videos (infinite scroll).
    Will eventually use continuation_data. For now, returns static list.
    Output should be: {'videos': [...], 'continuation_token': '...'}.
    """
    print(f"API_PLACEHOLDER: get_more_home_videos_parsed called (token: {next_page_token}, data: {continuation_data}) - returning STATIC list for now.")
    # Simulate fetching data.
    static_more_videos = [
        {
            'video_id': f'moreHomeVid{i}',
            'youtube_url': f'https://www.youtube.com/watch?v=moreHomeVid{i}',
            'title': f'More Home Video {i} (Static)',
            'thumbnail_url': 'https://i.ytimg.com/vi/static_placeholder/hqdefault.jpg',
            'channel_name': f'Channel for More {i}',
            'channel_url': '#',
            'duration_text': '10:00',
            'published_time_text': f'{i} day(s) ago'
        } for i in range(1, 4) # 3 more videos
    ]
    return {'videos': static_more_videos, 'continuation_token': f'fake_home_cont_token_{int(time.time())}'} # New fake token

def get_more_subscriptions_videos_parsed(continuation_data=None):
    """
    Placeholder for fetching more subscription videos.
    Output should be: {'videos': [...], 'continuation_token': '...'}.
    """
    print(f"API_PLACEHOLDER: get_more_subscriptions_videos_parsed called (data: {continuation_data}) - returning STATIC list for now.")
    static_more_subs_videos = [
        {
            'video_id': f'moreSubVid{i}',
            'youtube_url': f'https://www.youtube.com/watch?v=moreSubVid{i}',
            'title': f'More Subscription Video {i} (Static)',
            'thumbnail_url': 'https://i.ytimg.com/vi/static_placeholder_subs/hqdefault.jpg',
            'channel_name': f'Subscribed Channel More {i}',
            'channel_url': '#',
            'duration_text': '05:30',
            'published_time_text': f'{i+3} day(s) ago'
        } for i in range(1, 3) # 2 more videos
    ]
    return {'videos': static_more_subs_videos, 'continuation_token': f'fake_subs_cont_token_{int(time.time())}'}


def get_more_channel_videos_parsed(channel_url, continuation_data=None):
    """
    Placeholder for fetching more channel videos.
    Output should be: {'videos': [...], 'continuation_token': '...'}.
    """
    print(f"API_PLACEHOLDER: get_more_channel_videos_parsed for {channel_url} (data: {continuation_data}) - returning STATIC list.")
    static_more_channel_videos = [
        {
            'video_id': f'moreChanVid{i}',
            'youtube_url': f'https://www.youtube.com/watch?v=moreChanVid{i}',
            'title': f'More Channel Video {i} (Static from {channel_url})',
            'thumbnail_url': 'https://i.ytimg.com/vi/static_placeholder_chan/hqdefault.jpg',
            'channel_name': f'Channel from URL',
            'channel_url': channel_url,
            'duration_text': '12:12',
            'published_time_text': f'{i*2} day(s) ago'
        } for i in range(1, 3)
    ]
    return {'videos': static_more_channel_videos, 'continuation_token': f'fake_chan_cont_token_{int(time.time())}'}


def get_more_recommended_videos_parsed(current_video_id, continuation_data=None):
    """
    Placeholder for fetching more recommended videos.
    Output should be: {'videos': [...], 'continuation_token': '...'}.
    """
    print(f"API_PLACEHOLDER: get_more_recommended_videos_parsed for {current_video_id} (data: {continuation_data}) - returning STATIC list.")
    static_more_reco_videos = [
        {
            'video_id': f'moreRecoVid{i}',
            'youtube_url': f'https://www.youtube.com/watch?v=moreRecoVid{i}',
            'title': f'More Recommended Video {i} (Static)',
            'thumbnail_url': 'https://i.ytimg.com/vi/static_placeholder_reco/hqdefault.jpg',
            'channel_name': f'Reco Channel {i}',
            'channel_url': '#',
            'duration_text': '08:00',
            'published_time_text': f'{i} hour(s) ago'
        } for i in range(1, 3)
    ]
    return {'videos': static_more_reco_videos, 'continuation_token': f'fake_reco_cont_token_{int(time.time())}'}


# --- Original get_more_home_videos_parsed (now with correct signature but static data) ---
def get_more_home_videos_parsed(continuation_data=None): # Ensure signature matches new use
    """
    Placeholder for fetching more homepage videos (infinite scroll).
    Will eventually use continuation_data. For now, returns static list.
    This will require identifying how these tokens are passed and what request to make.
    """
    print(f"API_PLACEHOLDER: get_more_home_videos_parsed called (token: {next_page_token}, data: {continuation_data}) - returning empty list for now.")
    # cookies = load_cookies()
    # html_content_or_json_response = # ... fetch more videos using token/data ...
    # if html_content_or_json_response:
    #     # Parsing logic might differ for continuation responses (often JSON directly)
    #     return parse_video_data_from_continuation(html_content_or_json_response)
    return []

# Placeholder for a function that would parse continuation data (often JSON)
# def parse_video_data_from_continuation(json_response):
#    video_data = []
#    # ... logic to extract video renderers from the continuation JSON ...
#    return video_data

def get_recommended_videos_for_player(current_video_id=None):
    """
    Placeholder for fetching and parsing recommended videos for the currently playing video.
    For now, returns a static list, ignoring current_video_id.
    """
    print(f"API_PLACEHOLDER: get_recommended_videos_for_player called (for video: {current_video_id}) - returning STATIC list.")
    static_reco_videos = [
        {
            'video_id': 'recoVid1',
            'youtube_url': 'https://www.youtube.com/watch?v=recoVid1',
            'title': 'Recommended: Fun Adventure Time!',
            'thumbnail_url': 'https://i.ytimg.com/vi/3yNSF7w2T9c/hqdefault.jpg', # Placeholder
            'channel_name': 'Adventure Vids',
            'channel_url': '#'
        },
        {
            'video_id': 'recoVid2',
            'youtube_url': 'https://www.youtube.com/watch?v=recoVid2',
            'title': 'You Might Also Like: Cooking Show Ep 5',
            'thumbnail_url': 'https://i.ytimg.com/vi/6Af6b_wyiwI/hqdefault.jpg', # Placeholder
            'channel_name': 'Kitchen Delights',
            'channel_url': '#'
        },
        {
            'video_id': 'recoVid3',
            'youtube_url': 'https://www.youtube.com/watch?v=recoVid3',
            'title': 'Up Next (Static): Learning Python Basics',
            'thumbnail_url': 'https://i.ytimg.com/vi/x7Xzbcq_xG4/hqdefault.jpg', # Placeholder
            'channel_name': 'Code Master',
            'channel_url': '#'
        }
    ]
    # Ensure no recommendation is the same as the current video
    return [v for v in static_reco_videos if v['video_id'] != current_video_id][:3] # Max 3 recos

def get_channel_videos_parsed(channel_url):
    """
    Placeholder for fetching and parsing videos from a specific YouTube channel page.
    For now, returns a static list of sample videos.
    Actual implementation would fetch channel_url/videos and parse ytInitialData.
    """
    print(f"API_PLACEHOLDER: get_channel_videos_parsed called for URL '{channel_url}' - returning STATIC list.")
    # Extract a pseudo channel name from URL for varied static data (optional)
    pseudo_channel_name = "UnknownChannel"
    if channel_url:
        if "/@" in channel_url:
            pseudo_channel_name = channel_url.split("/@")[1].split("/")[0]
        elif "/channel/" in channel_url:
            pseudo_channel_name = channel_url.split("/channel/")[1].split("/")[0]

    static_channel_videos = [
        {
            'video_id': f'chanVid1_{pseudo_channel_name}',
            'youtube_url': f'https://www.youtube.com/watch?v=chanVid1_{pseudo_channel_name}',
            'title': f'Video 1 from {pseudo_channel_name} (Static)',
            'thumbnail_url': 'https://i.ytimg.com/vi/ primjer/hqdefault.jpg', # Generic placeholder
            'channel_name': pseudo_channel_name,
            'channel_url': channel_url # Pass original channel_url back
        },
        {
            'video_id': f'chanVid2_{pseudo_channel_name}',
            'youtube_url': f'https://www.youtube.com/watch?v=chanVid2_{pseudo_channel_name}',
            'title': f'Second Video by {pseudo_channel_name} - Static Data',
            'thumbnail_url': 'https://i.ytimg.com/vi_primjer/hqdefault.jpg', # Generic placeholder
            'channel_name': pseudo_channel_name,
            'channel_url': channel_url
        }
    ]
    return static_channel_videos
