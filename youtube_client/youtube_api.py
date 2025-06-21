import json
import requests
from bs4 import BeautifulSoup
from . import config # Import config

# Configuration for cookie file is now in config.py
# COOKIE_FILE = 'cookies.json' # Old way

# Standard headers to mimic a browser. This might need adjustments.
BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'DNT': '1', # Do Not Track
    'Upgrade-Insecure-Requests': '1'
}

def load_cookies():
    """Loads cookies from the COOKIE_FILE_PATH specified in config."""
    try:
        with open(config.COOKIE_FILE_PATH, 'r') as f:
            cookies_list = json.load(f) # Expecting a list of cookie objects

        # Convert list of cookie objects to a dictionary suitable for requests
        cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies_list}
        return cookies_dict
    except FileNotFoundError:
        print(f"Warning: Cookie file '{config.COOKIE_FILE_PATH}' not found. Requests will be made without authentication.")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{config.COOKIE_FILE_PATH}'. Please ensure it's valid JSON.")
        return None
    except Exception as e:
        print(f"An error occurred while loading cookies: {e}")
        return None

def get_youtube_homepage_html(cookies=None):
    """
    Fetches the YouTube homepage HTML.
    Tries to use cookies if provided.
    """
    url = "https://www.youtube.com/"
    headers = BASE_HEADERS.copy()

    session = requests.Session()
    session.headers.update(headers)

    if cookies:
        session.cookies.update(cookies)

    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching YouTube homepage: {e}")
        return None

def search_youtube_html(query, cookies=None):
    """
    Fetches YouTube search results page HTML for a given query.
    Tries to use cookies if provided.
    """
    url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    headers = BASE_HEADERS.copy()

    session = requests.Session()
    session.headers.update(headers)

    if cookies:
        session.cookies.update(cookies)

    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching YouTube search results for '{query}': {e}")
        return None

# --- Placeholder parsing functions ---
# These will be significantly more complex and are the core challenge.
# We'll need to inspect YouTube's HTML/JavaScript to implement these correctly.

def parse_video_data_from_script(html_content):
    """
    Attempts to parse video data directly from <script> tags in YouTube's HTML,
    often where initial data is embedded as JSON. This is a common pattern.
    This is a complex task and highly dependent on YouTube's current structure.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    scripts = soup.find_all('script')
    video_data = []
    yt_initial_data = None

    for script in scripts:
        if script.string and 'var ytInitialData = ' in script.string:
            try:
                json_str = script.string.split('var ytInitialData = ', 1)[1].rstrip(';')
                # It might be `window["ytInitialData"] = ` or `var ytInitialData = `
                # Let's try to make it more robust for extraction
                if json_str.endswith("</script>"): # handle case where rstrip(';') is not enough
                    json_str = json_str[:-len("</script>")]

                # More robust split: find the start of the JSON object after the variable assignment
                potential_json_starts = [
                    'var ytInitialData = {',
                    'window["ytInitialData"] = {',
                    'ytInitialData = {'
                ]
                found_json = False
                for start_pattern in potential_json_starts:
                    if start_pattern[:-1] in script.string: # Check for pattern minus the opening brace
                        # Manually find the start and end of the JSON object
                        # This is tricky because the JSON itself can contain braces
                        obj_start_index = script.string.find(start_pattern[-1], script.string.find(start_pattern[:-1]))
                        if obj_start_index != -1:
                            balance = 0
                            obj_end_index = -1
                            # Iterate through the string to find the matching closing brace
                            for i in range(obj_start_index, len(script.string)):
                                if script.string[i] == '{':
                                    balance += 1
                                elif script.string[i] == '}':
                                    balance -= 1
                                    if balance == 0:
                                        obj_end_index = i + 1
                                        break
                            if obj_end_index != -1:
                                json_str = script.string[obj_start_index:obj_end_index]
                                yt_initial_data = json.loads(json_str)
                                found_json = True
                                break # Found and parsed
                if not found_json:
                    # Fallback to simpler split if the robust one fails.
                    # This was the original simpler approach.
                    json_str_parts = script.string.split('var ytInitialData = ')
                    if len(json_str_parts) > 1:
                        json_str = json_str_parts[1].rstrip(';')
                        if json_str.endswith("</script>"):
                           json_str = json_str[:-len("</script>")]
                        yt_initial_data = json.loads(json_str)
                    else: # Try another common pattern
                        json_str_parts = script.string.split('window["ytInitialData"] = ')
                        if len(json_str_parts) > 1:
                            json_str = json_str_parts[1].rstrip(';')
                            if json_str.endswith("</script>"):
                                json_str = json_str[:-len("</script>")]
                            yt_initial_data = json.loads(json_str)

                if not yt_initial_data:
                    print("Could not extract ytInitialData JSON string.")
                    continue # Try next script tag

                print("Successfully extracted and parsed ytInitialData.")
                break # Found ytInitialData, no need to check other script tags
            except Exception as e:
                print(f"Error processing script tag for ytInitialData: {e}")
                yt_initial_data = None # Ensure it's reset if parsing fails
                continue

    if not yt_initial_data:
        print("Failed to find or parse ytInitialData from any script tag.")
        return []

    # Now, try to extract video information from ytInitialData
    # This structure can change, so it needs to be robust or updated frequently.

    # Helper function to safely navigate the deeply nested JSON
    def get_nested(data, keys, default=None):
        for key in keys:
            if isinstance(data, dict):
                data = data.get(key)
            elif isinstance(data, list):
                try:
                    data = data[key]
                except (IndexError, TypeError): # TypeError if key is not int for list
                    return default
            else:
                return default
            if data is None:
                return default
        return data

    # Try parsing for homepage (richGridRenderer)
    # Path: contents.twoColumnBrowseResultsRenderer.tabs[0].tabRenderer.content.richGridRenderer.contents
    raw_video_items = get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'richGridRenderer', 'contents'])

    if not raw_video_items:
        # Try parsing for search results (itemSectionRenderer)
        # Path: contents.twoColumnSearchResultsRenderer.primaryContents.sectionListRenderer.contents[0].itemSectionRenderer.contents
        raw_video_items = get_nested(yt_initial_data, ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents', 'sectionListRenderer', 'contents', 0, 'itemSectionRenderer', 'contents'])

    if not raw_video_items:
        # Try another common path for search or general lists (often within sectionListRenderer)
        section_list_contents = get_nested(yt_initial_data, ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents', 'sectionListRenderer', 'contents'])
        if section_list_contents:
            for section in section_list_contents:
                item_section = get_nested(section, ['itemSectionRenderer', 'contents'])
                if item_section:
                    raw_video_items = item_section
                    break

    if not raw_video_items:
        # A path sometimes seen for homepage or subscriptions (sectionListRenderer directly under tabs content)
        raw_video_items = get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'sectionListRenderer', 'contents', 0, 'itemSectionRenderer', 'contents'])


    if not raw_video_items:
        print("Could not find video items list in ytInitialData using known paths.")
        return []

    for item in raw_video_items:
        video_renderer = None
        if 'richItemRenderer' in item:
            video_renderer = get_nested(item, ['richItemRenderer', 'content', 'videoRenderer'])
        elif 'videoRenderer' in item:
            video_renderer = item.get('videoRenderer')
        # Add other item types like 'compactVideoRenderer' if needed

        if video_renderer:
            try:
                video_id = video_renderer.get('videoId')
                title = get_nested(video_renderer, ['title', 'runs', 0, 'text']) or get_nested(video_renderer, ['title', 'simpleText'])
                thumbnails = get_nested(video_renderer, ['thumbnail', 'thumbnails'])
                thumbnail_url = thumbnails[-1]['url'] if thumbnails and isinstance(thumbnails, list) and thumbnails[-1] and 'url' in thumbnails[-1] else None

                channel_name_runs = get_nested(video_renderer, ['longBylineText', 'runs'])
                channel_name = None
                channel_url_suffix = None
                if channel_name_runs and isinstance(channel_name_runs, list) and channel_name_runs[0]:
                    channel_name = channel_name_runs[0].get('text')
                    channel_url_suffix = get_nested(channel_name_runs[0], ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])

                if not channel_name: # Fallback for channel name
                    channel_name = get_nested(video_renderer, ['shortBylineText', 'runs', 0, 'text'])
                    if not channel_url_suffix: # And its URL
                         channel_url_suffix = get_nested(video_renderer, ['shortBylineText', 'runs', 0, 'navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])


                if video_id and title and thumbnail_url:
                    video_data.append({
                        'title': title,
                        'url': f'https://www.youtube.com/watch?v={video_id}',
                        'thumbnail': thumbnail_url,
                        'channel_name': channel_name or "N/A",
                        'channel_url': f'https://www.youtube.com{channel_url_suffix}' if channel_url_suffix else '#'
                    })
            except Exception as e:
                print(f"Error parsing a videoRenderer item: {e}. Item: {video_renderer}")
                continue

    if not video_data:
        print("Found ytInitialData, but failed to extract any video details using current parsing logic.")
    else:
        print(f"Successfully parsed {len(video_data)} videos from ytInitialData.")

    return video_data


def parse_videos_from_html(html_content):
    """
    Parses video information from YouTube HTML content.
    This is a fallback if JSON parsing from script tags is not feasible or fails.
    This is highly susceptible to changes in YouTube's page structure.
    """
    if not html_content:
        return []

    # First, attempt to parse using the script data method
    videos = parse_video_data_from_script(html_content)
    if videos:
        return videos

    # Fallback to more direct (and fragile) HTML parsing if script parsing fails
    print("Falling back to basic HTML parsing (less reliable).")
    soup = BeautifulSoup(html_content, 'html.parser')
    video_data = []

    # This is a generic placeholder and will likely NOT work without specific selectors
    # found by inspecting YouTube's current HTML structure for video listings.
    # For example, YouTube might use elements like <ytd-rich-item-renderer> or similar.
    # We would need to find the container for each video and then extract elements within it.

    # Example (highly speculative, WILL need adjustment):
    # for item in soup.find_all('div', class_='some-video-container-class'):
    #     try:
    #         title_tag = item.find('a', id='video-title')
    #         thumb_tag = item.find('img') # This is too generic
    #         channel_tag = item.find('a', class_='yt-simple-endpoint style-scope yt-formatted-string')
    #
    #         if title_tag and title_tag.has_attr('href') and thumb_tag:
    #             title = title_tag.text.strip()
    #             url = 'https://www.youtube.com' + title_tag['href']
    #             thumbnail = thumb_tag.get('src', '') # Might need to check data-src or other attributes
    #             channel_name = channel_tag.text.strip() if channel_tag else "N/A"
    #             channel_url = 'https://www.youtube.com' + channel_tag['href'] if channel_tag and channel_tag.has_attr('href') else "#"
    #
    #             video_data.append({
    #                 'title': title,
    #                 'url': url,
    #                 'thumbnail': thumbnail,
    #                 'channel_name': channel_name,
    #                 'channel_url': channel_url
    #             })
    #     except Exception as e:
    #         print(f"Error parsing a video item: {e}")

    if not video_data:
        print("Basic HTML parsing did not find any video items with current selectors.")
    return video_data


def get_homepage_videos():
    """Fetches and parses videos from the YouTube homepage."""
    cookies = load_cookies()
    html_content = get_youtube_homepage_html(cookies)
    if html_content:
        return parse_videos_from_html(html_content)
    return []

def search_videos(query):
    """Fetches and parses videos from YouTube search results."""
    cookies = load_cookies() # Cookies might influence search results
    html_content = search_youtube_html(query, cookies)
    if html_content:
        return parse_videos_from_html(html_content)
    return []

if __name__ == '__main__':
    # Example usage (for testing this module directly)
    print("Attempting to load cookies...")
    my_cookies = load_cookies()
    if my_cookies:
        print("Cookies loaded successfully.")
    else:
        print("No cookies loaded or error during loading. Proceeding without authentication.")

    print("\nFetching homepage videos...")
    homepage_vids = get_homepage_videos()
    if homepage_vids:
        print(f"Found {len(homepage_vids)} videos on homepage (or from parsed data):")
        for vid in homepage_vids[:2]: # Print first 2
            print(f"  Title: {vid['title']}")
            print(f"  URL: {vid['url']}")
            print(f"  Thumbnail: {vid['thumbnail']}")
    else:
        print("Could not fetch or parse homepage videos.")

    print("\nSearching for 'Python programming'...")
    search_results_vids = search_videos("Python programming")
    if search_results_vids:
        print(f"Found {len(search_results_vids)} videos for 'Python programming':")
        for vid in search_results_vids[:2]: # Print first 2
            print(f"  Title: {vid['title']}")
            print(f"  URL: {vid['url']}")
            print(f"  Thumbnail: {vid['thumbnail']}")
    else:
        print("Could not fetch or parse search results.")
