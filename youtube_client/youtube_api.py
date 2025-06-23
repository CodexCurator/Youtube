import json
import requests
from bs4 import BeautifulSoup
from http.cookiejar import MozillaCookieJar
import os
import time

from youtube_client import config

BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'DNT': '1',
    'Upgrade-Insecure-Requests': '1'
}
DEFAULT_THUMBNAIL_PLACEHOLDER = "https://via.placeholder.com/320x180.png?text=No+Thumbnail"

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

def _make_yt_request(url, cookies_jar, is_continuation=False, continuation_token=None, client_context=None):
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    if cookies_jar and len(cookies_jar) > 0:
        session.cookies.update(cookies_jar)
    else:
        print(f"DEBUG: No cookies provided or jar is empty for request to {url}.")

    if is_continuation:
        # This is a simplified payload. Real payloads can be much more complex
        # and might require specific client version, etc., from initial page load.
        # This is a common endpoint, but might vary.
        api_url = "https://www.youtube.com/youtubei/v1/browse?key=" # Key might be needed from initial page
        # A more common endpoint for continuations is /youtubei/v1/next or /youtubei/v1/browse
        # The key is often part of ytInitialData or a global JS variable like YT_API_KEY.
        # For now, this is a placeholder structure.
        # A more realistic payload would look something like:
        # payload = {
        #     "context": client_context or {"client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00"}}, # Example
        #     "continuation": continuation_token
        # }
        # response = session.post(api_url, json=payload, timeout=15)
        # For now, this part is highly speculative and will likely fail without the correct API key and context.
        # We'll make this a GET request for placeholder, though real continuations are POST.
        print(f"API_PLACEHOLDER: Making FAKE continuation request for token {continuation_token} to {url}")
        # This will not work for actual continuation, just a placeholder for structure.
        # For the purpose of this plan, we'll assume this part needs full research for actual continuation.
        return None # Placeholder: actual continuation logic is complex
    else: # Normal GET request
        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"API Error: Could not fetch page {url}: {e}")
            return None


def get_nested(data, keys, default=None):
    for key_part in keys:
        if isinstance(data, dict): data = data.get(key_part)
        elif isinstance(data, list):
            try: data = data[key_part] if isinstance(key_part, int) else default
            except IndexError: return default
        else: return default
        if data is None: return default
    return data

def extract_best_thumbnail(thumbnails_list):
    if not thumbnails_list or not isinstance(thumbnails_list, list):
        return DEFAULT_THUMBNAIL_PLACEHOLDER

    url_prefs = {"hq720": None, "sddefault": None, "hqdefault": None, "mqdefault": None, "default": None}
    last_good_url = DEFAULT_THUMBNAIL_PLACEHOLDER

    for thumb in thumbnails_list:
        url = thumb.get('url')
        if not url: continue
        last_good_url = url # Keep track of the last valid URL
        if 'hq720.jpg' in url: url_prefs['hq720'] = url
        elif 'sddefault.jpg' in url: url_prefs['sddefault'] = url
        elif 'hqdefault.jpg' in url: url_prefs['hqdefault'] = url
        elif 'mqdefault.jpg' in url: url_prefs['mqdefault'] = url
        elif 'default.jpg' in url: url_prefs['default'] = url

    if url_prefs['hq720']: return url_prefs['hq720']
    if url_prefs['sddefault']: return url_prefs['sddefault']
    if url_prefs['hqdefault']: return url_prefs['hqdefault']
    if url_prefs['mqdefault']: return url_prefs['mqdefault']
    if url_prefs['default']: return url_prefs['default']

    return last_good_url # Fallback to the highest resolution found if no standard keys match

def parse_video_data_from_json_response(json_data, context=None, limit=None):
    """
    Parses video data from a JSON response (typically from /youtubei/v1/browse or /youtubei/v1/next).
    This is a new function to handle continuation data specifically.
    """
    video_data_list = []
    new_continuation_token = None

    # The structure of continuation responses varies. Common patterns:
    # response -> onResponseReceivedActions/onResponseReceivedEndpoints -> ... -> continuationItems
    # response -> continuationContents.sectionListContinuation.contents ...
    # response -> continuationContents.richGridContinuation.contents ...

    actions = get_nested(json_data, ['onResponseReceivedActions']) or \
              get_nested(json_data, ['onResponseReceivedEndpoints'])

    continuation_items_list = []

    if actions and isinstance(actions, list):
        for action in actions:
            # Look for items to append
            items_to_append = get_nested(action, ['appendContinuationItemsAction', 'continuationItems'])
            if items_to_append and isinstance(items_to_append, list):
                continuation_items_list.extend(items_to_append)
                print(f"API_PARSE_CONTINUATION: Found {len(items_to_append)} items in appendContinuationItemsAction.")

            # Look for items in a grid continuation (common for homepage/channels)
            grid_continuation = get_nested(action, ['reloadContinuationItemsCommand', 'continuationItems']) or \
                                get_nested(action, ['appendContinuationItemsAction', 'continuationItems']) # Some use this too

            if grid_continuation and isinstance(grid_continuation, list):
                 # Sometimes gridContinuation itself is the list of items,
                 # other times it's nested further e.g. gridRenderer.items
                is_direct_list_of_videos = True
                for item_check in grid_continuation[:1]: # Check first item
                    if not (get_nested(item_check, ['gridVideoRenderer']) or \
                            get_nested(item_check, ['videoRenderer']) or \
                            get_nested(item_check, ['pivotVideoRenderer']) or \
                            get_nested(item_check, ['richItemRenderer', 'content', 'videoRenderer']) or \
                            get_nested(item_check, ['richItemRenderer', 'content', 'reelItemRenderer'])):
                        is_direct_list_of_videos = False
                        break
                if is_direct_list_of_videos:
                    continuation_items_list.extend(grid_continuation)
                    print(f"API_PARSE_CONTINUATION: Found {len(grid_continuation)} items directly in grid_continuation.")
                else: # Try to go deeper, e.g. for itemSectionRenderer or shelfRenderer
                    for sub_section in grid_continuation:
                        current_section_video_items = get_nested(sub_section, ['itemSectionRenderer', 'contents'])
                        if not current_section_video_items:
                            shelf_content_node = get_nested(sub_section, ['shelfRenderer', 'content'])
                            if shelf_content_node:
                                current_section_video_items = get_nested(shelf_content_node, ['gridRenderer', 'items'])
                        if current_section_video_items and isinstance(current_section_video_items, list):
                             continuation_items_list.extend(current_section_video_items)
                             print(f"API_PARSE_CONTINUATION: Found {len(current_section_video_items)} items in nested grid_continuation section.")


    # Fallback for slightly different continuation structures
    if not continuation_items_list:
        continuation_contents_node = get_nested(json_data, ['continuationContents'])
        if continuation_contents_node:
            possible_item_paths = [
                ['sectionListContinuation', 'contents'],
                ['richGridContinuation', 'items'],             # Often for home/channel
                ['liveChatContinuation', 'actions'],          # Not videos, but shows structure
                ['playlistVideoListContinuation', 'contents'], # For playlists
                # Add more specific continuation types as discovered
            ]
            for path in possible_item_paths:
                items = get_nested(continuation_contents_node, path)
                if items and isinstance(items, list):
                    continuation_items_list.extend(items) # Should only match one path ideally
                    print(f"API_PARSE_CONTINUATION: Found {len(items)} items via continuationContents.{path[0]}.")
                    break

    if not continuation_items_list:
        print("API_PARSE_CONTINUATION: No continuation items found in JSON response.")
        return {'videos': [], 'continuation_token': None}

    # Now parse these items (similar to parse_video_data_from_script's item loop)
    item_count = 0
    for item_content in continuation_items_list:
        if limit and item_count >= limit:
            print(f"API_PARSE_CONTINUATION: Reached item limit of {limit}. Parsed {item_count} videos.")
            break

        cont_renderer = get_nested(item_content, ['continuationItemRenderer'])
        if cont_renderer:
            token = get_nested(cont_renderer, ['continuationEndpoint', 'continuationCommand', 'token'])
            if token: new_continuation_token = token; print(f"API_PARSE_CONTINUATION: Found new continuation token: {token[:20]}...")
            continue # This item is just for the token

        renderer = get_nested(item_content, ['gridVideoRenderer']) or \
                   get_nested(item_content, ['videoRenderer']) or \
                   get_nested(item_content, ['pivotVideoRenderer']) or \
                   get_nested(item_content, ['richItemRenderer', 'content', 'videoRenderer']) or \
                   get_nested(item_content, ['richItemRenderer', 'content', 'reelItemRenderer'])

        if renderer:
            video_id = renderer.get('videoId')
            if not video_id and 'reelItemRenderer' in item_content.get('richItemRenderer', {}).get('content', {}):
                video_id = get_nested(item_content, ['richItemRenderer', 'content', 'reelItemRenderer', 'navigationEndpoint', 'watchEndpoint', 'videoId'])
            if not video_id: continue

            title_obj = renderer.get('title', {}) or renderer.get('headline', {})
            title = get_nested(title_obj, ['runs', 0, 'text']) or title_obj.get('simpleText')

            thumbnail_url = extract_best_thumbnail(get_nested(renderer, ['thumbnail', 'thumbnails']))

            channel_name, channel_url_suffix = None, None
            byline_sources = [
                get_nested(renderer, ['longBylineText', 'runs', 0]),
                get_nested(renderer, ['shortBylineText', 'runs', 0]),
                get_nested(renderer, ['ownerText', 'runs', 0]),
                get_nested(renderer, ['byline', 'videoBylineRenderer', 'runs', 0])
            ]
            for byline in byline_sources:
                if byline and 'text' in byline:
                    channel_name = byline.get('text')
                    channel_url_suffix = get_nested(byline, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                         get_nested(byline, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])
                    if channel_name: break

            duration_text_obj = renderer.get('lengthText', {})
            duration_text = duration_text_obj.get('simpleText') or "".join(r.get('text','') for r in duration_text_obj.get('runs',[]))
            if not duration_text:
                 overlay_time_status = get_nested(renderer,['thumbnailOverlays',0,'thumbnailOverlayTimeStatusRenderer','text'])
                 duration_text = overlay_time_status.get('simpleText') or "".join(r.get('text','') for r in overlay_time_status.get('runs',[]))

            published_time_text_obj = renderer.get('publishedTimeText', {})
            published_time_text = published_time_text_obj.get('simpleText') or \
                                  "".join(r.get('text','') for r in published_time_text_obj.get('runs',[]))

            if video_id and title:
                video_data_list.append({
                    'video_id': video_id,
                    'youtube_url': f'https://www.youtube.com/watch?v={video_id}',
                    'title': title,
                    'thumbnail_url': thumbnail_url,
                    'channel_name': channel_name or "N/A",
                    'channel_url': f'https://www.youtube.com{channel_url_suffix}' if channel_url_suffix and channel_url_suffix.startswith('/') else (channel_url_suffix or '#'),
                    'duration_text': duration_text or "N/A",
                    'published_time_text': published_time_text or "N/A"
                })
                item_count += 1

    print(f"API_PARSE_CONTINUATION: Successfully parsed {len(video_data_list)} videos from continuation. New token: {str(new_continuation_token)[:20] if new_continuation_token else 'None'}")
    return {'videos': video_data_list, 'continuation_token': new_continuation_token}


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
            except Exception as e:
                print(f"API_PARSE: Error parsing ytInitialData JSON: {e}")
                yt_initial_data = None

    if not yt_initial_data:
        print("API_PARSE: Failed to find or parse ytInitialData from any script tag.")
        return {'videos': [], 'continuation_token': None}

    video_data_list = []
    continuation_token = None
    raw_video_items = []

    # --- Path finding logic based on context ---
    # General paths (often for homepage / search / fallback)
    paths_to_try_general = [
        ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'richGridRenderer', 'contents'],
        ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents', 'sectionListRenderer', 'contents', 0, 'itemSectionRenderer', 'contents'],
        # For channels, the "Videos" tab content often has a grid
        ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 1, 'tabRenderer', 'content', 'richGridRenderer', 'contents'], # Assuming Videos tab is index 1
        ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content', 'sectionListRenderer', 'contents'] # Sometimes sections are directly under tab
    ]

    if context == "subscriptions":
        print("API_PARSE(Subs): Attempting subscriptions specific parsing...")
        tab_content = get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs', 0, 'tabRenderer', 'content'])
        if tab_content:
            sections = get_nested(tab_content, ['sectionListRenderer', 'contents'])
            if sections and isinstance(sections, list):
                print(f"API_PARSE(Subs): Found {len(sections)} sections in sectionListRenderer.")
                for section_idx, section_content in enumerate(sections):
                    items_in_section = get_nested(section_content, ['itemSectionRenderer', 'contents'])
                    if not items_in_section:
                        shelf_content_node = get_nested(section_content, ['shelfRenderer', 'content'])
                        if shelf_content_node:
                            items_in_section = get_nested(shelf_content_node, ['gridRenderer', 'items']) or \
                                               get_nested(shelf_content_node, ['expandedShelfContentsRenderer', 'items']) or \
                                               get_nested(shelf_content_node, ['verticalListRenderer', 'items']) # Less common
                    if not items_in_section:
                         rich_shelf_node = get_nested(section_content, ['richShelfRenderer', 'contents'])
                         if rich_shelf_node : items_in_section = rich_shelf_node

                    if items_in_section and isinstance(items_in_section, list):
                        print(f"API_PARSE(Subs): Section {section_idx} yielded {len(items_in_section)} raw items.")
                        raw_video_items.extend(items_in_section)

                    if not continuation_token: # Check for continuation at section level
                        token = get_nested(section_content, ['continuationItemRenderer', 'continuationEndpoint', 'continuationCommand', 'token']) or \
                                get_nested(section_content, ['shelfRenderer', 'continuation', 'reloadContinuationData', 'continuation']) or \
                                get_nested(section_content, ['richShelfRenderer', 'continuation', 'reloadContinuationData', 'continuation'])
                        if token: continuation_token = token; print(f"API_PARSE(Subs): Found continuation at section {section_idx} level.")

            if not raw_video_items: # Fallback for subs if sectionListRenderer not fruitful
                grid_items = get_nested(tab_content, ['richGridRenderer', 'contents'])
                if grid_items and isinstance(grid_items, list):
                    print(f"API_PARSE(Subs): Using richGridRenderer fallback for subs, {len(grid_items)} items.")
                    raw_video_items.extend(grid_items)
        if not raw_video_items: print("API_PARSE(Subs): No specific subscription items found via primary paths.")

    elif context == "channel":
        print("API_PARSE(Channel): Attempting channel specific parsing...")
        tabs = get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs'])
        videos_tab_content = None
        if tabs and isinstance(tabs, list):
            for tab_idx, tab_data in enumerate(tabs):
                tab_renderer = get_nested(tab_data, ['tabRenderer'])
                if not tab_renderer: continue
                # Channel "Videos" tab often has a specific browseId or title
                # This is heuristic; a more robust way might involve checking endpoint commands
                tab_title = get_nested(tab_renderer, ['title'])
                browse_id = get_nested(tab_renderer, ['endpoint', 'browseEndpoint', 'browseId'], '')
                if (isinstance(tab_title, str) and "videos" in tab_title.lower()) or \
                   (isinstance(browse_id, str) and browse_id.endswith("videos")) or \
                   tab_idx == 1: # Often the second tab after "Home"
                    videos_tab_content = get_nested(tab_renderer, ['content'])
                    print(f"API_PARSE(Channel): Found potential videos tab (index {tab_idx}, title '{tab_title}').")
                    break
            if not videos_tab_content and tabs: videos_tab_content = get_nested(tabs[0], ['tabRenderer', 'content']) # Fallback

        if videos_tab_content:
            # Common structure: sectionListRenderer -> itemSectionRenderer -> gridVideoRenderer
            sections = get_nested(videos_tab_content, ['sectionListRenderer', 'contents'])
            if sections and isinstance(sections, list) and sections:
                # Typically, channel videos are in the first itemSection of the first section
                items_in_section = get_nested(sections, [0, 'itemSectionRenderer', 'contents'])
                if items_in_section and isinstance(items_in_section, list):
                    raw_video_items.extend(items_in_section)
                    print(f"API_PARSE(Channel): Found {len(items_in_section)} items in itemSectionRenderer.")

            if not raw_video_items: # Fallback to richGridRenderer for channel videos
                grid_items = get_nested(videos_tab_content, ['richGridRenderer', 'contents'])
                if grid_items and isinstance(grid_items, list):
                    raw_video_items.extend(grid_items)
                    print(f"API_PARSE(Channel): Found {len(grid_items)} items in richGridRenderer.")
        if not raw_video_items: print("API_PARSE(Channel): No items found via specific channel paths.")

    # General path finding if context-specific parsing failed or no context / other contexts like 'home', 'search'
    if not raw_video_items:
        print(f"API_PARSE: No items from context '{context}'. Trying general paths...")
        for path_spec in paths_to_try_general:
            current_batch = get_nested(yt_initial_data, path_spec)
            if current_batch and isinstance(current_batch, list):
                print(f"API_PARSE: Found {len(current_batch)} items via general path: {path_spec}")
                raw_video_items.extend(current_batch)
                if raw_video_items: break

    if not raw_video_items:
        print(f"API_PARSE: No raw video items found for context '{context}' using any method.")
        return {'videos': [], 'continuation_token': None}

    # Process collected raw_video_items
    item_count = 0
    for item_content in raw_video_items:
        if limit and item_count >= limit and continuation_token:
             print(f"API_PARSE: Reached item limit ({limit}) and have continuation. Parsed {item_count}.")
             break
        if limit and item_count >= limit and not get_nested(item_content, ['continuationItemRenderer']):
             print(f"API_PARSE: Reached item limit ({limit}), no token yet, current item not continuation. Parsed {item_count}.")
             break

        cont_renderer_item = get_nested(item_content, ['continuationItemRenderer'])
        if cont_renderer_item:
            token = get_nested(cont_renderer_item, ['continuationEndpoint', 'continuationCommand', 'token'])
            if token: continuation_token = token; print(f"API_PARSE: Found/updated continuation token from item: {token[:20]}...")
            continue

        renderer = get_nested(item_content, ['gridVideoRenderer']) or \
                   get_nested(item_content, ['videoRenderer']) or \
                   get_nested(item_content, ['pivotVideoRenderer']) or \
                   get_nested(item_content, ['richItemRenderer', 'content', 'videoRenderer']) or \
                   get_nested(item_content, ['richItemRenderer', 'content', 'reelItemRenderer'])

        if renderer:
            video_id = renderer.get('videoId')
            if not video_id and get_nested(item_content, ['richItemRenderer', 'content', 'reelItemRenderer']):
                video_id = get_nested(item_content, ['richItemRenderer', 'content', 'reelItemRenderer', 'navigationEndpoint', 'watchEndpoint', 'videoId'])
            if not video_id: continue

            title_obj = renderer.get('title', {}) or renderer.get('headline', {})
            title = get_nested(title_obj, ['runs', 0, 'text']) or title_obj.get('simpleText')

            thumbnail_url = extract_best_thumbnail(get_nested(renderer, ['thumbnail', 'thumbnails']))

            channel_name, channel_url_suffix = None, None
            byline_sources = [
                get_nested(renderer, ['longBylineText', 'runs', 0]),
                get_nested(renderer, ['shortBylineText', 'runs', 0]),
                get_nested(renderer, ['ownerText', 'runs', 0]),
                get_nested(renderer, ['byline', 'videoBylineRenderer', 'runs', 0])
            ]
            for byline in byline_sources:
                if byline and 'text' in byline:
                    channel_name = byline.get('text')
                    channel_url_suffix = get_nested(byline, ['navigationEndpoint', 'browseEndpoint', 'canonicalBaseUrl']) or \
                                         get_nested(byline, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])
                    if channel_name: break

            duration_text_obj = renderer.get('lengthText', {})
            duration_text = duration_text_obj.get('simpleText') or "".join(r.get('text','') for r in duration_text_obj.get('runs',[]))
            if not duration_text:
                 overlay_time_status = get_nested(renderer,['thumbnailOverlays',0,'thumbnailOverlayTimeStatusRenderer','text'])
                 if overlay_time_status: # Ensure overlay_time_status is not None
                    duration_text = overlay_time_status.get('simpleText') or "".join(r.get('text','') for r in overlay_time_status.get('runs',[]))

            published_time_text_obj = renderer.get('publishedTimeText', {})
            published_time_text = published_time_text_obj.get('simpleText') or \
                                  "".join(r.get('text','') for r in published_time_text_obj.get('runs',[]))

            if video_id and title:
                video_data_list.append({
                    'video_id': video_id,
                    'youtube_url': f'https://www.youtube.com/watch?v={video_id}',
                    'title': title,
                    'thumbnail_url': thumbnail_url,
                    'channel_name': channel_name or "N/A",
                    'channel_url': f'https://www.youtube.com{channel_url_suffix}' if channel_url_suffix and channel_url_suffix.startswith('/') else (channel_url_suffix or '#'),
                    'duration_text': duration_text or "N/A",
                    'published_time_text': published_time_text or "N/A"
                })
                item_count += 1
        elif get_nested(item_content, ['continuationItemRenderer']) and not continuation_token:
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
        return parse_video_data_from_script(html_content, context="subscriptions", limit=limit)
    print("API: Failed to get subscriptions page HTML.")
    return {'videos': [], 'continuation_token': None}

def get_channel_videos_parsed(channel_url, limit=30):
    print(f"API: Attempting to fetch DYNAMIC channel videos for '{channel_url}'...")
    cookies = load_cookies()

    if not channel_url.startswith("http"):
        if channel_url.startswith("@"): channel_url = f"https://www.youtube.com/{channel_url}"
        else: channel_url = f"https://www.youtube.com/channel/{channel_url}"

    channel_videos_url = channel_url.rstrip('/') + "/videos"

    print(f"API: Fetching channel videos from URL: {channel_videos_url}")
    html_content = _make_yt_request(channel_videos_url, cookies)

    if html_content:
        return parse_video_data_from_script(html_content, context="channel", limit=limit)

    print(f"API: Failed to get channel page HTML for '{channel_videos_url}'.")
    return {'videos': [], 'continuation_token': None}

# --- Dynamic "Load More" functions ---

YOUTUBE_API_KEY = None # This would be needed if using official API, not for internal
YOUTUBE_CLIENT_CONTEXT = { # Example client context, might need to be extracted from initial page
    "client": {
        "hl": "en",
        "gl": "US",
        "clientName": "WEB",
        "clientVersion": "2.20240101.00.00" # This needs to be a recent valid version
    }
}

def _fetch_youtube_continuation_json(continuation_token, cookies):
    """Fetches more items using a continuation token via YouTube's internal API."""
    if not YOUTUBE_API_KEY: # Attempt to find it in ytInitialData if not hardcoded
        # This is a simplification; a robust solution would extract this from the initial page load's JS variables.
        # For now, if not set, this will likely fail.
        print("API_CONTINUATION: YOUTUBE_API_KEY not available. Continuation request will likely fail.")
        # A common public key, but might not work for all contexts or be rate-limited.
        # It's better to extract this from the page source.
        temp_api_key = "AIzaSyA_...YOUR_EXTRACTED_OR_A_KNOWN_PUBLIC_WEB_API_KEY" # Redacted for safety
        # return None # Or raise error

    # The endpoint can vary, /youtubei/v1/browse or /youtubei/v1/next are common
    api_url = f"https://www.youtube.com/youtubei/v1/browse?key={YOUTUBE_API_KEY or temp_api_key}"

    payload = {
        "context": YOUTUBE_CLIENT_CONTEXT, # This context might need more fields from initial page
        "continuation": continuation_token
    }

    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    session.headers.update({ # Additional headers often seen in these POST requests
        'Content-Type': 'application/json',
        'X-YouTube-Client-Name': '1', # Corresponds to WEB client
        'X-YouTube-Client-Version': YOUTUBE_CLIENT_CONTEXT["client"]["clientVersion"],
        # 'Authorization': ... (if needed, but cookies usually handle this)
    })
    if cookies and len(cookies) > 0:
        session.cookies.update(cookies)

    try:
        print(f"API_CONTINUATION: POSTing to {api_url} with token {continuation_token[:20]}...")
        response = session.post(api_url, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"API_CONTINUATION Error: Request failed for token {continuation_token[:20]}: {e}")
        if response is not None: print(f"API_CONTINUATION Error Response: {response.text[:500]}")
        return None
    except json.JSONDecodeError as e:
        print(f"API_CONTINUATION Error: Failed to decode JSON response for token {continuation_token[:20]}: {e}")
        print(f"API_CONTINUATION Raw Response: {response.text[:500]}")
        return None


def get_more_home_videos_parsed(continuation_token):
    print(f"API: Getting MORE homepage videos (token: {continuation_token[:20] if continuation_token else 'None'})...")
    if not continuation_token: return {'videos': [], 'continuation_token': None}
    cookies = load_cookies()
    json_response = _fetch_youtube_continuation_json(continuation_token, cookies)
    if json_response:
        return _parse_continuation_json_response(json_response, context="home")
    return {'videos': [], 'continuation_token': None}

def get_more_subscriptions_videos_parsed(continuation_token):
    print(f"API: Getting MORE subscription videos (token: {continuation_token[:20] if continuation_token else 'None'})...")
    if not continuation_token: return {'videos': [], 'continuation_token': None}
    cookies = load_cookies()
    json_response = _fetch_youtube_continuation_json(continuation_token, cookies)
    if json_response:
        return _parse_continuation_json_response(json_response, context="subscriptions")
    return {'videos': [], 'continuation_token': None}

def get_more_channel_videos_parsed(channel_url, continuation_token): # channel_url might be needed for context in API call
    print(f"API: Getting MORE channel videos for {channel_url} (token: {continuation_token[:20] if continuation_token else 'None'})...")
    if not continuation_token: return {'videos': [], 'continuation_token': None}
    cookies = load_cookies()
    # The client context might need to include channel specific browseId if available from initial load
    json_response = _fetch_youtube_continuation_json(continuation_token, cookies)
    if json_response:
        return _parse_continuation_json_response(json_response, context="channel")
    return {'videos': [], 'continuation_token': None}

def get_recommended_videos_for_player(current_video_id=None, limit=15): # Increased limit for recommendations
    print(f"API: Getting recommended videos for {current_video_id} (currently static)...")
    # This would ideally fetch the watch page of current_video_id, then parse recommendations.
    # For now, it's static.
    static_reco_videos = [
        {'video_id': 'recoVid1', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid1', 'title': 'Recommended: Fun Adventure Time!', 'thumbnail_url': 'https://i.ytimg.com/vi/3yNSF7w2T9c/hqdefault.jpg', 'channel_name': 'Adventure Vids', 'channel_url': '#', 'duration_text': '11:11', 'published_time_text': '1 day ago'},
        {'video_id': 'recoVid2', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid2', 'title': 'You Might Also Like: Cooking Show Ep 5', 'thumbnail_url': 'https://i.ytimg.com/vi/6Af6b_wyiwI/hqdefault.jpg', 'channel_name': 'Kitchen Delights', 'channel_url': '#', 'duration_text': '22:22', 'published_time_text': '2 days ago'},
        {'video_id': 'recoVid3', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid3', 'title': 'Up Next (Static): Learning Python Basics', 'thumbnail_url': 'https://i.ytimg.com/vi/x7Xzbcq_xG4/hqdefault.jpg', 'channel_name': 'Code Master', 'channel_url': '#', 'duration_text': '33:33', 'published_time_text': '3 days ago'},
        {'video_id': 'recoVid4', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid4', 'title': 'Another Cool Reco Video', 'thumbnail_url': 'https://i.ytimg.com/vi/placeholder/hqdefault.jpg', 'channel_name': 'Cool Vids', 'channel_url': '#', 'duration_text': '04:44', 'published_time_text': '4 days ago'}
    ]
    filtered_recos = [v for v in static_reco_videos if v['video_id'] != current_video_id][:limit]
    # Simulate a continuation token if more static data could be "loaded"
    has_more_static = len(static_reco_videos) > limit and len(filtered_recos) == limit
    return {'videos': filtered_recos, 'continuation_token': f'fake_reco_cont_{current_video_id}_{int(time.time())}' if has_more_static else None}

def get_more_recommended_videos_parsed(current_video_id, continuation_data=None):
    print(f"API_PLACEHOLDER: get_more_recommended_videos_parsed for {current_video_id} (data: {continuation_data}) - returning STATIC.")
    time.sleep(0.5)
    # Simulate that loading more gives 2 more videos, then no more token
    if "second_page" in (continuation_data or ""): # Simple check for a second call
        return {'videos': [], 'continuation_token': None}

    return {'videos': [
        {'video_id': f'moreReco{i}_{current_video_id}', 'youtube_url': '#', 'title': f'More Reco {i} for {current_video_id}',
         'thumbnail_url': DEFAULT_THUMBNAIL_PLACEHOLDER,
         'channel_name': 'RecoChan', 'channel_url': '#', 'duration_text': '00:0'+str(i), 'published_time_text': 'Just now'}
        for i in range(5,7) # e.g. items 5 and 6
    ], 'continuation_token': f'fake_reco_cont_{current_video_id}_{int(time.time())}_second_page'}
