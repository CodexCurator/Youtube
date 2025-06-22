import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import json
import os

# Target file for the main application (Netscape format)
NETSCAPE_COOKIES_FILE_PATH = 'www.youtube.com_cookies.txt'
# Previous JSON target, can be kept for reference or if we add conversion
# JSON_COOKIES_FILE_PATH = 'cookies.json'

class CookieHelperApp:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("YouTube Cookie Helper")
        # Increased height to better accommodate instructions and text area
        self.root.geometry("650x600")

        # Instructions Frame
        instruction_frame = tk.Frame(root_window, bd=1, relief=tk.GROOVE)
        instruction_frame.pack(pady=10, padx=10, fill=tk.X)

        tk.Label(instruction_frame, text="Cookie Input Guide:", font=('Arial', 12, 'bold')).pack(anchor="w", padx=5, pady=(5,0))
        instructions_text = (
            f"This tool helps you create/update '{NETSCAPE_COOKIES_FILE_PATH}'.\n"
            "The main application uses this file to load your YouTube cookies.\n\n"
            "Recommended Method: Netscape Format (cookies.txt)\n"
            "1. Use a browser extension like 'Get cookies.txt' or 'cookies.txt' to export cookies \n"
            "   from youtube.com in the Netscape `cookies.txt` format.\n"
            "2. Click 'Load Netscape Cookies.txt File...' below and select your exported file, OR\n"
            "3. Paste the content of your `cookies.txt` file directly into the text area.\n"
            "4. Click 'Save to www.youtube.com_cookies.txt'.\n\n"
            "Alternative (if you have JSON cookies from another tool):\n"
            "   If you have cookies in the JSON array format (like the old `cookies.json`):\n"
            "   - You can paste this JSON array into the text area.\n"
            "   - Then click 'Save as JSON (cookies.json)'. Note: The main app currently DOES NOT use this JSON file.\n"
            "   - Manual conversion or a more advanced tool would be needed to convert this JSON to Netscape format for the main app.\n"
        )
        self.instructions_label = tk.Label(instruction_frame, text=instructions_text, justify=tk.LEFT, anchor="w", wraplength=620)
        self.instructions_label.pack(pady=5, padx=5, fill=tk.X)

        # Text Area for Cookie Data
        tk.Label(root_window, text="Cookie Data (Paste Netscape format or JSON array here):").pack(anchor="w", padx=10, pady=(10,0))
        self.cookie_text_area = scrolledtext.ScrolledText(root_window, wrap=tk.WORD, height=15, width=75)
        self.cookie_text_area.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        # Frame for buttons
        button_frame = tk.Frame(root_window)
        button_frame.pack(pady=10, padx=10, fill=tk.X)

        self.load_netscape_button = tk.Button(button_frame, text="Load Netscape Cookies.txt File...", command=self.load_netscape_file)
        self.load_netscape_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.save_netscape_button = tk.Button(button_frame, text=f"Save to {NETSCAPE_COOKIES_FILE_PATH}", command=self.save_netscape_cookies)
        self.save_netscape_button.pack(side=tk.LEFT, padx=5, pady=5)

        # self.save_json_button = tk.Button(button_frame, text="Save as JSON (cookies.json)", command=self.save_json_cookies)
        # self.save_json_button.pack(side=tk.LEFT, padx=5, pady=5) # Kept for reference, but less critical now

        # Status Label
        self.status_label_text = tk.StringVar()
        self.status_label = tk.Label(root_window, textvariable=self.status_label_text, fg="blue")
        self.status_label.pack(pady=5, padx=10)

        self.load_existing_netscape_cookies()

    def load_existing_netscape_cookies(self):
        if os.path.exists(NETSCAPE_COOKIES_FILE_PATH):
            try:
                with open(NETSCAPE_COOKIES_FILE_PATH, 'r', encoding='utf-8') as f:
                    self.cookie_text_area.insert(tk.INSERT, f.read())
                self.status_label_text.set(f"Loaded existing '{NETSCAPE_COOKIES_FILE_PATH}'.")
                self.status_label.config(fg="blue")
            except Exception as e:
                self.status_label_text.set(f"Error loading '{NETSCAPE_COOKIES_FILE_PATH}': {e}")
                self.status_label.config(fg="red")
        else:
            self.status_label_text.set(f"'{NETSCAPE_COOKIES_FILE_PATH}' not found. Ready for input or load.")
            self.status_label.config(fg="blue")

    def load_netscape_file(self):
        filepath = filedialog.askopenfilename(
            title="Open Netscape Cookie File (cookies.txt)",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*"))
        )
        if not filepath:
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            # Basic validation: Does it look like a Netscape file (comments, tab-separated values)?
            # This is a weak check. Stronger validation would parse line by line.
            if not ("# Netscape HTTP Cookie File" in content or "# HTTP Cookie File" in content or "\t" in content):
                 if not messagebox.askyesno("Potential Format Issue", "The file doesn't strongly resemble a Netscape cookies.txt file. Load anyway?"):
                    return

            self.cookie_text_area.delete('1.0', tk.END)
            self.cookie_text_area.insert(tk.INSERT, content)
            self.status_label_text.set(f"Content loaded from '{os.path.basename(filepath)}'. Review and save.")
            self.status_label.config(fg="green")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file: {e}")
            self.status_label_text.set(f"Error loading file: {e}")
            self.status_label.config(fg="red")

    def save_netscape_cookies(self):
        cookie_data_string = self.cookie_text_area.get("1.0", tk.END).strip()
        if not cookie_data_string:
            messagebox.showerror("Error", "Cookie data input is empty.")
            self.status_label_text.set("Error: Text area is empty.")
            self.status_label.config(fg="red")
            return

        # Basic validation for Netscape format:
        # Should contain some tab characters if it has actual cookie lines.
        # Should not be a JSON array start/end character if it's meant to be Netscape.
        if cookie_data_string.startswith("[") and cookie_data_string.endswith("]"):
            if not messagebox.askyesno("Potential Format Mismatch",
                                       f"The data looks like JSON, but you are saving to '{NETSCAPE_COOKIES_FILE_PATH}' (Netscape format).\n"
                                       "The main app expects Netscape format in this file. Continue saving as is?"):
                self.status_label_text.set("Save cancelled by user due to format mismatch concern.")
                self.status_label.config(fg="orange")
                return
        elif "\t" not in cookie_data_string and "#" not in cookie_data_string: # Heuristic
             if not messagebox.askyesno("Potential Format Issue",
                                       f"The data doesn't clearly look like Netscape format (missing tabs or comments). Save to '{NETSCAPE_COOKIES_FILE_PATH}' anyway?"):
                self.status_label_text.set("Save cancelled by user due to format concern.")
                self.status_label.config(fg="orange")
                return


        try:
            with open(NETSCAPE_COOKIES_FILE_PATH, 'w', encoding='utf-8') as f:
                # Add a BOM if it's not there? Some tools expect it, some don't.
                # Python's default utf-8 encoding doesn't add BOM. This is usually fine.
                # Ensure final newline if not present, as some parsers are picky
                if not cookie_data_string.endswith('\n'):
                    cookie_data_string += '\n'
                f.write(cookie_data_string)

            self.status_label_text.set(f"Success! Cookies saved to '{NETSCAPE_COOKIES_FILE_PATH}'.")
            self.status_label.config(fg="green")
            messagebox.showinfo("Success", f"Cookies saved to '{NETSCAPE_COOKIES_FILE_PATH}'.\nThe main application will use this file.")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
            self.status_label_text.set(f"Error saving cookies: {e}")
            self.status_label.config(fg="red")

    # def save_json_cookies(self):
    #     """Saves content of text area as JSON to cookies.json.
    #        Main app currently does not use this file.
    #     """
    #     cookie_json_string = self.cookie_text_area.get("1.0", tk.END).strip()
    #     if not cookie_json_string:
    #         messagebox.showerror("Error", "Cookie JSON input is empty.")
    #         self.status_label_text.set("Error: Text area is empty for JSON save.")
    #         self.status_label.config(fg="red")
    #         return

    #     try:
    #         parsed_cookies = json.loads(cookie_json_string)
    #         if not isinstance(parsed_cookies, list):
    #             messagebox.showerror("Error", "Invalid JSON format. Expected a JSON array.")
    #             self.status_label_text.set("Error: Not a JSON array.")
    #             self.status_label.config(fg="red")
    #             return
    #         if parsed_cookies and not all(isinstance(item, dict) for item in parsed_cookies):
    #             messagebox.showerror("Error", "Invalid JSON format. Array should contain cookie objects.")
    #             self.status_label_text.set("Error: Array items not objects.")
    #             self.status_label.config(fg="red")
    #             return

    #         with open(JSON_COOKIES_FILE_PATH, 'w', encoding='utf-8') as f:
    #             json.dump(parsed_cookies, f, indent=2)

    #         self.status_label_text.set(f"Success! Cookies saved to '{JSON_COOKIES_FILE_PATH}'. (Main app does not use this file).")
    #         self.status_label.config(fg="green")
    #         messagebox.showinfo("Success", f"Cookies saved to '{JSON_COOKIES_FILE_PATH}'.\nNote: The main application currently uses '{NETSCAPE_COOKIES_FILE_PATH}'.")
    #     except json.JSONDecodeError:
    #         messagebox.showerror("Error", "Invalid JSON format. Please check input.")
    #         self.status_label_text.set("Error: Invalid JSON for JSON save.")
    #         self.status_label.config(fg="red")
    #     except Exception as e:
    #         messagebox.showerror("Error", f"An unexpected error occurred: {e}")
    #         self.status_label_text.set(f"Error saving JSON cookies: {e}")
    #         self.status_label.config(fg="red")


if __name__ == "__main__":
    main_window = tk.Tk()
    app = CookieHelperApp(main_window)
    main_window.mainloop()
