#!/usr/bin/env python3
"""
Upwork Auto Login - PyAutoGUI Edition
======================================
Opens a REAL Chrome browser (no automation flags) and uses OS-level
keyboard/mouse simulation via PyAutoGUI to fill login credentials.

This approach avoids antibot detection because:
1. Chrome is launched as a normal process (no --enable-automation)
2. No WebDriver/Playwright/Selenium fingerprints
3. Input is simulated at the OS level (indistinguishable from real user)
4. Random human-like delays between actions

Usage:
    python3 login_upwork.py                    # Login with email/password
    python3 login_upwork.py --google           # Login via Google OAuth
    python3 login_upwork.py --session myprofile # Use a named Chrome profile
"""

import subprocess
import time
import random
import os
import sys
import argparse
import logging
from pathlib import Path

# ─── Disable PyAutoGUI fail-safe ─────────────────────────────────
import pyautogui
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1

# ─── Setup logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('upwork_login')

# ─── Load .env ───────────────────────────────────────────────────
def load_env(env_path=None):
    """Load .env file manually (no dependency needed)."""
    if env_path is None:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    
    if not os.path.exists(env_path):
        log.error(f"❌ .env file not found at: {env_path}")
        sys.exit(1)
    
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip().strip("'\"")
                os.environ[key] = value
    
    log.info(f"✅ Loaded credentials from {env_path}")


# ─── Human-like delays ──────────────────────────────────────────
def human_delay(min_s=0.5, max_s=1.5):
    """Random delay to mimic human behavior."""
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)

def human_type(text, interval_range=(0.04, 0.12)):
    """Type text character by character with human-like speed variation."""
    import pyautogui
    for char in text:
        pyautogui.press(char) if len(char) > 1 else pyautogui.typewrite(char, interval=0)
        time.sleep(random.uniform(*interval_range))


# ─── Chrome launcher ────────────────────────────────────────────
def get_chrome_path():
    """Find Chrome executable on macOS."""
    paths = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        os.path.expanduser('~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    
    # Try homebrew Chrome
    try:
        result = subprocess.run(['which', 'google-chrome'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    
    return None


def launch_chrome(url, profile_dir=None):
    """Launch a real Chrome browser with no automation flags."""
    chrome_path = get_chrome_path()
    if not chrome_path:
        log.error("❌ Google Chrome not found!")
        sys.exit(1)
    
    args = [chrome_path]
    
    if profile_dir:
        profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), profile_dir)
        os.makedirs(profile_path, exist_ok=True)
        args.extend([f'--user-data-dir={profile_path}'])
        log.info(f"📁 Using Chrome profile: {profile_path}")
    
    args.extend([
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-infobars',
        '--start-maximized',
        url
    ])
    
    log.info(f"🚀 Launching Chrome → {url}")
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process


# ─── AppleScript helpers (macOS) ─────────────────────────────────
def run_applescript(script):
    """Run an AppleScript command."""
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception as e:
        log.warning(f"AppleScript error: {e}")
        return None


def bring_chrome_to_front():
    """Bring Chrome to the foreground."""
    run_applescript('tell application "Google Chrome" to activate')
    time.sleep(0.5)


def get_chrome_url():
    """Get the current URL from Chrome's address bar."""
    return run_applescript(
        'tell application "Google Chrome" to return URL of active tab of front window'
    )


def wait_for_url_contains(substring, timeout=120, check_interval=2):
    """Wait until Chrome's URL contains a specific substring."""
    start = time.time()
    while time.time() - start < timeout:
        url = get_chrome_url()
        if url and substring in url:
            return True
        time.sleep(check_interval)
    return False


# ─── Login flows ─────────────────────────────────────────────────
def login_with_email(email, password):
    """
    Login to Upwork using email/password.
    
    Flow:
    1. Open Upwork login page
    2. Wait for page to load
    3. Tab to email field → type email
    4. Click "Continue with Email" → press Enter
    5. Wait for password field
    6. Type password → press Enter
    """
    import pyautogui
    
    log.info("=" * 55)
    log.info("  🔐 UPWORK LOGIN - PyAutoGUI Mode (Anti-Detection)")
    log.info("=" * 55)
    
    # Step 1: Wait for login page to fully load
    log.info("⏳ Waiting for login page to load...")
    time.sleep(6)
    
    # Step 2: Bring Chrome to front
    bring_chrome_to_front()
    human_delay(0.5, 1.0)
    
    # Step 3: Click in the center of the page to ensure focus
    screen_w, screen_h = pyautogui.size()
    pyautogui.click(screen_w // 2, screen_h // 2)
    human_delay(0.8, 1.2)
    
    # Step 4: Use Tab key to navigate to the email/username field
    # On Upwork login page, the username field is typically the first input
    log.info("📧 Navigating to email field...")
    
    # Press Tab several times to reach the input field
    # First, let's try clicking directly — Upwork's login page has a centered form
    # We'll use keyboard shortcut to focus the first input
    pyautogui.hotkey('command', 'l')  # Focus address bar first
    human_delay(0.3, 0.5)
    pyautogui.press('tab')  # Tab into page content
    human_delay(0.3, 0.5)
    
    # Tab to find the username/email input (usually 2-4 tabs from top)
    for i in range(6):
        pyautogui.press('tab')
        human_delay(0.15, 0.3)
    
    # Step 5: Clear any existing text and type email
    pyautogui.hotkey('command', 'a')  # Select all in field
    human_delay(0.2, 0.4)
    
    log.info(f"📧 Typing email: {email[:3]}***{email[email.index('@'):]}")
    human_type(email)
    human_delay(0.5, 1.0)
    
    # Step 6: Press Enter or Tab to "Continue with Email"
    log.info("➡️  Submitting email (pressing Enter)...")
    pyautogui.press('enter')
    
    # Step 7: Wait for password field to appear
    log.info("⏳ Waiting for password field...")
    time.sleep(4)
    human_delay(1.0, 2.0)
    
    # Step 8: The password field should be auto-focused, but let's make sure
    # Click in center area again
    pyautogui.click(screen_w // 2, screen_h // 2)
    human_delay(0.5, 0.8)
    
    # Tab to password field
    pyautogui.hotkey('command', 'l')
    human_delay(0.3, 0.5)
    pyautogui.press('tab')
    human_delay(0.3, 0.5)
    
    for i in range(6):
        pyautogui.press('tab')
        human_delay(0.15, 0.3)
    
    pyautogui.hotkey('command', 'a')
    human_delay(0.2, 0.3)
    
    log.info("🔑 Typing password...")
    human_type(password)
    human_delay(0.5, 1.0)
    
    # Step 9: Submit login
    log.info("➡️  Submitting login (pressing Enter)...")
    pyautogui.press('enter')
    
    # Step 10: Wait for dashboard
    log.info("⏳ Waiting for Upwork dashboard (up to 2 minutes)...")
    if wait_for_url_contains('/nx/find-work', timeout=120):
        log.info("✅ 🎉 LOGIN SUCCESSFUL! Dashboard detected.")
    elif wait_for_url_contains('/feed', timeout=10):
        log.info("✅ 🎉 LOGIN SUCCESSFUL! Feed page detected.")
    elif wait_for_url_contains('/ab/account-security', timeout=5):
        log.info("⚠️  Still on login/security page. May need 2FA or manual intervention.")
        handle_2fa()
    else:
        current_url = get_chrome_url()
        log.info(f"📍 Current URL: {current_url}")
        if current_url and 'upwork.com' in current_url and 'login' not in current_url:
            log.info("✅ Appears to be logged in!")
        else:
            log.warning("⚠️  Could not confirm login. Please check the browser.")


def login_with_google(email, password):
    """
    Login to Upwork via Google OAuth.
    
    Flow:
    1. Open Upwork login page  
    2. Tab to "Continue with Google" button → click it
    3. Google popup appears → type email → Enter
    4. Type password → Enter
    5. Handle 2FA if needed
    """
    import pyautogui
    
    log.info("=" * 55)
    log.info("  🔐 UPWORK LOGIN via GOOGLE - PyAutoGUI Mode")
    log.info("=" * 55)
    
    # Wait for login page
    log.info("⏳ Waiting for login page to load...")
    time.sleep(6)
    
    bring_chrome_to_front()
    human_delay(0.5, 1.0)
    
    # Click page center
    screen_w, screen_h = pyautogui.size()
    pyautogui.click(screen_w // 2, screen_h // 2)
    human_delay(0.8, 1.2)
    
    # Tab to the "Continue with Google" button
    # On Upwork's login page, Google button is typically before the email field
    log.info("🔍 Looking for 'Continue with Google' button...")
    pyautogui.hotkey('command', 'l')
    human_delay(0.3, 0.5)
    pyautogui.press('tab')
    human_delay(0.3, 0.5)
    
    # The Google button is usually one of the first interactive elements
    for i in range(4):
        pyautogui.press('tab')
        human_delay(0.2, 0.4)
    
    log.info("👆 Pressing Enter on Google button...")
    pyautogui.press('enter')
    
    # Wait for Google popup
    log.info("⏳ Waiting for Google login popup...")
    time.sleep(5)
    
    # The Google popup should now be in focus
    # If not, try switching to it
    human_delay(1.0, 2.0)
    
    # Type Google email
    log.info(f"📧 Typing Google email...")
    human_type(email)
    human_delay(0.5, 1.0)
    
    pyautogui.press('enter')
    log.info("⏳ Waiting for Google password field...")
    time.sleep(4)
    human_delay(1.0, 2.0)
    
    # Type Google password
    log.info("🔑 Typing Google password...")
    human_type(password)
    human_delay(0.5, 1.0)
    
    pyautogui.press('enter')
    
    # Handle potential 2FA
    log.info("⏳ Checking for 2FA...")
    time.sleep(5)
    handle_2fa()
    
    # Wait for Upwork dashboard
    log.info("⏳ Waiting for Upwork dashboard...")
    time.sleep(10)
    
    current_url = get_chrome_url()
    log.info(f"📍 Current URL: {current_url}")
    
    if current_url and 'login' not in current_url and 'upwork.com' in current_url:
        log.info("✅ 🎉 LOGIN SUCCESSFUL!")
    else:
        log.warning("⚠️  Please check browser manually.")


def handle_2fa():
    """Handle 2FA by asking user for code in terminal."""
    try:
        code = input("\n🔐 2FA CODE REQUIRED! Enter the code from your authenticator app: ").strip()
        if code:
            import pyautogui
            log.info("🤖 Typing 2FA code...")
            human_type(code)
            human_delay(0.3, 0.5)
            pyautogui.press('enter')
            log.info("✅ 2FA code submitted. Waiting...")
            time.sleep(5)
    except EOFError:
        log.info("⏩ No 2FA input provided, skipping.")


# ─── Main ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='🚀 Upwork Auto Login - PyAutoGUI (Anti-Detection)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 login_upwork.py                     # Email/password login
  python3 login_upwork.py --google            # Google OAuth login  
  python3 login_upwork.py --session myprofile # Named Chrome profile
  python3 login_upwork.py --env /path/to/.env # Custom .env path
        """
    )
    parser.add_argument('--google', action='store_true', help='Login via Google OAuth instead of email/password')
    parser.add_argument('--session', default='upwork_pyautogui_session', help='Chrome profile directory name (default: upwork_pyautogui_session)')
    parser.add_argument('--env', default=None, help='Path to .env file')
    parser.add_argument('--no-profile', action='store_true', help='Use default Chrome profile (no dedicated profile)')
    parser.add_argument('--delay', type=float, default=6.0, help='Initial page load delay in seconds (default: 6)')
    
    args = parser.parse_args()
    
    # Load credentials
    load_env(args.env)
    
    email = os.environ.get('UPWORK_EMAIL')
    password = os.environ.get('UPWORK_PASSWORD')
    google_email = os.environ.get('GOOGLE_EMAIL', email)
    google_password = os.environ.get('GOOGLE_PASSWORD', password)
    
    if not email or not password:
        log.error("❌ Missing UPWORK_EMAIL or UPWORK_PASSWORD in .env file!")
        sys.exit(1)
    
    # Launch Chrome
    profile = None if args.no_profile else args.session
    chrome_process = launch_chrome(
        'https://www.upwork.com/ab/account-security/login',
        profile_dir=profile
    )
    
    try:
        if args.google:
            login_with_google(google_email, google_password)
        else:
            login_with_email(email, password)
    except KeyboardInterrupt:
        log.info("\n🛑 Login cancelled by user.")
    except Exception as e:
        log.error(f"❌ Error: {e}")
        raise
    finally:
        log.info("=" * 55)
        log.info("  🏁 Login script finished.")
        log.info("  Chrome remains open for your use.")
        log.info("=" * 55)


if __name__ == '__main__':
    main()
