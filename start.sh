#!/bin/bash
# ArchiveVault Indexer — Linux / macOS startup

set -e
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "  =========================================="
echo "   ArchiveVault Indexer - Linux"
echo "  =========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check config
if [ ! -f "config.json" ]; then
    echo -e "${YELLOW}  [!] config.json not found.${NC}"
    echo "      Copy config.json.example to config.json"
    echo "      and fill in your server URL and token."
    echo ""
    exit 1
fi

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "  [!] Python 3 not found. Install with: sudo apt install python3 python3-venv"
    exit 1
fi

# Setup virtualenv if needed
if [ ! -d "venv" ]; then
    echo "  [*] Creating virtual environment..."
    python3 -m venv venv
    echo "  [*] Installing dependencies..."
    venv/bin/pip install -r requirements.txt -q
    echo -e "${GREEN}  [OK] Dependencies installed.${NC}"
fi

echo -e "${GREEN}  [*] Starting indexer on http://localhost:8989${NC}"
echo "  [*] Browser will open automatically..."
echo "  [*] Press Ctrl+C to stop"
echo ""

venv/bin/python server.py
