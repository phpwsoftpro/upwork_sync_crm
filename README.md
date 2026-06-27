# Upwork → CRM Auto Sync

Automated pipeline that scrapes Upwork IT jobs and syncs them to Odoo CRM (crm.wsoftpro.com).

## Architecture

```
Upwork (HTTP Scrape) → auto_sync.py → Odoo CRM (JSON-RPC)
        ↑                                    ↑
   upwork_cookies.json              crm.wsoftpro.com
   (from login_cdp.py)             Project: "Bid Jobs Upwork"
```

## Files

| File | Purpose |
|------|---------|
| `auto_sync.py` | 🔄 Main automation — scrapes Upwork + syncs to CRM |
| `scrape_jobs.py` | 📡 Standalone Upwork scraper (NUXT parser) |
| `create_crm_tasks.py` | 📋 Bulk create tasks in CRM from JSON |
| `update_crm_tasks.py` | 🔄 Update existing CRM tasks with full data |
| `login_cdp.py` | 🔐 Upwork login via Chrome DevTools Protocol |
| `manage_sync.sh` | 🛠️ Service manager (start/stop/status/logs) |
| `com.wsoftpro.upwork-crm-sync.plist` | ⏱️ macOS launchd config (every 20 min) |
| `setup_and_run.sh` | 🚀 Initial setup script |
| `requirements.txt` | 📦 Python dependencies |

## Setup

```bash
# 1. Create venv + install deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Login to Upwork (saves cookies)
python3 login_cdp.py

# 3. Create .env with CRM credentials
cat > .env << EOF
CRM_EMAIL=trung@wsoftpro.com
CRM_PASSWORD=1
UPWORK_EMAIL=upworkwsoftpro6@gmail.com
UPWORK_PASSWORD=@Wsoftpro1
EOF

# 4. Install auto-sync service (every 20 min)
cp com.wsoftpro.upwork-crm-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wsoftpro.upwork-crm-sync.plist
```

## Usage

```bash
# Check service status
./manage_sync.sh status

# View logs
./manage_sync.sh logs

# Run sync manually
./manage_sync.sh run

# Stop/start service
./manage_sync.sh stop
./manage_sync.sh start
```

## Notes

- Upwork cookies expire periodically — re-run `login_cdp.py` when sync reports session expired
- Jobs are deduplicated by ciphertext ID (tracked in `synced_jobs.json`)
- CRM project: **Bid Jobs Upwork** (ID: 74), Stage: **Pending** (ID: 1889)
