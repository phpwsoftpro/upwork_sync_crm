#!/bin/bash
# ============================================
# Setup & Run - Upwork PyAutoGUI Login
# ============================================
# Run this script on the mac32 machine:
#   chmod +x setup_and_run.sh
#   ./setup_and_run.sh
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo " 🚀 Upwork PyAutoGUI Login - Setup"
echo "=================================================="

# Check Python3
if ! command -v python3 &> /dev/null; then
    echo "❌ python3 not found! Install it first."
    exit 1
fi

echo "✅ Python3: $(python3 --version)"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate
echo "✅ Virtual environment activated"

# Install dependencies
echo "📦 Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ Dependencies installed"

# Check .env
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  No .env file found! Creating from template..."
    cat > .env << 'EOF'
# Upwork Credentials
UPWORK_EMAIL='your_email@example.com'
UPWORK_PASSWORD='your_password'

# Google Credentials (for --google mode)
# GOOGLE_EMAIL='your_google@gmail.com'
# GOOGLE_PASSWORD='your_google_password'
EOF
    echo "📝 Please edit .env with your credentials before running!"
    echo "   nano .env"
    exit 0
fi

echo ""
echo "=================================================="
echo " 🏁 Starting Upwork Login..."
echo "=================================================="
echo ""

# Run the login script (pass all arguments through)
python3 login_upwork.py "$@"
