#!/bin/bash
# Giljo HQ Service Stopper (Linux/macOS)

set -e

echo "==============================================="
echo "   Giljo HQ - Stopping Services"
echo "==============================================="
echo

# Get script directory and change to it
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Stopping all Giljo HQ services..."
echo

# Find and kill processes gracefully
pkill -f "python.*start_giljo" 2>/dev/null || true
pkill -f "python.*giljo_mcp" 2>/dev/null || true
pkill -f "uvicorn.*giljo" 2>/dev/null || true

# Wait a bit for graceful shutdown
sleep 2

# Force kill if still running
pkill -9 -f "python.*start_giljo" 2>/dev/null || true
pkill -9 -f "python.*giljo_mcp" 2>/dev/null || true

echo
echo "==============================================="
echo "   All Giljo HQ services stopped"
echo "==============================================="
echo
