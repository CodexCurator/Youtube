# YouTube Data Viewer & Player

This Flask application allows you to browse YouTube content (homepage recommendations and search results) using your own YouTube account's context by leveraging your browser cookies. When you click on a video, it is downloaded to a temporary local directory and then played directly in your browser using an HTML5 video player.

The tool also includes a GUI utility (`cookie_gui_helper.py`) to help you manage the necessary cookie file.

## Features

*   View YouTube homepage recommendations (if cookies are correctly configured and parsed).
*   Search YouTube for videos.
*   Displays video title, thumbnail, channel name.
*   **Click-to-Play:** Clicking a video downloads it to a local temporary folder (`youtube_client/static/temp_videos/`) and then plays it in a dedicated page within the app.
*   Downloads are in MP4 format where possible.
*   **GUI Cookie Helper:** A Tkinter-based GUI tool (`cookie_gui_helper.py`) to help create/update the `www.youtube.com_cookies.txt` file from your browser's exported cookies (Netscape format).

## Limitations & Disclaimer

*   **EXTREMELY FRAGILE PARSER:** Relies on parsing `ytInitialData` from YouTube's web page. YouTube changes can break this.
*   **Cookie Dependent:** Personalized content (especially homepage) relies on valid cookies in the Netscape `cookies.txt` format. Search functionality may work without full cookie authentication.
*   **Synchronous Downloads for Playback:** When you click to play a video, the page will wait (hang) until the download is complete. This is not ideal for large files or slow connections.
*   **`yt-dlp` Dependency:** Video downloading requires `yt-dlp` to be installed and accessible in your system's PATH.
*   **Temporary File Storage:** Downloaded videos are stored in `youtube_client/static/temp_videos/`. These files currently accumulate. There is no automatic cleanup mechanism for old temporary files in this version.
*   **Bot Detection:** Use responsibly.
*   **Terms of Service:** Be mindful of YouTube's Terms of Service.

## Prerequisites

*   Python 3.7+
*   `pip` (Python package installer)
*   A web browser (for viewing the app)
*   **`yt-dlp`:** Must be installed and globally accessible in your system's PATH. (Installation: [https://github.com/yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp))

## Setup Instructions

1.  **Clone the Repository or Download Files:**
    Ensure you have all project files, including the `youtube_client` directory, `cookie_gui_helper.py`, and `requirements.txt`.

2.  **Create and Activate a Python Virtual Environment:**
    (Recommended to avoid conflicts with global Python packages)
    *   In your project root directory (e.g., `C:\Users\artur\Desktop\Youtube\`):
    *   macOS/Linux:
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```
    *   Windows:
        ```bash
        python -m venv venv
        .\venv\Scripts\activate
        ```

3.  **Install Dependencies:**
    With your virtual environment activated, run:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Up Cookies (`www.youtube.com_cookies.txt`):**
    This application requires your YouTube cookies in the **Netscape `cookies.txt` format**. The file must be named `www.youtube.com_cookies.txt` and placed in the **project root directory** (e.g., `C:\Users\artur\Desktop\Youtube\www.youtube.com_cookies.txt`).

    *   **Using the GUI Cookie Helper (Recommended):**
        1.  Run the helper script from the project root:
            ```bash
            python cookie_gui_helper.py
            ```
        2.  The GUI will open. Follow the instructions within the helper:
            *   It's designed primarily for Netscape `cookies.txt` format.
            *   Use a browser extension like "Get cookies.txt" or "cookies.txt" to export cookies from `youtube.com`.
            *   In the helper, click "Load Netscape Cookies.txt File...", select your exported file, then click "Save to www.youtube.com_cookies.txt".
            *   Alternatively, you can paste the raw text content of a `cookies.txt` file into the text area and save.

    *   **Manual Method:**
        1.  Export your cookies from `youtube.com` using a browser extension that supports Netscape `cookies.txt` format (e.g., "Get cookies.txt").
        2.  Save this file as `www.youtube.com_cookies.txt` directly in your project root directory.

    *   **Important:** This cookie file is sensitive. The `.gitignore` file is set up to prevent it from being accidentally committed to a Git repository.

5.  **Ensure `yt-dlp` is Installed:**
    If you haven't already, download `yt-dlp` from its official repository and ensure the executable is in your system's PATH.

## Running the Application

1.  **Activate your virtual environment** (if not already active).
2.  **Navigate to the project root directory** (e.g., `C:\Users\artur\Desktop\Youtube\`). This is the directory that contains the `youtube_client` folder and your `www.youtube.com_cookies.txt`.
3.  **Run the application using the following command:**
    ```bash
    python -m youtube_client.app
    ```
    *   **Note:** Running `python youtube_client/app.py` directly will likely cause `ImportError`s. The command above is the correct way.

4.  Open your web browser and go to: `http://127.0.0.1:5001/`

## Using the Application

*   The homepage should display recommended videos if your cookies are working correctly. (Currently, there's a known issue where homepage cookies might not be fully effective, but search should work).
*   Use the search bar to find videos.
*   Click on any video's thumbnail or title.
*   The application will then download that video to a temporary local directory (`youtube_client/static/temp_videos/`) and automatically start playing it on a new page within the application. Please be patient as the download occurs.

## How It Works

*   **Web Interface:** A Flask web application serves the frontend.
*   **YouTube Data:** It fetches data by making HTTP requests to YouTube (mimicking a browser) and parsing a JavaScript object (`ytInitialData`) found in the page source. It does **not** use the official YouTube API.
*   **Cookies:** Uses cookies from your `www.youtube.com_cookies.txt` file (Netscape format) for making authenticated requests to YouTube.
*   **Video Playing:** When a video is clicked, `yt-dlp` is called as a subprocess to download the video. The downloaded video (MP4 if possible) is then served via a static path to an HTML5 `<video>` player.

## Troubleshooting

*   **ImportError:** If you get import errors, ensure you are running the app with `python -m youtube_client.app` from the **project root directory**.
*   **No Personalized Homepage / Search Works:** This likely means there's an issue with how your cookies are being parsed or sent for the homepage request. Debugging statements in `youtube_client/youtube_api.py` can be uncommented to investigate. Ensure `www.youtube.com_cookies.txt` is correctly formatted and contains fresh, valid cookies.
*   **Downloads Fail:**
    *   Ensure `yt-dlp` is installed and in your system's PATH.
    *   Check for error messages flashed in the web UI.
    *   The video might be private, region-restricted, or have other download issues.
*   **Video Player Issues:** The built-in HTML5 video player relies on browser support for MP4 (H.264/AAC). Most modern browsers are fine. If a video downloads in a different format unexpectedly, it might not play.
---

This README should now be up-to-date with the project's current state and instructions.
