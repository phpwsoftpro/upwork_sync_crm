#!/usr/bin/env python3
"""
CDP-Based Multi-Category Upwork Scraper
========================================
Launches Chrome with remote debugging (NOT headless, but minimized/background),
navigates to search pages, and extracts job data from NUXT.

Uses the existing Chrome profile and cookies to bypass Cloudflare.
"""

import os, sys, json, time, re, subprocess, signal, argparse, logging
from urllib.parse import quote_plus

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(SCRIPT_DIR, 'upwork_cookies.json')
CDP_PROFILE = os.path.join(SCRIPT_DIR, 'chrome_cdp_profile')
CDP_PORT = 9234  # Different port from login_cdp.py to avoid conflicts

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-7s %(message)s',
                    datefmt='%H:%M:%S', stream=sys.stderr)
log = logging.getLogger('cdp_scraper')

# ─── Search queries covering all categories ─────────────────────
SEARCH_QUERIES = [
    'web development', 'mobile app', 'software development',
    'python developer', 'javascript', 'react developer',
    'full stack developer', 'backend developer', 'frontend developer',
    'wordpress', 'shopify', 'flutter', 'node.js', 'PHP', 'devops',
    'artificial intelligence', 'machine learning', 'chatbot',
    'AI automation', 'prompt engineering', 'data science',
    'UI UX design', 'graphic design', 'logo design', 'web design',
    'digital marketing', 'SEO', 'social media marketing',
    'content writing', 'copywriting', 'technical writing',
    'video editing', 'animation', 'motion graphics',
    'virtual assistant', 'data entry', 'customer support',
]


def find_chrome():
    paths = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def launch_chrome():
    """Launch Chrome with remote debugging, window off-screen."""
    chrome = find_chrome()
    if not chrome:
        log.error("❌ Chrome not found!")
        return None

    cmd = [
        chrome,
        f'--remote-debugging-port={CDP_PORT}',
        f'--user-data-dir={CDP_PROFILE}',
        '--remote-allow-origins=*',
        '--window-position=10000,10000',   # Off-screen so it doesn't interfere
        '--window-size=1,1',
        '--disable-extensions',
        '--no-first-run',
        '--no-default-browser-check',
        'about:blank',
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    log.info(f"✅ Chrome launched (PID: {proc.pid}, port: {CDP_PORT})")
    return proc


def cdp_request(method, params=None, session_id=None):
    """Send CDP command via HTTP endpoint."""
    import urllib.request, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Get WebSocket target via /json
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{CDP_PORT}/json')
        resp = urllib.request.urlopen(req, timeout=5)
        targets = json.loads(resp.read())
    except Exception as e:
        log.error(f"CDP connection error: {e}")
        return None

    if not targets:
        return None

    # Use CDP via /json/protocol is limited; use websocket instead
    return targets


def navigate_and_extract(ws_url, url, label):
    """Navigate to URL and extract page source via WebSocket CDP."""
    import websocket

    ws = websocket.create_connection(ws_url, timeout=30)
    msg_id = 1

    def send_cmd(method, params=None):
        nonlocal msg_id
        cmd = {'id': msg_id, 'method': method}
        if params:
            cmd['params'] = params
        ws.send(json.dumps(cmd))
        msg_id += 1

        # Wait for response
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                resp = json.loads(ws.recv())
                if resp.get('id') == msg_id - 1:
                    return resp.get('result', {})
            except:
                break
        return {}

    try:
        # Navigate
        send_cmd('Page.navigate', {'url': url})
        time.sleep(4)  # Wait for page load

        # Get page HTML
        result = send_cmd('Runtime.evaluate', {
            'expression': 'document.documentElement.outerHTML',
            'returnByValue': True
        })

        html = result.get('result', {}).get('value', '')
        ws.close()
        return html

    except Exception as e:
        log.error(f"  ❌ {label}: {e}")
        try:
            ws.close()
        except:
            pass
        return ''


# ─── NUXT Parser (same as auto_sync.py) ──────────────────────────

def parse_nuxt_args(args_str):
    values = []
    i = 0
    while i < len(args_str):
        c = args_str[i]
        if c == '"':
            j = i + 1
            while j < len(args_str):
                if args_str[j] == '\\': j += 2; continue
                if args_str[j] == '"': break
                j += 1
            values.append(args_str[i + 1:j])
            i = j + 1
            while i < len(args_str) and args_str[i] in ' ,': i += 1
        elif c in '0123456789.':
            j = i
            while j < len(args_str) and args_str[j] not in ',)': j += 1
            val = args_str[i:j].strip()
            try: values.append(float(val) if '.' in val else int(val))
            except ValueError: values.append(val)
            i = j + 1
        elif c == '-' and i + 1 < len(args_str) and args_str[i + 1].isdigit():
            j = i + 1
            while j < len(args_str) and args_str[j] not in ',)': j += 1
            val = args_str[i:j].strip()
            try: values.append(float(val) if '.' in val else int(val))
            except ValueError: values.append(val)
            i = j + 1
        elif args_str[i:i + 4] == 'true':
            values.append(True); i += 4
            while i < len(args_str) and args_str[i] in ' ,': i += 1
        elif args_str[i:i + 5] == 'false':
            values.append(False); i += 5
            while i < len(args_str) and args_str[i] in ' ,': i += 1
        elif args_str[i:i + 4] in ('null', 'void'):
            values.append(None)
            j = i
            while j < len(args_str) and args_str[j] != ',': j += 1
            i = j + 1
        elif c in ' ,': i += 1
        else:
            j = i
            while j < len(args_str) and args_str[j] != ',': j += 1
            values.append(args_str[i:j].strip()); i = j + 1
    return values


def resolve_var(val_str, var_map):
    val_str = val_str.strip()
    if val_str.startswith('"') and val_str.endswith('"'):
        return val_str[1:-1]
    if val_str in var_map:
        return var_map[val_str]
    if val_str == 'true': return True
    if val_str == 'false': return False
    if val_str in ('null', 'void 0', ''): return None
    try: return float(val_str) if '.' in val_str else int(val_str)
    except: return val_str


def extract_jobs_from_html(html):
    match = re.search(
        r'window\.__NUXT__=\(function\((.*?)\)\{return\s*(.*)\}\((.*)\)\)',
        html, re.DOTALL
    )
    if not match:
        return []

    param_list = [p.strip() for p in match.group(1).split(',')]
    arg_values = parse_nuxt_args(match.group(3).strip())
    var_map = {param_list[i]: arg_values[i]
               for i in range(min(len(param_list), len(arg_values)))}
    body = match.group(2)

    all_jobs = []
    for section in ['feedBestMatch', 'feedMostRecent', 'searchResults', 'jobsSearch']:
        feed = re.search(rf'{section}:\{{[^{{]*?jobs:\[(.*?)\],paging:', body, re.DOTALL)
        if not feed:
            feed = re.search(rf'{section}:\{{[^[]*?jobs:\[(.*?)\],(paging|total)', body, re.DOTALL)
        if not feed:
            continue
        job_objs = _split_objects(feed.group(1))
        for obj_str in job_objs:
            job = _parse_job(obj_str, var_map)
            if job.get('title'):
                all_jobs.append(_format_job(job))
    return all_jobs


def _split_objects(raw):
    objs = []
    depth = start = 0
    for i, c in enumerate(raw):
        if c == '{':
            if depth == 0: start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0: objs.append(raw[start:i + 1])
    return objs


def _parse_job(obj_str, var_map):
    job = {}
    pairs = re.findall(r'(\w+)\s*:\s*("(?:[^"\\]|\\.)*"|[^,}\[\{]+)', obj_str)
    for key, val in pairs:
        resolved = resolve_var(val.strip(), var_map)
        if isinstance(resolved, str):
            resolved = (resolved.replace('\\u002F', '/').replace('\\u0026', '&')
                       .replace('\\u003C', '<').replace('\\u003E', '>').replace('\\n', '\n'))
        job[key] = resolved

    amt = re.search(r'amount:\{amount:(\w+),currencyCode:(\w+)\}', obj_str)
    if amt:
        job['budget_amount'] = resolve_var(amt.group(1), var_map)
        job['budget_currency'] = resolve_var(amt.group(2), var_map)

    seen_skills = set()
    skills = []
    for arr_key in ['skills', 'attrs']:
        m = re.search(rf'{arr_key}:\[(.*?)\]', obj_str, re.DOTALL)
        if m:
            for name in re.findall(r'prettyName:(\w+)', m.group(1)):
                s = resolve_var(name, var_map)
                if s and s not in seen_skills and isinstance(s, str):
                    seen_skills.add(s); skills.append(s)
    job['skills_list'] = skills

    occ = re.search(r'occupations:\{[^}]*prefLabel:(\w+)', obj_str)
    if occ:
        job['category'] = resolve_var(occ.group(1), var_map)

    return job


def _format_job(raw):
    def esc(s):
        return s.replace('\\u002F', '/').replace('\\u0026', '&').replace('\\n', '\n') if isinstance(s, str) else s

    budget = 'Not specified'
    hmin, hmax = raw.get('min'), raw.get('max')
    amt = raw.get('budget_amount', raw.get('amount'))
    try:
        hmin = float(hmin) if hmin else 0
        hmax = float(hmax) if hmax else 0
    except (ValueError, TypeError):
        hmin = hmax = 0
    try:
        amt = float(amt) if amt else 0
    except (ValueError, TypeError):
        amt = 0
    if hmin > 0 or hmax > 0:
        budget = f"${hmin:.0f}-${hmax:.0f}/hr"
    elif amt > 0:
        budget = f"${amt:,.0f}"

    spent = raw.get('totalSpent')
    spent_str = f"${spent:,.2f}" if spent and isinstance(spent, (int, float)) and spent > 0 else "New client"
    pv = raw.get('paymentVerificationStatus')

    return {
        'title': esc(str(raw.get('title', ''))),
        'ciphertext': raw.get('ciphertext', ''),
        'link': f"https://www.upwork.com/jobs/{raw.get('ciphertext', '')}",
        'description': esc(str(raw.get('description', ''))),
        'budget': budget,
        'experience_level': str(raw.get('tier', raw.get('tierText', ''))),
        'duration': esc(str(raw.get('durationLabel', raw.get('duration', '')))),
        'workload': esc(str(raw.get('engagement', ''))),
        'skills': raw.get('skills_list', []),
        'proposals': str(raw.get('proposalsTier', '')),
        'freelancers_to_hire': raw.get('freelancersToHire', 1),
        'published_on': str(raw.get('publishedOn', '')),
        'client_country': esc(str(raw.get('country', ''))),
        'client_city': esc(str(raw.get('city', ''))) if raw.get('city') else '',
        'client_total_spent': spent_str,
        'client_total_hires': raw.get('totalHires', 0),
        'client_total_reviews': raw.get('totalReviews', 0),
        'client_rating': raw.get('totalFeedback', ''),
        'client_payment_verified': "✅ Verified" if pv == 1 else ("❌ Not verified" if pv else ""),
        'is_premium': raw.get('premium', False),
        'category': str(raw.get('category', raw.get('prettyName', ''))),
    }


# ─── Main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='🔍 CDP Upwork Multi-Category Scraper')
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--output', default='', help='Output JSON file')
    args = parser.parse_args()

    log.info(f"🚀 CDP scraper (target: {args.count} jobs)")

    # Install websocket-client if needed
    try:
        import websocket
    except ImportError:
        log.info("Installing websocket-client...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'websocket-client'],
                      capture_output=True)
        import websocket

    # Launch Chrome
    proc = launch_chrome()
    if not proc:
        sys.exit(1)

    all_jobs = []
    seen = set()

    def add_jobs(jobs, label):
        added = 0
        for j in jobs:
            key = j.get('ciphertext') or j['title']
            if key not in seen:
                seen.add(key)
                all_jobs.append(j)
                added += 1
        if jobs:
            log.info(f"  ✅ {label}: {len(jobs)} found, {added} new (total: {len(all_jobs)})")
        else:
            log.warning(f"  ⚠️  {label}: 0 jobs")

    try:
        # Get CDP targets
        import urllib.request
        req = urllib.request.Request(f'http://127.0.0.1:{CDP_PORT}/json')
        resp = urllib.request.urlopen(req, timeout=5)
        targets = json.loads(resp.read())

        page_target = None
        for t in targets:
            if t.get('type') == 'page':
                page_target = t
                break

        if not page_target:
            log.error("❌ No page target found")
            return

        ws_url = page_target['webSocketDebuggerUrl']
        log.info(f"📡 Connected to CDP: {ws_url[:50]}...")

        # First, load cookies
        ws = websocket.create_connection(ws_url, timeout=30)
        msg_id = [1]

        def send_and_wait(method, params=None, timeout=15):
            cmd = {'id': msg_id[0], 'method': method}
            if params:
                cmd['params'] = params
            ws.send(json.dumps(cmd))
            current_id = msg_id[0]
            msg_id[0] += 1

            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    ws.settimeout(max(0.1, deadline - time.time()))
                    resp = json.loads(ws.recv())
                    if resp.get('id') == current_id:
                        return resp.get('result', {})
                except:
                    continue
            return {}

        # Enable Page events
        send_and_wait('Page.enable')

        # Load cookies from file
        with open(COOKIE_FILE) as f:
            cookies = json.load(f)

        for c in cookies:
            try:
                cookie_params = {
                    'name': c['name'],
                    'value': c['value'],
                    'domain': c.get('domain', '.upwork.com'),
                    'path': c.get('path', '/'),
                }
                if c.get('secure'):
                    cookie_params['secure'] = True
                if c.get('httpOnly'):
                    cookie_params['httpOnly'] = True
                send_and_wait('Network.setCookie', cookie_params, timeout=3)
            except:
                pass

        log.info("🍪 Cookies loaded")

        # Phase 1: Feed pages
        urls = [
            ('Best Matches', 'https://www.upwork.com/nx/find-work/best-matches'),
            ('Most Recent', 'https://www.upwork.com/nx/find-work/most-recent'),
        ]

        for label, url in urls:
            send_and_wait('Page.navigate', {'url': url})
            time.sleep(5)

            result = send_and_wait('Runtime.evaluate', {
                'expression': 'document.documentElement.outerHTML',
                'returnByValue': True
            }, timeout=10)

            html = result.get('result', {}).get('value', '')
            if html:
                if 'account-security/login' in html[:3000]:
                    log.error("❌ Session expired!")
                    return
                jobs = extract_jobs_from_html(html)
                add_jobs(jobs, label)
            time.sleep(1)

        # Phase 2: Search pages
        if len(all_jobs) < args.count:
            log.info(f"📡 Phase 2: Searching categories (need {args.count - len(all_jobs)} more)...")

            for query in SEARCH_QUERIES:
                if len(all_jobs) >= args.count:
                    log.info(f"  🎯 Reached target!")
                    break

                search_url = f'https://www.upwork.com/nx/search/jobs/?q={quote_plus(query)}&sort=recency&per_page=50'
                send_and_wait('Page.navigate', {'url': search_url})
                time.sleep(5)

                result = send_and_wait('Runtime.evaluate', {
                    'expression': 'document.documentElement.outerHTML',
                    'returnByValue': True
                }, timeout=10)

                html = result.get('result', {}).get('value', '')
                if html:
                    jobs = extract_jobs_from_html(html)
                    add_jobs(jobs, f'Search: {query}')

                time.sleep(1.5)

        ws.close()

    finally:
        # Kill Chrome
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except:
            try:
                proc.kill()
            except:
                pass
        log.info("🔒 Chrome closed")

    log.info(f"📊 Final: {len(all_jobs)} unique jobs")

    output_data = json.dumps(all_jobs, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_data)
        log.info(f"💾 Saved to {args.output}")
    else:
        print(output_data)


if __name__ == '__main__':
    main()
