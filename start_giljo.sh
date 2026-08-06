#!/usr/bin/env bash
# Giljo HQ Linux/macOS Launcher
# Updated to use unified startup.py

set -e

echo "==============================================="
echo "   Giljo HQ Launcher"
echo "==============================================="
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if venv exists
if [ -f "venv/bin/python" ]; then
    echo "Using virtual environment Python"
    venv/bin/python startup.py "$@"
else
    # Fallback to system Python
    if ! command -v python3 &> /dev/null; then
        echo "Error: Python 3 not found and venv not found"
        echo "Please install Python 3.12+ from python.org"
        exit 1
    fi
    echo "Warning: Using system Python (venv not found)"
    python3 startup.py "$@"
fi
