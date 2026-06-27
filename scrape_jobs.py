#!/usr/bin/env python3
"""
Upwork Job Scraper - Full Data, Pure HTTP, No Browser!
======================================================
Fetches complete job data (title, description, budget, skills,
client info, proposals, etc.) using saved cookies.

No Chrome launch. No Cloudflare. No crash. No mouse/keyboard.

Usage:
    python3 scrape_jobs.py                     # 50 latest IT jobs  
    python3 scrape_jobs.py --query "Python"    # Custom search
    python3 scrape_jobs.py --count 30          # Limit results
"""

import os
import sys
import re
import json
import argparse
import logging
import urllib.request
import urllib.error
from datetime import datetime
from urllib.parse import quote_plus

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('upwork_scraper')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ─── Cookie loader ──────────────────────────────────────────────
def load_cookies():
    path = os.path.join(SCRIPT_DIR, 'upwork_cookies.json')
    if not os.path.exists(path):
        log.error("❌ No saved cookies! Run login_cdp.py first.")
        sys.exit(1)
    with open(path) as f:
        cookies = json.load(f)
    parts = [f"{c['name']}={c['value']}" for c in cookies
             if '.upwork.com' in c.get('domain', '') or 'www.upwork.com' in c.get('domain', '')]
    log.info(f"🍪 Loaded {len(parts)} cookies")
    return '; '.join(parts)


# ─── HTTP fetcher ────────────────────────────────────────────────
def fetch_page(cookie_str, url, referer=None):
    headers = {
        'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cookie': cookie_str,
        'Referer': referer or 'https://www.upwork.com/nx/find-work/',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        log.error(f"   ❌ HTTP {e.code}: {e.reason}")
        return None
    except Exception as e:
        log.error(f"   ❌ {e}")
        return None


# ─── NUXT data parser ───────────────────────────────────────────
def parse_nuxt_args(args_str):
    """Parse the NUXT function arguments into a list of values."""
    values = []
    i = 0
    while i < len(args_str):
        c = args_str[i]
        if c == '"':
            j = i + 1
            while j < len(args_str):
                if args_str[j] == '\\':
                    j += 2
                    continue
                if args_str[j] == '"':
                    break
                j += 1
            values.append(args_str[i + 1:j])
            i = j + 1
            while i < len(args_str) and args_str[i] in ' ,':
                i += 1
        elif c in '0123456789.':
            j = i
            while j < len(args_str) and args_str[j] not in ',)':
                j += 1
            val = args_str[i:j].strip()
            try:
                values.append(float(val) if '.' in val else int(val))
            except ValueError:
                values.append(val)
            i = j + 1
        elif c == '-' and i + 1 < len(args_str) and args_str[i + 1].isdigit():
            j = i + 1
            while j < len(args_str) and args_str[j] not in ',)':
                j += 1
            val = args_str[i:j].strip()
            try:
                values.append(float(val) if '.' in val else int(val))
            except ValueError:
                values.append(val)
            i = j + 1
        elif args_str[i:i + 4] == 'true':
            values.append(True)
            i += 4
            while i < len(args_str) and args_str[i] in ' ,':
                i += 1
        elif args_str[i:i + 5] == 'false':
            values.append(False)
            i += 5
            while i < len(args_str) and args_str[i] in ' ,':
                i += 1
        elif args_str[i:i + 4] in ('null', 'void'):
            values.append(None)
            j = i
            while j < len(args_str) and args_str[j] != ',':
                j += 1
            i = j + 1
        elif c in ' ,':
            i += 1
        else:
            j = i
            while j < len(args_str) and args_str[j] != ',':
                j += 1
            values.append(args_str[i:j].strip())
            i = j + 1
    return values


def resolve_var(val_str, var_map):
    """Resolve a variable reference to its actual value."""
    val_str = val_str.strip()
    if val_str.startswith('"') and val_str.endswith('"'):
        return val_str[1:-1]
    if val_str in var_map:
        return var_map[val_str]
    if val_str == 'true':
        return True
    if val_str == 'false':
        return False
    if val_str in ('null', 'void 0', ''):
        return None
    try:
        return float(val_str) if '.' in val_str else int(val_str)
    except (ValueError, TypeError):
        return val_str


def extract_jobs_from_nuxt(html):
    """Parse NUXT compressed data to extract full job information."""
    # Match the NUXT function pattern
    match = re.search(
        r'window\.__NUXT__=\(function\((.*?)\)\{return\s*(.*)\}\((.*)\)\)',
        html, re.DOTALL
    )
    if not match:
        log.warning("   Could not find NUXT function")
        return []

    params_str = match.group(1)
    body = match.group(2)
    args_str = match.group(3).strip()

    # Build variable mapping
    param_list = [p.strip() for p in params_str.split(',')]
    arg_values = parse_nuxt_args(args_str)

    var_map = {}
    for idx, param in enumerate(param_list):
        if idx < len(arg_values):
            var_map[param] = arg_values[idx]

    # Find job arrays in the body
    # Try multiple patterns for different page types
    job_sections = []

    # Best matches feed
    feed_match = re.search(r'feedBestMatch:\{jobs:\[(.*?)\],paging:', body, re.DOTALL)
    if feed_match:
        job_sections.append(('Best Matches', feed_match.group(1)))

    # Search results
    search_match = re.search(r'searchResults?:\{jobs:\[(.*?)\],paging:', body, re.DOTALL)
    if search_match:
        job_sections.append(('Search', search_match.group(1)))

    # Most recent
    recent_match = re.search(r'feedMostRecent:\{jobs:\[(.*?)\],paging:', body, re.DOTALL)
    if recent_match:
        job_sections.append(('Most Recent', recent_match.group(1)))

    # Generic fallback - find any jobs array
    if not job_sections:
        generic = re.search(r'jobs:\[(.*?)\],paging:', body, re.DOTALL)
        if generic:
            job_sections.append(('Generic', generic.group(1)))

    all_jobs = []
    for section_name, jobs_raw in job_sections:
        # Split into individual job objects
        job_objs = split_objects(jobs_raw)
        log.info(f"   📂 {section_name}: {len(job_objs)} jobs")

        for obj_str in job_objs:
            job = parse_job_object(obj_str, var_map)
            if job and job.get('title'):
                all_jobs.append(job)

    return all_jobs


def split_objects(raw):
    """Split a comma-separated list of {...} objects."""
    objects = []
    depth = 0
    start = 0
    for i, c in enumerate(raw):
        if c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                objects.append(raw[start:i + 1])
    return objects


def parse_job_object(obj_str, var_map):
    """Parse a single job object string and resolve all variables."""
    job = {}

    # Extract simple key:value pairs
    pairs = re.findall(r'(\w+)\s*:\s*("(?:[^"\\]|\\.)*"|[^,}\[\{]+)', obj_str)
    for key, val in pairs:
        resolved = resolve_var(val.strip(), var_map)
        if isinstance(resolved, str):
            resolved = (resolved.replace('\\u002F', '/')
                       .replace('\\u0026', '&')
                       .replace('\\u003C', '<')
                       .replace('\\u003E', '>')
                       .replace('\\n', '\n'))
        job[key] = resolved

    # Parse nested amount object
    amount_match = re.search(r'amount:\{amount:(\w+),currencyCode:(\w+)\}', obj_str)
    if amount_match:
        job['budget_amount'] = resolve_var(amount_match.group(1), var_map)
        job['budget_currency'] = resolve_var(amount_match.group(2), var_map)

    # Parse skills array — get from both 'skills' and 'attrs' 
    all_skill_names = []
    for arr_key in ['skills', 'attrs']:
        arr_match = re.search(rf'{arr_key}:\[(.*?)\]', obj_str, re.DOTALL)
        if arr_match:
            names = re.findall(r'prettyName:(\w+)', arr_match.group(1))
            if not names:
                names = re.findall(r'prefLabel:(\w+)', arr_match.group(1))
            all_skill_names.extend(names)

    # Deduplicate while preserving order
    seen_skills = set()
    unique_skills = []
    for s in all_skill_names:
        resolved = resolve_var(s, var_map)
        if resolved and resolved not in seen_skills and isinstance(resolved, str):
            seen_skills.add(resolved)
            unique_skills.append(resolved)
    job['skills_list'] = unique_skills

    # Parse occupations for category
    occ_match = re.search(r'occupations:\{[^}]*prefLabel:(\w+)', obj_str)
    if occ_match:
        job['category'] = resolve_var(occ_match.group(1), var_map)
    elif not job.get('category'):
        # Fallback: first prefLabel outside skills
        pref = re.search(r'prefLabel:(\w+)', obj_str)
        if pref:
            job['category'] = resolve_var(pref.group(1), var_map)

    return job


def format_job(raw_job):
    """Convert raw parsed job into a clean, structured dict."""
    def unescape(s):
        if not isinstance(s, str):
            return s
        return (s.replace('\\u002F', '/')
                 .replace('\\u0026', '&')
                 .replace('\\n', '\n')
                 .replace('\\t', ' '))

    # Budget
    budget = ''
    amt = raw_job.get('budget_amount', raw_job.get('amount'))
    curr = raw_job.get('budget_currency', raw_job.get('currencyCode', 'USD'))
    hourly_min = raw_job.get('min')
    hourly_max = raw_job.get('max')

    if hourly_min and hourly_max and (hourly_min > 0 or hourly_max > 0):
        budget = f"${hourly_min}-${hourly_max}/hr"
    elif amt and amt > 0:
        budget = f"${amt:,.0f}" if isinstance(amt, (int, float)) else f"${amt}"
    else:
        budget = "Not specified"

    # Description
    desc = unescape(str(raw_job.get('description', '')))

    # Skills
    skills = raw_job.get('skills_list', [])
    if not skills:
        cat = raw_job.get('category', raw_job.get('prettyName', ''))
        if cat:
            skills = [str(cat)]

    # Client info
    client_spent = raw_job.get('totalSpent')
    if client_spent and isinstance(client_spent, (int, float)) and client_spent > 0:
        client_spent_str = f"${client_spent:,.2f}"
    else:
        client_spent_str = "New client"

    payment_status = raw_job.get('paymentVerificationStatus')
    payment_verified = "✅ Verified" if payment_status == 1 else "❌ Not verified" if payment_status else ""

    return {
        'title': unescape(str(raw_job.get('title', ''))),
        'link': f"https://www.upwork.com/jobs/{raw_job.get('ciphertext', '')}",
        'description': desc,  # Full description, no truncation
        'budget': budget,
        'experience_level': str(raw_job.get('tier', raw_job.get('tierText', ''))),
        'duration': unescape(str(raw_job.get('durationLabel', raw_job.get('duration', '')))),
        'workload': unescape(str(raw_job.get('engagement', ''))),
        'skills': skills,
        'proposals': str(raw_job.get('proposalsTier', '')),
        'freelancers_to_hire': raw_job.get('freelancersToHire', 1),
        'published_on': str(raw_job.get('publishedOn', '')),
        'client_country': unescape(str(raw_job.get('country', ''))),
        'client_city': unescape(str(raw_job.get('city', ''))) if raw_job.get('city') else '',
        'client_total_spent': client_spent_str,
        'client_total_hires': raw_job.get('totalHires', 0),
        'client_total_reviews': raw_job.get('totalReviews', 0),
        'client_rating': raw_job.get('totalFeedback', ''),
        'client_payment_verified': payment_verified,
        'is_premium': raw_job.get('premium', False),
        'category': str(raw_job.get('category', raw_job.get('prettyName', ''))),
    }


# ─── Main scraping ──────────────────────────────────────────────
def scrape_jobs(cookie_str, query='IT', max_jobs=50):
    all_jobs = []
    seen_titles = set()

    # Pages to fetch
    urls = [
        ('Best Matches', 'https://www.upwork.com/nx/find-work/best-matches'),
        ('Most Recent', 'https://www.upwork.com/nx/find-work/most-recent'),
    ]

    # Add search pages if query is not generic
    encoded_q = quote_plus(query)
    for pg in range(1, 4):
        urls.append(
            (f'Search p{pg}',
             f'https://www.upwork.com/nx/search/jobs/?q={encoded_q}&sort=recency&per_page=20&page={pg}')
        )

    for label, url in urls:
        if len(all_jobs) >= max_jobs:
            break

        log.info(f"📄 Fetching: {label}...")
        html = fetch_page(cookie_str, url)
        if not html:
            continue

        if 'account-security/login' in html[:3000]:
            log.error("❌ Session expired! Run login_cdp.py to re-login.")
            break

        if 'Verify you are human' in html[:3000]:
            log.warning(f"   ⚠️  Cloudflare on {label}, skipping...")
            continue

        raw_jobs = extract_jobs_from_nuxt(html)
        for rj in raw_jobs:
            if rj.get('title') and rj['title'] not in seen_titles:
                seen_titles.add(rj['title'])
                all_jobs.append(format_job(rj))

        log.info(f"   ✅ Total so far: {len(all_jobs)} unique jobs")

    return all_jobs[:max_jobs]


# ─── Display & Save ─────────────────────────────────────────────
def display_and_save(jobs, query):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = os.path.join(SCRIPT_DIR, f'upwork_jobs_{ts}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 110}")
    print(f"  📋 UPWORK JOBS: '{query}' — {len(jobs)} Listings (Full Data)")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 110}")

    for i, j in enumerate(jobs, 1):
        print(f"\n{'━' * 110}")
        title = j['title']
        premium = " ⭐ PREMIUM" if j.get('is_premium') else ""
        print(f"  #{i:02d}  {title}{premium}")
        print(f"  {'─' * 106}")

        # Row 1: Budget & Experience
        parts = []
        if j.get('budget'):
            parts.append(f"💰 {j['budget']}")
        if j.get('experience_level') and j['experience_level'] != 'None':
            parts.append(f"📊 {j['experience_level']}")
        if j.get('duration') and j['duration'] != 'None':
            parts.append(f"⏱️  {j['duration']}")
        if j.get('workload') and j['workload'] != 'None':
            parts.append(f"🕐 {j['workload']}")
        if parts:
            print(f"      {' │ '.join(parts)}")

        # Row 2: Proposals & Category
        parts2 = []
        if j.get('proposals') and j['proposals'] != 'None':
            parts2.append(f"📝 Proposals: {j['proposals']}")
        if j.get('category') and j['category'] != 'None':
            parts2.append(f"📂 {j['category']}")
        if j.get('freelancers_to_hire', 1) > 1:
            parts2.append(f"👥 Hiring: {j['freelancers_to_hire']}")
        if parts2:
            print(f"      {' │ '.join(parts2)}")

        # Row 3: Skills
        if j.get('skills') and j['skills']:
            print(f"      🏷️  {', '.join(str(s) for s in j['skills'][:8])}")

        # Row 4: Description
        if j.get('description'):
            desc = j['description'].replace('\n', ' ').strip()
            if len(desc) > 200:
                desc = desc[:200] + '...'
            print(f"      📄 {desc}")

        # Row 5: Client info
        client_parts = []
        if j.get('client_country') and j['client_country'] != 'None':
            loc = j['client_country']
            if j.get('client_city'):
                loc = f"{j['client_city']}, {loc}"
            client_parts.append(f"📍 {loc}")
        if j.get('client_total_spent'):
            client_parts.append(f"💵 Spent: {j['client_total_spent']}")
        if j.get('client_total_hires'):
            client_parts.append(f"👤 Hires: {j['client_total_hires']}")
        if j.get('client_rating') and j['client_rating']:
            client_parts.append(f"⭐ {j['client_rating']}")
        if j.get('client_payment_verified'):
            client_parts.append(j['client_payment_verified'])
        if client_parts:
            print(f"      {' │ '.join(client_parts)}")

        # Row 6: Time & Link
        if j.get('published_on') and j['published_on'] != 'None':
            print(f"      🕐 Published: {j['published_on']}")
        print(f"      🔗 {j['link']}")

    print(f"\n{'=' * 110}")
    print(f"  ✅ {len(jobs)} jobs saved → {json_path}")
    print(f"{'=' * 110}\n")
    return json_path


def main():
    parser = argparse.ArgumentParser(description='📋 Upwork Full Job Scraper (No Browser!)')
    parser.add_argument('--query', default='IT', help='Search query (default: IT)')
    parser.add_argument('--count', type=int, default=50, help='Max jobs (default: 50)')
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("  📋 UPWORK JOB SCRAPER — Full Data, Pure HTTP")
    log.info(f"  🔍 Query: '{args.query}' | Max: {args.count}")
    log.info("  🚫 No browser needed!")
    log.info("=" * 60)

    cookie_str = load_cookies()
    jobs = scrape_jobs(cookie_str, args.query, args.count)

    if jobs:
        display_and_save(jobs, args.query)
    else:
        log.warning("⚠️  No jobs found. Session may have expired.")
        log.info("💡 Run: python3 login_cdp.py")


if __name__ == '__main__':
    main()
