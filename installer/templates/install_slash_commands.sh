#!/bin/bash
# GiljoAI Slash Command Installer
# Cross-platform installation script for slash commands

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "GiljoAI Slash Command Installer"
echo "================================"
echo ""

# Check for API key
if [ -z "$GILJO_API_KEY" ]; then
  echo -e "${RED}Error: GILJO_API_KEY environment variable not set${NC}"
  echo ""
  echo "Please configure Giljo HQ first:"
  echo "  Tools → Connect → MCP Configuration"
  echo ""
  echo "This will set up the required environment variable."
  exit 1
fi

# Server URL (templated by backend)
SERVER_URL="{{SERVER_URL}}"

# Download URL
DOWNLOAD_URL="${SERVER_URL}/api/download/slash-commands.zip"

# Create temp directory
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo -e "${YELLOW}Downloading slash commands...${NC}"
curl -H "X-API-Key: $GILJO_API_KEY" \
  "$DOWNLOAD_URL" \
  -o "$TEMP_DIR/commands.zip" \
  --fail --silent --show-error

# Target directory
TARGET_DIR="$HOME/.claude/commands"
mkdir -p "$TARGET_DIR"

echo -e "${YELLOW}Installing to $TARGET_DIR...${NC}"
unzip -o "$TEMP_DIR/commands.zip" -d "$TARGET_DIR" > /dev/null

echo ""
echo -e "${GREEN}✅ Installation complete!${NC}"
echo ""
echo "Installed commands:"
ls -1 "$TARGET_DIR"/gil_*.md | sed 's/.*\//  - /'
echo ""
echo "Restart your CLI tool to load the commands."
