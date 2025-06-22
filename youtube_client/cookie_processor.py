import os
import shutil

def process_new_cookie_file(source_path, operational_cookie_path):
    """
    Processes a new cookie file from source_path and updates the operational_cookie_path.

    Args:
        source_path (str): Path to the new cookie file (expected Netscape format).
        operational_cookie_path (str): Path where the app expects its cookie file.

    Returns:
        bool: True if processing was successful, False otherwise.
    """
    if not os.path.exists(source_path):
        print(f"Cookie Processor: Source cookie file not found at '{source_path}'.")
        return False

    try:
        # Read content from source
        with open(source_path, 'r', encoding='utf-8') as f_source:
            content = f_source.read().strip()

        # Basic validation for Netscape format
        # A very simple check: non-empty and contains at least one tab (common in Netscape data lines)
        # or starts with the typical Netscape header.
        is_likely_netscape = False
        if content:
            if content.startswith("# Netscape HTTP Cookie File") or \
               content.startswith("# HTTP Cookie File") or \
               "\t" in content:
                is_likely_netscape = True

        if not is_likely_netscape:
            print(f"Cookie Processor: Content of '{source_path}' does not appear to be a valid Netscape cookie file.")
            # Optionally, could try to parse more strictly here if needed
            return False

        # Overwrite/create the operational cookie file
        # Ensure the directory for operational_cookie_path exists if it's nested
        operational_dir = os.path.dirname(operational_cookie_path)
        if operational_dir and not os.path.exists(operational_dir):
            os.makedirs(operational_dir, exist_ok=True)
            print(f"Cookie Processor: Created directory for operational cookie file: {operational_dir}")

        with open(operational_cookie_path, 'w', encoding='utf-8') as f_dest:
            # Ensure a newline at the end, as some parsers are picky
            if not content.endswith('\n'):
                content += '\n'
            f_dest.write(content)

        print(f"Cookie Processor: Successfully processed '{source_path}' and updated '{operational_cookie_path}'.")
        return True

    except IOError as e:
        print(f"Cookie Processor: IOError while processing cookie files: {e}")
        return False
    except Exception as e:
        print(f"Cookie Processor: Unexpected error during cookie processing: {e}")
        return False

if __name__ == '__main__':
    # Example Usage (for testing this module directly)
    print("Testing cookie_processor.py...")

    # Create dummy source and operational paths for testing
    test_project_root = "_test_cookie_proc_temp"
    if not os.path.exists(test_project_root):
        os.makedirs(test_project_root)

    dummy_source_cookie_path = os.path.join(test_project_root, "new_cookies_test.txt")
    dummy_operational_cookie_path = os.path.join(test_project_root, "www.youtube.com_cookies.txt")

    # Test case 1: Source file doesn't exist
    print("\nTest Case 1: Source file does not exist")
    if os.path.exists(dummy_source_cookie_path): os.remove(dummy_source_cookie_path)
    if os.path.exists(dummy_operational_cookie_path): os.remove(dummy_operational_cookie_path)
    result = process_new_cookie_file(dummy_source_cookie_path, dummy_operational_cookie_path)
    print(f"Result: {result} (Expected: False)")
    assert not result
    assert not os.path.exists(dummy_operational_cookie_path)

    # Test case 2: Source file is empty
    print("\nTest Case 2: Source file is empty")
    with open(dummy_source_cookie_path, 'w') as f: f.write("")
    result = process_new_cookie_file(dummy_source_cookie_path, dummy_operational_cookie_path)
    print(f"Result: {result} (Expected: False)")
    assert not result # Empty file is not valid Netscape for this basic check
    if os.path.exists(dummy_operational_cookie_path): os.remove(dummy_operational_cookie_path)


    # Test case 3: Source file has invalid content (not Netscape-like)
    print("\nTest Case 3: Source file has invalid content")
    with open(dummy_source_cookie_path, 'w') as f: f.write("This is not a cookie file.")
    result = process_new_cookie_file(dummy_source_cookie_path, dummy_operational_cookie_path)
    print(f"Result: {result} (Expected: False)")
    assert not result
    if os.path.exists(dummy_operational_cookie_path): os.remove(dummy_operational_cookie_path)

    # Test case 4: Valid Netscape content
    print("\nTest Case 4: Valid Netscape content")
    valid_netscape_content = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t1782536059\tLOGIN_INFO\tSOME_LOGIN_INFO_VALUE\n"
        ".youtube.com\tTRUE\t/\tFALSE\t1785110970\tHSID\tSOME_HSID_VALUE\n"
    )
    with open(dummy_source_cookie_path, 'w', encoding='utf-8') as f: f.write(valid_netscape_content)
    result = process_new_cookie_file(dummy_source_cookie_path, dummy_operational_cookie_path)
    print(f"Result: {result} (Expected: True)")
    assert result
    assert os.path.exists(dummy_operational_cookie_path)
    with open(dummy_operational_cookie_path, 'r', encoding='utf-8') as f_op:
        op_content = f_op.read()
    # Check if content matches (ensure newline at end)
    assert op_content.strip() == valid_netscape_content.strip()
    print(f"Operational file content:\n{op_content}")


    # Test case 5: Valid Netscape content without header, but with tabs
    print("\nTest Case 5: Valid Netscape content without header, with tabs")
    valid_netscape_content_no_header = (
        ".youtube.com\tTRUE\t/\tTRUE\t1782536059\tLOGIN_INFO\tANOTHER_LOGIN_INFO\n"
    )
    with open(dummy_source_cookie_path, 'w', encoding='utf-8') as f: f.write(valid_netscape_content_no_header)
    result = process_new_cookie_file(dummy_source_cookie_path, dummy_operational_cookie_path)
    print(f"Result: {result} (Expected: True)")
    assert result
    assert os.path.exists(dummy_operational_cookie_path)
    with open(dummy_operational_cookie_path, 'r', encoding='utf-8') as f_op:
        op_content = f_op.read()
    assert op_content.strip() == valid_netscape_content_no_header.strip()
    print(f"Operational file content (no header test):\n{op_content}")


    print("\nCleaning up test files...")
    if os.path.exists(dummy_source_cookie_path): os.remove(dummy_source_cookie_path)
    if os.path.exists(dummy_operational_cookie_path): os.remove(dummy_operational_cookie_path)
    if os.path.exists(test_project_root): os.rmdir(test_project_root)
    print("Cookie processor tests complete.")
