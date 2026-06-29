#!/usr/bin/env python3
"""
Upwork Proposal Submitter — Chrome CDP Edition
================================================
Reads proposals from CRM (stage "Send Proposal with Client"),
submits them to Upwork via Chrome CDP, then updates CRM.

Usage:
    python3 submit_proposal.py              # Submit all pending proposals
    python3 submit_proposal.py --dry-run    # Preview only, no submit
    python3 submit_proposal.py --list       # List pending proposals

CRM Workflow:
    1. Job synced to CRM → "Pending" stage
    2. User writes cover letter in description (below --- separator)
    3. User adds tag "bid:25" for hourly rate
    4. User moves task to "Send Proposal with Client" stage
    5. This script submits the proposal to Upwork
    6. Task moves to "Done" stage
"""

import os
import sys
import re
import json
import time
import logging
import argparse
import subprocess
import ssl
import http.cookiejar
import urllib.request
import urllib.parse
from datetime import datetime

# ─── Setup ──────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('proposal_submit')

# Load .env
env_path = os.path.join(SCRIPT_DIR, '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v.strip().strip("'\"")

CRM_URL = os.environ.get('CRM_URL', 'https://crm.wsoftpro.com')
CRM_EMAIL = os.environ.get('CRM_EMAIL', 'trung@wsoftpro.com')
CRM_PASSWORD = os.environ.get('CRM_PASSWORD', '1')
PROJECT_ID = int(os.environ.get('CRM_PROJECT_ID', '74'))
PROPOSAL_STAGE_ID = 1894  # "Send Proposal with Client"
DONE_STAGE_ID = 1895       # "Done"
COOKIE_FILE = os.path.join(SCRIPT_DIR, 'upwork_cookies.json')


# ═══════════════════════════════════════════════════════════════
#  PART 1: CRM CLIENT
# ═══════════════════════════════════════════════════════════════

class OdooClient:
    def __init__(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=ctx)
        )
        self.ua = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        self.rpc_id = 0

    def login(self):
        req = urllib.request.Request(f'{CRM_URL}/web/login', headers={'User-Agent': self.ua})
        resp = self.opener.open(req, timeout=15)
        html = resp.read().decode()
        csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)
        data = urllib.parse.urlencode({
            'login': CRM_EMAIL, 'password': CRM_PASSWORD,
            'csrf_token': csrf, 'redirect': '/odoo?',
        }).encode()
        req2 = urllib.request.Request(f'{CRM_URL}/web/login', data=data, headers={
            'User-Agent': self.ua, 'Content-Type': 'application/x-www-form-urlencoded',
        })
        resp2 = self.opener.open(req2, timeout=15)
        if 'login' in resp2.url and 'redirect' in resp2.url:
            log.error("❌ CRM login failed!")
            return False
        return True

    def rpc(self, model, method, args=None, kwargs=None):
        self.rpc_id += 1
        payload = json.dumps({
            "jsonrpc": "2.0", "method": "call",
            "params": {"model": model, "method": method,
                       "args": args or [], "kwargs": kwargs or {}},
            "id": self.rpc_id,
        }).encode()
        req = urllib.request.Request(f'{CRM_URL}/web/dataset/call_kw', data=payload, headers={
            'User-Agent': self.ua, 'Content-Type': 'application/json',
        })
        resp = self.opener.open(req, timeout=30)
        result = json.loads(resp.read().decode())
        if 'error' in result:
            log.error(f"   RPC Error: {result['error'].get('message', '')[:100]}")
            return None
        return result.get('result')


def get_pending_proposals(crm):
    """Get tasks in 'Send Proposal with Client' stage."""
    tasks = crm.rpc('project.task', 'search_read',
        args=[[
            ['project_id', '=', PROJECT_ID],
            ['stage_id', '=', PROPOSAL_STAGE_ID],
        ]],
        kwargs={
            'fields': ['name', 'description', 'tag_ids'],
            'order': 'create_date asc',
        }
    )
    return tasks or []


def parse_proposal_data(task):
    """Extract ciphertext, cover letter, and bid from CRM task."""
    desc = task.get('description', '') or ''
    
    # 1. Extract ciphertext
    cipher_match = re.search(r'CIPHER:(~\w+)', desc)
    if not cipher_match:
        # Try from URL
        cipher_match = re.search(r'/jobs/details/(~\w+)', desc)
    if not cipher_match:
        cipher_match = re.search(r'data-ciphertext="(~\w+)"', desc)
    ciphertext = cipher_match.group(1) if cipher_match else None

    # 2. Extract cover letter (everything after PROPOSAL separator)
    cover_letter = ''
    proposal_match = re.search(
        r'(?:✍️\s*PROPOSAL|---PROPOSAL---|PROPOSAL\s*\(Write)',
        desc, re.IGNORECASE
    )
    if proposal_match:
        raw_after = desc[proposal_match.end():]
        # Strip HTML tags
        text = re.sub(r'<[^>]+>', '\n', raw_after)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        # Remove the placeholder instruction text
        text = re.sub(r'Write your cover letter here.*?stage\.?', '', text, flags=re.I).strip()
        cover_letter = text

    # 3. Extract bid from tags or description
    bid_rate = None
    # Check tag names  
    tag_ids = task.get('tag_ids', [])
    # tag_ids are just IDs, we need to resolve them
    # For now, also check description for BID: pattern
    bid_match = re.search(r'(?:bid|rate|price)[:\s]*\$?(\d+(?:\.\d+)?)', desc, re.I)
    if bid_match:
        bid_rate = float(bid_match.group(1))

    return {
        'ciphertext': ciphertext,
        'cover_letter': cover_letter,
        'bid_rate': bid_rate,
        'task_id': task['id'],
        'task_name': task['name'],
        'tag_ids': tag_ids,
    }


def resolve_bid_from_tags(crm, tag_ids):
    """Resolve tag IDs to find bid:XX tag."""
    if not tag_ids:
        return None
    tags = crm.rpc('project.tags', 'read', args=[tag_ids], kwargs={'fields': ['name']})
    if tags:
        for t in tags:
            m = re.match(r'bid[:\s]*\$?(\d+(?:\.\d+)?)', t['name'], re.I)
            if m:
                return float(m.group(1))
    return None


# ═══════════════════════════════════════════════════════════════
#  PART 2: CHROME CDP PROPOSAL SUBMITTER
# ═══════════════════════════════════════════════════════════════

class ChromeCDP:
    """Manages Chrome CDP connection for proposal submission."""
    
    def __init__(self, port=9234):
        self.port = port
        self.chrome_proc = None
        self.ws = None
        self._msg_id = 1

    def launch(self):
        """Launch Chrome off-screen with debug port."""
        chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        profile = os.path.join(SCRIPT_DIR, 'chrome_cdp_profile')

        # Kill any existing on this port
        try:
            subprocess.run(['pkill', '-f', f'--remote-debugging-port={self.port}'],
                           capture_output=True, timeout=3)
            time.sleep(1)
        except:
            pass

        self.chrome_proc = subprocess.Popen([
            chrome_path,
            f'--remote-debugging-port={self.port}',
            f'--user-data-dir={profile}',
            '--remote-allow-origins=*',
            '--window-position=10000,10000',  # Off-screen
            '--window-size=1280,900',
            '--disable-extensions',
            '--no-first-run',
            '--no-default-browser-check',
            'about:blank'
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(4)
        log.info(f"  🌐 Chrome launched (PID: {self.chrome_proc.pid})")

    def connect(self):
        """Connect to Chrome via WebSocket."""
        import websocket
        targets = json.loads(urllib.request.urlopen(
            f'http://127.0.0.1:{self.port}/json', timeout=5).read())
        ws_url = [t for t in targets if t.get('type') == 'page'][0]['webSocketDebuggerUrl']
        self.ws = websocket.create_connection(ws_url, timeout=30)
        log.info("  🔗 CDP connected")

    def cdp(self, method, params=None, timeout=15):
        """Send CDP command and wait for response."""
        cmd = {'id': self._msg_id, 'method': method}
        if params:
            cmd['params'] = params
        self.ws.send(json.dumps(cmd))
        cid = self._msg_id
        self._msg_id += 1
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.ws.settimeout(max(0.1, deadline - time.time()))
                r = json.loads(self.ws.recv())
                if r.get('id') == cid:
                    return r.get('result', {})
            except:
                continue
        return {}

    def load_cookies(self):
        """Load Upwork cookies into Chrome."""
        self.cdp('Network.enable')
        with open(COOKIE_FILE) as f:
            cookies = json.load(f)
        loaded = 0
        for c in cookies:
            try:
                self.cdp('Network.setCookie', {
                    'name': c['name'], 'value': c['value'],
                    'domain': c.get('domain', '.upwork.com'),
                    'path': c.get('path', '/'),
                }, timeout=2)
                loaded += 1
            except:
                pass
        log.info(f"  🍪 Loaded {loaded} cookies")

    def navigate(self, url, wait=5):
        """Navigate to URL and wait."""
        self.cdp('Page.enable')
        self.cdp('Page.navigate', {'url': url})
        time.sleep(wait)
        result = self.cdp('Runtime.evaluate', {
            'expression': 'window.location.href',
            'returnByValue': True
        })
        return result.get('result', {}).get('value', '')

    def evaluate(self, js, timeout=10):
        """Evaluate JavaScript in the page."""
        result = self.cdp('Runtime.evaluate', {
            'expression': js,
            'returnByValue': True,
            'awaitPromise': True,
        }, timeout=timeout)
        return result.get('result', {}).get('value')

    def close(self):
        """Close Chrome and WebSocket."""
        try:
            self.ws.close()
        except:
            pass
        try:
            self.chrome_proc.terminate()
            self.chrome_proc.wait(timeout=5)
        except:
            try:
                self.chrome_proc.kill()
            except:
                pass
        log.info("  🔒 Chrome closed")


def submit_proposal_via_cdp(chrome, ciphertext, cover_letter, bid_rate=None):
    """
    Submit a proposal on Upwork via Chrome CDP.
    Returns (success: bool, message: str)
    """
    apply_url = f'https://www.upwork.com/nx/proposals/job/{ciphertext}/apply/'
    log.info(f"  📝 Navigating to apply page...")
    
    current_url = chrome.navigate(apply_url, wait=6)
    log.info(f"  📍 URL: {current_url[:80]}")

    # Check if we're on the apply page
    if 'login' in current_url:
        return False, "Session expired — not logged in"
    
    if 'proposals' not in current_url and 'apply' not in current_url:
        return False, f"Unexpected page: {current_url}"

    # Check for "Already Applied" or other blockers
    page_text = chrome.evaluate('document.body.innerText.substring(0, 2000)') or ''
    if 'already submitted' in page_text.lower() or 'already applied' in page_text.lower():
        return False, "Already submitted a proposal for this job"
    
    if 'not enough connects' in page_text.lower():
        return False, "Not enough Upwork Connects"

    # Wait for form to fully load
    time.sleep(3)

    # Fill cover letter
    log.info(f"  ✍️  Filling cover letter ({len(cover_letter)} chars)...")
    escaped_letter = cover_letter.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace("'", "\\'").replace('"', '\\"')
    
    fill_result = chrome.evaluate(f'''
    (function() {{
        // Try multiple selectors for the cover letter field
        var selectors = [
            'textarea[data-test="coverLetter"]',
            'textarea[name="coverLetter"]',
            'textarea#cover-letter',
            'textarea.cover-letter',
            '[data-cy="coverLetter"] textarea',
            'textarea',
        ];
        var textarea = null;
        for (var i = 0; i < selectors.length; i++) {{
            var el = document.querySelector(selectors[i]);
            if (el && (el.offsetParent !== null || el.offsetHeight > 0)) {{
                textarea = el;
                break;
            }}
        }}
        if (!textarea) return "NO_TEXTAREA";
        
        // Set value using React-compatible method
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, "value"
        ).set;
        nativeInputValueSetter.call(textarea, "{escaped_letter}");
        textarea.dispatchEvent(new Event("input", {{ bubbles: true }}));
        textarea.dispatchEvent(new Event("change", {{ bubbles: true }}));
        return "OK:" + textarea.value.length;
    }})()
    ''')
    log.info(f"  📋 Cover letter fill result: {fill_result}")
    
    if fill_result == 'NO_TEXTAREA':
        return False, "Could not find cover letter textarea"

    # Fill bid rate if provided
    if bid_rate:
        log.info(f"  💰 Setting bid rate: ${bid_rate}/hr...")
        chrome.evaluate(f'''
        (function() {{
            var inputs = document.querySelectorAll('input[type="text"], input[type="number"]');
            for (var i = 0; i < inputs.length; i++) {{
                var el = inputs[i];
                var label = (el.getAttribute("aria-label") || "").toLowerCase();
                var name = (el.getAttribute("name") || "").toLowerCase();
                var placeholder = (el.getAttribute("placeholder") || "").toLowerCase();
                if (label.includes("rate") || label.includes("bid") || label.includes("amount") ||
                    name.includes("rate") || name.includes("amount") || name.includes("bid") ||
                    placeholder.includes("rate") || placeholder.includes("bid")) {{
                    var setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, "value"
                    ).set;
                    setter.call(el, "{bid_rate}");
                    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
                    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
                    return "OK";
                }}
            }}
            return "NO_RATE_INPUT";
        }})()
        ''')

    # Small pause before submit
    time.sleep(2)

    # Click submit button
    log.info("  🚀 Clicking Submit...")
    submit_result = chrome.evaluate('''
    (function() {
        var selectors = [
            'button[data-test="submit-proposal"]',
            'button[data-cy="submit-proposal"]',
            'button.submit-proposal',
            'button[type="submit"]',
        ];
        // Also try buttons by text content
        var buttons = document.querySelectorAll("button");
        for (var i = 0; i < buttons.length; i++) {
            var txt = buttons[i].innerText.toLowerCase().trim();
            if (txt.includes("submit") && txt.includes("proposal")) {
                buttons[i].click();
                return "CLICKED:" + txt;
            }
            if (txt === "submit" || txt === "send proposal") {
                buttons[i].click();
                return "CLICKED:" + txt;
            }
        }
        // Try data-test selectors
        for (var j = 0; j < selectors.length; j++) {
            var btn = document.querySelector(selectors[j]);
            if (btn) {
                btn.click();
                return "CLICKED:" + btn.innerText;
            }
        }
        return "NO_SUBMIT_BUTTON";
    })()
    ''')
    log.info(f"  🔘 Submit result: {submit_result}")

    if 'NO_SUBMIT_BUTTON' in str(submit_result):
        return False, "Could not find Submit button"

    # Wait for submission to complete
    time.sleep(5)

    # Check result
    final_url = chrome.evaluate('window.location.href') or ''
    final_text = chrome.evaluate('document.body.innerText.substring(0, 1000)') or ''
    
    if 'success' in final_text.lower() or 'submitted' in final_text.lower() or 'proposal' in final_url:
        return True, "Proposal submitted successfully!"
    
    # Check for errors
    errors = chrome.evaluate('''
        (function() {
            var errs = document.querySelectorAll('.error, .alert-danger, [role="alert"]');
            var texts = [];
            errs.forEach(function(e) { if (e.innerText.trim()) texts.push(e.innerText.trim()); });
            return texts.join(" | ");
        })()
    ''') or ''
    
    if errors:
        return False, f"Error: {errors[:200]}"
    
    return True, f"Submit clicked — verify on Upwork (URL: {final_url[:60]})"


# ═══════════════════════════════════════════════════════════════
#  PART 3: MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='📤 Upwork Proposal Submitter')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no submit')
    parser.add_argument('--list', action='store_true', help='List pending proposals')
    args = parser.parse_args()

    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info("=" * 60)
    log.info(f"  📤 UPWORK PROPOSAL SUBMITTER")
    log.info(f"  📅 {ts}")
    log.info("=" * 60)

    # Step 1: Login to CRM
    log.info("🔐 Connecting to CRM...")
    crm = OdooClient()
    if not crm.login():
        sys.exit(1)
    log.info("✅ CRM connected")

    # Step 2: Get pending proposals
    tasks = get_pending_proposals(crm)
    if not tasks:
        log.info("📭 No proposals pending. Move tasks to 'Send Proposal with Client' stage.")
        return

    log.info(f"📋 Found {len(tasks)} pending proposal(s):")
    
    proposals = []
    for task in tasks:
        data = parse_proposal_data(task)
        
        # Resolve bid from tags
        if not data['bid_rate'] and data['tag_ids']:
            data['bid_rate'] = resolve_bid_from_tags(crm, data['tag_ids'])
        
        proposals.append(data)
        
        status_parts = []
        if data['ciphertext']:
            status_parts.append(f"✅ Job ID")
        else:
            status_parts.append(f"❌ No job ID")
        if data['cover_letter']:
            status_parts.append(f"✅ Cover ({len(data['cover_letter'])} chars)")
        else:
            status_parts.append(f"❌ No cover letter")
        if data['bid_rate']:
            status_parts.append(f"✅ ${data['bid_rate']}/hr")
        else:
            status_parts.append(f"⚠️  No bid rate")

        log.info(f"  {'→'} {data['task_name'][:55]}")
        log.info(f"    {' | '.join(status_parts)}")

    if args.list:
        return

    # Filter valid proposals
    valid = [p for p in proposals if p['ciphertext'] and p['cover_letter']]
    invalid = [p for p in proposals if not p['ciphertext'] or not p['cover_letter']]

    if invalid:
        log.warning(f"⚠️  {len(invalid)} proposal(s) incomplete (missing job ID or cover letter)")
        for p in invalid:
            log.warning(f"    ❌ {p['task_name'][:55]}")

    if not valid:
        log.error("❌ No valid proposals to submit. Make sure each task has:")
        log.error("   - Job ciphertext (auto-included by sync)")
        log.error("   - Cover letter (write below PROPOSAL section)")
        return

    if args.dry_run:
        log.info(f"\n🏃 DRY RUN — would submit {len(valid)} proposal(s):")
        for p in valid:
            log.info(f"  📝 {p['task_name'][:55]}")
            log.info(f"     Job: {p['ciphertext']}")
            log.info(f"     Bid: ${p['bid_rate']}/hr" if p['bid_rate'] else "     Bid: Not set")
            log.info(f"     Cover: {p['cover_letter'][:100]}...")
        return

    # Step 3: Launch Chrome CDP
    log.info(f"\n🌐 Launching Chrome for {len(valid)} proposal(s)...")
    chrome = ChromeCDP(port=9234)
    
    try:
        chrome.launch()
        chrome.connect()
        chrome.load_cookies()

        submitted = 0
        failed = 0

        for p in valid:
            log.info(f"\n{'─' * 50}")
            log.info(f"📤 Submitting: {p['task_name'][:55]}")
            log.info(f"   Job: {p['ciphertext']}")
            
            success, message = submit_proposal_via_cdp(
                chrome, p['ciphertext'], p['cover_letter'], p['bid_rate']
            )

            if success:
                log.info(f"  ✅ {message}")
                submitted += 1

                # Move task to Done in CRM
                crm.rpc('project.task', 'write',
                    args=[[p['task_id']], {'stage_id': DONE_STAGE_ID}]
                )
                log.info(f"  📋 CRM task moved to 'Done'")
            else:
                log.error(f"  ❌ {message}")
                failed += 1

            time.sleep(2)  # Pause between proposals

    except ImportError:
        log.error("❌ websocket-client not installed. Run: pip install websocket-client")
        sys.exit(1)
    except Exception as e:
        log.error(f"❌ Chrome error: {e}")
    finally:
        chrome.close()

    # Summary
    log.info(f"\n{'=' * 60}")
    log.info(f"  📊 RESULTS: Submitted: {submitted} | Failed: {failed}")
    log.info(f"  🔗 {CRM_URL}/odoo/project/{PROJECT_ID}")
    log.info(f"{'=' * 60}")


if __name__ == '__main__':
    main()
