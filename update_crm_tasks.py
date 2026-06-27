#!/usr/bin/env python3
"""
Update existing CRM tasks with full data from re-scraped jobs.
Matches by title, updates description with full content.
"""

import os, sys, re, json, time, ssl, urllib.request, urllib.parse, http.cookiejar
from glob import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CRM_URL = 'https://crm.wsoftpro.com'
CRM_EMAIL = 'trung@wsoftpro.com'
CRM_PASSWORD = os.environ.get('CRM_PASSWORD', '')
PROJECT_ID = 74


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
        self.ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
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
        self.opener.open(req2, timeout=15)
        print("✅ Logged in to CRM")

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
            print(f"   ❌ RPC Error: {result['error'].get('message','')[:100]}")
            return None
        return result.get('result')

    def get_tasks(self):
        return self.rpc('project.task', 'search_read',
            args=[[['project_id', '=', PROJECT_ID]]],
            kwargs={'fields': ['name', 'id'], 'limit': 500}
        ) or []

    def update_task(self, task_id, vals):
        return self.rpc('project.task', 'write', args=[[task_id], vals])


def job_to_html(job):
    """Convert job to rich HTML with FULL description."""
    parts = []

    link = job.get('link', '')
    if link:
        parts.append(f'<p><strong>🔗 Upwork Link:</strong> <a href="{link}" target="_blank">{link}</a></p>')

    # Info table
    rows = []
    budget = job.get('budget', '')
    if budget and budget != 'Not specified':
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>💰 Budget</strong></td><td>{budget}</td></tr>')
    exp = job.get('experience_level', '')
    if exp and exp != 'None':
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>📊 Experience Level</strong></td><td>{exp}</td></tr>')
    dur = job.get('duration', '')
    if dur and dur != 'None':
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>⏱️ Duration</strong></td><td>{dur}</td></tr>')
    wl = job.get('workload', '')
    if wl and wl != 'None':
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>🕐 Workload</strong></td><td>{wl}</td></tr>')
    prop = job.get('proposals', '')
    if prop and prop != 'None':
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>📝 Proposals</strong></td><td>{prop}</td></tr>')
    cat = job.get('category', '')
    if cat and cat != 'None':
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>📂 Category</strong></td><td>{cat}</td></tr>')
    hire = job.get('freelancers_to_hire', 1)
    if hire and hire > 1:
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>👥 Hiring</strong></td><td>{hire} people</td></tr>')
    pub = job.get('published_on', '')
    if pub and pub != 'None':
        rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>📅 Published</strong></td><td>{pub[:19].replace("T"," ")} UTC</td></tr>')

    if rows:
        parts.append('<table style="border-collapse:collapse; margin:8px 0;">')
        parts.extend(rows)
        parts.append('</table>')

    # Skills
    skills = job.get('skills', [])
    if skills:
        tags = ' '.join(
            f'<span style="background:#e8f0fe; color:#1a73e8; padding:3px 10px; '
            f'border-radius:14px; margin:2px; display:inline-block; font-size:13px;">{s}</span>'
            for s in skills if s
        )
        parts.append(f'<h3>🏷️ Skills Required</h3><p>{tags}</p>')

    # Full Description
    desc = job.get('description', '')
    if desc:
        # Convert markdown-like formatting to HTML
        desc_html = desc
        # Headers
        desc_html = re.sub(r'^### (.+)$', r'<h4>\1</h4>', desc_html, flags=re.MULTILINE)
        desc_html = re.sub(r'^## (.+)$', r'<h3>\1</h3>', desc_html, flags=re.MULTILINE)
        desc_html = re.sub(r'^# (.+)$', r'<h2>\1</h2>', desc_html, flags=re.MULTILINE)
        # Bold
        desc_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', desc_html)
        # Bullet points
        desc_html = re.sub(r'^\* (.+)$', r'<li>\1</li>', desc_html, flags=re.MULTILINE)
        desc_html = re.sub(r'^- (.+)$', r'<li>\1</li>', desc_html, flags=re.MULTILINE)
        desc_html = re.sub(r'^• (.+)$', r'<li>\1</li>', desc_html, flags=re.MULTILINE)
        # Wrap consecutive <li> in <ul>
        desc_html = re.sub(r'((?:<li>.*?</li>\n?)+)', r'<ul>\1</ul>', desc_html)
        # Paragraphs (double newline)
        desc_html = re.sub(r'\n\n+', '</p><p>', desc_html)
        # Single newlines
        desc_html = desc_html.replace('\n', '<br/>')
        desc_html = f'<p>{desc_html}</p>'
        
        parts.append(f'<h3>📄 Job Description & Requirements</h3>')
        parts.append(desc_html)

    # Client Info
    client_rows = []
    country = job.get('client_country', '')
    city = job.get('client_city', '')
    if country and country != 'None':
        loc = f"{city}, {country}" if city else country
        client_rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>📍 Location</strong></td><td>{loc}</td></tr>')
    spent = job.get('client_total_spent', '')
    if spent:
        client_rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>💵 Total Spent</strong></td><td>{spent}</td></tr>')
    hires = job.get('client_total_hires', 0)
    if hires:
        client_rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>👤 Total Hires</strong></td><td>{hires}</td></tr>')
    reviews = job.get('client_total_reviews', 0)
    if reviews:
        client_rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>📊 Reviews</strong></td><td>{reviews}</td></tr>')
    rating = job.get('client_rating', '')
    if rating and rating != 'None' and rating:
        client_rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>⭐ Rating</strong></td><td>{rating}/5</td></tr>')
    pv = job.get('client_payment_verified', '')
    if pv:
        client_rows.append(f'<tr><td style="padding:4px 12px 4px 0;"><strong>💳 Payment</strong></td><td>{pv}</td></tr>')

    if client_rows:
        parts.append('<h3>👤 Client Information</h3>')
        parts.append('<table style="border-collapse:collapse;">')
        parts.extend(client_rows)
        parts.append('</table>')

    return '\n'.join(parts)


def main():
    # Find latest jobs file
    files = sorted(glob(os.path.join(SCRIPT_DIR, 'upwork_jobs_*.json')))
    if not files:
        print("❌ No job files found")
        sys.exit(1)
    
    job_file = files[-1]
    print(f"📂 Loading: {os.path.basename(job_file)}")
    with open(job_file) as f:
        jobs = json.load(f)
    print(f"   {len(jobs)} jobs loaded")

    # Build lookup by title
    jobs_by_title = {j['title']: j for j in jobs}

    # Login to CRM
    client = OdooClient()
    client.login()

    # Get existing tasks
    tasks = client.get_tasks()
    print(f"📋 Found {len(tasks)} tasks in CRM project")

    updated = 0
    skipped = 0

    for task in tasks:
        title = task['name']
        task_id = task['id']

        if title in jobs_by_title:
            job = jobs_by_title[title]
            desc_html = job_to_html(job)

            print(f"  📝 Updating #{task_id}: {title[:60]}...")
            result = client.update_task(task_id, {'description': desc_html})
            if result:
                print(f"       ✅ Updated ({len(job.get('description',''))} chars desc, {len(job.get('skills',[]))} skills)")
                updated += 1
            else:
                print(f"       ❌ Failed")
            time.sleep(0.3)
        else:
            print(f"  ⏭️  Skip #{task_id}: {title[:60]} (no matching job)")
            skipped += 1

    print(f"\n{'='*60}")
    print(f"  ✅ Updated: {updated} | Skipped: {skipped}")
    print(f"  🔗 {CRM_URL}/odoo/project/{PROJECT_ID}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
