import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import json
import os

# Define the target cookies.json path (assuming this script is in the project root)
COOKIES_FILE_PATH = 'cookies.json'
# If this script were in youtube_client/, COOKIES_FILE_PATH would be '../cookies.json'

class CookieHelperApp:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("YouTube Cookie Helper")
        self.root.geometry("600x550") # Adjusted size for better layout

        # Instructions
        instructions_text = (
            "How to get your YouTube cookies (JSON format):\n"
            "1. Open YouTube in your browser (ensure you are logged in).\n"
            "2. Open Developer Tools (usually F12 or Right-click -> Inspect).\n"
            "3. Go to 'Application' (Chrome/Edge) or 'Storage' (Firefox).\n"
            "4. Under 'Cookies', select 'https://www.youtube.com'.\n"
            "5. You need to export these cookies as a JSON array.\n"
            "   - Extensions like 'EditThisCookie' (Chrome) can export in JSON format.\n"
            "   - Or, 'Get cookies.txt' can export, then you might need to convert it.\n"
            "   - The format should be an array of cookie objects, like in cookies.json.example.\n"
            "6. Paste the entire JSON array string into the text box below.\n"
            "7. Click 'Save Cookies'. This will create/overwrite 'cookies.json' in the app's root."
        )
        self.instructions_label = tk.Label(root_window, text=instructions_text, justify=tk.LEFT, anchor="w", wraplength=580)
        self.instructions_label.pack(pady=10, padx=10, fill=tk.X)

        # Text Area for Cookie JSON
        self.cookie_text_area_label = tk.Label(root_window, text="Paste Cookie JSON here:")
        self.cookie_text_area_label.pack(anchor="w", padx=10)
        self.cookie_text_area = scrolledtext.ScrolledText(root_window, wrap=tk.WORD, height=15, width=70)
        self.cookie_text_area.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        # Frame for buttons
        button_frame = tk.Frame(root_window)
        button_frame.pack(pady=10, padx=10, fill=tk.X)

        # Load from File Button
        self.load_button = tk.Button(button_frame, text="Load from File...", command=self.load_cookies_from_file)
        self.load_button.pack(side=tk.LEFT, padx=5)

        # Save Button
        self.save_button = tk.Button(button_frame, text="Save Cookies to cookies.json", command=self.save_cookies)
        self.save_button.pack(side=tk.LEFT, padx=5)

        # Status Label
        self.status_label_text = tk.StringVar()
        self.status_label = tk.Label(root_window, textvariable=self.status_label_text, fg="green")
        self.status_label.pack(pady=5, padx=10)

        # Pre-fill with existing cookies.json if it exists
        self.load_existing_cookies()

    def load_existing_cookies(self):
        if os.path.exists(COOKIES_FILE_PATH):
            try:
                with open(COOKIES_FILE_PATH, 'r', encoding='utf-8') as f:
                    # Read and pretty print for display
                    cookies_data = json.load(f)
                    self.cookie_text_area.insert(tk.INSERT, json.dumps(cookies_data, indent=2))
                self.status_label_text.set(f"Loaded existing '{COOKIES_FILE_PATH}'.")
                self.status_label.config(fg="blue")
            except Exception as e:
                self.status_label_text.set(f"Error loading existing '{COOKIES_FILE_PATH}': {e}")
                self.status_label.config(fg="red")
        else:
            self.status_label_text.set(f"'{COOKIES_FILE_PATH}' not found. Ready for new input.")
            self.status_label.config(fg="blue")


    def load_cookies_from_file(self):
        filepath = filedialog.askopenfilename(
            title="Open Cookie File",
            filetypes=(("JSON files", "*.json"), ("Text files", "*.txt"), ("All files", "*.*"))
        )
        if not filepath:
            return # User cancelled

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Try to parse as JSON directly
            try:
                cookies_data = json.loads(content)
                # Basic validation: is it a list?
                if not isinstance(cookies_data, list):
                    # If not a list, maybe it's a single cookie object, or Netscape format
                    # For now, we are strict and expect a JSON array as per cookies.json.example
                    messagebox.showerror("Error", "Invalid format. Expected a JSON array of cookie objects.")
                    self.status_label_text.set("Load failed: Not a JSON array.")
                    self.status_label.config(fg="red")
                    return

                self.cookie_text_area.delete('1.0', tk.END)
                self.cookie_text_area.insert(tk.INSERT, json.dumps(cookies_data, indent=2))
                self.status_label_text.set(f"Cookies loaded from '{os.path.basename(filepath)}'. Review and save.")
                self.status_label.config(fg="green")

            except json.JSONDecodeError:
                # Could try parsing Netscape cookies.txt format here if desired as an enhancement
                messagebox.showerror("Error", "Could not parse file as JSON. Ensure it's a valid JSON array of cookies.")
                self.status_label_text.set("Load failed: Not valid JSON.")
                self.status_label.config(fg="red")
                return

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file: {e}")
            self.status_label_text.set(f"Error loading file: {e}")
            self.status_label.config(fg="red")


    def save_cookies(self):
        cookie_json_string = self.cookie_text_area.get("1.0", tk.END).strip()
        if not cookie_json_string:
            self.status_label_text.set("Error: Text area is empty.")
            self.status_label.config(fg="red")
            messagebox.showerror("Error", "Cookie JSON input is empty.")
            return

        try:
            # Parse the JSON to validate its structure
            parsed_cookies = json.loads(cookie_json_string)

            # Basic validation: should be a list of objects (cookies)
            if not isinstance(parsed_cookies, list):
                self.status_label_text.set("Error: Cookie data must be a JSON array.")
                self.status_label.config(fg="red")
                messagebox.showerror("Error", "Invalid format. Expected a JSON array of cookie objects.")
                return

            # Further validation: check if items in list are dictionaries (optional but good)
            if parsed_cookies: # if list is not empty
                if not all(isinstance(item, dict) for item in parsed_cookies):
                    self.status_label_text.set("Error: Array items must be cookie objects (dictionaries).")
                    self.status_label.config(fg="red")
                    messagebox.showerror("Error", "Invalid format. Array should contain cookie objects.")
                    return

            # If validation passes, save to cookies.json
            # Save with indent for readability, though not strictly necessary for the app
            with open(COOKIES_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(parsed_cookies, f, indent=2) # Save pretty-printed

            self.status_label_text.set(f"Success! Cookies saved to '{COOKIES_FILE_PATH}'.")
            self.status_label.config(fg="green")
            messagebox.showinfo("Success", f"Cookies successfully saved to '{COOKIES_FILE_PATH}'.\nThe main application will now use these cookies.")

        except json.JSONDecodeError:
            self.status_label_text.set("Error: Invalid JSON format in text area.")
            self.status_label.config(fg="red")
            messagebox.showerror("Error", "Invalid JSON format. Please check your input.")
        except Exception as e:
            self.status_label_text.set(f"Error saving cookies: {e}")
            self.status_label.config(fg="red")
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main_window = tk.Tk()
    app = CookieHelperApp(main_window)
    main_window.mainloop()
