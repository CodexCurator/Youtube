import json
import requests
from bs4 import BeautifulSoup
from http.cookiejar import MozillaCookieJar
import os
import time
import re # <--- Added import re

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

def _fetch_youtube_continuation_json(
    continuation_token: str,
    cookies: requests.cookies.RequestsCookieJar,
    innertube_api_key: str,
    client_config: dict,
    endpoint_suffix: str = "browse"
) -> dict | None:
    """
    Fetches continuation data from YouTube's internal youtubei/v1 API.

    Args:
        continuation_token: The token for the next page of results.
        cookies: The user's cookies.
        innertube_api_key: The public Innertube API key (extracted from YouTube's JS).
        client_config: The client configuration dictionary (e.g., from ytInitialData.client).
        endpoint_suffix: The API endpoint (e.g., "browse", "next", "search").
    Returns:
        A dictionary with the JSON response or None on error.
    """
    if not all([continuation_token, innertube_api_key, client_config]):
        print("API_CONTINUATION ERROR: Missing one or more required arguments: continuation_token, innertube_api_key, client_config.")
        return None

    # Basic validation for the key, real keys are usually long alphanumeric strings.
    if len(innertube_api_key) < 20 or "YOUR_KEY" in innertube_api_key or "PLACEHOLDER" in innertube_api_key:
         print(f"API_CONTINUATION WARNING: Potentially invalid or placeholder Innertube API key provided: '{str(innertube_api_key)[:20]}...'. Request will likely fail.")
         # Do not return None here yet, let the request attempt, but it's a strong indicator of failure.

    api_url = f"https://www.youtube.com/youtubei/v1/{endpoint_suffix}?key={innertube_api_key}&prettyPrint=false"

    # Construct the payload context. client_config is expected to be the 'client' dict.
    # Other parts of the context (user, request) can be added if found to be necessary.
    # Minimal context often includes 'client', 'user', and 'request'.
    payload_full_context = {
        "client": client_config,
        "user": {}, # Typically empty for basic browsing unless specific user features are needed.
        "request": {"useSsl": True}, # Common default.
        # 'clickTracking': get_nested(ytInitialData, ['clickTracking'], {}), # Example if needed
    }

    # Ensure essential client fields from placeholder if missing in provided client_config
    # This is a fallback; ideally, client_config passed should be complete from ytInitialData.client
    for key, value in YT_CLIENT_CONTEXT_PLACEHOLDER["client"].items():
        if key not in payload_full_context["client"]:
            payload_full_context["client"][key] = value
            print(f"API_CONTINUATION_PAYLOAD_DEBUG: Using placeholder for client_config.{key}: {value}")


    payload = {
        "context": payload_full_context,
        "continuation": continuation_token
    }

    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    session.headers.update({
        'Content-Type': 'application/json',
        # These headers are often derived from the clientConfig.
        'X-YouTube-Client-Name': str(client_config.get('clientName', YT_CLIENT_CONTEXT_PLACEHOLDER['client']['clientName'])),
        'X-YouTube-Client-Version': client_config.get('clientVersion', YT_CLIENT_CONTEXT_PLACEHOLDER['client']['clientVersion']),
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
    duration_text = duration_text_obj.get('simpleText') or "".join(r.get('text','') for r in duration_text_obj.get('runs', [])) # Fixed: default=[] to []
    if not duration_text:
         overlay_time_status = get_nested(renderer,['thumbnailOverlays',0,'thumbnailOverlayTimeStatusRenderer','text'])
         if overlay_time_status:
            duration_text = overlay_time_status.get('simpleText') or "".join(r.get('text','') for r in overlay_time_status.get('runs', [])) # Fixed: default=[] to []

    published_time_text_obj = renderer.get('publishedTimeText', {})
    published_time_text = published_time_text_obj.get('simpleText') or \
                          "".join(r.get('text','') for r in published_time_text_obj.get('runs', [])) # Fixed: default=[] to []

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

    # For "Load More" functionality context
    extracted_innertube_api_key = None
    extracted_client_config = None

    # Attempt to extract Innertube API Key and client version from script tags
    # This is fragile as YouTube's JS can change.
    # Common pattern: ytcfg.set({"INNERTUBE_API_KEY": "...", "INNERTUBE_CONTEXT_CLIENT_VERSION": "..."});
    # Or sometimes found in ytInitialPlayerResponse for watch pages.

    # First, try to get client config directly from ytInitialData if it was parsed
    if yt_initial_data:
        extracted_client_config = yt_initial_data.get("client")
        # Also, sometimes the full context is in ytInitialData.responseContext which might be useful
        # full_context_from_initial_data = yt_initial_data.get("responseContext")
        # if full_context_from_initial_data:
        #    print(f"API_PARSE_DEBUG: Found responseContext in ytInitialData: {str(full_context_from_initial_data)[:200]}")


    for script_tag_content in [s.string for s in scripts if s.string]:
        if extracted_innertube_api_key and extracted_client_config and extracted_client_config.get('clientVersion') != YT_CLIENT_CONTEXT_PLACEHOLDER['client']['clientVersion']:
            # If we have a key and a non-placeholder client config, we might be done with script searching for these.
            # However, client_config can also come from ytInitialData.client directly.
            # The key is the main thing from ytcfg.
            if extracted_innertube_api_key: # Only break if key is found, client_config might be better from ytInitialData
                 break


        # Attempt to find Innertube API Key
        if not extracted_innertube_api_key:
            match_api_key = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', script_tag_content)
            if match_api_key:
                extracted_innertube_api_key = match_api_key.group(1)
                print(f"API_PARSE_CONTEXT: Found INNERTUBE_API_KEY: ...{extracted_innertube_api_key[-10:]}") # Log last 10 chars for brevity

        # Attempt to find client version and name from ytcfg if client_config wasn't fully populated from ytInitialData
        # This provides a fallback or supplement to ytInitialData.client
        if not extracted_client_config or not extracted_client_config.get('clientVersion') or not extracted_client_config.get('clientName'):
            temp_client_version = None
            temp_client_name = None

            match_client_version = re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION"\s*:\s*"([^"]+)"', script_tag_content)
            if match_client_version:
                temp_client_version = match_client_version.group(1)
                print(f"API_PARSE_CONTEXT: Found INNERTUBE_CONTEXT_CLIENT_VERSION: {temp_client_version}")

            # clientName is often "WEB" or "WEB_REMIX" (for YouTube Music)
            # It might be in INNERTUBE_CONTEXT or directly as clientName in ytcfg
            match_client_name = re.search(r'"INNERTUBE_CLIENT_NAME"\s*:\s*"([^"]+)"', script_tag_content) \
                                 or re.search(r'"CLIENT_NAME"\s*:\s*"([^"]+)"', script_tag_content) # Common variations
            if match_client_name:
                temp_client_name = match_client_name.group(1).upper() # Often "WEB"
                print(f"API_PARSE_CONTEXT: Found client name from ytcfg: {temp_client_name}")

            if temp_client_version or temp_client_name:
                if not extracted_client_config: # If no client config from ytInitialData at all
                    extracted_client_config = YT_CLIENT_CONTEXT_PLACEHOLDER['client'].copy() # Start with placeholder

                if temp_client_version and extracted_client_config.get('clientVersion') == YT_CLIENT_CONTEXT_PLACEHOLDER['client']['clientVersion']:
                     extracted_client_config['clientVersion'] = temp_client_version
                if temp_client_name: # ytcfg clientName might be more specific (e.g. WEB_REMIX)
                     extracted_client_config['clientName'] = temp_client_name

    # If still no complete client_config, use placeholder as last resort
    if not extracted_client_config:
        print("API_PARSE_CONTEXT: No client config found from ytInitialData or ytcfg, using placeholder.")
        extracted_client_config = YT_CLIENT_CONTEXT_PLACEHOLDER['client'].copy()
    elif extracted_client_config.get('clientVersion') == YT_CLIENT_CONTEXT_PLACEHOLDER['client']['clientVersion'] and 'INNERTUBE_CONTEXT_CLIENT_VERSION' not in str(scripts):
        # If clientVersion is still the placeholder and we didn't find a specific one in scripts, it's likely correct enough for WEB.
        pass


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
    return {
        'videos': video_data_list,
        'continuation_token': continuation_token,
        'innertube_api_key': extracted_innertube_api_key,
        'client_config': extracted_client_config
    }

# --- Main Data Fetching Functions ---
# Standard dictionary to return on failure for main fetch functions
EMPTY_PARSED_DATA = {
    'videos': [],
    'continuation_token': None,
    'innertube_api_key': None,
    'client_config': None
}

def get_homepage_videos_parsed(limit=30):
    print("API: Attempting to fetch and parse homepage videos...")
    cookies = load_cookies()
    html_content = _make_yt_request("https://www.youtube.com/", cookies)
    if html_content:
        return parse_video_data_from_script(html_content, context="home", limit=limit)
    print("API: Failed to get homepage HTML.")
    return EMPTY_PARSED_DATA.copy()

def search_videos_parsed(query, limit=30):
    print(f"API: Searching for '{query}'...")
    cookies = load_cookies()
    html_content = _make_yt_request(f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}", cookies)
    if html_content:
        return parse_video_data_from_script(html_content, context="search", limit=limit)
    print(f"API: Failed to get search results HTML for '{query}'.")
    return EMPTY_PARSED_DATA.copy()

def get_subscriptions_feed_parsed(limit=30):
    print("API: Attempting to fetch and parse actual subscriptions feed...")
    cookies = load_cookies()
    if not cookies or len(cookies) == 0:
        print("API: No cookies loaded, cannot fetch subscriptions feed.")
        return EMPTY_PARSED_DATA.copy()
    html_content = _make_yt_request("https://www.youtube.com/feed/subscriptions", cookies)
    if html_content:
        return parse_video_data_from_script(html_content, context="subscriptions", limit=limit)
    print("API: Failed to get subscriptions page HTML.")
    return EMPTY_PARSED_DATA.copy()

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
                        if token: next_continuation_token = token; print(f"API_RECO: Found continuation token from item: {str(token)[:20]}...")
                        continue

                    # Try various common renderer paths for recommendations
                    # compactVideoRenderer is very common for recommendations.
                    # Sometimes it might be nested under other renderers (e.g. shelfRenderer, itemSectionRenderer content)
                    # However, 'results' usually gives a flat list of these directly.

                    possible_renderers = [
                        get_nested(item_content, ['compactVideoRenderer']),
                        get_nested(item_content, ['videoRenderer']), # Less common directly in reco list, but possible
                        # Could add more specific ones if found during debugging, e.g., from a playlist or mix
                        get_nested(item_content, ['pivotVideoRenderer']), # Older, but for completeness
                        get_nested(item_content, ['richItemRenderer', 'content', 'compactVideoRenderer']), # If wrapped
                        get_nested(item_content, ['richItemRenderer', 'content', 'videoRenderer'])
                    ]
                    renderer = next((r for r in possible_renderers if r), None)

                    if not renderer and isinstance(item_content, dict) : # Log if no renderer found in an item
                         print(f"API_RECO_DEBUG: No direct renderer found in item. Keys: {list(item_content.keys())}")
                         # Check for common wrappers if direct access failed
                         if get_nested(item_content, ['videoLockupRenderer', 'videoLockupViewModel', 'videoViewModel', 'videoRenderer']): # A very specific observed path
                            renderer = get_nested(item_content, ['videoLockupRenderer', 'videoLockupViewModel', 'videoViewModel', 'videoRenderer'])
                            if renderer: print("API_RECO_DEBUG: Found renderer via videoLockupRenderer path.")


                    if renderer:
                        video_dict = _parse_video_renderer_item(renderer)
                        if video_dict:
                            if video_dict.get('video_id') != current_video_id:
                                video_data_list.append(video_dict)
                                item_count += 1
                                # print(f"API_RECO_DEBUG: Added reco: {video_dict.get('title')}") # Verbose
                            # else: # Debugging for why a video might be skipped
                                # print(f"API_RECO_DEBUG: Skipped reco (matches current video): {video_dict.get('title')}")
                        # else: # Debugging for why parsing failed for a renderer
                            # print(f"API_RECO_DEBUG: _parse_video_renderer_item failed for renderer: {str(renderer)[:100]}")
                    # else: # Debugging for items that don't yield any renderer
                        # if not cont_renderer: # Avoid logging continuation items as "no renderer"
                            # print(f"API_RECO_DEBUG: No renderer extracted from item_content: {str(item_content)[:200]}")

                print(f"API_RECO: Parsed {len(video_data_list)} recommended videos. Next token: {str(next_continuation_token)[:20] if next_continuation_token else 'None'}")
                return {'videos': video_data_list[:limit], 'continuation_token': next_continuation_token}
            else: # raw_reco_items was None or not a list
                if yt_initial_data: # Log structure if results path failed
                    secondary_results_node = get_nested(yt_initial_data, ['contents', 'twoColumnWatchNextResults', 'secondaryResults', 'secondaryResults'])
                    if secondary_results_node:
                        print(f"API_RECO_DEBUG: secondaryResults.secondaryResults node found. Keys: {list(secondary_results_node.keys())}")
                    else:
                        watch_next_node = get_nested(yt_initial_data, ['contents', 'twoColumnWatchNextResults'])
                        if watch_next_node:
                             print(f"API_RECO_DEBUG: twoColumnWatchNextResults node found. Keys: {list(watch_next_node.keys())}")


    print(f"API: Failed to get or parse recommendations for {current_video_id}. Returning static fallback.")
    # Static fallback should also conform to the new richer dictionary structure, even if key/config are None
    static_reco_videos = [
        {'video_id': 'recoVid1', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid1', 'title': 'Static Reco 1', 'thumbnail_url': DEFAULT_THUMBNAIL_PLACEHOLDER, 'channel_name': 'RecoChan1', 'channel_url': '#', 'duration_text': '10:00', 'published_time_text': '1 day ago'},
        {'video_id': 'recoVid2', 'youtube_url': 'https://www.youtube.com/watch?v=recoVid2', 'title': 'Static Reco 2', 'thumbnail_url': DEFAULT_THUMBNAIL_PLACEHOLDER, 'channel_name': 'RecoChan2', 'channel_url': '#', 'duration_text': '12:00', 'published_time_text': '2 days ago'}
    ]
    filtered_recos = [v for v in static_reco_videos if v['video_id'] != current_video_id][:limit]

    return {
        'videos': filtered_recos,
        'continuation_token': f'fake_reco_cont_{current_video_id}_{int(time.time())}' if len(filtered_recos) == limit and len(static_reco_videos) > limit else None,
        'innertube_api_key': None, # No key from static data
        'client_config': None # No client config from static data
    }

# --- "Load More" API functions ---
# Each of these will now require innertube_api_key and client_config to be passed.
# They will return the standard rich dictionary, including these keys for the next call.

def get_more_home_videos_parsed(continuation_data: str, innertube_api_key: str, client_config: dict):
    print(f"API: Getting MORE homepage videos (token: {str(continuation_data)[:20]})...")
    if not all([continuation_data, innertube_api_key, client_config]):
        print("API_MORE_HOME: Missing required arguments for continuation.")
        return EMPTY_PARSED_DATA.copy()

    cookies = load_cookies()
    json_response = _fetch_youtube_continuation_json(
        continuation_token=continuation_data,
        cookies=cookies,
        innertube_api_key=innertube_api_key,
        client_config=client_config,
        endpoint_suffix="browse"
    )
    if json_response:
        parsed = _parse_continuation_json_response(json_response, context="home", limit=30)
        # Return the original key/config as they are typically stable for a session of pagination
        parsed['innertube_api_key'] = innertube_api_key
        parsed['client_config'] = client_config
        return parsed
    return {**EMPTY_PARSED_DATA.copy(), 'innertube_api_key': innertube_api_key, 'client_config': client_config}


def get_more_subscriptions_videos_parsed(continuation_data: str, innertube_api_key: str, client_config: dict):
    print(f"API: Getting MORE subscription videos (token: {str(continuation_data)[:20]})...")
    if not all([continuation_data, innertube_api_key, client_config]):
        print("API_MORE_SUBS: Missing required arguments for continuation.")
        return EMPTY_PARSED_DATA.copy()

    cookies = load_cookies()
    json_response = _fetch_youtube_continuation_json(
        continuation_token=continuation_data,
        cookies=cookies,
        innertube_api_key=innertube_api_key,
        client_config=client_config,
        endpoint_suffix="browse"
    )
    if json_response:
        parsed = _parse_continuation_json_response(json_response, context="subscriptions", limit=30)
        parsed['innertube_api_key'] = innertube_api_key
        parsed['client_config'] = client_config
        return parsed
    return {**EMPTY_PARSED_DATA.copy(), 'innertube_api_key': innertube_api_key, 'client_config': client_config}

def get_more_channel_videos_parsed(channel_url: str, continuation_data: str, innertube_api_key: str, client_config: dict):
    # channel_url might not be strictly needed if context is well-formed, but good for logging
    print(f"API: Getting MORE channel videos for {channel_url} (token: {str(continuation_data)[:20]})...")
    if not all([continuation_data, innertube_api_key, client_config]):
        print("API_MORE_CHANNEL: Missing required arguments for continuation.")
        return EMPTY_PARSED_DATA.copy()

    cookies = load_cookies()
    json_response = _fetch_youtube_continuation_json(
        continuation_token=continuation_data,
        cookies=cookies,
        innertube_api_key=innertube_api_key,
        client_config=client_config,
        endpoint_suffix="browse"
    )
    if json_response:
        parsed = _parse_continuation_json_response(json_response, context="channel", limit=30)
        parsed['innertube_api_key'] = innertube_api_key
        parsed['client_config'] = client_config
        return parsed
    return {**EMPTY_PARSED_DATA.copy(), 'innertube_api_key': innertube_api_key, 'client_config': client_config}


def get_more_recommended_videos_parsed(current_video_id: str, continuation_data: str, innertube_api_key: str, client_config: dict):
    print(f"API: Getting MORE recommended videos for {current_video_id} (token: {str(continuation_data)[:20]})...")
    if not all([continuation_data, innertube_api_key, client_config]):
        print("API_MORE_RECO: Missing required arguments for continuation.")
        return EMPTY_PARSED_DATA.copy()

    cookies = load_cookies()
    json_response = _fetch_youtube_continuation_json(
        continuation_token=continuation_data,
        cookies=cookies,
        innertube_api_key=innertube_api_key,
        client_config=client_config,
        endpoint_suffix="next" # Recommendations use "next" endpoint
    )
    if json_response:
        parsed = _parse_continuation_json_response(json_response, context="recommendations", limit=15)
        parsed['innertube_api_key'] = innertube_api_key
        parsed['client_config'] = client_config
        return parsed
    return {**EMPTY_PARSED_DATA.copy(), 'innertube_api_key': innertube_api_key, 'client_config': client_config}
