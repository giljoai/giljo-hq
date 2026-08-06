# GiljoAI Slash Command Installer (PowerShell)
# Cross-platform installation script for slash commands

$ErrorActionPreference = "Stop"

Write-Host "GiljoAI Slash Command Installer" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Check for API key
if (-not $env:GILJO_API_KEY) {
    Write-Host "Error: GILJO_API_KEY environment variable not set" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please configure Giljo HQ first:"
    Write-Host "  Tools → Connect → MCP Configuration"
    Write-Host ""
    Write-Host "This will set up the required environment variable."
    exit 1
}

# Server URL (templated by backend)
$SERVER_URL = "{{SERVER_URL}}"

# Download URL
$DOWNLOAD_URL = "$SERVER_URL/api/download/slash-commands.zip"

# Create temp directory
$TEMP_DIR = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null

try {
    Write-Host "Downloading slash commands..." -ForegroundColor Yellow

    # Download ZIP file
    $ZIP_PATH = Join-Path $TEMP_DIR "commands.zip"
    $headers = @{
        "X-API-Key" = $env:GILJO_API_KEY
    }

    Invoke-WebRequest -Uri $DOWNLOAD_URL -Headers $headers -OutFile $ZIP_PATH

    # Target directory
    $TARGET_DIR = Join-Path $env:USERPROFILE ".claude\commands"
    New-Item -ItemType Directory -Path $TARGET_DIR -Force | Out-Null

    Write-Host "Installing to $TARGET_DIR..." -ForegroundColor Yellow

    # Extract ZIP
    Expand-Archive -Path $ZIP_PATH -DestinationPath $TARGET_DIR -Force

    Write-Host ""
    Write-Host "✅ Installation complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Installed commands:"
    Get-ChildItem -Path $TARGET_DIR -Filter "gil_*.md" | ForEach-Object {
        Write-Host "  - $($_.Name)"
    }
    Write-Host ""
    Write-Host "Restart your CLI tool to load the commands."

} finally {
    # Clean up temp directory
    Remove-Item -Path $TEMP_DIR -Recurse -Force -ErrorAction SilentlyContinue
}
