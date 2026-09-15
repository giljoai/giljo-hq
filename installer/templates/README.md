# Giljo HQ - Install Script Templates

Cross-platform installation scripts for token-efficient MCP downloads (Handover 0094).

## Overview

This directory contains 2 production-ready installation scripts that users can download and execute to install Giljo HQ components:

1. **Slash Commands Installers** - Install Claude Code slash commands to `~/.claude/commands/`

Agent templates are not installed as files: agents receive their profile from the server when a job starts.

## Scripts

### Slash Commands Installation

| Script | Platform | Lines | Description |
|--------|----------|-------|-------------|
| `install_slash_commands.sh` | Unix/Linux/macOS | 57 | Bash installer for slash commands |
| `install_slash_commands.ps1` | Windows | 64 | PowerShell installer for slash commands |

**Target Directory**: `$HOME/.claude/commands/` (all platforms)

**Usage**:
```bash
# Unix/Linux/macOS
bash install_slash_commands.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File install_slash_commands.ps1
```

## Features

All scripts implement the following production-grade features:

### Security & Authentication
- ✅ Requires `GILJO_API_KEY` environment variable
- ✅ Uses `X-API-Key` header for API authentication
- ✅ Validates API key before download
- ✅ Clear error messages if API key missing

### Cross-Platform Compatibility
- ✅ Uses `{{SERVER_URL}}` placeholder (rendered by backend)
- ✅ Platform-appropriate paths (`$HOME`, `$env:USERPROFILE`)
- ✅ No hardcoded absolute paths
- ✅ Works on Windows, macOS, Linux, WSL, Git Bash

### Error Handling
- ✅ Graceful failure with helpful error messages
- ✅ Network failure handling
- ✅ Download validation (HTTP status codes)
- ✅ Automatic cleanup on failure

### User Experience
- ✅ Colored output (green=success, red=error, yellow=steps)
- ✅ Progress feedback during installation
- ✅ List installed files after completion
- ✅ Clear instructions for next steps

### Data Safety
- ✅ Automatic temp directory cleanup
- ✅ Exit traps ensure cleanup on interruption

## Template Rendering

Backend renders scripts with actual server URL before download:

```bash
# Template (what's stored in Git):
SERVER_URL="{{SERVER_URL}}"

# Rendered (what user downloads):
SERVER_URL="http://192.0.2.10:7272"
```

## Environment Setup

Users must set `GILJO_API_KEY` environment variable:

### Unix/Linux/macOS
```bash
export GILJO_API_KEY="your-api-key-here"

# Persist in shell profile:
echo 'export GILJO_API_KEY="your-api-key-here"' >> ~/.bashrc
echo 'export GILJO_API_KEY="your-api-key-here"' >> ~/.zshrc
```

### Windows PowerShell
```powershell
# Current session only:
$env:GILJO_API_KEY = "your-api-key-here"

# Persistent (user scope):
[System.Environment]::SetEnvironmentVariable('GILJO_API_KEY', 'your-api-key-here', 'User')

# Persistent (system scope - requires admin):
[System.Environment]::SetEnvironmentVariable('GILJO_API_KEY', 'your-api-key-here', 'Machine')
```

## Syntax Validation

All scripts have been validated for syntax correctness:

### Bash Scripts
```bash
bash -n install_slash_commands.sh      # ✓ Syntax OK
```

### PowerShell Scripts
```powershell
# Both scripts parse correctly and execute as expected
# Tested with PowerShell 5.1+ and PowerShell Core 7+
```

## Testing Results

### Cross-Platform Testing
- ✓ Windows PowerShell 5.1 (tested)
- ✓ Git Bash on Windows (tested)
- ✓ Bash syntax validation (tested)
- ✓ PowerShell syntax validation (tested)

### Feature Verification
- ✓ `{{SERVER_URL}}` placeholder present in all scripts
- ✓ API key validation in all scripts
- ✓ Cleanup mechanisms (traps/finally blocks) in all scripts
- ✓ Colored output in all scripts
- ✓ Cross-platform path handling (no hardcoded paths)

### Error Handling Verification
- ✓ Missing API key → Clear error message with setup instructions
- ✓ Network failure → Graceful failure with manual download instructions
- ✓ Invalid download → Automatic cleanup and error reporting

## Integration with Backend

Backend endpoints must implement:

1. **Template Rendering**: Replace `{{SERVER_URL}}` with actual server URL
2. **Download Endpoints**:
   - `GET /api/download/slash-commands.zip` - Returns slash commands ZIP
3. **Authentication**: Slash commands + install scripts are public
4. **ZIP Archive Structure**:
   - Slash commands: Flat structure with `*.md` files

## File Locations

After successful installation:

### Slash Commands
```
$HOME/.claude/commands/
├── gil_get_agents.md
├── gil_activate.md
├── gil_launch.md
└── gil_handover.md
```
