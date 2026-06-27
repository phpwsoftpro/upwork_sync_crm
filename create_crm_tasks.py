#!/usr/bin/env python3
"""
Create Upwork Jobs in Odoo CRM (crm.wsoftpro.com)
==================================================
Reads scraped Upwork jobs and creates them as tasks
in the "Bid Jobs Upwork" project.

Usage:
    python3 create_crm_tasks.py
    python3 create_crm_tasks.py --file upwork_jobs_20260627_112517.json
"""

import os
import sys
import re
import json
import time
import ssl
import argparse
import logging
import urllib.request
import urllib.parse
import http.cookiejar
from datetime import datetime
from glob import glob

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('crm_creator')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# CRM Config
CRM_URL = 'https://crm.wsoftpro.com'
CRM_EMAIL = 'trung@wsoftpro.com'
CRM_PASSWORD = os.environ.get('CRM_PASSWORD', '')
PROJECT_ID = 74  # "Bid Jobs Upwork"
STAGE_PENDING_ID = 1889  # "Pending"


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
        """Login to Odoo CRM."""
        log.info(f"🔐 Logging in to {CRM_URL}...")

        # Get CSRF token
        req = urllib.request.Request(f'{CRM_URL}/web/login', headers={'User-Agent': self.ua})
        resp = self.opener.open(req, timeout=15)
        html = resp.read().decode()

        csrf_match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        if not csrf_match:
            csrf_match = re.search(r'csrf_token:\s*"([^"]+)"', html)
        if not csrf_match:
            log.error("❌ Could not find CSRF token")
            sys.exit(1)

        csrf_token = csrf_match.group(1)

        # Submit login
        data = urllib.parse.urlencode({
            'login': CRM_EMAIL,
            'password': CRM_PASSWORD,
            'csrf_token': csrf_token,
            'redirect': '/odoo?',
        }).encode()

        req2 = urllib.request.Request(f'{CRM_URL}/web/login', data=data, headers={
            'User-Agent': self.ua,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': f'{CRM_URL}/web/login',
        })

        resp2 = self.opener.open(req2, timeout=15)
        if 'login' in resp2.url and 'redirect' in resp2.url:
            log.error("❌ Login failed!")
            sys.exit(1)

        log.info("✅ Logged in successfully!")

    def rpc_call(self, model, method, args=None, kwargs=None):
        """Make an Odoo JSON-RPC call."""
        self.rpc_id += 1

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": model,
                "method": method,
                "args": args or [],
                "kwargs": kwargs or {},
            },
            "id": self.rpc_id,
        }

        data = json.dumps(payload).encode()
        req = urllib.request.Request(f'{CRM_URL}/web/dataset/call_kw', data=data, headers={
            'User-Agent': self.ua,
            'Content-Type': 'application/json',
        })

        resp = self.opener.open(req, timeout=30)
        result = json.loads(resp.read().decode())

        if 'error' in result:
            err = result['error']
            log.error(f"   RPC Error: {err.get('message', '')}")
            log.error(f"   Detail: {err.get('data', {}).get('message', '')[:200]}")
            return None

        return result.get('result')

    def create_task(self, name, description_html, stage_id=STAGE_PENDING_ID):
        """Create a task in the Bid Jobs Upwork project."""
        vals = {
            'name': name,
            'project_id': PROJECT_ID,
            'stage_id': stage_id,
            'description': description_html,
            'priority': '0',
        }

        result = self.rpc_call(
            'project.task', 'create',
            args=[vals],
            kwargs={}
        )
        return result

    def get_existing_tasks(self):
        """Get existing task names to avoid duplicates."""
        result = self.rpc_call(
            'project.task', 'search_read',
            args=[[['project_id', '=', PROJECT_ID]]],
            kwargs={'fields': ['name'], 'limit': 500}
        )
        if result:
            return {t['name'] for t in result}
        return set()


def job_to_html(job):
    """Convert job data to rich HTML description for Odoo."""
    parts = []

    # Job Link
    link = job.get('link', '')
    if link:
        parts.append(f'<p><strong>🔗 Upwork Link:</strong> <a href="{link}" target="_blank">{link}</a></p>')

    # Budget & Level
    info_rows = []
    if job.get('budget') and job['budget'] != 'Not specified':
        info_rows.append(f'<tr><td><strong>💰 Budget</strong></td><td>{job["budget"]}</td></tr>')
    if job.get('experience_level') and job['experience_level'] != 'None':
        info_rows.append(f'<tr><td><strong>📊 Level</strong></td><td>{job["experience_level"]}</td></tr>')
    if job.get('duration') and job['duration'] != 'None':
        info_rows.append(f'<tr><td><strong>⏱️ Duration</strong></td><td>{job["duration"]}</td></tr>')
    if job.get('workload') and job['workload'] != 'None':
        info_rows.append(f'<tr><td><strong>🕐 Workload</strong></td><td>{job["workload"]}</td></tr>')
    if job.get('proposals') and job['proposals'] != 'None':
        info_rows.append(f'<tr><td><strong>📝 Proposals</strong></td><td>{job["proposals"]}</td></tr>')
    if job.get('category') and job['category'] != 'None':
        info_rows.append(f'<tr><td><strong>📂 Category</strong></td><td>{job["category"]}</td></tr>')
    if job.get('published_on') and job['published_on'] != 'None':
        pub = job['published_on'][:19].replace('T', ' ')
        info_rows.append(f'<tr><td><strong>📅 Published</strong></td><td>{pub} UTC</td></tr>')

    if info_rows:
        parts.append('<table style="border-collapse: collapse; margin: 10px 0;">')
        for row in info_rows:
            parts.append(row)
        parts.append('</table>')

    # Description
    desc = job.get('description', '')
    if desc:
        desc_html = desc.replace('\n', '<br/>')
        parts.append(f'<h3>📄 Job Description</h3>')
        parts.append(f'<p>{desc_html}</p>')

    # Skills
    skills = job.get('skills', [])
    if skills:
        skill_tags = ' '.join(f'<span style="background: #e8f0fe; color: #1a73e8; padding: 2px 8px; '
                              f'border-radius: 12px; margin: 2px; display: inline-block; font-size: 12px;">'
                              f'{s}</span>' for s in skills if s)
        parts.append(f'<h3>🏷️ Skills</h3><p>{skill_tags}</p>')

    # Client Info
    client_parts = []
    if job.get('client_country') and job['client_country'] != 'None':
        loc = job['client_country']
        if job.get('client_city'):
            loc = f"{job['client_city']}, {loc}"
        client_parts.append(f'<tr><td><strong>📍 Location</strong></td><td>{loc}</td></tr>')
    if job.get('client_total_spent'):
        client_parts.append(f'<tr><td><strong>💵 Total Spent</strong></td><td>{job["client_total_spent"]}</td></tr>')
    if job.get('client_total_hires'):
        client_parts.append(f'<tr><td><strong>👤 Total Hires</strong></td><td>{job["client_total_hires"]}</td></tr>')
    if job.get('client_rating') and job['client_rating'] != 'None' and job['client_rating']:
        client_parts.append(f'<tr><td><strong>⭐ Rating</strong></td><td>{job["client_rating"]}/5</td></tr>')
    if job.get('client_payment_verified'):
        client_parts.append(f'<tr><td><strong>💳 Payment</strong></td><td>{job["client_payment_verified"]}</td></tr>')

    if client_parts:
        parts.append('<h3>👤 Client Info</h3>')
        parts.append('<table style="border-collapse: collapse;">')
        for row in client_parts:
            parts.append(row)
        parts.append('</table>')

    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description='📋 Create Upwork jobs in Odoo CRM')
    parser.add_argument('--file', help='JSON file with job data')
    args = parser.parse_args()

    # Find the latest job file
    if args.file:
        job_file = args.file
    else:
        files = sorted(glob(os.path.join(SCRIPT_DIR, 'upwork_jobs_*.json')))
        if not files:
            log.error("❌ No upwork_jobs_*.json found! Run scrape_jobs.py first.")
            sys.exit(1)
        job_file = files[-1]

    log.info(f"📂 Loading jobs from: {os.path.basename(job_file)}")
    with open(job_file) as f:
        jobs = json.load(f)
    log.info(f"   Found {len(jobs)} jobs")

    # Login to CRM
    client = OdooClient()
    client.login()

    # Get existing tasks to avoid duplicates
    log.info("🔍 Checking existing tasks...")
    existing = client.get_existing_tasks()
    log.info(f"   Found {len(existing)} existing tasks")

    # Create tasks
    created = 0
    skipped = 0
    failed = 0

    print(f"\n{'=' * 80}")
    print(f"  📋 Creating {len(jobs)} jobs in CRM → 'Bid Jobs Upwork' project")
    print(f"{'=' * 80}\n")

    for i, job in enumerate(jobs, 1):
        title = job.get('title', 'Untitled')

        # Skip duplicates
        if title in existing:
            log.info(f"  ⏭️  #{i:02d} SKIP (exists): {title[:60]}")
            skipped += 1
            continue

        # Create HTML description
        desc_html = job_to_html(job)

        # Create task
        log.info(f"  📝 #{i:02d} Creating: {title[:60]}...")
        result = client.create_task(title, desc_html)

        if result:
            log.info(f"       ✅ Created (Task ID: {result})")
            created += 1
            existing.add(title)
        else:
            log.error(f"       ❌ Failed to create!")
            failed += 1

        # Small delay to not overwhelm the server
        time.sleep(0.5)

    print(f"\n{'=' * 80}")
    print(f"  ✅ DONE!")
    print(f"  📊 Created: {created} | Skipped (duplicates): {skipped} | Failed: {failed}")
    print(f"  🔗 View: {CRM_URL}/odoo/project/{PROJECT_ID}")
    print(f"{'=' * 80}\n")


if __name__ == '__main__':
    main()
