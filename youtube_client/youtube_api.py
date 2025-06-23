import json
import requests
from bs4 import BeautifulSoup
from http.cookiejar import MozillaCookieJar
import os
import time # For fake continuation tokens in placeholders

from youtube_client import config

BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'DNT': '1',
    'Upgrade-Insecure-Requests': '1'
}

def load_cookies():
    cookie_jar = requests.cookies.RequestsCookieJar()
    file_path = config.COOKIE_FILE_PATH
    if not os.path.exists(file_path):
        print(f"Warning: Cookie file '{file_path}' not found.")
        return cookie_jar
    mozilla_jar = MozillaCookieJar(file_path)
    try:
        mozilla_jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as e:
        print(f"Error loading cookies from Netscape file '{file_path}': {e}")
        return cookie_jar
    for cookie in mozilla_jar:
        cookie_jar.set_cookie(requests.cookies.create_cookie(
            name=cookie.name, value=cookie.value, domain=cookie.domain,
            path=cookie.path, secure=cookie.secure, expires=cookie.expires,
            rest={'HttpOnly': cookie.has_nonstandard_attr('HttpOnly') or cookie.has_nonstandard_attr('httponly')}
        ))
    if len(cookie_jar) == 0 and os.path.exists(file_path):
        print(f"WARNING: Cookie file {file_path} found but no cookies loaded. Check format.")
    return cookie_jar

def _make_yt_request(url, cookies_jar):
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    if cookies_jar and len(cookies_jar) > 0:
        session.cookies.update(cookies_jar)
    else:
        print(f"DEBUG: No cookies provided or jar is empty for request to {url}.")
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"API Error: Could not fetch page {url}: {e}")
        return None

def get_youtube_homepage_html(cookies_jar=None): # Retained for direct call if needed
    return _make_yt_request("https://www.youtube.com/", cookies_jar)

def search_youtube_html(query, cookies_jar=None): # Retained
    return _make_yt_request(f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}", cookies_jar)

def get_nested(data, keys, default=None):
    for key in keys:
        if isinstance(data, dict): data = data.get(key)
        elif isinstance(data, list):
            try: data = data[key] if isinstance(key, int) else default
            except IndexError: return default
        else: return default
        if data is None: return default
    return data

def parse_video_data_from_script(html_content, context=None, limit=None):
    if not html_content: return {'videos': [], 'continuation_token': None}
    soup = BeautifulSoup(html_content, 'html.parser')
    scripts = soup.find_all('script')
    yt_initial_data = None
    for script in scripts:
        script_text = script.string
        if script_text and ('var ytInitialData = ' in script_text or 'window["ytInitialData"] = ' in script_text):
            try:
                json_str_part = script_text.split('var ytInitialData = ', 1)[-1].split('window["ytInitialData"] = ', 1)[-1]
                json_str = json_str_part.rstrip(';').split(';</script>')[0]
                yt_initial_data = json.loads(json_str)
                break
            except Exception as e: yt_initial_data = None
    if not yt_initial_data:
        print("API_PARSE: Failed to find or parse ytInitialData.")
        return {'videos': [], 'continuation_token': None}

    video_data_list = []
    continuation_token = None
    raw_video_items = []

    paths_to_try_general = [
        ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'richGridRenderer', 'contents'],
        ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents', 'sectionListRenderer', 'contents', 0, 'itemSectionRenderer', 'contents'],
    ]

    if context == "subscriptions":
        print("API_PARSE(Subs): Attempting subscriptions specific parsing...")
        tab_content = get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content'])
        if tab_content:
            sections = get_nested(tab_content, ['sectionListRenderer', 'contents'])
            if sections and isinstance(sections, list):
                print(f"API_PARSE(Subs): Found {len(sections)} sections in sectionListRenderer.")
                for section_idx, section_content in enumerate(sections):
                    current_section_video_items = get_nested(section_content, ['itemSectionRenderer', 'contents'])
                    if not current_section_video_items: # Try shelf renderers if itemSection not found/empty
                        shelf_renderer = get_nested(section_content, ['shelfRenderer', 'content'])
                        if shelf_renderer:
                            current_section_video_items = get_nested(shelf_renderer, ['gridRenderer', 'items']) or \
                                                          get_nested(shelf_renderer, ['expandedShelfContentsRenderer', 'items'])
                    if current_section_video_items and isinstance(current_section_video_items, list):
                        print(f"API_PARSE(Subs): Section {section_idx} yielded {len(current_section_video_items)} items.")
                        raw_video_items.extend(current_section_video_items)
                        if not continuation_token: # Check for continuation at end of this section's items
                            if current_section_video_items and get_nested(current_section_video_items[-1], ['continuationItemRenderer']):
                                token = get_nested(current_section_video_items[-1], ['continuationItemRenderer', 'continuationEndpoint', 'continuationCommand', 'token'])
                                if token: continuation_token = token; print(f"API_PARSE(Subs): Found continuation in itemSection {section_idx}")
                    # Check for continuation at section level (sometimes for shelves)
                    if not continuation_token:
                         token = get_nested(section_content, ['continuationItemRenderer', 'continuationEndpoint', 'continuationCommand', 'token'])
                         if token: continuation_token = token; print(f"API_PARSE(Subs): Found continuation at section {section_idx} level")
            if not raw_video_items: # Fallback for subs if sectionListRenderer not fruitful
                grid_contents = get_nested(tab_content, ['richGridRenderer', 'contents'])
                if grid_contents and isinstance(grid_contents, list):
                    print(f"API_PARSE(Subs): Using richGridRenderer fallback for subs, {len(grid_contents)} items.")
                    raw_video_items.extend(grid_contents)
                    if not continuation_token and grid_contents and get_nested(grid_contents[-1], ['continuationItemRenderer']):
                         token = get_nested(grid_contents[-1],['continuationItemRenderer','continuationEndpoint','continuationCommand','token'])
                         if token: continuation_token = token; print(f"API_PARSE(Subs): Found continuation in richGridRenderer.")
        if not raw_video_items: print("API_PARSE(Subs): No specific subscription items found via primary paths.")

    if not raw_video_items or context not in ["subscriptions", "channel"]: # If subs parsing failed or other context
        if not raw_video_items: print(f"API_PARSE: No items from context '{context}'. Trying general paths.")
        for path_spec in paths_to_try_general:
            current_batch = get_nested(yt_initial_data, path_spec)
            if current_batch and isinstance(current_batch, list):
                raw_video_items.extend(current_batch)
                if not continuation_token and current_batch and get_nested(current_batch[-1],['continuationItemRenderer']):
                    token = get_nested(current_batch[-1],['continuationItemRenderer','continuationEndpoint','continuationCommand','token'])
                    if token: continuation_token = token; print("API_PARSE: Found continuation in general path.")
                if raw_video_items: break

    if not raw_video_items:
        print(f"API_PARSE: No raw video items found for context '{context}'.")
        return {'videos': [], 'continuation_token': None}

    item_count = 0
    for item_content in raw_video_items:
        if limit and item_count >= limit and continuation_token: # If limit reached and have a token, stop.
             print(f"API_PARSE: Reached item limit of {limit} AND found continuation token. Parsed {item_count} videos.")
             break
        if limit and item_count >=limit and not continuation_token: # If limit reached but no token, still stop.
             print(f"API_PARSE: Reached item limit of {limit} (no continuation token found yet). Parsed {item_count} videos.")
             break


        # If continuation token is found as a standalone item, store it and skip to next item.
        # This must be checked before trying to parse as a video_renderer.
        if not continuation_token: # Only if we haven't found one at a higher level (section end)
            cont_renderer = get_nested(item_content, ['continuationItemRenderer'])
            if cont_renderer:
                token = get_nested(cont_renderer, ['continuationEndpoint', 'continuationCommand', 'token'])
                if token: continuation_token = token; print(f"API_PARSE: Found continuation token as item: {token[:20]}..."); continue

        renderer = get_nested(item_content, ['gridVideoRenderer']) or \
                   get_nested(item_content, ['videoRenderer']) or \
                   get_nested(item_content, ['pivotVideoRenderer']) or \
                   get_nested(item_content, ['richItemRenderer', 'content', 'videoRenderer']) or \
                   get_nested(item_content, ['richItemRenderer', 'content', 'reelItemRenderer']) # For Shorts

        if renderer:
            video_id = renderer.get('videoId')
            if not video_id and 'reelItemRenderer' in item_content.get('richItemRenderer', {}).get('content', {}): # Shorts have ID at different spot
                video_id = get_nested(item_content, ['richItemRenderer', 'content', 'reelItemRenderer', 'navigationEndpoint', 'watchEndpoint', 'videoId'])

            if not video_id: continue # Skip if no ID

            title_obj = renderer.get('title', {}) # Common for videoRenderer
            if not title_obj: title_obj = renderer.get('headline', {}) # Common for reelItemRenderer (Shorts)
            title = get_nested(title_obj, ['runs', 0, 'text']) or title_obj.get('simpleText')

            thumbnails = get_nested(renderer, ['thumbnail', 'thumbnails'])
            thumbnail_url = thumbnails[-1]['url'] if thumbnails else None

            long_byline = get_nested(renderer, ['longBylineText', 'runs', 0])
            short_byline = get_nested(renderer, ['shortBylineText', 'runs', 0]) # Often has channel for videos
            owner_text_runs = get_nested(renderer, ['ownerText', 'runs', 0]) # Common in search
            byline_runs = get_nested(renderer, ['byline', 'videoBylineRenderer', 'runs', 0]) # For Shorts

            channel_name, channel_url_suffix = None, None
            if long_byline and 'text' in long_byline:
                channel_name = long_byline.get('text')
                channel_url_suffix = get_nested(long_byline, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                     get_nested(long_byline, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])
            elif short_byline and 'text' in short_byline:
                channel_name = short_byline.get('text')
                channel_url_suffix = get_nested(short_byline, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                     get_nested(short_byline, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])
            elif owner_text_runs and 'text' in owner_text_runs:
                 channel_name = owner_text_runs.get('text')
                 channel_url_suffix = get_nested(owner_text_runs, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                      get_nested(owner_text_runs, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])
            elif byline_runs and 'text' in byline_runs: # For Shorts
                channel_name = byline_runs.get('text')
                channel_url_suffix = get_nested(byline_runs, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl'])


            duration_text_obj = renderer.get('lengthText', {})
            duration_text = duration_text_obj.get('simpleText') or "".join(r.get('text','') for r in duration_text_obj.get('runs',[]))
            if not duration_text: # For Shorts, duration is often in an overlay
                 duration_text = get_nested(renderer,['thumbnailOverlays',0,'thumbnailOverlayTimeStatusRenderer','text','simpleText'])

            published_time_text = get_nested(renderer, ['publishedTimeText', 'simpleText'])

            if video_id and title: # Thumbnail optional for now to ensure more items if some lack it
                video_data_list.append({
                    'video_id': video_id,
                    'youtube_url': f'https://www.youtube.com/watch?v={video_id}',
                    'title': title,
                    'thumbnail_url': thumbnail_url or "https://via.placeholder.com/320x180.png?text=No+Thumbnail", # Placeholder
                    'channel_name': channel_name or "N/A",
                    'channel_url': f'https://www.youtube.com{channel_url_suffix}' if channel_url_suffix and channel_url_suffix.startswith('/') else (channel_url_suffix or '#'),
                    'duration_text': duration_text or "N/A",
                    'published_time_text': published_time_text or "N/A"
                })
                item_count += 1
        elif get_nested(item_content, ['continuationItemRenderer']) and not continuation_token: # Check again if this item itself is a continuation
            token = get_nested(item_content, ['continuationItemRenderer', 'continuationEndpoint', 'continuationCommand', 'token'])
            if token: continuation_token = token; print(f"API_PARSE: Found continuation token as standalone item: {token[:20]}...")

    print(f"API_PARSE: Successfully parsed {len(video_data_list)} videos for context '{context}'. Continuation: {str(continuation_token)[:20] if continuation_token else 'None'}")
    return {'videos': video_data_list, 'continuation_token': continuation_token}

def get_homepage_videos_parsed(limit=30):
    print("API: Attempting to fetch and parse homepage videos...")
    cookies = load_cookies()
    html_content = _make_yt_request("https://www.youtube.com/", cookies)
    if html_content:
        return parse_video_data_from_script(html_content, context="home", limit=limit)
    print("API: Failed to get homepage HTML.")
    return {'videos': [], 'continuation_token': None}

def search_videos_parsed(query, limit=30):
    print(f"API: Searching for '{query}'...")
    cookies = load_cookies()
    html_content = _make_yt_request(f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}", cookies)
    if html_content:
        return parse_video_data_from_script(html_content, context="search", limit=limit)
    print(f"API: Failed to get search results HTML for '{query}'.")
    return {'videos': [], 'continuation_token': None}

def get_subscriptions_feed_parsed(limit=30):
    print("API: Attempting to fetch and parse actual subscriptions feed...")
    cookies = load_cookies()
    if not cookies or len(cookies) == 0:
        print("API: No cookies loaded, cannot fetch subscriptions feed.")
        return {'videos': [], 'continuation_token': None}
    html_content = _make_yt_request("https://www.youtube.com/feed/subscriptions", cookies)
    if html_content:
        return parse_video_data_from_script(html_content, context="subscriptions", limit=limit) # Corrected to use html_content
    print("API: Failed to get subscriptions page HTML.")
    return {'videos': [], 'continuation_token': None}

# --- Placeholder "Load More" functions ---
# These will eventually make API calls with continuation tokens

def get_more_home_videos_parsed(continuation_data=None):
    print(f"API_PLACEHOLDER: get_more_home_videos_parsed (token: {continuation_data}) - returning STATIC.")
    # Actual implementation would use continuation_data to fetch more.
    time.sleep(0.5) # Simulate network
    return {'videos': [
        {'video_id': f'moreHome{i}', 'youtube_url': '#', 'title': f'More Home Video {i}',
         'thumbnail_url': 'https://via.placeholder.com/320x180.png?text=More+Home',
         'channel_name': 'More Channel', 'channel_url': '#', 'duration_text': '00:00', 'published_time_text': 'Just now'}
        for i in range(1,4)
    ], 'continuation_token': f'fake_home_cont_{int(time.time())}' if continuation_data else None}


def get_more_subscriptions_videos_parsed(continuation_data=None):
    print(f"API_PLACEHOLDER: get_more_subscriptions_videos_parsed (token: {continuation_data}) - returning STATIC.")
    time.sleep(0.5)
    return {'videos': [
        {'video_id': f'moreSubs{i}', 'youtube_url': '#', 'title': f'More Subscription Video {i}',
         'thumbnail_url': 'https://via.placeholder.com/320x180.png?text=More+Subs',
         'channel_name': 'Subbed More', 'channel_url': '#', 'duration_text': '00:00', 'published_time_text': 'Just now'}
        for i in range(1,3)
    ], 'continuation_token': f'fake_subs_cont_{int(time.time())}' if continuation_data else None}


def get_channel_videos_parsed(channel_url, limit=30):
    print(f"API: Attempting to fetch DYNAMIC channel videos for '{channel_url}'...")
    cookies = load_cookies()

    # Normalize channel URL to point to the /videos tab
    if not channel_url.startswith("http"):
        # Assuming it's a handle like @channelname or ID UCxxxx
        if channel_url.startswith("@"):
            channel_url = f"https://www.youtube.com/{channel_url}"
        else: # Assume it's a UC... ID
            channel_url = f"https://www.youtube.com/channel/{channel_url}"

    # Ensure it points to the videos tab
    # Remove trailing slash if any, then append /videos
    channel_videos_url = channel_url.rstrip('/') + "/videos"

    print(f"API: Fetching channel videos from URL: {channel_videos_url}")
    html_content = _make_yt_request(channel_videos_url, cookies)

    if html_content:
        # For channel pages, ytInitialData often contains video lists under gridRenderer or richItemRenderer.
        # Using context="channel" if specific parsing paths are added for it later,
        # otherwise general parsing paths will be attempted by parse_video_data_from_script.
        # The general parser already looks for gridVideoRenderer and richItemRenderer.
        parsed_data = parse_video_data_from_script(html_content, context="channel", limit=limit)

        # Attempt to extract channel metadata if possible (e.g., for display on the page)
        # This is a simplified example; real metadata extraction is more complex.
        # if parsed_data.get('yt_initial_data'): # Assuming parse_video_data_from_script could return this
        #    channel_title = get_nested(parsed_data['yt_initial_data'], ['metadata', 'channelMetadataRenderer', 'title'])
        #    if channel_title:
        #        parsed_data['channel_title_from_page'] = channel_title
        #        print(f"API: Extracted channel title from page: {channel_title}")

        return parsed_data

    print(f"API: Failed to get channel page HTML for '{channel_videos_url}'.")
    return {'videos': [], 'continuation_token': None}


def get_more_channel_videos_parsed(channel_url, continuation_data=None):
    print(f"API_PLACEHOLDER: get_more_channel_videos_parsed for {channel_url} (token: {continuation_data}) - returning STATIC.")
    time.sleep(0.5)
    return {'videos': [
         {'video_id': f'moreChan{i}', 'youtube_url': '#', 'title': f'More Channel Video {i} for {channel_url.split("/")[-1]}',
          'thumbnail_url': 'https://via.placeholder.com/320x180.png?text=More+Chan',
          'channel_name': channel_url.split("/")[-1], 'channel_url': channel_url, 'duration_text': '00:00', 'published_time_text': 'Just now'}
         for i in range(1,3)
    ], 'continuation_token': f'fake_chan_cont_{int(time.time())}' if continuation_data else None}


def get_recommended_videos_for_player(current_video_id=None, limit=5): # limit for recommendations
    print(f"API: Getting recommended videos for {current_video_id} (currently static)...")
    # In a real scenario, this would fetch the watch page of current_video_id
    # and parse recommendations from its ytInitialData or related player data.
    # For now, return static, excluding current_video_id.
    static_reco_videos = [
        {'video_id': 'recoVid1', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid1', 'title': 'Recommended: Fun Adventure Time!', 'thumbnail_url': 'https://i.ytimg.com/vi/3yNSF7w2T9c/hqdefault.jpg', 'channel_name': 'Adventure Vids', 'channel_url': '#', 'duration_text': '11:11', 'published_time_text': '1 day ago'},
        {'video_id': 'recoVid2', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid2', 'title': 'You Might Also Like: Cooking Show Ep 5', 'thumbnail_url': 'https://i.ytimg.com/vi/6Af6b_wyiwI/hqdefault.jpg', 'channel_name': 'Kitchen Delights', 'channel_url': '#', 'duration_text': '22:22', 'published_time_text': '2 days ago'},
        {'video_id': 'recoVid3', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid3', 'title': 'Up Next (Static): Learning Python Basics', 'thumbnail_url': 'https://i.ytimg.com/vi/x7Xzbcq_xG4/hqdefault.jpg', 'channel_name': 'Code Master', 'channel_url': '#', 'duration_text': '33:33', 'published_time_text': '3 days ago'},
        {'video_id': 'recoVid4', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid4', 'title': 'Another Cool Reco Video', 'thumbnail_url': 'https://i.ytimg.com/vi/placeholder/hqdefault.jpg', 'channel_name': 'Cool Vids', 'channel_url': '#', 'duration_text': '04:44', 'published_time_text': '4 days ago'}
    ]
    filtered_recos = [v for v in static_reco_videos if v['video_id'] != current_video_id][:limit]
    return {'videos': filtered_recos, 'continuation_token': f'fake_reco_cont_{current_video_id}_{int(time.time())}' if len(filtered_recos) == limit else None} # Fake token if limit reached

def get_more_recommended_videos_parsed(current_video_id, continuation_data=None):
    print(f"API_PLACEHOLDER: get_more_recommended_videos_parsed for {current_video_id} (data: {continuation_data}) - returning STATIC.")
    time.sleep(0.5)
    return {'videos': [
        {'video_id': f'moreReco{i}_{current_video_id}', 'youtube_url': '#', 'title': f'More Reco {i} for {current_video_id}',
         'thumbnail_url': 'https://via.placeholder.com/320x180.png?text=More+Reco',
         'channel_name': 'RecoChan', 'channel_url': '#', 'duration_text': '00:00', 'published_time_text': 'Just now'}
        for i in range(1,3)
    ], 'continuation_token': f'fake_more_reco_cont_{int(time.time())}' if continuation_data else None}
