"""
extractor.py
Playwright-based Azure DevOps CSV exporter.
Supports both Azure DevOps cloud (login.microsoftonline.com)
and on-premise Azure DevOps Server (forms-based login on the server itself).
"""

import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _is_login_page(page) -> bool:
    """Detect any login/authentication page."""
    url = page.url.lower()
    login_domains = ["login.microsoftonline.com", "login.live.com", "login.windows.net"]
    if any(d in url for d in login_domains):
        return True
    # On-prem: login form appears on the server itself
    has_email_input = page.query_selector("input[type='email'], input[name='UserName'], input[name='username']")
    has_password_input = page.query_selector("input[type='password']")
    return bool(has_email_input and has_password_input) or bool(has_password_input)


def _login_cloud(page, username: str, password: str):
    """Handle Microsoft cloud (AAD) login flow."""
    page.wait_for_selector("input[type='email']", timeout=15000)
    page.fill("input[type='email']", username)
    page.click("input[type='submit']")

    page.wait_for_selector("input[type='password']", timeout=15000)
    page.fill("input[type='password']", password)
    page.click("input[type='submit']")

    # Handle "Stay signed in?" prompt
    try:
        page.wait_for_selector("#idBtn_Back, #idSIButton9", timeout=8000)
        no_btn = page.query_selector("#idBtn_Back")
        if no_btn:
            no_btn.click()
        else:
            page.click("#idSIButton9")
    except PlaywrightTimeoutError:
        pass


def _login_onprem(page, username: str, password: str):
    """Handle on-premise Azure DevOps Server forms-based login."""
    # Try common on-prem field names
    username_selectors = [
        "input[name='UserName']",
        "input[name='username']",
        "input[id='UserName']",
        "input[type='text']",
        "input[type='email']",
    ]
    password_selectors = [
        "input[name='Password']",
        "input[name='password']",
        "input[id='Password']",
        "input[type='password']",
    ]
    submit_selectors = [
        "input[type='submit']",
        "button[type='submit']",
        "input[id='submitButton']",
    ]

    # Fill username
    for sel in username_selectors:
        el = page.query_selector(sel)
        if el:
            el.fill(username)
            break

    # Fill password
    for sel in password_selectors:
        el = page.query_selector(sel)
        if el:
            el.fill(password)
            break

    # Submit
    for sel in submit_selectors:
        el = page.query_selector(sel)
        if el:
            el.click()
            break


def _do_login(page, username: str, password: str):
    """Detect login type and authenticate."""
    url = page.url.lower()
    cloud_domains = ["login.microsoftonline.com", "login.live.com", "login.windows.net"]

    if any(d in url for d in cloud_domains):
        print("  Detected: Microsoft cloud login")
        _login_cloud(page, username, password)
    else:
        print("  Detected: On-premise / forms-based login")
        _login_onprem(page, username, password)


def _export_query_to_csv(page, query_url: str, download_dir: Path, index: int) -> Path | None:
    """
    Navigate to a query URL and trigger the CSV export.
    Returns the path of the downloaded file, or None on failure.
    """
    # Normalise URL: query-edit -> query (view mode shows results + export button)
    view_url = query_url.replace("/_queries/query-edit/", "/_queries/query/")

    print(f"  Navigating to query {index + 1}: {view_url}")
    try:
        page.goto(view_url, wait_until="networkidle", timeout=60000)
    except PlaywrightTimeoutError:
        print(f"  [warn] Page load timed out for query {index + 1}, trying to continue...")

    # Wait for query results grid
    try:
        page.wait_for_selector(
            ".query-results-grid, .wit-grid-row, [data-is-scrollable], .ms-DetailsList",
            timeout=20000,
        )
    except PlaywrightTimeoutError:
        print(f"  [warn] Query results grid not detected for query {index + 1}")

    # Trigger CSV export
    try:
        with page.expect_download(timeout=30000) as download_info:
            # Try "..." More commands menu first
            more_btn = page.query_selector(
                "button[aria-label='More commands'], "
                "button[aria-label='More actions'], "
                "button[title='More commands'], "
                "button[title='More actions']"
            )
            if more_btn:
                more_btn.click()
                time.sleep(0.5)
                export_item = page.query_selector(
                    "li[data-value='exportToCsv'], "
                    "button:has-text('Export to CSV'), "
                    "span:has-text('Export to CSV'), "
                    "[role='menuitem']:has-text('Export to CSV')"
                )
                if export_item:
                    export_item.click()
                else:
                    raise ValueError("Export to CSV menu item not found after opening More menu")
            else:
                # Direct export button fallback
                page.click(
                    "button:has-text('Export to CSV'), "
                    "[aria-label='Export to CSV'], "
                    "[title='Export to CSV']"
                )

        download = download_info.value
        dest = download_dir / f"query_{index + 1:02d}_{download.suggested_filename}"
        download.save_as(str(dest))
        print(f"  Downloaded: {dest.name}")
        return dest

    except Exception as e:
        print(f"  [error] Could not trigger export for query {index + 1}: {e}")
        return None


def download_all_csvs(
    query_links: list[str],
    username: str,
    password: str,
    download_dir: str = "downloads",
    headless: bool = True,
) -> list[Path]:
    """
    Log in to Azure DevOps and download CSV exports for all query links.
    Returns list of downloaded file paths.
    """
    out_dir = Path(download_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            accept_downloads=True,
            http_credentials={"username": username, "password": password},
        )
        page = context.new_page()

        # Navigate to first query URL to trigger auth
        print("Connecting to Azure DevOps...")
        first_url = query_links[0].replace("/_queries/query-edit/", "/_queries/query/")
        page.goto(first_url, wait_until="networkidle", timeout=60000)

        # Login if a login page is detected
        if _is_login_page(page):
            print("Login page detected — authenticating...")
            _do_login(page, username, password)

            # Wait for redirect back to ADO
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
                # Check if still on login page (wrong credentials)
                if _is_login_page(page):
                    print("[error] Still on login page after submitting — check credentials in .env")
                    browser.close()
                    return []
            except PlaywrightTimeoutError:
                print("[warn] Timeout waiting after login — continuing anyway...")

            print("Login successful.")
        else:
            print("No login page detected — already authenticated or Windows SSO active.")

        # Export each query
        for i, url in enumerate(query_links):
            path = _export_query_to_csv(page, url, out_dir, i)
            if path:
                downloaded.append(path)

        browser.close()

    print(f"\nDownloaded {len(downloaded)}/{len(query_links)} CSV files.")
    return downloaded
