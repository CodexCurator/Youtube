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
YT_API_KEY_PLACEHOLDER = "YOUR_VALID_WEB_API_KEY_HERE"  # User must replace this
YT_CLIENT_CONTEXT_PLACEHOLDER = {
    "client": {
        "hl": "en",
        "gl": "US",
        "clientName": "WEB",
        "clientVersion": "2.20240620.00.00",
    }
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
        print(f"DEBUG: No cookies provided or jar is empty for GET request to {url}.")
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"API Error: Could not fetch page {url}: {e}")
        return None

def _fetch_youtube_continuation_json(continuation_token, cookies, client_context=None, endpoint_suffix="browse"):
    api_key = YT_API_KEY_PLACEHOLDER
    if "YOUR_VALID_WEB_API_KEY" in api_key:
        print("API_CONTINUATION WARNING: Placeholder API key is being used. Real continuation requests will fail.")
        return None

    api_url = f"https://www.youtube.com/youtubei/v1/{endpoint_suffix}?key={api_key}&prettyPrint=false"

    final_client_context = client_context or YT_CLIENT_CONTEXT_PLACEHOLDER
    # Ensure essential client fields are present if overriding
    if 'client' not in final_client_context:
        final_client_context['client'] = YT_CLIENT_CONTEXT_PLACEHOLDER['client']
    elif 'clientName' not in final_client_context['client']:
        final_client_context['client']['clientName'] = YT_CLIENT_CONTEXT_PLACEHOLDER['client']['clientName']
    if 'clientVersion' not in final_client_context['client']:
        final_client_context['client']['clientVersion'] = YT_CLIENT_CONTEXT_PLACEHOLDER['client']['clientVersion']


    payload = {
        "context": final_client_context,
        "continuation": continuation_token
    }

    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    session.headers.update({
        'Content-Type': 'application/json',
        'X-YouTube-Client-Name': str(get_nested(payload, ['context','client','clientName'], default='1')),
        'X-YouTube-Client-Version': get_nested(payload,['context','client','clientVersion'], default='2.20240620.00.00'),
        'Origin': 'https://www.youtube.com',
        'Referer': 'https://www.youtube.com/',
    })
    if cookies and len(cookies) > 0:
        session.cookies.update(cookies)

    try:
        print(f"API_CONTINUATION: POSTing to {api_url} with token {str(continuation_token)[:30]}...")
        response = session.post(api_url, json=payload, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"API_CONTINUATION Error: Request failed for token {str(continuation_token)[:30]}: {e}")
        if hasattr(response, 'text'): print(f"API_CONTINUATION Error Response Content: {response.text[:500]}")
        return None
    except json.JSONDecodeError as e_json:
        print(f"API_CONTINUATION Error: Failed to decode JSON for token {str(continuation_token)[:30]}: {e_json}")
        if hasattr(response, 'text'): print(f"API_CONTINUATION Raw Response: {response.text[:500]}")
        return None
    except Exception as e_gen:
        print(f"API_CONTINUATION Error: Unexpected error for token {str(continuation_token)[:30]}: {e_gen}")
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
    highest_res_url = None
    highest_width = 0

    for thumb in thumbnails_list:
        url = thumb.get('url')
        width = thumb.get('width', 0)
        if not url: continue

        # Ensure URL starts with http, some relative URLs (//i.ytimg.com...) might appear
        if url.startswith("//"): url = "https:" + url

        if width > highest_width:
            highest_width = width
            highest_res_url = url

        if 'hq720.jpg' in url: url_prefs['hq720'] = url
        elif 'sddefault.jpg' in url: url_prefs['sddefault'] = url
        elif 'hqdefault.jpg' in url: url_prefs['hqdefault'] = url
        elif 'mqdefault.jpg' in url: url_prefs['mqdefault'] = url
        elif 'default.jpg' in url: url_prefs['default'] = url

    for quality in ['hq720', 'sddefault', 'hqdefault', 'mqdefault']:
        if url_prefs[quality]: return url_prefs[quality]

    if highest_res_url: return highest_res_url # Fallback to numerically highest if standard keys not found
    if url_prefs['default']: return url_prefs['default'] # Smallest default

    return DEFAULT_THUMBNAIL_PLACEHOLDER


def _parse_video_renderer_item(renderer):
    if not renderer: return None
    video_id = renderer.get('videoId')
    if not video_id and renderer.get('navigationEndpoint'):
        video_id = get_nested(renderer, ['navigationEndpoint', 'watchEndpoint', 'videoId']) or \
                   get_nested(renderer, ['navigationEndpoint', 'commandMetadata', 'webCommandMetadata', 'url'])
        if isinstance(video_id, str) and "/watch?v=" in video_id:
            video_id = video_id.split("/watch?v=")[1].split("&")[0]
        elif not (isinstance(video_id, str) and len(video_id) == 11): # Basic check for valid ID format
            video_id = None # Invalidate if not a proper ID like string

    if not video_id: return None

    title_obj = renderer.get('title', {}) or renderer.get('headline', {})
    title = get_nested(title_obj, ['runs', 0, 'text']) or title_obj.get('simpleText')
    if not title: title = "Unknown Title" # Ensure title is never None

    thumbnail_url = extract_best_thumbnail(get_nested(renderer, ['thumbnail', 'thumbnails']))
    if video_id and (thumbnail_url is None or DEFAULT_THUMBNAIL_PLACEHOLDER in thumbnail_url) :
        raw_thumbnails = get_nested(renderer, ['thumbnail', 'thumbnails'])
        print(f"DEBUG_THUMBNAIL: VideoID {video_id} got placeholder. Raw thumbnails: {str(raw_thumbnails)[:200]}") # Log first 200 chars

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
            nav_endpoint = byline.get('navigationEndpoint')
            if nav_endpoint:
                channel_url_suffix = get_nested(nav_endpoint, ['browseEndpoint', 'canonicalBaseUrl']) or \
                                     get_nested(nav_endpoint, ['commandMetadata', 'webCommandMetadata', 'url'])
            if channel_name: break

    duration_text_obj = renderer.get('lengthText', {})
    duration_text = duration_text_obj.get('simpleText') or "".join(r.get('text','') for r in duration_text_obj.get('runs', default=[]))
    if not duration_text:
         overlay_time_status = get_nested(renderer,['thumbnailOverlays',0,'thumbnailOverlayTimeStatusRenderer','text'])
         if overlay_time_status:
            duration_text = overlay_time_status.get('simpleText') or "".join(r.get('text','') for r in overlay_time_status.get('runs', default=[]))

    published_time_text_obj = renderer.get('publishedTimeText', {})
    published_time_text = published_time_text_obj.get('simpleText') or \
                          "".join(r.get('text','') for r in published_time_text_obj.get('runs', default=[]))

    return {
        'video_id': video_id,
        'youtube_url': f'https://www.youtube.com/watch?v={video_id}',
        'title': title,
        'thumbnail_url': thumbnail_url,
        'channel_name': channel_name or "N/A",
        'channel_url': f'https://www.youtube.com{channel_url_suffix}' if channel_url_suffix and channel_url_suffix.startswith('/') else (channel_url_suffix or '#'),
        'duration_text': duration_text or "N/A",
        'published_time_text': published_time_text or "N/A"
    }

def _parse_continuation_items(continuation_items_list, context=None, limit=None):
    video_data_list = []
    new_continuation_token = None
    item_count = 0

    if not continuation_items_list or not isinstance(continuation_items_list, list):
        return {'videos': [], 'continuation_token': None}

    for item_content in continuation_items_list:
        if limit and item_count >= limit and new_continuation_token: break
        if limit and item_count >= limit and not get_nested(item_content, ['continuationItemRenderer']): break

        cont_renderer = get_nested(item_content, ['continuationItemRenderer'])
        if cont_renderer:
            token = get_nested(cont_renderer, ['continuationEndpoint', 'continuationCommand', 'token']) or \
                    get_nested(cont_renderer, ['button', 'buttonRenderer', 'command', 'continuationCommand', 'token'])
            if token: new_continuation_token = token; print(f"API_PARSE_CONTINUATION({context}): Found new continuation token: {token[:20]}...")
            continue

        renderer_options = [
            get_nested(item_content, ['richItemRenderer', 'content', 'videoRenderer']),
            get_nested(item_content, ['gridVideoRenderer']),
            get_nested(item_content, ['videoRenderer']),
            get_nested(item_content, ['pivotVideoRenderer']),
            get_nested(item_content, ['compactVideoRenderer']),
            get_nested(item_content, ['richItemRenderer', 'content', 'reelItemRenderer'])
        ]
        renderer = next((r for r in renderer_options if r is not None), None)

        video_dict = _parse_video_renderer_item(renderer)
        if video_dict:
            video_data_list.append(video_dict)
            item_count += 1

    print(f"API_PARSE_CONTINUATION({context}): Parsed {len(video_data_list)} videos from continuation. Next token: {str(new_continuation_token)[:20] if new_continuation_token else 'None'}")
    return {'videos': video_data_list, 'continuation_token': new_continuation_token}

def _parse_continuation_json_response(json_data, context=None, limit=None):
    if not json_data: return {'videos': [], 'continuation_token': None}

    continuation_items_list = []
    actions = get_nested(json_data, ['onResponseReceivedActions']) or \
              get_nested(json_data, ['onResponseReceivedCommands'])

    if actions and isinstance(actions, list):
        for action_idx, action in enumerate(actions):
            items = get_nested(action, ['appendContinuationItemsAction', 'continuationItems']) or \
                    get_nested(action, ['reloadContinuationItemsCommand', 'continuationItems'])
            if items and isinstance(items, list):
                print(f"API_PARSE_CONTINUATION({context}): Found {len(items)} items in action {action_idx}.")
                continuation_items_list.extend(items)
                break

    if not continuation_items_list:
        continuation_contents_node = get_nested(json_data, ['continuationContents'])
        if continuation_contents_node:
            possible_wrappers = [
                'sectionListContinuation', 'richGridContinuation', 'playlistVideoListContinuation',
                'itemSectionContinuation', 'liveChatContinuation' # liveChat is not videos but for structure
            ]
            for wrapper_key in possible_wrappers:
                wrapper_node = get_nested(continuation_contents_node, [wrapper_key])
                if wrapper_node:
                    items = get_nested(wrapper_node, ['items']) or get_nested(wrapper_node, ['contents']) or get_nested(wrapper_node, ['actions'])
                    if items and isinstance(items, list):
                        print(f"API_PARSE_CONTINUATION({context}): Found {len(items)} items via continuationContents.{wrapper_key}.")
                        continuation_items_list.extend(items)
                        # Token is often inside the wrapper_node or at the end of items list
                        token_in_wrapper = get_nested(wrapper_node, ['continuations', 0, 'nextContinuationData', 'continuation']) or \
                                           get_nested(wrapper_node, ['continuations', 0, 'reloadContinuationData', 'continuation'])
                        if token_in_wrapper: # Prioritize token from wrapper if available
                            # This will be picked up by _parse_continuation_items if last item is token renderer
                            pass # Let _parse_continuation_items handle it by appending the token item
                        break

    return _parse_continuation_items(continuation_items_list, context=context, limit=limit)


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

    tab_content = None
    # Try to find main content area based on typical structures for different contexts
    if context in ["home", "subscriptions", "channel"]:
        tabs = get_nested(yt_initial_data, ['contents', 'twoColumnBrowseResultsRenderer', 'tabs'])
        if tabs and isinstance(tabs, list) and tabs:
            tab_index = 0 # Default for home/subscriptions
            if context == "channel": # Try to find "Videos" tab for channels
                for i, tab_data in enumerate(tabs):
                    tab_renderer = get_nested(tab_data, ['tabRenderer'])
                    if tab_renderer:
                        tab_title = get_nested(tab_renderer, ['title'], '').lower()
                        tab_url_suffix = (get_nested(tab_renderer, ['endpoint', 'commandMetadata', 'webCommandMetadata', 'url']) or "").lower()
                        if "videos" == tab_title or tab_url_suffix.endswith("/videos"):
                            tab_index = i; print(f"API_PARSE({context}): Found specific 'videos' tab at index {i}.")
                            break
                else: # If loop finished without break, use heuristic for channel (often index 1 or 0)
                    if len(tabs) > 1 and "home" not in get_nested(tabs[0],['tabRenderer','title'],'').lower(): tab_index = 0
                    elif len(tabs) > 1 : tab_index = 1
                    print(f"API_PARSE({context}): Using heuristic tab index {tab_index} for videos tab.")
            tab_content = get_nested(tabs, [tab_index, 'tabRenderer', 'content'])
    elif context == "search":
        tab_content = get_nested(yt_initial_data, ['contents', 'twoColumnSearchResultsRenderer', 'primaryContents'])

    if tab_content:
        # Common patterns for item lists within tab_content
        primary_item_container_node = None
        if get_nested(tab_content, ['sectionListRenderer', 'contents']):
            primary_item_container_node = get_nested(tab_content, ['sectionListRenderer', 'contents'])
            if context == "home": print(f"API_PARSE({context}): Found sectionListRenderer for items.")
        elif get_nested(tab_content, ['richGridRenderer', 'contents']):
            primary_item_container_node = get_nested(tab_content, ['richGridRenderer', 'contents'])
            if context == "home": print(f"API_PARSE({context}): Found richGridRenderer for items.")

        if primary_item_container_node and isinstance(primary_item_container_node, list):
            print(f"API_PARSE({context}): Found {len(primary_item_container_node)} primary content sections/items.")
            for i, section_or_item_content in enumerate(primary_item_container_node):
                if context == "home": print(f"API_PARSE({context}): Processing section/item {i} from primary container.")

                current_section_items = None
                # Path 1: Item Section Renderer
                item_section_contents = get_nested(section_or_item_content, ['itemSectionRenderer', 'contents'])
                if item_section_contents:
                    if context == "home": print(f"API_PARSE({context}): Section {i} is itemSectionRenderer with {len(item_section_contents)} items.")
                    current_section_items = item_section_contents

                # Path 2: Shelf Renderer (grid, expanded, vertical)
                if not current_section_items:
                    shelf_content_node = get_nested(section_or_item_content, ['shelfRenderer', 'content'])
                    if shelf_content_node:
                        if context == "home": print(f"API_PARSE({context}): Section {i} is shelfRenderer.")
                        current_section_items = get_nested(shelf_content_node, ['gridRenderer', 'items']) or \
                                              get_nested(shelf_content_node, ['expandedShelfContentsRenderer', 'items']) or \
                                              get_nested(shelf_content_node, ['verticalListRenderer', 'items'])
                        if context == "home" and current_section_items: print(f"API_PARSE({context}): Shelf has {len(current_section_items)} items.")

                # Path 3: Rich Shelf Renderer
                if not current_section_items:
                     rich_shelf_contents = get_nested(section_or_item_content, ['richShelfRenderer', 'contents'])
                     if rich_shelf_contents:
                        if context == "home": print(f"API_PARSE({context}): Section {i} is richShelfRenderer with {len(rich_shelf_contents)} items.")
                        current_section_items = rich_shelf_contents

                # Path 4: Direct item (e.g. videoRenderer, gridVideoRenderer directly in richGridRenderer.contents)
                if not current_section_items and isinstance(section_or_item_content, dict):
                    # This check is important for richGridRenderer where items are direct children
                    if get_nested(section_or_item_content, ['richItemRenderer', 'content']) or \
                       section_or_item_content.get('videoRenderer') or \
                       section_or_item_content.get('gridVideoRenderer') or \
                       section_or_item_content.get('reelItemRenderer'): # Added reelItemRenderer
                        if context == "home": print(f"API_PARSE({context}): Section {i} is a direct renderable item itself.")
                        current_section_items = [section_or_item_content] # Treat as a list of one

                if current_section_items and isinstance(current_section_items, list):
                    if context == "home": print(f"API_PARSE({context}): Extending raw_video_items with {len(current_section_items)} items from section {i}.")
                    raw_video_items.extend(current_section_items)
                elif context == "home" and not get_nested(section_or_item_content, ['continuationItemRenderer']): # Don't log if it's just a continuation token
                    print(f"API_PARSE({context}): No parsable video items found in section/item {i} structure: {list(section_or_item_content.keys()) if isinstance(section_or_item_content, dict) else type(section_or_item_content)}")


                # Look for continuation token at the end of this section or its items
                if not continuation_token:
                    # Check if the current section_or_item_content itself is a continuation item
                    if get_nested(section_or_item_content, ['continuationItemRenderer']):
                        token = get_nested(section_or_item_content, ['continuationItemRenderer', 'continuationEndpoint', 'continuationCommand', 'token'])
                        if token: continuation_token = token; print(f"API_PARSE({context}): Found continuation at section level {i}.")
                    # Check if the last item within current_section_items (if any) is a continuation item
                    elif current_section_items and get_nested(current_section_items[-1], ['continuationItemRenderer']):
                        token = get_nested(current_section_items[-1], ['continuationItemRenderer', 'continuationEndpoint', 'continuationCommand', 'token'])
                        if token: continuation_token = token; print(f"API_PARSE({context}): Found continuation at end of item list in section {i}.")

        else: # No sectionList or richGrid, maybe items are directly under tab_content (rare)
            if isinstance(tab_content, list): raw_video_items.extend(tab_content)
            if context == "home": print(f"API_PARSE({context}): No primary item container (sectionList/richGrid). Raw tab_content has {len(tab_content) if isinstance(tab_content, list) else 0} items.")

    if not raw_video_items:
        if context == "home":
            # If homepage parsing fails, let's dump a bit of the ytInitialData structure to help diagnose
            if yt_initial_data:
                print(f"API_PARSE({context}): ytInitialData keys: {list(yt_initial_data.keys())}")
                if 'contents' in yt_initial_data:
                    print(f"API_PARSE({context}): ytInitialData.contents keys: {list(yt_initial_data['contents'].keys())}")
                    if 'twoColumnBrowseResultsRenderer' in yt_initial_data['contents']:
                        print(f"API_PARSE({context}): ytInitialData.contents.twoColumnBrowseResultsRenderer keys: {list(yt_initial_data['contents']['twoColumnBrowseResultsRenderer'].keys())}")
                        if 'tabs' in yt_initial_data['contents']['twoColumnBrowseResultsRenderer']:
                             print(f"API_PARSE({context}): Number of tabs: {len(yt_initial_data['contents']['twoColumnBrowseResultsRenderer']['tabs'])}")
                             if yt_initial_data['contents']['twoColumnBrowseResultsRenderer']['tabs']:
                                first_tab_keys = list(yt_initial_data['contents']['twoColumnBrowseResultsRenderer']['tabs'][0].keys())
                                print(f"API_PARSE({context}): First tab keys: {first_tab_keys}")
                                if 'tabRenderer' in yt_initial_data['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]:
                                    tab_renderer_keys = list(yt_initial_data['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]['tabRenderer'].keys())
                                    print(f"API_PARSE({context}): First tabRenderer keys: {tab_renderer_keys}")
                                    if 'content' in yt_initial_data['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]['tabRenderer']:
                                        content_keys = list(yt_initial_data['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]['tabRenderer']['content'].keys())
                                        print(f"API_PARSE({context}): First tabRenderer.content keys: {content_keys}")


        print(f"API_PARSE: No raw video items found for context '{context}' after specific pathing.")
        return {'videos': [], 'continuation_token': None}

    # Process collected raw_video_items
    item_count = 0
    for item_data_content in raw_video_items: # Renamed item_content to item_data_content
        if limit and item_count >= limit and continuation_token:
             print(f"API_PARSE: Reached item limit ({limit}) and have continuation. Parsed {item_count}.")
             break
        if limit and item_count >= limit and not get_nested(item_data_content, ['continuationItemRenderer']):
             print(f"API_PARSE: Reached item limit ({limit}), no token yet, current item not continuation. Parsed {item_count}.")
             break

        cont_renderer_item = get_nested(item_data_content, ['continuationItemRenderer'])
        if cont_renderer_item:
            token = get_nested(cont_renderer_item, ['continuationEndpoint', 'continuationCommand', 'token'])
            if token: continuation_token = token; print(f"API_PARSE: Found/updated continuation token from item: {token[:20]}...")
            continue

        renderer_options = [
            get_nested(item_data_content, ['gridVideoRenderer']),
            get_nested(item_data_content, ['videoRenderer']),
            get_nested(item_data_content, ['pivotVideoRenderer']),
            get_nested(item_data_content, ['richItemRenderer', 'content', 'videoRenderer']),
            get_nested(item_data_content, ['richItemRenderer', 'content', 'reelItemRenderer']),
            get_nested(item_data_content, ['compactVideoRenderer'])
        ]
        renderer = next((r for r in renderer_options if r is not None), None)

        if renderer:
            video_dict = _parse_video_renderer_item(renderer)
            if video_dict:
                video_data_list.append(video_dict)
                item_count += 1

    print(f"API_PARSE: Successfully parsed {len(video_data_list)} videos for context '{context}'. Continuation: {str(continuation_token)[:20] if continuation_token else 'None'}")
    return {'videos': video_data_list, 'continuation_token': continuation_token}

# --- Main Data Fetching Functions ---
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

    # Normalize channel_url to a full base URL (e.g., https://www.youtube.com/@handle or https://www.youtube.com/channel/ID)
    if not channel_url.startswith("http"):
        if channel_url.startswith("@"):
            # Input: @handle -> Output: https://www.youtube.com/@handle
            channel_url = f"https://www.youtube.com/{channel_url}"
        elif channel_url.startswith("channel/"):
            # Input: channel/ID -> Output: https://www.youtube.com/channel/ID
            channel_url = f"https://www.youtube.com/{channel_url}"
        elif channel_url.startswith("user/"):
            # Input: user/name -> Output: https://www.youtube.com/user/name
            channel_url = f"https://www.youtube.com/{channel_url}"
        elif channel_url.startswith("UC") and len(channel_url) > 20 and not "/" in channel_url: # Heuristic for bare Channel ID
            # Input: UCxxxx -> Output: https://www.youtube.com/channel/UCxxxx
            channel_url = f"https://www.youtube.com/channel/{channel_url}"
        else:
            # Input: barehandle (custom URL or new style short handle without @) -> Output: https://www.youtube.com/@barehandle
            # This assumes if no other prefix, it's a handle-like name.
            channel_url = f"https://www.youtube.com/@{channel_url}"

    # Append /videos to the normalized base channel URL
    # Ensure no double slashes if channel_url might already end with one (though above logic shouldn't produce that)
    base_channel_url = channel_url.rstrip('/')
    channel_videos_url = f"{base_channel_url}/videos"

    print(f"API: Fetching DYNAMIC channel videos from normalized URL: {channel_videos_url}")
    html_content = _make_yt_request(channel_videos_url, cookies)
    if html_content:
        return parse_video_data_from_script(html_content, context="channel", limit=limit)
    print(f"API: Failed to get channel page HTML for '{channel_videos_url}'.")
    return {'videos': [], 'continuation_token': None}

def get_recommended_videos_for_player(current_video_id=None, limit=15):
    print(f"API: Getting recommended videos for {current_video_id}...")
    cookies = load_cookies()
    watch_url = f"https://www.youtube.com/watch?v={current_video_id}"
    html_content = _make_yt_request(watch_url, cookies)

    if html_content:
        soup = BeautifulSoup(html_content, 'html.parser')
        scripts = soup.find_all('script')
        yt_initial_data = None
        for script in scripts: # Find ytInitialData again for this page
            script_text = script.string
            if script_text and ('var ytInitialData = ' in script_text or 'window["ytInitialData"] = ' in script_text):
                try:
                    json_str_part = script_text.split('var ytInitialData = ', 1)[-1].split('window["ytInitialData"] = ', 1)[-1]
                    json_str = json_str_part.rstrip(';').split(';</script>')[0]
                    yt_initial_data = json.loads(json_str)
                    break
                except Exception: yt_initial_data = None

        if yt_initial_data:
            # Path to recommendations: contents.twoColumnWatchNextResults.secondaryResults.secondaryResults.results
            raw_reco_items = get_nested(yt_initial_data, ['contents', 'twoColumnWatchNextResults', 'secondaryResults', 'secondaryResults', 'results'])
            if raw_reco_items and isinstance(raw_reco_items, list):
                print(f"API_RECO: Found {len(raw_reco_items)} raw items for recommendations.")
                video_data_list = []
                item_count = 0
                next_continuation_token = None

                for item_content in raw_reco_items:
                    if limit and item_count >= limit and next_continuation_token: break
                    if limit and item_count >= limit and not get_nested(item_content, ['continuationItemRenderer']): break

                    cont_renderer = get_nested(item_content, ['continuationItemRenderer'])
                    if cont_renderer:
                        token = get_nested(cont_renderer, ['continuationEndpoint', 'continuationCommand', 'token'])
                        if token: next_continuation_token = token; print(f"API_RECO: Found continuation token: {token[:20]}...")
                        continue

                    renderer = get_nested(item_content, ['compactVideoRenderer']) # Recommendations often use this
                    if not renderer: renderer = get_nested(item_content, ['videoRenderer']) # Fallback

                    if renderer:
                        video_dict = _parse_video_renderer_item(renderer)
                        if video_dict and video_dict.get('video_id') != current_video_id:
                            video_data_list.append(video_dict)
                            item_count +=1

                print(f"API_RECO: Parsed {len(video_data_list)} recommended videos.")
                return {'videos': video_data_list[:limit], 'continuation_token': next_continuation_token}

    print(f"API: Failed to get or parse recommendations for {current_video_id}. Returning static fallback.")
    static_reco_videos = [
        {'video_id': 'recoVid1', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid1', 'title': 'Static Reco 1', 'thumbnail_url': DEFAULT_THUMBNAIL_PLACEHOLDER, 'channel_name': 'RecoChan1', 'channel_url': '#', 'duration_text': '10:00', 'published_time_text': '1 day ago'},
        {'video_id': 'recoVid2', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid2', 'title': 'Static Reco 2', 'thumbnail_url': DEFAULT_THUMBNAIL_PLACEHOLDER, 'channel_name': 'RecoChan2', 'channel_url': '#', 'duration_text': '12:00', 'published_time_text': '2 days ago'}
    ]
    filtered_recos = [v for v in static_reco_videos if v['video_id'] != current_video_id][:limit]
    return {'videos': filtered_recos, 'continuation_token': f'fake_reco_cont_{current_video_id}_{int(time.time())}' if len(filtered_recos) == limit and len(static_reco_videos) > limit else None}

# --- "Load More" API functions ---
def get_more_home_videos_parsed(continuation_data=None, client_context_from_page=None):
    print(f"API: Getting MORE homepage videos (token: {str(continuation_data)[:20] if continuation_data else 'None'})...")
    if not continuation_data: return {'videos': [], 'continuation_token': None}
    cookies = load_cookies()
    client_context = client_context_from_page or YT_CLIENT_CONTEXT_PLACEHOLDER # Use page context if available
    json_response = _fetch_youtube_continuation_json(continuation_data, cookies, client_context=client_context, endpoint_suffix="browse")
    if json_response:
        return _parse_continuation_json_response(json_response, context="home", limit=30) # Apply limit to continued items too
    return {'videos': [], 'continuation_token': None}

def get_more_subscriptions_videos_parsed(continuation_data=None, client_context_from_page=None):
    print(f"API: Getting MORE subscription videos (token: {str(continuation_data)[:20] if continuation_data else 'None'})...")
    if not continuation_data: return {'videos': [], 'continuation_token': None}
    cookies = load_cookies()
    client_context = client_context_from_page or YT_CLIENT_CONTEXT_PLACEHOLDER
    json_response = _fetch_youtube_continuation_json(continuation_data, cookies, client_context=client_context, endpoint_suffix="browse")
    if json_response:
        return _parse_continuation_json_response(json_response, context="subscriptions", limit=30)
    return {'videos': [], 'continuation_token': None}

def get_more_channel_videos_parsed(channel_url, continuation_data=None, client_context_from_page=None):
    print(f"API: Getting MORE channel videos for {channel_url} (token: {str(continuation_data)[:20] if continuation_data else 'None'})...")
    if not continuation_data: return {'videos': [], 'continuation_token': None}
    cookies = load_cookies()
    client_context = client_context_from_page or YT_CLIENT_CONTEXT_PLACEHOLDER
    # Client context might need specific browseId for channel, usually part of initial ytInitialData.context
    # This part is tricky and might need info from the first page load's context.
    json_response = _fetch_youtube_continuation_json(continuation_data, cookies, client_context=client_context, endpoint_suffix="browse")
    if json_response:
        return _parse_continuation_json_response(json_response, context="channel", limit=30)
    return {'videos': [], 'continuation_token': None}

def get_more_recommended_videos_parsed(current_video_id, continuation_data=None, client_context_from_page=None):
    print(f"API: Getting MORE recommended videos for {current_video_id} (token: {str(continuation_data)[:20] if continuation_data else 'None'})...")
    if not continuation_data: return {'videos': [], 'continuation_token': None}
    cookies = load_cookies()
    client_context = client_context_from_page or YT_CLIENT_CONTEXT_PLACEHOLDER
    # Recommendations often use the /youtubei/v1/next endpoint
    json_response = _fetch_youtube_continuation_json(continuation_data, cookies, client_context=client_context, endpoint_suffix="next")
    if json_response:
        # Recommended items often use compactVideoRenderer
        return _parse_continuation_json_response(json_response, context="recommendations", limit=15) # Limit for recos
    return {'videos': [], 'continuation_token': None}
