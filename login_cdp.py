#!/usr/bin/env python3
"""
Upwork Auto Login - Real Chrome + CDP Edition
==============================================
Uses YOUR real Chrome browser via Chrome DevTools Protocol.
Cloudflare cannot detect this because it's a real Chrome, not Playwright's Chromium.

Workflow:
  1. Launch real Chrome with --remote-debugging-port
  2. Connect Playwright to it via CDP
  3. Automate login using real Chrome (bypasses Cloudflare)
  4. Save session cookies for future use

Usage:
    python3 login_cdp.py              # Headless-like (Chrome runs but you don't touch it)
    python3 login_cdp.py --wait-captcha 60   # Wait 60s for manual captcha solve
"""

import os
import sys
import time
import random
import subprocess
import argparse
import logging
import signal
import json
import asyncio
from pathlib import Path

# ─── Setup logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('upwork_login')


# ─── Load .env ───────────────────────────────────────────────────
def load_env(env_path=None):
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
                os.environ[key.strip()] = value.strip().strip("'\"")
    log.info(f"✅ Loaded credentials from {env_path}")


# ─── Human-like helpers ─────────────────────────────────────────
async def human_delay(min_s=0.5, max_s=1.5):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def human_type(page, selector, text):
    """Type text character by character with human-like speed."""
    await page.click(selector)
    await human_delay(0.3, 0.6)
    await page.fill(selector, '')
    await human_delay(0.2, 0.4)
    for char in text:
        await page.type(selector, char, delay=random.randint(50, 130))
    await human_delay(0.3, 0.8)


# ─── Chrome launcher ────────────────────────────────────────────
def get_chrome_path():
    paths = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        os.path.expanduser('~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def launch_real_chrome(debug_port=9222, profile_dir=None):
    """Launch real Chrome with remote debugging enabled."""
    chrome_path = get_chrome_path()
    if not chrome_path:
        log.error("❌ Google Chrome not found!")
        sys.exit(1)

    if profile_dir is None:
        profile_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'chrome_cdp_profile'
        )
    os.makedirs(profile_dir, exist_ok=True)

    args = [
        chrome_path,
        f'--remote-debugging-port={debug_port}',
        f'--user-data-dir={profile_dir}',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-infobars',
        '--window-size=1920,1080',
        '--window-position=0,0',
        'about:blank',
    ]

    log.info(f"🚀 Launching real Chrome (debug port: {debug_port})...")
    log.info(f"📁 Profile: {profile_dir}")

    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)  # Wait for Chrome to start

    if process.poll() is not None:
        log.error("❌ Chrome failed to start!")
        sys.exit(1)

    log.info("✅ Chrome launched successfully")
    return process


# ─── Wait for Cloudflare ────────────────────────────────────────
async def wait_for_cloudflare(page, timeout=30):
    """Wait for Cloudflare challenge to be solved (manually or auto)."""
    log.info(f"🛡️  Checking for Cloudflare challenge (timeout: {timeout}s)...")

    start = time.time()
    while time.time() - start < timeout:
        # Check if we're past Cloudflare
        content = await page.content()
        if 'Verify you are human' in content or 'cf-turnstile' in content:
            remaining = int(timeout - (time.time() - start))
            log.info(f"⏳ Cloudflare challenge detected. Please click 'Verify' in Chrome. ({remaining}s left)")
            await asyncio.sleep(3)
        else:
            log.info("✅ Cloudflare challenge passed!")
            return True

    log.warning("⚠️  Cloudflare timeout - may need more time")
    return False


# ─── Find input field with multiple strategies ──────────────────
async def find_input(page, selectors, name, timeout=15):
    """Try multiple selectors to find an input field."""
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout * 1000 // len(selectors))
            if el:
                log.info(f"✅ Found {name} field: {sel}")
                return sel
        except Exception:
            continue
    return None


# ─── Main login flow ────────────────────────────────────────────
async def login_upwork(email, password, debug_port=9222, captcha_wait=45):
    from playwright.async_api import async_playwright

    log.info("=" * 55)
    log.info("  🔐 UPWORK LOGIN - Real Chrome + CDP Mode")
    log.info("=" * 55)

    screenshot_dir = os.path.dirname(os.path.abspath(__file__))

    async with async_playwright() as p:
        # Connect to the real Chrome via CDP
        log.info(f"🔗 Connecting to Chrome on port {debug_port}...")
        try:
            browser = await p.chromium.connect_over_cdp(f'http://localhost:{debug_port}')
        except Exception as e:
            log.error(f"❌ Failed to connect to Chrome: {e}")
            log.error("   Make sure Chrome is running with --remote-debugging-port")
            return False

        log.info("✅ Connected to Chrome via CDP")

        # Get default context and create new page
        context = browser.contexts[0]
        page = await context.new_page()

        # ─── Step 1: Navigate to login page ─────────────────
        log.info("🌐 Navigating to Upwork login page...")
        await page.goto(
            'https://www.upwork.com/ab/account-security/login',
            wait_until='domcontentloaded',
            timeout=60000
        )
        await human_delay(2.0, 3.0)

        current_url = page.url
        log.info(f"📍 Current URL: {current_url}")

        # Check if already logged in
        if '/login' not in current_url and '/account-security' not in current_url:
            log.info("✅ 🎉 Already logged in!")
            await browser.close()
            return True

        # ─── Step 2: Handle Cloudflare if present ────────────
        await wait_for_cloudflare(page, timeout=captcha_wait)
        await human_delay(1.0, 2.0)

        # Reload URL check after Cloudflare
        current_url = page.url
        log.info(f"📍 URL after Cloudflare: {current_url}")

        # ─── Step 3: Enter email ─────────────────────────────
        log.info("📧 Looking for email field...")

        email_selectors = [
            '#login_username',
            'input[name="login[username]"]',
            'input[type="email"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="username" i]',
            'input[type="text"]',
        ]

        email_sel = await find_input(page, email_selectors, "email", timeout=20)

        if not email_sel:
            log.error("❌ Could not find email field!")
            await page.screenshot(path=os.path.join(screenshot_dir, 'debug_no_email.png'))
            await browser.close()
            return False

        email_display = f"{email[:3]}***{email[email.index('@'):]}"
        log.info(f"📧 Typing email: {email_display}")
        await human_type(page, email_sel, email)
        await human_delay(0.5, 1.0)

        # ─── Step 4: Submit email ────────────────────────────
        log.info("➡️  Submitting email...")
        submit_selectors = ['#login_password_continue', 'button[type="submit"]', 'button:has-text("Continue")']
        for sel in submit_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    log.info(f"   Clicked: {sel}")
                    break
            except Exception:
                continue
        else:
            await page.press(email_sel, 'Enter')

        await human_delay(3.0, 5.0)

        # ─── Step 5: Handle Cloudflare again if needed ───────
        content = await page.content()
        if 'Verify you are human' in content or 'cf-turnstile' in content:
            log.info("🛡️  Second Cloudflare challenge detected...")
            await wait_for_cloudflare(page, timeout=captcha_wait)
            await human_delay(2.0, 3.0)

        # ─── Step 6: Enter password ──────────────────────────
        log.info("🔑 Waiting for password field...")

        password_selectors = [
            '#login_password',
            'input[name="login[password]"]',
            'input[type="password"]',
            'input[placeholder*="password" i]',
        ]

        password_sel = await find_input(page, password_selectors, "password", timeout=20)

        if not password_sel:
            log.error("❌ Could not find password field!")
            await page.screenshot(path=os.path.join(screenshot_dir, 'debug_no_password.png'))
            log.info("📸 Screenshot saved for debugging")
            await browser.close()
            return False

        log.info("🔑 Typing password...")
        await human_type(page, password_sel, password)
        await human_delay(0.5, 1.0)

        # ─── Step 7: Submit login ────────────────────────────
        log.info("➡️  Submitting login...")
        login_selectors = ['#login_control_continue', 'button[type="submit"]', 'button:has-text("Log in")']
        for sel in login_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    log.info(f"   Clicked: {sel}")
                    break
            except Exception:
                continue
        else:
            await page.press(password_sel, 'Enter')

        # ─── Step 8: Handle Cloudflare one more time ─────────
        await human_delay(3.0, 5.0)
        content = await page.content()
        if 'Verify you are human' in content or 'cf-turnstile' in content:
            log.info("🛡️  Post-login Cloudflare challenge...")
            await wait_for_cloudflare(page, timeout=captcha_wait)

        # ─── Step 9: Wait for result ─────────────────────────
        log.info("⏳ Waiting for login result (up to 60s)...")

        try:
            await page.wait_for_url(
                lambda url: 'upwork.com' in url and '/login' not in url and '/account-security' not in url,
                timeout=60000
            )
            final_url = page.url
            log.info(f"📍 Final URL: {final_url}")
            log.info("✅ 🎉 LOGIN SUCCESSFUL!")

            # Save cookies
            cookies = await context.cookies()
            cookie_path = os.path.join(screenshot_dir, 'upwork_cookies.json')
            with open(cookie_path, 'w') as f:
                json.dump(cookies, f, indent=2)
            log.info(f"🍪 Cookies saved: {cookie_path}")

            await browser.close()
            return True

        except Exception as e:
            final_url = page.url
            log.warning(f"📍 Current URL: {final_url}")

            await page.screenshot(path=os.path.join(screenshot_dir, 'debug_final.png'))
            log.info("📸 Debug screenshot saved")

            if 'account-security' in final_url:
                log.warning("⚠️  May need 2FA or security verification.")
                log.warning("   Check the Chrome window and complete manually.")
                log.warning("   Waiting 60s for manual intervention...")
                await asyncio.sleep(60)
                final_url = page.url
                if '/login' not in final_url and '/account-security' not in final_url:
                    log.info("✅ 🎉 LOGIN SUCCESSFUL (after manual step)!")
                    cookies = await context.cookies()
                    cookie_path = os.path.join(screenshot_dir, 'upwork_cookies.json')
                    with open(cookie_path, 'w') as f:
                        json.dump(cookies, f, indent=2)
                    await browser.close()
                    return True

            await browser.close()
            return False


# ─── Entry point ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='🚀 Upwork Login - Real Chrome + CDP (Anti-Detection)'
    )
    parser.add_argument('--port', type=int, default=9222, help='Chrome debug port (default: 9222)')
    parser.add_argument('--wait-captcha', type=int, default=45, help='Seconds to wait for captcha (default: 45)')
    parser.add_argument('--env', default=None, help='Path to .env file')
    parser.add_argument('--profile', default=None, help='Chrome profile directory')

    args = parser.parse_args()

    load_env(args.env)
    email = os.environ.get('UPWORK_EMAIL')
    password = os.environ.get('UPWORK_PASSWORD')
    if not email or not password:
        log.error("❌ Missing UPWORK_EMAIL or UPWORK_PASSWORD in .env!")
        sys.exit(1)

    # Launch real Chrome
    chrome_proc = launch_real_chrome(debug_port=args.port, profile_dir=args.profile)

    try:
        success = asyncio.run(login_upwork(email, password, debug_port=args.port, captcha_wait=args.wait_captcha))
    except KeyboardInterrupt:
        log.info("\n🛑 Cancelled by user.")
        success = False
    finally:
        # Don't kill Chrome — let user keep using it
        log.info("=" * 55)
        if success:
            log.info("  ✅ Login completed! Chrome remains open.")
        else:
            log.info("  ⚠️  Check Chrome window for manual steps.")
        log.info("=" * 55)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
