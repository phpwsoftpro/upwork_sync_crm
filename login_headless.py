#!/usr/bin/env python3
"""
Upwork Auto Login - Headless Playwright Edition
=================================================
Runs in HEADLESS mode so you can keep using your mouse/keyboard.
Uses playwright-stealth to avoid bot detection.

Usage:
    python3 login_headless.py
    python3 login_headless.py --headed    # Show browser for debugging
"""

import os
import sys
import time
import random
import argparse
import logging
import json
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
    """Load .env file manually."""
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


# ─── Human-like helpers ─────────────────────────────────────────
async def human_delay(min_s=0.5, max_s=1.5):
    """Random delay to mimic human behavior."""
    import asyncio
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


async def human_type(page, selector, text):
    """Type text character by character with human-like speed."""
    await page.click(selector)
    await human_delay(0.3, 0.6)
    
    # Clear existing content
    await page.fill(selector, '')
    await human_delay(0.2, 0.4)
    
    # Type character by character
    for char in text:
        await page.type(selector, char, delay=random.randint(40, 120))
    
    await human_delay(0.3, 0.8)


# ─── Apply stealth settings ─────────────────────────────────────
async def apply_stealth(page):
    """Apply anti-detection stealth scripts."""
    stealth_js = """
    // Override navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    
    // Override chrome runtime
    window.chrome = { runtime: {} };
    
    // Override permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
    
    // Override plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    
    // Override languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });
    
    // Override platform
    Object.defineProperty(navigator, 'platform', {
        get: () => 'MacIntel',
    });
    """
    await page.add_init_script(stealth_js)


# ─── Main login flow ────────────────────────────────────────────
async def login_upwork(email, password, headed=False):
    """Login to Upwork using Playwright."""
    from playwright.async_api import async_playwright
    
    log.info("=" * 55)
    log.info("  🔐 UPWORK LOGIN - Headless Playwright Mode")
    log.info("=" * 55)
    
    storage_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'upwork_session_storage.json'
    )
    
    async with async_playwright() as p:
        # Launch browser with anti-detection settings
        browser = await p.chromium.launch(
            headless=not headed,
            args=[
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--window-size=1920,1080',
            ]
        )
        
        # Create context with realistic settings
        context_args = {
            'viewport': {'width': 1920, 'height': 1080},
            'user_agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/131.0.0.0 Safari/537.36'
            ),
            'locale': 'en-US',
            'timezone_id': 'Asia/Ho_Chi_Minh',
        }
        
        # Load saved session if exists
        if os.path.exists(storage_path):
            log.info("📂 Loading saved session...")
            context_args['storage_state'] = storage_path
        
        context = await browser.new_context(**context_args)
        page = await context.new_page()
        
        # Apply stealth
        await apply_stealth(page)
        
        # ─── Step 1: Navigate to login page ─────────────────
        log.info("🌐 Navigating to Upwork login page...")
        await page.goto(
            'https://www.upwork.com/ab/account-security/login',
            wait_until='networkidle',
            timeout=60000
        )
        await human_delay(2.0, 3.0)
        
        current_url = page.url
        log.info(f"📍 Current URL: {current_url}")
        
        # Check if already logged in
        if '/login' not in current_url and '/account-security' not in current_url:
            log.info("✅ 🎉 Already logged in from saved session!")
            await context.storage_state(path=storage_path)
            await browser.close()
            return True
        
        # ─── Step 2: Enter email ─────────────────────────────
        log.info("📧 Looking for email field...")
        
        # Wait for the login form
        try:
            email_selector = '#login_username'
            await page.wait_for_selector(email_selector, timeout=15000)
            log.info("📧 Found email field")
        except Exception:
            # Try alternative selectors
            for sel in ['input[name="login[username]"]', 'input[type="email"]', 'input[type="text"]']:
                try:
                    await page.wait_for_selector(sel, timeout=3000)
                    email_selector = sel
                    log.info(f"📧 Found email field with selector: {sel}")
                    break
                except Exception:
                    continue
            else:
                log.error("❌ Could not find email field!")
                # Take screenshot for debugging
                screenshot_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    'debug_screenshot.png'
                )
                await page.screenshot(path=screenshot_path)
                log.info(f"📸 Screenshot saved: {screenshot_path}")
                await browser.close()
                return False
        
        # Type email
        email_display = f"{email[:3]}***{email[email.index('@'):]}"
        log.info(f"📧 Typing email: {email_display}")
        await human_type(page, email_selector, email)
        await human_delay(0.5, 1.0)
        
        # ─── Step 3: Click Continue / Submit email ───────────
        log.info("➡️  Submitting email...")
        try:
            # Look for "Continue with Email" or submit button
            continue_btn = await page.query_selector('#login_password_continue')
            if continue_btn:
                await continue_btn.click()
            else:
                # Try pressing Enter
                await page.press(email_selector, 'Enter')
        except Exception as e:
            log.warning(f"Submit attempt: {e}")
            await page.press(email_selector, 'Enter')
        
        await human_delay(2.0, 4.0)
        
        # ─── Step 4: Enter password ──────────────────────────
        log.info("🔑 Waiting for password field...")
        
        try:
            password_selector = '#login_password'
            await page.wait_for_selector(password_selector, timeout=15000)
            log.info("🔑 Found password field")
        except Exception:
            for sel in ['input[name="login[password]"]', 'input[type="password"]']:
                try:
                    await page.wait_for_selector(sel, timeout=3000)
                    password_selector = sel
                    log.info(f"🔑 Found password field with selector: {sel}")
                    break
                except Exception:
                    continue
            else:
                log.error("❌ Could not find password field!")
                screenshot_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    'debug_password_screenshot.png'
                )
                await page.screenshot(path=screenshot_path)
                log.info(f"📸 Screenshot saved: {screenshot_path}")
                await browser.close()
                return False
        
        log.info("🔑 Typing password...")
        await human_type(page, password_selector, password)
        await human_delay(0.5, 1.0)
        
        # ─── Step 5: Submit login ────────────────────────────
        log.info("➡️  Submitting login...")
        try:
            login_btn = await page.query_selector('#login_control_continue')
            if login_btn:
                await login_btn.click()
            else:
                await page.press(password_selector, 'Enter')
        except Exception:
            await page.press(password_selector, 'Enter')
        
        # ─── Step 6: Wait for result ─────────────────────────
        log.info("⏳ Waiting for login result (up to 60s)...")
        
        try:
            await page.wait_for_url(
                lambda url: '/login' not in url and '/account-security' not in url,
                timeout=60000
            )
            final_url = page.url
            log.info(f"📍 Final URL: {final_url}")
            
            if 'upwork.com' in final_url:
                log.info("✅ 🎉 LOGIN SUCCESSFUL!")
                
                # Save session for next time
                await context.storage_state(path=storage_path)
                log.info(f"💾 Session saved to: {storage_path}")
                
                await browser.close()
                return True
        except Exception as e:
            final_url = page.url
            log.info(f"📍 Current URL after wait: {final_url}")
            
            # Check for 2FA
            if 'account-security' in final_url or 'verification' in final_url:
                log.warning("⚠️  2FA or security check required!")
                log.warning("   Please run with --headed flag to complete manually:")
                log.warning("   python3 login_headless.py --headed")
                
                screenshot_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    'debug_2fa_screenshot.png'
                )
                await page.screenshot(path=screenshot_path)
                log.info(f"📸 Screenshot saved: {screenshot_path}")
            else:
                log.warning(f"⚠️  Login may have failed: {e}")
                screenshot_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    'debug_final_screenshot.png'
                )
                await page.screenshot(path=screenshot_path)
                log.info(f"📸 Screenshot saved: {screenshot_path}")
        
        await browser.close()
        return False


# ─── Entry point ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='🚀 Upwork Auto Login - Headless Playwright Mode'
    )
    parser.add_argument('--headed', action='store_true',
                       help='Show browser window (for debugging/2FA)')
    parser.add_argument('--env', default=None,
                       help='Path to .env file')
    
    args = parser.parse_args()
    
    # Load credentials
    load_env(args.env)
    
    email = os.environ.get('UPWORK_EMAIL')
    password = os.environ.get('UPWORK_PASSWORD')
    
    if not email or not password:
        log.error("❌ Missing UPWORK_EMAIL or UPWORK_PASSWORD in .env file!")
        sys.exit(1)
    
    # Run async login
    import asyncio
    success = asyncio.run(login_upwork(email, password, headed=args.headed))
    
    if success:
        log.info("🏁 Login completed successfully!")
    else:
        log.warning("🏁 Login may need manual intervention. Try --headed mode.")
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
