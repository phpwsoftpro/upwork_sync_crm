#!/usr/bin/env python3
"""
Upwork → CRM Auto Sync
=======================
Scrapes latest IT jobs from Upwork and syncs new ones to Odoo CRM.
Designed to run every 20 minutes via macOS launchd.

Usage:
    python3 auto_sync.py                    # Default: IT jobs
    python3 auto_sync.py --query "Python"   # Custom search
    python3 auto_sync.py --dry-run          # Preview only, no CRM write
"""

import os, sys, re, json, time, ssl, logging, argparse
import urllib.request, urllib.parse, http.cookiejar
from datetime import datetime
from urllib.parse import quote_plus

# ─── Config ──────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, 'logs')
COOKIE_FILE = os.path.join(SCRIPT_DIR, 'upwork_cookies.json')
SYNCED_FILE = os.path.join(SCRIPT_DIR, 'synced_jobs.json')  # Track already-synced jobs

CRM_URL = 'https://crm.wsoftpro.com'
CRM_EMAIL = 'trung@wsoftpro.com'
CRM_PASSWORD = os.environ.get('CRM_PASSWORD', '')
PROJECT_ID = 74        # "Bid Jobs Upwork"
STAGE_PENDING = 1889   # "Pending"

os.makedirs(LOG_DIR, exist_ok=True)

# Logging: both console + file
log_file = os.path.join(LOG_DIR, f'sync_{datetime.now().strftime("%Y%m%d")}.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger('auto_sync')


# ═══════════════════════════════════════════════════════════════════
#  PART 1: UPWORK SCRAPER (Pure HTTP)
# ═══════════════════════════════════════════════════════════════════

def load_upwork_cookies():
    if not os.path.exists(COOKIE_FILE):
        log.error("❌ No upwork_cookies.json! Run login_cdp.py first.")
        return None
    with open(COOKIE_FILE) as f:
        cookies = json.load(f)
    parts = [f"{c['name']}={c['value']}" for c in cookies
             if '.upwork.com' in c.get('domain', '') or 'www.upwork.com' in c.get('domain', '')]
    return '; '.join(parts)


def fetch_page(cookie_str, url):
    headers = {
        'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cookie': cookie_str,
        'Referer': 'https://www.upwork.com/nx/find-work/',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        log.error(f"   Fetch error: {e}")
        return None


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


def extract_jobs_from_nuxt(html):
    match = re.search(
        r'window\.__NUXT__=\(function\((.*?)\)\{return\s*(.*)\}\((.*)\)\)',
        html, re.DOTALL
    )
    if not match:
        return []

    param_list = [p.strip() for p in match.group(1).split(',')]
    arg_values = parse_nuxt_args(match.group(3).strip())
    var_map = {param_list[i]: arg_values[i] for i in range(min(len(param_list), len(arg_values)))}
    body = match.group(2)

    all_jobs = []
    for section in ['feedBestMatch', 'feedMostRecent', 'searchResults']:
        feed = re.search(rf'{section}:\{{jobs:\[(.*?)\],paging:', body, re.DOTALL)
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

    # Amount
    amt = re.search(r'amount:\{amount:(\w+),currencyCode:(\w+)\}', obj_str)
    if amt:
        job['budget_amount'] = resolve_var(amt.group(1), var_map)
        job['budget_currency'] = resolve_var(amt.group(2), var_map)

    # Skills from both arrays
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

    # Category
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
    if hmin and hmax and (hmin > 0 or hmax > 0):
        budget = f"${hmin}-${hmax}/hr"
    elif amt and amt > 0:
        budget = f"${amt:,.0f}" if isinstance(amt, (int, float)) else f"${amt}"

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


def scrape_upwork(cookie_str, query='IT'):
    all_jobs = []
    seen = set()
    urls = [
        ('Best Matches', 'https://www.upwork.com/nx/find-work/best-matches'),
        ('Most Recent', 'https://www.upwork.com/nx/find-work/most-recent'),
    ]
    for label, url in urls:
        log.info(f"  📄 Fetching {label}...")
        html = fetch_page(cookie_str, url)
        if not html:
            continue
        if 'account-security/login' in html[:3000]:
            log.error("❌ Upwork session expired! Run login_cdp.py to re-login.")
            return None  # Signal session expired
        if 'Verify you are human' in html[:3000]:
            log.warning(f"  ⚠️  Cloudflare on {label}, skipping")
            continue
        jobs = extract_jobs_from_nuxt(html)
        for j in jobs:
            if j['title'] not in seen:
                seen.add(j['title'])
                all_jobs.append(j)
        log.info(f"  ✅ {label}: {len(jobs)} jobs (total unique: {len(all_jobs)})")
    return all_jobs


# ═══════════════════════════════════════════════════════════════════
#  PART 2: ODOO CRM CLIENT
# ═══════════════════════════════════════════════════════════════════

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

    def get_existing_titles(self):
        tasks = self.rpc('project.task', 'search_read',
            args=[[['project_id', '=', PROJECT_ID]]],
            kwargs={'fields': ['name'], 'limit': 1000}
        )
        return {t['name'] for t in (tasks or [])}

    def create_task(self, name, description_html):
        return self.rpc('project.task', 'create',
            args=[{'name': name, 'project_id': PROJECT_ID,
                   'stage_id': STAGE_PENDING, 'description': description_html}])


def job_to_html(job):
    parts = []
    link = job.get('link', '')
    if link:
        parts.append(f'<p><strong>🔗 Upwork Link:</strong> <a href="{link}" target="_blank">{link}</a></p>')

    rows = []
    for icon, label, key in [
        ('💰', 'Budget', 'budget'), ('📊', 'Level', 'experience_level'),
        ('⏱️', 'Duration', 'duration'), ('🕐', 'Workload', 'workload'),
        ('📝', 'Proposals', 'proposals'), ('📂', 'Category', 'category'),
    ]:
        val = job.get(key, '')
        if val and val != 'None' and val != 'Not specified':
            rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>{icon} {label}</strong></td><td>{val}</td></tr>')
    hire = job.get('freelancers_to_hire', 1)
    if hire and hire > 1:
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>👥 Hiring</strong></td><td>{hire}</td></tr>')
    pub = job.get('published_on', '')
    if pub and pub != 'None':
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>📅 Published</strong></td><td>{pub[:19].replace("T"," ")} UTC</td></tr>')
    if rows:
        parts.append('<table style="border-collapse:collapse; margin:8px 0;">' + ''.join(rows) + '</table>')

    skills = job.get('skills', [])
    if skills:
        tags = ' '.join(f'<span style="background:#e8f0fe; color:#1a73e8; padding:3px 10px; '
                        f'border-radius:14px; margin:2px; display:inline-block; font-size:13px;">{s}</span>'
                        for s in skills if s)
        parts.append(f'<h3>🏷️ Skills</h3><p>{tags}</p>')

    desc = job.get('description', '')
    if desc:
        d = desc
        d = re.sub(r'^### (.+)$', r'<h4>\1</h4>', d, flags=re.MULTILINE)
        d = re.sub(r'^## (.+)$', r'<h3>\1</h3>', d, flags=re.MULTILINE)
        d = re.sub(r'^# (.+)$', r'<h2>\1</h2>', d, flags=re.MULTILINE)
        d = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', d)
        d = re.sub(r'^[*\-•] (.+)$', r'<li>\1</li>', d, flags=re.MULTILINE)
        d = re.sub(r'((?:<li>.*?</li>\n?)+)', r'<ul>\1</ul>', d)
        d = re.sub(r'\n\n+', '</p><p>', d)
        d = d.replace('\n', '<br/>')
        parts.append(f'<h3>📄 Job Description & Requirements</h3><p>{d}</p>')

    client_rows = []
    for icon, label, key in [
        ('📍', 'Location', 'client_country'), ('💵', 'Spent', 'client_total_spent'),
        ('👤', 'Hires', 'client_total_hires'), ('⭐', 'Rating', 'client_rating'),
        ('💳', 'Payment', 'client_payment_verified'),
    ]:
        val = job.get(key, '')
        if key == 'client_country':
            city = job.get('client_city', '')
            val = f"{city}, {val}" if city else val
        if key == 'client_rating' and val:
            val = f"{val}/5"
        if val and val != 'None' and val != '' and val != 0:
            client_rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>{icon} {label}</strong></td><td>{val}</td></tr>')
    if client_rows:
        parts.append('<h3>👤 Client</h3><table style="border-collapse:collapse;">' + ''.join(client_rows) + '</table>')

    return '\n'.join(parts)


# ═══════════════════════════════════════════════════════════════════
#  PART 3: SYNC LOGIC
# ═══════════════════════════════════════════════════════════════════

def load_synced():
    """Load set of previously synced job ciphertexts."""
    if os.path.exists(SYNCED_FILE):
        with open(SYNCED_FILE) as f:
            return set(json.load(f))
    return set()


def save_synced(synced_set):
    with open(SYNCED_FILE, 'w') as f:
        json.dump(list(synced_set), f)


def main():
    parser = argparse.ArgumentParser(description='🔄 Upwork → CRM Auto Sync')
    parser.add_argument('--query', default='IT', help='Search query (default: IT)')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no CRM write')
    args = parser.parse_args()

    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info("=" * 60)
    log.info(f"  🔄 UPWORK → CRM AUTO SYNC")
    log.info(f"  📅 {ts} | Query: '{args.query}'")
    log.info("=" * 60)

    # Step 1: Load cookies
    cookie_str = load_upwork_cookies()
    if not cookie_str:
        sys.exit(1)

    # Step 2: Scrape Upwork
    log.info("📡 Scraping Upwork...")
    jobs = scrape_upwork(cookie_str, args.query)
    if jobs is None:
        log.error("❌ Session expired. Please run login_cdp.py manually.")
        sys.exit(1)
    if not jobs:
        log.info("📭 No jobs found this round.")
        return

    log.info(f"📊 Scraped {len(jobs)} total jobs")

    # Step 3: Filter new jobs (not yet synced)
    synced = load_synced()
    new_jobs = [j for j in jobs if j.get('ciphertext') and j['ciphertext'] not in synced]
    log.info(f"🆕 New jobs to sync: {len(new_jobs)} (already synced: {len(jobs) - len(new_jobs)})")

    if not new_jobs:
        log.info("✅ All jobs already synced. Nothing to do.")
        return

    if args.dry_run:
        log.info("🏃 DRY RUN — would create these tasks:")
        for j in new_jobs:
            log.info(f"  📝 {j['title'][:70]}")
        return

    # Step 4: Login to CRM
    log.info("🔐 Logging in to CRM...")
    crm = OdooClient()
    if not crm.login():
        sys.exit(1)
    log.info("✅ CRM connected")

    # Step 5: Get existing task names to avoid duplicates
    existing_titles = crm.get_existing_titles()
    log.info(f"📋 Existing CRM tasks: {len(existing_titles)}")

    # Step 6: Create new tasks
    created = 0
    skipped = 0
    for j in new_jobs:
        title = j['title']
        if title in existing_titles:
            log.info(f"  ⏭️  Skip (exists): {title[:60]}")
            synced.add(j['ciphertext'])
            skipped += 1
            continue

        desc_html = job_to_html(j)
        log.info(f"  📝 Creating: {title[:60]}...")
        result = crm.create_task(title, desc_html)

        if result:
            log.info(f"       ✅ Created (ID: {result}, {len(j.get('description',''))} chars)")
            synced.add(j['ciphertext'])
            existing_titles.add(title)
            created += 1
        else:
            log.error(f"       ❌ Failed!")

        time.sleep(0.3)

    # Step 7: Save synced state
    save_synced(synced)

    log.info("")
    log.info("=" * 60)
    log.info(f"  ✅ SYNC COMPLETE")
    log.info(f"  📊 Created: {created} | Skipped: {skipped} | Total synced: {len(synced)}")
    log.info(f"  🔗 {CRM_URL}/odoo/project/{PROJECT_ID}")
    log.info("=" * 60)


if __name__ == '__main__':
    main()
